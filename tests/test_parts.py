import math

import pytest

from swforge import parts
from swforge.demo import showcase
from swforge.spec import PartSpec


def test_every_kind_has_an_analytic_answer():
    for kind in parts.KINDS:
        spec = next(s for s in showcase() if s.kind == kind)
        solid = parts.analytic(kind, spec.params)
        assert solid.volume_mm3 > 0
        assert all(value > 0 for value in solid.bbox_mm)


def test_unknown_kind_names_the_alternatives():
    with pytest.raises(KeyError) as excinfo:
        parts.analytic("gizmo", {})
    assert "hex_bolt" in str(excinfo.value)


def test_hex_bolt_is_head_plus_shank():
    solid = parts.analytic("hex_bolt", {"size": "M8", "length": 40})
    head = math.sqrt(3) / 2 * 13**2 * 5.3
    shank = math.pi / 4 * 8**2 * 40
    assert solid.volume_mm3 == pytest.approx(head + shank)
    x, y, z = solid.bbox_mm
    assert y == pytest.approx(45.3)
    assert z == pytest.approx(13.0)


def test_hex_nut_is_a_prism_minus_the_clearance_bore():
    solid = parts.analytic("hex_nut", {"size": "M8"})
    prism = math.sqrt(3) / 2 * 13**2 * 6.8
    hole = math.pi / 4 * 8.4**2 * 6.8
    assert solid.volume_mm3 == pytest.approx(prism - hole)


def test_washer_is_an_annulus():
    solid = parts.analytic("washer", {"size": "M8"})
    expected = math.pi / 4 * (16**2 - 8.4**2) * 1.6
    assert solid.volume_mm3 == pytest.approx(expected)
    assert solid.bbox_mm == (16.0, 1.6, 16.0)


def test_socket_screw_removes_the_socket():
    plain = parts.analytic("socket_screw", {"size": "M6", "length": 25})
    with_socket = math.sqrt(3) / 2 * 5**2 * (0.6 * 6.0)
    head_and_shank = math.pi / 4 * 10**2 * 6 + math.pi / 4 * 6**2 * 25
    assert plain.volume_mm3 == pytest.approx(head_and_shank - with_socket)


def test_l_bracket_counts_the_corner_once():
    params = {
        "leg_a": 100.0,
        "leg_b": 50.0,
        "width": 40.0,
        "thickness": 5.0,
        "hole_d": 0,
    }
    solid = parts.analytic("l_bracket", params)
    expected = 100 * 40 * 5 + 5 * 40 * 50 - 5 * 40 * 5
    assert solid.volume_mm3 == pytest.approx(expected)


def test_l_bracket_holes_are_subtracted():
    base = {"leg_a": 100.0, "leg_b": 50.0, "width": 40.0, "thickness": 5.0}
    drilled = dict(base, hole_d=9.0, holes_in_long_leg=2)
    with_holes = parts.analytic("l_bracket", drilled)
    without = parts.analytic("l_bracket", base)
    removed = with_holes.volume_mm3 - without.volume_mm3
    # Only the long leg is drilled: two holes through the 5 mm plate.
    assert removed == pytest.approx(-2 * math.pi / 4 * 81 * 5)


def test_l_bracket_refuses_to_drill_the_short_leg():
    """Refusing beats shipping half a bracket that measures correct.

    A hole through the short leg is cut along X, across the plate thickness;
    every feature the builder draws starts from a top-plane profile extruded
    along Y.  Modelled solid, the bracket still verifies, because analytic and
    build leave the same holes out.
    """
    params = {
        "leg_a": 60.0,
        "leg_b": 40.0,
        "width": 40.0,
        "thickness": 5.0,
        "hole_d": 6.0,
        "short_leg_holes": 2,
    }
    with pytest.raises(ValueError) as excinfo:
        parts.analytic("l_bracket", params)
    message = str(excinfo.value)
    assert "modelled solid" in message, message
    assert "short_leg_holes" in message, message


