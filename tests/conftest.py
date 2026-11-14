"""Stand-ins for the slice of the SolidWorks COM API the session module uses.

SwModel needs no licence to be useful in a test: __init__ only reads
.Extension, .SketchManager and .FeatureManager, and close() only reads
.GetTitle and .GetPathName before calling into the application.  Handing it
these three members by hand is enough to observe what the wrapper actually
asks SolidWorks to do, on a machine where SolidWorks is not installed.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import fakecom

TITLE = "multi_hole_plate_120x80x6.SLDPRT"
PATH = r"C:\out\a\multi_hole_plate_120x80x6.sldprt"


class FakeApp:
    """The application object, remembering what it opened and closed.

    Every close path in the wrapper ends in CloseDoc, so the recorded argument
    is the observable difference between closing by path and closing by title.
    GetDocuments is kept honest: closing a document removes it, exactly as
    SolidWorks does, so a ledger that closes the same file twice shows up.
    """

    def __init__(self) -> None:
        self.closed: list[str] = []
        self.opened: list[str] = []
        self.docs: list[Any] = []

    def CloseDoc(self, what: str) -> None:
        self.closed.append(what)
        self.docs = [
            doc
            for doc in self.docs
            if str(doc.GetPathName) != what and str(doc.GetTitle) != what
        ]

    def GetDocuments(self) -> tuple[Any, ...]:
        return tuple(self.docs)

    def OpenDoc6(self, path, doctype, options, arg, errors, warnings):
        self.opened.append(str(path))
        doc = make_doc(title=Path(str(path)).name, path=str(path))
        self.docs.append(doc)
        return doc


def make_doc(title: str = TITLE, path: str = PATH, **overrides: Any):
    """A document stand-in; *overrides* replace the members close() reads."""
    doc = SimpleNamespace(
        GetTitle=title,
        GetPathName=path,
        ClearSelection2=lambda *args: True,
        Close=lambda: None,
        Extension=None,
        SketchManager=None,
        FeatureManager=None,
    )
    for name, value in overrides.items():
        setattr(doc, name, value)
    return doc


@pytest.fixture
def fake_app() -> FakeApp:
    """The application object, remembering what it was asked to close."""
    return FakeApp()


@pytest.fixture
def fake_doc():
    """One saved part whose title and full path are deliberately different."""
    return make_doc()


@pytest.fixture
def doc_factory():
    """Build documents with one member swapped out, e.g. an unsaved one."""
    return make_doc


@pytest.fixture
def fake_com(monkeypatch):
    """pywin32's import surface, so save() runs where it is not installed.

    The wrapper imports pythoncom lazily inside the functions that build a
    VARIANT, so shadowing the modules covers exactly the same code a Windows
    host would run.  Without this the save paths are unreachable on the Linux
    runners and the retry logic is never exercised there.
    """
    fakecom.install(monkeypatch)
