"""The assembly envelope, computed the way SolidWorks makes it necessary.

_assembly_bbox() maps every component's body box through that component's own
placement before the boxes are unioned.  Every other test that reaches
build_assembly() stubs the function out, so the union itself never runs, and the
bug it was written for -- GetBodyBox() answering in *part* coordinates, which
inflated a 120.00 mm assembly to 127.51 mm -- could come back with the suite
still green.

These tests drive the real function over components shaped the way
SwAssembly.components() hands them over, then push one assembly through
build_assembly() to the pass/fail rule.
"""

import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from swforge.assembly import Component
from swforge.generate import _assembly_bbox, build_assembly

IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


def turn_about_y(degrees: float) -> tuple[float, ...]:
    """A row-major 3x3 turn, the way Transform2.ArrayData carries one."""
    radians = math.radians(degrees)
    cos, sin = round(math.cos(radians), 12), round(math.sin(radians), 12)
    return (cos, 0.0, sin, 0.0, 1.0, 0.0, -sin, 0.0, cos)


def turn_about_z(degrees: float) -> tuple[float, ...]:
    radians = math.radians(degrees)
    cos, sin = round(math.cos(radians), 12), round(math.sin(radians), 12)
    return (cos, -sin, 0.0, sin, cos, 0.0, 0.0, 0.0, 1.0)


def metres(values):
    return tuple(float(value) / 1000.0 for value in values)


def placement(matrix=IDENTITY, at_mm=(0.0, 0.0, 0.0)):
    """The transform as Transform2.ArrayData reports it: nine matrix slots,
    then three metres of translation, metres throughout."""
    return (*matrix, *metres(at_mm), 0.0, 0.0, 0.0, 1.0)


def body(lo_mm, hi_mm):
    """GetBodyBox(): six metres, the low corner first."""
    return SimpleNamespace(GetBodyBox=lambda: (*metres(lo_mm), *metres(hi_mm)))


def component(name, box_mm=None, matrix=IDENTITY, at_mm=(0.0, 0.0, 0.0), placed=True):
    """One component as components() returns it: a COM stand-in plus a name."""
    bodies = [] if box_mm is None else [body(*box_mm)]
    comp = SimpleNamespace(
        Name2=name,
        GetPathName=rf"C:\out\{name}.sldprt",
        GetBodies2=lambda *args: list(bodies),
        Transform2=(
            SimpleNamespace(ArrayData=placement(matrix, at_mm)) if placed else None
        ),
    )
    return Component(name, f"{name}@stack", comp, Path(rf"C:\out\{name}.sldprt"))


def plate_and_bolts():
    """The showcase shape: a 120 x 80 plate with one bolt in each corner.

    Each bolt is modelled about its own centre, so its body box runs -6.5..6.5.
    Their placements put those halves back inside the plate, which is the whole
    point: the union is the plate, 120.0 x 6.0 x 80.0, not 126.5 x 6.0 x 86.5.
    """
    corners = ((6.5, 0.0, 6.5), (113.5, 0.0, 6.5), (6.5, 0.0, 73.5), (113.5, 0.0, 73.5))
    bolts = [
        component(
            f"bolt-{index}",
            box_mm=((-6.5, 0.0, -6.5), (6.5, 5.3, 6.5)),
            at_mm=at,
        )
        for index, at in enumerate(corners, start=1)
    ]
    plate = component("plate-1", box_mm=((0.0, 0.0, 0.0), (120.0, 6.0, 80.0)))
    return [plate, *bolts]


def assembly_of(components):
    return SimpleNamespace(components=lambda: list(components))


def test_a_single_component_reports_its_own_box():
    one = component("washer-1", box_mm=((0.0, 0.0, 0.0), (22.0, 1.6, 22.0)))
    assert _assembly_bbox(assembly_of([one])) == pytest.approx((22.0, 1.6, 22.0))


