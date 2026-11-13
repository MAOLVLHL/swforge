"""Part builders, keyed by the kind used in a PartSpec.

Each module exposes analytic(params) -> Solid and build(model, params) -> None.
The analytic answer is what the builder is checked against; build() only talks
to SolidWorks.
"""

from __future__ import annotations

from typing import Any, Callable

from ..geometry import Solid
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

PARTS: dict[str, tuple[Analytic, Builder]] = {
    "hex_bolt": (hex_bolt.analytic, hex_bolt.build),
    "hex_nut": (hex_nut.analytic, hex_nut.build),
    "washer": (washer.analytic, washer.build),
    "socket_screw": (socket_screw.analytic, socket_screw.build),
    "l_bracket": (l_bracket.analytic, l_bracket.build),
    "multi_hole_plate": (multi_hole_plate.analytic, multi_hole_plate.build),
    "stepped_shaft": (stepped_shaft.analytic, stepped_shaft.build),
    "flange": (flange.analytic, flange.build),
}

KINDS = tuple(PARTS)


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
