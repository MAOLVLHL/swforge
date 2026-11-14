"""Thin, defensive wrapper around the SolidWorks COM API.

The wrapper exists because the raw COM surface has three traps that make naive
scripts fail silently:

1. Many members are *properties*, not methods (FirstFeature,
   CreateMassProperty, EditRebuild3).  Calling them raises
   "-2147352573 member not found".  The module-level helper member() handles
   both shapes.
2. SelectByID2 needs a real VARIANT for the callout argument; passing None
   raises "-2147352571 type mismatch".
3. Drawing entities into a brand-new part can be dropped unless
   SketchManager.AddToDB is on: the circle is rejected, the sketch ends up
   empty and SolidWorks silently deletes it when the sketch is closed.

SolidWorks must already be running and a licence must be available; the wrapper
never launches the application.
"""

from __future__ import annotations

import math
from contextlib import contextmanager
from dataclasses import dataclass
import time
from pathlib import Path
from typing import Any, Iterator

TOP_PLANE = "上视基准面"
FRONT_PLANE = "前视基准面"
RIGHT_PLANE = "右视基准面"

#: English aliases accepted by SwModel.select_plane.  A Chinese UI is the
#: default here, but the library should not care where it runs.
PLANE_ALIASES: dict[str, str] = {
    "top": TOP_PLANE,
    "top plane": TOP_PLANE,
    "上视基准面": TOP_PLANE,
    "front": FRONT_PLANE,
    "front plane": FRONT_PLANE,
    "前视基准面": FRONT_PLANE,
    "right": RIGHT_PLANE,
    "right plane": RIGHT_PLANE,
    "右视基准面": RIGHT_PLANE,
}

PLANE = "PLANE"
SKETCH = "SKETCH"

MISSING_MEMBER = "-2147352573"


class SwError(RuntimeError):
    """Raised when SolidWorks rejects an operation or is not reachable."""


@dataclass(frozen=True)
class Measure:
    volume_mm3: float
    area_mm2: float


def _com() -> tuple[Any, Any]:
    try:
        import pythoncom  # type: ignore
        import win32com.client  # type: ignore
    except ImportError as exc:  # pragma: no cover - only on non-Windows hosts
        raise SwError(
            "pywin32 is required to talk to SolidWorks: pip install 'swforge[com]'"
        ) from exc
    return pythoncom, win32com.client


def member(obj: Any, name: str, *args: Any, default: Any = None) -> Any:
    """Read obj.name, calling it only when the COM member is a method.

    SolidWorks uses both shapes for same-looking members and pywin32 cannot
    tell them apart, so a wrong guess raises a COM error, not a TypeError.
    """
    try:
        attr = getattr(obj, name)
    except AttributeError:
        return default
    try:
        if args:
            return attr(*args)
        return attr() if callable(attr) else attr
    except TypeError:
        return attr
    except Exception as exc:  # pywintypes.com_error
        if MISSING_MEMBER in str(exc):
            return attr
        raise


def _select_object(obj: Any) -> bool:
    """Select a COM entity through its own Select2/Select4.

    Selecting by object avoids the name resolution SelectByID2 performs, which
    is what makes sketch selection flaky on a localized SolidWorks.
    """
    pythoncom, _ = _com()
    try:
        if obj.Select2(False, 0):
            return True
    except Exception:
        pass
    try:
        if obj.Select4(False, _callout(pythoncom)):
            return True
    except Exception:
        pass
    return False


def _callout(pythoncom: Any) -> Any:
    """An empty IDispatch VARIANT, the value SelectByID2 expects."""
    from win32com.client import VARIANT  # type: ignore

    return VARIANT(pythoncom.VT_DISPATCH, None)


