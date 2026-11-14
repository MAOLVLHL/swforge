"""What a part kind reads out of PartSpec.params, as data.

Imports nothing but dataclasses, like swforge.kinds: the registry and anything
that wants to render a form over the kinds both need it, and neither can afford
to import SolidWorks geometry or COM to get it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Param:
    """One key a builder takes out of the params dict.

    A module declares the keys it reads as a module-level PARAMS tuple next to
    the code that reads them, and parts.schema() publishes that tuple.  The
    declaration is data, not a second validator: a key listed here is one the
    builder looks up, and required/default describe the lookup itself.
    """

    name: str
    required: bool = True
    #: Only meaningful when required is False.  This is the value the builder
    #: substitutes when the key is absent, not always the value it ends up
    #: using: multi_hole_plate turns a margin of 0.0 into a hole-sized one.
    default: Any = None
    #: Legal values, when the builder looks the value up in a table.  Empty
    #: means the builder accepts any value, so no range is advertised.
    choices: tuple[str, ...] = ()

    def describe(self) -> dict[str, Any]:
        """Flatten to the row schema() publishes; a list keeps it JSON-safe."""
        return {
            "name": self.name,
            "required": self.required,
            "default": self.default,
            "choices": list(self.choices),
        }
