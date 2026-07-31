"""M7: attributing instants to calendar days (§9), and the §10 trap it exists to close."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

import better_calendar as bcal
from better_calendar import Calendar, at_times, config, session_bounds, session_of
from better_calendar.core.errors import AmbiguousTimezoneError, BetterCalendarError

UTC_CAL = Calendar("utc", tz="UTC")
PARIS = Calendar("paris", tz="Europe/Paris")
TOKYO = Calendar("tokyo", tz="Asia/Tokyo")
FX = Calendar("fx", tz="America/New_York", session_start=time(17, 0))
CRYPTO = Calendar("crypto", weekmask="all", tz="UTC")


@pytest.fixture(autouse=True)
def _reset_config():
    original = config.default_tz
    yield
    config.default_tz = original


# --- the failure that motivated the whole timezone policy (§10) ---------------


def test_the_utc_paris_attribution_failure():
    """The same instant is Friday in UTC and Saturday in Paris. `.date()` hides that."""
    ts = pd.Timestamp("2026-07-31 23:30", tz="UTC")

    # What the standard library does, and why it is a trap: the answer silently depends
    # on which zone the timestamp happens to be carrying.
    assert ts.date() == date(2026, 7, 31)
    assert ts.tz_convert("Europe/Paris").date() == date(2026, 8, 1)

    # What this library does: you say which frame you mean, and it says so back.
    assert session_of(ts, cal=UTC_CAL) == date(2026, 7, 31)
    assert session_of(ts, cal=PARIS) == date(2026, 8, 1)
    assert session_of(ts, tz="Asia/Tokyo") == date(2026, 8, 1)


def test_the_same_instant_lands_on_a_business_day_or_not_depending_on_the_zone():
    """The consequence that actually bites: Friday in UTC, weekend in Paris."""
    ts = pd.Timestamp("2026-07-31 23:30", tz="UTC")
    assert UTC_CAL.is_bday(ts) is True
    assert PARIS.is_bday(ts) is False


def test_a_timezone_must_come_from_somewhere():
    """I4: no silent fallback. The weekday calendar declares no zone."""
    ts = pd.Timestamp("2026-07-31 23:30", tz="UTC")
    with pytest.raises(AmbiguousTimezoneError, match="needs a timezone"):
        session_of(ts)
    assert session_of(ts, tz="UTC") == date(2026, 7, 31)
    config.default_tz = "Europe/Paris"
    assert session_of(ts) == date(2026, 8, 1)


def test_a_composite_across_zones_refuses():
    """§6: a composite loses its timezone when the operands disagree, and says so."""
    composite = PARIS & TOKYO
    assert composite.tz is None
    with pytest.raises(AmbiguousTimezoneError, match="composite calendar"):
        composite.session_of(pd.Timestamp("2026-07-31 23:30", tz="UTC"))


# --- session_of ----------------------------------------------------------------


def test_naive_input_is_read_literally():
    """I3: a naive value is a label in the resolved frame, not converted into it."""
    assert session_of(datetime(2026, 7, 31, 23, 30), cal=PARIS) == date(2026, 7, 31)
    assert session_of("2026-07-31", cal=PARIS) == date(2026, 7, 31)


def test_session_start_shifts_the_boundary():
    """With a 17:00 start, the morning belongs to the session that opened last night."""
    morning = pd.Timestamp("2026-07-31 09:00", tz="America/New_York")
    evening = pd.Timestamp("2026-07-31 18:00", tz="America/New_York")
    assert session_of(morning, cal=FX) == date(2026, 7, 30)
    assert session_of(evening, cal=FX) == date(2026, 7, 31)
    # Exactly at the boundary, the new session has begun (half-open, I10).
    boundary = pd.Timestamp("2026-07-31 17:00", tz="America/New_York")
    assert session_of(boundary, cal=FX) == date(2026, 7, 31)


def test_midnight_start_is_the_ordinary_case():
    for hour in (0, 9, 23):
        moment = pd.Timestamp(f"2026-07-31 {hour:02d}:00", tz="UTC")
        assert session_of(moment, cal=UTC_CAL) == date(2026, 7, 31)


def test_session_of_is_vectorised():
    instants = pd.DatetimeIndex(["2026-07-31 23:30", "2026-08-01 00:30"]).tz_localize("UTC")
    result = session_of(instants, cal=PARIS)
    assert list(result.strftime("%Y-%m-%d")) == ["2026-08-01", "2026-08-01"]


def test_session_of_returns_a_label_not_an_instant():
    """A day is not a moment; the result carries no timezone on purpose."""
    result = session_of(pd.Timestamp("2026-07-31 23:30", tz="UTC"), cal=PARIS)
    assert isinstance(result, date)
    assert not isinstance(result, datetime)


# --- session_bounds ------------------------------------------------------------


def test_session_bounds_are_half_open_utc():
    first, last = session_bounds("2026-07-31", cal=UTC_CAL)
    assert str(first) == "2026-07-31 00:00:00+00:00"
    assert str(last) == "2026-08-01 00:00:00+00:00"
    assert last - first == pd.Timedelta(hours=24)


def test_session_bounds_follow_the_calendar_zone():
    first, last = session_bounds("2026-07-31", cal=PARIS)
    assert str(first) == "2026-07-30 22:00:00+00:00"  # 31 July 00:00 Paris is 30th in UTC
    assert str(last) == "2026-07-31 22:00:00+00:00"


@pytest.mark.parametrize(
    ("day", "hours"),
    [("2026-03-29", 23), ("2026-10-25", 25), ("2026-07-31", 24)],
)
def test_daylight_saving_makes_sessions_short_or_long(day, hours):
    """Not a bug to normalise away: the session really is 23 or 25 hours that day."""
    first, last = session_bounds(day, cal=PARIS)
    assert last - first == pd.Timedelta(hours=hours)


def test_session_bounds_with_a_session_start():
    first, last = session_bounds("2026-07-31", cal=FX)
    assert str(first) == "2026-07-31 21:00:00+00:00"  # 17:00 New York in July is UTC-4
    assert last - first == pd.Timedelta(hours=24)


def test_an_instant_belongs_to_the_session_whose_bounds_contain_it():
    """The two functions have to agree, or neither means anything."""
    for calendar in (UTC_CAL, PARIS, FX, CRYPTO):
        for hour in (0, 6, 12, 18, 23):
            moment = pd.Timestamp(f"2026-07-31 {hour:02d}:17", tz="UTC")
            day = session_of(moment, cal=calendar)
            first, last = session_bounds(day, cal=calendar)
            assert first <= moment < last, (calendar.name, hour)


# --- grid ----------------------------------------------------------------------


def test_grid_is_anchored_on_the_session_not_on_utc_midnight():
    """The whole point: a Paris session starts at 22:00 UTC, not at 00:00 UTC."""
    points = bcal.get("weekday").grid("2026-07-31", "2026-07-31", "6h", tz="Europe/Paris")
    assert list(points.strftime("%m-%d %H:%M")) == [
        "07-30 22:00",
        "07-31 04:00",
        "07-31 10:00",
        "07-31 16:00",
    ]


def test_grid_covers_only_sessions():
    weekend = PARIS.grid("2026-08-01", "2026-08-02", "6h")
    assert len(weekend) == 0
    always = CRYPTO.grid("2026-08-01", "2026-08-02", "6h")
    assert len(always) == 8


def test_grid_restarts_each_session_so_dst_does_not_shift_later_points():
    points = PARIS.grid("2026-03-27", "2026-03-31", "6h")
    starts = [p for p in points if p.tz_convert("Europe/Paris").hour == 0]
    # Every session still begins exactly at local midnight, transition or not.
    assert len(starts) == 3  # Friday, Monday, Tuesday
    short = PARIS.grid("2026-03-30", "2026-03-30", "6h")
    assert len(short) == 4


@pytest.mark.parametrize(
    ("step", "expected"), [("6h", 4), ("8h", 3), ("1h", 24), ("30min", 48), ("3600s", 24)]
)
def test_grid_steps(step, expected):
    assert len(CRYPTO.grid("2026-07-31", "2026-07-31", step)) == expected


@pytest.mark.parametrize("step", ["", "4", "4x", "0h", "-1h", "4m", "1.5h"])
def test_bad_grid_steps_are_actionable(step):
    with pytest.raises(BetterCalendarError, match="grid step"):
        CRYPTO.grid("2026-07-31", "2026-07-31", step)


def test_a_bare_unit_means_one_of_them():
    assert len(CRYPTO.grid("2026-07-31", "2026-07-31", "h")) == 24


def test_minutes_are_spelled_min_not_m():
    """`m` reads as months to half of pandas' users, so it is refused outright."""
    with pytest.raises(BetterCalendarError, match="cannot be read as months"):
        CRYPTO.grid("2026-07-31", "2026-07-31", "15m")


