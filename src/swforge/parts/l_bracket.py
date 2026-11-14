"""L-shaped angle bracket cut from plate thickness T.

Parameters (all millimetres):
    leg_a   length of the long leg, along X
    leg_b   height of the short leg, along Y
    width   width of both legs, along Z
    thickness  plate thickness
    hole_d  clearance hole diameter, 0 disables drilling
    holes_per_leg  holes through the long leg, centred on its width

The short leg is modelled solid: its holes are drilled across the plate
thickness, i.e. along X, which a single top-plane extrusion cannot express.
The long leg carries the full hole pattern the parameters ask for.

The two legs share the corner block T x W x T, which is counted once only.
"""

from __future__ import annotations

import math
from typing import Any

from ..geometry import Solid, plate
from ..params import Param

#: Read by _validated(); hole_d of 0 disables drilling, so it may be omitted.
PARAMS = (
    Param("leg_a"),
    Param("leg_b"),
    Param("width"),
    Param("thickness"),
    Param("hole_d", required=False, default=0.0),
    Param("holes_per_leg", required=False, default=2),
)


def _validated(params: dict[str, Any]) -> dict[str, float]:
    values = {
        "leg_a": float(params["leg_a"]),
        "leg_b": float(params["leg_b"]),
        "width": float(params["width"]),
        "thickness": float(params["thickness"]),
        "hole_d": float(params.get("hole_d", 0.0)),
        "holes_per_leg": int(params.get("holes_per_leg", 2)),
    }
    for key in ("leg_a", "leg_b", "width", "thickness"):
        if values[key] <= 0:
            raise ValueError(f"{key} must be positive, got {values[key]}")
    if values["thickness"] >= min(values["leg_a"], values["leg_b"]):
        raise ValueError("thickness must be smaller than both legs")
    if values["hole_d"] and values["hole_d"] >= 0.8 * values["width"]:
        raise ValueError("hole_d is too large for the bracket width")
    return values


def analytic(params: dict[str, Any]) -> Solid:
    v = _validated(params)
    long_leg = plate(v["leg_a"], v["width"], v["thickness"])
    short_leg = plate(v["thickness"], v["width"], v["leg_b"])
    corner = plate(v["thickness"], v["width"], v["thickness"])
    body = Solid(
        long_leg.volume_mm3 + short_leg.volume_mm3 - corner.volume_mm3,
        (
            max(v["leg_a"], v["thickness"]),
            max(v["thickness"], v["leg_b"]),
            v["width"],
        ),
    )
    if v["hole_d"]:
        one_hole = math.pi / 4.0 * v["hole_d"] ** 2 * v["thickness"]
        body = Solid(
            body.volume_mm3 - one_hole * v["holes_per_leg"], body.bbox_mm
        )
    return body


def build(model: Any, params: dict[str, Any]) -> None:
    v = _validated(params)
    t = v["thickness"]

    holes = _hole_positions(v) if v["hole_d"] else []
    with model.sketch("top") as sk:
        sk.rectangle(0.0, 0.0, v["leg_a"], v["width"])
        for x, z in holes:
            sk.circle(x, z, v["hole_d"])
    model.clear_selection()
    model.select_sketch(model.last_sketch)
    model.extrude(t)

    with model.sketch("top") as sk:
        sk.rectangle(0.0, 0.0, t, v["width"])
    model.clear_selection()
    model.select_sketch(model.last_sketch)
    model.extrude(v["leg_b"])


def _hole_positions(v: dict[str, float]) -> list[tuple[float, float]]:
    """Evenly spaced holes along each leg, a plate thickness in from the edge."""
    count = int(v["holes_per_leg"])
    t = v["thickness"]
    points: list[tuple[float, float]] = []
    for index in range(count):
        x = t + (v["leg_a"] - 2 * t) * (index + 0.5) / count
        points.append((x, v["width"] / 2.0))
    return points
