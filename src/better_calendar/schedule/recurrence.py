"""Named spellings of the common recurrences (§8).

Each of these is one line over :func:`~better_calendar.schedule.schedule.schedule`. They
exist because ``last_weekday(start, end, FRI)`` says what it means to a reader who has
never seen the selector grammar, and because these are the shapes people actually ask for:

    last_weekday("2026-01-01", "2026-12-31", FRI)              # last Friday of each month
    nth_weekday("2026-01-01", "2026-12-31", 2, THU, freq="Q")  # 2nd Thursday of each quarter

Three conventions run through all of them, and through the engine underneath:

* **``n`` is 1-based, and negative counts from the end.** ``n=-1`` is the last, ``-2`` the
  second to last. Making ``-1`` mean "last" is the entire point — it is the thing people
  actually ask for, and computing it by hand is where the bugs are.
* **A missing occurrence is skipped, silently.** February has no fifth Friday. Raising
  would make ``nth_weekday(..., 5, FRI)`` unusable over any real span, so the result has
  fewer entries than there were periods. Pass ``missing="clamp"`` when you want the
  nearest occurrence that does exist instead.
* **The occurrence is found inside the whole period, then filtered to the window.** "The
  last Friday of January" is a property of January, not of the query: asking from the 15th
  still returns the 30th; asking from February does not return January's at all.
"""

from __future__ import annotations

from typing import Any

from better_calendar.calendars.registry import CalendarLike
from better_calendar.core.types import DateLike
from better_calendar.offsets.conventions import Roll, RollLike
from better_calendar.schedule.schedule import schedule
from better_calendar.schedule.selector import (
    FRI,
    MON,
    SAT,
    SUN,
    THU,
    TUE,
    WED,
    Nth,
    Weekday,
)

__all__ = [
    "FRI",
    "MON",
    "SAT",
    "SUN",
    "THU",
    "TUE",
    "WED",
    "Weekday",
    "last_weekday",
    "nth_business_day",
    "nth_day",
    "nth_weekday",
]


def nth_weekday(
    start: DateLike,
    end: DateLike,
    n: int,
    weekday: int,
    *,
    freq: str = "M",
    cal: CalendarLike = None,
    roll: RollLike = Roll.NONE,
    anchor_month: int | None = None,
) -> Any:
    """The ``n``-th given weekday of each period in ``[start, end]``.

    The same thing as ``schedule(start, end, freq, Nth(n, weekday))``.

    Args:
        start: First day of the window.
        end: Last day of the window, inclusive.
        n: 1-based occurrence; negative counts from the end of the period.
        weekday: A :class:`~better_calendar.schedule.selector.Weekday`, or any
            ``date.weekday()`` index.
        freq: Period length — ``"D"``, ``"W"``, ``"M"``, ``"Q"``, ``"Y"``, or a multiple.
        cal: Calendar used by ``roll``; ignored when ``roll`` is ``Roll.NONE``.
        roll: How to adjust each result onto a business day.
        anchor_month: For month-based frequencies, the month a period ends in.

    Returns:
        A ``DatetimeIndex`` (or a ``datetime64[D]`` array without pandas). Periods with no
        such occurrence are skipped rather than raising.

    Examples:
        >>> dates = nth_weekday("2026-01-01", "2026-12-31", 2, THU, freq="Q")
        >>> list(dates.strftime("%Y-%m-%d"))
        ['2026-01-08', '2026-04-09', '2026-07-09', '2026-10-08']
        >>> len(nth_weekday("2026-01-01", "2026-12-31", 5, FRI))   # not every month has one
        4
    """
    return schedule(
        start,
        end,
        freq,
        Nth(n, Weekday(int(weekday) % 7)),
        cal=cal,
        roll=roll,
        anchor_month=anchor_month,
    )


