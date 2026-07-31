"""Calendar-free function facade (§13).

Every function here mirrors a :class:`~better_calendar.calendars.base.Calendar` method,
taking the calendar as a keyword argument that accepts a ``Calendar``, an identifier
resolved through the registry, or ``None`` for the default ``weekday`` calendar.

They exist because most call sites want one line, not a calendar variable::

    bcal.adjust("2026-08-01", "MF", cal="XNYS")
"""

from __future__ import annotations

from typing import Any

from better_calendar.calendars.registry import CalendarLike, resolve
from better_calendar.offsets.conventions import Roll, RollLike
from better_calendar.offsets.spot import spot

__all__ = [
    "add_tenor",
    "adjust",
    "count",
    "is_bday",
    "next_bday",
    "offset",
    "prev_bday",
    "sessions",
    "spot",
]


def is_bday(value: Any, *, cal: CalendarLike = None, tz: str | None = None) -> Any:
    """Whether each date is a business day.

    Args:
        value: A date-like scalar or sequence.
        cal: A calendar, an identifier, or ``None`` for ``weekday``.
        tz: Timezone used to project aware inputs.

    Returns:
        ``bool`` for a scalar, a ``bool`` array for a sequence.

    Examples:
        >>> is_bday("2026-08-01")
        False
        >>> is_bday("2026-08-01", cal="crypto:24x7")
        True
    """
    return resolve(cal).is_bday(value, tz=tz)


def next_bday(
    value: Any, *, cal: CalendarLike = None, inclusive: bool = False, tz: str | None = None
) -> Any:
    """The next business day on or after ``value``.

    Args:
        value: A date-like scalar or sequence.
        cal: A calendar, an identifier, or ``None`` for ``weekday``.
        inclusive: If ``True``, a business day is returned unchanged.
        tz: Timezone used to project aware inputs.

    Returns:
        The same type as ``value``.

    Examples:
        >>> next_bday("2026-08-01")
        '2026-08-03'
    """
    return resolve(cal).next_bday(value, inclusive=inclusive, tz=tz)


def prev_bday(
    value: Any, *, cal: CalendarLike = None, inclusive: bool = False, tz: str | None = None
) -> Any:
    """The previous business day on or before ``value``.

    Args:
        value: A date-like scalar or sequence.
        cal: A calendar, an identifier, or ``None`` for ``weekday``.
        inclusive: If ``True``, a business day is returned unchanged.
        tz: Timezone used to project aware inputs.

    Returns:
        The same type as ``value``.

    Examples:
        >>> prev_bday("2026-08-01")
        '2026-07-31'
    """
    return resolve(cal).prev_bday(value, inclusive=inclusive, tz=tz)


def adjust(
    value: Any,
    roll: RollLike = Roll.FOLLOWING,
    *,
    cal: CalendarLike = None,
    tz: str | None = None,
) -> Any:
    """Move a date to a nearby business day per an ISDA roll convention.

    Args:
        value: A date-like scalar or sequence.
        roll: A :class:`~better_calendar.offsets.conventions.Roll`, full name, or short
            alias such as ``"MF"``.
        cal: A calendar, an identifier, or ``None`` for ``weekday``.
        tz: Timezone used to project aware inputs.

    Returns:
        The same type as ``value``.

    Examples:
        >>> adjust("2026-05-31", "MF")   # Sunday; rolling forward would leave May
        '2026-05-29'
    """
    return resolve(cal).adjust(value, roll, tz=tz)


def offset(
    value: Any,
    n: int,
    *,
    cal: CalendarLike = None,
    roll: RollLike = Roll.FOLLOWING,
    tz: str | None = None,
) -> Any:
    """Move ``n`` business days from ``value``.

    Args:
        value: A date-like scalar or sequence.
        n: Number of business days; may be negative or zero.
        cal: A calendar, an identifier, or ``None`` for ``weekday``.
        roll: How to normalise ``value`` before moving.
        tz: Timezone used to project aware inputs.

    Returns:
        The same type as ``value``.

    Examples:
        >>> offset("2026-07-31", 5)
        '2026-08-07'
    """
    return resolve(cal).offset(value, n, roll=roll, tz=tz)


def count(
    start: Any,
    end: Any,
    *,
    cal: CalendarLike = None,
    closed: str = "left",
    tz: str | None = None,
) -> Any:
    """Count business days between two dates, half-open ``[start, end)`` by default.

    Args:
        start: First date, or a sequence of them.
        end: Second date, or a sequence of them.
        cal: A calendar, an identifier, or ``None`` for ``weekday``.
        closed: One of ``"left"``, ``"right"``, ``"both"``, ``"neither"``.
        tz: Timezone used to project aware inputs.

    Returns:
        ``int`` for scalars, an ``int64`` array if either side is a sequence.

    Examples:
        >>> count("2026-07-27", "2026-08-01")
        5
    """
    return resolve(cal).count(start, end, closed=closed, tz=tz)


def sessions(*, cal: CalendarLike = None) -> Any:
    """Every business day inside the calendar's bounds.

    Args:
        cal: A calendar, an identifier, or ``None`` for ``weekday``.

    Returns:
        A ``DatetimeIndex``, or a ``datetime64[D]`` array if pandas is absent.

    Examples:
        >>> len(sessions(cal="weekday")) > 30000
        True
    """
    return resolve(cal).sessions()


def add_tenor(
    value: Any,
    tenor: str,
    *,
    cal: CalendarLike = None,
    roll: RollLike = Roll.NONE,
    eom: bool = False,
    tz: str | None = None,
) -> Any:
    """Add a tenor expression such as ``"3M"``, ``"2B"`` or ``"1Y+2B"``.

    Terms apply left to right. Month and year terms clamp to the end of the target month;
    ``eom`` additionally applies the end-of-month rule.

    Args:
        value: A date-like scalar or sequence.
        tenor: The tenor expression, case-insensitive.
        cal: A calendar, an identifier, or ``None`` for ``weekday``. Required in practice
            for any expression containing a ``B`` term.
        roll: How to adjust the final result.
        eom: Apply the end-of-month rule to month and year terms.
        tz: Timezone used to project aware inputs.

    Returns:
        The same type as ``value``.

    Examples:
        >>> add_tenor("2026-01-31", "1M")
        '2026-02-28'
        >>> add_tenor("2026-02-28", "1M", eom=True)
        '2026-03-31'
        >>> add_tenor("2026-07-31", "1Y+2B", cal="XNYS")
        '2027-08-04'
    """
    return resolve(cal).add_tenor(value, tenor, roll=roll, eom=eom, tz=tz)
