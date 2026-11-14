"""The canonical list of part kinds, and nothing else.

This module exists so that exactly one place names the kinds.  Three places
used to: the PARTS registry in parts/__init__.py, the PartKind Literal in
spec.py, and two frozensets in spec.py that nothing ever read.  A new part had
to be added to all of them, and forgetting one produced a type annotation that
lied rather than an error.

It imports nothing, so both spec.py (plain data) and parts/ (builders, which
pull in SolidWorks geometry) can depend on it without a cycle or a layering
inversion.
"""

from __future__ import annotations

from typing import Literal

#: Catalogue parts: every dimension comes from a GB table in swforge.catalog.
STANDARD_KINDS: frozenset[str] = frozenset(
    {"hex_bolt", "hex_nut", "washer", "socket_screw"}
)

#: Free-form parts: every dimension comes from the caller.
NON_STANDARD_KINDS: frozenset[str] = frozenset(
    {"l_bracket", "multi_hole_plate", "stepped_shaft", "flange"}
)

#: Every kind, sorted so that error messages and listings are reproducible.
KINDS: tuple[str, ...] = tuple(sorted(STANDARD_KINDS | NON_STANDARD_KINDS))

#: Literal[*KINDS] is 3.11 grammar and this package supports 3.10, so the
#: special form is subscripted with the tuple directly.  It produces the same
#: Literal at runtime -- test_the_literal_is_derived_from_the_tuple pins that --
#: and it is the only spelling that keeps one source of truth on 3.10.
PartKind = Literal.__getitem__(KINDS)


def is_standard(kind: str) -> bool:
    """Whether *kind* takes catalogue dimensions rather than caller dimensions."""
    return kind in STANDARD_KINDS
