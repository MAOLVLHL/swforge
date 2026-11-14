"""The document lifecycle every build ends in.

Nothing here needs SolidWorks.  SwModel only reads .Extension, .SketchManager
and .FeatureManager when it is constructed, and .GetTitle / .GetPathName when
it is closed, so the fake COM fixtures are enough to assert what the wrapper
asks the application to do.  That is where the defect lived: one class carried
two close methods and Python kept the second one, which closed by title and
skipped the pause.
"""

import ast
from pathlib import Path

import pytest

from swforge import session
from swforge.session import SwModel

SOURCE = Path(session.__file__)


def test_close_passes_the_full_path_not_the_title(fake_app, fake_doc):
    SwModel(fake_doc, fake_app).close()
    assert fake_app.closed == [fake_doc.GetPathName], (
        "CloseDoc must receive the full path: two parts built into different "
        "output directories share a title, and an ambiguous title closes "
        f"nothing at all. Got {fake_app.closed!r}."
    )


def test_close_marks_the_handle_closed(fake_app, fake_doc):
    model = SwModel(fake_doc, fake_app)
    assert model.closed is False, (
        "closed is a class attribute; a stale True from another handle would "
        "make this assertion meaningless"
    )
    model.close()
    assert model.closed is True


def test_close_paces_successive_closes(fake_app, fake_doc, monkeypatch):
    slept: list[float] = []
    # session.time is the time module, so this is the same object time.sleep
    # lives on; monkeypatch puts it back afterwards, and no test actually waits.
    monkeypatch.setattr(session.time, "sleep", slept.append)
    SwModel(fake_doc, fake_app).close()
    assert slept == [0.25], (
        "closing a batch of documents back-to-back crashed this SolidWorks "
        f"build; the gap between closes is the mitigation. Slept {slept!r}."
    )


def test_close_falls_back_to_the_title_when_unsaved(fake_app, doc_factory):
    doc = doc_factory(path="")
    SwModel(doc, fake_app).close()
    assert fake_app.closed == [doc.GetTitle], (
        "a document that was never saved has no path to close by, so the "
        "title is the only handle; dropping the fallback would silently stop "
        "closing brand-new documents"
    )


def test_close_uses_the_document_handle_without_an_application(doc_factory):
    closed: list[bool] = []
    doc = doc_factory(Close=lambda: closed.append(True))
    SwModel(doc, None).close()
    assert closed == [True]


def test_close_leaves_an_untitled_document_alone(fake_app, doc_factory):
    SwModel(doc_factory(title=""), fake_app).close()
    assert fake_app.closed == []


def test_close_survives_a_handle_that_refuses_selection(fake_app, doc_factory):
    def dead(*args):
        raise RuntimeError("-2147221013 document not found")

    doc = doc_factory(ClearSelection2=dead)
    SwModel(doc, fake_app).close()
    assert fake_app.closed == [doc.GetPathName], (
        "close runs from finally blocks at seven call sites, so it must never "
        "raise: an exception here would hide the error that got us there"
    )


def test_each_method_is_defined_once():
    """Python keeps the last definition and reports nothing; catch it here.

    SwModel carried two close methods.  The second one won, so the docstring,
    the full-path CloseDoc, the closed flag and the pause all became dead
    code without a single warning.  Re-declaring a method in a class body is
    always a mistake, so the rule can be checked mechanically.
    """
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    duplicates = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        seen: dict[str, int] = {}
        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if item.name in seen:
                duplicates.append(
                    f"{node.name}.{item.name} defined at line "
                    f"{seen[item.name]} and {item.lineno}"
                )
            seen[item.name] = item.lineno
    assert not duplicates, f"{SOURCE.name}: " + "; ".join(duplicates)


class _Extension:
    """Extension.SaveAs with scripted results, writing bytes when it succeeds."""

    def __init__(self, results: list[bool], payload: bytes = b"fresh") -> None:
        self.results = list(results)
        self.payload = payload
        self.calls: list[str] = []

    def SaveAs(self, path: str, *args: object) -> bool:
        self.calls.append(str(path))
        ok = self.results.pop(0) if self.results else False
        if ok:
            Path(path).write_bytes(self.payload)
        return ok


