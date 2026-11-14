"""Bolted flange: disc, hub, through bore and a bolt circle.

Parameters: outer diameter, hub diameter, plate thickness, hub height, bore
diameter, bolt hole diameter and bolt count.
"""

from __future__ import annotations

import math
from typing import Any

from ..geometry import Solid, annulus, cylinder
from ..params import Param

#: Read by _validated(); the bolt circle may be omitted for a plain flange.
PARAMS = (
    Param("outer_d"),
    Param("hub_d"),
    Param("plate_t"),
    Param("hub_h"),
    Param("bore_d"),
    Param("bolt_d", required=False, default=0.0),
    Param("bolt_count", required=False, default=4),
    Param("bolt_circle_d", required=False, default=0.0),
)


def _validated(params: dict[str, Any]) -> dict[str, float]:
    v = {
        "outer_d": float(params["outer_d"]),
        "hub_d": float(params["hub_d"]),
        "plate_t": float(params["plate_t"]),
        "hub_h": float(params["hub_h"]),
        "bore_d": float(params["bore_d"]),
        "bolt_d": float(params.get("bolt_d", 0.0)),
        "bolt_count": int(params.get("bolt_count", 4)),
        "bolt_circle_d": float(params.get("bolt_circle_d", 0.0)),
    }
    if v["bore_d"] >= min(v["outer_d"], v["hub_d"]):
        raise ValueError("bore must be smaller than the flange and hub")
    if v["hub_d"] > v["outer_d"]:
        raise ValueError("hub cannot be larger than the flange")
    if v["bolt_d"] and not (v["bore_d"] < v["bolt_circle_d"] < v["outer_d"]):
        raise ValueError("bolt circle must sit between the bore and the rim")
    return v


def bolt_positions(params: dict[str, Any]) -> list[tuple[float, float]]:
    v = _validated(params)
    if not v["bolt_d"]:
        return []
    radius = v["bolt_circle_d"] / 2.0
    return [
        (
            radius * math.cos(2 * math.pi * index / v["bolt_count"]),
            radius * math.sin(2 * math.pi * index / v["bolt_count"]),
        )
        for index in range(int(v["bolt_count"]))
    ]


def analytic(params: dict[str, Any]) -> Solid:
    v = _validated(params)
    plate = annulus(v["outer_d"], v["bore_d"], v["plate_t"])
    hub = annulus(v["hub_d"], v["bore_d"], v["hub_h"])
    holes = 0.0
    if v["bolt_d"]:
        holes = (
            math.pi
            / 4.0
            * v["bolt_d"] ** 2
            * v["plate_t"]
            * int(v["bolt_count"])
        )
    body = plate.extend(hub)
    return Solid(body.volume_mm3 - holes, body.bbox_mm)


def build(model: Any, params: dict[str, Any]) -> None:
    v = _validated(params)

    # Plate: rim, bore and bolt circle as loops of one sketch.  Hub: a second
    # annular extrude stacked on top, so the bore runs straight through both
    # without a single cut feature.
    with model.sketch("top") as sk:
        sk.circle(0.0, 0.0, v["outer_d"])
        sk.circle(0.0, 0.0, v["bore_d"])
        for x, z in bolt_positions(params):
            sk.circle(x, z, v["bolt_d"])
    model.clear_selection()
    model.select_sketch(model.last_sketch)
    model.extrude(v["plate_t"])

    with model.sketch("top") as sk:
        sk.circle(0.0, 0.0, v["hub_d"])
        sk.circle(0.0, 0.0, v["bore_d"])
    model.clear_selection()
    model.select_sketch(model.last_sketch)
    model.extrude(v["hub_h"], start_mm=-v["plate_t"])