def test_l_bracket_counts_only_the_long_leg_holes_it_drills():
    """holes_in_long_leg says where the holes are, so the count is the long leg."""
    base = {"leg_a": 100.0, "leg_b": 50.0, "width": 40.0, "thickness": 5.0}
    drilled = dict(base, hole_d=9.0, holes_in_long_leg=3)
    with_holes = parts.analytic("l_bracket", drilled)
    without = parts.analytic("l_bracket", base)
    removed = with_holes.volume_mm3 - without.volume_mm3
    assert removed == pytest.approx(-3 * math.pi / 4 * 81 * 5)


def test_l_bracket_rejects_two_holes_that_meet():
    """Two 95 mm loops 95 mm apart are one slot, and the sketch says two holes.

    The spacing of two holes across a leg is (leg_a - 2T) / 2, so this is the
    widest pair a bracket can hold at equality: anything closer and the first
    hole is already inside the corner.
    """
    params = {
        "leg_a": 200.0,
        "leg_b": 40.0,
        "width": 120.0,
        "thickness": 5.0,
        "hole_d": 95.0,
        "holes_in_long_leg": 2,
    }
    with pytest.raises(ValueError) as excinfo:
        parts.analytic("l_bracket", params)
    message = str(excinfo.value)
    assert "the 95 mm holes at (52.5, 60) and (147.5, 60) are 95 mm apart" in message
    assert "cut one slot" in message


def test_l_bracket_rejects_a_hole_that_runs_into_the_corner():
    # A 30 mm hole on a 36 mm leg sits at x 18, so it spans 3 .. 33 mm and
    # reaches back past the corner block that ends at x 5.  The short leg is a
    # profile from x 0 to x 5, and this loop would start it on a void.
    params = {
        "leg_a": 36.0,
        "leg_b": 40.0,
        "width": 40.0,
        "thickness": 5.0,
        "hole_d": 30.0,
        "holes_in_long_leg": 1,
    }
    with pytest.raises(ValueError) as excinfo:
        parts.analytic("l_bracket", params)
    message = str(excinfo.value)
    assert "the 30 mm hole at (18, 20) runs into the short leg" in message
    assert "cut from x 0 to x 5 mm" in message
    assert "it spans 3 .. 33 mm in x" in message


def test_l_bracket_keeps_a_hole_whose_edge_lands_on_the_corner():
    # The far side of the corner is not a wall: a loop ending exactly at x = T
    # still has the long leg under it from T onwards, and SolidWorks cuts this
    # without complaint.  A 26 mm hole at x 18 spans 5 .. 31 mm, so its edge is
    # on the corner face and one millimetre of it hangs over the void.
    params = {
        "leg_a": 36.0,
        "leg_b": 40.0,
        "width": 40.0,
        "thickness": 5.0,
        "hole_d": 26.0,
        "holes_in_long_leg": 1,
    }
    solid = parts.analytic("l_bracket", params)
    assert solid.volume_mm3 == pytest.approx(
        36 * 40 * 5 + 5 * 40 * 40 - 5 * 40 * 5 - math.pi / 4 * 26**2 * 5
    )


def test_l_bracket_refuses_a_hole_that_breaks_the_far_end_too():
    """The corner test is the only one needed, and this is why.

    A hole wide enough to leave the far end of the leg has already left the
    corner: the holes sit at the middle of the span from T to leg_a - T, so the
    margin at the corner is never the larger of the two.  One test, two ends.
    """
    params = {
        "leg_a": 36.0,
        "leg_b": 40.0,
        "width": 140.0,
        "thickness": 5.0,
        "hole_d": 100.0,
        "holes_in_long_leg": 1,
    }
    with pytest.raises(ValueError) as excinfo:
        parts.analytic("l_bracket", params)
    assert "runs into the short leg" in str(excinfo.value)


def test_l_bracket_does_not_need_a_width_test():
    """hole_d is capped below 0.8 * width, so a centred hole cannot reach a side.

    Naming the reason here keeps the cap and the missing check tied together: if
    the cap is ever loosened, this is the test that says what the cap was for.
    """
    params = {
        "leg_a": 100.0,
        "leg_b": 40.0,
        "width": 40.0,
        "thickness": 5.0,
        "hole_d": 31.0,
        "holes_in_long_leg": 1,
    }
    # 31 mm is under 0.8 * 40 = 32, and the hole spans 4.5 .. 35.5 mm in z.
    assert parts.analytic("l_bracket", params).volume_mm3 > 0
    with pytest.raises(ValueError) as excinfo:
        parts.analytic("l_bracket", dict(params, hole_d=32.0))
    assert "too large for the bracket width" in str(excinfo.value)


