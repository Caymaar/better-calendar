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
    Nth,
    Roll,
    Weekday,
    periods,
    schedule,
)
from better_calendar.core.errors import BetterCalendarError, ScheduleError
from better_calendar.schedule.stubs import unadjusted_dates


def iso(index) -> list[str]:
    return list(index.strftime("%Y-%m-%d"))


def edges(start, end, freq="6M", **kwargs):
    """What `Schedule(...).unadjusted()` / `.dates()` used to be, now one call."""
    return schedule(start, end, freq, "edges", **kwargs)


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


# --- on="edges" : ce que la classe Schedule faisait ----------------------------


def test_regular_boundaries():
    assert iso(edges("2026-01-15", "2027-01-15")) == [
        "2026-01-15",
        "2026-07-15",
        "2027-01-15",
    ]


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
    assert iso(edges("2026-01-15", "2026-06-15", "3M", stub=stub)) == expected


def test_stub_none_requires_a_whole_number_of_periods():
    assert iso(edges("2026-01-15", "2026-07-15", "3M", stub="none")) == [
        "2026-01-15",
        "2026-04-15",
        "2026-07-15",
    ]
    with pytest.raises(ScheduleError, match="not a whole number"):
        edges("2026-01-15", "2026-06-15", "3M", stub="none")


def test_unknown_stub_is_actionable():
    with pytest.raises(ScheduleError, match="Unknown stub convention"):
        edges("2026-01-15", "2026-06-15", stub="sideways")


def test_front_stubs_anchor_on_the_end_date():
    """Coupon dates must land on maturity, not drift away from it."""
    dates = iso(edges("2026-01-10", "2027-01-15", stub="short_front"))
    assert dates[-1] == "2027-01-15"
    assert dates == ["2026-01-10", "2026-01-15", "2026-07-15", "2027-01-15"]


def test_back_stubs_anchor_on_the_start_date():
    dates = iso(edges("2026-01-10", "2027-01-15", stub="short_back"))
    assert dates[0] == "2026-01-10"
    assert dates == ["2026-01-10", "2026-07-10", "2027-01-10", "2027-01-15"]


def test_dates_are_measured_from_the_anchor_not_iteratively():
    """31 January stepping monthly must return to the 31st, not stay on the 28th."""
    assert iso(edges("2026-01-31", "2026-05-31", "1M", stub="short_back")) == [
        "2026-01-31",
        "2026-02-28",
        "2026-03-31",
        "2026-04-30",
        "2026-05-31",
    ]


def test_eom_rule():
    plain = edges("2026-02-28", "2026-08-31", "3M", stub="short_back")
    assert iso(plain) == ["2026-02-28", "2026-05-28", "2026-08-28", "2026-08-31"]
    with_eom = edges("2026-02-28", "2026-08-31", "3M", eom=True, stub="short_back")
    assert iso(with_eom) == ["2026-02-28", "2026-05-31", "2026-08-31"]


def test_same_start_and_end():
    assert iso(edges("2026-01-15", "2026-01-15")) == ["2026-01-15"]


def test_inverted_schedule_is_rejected():
    with pytest.raises(BetterCalendarError, match=r"ends .* before it starts"):
        edges("2027-01-15", "2026-01-15")


def test_edges_refuses_options_that_do_not_apply():
    with pytest.raises(ScheduleError, match="months="):
        schedule("2026-01-01", "2026-12-31", "3M", "edges", months=(3, 6, 9, 12))
    with pytest.raises(ScheduleError, match="cannot be combined"):
        schedule("2026-01-01", "2026-12-31", "3M", ["edges", "last"])


# --- the critical architectural rule (§8.1) -----------------------------------


def test_unadjusted_needs_no_calendar_at_all():
    """§8.1: the unadjusted schedule must be reproducible with no calendar."""
    from_terms = unadjusted_dates(date(2026, 1, 15), date(2027, 1, 15), "6M")
    for calendar in (None, "XNYS", "fin:TARGET2", Calendar("odd", holidays=["2026-07-15"])):
        produced = edges("2026-01-15", "2027-01-15", cal=calendar)
        assert [date.fromisoformat(day) for day in iso(produced)] == from_terms


def test_the_calendar_moves_only_the_adjusted_dates():
    """Unadjusted is a function of the terms; only `roll` lets the calendar in."""
    closed = Calendar("odd", holidays=["2026-07-15", "2026-07-16"])
    quiet = "weekday"

    assert iso(edges("2026-01-15", "2027-01-15", cal=quiet)) == iso(
        edges("2026-01-15", "2027-01-15", cal=closed)
    )
    adjusted_quiet = edges("2026-01-15", "2027-01-15", cal=quiet, roll=Roll.MODIFIED_FOLLOWING)
    adjusted_closed = edges(
        "2026-01-15", "2027-01-15", cal=closed, roll=Roll.MODIFIED_FOLLOWING
    )
    assert iso(adjusted_quiet) != iso(adjusted_closed)
    assert iso(adjusted_closed) == ["2026-01-15", "2026-07-17", "2027-01-15"]


