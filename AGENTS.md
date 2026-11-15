# AGENTS.md

Instructions for any automated agent (Copilot coding agent, Claude Code, Codex) working in
this repository. Read this before touching a file; it is the contract the CI gate enforces.

## What this project is

swforge describes every part twice: once as closed-form Python mathematics under
`src/swforge/` and once as a sequence of SolidWorks features. A build only counts as
correct when volume and bounding box agree to within 0.1%. Never weaken that comparison
to make a build pass.

Layout: `src/swforge/*.py` (library), `src/swforge/parts/` (one module per part kind),
`tests/` (pytest suite, ~300 tests, runs without SolidWorks), `examples/` (JSON specs).

## Hard rules

1. **Python 3.10 syntax only.** CI runs 3.10, 3.12 (Windows) and 3.13. No `ExceptionGroup`,
   no `typing.Self`, no 3.11+ stdlib additions.
2. **No COM on import.** `import swforge` must work on Linux with no pywin32. `pythoncom`
   and `win32com.client` may only be imported inside the function that needs them.
   Code that reaches SolidWorks goes through `src/swforge/session.py`.
3. **Tests use the fakes, not SolidWorks.** `tests/fakecom.py` stubs pywin32 in
   `sys.modules`; `tests/conftest.py` holds the SolidWorks object stand-ins. Extend those
   fakes rather than adding a skip marker.
4. **Run the suite before you claim success**: `python -m pytest -q` (set
   `PYTHONPATH=src` if the package is not installed). CI also runs
   `python -m compileall -q src` and `ruff check --select E9,F63,F7,F82`.
5. **No debugging hooks or secrets.** The guard job rejects trace calls, breakpoint calls,
   private-key blocks and access tokens in added lines. Do not paste such a string into
   this file or any test fixture either.
6. **Keep a PR under 600 added lines.** The guard job fails above that. If an issue needs
   more, split it and say so in the issue thread.
7. **PR titles are conventional commits**: `type(scope): what changed`, at least 8
   characters after the colon, type in `feat fix test docs refactor perf build ci chore`.
   Example: `fix(session): report a failed save instead of crashing`.
8. **One concern per PR.** Do not reformat untouched code and do not rename public API
   unless the issue asks for it; reviewers read the diff, not the whole tree.

## How to work an issue

1. Restate the problem in one sentence and quote the file and line that shows it. If you
   cannot find that line, say so in a comment and stop — do not invent a fix.
2. Write or extend the failing test first. For a geometry or parsing bug, the test should
   fail on `main` with a specific number, not with `assert False`.
3. Make the smallest change that turns the test green. `src/swforge/` modules are small on
   purpose (45-350 lines each); prefer editing the existing function to adding a layer.
4. Cover the failing path *and* the neighbouring one you now touch (e.g. resume path and
   cold path, Windows path and POSIX path).
5. Re-run the full suite, then fill in the PR body from `.github/pull_request_template.md`
   (Problem / Solution / Changes / Testing / Notes) with the real pytest summary line.
6. If the issue turns out to be wrong, underspecified, or already fixed, close the loop in
   a comment with what you found instead of opening a PR.

## Things reviewers here care about

- Errors are reported, never swallowed: a failed save must surface as a failure, and a
  progress callback that raises must be logged and ignored, not crash the build.
- Absolute paths before COM: a relative `-o` is resolved against the caller's directory.
- The library never prints and never configures logging; the CLI owns stderr and `-v`.
- Comments explain *why* a line exists, in the register used across the codebase. Do not
  add banner comments or restate what the code says.
