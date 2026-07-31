"""Minimal frequency parsing shared by :mod:`~better_calendar.core.range` and schedules.

A frequency is a signed multiple of a calendar step: ``"M"``, ``"3M"``, ``"6M"``, ``"Q"``,
``"Y"``, ``"W"``, ``"D"``. It is deliberately *not* the tenor grammar of §7.3 — a tenor is
an offset applied once, a frequency is a repeating step and therefore admits no business
day unit and no compound terms.
"""

from __future__ import annotations

import calendar as _stdlib_calendar
import re
from datetime import date, timedelta
from functools import lru_cache
from typing import NamedTuple

from better_calendar.core.errors import BetterCalendarError

__all__ = ["Freq", "parse_freq", "step_date"]

_FREQ_RE = re.compile(r"^(?P<count>\d*)(?P<unit>[DWMQY])$")

#: How many months each month-based unit advances per step.
_MONTHS_PER_UNIT = {"M": 1, "Q": 3, "Y": 12}
#: How many days each day-based unit advances per step.
_DAYS_PER_UNIT = {"D": 1, "W": 7}


class Freq(NamedTuple):
    """A parsed frequency: ``multiple`` repetitions of ``unit``.

    Examples:
        >>> parse_freq("3M")
        Freq(multiple=3, unit='M')
    """

    # Named `multiple`, not `count`: a NamedTuple field called `count` would shadow
    # `tuple.count`.
    multiple: int
    unit: str


@lru_cache(maxsize=256)
def parse_freq(text: str) -> Freq:
    """Parse a frequency string such as ``"M"``, ``"3M"`` or ``"Q"``.

    Args:
        text: The frequency, case-insensitive. A bare unit means a count of 1.

    Returns:
        The parsed :class:`Freq`.

    Raises:
        BetterCalendarError: If the string is not a valid frequency.

    Examples:
        >>> parse_freq("q")
        Freq(multiple=1, unit='Q')
        >>> parse_freq("6M")
        Freq(multiple=6, unit='M')
    """
    match = _FREQ_RE.match(text.strip().upper())
    if match is None:
        raise BetterCalendarError(
            f"Cannot parse frequency {text!r}. Use a unit D, W, M, Q or Y, optionally "
            f"prefixed by a positive count, for example 'M', '3M' or 'Q'."
        )
    multiple = int(match["count"] or 1)
    if multiple == 0:
        raise BetterCalendarError(
            f"Frequency {text!r} has a count of zero, which would never advance. "
            f"Use a count of 1 or more."
        )
    return Freq(multiple, match["unit"])


def _add_months(value: date, months: int) -> date:
    """Add months, clamping to the end of the target month (31 Jan + 1M -> 28/29 Feb)."""
    total = value.year * 12 + (value.month - 1) + months
    year, month_index = divmod(total, 12)
    month = month_index + 1
    last_day = _stdlib_calendar.monthrange(year, month)[1]
    return date(year, month, min(value.day, last_day))


def step_date(value: date, freq: Freq, steps: int = 1) -> date:
    """Advance ``value`` by ``steps`` repetitions of ``freq``.

    Args:
        value: The date to advance.
        freq: The parsed frequency.
        steps: How many steps to take; may be negative.

    Returns:
        The advanced date.

    Examples:
        >>> step_date(date(2026, 1, 31), parse_freq("1M"))
        datetime.date(2026, 2, 28)
        >>> step_date(date(2026, 1, 1), parse_freq("2W"), steps=3)
        datetime.date(2026, 2, 12)
    """
    amount = freq.multiple * steps
    if freq.unit in _MONTHS_PER_UNIT:
        return _add_months(value, _MONTHS_PER_UNIT[freq.unit] * amount)
    return value + timedelta(days=_DAYS_PER_UNIT[freq.unit] * amount)
