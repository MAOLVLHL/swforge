# Releasing

The distribution name is **swforge-cad**. The import name and the console script
are still `swforge` — only the PyPI name differs, because `swforge` there
belongs to an unrelated project (https://pypi.org/project/swforge/).

There is one workflow, `.github/workflows/release.yml`, and it runs on a tag
matching `v*`. It has three jobs, and two of them need nothing from you:

| job | what it proves | needs |
|---|---|---|
| `build` | the sdist and wheel build, pass `twine check --strict`, and the wheel installs into an empty venv where it answers `catalog`, `demo`, `verify`, `stack` and `verify --assembly` | nothing |
| `github-release` | the artefacts are attached to the tag with generated notes | nothing |
| `publish` | the artefact is uploaded to PyPI | a trusted publisher plus one repository variable |

The third job is off by default. A publish job that fails on every tag is worse
than no publish job: it teaches everyone to ignore a red CI badge.

## Cutting a release

1. Bump `__version__` in `src/swforge/__init__.py`. That is the only place a
   version lives; `pyproject.toml` reads it through
   `[tool.setuptools.dynamic]`. `tests/test_packaging.py` fails if a second
   copy appears.
2. Run the suite: `python -m pytest`.
3. Commit, push, and tag the same commit:

   ```bash
   git tag -a v0.1.1 -m "v0.1.1"
   git push origin v0.1.1
   ```

4. Watch the run. The tag check compares `v0.1.1` against the wheel that was
   actually built, so a forgotten version bump fails there and not on PyPI.

## Turning the upload on

PyPI uploads use [trusted publishing](https://docs.pypi.org/trusted-publishers/):
GitHub mints a short-lived OIDC token for the job, PyPI verifies it, and no
long-lived API token is ever stored in this repository.

1. On https://pypi.org/manage/account/publishing/ add a *pending publisher*:
   - PyPI project name: `swforge-cad`
   - Owner: `MAOLVLHL`
   - Repository name: `swforge`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
2. Create the same environment in the repository
   (Settings → Environments → `pypi`). Adding required reviewers here is what
   turns the upload into a two-person decision.
3. Set the repository variable that arms the job
   (Settings → Variables → Actions):

   ```bash
   gh variable set PYPI_TRUSTED_PUBLISHER --body true
   ```

From then on, every tag publishes. To go back to Releases-only, unset it:

```bash
gh variable delete PYPI_TRUSTED_PUBLISHER
```

## Testing the upload without spending a version number

Trusted publishing also works against TestPyPI, and the workflow keeps its
artefacts for seven days, so a dry run costs nothing:

1. Register the same pending publisher on https://test.pypi.org/manage/account/publishing/
   with the same four fields.
2. Add `repository-url: https://test.pypi.org/legacy/` to the `pypa/gh-action-pypi-publish`
   step, or run it from a branch with `workflow_dispatch`.
3. A version published to TestPyPI cannot be republished there, so tag a
   `v0.1.1rc1` rather than `v0.1.1`.

## Building locally

```bash
python -m pip install build twine
python -m build
python -m twine check --strict dist/*
```

`dist/` is git-ignored; the artefacts the workflow uploads are the ones it built
from the tag, never ones committed by hand.
