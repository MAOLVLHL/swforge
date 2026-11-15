"""What :class:`Sketch` asks ``SketchManager`` to draw, in metres.

The builders in :mod:`swforge.parts` are replayed against a recording model in
test_part_builds.py; this file covers the layer underneath them, where two
conversions live: millimetres to metres, and *across-flats* to circumradius.
A wrong factor in either one never raises.  SolidWorks draws a smaller
polygon, and the extrusion, the volume check and the STEP export all agree
with each other -- about the wrong part.  That is exactly the failure mode
this library exists to make impossible, so it is pinned at the COM boundary:
the assertions below read the numbers handed to ``CreatePolygon``.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from fakebrep import Loop

from swforge.geometry import hex_prism
from swforge.session import Sketch


class SketchManagerStub:
    """Records the arguments of the three entity calls and returns handles."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def CreateCircleByRadius(self, *args: float) -> str:
        self.calls.append(("circle", *args))
        return "circle-handle"

    def CreatePolygon(self, *args: float) -> str:
        self.calls.append(("polygon", *args))
        return "polygon-handle"

    def CreateCenterRectangle(self, *args: float) -> str:
        self.calls.append(("rectangle", *args))
        return "rectangle-handle"


@pytest.fixture
def sm() -> SketchManagerStub:
    """The sketch manager the Sketch writes through."""
    return SketchManagerStub()


@pytest.fixture
def sketch(sm: SketchManagerStub) -> Sketch:
    """A sketch on a stub model; Sketch.__init__ only touches ``model.sm``."""
    return Sketch(SimpleNamespace(sm=sm), "Sketch1")


def _only_call(sm: SketchManagerStub) -> tuple:
    assert len(sm.calls) == 1, f"expected exactly one entity call, got {sm.calls!r}"
    return sm.calls[0]


def _only_call_radius(sm: SketchManagerStub) -> float:
    """The circumradius, in metres, of the single polygon call recorded."""
    *_, radius_m, _second, _third, _sides, _inscribed = _only_call(sm)
    return float(radius_m)


def _across_flats_mm(radius_m: float, sides: int) -> float:
    """The across-flats distance of the polygon that radius produces.

    CreatePolygon with ``inscribed`` True takes the circumradius, so the
    vertices sit on the circle and the flats -- the apothem -- sit r*cos(pi/n)
    away from the centre.
    """
    return 2.0 * radius_m * 1000.0 * math.cos(math.pi / sides)


#: Side counts a caller may reasonably pass to the documented public API.
POLYGON_SIDES = [3, 4, 5, 6, 7, 8, 12]


@pytest.mark.parametrize("sides", POLYGON_SIDES)
def test_the_polygon_honours_the_across_flats_distance_it_was_given(sketch, sm, sides):
    sketch.polygon(0.0, 0.0, 13.0, sides)
    _, _, _, _, radius_m, _, _, drawn_sides, inscribed = _only_call(sm)
    assert drawn_sides == sides
    assert inscribed is True, (
        "inscribed=True is what makes the fourth argument a circumradius; if a "
        "future change flips it the point below becomes the apothem and every "
        "polygon grows by 1/cos(pi/n)"
    )
    assert _across_flats_mm(radius_m, sides) == pytest.approx(13.0, rel=1e-12), (
        "across-flats is the one number a polygon caller knows: it is the "
        "spanner size, the socket size, the dimension on the drawing. A "
        f"{sides}-gon asked for 13 mm across the flats came out at "
        f"{_across_flats_mm(radius_m, sides):.6f} mm."
    )


def test_a_square_comes_out_square(sketch, sm):
    """n = 4 is the case a reviewer can check by hand: af = r * sqrt(2)."""
    sketch.polygon(0.0, 0.0, 10.0, 4)
    _, _, _, _, radius_m, _, _, _, _ = _only_call(sm)
    assert radius_m == pytest.approx(0.005 * math.sqrt(2.0), rel=1e-12), (
        "a 10 mm square across the flats has its corners 7.071 mm from the "
        "centre; half of the flat-to-flat distance is the inscribed circle, "
        "not the circumscribed one"
    )


def test_the_hexagon_keeps_the_sqrt_three_conversion(sketch, sm):
    """The one side count that worked before, pinned so it cannot drift."""
    sketch.polygon(0.0, 0.0, 13.0)
    _, _, _, _, radius_m, _, _, sides, _ = _only_call(sm)
    assert sides == 6, "hexagon is the default every part builder relies on"
    assert radius_m == pytest.approx(13.0 / math.sqrt(3.0) / 1000.0, rel=1e-12)


