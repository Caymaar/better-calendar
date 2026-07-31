"""The canonical internal representation: ``int64`` days since 1970-01-01 (§3).

Everything the library computes — membership, offsets, counting, set algebra —
reduces to ``searchsorted`` and numpy set operations on sorted ``int64`` arrays of
*good days*. Conversions between that representation and ``numpy.datetime64[D]``
are ``view`` casts, not copies: both dtypes are 8 bytes wide and share a layout.

:data:`MAX_YEAR` is the single knob controlling the horizon. Nothing else in the
codebase may hardcode a terminal year.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Final

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "DAY_ORIGIN",
    "DEFAULT_BOUNDS",
    "MAX_DAY",
    "MAX_YEAR",
    "MIN_DAY",
    "MIN_YEAR",
    "add_months",
    "date_to_days",
    "datetime64_to_days",
    "days_to_date",
    "days_to_datetime64",
    "weekday_of",
]

#: Day 0 of the internal representation.
DAY_ORIGIN: Final[date] = date(1970, 1, 1)

MIN_YEAR: Final[int] = 1970
MAX_YEAR: Final[int] = 2100  # single knob; easy to raise later

#: Default finite horizon for every calendar (I2 — never extrapolate).
DEFAULT_BOUNDS: Final[tuple[date, date]] = (date(MIN_YEAR, 1, 1), date(MAX_YEAR, 12, 31))

#: 1970-01-01 is a **Thursday**, so ``(days + WEEKDAY_SHIFT) % 7`` gives ``date.weekday()``
#: (Monday = 0). Written as a named constant because the off-by-three is easy to get wrong.
WEEKDAY_SHIFT: Final[int] = 3

#: The internal day numbers of :data:`DEFAULT_BOUNDS`.
MIN_DAY: Final[int] = (DEFAULT_BOUNDS[0] - DAY_ORIGIN).days
MAX_DAY: Final[int] = (DEFAULT_BOUNDS[1] - DAY_ORIGIN).days


def date_to_days(value: date) -> int:
    """Convert a :class:`datetime.date` to days since the epoch.

    Args:
        value: Any ``date`` (a ``datetime`` is accepted; its time part is dropped).

    Returns:
        Whole days since 1970-01-01, negative before it.

    Examples:
        >>> date_to_days(date(1970, 1, 1))
        0
        >>> date_to_days(date(2026, 7, 31))
        20665
    """
    if not isinstance(value, date):  # defensive: callers should have converted already
        raise TypeError(f"expected datetime.date, got {type(value).__name__}")
    return (date(value.year, value.month, value.day) - DAY_ORIGIN).days


def days_to_date(days: int) -> date:
    """Convert days since the epoch back to a :class:`datetime.date`.

    Args:
        days: Whole days since 1970-01-01.

    Returns:
        The corresponding civil date.

    Examples:
        >>> days_to_date(20665)
        datetime.date(2026, 7, 31)
    """
    return DAY_ORIGIN + timedelta(days=int(days))


def days_to_datetime64(days: NDArray[np.int64]) -> NDArray[np.datetime64]:
    """View an ``int64`` day array as ``datetime64[D]`` without copying.

    Args:
        days: Contiguous ``int64`` array of days since the epoch.

    Returns:
        The same buffer reinterpreted as ``datetime64[D]``.

    Examples:
        >>> days_to_datetime64(np.array([0, 20665], dtype=np.int64))
        array(['1970-01-01', '2026-07-31'], dtype='datetime64[D]')
    """
    return np.ascontiguousarray(days, dtype=np.int64).view("datetime64[D]")


def datetime64_to_days(values: NDArray[np.datetime64]) -> NDArray[np.int64]:
    """View a ``datetime64[D]`` array as ``int64`` days without copying.

    Args:
        values: Array of any ``datetime64`` unit; finer units are truncated to days
            (which *does* copy, since truncation is a real conversion).

    Returns:
        ``int64`` days since the epoch.

    Examples:
        >>> datetime64_to_days(np.array(["2026-07-31"], dtype="datetime64[D]"))
        array([20665])
    """
    as_days = np.asarray(values, dtype="datetime64[D]")
    return np.ascontiguousarray(as_days).view(np.int64)


def weekday_of(days: NDArray[np.int64]) -> NDArray[np.int64]:
    """Return ``date.weekday()`` (Monday = 0) for an array of epoch days.

    Args:
        days: ``int64`` days since the epoch.

    Returns:
        Weekday indices in ``0..6``, matching :meth:`datetime.date.weekday`.

    Examples:
        >>> weekday_of(np.array([0], dtype=np.int64))  # 1970-01-01 was a Thursday
        array([3])
    """
    return np.asarray((days + WEEKDAY_SHIFT) % 7, dtype=np.int64)


def add_months(
    days: NDArray[np.int64],
    months: int,
    *,
    end_of_month: bool = False,
) -> NDArray[np.int64]:
    """Add whole months to epoch days, vectorised, with the two month-end rules (§7.3).

    **Clamping** is unconditional: 31 January plus one month is 28 or 29 February, because
    the 31st of February does not exist. **The end-of-month rule** is separate and opt-in:
    when ``end_of_month`` is set and the input is the last day of its month, the result is
    the last day of *its* month, so 28 February 2026 plus one month becomes 31 March
    rather than 28 March. Keeping the two apart is the whole point — conflating them is
    where the off-by-one-day bugs live.

    Args:
        days: ``int64`` epoch days.
        months: Whole months to add; may be negative.
        end_of_month: Apply the end-of-month rule on top of clamping.

    Returns:
        The shifted epoch days.

    Examples:
        >>> jan31 = np.array([date_to_days(date(2026, 1, 31))], dtype=np.int64)
        >>> days_to_date(int(add_months(jan31, 1)[0]))            # clamped
        datetime.date(2026, 2, 28)
        >>> feb28 = np.array([date_to_days(date(2026, 2, 28))], dtype=np.int64)
        >>> days_to_date(int(add_months(feb28, 1)[0]))            # no EOM rule
        datetime.date(2026, 3, 28)
        >>> days_to_date(int(add_months(feb28, 1, end_of_month=True)[0]))
        datetime.date(2026, 3, 31)
    """
    as_days = days_to_datetime64(np.ascontiguousarray(days, dtype=np.int64))
    source_month = as_days.astype("datetime64[M]")
    source_first = source_month.astype("datetime64[D]")
    day_index = (as_days - source_first).astype(np.int64)
    source_length = ((source_month + 1).astype("datetime64[D]") - source_first).astype(np.int64)

    target_month = source_month + months
    target_first = target_month.astype("datetime64[D]")
    target_length = ((target_month + 1).astype("datetime64[D]") - target_first).astype(np.int64)

    clamped = np.minimum(day_index, target_length - 1)
    if end_of_month:
        clamped = np.where(day_index == source_length - 1, target_length - 1, clamped)
    shifted = target_first + clamped.astype("timedelta64[D]")
    return datetime64_to_days(np.ascontiguousarray(shifted))
