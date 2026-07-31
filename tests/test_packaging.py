"""§14: dependency discipline, and §3: the MAX_YEAR knob."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "better_calendar"


def test_importing_the_package_does_not_import_pandas():
    """§14: the import must stay cheap and numpy-only."""
    code = "import sys, better_calendar; print('pandas' in sys.modules)"
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "False"


def test_importing_the_package_does_not_import_a_provider():
    """§5.3: providers are build-time code, never touched at import or query time."""
    code = (
        "import sys, better_calendar; "
        "print(any(m in sys.modules for m in "
        "('exchange_calendars', 'holidays', 'QuantLib', 'workalendar')))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "False"


def test_max_year_is_the_only_knob():
    """§3/§18: no literal terminal year anywhere except where MAX_YEAR is defined."""
    offenders = []
    for path in SRC.rglob("*.py"):
        if path.name == "epoch.py":
            continue
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if re.search(r"(?<![\d\-])2100(?![\d])", line):
                offenders.append(f"{path.relative_to(SRC)}:{number}: {line.strip()}")
    assert offenders == []


@pytest.mark.parametrize(
    "name",
    [
        "Calendar",
        "get",
        "list",
        "describe",
        "register",
        "Roll",
        "adjust",
        "offset",
        "count",
        "DateRange",
        "to_date",
        "to_datetime",
        "to_timestamp",
        "MAX_YEAR",
        "config",
    ],
)
def test_public_api_surface(name):
    """§13: the curated names must actually be exported."""
    import better_calendar

    assert hasattr(better_calendar, name)
    assert name in better_calendar.__all__


def test_list_shadows_the_builtin_only_inside_the_namespace():
    import better_calendar

    assert better_calendar.list is better_calendar.list_calendars
    assert list is not better_calendar.list


def test_aliases_file_ships_with_the_package():
    assert (SRC / "calendars" / "aliases.toml").exists()


def test_sequence_output_degrades_to_numpy_without_pandas():
    """I6: a DatetimeIndex when pandas is there, a datetime64[D] array when it is not."""
    code = (
        "import sys; sys.modules['pandas'] = None\n"
        "import better_calendar as bcal\n"
        "from better_calendar.core import _pandas\n"
        "_pandas._optional = None\n"
        "r = bcal.offset(['2026-07-31', '2026-08-03'], 1)\n"
        "print(type(r).__name__, r.dtype)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "ndarray datetime64[D]"
