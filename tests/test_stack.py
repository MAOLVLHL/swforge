"""Assembly specs: validation, prediction and the analytic contract.

These tests never touch SolidWorks.  They cover the half of the assembly path
that can be checked on any machine, which is also the half that decides whether
a build is accepted: the predicted volume and envelope.
"""

import json

import pytest

from swforge import parts
from swforge.demo import BOLT_HOLES, HEAD_HEIGHT_M8, bolt_stack
from swforge.spec import PartSpec
from swforge.stack import AssemblySpec, Mate, Placement, dump_assembly, load_assembly


def _plate() -> PartSpec:
    return PartSpec(
        "multi_hole_plate",
        "120x80x6",
        {
            "length": 120,
            "width": 80,
            "thickness": 6,
            "hole_d": 9,
            "rows": 2,
            "cols": 3,
        },
    )


def _bolt() -> PartSpec:
    return PartSpec("hex_bolt", "M8x40", {"size": "M8", "length": 40})


def test_bolt_stack_uses_one_plate_and_four_bolts():
    spec = bolt_stack()
    assert spec.name == "bolt_stack"
    assert len(spec.parts) == 2
    assert len(list(spec.instances("M8x40"))) == len(BOLT_HOLES) == 4
    assert len(spec.mates) == 4


def test_predicted_volume_is_the_sum_of_the_instances():
    spec = bolt_stack()
    predicted = spec.predict()
    plate = parts.analytic("multi_hole_plate", spec.parts["120x80x6"].params)
    bolt = parts.analytic("hex_bolt", spec.parts["M8x40"].params)
    assert predicted.volume_mm3 == pytest.approx(
        plate.volume_mm3 + 4 * bolt.volume_mm3
    )


def test_predicted_envelope_is_the_plate_footprint_and_one_bolt_height():
    spec = bolt_stack()
    plate = parts.analytic("multi_hole_plate", spec.parts["120x80x6"].params)
    bolt = parts.analytic("hex_bolt", spec.parts["M8x40"].params)
    predicted = spec.predict()
    # The bolts pass through the plate and hang below it, so the height is one
    # whole bolt (head + shank) and the plate only sets the footprint.
    assert predicted.bbox_mm[0] == pytest.approx(plate.bbox_mm[0])
    assert predicted.bbox_mm[2] == pytest.approx(plate.bbox_mm[2])
    assert predicted.bbox_mm[1] == pytest.approx(bolt.bbox_mm[1])
    assert HEAD_HEIGHT_M8 + 40.0 == pytest.approx(bolt.bbox_mm[1])


def test_every_mate_refers_to_instances_that_exist():
    spec = bolt_stack()
    instances = {p.instance for p in spec.placements}
    for mate in spec.mates:
        assert mate.first in instances
        assert mate.second in instances


def test_distance_mates_are_reported_as_distance_kind():
    spec = bolt_stack()
    assert {mate.kind for mate in spec.mates} == {"distance"}


def test_coincident_mate_has_no_distance():
    assert Mate("a", "b").kind == "coincident"
    assert Mate("a", "b", distance_mm=0.0).kind == "coincident"
    assert Mate("a", "b", distance_mm=5.0).kind == "distance"


def test_validate_rejects_an_unknown_part():
    spec = AssemblySpec(
        name="bad",
        parts={"120x80x6": _plate()},
        placements=[Placement("i-1", "missing")],
    )
    with pytest.raises(ValueError, match="unknown part"):
        spec.validate()


def test_validate_rejects_a_duplicate_instance():
    spec = AssemblySpec(
        name="bad",
        parts={"120x80x6": _plate()},
        placements=[
            Placement("i-1", "120x80x6"),
            Placement("i-1", "120x80x6"),
        ],
    )
    with pytest.raises(ValueError, match="duplicate instance"):
        spec.validate()


def test_validate_rejects_a_self_mate():
    spec = AssemblySpec(
        name="bad",
        parts={"120x80x6": _plate()},
        placements=[Placement("i-1", "120x80x6")],
        mates=[Mate("i-1", "i-1")],
    )
    with pytest.raises(ValueError, match="cannot mate to itself"):
        spec.validate()


def test_validate_rejects_a_mate_to_an_unknown_instance():
    spec = AssemblySpec(
        name="bad",
        parts={"120x80x6": _plate()},
        placements=[Placement("i-1", "120x80x6")],
        mates=[Mate("i-1", "i-2")],
    )
    with pytest.raises(ValueError, match="unknown instance"):
        spec.validate()


def test_validate_rejects_a_part_key_that_differs_from_its_name():
    spec = AssemblySpec(name="bad", parts={"other": _plate()})
    with pytest.raises(ValueError, match="must equal its spec name"):
        spec.validate()


def test_validate_rejects_an_empty_assembly():
    with pytest.raises(ValueError, match="no parts"):
        AssemblySpec(name="empty").validate()


def test_round_trip_through_json(tmp_path):
    spec = bolt_stack()
    path = tmp_path / "stack.json"
    dump_assembly(spec, path)
    again = load_assembly(path)
    assert again.to_dict() == spec.to_dict()
    assert "\u4e0a\u89c6" in path.read_text(encoding="utf-8")


def test_summary_lists_every_instance():
    lines = bolt_stack().summary()
    assert lines[0].startswith("assembly bolt_stack: 5 instances, 4 mates")
    assert sum(1 for line in lines if "M8x40" in line) == 4


def test_placements_are_millimetres_and_plain_dicts():
    placement = Placement("i-1", "p", x_mm=1.0, y_mm=2.0, z_mm=3.0)
    assert placement.to_dict()["x_mm"] == 1.0
    assert Placement.from_dict(placement.to_dict()) == placement


def test_mate_defaults_to_the_top_plane():
    assert Mate("a", "b").plane == "\u4e0a\u89c6\u57fa\u51c6\u9762"


def test_mate_defaults_to_not_flipped():
    assert Mate("a", "b", distance_mm=5.0).flip is False


def test_flip_survives_the_json_round_trip():
    mate = Mate("a", "b", distance_mm=5.0, flip=True)
    assert Mate.from_dict(mate.to_dict()) == mate


def test_bolt_stack_flips_every_mate_to_keep_bolts_above_the_plate():
    # A distance mate constrains magnitude only; without flip the whole stack
    # resolves under the plate and the envelope grows by one head height while
    # the volume stays exactly right.
    spec = bolt_stack()
    assert all(mate.flip for mate in spec.mates)


def test_assembly_spec_is_json_serialisable():
    payload = json.dumps(bolt_stack().to_dict(), ensure_ascii=False)
    assert "bolt_stack" in payload


def test_load_assembly_reads_a_file_that_starts_with_a_bom(tmp_path):
    path = tmp_path / "stack.json"
    payload = json.dumps(bolt_stack().to_dict(), ensure_ascii=False)
    path.write_bytes(b"\xef\xbb\xbf" + payload.encode("utf-8"))
    assert load_assembly(path).name == "bolt_stack", (
        "an assembly spec written from PowerShell carries a BOM; reading it "
        "as plain utf-8 raises Unexpected UTF-8 BOM before any of it is used"
    )
