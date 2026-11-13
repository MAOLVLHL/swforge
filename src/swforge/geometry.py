"""Analytic geometry used to verify what SolidWorks actually built.

Every part is described twice: once analytically (pure Python, no SolidWorks)
and once as a sequence of SolidWorks features.  The two must agree, otherwise
the build is rejected.  That is the whole point of the library: a model is only
trusted after its mass properties match the closed-form answer.

Coordinate convention
---------------------
Parts are modelled with their axis along **-Y**: the profile sketch lives on the
Top plane (XZ) and :meth:`extrude` pulls material towards -Y.  A bounding box is
therefore reported as `(x, y, z)` in millimetres, where `y` is the length along
the part axis.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

SQRT3 = math.sqrt(3.0)


@dataclass(frozen=True)
class Solid:
    """A volume plus its axis-aligned bounding-box size, both in millimetres."""

    volume_mm3: float
    bbox_mm: tuple[float, float, float]

    def union(self, other: "Solid") -> "Solid":
        """Fuse two solids that share the same axis (volumes add, boxes merge)."""
        return Solid(
            self.volume_mm3 + other.volume_mm3,
            tuple(max(a, b) for a, b in zip(self.bbox_mm, other.bbox_mm)),
        )

    def extend(self, other: "Solid") -> "Solid":
        """Stack a second segment below this one along -Y.

        The bounding box grows along the part axis and stays the max of the two
        profiles in the other two directions, which is exactly how the builders
        stack extrusions.
        """
        return Solid(
            self.volume_mm3 + other.volume_mm3,
            (
                max(self.bbox_mm[0], other.bbox_mm[0]),
                self.bbox_mm[1] + other.bbox_mm[1],
                max(self.bbox_mm[2], other.bbox_mm[2]),
            ),
        )

    def difference(self, other: "Solid") -> "Solid":
        """Remove material; the bounding box of the remaining body is unchanged."""
        if other.volume_mm3 >= self.volume_mm3:
            raise ValueError("cut removes more material than the body contains")
        return Solid(self.volume_mm3 - other.volume_mm3, self.bbox_mm)

    def scaled(self, factor: float) -> "Solid":
        return Solid(self.volume_mm3 * factor, self.bbox_mm)


def hex_prism(across_flats: float, height: float) -> Solid:
    """Regular hexagonal prism, flats normal to Z, corners along X."""
    return Solid(
        SQRT3 / 2.0 * across_flats**2 * height,
        (2.0 * across_flats / SQRT3, height, across_flats),
    )


def hex_prism_across_corners(across_corners: float, height: float) -> Solid:
    """Same prism, but parameterised by its circumscribed diameter."""
    return hex_prism(across_corners * SQRT3 / 2.0, height)


def cylinder(diameter: float, height: float) -> Solid:
    return Solid(math.pi / 4.0 * diameter**2 * height, (diameter, height, diameter))


def annulus(outer_diameter: float, inner_diameter: float, height: float) -> Solid:
    area = math.pi / 4.0 * (outer_diameter**2 - inner_diameter**2)
    return Solid(area * height, (outer_diameter, height, outer_diameter))


def plate(length: float, width: float, thickness: float) -> Solid:
    """Rectangular plate: length along X, thickness along the part axis (-Y)."""
    return Solid(length * width * thickness, (length, thickness, width))


def hole(diameter: float, through: float) -> Solid:
    """A drilled hole, used with :meth:`Solid.difference`."""
    return cylinder(diameter, through)


def hole_pattern(diameter: float, through: float, count: int) -> Solid:
    """`count` identical holes; only the total removed volume matters here."""
    one = hole(diameter, through)
    return Solid(one.volume_mm3 * count, one.bbox_mm)


def tap_drill(diameter: float) -> float:
    """Simplified thread: the minor diameter of a coarse metric thread.

    SolidWorks models in this library are threadless on purpose; a tapped hole
    is drawn as a plain hole at this diameter so the volume stays realistic
    without the cost of a cosmetic thread (or a helical cut).
    """
    return round(0.85 * diameter, 3)


def bolt_cylinder_volume(diameter: float, length: float) -> float:
    return cylinder(diameter, length).volume_mm3


def round_mm(value: float, digits: int = 3) -> float:
    return round(value + 0.0, digits)


def relative_error(expected: float, actual: float) -> float:
    if expected == 0:
        return 0.0 if actual == 0 else math.inf
    return abs(actual - expected) / abs(expected)
