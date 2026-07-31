"""M1: DateRange (§8.2)."""

from __future__ import annotations

from datetime import date

import pytest

from better_calendar import DateRange
from better_calendar.core.errors import BetterCalendarError


def test_half_open_by_default():
    """I10: [start, end) unless asked otherwise."""
    period = DateRange("2026-07-27", "2026-08-01")
    assert len(period) == 5
    assert date(2026, 7, 27) in period
    assert date(2026, 8, 1) not in period


@pytest.mark.parametrize(
    ("closed", "expected"),
    [("left", 5), ("right", 5), ("both", 6), ("neither", 4)],
)
def test_conventions(closed, expected):
    assert len(DateRange("2026-07-27", "2026-08-01", closed)) == expected


def test_iteration():
    assert list(DateRange("2026-07-27", "2026-07-29")) == [
        date(2026, 7, 27),
        date(2026, 7, 28),
    ]


def test_empty_range():
    period = DateRange("2026-07-27", "2026-07-27")
    assert period.is_empty()
    assert len(period) == 0
    assert list(period) == []


def test_inverted_range_is_rejected():
    with pytest.raises(BetterCalendarError, match="is before start"):
        DateRange("2026-08-01", "2026-07-01")


def test_bad_convention_is_rejected():
    with pytest.raises(BetterCalendarError, match="Unknown interval convention"):
        DateRange("2026-07-01", "2026-08-01", "sideways")


def test_membership_of_a_non_date_is_false():
    assert "not a date" not in DateRange("2026-07-01", "2026-08-01")


def test_overlaps_and_intersection():
    a = DateRange("2026-01-01", "2026-02-01")
    b = DateRange("2026-01-15", "2026-03-01")
    c = DateRange("2026-06-01", "2026-07-01")
    assert a.overlaps(b)
    assert not a.overlaps(c)
    assert a.intersection(b) == DateRange("2026-01-15", "2026-01-31", "both")
    assert a.intersection(c).is_empty()


def test_business_days():
    assert len(DateRange("2026-07-27", "2026-08-03").business_days()) == 5
    assert len(DateRange("2026-07-27", "2026-08-03").business_days("crypto:24x7")) == 7


def test_split_tiles_without_gaps_or_overlap():
    period = DateRange("2026-01-01", "2026-04-01")
    pieces = period.split("M")
    assert [p.start for p in pieces] == [
        date(2026, 1, 1),
        date(2026, 2, 1),
        date(2026, 3, 1),
    ]
    assert sum(len(p) for p in pieces) == len(period)


def test_split_truncates_the_last_piece():
    pieces = DateRange("2026-01-01", "2026-03-15").split("M")
    assert pieces[-1].start == date(2026, 3, 1)
    assert pieces[-1].end == date(2026, 3, 15)


def test_split_respects_the_outer_convention():
    period = DateRange("2026-01-01", "2026-04-01", "both")
    pieces = period.split("M")
    assert pieces[-1].closed == "both"
    assert sum(len(p) for p in pieces) == len(period)


def test_bad_frequency():
    with pytest.raises(BetterCalendarError, match="Cannot parse frequency"):
        DateRange("2026-01-01", "2026-04-01").split("3X")


def test_range_is_hashable_and_frozen():
    period = DateRange("2026-01-01", "2026-02-01")
    assert {period, DateRange("2026-01-01", "2026-02-01")} == {period}
    with pytest.raises(Exception, match=r"frozen|cannot assign"):
        period.closed = "both"  # type: ignore[misc]  # the point of the test
