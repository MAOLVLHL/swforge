# swforge

Parametric SolidWorks parts, assemblies, and drawings — **checked against closed-form geometry**.

Most CAD automation scripts build something and hope. swforge describes every part twice:
once as pure-Python mathematics (no SolidWorks, runs anywhere, runs in CI), and once as a
sequence of SolidWorks features. The build only passes when the two agree on volume and
bounding box, to within 0.1 %.

```
[PASS] hex_bolt/M8x40: volume 2786.3 mm3 (expected 2786.3, err 0.000%), bbox 15.01x45.30x13.00
```

中文简介：给 SolidWorks 用的参数化零件/装配/工程图库。每个零件都有解析解，建模后先算体积与包围盒
再比对，误差超过 0.1% 直接判失败——不是"能导出 STEP 就算成功"。

## Why

Generating CAD from code fails silently. A sketch that loses a constraint, an extrusion that
returns `None`, a cut whose direction flag is wrong — SolidWorks reports none of it. The part
looks plausible and the volume is quietly 6 % off.

swforge makes that failure impossible to miss: each part carries a closed-form volume and
bounding box, and the builder refuses to call the result good until the measured model matches.

## Install

```bash
pip install -e .            # analytic half only, works on any OS
pip install -e ".[com]"     # adds pywin32 so the SolidWorks half works
```

Requires Python 3.10+ and, for real modelling, a running SolidWorks instance on Windows.
Importing the package never touches COM, so `swforge.parts`, `swforge.geometry` and
`swforge.stack` are fully testable without SolidWorks.

## Quick start

```bash
swforge catalog                 # print the built-in GB dimension tables
swforge kinds                   # list the part kinds and what each one is
swforge demo showcase.json      # write the eight-part showcase spec
swforge verify showcase.json    # analytic answers only — no SolidWorks needed
swforge build  showcase.json -o build
```

`build` attaches to the running SolidWorks, builds each part, compares against the analytic
answer, and writes `.sldprt` + `.step`. Exit code is non-zero if any part disagrees.

`-o` is resolved against *your* current directory before it is handed to COM, so a relative
`build` lands next to the spec wherever you ran the command. (It did not always: SolidWorks
expands a relative path against its own working directory, so until this was fixed the line
above wrote into whatever folder the application was started from and failed with
`save failed: build\washer_M8.sldprt (errors=1, warnings=0)`.)

A run of eight parts takes minutes, so `build` and `assemble` accept `-v` to log every stage to
stderr as it starts:

```
15:04:12  part.building kind=hex_bolt name=M8x40
15:04:19  part.built kind=hex_bolt name=M8x40 volume_mm3=2786.34 ok=True
15:04:19  part.saved kind=hex_bolt name=M8x40 files=2
```

The same events reach a caller that wants to draw its own progress bar:

```python
from swforge.generate import build_assembly

result = build_assembly(
    session, spec, on_progress=lambda stage, payload: bar.update(stage, payload)
)
```

Stages are `part.building`, `part.built`, `part.saved`, `part.reused`, then `assembly.parts`,
`assembly.inserting`, `assembly.mating`, `assembly.saving`, `assembly.closed`. The library itself
never prints and never configures logging — a callback that raises is logged and the build
continues, because a broken progress bar must not destroy the work it is reporting on.

### Picking up where a run stopped

Eight parts is several minutes, and a run that dies on the seventh should not cost you the six
that already passed. Both `build` and `assemble` take `--resume`:

```bash
swforge build showcase.json -o build --resume
```

A part already sitting in the output directory is opened, measured and checked against its
closed-form answer exactly like a freshly built one — the numbers are re-derived, not remembered,
so a file edited by hand still has to survive the comparison. Only a part that is missing gets
built. A part that exists but cannot be read is reported as `[SKIP]` and built instead, because a
stale file is a reason to build, not a reason to lose the run.

For an assembly, `--resume` checks each component part the same way and prints
`resumed 3/5 parts from disk` before it opens the assembly:

```bash
swforge assemble bolt_stack.json -o build --resume
```

From Python the same shortcut is `reuse_part` returning a result, or `parts_done=` on
`build_assembly` — which is what `examples/build_showcase.py` has always done by hand.

