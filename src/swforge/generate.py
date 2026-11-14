"""Build parts and assemblies in SolidWorks, and refuse to accept them unless
the numbers match.

The contract is simple: every generated solid must reproduce the closed-form
volume and bounding box from swforge.parts within tolerance.  A mismatch means the
model is wrong, not the arithmetic, so the build fails loudly instead of writing
a quiet bad file.

Assemblies extend the same contract by one level: the volume of the joined
components plus the envelope predicted from their placements must match the mass
properties and bounding box SolidWorks reports for the assembly itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import parts
from .assembly import MATE_COINCIDENT, MATE_DISTANCE, world_box_mm
from .geometry import Solid, relative_error
from .progress import Progress, emit
from .session import SwError, SwModel
from .spec import PartSpec
from .stack import AssemblySpec

#: Bounding boxes are compared with this absolute slack, in millimetres.
BBOX_SLACK_MM = 0.05

#: Prefix for the orientations stored on a model before a drawing refers to them.
DRAWING_VIEW_NAME = "swforge_iso"


@dataclass
class BuildResult:
    spec: PartSpec
    expected: Solid
    measured_volume_mm3: float
    measured_bbox_mm: tuple[float, float, float] | None
    volume_error: float
    bbox_errors: dict[str, float] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        if self.volume_error > self.spec.tolerance:
            return False
        return all(error <= 1e-6 for error in self.bbox_errors.values())

    def summary(self) -> str:
        status = "PASS" if self.ok else "FAIL"
        bbox = self.measured_bbox_mm
        bbox_text = "x".join(f"{v:.2f}" for v in bbox) if bbox else "no body"
        return (
            f"[{status}] {self.spec.kind}/{self.spec.name}: "
            f"volume {self.measured_volume_mm3:.1f} mm3 "
            f"(expected {self.expected.volume_mm3:.1f}, "
            f"err {self.volume_error * 100:.3f}%), bbox {bbox_text}"
        )


@dataclass
class AssemblyResult:
    spec: AssemblySpec
    expected: Solid
    measured_volume_mm3: float
    measured_bbox_mm: tuple[float, float, float] | None
    volume_error: float
    bbox_errors: dict[str, float] = field(default_factory=dict)
    mates: list[str] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    #: Part key -> the exception that stopped it.  A failed part is data, not an
    #: abort: the other parts are still built and the assembly still gets made
    #: from what survived, so one bad washer does not cost the whole run.
    failures: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        if self.failures:
            return False
        if self.volume_error > self.spec.tolerance:
            return False
        return all(error <= 1e-6 for error in self.bbox_errors.values())

    def summary(self) -> str:
        status = "PASS" if self.ok else "FAIL"
        bbox = self.measured_bbox_mm
        bbox_text = "x".join(f"{v:.2f}" for v in bbox) if bbox else "no body"
        tail = f", {len(self.mates)} mates"
        if self.failures:
            tail += f", {len(self.failures)} failed"
        return (
            f"[{status}] assembly/{self.spec.name}: "
            f"volume {self.measured_volume_mm3:.1f} mm3 "
            f"(expected {self.expected.volume_mm3:.1f}, "
            f"err {self.volume_error * 100:.3f}%), bbox {bbox_text}{tail}"
        )


def _bbox_errors(
    expected: tuple[float, float, float],
    measured: tuple[float, float, float] | None,
) -> dict[str, float]:
    if measured is None:
        return {"x": float("inf"), "y": float("inf"), "z": float("inf")}
    slack = BBOX_SLACK_MM
    return {
        axis: max(0.0, abs(got - want) - slack)
        for axis, got, want in zip("xyz", measured, expected)
    }


def generate(
    session: Any,
    spec: PartSpec,
    out_dir: str | Path = "build",
    export_step: bool = True,
    save_part: bool = True,
    on_progress: Progress | None = None,
) -> BuildResult:
    """Build one part, verify it, and write .sldprt/.step files.

    Raises ValueError before touching SolidWorks when the parameters are
    invalid, so a bad spec never leaves a half-built document behind.

    *on_progress* receives "part.building", "part.built" and "part.saved" as the
    build moves; a caller that shows a progress bar or a log line needs those
    three to tell a slow build from a stuck one.
    """
    expected = parts.analytic(spec.kind, spec.params)
    emit(on_progress, "part.building", kind=spec.kind, name=spec.name)

    model = session.new_part()
    try:
        parts.build(model, spec.kind, spec.params)
        measure = model.measure()
        bbox = model.bbox_mm()
        result = BuildResult(
            spec=spec,
            expected=expected,
            measured_volume_mm3=measure.volume_mm3,
            measured_bbox_mm=bbox,
            volume_error=relative_error(expected.volume_mm3, measure.volume_mm3),
            bbox_errors=_bbox_errors(expected.bbox_mm, bbox),
        )
        emit(
            on_progress,
            "part.built",
            kind=spec.kind,
            name=spec.name,
            volume_mm3=round(measure.volume_mm3, 3),
            ok=result.ok,
        )
        stem = Path(out_dir) / f"{spec.kind}_{spec.name}"
        if save_part:
            result.files["part"] = str(model.save(stem.with_suffix(".sldprt")))
        if export_step:
            result.files["step"] = str(model.export_step(stem.with_suffix(".step")))
        emit(on_progress, "part.saved", kind=spec.kind, name=spec.name, files=len(result.files))
        return result
    finally:
        # Close as soon as the files are written.  Leaving documents open is
        # not free: nineteen of them accumulate over one showcase run and the
        # next run starts on top of that, which slows SolidWorks and heats the
        # machine for a document nobody reads again.  SwModel.close() paces the
        # closes, because closing a batch back-to-back crashed this build.
        if save_part:
            model.close()


def reuse_part(
    session: Any,
    spec: PartSpec,
    out_dir: str | Path = "build",
) -> BuildResult | None:
    """Verify a part that is already on disk instead of building it again.

    Returns None when the file is missing, so the caller can fall back to
    generate().  A resumed run reads the saved document, measures it and applies
    exactly the same closed-form check -- the numbers are re-derived, not
    trusted from a previous run, so a file edited by hand still has to survive.
    """
    stem = Path(out_dir) / f"{spec.kind}_{spec.name}"
    part = stem.with_suffix(".sldprt")
    if not part.exists():
        return None
    expected = parts.analytic(spec.kind, spec.params)
    model = session.open_part(part)
    try:
        measure = model.measure()
        bbox = model.bbox_mm()
        result = BuildResult(
            spec=spec,
            expected=expected,
            measured_volume_mm3=measure.volume_mm3,
            measured_bbox_mm=bbox,
            volume_error=relative_error(expected.volume_mm3, measure.volume_mm3),
            bbox_errors=_bbox_errors(expected.bbox_mm, bbox),
        )
    finally:
        model.close()
    result.files["part"] = str(part)
    step = stem.with_suffix(".step")
    if step.exists():
        result.files["step"] = str(step)
    result.notes.append("verified from disk, not rebuilt")
    return result


def build_assembly(
    session: Any,
    spec: AssemblySpec,
    out_dir: str | Path = "build",
    export_step: bool = True,
    save_parts: bool = True,
    parts_done: dict[str, BuildResult] | None = None,
    on_progress: Progress | None = None,
) -> AssemblyResult:
    """Build every part, insert them into an assembly, mate it, then verify.

    The parts are written first because AddComponent5 inserts *files*: a
    component cannot carry an in-memory body, so each part has to exist on disk
    before the assembly document refers to it.

    Pass *parts_done* to reuse parts that were already built and verified in
    this session.  Without it every part is rebuilt into the same directory,
    which overwrites the file an open document still holds -- correct, but it
    doubles the SolidWorks work and pays the close-and-retry path for nothing.

    A part that fails is recorded in *failures* and skipped, not raised: a batch
    that loses one washer should still finish the other nine parts and still
    mate what survived.  Only when *every* part fails is there nothing left to
    assemble, and then the result says so instead of opening an empty document.

    *on_progress* gets the part events from each nested build, plus one event
    per assembly phase: "assembly.parts", "assembly.inserting",
    "assembly.mating", "assembly.saving" and "assembly.closed".  A ten-part
    assembly spends most of its wall clock inside this function, so a caller
    that only hears about parts sees nothing at all between the last part and
    the final file.
    """
    spec.validate()
    out = Path(out_dir)
    reusable = parts_done or {}
    part_results: dict[str, BuildResult] = {}
    failures: dict[str, str] = {}
    notes: list[str] = []
    expected = spec.predict()

    for key, part_spec in spec.parts.items():
        already = reusable.get(key)
        if already is not None and "part" in already.files:
            part_results[key] = already
            continue
        try:
            part_results[key] = generate(
                session,
                part_spec,
                out_dir=out,
                export_step=export_step,
                save_part=save_parts,
                on_progress=on_progress,
            )
        except Exception as error:  # noqa: BLE001 - isolating it is the point
            failures[key] = f"{type(error).__name__}: {error}"
            notes.append(f"part {key!r} failed: {failures[key]}")

    emit(on_progress, "assembly.parts", built=len(part_results), failed=len(failures))

    if not part_results:
        # Every part failed, so there is nothing to insert and no reason to ask
        # SolidWorks for an empty assembly: report what went wrong instead.
        notes.append("no part was built, so no assembly was created")
        return AssemblyResult(
            spec=spec,
            expected=expected,
            measured_volume_mm3=0.0,
            measured_bbox_mm=None,
            volume_error=float("inf"),
            bbox_errors=_bbox_errors(expected.bbox_mm, None),
            notes=notes,
            failures=failures,
        )

    assembly = session.new_assembly()
    emit(on_progress, "assembly.inserting", components=len(spec.placements))
    for placement in spec.placements:
        done = part_results.get(placement.part)
        part_file = done.files.get("part") if done is not None else None
        if not part_file:
            reason = (
                "failed to build" if placement.part in failures else "was not written to disk"
            )
            notes.append(
                f"instance {placement.instance!r} skipped: part "
                f"{placement.part!r} {reason}"
            )
            continue
        assembly.add_component(
            part_file,
            placement.x_mm,
            placement.y_mm,
            placement.z_mm,
            instance=placement.instance,
        )

    mates: list[str] = []
    emit(on_progress, "assembly.mating", mates=len(spec.mates))
    for mate in spec.mates:
        try:
            first = assembly.find(mate.first)
            second = assembly.find(mate.second)
        except SwError as error:
            # A mate needs both components present; losing one part must not
            # cost the mates that do not mention it.
            notes.append(f"mate {mate.first!r}-{mate.second!r} skipped: {error}")
            continue
        kind = MATE_COINCIDENT if mate.kind == "coincident" else MATE_DISTANCE
        mates.append(
            assembly.mate_planes(
                first,
                second,
                plane=mate.plane,
                mate_type=kind,
                distance_mm=mate.distance_mm,
                flip=mate.flip,
            )
        )

    volume_mm3, bbox = 0.0, None
    try:
        volume_mm3, _ = assembly.measure()
        bbox = _assembly_bbox(assembly)
    except Exception as error:  # noqa: BLE001 - report, do not lose the parts
        failures["<assembly>"] = f"{type(error).__name__}: {error}"
        notes.append(f"assembly measurement failed: {failures['<assembly>']}")

    result = AssemblyResult(
        spec=spec,
        expected=expected,
        measured_volume_mm3=volume_mm3,
        measured_bbox_mm=bbox,
        volume_error=relative_error(expected.volume_mm3, volume_mm3),
        bbox_errors=_bbox_errors(expected.bbox_mm, bbox),
        mates=mates,
        notes=notes,
        failures=failures,
    )
    stem = out / f"assembly_{spec.name}"
    emit(on_progress, "assembly.saving", name=spec.name)
    try:
        result.files["assembly"] = str(assembly.save(stem.with_suffix(".sldasm")))
        if export_step:
            result.files["step"] = str(assembly.export_step(stem.with_suffix(".step")))
    except Exception as error:  # noqa: BLE001 - the parts are still on disk
        failures["<assembly>"] = f"{type(error).__name__}: {error}"
        notes.append(f"assembly save failed: {failures['<assembly>']}")
    finally:
        # The assembly is on disk and verified; keeping it loaded only piles
        # another document onto a session that already built every part.
        assembly.close()
        emit(on_progress, "assembly.closed", name=spec.name, files=len(result.files))
    return result


def _assembly_bbox(assembly: Any) -> tuple[float, float, float] | None:
    """Bounding box of the assembly, in assembly coordinates.

    Each component's body box has to be mapped through its own placement before
    the boxes are unioned.  GetBodyBox() answers in *part* coordinates even when
    it is asked of an assembly component -- all four bolts of the showcase report
    the same box while sitting in different corners -- so a naive union adds one
    whole part width to the envelope.  That is exactly the 127.51 x 45.30 x 86.50
    this used to report against a predicted 120.00 x 45.30 x 80.00.
    """
    lows = [float("inf")] * 3
    highs = [float("-inf")] * 3
    found = False
    for comp in assembly.components():
        box = world_box_mm(comp)
        if box is None:
            continue
        lo, hi = box
        for axis in range(3):
            lows[axis] = min(lows[axis], lo[axis])
            highs[axis] = max(highs[axis], hi[axis])
        found = True
    if not found:
        return None
    return tuple(round(highs[a] - lows[a], 3) for a in range(3))


def draw(
    session: Any,
    model_path: str | Path,
    out_dir: str | Path = "build",
    views: tuple[str, ...] = ("front", "top", "right", "iso"),
    sheet: str | None = None,
) -> dict[str, str]:
    """Create a drawing for *model_path*, then export .slddrw and .pdf.

    Named views are used rather than the star tokens (star-Front and friends)
    because CreateDrawViewFromModelView3 refuses those.  The orientations are
    stored on the model first, which is why this function reopens and activates
    it before touching the drawing.
    """
    from .drawing import VIEW_FRONT, VIEW_ISOMETRIC, VIEW_RIGHT, VIEW_TOP

    target = Path(model_path).resolve()
    doctype = 2 if target.suffix.lower() == ".sldasm" else 1
    model = session.open_document(target, doctype)
    session.activate(model)

    ids = {
        "front": VIEW_FRONT,
        "right": VIEW_RIGHT,
        "top": VIEW_TOP,
        "iso": VIEW_ISOMETRIC,
    }
    for name in views:
        model.ShowNamedView2("", ids[name])
        model.NameView(f"{DRAWING_VIEW_NAME}_{name}")

    drawing = session.new_drawing(sheet) if sheet else session.new_drawing()
    positions = {
        "front": (60.0, 140.0),
        "top": (60.0, 70.0),
        "right": (170.0, 140.0),
        "iso": (190.0, 70.0),
    }
    placed: list[str] = []
    for name in views:
        x, y = positions.get(name, (60.0, 120.0))
        placed.append(
            drawing.add_named_view(target, f"{DRAWING_VIEW_NAME}_{name}", x, y)
        )

    stem = Path(out_dir) / f"drawing_{target.stem}"
    files = {"drawing": str(drawing.save(stem.with_suffix(".slddrw")))}
    files["pdf"] = str(drawing.export_pdf(stem.with_suffix(".pdf")))
    files["views"] = ", ".join(placed)
    # Close the drawing first: it holds the model open through its view
    # references, so the model goes second.  *model* here is the raw COM
    # document, so it needs the wrapper before it can be closed.
    drawing.close()
    SwModel(model, session.app).close()
    return files