def last_weekday(
    start: DateLike,
    end: DateLike,
    weekday: int,
    *,
    freq: str = "M",
    cal: CalendarLike = None,
    roll: RollLike = Roll.NONE,
    anchor_month: int | None = None,
) -> Any:
    """The last given weekday of each period. Exactly ``nth_weekday`` with ``n=-1``.

    Args:
        start: First day of the window.
        end: Last day of the window, inclusive.
        weekday: A :class:`~better_calendar.schedule.selector.Weekday`, or any
            ``date.weekday()`` index.
        freq: Period length.
        cal: Calendar used by ``roll``.
        roll: How to adjust each result onto a business day.
        anchor_month: For month-based frequencies, the month a period ends in.

    Returns:
        A ``DatetimeIndex`` (or a ``datetime64[D]`` array without pandas).

    Examples:
        >>> dates = last_weekday("2026-01-01", "2026-12-31", FRI)
        >>> list(dates.strftime("%Y-%m-%d"))[:3]
        ['2026-01-30', '2026-02-27', '2026-03-27']
        >>> len(dates)
        12
    """
    return nth_weekday(
        start, end, -1, weekday, freq=freq, cal=cal, roll=roll, anchor_month=anchor_month
    )


def nth_day(
    start: DateLike,
    end: DateLike,
    n: int,
    *,
    freq: str = "M",
    cal: CalendarLike = None,
    roll: RollLike = Roll.NONE,
    anchor_month: int | None = None,
    missing: str = "skip",
) -> Any:
    """The ``n``-th calendar day of each period in ``[start, end]``.

    The same thing as ``schedule(start, end, freq, str(n))``.

    Args:
        start: First day of the window.
        end: Last day of the window, inclusive.
        n: 1-based; negative counts from the end, so ``-1`` is the period's last day.
        freq: Period length.
        cal: Calendar used by ``roll``.
        roll: How to adjust each result onto a business day.
        anchor_month: For month-based frequencies, the month a period ends in.
        missing: What to do about periods too short to have an ``n``-th day.

    Returns:
        A ``DatetimeIndex`` (or a ``datetime64[D]`` array without pandas).

    Examples:
        >>> list(nth_day("2026-01-01", "2026-03-31", 1).strftime("%Y-%m-%d"))
        ['2026-01-01', '2026-02-01', '2026-03-01']
        >>> list(nth_day("2026-01-01", "2026-03-31", -1).strftime("%Y-%m-%d"))
        ['2026-01-31', '2026-02-28', '2026-03-31']
        >>> len(nth_day("2026-01-01", "2026-12-31", 30))     # February is too short
        11
        >>> len(nth_day("2026-01-01", "2026-12-31", 30, missing="clamp"))
        12
    """
    return schedule(
        start,
        end,
        freq,
        Nth(n),
        cal=cal,
        roll=roll,
        anchor_month=anchor_month,
        missing=missing,
    )


def nth_business_day(
    start: DateLike,
    end: DateLike,
    n: int,
    *,
    freq: str = "M",
    cal: CalendarLike = None,
    anchor_month: int | None = None,
    missing: str = "skip",
) -> Any:
    """The ``n``-th business day of each period in ``[start, end]``.

    The same thing as ``schedule(start, end, freq, Nth(n, "B"), cal=cal)``. There is no
    ``roll``: the result is a business day by construction.

    Args:
        start: First day of the window.
        end: Last day of the window, inclusive.
        n: 1-based; negative counts from the end.
        freq: Period length.
        cal: The calendar, an identifier, or ``None`` for ``weekday``.
        anchor_month: For month-based frequencies, the month a period ends in.
        missing: What to do about periods with fewer than ``n`` business days.

    Returns:
        A ``DatetimeIndex`` (or a ``datetime64[D]`` array without pandas).

    Examples:
        >>> dates = nth_business_day("2026-01-01", "2026-03-31", 1, cal="XNYS")
        >>> list(dates.strftime("%Y-%m-%d"))       # 1 January is a holiday
        ['2026-01-02', '2026-02-02', '2026-03-02']
        >>> list(nth_business_day("2026-01-01", "2026-02-28", -1).strftime("%Y-%m-%d"))
        ['2026-01-30', '2026-02-27']
    """
    return schedule(
        start,
        end,
        freq,
        Nth(n, "B"),
        cal=cal,
        anchor_month=anchor_month,
        missing=missing,
    )
