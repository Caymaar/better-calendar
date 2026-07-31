"""Recurrence rules: the nth weekday, day or business day of each period (§8).

This module answers the question that motivated the library::

    last_weekday("2026-01-01", "2026-12-31", FRI)              # last Friday of each month
    nth_weekday("2026-01-01", "2026-12-31", 2, THU, freq="Q")  # 2nd Thursday of each quarter

Three conventions, all deliberate:

* **``n`` is 1-based, and negative counts from the end.** ``n=1`` is the first, ``n=-1``
  the last, ``n=-2`` the second to last. Making ``-1`` mean "last" is the entire point —
  "the last Friday of the month" is the thing people actually ask for, and computing it by
  hand is where the bugs are.
* **A missing occurrence is skipped, silently.** February has no fifth Friday most years.
  Raising would make ``nth_weekday(..., 5, FRI)`` unusable over any real span, so the
  result simply has fewer entries than there were periods. This is documented rather than
  clever, and it is tested.
* **The occurrence is found inside the whole period, then filtered to the window.** "The
  last Friday of January" is a property of January, not of the query. Asking from the 15th
  still returns the 30th; asking from February does not return January's at all.
"""

from __future__ import annotations

from datetime import date
from enum import IntEnum
from typing import Any

import numpy as np
from numpy.typing import NDArray

from better_calendar.calendars.registry import CalendarLike, resolve
from better_calendar.core._freq import parse_freq
from better_calendar.core.epoch import date_to_days, weekday_of
from better_calendar.core.errors import BetterCalendarError
from better_calendar.core.types import DateLike, days_to_index, to_date
from better_calendar.offsets.conventions import Roll, RollLike

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
    "month_of",
    "nth_business_day",
    "nth_day",
    "nth_weekday",
    "periods",
    "weekday_within",
]

#: Months in one period of each unit; ``D`` and ``W`` are handled in days instead.
_MONTHS_PER_UNIT = {"M": 1, "Q": 3, "Y": 12}
_DAYS_PER_UNIT = {"D": 1, "W": 7}

#: ``datetime64[M]`` counts months from 1970-01, our month index counts from year 0.
_EPOCH_MONTH_INDEX = 1970 * 12


class Weekday(IntEnum):
    """Weekday constants matching :meth:`datetime.date.weekday` — Monday is 0.

    Examples:
        >>> Weekday.MON, Weekday.SUN
        (<Weekday.MON: 0>, <Weekday.SUN: 6>)
        >>> int(FRI)
        4
    """

    MON = 0
    TUE = 1
    WED = 2
    THU = 3
    FRI = 4
    SAT = 5
    SUN = 6


MON, TUE, WED, THU, FRI, SAT, SUN = Weekday


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------


def _month_periods(
    first: date, last: date, months: int, anchor_month: int | None
) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    """Whole-month periods covering ``[first, last]``.

    ``anchor_month`` pins the alignment to the calendar: quarters "ending in March" start
    in January whatever the query window is. Without it — which is the case for a
    multiple like ``"3M"`` — periods are anchored on the month ``first`` falls in, since
    "every three months" can only mean "from where I started".
    """
    first_index = first.year * 12 + first.month - 1
    last_index = last.year * 12 + last.month - 1
    offset = (anchor_month % months) if anchor_month is not None else (first_index % months)

    lowest = (first_index - offset) // months
    highest = (last_index - offset) // months
    steps = np.arange(lowest, highest + 1, dtype=np.int64)

    starts_index = offset + steps * months - _EPOCH_MONTH_INDEX
    starts_month = starts_index.astype("datetime64[M]")
    ends_month = (starts_index + months).astype("datetime64[M]")
    starts = np.ascontiguousarray(starts_month.astype("datetime64[D]")).view(np.int64)
    ends = np.ascontiguousarray(ends_month.astype("datetime64[D]")).view(np.int64) - 1
    return starts, ends


def _day_periods(
    first: date, last: date, days: int, *, align_to_monday: bool
) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    """Fixed-length day periods covering ``[first, last]``."""
    start_day = date_to_days(first)
    if align_to_monday:
        start_day -= int(weekday_of(np.array([start_day], dtype=np.int64))[0])
    starts = np.arange(start_day, date_to_days(last) + 1, days, dtype=np.int64)
    return starts, starts + days - 1


