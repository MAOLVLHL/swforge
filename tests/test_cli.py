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