def test_a_bolt_in_the_corner_adds_nothing_to_the_plate():
    """The 127.51 mm bug: a part box unioned without its own placement.

    Unioning the bolt box raw would extend the envelope half a bolt width past
    the plate, which is the shape of the 127.51 x 45.30 x 86.50 that used to
    be reported against a predicted 120.00 x 45.30 x 80.00.
    """
    assert _assembly_bbox(assembly_of(plate_and_bolts())) == pytest.approx(
        (120.0, 6.0, 80.0)
    ), "the bolts sit in the corners of the plate, so the plate is the envelope"


def test_four_bolts_in_four_corners_span_the_whole_pattern():
    corners = ((0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (0.0, 0.0, 70.0), (100.0, 0.0, 70.0))
    bolts = [
        component(
            f"bolt-{index}", box_mm=((0.0, 0.0, 0.0), (13.0, 5.3, 13.0)), at_mm=at
        )
        for index, at in enumerate(corners, start=1)
    ]
    assert _assembly_bbox(assembly_of(bolts)) == pytest.approx((113.0, 5.3, 83.0)), (
        "the corners are centres, so each part reaches half a width past its own "
        "centre: 100 + 13 in x, 70 + 13 in z"
    )


def test_a_part_turned_ninety_degrees_reports_its_turned_extent():
    turned = component(
        "bracket-1",
        box_mm=((0.0, 0.0, 0.0), (30.0, 10.0, 4.0)),
        matrix=turn_about_y(90.0),
    )
    assert _assembly_bbox(assembly_of([turned])) == pytest.approx((4.0, 10.0, 30.0)), (
        "the box read in part coordinates would claim 30 x 10 x 4 right here"
    )


def test_a_part_turned_forty_five_degrees_grows_by_root_two():
    turned = component(
        "plate-1",
        box_mm=((0.0, 0.0, 0.0), (10.0, 0.0, 10.0)),
        matrix=turn_about_y(45.0),
    )
    dx, dy, dz = _assembly_bbox(assembly_of([turned]))
    assert dx == pytest.approx(10.0 * math.sqrt(2.0), abs=1e-3), (
        "all eight corners are mapped, so the turned diagonal is the extent"
    )
    assert dx == pytest.approx(dz), "a square turned 45 degrees stays square"
    assert dy == pytest.approx(0.0), "nothing turns about the flat axis"


def test_the_envelope_is_rounded_to_a_thousandth_of_a_millimetre():
    turned = component(
        "plate-1",
        box_mm=((0.0, 0.0, 0.0), (7.0, 3.0, 7.0)),
        matrix=turn_about_z(30.0),
    )
    box = _assembly_bbox(assembly_of([turned]))
    assert box == tuple(round(value, 3) for value in box), (
        "this number goes into a summary line and a tolerance check"
    )


def test_a_component_without_a_body_is_skipped_not_counted():
    empty = component("ghost-1", box_mm=None)
    solid = component("plate-1", box_mm=((0.0, 0.0, 0.0), (10.0, 2.0, 4.0)))
    assert _assembly_bbox(assembly_of([empty])) is None, (
        "no component produced a body, so there is nothing to measure"
    )
    pair = assembly_of([empty, solid])
    assert _assembly_bbox(pair) == pytest.approx((10.0, 2.0, 4.0)), (
        "one body-less component must not turn the whole measurement into None"
    )


def test_an_empty_assembly_has_no_envelope():
    assert _assembly_bbox(assembly_of([])) is None, (
        "the union starts at infinities, and only a real box brings it back"
    )


class EnvelopeAssembly:
    """An assembly whose components() hands back real Components.

    build_assembly() asks an assembly for add_component(), find(), mate_planes(),
    measure(), save() and export_step(); only components() matters for the
    envelope, and this one answers it with the same objects SolidWorks fills in.
    """

    def __init__(self, components):
        self._components = list(components)
        self.inserted = []
        self.saved = None
        self.closed = False

    def components(self):
        return list(self._components)

    def add_component(self, path, x, y, z, instance=None):
        self.inserted.append(instance)
        return SimpleNamespace(name=instance)

    def find(self, name):
        return SimpleNamespace(name=name)

    def mate_planes(self, first, second, **kwargs):
        return f"{first.name}-{second.name}"

    def measure(self):
        return 1000.0, 0.0

    def save(self, path):
        self.saved = str(path)
        return path

    def export_step(self, path):
        return path

    def close(self):
        self.closed = True


def one_bolt_spec(bbox_mm=(120.0, 6.0, 80.0)):
    """One part, one placement: enough to reach the measurement."""
    part = SimpleNamespace(kind="plate")
    placement_spec = SimpleNamespace(
        part="plate", instance="plate-1", x_mm=0.0, y_mm=0.0, z_mm=0.0
    )
    return SimpleNamespace(
        name="stack",
        tolerance=0.01,
        parts={"plate": part},
        placements=[placement_spec],
        mates=[],
        predict=lambda: SimpleNamespace(volume_mm3=1000.0, bbox_mm=bbox_mm),
        validate=lambda: None,
    )


def build_with(monkeypatch, components, spec=None):
    """Run build_assembly() over *components*, with the real envelope code."""
    monkeypatch.setattr(
        "swforge.generate.generate",
        lambda session, part_spec, **kwargs: SimpleNamespace(
            files={"part": r"C:\out\plate.sldprt"}
        ),
    )
    session = SimpleNamespace(new_assembly=lambda: EnvelopeAssembly(components))
    return build_assembly(session, spec or one_bolt_spec())


def test_the_assembly_passes_when_the_real_envelope_matches_the_prediction(monkeypatch):
    """The one path the stubbed tests never walk: a measured envelope, verified."""
    components = [component("plate-1", box_mm=((0.0, 0.0, 0.0), (120.0, 6.0, 80.0)))]
    result = build_with(monkeypatch, components)
    assert result.measured_bbox_mm == pytest.approx((120.0, 6.0, 80.0))
    assert result.bbox_errors == {"x": 0.0, "y": 0.0, "z": 0.0}
    assert result.ok, result.summary()


def test_a_wrongly_placed_component_fails_the_assembly_it_would_have_passed(
    monkeypatch,
):
    """A bolt dropped outside the plate is caught by the envelope, not the volume."""
    plate = component("plate-1", box_mm=((0.0, 0.0, 0.0), (120.0, 6.0, 80.0)))
    stray = component(
        "bolt-1",
        box_mm=((0.0, 0.0, 0.0), (13.0, 5.3, 13.0)),
        at_mm=(130.0, 0.0, 0.0),
    )
    result = build_with(monkeypatch, [plate, stray])
    assert result.measured_bbox_mm == pytest.approx((143.0, 6.0, 80.0))
    assert not result.ok, "the volume is untouched; only the envelope knows"
    assert result.bbox_errors["x"] == pytest.approx(23.0 - 0.05), (
        "23 mm over, less the 0.05 mm tessellation slack the checker forgives"
    )
    assert result.volume_error == pytest.approx(0.0)


def test_a_component_without_a_placement_is_reported_as_a_measurement_failure(
    monkeypatch,
):
    """world_box_mm raises for it, and build_assembly reports instead of raising."""
    box = ((0.0, 0.0, 0.0), (120.0, 6.0, 80.0))
    broken = component("plate-1", box_mm=box, placed=False)
    result = build_with(monkeypatch, [broken])
    assert result.measured_bbox_mm is None
    assert "has no usable transform" in result.failures["<assembly>"]
    assert "assembly measurement failed" in " | ".join(result.notes)
    assert not result.ok
    assert "assembly" in result.files, (
        "a measurement that failed must not cost the .sldasm that was already saved"
    )


def test_a_body_less_assembly_reports_no_envelope_and_fails(monkeypatch):
    result = build_with(monkeypatch, [component("plate-1", box_mm=None)])
    assert result.measured_bbox_mm is None
    assert result.bbox_errors == dict.fromkeys(("x", "y", "z"), float("inf"))
    assert not result.ok
