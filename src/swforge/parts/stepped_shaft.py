"""Three-diameter stepped shaft, machined from bar stock.

Parameters: d1/d2/d3 and l1/l2/l3, millimetres, stacked along -Y.
"""

from __future__ import annotations

from typing import Any

from ..geometry import Solid, cylinder


def _validated(params: dict[str, Any]) -> list[tuple[float, float]]:
    steps = []
    for index in (1, 2, 3):
        d = float(params[f"d{index}"])
        length = float(params[f"l{index}"])
        if d <= 0 or length <= 0:
            raise ValueError(f"step {index} needs a positive diameter and length")
        steps.append((d, length))
    return steps


def analytic(params: dict[str, Any]) -> Solid:
    steps = _validated(params)
    body = cylinder(*steps[0])
    for step in steps[1:]:
        body = body.extend(cylinder(*step))
    return body


def build(model: Any, params: dict[str, Any]) -> None:
    steps = _validated(params)
    start = 0.0
    for index, (diameter, length) in enumerate(steps):
        with model.sketch("top") as sk:
            sk.circle(0.0, 0.0, diameter)
        model.clear_selection()
        model.select_sketch(model.last_sketch)
        model.extrude(length, start_mm=start)
        start -= length