def test_the_hexagon_agrees_with_the_analytic_bounding_box(sketch, sm):
    """Ties the COM conversion to geometry.hex_prism, the volume oracle."""
    sketch.polygon(0.0, 0.0, 13.0)
    _, _, _, _, radius_m, _, _, _, _ = _only_call(sm)
    across_corners_mm = 2.0 * radius_m * 1000.0
    assert across_corners_mm == pytest.approx(hex_prism(13.0, 1.0).bbox_mm[0]), (
        "hex_prism sizes its x envelope at 2 * across_flats / sqrt(3), which "
        "is the across-corners width a real hexagon has; a session polygon "
        "that disagrees would pass the volume check and fail the bbox check"
    )


@pytest.mark.parametrize("sides", [0, 1, 2, -6])
def test_a_polygon_needs_at_least_three_sides(sketch, sm, sides):
    with pytest.raises(ValueError, match="at least 3 sides"):
        sketch.polygon(0.0, 0.0, 13.0, sides)
    assert sm.calls == [], (
        "refusing before the call is the point: a two-sided polygon has no "
        "across-flats distance to divide by, and COM would be handed garbage"
    )


def test_the_polygon_reaches_com_in_metres_at_the_requested_centre(sketch, sm):
    assert sketch.polygon(20.0, -5.0, 13.0) == "polygon-handle", (
        "the entity handle is the documented return value"
    )
    kind, x_m, z_m, z_m2, radius_m, second, third, _, _ = _only_call(sm)
    assert kind == "polygon"
    assert (x_m, z_m, z_m2) == pytest.approx((0.02, -0.005, 0.0)), (
        "SolidWorks works in metres; a millimetre centre lands 1000x away and "
        "the sketch is silently off-plane"
    )
    reference = 13.0 / math.sqrt(3.0) / 1000.0
    assert (radius_m, second, third) == pytest.approx((reference, 0.0, 0.0)), (
        "the second point of a CreatePolygon call is the centre displaced by "
        "the circumradius along +u; anything else draws a different shape"
    )


def test_a_circle_is_drawn_from_its_diameter(sketch, sm):
    assert sketch.circle(5.0, -2.0, 8.0) == "circle-handle"
    kind, x_m, z_m, z_m2, radius_m = _only_call(sm)
    assert kind == "circle"
    assert (x_m, z_m, z_m2) == pytest.approx((0.005, -0.002, 0.0))
    assert radius_m == pytest.approx(0.004), (
        "CreateCircleByRadius takes a radius while the API above it takes a "
        "diameter; passing the diameter through doubles every hole and the "
        "volume check only catches it because the hole count is exact"
    )


def test_a_rectangle_is_drawn_as_a_centre_rectangle(sketch, sm):
    assert sketch.rectangle(0.0, 0.0, 10.0, 5.0) == "rectangle-handle"
    kind, x_m, z_m, z_m2, corner_x_m, corner_z_m, corner_z2 = _only_call(sm)
    assert kind == "rectangle"
    assert (x_m, z_m, z_m2) == pytest.approx((0.005, 0.0025, 0.0)), (
        "the centre of the two opposite corners, in metres"
    )
    assert (corner_x_m, corner_z_m, corner_z2) == pytest.approx((0.01, 0.005, 0.0)), (
        "the corner is handed over in absolute sketch coordinates, not as an "
        "offset from the centre, so it is simply x1 and z1 in metres"
    )


def test_the_recorder_reads_a_polygon_the_way_the_sketch_draws_it(sm):
    """test_part_builds replays builders through fakebrep.Loop.

    The replay is only an oracle if its polygon area is computed from the same
    circumradius the Sketch hands to CreatePolygon; a recorder that keeps a
    stale conversion would quietly bless a wrong builder.
    """
    sketch = Sketch(SimpleNamespace(sm=sm), "Sketch1")
    for sides in POLYGON_SIDES:
        sketch.polygon(0.0, 0.0, 13.0, sides)
        radius_m = _only_call_radius(sm)
        loop = Loop("polygon", 0.0, 0.0, 13.0, sides)
        expected = (
            sides / 2.0 * (radius_m * 1000.0) ** 2 * math.sin(2.0 * math.pi / sides)
        )
        assert loop.area == pytest.approx(expected, rel=1e-12), (
            f"the recording model reads a {sides}-gon as {loop.area:.6f} mm2 "
            f"while the sketch draws the circumradius {radius_m:.9f} m, i.e. "
            f"{expected:.6f} mm2"
        )
        sm.calls.clear()
