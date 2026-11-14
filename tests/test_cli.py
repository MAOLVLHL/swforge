import json
import re

from swforge.cli import main
from swforge.demo import bolt_stack, showcase
from swforge.spec import dump_specs
from swforge.stack import dump_assembly


def test_catalog_prints_the_tables(capsys):
    assert main(["catalog"]) == 0
    assert "GB/T 5783" in capsys.readouterr().out


def test_verify_prints_a_plan_without_solidworks(tmp_path, capsys):
    path = tmp_path / "showcase.json"
    dump_specs(showcase(), path)
    assert main(["verify", str(path)]) == 0
    out = capsys.readouterr().out
    assert "hex_bolt" in out
    assert "bbox=" in out


def test_demo_writes_the_showcase_file(tmp_path):
    target = tmp_path / "showcase.json"
    assert main(["demo", str(target)]) == 0
    specs = json.loads(target.read_text(encoding="utf-8"))
    assert len(specs) == 8

def test_stack_writes_the_assembly_file(tmp_path, capsys):
    target = tmp_path / "bolt_stack.json"
    assert main(["stack", str(target)]) == 0
    assert "assembly bolt_stack: 5 instances, 4 mates" in capsys.readouterr().out
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["name"] == "bolt_stack"
    assert len(payload["placements"]) == 5


def test_verify_assembly_prints_the_prediction(tmp_path, capsys):
    target = tmp_path / "bolt_stack.json"
    dump_assembly(bolt_stack(), target)
    assert main(["verify", str(target), "--assembly"]) == 0
    out = capsys.readouterr().out
    assert "volume" in out
    assert "envelope 120.00x45.30x80.00 mm" in out


def test_assemble_dry_run_does_not_touch_solidworks(tmp_path, capsys):
    target = tmp_path / "bolt_stack.json"
    dump_assembly(bolt_stack(), target)
    assert main(["assemble", str(target), "--dry-run"]) == 0
    assert "bolt-4" in capsys.readouterr().out

def test_one_bad_spec_does_not_stop_the_batch(monkeypatch, tmp_path, capsys):
    from types import SimpleNamespace

    from swforge import cli
    from swforge.session import SwError

    specs = [
        SimpleNamespace(kind="plate", name="a"),
        SimpleNamespace(kind="hex_bolt", name="b"),
        SimpleNamespace(kind="plate", name="c"),
    ]
    seen = []

    def fake_generate(session, spec, out_dir=None, export_step=True):
        seen.append(spec.name)
        if spec.name == "b":
            raise SwError("no drawing template")
        return SimpleNamespace(
            summary=lambda: f"[PASS] {spec.kind}/{spec.name}",
            files={},
            notes=[],
            ok=True,
            bbox_errors={},
        )

    monkeypatch.setattr(cli, "generate", fake_generate)
    failures = cli._build_specs(object(), specs, str(tmp_path), export_step=True)

    assert seen == ["a", "b", "c"], (
        "the spec after the failing one must still be built"
    )
    assert failures == 1
    out = capsys.readouterr().out
    assert "[FAIL] hex_bolt/b: SwError: no drawing template" in out
    assert "[PASS] plate/c" in out
    assert "2/3 parts verified" in out


def test_verbose_sends_stage_events_to_stderr_and_not_to_stdout(tmp_path, capsys):
    """A person watching a five-minute build needs the stages on stderr."""
    import logging

    from swforge.progress import emit

    logger = logging.getLogger("swforge")
    before = list(logger.handlers)
    path = tmp_path / "showcase.json"
    dump_specs(showcase(), path)
    try:
        assert main(["build", str(path), "--dry-run", "-v"]) == 0
        emit(None, "part.building", kind="washer")
        captured = capsys.readouterr()
    finally:
        for handler in list(logger.handlers):
            if handler not in before:
                logger.removeHandler(handler)
        logger.setLevel(logging.NOTSET)

    assert "part.building kind=washer" in captured.err, (
        "progress belongs on stderr so that piping stdout still yields the report"
    )
    assert "part.building" not in captured.out


