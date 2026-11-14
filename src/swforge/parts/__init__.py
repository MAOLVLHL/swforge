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


class ParamError(ValueError):
    """Raised when a builder cannot make sense of the parameters it was handed.

    A JSON file can put any type in any field, so the first thing a builder does
    with a designation -- upper() -- fails with AttributeError when the value is
    a number, and float("M8") fails with ValueError when a length is a word.  To
    the person who wrote the file both mean the same thing: these are not the
    parameters this kind takes.  Naming the kind here is what turns either one
    into a sentence instead of a traceback.
    """


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


def check_kind(kind: str) -> None:
    """Raise KeyError, with the known kinds, when *kind* has no builder.

    Split out so a caller can tell the two KeyErrors apart: an unknown kind is
    this function's message, while a KeyError that escapes the builder is a
    missing parameter.  They need different advice, so they cannot share one
    catch-all.

    A kind that is not a string at all is answered here too: a JSON file can put
    a list where a name belongs, and "kind not in PARTS" would raise TypeError
    (unhashable) instead of the message the caller knows how to report.
    """
    if not isinstance(kind, str) or kind not in PARTS:
        raise KeyError(f"unknown part kind {kind!r}; known: {', '.join(KINDS)}")


def analytic(kind: str, params: dict[str, Any]) -> Solid:
    check_kind(kind)
    filler, _ = PARTS[kind]
    try:
        return filler(params)
    except KeyError as error:
        missing = error.args[0] if error.args else None
        if isinstance(missing, str) and missing.isidentifier():
            raise  # a missing parameter: the caller says which one is needed
        raise ParamError(str(missing)) from None
    except (AttributeError, TypeError) as error:
        raise ParamError(f"{kind} cannot use these parameters: {error}") from None


def build(model: Any, kind: str, params: dict[str, Any]) -> None:
    check_kind(kind)
    _, builder = PARTS[kind]
    try:
        builder(model, params)
    except KeyError as error:
        missing = error.args[0] if error.args else None
        if isinstance(missing, str) and missing.isidentifier():
            raise  # a missing parameter: the caller says which one is needed
        raise ParamError(str(missing)) from None
    except (AttributeError, TypeError) as error:
        raise ParamError(f"{kind} cannot use these parameters: {error}") from None


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
