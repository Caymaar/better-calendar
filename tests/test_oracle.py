"""Oracle tests (§15a): the committed snapshot against the live upstreams.

These are the evidence that the snapshot says what its provider says. They import the
upstream packages directly and compare every single day over the full horizon — if a
snapshot file were stale, truncated or mis-parsed, the comparison fails on the first
disagreeing date.

Marked ``oracle`` and skipped cleanly when an extra is absent, so an install without the
provider extras still runs the rest of the suite.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pytest

import better_calendar as bcal
from better_calendar.calendars.snapshot import load_manifest

pytestmark = pytest.mark.oracle

MANIFEST = load_manifest()
ql = pytest.importorskip("QuantLib", reason="needs the 'quantlib' extra")


def _every_day(bounds: tuple[date, date]) -> np.ndarray[Any, Any]:
    return np.arange(
        np.datetime64(bounds[0].isoformat()),
        np.datetime64(bounds[1].isoformat()) + np.timedelta64(1, "D"),
        dtype="datetime64[D]",
    )


def _quantlib_calendar(target: str):
    class_name, _, market = target.partition(".")
    calendar_class = getattr(ql, class_name)
    return calendar_class(getattr(calendar_class, market)) if market else calendar_class()


def _ql_date(day: Any) -> Any:
    text = str(day)
    return ql.Date(int(text[8:10]), int(text[5:7]), int(text[:4]))


@pytest.mark.parametrize(
    "identifier",
    ["fin:TARGET2", "fin:NYB", "fin:LNB", "fin:TKB", "fin:ZUB", "rate:SOFR", "rate:CORRA"],
)
def test_snapshot_matches_quantlib_day_for_day(identifier):
    """Every day of the horizon, ours against QuantLib's. No sampling."""
    entry = MANIFEST[identifier]
    calendar = bcal.get(identifier)
    upstream = _quantlib_calendar(entry.upstream)

    days = _every_day(entry.bounds)
    ours = calendar.is_bday(days)
    theirs = np.fromiter(
        (upstream.isBusinessDay(_ql_date(day)) for day in days),
        dtype=bool,
        count=days.size,
    )
    disagreements = days[ours != theirs]
    assert disagreements.size == 0, f"{identifier}: first is {disagreements[:3]}"


@pytest.mark.parametrize("identifier", ["fin:TARGET2", "rate:SOFR"])
def test_roll_conventions_agree_with_quantlib(identifier):
    """§15a: the roll conventions themselves, not just membership."""
    entry = MANIFEST[identifier]
    calendar = bcal.get(identifier)
    upstream = _quantlib_calendar(entry.upstream)
    days = _every_day((date(2000, 1, 1), date(2050, 12, 31)))

    for ours_roll, theirs_roll in (
        (bcal.Roll.FOLLOWING, ql.Following),
        (bcal.Roll.PRECEDING, ql.Preceding),
        (bcal.Roll.MODIFIED_FOLLOWING, ql.ModifiedFollowing),
        (bcal.Roll.MODIFIED_PRECEDING, ql.ModifiedPreceding),
    ):
        ours = calendar.adjust(days, ours_roll)
        theirs = np.array(
            [str(upstream.adjust(_ql_date(day), theirs_roll).ISO()) for day in days],
            dtype="datetime64[D]",
        )
        actual = np.asarray(ours.values if hasattr(ours, "values") else ours)
        np.testing.assert_array_equal(
            actual.astype("datetime64[D]"), theirs, err_msg=f"{identifier} {ours_roll}"
        )


@pytest.mark.parametrize("identifier", ["fin:TARGET2", "fin:NYB"])
def test_business_day_counts_agree_with_quantlib(identifier):
    entry = MANIFEST[identifier]
    calendar = bcal.get(identifier)
    upstream = _quantlib_calendar(entry.upstream)
    for first, last in (
        (date(2000, 1, 1), date(2001, 1, 1)),
        (date(2020, 3, 1), date(2020, 12, 31)),
        (date(2050, 1, 1), date(2060, 1, 1)),
    ):
        ours = calendar.count(first, last)
        theirs = upstream.businessDaysBetween(
            ql.Date(first.day, first.month, first.year),
            ql.Date(last.day, last.month, last.year),
            True,
            False,
        )
        assert ours == theirs, f"{identifier} {first}..{last}"


# --- exchange-calendars ------------------------------------------------------


xc = pytest.importorskip("exchange_calendars", reason="needs the 'exchange' extra")


@pytest.mark.parametrize("identifier", ["XNYS", "XLON", "XPAR", "XETR", "XTKS", "XTAE"])
def test_snapshot_matches_exchange_calendars_session_for_session(identifier):
    """Our good days must be exactly the upstream's sessions, over the whole horizon."""
    entry = MANIFEST[identifier]
    calendar = bcal.get(identifier)
    upstream = xc.get_calendar(
        entry.upstream, start=entry.bounds[0].isoformat(), end=entry.bounds[1].isoformat()
    )
    theirs = np.ascontiguousarray(upstream.sessions.values.astype("datetime64[D]"))
    ours = calendar.sessions()
    ours = np.asarray(ours.values if hasattr(ours, "values") else ours).astype("datetime64[D]")
    np.testing.assert_array_equal(ours, theirs)


def test_a_non_monday_friday_exchange_survives_the_round_trip():
    """XTAE trades Sunday to Thursday; the weekmask has to come from the data."""
    assert bcal.get("XTAE").weekmask == "Mon Tue Wed Thu Sun"
    assert bcal.get("XTAE").is_bday("2026-08-02") is True  # a Sunday
    assert bcal.get("XTAE").is_bday("2026-07-31") is False  # a Friday


# --- python-holidays ---------------------------------------------------------


holidays_pkg = pytest.importorskip("holidays", reason="needs the 'holidays' extra")


@pytest.mark.parametrize("identifier", ["country:FR", "country:US", "country:DE", "country:JP"])
def test_snapshot_matches_python_holidays(identifier):
    entry = MANIFEST[identifier]
    calendar = bcal.get(identifier)
    upstream = holidays_pkg.country_holidays(
        entry.upstream, years=range(entry.bounds[0].year, entry.bounds[1].year + 1)
    )
    weekend = set(getattr(upstream, "weekend", {5, 6}))
    theirs = sorted(
        day
        for day in upstream
        if entry.bounds[0] <= day <= entry.bounds[1] and day.weekday() not in weekend
    )
    ours = calendar.holidays.astype("datetime64[D]").astype(date).tolist()
    assert ours == theirs
