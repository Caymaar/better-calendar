"""Property-based tests (§15b). These are the invariants, stated as code."""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from better_calendar import Calendar, Roll

BOUNDS = (date(2015, 1, 1), date(2035, 12, 31))
# Offsets are tested inside a margin, so that hitting a bound is a separate concern.
INNER = st.dates(min_value=date(2018, 1, 1), max_value=date(2032, 12, 31))
OFFSETS = st.integers(min_value=-250, max_value=250)
ROLLS = st.sampled_from([r for r in Roll if r is not Roll.RAISE])
ADJUSTING_ROLLS = st.sampled_from([r for r in Roll if r not in (Roll.NONE, Roll.RAISE)])

_HOLIDAYS = st.lists(
    st.dates(min_value=BOUNDS[0], max_value=BOUNDS[1]), min_size=0, max_size=40
)
_WEEKMASKS = st.sampled_from(
    ["Mon Tue Wed Thu Fri", "all", "Sun Mon Tue Wed Thu", "Mon Wed Fri", "1111110"]
)


@st.composite
def calendars(draw) -> Calendar:
    return Calendar(
        "prop",
        holidays=draw(_HOLIDAYS),
        weekmask=draw(_WEEKMASKS),
        bounds=BOUNDS,
    )


WEEKDAY = Calendar("weekday", bounds=BOUNDS)


@given(day=INNER, n=OFFSETS)
def test_count_of_an_offset_is_the_offset(day, n):
    """count(d, offset(d, n)) == n, for any good day and any n inside the bounds."""
    assume(WEEKDAY.is_bday(day))
    assert WEEKDAY.count(day, WEEKDAY.offset(day, n)) == n


@given(day=INNER, n=OFFSETS)
def test_offset_round_trips(day, n):
    assume(WEEKDAY.is_bday(day))
    assert WEEKDAY.offset(WEEKDAY.offset(day, n), -n) == day


@given(day=INNER, roll=ROLLS)
def test_adjust_is_idempotent(day, roll):
    once = WEEKDAY.adjust(day, roll)
    assert WEEKDAY.adjust(once, roll) == once


@given(day=INNER, roll=ADJUSTING_ROLLS)
def test_adjust_lands_on_a_business_day(day, roll):
    assert WEEKDAY.is_bday(WEEKDAY.adjust(day, roll)) is True


@given(day=INNER)
def test_modified_following_stays_in_the_month(day):
    adjusted = WEEKDAY.adjust(day, Roll.MODIFIED_FOLLOWING)
    assert (adjusted.year, adjusted.month) == (day.year, day.month)


@given(day=INNER)
def test_modified_preceding_stays_in_the_month(day):
    adjusted = WEEKDAY.adjust(day, Roll.MODIFIED_PRECEDING)
    assert (adjusted.year, adjusted.month) == (day.year, day.month)


@given(day=INNER)
def test_next_and_prev_bracket_the_day(day):
    assert (
        WEEKDAY.prev_bday(day, inclusive=True) <= day <= WEEKDAY.next_bday(day, inclusive=True)
    )


@given(cal=calendars(), day=INNER, n=st.integers(min_value=-50, max_value=50))
@settings(max_examples=50)
def test_properties_hold_for_arbitrary_calendars(cal, day, n):
    assume(cal.is_bday(day))
    moved = cal.offset(day, n)
    assert cal.is_bday(moved) is True
    assert cal.count(day, moved) == n
    assert cal.offset(moved, -n) == day


# --- algebra (§15b) ---------------------------------------------------------


@given(left=calendars(), right=calendars())
@settings(max_examples=30)
def test_intersection_is_contained_in_both(left, right):
    both = set((left & right).good_days().tolist())
    assert both <= set(left.good_days().tolist())
    assert both <= set(right.good_days().tolist())


@given(left=calendars(), right=calendars())
@settings(max_examples=30)
def test_union_is_commutative(left, right):
    np.testing.assert_array_equal((left | right).good_days(), (right | left).good_days())


@given(a=calendars(), b=calendars(), c=calendars())
@settings(max_examples=20)
def test_union_is_associative(a, b, c):
    np.testing.assert_array_equal(((a | b) | c).good_days(), (a | (b | c)).good_days())


@given(left=calendars(), right=calendars())
@settings(max_examples=30)
def test_and_is_the_union_of_the_holiday_sets(left, right):
    """I9 restated as a property: closed in the composite iff closed in either operand."""
    good_left = set(left.good_days().tolist())
    good_right = set(right.good_days().tolist())
    assert set((left & right).good_days().tolist()) == good_left & good_right


# --- type preservation (I6) -------------------------------------------------

SAMPLES = [
    date(2026, 7, 31),
    datetime(2026, 7, 31, 9, 30),
    pd.Timestamp("2026-07-31 09:30"),
    np.datetime64("2026-07-31"),
    "2026-07-31",
    "20260731",
    20260731,
]


@pytest.mark.parametrize("value", SAMPLES)
@given(n=st.integers(min_value=-100, max_value=100))
def test_offset_preserves_type(value, n):
    assert type(WEEKDAY.offset(value, n)) is type(value)


@pytest.mark.parametrize("value", SAMPLES)
@given(roll=ADJUSTING_ROLLS)
def test_adjust_preserves_type(value, roll):
    assert type(WEEKDAY.adjust(value, roll)) is type(value)
