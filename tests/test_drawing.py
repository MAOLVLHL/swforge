"""SwDrawing against a fake sheet: the seam between a view request and COM."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from swforge.drawing import SwDrawing
from swforge.session import SwError

MODEL = r"C:\out\plate.sldprt"


class FakeView:
    def __init__(self, name: str = "Drawing View1", scale=(1.0, 2.0)):
        self.Name = name
        self._scale = scale
        self.ratio_calls = 0

    def ScaleRatio(self):  # the COM member is a method, not a property
        self.ratio_calls += 1
        return self._scale


class FakeSheet:
    def __init__(self, name: str = "Sheet1", views=()):
        self.GetName = name
        self._views = list(views)
        self.scale: tuple | None = None

    def SetScale(self, numerator, denominator, first, second, third):
        self.scale = (numerator, denominator, first, second, third)

    def GetViews(self):
        return tuple(self._views)


class FakeDrawingModel:
    def __init__(self, sheet=None, created=(), named=None):
        self.Extension = SimpleNamespace(
            SaveAs=self._save_as,
            ExportData=self._export_data,
        )
        self.sheet = sheet if sheet is not None else FakeSheet()
        self._created = list(created)
        self._named = named
        self.saved: list[str] = []
        self.exported: list[str] = []
        self.save_ok = True
        self.inserted = None

    def GetCurrentSheet(self):
        return self.sheet

    def Create3rdAngleViews2(self, path):
        self.created_path = path
        return list(self._created)

    def CreateDrawViewFromModelView3(self, path, name, x, y, z):
        self.named_args = (path, name, x, y, z)
        return self._named

    def InsertModelAnnotations3(self, *args):
        self.inserted = args
        return True

    def _save_as(self, path, *args):
        self.saved.append(path)
        return self.save_ok

    def _export_data(self, path, *args):
        self.exported.append(path)
        return True


def test_standard_views_keep_the_names_solidworks_assigned(tmp_path):
    model_path = tmp_path / "plate.sldprt"
    view = FakeView("Drawing View1")
    drawing = SwDrawing(FakeDrawingModel(created=[view]))
    assert drawing.add_standard_views(model_path) == ["Drawing View1"]


def test_standard_views_explain_that_the_model_must_be_open(tmp_path):
    drawing = SwDrawing(FakeDrawingModel(created=[]))
    with pytest.raises(SwError, match="has to be open in this session"):
        drawing.add_standard_views(tmp_path / "plate.sldprt")


def test_named_view_passes_metres_and_the_stored_orientation(tmp_path):
    model_path = tmp_path / "plate.sldprt"
    drawing = SwDrawing(FakeDrawingModel(named=FakeView("swforge_iso")))
    assert drawing.add_named_view(model_path, "swforge_iso", 120.0, 80.0) == "swforge_iso"
    _path, name, x, y, z = drawing.model.named_args
    assert name == "swforge_iso"
    assert (x, y, z) == pytest.approx((0.120, 0.080, 0.0)), "COM takes metres"


def test_named_view_says_the_orientation_has_to_exist(tmp_path):
    drawing = SwDrawing(FakeDrawingModel(named=None))
    with pytest.raises(SwError, match="carry an orientation saved under that exact name"):
        drawing.add_named_view(tmp_path / "plate.sldprt", "swforge_iso", 0.0, 0.0)


def test_views_and_view_scale_read_through_the_method_form():
    view = FakeView("Section A-A", scale=(1.0, 4.0))
    drawing = SwDrawing(FakeDrawingModel(sheet=FakeSheet(views=[view])))
    assert drawing.views() == ["Section A-A"]
    assert drawing.view_scale("Section A-A") == (1.0, 4.0)


def test_view_scale_names_the_view_it_could_not_find():
    drawing = SwDrawing(FakeDrawingModel(sheet=FakeSheet(views=[FakeView("Front")])))
    with pytest.raises(SwError, match="no view named 'Back'"):
        drawing.view_scale("Back")


def test_set_scale_sets_the_first_flag_only():
    drawing = SwDrawing(FakeDrawingModel())
    drawing.set_scale(1.0, 2.0)
    assert drawing.sheet.scale == (1.0, 2.0, True, False, False)


def test_save_blames_a_locked_file_only_when_the_file_exists(tmp_path, fake_com):
    drawing = SwDrawing(FakeDrawingModel())
    drawing.model.save_ok = False
    existing = tmp_path / "plate.SLDDRW"
    existing.write_bytes(b"old")
    with pytest.raises(SwError, match="locked by an open document"):
        drawing.save(existing)
    with pytest.raises(SwError, match="save failed:"):
        drawing.save(tmp_path / "new.SLDDRW")


def test_annotations_ask_for_dimensions_and_notes():
    drawing = SwDrawing(FakeDrawingModel())
    drawing.annotations()
    assert drawing.model.inserted == (0, 1, True, True, False, False)


def test_a_drawing_without_a_sheet_says_so():
    model = FakeDrawingModel()
    model.sheet = None
    model.GetCurrentSheet = lambda: None
    with pytest.raises(SwError, match="no current sheet"):
        SwDrawing(model).sheet
