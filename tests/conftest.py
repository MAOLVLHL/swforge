"""Stand-ins for the slice of the SolidWorks COM API the session module uses.

SwModel needs no licence to be useful in a test: __init__ only reads
.Extension, .SketchManager and .FeatureManager, and close() only reads
.GetTitle and .GetPathName before calling into the application.  Handing it
these three members by hand is enough to observe what the wrapper actually
asks SolidWorks to do, on a machine where SolidWorks is not installed.
"""

from types import SimpleNamespace
from typing import Any

import pytest

TITLE = "multi_hole_plate_120x80x6.SLDPRT"
PATH = r"C:\out\a\multi_hole_plate_120x80x6.sldprt"


class FakeApp:
    """The application object, remembering what it was asked to close.

    Every close path in the wrapper ends in CloseDoc, so the recorded argument
    is the observable difference between closing by path and closing by title.
    """

    def __init__(self) -> None:
        self.closed: list[str] = []

    def CloseDoc(self, what: str) -> None:
        self.closed.append(what)

    def GetDocuments(self) -> tuple[Any, ...]:
        return ()


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
