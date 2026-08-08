"""How the window is cut into periods — the ``every`` argument of :func:`schedule` (§8).

Two alignments, and the choice between them is carried by the frequency string itself
rather than by a separate parameter:

* a **bare unit** aligns to the calendar. ``"M"`` is calendar months, ``"Q"`` calendar
  quarters, ``"Y"`` calendar years — the same periods whatever window you ask about.
* a **multiple** aligns to the window's start. ``"3M"`` means "every three months from
  here", which is the only thing it can mean.

So ``"Q"`` and ``"3M"`` are both three months long and are deliberately different: the
first is a property of the calendar, the second of your start date.
"""

from __future__ import annotations

from datetime import date

import numpy as np
from numpy.typing import NDArray

from better_calendar.core._freq import parse_freq
from better_calendar.core.epoch import date_to_days, weekday_of

__all__ = ["month_of", "period_bounds"]

#: Months in one period of each unit; ``D`` and ``W`` are counted in days instead.
_MONTHS_PER_UNIT = {"M": 1, "Q": 3, "Y": 12}
_DAYS_PER_UNIT = {"D": 1, "W": 7}

#: The calendar month a bare ``Q`` or ``Y`` period ends in, absent an explicit anchor.
_NATURAL_ANCHOR = {"Q": 3, "Y": 12}

#: ``datetime64[M]`` counts months from 1970-01; our month index counts from year 0.
_EPOCH_MONTH_INDEX = 1970 * 12


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


def _month_periods(
    first: date, last: date, months: int, anchor_month: int | None
) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    """Whole-month periods covering ``[first, last]``."""
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


def period_bounds(
    first: date, last: date, every: str, *, anchor_month: int | None = None
) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    """The periods of length ``every`` covering ``[first, last]``, as epoch days.

    Args:
        first: Start of the window.
        last: End of the window, inclusive.
        every: ``"D"``, ``"W"``, ``"M"``, ``"Q"``, ``"Y"``, or a multiple such as ``"3M"``.
        anchor_month: For month-based frequencies, the calendar month a period ends in.
            Pins ``"Q"`` and ``"Y"`` to a fiscal year; ignored by ``"D"`` and ``"W"``.

    Returns:
        Two ``int64`` arrays: the first and last day of each period.

    Examples:
        >>> starts, ends = period_bounds(date(2026, 1, 15), date(2026, 3, 5), "M")
        >>> len(starts)                      # January, February and March
        3
        >>> starts, _ = period_bounds(date(2026, 1, 1), date(2026, 12, 31), "Q")
        >>> month_of(starts).tolist()        # calendar quarters start in Jan/Apr/Jul/Oct
        [1, 4, 7, 10]
    """
    parsed = parse_freq(every)
    if parsed.unit in _MONTHS_PER_UNIT:
        months = parsed.multiple * _MONTHS_PER_UNIT[parsed.unit]
        implied = anchor_month
        if implied is None and parsed.multiple == 1:
            implied = _NATURAL_ANCHOR.get(parsed.unit)
        return _month_periods(first, last, months, implied)
    days = parsed.multiple * _DAYS_PER_UNIT[parsed.unit]
    return _day_periods(
        first, last, days, align_to_monday=parsed.unit == "W" and parsed.multiple == 1
    )
