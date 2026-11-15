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
    with pytest.raises(session.SwError) as raised:
        SwModel(doc_factory(Extension=ext), fake_app).save(target)
    assert target.read_bytes() == b"last good save", (
        "a save that fails twice must leave the file the user already had; "
        "unlinking before the retry destroys the only copy when it fails too"
    )
    assert "previous save kept at" not in str(raised.value), (
        "the backup moved back onto the target, so pointing at the .bak would "
        f"send the user to a path that no longer exists. Got {raised.value!r}"
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

class _Blocked:
    """SaveAs that fails twice and leaves a directory where the file goes.

    The second attempt is the one that matters: after the previous file has
    been moved aside, a save that fails *again* has to put it back, and this
    fake makes that move impossible so the "previous save kept at" branch is
    reachable without an antivirus or a second SolidWorks process.
    """

    def __init__(self, target: Path) -> None:
        self.target = target
        self.calls = 0

    def SaveAs(self, path: str, *args: object) -> bool:
        self.calls += 1
        if self.calls == 2:
            self.target.mkdir()
        return False


def test_a_save_that_cannot_move_the_old_file_aside_still_raises_sw_error(
    fake_app, doc_factory, tmp_path, fake_com
):
    target = tmp_path / "plate.sldprt"
    target.write_bytes(b"last good save")
    (tmp_path / "plate.sldprt.bak").mkdir()
    with pytest.raises(session.SwError) as raised:
        SwModel(doc_factory(Extension=_Extension([False, False])), fake_app).save(
            target
        )
    assert str(target) in str(raised.value) and "(errors=" in str(raised.value), (
        "when the backup cannot be moved the retry still fails, and the caller "
        "has to hear it as a save failure naming the target and the counters; "
        f"it heard {raised.value!r} instead"
    )
    assert target.read_bytes() == b"last good save", (
        "the move failing means the original never left, so the user's file "
        "has to be exactly as it was"
    )


def test_a_failed_retry_names_the_backup_it_kept(
    fake_app, doc_factory, tmp_path, fake_com
):
    target = tmp_path / "plate.sldprt"
    target.write_bytes(b"last good save")
    with pytest.raises(session.SwError) as raised:
        SwModel(doc_factory(Extension=_Blocked(target)), fake_app).save(target)
    backup = tmp_path / "plate.sldprt.bak"
    assert f"previous save kept at {backup}" in str(raised.value), (
        "the file was moved aside and could not be moved back, so the only "
        "copy left is the .bak; the message has to say where it is or the user "
        f"searches for a part that looks deleted. Got {raised.value!r}"
    )
    assert backup.read_bytes() == b"last good save", (
        "the kept copy is the whole point of the hint"
    )


def test_close_document_answers_false_without_an_application(tmp_path):
    assert session.close_document(None, tmp_path / "plate.sldprt") is False, (
        "the handle can already be dead when the save fails, and asking a None "
        "application for its documents would turn a failing save into a "
        "TypeError"
    )


def test_close_document_closes_only_the_file_it_was_asked_about(
    fake_app, doc_factory, tmp_path
):
    target = tmp_path / "plate.sldprt"
    fake_app.docs = [
        doc_factory(path=""),
        doc_factory(path=str(tmp_path / "other.sldprt")),
        doc_factory(path=str(target)),
    ]
    assert session.close_document(fake_app, target) is True, (
        "a document that was saved to the target is exactly what the retry "
        "needs closed"
    )
    assert fake_app.closed == [str(target.resolve())], (
        "the user's own documents and the untitled ones have to be left alone; "
        f"closed {fake_app.closed!r}"
    )


def test_close_document_reports_a_close_that_raised(fake_app, doc_factory, tmp_path):
    target = tmp_path / "plate.sldprt"
    fake_app.docs = [doc_factory(path=str(target))]

    def refuse(what: str) -> None:
        raise RuntimeError("CloseDoc refused")

    fake_app.CloseDoc = refuse
    assert session.close_document(fake_app, target) is False, (
        "CloseDoc failing is not the save's problem to crash on: the retry "
        "still runs, and a False here keeps the reason in the save error"
    )


def test_the_rollback_helpers_keep_quiet_when_the_file_system_refuses(tmp_path):
    backup = tmp_path / "plate.sldprt.bak"
    backup.mkdir()
    session._discard(backup)
    session._discard(None)
    assert backup.is_dir(), (
        "a backup that cannot be unlinked is left alone: the save already "
        "succeeded, and raising here would report success as a failure"
    )
    target = tmp_path / "plate.sldprt"
    target.write_bytes(b"last good save")
    session._restore(None, target)
    session._restore(tmp_path / "gone.bak", target)
    assert target.read_bytes() == b"last good save", (
        "restoring without a backup, or with one that has already moved, must "
        "not touch the file that is there"
    )
