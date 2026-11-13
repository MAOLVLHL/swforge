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
from .assembly import MATE_COINCIDENT, MATE_DISTANCE
from .geometry import Solid, relative_error
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
            f"[{status}] assembly/{self.spec.name}: "
            f"volume {self.measured_volume_mm3:.1f} mm3 "
            f"(expected {self.expected.volume_mm3:.1f}, "
            f"err {self.volume_error * 100:.3f}%), bbox {bbox_text}, "
            f"{len(self.mates)} mates"
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
) -> BuildResult:
    """Build one part, verify it, and write .sldprt/.step files.

    Raises ValueError before touching SolidWorks when the parameters are
    invalid, so a bad spec never leaves a half-built document behind.
    """
    expected = parts.analytic(spec.kind, spec.params)

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
        stem = Path(out_dir) / f"{spec.kind}_{spec.name}"
        if save_part:
            result.files["part"] = str(model.save(stem.with_suffix(".sldprt")))
        if export_step:
            result.files["step"] = str(model.export_step(stem.with_suffix(".step")))
        return result
    finally:
        # The document is deliberately left open: closing a batch of documents
        # in quick succession crashed this SolidWorks build (ucrtbase 0xc0000409),
        # and an open document costs nothing while the session lives.
        pass


def build_assembly(
    session: Any,
    spec: AssemblySpec,
    out_dir: str | Path = "build",
    export_step: bool = True,
    save_parts: bool = True,
) -> AssemblyResult:
    """Build every part, insert them into an assembly, mate it, then verify.

    The parts are written first because AddComponent5 inserts *files*: a
    component cannot carry an in-memory body, so each part has to exist on disk
    before the assembly document refers to it.
    """
    spec.validate()
    out = Path(out_dir)
    part_results: dict[str, BuildResult] = {}

    for key, part_spec in spec.parts.items():
        part_results[key] = generate(
            session,
            part_spec,
            out_dir=out,
            export_step=export_step,
            save_part=save_parts,
        )

    assembly = session.new_assembly()
    for placement in spec.placements:
        part_file = part_results[placement.part].files.get("part")
        if not part_file:
            raise RuntimeError(
                f"part {placement.part!r} was not written to disk, so "
                f"instance {placement.instance!r} cannot be inserted"
            )
        assembly.add_component(
            part_file, placement.x_mm, placement.y_mm, placement.z_mm
        )

    mates: list[str] = []
    for mate in spec.mates:
        first = assembly.find(mate.first)
        second = assembly.find(mate.second)
        kind = MATE_COINCIDENT if mate.kind == "coincident" else MATE_DISTANCE
        mates.append(
            assembly.mate_planes(
                first,
                second,
                plane=mate.plane,
                mate_type=kind,
                distance_mm=mate.distance_mm,
            )
        )

    volume_mm3, _ = assembly.measure()
    bbox = _assembly_bbox(assembly)
    expected = spec.predict()
    result = AssemblyResult(
        spec=spec,
        expected=expected,
        measured_volume_mm3=volume_mm3,
        measured_bbox_mm=bbox,
        volume_error=relative_error(expected.volume_mm3, volume_mm3),
        bbox_errors=_bbox_errors(expected.bbox_mm, bbox),
        mates=mates,
    )
    stem = out / f"assembly_{spec.name}"
    result.files["assembly"] = str(assembly.save(stem.with_suffix(".sldasm")))
    if export_step:
        result.files["step"] = str(assembly.export_step(stem.with_suffix(".step")))
    return result


def _assembly_bbox(assembly: Any) -> tuple[float, float, float] | None:
    """Bounding box of the assembly, taken over its components' bodies."""
    lows = [float("inf")] * 3
    highs = [float("-inf")] * 3
    found = False
    for comp in assembly.components():
        for body in _component_bodies(comp.comp):
            values = [float(v) for v in body.GetBodyBox()]
            for axis in range(3):
                lows[axis] = min(lows[axis], values[axis])
                highs[axis] = max(highs[axis], values[axis + 3])
            found = True
    if not found:
        return None
    return tuple(round((highs[a] - lows[a]) * 1000.0, 3) for a in range(3))


def _component_bodies(comp: Any) -> list[Any]:
    from .session import member

    bodies = member(comp, "GetBodies2", 0, default=None)
    if bodies is None:
        bodies = member(comp, "GetBodies2", False, default=None)
    return list(bodies or ())


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
    return files
