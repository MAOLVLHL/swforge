import json
import re

import pytest

from swforge.spec import PartSpec, SpecError, dump_specs, load_specs, read_json


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


# -- the input path answers in sentences, not tracebacks --------------------


def test_read_json_reports_a_missing_file_without_the_oserror(tmp_path):
    path = tmp_path / "nope.json"
    with pytest.raises(SpecError) as caught:
        read_json(path, "spec")
    assert str(caught.value) == f"spec file not found: {path}"


def test_read_json_names_the_line_and_column_of_a_syntax_error(tmp_path):
    # The wording of the underlying json error and the column it reports both
    # move between interpreters (3.13 says "Illegal trailing comma" at column
    # 18, 3.10 and 3.12 say "Expecting property name" at column 19), so only
    # the shape of the position is pinned.  What has to be stable is that the
    # user is told where to look.
    path = tmp_path / "trailing.json"
    path.write_text('{"kind": "washer",}', encoding="utf-8")
    with pytest.raises(SpecError) as caught:
        read_json(path, "spec")
    message = str(caught.value)
    assert message.startswith(f"spec file {path} is not valid JSON: ")
    assert re.search(r"\(line 1, column \d+\)$", message), message


def test_read_json_accepts_the_byte_order_mark_notepad_writes(tmp_path):
    # PowerShell's Set-Content and Notepad both prefix UTF-8 with a BOM; calling
    # that file broken is the single most confusing thing a Windows tool can do
    # to a user whose JSON is perfectly valid.
    path = tmp_path / "bom.json"
    path.write_text('{"kind": "washer", "name": "M8"}', encoding="utf-8-sig")
    assert read_json(path, "spec")["kind"] == "washer"


def test_read_json_names_the_file_when_it_cannot_be_read(tmp_path):
    # A directory is the OSError branch a user can actually hit on Windows, by
    # pointing the CLI at the folder instead of the file inside it.
    with pytest.raises(SpecError) as caught:
        read_json(tmp_path, "assembly")
    assert str(caught.value).startswith(f"cannot read assembly file {tmp_path}")


def test_load_specs_says_an_empty_list_has_nothing_to_build(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(SpecError) as caught:
        load_specs(path)
    assert str(caught.value) == f"spec file {path} holds an empty list; nothing to build"


def test_load_specs_says_which_entry_is_not_an_object(tmp_path):
    path = tmp_path / "mixed.json"
    path.write_text(json.dumps([{"kind": "washer", "name": "M8"}, "oops"]), encoding="utf-8")
    with pytest.raises(SpecError) as caught:
        load_specs(path)
    assert str(caught.value) == (
        f"{path}: entry 1 is a str, expected an object with kind and name"
    )


def test_load_specs_names_the_missing_field_and_its_entry(tmp_path):
    path = tmp_path / "noname.json"
    path.write_text(json.dumps({"kind": "washer"}), encoding="utf-8")
    with pytest.raises(SpecError) as caught:
        load_specs(path)
    assert str(caught.value) == f"{path}: entry 0 is missing the 'name' field"


def test_load_specs_rejects_a_tolerance_that_is_not_a_number(tmp_path):
    path = tmp_path / "tol.json"
    path.write_text(
        json.dumps({"kind": "washer", "name": "M8", "tolerance": "fine"}),
        encoding="utf-8",
    )
    with pytest.raises(SpecError) as caught:
        load_specs(path)
    assert str(caught.value).startswith(f"{path}: entry 0 is invalid: ")
