"""Command line entry point: swforge catalog | kinds | demo | stack | build | assemble | draw | verify."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any, Sequence

from . import catalog, parts
from .demo import bolt_stack, showcase
from .generate import build_assembly, draw, generate, reuse_part
from .spec import PartSpec, SpecError, dump_specs, load_specs
from .stack import AssemblySpec, dump_assembly, load_assembly


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="swforge",
        description="Generate GB fasteners and simple non-standard parts in SolidWorks.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("catalog", help="print the built-in GB dimension tables")

    sub.add_parser("kinds", help="list the part kinds and what each one is")

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
        "--resume",
        action="store_true",
        help="verify parts already in the output directory instead of rebuilding them",
    )
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
        "--resume",
        action="store_true",
        help="verify parts already in the output directory instead of rebuilding them",
    )
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
    drawing.add_argument(
        "--no-dimensions",
        action="store_true",
        help="leave the views unannotated (default: auto-dimension each view)",
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


def _unquote(message: str) -> str:
    """Strip the quotes str(KeyError) adds, so the message reads as a sentence."""
    if len(message) >= 2 and message[0] == message[-1] and message[0] in "'\"":
        return message[1:-1]
    return message


def _print_plan(specs: Sequence[PartSpec]) -> None:
    """Print one line per spec, or raise SpecError naming the spec that is wrong.

    The analytic filler is computed here, which makes this the first place a bad
    kind or a missing parameter surfaces -- before SolidWorks is even attached.
    Reporting it as a SpecError keeps that failure on the input path instead of
    turning it into a KeyError traceback the user cannot act on.
    """
    for spec in specs:
        try:
            parts.check_kind(spec.kind)
        except KeyError as error:
            raise SpecError(
                f"spec {spec.name!r}: {_unquote(str(error))}; "
                "run 'swforge kinds' for the list"
            ) from None
        try:
            solid = parts.analytic(spec.kind, spec.params)
        except KeyError as error:
            raise SpecError(
                f"spec {spec.name!r}: missing the {_unquote(str(error))!r} "
                f"parameter; run 'swforge kinds' to see what {spec.kind} needs"
            ) from None
        except (parts.ParamError, TypeError, ValueError) as error:
            raise SpecError(f"spec {spec.name!r}: {error}") from None
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


def _resume_parts(session, specs: Sequence[PartSpec], out: str) -> dict[str, Any]:
    """Verify the parts already in *out*; return the ones that were reusable.

    Keyed by spec name, which is what build_assembly keys *parts_done* by.  A
    part whose file is missing or unreadable is left out, so the caller falls
    back to building it -- resuming must never lose a part that a real build
    would have produced.
    """
    done: dict[str, Any] = {}
    for spec in specs:
        try:
            result = reuse_part(session, spec, out_dir=out)
        except Exception as error:  # noqa: BLE001 - a bad file is not a lost run
            print(f"[SKIP] {spec.kind}/{spec.name}: {type(error).__name__}: {error}")
            continue
        if result is not None:
            done[spec.name] = result
    return done


def _build_specs(
    session,
    specs: Sequence[PartSpec],
    out: str,
    export_step: bool,
    resume: bool = False,
    parts_done: dict[str, Any] | None = None,
) -> int:
    """Build every spec, isolating the ones that fail; return the failure count.

    A single bad part used to end the whole batch, which is the worst answer a
    batch can give: every spec after it never even started.  Now the error is
    printed where it happened and the loop moves on, so the run still ends with
    one verdict per spec it was given.

    *resume* verifies the part already sitting in *out* instead of extruding it
    again; *parts_done* is the same shortcut keyed by name, for a caller that
    has already measured the parts it cares about.
    """
    reusable = parts_done or {}
    failures = 0
    for spec in specs:
        result = reusable.get(spec.name)
        if result is None and resume:
            try:
                result = reuse_part(session, spec, out_dir=out)
            except Exception as error:  # noqa: BLE001 - a stale file is not a lost run
                print(f"[SKIP] {spec.kind}/{spec.name}: {type(error).__name__}: {error}")
                result = None
        try:
            if result is None:
                result = generate(
                    session, spec, out_dir=out, export_step=export_step
                )
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


def _load_assembly(path: str):
    """Load an assembly and validate it, so a bad one fails before SolidWorks.

    validate() is the contract the build relies on: names that line up, mates
    that refer to instances that exist.  Running it here means `verify` and
    `assemble --dry-run` answer for the file itself, without a CAD session.
    """
    assembly = load_assembly(path)
    try:
        assembly.validate()
        # validate() only checks that the names line up.  The parameters inside
        # each part are read here too, because a stack whose washers have a size
        # of 7 or a length of "M8" is just as unusable as one that mates an
        # instance that does not exist -- and until now it reached SolidWorks and
        # failed there, or was never noticed at all on the dry-run path.
        assembly.predict()
    except KeyError as error:
        missing = error.args[0] if error.args else None
        if isinstance(missing, str) and missing.isidentifier():
            raise SpecError(
                f"assembly file {path}: missing the {missing!r} parameter"
            ) from None
        raise SpecError(f"assembly file {path}: {_unquote(str(error))}") from None
    except ValueError as error:
        raise SpecError(f"assembly file {path}: {error}") from None
    return assembly


#: Exit code for "the arguments or the input file were wrong", the same code an
#: unreachable SolidWorks gets: the run did not start, which is not a build that
#: failed (1).  Keeping the two apart is what lets a script retry on 1 but stop
#: on 2.
ARG_ERROR = 2


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI, turning a bad input file into one sentence and exit code 2.

    Every path that reads a file or validates a spec raises :class:`SpecError`
    with a message meant for the person who wrote the file.  Catching it here,
    once, is what keeps a typo from reaching the user as a traceback while still
    letting a genuine bug in swforge raise normally.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return _run(args)
    except SpecError as error:
        print(f"error: {error}", file=sys.stderr)
        return ARG_ERROR


def _run(args: argparse.Namespace) -> int:
    if args.command == "catalog":
        print(catalog.summary())
        return 0

    if args.command == "kinds":
        for row in parts.schema():
            tag = "standard" if row["standard"] else "custom  "
            print(f"{row['kind']:<17} {tag}  {row['summary']}")
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
            assembly = _load_assembly(args.spec)
            print("\n".join(assembly.summary()))
            return 0
        _print_plan(load_specs(args.spec))
        return 0

    if args.command == "assemble":
        if args.verbose:
            _log_stages()
        assembly = _load_assembly(args.spec)
        print("\n".join(assembly.summary()))
        if args.dry_run:
            return 0
        session = _attach()
        if session is None:
            return ARG_ERROR
        parts_done = {}
        if args.resume:
            parts_done = _resume_parts(
                session, list(assembly.parts.values()), args.out
            )
            print(f"resumed {len(parts_done)}/{len(assembly.parts)} parts from disk")
        result = build_assembly(
            session,
            assembly,
            out_dir=args.out,
            export_step=not args.no_step,
            parts_done=parts_done,
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
            return ARG_ERROR
        # The view names are validated inside draw(), so a typo there reaches
        # main() as a SpecError: one sentence on stderr and exit code 2, the
        # same answer every other bad argument gets.
        files = draw(
            session,
            args.model,
            out_dir=args.out,
            views=args.views,
            sheet=args.sheet,
            dimensions=not args.no_dimensions,
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
        return ARG_ERROR

    failures = _build_specs(
        session, specs, args.out, not args.no_step, resume=args.resume
    )
    return 0 if failures == 0 else 1
