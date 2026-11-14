"""Command line entry point: swforge catalog | demo | stack | build | assemble | draw | verify."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Sequence

from . import catalog, parts
from .demo import bolt_stack, showcase
from .generate import build_assembly, draw, generate
from .spec import PartSpec, dump_specs, load_specs
from .stack import AssemblySpec, dump_assembly, load_assembly


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="swforge",
        description="Generate GB fasteners and simple non-standard parts in SolidWorks.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("catalog", help="print the built-in GB dimension tables")

    demo = sub.add_parser("demo", help="write the showcase part spec file")
    demo.add_argument("path", nargs="?", default="showcase.json")

    stack = sub.add_parser("stack", help="write the showcase assembly spec file")
    stack.add_argument("path", nargs="?", default="bolt_stack.json")

    build = sub.add_parser("build", help="build, verify and export parts")
    build.add_argument("spec", help="JSON file with one spec or a list of specs")
    build.add_argument("-o", "--out", default="build", help="output directory")
    build.add_argument("--no-step", action="store_true", help="skip STEP export")
    build.add_argument("--dry-run", action="store_true", help="only print the plan")
    build.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="log each build stage as it starts (to stderr)",
    )

    assemble = sub.add_parser("assemble", help="build parts, mate them, verify")
    assemble.add_argument("spec", help="JSON assembly spec file")
    assemble.add_argument("-o", "--out", default="build", help="output directory")
    assemble.add_argument("--no-step", action="store_true", help="skip STEP export")
    assemble.add_argument("--dry-run", action="store_true", help="only print the plan")
    assemble.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="log each build stage as it starts (to stderr)",
    )

    drawing = sub.add_parser("draw", help="draw standard views of a built model")
    drawing.add_argument("model", help="path to a .sldprt or .sldasm")
    drawing.add_argument("-o", "--out", default="build", help="output directory")
    drawing.add_argument(
        "--sheet", default=None, help="drawing template (.drwdot); default from SW"
    )
    drawing.add_argument(
        "--views",
        default="front,top,right,iso",
        help="comma-separated subset of front,top,right,iso",
    )

    verify = sub.add_parser("verify", help="check analytic answers without SolidWorks")
    verify.add_argument("spec", help="JSON file with one part spec or a list")
    verify.add_argument(
        "--assembly", action="store_true", help="treat the file as an assembly spec"
    )
    return parser


def _log_stages() -> None:
    """Send the library's stage events to stderr, one line per event.

    The library never configures logging and never prints -- that is the
    application's job -- so *this* is where a person who ran "swforge build -v"
    gets to watch a five-minute assembly instead of a silent terminal.
    """
    logger = logging.getLogger("swforge")
    already = any(getattr(h, "_swforge_cli", False) for h in logger.handlers)
    if not already:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
        handler._swforge_cli = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _print_plan(specs: Sequence[PartSpec]) -> None:
    for spec in specs:
        solid = parts.analytic(spec.kind, spec.params)
        bbox = "x".join(f"{v:.2f}" for v in solid.bbox_mm)
        print(
            f"{spec.kind:<17} {spec.name:<16} "
            f"V={solid.volume_mm3:9.1f} mm3  bbox={bbox}"
        )


def _attach():
    from .session import SwError, SwSession

    try:
        session = SwSession.attach()
    except SwError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None
    print(f"SolidWorks {session.version or '(unknown version)'}")
    return session


def _build_specs(
    session, specs: Sequence[PartSpec], out: str, export_step: bool
) -> int:
    """Build every spec, isolating the ones that fail; return the failure count.

    A single bad part used to end the whole batch, which is the worst answer a
    batch can give: every spec after it never even started.  Now the error is
    printed where it happened and the loop moves on, so the run still ends with
    one verdict per spec it was given.
    """
    failures = 0
    for spec in specs:
        try:
            result = generate(session, spec, out_dir=out, export_step=export_step)
        except Exception as error:  # noqa: BLE001 - one spec must not stop the rest
            failures += 1
            print(f"[FAIL] {spec.kind}/{spec.name}: {type(error).__name__}: {error}")
            continue
        print(result.summary())
        for key, path in result.files.items():
            print(f"    {key}: {path}")
        for note in result.notes:
            print(f"    note: {note}")
        if not result.ok:
            failures += 1
            if result.bbox_errors:
                print(f"    bbox errors (mm): {result.bbox_errors}")
    print(f"{len(specs) - failures}/{len(specs)} parts verified")
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "catalog":
        print(catalog.summary())
        return 0

    if args.command == "demo":
        dump_specs(showcase(), args.path)
        print(f"wrote {args.path}")
        return 0

    if args.command == "stack":
        spec = bolt_stack()
        dump_assembly(spec, args.path)
        print("\n".join(spec.summary()))
        print(f"wrote {args.path}")
        return 0

    if args.command == "verify":
        if args.assembly:
            assembly = load_assembly(args.spec)
            print("\n".join(assembly.summary()))
            return 0
        _print_plan(load_specs(args.spec))
        return 0

    if args.command == "assemble":
        if args.verbose:
            _log_stages()
        assembly = load_assembly(args.spec)
        print("\n".join(assembly.summary()))
        if args.dry_run:
            return 0
        session = _attach()
        if session is None:
            return 2
        result = build_assembly(
            session,
            assembly,
            out_dir=args.out,
            export_step=not args.no_step,
        )
        print(result.summary())
        for key, path in result.files.items():
            print(f"    {key}: {path}")
        if result.mates:
            print(f"    mates: {', '.join(result.mates)}")
        return 0 if result.ok else 1

    if args.command == "draw":
        session = _attach()
        if session is None:
            return 2
        views = tuple(v.strip() for v in args.views.split(",") if v.strip())
        files = draw(
            session, args.model, out_dir=args.out, views=views, sheet=args.sheet
        )
        for key, value in files.items():
            print(f"{key}: {value}")
        return 0

    if args.verbose:
        _log_stages()
    specs = load_specs(args.spec)
    _print_plan(specs)
    if args.dry_run:
        return 0

    session = _attach()
    if session is None:
        return 2

    failures = _build_specs(session, specs, args.out, not args.no_step)
    return 0 if failures == 0 else 1
