"""Named date generators — the recurrences that already have a name (§8).

Like :mod:`~better_calendar.schedule.recurrence`, each of these is one line over
:func:`~better_calendar.schedule.schedule.schedule`. They exist so that the handful of
recurrences with a name do not get re-derived slightly differently in every codebase that
needs them.
"""

from __future__ import annotations

from typing import Any

from better_calendar.calendars.registry import CalendarLike
from better_calendar.core.types import DateLike
from better_calendar.offsets.conventions import Roll, RollLike
from better_calendar.schedule.schedule import schedule
from better_calendar.schedule.selector import FRI, WED, Nth

__all__ = [
    "imm_dates",
    "month_ends",
    "option_expiries",
    "quarter_ends",
    "year_ends",
]

#: The months an IMM quarter ends in.
_IMM_MONTHS = (3, 6, 9, 12)


def _period_ends(
    start: DateLike, end: DateLike, every: str, cal: CalendarLike, anchor_month: int | None
) -> Any:
    """Last day of each period — calendar day without a calendar, business day with one."""
    selector = Nth(-1, "B") if cal is not None else Nth(-1)
    return schedule(start, end, every, selector, cal=cal, anchor_month=anchor_month)


def month_ends(start: DateLike, end: DateLike, *, cal: CalendarLike = None) -> Any:
    """The last day of each month in ``[start, end]``.

    ``cal`` changes the question rather than merely adjusting the answer: without one you
    get the last *calendar* day, with one the last *business* day. 31 January 2026 is a
    Saturday, so the two differ. Written out, the two calls are
    ``schedule(s, e, "M", "last")`` and ``schedule(s, e, "M", "last B", cal=...)``.

    Args:
        start: First day of the window.
        end: Last day of the window, inclusive.
        cal: A calendar or identifier for business month ends; ``None`` for calendar ones.

    Returns:
        A ``DatetimeIndex`` (or a ``datetime64[D]`` array without pandas).

    Examples:
        >>> list(month_ends("2026-01-01", "2026-03-31").strftime("%Y-%m-%d"))
        ['2026-01-31', '2026-02-28', '2026-03-31']
        >>> list(month_ends("2026-01-01", "2026-03-31", cal="XNYS").strftime("%Y-%m-%d"))
        ['2026-01-30', '2026-02-27', '2026-03-31']
    """
    return _period_ends(start, end, "M", cal, None)


def quarter_ends(
    start: DateLike, end: DateLike, *, cal: CalendarLike = None, anchor_month: int = 3
) -> Any:
    """The last day of each quarter in ``[start, end]``.

    Args:
        start: First day of the window.
        end: Last day of the window, inclusive.
        cal: A calendar or identifier for business quarter ends; ``None`` for calendar ones.
        anchor_month: The month a quarter ends in. The default 3 gives the usual
            March / June / September / December quarters; 2 gives a fiscal year ending in
            February.

    Returns:
        A ``DatetimeIndex`` (or a ``datetime64[D]`` array without pandas).

    Examples:
        >>> list(quarter_ends("2026-01-01", "2026-12-31").strftime("%Y-%m-%d"))
        ['2026-03-31', '2026-06-30', '2026-09-30', '2026-12-31']
        >>> list(quarter_ends("2026-01-01", "2026-12-31", anchor_month=2).strftime("%m-%d"))
        ['02-28', '05-31', '08-31', '11-30']
    """
    return _period_ends(start, end, "Q", cal, anchor_month)


def year_ends(
    start: DateLike, end: DateLike, *, cal: CalendarLike = None, anchor_month: int = 12
) -> Any:
    """The last day of each year in ``[start, end]``.

    Args:
        start: First day of the window.
        end: Last day of the window, inclusive.
        cal: A calendar or identifier for business year ends; ``None`` for calendar ones.
        anchor_month: The month a year ends in, for a fiscal year that is not the calendar
            one.

    Returns:
        A ``DatetimeIndex`` (or a ``datetime64[D]`` array without pandas).

    Examples:
        >>> list(year_ends("2025-01-01", "2027-06-30").strftime("%Y-%m-%d"))
        ['2025-12-31', '2026-12-31']
        >>> list(year_ends("2025-01-01", "2027-06-30", cal="XNYS").strftime("%Y-%m-%d"))
        ['2025-12-31', '2026-12-31']
    """
    return _period_ends(start, end, "Y", cal, anchor_month)


def imm_dates(start: DateLike, end: DateLike) -> Any:
    """IMM dates: the third Wednesday of March, June, September and December.

    The third Wednesday of the quarter's *last month*, not of the quarter — those are
    different dates, and the distinction is worth stating because it is easy to get wrong.
    Written out: ``schedule(s, e, "M", "3 WED", months=(3, 6, 9, 12))``.

    Args:
        start: First day of the window.
        end: Last day of the window, inclusive.

    Returns:
        A ``DatetimeIndex`` (or a ``datetime64[D]`` array without pandas).

    Examples:
        >>> list(imm_dates("2026-01-01", "2026-12-31").strftime("%Y-%m-%d"))
        ['2026-03-18', '2026-06-17', '2026-09-16', '2026-12-16']
    """
    return schedule(start, end, "M", Nth(3, WED), months=_IMM_MONTHS)


def option_expiries(
    start: DateLike,
    end: DateLike,
    *,
    cal: CalendarLike = None,
    roll: RollLike = Roll.PRECEDING,
) -> Any:
    """Monthly option expiries: the third Friday, adjusted onto a business day.

    The adjustment defaults to ``Roll.PRECEDING`` because that is what listed equity
    options do — when the third Friday is Good Friday the expiry moves *back* to the
    Thursday, not forward into the next week.

    Args:
        start: First day of the window.
        end: Last day of the window, inclusive.
        cal: The exchange calendar, or ``None`` for ``weekday``.
        roll: How to adjust an expiry that lands on a holiday.

    Returns:
        A ``DatetimeIndex`` (or a ``datetime64[D]`` array without pandas).

    Examples:
        >>> expiries = option_expiries("2026-01-01", "2026-04-30", cal="XNYS")
        >>> list(expiries.strftime("%Y-%m-%d"))
        ['2026-01-16', '2026-02-20', '2026-03-20', '2026-04-17']
        >>> # In 2022 the third Friday of April *was* Good Friday, so expiry moved back.
        >>> list(option_expiries("2022-04-01", "2022-04-30", cal="XNYS").strftime("%m-%d"))
        ['04-14']
    """
    return schedule(start, end, "M", Nth(3, FRI), cal=cal, roll=roll)