def test_save_keeps_the_previous_file_when_the_retry_fails(
    fake_app, doc_factory, tmp_path, fake_com
):
    target = tmp_path / "plate.sldprt"
    target.write_bytes(b"last good save")
    ext = _Extension([False, False])
    with pytest.raises(session.SwError):
        SwModel(doc_factory(Extension=ext), fake_app).save(target)
    assert target.read_bytes() == b"last good save", (
        "a save that fails twice must leave the file the user already had; "
        "unlinking before the retry destroys the only copy when it fails too"
    )
    assert not (tmp_path / "plate.sldprt.bak").exists(), (
        "after the restore the backup has moved back, so no stray copy may "
        "be left next to the part"
    )


def test_close_twice_closes_the_document_once(fake_app, doc_factory):
    model = SwModel(doc_factory(), fake_app)
    model.close()
    model.close()
    assert len(fake_app.closed) == 1, (
        "the second CloseDoc would name a title SolidWorks no longer knows and "
        "pay the 0.25 s pause again; closed has to be read somewhere"
    )


def test_save_on_a_closed_document_names_the_reason(fake_app, doc_factory, tmp_path):
    model = SwModel(doc_factory(), fake_app)
    model.close()
    with pytest.raises(session.SwError, match="already closed"):
        model.save(tmp_path / "plate.sldprt")


def test_session_ledger_closes_only_what_it_opened(fake_app, tmp_path, fake_com):
    sess = session.SwSession(fake_app)
    target = tmp_path / "plate.sldprt"
    sess.open_document(target, 1)
    assert sess.opened == (Path(str(target)).resolve(),), (
        "open_document is the only place the ledger can learn about a document"
    )
    assert sess.close_opened() == 1
    assert fake_app.closed == [str(Path(str(target)).resolve())]
    assert sess.opened == (), "a settled ledger starts empty for the next run"
    assert sess.close_opened() == 0, "closing twice must not touch CloseDoc again"


class _Recording:
    """Extension.SaveAs that records the exact string it was handed."""

    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.calls: list[str] = []

    def SaveAs(self, path: str, *args: object) -> bool:
        self.calls.append(str(path))
        return self.ok


def test_save_resolves_a_relative_target_before_reaching_com(
    fake_app, doc_factory, tmp_path, fake_com, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    ext = _Recording()
    model = SwModel(doc_factory(Extension=ext), fake_app)
    returned = model.save("build/plate.sldprt")
    assert ext.calls == [str(tmp_path / "build" / "plate.sldprt")], (
        "Extension.SaveAs does not resolve: it is handed straight to "
        "SolidWorks, which expands a relative path against its own working "
        "directory -- the folder it was started from. 'swforge build "
        "showcase.json -o build' therefore wrote into an unrelated directory "
        "and failed with swFileSaveError 1. Got "
        f"{ext.calls!r}."
    )
    assert returned == Path(str(tmp_path / "build" / "plate.sldprt")), (
        "save() must return the path it actually wrote, or a caller joins a "
        "relative name onto the wrong base"
    )


def test_export_step_resolves_a_relative_target(
    fake_app, doc_factory, tmp_path, fake_com, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    ext = _Recording()
    SwModel(doc_factory(Extension=ext), fake_app).export_step("build/plate.step")
    assert ext.calls == [str(tmp_path / "build" / "plate.step")], (
        "the STEP export has the same COM path rule as save(); a relative "
        f"target lands under SolidWorks' cwd. Got {ext.calls!r}."
    )


def test_save_drops_the_backup_when_the_retry_succeeds(
    fake_app, doc_factory, tmp_path, fake_com
):
    target = tmp_path / "plate.sldprt"
    target.write_bytes(b"old")
    ext = _Extension([False, True])
    SwModel(doc_factory(Extension=ext), fake_app).save(target)
    assert target.read_bytes() == b"fresh", (
        "closing the stale document and retrying is what the branch is for; "
        "the retry has to win"
    )
    assert ext.calls == [str(target), str(target)], (
        "SaveAs must be retried on the same path, once"
    )
    assert not (tmp_path / "plate.sldprt.bak").exists(), (
        "the backup must not outlive a successful save"
    )
