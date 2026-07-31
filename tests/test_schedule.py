"""M6: recurrences, generators and coupon schedules (§8)."""

from __future__ import annotations

from datetime import date

import pytest

import better_calendar as bcal
from better_calendar import (
    FRI,
    MON,
    THU,
    TUE,
    WED,
    Calendar,
    Roll,
    Schedule,
    Weekday,
)
from better_calendar.core.errors import BetterCalendarError, ScheduleError
from better_calendar.schedule.stubs import unadjusted_dates


def iso(index) -> list[str]:
    return list(index.strftime("%Y-%m-%d"))


# --- the two examples that motivated the library (§8) -------------------------


def test_last_friday_of_each_month():
    dates = bcal.last_weekday("2026-01-01", "2026-12-31", FRI)
    assert iso(dates) == [
        "2026-01-30",
        "2026-02-27",
        "2026-03-27",
        "2026-04-24",
        "2026-05-29",
        "2026-06-26",
        "2026-07-31",
        "2026-08-28",
        "2026-09-25",
        "2026-10-30",
        "2026-11-27",
        "2026-12-25",
    ]
    assert all(date.fromisoformat(day).weekday() == FRI for day in iso(dates))


def test_second_thursday_of_each_quarter():
    dates = bcal.nth_weekday("2026-01-01", "2026-12-31", 2, THU, freq="Q")
    assert iso(dates) == ["2026-01-08", "2026-04-09", "2026-07-09", "2026-10-08"]
    assert all(date.fromisoformat(day).weekday() == THU for day in iso(dates))


# --- weekday constants --------------------------------------------------------


def test_weekday_matches_the_stdlib():
    assert (MON, TUE, WED, THU, FRI) == (0, 1, 2, 3, 4)
    assert date(2026, 7, 31).weekday() == FRI
    assert list(Weekday) == [0, 1, 2, 3, 4, 5, 6]


# --- nth_weekday --------------------------------------------------------------


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (1, "2026-01-02"),
        (2, "2026-01-09"),
        (5, "2026-01-30"),
        (-1, "2026-01-30"),
        (-2, "2026-01-23"),
        (-5, "2026-01-02"),
    ],
)
def test_nth_and_negative_n(n, expected):
    assert iso(bcal.nth_weekday("2026-01-01", "2026-01-31", n, FRI)) == [expected]


def test_missing_occurrences_are_skipped_silently():
    """§8: February rarely has a fifth Friday, and that must not raise."""
    dates = bcal.nth_weekday("2026-01-01", "2026-12-31", 5, FRI)
    assert iso(dates) == ["2026-01-30", "2026-05-29", "2026-07-31", "2026-10-30"]


def test_n_zero_is_rejected():
    with pytest.raises(BetterCalendarError, match="1-based"):
        bcal.nth_weekday("2026-01-01", "2026-12-31", 0, FRI)


def test_the_occurrence_belongs_to_the_period_not_the_window():
    """Asking from mid-January still returns January's last Friday."""
    assert iso(bcal.last_weekday("2026-01-15", "2026-01-31", FRI)) == ["2026-01-30"]
    # ... but one that falls before the window is filtered out.
    assert iso(bcal.nth_weekday("2026-01-15", "2026-01-31", 1, FRI)) == []


def test_inverted_window_is_rejected():
    with pytest.raises(BetterCalendarError, match=r"ends .* before it starts"):
        bcal.last_weekday("2026-12-31", "2026-01-01", FRI)


def test_roll_adjusts_the_result():
    # 2026-07-03 is the third Friday of no month, but Independence Day observed is a
    # holiday on XNYS; use Christmas Day 2026, a Friday, as the clean case.
    assert iso(bcal.last_weekday("2026-12-01", "2026-12-31", FRI)) == ["2026-12-25"]
    adjusted = bcal.last_weekday(
        "2026-12-01", "2026-12-31", FRI, cal="XNYS", roll=Roll.PRECEDING
    )
    assert iso(adjusted) == ["2026-12-24"]


def test_frequency_multiples_anchor_on_the_start():
    dates = bcal.nth_day("2026-02-01", "2026-12-31", 1, freq="3M")
    assert iso(dates) == ["2026-02-01", "2026-05-01", "2026-08-01", "2026-11-01"]


def test_weekly_frequency():
    dates = bcal.nth_weekday("2026-01-01", "2026-01-31", 1, MON, freq="W")
    assert iso(dates) == ["2026-01-05", "2026-01-12", "2026-01-19", "2026-01-26"]


# --- nth_day ------------------------------------------------------------------


def test_nth_day():
    assert iso(bcal.nth_day("2026-01-01", "2026-03-31", 1)) == [
        "2026-01-01",
        "2026-02-01",
        "2026-03-01",
    ]
    assert iso(bcal.nth_day("2026-01-01", "2026-03-31", -1)) == [
        "2026-01-31",
        "2026-02-28",
        "2026-03-31",
    ]


