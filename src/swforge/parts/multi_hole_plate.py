"""Rectangular plate with a rows x cols grid of clearance holes."""

from __future__ import annotations

import math
from typing import Any

from ..geometry import Solid, plate


def _validated(params: dict[str, Any]) -> dict[str, Any]:
    values = {
        "length": float(params["length"]),
        "width": float(params["width"]),
        "thickness": float(params["thickness"]),
        "hole_d": float(params["hole_d"]),
        "rows": int(params.get("rows", 2)),
        "cols": int(params.get("cols", 3)),
        "margin": float(params.get("margin", 0.0)),
    }
    for key in ("length", "width", "thickness", "hole_d"):
        if values[key] <= 0:
            raise ValueError(f"{key} must be positive, got {values[key]}")
    if values["rows"] < 1 or values["cols"] < 1:
        raise ValueError("rows and cols must be at least 1")
    if values["margin"] <= 0:
        values["margin"] = max(values["hole_d"], 2 * values["thickness"])
    return values


def hole_positions(params: dict[str, Any]) -> list[tuple[float, float]]:
    v = _validated(params)
    xs = _spread(v["margin"], v["length"] - v["margin"], v["cols"])
    zs = _spread(v["margin"], v["width"] - v["margin"], v["rows"])
    return [(x, z) for z in zs for x in xs]


def _spread(start: float, end: float, count: int) -> list[float]:
    if count == 1:
        return [(start + end) / 2.0]
    step = (end - start) / (count - 1)
    return [start + step * index for index in range(count)]


def analytic(params: dict[str, Any]) -> Solid:
    v = _validated(params)
    body = plate(v["length"], v["width"], v["thickness"])
    holes = len(hole_positions(params))
    removed = math.pi / 4.0 * v["hole_d"] ** 2 * v["thickness"] * holes
    return Solid(body.volume_mm3 - removed, body.bbox_mm)


def build(model: Any, params: dict[str, Any]) -> None:
    v = _validated(params)

    # Every hole is an inner loop of one sketch, so the plate is a single
    # extrude and the hole grid is visible in one place in the model tree.
    with model.sketch("top") as sk:
        sk.rectangle(0.0, 0.0, v["length"], v["width"])
        for x, z in hole_positions(params):
            sk.circle(x, z, v["hole_d"])
    model.clear_selection()
    model.select_sketch(model.last_sketch)
    model.extrude(v["thickness"])
