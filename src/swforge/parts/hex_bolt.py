"""GB/T 5783 hex bolt: hexagonal head plus a plain shank.

The thread is not modelled; see geometry.tap_drill for the reasoning.
"""

from __future__ import annotations

from typing import Any

from .. import catalog
from ..geometry import Solid, cylinder, hex_prism
from ..params import Param

#: Read by analytic() and build(); the shank length is free-form.
PARAMS = (
    Param("size", choices=tuple(catalog.HEX_BOLTS)),
    Param("length"),
)


def analytic(params: dict[str, Any]) -> Solid:
    size = catalog.hex_bolt(params["size"])
    length = float(params["length"])
    head = hex_prism(size.s, size.k)
    shank = cylinder(size.d, length)
    return head.extend(shank)


def build(model: Any, params: dict[str, Any]) -> None:
    size = catalog.hex_bolt(params["size"])
    length = float(params["length"])

    with model.sketch("top") as sk:
        sk.polygon(0.0, 0.0, size.s)
    model.clear_selection()
    model.select_sketch(model.last_sketch)
    model.extrude(size.k)

    with model.sketch("top") as sk:
        sk.circle(0.0, 0.0, size.d)
    model.clear_selection()
    model.select_sketch(model.last_sketch)
    model.extrude(length, start_mm=-size.k)
