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


def _validated(params: dict[str, Any]) -> tuple[Any, float]:
    """The head comes from the table, so only the shank length can be wrong.

    length is free-form, but it is still a length: 0 used to answer with the
    head alone and a negative one with a body shorter than the head, and both
    went to SolidWorks as an extrusion of that depth.
    """
    size = catalog.hex_bolt(params["size"])
    length = float(params["length"])
    if length <= 0:
        raise ValueError(f"length must be positive, got {length:g}")
    return size, length


def analytic(params: dict[str, Any]) -> Solid:
    size, length = _validated(params)
    head = hex_prism(size.s, size.k)
    shank = cylinder(size.d, length)
    return head.extend(shank)


def build(model: Any, params: dict[str, Any]) -> None:
    size, length = _validated(params)

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
