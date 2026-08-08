"""What to pick inside each period — the ``on`` argument of :func:`schedule` (§8).

A recurrence is two independent decisions: how to cut the window into periods, and what to
take from each one. This module owns the second.

A selector is written as an ordinal and, optionally, what to count::

    "last"        the last calendar day of the period
    "1"           the first calendar day
    "15"          the fifteenth calendar day
    "-2"          the second to last calendar day
    "last B"      the last business day
    "1st B"       the first business day
    "2 THU"       the second Thursday
    "last FRI"    the last Friday
    "-2 WED"      the second to last Wednesday
    "edges"       the period boundaries themselves, not a day inside them

Negative counts from the end throughout, so ``-1`` and ``"last"`` are the same thing.
Ordinal suffixes are cosmetic: ``"2 THU"`` and ``"2nd THU"`` parse identically.

The string form exists because schedules arrive from configuration files. In code the
equivalent value object reads better and survives a rename::

    Nth(-1)          == "last"
    Nth(-1, "B")     == "last B"
    Nth(2, THU)      == "2 THU"
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum
from functools import lru_cache
from typing import Union

from better_calendar._compat import DATACLASS_SLOTS, StrEnum
from better_calendar.core.errors import ScheduleError

__all__ = [
    "EDGES",
    "FRI",
    "MON",
    "SAT",
    "SUN",
    "THU",
    "TUE",
    "WED",
    "Edges",
    "Nth",
    "SelectorLike",
    "Unit",
    "Weekday",
    "parse_selector",
]


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

_FULL_NAMES = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
_WEEKDAY_BY_NAME = {name[:3]: Weekday(index) for index, name in enumerate(_FULL_NAMES)}
_WEEKDAY_BY_NAME.update({name: Weekday(index) for index, name in enumerate(_FULL_NAMES)})

#: What an ordinal counts.
_BUSINESS_WORDS = frozenset({"B", "BD", "BDAY", "BUSINESS"})
_DAY_WORDS = frozenset({"", "D", "DAY", "CAL", "CALENDAR"})

_ORDINAL_RE = re.compile(r"^(?P<sign>-?)(?P<count>\d+)(?:ST|ND|RD|TH)?$")


class Unit(StrEnum):
    """What a selector's ordinal counts.

    Examples:
        >>> parse_selector("last B").unit
        <Unit.BUSINESS: 'business'>
    """

    DAY = "day"
    BUSINESS = "business"
    WEEKDAY = "weekday"


@dataclass(frozen=True, **DATACLASS_SLOTS)
class Edges:
    """Select the period boundaries rather than a day inside each period.

    Produces one date more than there are periods, and is what turns
    :func:`~better_calendar.schedule.schedule.schedule` into a coupon schedule.

    Examples:
        >>> parse_selector("edges") is EDGES
        True
    """


#: The singleton boundary selector; ``on="edges"`` parses to this.
EDGES = Edges()


@dataclass(frozen=True, init=False, **DATACLASS_SLOTS)
class Nth:
    """The ``n``-th day, business day or weekday of a period.

    Attributes:
        n: 1-based occurrence. Negative counts from the end of the period, so ``-1`` is
            the last one.
        unit: What ``n`` counts.
        weekday: Which weekday, when ``unit`` is :attr:`Unit.WEEKDAY`.

    Examples:
        >>> Nth(-1)
        Nth(n=-1, unit=<Unit.DAY: 'day'>, weekday=None)
        >>> Nth(-1, "B").unit
        <Unit.BUSINESS: 'business'>
        >>> Nth(2, THU).weekday
        <Weekday.THU: 3>
        >>> Nth(2, THU) == parse_selector("2nd THU")
        True
    """

    n: int
    unit: Unit
    weekday: Weekday | None

    def __init__(self, n: int, of: str | Weekday | int | None = None) -> None:
        if int(n) == 0:
            raise ScheduleError(
                "A selector's ordinal is 1-based, so 0 selects nothing. Use 1 for the "
                "first occurrence and -1 (or 'last') for the last."
            )
        unit, weekday = _classify(of)
        object.__setattr__(self, "n", int(n))
        object.__setattr__(self, "unit", unit)
        object.__setattr__(self, "weekday", weekday)

    def __str__(self) -> str:
        ordinal = "last" if self.n == -1 else ("first" if self.n == 1 else str(self.n))
        if self.unit is Unit.BUSINESS:
            return f"{ordinal} B"
        if self.unit is Unit.WEEKDAY and self.weekday is not None:
            return f"{ordinal} {self.weekday.name}"
        return ordinal


def _classify(of: str | Weekday | int | None) -> tuple[Unit, Weekday | None]:
    """Work out what an ordinal counts, from the loose second argument of :class:`Nth`."""
    if of is None:
        return Unit.DAY, None
    if isinstance(of, Weekday):
        return Unit.WEEKDAY, of
    if isinstance(of, int):
        return Unit.WEEKDAY, Weekday(of)
    word = str(of).strip().upper()
    if word in _DAY_WORDS:
        return Unit.DAY, None
    if word in _BUSINESS_WORDS:
        return Unit.BUSINESS, None
    if word in _WEEKDAY_BY_NAME:
        return Unit.WEEKDAY, _WEEKDAY_BY_NAME[word]
    raise ScheduleError(
        f"Cannot read {of!r} as something to count. Use 'B' for business days, a weekday "
        f"name such as 'FRI' or 'FRIDAY', or nothing at all for calendar days."
    )


SelectorLike = Union[str, Nth, Edges]


@lru_cache(maxsize=256)
def parse_selector(text: str) -> Nth | Edges:
    """Parse the string form of a selector.

    Memoised, because selectors arrive from configuration files inside loops.

    Args:
        text: A selector such as ``"last"``, ``"1st B"``, ``"2 THU"`` or ``"edges"``.

    Returns:
        The parsed :class:`Nth`, or :data:`EDGES`.

    Raises:
        ScheduleError: If the text does not parse, naming what was expected.

    Examples:
        >>> parse_selector("last")
        Nth(n=-1, unit=<Unit.DAY: 'day'>, weekday=None)
        >>> parse_selector("last FRI").weekday
        <Weekday.FRI: 4>
        >>> parse_selector("3rd B").n
        3
        >>> parse_selector("last week")
        Traceback (most recent call last):
        ...
        better_calendar.core.errors.ScheduleError: Cannot read 'WEEK' as something to
        count. Use 'B' for business days, a weekday name such as 'FRI' or 'FRIDAY', or
        nothing at all for calendar days.
    """
    words = str(text).strip().upper().split()
    if not words:
        raise ScheduleError(
            "A selector cannot be empty. Use 'last', '1', '2 THU', 'last B' or 'edges'."
        )
    if len(words) == 1 and words[0] == "EDGES":
        return EDGES
    if len(words) > 2:
        raise ScheduleError(
            f"Cannot parse selector {text!r}: expected an ordinal and at most one thing "
            f"to count, as in 'last FRI' or '2nd B'."
        )

    head, tail = words[0], (words[1] if len(words) == 2 else "")
    if head == "LAST":
        count = -1
    elif head == "FIRST":
        count = 1
    else:
        match = _ORDINAL_RE.match(head)
        if match is None:
            raise ScheduleError(
                f"Cannot parse selector {text!r}: {head!r} is not an ordinal. Use a whole "
                f"number such as '1', '15' or '-2', or the words 'first' and 'last'."
            )
        count = int(match["count"]) * (-1 if match["sign"] == "-" else 1)
    return Nth(count, tail)


def as_selector(value: SelectorLike) -> Nth | Edges:
    """Coerce whatever the caller passed as ``on`` into a parsed selector.

    Args:
        value: A string, an :class:`Nth`, or :data:`EDGES`.

    Returns:
        The parsed selector.

    Examples:
        >>> as_selector("last FRI") == Nth(-1, FRI)
        True
        >>> as_selector(Nth(1, "B")).unit
        <Unit.BUSINESS: 'business'>
    """
    if isinstance(value, (Nth, Edges)):
        return value
    return parse_selector(str(value))