class SwSession:
    """A connection to a running SolidWorks instance."""

    def __init__(self, app: Any) -> None:
        self.app = app

    @classmethod
    def attach(cls, progid: str = "SldWorks.Application") -> "SwSession":
        _, wc = _com()
        try:
            app = wc.GetActiveObject(progid)
        except Exception as exc:
            raise SwError(
                "SolidWorks is not running. Start it, open a document, then retry."
            ) from exc
        return cls(app)

    @property
    def version(self) -> str:
        return str(member(self.app, "RevisionNumber", default=""))

    def _template(self, kind: int, what: str) -> str:
        raw = str(self.app.GetUserPreferenceStringValue(kind) or "")
        first = raw.split(";")[0].strip().strip('"')
        if not first:
            raise SwError(f"SolidWorks has no default {what} template configured")
        return first

    @property
    def template(self) -> str:
        return self._template(8, "part")

    @property
    def assembly_template(self) -> str:
        return self._template(9, "assembly")

    @property
    def drawing_template(self) -> str:
        return self._template(10, "drawing")

    def new_part(self) -> "SwModel":
        model = self.app.NewDocument(self.template, 0, 0, 0) or self.app.ActiveDoc
        if model is None:
            raise SwError("SolidWorks refused to create a new part")
        return SwModel(model, self.app)

    def new_assembly(self) -> Any:
        from .assembly import SwAssembly

        model = (
            self.app.NewDocument(self.assembly_template, 0, 0, 0)
            or self.app.ActiveDoc
        )
        if model is None:
            raise SwError("SolidWorks refused to create a new assembly")
        return SwAssembly(model, self.app)

    def new_drawing(self, template: str | None = None) -> Any:
        from .drawing import SwDrawing

        model = (
            self.app.NewDocument(template or self.drawing_template, 0, 0, 0)
            or self.app.ActiveDoc
        )
        if model is None:
            raise SwError("SolidWorks refused to create a new drawing")
        return SwDrawing(model, self.app)

    def open_document(self, path: str | Path, doctype: int = 1) -> Any:
        """Open a document and return the model itself.

        OpenDoc6 only binds when *every* argument is a VARIANT: the path, the
        type and the options as plain values raise "type mismatch" and the
        document is silently left unopened.  That silent failure is the reason
        AddComponent5 later returns None on a part that "exists".

        doctype is swDocumentTypes_e: 1 part, 2 assembly, 3 drawing.
        """
        pythoncom, _ = _com()
        from win32com.client import VARIANT  # type: ignore

        target = str(Path(path).resolve())
        errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        doc = self.app.OpenDoc6(
            target,
            VARIANT(pythoncom.VT_I4, doctype),
            VARIANT(pythoncom.VT_I4, 0),
            VARIANT(pythoncom.VT_BSTR, ""),
            errors,
            warnings,
        )
        if doc is None:
            raise SwError(
                f"cannot open {target} (errors={errors.value}, "
                f"warnings={warnings.value})"
            )
        return doc

    def open_part(self, path: str | Path) -> "SwModel":
        return SwModel(self.open_document(path, 1), self.app)

    def activate(self, model: Any) -> Any:
        """Bring *model* to the front and return it.

        Several document-level calls (SelectByID2 with plain names, view
        creation) only look at the active document, so an assembly opened by
        path stays inert until it is activated.
        """
        pythoncom, _ = _com()
        from win32com.client import VARIANT  # type: ignore

        title = str(member(model, "GetTitle", default=""))
        if not title:
            raise SwError("cannot activate a document without a title")
        errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        self.app.ActivateDoc2(title, VARIANT(pythoncom.VT_BOOL, False), errors)
        active = self.app.ActiveDoc
        if active is None:
            raise SwError(f"cannot activate {title!r} (errors={errors.value})")
        return active


def close_document(app: Any, target: Any) -> bool:
    """Close the open document saved at *target*, by full path.

    CloseDoc must be given the *full path*, not the title: two documents built
    into different output directories share a title
    ("multi_hole_plate_120x80x6.SLDPRT"), and closing by that ambiguous title
    silently closes nothing at all -- the file stays locked, the retry fails,
    and the error blames the save instead of the close.

    This is a module-level function so it still works after the caller's own
    document handle is dead, where constructing SwModel over it would raise
    while looking up .Extension.
    """
    if app is None:
        return False
    wanted = Path(target).resolve()
    for doc in member(app, "GetDocuments", default=()) or ():
        got = str(member(doc, "GetPathName", default=""))
        if got and Path(got).resolve() == wanted:
            try:
                app.CloseDoc(str(wanted))
            except Exception:
                return False
            return True
    return False


def _back_up(target: Path) -> Path | None:
    """Move the file that is about to be overwritten out of the way.

    Returns the backup path, or None when the move itself failed -- in which
    case the original is still untouched and the caller retries over it.
    """
    backup = target.with_name(target.name + ".bak")
    try:
        target.replace(backup)
    except OSError:
        return None
    return backup


def _discard(backup: Path | None) -> None:
    """Drop the backup once the new save is on disk."""
    if backup is None:
        return
    try:
        backup.unlink(missing_ok=True)
    except OSError:
        pass


