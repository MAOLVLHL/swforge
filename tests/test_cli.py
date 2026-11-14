import json

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
