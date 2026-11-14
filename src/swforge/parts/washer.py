"""GB/T 97.1 plain washer, product grade A."""

from __future__ import annotations

from typing import Any

from .. import catalog
from ..geometry import Solid, annulus
from ..params import Param

#: Read by analytic() and build(); every dimension comes from the table.
PARAMS = (Param("size", choices=tuple(catalog.WASHERS)),)


def analytic(params: dict[str, Any]) -> Solid:
    size = catalog.washer(params["size"])
    return annulus(size.outer, size.inner, size.t)


def build(model: Any, params: dict[str, Any]) -> None:
    """One sketch, two loops: the inner circle is a hole, not a second feature.

    A single extrude keeps the model rebuildable and avoids a feature cut,
    which is the operation most sensitive to how the profile is selected.
    """
    size = catalog.washer(params["size"])

    with model.sketch("top") as sk:
        sk.circle(0.0, 0.0, size.outer)
        sk.circle(0.0, 0.0, size.inner)
    model.clear_selection()
    model.select_sketch(model.last_sketch)
    model.extrude(size.t)