def test_without_verbose_the_stage_events_stay_silent(tmp_path, capsys):
    import logging

    from swforge.progress import emit

    logger = logging.getLogger("swforge")
    path = tmp_path / "showcase.json"
    dump_specs(showcase(), path)
    assert main(["build", str(path), "--dry-run"]) == 0
    emit(None, "part.building", kind="washer")
    captured = capsys.readouterr()

    assert "part.building" not in captured.err
    assert logger.handlers == [], (
        "a run without -v must not leave a handler attached to the shared logger"
    )


def test_asking_for_verbose_twice_leaves_one_handler(tmp_path, capsys):
    """main() is called again in the same process by tests, notebooks, embedders."""
    import logging

    logger = logging.getLogger("swforge")
    path = tmp_path / "showcase.json"
    dump_specs(showcase(), path)
    try:
        main(["build", str(path), "--dry-run", "-v"])
        main(["build", str(path), "--dry-run", "-v"])
        ours = [h for h in logger.handlers if getattr(h, "_swforge_cli", False)]
    finally:
        for handler in list(logger.handlers):
            if getattr(handler, "_swforge_cli", False):
                logger.removeHandler(handler)
        logger.setLevel(logging.NOTSET)

    assert len(ours) == 1, "two runs must not print every event twice"

def _fake_result(kind, name, ok=True):
    from types import SimpleNamespace

    return SimpleNamespace(
        summary=lambda: f"[PASS] {kind}/{name}",
        files={},
        notes=[],
        ok=ok,
        bbox_errors={},
    )


def test_resume_reuses_a_part_that_is_already_on_disk(monkeypatch, tmp_path, capsys):
    """A rerun after a late failure must not extrude the same eight parts again."""
    from types import SimpleNamespace

    from swforge import cli

    specs = [
        SimpleNamespace(kind="plate", name="a"),
        SimpleNamespace(kind="hex_bolt", name="b"),
    ]
    built, reused = [], []

    def fake_generate(session, spec, out_dir=None, export_step=True):
        built.append(spec.name)
        return _fake_result(spec.kind, spec.name)

    def fake_reuse(session, spec, out_dir=None):
        reused.append(spec.name)
        if spec.name == "a":
            return _fake_result(spec.kind, spec.name)
        return None

    monkeypatch.setattr(cli, "generate", fake_generate)
    monkeypatch.setattr(cli, "reuse_part", fake_reuse)

    failures = cli._build_specs(
        object(), specs, str(tmp_path), export_step=True, resume=True
    )

    assert reused == ["a", "b"], "every spec is checked against the disk first"
    assert built == ["b"], (
        "the part that was found on disk is verified, not rebuilt; the missing "
        "one still gets built"
    )
    assert failures == 0
    out = capsys.readouterr().out
    assert "[PASS] plate/a" in out
    assert "2/2 parts verified" in out


