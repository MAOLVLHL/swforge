"""Stage events: both channels, and neither of them writes to stdout."""

import logging

import pytest

from swforge.progress import emit


def test_the_callback_gets_the_stage_and_its_numbers():
    seen = []
    emit(lambda stage, payload: seen.append((stage, payload)), "part.built",
         kind="washer", volume_mm3=1234.5)

    assert len(seen) == 1, "one emit is one call, not one call per keyword"
    stage, payload = seen[0]
    assert stage == "part.built"
    assert payload == {"kind": "washer", "volume_mm3": 1234.5}


def test_a_callback_that_raises_cannot_destroy_the_build_it_decorates():
    def boom(stage, payload):
        raise RuntimeError("the progress bar is broken")

    emit(boom, "part.building", kind="washer")  # must not propagate


def test_a_broken_callback_is_logged_so_it_is_not_silently_lost(caplog):
    def boom(stage, payload):
        raise RuntimeError("the progress bar is broken")

    with caplog.at_level(logging.WARNING, logger="swforge"):
        emit(boom, "part.mating")

    assert "progress callback failed at part.mating" in caplog.text
    assert any(record.exc_info for record in caplog.records), (
        "a swallowed traceback still has to be readable"
    )


def test_nothing_is_printed_or_logged_when_nobody_asked(capsys, caplog):
    caplog.set_level(logging.WARNING, logger="swforge")
    emit(None, "assembly.saving", name="bracket")

    assert capsys.readouterr().out == "", "a library that prints hijacks the caller TTY"
    assert not [r for r in caplog.records if r.levelno == logging.INFO], (
        "the INFO line is opt-in: a caller that never enabled it gets silence"
    )


def test_the_info_line_carries_every_field_when_the_logger_is_enabled(caplog):
    with caplog.at_level(logging.INFO, logger="swforge"):
        emit(None, "part.saved", kind="washer", files=2)

    assert "part.saved kind=washer files=2" in caplog.text


def test_the_library_never_installs_a_handler():
    logger = logging.getLogger("swforge")
    assert logger.propagate, (
        "the app decides where the records go; a library handler fights it"
    )


def test_a_positional_stage_keeps_keywords_free_for_the_payload():
    seen = []
    with pytest.raises(TypeError):
        emit(seen.append, stage="part.built")
    assert seen == []


def _fake_part_build(monkeypatch, *, measured=1234.5, expected=1234.5, bbox=(20.0, 20.0, 2.0)):
    """Make generate() run without SolidWorks and hand back a session and a spec."""
    from types import SimpleNamespace

    import swforge.generate as gen

    class Model:
        def measure(self):
            return SimpleNamespace(volume_mm3=measured)

        def bbox_mm(self):
            return bbox

        def save(self, path):
            return path

        def export_step(self, path):
            return path

        def close(self):
            pass

    class Session:
        def new_part(self):
            return Model()

    spec = SimpleNamespace(
        kind="washer",
        name="washer_M8",
        params={},
        tolerance=0.01,
        validate=lambda: None,
    )
    monkeypatch.setattr(gen.parts, "build", lambda model, kind, params: None)
    monkeypatch.setattr(
        gen.parts,
        "analytic",
        lambda kind, params: SimpleNamespace(volume_mm3=expected, bbox_mm=bbox),
    )
    return Session(), spec


def test_a_part_build_reports_building_then_built_then_saved(monkeypatch):
    session, spec = _fake_part_build(monkeypatch)
    from swforge.generate import generate

    seen = []
    result = generate(
        session, spec, out_dir="build", on_progress=lambda s, p: seen.append((s, p))
    )

    assert result.ok
    assert [stage for stage, _ in seen] == ["part.building", "part.built", "part.saved"]
    assert seen[0][1] == {"kind": "washer", "name": "washer_M8"}
    assert seen[1][1]["volume_mm3"] == 1234.5
    assert seen[1][1]["ok"] is True
    assert seen[2][1] == {"kind": "washer", "name": "washer_M8", "files": 2}


def test_a_part_that_fails_to_verify_is_reported_as_not_ok(monkeypatch):
    """The caller learns the verdict from the event, not by re-measuring."""
    session, spec = _fake_part_build(monkeypatch, measured=9999.0)
    from swforge.generate import generate

    seen = []
    result = generate(
        session, spec, out_dir="build", on_progress=lambda s, p: seen.append((s, p))
    )

    assert not result.ok
    built = [payload for stage, payload in seen if stage == "part.built"][0]
    assert built["ok"] is False, (
        "a wrong volume is the one thing a watcher wants to hear about early"
    )
