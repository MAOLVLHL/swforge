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

from .session import SwError, SwModel, _callout, _com, close_document, member

#: swMateType_e values used by this library.
MATE_COINCIDENT = 0
MATE_DISTANCE = 5

#: swAddMateError_e.swAddMateError_NoError; a successful mate reports 1, not 0.
MATE_NO_ERROR = 1

#: The three reference planes every generated part carries, in SolidWorks order.
REFERENCE_PLANES = ("前视基准面", "上视基准面", "右视基准面")


def _half_height_mm(document: Any) -> float:
    """Half the part's height in its own frame, in millimetres.

    This is the correction AddComponent5 needs to turn "place the top face here"
    into "place the bounding-box centre here".  A part with no bodies reports 0,
    which degrades to the raw point rather than refusing to insert.
    """
    box = SwModel(document, None).bbox_limits_mm()
    if not box:
        return 0.0
    return (float(box[4]) - float(box[1])) / 2.0


def local_box_mm(
    component: Component,
) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    """The component's body box in its own part frame, in millimetres.

    GetBodyBox() on an assembly component answers in *part* coordinates: all four
    bolts of the showcase report the same box even though they sit in different
    corners, so treating this as a world box inflates the envelope by exactly one
    part width (measured 127.51 mm against a predicted 120.00).  The pose lives
    in Transform2; a world box needs both.
    """
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    found = False
    bodies = member(component.comp, "GetBodies2", 0, default=None)
    if bodies is None:
        bodies = member(component.comp, "GetBodies2", False, default=None)
    for body in bodies or ():
        values = [float(value) * 1000.0 for value in body.GetBodyBox()]
        for axis in range(3):
            lo[axis] = min(lo[axis], values[axis])
            hi[axis] = max(hi[axis], values[axis + 3])
        found = True
    if not found:
        return None
    return (tuple(lo), tuple(hi))  # type: ignore[return-value]