## Parts

Eight kinds ship today. Four are GB standard fasteners driven by catalogue tables, four are
simple non-standard parts driven by user dimensions. `swforge kinds` prints the list, and
`swforge.parts.schema()` returns it as data for anything that wants to build a form or a
validator over it.

| kind | params | analytic volume (showcase) |
|---|---|---|
| `hex_bolt` | `size`, `length` | 2786.3 mm³ (M8×40) |
| `hex_nut` | `size` | 748.3 mm³ (M8) |
| `washer` | `size` | 233.0 mm³ (M8) |
| `socket_screw` | `size`, `length` | 1100.2 mm³ (M6×25) |
| `l_bracket` | `leg_a`, `leg_b`, `width`, `thickness`, `hole_d`, `holes_per_leg` | 18363.8 mm³ |
| `multi_hole_plate` | `length`, `width`, `thickness`, `hole_d`, `rows`, `cols` | 55309.8 mm³ |
| `stepped_shaft` | `d1`/`l1`, `d2`/`l2`, `d3`/`l3` | 18456.9 mm³ |
| `flange` | `outer_d`, `hub_d`, `plate_t`, `hub_h`, `bore_d`, `bolt_d`, `bolt_count`, `bolt_circle_d` | 74568.8 mm³ |

Catalogue tables cover M6–M20 for GB/T 5783 (hex bolts), GB/T 6170 (hex nuts),
GB/T 97.1 (plain washers) and GB/T 70.1 (socket head cap screws), at maximum material
condition.

The list of kinds has exactly one home, `swforge.kinds`, and `swforge.parts` refuses to
import if it registers a different set — a kind promised by the type annotation and missing
from the registry should be an ImportError at build time, not a KeyError for the first user.

## Assemblies

An assembly is also plain data: which parts, where they sit, and how they are mated.

```bash
swforge stack bolt_stack.json    # write the showcase assembly
swforge verify  bolt_stack.json --assembly   # predict volume + envelope, no SolidWorks
swforge assemble bolt_stack.json -o build
```

```
assembly bolt_stack: 5 instances, 4 mates
  volume 66455.1 mm3, envelope 120.00x45.30x80.00 mm
  plate-1   120x80x6   at (60.0, -5.3, 40.0)
  bolt-1    M8x40      at (12.0, 0.0, 12.0)
  ...
```

Because the plates and bolts are themselves checked, the stacked volume and envelope are known
before SolidWorks is asked, and `build_assembly` compares both. Mates are distance or
coincident on a named reference plane:

```python
Mate(first="bolt-1", second="plate-1", plane="上视基准面", distance_mm=5.3, flip=True)
```

`flip` is not decoration. A distance mate constrains the *magnitude* only, so SolidWorks picks
a side — and by default it picks the reversed one. The showcase bolts were mathematically
placed above the plate, the mate reported success, the volume matched exactly, and the envelope
came out `120.00 × 50.60 × 80.00` instead of `120.00 × 45.30 × 80.00`: the whole bolt stack had
been flipped under the plate, one head height deeper than predicted. Volume alone would never
have caught it, which is why the envelope is checked too.

## Drawings

```bash
swforge draw build/bolt_stack.sldasm -o build --views front,top,right,iso
```

Opens the model, names a view per orientation, then places each named view on a new sheet from
the SolidWorks default drawing template, and exports both `.slddrw` and `.pdf`.

## Coordinate convention

Parts are modelled with their axis along **−Y**: the profile sketch lives on the Top plane (XZ)
and extrusion pulls material towards −Y. A part's bounding box is reported as `(x, y, z)` in
millimetres, where `y` is the length along the part axis. Sketch coordinates passed to
`Sketch.circle`, `Sketch.polygon` and `Sketch.rectangle` are **sketch-local 2D**
(`u` → +X, `v` → −Z), not world coordinates.

## SolidWorks API notes

The COM surface is full of silent traps. These are the ones this library had to work around;
they cost real debugging time and are documented so you do not pay for them again.

- **`AddComponent5` returns `None` unless the part is already open in the session.** The file
  existing on disk is not enough — it must be loaded. `SwAssembly.add_component` opens it first.
