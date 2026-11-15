"""Mates: the two calls that make one, without SolidWorks anywhere near them.

AddMate5 is the only member this library drives to create a mate, and its error
code is the opposite of every other call in the wrapper: swAddMateError_e
numbers failure 0 and success 1.  A fake that left the by-reference slot alone
would report every good mate as a failure, so the one below fills it in the way
the real call does.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

import fakecom
from swforge import generate
from swforge.assembly import (
    MATE_COINCIDENT,
    MATE_DISTANCE,
    MATE_NO_ERROR,
    Component,
    SwAssembly,
)
from swforge.session import SwError
from swforge.stack import Mate

ASM_PATH = r"C:\out\stack.SLDASM"
TOP = "上视基准面"
FRONT = "前视基准面"


def component(name: str = "bolt-1") -> Component:
    """One placed instance, addressed the way SelectByID2 needs it."""
    return Component(
        name=name,
        qualified=f"{name}@stack",
        comp=SimpleNamespace(Name2=name),
        path=Path(rf"C:\out\{name}.sldprt"),
    )


class FakeMateModel:
    """The assembly document as add_mate and mate_planes see it.

    Only the members those two functions read, but answered the way SolidWorks
    answers them: the error code arrives as a by-reference VARIANT that the call
    itself fills in, and every selection is one argument to SelectByID2.
    """

    def __init__(self, error: int = MATE_NO_ERROR, feature=True, select: bool = True):
        self.GetPathName = ASM_PATH
        self.GetTitle = Path(ASM_PATH).stem
        self.error = error
        #: True models a mate SolidWorks created; None models a call that
        #: answered nothing, which is what a refused selection looks like here.
        self.feature = (
            SimpleNamespace(Name="Distance1") if feature is True else feature
        )
        self.select = select
        #: Selection and mate calls in the order they happened -- the only way
        #: to tell "clear, select, mate, clear" from "select, mate".
        self.events: list[tuple] = []
        self.Extension = SimpleNamespace(SelectByID2=self._select)

    def _select(self, name, kind, x, y, z, append, mark, callout, options):
        self.events.append(("select", name, append))
        return self.select

    def ClearSelection2(self, *_args):
        self.events.append(("clear",))
        return True

    def AddMate5(self, *args):
        self.events.append(("mate", args[0], args[3]))
        args[-1].value = self.error
        return self.feature


def assembly(model: FakeMateModel) -> SwAssembly:
    return SwAssembly(model, None)


def test_the_error_code_that_means_success_is_one():
    assert MATE_NO_ERROR == 1, (
        "swAddMateError_e numbers failure 0 and success 1; reading it the "
        "intuitive way silently throws away every good mate"
    )
    assert (MATE_COINCIDENT, MATE_DISTANCE) == (0, 5), (
        "swMateType_e: coincident is 0, distance is 5"
    )


def test_add_mate_gives_solidworks_metres_and_a_by_reference_error(fake_com):
    model = FakeMateModel()
    name = assembly(model).add_mate(MATE_DISTANCE, distance_mm=5.3, flip=True)

    assert name == "Distance1"
    ((event, mate_type, distance_m),) = model.events
    assert event == "mate" and mate_type == MATE_DISTANCE
    assert distance_m == pytest.approx(0.0053), (
        "the API takes metres while every spec, parameter and measurement in "
        "this library is millimetres; this call is where the two meet"
    )


def test_add_mate_passes_fourteen_positional_arguments_and_the_error(fake_com):
    model = FakeMateModel()
    seen: list[tuple] = []

    def record(*args):
        seen.append(args)
        args[-1].value = MATE_NO_ERROR
        return SimpleNamespace(Name="Coincident1")

    model.AddMate5 = record
    name = assembly(model).add_mate(MATE_COINCIDENT, align=1, flip=True)
    assert name == "Coincident1"

    (args,) = seen
    assert len(args) == 15, "fourteen inputs plus the [out] swAddMateError"
    assert args[1] == 1, "align is the second argument"
    assert args[2] is True, "flip is the third"
    assert args[3] == 0.0, "a coincident mate has no distance to express"
    assert args[4:11] == (0.0,) * 7, "the seven unused distance arguments stay zero"
    assert args[11] is False and args[12] is False, "both flip flags are off"
    assert args[13] == 0.0
    assert args[-1].vt == fakecom.VT_BYREF | fakecom.VT_I4, (
        "a plain int here raises a type mismatch and the call reports nothing"
    )


def test_a_mate_reporting_zero_is_a_failure_not_a_success(fake_com):
    model = FakeMateModel(error=0)
    with pytest.raises(SwError) as caught:
        assembly(model).add_mate(MATE_DISTANCE, distance_mm=5.3)

    assert str(caught.value) == "mate of type 5 failed (swAddMateError=0)", (
        "the message has to name which mate failed and what SolidWorks thought "
        "was wrong with it"
    )


def test_a_mate_without_a_feature_fails_even_when_the_code_is_clean(fake_com):
    model = FakeMateModel(error=MATE_NO_ERROR, feature=None)
    with pytest.raises(SwError, match="swAddMateError=1"):
        assembly(model).add_mate(MATE_COINCIDENT)


def test_a_feature_without_a_name_still_returns_a_string(fake_com):
    model = FakeMateModel(feature=SimpleNamespace())
    assert assembly(model).add_mate(MATE_COINCIDENT) == "", (
        "the name is only used to report the mate, so a missing one degrades to "
        "an empty string instead of raising"
    )


def test_mate_planes_selects_the_same_plane_of_both_components_in_order(fake_com):
    model = FakeMateModel()
    assembly(model).mate_planes(component("bolt-1"), component("plate-1"))

    assert model.events == [
        ("clear",),
        ("select", f"{TOP}@bolt-1@stack", False),
        ("select", f"{TOP}@plate-1@stack", True),
        ("mate", MATE_COINCIDENT, 0.0),
        ("clear",),
    ], (
        "the second plane is appended to the first selection and the pair is "
        "dropped again afterwards: a stale selection reads as an extra entity "
        "and SolidWorks refuses the mate"
    )


def test_mate_planes_forwards_the_plane_type_distance_and_flip(fake_com):
    model = FakeMateModel()
    assembly(model).mate_planes(
        component("bolt-1"),
        component("plate-1"),
        plane=FRONT,
        mate_type=MATE_DISTANCE,
        distance_mm=5.3,
        flip=True,
    )

    assert model.events[1] == ("select", f"{FRONT}@bolt-1@stack", False)
    assert model.events[3] == ("mate", MATE_DISTANCE, pytest.approx(0.0053))


def test_a_coincident_mate_between_the_top_planes_is_the_default(fake_com):
    model = FakeMateModel()
    assembly(model).mate_planes(component("bolt-1"), component("plate-1"))
    assert model.events[3] == ("mate", MATE_COINCIDENT, 0.0), (
        "two planes that touch: no distance, no type argument, and the top "
        "plane of every generated part"
    )


def test_a_failed_mate_still_clears_the_selection(fake_com):
    model = FakeMateModel(error=0)
    with pytest.raises(SwError):
        assembly(model).mate_planes(component("bolt-1"), component("plate-1"))
    assert model.events[-1] == ("clear",), (
        "a raised mate leaves both planes selected; the next call would then "
        "start with three entities instead of two"
    )


def test_a_plane_solidworks_refuses_never_reaches_add_mate(fake_com):
    model = FakeMateModel(select=False)
    with pytest.raises(SwError, match="cannot select"):
        assembly(model).mate_planes(component("bolt-1"), component("plate-1"))
    assert [event for event, *_ in model.events] == ["clear", "select"], (
        "a mate between entities that are not both selected would be made "
        "against whatever was selected before"
    )


class RecordedAssembly:
    """Enough of an assembly to watch what build_assembly asks it to mate."""

    def __init__(self, fail: Exception | None = None):
        self.mated: list[dict] = []
        self.fail = fail
        self.closed = False

    def add_component(self, path, x, y, z, instance=None):
        return SimpleNamespace(name=instance)

    def find(self, name):
        return SimpleNamespace(name=name)

    def mate_planes(self, first, second, **kwargs):
        self.mated.append({"first": first.name, "second": second.name, **kwargs})
        if self.fail is not None:
            raise self.fail
        return f"{first.name}-{second.name}"

    def measure(self):
        return 1000.0, 1000.0

    def save(self, path):
        return path

    def export_step(self, path):
        return path

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, assembly):
        self.assembly = assembly

    def new_assembly(self):
        return self.assembly


def make_spec(distance_mm: float, flip: bool = False):
    """One plate placed twice and mated across its top planes."""
    part = SimpleNamespace(kind="plate", name="plate", params={})
    placements = [
        SimpleNamespace(part="plate", instance="plate-1", x_mm=0.0, y_mm=0.0, z_mm=0.0),
        SimpleNamespace(
            part="plate", instance="plate-2", x_mm=10.0, y_mm=0.0, z_mm=0.0
        ),
    ]
    mate = Mate(
        first="plate-1",
        second="plate-2",
        plane=TOP,
        distance_mm=distance_mm,
        flip=flip,
    )
    return SimpleNamespace(
        name="stack",
        tolerance=0.01,
        parts={"plate": part},
        placements=placements,
        mates=[mate],
        predict=lambda: SimpleNamespace(volume_mm3=1000.0, bbox_mm=(20.0, 20.0, 2.0)),
        validate=lambda: None,
    )


def build(record: RecordedAssembly, spec, monkeypatch):
    monkeypatch.setattr(
        generate,
        "generate",
        lambda session, part_spec, **kwargs: SimpleNamespace(files={"part": "p"}),
    )
    monkeypatch.setattr(
        generate, "_assembly_bbox", lambda assembly: (20.0, 20.0, 2.0)
    )
    return generate.build_assembly(FakeSession(record), spec)


def test_a_distance_mate_in_the_spec_arrives_as_type_five_in_metres(monkeypatch):
    """The spec speaks kind, plane and flip; AddMate5 speaks integers."""
    record = RecordedAssembly()
    result = build(record, make_spec(distance_mm=5.3, flip=True), monkeypatch)

    assert result.ok
    (call,) = record.mated
    assert call["mate_type"] == 5, "a 5.3 mm mate is a distance mate, type 5"
    assert call["distance_mm"] == 5.3, (
        "the spec's millimetres reach mate_planes unconverted: only add_mate "
        "divides by 1000, once"
    )
    assert call["flip"] is True, (
        "a distance mate is unsigned, so the spec's flip is the only thing "
        "saying which side the bolt hangs on"
    )
    assert call["plane"] == TOP


def test_a_zero_distance_mate_in_the_spec_arrives_as_type_zero(monkeypatch):
    record = RecordedAssembly()
    result = build(record, make_spec(distance_mm=0.0), monkeypatch)

    assert result.ok
    (call,) = record.mated
    assert call["mate_type"] == 0, (
        "Mate.kind calls a zero distance coincident; the mapping has to agree, "
        "or a touching pair is mated 5 mm apart"
    )
    assert call["distance_mm"] == 0.0


def test_a_mate_solidworks_refuses_stops_the_build(monkeypatch):
    """Only a missing component is skipped; a refused mate is not swallowed."""
    record = RecordedAssembly(fail=SwError("mate of type 5 failed (swAddMateError=0)"))
    with pytest.raises(SwError, match="swAddMateError=0"):
        build(record, make_spec(distance_mm=5.3), monkeypatch)
