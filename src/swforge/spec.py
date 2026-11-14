"""Part specifications: plain data that can be stored, diffed and generated."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .kinds import PartKind


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


#: Encoding used to read a spec file.  "utf-8-sig" is utf-8 that also
#: tolerates a byte-order mark, and it is the right default because the files
#: this reads are hand-written: PowerShell's `Set-Content` and `Out-File` write
#: a BOM by default on Windows, as does Notepad's "UTF-8" option.  `json.loads`
#: refuses a BOM outright -- "Unexpected UTF-8 BOM (decode using utf-8-sig)" --
#: so a spec that looks perfectly fine in an editor failed to load.  Reading is
#: forgiving; writing stays plain utf-8, so the files this package produces are
#: byte-identical everywhere.
SPEC_ENCODING = "utf-8-sig"


def load_specs(path: str | Path) -> list[PartSpec]:
    """Load a JSON file holding either one spec or a list of specs."""
    raw = json.loads(Path(path).read_text(encoding=SPEC_ENCODING))
    items = raw if isinstance(raw, list) else [raw]
    return [PartSpec.from_dict(item) for item in items]


def dump_specs(specs: list[PartSpec], path: str | Path) -> None:
    Path(path).write_text(
        json.dumps([spec.to_dict() for spec in specs], indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
