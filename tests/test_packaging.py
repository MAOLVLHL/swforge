"""The packaging has to describe the same project the code describes.

None of this needs SolidWorks or even an installed wheel: pyproject.toml is a
file in the repository, and __init__.py is importable by path.  The point is to
catch the two ways a release goes wrong quietly -- a second copy of the version
number that nobody updates, and a console script that names a function the
package does not have.
"""

from pathlib import Path

import pytest

import swforge

# tomllib only reached the stdlib in 3.11 and the matrix still runs 3.10.  The
# subject of these tests is metadata, not a feature, so skipping there costs
# nothing -- inventing a TOML parser to run them twice would.
tomllib = pytest.importorskip("tomllib", reason="stdlib TOML reader needs 3.11+")

ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_the_version_has_exactly_one_source():
    project = _pyproject()["project"]
    assert "version" not in project, (
        "a static version in pyproject.toml is a second copy of "
        "swforge.__version__; the two drift the first time somebody bumps one"
    )
    assert "version" in project["dynamic"]
    attr = _pyproject()["tool"]["setuptools"]["dynamic"]["version"]["attr"]
    assert attr == "swforge.__version__"
    assert swforge.__version__.count(".") >= 1, "the version feeds PEP 440 parsing"


def test_the_console_script_points_at_a_real_callable():
    entry = _pyproject()["project"]["scripts"]["swforge"]
    module_name, _, attribute = entry.partition(":")
    module = __import__(module_name, fromlist=["_"])
    assert callable(getattr(module, attribute)), (
        f"pip installs a swforge command that would fail on import: {entry}"
    )


def test_the_distribution_name_is_not_the_one_already_on_pypi():
    name = _pyproject()["project"]["name"]
    assert name == "swforge-cad", (
        "swforge is taken on PyPI by another project; the import name and the "
        "command stay swforge, but the distribution has to differ"
    )


def test_the_licence_is_declared_the_way_pep_639_asks():
    project = _pyproject()["project"]
    assert project["license"] == "MIT", (
        "setuptools>=77 wants an SPDX expression here, not a table"
    )
    assert project["license-files"] == ["LICENSE"]
    assert (ROOT / "LICENSE").is_file()


def test_the_metadata_does_not_promise_a_platform_it_cannot_run_on():
    classifiers = _pyproject()["project"]["classifiers"]
    assert "Operating System :: Microsoft :: Windows" in classifiers, (
        "the SolidWorks half is Windows-only; saying so in the metadata is the "
        "cheapest place to prevent a misleading install"
    )


def test_the_package_directory_is_the_one_that_gets_built():
    where = _pyproject()["tool"]["setuptools"]["packages"]["find"]["where"]
    assert where == ["src"]
    assert (ROOT / "src" / "swforge" / "__init__.py").is_file()
