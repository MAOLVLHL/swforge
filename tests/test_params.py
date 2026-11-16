"""The parameter list schema() publishes has to match what builders read."""

import json
from collections.abc import Mapping
from typing import Any

import pytest

from swforge import catalog, parts
from swforge.demo import showcase
from swforge.params import Param

#: The kinds whose size comes from a catalogue table, and that table.
CATALOGUED = {
    "hex_bolt": catalog.HEX_BOLTS,
    "hex_nut": catalog.HEX_NUTS,
    "washer": catalog.WASHERS,
    "socket_screw": catalog.SOCKET_SCREWS,
}


class RecordingDict(Mapping[str, Any]):
    """A params dict that remembers which keys a builder looked up.

    Mapping.get is defined in terms of __getitem__, so one override sees both
    `params["size"]` and `params.get("rows", 2)`.  That matters because the
    builders use both spellings, and a drift test that only understood the
    first would miss an undeclared optional key.
    """

    def __init__(self, values: dict[str, Any]) -> None:
        self._values = dict(values)
        self.reads: list[str] = []

    def __getitem__(self, key: str) -> Any:
        self.reads.append(key)
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


def showcase_params() -> dict[str, dict[str, Any]]:
    return {spec.kind: spec.params for spec in showcase()}


def declared(kind: str) -> tuple[Param, ...]:
    return parts._MODULES[kind].PARAMS


@pytest.mark.parametrize("kind", parts.KINDS)
def test_every_kind_publishes_a_non_empty_parameter_list(kind):
    names = [param.name for param in declared(kind)]
    assert names, "the registry refuses to import a kind with no PARAMS"
    assert len(names) == len(set(names)), (
        "a duplicated name would render as two identical form fields"
    )
    published = next(row for row in parts.schema() if row["kind"] == kind)
    assert [entry["name"] for entry in published["params"]] == names, (
        "schema() has to publish the declaration, not a second copy of it"
    )


@pytest.mark.parametrize("kind", parts.KINDS)
def test_the_declared_parameters_are_the_ones_the_builder_reads(kind):
    recorded = RecordingDict(showcase_params()[kind])
    parts.analytic(kind, recorded)
    assert set(recorded.reads) == {param.name for param in declared(kind)}, (
        "a key the builder reads but does not declare is invisible to anyone "
        "building a form over schema(), and a key nobody reads is a field the "
        "form offers and the builder then ignores"
    )


@pytest.mark.parametrize("kind", parts.KINDS)
def test_a_builder_runs_on_its_required_parameters_alone(kind):
    optional = {param.name for param in declared(kind) if not param.required}
    params = {
        name: value
        for name, value in showcase_params()[kind].items()
        if name not in optional
    }
    solid = parts.analytic(kind, params)
    assert solid.volume_mm3 > 0, (
        "required is the list a form may mark as mandatory; if the builder "
        "needs anything else it gets a KeyError from inside a build"
    )


def outline(kind: str, params: dict[str, Any]) -> tuple[str, Any]:
    """Either ("built", volume) or ("rejected", exception type).

    Some defaults are only meaningful next to another key: falling back to a
    0 mm bolt circle is fine for a plain flange and a ValueError for a drilled
    one.  Recording the rejection instead of letting it escape keeps the
    comparison about the default and not about which fixture happens to be
    valid.
    """
    try:
        return "built", parts.analytic(kind, params).volume_mm3
    except ValueError as exc:
        return "rejected", type(exc)


def test_an_omitted_optional_parameter_matches_its_declared_default():
    checked = 0
    for kind in parts.KINDS:
        params = showcase_params()[kind]
        for param in declared(kind):
            if param.required:
                continue
            with_default = dict(params, **{param.name: param.default})
            without = {
                name: value for name, value in params.items() if name != param.name
            }
            with_ = outline(kind, with_default)
            omit = outline(kind, without)
            same = with_[0] == omit[0] and (
                with_[1] == omit[1]
                if with_[0] == "rejected"
                else with_[1] == pytest.approx(omit[1])
            )
            assert same, (
                f"{kind}.{param.name}: passing the declared default "
                f"{param.default!r} gave {with_}, omitting the key gave {omit}; "
                "the default misdescribes what the builder falls back to"
            )
            checked += 1
    assert checked >= 8, "the builders declare more optional keys than this"


def test_a_declared_choice_list_is_the_catalogue_table():
    for kind, table in CATALOGUED.items():
        size = next(param for param in declared(kind) if param.name == "size")
        assert size.choices == tuple(table), (
            "the size domain is a closed set, and the only home it has is the "
            "table the builder looks the value up in"
        )


def test_a_free_form_parameter_advertises_no_choices():
    length = next(param for param in declared("hex_bolt") if param.name == "length")
    assert length.choices == (), (
        "hex_bolt converts any positive length without a table lookup, so a "
        "non-empty list here would refuse values the builder accepts"
    )


def test_the_schema_rows_survive_a_json_round_trip():
    rows = parts.schema()
    assert json.loads(json.dumps(rows)) == rows, (
        "a tuple left in a row would serialise as a list on the way out and "
        "compare unequal on the way back"
    )

#: One declared key per kind, and the typo a person makes on it: the last letter
#: doubled, which is one keystroke away and still close enough for difflib.
TYPOS = {
    "hex_bolt": "size",
    "hex_nut": "size",
    "washer": "size",
    "socket_screw": "size",
    "l_bracket": "leg_a",
    "multi_hole_plate": "margin",
    "stepped_shaft": "d1",
    "flange": "outer_d",
}