# --- at_times ------------------------------------------------------------------


def test_at_times_crosses_days_with_times():
    fixings = at_times(bcal.imm_dates("2026-01-01", "2026-06-30"), ["08:00", "16:00"])
    assert list(fixings.strftime("%Y-%m-%d %H:%M%z")) == [
        "2026-03-18 08:00+0000",
        "2026-03-18 16:00+0000",
        "2026-06-17 08:00+0000",
        "2026-06-17 16:00+0000",
    ]


def test_at_times_honours_the_timezone():
    result = at_times(["2026-07-31"], ["09:00"], tz="Europe/Paris")
    assert str(result[0]) == "2026-07-31 09:00:00+02:00"
    assert str(result.tz) == "Europe/Paris"


def test_at_times_accepts_seconds():
    result = at_times(["2026-07-31"], ["09:30:15"])
    assert list(result.strftime("%H:%M:%S")) == ["09:30:15"]


@pytest.mark.parametrize("moment", ["9", "09-00", "aa:bb", "25:00", "09:61"])
def test_bad_times_are_actionable(moment):
    with pytest.raises(BetterCalendarError, match="time of day"):
        at_times(["2026-07-31"], [moment])


def test_at_times_needs_at_least_one_time():
    with pytest.raises(BetterCalendarError, match="at least one time"):
        at_times(["2026-07-31"], [])


