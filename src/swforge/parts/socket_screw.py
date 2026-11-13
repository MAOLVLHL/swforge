"""GB/T 70.1 hex socket head cap screw.

The hex socket is cut as a prism of the nominal key size to 0.6 * k depth, which
is what the standard calls for and what a real key needs.
"""

from __future__ import annotations

from typing import Any

from .. import catalog
from ..geometry import Solid, cylinder, hex_prism


def analytic(params: dict[str, Any]) -> Solid:
    size = catalog.socket_screw(params["size"])
    length = float(params["length"])
    socket_depth = round(0.6 * size.k, 3)
    head = cylinder(size.dk, size.k)
    shank = cylinder(size.d, length)
    socket = hex_prism(size.socket, socket_depth)
    return head.extend(shank).difference(socket)


def build(model: Any, params: dict[str, Any]) -> None:
    size = catalog.socket_screw(params["size"])
    length = float(params["length"])
    socket_depth = round(0.6 * size.k, 3)

    with model.sketch("top") as sk:
        sk.circle(0.0, 0.0, size.dk)
    model.clear_selection()
    model.select_sketch(model.last_sketch)
    model.extrude(size.k)

    with model.sketch("top") as sk:
        sk.circle(0.0, 0.0, size.d)
    model.clear_selection()
    model.select_sketch(model.last_sketch)
    model.extrude(length, start_mm=-size.k)

    with model.sketch("top") as sk:
        sk.polygon(0.0, 0.0, size.socket)
    model.clear_selection()
    model.select_sketch(model.last_sketch)
    model.cut_blind(socket_depth)
