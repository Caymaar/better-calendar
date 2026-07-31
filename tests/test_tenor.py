"""M5: the tenor grammar (§7.3), with the end-of-month rule tested explicitly."""

from __future__ import annotations

from datetime import date

import pytest

import better_calendar as bcal
from better_calendar import Calendar, Roll
from better_calendar.core.errors import OutOfBoundsError, TenorParseError
from better_calendar.offsets.tenor import TenorTerm, parse_tenor

WEEKDAY = Calendar("weekday")


# --- grammar -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "terms"),
    [
        ("1D", [(1, "D")]),
        ("3M", [(3, "M")]),
        ("2b", [(2, "B")]),
        ("1W", [(1, "W")]),
        ("10Y", [(10, "Y")]),
        ("-1M", [(-1, "M")]),
        ("1Y+2B", [(1, "Y"), (2, "B")]),
        ("1Y-2B", [(1, "Y"), (-2, "B")]),
        ("1M+-1M", [(1, "M"), (-1, "M")]),
        ("-1Y-2M+3D", [(-1, "Y"), (-2, "M"), (3, "D")]),
        ("  6M  ", [(6, "M")]),
    ],
)
def test_grammar(text, terms):
    assert parse_tenor(text).terms == tuple(TenorTerm(n, u) for n, u in terms)


@pytest.mark.parametrize("text", ["", "   ", "M", "3", "3Q", "3M5D", "3M+", "+", "1.5M", "3 M"])
def test_parse_failures(text):
    with pytest.raises(TenorParseError):
        parse_tenor(text)


def test_parse_error_names_the_offending_substring():
    with pytest.raises(TenorParseError, match=r"at '3Q'"):
        parse_tenor("3Q")
    with pytest.raises(TenorParseError, match=r"at '5D'"):
        parse_tenor("3M5D")


def test_parsing_is_memoised():
    assert parse_tenor("3M") is parse_tenor("3M")


def test_needs_calendar():
    assert parse_tenor("2B").needs_calendar is True
    assert parse_tenor("1Y+2B").needs_calendar is True
    assert parse_tenor("3M").needs_calendar is False


def test_tenor_is_hashable_and_stringifies():
    assert str(parse_tenor("3M")) == "3M"
    assert {parse_tenor("3M"), parse_tenor("3M")} == {parse_tenor("3M")}


# --- units -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "tenor", "expected"),
    [
        ("2026-07-31", "1D", "2026-08-01"),  # calendar days ignore the weekend
        ("2026-07-31", "3D", "2026-08-03"),
        ("2026-07-31", "1W", "2026-08-07"),  # a week is seven calendar days
        ("2026-07-31", "2W", "2026-08-14"),
        ("2026-07-31", "1M", "2026-08-31"),
        ("2026-07-31", "1Y", "2027-07-31"),
        ("2026-07-31", "1B", "2026-08-03"),  # business days do skip it
        ("2026-07-31", "-1B", "2026-07-30"),
        ("2026-07-31", "0B", "2026-07-31"),
    ],
)
def test_units(start, tenor, expected):
    assert WEEKDAY.add_tenor(start, tenor) == expected


def test_business_day_terms_roll_before_moving():
    """A B term starting from a weekend rolls forward first, as `offset` does."""
    assert WEEKDAY.add_tenor("2026-08-01", "1B") == "2026-08-04"  # Sat -> Mon -> Tue


def test_business_day_terms_use_the_calendar():
    assert bcal.add_tenor("2026-07-02", "1B", cal="XNYS") == "2026-07-06"  # skips 3 July


# --- clamping, which is unconditional ----------------------------------------


@pytest.mark.parametrize(
    ("start", "tenor", "expected"),
    [
        ("2026-01-31", "1M", "2026-02-28"),  # February is short
        ("2024-01-31", "1M", "2024-02-29"),  # and shorter still in a leap year
        ("2026-03-31", "1M", "2026-04-30"),
        ("2026-08-31", "-1M", "2026-07-31"),
        ("2026-01-31", "1Y", "2027-01-31"),
        ("2024-02-29", "1Y", "2025-02-28"),  # 29 February plus a year
    ],
)
def test_month_arithmetic_clamps(start, tenor, expected):
    assert WEEKDAY.add_tenor(start, tenor) == expected


def test_clamping_is_not_reversible():
    """31 Jan +1M is 28 Feb, and 28 Feb -1M is 28 Jan. Information is lost, by design."""
    forward = WEEKDAY.add_tenor("2026-01-31", "1M")
    assert forward == "2026-02-28"
    assert WEEKDAY.add_tenor(forward, "-1M") == "2026-01-28"