def periods(
    first: date, last: date, freq: str, *, anchor_month: int | None = None
) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    """The periods of length ``freq`` covering ``[first, last]``, as epoch days.

    Args:
        first: Start of the window.
        last: End of the window, inclusive.
        freq: ``"D"``, ``"W"``, ``"M"``, ``"Q"``, ``"Y"``, or a multiple such as ``"3M"``.
        anchor_month: For month-based frequencies, the month a period ends in, which pins
            the alignment to the calendar. ``None`` anchors on ``first`` instead.

    Returns:
        Two ``int64`` arrays: the first and last day of each period.

    Examples:
        >>> starts, ends = periods(date(2026, 1, 15), date(2026, 3, 5), "M")
        >>> len(starts)                      # January, February and March
        3
    """
    parsed = parse_freq(freq)
    if parsed.unit in _MONTHS_PER_UNIT:
        months = parsed.multiple * _MONTHS_PER_UNIT[parsed.unit]
        # A bare Q or Y means the calendar quarter or year; a multiple means "every n
        # months from here", so it has no calendar alignment to inherit.
        implied = anchor_month
        if implied is None and parsed.multiple == 1 and parsed.unit in ("Q", "Y"):
            implied = 3 if parsed.unit == "Q" else 12
        return _month_periods(first, last, months, implied)
    days = parsed.multiple * _DAYS_PER_UNIT[parsed.unit]
    return _day_periods(
        first, last, days, align_to_monday=parsed.unit == "W" and parsed.multiple == 1
    )


# ---------------------------------------------------------------------------
# Recurrences
# ---------------------------------------------------------------------------


def _window(start: DateLike, end: DateLike) -> tuple[date, date]:
    first, last = to_date(start), to_date(end)
    if last < first:
        raise BetterCalendarError(
            f"The window ends {last.isoformat()} before it starts {first.isoformat()}. "
            f"Pass the earlier date first."
        )
    return first, last


def _finish(
    days: NDArray[np.int64],
    valid: NDArray[np.bool_],
    window: tuple[date, date],
    cal: CalendarLike,
    roll: RollLike,
) -> Any:
    """Drop missing occurrences, adjust, clip to the window, and present as an index."""
    found = np.asarray(days[valid], dtype=np.int64)
    parsed = Roll.parse(roll)
    if parsed is not Roll.NONE and found.size:
        calendar = resolve(cal)
        found = np.atleast_1d(np.asarray(calendar._adjust_days(found, parsed), dtype=np.int64))
    low, high = date_to_days(window[0]), date_to_days(window[1])
    return days_to_index(np.sort(found[(found >= low) & (found <= high)]))


def weekday_within(
    starts: NDArray[np.int64], ends: NDArray[np.int64], n: int, weekday: int
) -> NDArray[np.int64]:
    """The ``n``-th ``weekday`` inside each period, as epoch days.

    The result may fall outside its period when the occurrence does not exist; callers
    filter on ``starts <= found <= ends``, which is what makes a missing fifth Friday a
    skipped row rather than an error.

    Args:
        starts: First day of each period.
        ends: Last day of each period.
        n: 1-based occurrence; negative counts from the end of the period.
        weekday: A ``date.weekday()`` index.

    Returns:
        One candidate day per period.

    Examples:
        >>> starts, ends = periods(date(2026, 1, 1), date(2026, 1, 31), "M")
        >>> int(weekday_within(starts, ends, -1, FRI)[0])       # 30 January 2026
        20483
    """
    target = int(weekday) % 7
    if n > 0:
        # First occurrence on or after the period start, then step forward.
        return np.asarray(
            starts + (target - weekday_of(starts)) % 7 + 7 * (n - 1), dtype=np.int64
        )
    if n < 0:
        # Last occurrence on or before the period end, then step back.
        return np.asarray(ends - (weekday_of(ends) - target) % 7 + 7 * (n + 1), dtype=np.int64)
    raise BetterCalendarError(
        "n is 1-based, so 0 selects nothing. Use 1 for the first occurrence and -1 for "
        "the last."
    )


