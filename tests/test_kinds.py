"""One list of part kinds, and every other list has to agree with it."""

from typing import get_args

from swforge import kinds, parts
from swforge.kinds import KINDS, NON_STANDARD_KINDS, STANDARD_KINDS, is_standard


def test_the_kinds_are_sorted_and_unique():
    assert list(KINDS) == sorted(set(KINDS)), (
        "error messages and the schema listing iterate this tuple, so an "
        "unsorted or duplicated entry makes them unstable"
    )


def test_the_literal_is_derived_from_the_tuple():
    assert get_args(kinds.PartKind) == KINDS, (
        "the annotation used to be hand-copied, so it could promise a kind "
        "that no builder answered"
    )


def test_the_two_families_partition_every_kind():
    assert STANDARD_KINDS | NON_STANDARD_KINDS == set(KINDS)
    assert STANDARD_KINDS & NON_STANDARD_KINDS == set(), (
        "a kind is either from a GB table or from the caller, never both"
    )


def test_is_standard_answers_for_every_kind():
    for kind in KINDS:
        assert is_standard(kind) is (kind in STANDARD_KINDS)
    assert not is_standard("gizmo"), "an unknown kind is not standard, it is unknown"


def test_every_kind_has_a_builder():
    assert set(parts.PARTS) == set(KINDS), (
        "a kind without a builder is a KeyError for the first user, and the "
        "registry refuses to import when the two lists disagree"
    )


def test_the_schema_lists_every_kind_with_its_own_docstring():
    rows = parts.schema()
    assert [row["kind"] for row in rows] == list(KINDS)
    for row in rows:
        module = parts._MODULES[row["kind"]]
        assert row["summary"] == module.__doc__.strip().splitlines()[0], (
            "the schema quotes the builder module so that the two cannot drift"
        )
        assert row["standard"] is is_standard(row["kind"])


def test_the_schema_covers_both_families():
    flags = {row["kind"]: row["standard"] for row in parts.schema()}
    assert sum(flags.values()) == len(STANDARD_KINDS)
    assert sum(not value for value in flags.values()) == len(NON_STANDARD_KINDS)