def test_roll_is_opt_in_everywhere():
    """No calendar can move a date unless `roll` is set. That is the whole separation."""
    naked = edges("2026-02-28", "2026-08-31", "3M", cal="XNYS")
    assert iso(naked)[0] == "2026-02-28"  # a Saturday, left alone
    rolled = edges("2026-02-28", "2026-08-31", "3M", cal="XNYS", roll="MF")
    assert iso(rolled)[0] == "2026-02-27"


def test_adjusted_dates_are_business_days():
    calendar = bcal.get("XNYS")
    produced = edges("2026-01-01", "2028-01-01", "3M", cal="XNYS", roll=Roll.MODIFIED_FOLLOWING)
    for day in iso(produced):
        assert calendar.is_bday(day) is True


def test_periods_tile_without_overlap():
    boundaries = edges("2026-01-15", "2027-01-15", "3M")
    intervals = periods("2026-01-15", "2027-01-15", "3M")
    assert len(intervals) == len(boundaries) - 1
    for earlier, later in zip(intervals, intervals[1:]):
        assert earlier.end == later.start
    assert intervals[0].closed == "left"


def test_periods_works_with_any_selector():
    monthly = periods("2026-01-01", "2026-12-31", "M", "last")
    assert len(monthly) == 11
    assert str(monthly[0].start) == "2026-01-31"


# --- the generic engine -------------------------------------------------------


def test_the_named_functions_are_the_engine():
    """Each wrapper must be exactly its `schedule(...)` spelling, or the docs lie."""
    window = ("2026-01-01", "2026-12-31")
    equivalences = [
        (bcal.last_weekday(*window, FRI), schedule(*window, "M", "last FRI")),
        (bcal.nth_weekday(*window, 2, THU, freq="Q"), schedule(*window, "Q", "2 THU")),
        (bcal.nth_day(*window, 1), schedule(*window, "M", "1")),
        (bcal.nth_day(*window, -1), schedule(*window, "M", "last")),
        (
            bcal.nth_business_day(*window, 1, cal="XNYS"),
            schedule(*window, "M", "1 B", cal="XNYS"),
        ),
        (bcal.month_ends(*window), schedule(*window, "M", "last")),
        (bcal.month_ends(*window, cal="XNYS"), schedule(*window, "M", "last B", cal="XNYS")),
        (bcal.quarter_ends(*window), schedule(*window, "Q", "last")),
        (bcal.year_ends(*window), schedule(*window, "Y", "last")),
        (bcal.imm_dates(*window), schedule(*window, "M", "3 WED", months=(3, 6, 9, 12))),
        (
            bcal.option_expiries(*window, cal="XNYS"),
            schedule(*window, "M", "3 FRI", cal="XNYS", roll=Roll.PRECEDING),
        ),
    ]
    for named, generic in equivalences:
        assert iso(named) == iso(generic)


@pytest.mark.parametrize(
    ("on", "expected"),
    [
        ("1", ["2026-01-01", "2026-02-01", "2026-03-01"]),
        ("first", ["2026-01-01", "2026-02-01", "2026-03-01"]),
        ("15", ["2026-01-15", "2026-02-15", "2026-03-15"]),
        ("last", ["2026-01-31", "2026-02-28", "2026-03-31"]),
        ("-1", ["2026-01-31", "2026-02-28", "2026-03-31"]),
        ("-2", ["2026-01-30", "2026-02-27", "2026-03-30"]),
        ("1 B", ["2026-01-01", "2026-02-02", "2026-03-02"]),
        ("last B", ["2026-01-30", "2026-02-27", "2026-03-31"]),
        ("1st FRI", ["2026-01-02", "2026-02-06", "2026-03-06"]),
        ("2 THU", ["2026-01-08", "2026-02-12", "2026-03-12"]),
        ("last FRI", ["2026-01-30", "2026-02-27", "2026-03-27"]),
        ("-2 WED", ["2026-01-21", "2026-02-18", "2026-03-18"]),
    ],
)
def test_selector_grammar(on, expected):
    assert iso(schedule("2026-01-01", "2026-03-31", "M", on)) == expected


def test_ordinal_suffixes_are_cosmetic():
    for pair in (("1 B", "1st B"), ("2 THU", "2nd THU"), ("3 WED", "3rd WED"), ("4", "4th")):
        assert iso(schedule("2026-01-01", "2026-03-31", "M", pair[0])) == iso(
            schedule("2026-01-01", "2026-03-31", "M", pair[1])
        )


def test_selector_accepts_the_value_object():
    window = ("2026-01-01", "2026-03-31")
    assert iso(schedule(*window, "M", Nth(-1, FRI))) == iso(schedule(*window, "M", "last FRI"))
    assert iso(schedule(*window, "M", Nth(1, "B"))) == iso(schedule(*window, "M", "1 B"))
    assert iso(schedule(*window, "M", Nth(-1))) == iso(schedule(*window, "M", "last"))


def test_selector_round_trips_through_its_string():
    for text in ("last", "first", "15", "-2", "last B", "2 THU", "-2 WED"):
        assert isinstance(bcal.parse_selector(text), Nth)
        assert iso(schedule("2026-01-01", "2026-03-31", "M", text)) == iso(
            schedule("2026-01-01", "2026-03-31", "M", str(bcal.parse_selector(text)))
        )


