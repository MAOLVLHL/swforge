"""The pass/fail rule of a build, without SolidWorks anywhere near it."""

from types import SimpleNamespace

import pytest

from swforge.generate import (
    BBOX_SLACK_MM,
    AssemblyResult,
    BuildResult,
    _bbox_errors,
    build_assembly,
)
from swforge.session import SwError


def make_spec(tolerance=0.01, kind="washer", name="washer_M8"):
    return SimpleNamespace(tolerance=tolerance, kind=kind, name=name)


def make_result(**overrides):
    base = dict(
        spec=make_spec(),
        expected=SimpleNamespace(volume_mm3=1000.0),
        measured_volume_mm3=1000.0,
        measured_bbox_mm=(20.0, 20.0, 2.0),
        volume_error=0.0,
        bbox_errors={"x": 0.0, "y": 0.0, "z": 0.0},
        files={},
        notes=[],
    )
    base.update(overrides)
    return BuildResult(**base)


def test_a_body_without_a_measurement_is_an_error_on_every_axis():
    errors = _bbox_errors((20.0, 20.0, 2.0), None)
    assert errors == {"x": float("inf"), "y": float("inf"), "z": float("inf")}, (
        "a part that produced no body must fail, not slip through as zero error"
    )


def test_the_slack_is_forgiven_but_nothing_beyond_it():
    assert BBOX_SLACK_MM == 0.05
    errors = _bbox_errors((20.0, 20.0, 2.0), (20.04, 20.06, 2.0))
    assert errors["x"] == 0.0, "4 hundredths of a millimetre is tessellation noise"
    assert errors["y"] == pytest.approx(0.01), (
        "the slack is subtracted once, not compounded: 20.06 - 20 - 0.05"
    )
    assert errors["z"] == 0.0


def test_a_volume_inside_tolerance_passes_and_reports_numbers():
    result = make_result(volume_error=0.009)
    assert result.ok
    summary = result.summary()
    assert summary.startswith("[PASS] washer/washer_M8: volume 1000.0 mm3")
    assert "err 0.900%" in summary


def test_a_volume_outside_tolerance_fails():
    assert not make_result(volume_error=0.02).ok
    assert make_result(volume_error=0.02).summary().startswith("[FAIL]")


def test_a_bbox_error_fails_even_when_the_volume_matches():
    result = make_result(bbox_errors={"x": 0.0, "y": 1e-6 + 1e-9, "z": 0.0})
    assert not result.ok, (
        "a bolt with the right volume in the wrong place is still wrong"
    )


def test_a_failed_build_says_so_when_there_is_no_body():
    result = make_result(
        measured_bbox_mm=None,
        bbox_errors={"x": float("inf"), "y": float("inf"), "z": float("inf")},
    )
    assert not result.ok
    assert result.summary().endswith("bbox no body"), (
        "a blank bbox field reads like a formatting bug, not like a missing body"
    )


def test_an_assembly_summary_counts_its_mates():
    result = AssemblyResult(
        spec=make_spec(kind="l_bracket", name="bracket"),
        expected=SimpleNamespace(volume_mm3=500.0),
        measured_volume_mm3=500.0,
        measured_bbox_mm=(10.0, 10.0, 10.0),
        volume_error=0.0,
        bbox_errors={"x": 0.0, "y": 0.0, "z": 0.0},
        files={},
        notes=[],
        mates=["base", "upright"],
    )
    assert result.ok
    summary = result.summary()
    assert summary.startswith("[PASS] assembly/bracket:")
    assert summary.endswith("2 mates")

class FakeAssembly:
    """Just enough of an assembly to watch what build_assembly does with it."""

    def __init__(self):
        self.inserted: list[str] = []
        self.mates: list[str] = []
        self.closed = False
        self.saved = None

    def add_component(self, path, x, y, z, instance=None):
        self.inserted.append(instance)
        return SimpleNamespace(name=instance)

    def find(self, name):
        if name in self.inserted:
            return SimpleNamespace(name=name)
        raise SwError(f"no component named {name!r}")

    def mate_planes(self, first, second, **kwargs):
        label = f"{first.name}-{second.name}"
        self.mates.append(label)
        return label

    def measure(self):
        return 1000.0, 1000.0

    def save(self, path):
        self.saved = str(path)
        return path

    def export_step(self, path):
        return path

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self):
        self.assembly = None

    def new_assembly(self):
        self.assembly = FakeAssembly()
        return self.assembly