def world_box_mm(
    component: Component,
) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    """The component's body box in assembly coordinates, in millimetres.

    Transform2.ArrayData is the component's 4x4 placement matrix, row-major, with
    the translation in slots 9..11 and metres throughout.  All eight corners of
    the local box are mapped through it, so a rotated component still reports a
    correct axis-aligned extent.
    """
    box = local_box_mm(component)
    if box is None:
        return None
    lo, hi = box
    data = member(
        member(component.comp, "Transform2", default=None), "ArrayData", default=None
    ) or ()
    if len(data) < 12:
        raise SwError(
            f"component {component.name!r} has no usable transform "
            f"({len(data)} values instead of 16)"
        )
    matrix = [float(value) for value in data[:9]]
    translation = [float(value) * 1000.0 for value in data[9:12]]
    out_lo = [float("inf")] * 3
    out_hi = [float("-inf")] * 3
    for x in (lo[0], hi[0]):
        for y in (lo[1], hi[1]):
            for z in (lo[2], hi[2]):
                for axis in range(3):
                    value = (
                        matrix[axis * 3] * x
                        + matrix[axis * 3 + 1] * y
                        + matrix[axis * 3 + 2] * z
                        + translation[axis]
                    )
                    out_lo[axis] = min(out_lo[axis], value)
                    out_hi[axis] = max(out_hi[axis], value)
    return (tuple(out_lo), tuple(out_hi))  # type: ignore[return-value]


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
        #: Components keyed by the caller's own instance name.  SolidWorks
        #: renames every inserted part to <file stem>-<n>, so a spec that says
        #: "bolt-1" can never find its component by name afterwards.  Recording
        #: the mapping at insertion time is the only place the two names meet.
        self._instances: dict[str, Component] = {}
        #: Documents this assembly opened purely so AddComponent5 would accept
        #: them.  They are closed again with the assembly: inserting four bolts
        #: off one file opens that file once, but a five-part stack still leaves
        #: the plate and the bolt loaded for the rest of the session.
        self._opened: list[Any] = []

    # -- identity ---------------------------------------------------------
    @property
    def title(self) -> str:
        return str(member(self.model, "GetTitle", default=""))

    def _stem_now(self) -> str:
        """Assembly name used in qualified names.

        A document that has never been saved has no path, and its components are
        addressed by the window title instead ("\u88c5\u914d\u4f531").  Reading
        only the path left the stem empty, so every qualified name ended in a
        bare "@" and selected nothing.
        """
        path = str(member(self.model, "GetPathName", default=""))
        if path:
            self._stem = Path(path).stem
        elif not self._stem:
            self._stem = str(member(self.model, "GetTitle", default=""))
        return self._stem

    # -- components -------------------------------------------------------
    def load_part(self, path: str | Path) -> Any:
        """Open a part so AddComponent5 will accept it.

        A part that is *already open* is reused rather than reopened.  That is
        not an optimisation: when a document holds the file, OpenDoc6 answers
        errors=65536 ("the document is in use") instead of handing back the
        open one, and the assembly fails on a part that visibly exists and just
        passed its own verification.  generate() closes its documents now, but
        a caller that keeps them open (or a hand-opened file) still hits this.
        """
        from .session import SwSession

        if self.app is None:
            raise SwError("the assembly is not bound to a SolidWorks instance")
        target = Path(path).resolve()
        for doc in member(self.app, "GetDocuments", default=()) or ():
            got = str(member(doc, "GetPathName", default=""))
            if got and Path(got).resolve() == target:
                return doc
        opened = SwSession(self.app).open_document(target, 1)
        self._opened.append(target)
        return opened

    def add_component(
        self,
        path: str | Path,
        x_mm: float = 0.0,
        y_mm: float = 0.0,
        z_mm: float = 0.0,
        instance: str | None = None,
    ) -> Component:
        """Insert one instance of *path* at the given position, in millimetres.

        Pass *instance* to keep the caller's own name for the component; the
        returned handle is then reachable through find() under that name.

        Position follows the placement convention of AssemblySpec: x and z are
        where the instance is centred, y is where its top face sits, and the body
        hangs below that.  AddComponent5 does not honour that directly -- it puts
        the part's *bounding-box centre* on the point it is given, so a bolt asked
        for at y = 0 lands with its box centre at 0 and its head 22.65 mm high
        (half of its 45.3 mm length).  Only the vertical term needs correcting:
        x and z already mean "centre", while y means "top", which is half a part
        height above the centre.  Verified against the real assembly: with this
        offset the three probes come out at exactly (60, -5.3, 40), (12, 0, 12)
        and (108, 0, 68) with the predicted 120 x 45.30 x 80 envelope.
        """
        target = Path(path).resolve()
        if not target.exists():
            raise SwError(f"part does not exist: {target}")
        document = self.load_part(target)
        comp = self.model.AddComponent5(
            str(target),
            0,
            "",
            False,
            "",
            x_mm / 1000.0,
            (y_mm - _half_height_mm(document)) / 1000.0,
            z_mm / 1000.0,
        )
        if comp is None:
            raise SwError(
                f"AddComponent5 refused {target.name}; the part must be loaded "
                "in this session before it can be inserted"
            )
        name = str(member(comp, "Name2", default=""))
        inserted = Component(
            name=name, qualified=f"{name}@{self._stem_now()}", comp=comp, path=target
        )
        if instance:
            self._instances[instance] = inserted
        return inserted

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
        recorded = self._instances.get(name)
        if recorded is not None:
            return recorded
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
        flip: bool = False,
    ) -> str:
        """Mate the same reference plane of two components.

        A distance mate constrains the *magnitude* only, so SolidWorks picks a
        side; by default it picks the reversed one, which puts a bolted stack
        upside down (measured: bolt top at -10.6 instead of 0).  Pass flip=True
        to force the forward side.
        """
        self.clear_selection()
        self.select_plane(first, plane)
        self.select_plane(second, plane, append=True)
        try:
            return self.add_mate(mate_type, distance_mm, flip=flip)
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

    def close(self) -> None:
        """Close the assembly and every part it opened to insert.

        Same reason as SwModel.close(): a finished assembly is another loaded
        document on a session that just built every one of its parts, and the
        parts this assembly opened for AddComponent5 are loaded documents too.
        The assembly goes first so its component references are gone before
        their files disappear.
        """
        # The opened parts go first: once the assembly document is closed its
        # model handle is dead, and SwModel(...) over a dead handle raises while
        # looking up .Extension.  Closing by path needs only the application.
        for target in self._opened:
            close_document(self.app, target)
        self._opened.clear()
        SwModel(self.model, self.app).close()

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
