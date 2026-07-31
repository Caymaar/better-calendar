"""M2: Calendar membership, roll conventions, offsets and counting."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal

import numpy as np
import pandas as pd
import pytest

from better_calendar import Calendar, Roll
from better_calendar.core.errors import (
    BetterCalendarError,
    NotABusinessDayError,
    OutOfBoundsError,
)

NumpyRoll = Literal["forward", "backward", "modifiedfollowing", "modifiedpreceding"]

#: Our roll conventions paired with the numpy names they must agree with.
NUMPY_ROLLS: list[tuple[Roll, NumpyRoll]] = [
    (Roll.FOLLOWING, "forward"),
    (Roll.PRECEDING, "backward"),
    (Roll.MODIFIED_FOLLOWING, "modifiedfollowing"),
    (Roll.MODIFIED_PRECEDING, "modifiedpreceding"),
]

FRIDAY = "2026-07-31"
SATURDAY = "2026-08-01"
MONDAY = "2026-08-03"


# --- construction and identity (I1) ----------------------------------------


def test_calendar_is_frozen(weekday):
    with pytest.raises(Exception, match=r"frozen|read-only|cannot assign"):
        weekday.name = "nope"


def test_holidays_are_read_only(holiday_cal):
    with pytest.raises(ValueError, match="read-only"):
        holiday_cal.holidays[0] = np.datetime64("2000-01-01")


def test_same_inputs_hash_equal():
    a = Calendar("x", holidays=["2026-07-31", "2026-07-30"])
    b = Calendar("x", holidays=["2026-07-30", "2026-07-31", "2026-07-30"])
    assert a == b
    assert hash(a) == hash(b)
    assert {a, b} == {a}


def test_different_holidays_hash_differently():
    assert Calendar("x", holidays=["2026-07-31"]) != Calendar("x", holidays=["2026-07-30"])


def test_calendar_is_usable_as_a_cache_key(weekday):
    assert {weekday: 1}[Calendar("weekday")] == 1


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("Mon Tue Wed Thu Fri", "Mon Tue Wed Thu Fri"),
        ("1111100", "Mon Tue Wed Thu Fri"),
        ("all", "Mon Tue Wed Thu Fri Sat Sun"),
        ("Fri,Mon", "Mon Fri"),
        ("monday tuesday", "Mon Tue"),
    ],
)
def test_weekmask_is_canonicalised(given, expected):
    assert Calendar("x", weekmask=given).weekmask == expected


def test_empty_weekmask_is_rejected():
    with pytest.raises(BetterCalendarError, match="selects no days"):
        Calendar("x", weekmask="0000000")


def test_inverted_bounds_are_rejected():
    with pytest.raises(BetterCalendarError, match="before they start"):
        Calendar("x", bounds=(date(2030, 1, 1), date(2020, 1, 1)))


# --- membership ------------------------------------------------------------


def test_is_bday_scalar_and_vector(weekday):
    assert weekday.is_bday(FRIDAY) is True
    assert weekday.is_bday(SATURDAY) is False
    np.testing.assert_array_equal(
        weekday.is_bday([FRIDAY, SATURDAY, MONDAY]), [True, False, True]
    )


def test_holidays_are_not_business_days(holiday_cal):
    assert holiday_cal.is_bday("2026-07-30") is False
    assert holiday_cal.is_bday("2026-07-31") is True


def test_crypto_is_always_open():
    crypto = Calendar("crypto", weekmask="all")
    assert crypto.is_bday(SATURDAY) is True


# --- normalisation ---------------------------------------------------------


def test_next_and_prev(weekday):
    assert weekday.next_bday(SATURDAY) == MONDAY
    assert weekday.prev_bday(SATURDAY) == FRIDAY
    assert weekday.next_bday(FRIDAY) == MONDAY
    assert weekday.next_bday(FRIDAY, inclusive=True) == FRIDAY
    assert weekday.prev_bday(MONDAY, inclusive=True) == MONDAY


@pytest.mark.parametrize(
    ("value", "roll", "expected"),
    [
        (SATURDAY, Roll.NONE, SATURDAY),
        (SATURDAY, Roll.FOLLOWING, MONDAY),
        (SATURDAY, Roll.PRECEDING, FRIDAY),
        (SATURDAY, Roll.NEAREST, FRIDAY),
        (FRIDAY, Roll.FOLLOWING, FRIDAY),
        # Sunday 31 May: forward is 1 June, which leaves May.
        ("2026-05-31", Roll.MODIFIED_FOLLOWING, "2026-05-29"),
        ("2026-05-31", Roll.FOLLOWING, "2026-06-01"),
        # Sunday 1 Feb: back is 30 January, which leaves February.
        ("2026-02-01", Roll.MODIFIED_PRECEDING, "2026-02-02"),
        ("2026-02-01", Roll.PRECEDING, "2026-01-30"),
    ],
)
def test_adjust(weekday, value, roll, expected):
    assert weekday.adjust(value, roll) == expected


def test_nearest_ties_go_forward():
    """Sunday between a good Friday and a good Tuesday is exactly two days from each."""
    cal = Calendar("x", holidays=["2026-08-03"])  # close the Monday
    assert cal.adjust("2026-08-02", Roll.NEAREST) == "2026-08-04"


def test_roll_raise(weekday):
    assert weekday.adjust(FRIDAY, Roll.RAISE) == FRIDAY
    with pytest.raises(NotABusinessDayError, match="not a business day"):
        weekday.adjust(SATURDAY, Roll.RAISE)


@pytest.mark.parametrize("alias", ["MF", "mf", "Modified_Following"])
def test_roll_aliases(weekday, alias):
    assert weekday.adjust("2026-05-31", alias) == "2026-05-29"


def test_unknown_roll():
    with pytest.raises(BetterCalendarError, match="Unknown roll convention"):
        Roll.parse("sideways")


# --- offsets ---------------------------------------------------------------


def test_offset(weekday):
    assert weekday.offset(FRIDAY, 1) == MONDAY
    assert weekday.offset(MONDAY, -1) == FRIDAY
    assert weekday.offset(FRIDAY, 0) == FRIDAY
    assert weekday.offset(SATURDAY, 0) == MONDAY  # rolled first, then moved


def test_offset_matches_numpy_busday_offset(weekday):
    """Oracle: numpy is authoritative for a plain weekday calendar (M2)."""
    dates = np.arange(
        np.datetime64("2020-01-01"), np.datetime64("2030-01-01"), dtype="datetime64[D]"
    )
    for n in (-20, -3, -1, 0, 1, 3, 20):
        for roll, np_roll in NUMPY_ROLLS:
            expected = np.busday_offset(dates, n, roll=np_roll)
            actual = weekday.offset(dates, n, roll=roll)
            np.testing.assert_array_equal(actual.values.astype("datetime64[D]"), expected)


def test_adjust_matches_numpy_busday_offset(holiday_cal):
    """Oracle: holidays and weekmask together, against numpy's busdaycalendar."""
    dates = np.arange(
        np.datetime64("2026-07-01"), np.datetime64("2026-09-01"), dtype="datetime64[D]"
    )
    npcal = np.busdaycalendar(weekmask="1111100", holidays=holiday_cal.holidays)
    for roll, np_roll in NUMPY_ROLLS:
        expected = np.busday_offset(dates, 0, roll=np_roll, busdaycal=npcal)
        actual = holiday_cal.adjust(dates, roll)
        np.testing.assert_array_equal(actual.values.astype("datetime64[D]"), expected)


