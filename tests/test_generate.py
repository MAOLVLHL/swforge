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
