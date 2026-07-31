"""M3: calendar set operations (§6) — the vocabulary trap lives here."""

from __future__ import annotations

from datetime import date, time

import numpy as np
import pytest

from better_calendar import Calendar
from better_calendar.calendars.algebra import all_open, any_open
from better_calendar.core.errors import BetterCalendarError

BOUNDS = (date(2026, 1, 1), date(2026, 12, 31))


@pytest.fixture
def nyse_like() -> Calendar:
    return Calendar("nyse-like", holidays=["2026-07-03"], bounds=BOUNDS, tz="America/New_York")


@pytest.fixture
def target_like() -> Calendar:
    return Calendar("target-like", holidays=["2026-04-06"], bounds=BOUNDS, tz="Europe/Brussels")


# --- the vocabulary trap ---------------------------------------------------


def test_and_is_the_union_of_holidays(nyse_like, target_like):
    """`a & b` = good in BOTH = closed if EITHER is closed. The settlement case."""
    both = nyse_like & target_like
    assert both.is_bday("2026-07-03") is False  # closed in New York
    assert both.is_bday("2026-04-06") is False  # closed in the euro area
    assert both.is_bday("2026-07-02") is True


def test_or_is_the_intersection_of_holidays(nyse_like, target_like):
    either = nyse_like | target_like
    assert either.is_bday("2026-07-03") is True
    assert either.is_bday("2026-04-06") is True
    assert either.is_bday("2026-07-04") is False  # a Saturday: neither is open


def test_difference(nyse_like, target_like):
    only_nyse = nyse_like - target_like
    assert only_nyse.is_bday("2026-04-06") is True
    assert only_nyse.is_bday("2026-07-03") is False
    assert only_nyse.is_bday("2026-07-02") is False


def test_symmetric_difference(nyse_like, target_like):
    exactly_one = nyse_like ^ target_like
    assert exactly_one.is_bday("2026-04-06") is True
    assert exactly_one.is_bday("2026-07-03") is True
    assert exactly_one.is_bday("2026-07-02") is False


def test_verbose_aliases_match_the_operators(nyse_like, target_like):
    assert all_open([nyse_like, target_like]) == nyse_like & target_like
    assert any_open([nyse_like, target_like]) == nyse_like | target_like
    assert Calendar.all_open([nyse_like, target_like]) == nyse_like & target_like
    assert Calendar.any_open([nyse_like, target_like]) == nyse_like | target_like


# --- heterogeneous weekmasks -----------------------------------------------


def test_disagreeing_weekends(small, gulf):
    """Sun-Thu against Mon-Fri: merging weekmask strings would get this wrong."""
    both = small & gulf
    assert both.weekmask == "Mon Tue Wed Thu"
    either = small | gulf
    assert either.weekmask == "Mon Tue Wed Thu Fri Sun"
    assert either.is_bday("2026-08-01") is False  # Saturday: closed everywhere
    assert either.is_bday("2026-08-02") is True  # Sunday: the Gulf calendar is open


# --- composite properties --------------------------------------------------


def test_composite_name_is_deterministic(nyse_like, target_like):
    assert (nyse_like & target_like).name == "(nyse-like & target-like)"
    assert (nyse_like | target_like).name == "(nyse-like | target-like)"
    assert (nyse_like - target_like).name == "(nyse-like - target-like)"
    assert (nyse_like ^ target_like).name == "(nyse-like ^ target-like)"


def test_composite_is_a_normal_calendar(nyse_like, target_like):
    both = nyse_like & target_like
    assert isinstance(both, Calendar)
    assert hash(both) == hash(nyse_like & target_like)
    assert both.offset("2026-07-02", 1) == "2026-07-06"  # skips the 3rd and the weekend


def test_bounds_are_intersected():
    a = Calendar("a", bounds=(date(2020, 1, 1), date(2026, 12, 31)))
    b = Calendar("b", bounds=(date(2024, 1, 1), date(2030, 12, 31)))
    assert (a & b).bounds == (date(2024, 1, 1), date(2026, 12, 31))


def test_disjoint_bounds_are_rejected():
    a = Calendar("a", bounds=(date(2020, 1, 1), date(2021, 12, 31)))
    b = Calendar("b", bounds=(date(2024, 1, 1), date(2030, 12, 31)))
    with pytest.raises(BetterCalendarError, match="bounds do not overlap"):
        _ = a & b


def test_composite_drops_a_disagreeing_timezone(nyse_like, target_like):
    """§6: a composite spanning two zones has no meaningful instant semantics."""
    assert (nyse_like & target_like).tz is None


def test_composite_keeps_an_agreed_timezone():
    a = Calendar("a", tz="UTC", session_start=time(17, 0))
    b = Calendar("b", tz="UTC", session_start=time(17, 0))
    composite = a & b
    assert composite.tz == "UTC"
    assert composite.session_start == time(17, 0)


def test_algebra_needs_two_operands():
    with pytest.raises(BetterCalendarError, match="at least two calendars"):
        all_open([Calendar("a")])


# --- properties (§15b) ------------------------------------------------------


def _good_set(cal: Calendar, bounds) -> set[int]:
    return set(cal.good_days(*bounds).tolist())


def test_intersection_is_a_subset_of_both(nyse_like, target_like):
    both = nyse_like & target_like
    assert _good_set(both, BOUNDS) <= _good_set(nyse_like, BOUNDS)
    assert _good_set(both, BOUNDS) <= _good_set(target_like, BOUNDS)


def test_union_is_a_superset_of_both(nyse_like, target_like):
    either = nyse_like | target_like
    assert _good_set(either, BOUNDS) >= _good_set(nyse_like, BOUNDS)
    assert _good_set(either, BOUNDS) >= _good_set(target_like, BOUNDS)


def test_commutativity(nyse_like, target_like):
    assert _good_set(nyse_like | target_like, BOUNDS) == _good_set(
        target_like | nyse_like, BOUNDS
    )
    assert _good_set(nyse_like & target_like, BOUNDS) == _good_set(
        target_like & nyse_like, BOUNDS
    )


def test_associativity(nyse_like, target_like):
    third = Calendar("third", holidays=["2026-05-01"], bounds=BOUNDS)
    left = (nyse_like | target_like) | third
    right = nyse_like | (target_like | third)
    assert _good_set(left, BOUNDS) == _good_set(right, BOUNDS)


def test_from_good_days_round_trips(holiday_cal):
    rebuilt = Calendar.from_good_days(
        "rebuilt", holiday_cal.good_days(), bounds=holiday_cal.bounds
    )
    np.testing.assert_array_equal(rebuilt.good_days(), holiday_cal.good_days())