def test_without_resume_every_part_is_built_again(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from swforge import cli

    specs = [SimpleNamespace(kind="plate", name="a")]
    built = []

    def fake_generate(session, spec, out_dir=None, export_step=True):
        built.append(spec.name)
        return _fake_result(spec.kind, spec.name)

    def fake_reuse(session, spec, out_dir=None):
        raise AssertionError("--resume was not asked for")

    monkeypatch.setattr(cli, "generate", fake_generate)
    monkeypatch.setattr(cli, "reuse_part", fake_reuse)

    assert cli._build_specs(object(), specs, str(tmp_path), export_step=True) == 0
    assert built == ["a"]


def test_a_part_that_cannot_be_reused_falls_back_to_building_it(
    monkeypatch, tmp_path, capsys
):
    """A corrupt file on disk is a reason to build, not a reason to stop."""
    from types import SimpleNamespace

    from swforge import cli
    from swforge.session import SwError

    specs = [SimpleNamespace(kind="plate", name="a")]
    built, skipped = [], []

    def fake_generate(session, spec, out_dir=None, export_step=True):
        built.append(spec.name)
        return _fake_result(spec.kind, spec.name)

    def fake_reuse(session, spec, out_dir=None):
        skipped.append(spec.name)
        raise SwError("cannot open a.sldprt (errors=65536)")

    monkeypatch.setattr(cli, "generate", fake_generate)
    monkeypatch.setattr(cli, "reuse_part", fake_reuse)

    failures = cli._build_specs(
        object(), specs, str(tmp_path), export_step=True, resume=True
    )

    assert skipped == ["a"]
    assert built == ["a"], "the fallback is the whole point of a resume flag"
    assert failures == 0
    assert "[PASS] plate/a" in capsys.readouterr().out


def test_assemble_resume_hands_the_measured_parts_to_the_assembly(
    monkeypatch, tmp_path, capsys
):
    from types import SimpleNamespace

    from swforge import cli
    from swforge.demo import bolt_stack
    from swforge.stack import dump_assembly

    spec = bolt_stack()
    target = tmp_path / "bolt_stack.json"
    dump_assembly(spec, target)

    reused_names = []

    def fake_reuse_part(session, part_spec, out_dir=None):
        reused_names.append(part_spec.name)
        return SimpleNamespace(
            summary=lambda: f"[PASS] {part_spec.kind}/{part_spec.name}",
            files={},
            notes=["verified from disk, not rebuilt"],
            ok=True,
            bbox_errors={},
        )

    seen = {}

    def fake_build_assembly(session, assembly, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            summary=lambda: "[PASS] assembly/bolt_stack: 0 mates",
            files={},
            notes=[],
            ok=True,
            mates=[],
        )

    monkeypatch.setattr(cli, "reuse_part", fake_reuse_part)
    monkeypatch.setattr(cli, "build_assembly", fake_build_assembly)
    monkeypatch.setattr(cli, "_attach", lambda: object())

    assert main(["assemble", str(target), "--resume"]) == 0
    names = list(spec.parts)
    assert sorted(reused_names) == sorted(names), "every part in the stack is checked"
    assert set(seen["parts_done"]) == set(names)
    assert f"resumed {len(names)}/{len(names)} parts from disk" in capsys.readouterr().out


def test_assemble_without_resume_rebuilds_the_parts(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from swforge import cli
    from swforge.demo import bolt_stack
    from swforge.stack import dump_assembly

    target = tmp_path / "bolt_stack.json"
    dump_assembly(bolt_stack(), target)

    seen = {}

    def fake_build_assembly(session, assembly, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            summary=lambda: "x", files={}, notes=[], ok=True, mates=[]
        )

    def fake_reuse_part(*args, **kwargs):
        raise AssertionError("--resume was not asked for")

    monkeypatch.setattr(cli, "reuse_part", fake_reuse_part)
    monkeypatch.setattr(cli, "build_assembly", fake_build_assembly)
    monkeypatch.setattr(cli, "_attach", lambda: object())

    assert main(["assemble", str(target)]) == 0
    assert seen["parts_done"] == {}


# -- a bad input file is answered in one sentence, exit 2 -------------------
#
# These are the failures a user actually meets: a path they typed wrong, a file
# they saved from Notepad, a kind they misspelled.  All of them used to arrive
# as a traceback, which says where swforge gave up and nothing about the file.


def test_a_missing_spec_file_is_one_sentence_and_exit_two(tmp_path, capsys):
    path = tmp_path / "nope.json"
    assert main(["build", str(path)]) == 2, "the run never started, so not a build failure"
    captured = capsys.readouterr()
    assert captured.err == f"error: spec file not found: {path}\n"
    assert captured.out == "", "nothing was planned, so nothing is printed to stdout"


def test_a_json_typo_reports_the_line_and_column(tmp_path, capsys):
    path = tmp_path / "trailing.json"
    path.write_text('{"kind": "washer",}', encoding="utf-8")
    assert main(["build", str(path)]) == 2
    err = capsys.readouterr().err
    assert err.startswith(f"error: spec file {path} is not valid JSON: ")
    assert re.search(r"\(line 1, column \d+\)\n$", err), err


def test_a_misspelled_kind_lists_the_kinds_that_exist(tmp_path, capsys):
    path = tmp_path / "typo.json"
    path.write_text('{"kind": "washerr", "name": "M8"}', encoding="utf-8")
    assert main(["build", str(path), "--dry-run"]) == 2
    err = capsys.readouterr().err
    assert "unknown part kind 'washerr'" in err
    assert "known: flange, hex_bolt" in err
    assert "run 'swforge kinds' for the list" in err


def test_a_missing_parameter_names_the_parameter_not_the_kind(tmp_path, capsys):
    # An unknown kind and a missing parameter are both KeyError inside the
    # registry, but they need opposite advice: fix the kind, or add the field.
    path = tmp_path / "nosize.json"
    path.write_text('{"kind": "washer", "name": "nosize"}', encoding="utf-8")
    assert main(["build", str(path), "--dry-run"]) == 2
    err = capsys.readouterr().err
    assert "missing the 'size' parameter" in err
    assert "unknown part kind" not in err


def test_a_spec_file_with_a_bom_still_builds(tmp_path, capsys):
    path = tmp_path / "bom.json"
    path.write_text('{"kind": "washer", "name": "M8", "params": {"size": "M8"}}', encoding="utf-8-sig")
    assert main(["build", str(path), "--dry-run"]) == 0
    assert "washer" in capsys.readouterr().out


def test_an_assembly_that_names_an_unknown_part_is_rejected_before_solidworks(
    tmp_path, capsys
):
    from swforge.demo import bolt_stack

    spec = bolt_stack()
    payload = spec.to_dict()
    payload["placements"][0]["part"] = "ghost"
    path = tmp_path / "ghost.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert main(["assemble", str(path), "--dry-run"]) == 2
    err = capsys.readouterr().err
    assert "refers to unknown part 'ghost'" in err
    assert "known:" in err


# -- a parameter of the wrong type is the same kind of mistake --------------
#
# The section above covers the file: missing, unreadable, not JSON.  These cover
# values that parse fine and are still unusable, which is the harder case -- the
# file is valid JSON, so only the part builder can say what is wrong with it.


def test_a_parameter_of_the_wrong_type_is_one_sentence_not_a_traceback(tmp_path, capsys):
    # A JSON file can put a number where a size belongs.  catalog then calls
    # upper() on it and raises AttributeError, which is neither a SpecError nor
    # anything the person who wrote the file can act on -- so it used to escape
    # main() as a traceback even though the same file with a *missing* size was
    # already answered in one sentence.
    path = tmp_path / "badsize.json"
    path.write_text(
        '{"kind": "washer", "name": "w", "params": {"size": 8}}', encoding="utf-8"
    )
    assert main(["build", str(path), "--dry-run"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: spec 'w': washer cannot use these parameters: "), err
    assert "AttributeError" not in err
    assert "Traceback" not in err


def test_a_size_the_catalogue_does_not_know_is_not_reported_as_missing(tmp_path, capsys):
    # catalog raises KeyError for an unknown designation, the builder raises the
    # same type for a missing parameter, and the two need opposite advice:
    # "pick another size" versus "add the size field".  Telling the user their
    # size is missing when it is present but wrong sends them in circles.
    path = tmp_path / "m7.json"
    path.write_text(
        '{"kind": "hex_bolt", "name": "b", "params": {"size": "M7", "length": 40}}',
        encoding="utf-8",
    )
    assert main(["build", str(path), "--dry-run"]) == 2
    err = capsys.readouterr().err
    assert "'M7' is not in" in err and "known sizes" in err
    assert "missing the" not in err


def test_a_kind_that_is_not_even_a_string_is_still_answered(tmp_path, capsys):
    # "kind not in PARTS" raises TypeError for a list, because a list is
    # unhashable.  That would have escaped main() as a traceback too.
    path = tmp_path / "listkind.json"
    path.write_text('{"kind": ["washer"], "name": "w"}', encoding="utf-8")
    assert main(["build", str(path), "--dry-run"]) == 2
    err = capsys.readouterr().err
    assert "unknown part kind ['washer']" in err
    assert "run 'swforge kinds' for the list" in err


def test_an_assembly_with_an_unusable_parameter_is_rejected_before_solidworks(
    tmp_path, capsys,
):
    # validate() only checks that names line up.  It never reads the parameters,
    # so this stack used to pass the dry run and fail inside SolidWorks.
    from swforge.demo import bolt_stack

    payload = bolt_stack().to_dict()
    for spec in payload["parts"].values():
        if spec["kind"] == "hex_bolt":
            spec["params"]["size"] = 8
    path = tmp_path / "badparam.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert main(["assemble", str(path), "--dry-run"]) == 2
    err = capsys.readouterr().err
    assert err.startswith(f"error: assembly file {path}: hex_bolt cannot use "), err

# -- draw names its views before it opens SolidWorks ------------------------
#
# draw is the one subcommand whose argument is a list of names rather than a
# file, and it used to hand those names straight to a dictionary lookup: a typo
# came out as a KeyError traceback, and an empty flag produced a drawing with no
# views on it and exit code 0.  Both are the kind of mistake the section above
# is about -- the run never got as far as doing anything -- so both are exit 2
# with one sentence on stderr.


def _fake_draw(monkeypatch, seen, files=None):
    from swforge import cli

    monkeypatch.setattr(cli, "_attach", lambda: object())
    monkeypatch.setattr(
        cli,
        "draw",
        lambda session, model, **kwargs: (
            seen.update(kwargs, model=model)
            or files
            or {"drawing": "build/drawing_plate.slddrw", "pdf": "build/drawing_plate.pdf",
                "views": "Drawing View1", "dimensions": "4"}
        ),
    )


def test_draw_prints_the_files_it_wrote(monkeypatch, tmp_path, capsys):
    seen = {}
    _fake_draw(monkeypatch, seen)

    assert main(["draw", str(tmp_path / "plate.sldprt"), "-o", "out"]) == 0

    out = capsys.readouterr().out
    assert "drawing: build/drawing_plate.slddrw" in out
    assert "dimensions: 4" in out
    assert seen["out_dir"] == "out"
    assert seen["dimensions"] is True


def test_draw_passes_the_view_flag_through_whole(monkeypatch, tmp_path):
    # The flag is handed to draw() as typed: splitting and validating it in two
    # places is how the two copies drift, and the check belongs next to the
    # table of names it checks against.
    seen = {}
    _fake_draw(monkeypatch, seen)

    assert main(["draw", str(tmp_path / "plate.sldprt"), "--views", "iso, front"]) == 0
    assert seen["views"] == "iso, front"


def test_no_dimensions_reaches_draw(monkeypatch, tmp_path):
    seen = {}
    _fake_draw(monkeypatch, seen)

    assert main(["draw", str(tmp_path / "p.sldprt"), "--no-dimensions"]) == 0
    assert seen["dimensions"] is False


def test_a_misspelled_view_is_one_sentence_and_exit_two(monkeypatch, tmp_path, capsys):
    # draw itself is not patched: the real one is what rejects the name.  Only
    # the SolidWorks handle is faked, and the model path is a file that does not
    # exist -- so if the check ever moved below open_document, this test would
    # fail with a different error instead of passing.
    from swforge import cli

    monkeypatch.setattr(cli, "_attach", lambda: object())

    path = tmp_path / "plate.sldprt"
    assert main(["draw", str(path), "--views", "frnt"]) == 2
    captured = capsys.readouterr()
    assert captured.err == (
        "error: unknown drawing view 'frnt'; known views: front, top, right, iso\n"
    ), captured.err
    assert captured.out == "", "no file was written, so nothing goes to stdout"


def test_an_empty_view_flag_is_exit_two_not_an_empty_sheet(monkeypatch, tmp_path, capsys):
    from swforge import cli

    monkeypatch.setattr(cli, "_attach", lambda: object())

    path = tmp_path / "plate.sldprt"
    assert main(["draw", str(path), "--views", ""]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: no drawing views to place; pick at least one of "), err


def test_draw_without_solidworks_is_exit_two(monkeypatch, capsys):
    from swforge import cli

    monkeypatch.setattr(cli, "_attach", lambda: None)

    assert main(["draw", "plate.sldprt"]) == 2


