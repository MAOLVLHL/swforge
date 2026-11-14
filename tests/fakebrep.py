"""A SolidWorks stand-in that records what a part builder asks it to draw.

The builders in :mod:`swforge.parts.*` touch a small slice of :class:`SwModel`:
``sketch()``, ``clear_selection()``, ``select_sketch()``, ``last_sketch``, ``extrude()``,
``cut_blind()`` and ``cut_through()``.  Recording those calls is enough to read the
builder's intent back -- how many sketches it opens, which loops each one carries
and in what order, and how each is extruded or cut -- on a host that has never
had SolidWorks installed.

The recording is also replayable: signed loop areas times extrusion depth, minus
the cuts, gives the volume the builder just asked for.  That is what makes the
check in tests/test_part_builds.py worth more than a golden call log: a builder
that sketches the right circles but extrudes the wrong depth produces a number
that no longer matches the closed-form answer in ``swforge.geometry``.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from contextlib import contextmanager

#: Loops after the first one in a sketch are holes: that is the convention the
#: builders rely on, and the one SolidWorks itself applies to an inner profile.
FIRST_LOOP_IS_MATERIAL = True


class Loop:
    """One closed profile in a sketch, in sketch-plane millimetres."""

    __slots__ = ("args", "shape")

    def __init__(self, shape: str, *args: float) -> None:
        self.shape = shape
        self.args = tuple(float(value) for value in args)

    @property
    def area(self) -> float:
        if self.shape == "circle":
            _, _, diameter = self.args
            return math.pi / 4.0 * diameter**2
        if self.shape == "polygon":
            _, _, across_flats, sides = self.args
            count = int(sides)
            # CreatePolygon takes the circumradius; a hexagon's across-flats
            # distance is sqrt(3) * r, which is the conversion the Sketch class
            # applies before the call.
            radius = (
                across_flats / math.sqrt(3.0) if count == 6 else across_flats / 2.0
            )
            return count / 2.0 * radius**2 * math.sin(2.0 * math.pi / count)
        if self.shape == "rectangle":
            x0, z0, x1, z1 = self.args
            return abs(x1 - x0) * abs(z1 - z0)
        raise AssertionError(f"unknown loop shape {self.shape!r}")

    def __repr__(self) -> str:
        joined = ", ".join(f"{value:g}" for value in self.args)
        return f"{self.shape}({joined})"


class RecordingSketch:
    """The open sketch: every entity the builder adds, in order."""

    def __init__(self, plane: str) -> None:
        self.plane = plane
        self.loops: list[Loop] = []

    def circle(self, x_mm: float, z_mm: float, diameter_mm: float) -> Loop:
        loop = Loop("circle", x_mm, z_mm, diameter_mm)
        self.loops.append(loop)
        return loop

    def polygon(
        self, x_mm: float, z_mm: float, across_flats_mm: float, sides: int = 6
    ) -> Loop:
        loop = Loop("polygon", x_mm, z_mm, across_flats_mm, sides)
        self.loops.append(loop)
        return loop

    def rectangle(
        self, x0_mm: float, z0_mm: float, x1_mm: float, z1_mm: float
    ) -> Loop:
        loop = Loop("rectangle", x0_mm, z0_mm, x1_mm, z1_mm)
        self.loops.append(loop)
        return loop

    @property
    def area(self) -> float:
        """Profile area: the first loop is material, the rest are holes."""
        if not self.loops:
            return 0.0
        material = self.loops[0].area
        holes = sum(loop.area for loop in self.loops[1:])
        return material - holes

    def __repr__(self) -> str:
        return f"sketch({self.plane}: {', '.join(map(repr, self.loops))})"


class Feature:
    """One extrude or cut, and the sketch it was applied to."""

    __slots__ = ("depth", "op", "sketch", "start")

    def __init__(self, op: str, depth: float, start: float, sketch: int) -> None:
        self.op = op
        self.depth = depth
        self.start = start
        self.sketch = sketch

    def __repr__(self) -> str:
        return f"{self.op}(depth={self.depth:g}, start={self.start:g})"


class RecordingModel:
    """A SwModel that writes down the build instead of talking to COM."""

    def __init__(self) -> None:
        self.sketches: list[RecordingSketch] = []
        self.features: list[Feature] = []
        self.selected: list[str] = []
        #: Every profile ever selected, in order; unlike *selected* this is not
        #: cleared, so a test can count selections against features drawn.
        self.selections: list[str] = []
        self.last_sketch = ""

    # -- sketching --------------------------------------------------------
    @contextmanager
    def sketch(self, plane: str = "top") -> Iterator[RecordingSketch]:
        # SwModel.sketch() clears the selection before it picks the plane; the
        # recorder does the same so a builder cannot inherit a stale profile.
        self.clear_selection()
        sketch = RecordingSketch(plane)
        self.sketches.append(sketch)
        self.last_sketch = f"Sketch{len(self.sketches)}"
        yield sketch

    # -- selection --------------------------------------------------------
    def clear_selection(self) -> None:
        self.selected.clear()

    def select_sketch(self, name: str | None = None) -> str:
        name = name or self.last_sketch
        if self.selected:
            raise AssertionError(
                f"select_sketch({name!r}) grew a selection to {len(self.selected) + 1}: "
                "call clear_selection() first"
            )
        if name != self.last_sketch:
            raise AssertionError(
                f"select_sketch({name!r}) does not name the sketch just drawn "
                f"({self.last_sketch!r})"
            )
        self.selected.append(name)
        self.selections.append(name)
        return name

    def _claim(self, what: str) -> int:
        if len(self.selected) != 1:
            raise AssertionError(
                f"{what} wants exactly one selected profile, "
                f"got {len(self.selected)}: {self.selected}"
            )
        index = self.selected[-1]
        return int(index.removeprefix("Sketch")) - 1

    # -- features ---------------------------------------------------------
    def extrude(
        self, depth_mm: float, start_mm: float = 0.0, reverse: bool = True
    ) -> str:
        if reverse is not True:
            raise AssertionError("every builder extrudes along -Y")
        index = self._claim(f"extrude of {depth_mm} mm")
        self.features.append(Feature("extrude", float(depth_mm), float(start_mm), index))
        return f"Boss-Extrude{len(self.features)}"

    def cut_blind(self, depth_mm: float, flip: bool = False) -> str:
        index = self._claim(f"blind cut of {depth_mm} mm")
        self.features.append(Feature("cut_blind", float(depth_mm), 0.0, index))
        return f"Cut-Extrude{len(self.features)}"

    def cut_through(self, flip: bool = False) -> str:
        index = self._claim("through-all cut")
        self.features.append(Feature("cut_through", 0.0, 0.0, index))
        return f"Cut-Extrude{len(self.features)}"

    # -- replay -----------------------------------------------------------
    def volume_mm3(self, overlap_mm3: float = 0.0) -> float:
        """The material this script adds, minus what it cuts away.

        Extrusions are summed as separate bodies.  Two of them that share a
        region are not a union yet -- SolidWorks merges the second body into the
        first, and this replay does not -- so a builder whose legs overlap has to
        pass that overlap in for the comparison to mean anything.
        """
        top = 0.0
        bottom = 0.0
        volume = 0.0
        for feature in self.features:
            area = self.sketches[feature.sketch].area
            if feature.op == "extrude":
                volume += area * feature.depth
                top = max(top, feature.start)
                bottom = min(bottom, feature.start - feature.depth)
            elif feature.op == "cut_blind":
                volume -= area * feature.depth
            else:
                volume -= area * (top - bottom)
        return volume - overlap_mm3

    def __repr__(self) -> str:
        parts = [repr(sketch) for sketch in self.sketches]
        parts.extend(repr(feature) for feature in self.features)
        return " -> ".join(parts)
