"""Every number README.md prints has to be a number the library still reports.

Nothing mechanical linked the prose to the code, so the kind table drifted the
moment a bore changed: #40 replaced the M8 nut 6.8 mm threadless hole with the
8.4 mm washer bore, and README.md went on advertising 748.3 mm3 for a part that
measures 618.4.  The table is the first thing a reader checks the library
against, so a wrong number there is worse than no number: it reads as a promise.

These tests parse the two places README.md quotes arithmetic -- the kind table
and the showcase assembly transcript -- and compare them with what analytic()
and predict() answer today.  They need no SolidWorks session for the same
reason the tables do not: both halves come from closed-form geometry.
"""

import re
from pathlib import Path

import pytest

from swforge import demo, parts

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"

KIND_HEADER = "| kind | params | analytic volume (showcase) |"
VOLUME_IN_TABLE = re.compile(r"([0-9]+(?:\.[0-9]+)?) mm")
VOLUME_IN_PROSE = re.compile(r"volume ([0-9]+(?:\.[0-9]+)?) mm3")
ENVELOPE_IN_PROSE = re.compile(r"envelope ([0-9.]+)x([0-9.]+)x([0-9.]+) mm")


def _lines():
    return README.read_text(encoding="utf-8").splitlines()


def _kind_rows():
    """{kind: (params, volume_mm3)} from the table under "## Parts"."""
    lines = _lines()
    start = lines.index(KIND_HEADER)
    rows = {}
    # Skip the |---|---| rule; the table ends at the first line that is not a row.
    for line in lines[start + 2:]:
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        assert len(cells) == 3, f"expected three columns in {line!r}"
        match = VOLUME_IN_TABLE.search(cells[2])
        assert match, f"no volume in millimetres on {line!r}"
        kind = cells[0].strip("`")
        assert kind not in rows, f"README.md lists {kind!r} more than once"
        params = [name.strip().strip("`") for name in re.split(r"[,/]", cells[1])]
        rows[kind] = (params, float(match.group(1)))
    assert rows, "the kind table in README.md is empty"
    return rows


def _assembly_transcript():
    """The showcase transcript block under "## Assemblies", as one string."""
    lines = _lines()
    first = next(i for i, line in enumerate(lines)
                 if line.startswith("assembly bolt_stack:"))
    # The heading line sits inside a fence; walk back to the opening ``` and
    # forward to the closing one so a second transcript cannot leak in.
    start = first - 1 - lines[:first][::-1].index("```")
    end = lines.index("```", first)
    return "\n".join(lines[start:end + 1])


def _declared(kind):
    row = [r for r in parts.schema() if r["kind"] == kind][0]
    return [param["name"] for param in row["params"]]


def _showcase_volumes():
    return {spec.kind: parts.analytic(spec.kind, spec.params).volume_mm3
            for spec in demo.showcase()}


def test_the_kind_table_lists_every_kind_exactly_once():
    assert sorted(_kind_rows()) == sorted(parts.PARTS), (
        "README.md names a different set of kinds than swforge.parts registers"
    )


@pytest.mark.parametrize("kind", sorted(parts.PARTS))
def test_the_kind_table_names_every_key_the_builder_reads(kind):
    params, _ = _kind_rows()[kind]
    assert sorted(params) == sorted(_declared(kind)), (
        f"README.md {kind} params disagree with the PARAMS tuple in its module"
    )


@pytest.mark.parametrize("kind", sorted(parts.PARTS))
def test_the_kind_table_quotes_the_volume_the_showcase_builds(kind):
    _, documented = _kind_rows()[kind]
    wanted = round(_showcase_volumes()[kind], 1)
    assert documented == wanted, (
        f"README.md says the showcase {kind} is {documented} mm3; "
        f"parts.analytic() answers {wanted} mm3"
    )


def test_the_assembly_transcript_counts_the_instances_and_mates():
    spec = demo.bolt_stack()
    heading = f"assembly {spec.name}: {len(spec.placements)} instances, "
    assert heading in _assembly_transcript(), (
        f"README.md transcript does not open with {heading!r}"
    )
    assert f"{len(spec.mates)} mates" in _assembly_transcript()


def test_the_assembly_transcript_quotes_the_predicted_volume():
    documented = float(VOLUME_IN_PROSE.search(_assembly_transcript()).group(1))
    wanted = round(demo.bolt_stack().predict().volume_mm3, 1)
    assert documented == wanted, (
        f"README.md says the showcase stack is {documented} mm3; predict() "
        f"answers {wanted} mm3"
    )


def test_the_assembly_transcript_quotes_the_predicted_envelope():
    match = ENVELOPE_IN_PROSE.search(_assembly_transcript())
    documented = tuple(float(value) for value in match.groups())
    wanted = tuple(round(value, 2) for value in demo.bolt_stack().predict().bbox_mm)
    assert documented == wanted, (
        f"README.md says the showcase envelope is {documented}; predict() "
        f"answers {wanted} mm"
    )
