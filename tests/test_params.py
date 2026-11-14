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
