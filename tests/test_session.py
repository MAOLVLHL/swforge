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
