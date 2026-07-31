"""M1: conversion, type preservation and the §10 timezone policy."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from better_calendar import config
from better_calendar.core.errors import AmbiguousTimezoneError, BetterCalendarError
from better_calendar.core.types import Kind, from_days, kind_of, to_date, to_days

PARIS = ZoneInfo("Europe/Paris")

# 2026-07-31 is a Friday; day 20665 since the epoch.
FRIDAY = date(2026, 7, 31)
FRIDAY_DAY = 20665


@pytest.fixture(autouse=True)
def _reset_config():
    original = config.default_tz
    yield
    config.default_tz = original


# --- kind_of ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (FRIDAY, Kind.DATE),
        (datetime(2026, 7, 31, 9, 30), Kind.DATETIME),
        (pd.Timestamp("2026-07-31"), Kind.TIMESTAMP),
        (np.datetime64("2026-07-31"), Kind.NP),
        ("2026-07-31", Kind.STR),
        (20260731, Kind.INT),
        ([FRIDAY], Kind.SEQ),
        (pd.DatetimeIndex(["2026-07-31"]), Kind.SEQ),
        (np.array(["2026-07-31"], dtype="datetime64[D]"), Kind.SEQ),
    ],
)
def test_kind_of(value, expected):
    assert kind_of(value) is expected


def test_bool_is_not_a_date():
    with pytest.raises(BetterCalendarError, match="bool is not a date"):
        kind_of(True)


# --- parsing ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-07-31", FRIDAY_DAY),
        ("20260731", FRIDAY_DAY),
        ("2026-07-31T14:30:00", FRIDAY_DAY),
        ("2026-07-31 14:30", FRIDAY_DAY),
        ("2026-07-31T14:30:00.123456", FRIDAY_DAY),
    ],
)
def test_iso_strings(text, expected):
    assert int(to_days(text)) == expected


@pytest.mark.parametrize("text", ["31/07/2026", "07/31/2026", "31-07-2026", "Jul 31 2026", ""])
def test_ambiguous_formats_are_rejected(text):
    with pytest.raises(BetterCalendarError, match=r"Ambiguous formats|Cannot parse"):
        to_days(text)


def test_int_must_be_yyyymmdd():
    # A Unix timestamp passed by accident must not silently become a date.
    with pytest.raises(BetterCalendarError, match="yyyymmdd"):
        to_days(1785456000)


def test_int_rejects_impossible_date():
    with pytest.raises(BetterCalendarError, match="Invalid yyyymmdd"):
        to_days(20260732)


def test_nat_is_rejected():
    with pytest.raises(BetterCalendarError, match="NaT is not a date"):
        to_days(np.datetime64("NaT"))
    with pytest.raises(BetterCalendarError, match="NaT is not a date"):
        to_days(pd.DatetimeIndex(["2026-07-31", None]))


# --- timezone policy (§10) -------------------------------------------------


def test_naive_is_a_label_not_an_instant():
    """I3: the date part of a naive datetime is taken literally."""
    assert to_date(datetime(2026, 7, 31, 23, 30)) == FRIDAY


def test_aware_without_tz_raises():
    """I4: an aware value is an instant and needs a timezone to become a day."""
    aware = datetime(2026, 7, 31, 23, 30, tzinfo=timezone.utc)
    with pytest.raises(AmbiguousTimezoneError, match="timezone-aware"):
        to_date(aware)


def test_the_motivating_utc_paris_failure():
    """§10: the same instant is Friday in UTC and Saturday in Paris."""
    ts = pd.Timestamp("2026-07-31 23:30", tz="UTC")
    assert to_date(ts, tz="UTC") == date(2026, 7, 31)
    assert to_date(ts, tz="Europe/Paris") == date(2026, 8, 1)


def test_default_tz_escape_hatch():
    aware = datetime(2026, 7, 31, 23, 30, tzinfo=timezone.utc)
    config.default_tz = "Europe/Paris"
    assert to_date(aware) == date(2026, 8, 1)


def test_aware_sequence_needs_a_tz():
    index = pd.DatetimeIndex(["2026-07-31 23:30"]).tz_localize("UTC")
    with pytest.raises(AmbiguousTimezoneError):
        to_days(index)
    assert list(to_days(index, tz="Europe/Paris")) == [FRIDAY_DAY + 1]


def test_unknown_timezone_is_actionable():
    aware = datetime(2026, 7, 31, tzinfo=timezone.utc)
    with pytest.raises(BetterCalendarError, match="IANA name"):
        to_date(aware, tz="Europe/Atlantis")


# --- type preservation (I6) ------------------------------------------------

PRESERVED = [
    FRIDAY,
    datetime(2026, 7, 31, 9, 30),
    pd.Timestamp("2026-07-31 09:30"),
    np.datetime64("2026-07-31"),
    np.datetime64("2026-07-31T09:30", "ns"),
    "2026-07-31",
    "20260731",
    20260731,
]


@pytest.mark.parametrize("value", PRESERVED)
def test_type_is_preserved(value):
    result = from_days(FRIDAY_DAY + 1, like=value)
    assert type(result) is type(value)


@pytest.mark.parametrize("value", PRESERVED)
def test_round_trip_through_days(value):
    assert from_days(to_days(value), like=value) == value


def test_string_shape_is_preserved():
    assert from_days(FRIDAY_DAY + 1, like="20260731") == "20260801"
    assert from_days(FRIDAY_DAY + 1, like="2026-07-31") == "2026-08-01"
    assert from_days(FRIDAY_DAY + 1, like="2026-07-31T14:30:00") == "2026-08-01T14:30:00"


def test_numpy_unit_and_time_are_preserved():
    value = np.datetime64("2026-07-31T09:30", "ns")
    result = from_days(FRIDAY_DAY + 1, like=value)
    assert result == np.datetime64("2026-08-01T09:30", "ns")
    assert result.dtype == value.dtype


def test_wall_clock_and_tzinfo_survive_a_dst_transition():
    """I5: +1 day across the spring transition is +23h in absolute terms, by design."""
    before = datetime(2026, 3, 28, 9, 0, tzinfo=PARIS)
    after = from_days(to_days(before, tz="Europe/Paris") + 1, like=before)
    assert after.hour == 9
    assert after.tzinfo is PARIS
    # CET -> CEST: the wall clock is unchanged, so only 23 hours actually elapsed.
    assert after.astimezone(timezone.utc) - before.astimezone(timezone.utc) == timedelta(
        hours=23
    )


def test_sequence_returns_a_datetime_index():
    result = from_days(np.array([FRIDAY_DAY, FRIDAY_DAY + 3], dtype=np.int64), like=[FRIDAY])
    assert isinstance(result, pd.DatetimeIndex)
    assert list(result.strftime("%Y-%m-%d")) == ["2026-07-31", "2026-08-03"]


def test_aware_index_keeps_wall_clock_and_zone():
    index = pd.DatetimeIndex(["2026-03-28 09:00"]).tz_localize("Europe/Paris")
    days = to_days(index, tz="Europe/Paris")
    result = from_days(days + 1, like=index)
    assert str(result.tz) == "Europe/Paris"
    assert list(result.strftime("%Y-%m-%d %H:%M")) == ["2026-03-29 09:00"]


def test_empty_sequence():
    assert to_days([]).shape == (0,)