def _restore(backup: Path | None, target: Path) -> None:
    """Put the previous save back after a retry that failed too."""
    if backup is None:
        return
    try:
        backup.replace(target)
    except OSError:
        pass


class SwModel:
    """One part document, plus the operations this library needs."""

    #: True once close() has run, so callers can tell a live handle from a
    #: closed document instead of tripping over "-2147221013 document not found".
    closed: bool = False

    def __init__(self, model: Any, app: Any = None) -> None:
        self.model = model
        self.app = app
        self.ext = model.Extension
        self.sm = model.SketchManager
        self.fm = model.FeatureManager
        # SketchManager.AddToDB / DisplayWhenAdded are left at the SolidWorks
        # defaults on purpose: switching them on makes SolidWorks keep every
        # entity as a loose database entry and the resulting profile is refused
        # by the extrude.  Positioned entities are already exact.
        self.last_sketch = ""
        self.sketches: dict[str, "Sketch"] = {}

    # -- identity ---------------------------------------------------------
    @property
    def title(self) -> str:
        return str(self.model.GetTitle)

    @property
    def feature_count(self) -> int:
        return int(self.model.GetFeatureCount)

    # -- selection --------------------------------------------------------
    def select_plane(self, plane: str = "top") -> str:
        name = PLANE_ALIASES.get(plane.strip().lower(), plane)
        pythoncom, _ = _com()
        if not self.ext.SelectByID2(
            name, PLANE, 0, 0, 0, False, 0, _callout(pythoncom), 0
        ):
            raise SwError(f"cannot select plane {name!r}")
        return name

    def select_sketch(self, name: str | None = None) -> str:
        """Select a sketch so the next feature uses it as its profile.

        Name lookup (SelectByID2 with type SKETCH) is unreliable on a Chinese
        SolidWorks: it can return False forever, or select something the
        feature manager refuses.  The sketch object captured when the sketch
        was closed is a stable handle, so it is tried first.
        """
        name = name or self.last_sketch
        self.clear_selection()
        ref = self.sketches.get(name)
        if ref is not None:
            for obj in (ref.feature, ref.obj):
                if obj is not None and _select_object(obj):
                    return name
            self.clear_selection()
        pythoncom, _ = _com()
        if self.ext.SelectByID2(
            name, SKETCH, 0, 0, 0, False, 0, _callout(pythoncom), 0
        ):
            return name
        raise SwError(f"cannot select sketch {name!r}")

    def clear_selection(self) -> None:
        self.model.ClearSelection2(True)

    # -- sketching --------------------------------------------------------
    @contextmanager
    def sketch(self, plane: str = "top") -> Iterator["Sketch"]:
        self.clear_selection()
        self.select_plane(plane)
        self.sm.InsertSketch(True)
        active = member(self.sm, "ActiveSketch")
        name = str(member(active, "Name", default="")) if active is not None else ""
        sk = Sketch(self, name)
        sk.obj = active
        try:
            yield sk
        finally:
            self.sm.InsertSketch(True)
        if not self._has_feature(name):
            raise SwError(
                f"sketch {name!r} was discarded (it had no entities); "
                "check SketchManager.AddToDB and the entity calls"
            )
        sk.feature = (
            member(active, "GetFeature", default=None)
            if active is not None
            else None
        )
        if sk.feature is None:
            sk.feature = self._feature_by_name(name)
        self.last_sketch = name
        self.sketches[name] = sk

    def _feature_by_name(self, name: str) -> Any:
        feature = member(self.model, "FirstFeature")
        while feature is not None:
            if str(member(feature, "Name", default="")) == name:
                return feature
            feature = member(feature, "GetNextFeature")
        return None

    def _has_feature(self, name: str) -> bool:
        feature = member(self.model, "FirstFeature")
        while feature is not None:
            if str(member(feature, "Name", default="")) == name:
                return True
            feature = member(feature, "GetNextFeature")
        return False

    # -- features ---------------------------------------------------------
    def extrude(
        self, depth_mm: float, start_mm: float = 0.0, reverse: bool = True
    ) -> str:
        """Extrude the selected sketch along -Y (reverse=True).

        start_mm shifts the start of the extrusion along Y: negative values
        start below the sketch plane, which is how stacked segments are built.
        """
        depth = depth_mm / 1000.0
        if abs(start_mm) < 1e-9:
            t0, offset = 0, 0.0
        else:
            t0, offset = 3, start_mm / 1000.0
        feature = self.fm.FeatureExtrusion3(
            True, False, reverse, 0, 0, depth, 0.0,
            False, False, False, False, 0.0, 0.0,
            False, False, False, False,
            True, False, True, t0, offset, False,
        )
        if feature is None:
            raise SwError(f"extrude of {depth_mm} mm failed")
        return str(member(feature, "Name", default=""))

    def cut_blind(self, depth_mm: float, flip: bool = False) -> str:
        """Blind cut along -Y from the selected sketch."""
        return self._cut(0, depth_mm / 1000.0, flip, f"blind cut of {depth_mm} mm")

    def cut_through(self, flip: bool = False) -> str:
        """Through-all cut along -Y from the selected sketch."""
        return self._cut(1, 0.01, flip, "through-all cut")

    def _cut(self, end_condition: int, depth: float, flip: bool, what: str) -> str:
        """FeatureCut4 with the 27 positional arguments SolidWorks accepts.

        The argument list has no names in COM, so it is easy to be off by one:
        passing 26 values raises "non-optional parameter", and a misplaced
        False silently returns None.  The order below is the one the recorded
        SolidWorks macros use: ... NormalCut, UseFeatScope, UseAutoSelect,
        then four assembly-scope flags, propagate, T0, StartOffset,
        FlipStartOffset.
        """
        feature = self.fm.FeatureCut4(
            # Dir is False here while extrude passes True: FeatureCut4 reads
            # that argument the opposite way, and True leaves the body intact
            # while returning None.
            True, flip, False,  # Sd (single direction), Flip, Dir (along -Y)
            end_condition, 0, depth, 0.0,
            False, False, False, False, 0.0, 0.0,
            False, False, False, False, False,
            True, True, False, False,  # UseFeatScope, UseAutoSelect, asm scope
            False, 0, 0.0, False, False,
        )
        if feature is None:
            raise SwError(f"{what} failed")
        return str(member(feature, "Name", default=""))

    # -- measurement ------------------------------------------------------
    def measure(self) -> Measure:
        prop = self.ext.CreateMassProperty
        if prop is None:
            raise SwError("mass properties are unavailable (no solid body?)")
        return Measure(
            volume_mm3=float(prop.Volume) * 1e9,
            area_mm2=float(prop.SurfaceArea) * 1e6,
        )

    def bbox_mm(self) -> tuple[float, float, float] | None:
        bodies = self.model.GetBodies2(0, True)
        if not bodies:
            return None
        box = bodies[0].GetBodyBox()
        values = [float(v) for v in box]
        return (
            round((values[3] - values[0]) * 1000.0, 3),
            round((values[4] - values[1]) * 1000.0, 3),
            round((values[5] - values[2]) * 1000.0, 3),
        )

    def bbox_limits_mm(self) -> tuple[float, ...] | None:
        bodies = self.model.GetBodies2(0, True)
        if not bodies:
            return None
        box = bodies[0].GetBodyBox()
        return tuple(round(float(v) * 1000.0, 3) for v in box)

    # -- output -----------------------------------------------------------
    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        pythoncom, _ = _com()
        from win32com.client import VARIANT  # type: ignore

        errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        ok = self._save_as(target, errors, warnings)
        kept: Path | None = None
        if not ok and target.exists():
            # swFileSaveError 1 means the file is already there.  When the old
            # document is still open it holds a lock on the file, so close that
            # document first, then retry once.
            #
            # The file is moved aside, never deleted: this branch is reached for
            # *any* failure -- a full disk, an invalid path, another process
            # holding the file -- so unlinking here would take the user's last
            # good save with it whenever the retry failed as well.
            self.close_document_at(target)
            kept = _back_up(target)
            ok = self._save_as(target, errors, warnings)
            if ok:
                _discard(kept)
                kept = None
            else:
                _restore(kept, target)
                kept = kept if kept.exists() else None
        if not ok:
            hint = f"; previous save kept at {kept}" if kept is not None else ""
            raise SwError(
                f"save failed: {target} (errors={errors.value}, "
                f"warnings={warnings.value}){hint}"
            )
        return target

    def close(self) -> None:
        """Close this document and leave the rest of the session alone.

        Every finished part used to stay loaded for the life of the session,
        which is invisible until it is not: one showcase run leaves nineteen
        documents open (two part sets plus the assembly and its drawing), and
        the next run adds nineteen more.  SolidWorks gets slow and the user's
        machine gets hot for nothing -- the file is already written and
        verified, so holding it open buys nothing.

        Pausing between closes is deliberate.  Closing a batch of documents
        back-to-back crashed this build (ucrtbase 0xc0000409); one at a time
        with a short gap is what the same build survives.
        """
        title = str(member(self.model, "GetTitle", default=""))
        if not title:
            return
        try:
            self.model.ClearSelection2(True)
        except Exception:
            pass
        path = str(member(self.model, "GetPathName", default=""))
        try:
            if self.app is not None:
                # Full path first: two documents built into different output
                # directories share a title, and CloseDoc given an ambiguous
                # title quietly closes nothing.
                self.app.CloseDoc(path or title)
            else:
                self.model.Close()
        except Exception:
            pass
        # Rebuild the flag so a later save is not fooled by a stale handle.
        self.closed = True
        time.sleep(0.25)

    def close_document_at(self, target: Path) -> None:
        """Close any open document that was saved to *target*.

        Rebuilding a part a second time fails with swFileSaveError 1 because
        the previous run's document still holds the .sldprt file open.  Only a
        document whose path matches is closed; the user's own documents are
        never touched.

        Closing is done by full path, for the reason given on close_document().
        """
        close_document(self.app, target)

    def _save_as(self, target: Path, errors: Any, warnings: Any) -> bool:
        pythoncom, _ = _com()
        return bool(
            self.ext.SaveAs(
                str(target), 0, 1, _callout(pythoncom), errors, warnings
            )
        )

    def export_step(self, path: str | Path) -> Path:
        """Write a STEP file through Extension.SaveAs with the silent option.

        The last two arguments are [out] error counters, so they must be passed
        as by-reference VARIANTs; plain ints raise a type mismatch.
        """
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        pythoncom, _ = _com()
        from win32com.client import VARIANT  # type: ignore

        errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        ok = self.ext.SaveAs(
            str(target), 0, 1, _callout(pythoncom), errors, warnings
        )
        if not ok:
            raise SwError(
                f"STEP export failed: {target} (errors={errors.value}, "
                f"warnings={warnings.value})"
            )
        return target