# --- the end-of-month rule, which is separate and opt-in ---------------------


@pytest.mark.parametrize(
    ("start", "tenor", "plain", "with_eom"),
    [
        # The start is the last day of its month, so EOM moves the answer.
        ("2026-02-28", "1M", "2026-03-28", "2026-03-31"),
        ("2026-04-30", "1M", "2026-05-30", "2026-05-31"),
        ("2026-02-28", "1Y", "2027-02-28", "2027-02-28"),
        ("2024-02-29", "1M", "2024-03-29", "2024-03-31"),
        ("2026-11-30", "3M", "2027-02-28", "2027-02-28"),
        # The start is not month-end, so EOM changes nothing.
        ("2026-02-27", "1M", "2026-03-27", "2026-03-27"),
        ("2026-07-15", "1M", "2026-08-15", "2026-08-15"),
        # Clamping already lands on month-end; EOM agrees.
        ("2026-01-31", "1M", "2026-02-28", "2026-02-28"),
    ],
)
def test_end_of_month_rule(start, tenor, plain, with_eom):
    assert WEEKDAY.add_tenor(start, tenor) == plain
    assert WEEKDAY.add_tenor(start, tenor, eom=True) == with_eom


def test_eom_does_not_touch_day_or_business_day_terms():
    assert WEEKDAY.add_tenor("2026-02-28", "1D", eom=True) == "2026-03-01"
    assert WEEKDAY.add_tenor("2026-02-27", "1B", eom=True) == "2026-03-02"


def test_eom_applies_per_term_left_to_right():
    """ "1M+1M" is two month-end steps, not one two-month step."""
    once = WEEKDAY.add_tenor("2026-02-28", "1M", eom=True)
    assert once == "2026-03-31"
    assert WEEKDAY.add_tenor(once, "1M", eom=True) == "2026-04-30"
    assert WEEKDAY.add_tenor("2026-02-28", "1M+1M", eom=True) == "2026-04-30"
    assert WEEKDAY.add_tenor("2026-02-28", "2M", eom=True) == "2026-04-30"


# --- ordering ----------------------------------------------------------------


def test_terms_apply_left_to_right_and_the_order_matters():
    """§7.3: "1M+2B" is not "2B+1M" in general."""
    start = "2026-01-30"  # a Friday
    assert WEEKDAY.add_tenor(start, "1M+2B") == "2026-03-04"
    assert WEEKDAY.add_tenor(start, "2B+1M") == "2026-03-03"


def test_round_trip_where_unambiguous():
    """§15b: add_tenor(d, "1M+-1M") round-trips when clamping did not lose a day."""
    for start in ("2026-07-15", "2026-03-10", "2026-11-01"):
        assert WEEKDAY.add_tenor(start, "1M+-1M") == start
        assert WEEKDAY.add_tenor(start, "1Y-1Y") == start
        assert WEEKDAY.add_tenor(start, "3D-3D") == start


# --- roll, type preservation, bounds -----------------------------------------


def test_roll_is_applied_once_at_the_end():
    # 31 May 2026 is a Sunday; MF must not leave May.
    assert WEEKDAY.add_tenor("2026-04-30", "1M") == "2026-05-30"
    assert WEEKDAY.add_tenor("2026-04-30", "1M", eom=True) == "2026-05-31"
    assert WEEKDAY.add_tenor("2026-04-30", "1M", eom=True, roll=Roll.MODIFIED_FOLLOWING) == (
        "2026-05-29"
    )


def test_default_roll_is_none():
    """A tenor is a period; adjusting the result is a separate decision."""
    assert WEEKDAY.add_tenor("2026-05-29", "2D") == "2026-05-31"  # a Sunday, unadjusted


@pytest.mark.parametrize(
    "value",
    [date(2026, 1, 31), "2026-01-31", 20260131],
)
def test_type_is_preserved(value):
    assert type(WEEKDAY.add_tenor(value, "1M")) is type(value)


def test_vectorised():
    result = WEEKDAY.add_tenor(["2026-01-31", "2026-03-31"], "1M")
    assert list(result.strftime("%Y-%m-%d")) == ["2026-02-28", "2026-04-30"]


def test_out_of_bounds():
    small = Calendar("small", bounds=(date(2026, 1, 1), date(2026, 12, 31)))
    with pytest.raises(OutOfBoundsError):
        small.add_tenor("2026-12-01", "6M")
    with pytest.raises(OutOfBoundsError):
        small.add_tenor("2026-12-30", "500B")