def make_assembly_spec():
    parts = {
        "plate": SimpleNamespace(kind="plate"),
        "bolt": SimpleNamespace(kind="hex_bolt"),
    }
    placements = [
        SimpleNamespace(part="plate", instance="plate-1", x_mm=0.0, y_mm=0.0, z_mm=0.0),
        SimpleNamespace(part="bolt", instance="bolt-1", x_mm=10.0, y_mm=0.0, z_mm=10.0),
    ]
    mates = [
        SimpleNamespace(
            first="plate-1",
            second="bolt-1",
            plane="top",
            kind="coincident",
            distance_mm=0.0,
            flip=False,
        ),
        # Nothing ever places this component, so the mate can only fail.
        SimpleNamespace(
            first="plate-1",
            second="post-1",
            plane="top",
            kind="coincident",
            distance_mm=0.0,
            flip=False,
        ),
    ]
    predict = lambda: SimpleNamespace(volume_mm3=1000.0, bbox_mm=(20.0, 20.0, 2.0))  # noqa: E731
    return SimpleNamespace(
        name="bracket",
        tolerance=0.01,
        parts=parts,
        placements=placements,
        mates=mates,
        predict=predict,
        validate=lambda: None,
    )


def test_one_failed_part_does_not_take_the_assembly_with_it(monkeypatch):
    def fake_generate(session, part_spec, **kwargs):
        if part_spec.kind == "hex_bolt":
            raise SwError("FeatureCut4 returned Nothing")
        return SimpleNamespace(files={"part": r"C:\out\plate.sldprt"})

    monkeypatch.setattr("swforge.generate.generate", fake_generate)
    monkeypatch.setattr("swforge.generate._assembly_bbox", lambda assembly: (20.0, 20.0, 2.0))

    session = FakeSession()
    result = build_assembly(session, make_assembly_spec())

    assert result.failures == {"bolt": "SwError: FeatureCut4 returned Nothing"}
    assert session.assembly.inserted == ["plate-1"], (
        "the survivor is still inserted; only the failed part is skipped"
    )
    assert session.assembly.mates == [], (
        "both mates name the component that is missing, so neither can be made -- "
        "and neither is allowed to stop the run"
    )
    joined = " | ".join(result.notes)
    assert "mate 'plate-1'-'bolt-1' skipped" in joined
    assert "part 'bolt' failed: SwError: FeatureCut4 returned Nothing" in joined
    assert "instance 'bolt-1' skipped: part 'bolt' failed to build" in joined
    assert "mate 'plate-1'-'post-1' skipped" in joined
    assert not result.ok
    assert result.summary().endswith("0 mates, 1 failed")
    assert "assembly" in result.files, "the assembly still gets written from what survived"
    assert session.assembly.closed


def test_a_batch_that_loses_every_part_never_asks_for_an_assembly(monkeypatch):
    def fake_generate(session, part_spec, **kwargs):
        raise SwError("no part template")

    monkeypatch.setattr("swforge.generate.generate", fake_generate)

    class ExplodingSession:
        def new_assembly(self):
            raise AssertionError("an assembly of nothing is not worth opening")

    result = build_assembly(ExplodingSession(), make_assembly_spec())

    assert result.failures == {
        "plate": "SwError: no part template",
        "bolt": "SwError: no part template",
    }
    assert result.files == {}
    assert result.measured_volume_mm3 == 0.0
    assert result.measured_bbox_mm is None
    assert result.volume_error == float("inf")
    assert result.notes[-1] == "no part was built, so no assembly was created"
    assert not result.ok


def test_an_assembly_whose_parts_all_build_still_passes(monkeypatch):
    def fake_generate(session, part_spec, **kwargs):
        return SimpleNamespace(files={"part": rf"C:\out\{part_spec.kind}.sldprt"})

    monkeypatch.setattr("swforge.generate.generate", fake_generate)
    monkeypatch.setattr("swforge.generate._assembly_bbox", lambda assembly: (20.0, 20.0, 2.0))

    session = FakeSession()
    result = build_assembly(session, make_assembly_spec())

    assert result.failures == {}
    assert result.ok
    assert session.assembly.inserted == ["plate-1", "bolt-1"]
    assert session.assembly.mates == ["plate-1-bolt-1"]
    assert "mate 'plate-1'-'post-1' skipped" in " | ".join(result.notes), (
        "a mate naming a component that was never placed is reported, not raised"
    )


