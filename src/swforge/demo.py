"""Showcase sets: four catalogue fasteners, four non-standard parts, and a stack.

The assembly is deliberately built from parts that already have a closed-form
answer, so the stacked result can be predicted before SolidWorks is asked for it.
"""

from __future__ import annotations

from .spec import PartSpec
from .stack import AssemblySpec, Mate, Placement


def showcase() -> list[PartSpec]:
    return [
        PartSpec("hex_bolt", "M8x40", {"size": "M8", "length": 40}),
        PartSpec("hex_nut", "M8", {"size": "M8"}),
        PartSpec("washer", "M8", {"size": "M8"}),
        PartSpec("socket_screw", "M6x25", {"size": "M6", "length": 25}),
        PartSpec(
            "l_bracket",
            "60x40x40x5",
            {
                "leg_a": 60,
                "leg_b": 40,
                "width": 40,
                "thickness": 5,
                "hole_d": 9,
                "holes_per_leg": 2,
            },
        ),
        PartSpec(
            "multi_hole_plate",
            "120x80x6",
            {
                "length": 120,
                "width": 80,
                "thickness": 6,
                "hole_d": 9,
                "rows": 2,
                "cols": 3,
            },
        ),
        PartSpec(
            "stepped_shaft",
            "20-15-10",
            {"d1": 20, "l1": 30, "d2": 15, "l2": 40, "d3": 10, "l3": 25},
        ),
        PartSpec(
            "flange",
            "DN50",
            {
                "outer_d": 100,
                "hub_d": 62,
                "plate_t": 12,
                "hub_h": 8,
                "bore_d": 50,
                "bolt_d": 11,
                "bolt_count": 4,
                "bolt_circle_d": 78,
            },
        ),
    ]


#: The four clearance holes of the plate that the bolts go through; the plate
#: spans 0..120 in x and 0..80 in z, and its 2x3 grid sits at these points.
BOLT_HOLES = ((12.0, 12.0), (108.0, 12.0), (12.0, 68.0), (108.0, 68.0))

#: Head height of GB/T 5783 M8 (catalogue value for s=13, k=5.3).
HEAD_HEIGHT_M8 = 5.3


def bolt_stack() -> AssemblySpec:
    """A plain plate with four M8x40 bolts dropped through its corner holes.

    Placement is stated in the coordinate system the builders use: a part is
    centred on its placement point in x and z, and its body extends downwards
    from it.  So the plate's top face sits at y = -5.3 (one head height below the
    origin) and each bolt's top face sits at y = 0, which is exactly the distance
    the mates then lock in.
    """
    plate = PartSpec(
        "multi_hole_plate",
        "120x80x6",
        {
            "length": 120,
            "width": 80,
            "thickness": 6,
            "hole_d": 9,
            "rows": 2,
            "cols": 3,
        },
    )
    bolt = PartSpec("hex_bolt", "M8x40", {"size": "M8", "length": 40})

    placements = [
        Placement("plate-1", plate.name, x_mm=60.0, y_mm=-HEAD_HEIGHT_M8, z_mm=40.0)
    ]
    mates: list[Mate] = []
    for index, (x, z) in enumerate(BOLT_HOLES, start=1):
        name = f"bolt-{index}"
        placements.append(
            Placement(name, bolt.name, x_mm=x, y_mm=0.0, z_mm=z)
        )
        mates.append(
            Mate(
                first=name,
                second="plate-1",
                plane="上视基准面",
                distance_mm=HEAD_HEIGHT_M8,
                # The bolt goes *above* the plate.  A distance mate is unsigned
                # and SolidWorks takes the reversed side by default, which drops
                # the head through the plate and adds a head height to the
                # envelope (measured 50.60 instead of 45.30).
                flip=True,
            )
        )

    return AssemblySpec(
        name="bolt_stack",
        parts={plate.name: plate, bolt.name: bolt},
        placements=placements,
        mates=mates,
    )
