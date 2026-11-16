"""L-shaped angle bracket cut from plate thickness T.

Parameters (all millimetres):
    leg_a   length of the long leg, along X
    leg_b   height of the short leg, along Y
    width   width of both legs, along Z
    thickness  plate thickness
    hole_d  clearance hole diameter, 0 disables drilling
    holes_in_long_leg  holes through the long leg, centred on its width
    short_leg_holes  must be 0: the short leg is modelled solid

The short leg has no holes. Drilling it means cutting across the plate
thickness, i.e. along X, and every feature this builder draws starts from a
top-plane profile extruded along Y; the cut it would need is a second
direction, not a second sketch. short_leg_holes therefore exists only to
refuse the request with that reason instead of shipping half a bracket that
measures correct, because analytic and build leave the same holes out and
volume plus box cannot see the missing holes.

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
    Param("holes_in_long_leg", required=False, default=2),
    Param("short_leg_holes", required=False, default=0),
)


def _validated(params: dict[str, Any]) -> dict[str, float]:
    values = {
        "leg_a": float(params["leg_a"]),
        "leg_b": float(params["leg_b"]),
        "width": float(params["width"]),
        "thickness": float(params["thickness"]),
        "hole_d": float(params.get("hole_d", 0.0)),
        "holes_in_long_leg": int(params.get("holes_in_long_leg", 2)),
        "short_leg_holes": int(params.get("short_leg_holes", 0)),
    }
    for key in ("leg_a", "leg_b", "width", "thickness"):
        if values[key] <= 0:
            raise ValueError(f"{key} must be positive, got {values[key]}")
    if values["thickness"] >= min(values["leg_a"], values["leg_b"]):
        raise ValueError("thickness must be smaller than both legs")
    if values["hole_d"] < 0:
        raise ValueError(f"hole_d must not be negative, got {values['hole_d']}")
    if values["hole_d"] and values["hole_d"] >= 0.8 * values["width"]:
        raise ValueError("hole_d is too large for the bracket width")
    if values["hole_d"] and values["holes_in_long_leg"] < 1:
        raise ValueError(
            f"holes_in_long_leg must be at least 1, got {values['holes_in_long_leg']}; "
            "use hole_d 0 to leave the leg solid"
        )
    if values["short_leg_holes"]:
        raise ValueError(
            "the short leg is modelled solid: its holes would be cut along X, "
            "and this builder only extrudes top-plane profiles along Y; "
            "short_leg_holes must be 0"
        )
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
            body.volume_mm3 - one_hole * v["holes_in_long_leg"], body.bbox_mm
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
    """Evenly spaced holes along the long leg, a plate thickness in from it."""
    count = int(v["holes_in_long_leg"])
    t = v["thickness"]
    points: list[tuple[float, float]] = []
    for index in range(count):
        x = t + (v["leg_a"] - 2 * t) * (index + 0.5) / count
        points.append((x, v["width"] / 2.0))
    return points
