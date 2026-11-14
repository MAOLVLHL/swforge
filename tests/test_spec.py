import json

import pytest

from swforge.spec import PartSpec, dump_specs, load_specs


def test_roundtrip_through_dict():
    spec = PartSpec("hex_bolt", "M8x40", {"size": "M8", "length": 40})
    assert PartSpec.from_dict(spec.to_dict()) == spec


def test_to_json_is_valid_json():
    spec = PartSpec("washer", "M8", {"size": "M8"})
    assert json.loads(spec.to_json())["params"] == {"size": "M8"}


def test_load_specs_accepts_a_single_object(tmp_path):
    path = tmp_path / "one.json"
    path.write_text(json.dumps({"kind": "washer", "name": "M8"}), encoding="utf-8")
    specs = load_specs(path)
    assert len(specs) == 1
    assert specs[0].params == {}


def test_dump_then_load_keeps_order(tmp_path):
    specs = [
        PartSpec("washer", "M6", {"size": "M6"}),
        PartSpec("hex_nut", "M6", {"size": "M6"}),
    ]
    path = tmp_path / "list.json"
    dump_specs(specs, path)
    assert [spec.name for spec in load_specs(path)] == ["M6", "M6"]
    assert [spec.kind for spec in load_specs(path)] == ["washer", "hex_nut"]


def test_default_tolerance_is_one_tenth_of_a_percent():
    assert PartSpec("washer", "M6").tolerance == pytest.approx(0.001)


def test_load_specs_reads_a_file_that_starts_with_a_bom(tmp_path):
    """Windows editors write a BOM by default; json.loads refuses it.

    PowerShell's Set-Content and Out-File, and Notepad's plain "UTF-8" option,
    all prefix the file with EF BB BF.  Reading such a spec as "utf-8" raises
    JSONDecodeError("Unexpected UTF-8 BOM (decode using utf-8-sig)") on a file
    that looks perfectly valid in every editor the user has.
    """
    path = tmp_path / "bom.json"
    path.write_bytes(
        b"\xef\xbb\xbf" + json.dumps({"kind": "washer", "name": "M6"}).encode()
    )
    specs = load_specs(path)
    assert [spec.name for spec in specs] == ["M6"]


def test_dump_specs_writes_without_a_bom(tmp_path):
    """Reading is forgiving, writing stays plain utf-8."""
    path = tmp_path / "clean.json"
    dump_specs([PartSpec("washer", "M6")], path)
    assert not path.read_bytes().startswith(b"\xef\xbb\xbf"), (
        "a BOM this package wrote itself would show up as a diff on every "
        "regeneration and break non-Python readers"
    )
