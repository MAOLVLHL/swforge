import math

import pytest

from swforge.geometry import (
    SQRT3,
    Solid,
    annulus,
    cylinder,
    hex_prism,
    hex_prism_across_corners,
    hole_pattern,
    plate,
    relative_error,
    tap_drill,
)


def test_hex_prism_volume_matches_closed_form():
    solid = hex_prism(13.0, 5.3)
    assert solid.volume_mm3 == pytest.approx(SQRT3 / 2 * 13**2 * 5.3)


def test_hex_prism_bbox_is_across_corners_by_height_by_flats():
    solid = hex_prism(13.0, 5.3)
    x, y, z = solid.bbox_mm
    assert x == pytest.approx(2 * 13 / SQRT3)
    assert y == pytest.approx(5.3)
    assert z == pytest.approx(13.0)


def test_hex_prism_across_corners_is_the_dual_parameterisation():
    by_flats = hex_prism(13.0, 5.0)
    by_corners = hex_prism_across_corners(2 * 13 / SQRT3, 5.0)
    assert by_corners.volume_mm3 == pytest.approx(by_flats.volume_mm3)


def test_cylinder_volume_and_bbox():
    solid = cylinder(8.0, 40.0)
    assert solid.volume_mm3 == pytest.approx(math.pi / 4 * 64 * 40)
    assert solid.bbox_mm == (8.0, 40.0, 8.0)


def test_annulus_removes_the_bore():
    solid = annulus(16.0, 8.4, 1.6)
    expected = math.pi / 4 * (16**2 - 8.4**2) * 1.6
    assert solid.volume_mm3 == pytest.approx(expected)


def test_union_adds_volume_and_merges_boxes():
    head = hex_prism(13.0, 5.3)
    shank = cylinder(8.0, 40.0)
    bolt = head.extend(shank)
    assert bolt.volume_mm3 == pytest.approx(head.volume_mm3 + shank.volume_mm3)
    assert bolt.bbox_mm == (
        pytest.approx(max(head.bbox_mm[0], shank.bbox_mm[0])),
        pytest.approx(45.3),
        pytest.approx(max(head.bbox_mm[2], shank.bbox_mm[2])),
    )


def test_union_keeps_the_largest_profile():
    boss = cylinder(20.0, 5.0)
    plate_body = plate(100.0, 60.0, 5.0)
    fused = boss.union(plate_body)
    assert fused.bbox_mm == (100.0, 5.0, 60.0)


def test_difference_keeps_the_bounding_box():
    body = plate(100.0, 60.0, 10.0)
    body = body.difference(hole_pattern(9.0, 10.0, 4))
    assert body.bbox_mm == (100.0, 10.0, 60.0)


def test_difference_refuses_to_remove_everything():
    with pytest.raises(ValueError):
        cylinder(10.0, 10.0).difference(cylinder(20.0, 20.0))


def test_plate_puts_thickness_on_the_part_axis():
    assert plate(120.0, 80.0, 6.0).bbox_mm == (120.0, 6.0, 80.0)


def test_tap_drill_is_below_the_nominal_diameter():
    assert tap_drill(10.0) == pytest.approx(8.5)
    assert tap_drill(8.0) < 8.0


def test_relative_error_handles_zero():
    assert relative_error(0.0, 0.0) == 0.0
    assert relative_error(100.0, 101.0) == pytest.approx(0.01)
    assert relative_error(0.0, 1.0) == math.inf


def test_solid_is_frozen():
    solid = Solid(1.0, (1.0, 1.0, 1.0))
    with pytest.raises(Exception):
        solid.volume_mm3 = 2.0  # type: ignore[misc]
