"""Rectangular plate with a rows x cols grid of clearance holes."""

from __future__ import annotations

import math
from typing import Any

from ..geometry import Solid, plate
from ..params import Param

#: Read by _validated(); a margin of 0 means "pick one from hole_d and thickness".
PARAMS = (
    Param("length"),
    Param("width"),
    Param("thickness"),
    Param("hole_d"),
    Param("rows", required=False, default=2),
    Param("cols", required=False, default=3),
    Param("margin", required=False, default=0.0),
)


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
    _check_holes_fit(values, _layout(values))
    return values


def hole_positions(params: dict[str, Any]) -> list[tuple[float, float]]:
    return _layout(_validated(params))


def _layout(v: dict[str, Any]) -> list[tuple[float, float]]:
    xs = _spread(v["margin"], v["length"] - v["margin"], v["cols"])
    zs = _spread(v["margin"], v["width"] - v["margin"], v["rows"])
    return [(x, z) for z in zs for x in xs]


def _spread(start: float, end: float, count: int) -> list[float]:
    if count == 1:
        return [(start + end) / 2.0]
    step = (end - start) / (count - 1)
    return [start + step * index for index in range(count)]


def _check_holes_fit(v: dict[str, Any], positions: list[tuple[float, float]]) -> None:
    """Refuse a drill pattern SolidWorks cannot cut.

    A hole that reaches past the outline, or into its neighbour, is dropped: the
    sketch keeps the loop, the extrude silently skips it, and the analytic answer
    then promises material the build never removes.  Both cases are arithmetic on
    numbers this module already has, so the check runs before any sketch exists.
    """
    hole_d = v["hole_d"]
    radius = hole_d / 2.0
    length = v["length"]
    width = v["width"]
    for x, z in positions:
        spans = (
            f"it spans {round(x - radius, 3):g} .. {round(x + radius, 3):g} mm in x and "
            f"{round(z - radius, 3):g} .. {round(z + radius, 3):g} mm in z"
        )
        where = f"the {hole_d:g} mm hole at ({round(x, 3):g}, {round(z, 3):g})"
        if (
            x - radius < 0
            or x + radius > length
            or z - radius < 0
            or z + radius > width
        ):
            raise ValueError(
                f"{where} breaks out of the {length:g} x {width:g} mm plate: {spans}"
            )
        # A loop that only touches the outline leaves no wall for the cut to
        # follow, and SolidWorks refuses the extrude rather than cutting it, so
        # landing on the edge is already outside what this plate can drill.
        if (
            x - radius == 0
            or x + radius == length
            or z - radius == 0
            or z + radius == width
        ):
            raise ValueError(
                f"{where} lands on the edge of the {length:g} x {width:g} mm plate: "
                f"{spans}"
            )
    for index, (x0, z0) in enumerate(positions):
        for x1, z1 in positions[index + 1 :]:
            distance = math.hypot(x1 - x0, z1 - z0)
            # Two loops that meet are one slot: SolidWorks keeps both and cuts
            # neither, so a distance equal to the diameter is already too close.
            if distance <= hole_d:
                raise ValueError(
                    f"the {hole_d:g} mm holes at ({round(x0, 3):g}, "
                    f"{round(z0, 3):g}) and ({round(x1, 3):g}, {round(z1, 3):g}) "
                    f"are {round(distance, 3):g} mm apart: at or under their own "
                    f"diameter, so the two loops meet and cut one slot"
                )


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