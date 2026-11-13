"""Build the showcase parts, a bolted assembly, and a drawing -- end to end.

Usage:
    python examples/build_showcase.py [output-dir] [--resume]

Pass --resume to verify the parts already sitting in the output directory
instead of extruding them again; useful when only the assembly or the drawing
stage needs another attempt.

SolidWorks must already be open; the script attaches to the running instance,
builds each part, checks volume and bounding box against the analytic answer,
joins four bolts and a plate into an assembly, mates them, draws the assembly,
and exits non-zero if any check disagrees.

Every stage is guarded separately so a drawing failure on one build of
SolidWorks still leaves the parts and the assembly on disk to inspect.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from swforge.demo import bolt_stack, showcase  # noqa: E402
from swforge.generate import build_assembly, draw, generate, reuse_part  # noqa: E402
from swforge.session import SwError, SwSession  # noqa: E402


def main(argv: list[str]) -> int:
    args = [value for value in argv[1:] if not value.startswith("--")]
    resume = "--resume" in argv
    out_dir = Path(args[0] if args else "build")
    try:
        session = SwSession.attach()
    except SwError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"attached to SolidWorks {session.version or '(unknown)'}")
    failures = 0

    print("\n-- parts " + "-" * 60)
    specs = showcase()
    built = {}
    for spec in specs:
        # --resume verifies a part that is already on disk instead of extruding
        # it again.  Rerunning the whole showcase to get past a later stage used
        # to rebuild eight verified parts and pay a minute of SolidWorks work
        # for nothing; the check still runs, only the modelling is skipped.
        result = reuse_part(session, spec, out_dir=out_dir) if resume else None
        if result is None:
            result = generate(session, spec, out_dir=out_dir)
        built[spec.name] = result
        print(result.summary())
        if not result.ok:
            failures += 1
            print(f"    bbox errors: {result.bbox_errors}")
        for kind, path in result.files.items():
            print(f"    {kind}: {path}")
    print(f"{len(specs) - failures}/{len(specs)} parts verified")

    print("\n-- assembly " + "-" * 57)
    stack = bolt_stack()
    assembly = build_assembly(
        session, stack, out_dir=out_dir, parts_done=built
    )
    print(assembly.summary())
    if not assembly.ok:
        failures += 1
        print(f"    bbox errors: {assembly.bbox_errors}")
    for kind, path in assembly.files.items():
        print(f"    {kind}: {path}")
    if assembly.mates:
        print(f"    mates: {', '.join(assembly.mates)}")

    print("\n-- drawing " + "-" * 58)
    assembly_file = assembly.files.get("assembly")
    if assembly_file:
        try:
            files = draw(session, assembly_file, out_dir=out_dir)
        except SwError as exc:
            failures += 1
            print(f"drawing failed: {exc}")
        else:
            for kind, value in files.items():
                print(f"    {kind}: {value}")

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