- **`OpenDoc6` needs every argument boxed as a `VARIANT`.** Passing bare values raises
  `类型不匹配` at argument 5, even if only the path is boxed.
- **A component's selection name is `plane@component@assembly_stem`** — the stem, not the file
  name, and no extension. `washer-1@bolt_stack` selects; `washer-1@bolt_stack.SLDASM` does not.
  The assembly must also be the active document.
- **`AddMate5` takes 14 positional arguments plus a by-ref error, and `1` means success.**
  `errors.value == 1` is `swAddMateError_NoError`; `0` is failure. Reading it the intuitive way
  silently throws away every good mate.
- **`FeatureCut4`'s third argument (Dir) must be `False`.** With `True` the feature returns
  `None` and the solid is unchanged — no exception, no warning.
- **`CreateDrawViewFromModelView3` only works with a view name that exists on the model.**
  `"*Front"` and `"Front"` both return `None`; call `ShowNamedView2` + `NameView` on the model
  first, then reference that name.
- **`Extension.SaveAs` needs an empty-dispatch `VARIANT` for its ExportData argument.** Passing
  `None` raises `类型不匹配`.
- **`EditRebuild3` is a property here, not a method**, and `dir()` on a COM object throws. Use a
  name-based accessor (`swforge.session.member`).
- **`GetBodyBox()` on an assembly component answers in *part* coordinates.** All four bolts of
  the showcase report the same box while sitting in different corners; the pose is in
  `Transform2`. Unioning the raw boxes inflated the envelope by one whole part width
  (`127.51` against a predicted `120.00`). `world_box_mm` maps all eight corners through the
  transform.
- **`AddComponent5` puts the part's bounding-box *centre* on the point you give it.** Only the
  vertical term needs a correction, because the placement convention here says y is where the
  *top face* sits: subtract half the part height. `Transform2` is read-only in practice —
  assigning to it is silently discarded and the next read shows zeros.
- **`CloseDoc` closes nothing when given an ambiguous title.** Two parts built into different
  output directories share a title, so the file stays locked and the retry fails blaming the
  save. Pass the full path. `SwModel.close` does exactly that, and forgets the document only
  after the close has been issued.
- **`OpenDoc6` answers `errors=65536` for a file an open document still holds.** Reuse the open
  document instead of reopening it, or close it first.

### One thread, one document at a time

SolidWorks is a single-threaded COM server, and this library does not pretend otherwise. Every
call in `swforge.session`, `swforge.assembly` and `swforge.drawing` happens on the thread that
called in, and the CLI has no `--jobs`: there is nothing to gain from one. Two threads asking for
a new document at the same time crashed `sldworks.exe` with `ucrtbase 0xc0000409` — an ordinary
access violation in the runtime, with no exception on our side and no hint about the cause. The
same build survives the same calls one at a time.

Two things follow, and both are visible in the code:

- **Closing is throttled on purpose.** `SwModel.close` pauses 0.25 s.
  Closing a batch of documents back-to-back crashed the same way; one at a time with a short gap
  is what the same build survives. If you write your own loop that calls `CloseDoc` directly, that
  gap is yours to keep.
- **There is no thread pool to add.** If a run of a hundred parts is too slow, the answer is more
  `sldworks.exe` processes driven by a process pool — each with its own `SldWorks` instance and its
  own output directory — not more threads in one. A thread would have to marshal every `IDispatch`
  to the owning apartment to be safe, at which point the parallelism is gone and only the bugs
  remain.

## Status

Everything below ran on SolidWorks 2025 SP3.0 (build 33.3.0), not in a mock:

| stage | result |
|---|---|
| 8 showcase parts | 8/8 pass, every one at `err 0.000%`, box exact to 0.01 mm |
| bolted assembly | passes: 66455.1 mm³ against 66455.1 predicted, box `120.00 × 45.30 × 80.00`, 4 distance mates |
| drawing | 4 views, `.slddrw` and `.pdf` written |

`examples/build_showcase.py` is the run that produces those numbers, and it is repeatable: a
second run into a clean directory reproduces them and leaves no documents open behind it.

## Tests

```bash
pytest        # 145 tests, no SolidWorks required
```

## License

MIT.
