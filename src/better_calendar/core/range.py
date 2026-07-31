"""A small frozen interval value object (§8.2).

Half-open ``[start, end)`` is the default everywhere in this library (I10); any other
convention has to be asked for by name via ``closed``.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from better_calendar._compat import DATACLASS_SLOTS
from better_calendar.core._freq import parse_freq, step_date
from better_calendar.core.errors import BetterCalendarError
from better_calendar.core.types import DateLike, to_date

if TYPE_CHECKING:  # pragma: no cover - typing only
    from better_calendar.calendars.base import Calendar

__all__ = ["Closed", "DateRange"]

#: The four interval conventions, spelled the way pandas spells them.
Closed = str
_CLOSED_VALUES = ("left", "right", "both", "neither")


@dataclass(frozen=True, init=False, **DATACLASS_SLOTS)
class DateRange:
    """An interval between two calendar days.

    Attributes:
        start: First day of the interval (included unless ``closed`` excludes it).
        end: Last day of the interval (excluded by default).
        closed: One of ``"left"`` (default), ``"right"``, ``"both"``, ``"neither"``.

    Examples:
        >>> period = DateRange("2026-07-27", "2026-08-01")
        >>> len(period)
        5
        >>> date(2026, 8, 1) in period          # half-open: `end` is excluded
        False
        >>> list(DateRange("2026-07-27", "2026-07-29"))
        [datetime.date(2026, 7, 27), datetime.date(2026, 7, 28)]
    """

    start: date
    end: date
    closed: Closed = "left"

    def __init__(self, start: DateLike, end: DateLike, closed: Closed = "left") -> None:
        if closed not in _CLOSED_VALUES:
            raise BetterCalendarError(
                f"Unknown interval convention {closed!r}. Use one of "
                f"{', '.join(repr(v) for v in _CLOSED_VALUES)}."
            )
        first, last = to_date(start), to_date(end)
        if last < first:
            raise BetterCalendarError(
                f"DateRange end {last.isoformat()} is before start {first.isoformat()}. "
                f"Swap the arguments, or build the range from the earlier date."
            )
        object.__setattr__(self, "start", first)
        object.__setattr__(self, "end", last)
        object.__setattr__(self, "closed", closed)

    # -- interval semantics -------------------------------------------------

    @property
    def first_day(self) -> date:
        """The first day actually inside the interval.

        Examples:
            >>> DateRange("2026-07-27", "2026-08-01", "neither").first_day
            datetime.date(2026, 7, 28)
        """
        return self.start if self.closed in ("left", "both") else self.start + timedelta(days=1)

    @property
    def last_day(self) -> date:
        """The last day actually inside the interval.

        Examples:
            >>> DateRange("2026-07-27", "2026-08-01").last_day
            datetime.date(2026, 7, 31)
        """
        return self.end if self.closed in ("right", "both") else self.end - timedelta(days=1)

    def __contains__(self, value: object) -> bool:
        try:
            day = to_date(value)  # type: ignore[arg-type]  # rejected below if unsupported
        except BetterCalendarError:
            return False
        return self.first_day <= day <= self.last_day

    def __iter__(self) -> Iterator[date]:
        day = self.first_day
        last = self.last_day
        while day <= last:
            yield day
            day += timedelta(days=1)

    def __len__(self) -> int:
        return max(0, (self.last_day - self.first_day).days + 1)

    def is_empty(self) -> bool:
        """Whether the interval contains no days.

        Examples:
            >>> DateRange("2026-07-27", "2026-07-27").is_empty()
            True
        """
        return len(self) == 0

    # -- set operations -----------------------------------------------------

    def overlaps(self, other: DateRange) -> bool:
        """Whether the two intervals share at least one day.

        Args:
            other: The interval to test against.

        Returns:
            ``True`` if any day belongs to both.

        Examples:
            >>> DateRange("2026-01-01", "2026-02-01").overlaps(
            ...     DateRange("2026-01-15", "2026-03-01")
            ... )
            True
        """
        if self.is_empty() or other.is_empty():
            return False
        return self.first_day <= other.last_day and other.first_day <= self.last_day

    def intersection(self, other: DateRange) -> DateRange:
        """Return the overlapping interval, as a closed-both range.

        Args:
            other: The interval to intersect with.

        Returns:
            The shared interval; an empty range if they do not overlap.

        Examples:
            >>> DateRange("2026-01-01", "2026-02-01").intersection(
            ...     DateRange("2026-01-15", "2026-03-01")
            ... )
            DateRange(start=datetime.date(2026, 1, 15), end=datetime.date(2026, 1, 31),
                      closed='both')
        """
        if not self.overlaps(other):
            return DateRange(self.start, self.start, "neither")
        return DateRange(
            max(self.first_day, other.first_day),
            min(self.last_day, other.last_day),
            "both",
        )

    # -- derived views ------------------------------------------------------

    def business_days(self, cal: Calendar | str | None = None) -> Any:
        """The good days of ``cal`` inside this interval.

        Args:
            cal: A calendar, an identifier resolved through the registry, or ``None``
                for the plain Mon-Fri ``weekday`` calendar.

        Returns:
            A ``DatetimeIndex`` (or a ``datetime64[D]`` array if pandas is absent).

        Examples:
            >>> len(DateRange("2026-07-27", "2026-08-03").business_days())
            5
            >>> len(DateRange("2026-07-27", "2026-08-03").business_days("crypto:24x7"))
            7
        """
        from better_calendar.calendars.registry import resolve

        return resolve(cal).bdays_between(self.first_day, self.last_day, closed="both")

    def split(self, freq: str) -> list[DateRange]:
        """Chop the interval into consecutive sub-ranges of length ``freq``.

        The final sub-range is truncated at :attr:`end` when the interval is not a whole
        multiple of ``freq``. Sub-ranges inherit this range's ``closed`` convention at the
        outer edges and are half-open between each other, so they tile without overlap.

        Args:
            freq: A frequency such as ``"M"``, ``"3M"``, ``"Q"``, ``"W"``.

        Returns:
            The sub-ranges, in order.

        Examples:
            >>> [str(r.start) for r in DateRange("2026-01-01", "2026-04-01").split("M")]
            ['2026-01-01', '2026-02-01', '2026-03-01']
        """
        parsed = parse_freq(freq)
        pieces: list[DateRange] = []
        cursor = self.start
        step = 1
        while cursor < self.end:
            nxt = min(step_date(self.start, parsed, step), self.end)
            if nxt <= cursor:  # pragma: no cover - guarded by parse_freq's multiple > 0
                break
            is_first = not pieces
            is_last = nxt >= self.end
            closed = _sub_closed(self.closed, is_first=is_first, is_last=is_last)
            pieces.append(DateRange(cursor, nxt, closed))
            cursor = nxt
            step += 1
        return pieces


def _sub_closed(outer: Closed, *, is_first: bool, is_last: bool) -> Closed:
    """Pick a sub-range convention that tiles the outer range without gaps or overlap."""
    left_open = outer in ("right", "neither") and is_first
    right_closed = outer in ("right", "both") and is_last
    if left_open and right_closed:
        return "right"
    if left_open:
        return "neither"
    if right_closed:
        return "both"
    return "left"