def test_l_bracket_rejects_impossible_geometry():
    with pytest.raises(ValueError):
        parts.analytic(
            "l_bracket",
            {"leg_a": 10.0, "leg_b": 10.0, "width": 10.0, "thickness": 20.0},
        )


def test_plate_hole_count_matches_the_grid():
    params = {
        "length": 120.0,
        "width": 80.0,
        "thickness": 6.0,
        "hole_d": 9.0,
        "rows": 2,
        "cols": 3,
    }
    grid = parts.analytic("multi_hole_plate", params)
    plate_only = 120 * 80 * 6
    assert grid.volume_mm3 == pytest.approx(
        plate_only - 6 * math.pi / 4 * 81 * 6
    )
    from swforge.parts.multi_hole_plate import hole_positions

    assert len(hole_positions(params)) == 6


def test_plate_rejects_zero_holes():
    with pytest.raises(ValueError):
        parts.analytic(
            "multi_hole_plate",
            {"length": 10, "width": 10, "thickness": 1, "hole_d": 2, "rows": 0},
        )


def test_stepped_shaft_sums_its_steps():
    params = {"d1": 20, "l1": 30, "d2": 15, "l2": 40, "d3": 10, "l3": 25}
    solid = parts.analytic("stepped_shaft", params)
    expected = sum(
        math.pi / 4 * d**2 * length
        for d, length in ((20, 30), (15, 40), (10, 25))
    )
    assert solid.volume_mm3 == pytest.approx(expected)
    assert solid.bbox_mm == (20.0, 95.0, 20.0)


def test_flange_subtracts_bore_and_bolt_holes():
    params = {
        "outer_d": 100.0,
        "hub_d": 62.0,
        "plate_t": 12.0,
        "hub_h": 8.0,
        "bore_d": 50.0,
        "bolt_d": 11.0,
        "bolt_count": 4,
        "bolt_circle_d": 78.0,
    }
    solid = parts.analytic("flange", params)
    plate = math.pi / 4 * (100**2 - 50**2) * 12
    hub = math.pi / 4 * (62**2 - 50**2) * 8
    holes = 4 * math.pi / 4 * 11**2 * 12
    assert solid.volume_mm3 == pytest.approx(plate + hub - holes)
    assert solid.bbox_mm == (100.0, 20.0, 100.0)


def test_flange_rejects_a_bore_bigger_than_the_hub():
    with pytest.raises(ValueError):
        parts.analytic(
            "flange",
            {
                "outer_d": 100.0,
                "hub_d": 40.0,
                "plate_t": 12.0,
                "hub_h": 8.0,
                "bore_d": 50.0,
            },
        )

def test_a_size_that_is_not_a_string_is_a_param_error_not_an_attribute_error():
    # catalog calls designation.upper(), so a number raises AttributeError from
    # two frames down.  The registry turns that into one exception type that says
    # which kind could not use the parameters.
    with pytest.raises(parts.ParamError) as excinfo:
        parts.analytic("washer", {"size": 8})
    assert "washer cannot use these parameters" in str(excinfo.value)
    assert isinstance(excinfo.value, ValueError), "callers catch ValueError"


def test_a_size_the_table_does_not_have_keeps_the_catalogue_message():
    # An unknown designation is also a KeyError, but its message already tells
    # the user the sizes that do exist -- wrapping it would bury that list.
    with pytest.raises(parts.ParamError) as excinfo:
        parts.analytic("hex_bolt", {"size": "M7", "length": 40})
    message = str(excinfo.value)
    assert "'M7' is not in GB/T 5783 hex bolts" in message
    assert "known sizes" in message


def test_a_missing_parameter_stays_a_key_error():
    # The CLI answers a missing parameter by naming it, which it can only do
    # while the KeyError survives with the field name in args[0].
    with pytest.raises(KeyError) as excinfo:
        parts.analytic("hex_bolt", {"size": "M8"})
    assert excinfo.value.args[0] == "length"