def typo(kind: str) -> tuple[str, str]:
    """The (wrong key, right key) pair used by the two tests below."""
    right = TYPOS[kind]
    return right + right[-1], right


@pytest.mark.parametrize("kind", parts.KINDS)
def test_a_misspelled_key_is_refused_and_the_neighbour_is_suggested(kind):
    """A typo used to fall back to the default, so the volume check agreed.

    Silent default substitution is the one failure a volume comparison cannot
    see: the builder and the analytic answer both read the substituted value
    and report PASS, so a plate drilled with margin 12 instead of 25 verifies.
    """
    wrong, right = typo(kind)
    params = dict(showcase_params()[kind], **{wrong: 1})
    with pytest.raises(parts.ParamError) as excinfo:
        parts.analytic(kind, params)
    message = str(excinfo.value)
    assert repr(wrong) in message, f"{kind}: the message has to name the key typed"
    assert f"did you mean {right!r}" in message, (
        f"{kind}: {wrong!r} is one keystroke from {right!r}, and saying so is the "
        f"whole point of the message; got {message!r}"
    )


@pytest.mark.parametrize("kind", parts.KINDS)
def test_build_refuses_the_same_key_before_it_touches_the_model(kind):
    """A typo must fail before a document exists, not halfway through a build."""
    wrong, _ = typo(kind)
    params = dict(showcase_params()[kind], **{wrong: 1})

    class Untouchable:
        def __getattr__(self, name):
            raise AssertionError(f"build() reached the model before validating: {name}")

    with pytest.raises(parts.ParamError):
        parts.build(Untouchable(), kind, params)


def test_the_message_lists_every_unknown_key_and_the_whole_declaration():
    params = {
        "length": 120,
        "width": 80,
        "thickness": 6,
        "hole_d": 9,
        "margine": 25,
        "colour": "red",
    }
    with pytest.raises(parts.ParamError) as excinfo:
        parts.analytic("multi_hole_plate", params)
    message = str(excinfo.value)
    assert "'colour'" in message and "'margine'" in message, (
        "one round trip should report every typo, not just the first"
    )
    for name in ("length", "width", "thickness", "hole_d", "rows", "cols", "margin"):
        assert name in message, f"the message has to say what the kind does take: {name}"


def test_a_key_with_no_neighbours_is_reported_without_a_guess():
    with pytest.raises(parts.ParamError) as excinfo:
        parts.analytic("hex_nut", {"size": "M8", "zzzzzzzzzz": 1})
    message = str(excinfo.value)
    assert "'zzzzzzzzzz'" in message
    assert "did you mean" not in message, (
        "a suggestion this far from every declared key would be noise"
    )


def test_every_declared_key_is_still_accepted():
    """The guard must not reject a key a builder really reads."""
    for kind in parts.KINDS:
        assert parts.analytic(kind, dict(showcase_params()[kind])).volume_mm3 > 0


def test_a_key_that_only_differs_in_case_is_still_unknown():
    """The builders index with the exact spelling, so a case slip is a typo.

    Accepting it in the guard would move the failure one frame down, where it
    reads as a missing parameter -- the opposite of what went wrong.
    """
    with pytest.raises(parts.ParamError) as excinfo:
        parts.analytic("hex_nut", {"Size": "M8"})
    message = str(excinfo.value)
    assert "'Size'" in message, message
    assert "did you mean 'size'" in message, message


def test_the_old_l_bracket_key_is_refused_with_the_new_name_as_the_suggestion():
    """holes_in_long_leg replaced holes_per_leg; the guard turns the old key into
    a message that names the replacement, so a spec written before the rename is
    fixed in one round trip rather than silently drilling what it did not ask for.
    """
    params = {
        "leg_a": 60,
        "leg_b": 40,
        "width": 40,
        "thickness": 5,
        "hole_d": 9,
        "holes_per_leg": 2,
    }
    with pytest.raises(parts.ParamError) as excinfo:
        parts.analytic("l_bracket", params)
    message = str(excinfo.value)
    assert "did you mean 'holes_in_long_leg'" in message, message
    assert "short_leg_holes" in message, (
        "the message lists the whole declaration, which now names both hole keys"
    )


def test_the_l_bracket_schema_names_the_leg_each_hole_key_belongs_to():
    row = next(row for row in parts.schema() if row["kind"] == "l_bracket")
    names = [entry["name"] for entry in row["params"]]
    assert "holes_in_long_leg" in names and "short_leg_holes" in names, names
    assert "holes_per_leg" not in names, (
        "a key that names neither leg is what let the builder drill one and claim both"
    )
    solid = next(entry for entry in row["params"] if entry["name"] == "short_leg_holes")
    assert solid["default"] == 0, (
        "the default has to be the value the builder accepts, not the one it refuses"
    )


def test_l_bracket_refuses_short_leg_holes_before_it_touches_the_model():
    class Untouchable:
        def __getattr__(self, name):
            raise AssertionError(f"build() reached the model first: {name}")

    params = {
        "leg_a": 60,
        "leg_b": 40,
        "width": 40,
        "thickness": 5,
        "short_leg_holes": 2,
    }
    with pytest.raises(ValueError) as excinfo:
        parts.build(Untouchable(), "l_bracket", params)
    assert "modelled solid" in str(excinfo.value)

