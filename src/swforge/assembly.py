"""Build assemblies from generated parts and mate them with native mates.

The assembly path needs three things the part path never did, and each of them
fails silently when it is missing:

1. A part must be *loaded* before AddComponent5 will accept it.  Passing the
   path of a part that is not open returns None and adds nothing; there is no
   error.  Pre-loading through OpenDoc6 fixes it.
2. SelectByID2 addresses a component through its assembly-qualified name,
   `washers-1@bracket_stack` -- the file extension is not part of it, and the
   bare component name selects nothing.
3. Document-scoped calls act on the *active* document only.  An assembly that
   was opened by path is not active, so every selection quietly fails until
   ActivateDoc2 runs.

Mates are created with AddMate5, which takes fourteen positional arguments and
one [out] error code.  Its error code is an swAddMateError_e value where 0 means
failure and 1 means success -- the opposite of the usual convention.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .session import SwError, SwModel, _callout, _com, member

#: swMateType_e values used by this library.
MATE_COINCIDENT = 0
MATE_DISTANCE = 5

#: swAddMateError_e.swAddMateError_NoError; a successful mate reports 1, not 0.
MATE_NO_ERROR = 1

#: The three reference planes every generated part carries, in SolidWorks order.
REFERENCE_PLANES = ("前视基准面", "上视基准面", "右视基准面")


@dataclass(frozen=True)
class Component:
    """One inserted component plus the names needed to address it."""

    name: str
    """Component name inside the assembly, e.g. `washer_M8-1`."""

    qualified: str
    """Name SelectByID2 wants: `washer_M8-1@bolt_stack`."""

    comp: Any
    """The IComponent2 itself."""

    path: Path
    """Source part file."""

    @property
    def select_id(self) -> str:
        return self.qualified


class SwAssembly:
    """A new or opened assembly document."""

    def __init__(self, model: Any, app: Any = None) -> None:
        self.model = model
        self.app = app
        self.ext = model.Extension
        self._stem = Path(str(member(model, "GetPathName", default=""))).stem

    # -- identity ---------------------------------------------------------
    @property
    def title(self) -> str:
        return str(member(self.model, "GetTitle", default=""))

    def _stem_now(self) -> str:
        """Assembly stem used in qualified names; set after the first save."""
        path = str(member(self.model, "GetPathName", default=""))
        if path:
            self._stem = Path(path).stem
        return self._stem

    # -- components -------------------------------------------------------
    def load_part(self, path: str | Path) -> Any:
        """Open a part so AddComponent5 will accept it.

        Returns the part document; already-open parts are reused by SolidWorks,
        so calling this twice is cheap and never duplicates a document.
        """
        from .session import open_document

        return open_document(self.app, path, 1)

    def add_component(
        self, path: str | Path, x_mm: float = 0.0, y_mm: float = 0.0, z_mm: float = 0.0
    ) -> Component:
        """Insert one instance of *path* at the given position, in millimetres."""
        target = Path(path).resolve()
        if not target.exists():
            raise SwError(f"part does not exist: {target}")
        self.load_part(target)
        comp = self.model.AddComponent5(
            str(target), 0, "", False, "", x_mm / 1000.0, y_mm / 1000.0, z_mm / 1000.0
        )
        if comp is None:
            raise SwError(
                f"AddComponent5 refused {target.name}; the part must be loaded "
                "in this session before it can be inserted"
            )
        name = str(member(comp, "Name2", default=""))
        return Component(
            name=name, qualified=f"{name}@{self._stem_now()}", comp=comp, path=target
        )

    def components(self) -> list[Component]:
        found = member(self.model, "GetComponents", True, default=()) or ()
        stem = self._stem_now()
        out: list[Component] = []
        for comp in found:
            name = str(member(comp, "Name2", default=""))
            path = str(member(comp, "GetPathName", default=""))
            out.append(
                Component(
                    name=name,
                    qualified=f"{name}@{stem}",
                    comp=comp,
                    path=Path(path),
                )
            )
        return out

    def find(self, name: str) -> Component:
        for comp in self.components():
            if comp.name == name:
                return comp
        known = ", ".join(c.name for c in self.components()) or "none"
        raise SwError(f"no component {name!r}; present: {known}")

    # -- selection --------------------------------------------------------
    def _select(self, name: str, kind: str, append: bool = False) -> bool:
        pythoncom, _ = _com()
        return bool(
            self.ext.SelectByID2(
                name, kind, 0, 0, 0, append, 0, _callout(pythoncom), 0
            )
        )

    def select_plane(self, component: Component, plane: str, append: bool = False) -> str:
        """Select one reference plane of a component.

        The qualified form is `plane@component@assembly`; SolidWorks resolves
        nothing shorter, and a bare plane name would hit the assembly's own
        planes instead of the component's.
        """
        qualified = f"{plane}@{component.qualified}"
        if not self._select(qualified, "PLANE", append):
            raise SwError(f"cannot select {qualified!r}")
        return qualified

    def clear_selection(self) -> None:
        self.model.ClearSelection2(True)

    # -- mates ------------------------------------------------------------
    def add_mate(
        self,
        mate_type: int,
        distance_mm: float = 0.0,
        align: int = 0,
        flip: bool = False,
    ) -> str:
        """Create a mate from the current selection (exactly two entities)."""
        pythoncom, _ = _com()
        from win32com.client import VARIANT  # type: ignore

        errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        feature = self.model.AddMate5(
            mate_type,
            align,
            flip,
            distance_mm / 1000.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            False,
            False,
            0.0,
            errors,
        )
        if feature is None or errors.value != MATE_NO_ERROR:
            raise SwError(
                f"mate of type {mate_type} failed (swAddMateError={errors.value})"
            )
        return str(member(feature, "Name", default=""))

    def mate_planes(
        self,
        first: Component,
        second: Component,
        plane: str = "上视基准面",
        mate_type: int = MATE_COINCIDENT,
        distance_mm: float = 0.0,
    ) -> str:
        """Mate the same reference plane of two components."""
        self.clear_selection()
        self.select_plane(first, plane)
        self.select_plane(second, plane, append=True)
        try:
            return self.add_mate(mate_type, distance_mm)
        finally:
            self.clear_selection()

    def constrained_status(self, component: Component) -> int:
        """swComponentConstrainedState_e: 0 unknown, 1 under-defined, 2 fixed."""
        return int(member(component.comp, "GetConstrainedStatus", default=0))

    def transforms(self) -> dict[str, list[float]]:
        """Component placements as 16-element transform arrays (metres)."""
        out: dict[str, list[float]] = {}
        for comp in self.components():
            transform = member(comp.comp, "Transform2", default=None)
            data = member(transform, "ArrayData", default=None)
            out[comp.name] = [round(float(v), 6) for v in (data or [])]
        return out

    # -- views ------------------------------------------------------------
    def name_view(self, name: str, view_id: int) -> None:
        """Save the current orientation under *name* so a drawing can use it.

        CreateDrawViewFromModelView3 only accepts named views (`*Front` and
        friends return None), so the orientation has to be stored on the model
        first.  view_id follows swStandardViews_e: 1 front, 3 right, 5 top,
        7 isometric.
        """
        self.model.ShowNamedView2("", view_id)
        self.model.NameView(name)

    # -- measurement ------------------------------------------------------
    def measure(self) -> tuple[float, float]:
        """Total volume in mm3 and surface area in mm2 for the assembly."""
        prop = self.ext.CreateMassProperty
        if prop is None:
            raise SwError("mass properties are unavailable (no components?)")
        return float(prop.Volume) * 1e9, float(prop.SurfaceArea) * 1e6

    # -- output -----------------------------------------------------------
    def save(self, path: str | Path) -> Path:
        return SwModel(self.model, self.app).save(path)

    def export_step(self, path: str | Path) -> Path:
        target = Path(path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        pythoncom, _ = _com()
        from win32com.client import VARIANT  # type: ignore

        errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        if not self.ext.SaveAs(
            str(target), 0, 1, _callout(pythoncom), errors, warnings
        ):
            raise SwError(f"STEP export failed: {target}")
        return target