def test_the_assembly_reports_every_phase_it_enters(monkeypatch):
    """A ten-part assembly is silent for minutes if only parts are reported."""

    def fake_generate(session, part_spec, **kwargs):
        return SimpleNamespace(files={"part": rf"C:\out\{part_spec.kind}.sldprt"})

    monkeypatch.setattr("swforge.generate.generate", fake_generate)
    monkeypatch.setattr("swforge.generate._assembly_bbox", lambda assembly: (20.0, 20.0, 2.0))

    seen = []
    result = build_assembly(
        FakeSession(), make_assembly_spec(), on_progress=lambda s, p: seen.append((s, p))
    )

    assert result.ok
    assert [stage for stage, _ in seen] == [
        "assembly.parts",
        "assembly.inserting",
        "assembly.mating",
        "assembly.saving",
        "assembly.closed",
    ], "the phases are reported in the order they run, and closing comes last"
    assert seen[0][1] == {"built": 2, "failed": 0}
    assert seen[1][1] == {"components": 2}
    assert seen[2][1] == {"mates": 2}, (
        "two mates were declared; one of them is skipped later, and the event "
        "reports what was attempted so that the wait is explainable"
    )
    assert seen[4][1] == {"name": "bracket", "files": 2}, (
        "the .sldasm and its STEP are both on disk by the time the assembly closes"
    )


def test_progress_is_optional_and_absent_by_default(monkeypatch):
    def fake_generate(session, part_spec, **kwargs):
        return SimpleNamespace(files={"part": rf"C:\out\{part_spec.kind}.sldprt"})

    monkeypatch.setattr("swforge.generate.generate", fake_generate)
    monkeypatch.setattr("swforge.generate._assembly_bbox", lambda assembly: (20.0, 20.0, 2.0))

    result = build_assembly(FakeSession(), make_assembly_spec())
    assert result.ok, "a caller that never asked to watch still gets the build"

def _disk_part(tmp_path, kind="washer", name="washer_M8"):
    stem = tmp_path / f"{kind}_{name}"
    part = stem.with_suffix(".sldprt")
    part.write_bytes(b"stand-in for a saved document")
    return part


class FakePartModel:
    """The three calls reuse_part makes on an opened document."""

    def __init__(self, volume_mm3=1000.0, box=(20.0, 20.0, 2.0)):
        self.volume_mm3 = volume_mm3
        self.box = box
        self.closed = False

    def measure(self):
        return SimpleNamespace(volume_mm3=self.volume_mm3)

    def bbox_mm(self):
        return self.box

    def close(self):
        self.closed = True


def test_a_part_already_on_disk_is_measured_and_reported_as_reused(
    tmp_path, monkeypatch
):
    """The whole point of --resume: read the file, re-derive the verdict, say so."""
    from swforge import generate

    spec = SimpleNamespace(tolerance=0.01, kind="washer", name="washer_M8", params={})
    part = _disk_part(tmp_path)
    (tmp_path / "washer_washer_M8.step").write_bytes(b"step")

    monkeypatch.setattr(
        generate.parts,
        "analytic",
        lambda kind, params: SimpleNamespace(volume_mm3=1000.0, bbox_mm=(20.0, 20.0, 2.0)),
    )

    model = FakePartModel()

    class Session:
        def open_part(self, path):
            assert path == part, "resume_part opens the file it just found"
            return model

    events = []
    result = generate.reuse_part(
        Session(), spec, out_dir=str(tmp_path), on_progress=lambda s, p: events.append((s, p))
    )

    assert result is not None
    assert model.closed, "the document is closed even when the measurement disagrees"
    assert result.ok
    assert result.volume_error == 0.0
    assert result.files["part"] == str(part)
    assert result.files["step"] == str(tmp_path / "washer_washer_M8.step")
    assert result.notes == ["verified from disk, not rebuilt"]
    assert events == [
        (
            "part.reused",
            {"kind": "washer", "name": "washer_M8", "volume_mm3": 1000.0, "ok": True},
        )
    ], "a resumed part must announce itself instead of going quiet"


def test_a_hand_edited_part_still_has_to_survive_the_check(tmp_path, monkeypatch):
    """Resume re-measures; it never trusts the numbers from the earlier run."""
    from swforge import generate

    spec = SimpleNamespace(tolerance=0.01, kind="washer", name="washer_M8", params={})
    _disk_part(tmp_path)
    monkeypatch.setattr(
        generate.parts,
        "analytic",
        lambda kind, params: SimpleNamespace(volume_mm3=1000.0, bbox_mm=(20.0, 20.0, 2.0)),
    )

    events = []

    class Session:
        def open_part(self, path):
            return FakePartModel(volume_mm3=1500.0)

    result = generate.reuse_part(
        Session(), spec, out_dir=str(tmp_path), on_progress=lambda s, p: events.append((s, p))
    )

    assert not result.ok, "a file that no longer matches its spec is not reusable as-is"
    assert result.measured_volume_mm3 == 1500.0
    assert events[0][1]["ok"] is False


