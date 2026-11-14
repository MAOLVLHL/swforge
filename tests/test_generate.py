"""The pass/fail rule of a build, without SolidWorks anywhere near it."""

from types import SimpleNamespace

import pytest

from swforge.generate import BBOX_SLACK_MM, AssemblyResult, BuildResult, _bbox_errors


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