@pytest.mark.parametrize(
    "on", ["", "   ", "0", "0 FRI", "last week", "2 FUNDAY", "one", "last FRI extra", "1.5"]
)
def test_bad_selectors_are_actionable(on):
    with pytest.raises(ScheduleError):
        schedule("2026-01-01", "2026-03-31", "M", on)


def test_business_selector_and_roll_are_different_axes():
    """`last B` counts business days; `roll` moves a calendar day onto one."""
    counted = schedule("2026-01-01", "2026-01-31", "M", "last B", cal="XNYS")
    rolled = schedule("2026-01-01", "2026-01-31", "M", "last", cal="XNYS", roll="P")
    assert iso(counted) == iso(rolled) == ["2026-01-30"]

    # They part company as soon as the ordinal is not the last one.
    counted_third = schedule("2026-01-01", "2026-01-31", "M", "3 B", cal="XNYS")
    rolled_third = schedule("2026-01-01", "2026-01-31", "M", "3", cal="XNYS", roll="F")
    assert iso(counted_third) == ["2026-01-06"]
    assert iso(rolled_third) == ["2026-01-05"]


def test_every_calendar_aligned_versus_start_anchored():
    """ "Q" is a calendar quarter; "3M" is three months from the start date."""
    calendar_aligned = schedule("2026-02-01", "2026-12-31", "Q", "1")
    start_anchored = schedule("2026-02-01", "2026-12-31", "3M", "1")
    assert iso(calendar_aligned) == ["2026-04-01", "2026-07-01", "2026-10-01"]
    assert iso(start_anchored) == ["2026-02-01", "2026-05-01", "2026-08-01", "2026-11-01"]


def test_daily_and_weekly_periods():
    every_day = schedule("2026-07-27", "2026-08-02", "D", "1")
    assert len(every_day) == 7
    # A one-day period whose only day is not a business day simply has none.
    business_days = schedule("2026-07-27", "2026-08-02", "D", "1 B", cal="XNYS")
    assert iso(business_days) == [
        "2026-07-27",
        "2026-07-28",
        "2026-07-29",
        "2026-07-30",
        "2026-07-31",
    ]
    # The week containing 1 January starts on Monday 29 December, whose first business
    # day falls before the window — so it is filtered out, not moved.
    assert iso(schedule("2026-01-01", "2026-01-31", "W", "1 B")) == [
        "2026-01-05",
        "2026-01-12",
        "2026-01-19",
        "2026-01-26",
    ]


def test_months_filter():
    quarterly = schedule("2026-01-01", "2026-12-31", "M", "last", months=(3, 6, 9, 12))
    assert iso(quarterly) == ["2026-03-31", "2026-06-30", "2026-09-30", "2026-12-31"]


def test_several_selectors_are_merged_sorted_and_deduplicated():
    both = schedule("2026-01-01", "2026-02-28", "M", ["1", "15"])
    assert iso(both) == ["2026-01-01", "2026-01-15", "2026-02-01", "2026-02-15"]
    # "last" and "-1" are the same day, and must not appear twice.
    once = schedule("2026-01-01", "2026-01-31", "M", ["last", "-1"])
    assert iso(once) == ["2026-01-31"]


# --- missing occurrences ------------------------------------------------------


def test_missing_skip_is_the_default():
    assert len(schedule("2026-01-01", "2026-12-31", "M", "5 FRI")) == 4
    assert len(schedule("2026-01-01", "2026-12-31", "M", "31")) == 7


def test_missing_clamp_takes_the_nearest_occurrence():
    """ "the 31st of each month" is a real contract term; clamp makes it expressible."""
    assert iso(schedule("2026-01-01", "2026-04-30", "M", "31", missing="clamp")) == [
        "2026-01-31",
        "2026-02-28",
        "2026-03-31",
        "2026-04-30",
    ]
    # A fifth Friday that does not exist clamps onto the fourth.
    clamped = schedule("2026-02-01", "2026-02-28", "M", "5 FRI", missing="clamp")
    assert iso(clamped) == ["2026-02-27"]
    # Counting back, it clamps onto the first.
    clamped_back = schedule("2026-02-01", "2026-02-28", "M", "-5 FRI", missing="clamp")
    assert iso(clamped_back) == ["2026-02-06"]


def test_missing_clamp_on_business_days():
    assert iso(schedule("2026-01-01", "2026-02-28", "M", "30 B", missing="clamp")) == [
        "2026-01-30",
        "2026-02-27",
    ]


def test_missing_raise_names_the_period():
    with pytest.raises(ScheduleError, match="2026-02-01 has no"):
        schedule("2026-01-01", "2026-12-31", "M", "31", missing="raise")


def test_missing_raise_is_silent_when_nothing_is_missing():
    assert len(schedule("2026-01-01", "2026-12-31", "M", "28", missing="raise")) == 12


def test_unknown_missing_policy():
    with pytest.raises(ScheduleError, match="missing-occurrence policy"):
        schedule("2026-01-01", "2026-12-31", "M", "1", missing="invent")