def test_is_bday_matches_numpy(holiday_cal):
    dates = np.arange(
        np.datetime64("2026-01-01"), np.datetime64("2027-01-01"), dtype="datetime64[D]"
    )
    npcal = np.busdaycalendar(weekmask="1111100", holidays=holiday_cal.holidays)
    np.testing.assert_array_equal(
        holiday_cal.is_bday(dates), np.is_busday(dates, busdaycal=npcal)
    )


# --- counting --------------------------------------------------------------


def test_count_conventions(weekday):
    # Mon 27 July .. Sat 1 August 2026.
    assert weekday.count("2026-07-27", "2026-08-01") == 5
    assert weekday.count("2026-07-27", "2026-07-31", closed="left") == 4
    assert weekday.count("2026-07-27", "2026-07-31", closed="both") == 5
    assert weekday.count("2026-07-27", "2026-07-31", closed="right") == 4
    assert weekday.count("2026-07-27", "2026-07-31", closed="neither") == 3


def test_count_is_signed(weekday):
    assert weekday.count("2026-08-01", "2026-07-27") == -5


def test_count_matches_numpy(holiday_cal):
    npcal = np.busdaycalendar(weekmask="1111100", holidays=holiday_cal.holidays)
    assert holiday_cal.count("2026-07-01", "2026-09-01") == int(
        np.busday_count("2026-07-01", "2026-09-01", busdaycal=npcal)
    )


def test_bad_closed_value(weekday):
    with pytest.raises(BetterCalendarError, match="Unknown interval convention"):
        weekday.count(FRIDAY, MONDAY, closed="sideways")


