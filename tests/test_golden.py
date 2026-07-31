"""Golden dates (§15c): the boundaries that break naive implementations.

Provider-sourced fixtures (TARGET2 Easter, NYSE Good Friday, Golden Week) arrive with
milestone M4. What can be pinned today are the pure calendar-arithmetic edges.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from better_calendar import MAX_YEAR, MIN_YEAR, Calendar, Roll
from better_calendar.core.errors import OutOfBoundsError

FULL = Calendar("weekday")


# --- 29 February ------------------------------------------------------------


@pytest.mark.parametrize(
    ("year", "is_leap"), [(2000, True), (2024, True), (2100, False), (1900, False)]
)
def test_leap_years(year, is_leap):
    import calendar as stdlib

    assert stdlib.isleap(year) is is_leap


def test_offsets_across_29_february():
    # 2024-02-28 is a Wednesday; the 29th is a Thursday.
    assert FULL.offset("2024-02-28", 1) == "2024-02-29"
    assert FULL.offset("2024-02-29", 1) == "2024-03-01"
    assert FULL.count("2024-02-01", "2024-03-01") == 21


def test_modified_following_at_a_leap_month_end():
    # 2026-02-28 is a Saturday and the last day of February.
    assert FULL.adjust("2026-02-28", Roll.FOLLOWING) == "2026-03-02"
    assert FULL.adjust("2026-02-28", Roll.MODIFIED_FOLLOWING) == "2026-02-27"


# --- year boundaries --------------------------------------------------------


def test_epoch_day_zero():
    assert FULL.is_bday(f"{MIN_YEAR}-01-01") is True  # 1970-01-01 was a Thursday
    with pytest.raises(OutOfBoundsError):
        FULL.prev_bday(f"{MIN_YEAR}-01-01")


def test_horizon_end():
    last = date(MAX_YEAR, 12, 31)
    assert FULL.is_bday(last) is True  # 2100-12-31 is a Friday
    with pytest.raises(OutOfBoundsError):
        FULL.next_bday(last)
    with pytest.raises(OutOfBoundsError):
        FULL.is_bday(date(MAX_YEAR + 1, 1, 1))


def test_new_year_crossings():
    assert FULL.offset("2025-12-31", 1) == "2026-01-01"
    assert FULL.count("2025-12-29", "2026-01-05") == 5


# --- DST weekends -----------------------------------------------------------

PARIS = ZoneInfo("Europe/Paris")
NEW_YORK = ZoneInfo("America/New_York")


@pytest.mark.parametrize(
    ("zone", "before", "elapsed_hours"),
    [
        (PARIS, datetime(2026, 3, 27, 9, 0), 71),  # Friday -> Monday over spring forward
        (PARIS, datetime(2026, 10, 23, 9, 0), 73),  # Friday -> Monday, ordinary week
        (NEW_YORK, datetime(2026, 3, 6, 9, 0), 71),  # Friday -> Monday over spring forward
    ],
)
def test_offsets_preserve_wall_clock_across_dst(zone, before, elapsed_hours):
    """I5: the clock reads 09:00 on both sides; only the absolute duration changes."""
    aware = before.replace(tzinfo=zone)
    after = FULL.offset(aware, 1, tz=str(zone))
    assert (after.hour, after.minute) == (9, 0)
    assert after.tzinfo is zone
    actual = after.astimezone(ZoneInfo("UTC")) - aware.astimezone(ZoneInfo("UTC"))
    assert actual == timedelta(hours=elapsed_hours)


def test_the_utc_paris_attribution_failure():
    """§10: the failure that motivated the timezone policy, as a calendar query."""
    ts = pd.Timestamp("2026-07-31 23:30", tz="UTC")  # Friday in UTC, Saturday in Paris
    assert Calendar("utc", tz="UTC").is_bday(ts) is True
    assert Calendar("paris", tz="Europe/Paris").is_bday(ts) is False


# --- weekmasks that are not Mon-Fri ----------------------------------------


def test_gulf_weekend():
    gulf = Calendar("gulf", weekmask="Sun Mon Tue Wed Thu")
    assert gulf.is_bday("2026-08-02") is True  # Sunday
    assert gulf.is_bday("2026-07-31") is False  # Friday


def test_24x7_never_closes():
    crypto = Calendar("crypto", weekmask="all")
    assert crypto.count("2026-01-01", "2027-01-01") == 365
    assert crypto.offset("2026-07-31", 1) == "2026-08-01"