class FakeDrawModel:
    """The document draw() opens, shows the four orientations on, and closes."""

    def __init__(self):
        self.named_views: list[str] = []
        self.closed = False

    def ShowNamedView2(self, name, view_id):
        self.shown = getattr(self, "shown", []) + [view_id]

    def NameView(self, name):
        self.named_views.append(name)

    def GetTitle(self):
        return "plate"

    def ClearSelection2(self, all_):
        return True


class FakeDrawingDoc:
    """A drawing that grows one view per add_named_view, then dimension it."""

    def __init__(self, gain=2):
        self.gain = gain
        self.calls: list[tuple[str, int]] = []
        self.dimensioned: list[str] = []
        self.saved = None
        self.exported = None
        self.closed = False

    def add_named_view(self, model_path, view_name, x_mm, y_mm):
        placed = f"Drawing View{len(self.calls) + 1}"
        self.calls.append((placed, 0))
        return placed

    def auto_dimension(self, view_name, **kwargs):
        self.dimensioned.append(view_name)
        for index, (name, count) in enumerate(self.calls):
            if name == view_name:
                self.calls[index] = (name, count + self.gain)
                return self.gain
        raise AssertionError(f"dimensioned a view that is not there: {view_name}")

    def save(self, path):
        self.saved = path
        return path

    def export_pdf(self, path):
        self.exported = path
        return path

    def close(self):
        self.closed = True


def _draw_session(drawing):
    events = []
    session = SimpleNamespace(
        open_document=lambda path, doctype: FakeDrawModel(),
        activate=lambda model: events.append("activate"),
        new_drawing=lambda sheet=None: drawing,
        app=None,
    )
    return session


def test_draw_dimensions_each_view_as_it_is_placed(tmp_path, monkeypatch):
    """AutoDimension only reaches the active view, so the order here is the feature.

    Placing all four views and dimensioning them afterwards puts every
    dimension on the last view and leaves the other three at zero (measured:
    front/top/right 0, iso 9).  Interleaving is what produces four annotated
    views, so the fake records the interleaving, not just the totals.
    """
    from swforge import generate

    drawing = FakeDrawingDoc(gain=2)
    monkeypatch.setattr(
        generate, "SwModel", lambda model, app: SimpleNamespace(close=lambda: None)
    )

    files = generate.draw(
        _draw_session(drawing), tmp_path / "plate.sldprt", out_dir=str(tmp_path)
    )

    assert len(drawing.calls) == 4, "four views, none of them skipped"
    assert drawing.calls == [
        ("Drawing View1", 2),
        ("Drawing View2", 2),
        ("Drawing View3", 2),
        ("Drawing View4", 2),
    ], "every view was dimensioned, and each view got its own dimensions"
    assert files["dimensions"] == "8"
    assert files["views"] == (
        "Drawing View1, Drawing View2, Drawing View3, Drawing View4"
    )
    assert drawing.closed


def test_draw_can_leave_the_views_unannotated(tmp_path, monkeypatch):
    from swforge import generate

    drawing = FakeDrawingDoc()
    monkeypatch.setattr(
        generate, "SwModel", lambda model, app: SimpleNamespace(close=lambda: None)
    )

    files = generate.draw(
        _draw_session(drawing),
        tmp_path / "plate.sldprt",
        out_dir=str(tmp_path),
        dimensions=False,
    )

    assert drawing.dimensioned == [], "--no-dimensions must not dimension"
    assert files["dimensions"] == "0"


def test_a_missing_part_is_not_an_error_and_says_nothing(tmp_path):
    """None is the signal to build it; a resumed run must not report a stage for it."""
    from swforge import generate

    spec = SimpleNamespace(tolerance=0.01, kind="washer", name="washer_M8", params={})
    events = []

    class Session:
        def open_part(self, path):  # pragma: no cover - must not be reached
            raise AssertionError("a missing file is not opened")

    result = generate.reuse_part(
        Session(), spec, out_dir=str(tmp_path), on_progress=lambda s, p: events.append((s, p))
    )

    assert result is None
    assert events == []
