"""Drawing documents: standard views, named views and PDF output.

Two SolidWorks behaviours shape this module:

* CreateDrawViewFromModelView3 accepts only a *named* view.  The built-in
  tokens (`*Front`, `*Isometric`, ...) all return None; the orientation has to
  be stored on the model first with NameView, and the drawing then refers to it
  by that name.  Create3rdAngleViews2 side-steps the naming entirely by adding
  front/top/right in one call, which is what the standard-sheet path uses.
* Every call acts on the active document, and a drawing created right after a
  model is not active.  SwSession.new_drawing returns a fresh document that is
  active already; a drawing opened by path must be activated first.

Importing the model's dimensions is not an option here: InsertModelAnnotations3
answers None and adds nothing on a model whose sketches were never dimensioned
by hand, which is every model this library builds.  Drawing-level AutoDimension
is what fills a sheet, and it only reaches the view that SolidWorks considers
active -- so a view has to be dimensioned the moment it is created (see
SwDrawing.auto_dimension).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .session import SwError, _callout, _com, member

#: swAutodimScheme_e: how the dimensions are laid out from the datum.
AUTODIM_BASELINE = 1
AUTODIM_ORDINATE = 2
AUTODIM_CHAIN = 3

#: swAutodimEntities_e: "all" rather than "what is preselected".
AUTODIM_ALL_ENTITIES = 1

#: swStandardViews_e values accepted by ShowNamedView2.
VIEW_FRONT = 1
VIEW_RIGHT = 3
VIEW_TOP = 5
VIEW_ISOMETRIC = 7


class SwDrawing:
    """A drawing document, built around model views."""

    def __init__(self, model: Any, app: Any = None) -> None:
        self.model = model
        self.app = app
        self.ext = model.Extension

    # -- identity ---------------------------------------------------------
    @property
    def title(self) -> str:
        return str(member(self.model, "GetTitle", default=""))

    @property
    def sheet(self) -> Any:
        sheet = member(self.model, "GetCurrentSheet", default=None)
        if sheet is None:
            raise SwError("the drawing has no current sheet")
        return sheet

    @property
    def sheet_name(self) -> str:
        return str(member(self.sheet, "GetName", default=""))

    def set_scale(self, numerator: float, denominator: float = 1.0) -> None:
        """Set the sheet scale; views added afterwards inherit it."""
        self.sheet.SetScale(
            float(numerator), float(denominator), True, False, False
        )

    # -- views ------------------------------------------------------------
    def add_standard_views(self, model_path: str | Path) -> list[str]:
        """Insert front, top and right views in one call.

        Create3rdAngleViews2 places three views at the sheet's default
        positions; it is the only view API that works without a pre-named
        orientation on the model.
        """
        target = str(Path(model_path).resolve())
        views = self.model.Create3rdAngleViews2(target)
        if not views:
            raise SwError(
                f"cannot create standard views for {Path(target).name}; the "
                "model document has to be open in this session first"
            )
        return [str(member(v, "Name", default="")) for v in views]

    def add_named_view(
        self, model_path: str | Path, view_name: str, x_mm: float, y_mm: float
    ) -> str:
        """Insert the orientation saved on the model as *view_name*.

        The name comes from SwAssembly.name_view / SwModel.name_view; `*Front`
        and friends are refused here even though they look like the documented
        argument.
        """
        target = str(Path(model_path).resolve())
        view = self.model.CreateDrawViewFromModelView3(
            target, view_name, x_mm / 1000.0, y_mm / 1000.0, 0.0
        )
        if view is None:
            raise SwError(
                f"cannot insert view {view_name!r}; the model must be open and "
                "carry an orientation saved under that exact name"
            )
        return str(member(view, "Name", default=""))

    def views(self) -> list[str]:
        sheet = self.sheet
        found = member(sheet, "GetViews", default=()) or ()
        return [str(member(v, "Name", default="")) for v in found]

    def _view(self, view_name: str) -> Any:
        """The view object whose Name is *view_name*.

        The name has to come from SolidWorks (view.Name), not from the
        orientation that was asked for: a view inserted as swforge_front is
        called "Drawing View1" on the sheet, and ActivateView only answers to
        the name SolidWorks gave it.
        """
        sheet = self.sheet
        found = member(sheet, "GetViews", default=()) or ()
        for view in found:
            if str(member(view, "Name", default="")) == view_name:
                return view
        raise SwError(f"no view named {view_name!r}")

    def view_scale(self, view_name: str) -> tuple[float, float]:
        view = self._view(view_name)
        # ScaleRatio is one two-element array.  Reading it twice, as this used
        # to, hands back the same pair twice, so a 1:4 view reported itself as
        # 1:1 to every caller.
        ratio = member(view, "ScaleRatio", default=(1.0, 1.0))
        if isinstance(ratio, (int, float)):
            return (float(ratio), 1.0)
        return (float(ratio[0]), float(ratio[1]))

    # -- dimensions -------------------------------------------------------
    def dimension_count(self, view_name: str) -> int:
        """How many dimensions appear on *view_name*; 0 means it carries none."""
        count = member(self._view(view_name), "GetDisplayDimensionCount", default=0)
        return int(count or 0)

    def auto_dimension(
        self,
        view_name: str,
        scheme: int = AUTODIM_BASELINE,
        horizontal_placement: int = 1,
        vertical_placement: int = 1,
    ) -> int:
        """Dimension *view_name* with SolidWorks' own auto-dimension, return how
        many dimensions it gained.

        InsertModelAnnotations3 would be the obvious way to put the model's
        dimensions on a sheet, and it is a dead end: it answers None and leaves
        every view at zero dimensions on a model whose sketches were never
        dimensioned by hand -- which is every model built by this library.  The
        drawing-level AutoDimension generates the dimensions from the view's
        own projection instead, and it is the only thing that fills a sheet.

        The catch is that it applies to the *active view*, and SolidWorks does
        not make a newly created view active.  Activating all four views after
        the fact does not work either: ActivateView answers True and names the
        right view, but all the call's dimensions still land on the last view
        that was created (front/top/right 0, iso 9, measured).  Creating a view
        and dimensioning it immediately is the sequence that works
        (front 4 / top 7 / right 4 / iso 6 on the same part).
        """
        before = self.dimension_count(view_name)
        self.activate_view(view_name)
        self.model.AutoDimension(
            AUTODIM_ALL_ENTITIES,
            scheme,
            horizontal_placement,
            scheme,
            vertical_placement,
        )
        return self.dimension_count(view_name) - before

    def activate_view(self, view_name: str) -> None:
        """Make *view_name* the view that AutoDimension acts on."""
        if not self.model.ActivateView(view_name):
            raise SwError(
                f"cannot activate drawing view {view_name!r}; the name has to "
                "be the one SolidWorks assigned, not the orientation"
            )

    # -- output -----------------------------------------------------------
    def save(self, path: str | Path) -> Path:
        target = Path(path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        pythoncom, _ = _com()
        from win32com.client import VARIANT  # type: ignore

        errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        if self.ext.SaveAs(str(target), 0, 1, _callout(pythoncom), errors, warnings):
            return target
        if target.exists():
            # Same lock as parts: the open document holds the old file.
            raise SwError(
                f"save failed, the file is locked by an open document: {target} "
                f"(errors={errors.value}, warnings={warnings.value})"
            )
        raise SwError(
            f"save failed: {target} (errors={errors.value}, "
            f"warnings={warnings.value})"
        )

    def export_pdf(self, path: str | Path) -> Path:
        """Export the sheet as PDF.

        ExportData is an empty dispatch for the drawing case and `None` is
        refused outright, so the empty dispatch is tried first and the plain
        call only as a fallback.
        """
        target = Path(path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        pythoncom, _ = _com()
        from win32com.client import VARIANT  # type: ignore

        for export_data in (_callout(pythoncom), None):
            errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            try:
                ok = self.ext.SaveAs(
                    str(target), 0, 1, export_data, errors, warnings
                )
            except Exception:
                continue
            if ok and target.exists():
                return target
        raise SwError(f"PDF export failed: {target}")

    def close(self) -> None:
        """Close the drawing document once its files are written.

        Same reason as SwModel.close(): a finished drawing is one more loaded
        document, and it holds its model open through the view references -- so
        the drawing goes before the model it draws.
        """
        from .session import SwModel

        SwModel(self.model, self.app).close()