def test_nth_day_skips_short_periods():
    """The 30th of February does not exist, so February is simply absent."""
    dates = bcal.nth_day("2026-01-01", "2026-12-31", 30)
    assert len(dates) == 11
    assert "2026-02-30" not in iso(dates)


# --- nth_business_day ---------------------------------------------------------


def test_nth_business_day():
    assert iso(bcal.nth_business_day("2026-01-01", "2026-03-31", 1, cal="XNYS")) == [
        "2026-01-02",
        "2026-02-02",
        "2026-03-02",
    ]
    assert iso(bcal.nth_business_day("2026-01-01", "2026-03-31", -1, cal="XNYS")) == [
        "2026-01-30",
        "2026-02-27",
        "2026-03-31",
    ]


def test_nth_business_day_result_is_always_a_business_day():
    calendar = bcal.get("XNYS")
    for n in (1, 3, -1, -3):
        for day in iso(bcal.nth_business_day("2026-01-01", "2026-12-31", n, cal="XNYS")):
            assert calendar.is_bday(day) is True


def test_nth_business_day_skips_periods_that_are_too_short():
    dates = bcal.nth_business_day("2026-01-01", "2026-12-31", 23, cal="XNYS")
    assert len(dates) < 12


# --- generators ---------------------------------------------------------------


def test_month_ends_calendar_versus_business():
    assert iso(bcal.month_ends("2026-01-01", "2026-03-31")) == [
        "2026-01-31",
        "2026-02-28",
        "2026-03-31",
    ]
    # 31 January and 28 February 2026 are Saturdays.
    assert iso(bcal.month_ends("2026-01-01", "2026-03-31", cal="XNYS")) == [
        "2026-01-30",
        "2026-02-27",
        "2026-03-31",
    ]


def test_quarter_ends():
    assert iso(bcal.quarter_ends("2026-01-01", "2026-12-31")) == [
        "2026-03-31",
        "2026-06-30",
        "2026-09-30",
        "2026-12-31",
    ]


def test_quarter_ends_with_a_fiscal_anchor():
    dates = bcal.quarter_ends("2026-01-01", "2026-12-31", anchor_month=2)
    assert iso(dates) == ["2026-02-28", "2026-05-31", "2026-08-31", "2026-11-30"]


def test_year_ends():
    assert iso(bcal.year_ends("2025-01-01", "2027-06-30")) == ["2025-12-31", "2026-12-31"]


def test_imm_dates():
    """Third Wednesday of March, June, September and December."""
    dates = bcal.imm_dates("2026-01-01", "2027-12-31")
    assert iso(dates) == [
        "2026-03-18",
        "2026-06-17",
        "2026-09-16",
        "2026-12-16",
        "2027-03-17",
        "2027-06-16",
        "2027-09-15",
        "2027-12-15",
    ]
    for day in iso(dates):
        parsed = date.fromisoformat(day)
        assert parsed.weekday() == WED
        assert parsed.month in (3, 6, 9, 12)
        assert 15 <= parsed.day <= 21  # the third Wednesday is always in this range


def test_imm_is_the_third_wednesday_of_the_month_not_of_the_quarter():
    """Q1 2026 starts on a Thursday; its third Wednesday is in January, not March."""
    quarter_third_wed = bcal.nth_weekday("2026-01-01", "2026-03-31", 3, WED, freq="Q")
    assert iso(quarter_third_wed) == ["2026-01-21"]
    assert iso(bcal.imm_dates("2026-01-01", "2026-03-31")) == ["2026-03-18"]


def test_option_expiries():
    dates = bcal.option_expiries("2026-01-01", "2026-04-30", cal="XNYS")
    assert iso(dates) == ["2026-01-16", "2026-02-20", "2026-03-20", "2026-04-17"]


def test_option_expiry_moves_back_off_good_friday():
    """In 2022 the third Friday of April was Good Friday; expiry moved to the Thursday."""
    assert iso(bcal.nth_weekday("2022-04-01", "2022-04-30", 3, FRI)) == ["2022-04-15"]
    assert iso(bcal.option_expiries("2022-04-01", "2022-04-30", cal="XNYS")) == ["2022-04-14"]


# --- Schedule -----------------------------------------------------------------


def test_regular_schedule():
    schedule = Schedule("2026-01-15", "2027-01-15", freq="6M")
    assert iso(schedule.unadjusted()) == ["2026-01-15", "2026-07-15", "2027-01-15"]
    assert len(schedule) == 3


@pytest.mark.parametrize(
    ("stub", "expected"),
    [
        ("short_front", ["2026-01-15", "2026-03-15", "2026-06-15"]),
        ("long_front", ["2026-01-15", "2026-06-15"]),
        ("short_back", ["2026-01-15", "2026-04-15", "2026-06-15"]),
        ("long_back", ["2026-01-15", "2026-06-15"]),
    ],
)
def test_stubs(stub, expected):
    """A five-month term at a quarterly frequency leaves two months to place."""
    schedule = Schedule("2026-01-15", "2026-06-15", freq="3M", stub=stub)
    assert iso(schedule.unadjusted()) == expected


