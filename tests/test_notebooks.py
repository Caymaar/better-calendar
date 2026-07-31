"""The notebooks are documentation that runs, so they are checked like documentation.

Two things are enforced here:

* every name in the curated public API (§13) is actually demonstrated somewhere, so
  "these notebooks cover the whole API" stays true rather than becoming true once;
* the committed notebooks are valid, carry their outputs, and recorded no errors.

Re-executing them is a CI job rather than a test — it needs the provider extras and a
Jupyter kernel, which is too much to ask of a plain ``pytest`` run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

NOTEBOOK_DIR = Path(__file__).resolve().parents[1] / "notebooks"
NOTEBOOKS = sorted(NOTEBOOK_DIR.glob("*.ipynb"))

#: Names whose demonstration is the *absence* of a call, or that only appear as types.
_DEMONSTRATED_INDIRECTLY = {
    "BetterCalendarError",  # the base class; the concrete subclasses are shown instead
    "ProviderError",  # only raised when an optional extra is missing
    "ScheduleError",  # shown via Schedule(stub="none")
    "DEFAULT_BOUNDS",
    "MIN_YEAR",
    "Config",
    "list_calendars",  # shown under its shadowing alias, bcal.list
    "resolve",
}


@pytest.fixture(scope="module")
def sources() -> str:
    """Every source line of every notebook, concatenated."""
    text = []
    for path in NOTEBOOKS:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for cell in payload["cells"]:
            text.append("".join(cell["source"]))
    return "\n".join(text)


def test_the_notebooks_are_there():
    assert len(NOTEBOOKS) >= 6, [p.name for p in NOTEBOOKS]
    assert (NOTEBOOK_DIR / "README.md").exists()


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.name)
def test_each_notebook_is_valid_and_executed(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["nbformat"] == 4

    code_cells = [c for c in payload["cells"] if c["cell_type"] == "code"]
    assert code_cells, path.name

    errors = [
        output
        for cell in code_cells
        for output in cell.get("outputs", [])
        if output.get("output_type") == "error"
    ]
    assert errors == [], f"{path.name}: {[e.get('ename') for e in errors]}"

    executed = [c for c in code_cells if c.get("outputs")]
    assert len(executed) >= len(code_cells) - 2, (
        f"{path.name}: only {len(executed)}/{len(code_cells)} code cells carry output; "
        f"the notebook was probably committed unexecuted"
    )


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.name)
def test_each_notebook_opens_with_a_title(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    first = payload["cells"][0]
    assert first["cell_type"] == "markdown"
    assert "".join(first["source"]).lstrip().startswith("# ")


def test_the_curated_api_is_demonstrated(sources: str):
    """§13's names must each appear in a notebook, or the coverage claim is hollow."""
    import better_calendar

    missing = sorted(
        name
        for name in better_calendar.__all__
        if not name.startswith("__")
        and name not in _DEMONSTRATED_INDIRECTLY
        and name not in sources
    )
    assert missing == [], f"not demonstrated in any notebook: {missing}"


def test_the_headline_functions_are_demonstrated(sources: str):
    """The ones a reader will look for first, named explicitly so they cannot drift."""
    for call in (
        "bcal.adjust(",
        "bcal.offset(",
        "bcal.count(",
        "bcal.add_tenor(",
        "bcal.spot(",
        "bcal.session_of(",
        "bcal.last_weekday(",
        "bcal.nth_weekday(",
        "bcal.imm_dates(",
        "bcal.option_expiries(",
        "Schedule(",
        "BDay(",
        ".unadjusted()",
        ".dates()",
        ".periods()",
        ".session_bounds(",
        ".grid(",
        "at_times(",
    ):
        assert call in sources, call
