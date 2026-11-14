"""What each builder actually asks SolidWorks to draw.

The analytic answers in swforge.geometry are checked elsewhere; these tests take
the other half of the contract: build() has to draw the part whose volume the
analytic answer promises.  A recording model stands in for SwModel, so the whole
sketch/extrude/cut script is readable in a test and replayable as a volume.
"""

from __future__ import annotations

import math

import pytest
from fakebrep import RecordingModel

from swforge import parts
from swforge.catalog import hex_bolt as hex_bolt_size
from swforge.catalog import socket_screw as socket_screw_size
from swforge.demo import showcase


def _volume(kind: str, params: dict) -> float:
    """Volume of the closed-form answer, i.e. what build() has to reproduce."""
    solid = parts.analytic(kind, params)
    return solid.volume_mm3


def _record(kind: str, params: dict) -> tuple[RecordingModel, float]:
    model = RecordingModel()
    parts.build(model, kind, params)
    return model, _volume(kind, params)


#: Bodies that SolidWorks merges but this replay sums: the builder has to say
#: how much of the second extrusion lands inside the first.
OVERLAP_MM3 = {
    # The two legs of the L share the corner block t x width x t.
    "l_bracket": lambda params: (
        float(params["thickness"]) * float(params["width"]) * float(params["thickness"])
    ),
}


@pytest.mark.parametrize("spec", showcase(), ids=lambda spec: spec.name)
def test_every_builder_draws_the_volume_the_analytic_answer_promises(spec):
    model, expected = _record(spec.kind, spec.params)
    overlap = OVERLAP_MM3.get(spec.kind)
    drawn = model.volume_mm3(overlap(spec.params) if overlap else 0.0)
    assert drawn == pytest.approx(expected, rel=1e-9), model


@pytest.mark.parametrize("spec", showcase(), ids=lambda spec: spec.name)
def test_every_builder_extrudes_something(spec):
    model, _ = _record(spec.kind, spec.params)
    assert any(feature.op == "extrude" for feature in model.features), model


def test_washer_is_one_sketch_with_two_loops_and_one_extrude():
    params = {"size": "M8"}
    model, expected = _record("washer", params)
    assert len(model.sketches) == 1
    assert [loop.shape for loop in model.sketches[0].loops] == ["circle", "circle"]
    assert [feature.op for feature in model.features] == ["extrude"]
    assert model.features[0].depth == pytest.approx(1.6)
    assert model.volume_mm3() == pytest.approx(expected)


def test_hex_nut_drills_its_hole_with_a_through_cut():
    """The hole is a second sketch cut through, not an inner loop.

    A hexagon and a circle in one profile come out wrong in the SolidWorks build
    this library targets -- the circle is dropped -- so the builder drills the
    way a shop would.  Moving the circle into the first sketch would halve the
    feature count and silently produce a solid nut.
    """
    params = {"size": "M8"}
    model, expected = _record("hex_nut", params)
    assert [len(sketch.loops) for sketch in model.sketches] == [1, 1]
    assert model.sketches[1].loops[0].args[2] == pytest.approx(round(0.85 * 8, 3))
    assert [feature.op for feature in model.features] == ["extrude", "cut_through"]
    assert model.volume_mm3() == pytest.approx(expected)


def test_socket_screw_cuts_the_socket_blind_to_six_tenths_of_the_head():
    params = {"size": "M6", "length": 25}
    size = socket_screw_size("M6")
    model, expected = _record("socket_screw", params)
    socket = model.features[-1]
    assert socket.op == "cut_blind"
    assert socket.depth == pytest.approx(round(0.6 * size.k, 3))
    assert model.volume_mm3() == pytest.approx(expected)


def test_hex_bolt_hangs_the_shank_below_the_head():
    params = {"size": "M8", "length": 40}
    head = hex_bolt_size("M8")
    model, expected = _record("hex_bolt", params)
    assert [(f.op, f.start) for f in model.features] == [
        ("extrude", 0.0),
        ("extrude", -head.k),
    ]
    assert model.features[1].depth == pytest.approx(40.0)
    assert model.volume_mm3() == pytest.approx(expected)


def test_stepped_shaft_stacks_each_step_below_the_previous_one():
    params = {"d1": 20, "l1": 30, "d2": 15, "l2": 40, "d3": 10, "l3": 25}
    model, expected = _record("stepped_shaft", params)
    assert [feature.start for feature in model.features] == [0.0, -30.0, -70.0]
    assert [feature.depth for feature in model.features] == [30.0, 40.0, 25.0]
    assert model.volume_mm3() == pytest.approx(expected)


def test_l_bracket_drills_the_long_leg_only():
    params = {
        "leg_a": 60,
        "leg_b": 40,
        "width": 40,
        "thickness": 5,
        "hole_d": 9,
        "holes_per_leg": 2,
    }
    model, expected = _record("l_bracket", params)
    long_leg, short_leg = model.sketches
    assert [loop.shape for loop in long_leg.loops] == ["rectangle", "circle", "circle"]
    assert [loop.shape for loop in short_leg.loops] == ["rectangle"]
    assert model.volume_mm3(5 * 40 * 5) == pytest.approx(expected)


def test_flange_stacks_the_hub_below_the_plate():
    params = {
        "outer_d": 100,
        "hub_d": 62,
        "plate_t": 12,
        "hub_h": 8,
        "bore_d": 50,
        "bolt_d": 11,
        "bolt_count": 4,
        "bolt_circle_d": 78,
    }
    model, expected = _record("flange", params)
    plate, hub = model.sketches
    assert len(plate.loops) == 2 + 4
    assert len(hub.loops) == 2
    assert model.features[1].start == pytest.approx(-12.0)
    assert model.features[1].depth == pytest.approx(8.0)
    assert model.volume_mm3() == pytest.approx(expected)