def test_build_reports_bad_parameters_the_same_way_as_analytic():
    # build() is the path a real SolidWorks run takes, and it reads the same
    # params, so it has to fail the same way instead of raising AttributeError
    # halfway through a sketch the user cannot see.
    with pytest.raises(parts.ParamError) as excinfo:
        parts.build(object(), "washer", {"size": 8})
    assert "washer cannot use these parameters" in str(excinfo.value)


def test_every_nut_can_pass_the_bolt_it_is_catalogued_for():
    """A threadless nut must be bored for the shank, not for a thread that is absent.

    The tap drill is 0.85*d, which leaves material for a thread this library
    never models -- so every nut was 0.2*d too small and refused its own bolt.
    """
    from swforge import catalog

    for designation in catalog.HEX_NUTS:
        bore = catalog.nut_bore(designation)
        bolt = catalog.hex_bolt(designation)
        assert bore > bolt.d, f"{designation}: bore {bore} does not clear d {bolt.d}"


def test_the_nut_bore_is_the_washer_inner_diameter_it_shares_a_size_with():
    """One clearance series, not two: a nut and its washer read the same bore."""
    from swforge import catalog

    for designation in catalog.HEX_NUTS:
        assert catalog.nut_bore(designation) == catalog.washer(designation).inner


def test_plate_rejects_a_hole_that_breaks_out_of_the_outline():
    # margin 2 puts a hole centre at (2, 2); a 9 mm hole there spans -2.5 .. 6.5
    # mm, so SolidWorks drops the loop and the extrude cuts nothing -- while
    # analytic() still subtracts 9 mm worth of material from the plate.
    with pytest.raises(ValueError) as excinfo:
        parts.analytic(
            "multi_hole_plate",
            {
                "length": 20,
                "width": 20,
                "thickness": 5,
                "hole_d": 9,
                "rows": 3,
                "cols": 3,
                "margin": 2,
            },
        )
    message = str(excinfo.value)
    assert "the 9 mm hole at (2, 2) breaks out of the 20 x 20 mm plate" in message
    assert "-2.5 .. 6.5 mm in x" in message


def test_plate_rejects_two_holes_that_overlap():
    # 19 mm holes on a 13.333 mm pitch are one slot, not two holes: the sketch
    # keeps both loops but the cut removes less than the arithmetic subtracts.
    with pytest.raises(ValueError) as excinfo:
        parts.analytic(
            "multi_hole_plate",
            {
                "length": 60,
                "width": 60,
                "thickness": 5,
                "hole_d": 19,
                "rows": 4,
                "cols": 4,
                "margin": 10,
            },
        )
    assert "the 19 mm holes at (10, 10) and (23.333, 10) are 13.333 mm apart" in str(
        excinfo.value
    )


@pytest.mark.parametrize(
    "length, width, rows, cols, margin, span",
    [
        (100, 20, 1, 2, 4.5, "it spans 0 .. 9 mm in x"),
        (100, 20, 1, 2, 95.5, "it spans 91 .. 100 mm in x"),
        (20, 100, 2, 1, 4.5, "0 .. 9 mm in z"),
        (20, 100, 2, 1, 95.5, "91 .. 100 mm in z"),
    ],
)
def test_plate_rejects_a_hole_whose_edge_lands_on_the_outline(
    length, width, rows, cols, margin, span
):
    # A loop that touches the outline without crossing it used to be accepted,
    # on the reasoning that a tangent loop is still a closed loop. SolidWorks
    # answers "extrude of 5.0 mm failed": with no wall behind it the cut has
    # nothing to follow, so the edge is already outside what this plate can
    # drill. Each of the four sides is checked on its own, because a test that
    # only touches the same edge cannot tell which comparison the code makes.
    params = {
        "length": length,
        "width": width,
        "thickness": 5,
        "hole_d": 9,
        "rows": rows,
        "cols": cols,
        "margin": margin,
    }
    with pytest.raises(ValueError) as excinfo:
        parts.analytic("multi_hole_plate", params)
    message = str(excinfo.value)
    assert "lands on the edge of the" in message, message
    assert span in message, message