def month_of(days: NDArray[np.int64]) -> NDArray[np.int64]:
    """The calendar month (1-12) of each epoch day.

    Args:
        days: ``int64`` epoch days.

    Returns:
        Month numbers.

    Examples:
        >>> month_of(np.array([20665], dtype=np.int64)).tolist()   # 2026-07-31
        [7]
    """
    months = np.ascontiguousarray(
        np.ascontiguousarray(days, dtype=np.int64).view("datetime64[D]").astype("datetime64[M]")
    ).view(np.int64)
    return np.asarray(months % 12 + 1, dtype=np.int64)


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

    Args:
        start: First day of the window.
        end: Last day of the window, inclusive.
        n: 1-based occurrence; negative counts from the end of the period, so ``-1`` is
            the last one.
        weekday: A :class:`Weekday`, or any ``date.weekday()`` index.
        freq: Period length — ``"D"``, ``"W"``, ``"M"``, ``"Q"``, ``"Y"``, or a multiple.
        cal: Calendar used by ``roll``; ignored when ``roll`` is ``Roll.NONE``.
        roll: How to adjust each result onto a business day. ``Roll.NONE`` by default,
            because a recurrence rule is a calendar fact before it is a trading date.
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
    window = _window(start, end)
    starts, ends = periods(*window, freq, anchor_month=anchor_month)
    found = weekday_within(starts, ends, n, weekday)
    return _finish(found, (found >= starts) & (found <= ends), window, cal, roll)


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
        weekday: A :class:`Weekday`, or any ``date.weekday()`` index.
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
) -> Any:
    """The ``n``-th calendar day of each period in ``[start, end]``.

    Args:
        start: First day of the window.
        end: Last day of the window, inclusive.
        n: 1-based; negative counts from the end, so ``-1`` is the period's last day.
        freq: Period length.
        cal: Calendar used by ``roll``.
        roll: How to adjust each result onto a business day.
        anchor_month: For month-based frequencies, the month a period ends in.

    Returns:
        A ``DatetimeIndex`` (or a ``datetime64[D]`` array without pandas). Periods too
        short to have an ``n``-th day are skipped.

    Examples:
        >>> list(nth_day("2026-01-01", "2026-03-31", 1).strftime("%Y-%m-%d"))
        ['2026-01-01', '2026-02-01', '2026-03-01']
        >>> list(nth_day("2026-01-01", "2026-03-31", -1).strftime("%Y-%m-%d"))
        ['2026-01-31', '2026-02-28', '2026-03-31']
        >>> len(nth_day("2026-01-01", "2026-12-31", 30))     # February is too short
        11
    """
    window = _window(start, end)
    starts, ends = periods(*window, freq, anchor_month=anchor_month)
    if n > 0:
        found = starts + (n - 1)
    elif n < 0:
        found = ends + (n + 1)
    else:
        raise BetterCalendarError(
            "n is 1-based, so 0 selects nothing. Use 1 for the first day of the period "
            "and -1 for the last."
        )
    return _finish(found, (found >= starts) & (found <= ends), window, cal, roll)


def nth_business_day(
    start: DateLike,
    end: DateLike,
    n: int,
    *,
    freq: str = "M",
    cal: CalendarLike = None,
    anchor_month: int | None = None,
) -> Any:
    """The ``n``-th business day of each period in ``[start, end]``.

    There is no ``roll``: the result is a business day by construction.

    Args:
        start: First day of the window.
        end: Last day of the window, inclusive.
        n: 1-based; negative counts from the end, so ``-1`` is the period's last business
            day.
        freq: Period length.
        cal: The calendar, an identifier, or ``None`` for ``weekday``.
        anchor_month: For month-based frequencies, the month a period ends in.

    Returns:
        A ``DatetimeIndex`` (or a ``datetime64[D]`` array without pandas). Periods with
        fewer than ``n`` business days are skipped.

    Examples:
        >>> dates = nth_business_day("2026-01-01", "2026-03-31", 1, cal="XNYS")
        >>> list(dates.strftime("%Y-%m-%d"))       # 1 January is a holiday
        ['2026-01-02', '2026-02-02', '2026-03-02']
        >>> list(nth_business_day("2026-01-01", "2026-02-28", -1).strftime("%Y-%m-%d"))
        ['2026-01-30', '2026-02-27']
    """
    window = _window(start, end)
    calendar = resolve(cal)
    starts, ends = periods(*window, freq, anchor_month=anchor_month)
    good = calendar.good_days()

    low = np.searchsorted(good, starts, side="left")
    high = np.searchsorted(good, ends, side="right")
    if n > 0:
        index = low + (n - 1)
    elif n < 0:
        index = high + n
    else:
        raise BetterCalendarError(
            "n is 1-based, so 0 selects nothing. Use 1 for the first business day of the "
            "period and -1 for the last."
        )
    valid = (index >= low) & (index < high)
    found = np.where(valid, good[np.clip(index, 0, max(good.size - 1, 0))], 0)
    return _finish(found, valid, window, cal, Roll.NONE)