class Sketch:
    """The currently open sketch; entities are added in millimetres."""

    def __init__(self, model: SwModel, name: str) -> None:
        self.model = model
        self.name = name
        #: The ISketch object while the sketch is open, and the feature that
        #: owns it afterwards; both are used to re-select the profile.
        self.obj: Any = None
        self.feature: Any = None

    def circle(self, x_mm: float, z_mm: float, diameter_mm: float) -> Any:
        """Add a circle; coordinates are sketch-plane 2D millimetres.

        SolidWorks sketch entities take the sketch's own (u, v) coordinates and
        project them onto the active plane.  On the top plane u runs along +X
        and v runs along -Z, so a part designed in the XZ plane is mirrored in
        Z; only the span matters for the bounding-box check.  Passing world
        coordinates here (x, 0, z) puts the entity at the wrong place and the
        resulting profile is silently rejected.
        """
        return self.model.sm.CreateCircleByRadius(
            x_mm / 1000.0, z_mm / 1000.0, 0.0, diameter_mm / 2000.0
        )

    def polygon(
        self, x_mm: float, z_mm: float, across_flats_mm: float, sides: int = 6
    ) -> Any:
        """Regular polygon whose *across-flats* distance is given.

        CreatePolygon takes the circumradius when inscribed is True, and the
        across-flats distance is sqrt(3) * r for a hexagon.
        """
        circumradius = (
            across_flats_mm / math.sqrt(3.0) if sides == 6 else across_flats_mm / 2.0
        )
        return self.model.sm.CreatePolygon(
            x_mm / 1000.0, z_mm / 1000.0, 0.0,
            circumradius / 1000.0, 0.0, 0.0,
            sides, True,
        )

    def rectangle(
        self, x0_mm: float, z0_mm: float, x1_mm: float, z1_mm: float
    ) -> Any:
        """Add a rectangle through CreateCenterRectangle (two opposite corners).

        Four separate CreateLine calls look equivalent but are not: the lines
        stay loose segments, the contour never closes, and the extrude is
        refused with no error.  The centre-rectangle API produces one closed
        contour that SolidWorks turns into a region.
        """
        sm = self.model.sm
        return sm.CreateCenterRectangle(
            (x0_mm + x1_mm) / 2000.0,
            (z0_mm + z1_mm) / 2000.0,
            0.0,
            x1_mm / 1000.0,
            z1_mm / 1000.0,
            0.0,
        )