def test_plate_rejects_two_holes_exactly_one_diameter_apart():
    # Two 10 mm loops 10 mm apart meet at a single point: the sketch keeps both,
    # the cut joins them into one slot and removes less than two holes' worth.
    params = {
        "length": 100,
        "width": 40,
        "thickness": 5,
        "hole_d": 10,
        "rows": 1,
        "cols": 2,
        "margin": 45,
    }
    with pytest.raises(ValueError) as excinfo:
        parts.analytic("multi_hole_plate", params)
    assert "the 10 mm holes at (45, 20) and (55, 20) are 10 mm apart" in str(
        excinfo.value
    )


@pytest.mark.parametrize(
    "length, width, rows, cols, margin, span",
    [
        (100, 20, 1, 2, 4.4, "-0.1 .. 8.9 mm in x"),
        (100, 20, 1, 2, 95.6, "91.1 .. 100.1 mm in x"),
        (20, 100, 2, 1, 4.4, "-0.1 .. 8.9 mm in z"),
        (20, 100, 2, 1, 95.6, "91.1 .. 100.1 mm in z"),
    ],
)
def test_plate_rejects_a_hole_that_crosses_one_edge(
    length, width, rows, cols, margin, span
):
    """Each of the four sides is checked on its own, on the hole's edge.

    A test that only ever breaks the same corner cannot tell which of the four
    comparisons the code actually makes.
    """
    params = {
        "length": length,
        "width": width,
        "thickness": 5,
        "hole_d": 9,
        "rows": rows,
        "cols": cols,
        "margin": margin,
    }
    with pytest.raises(ValueError) as excinfo:
        parts.analytic("multi_hole_plate", params)
    assert span in str(excinfo.value)


def test_plate_still_accepts_the_showcase_grid():
    """The default margin is exactly what makes a grid feasible, so keep it."""
    for spec in showcase():
        if spec.kind in {"multi_hole_plate", "flange"}:
            assert parts.analytic(spec.kind, spec.params).volume_mm3 > 0


def test_flange_rejects_bolt_holes_that_overlap_the_bore():
    with pytest.raises(ValueError) as excinfo:
        parts.analytic(
            "flange",
            {
                "outer_d": 100,
                "hub_d": 62,
                "plate_t": 12,
                "hub_h": 8,
                "bore_d": 50,
                "bolt_d": 20,
                "bolt_count": 4,
                "bolt_circle_d": 55,
            },
        )
    message = str(excinfo.value)
    assert "the 20 mm bolt holes reach 17.5 mm from the centre" in message
    assert "inside the 50 mm bore" in message


def test_flange_rejects_bolt_holes_that_run_past_the_rim():
    with pytest.raises(ValueError) as excinfo:
        parts.analytic(
            "flange",
            {
                "outer_d": 100,
                "hub_d": 62,
                "plate_t": 12,
                "hub_h": 8,
                "bore_d": 50,
                "bolt_d": 11,
                "bolt_count": 4,
                "bolt_circle_d": 96,
            },
        )
    message = str(excinfo.value)
    assert "the 11 mm bolt holes reach 53.5 mm from the centre" in message
    assert "past the 100 mm rim" in message


def test_flange_rejects_bolt_holes_that_meet_each_other():
    with pytest.raises(ValueError) as excinfo:
        parts.analytic(
            "flange",
            {
                "outer_d": 300,
                "hub_d": 62,
                "plate_t": 12,
                "hub_h": 8,
                "bore_d": 50,
                "bolt_d": 11,
                "bolt_count": 40,
                "bolt_circle_d": 100,
            },
        )
    assert "40 bolt holes 11 mm across sit 7.846 mm apart" in str(excinfo.value)


def test_flange_rejects_a_bolt_diameter_with_no_bolts():
    # bolt_count=0 removes no material in the build but subtracts a negative
    # count in the arithmetic, i.e. it adds plate that was never there.
    with pytest.raises(ValueError) as excinfo:
        parts.analytic(
            "flange",
            {
                "outer_d": 100,
                "hub_d": 62,
                "plate_t": 12,
                "hub_h": 8,
                "bore_d": 50,
                "bolt_d": 11,
                "bolt_count": 0,
                "bolt_circle_d": 78,
            },
        )
    assert "a 11 mm bolt hole needs at least one hole, got bolt_count=0" in str(
        excinfo.value
    )


