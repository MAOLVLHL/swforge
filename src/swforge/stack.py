"""Declarative assemblies: instances, placements, mates, and an analytic check.

An assembly spec is plain data -- the same shape as a part spec, one level up.
It exists because an assembly is the only place where a modelling claim can be
checked *before* SolidWorks is involved: the volume of n instances is the sum of
their volumes, and the envelope follows from where they were placed.  So the
same "predict, then verify" contract that makes the parts trustworthy applies to
the assembly too.

Two frame conventions hold this together, and both come from the builders:

* Every part is extruded downwards from its sketch plane, so its body spans
  y in [-height, 0] in its own frame.
* Each part is treated as centred on its placement point in x and z.  The
  builders disagree on this (a plate runs 0..length, a shaft is centred), so the
  envelope is exact only when the parts are stacked along y and the lateral
  offsets keep the small part inside the large one.  That is the intended use,
  and it is stated here rather than hidden behind a bounding-box claim that
  would be wrong for a general arrangement.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from . import parts
from .geometry import Solid
from .spec import PartSpec, SpecError, read_json

#: Mate kinds accepted by AssemblySpec.mates; 0 distance means coincident.
MATE_KINDS = ("coincident", "distance")


@dataclass(frozen=True)
class Placement:
    """One instance of a part, positioned in millimetres.

    (x, y, z) is the point the part's own origin is moved to.  Because every
    builder extrudes along -y, a placement with y = 0 puts the part's top face
    at the assembly origin.
    """

    instance: str
    part: str
    x_mm: float = 0.0
    y_mm: float = 0.0
    z_mm: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance": self.instance,
            "part": self.part,
            "x_mm": self.x_mm,
            "y_mm": self.y_mm,
            "z_mm": self.z_mm,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Placement":
        return cls(
            instance=str(data["instance"]),
            part=str(data["part"]),
            x_mm=float(data.get("x_mm", 0.0)),
            y_mm=float(data.get("y_mm", 0.0)),
            z_mm=float(data.get("z_mm", 0.0)),
        )


@dataclass(frozen=True)
class Mate:
    """One mate between two instances, expressed with reference planes.

    Reference planes are used instead of faces on purpose: face names in
    SolidWorks are positional ("Face<12>"), so they change whenever a feature is
    added to the part, while "上视基准面@instance@assembly" is stable across
    rebuilds.  A distance mate on the top planes constrains y only, which is
    exactly the degree of freedom a stack needs.

    *flip* picks which side of the second plane the first one is held on.  A
    distance mate is unsigned, so SolidWorks is free to satisfy it either way;
    it resolves to the reversed side whenever the components are already at the
    requested distance when the mate is added.  That is exactly the case here --
    placements are stated in their final positions before mating -- so a stack
    that wants the bolt above the plate has to say so.
    """

    first: str
    second: str
    plane: str = "上视基准面"
    distance_mm: float = 0.0
    flip: bool = False

    @property
    def kind(self) -> str:
        return "coincident" if abs(self.distance_mm) < 1e-9 else "distance"

    def to_dict(self) -> dict[str, Any]:
        return {
            "first": self.first,
            "second": self.second,
            "plane": self.plane,
            "distance_mm": self.distance_mm,
            "flip": self.flip,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Mate":
        return cls(
            first=str(data["first"]),
            second=str(data["second"]),
            plane=str(data.get("plane", "上视基准面")),
            distance_mm=float(data.get("distance_mm", 0.0)),
            flip=bool(data.get("flip", False)),
        )


@dataclass
class AssemblySpec:
    """Parts to build, where each instance sits, and how they are mated."""

    name: str
    parts: dict[str, PartSpec] = field(default_factory=dict)
    placements: list[Placement] = field(default_factory=list)
    mates: list[Mate] = field(default_factory=list)
    tolerance: float = 0.001
    """Relative volume tolerance between the assembly and the sum of its parts."""

    # -- validation -------------------------------------------------------
    def validate(self) -> None:
        """Reject a spec that could only fail later, inside SolidWorks."""
        if not self.parts:
            raise ValueError(f"assembly {self.name!r} has no parts")
        for key, spec in self.parts.items():
            if key != spec.name:
                raise ValueError(
                    f"part key {key!r} must equal its spec name {spec.name!r}"
                )
        seen: set[str] = set()
        for placement in self.placements:
            if placement.part not in self.parts:
                known = ", ".join(self.parts) or "none"
                raise ValueError(
                    f"placement {placement.instance!r} refers to unknown part "
                    f"{placement.part!r}; known: {known}"
                )
            if placement.instance in seen:
                raise ValueError(f"duplicate instance name {placement.instance!r}")
            seen.add(placement.instance)
        for mate in self.mates:
            for side in (mate.first, mate.second):
                if side not in seen:
                    raise ValueError(
                        f"mate refers to unknown instance {side!r}; "
                        f"instances: {', '.join(sorted(seen)) or 'none'}"
                    )
            if mate.first == mate.second:
                raise ValueError(f"instance {mate.first!r} cannot mate to itself")

    # -- prediction -------------------------------------------------------
    def instance_volume_mm3(self, placement: Placement) -> float:
        return parts.analytic(
            self.parts[placement.part].kind, self.parts[placement.part].params
        ).volume_mm3

    def predict(self) -> Solid:
        """The volume and envelope the built assembly has to reproduce."""
        self.validate()
        volume = sum(self.instance_volume_mm3(p) for p in self.placements)
        lo = [0.0, 0.0, 0.0]
        hi = [0.0, 0.0, 0.0]
        first = True
        for placement in self.placements:
            size = parts.analytic(
                self.parts[placement.part].kind, self.parts[placement.part].params
            ).bbox_mm
            centre = (placement.x_mm, placement.y_mm, placement.z_mm)
            # y spans [-height, 0] in the part frame; x and z are centred.
            spans = (
                (centre[0] - size[0] / 2.0, centre[0] + size[0] / 2.0),
                (centre[1] - size[1], centre[1]),
                (centre[2] - size[2] / 2.0, centre[2] + size[2] / 2.0),
            )
            for axis, (low, high) in enumerate(spans):
                lo[axis] = low if first else min(lo[axis], low)
                hi[axis] = high if first else max(hi[axis], high)
            first = False
        bbox = tuple(round(hi[axis] - lo[axis], 6) for axis in range(3))
        return Solid(round(volume, 6), bbox)  # type: ignore[arg-type]

    # -- convenience ------------------------------------------------------
    def instances(self, part: str) -> Iterator[Placement]:
        return (p for p in self.placements if p.part == part)

    def summary(self) -> list[str]:
        predicted = self.predict()
        lines = [
            f"assembly {self.name}: {len(self.placements)} instances, "
            f"{len(self.mates)} mates",
            f"  volume {predicted.volume_mm3:.1f} mm3, "
            f"envelope {'x'.join(f'{v:.2f}' for v in predicted.bbox_mm)} mm",
        ]
        for placement in self.placements:
            lines.append(
                f"  {placement.instance:<20} {placement.part:<18} "
                f"at ({placement.x_mm:.1f}, {placement.y_mm:.1f}, "
                f"{placement.z_mm:.1f})"
            )
        return lines

    # -- serialisation ----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "tolerance": self.tolerance,
            "parts": {key: spec.to_dict() for key, spec in self.parts.items()},
            "placements": [p.to_dict() for p in self.placements],
            "mates": [m.to_dict() for m in self.mates],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AssemblySpec":
        return cls(
            name=str(data["name"]),
            parts={
                key: PartSpec.from_dict(value)
                for key, value in dict(data.get("parts", {})).items()
            },
            placements=[
                Placement.from_dict(item)
                for item in data.get("placements", [])
            ],
            mates=[Mate.from_dict(item) for item in data.get("mates", [])],
            tolerance=float(data.get("tolerance", 0.001)),
        )


def load_assembly(path: str | Path) -> AssemblySpec:
    """Load an assembly spec, reporting a bad file as a SpecError.

    The shape checks are the ones a hand-written file actually fails: a list
    where an object belongs, a missing name, a part entry that is not a spec.
    The deeper consistency checks stay in :meth:`AssemblySpec.validate`, which
    the caller runs once it knows what it is building.
    """
    data = read_json(path, "assembly")
    if not isinstance(data, dict):
        raise SpecError(
            f"assembly file {path} holds a {type(data).__name__}, "
            "expected an object with name and parts"
        )
    try:
        spec = AssemblySpec.from_dict(data)
    except KeyError as error:
        raise SpecError(
            f"assembly file {path} is missing the {error.args[0]!r} field"
        ) from None
    except (TypeError, ValueError) as error:
        raise SpecError(f"assembly file {path} is invalid: {error}") from None
    if not spec.parts:
        raise SpecError(f"assembly file {path} has no parts; nothing to build")
    return spec


def dump_assembly(spec: AssemblySpec, path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(spec.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
