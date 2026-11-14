"""GB/T 6170 hex nut, style 1, with a simplified tapped through hole."""

from __future__ import annotations

from typing import Any

from .. import catalog
from ..geometry import Solid, hex_prism, hole, tap_drill
from ..params import Param

#: Read by analytic() and build(); every dimension comes from the table.
PARAMS = (Param("size", choices=tuple(catalog.HEX_NUTS)),)


def analytic(params: dict[str, Any]) -> Solid:
    size = catalog.hex_nut(params["size"])
    body = hex_prism(size.s, size.m)
    return body.difference(hole(tap_drill(size.d), size.m))


def build(model: Any, params: dict[str, Any]) -> None:
    size = catalog.hex_nut(params["size"])

    # A hexagon with a circle in the same sketch is refused by this SolidWorks
    # build (the circle ends up ignored and the body comes out wrong), so the
    # hole is drilled the way a shop would do it: extrude, then cut through.
    with model.sketch("top") as sk:
        sk.polygon(0.0, 0.0, size.s)
    model.clear_selection()
    model.select_sketch(model.last_sketch)
    model.extrude(size.m)

    with model.sketch("top") as sk:
        sk.circle(0.0, 0.0, tap_drill(size.d))
    model.clear_selection()
    model.select_sketch(model.last_sketch)
    model.cut_through()