def test_flange_rejects_a_plate_that_is_not_there():
    with pytest.raises(ValueError) as excinfo:
        parts.analytic(
            "flange",
            {
                "outer_d": 100,
                "hub_d": 62,
                "plate_t": -6,
                "hub_h": 8,
                "bore_d": 50,
            },
        )
    assert "plate_t must be positive, got -6.0" in str(excinfo.value)


def test_flange_rejects_a_hub_that_is_not_there():
    with pytest.raises(ValueError) as excinfo:
        parts.analytic(
            "flange",
            {
                "outer_d": 100,
                "hub_d": 62,
                "plate_t": 12,
                "hub_h": 0,
                "bore_d": 50,
            },
        )
    assert "hub_h must be positive, got 0.0" in str(excinfo.value)


@pytest.mark.parametrize(
    "kind, size",
    [("hex_bolt", "M8"), ("socket_screw", "M6")],
)
@pytest.mark.parametrize("length", [0, -1, -40])
def test_a_free_form_length_has_to_be_positive(kind, size, length):
    """Zero is not a short fastener: the answer used to be shorter than the head.

    hex_bolt M8 length=0 came back as V=775.699 bbox=(15.011, 5.3, 13) -- the
    head alone -- and length=-1 as V=725.433 with a 4.3 mm body.  Nothing
    downstream noticed, so verify printed both and exited 0.
    """
    with pytest.raises(ValueError) as excinfo:
        parts.analytic(kind, {"size": size, "length": length})
    assert "length must be positive" in str(excinfo.value)


def test_a_negative_hole_diameter_is_refused():
    """hole_d=-9 used to answer with the volume of hole_d=9, because of the square.

    The squared diameter hid the sign from the volume comparison while the
    builder put a -9 mm circle into the sketch and handed it to SolidWorks.
    """
    params = {"leg_a": 60, "leg_b": 40, "width": 40, "thickness": 5, "hole_d": -9}
    with pytest.raises(ValueError) as excinfo:
        parts.analytic("l_bracket", params)
    assert "hole_d must not be negative" in str(excinfo.value)


@pytest.mark.parametrize("count", [0, -1, -2])
def test_a_non_positive_hole_count_is_refused(count):
    """A count of -2 is subtracted backwards: the bracket gained material.

    The 60x40x40x5 bracket is 19000 mm3 with no holes and was 19636.173 with
    hole_d 9 and holes_in_long_leg -2, so the "verified" part matched a negative
    number of holes.
    """
    params = {
        "leg_a": 60,
        "leg_b": 40,
        "width": 40,
        "thickness": 5,
        "hole_d": 9,
        "holes_in_long_leg": count,
    }
    with pytest.raises(ValueError) as excinfo:
        parts.analytic("l_bracket", params)
    message = str(excinfo.value)
    assert "holes_in_long_leg must be at least 1" in message, message
    # The count is only half the message: it has to name the way out too.
    assert "use hole_d 0 to leave the leg solid" in message, message


def test_one_hole_per_leg_is_still_a_hole():
    """The guard is a floor, not a preference: one hole is a drilled leg."""
    params = {"leg_a": 60, "leg_b": 40, "width": 40, "thickness": 5, "hole_d": 9}
    solid = parts.analytic("l_bracket", dict(params, holes_in_long_leg=1))
    assert solid.volume_mm3 == pytest.approx(19000.0 - math.pi / 4 * 81 * 5)


def test_the_same_bracket_without_holes_is_unchanged():
    """hole_d 0 still means no drilling, so the count cannot change the answer."""
    params = {"leg_a": 60, "leg_b": 40, "width": 40, "thickness": 5}
    solid = parts.analytic("l_bracket", dict(params, hole_d=0, holes_in_long_leg=2))
    assert solid.volume_mm3 == pytest.approx(19000.0)

def test_a_solid_leg_does_not_need_a_hole_count():
    """No hole diameter means no holes, so the count cannot contradict anything.

    The count guard is gated on hole_d for this reason: hole_d defaults to 0.0,
    and a caller who wants solid legs should not have to know holes_in_long_leg
    exists.  Making the guard unconditional would reject that caller.
    """
    params = {"leg_a": 60, "leg_b": 40, "width": 40, "thickness": 5}
    solid = parts.analytic("l_bracket", dict(params, hole_d=0, holes_in_long_leg=0))
    assert solid.volume_mm3 == pytest.approx(19000.0)