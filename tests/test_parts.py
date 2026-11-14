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


def test_hex_nut_is_a_prism_minus_the_tapped_hole():
    solid = parts.analytic("hex_nut", {"size": "M8"})
    prism = math.sqrt(3) / 2 * 13**2 * 6.8
    hole = math.pi / 4 * (0.85 * 8) ** 2 * 6.8
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
    drilled = dict(base, hole_d=9.0, holes_per_leg=2)
    with_holes = parts.analytic("l_bracket", drilled)
    without = parts.analytic("l_bracket", base)
    removed = with_holes.volume_mm3 - without.volume_mm3
    # Only the long leg is drilled: two holes through the 5 mm plate.
    assert removed == pytest.approx(-2 * math.pi / 4 * 81 * 5)


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

