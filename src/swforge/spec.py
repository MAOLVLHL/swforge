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


class SpecError(ValueError):
    """A spec file a person can fix: unreadable, not JSON, or missing fields.

    Every failure of the input path ends up as this one type, so a caller can
    answer "your file says X" instead of printing a traceback.  The message is
    written for the person who typed the file, not for a stack frame.
    """


def read_json(path: str | Path, what: str) -> Any:
    """Read *path* as JSON, turning every readable failure into a SpecError.

    The file is decoded with :data:`SPEC_ENCODING` so a byte-order mark -- what
    Notepad and PowerShell's `Set-Content` write -- is accepted rather than
    reported as a broken file.
    """
    target = Path(path)
    try:
        text = target.read_text(encoding=SPEC_ENCODING)
    except FileNotFoundError:
        raise SpecError(f"{what} file not found: {target}") from None
    except OSError as error:
        raise SpecError(
            f"cannot read {what} file {target}: {error.strerror or error}"
        ) from None
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise SpecError(
            f"{what} file {target} is not valid JSON: {error.msg} "
            f"(line {error.lineno}, column {error.colno})"
        ) from None


def load_specs(path: str | Path) -> list[PartSpec]:
    """Load a JSON file holding either one spec or a list of specs."""
    raw = read_json(path, "spec")
    items = raw if isinstance(raw, list) else [raw]
    if not items:
        raise SpecError(f"spec file {path} holds an empty list; nothing to build")
    specs = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise SpecError(
                f"{path}: entry {index} is a {type(item).__name__}, "
                "expected an object with kind and name"
            )
        try:
            specs.append(PartSpec.from_dict(item))
        except KeyError as error:
            raise SpecError(
                f"{path}: entry {index} is missing the {error.args[0]!r} field"
            ) from None
        except (TypeError, ValueError) as error:
            raise SpecError(f"{path}: entry {index} is invalid: {error}") from None
    return specs


def dump_specs(specs: list[PartSpec], path: str | Path) -> None:
    Path(path).write_text(
        json.dumps([spec.to_dict() for spec in specs], indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
