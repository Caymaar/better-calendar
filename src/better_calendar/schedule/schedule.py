"""Coupon-style schedule generation (§8.1).

**The architectural rule this module exists to enforce:** generation happens in two
strictly separated stages. First :meth:`Schedule.unadjusted` produces dates by pure
calendar rules — no calendar, no holidays, no roll convention, nothing that could change
when a snapshot is regenerated. Only then does :meth:`Schedule.dates` apply
``cal.adjust(...)`` on top.

The two are never interleaved, and the reason is reconciliation. A downstream system
holding a trade booked last year needs to know that its 15 March coupon is the same
contractual date as ours, even if a holiday moved when it actually pays. An unadjusted
schedule that depended on the calendar could not answer that: upgrade the holiday data and
the *contract* appears to change. Keeping stage one calendar-free means the unadjusted
schedule is a function of the trade terms alone, forever.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np

from better_calendar.calendars.registry import CalendarLike, resolve
from better_calendar.core.epoch import date_to_days
from better_calendar.core.range import DateRange
from better_calendar.core.types import DateLike, days_to_index, to_date
from better_calendar.offsets.conventions import Roll, RollLike
from better_calendar.schedule.stubs import Stub, unadjusted_dates

__all__ = ["Schedule"]


@dataclass(frozen=True)
class Schedule:
    """A sequence of period boundaries between two dates.

    Attributes:
        start: First date of the schedule.
        end: Last date of the schedule.
        freq: Period length, such as ``"6M"`` or ``"3M"``.
        cal: Calendar used by :meth:`dates` and :meth:`periods`; ``None`` means the plain
            ``weekday`` calendar. :meth:`unadjusted` never touches it.
        roll: Roll convention applied when adjusting.
        stub: How to handle a term that is not a whole number of periods; see
            :mod:`better_calendar.schedule.stubs`.
        eom: Apply the end-of-month rule when stepping by months or years.

    Examples:
        >>> schedule = Schedule("2026-01-15", "2027-01-15", freq="6M", cal="XNYS")
        >>> list(schedule.unadjusted().strftime("%Y-%m-%d"))
        ['2026-01-15', '2026-07-15', '2027-01-15']
        >>> list(schedule.dates().strftime("%Y-%m-%d"))
        ['2026-01-15', '2026-07-15', '2027-01-15']
        >>> len(schedule.periods())
        2
    """

    start: DateLike
    end: DateLike
    freq: str = "6M"
    cal: CalendarLike = None
    roll: RollLike = Roll.MODIFIED_FOLLOWING
    stub: Stub = "short_front"
    eom: bool = False
    _cache: dict[str, Any] = field(default_factory=dict, repr=False, compare=False, hash=False)

    def _unadjusted_days(self) -> list[date]:
        cached = self._cache.get("unadjusted")
        if cached is None:
            cached = unadjusted_dates(
                to_date(self.start),
                to_date(self.end),
                self.freq,
                stub=self.stub,
                eom=self.eom,
            )
            self._cache["unadjusted"] = cached
        return cached

    def unadjusted(self) -> Any:
        """The schedule as pure calendar arithmetic, with no calendar involved.

        Reproducible from ``start``, ``end``, ``freq``, ``stub`` and ``eom`` alone. It does
        not change when holiday data does, which is what makes it the thing two systems
        can reconcile on.

        Returns:
            A ``DatetimeIndex`` (or a ``datetime64[D]`` array without pandas).

        Examples:
            >>> schedule = Schedule("2026-01-31", "2026-07-31", freq="3M")
            >>> list(schedule.unadjusted().strftime("%Y-%m-%d"))
            ['2026-01-31', '2026-04-30', '2026-07-31']
        """
        days = np.array([date_to_days(day) for day in self._unadjusted_days()], dtype=np.int64)
        return days_to_index(days)

    def dates(self) -> Any:
        """The schedule adjusted onto business days.

        Stage two: :meth:`unadjusted` first, then ``cal.adjust`` with :attr:`roll`. Two
        unadjusted dates can collapse onto the same business day; duplicates are kept
        rather than silently dropped, because a zero-length accrual period is a fact about
        the schedule and hiding it would be worse than showing it.

        Returns:
            A ``DatetimeIndex`` (or a ``datetime64[D]`` array without pandas).

        Examples:
            >>> schedule = Schedule("2026-02-28", "2026-08-31", freq="3M", cal="XNYS")
            >>> list(schedule.unadjusted().strftime("%Y-%m-%d"))
            ['2026-02-28', '2026-05-31', '2026-08-31']
            >>> # 28 February is a Saturday; modified following stays inside February.
            >>> list(schedule.dates().strftime("%Y-%m-%d"))
            ['2026-02-27', '2026-05-29', '2026-08-31']
        """
        calendar = resolve(self.cal)
        days = np.array([date_to_days(day) for day in self._unadjusted_days()], dtype=np.int64)
        adjusted = calendar._adjust_days(days, Roll.parse(self.roll))
        return days_to_index(np.asarray(adjusted, dtype=np.int64))

    def periods(self) -> list[DateRange]:
        """The accrual periods between consecutive adjusted dates.

        Half-open ``[start, end)`` so that consecutive periods tile without the boundary
        day being counted twice (I10).

        Returns:
            One :class:`~better_calendar.core.range.DateRange` per period.

        Examples:
            >>> schedule = Schedule("2026-01-15", "2027-01-15", freq="6M")
            >>> [(str(p.start), str(p.end)) for p in schedule.periods()]
            [('2026-01-15', '2026-07-15'), ('2026-07-15', '2027-01-15')]
        """
        index = self.dates()
        boundaries = [to_date(value) for value in index]
        return [DateRange(first, second) for first, second in zip(boundaries, boundaries[1:])]

    def __len__(self) -> int:
        return len(self._unadjusted_days())