def test_plate_puts_every_hole_in_the_one_sketch():
    params = {
        "length": 120,
        "width": 80,
        "thickness": 6,
        "hole_d": 9,
        "rows": 2,
        "cols": 3,
    }
    model, expected = _record("multi_hole_plate", params)
    assert len(model.sketches) == 1
    assert len(model.sketches[0].loops) == 1 + 6
    assert [feature.op for feature in model.features] == ["extrude"]
    assert model.volume_mm3() == pytest.approx(expected)


def test_a_builder_leaves_exactly_one_profile_selected():
    """select_sketch drops the previous selection before picking the sketch.

    Two selected profiles make FeatureExtrusion3 refuse the call with no error,
    so a builder that forgets clear_selection() loses the body instead of failing
    loudly.  The recorder counts the selection at every feature.
    """
    for spec in showcase():
        model, _ = _record(spec.kind, spec.params)
        assert len(model.selections) == len(model.features), spec.name


def test_the_recorder_replays_a_circle_exactly():
    """Guard the guard: the replay is only worth trusting if it is arithmetic.

    This is the one place a wrong Loop.area would hide -- every comparison above
    would still pass, because expected and drawn would both be wrong the same way
    if the builders and the closed forms shared the mistake.
    """
    model = RecordingModel()
    with model.sketch("top") as sk:
        sk.circle(0.0, 0.0, 10.0)
        sk.circle(0.0, 0.0, 4.0)
    model.clear_selection()
    model.select_sketch(model.last_sketch)
    model.extrude(3.0)
    assert model.volume_mm3() == pytest.approx(math.pi / 4 * (100 - 16) * 3.0)


def test_build_names_the_alternatives_for_an_unknown_kind():
    model = RecordingModel()
    with pytest.raises(KeyError) as excinfo:
        parts.build(model, "gizmo", {})
    assert "hex_bolt" in str(excinfo.value)
    assert model.features == []


def test_l_bracket_without_holes_drills_nothing():
    """hole_d 0 switches the pattern off, so the sketch is one rectangle.

    The builder branch matters: without it every bracket would carry a row of
    zero-diameter circles, which SolidWorks rejects as an invalid profile.
    """
    params = {
        "leg_a": 60,
        "leg_b": 40,
        "width": 40,
        "thickness": 5,
        "hole_d": 0,
    }
    model, expected = _record("l_bracket", params)
    assert [loop.shape for loop in model.sketches[0].loops] == ["rectangle"]
    assert model.volume_mm3(5 * 40 * 5) == pytest.approx(expected)


def test_flange_without_bolt_holes_has_no_bolt_circle():
    params = {
        "outer_d": 100,
        "hub_d": 62,
        "plate_t": 12,
        "hub_h": 8,
        "bore_d": 50,
    }
    model, expected = _record("flange", params)
    assert len(model.sketches[0].loops) == 2
    assert model.volume_mm3() == pytest.approx(expected)


def test_a_single_hole_is_centred_between_the_margins():
    """rows=cols=1 centres the one hole instead of dividing by zero."""
    params = {
        "length": 120,
        "width": 80,
        "thickness": 6,
        "hole_d": 9,
        "rows": 1,
        "cols": 1,
    }
    model, expected = _record("multi_hole_plate", params)
    hole = model.sketches[0].loops[1]
    # One hole in the middle of the plate: the grid spreads across the two
    # margins instead of dividing by (count - 1) == 0.
    assert hole.args[:2] == pytest.approx((60.0, 40.0))
    assert model.volume_mm3() == pytest.approx(expected)


@pytest.mark.parametrize(
    "kind, params",
    [
        ("multi_hole_plate", {"length": 0, "width": 80, "thickness": 6, "hole_d": 9}),
        ("l_bracket", {"leg_a": 60, "leg_b": 40, "width": 0, "thickness": 5}),
        ("l_bracket", {"leg_a": 10, "leg_b": 10, "width": 10, "thickness": 20}),
        ("l_bracket", {"leg_a": 60, "leg_b": 40, "width": 40, "thickness": 5, "hole_d": 35}),
        ("flange", {"outer_d": 100, "hub_d": 40, "plate_t": 12, "hub_h": 8, "bore_d": 50}),
        ("flange", {"outer_d": 100, "hub_d": 120, "plate_t": 12, "hub_h": 8, "bore_d": 50}),
        (
            "flange",
            {
                "outer_d": 100,
                "hub_d": 62,
                "plate_t": 12,
                "hub_h": 8,
                "bore_d": 50,
                "bolt_d": 11,
                "bolt_circle_d": 10,
            },
        ),
        ("stepped_shaft", {"d1": 20, "l1": 0, "d2": 15, "l2": 40, "d3": 10, "l3": 25}),
    ],
)
def test_a_builder_refuses_impossible_parameters_before_drawing(kind, params):
    """build() validates the same way analytic() does, and before any sketch.

    A builder that starts sketching first leaves a half-built document open, and
    the next run pays the close-and-retry path for a part nobody asked for.
    """
    with pytest.raises(ValueError):
        parts.analytic(kind, params)
    model = RecordingModel()
    with pytest.raises(ValueError):
        parts.build(model, kind, params)
    assert model.sketches == []