# --- introspection ---------------------------------------------------------


def test_bdays_between(weekday):
    result = weekday.bdays_between("2026-07-27", "2026-08-01")
    assert list(result.strftime("%Y-%m-%d")) == [
        "2026-07-27",
        "2026-07-28",
        "2026-07-29",
        "2026-07-30",
        "2026-07-31",
    ]


def test_holidays_between(holiday_cal):
    result = holiday_cal.holidays_between("2026-07-01", "2026-09-01")
    assert list(result.strftime("%Y-%m-%d")) == ["2026-07-30", "2026-08-03"]


def test_sessions_and_describe(small):
    assert len(small.sessions()) == small.describe()["business_days"]
    info = small.describe()
    assert info["weekmask"] == "Mon Tue Wed Thu Fri"
    assert info["bounds"] == ["2020-01-01", "2030-12-31"]


# --- derivation ------------------------------------------------------------


def test_with_and_without_holidays(weekday):
    closed = weekday.with_holidays([FRIDAY])
    assert closed.is_bday(FRIDAY) is False
    assert weekday.is_bday(FRIDAY) is True  # the original is untouched (I1)
    assert closed.without_holidays(FRIDAY).is_bday(FRIDAY) is True


# --- bounds (I2) -----------------------------------------------------------


def test_query_outside_bounds_raises(small):
    with pytest.raises(OutOfBoundsError, match="2019-12-31"):
        small.is_bday("2019-12-31")
    with pytest.raises(OutOfBoundsError, match="2031-01-01"):
        small.is_bday("2031-01-01")


def test_bounds_message_names_the_calendar_and_the_horizon(small):
    with pytest.raises(OutOfBoundsError, match=r"'small'.*2020-01-01 to 2030-12-31"):
        small.offset("2019-01-01", 1)


def test_offset_off_the_end_raises(small):
    with pytest.raises(OutOfBoundsError, match="Offsetting by"):
        small.offset("2030-12-31", 5)
    with pytest.raises(OutOfBoundsError, match="Offsetting by"):
        small.offset("2020-01-01", -5)


def test_next_bday_off_the_end_raises(small):
    with pytest.raises(OutOfBoundsError):
        small.next_bday("2030-12-31")


def test_min_year_edge():
    cal = Calendar("edge", bounds=(date(1970, 1, 1), date(1970, 12, 31)))
    assert cal.is_bday("1970-01-01") is True  # a Thursday
    with pytest.raises(OutOfBoundsError):
        cal.prev_bday("1970-01-01")


def test_max_year_edge():
    from better_calendar import MAX_YEAR

    cal = Calendar("edge", bounds=(date(MAX_YEAR, 1, 1), date(MAX_YEAR, 12, 31)))
    with pytest.raises(OutOfBoundsError):
        cal.next_bday(f"{MAX_YEAR}-12-31")


# --- type preservation across the calendar API (I6) ------------------------


@pytest.mark.parametrize(
    "value",
    [
        date(2026, 7, 31),
        datetime(2026, 7, 31, 9, 30),
        pd.Timestamp("2026-07-31 09:30"),
        np.datetime64("2026-07-31"),
        "2026-07-31",
        20260731,
    ],
)
@pytest.mark.parametrize("method", ["next_bday", "prev_bday", "adjust"])
def test_calendar_preserves_type(weekday, value, method):
    assert type(getattr(weekday, method)(value)) is type(value)


def test_offset_preserves_wall_clock(weekday):
    moment = datetime(2026, 7, 31, 9, 30)
    assert weekday.offset(moment, 1) == datetime(2026, 8, 3, 9, 30)


def test_sequence_in_index_out(weekday):
    result = weekday.offset([FRIDAY, MONDAY], 1)
    assert isinstance(result, pd.DatetimeIndex)
    assert list(result.strftime("%Y-%m-%d")) == ["2026-08-03", "2026-08-04"]


# --- calendar timezone ------------------------------------------------------


def test_calendar_tz_resolves_aware_inputs():
    cal = Calendar("paris", tz="Europe/Paris")
    ts = pd.Timestamp("2026-07-31 23:30", tz="UTC")  # Saturday in Paris
    assert cal.is_bday(ts) is False
    utc_cal = Calendar("utc", tz="UTC")
    assert utc_cal.is_bday(ts) is True


def test_session_start_participates_in_identity():
    a = Calendar("x", session_start=time(0, 0))
    b = Calendar("x", session_start=time(17, 0))
    assert a != b
