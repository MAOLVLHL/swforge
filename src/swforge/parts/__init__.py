"""Part builders, keyed by the kind used in a PartSpec.

Each module exposes analytic(params) -> Solid and build(model, params) -> None.
The analytic answer is what the builder is checked against; build() only talks
to SolidWorks.

The kinds themselves live in swforge.kinds, not here: the JSON schema, the
type annotation and the CLI all need the list, and none of them can afford to
import SolidWorks geometry to get it.  This module only has to agree with it,
and refuses to import if it does not.
"""

from __future__ import annotations

from typing import Any, Callable

from ..geometry import Solid
from ..kinds import KINDS, is_standard
from . import (
    flange,
    hex_bolt,
    hex_nut,
    l_bracket,
    multi_hole_plate,
    socket_screw,
    stepped_shaft,
    washer,
)

Analytic = Callable[[dict[str, Any]], Solid]
Builder = Callable[[Any, dict[str, Any]], None]

#: kind -> (module, ) so that the registry and the module list cannot drift.
_MODULES = {
    "hex_bolt": hex_bolt,
    "hex_nut": hex_nut,
    "washer": washer,
    "socket_screw": socket_screw,
    "l_bracket": l_bracket,
    "multi_hole_plate": multi_hole_plate,
    "stepped_shaft": stepped_shaft,
    "flange": flange,
}

PARTS: dict[str, tuple[Analytic, Builder]] = {
    kind: (module.analytic, module.build) for kind, module in _MODULES.items()
}


def _check_registry() -> None:
    """Fail at import time when kinds.py and the builders disagree.

    A kind listed in one place and missing from the other is a silent 500-line
    mismatch: the type annotation promises it, the JSON schema advertises it,
    and the first person to ask for it gets a KeyError from deep inside a
    build.  Cheaper to refuse the import.
    """
    missing = sorted(set(KINDS) - set(PARTS))
    extra = sorted(set(PARTS) - set(KINDS))
    if missing or extra:
        raise RuntimeError(
            "swforge.kinds and swforge.parts disagree: "
            f"no builder for {missing}, no kind for {extra}"
        )


_check_registry()


def analytic(kind: str, params: dict[str, Any]) -> Solid:
    try:
        filler, _ = PARTS[kind]
    except KeyError:
        raise KeyError(f"unknown part kind {kind!r}; known: {', '.join(KINDS)}") from None
    return filler(params)


def build(model: Any, kind: str, params: dict[str, Any]) -> None:
    try:
        _, builder = PARTS[kind]
    except KeyError:
        raise KeyError(f"unknown part kind {kind!r}; known: {', '.join(KINDS)}") from None
    builder(model, params)


def schema() -> list[dict[str, Any]]:
    """What each kind is and needs, without importing SolidWorks.

    The summary is the first line of the builder's own docstring, so the
    documentation of a kind lives next to the geometry that has to honour it
    rather than in a table that goes stale.
    """
    rows = []
    for kind in KINDS:
        module = _MODULES[kind]
        doc = (module.__doc__ or "").strip().splitlines()
        rows.append(
            {
                "kind": kind,
                "standard": is_standard(kind),
                "summary": doc[0].strip() if doc else "",
            }
        )
    return rows