# --- §9.3: what must not exist ---------------------------------------------------


def test_is_open_is_not_on_the_calendar():
    """§9.3: `is_open()` returning `is_bday()` would be false for every real exchange."""
    assert not hasattr(bcal.get("XNYS"), "is_open")
    for name in ("next_open", "next_close", "trading_minutes"):
        assert not hasattr(bcal.get("XNYS"), name)


def test_crypto_is_a_first_class_calendar():
    """§9.2: crypto code uses the identical API, and composes with an exchange."""
    crypto = bcal.get("crypto:24x7")
    assert crypto.tz == "UTC"
    assert crypto.session_start == time(0, 0)
    assert crypto.is_bday("2026-08-01") is True
    listed = crypto & bcal.get("XCBF")
    assert listed.is_bday("2026-08-01") is False


def test_wall_clock_offsets_still_hold_across_a_transition():
    """I5 again, now via session_of: +1 business day is +23h here, and that is right."""
    before = datetime(2026, 3, 27, 9, 0, tzinfo=ZoneInfo("Europe/Paris"))
    after = PARIS.offset(before, 1)
    assert session_of(after, cal=PARIS) == date(2026, 3, 30)
    elapsed = after.astimezone(timezone.utc) - before.astimezone(timezone.utc)
    assert elapsed == timedelta(hours=71)