def test_stub_none_requires_a_whole_number_of_periods():
    assert iso(Schedule("2026-01-15", "2026-07-15", freq="3M", stub="none").unadjusted()) == [
        "2026-01-15",
        "2026-04-15",
        "2026-07-15",
    ]
    with pytest.raises(ScheduleError, match="not a whole number"):
        Schedule("2026-01-15", "2026-06-15", freq="3M", stub="none").unadjusted()


def test_unknown_stub_is_actionable():
    with pytest.raises(ScheduleError, match="Unknown stub convention"):
        Schedule("2026-01-15", "2026-06-15", stub="sideways").unadjusted()


def test_front_stubs_anchor_on_the_end_date():
    """Coupon dates must land on maturity, not drift away from it."""
    schedule = Schedule("2026-01-10", "2027-01-15", freq="6M", stub="short_front")
    dates = iso(schedule.unadjusted())
    assert dates[-1] == "2027-01-15"
    assert dates == ["2026-01-10", "2026-01-15", "2026-07-15", "2027-01-15"]


def test_back_stubs_anchor_on_the_start_date():
    schedule = Schedule("2026-01-10", "2027-01-15", freq="6M", stub="short_back")
    dates = iso(schedule.unadjusted())
    assert dates[0] == "2026-01-10"
    assert dates == ["2026-01-10", "2026-07-10", "2027-01-10", "2027-01-15"]


def test_dates_are_measured_from_the_anchor_not_iteratively():
    """31 January stepping monthly must return to the 31st, not stay on the 28th."""
    schedule = Schedule("2026-01-31", "2026-05-31", freq="1M", stub="short_back")
    assert iso(schedule.unadjusted()) == [
        "2026-01-31",
        "2026-02-28",
        "2026-03-31",
        "2026-04-30",
        "2026-05-31",
    ]


def test_eom_rule():
    plain = Schedule("2026-02-28", "2026-08-31", freq="3M", stub="short_back")
    assert iso(plain.unadjusted()) == ["2026-02-28", "2026-05-28", "2026-08-28", "2026-08-31"]
    with_eom = Schedule("2026-02-28", "2026-08-31", freq="3M", eom=True, stub="short_back")
    assert iso(with_eom.unadjusted()) == ["2026-02-28", "2026-05-31", "2026-08-31"]


def test_same_start_and_end():
    assert iso(Schedule("2026-01-15", "2026-01-15").unadjusted()) == ["2026-01-15"]


def test_inverted_schedule_is_rejected():
    with pytest.raises(ScheduleError, match=r"ends .* before it starts"):
        Schedule("2027-01-15", "2026-01-15").unadjusted()


# --- the critical architectural rule (§8.1) -----------------------------------


def test_unadjusted_needs_no_calendar_at_all():
    """§8.1: the unadjusted schedule must be reproducible with no calendar."""
    from_terms = unadjusted_dates(date(2026, 1, 15), date(2027, 1, 15), "6M")
    for calendar in (None, "XNYS", "fin:TARGET2", Calendar("odd", holidays=["2026-07-15"])):
        schedule = Schedule("2026-01-15", "2027-01-15", freq="6M", cal=calendar)
        assert [date.fromisoformat(day) for day in iso(schedule.unadjusted())] == from_terms


def test_the_calendar_moves_only_the_adjusted_dates():
    quiet = Schedule("2026-01-15", "2027-01-15", freq="6M", cal="weekday")
    closed = Schedule(
        "2026-01-15",
        "2027-01-15",
        freq="6M",
        cal=Calendar("odd", holidays=["2026-07-15", "2026-07-16"]),
    )
    assert iso(quiet.unadjusted()) == iso(closed.unadjusted())
    assert iso(quiet.dates()) != iso(closed.dates())
    assert iso(closed.dates()) == ["2026-01-15", "2026-07-17", "2027-01-15"]


def test_adjusted_dates_are_business_days():
    calendar = bcal.get("XNYS")
    schedule = Schedule("2026-01-01", "2028-01-01", freq="3M", cal="XNYS")
    for day in iso(schedule.dates()):
        assert calendar.is_bday(day) is True


def test_periods_tile_without_overlap():
    schedule = Schedule("2026-01-15", "2027-01-15", freq="3M")
    periods = schedule.periods()
    assert len(periods) == len(schedule.dates()) - 1
    for earlier, later in zip(periods, periods[1:]):
        assert earlier.end == later.start
    assert periods[0].closed == "left"


def test_schedule_is_frozen_and_hashable():
    schedule = Schedule("2026-01-15", "2027-01-15")
    assert {schedule, Schedule("2026-01-15", "2027-01-15")} == {schedule}
    with pytest.raises(Exception, match=r"frozen|cannot assign"):
        schedule.freq = "3M"  # type: ignore[misc]  # the point of the test


def test_default_roll_is_modified_following():
    assert Schedule("2026-01-15", "2027-01-15").roll is Roll.MODIFIED_FOLLOWING
