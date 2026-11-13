"""Part specifications: plain data that can be stored, diffed and generated."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

PartKind = Literal[
    "hex_bolt",
    "hex_nut",
    "washer",
    "socket_screw",
    "l_bracket",
    "multi_hole_plate",
    "stepped_shaft",
    "flange",
]

STANDARD_KINDS: frozenset[str] = frozenset(
    {"hex_bolt", "hex_nut", "washer", "socket_screw"}
)
NON_STANDARD_KINDS: frozenset[str] = frozenset(
    {"l_bracket", "multi_hole_plate", "stepped_shaft", "flange"}
)


@dataclass
class PartSpec:
    """One part to generate.

    `params` is intentionally a plain dict: standard parts take catalogue
    dimensions, non-standard parts take user dimensions, and both are validated
    by the builder that owns the kind.
    """

    kind: PartKind
    name: str
    params: dict[str, Any] = field(default_factory=dict)
    tolerance: float = 0.001
    """Relative volume tolerance accepted between model and analytic answer."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PartSpec":
        return cls(
            kind=data["kind"],
            name=data["name"],
            params=dict(data.get("params", {})),
            tolerance=float(data.get("tolerance", 0.001)),
        )

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


def load_specs(path: str | Path) -> list[PartSpec]:
    """Load a JSON file holding either one spec or a list of specs."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else [raw]
    return [PartSpec.from_dict(item) for item in items]


def dump_specs(specs: list[PartSpec], path: str | Path) -> None:
    Path(path).write_text(
        json.dumps([spec.to_dict() for spec in specs], indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
