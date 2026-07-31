"""The :class:`Calendar` type (§5).

A calendar *is* a sorted ``int64`` array of good days over a bounded horizon. Everything
else — membership, roll conventions, offsets, counting, set algebra — is
``numpy.searchsorted`` on that array. Nothing here loops over dates.

Calendars are frozen and hashable (I1), which is what makes them safe as ``lru_cache``
keys in the registry and cheap to pass around.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, time
from typing import Any, Literal, Union

import numpy as np
from numpy.typing import NDArray

from better_calendar.core._pandas import optional_pandas, require_pandas
from better_calendar.core.epoch import (
    DEFAULT_BOUNDS,
    add_months,
    date_to_days,
    datetime64_to_days,
    days_to_date,
    days_to_datetime64,
    weekday_of,
)
from better_calendar.core.errors import (
    BetterCalendarError,
    NotABusinessDayError,
    OutOfBoundsError,
)
from better_calendar.core.types import DateLike, DateSeqLike, Kind, from_days, kind_of, to_days
from better_calendar.offsets.conventions import Roll, RollLike

__all__ = ["WEEKMASK_ALL", "WEEKMASK_WEEKDAYS", "Calendar"]

#: Day names in ``date.weekday()`` order, which is also the order numpy uses.
_DAY_NAMES: tuple[str, ...] = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_DAY_INDEX = {name.lower(): index for index, name in enumerate(_DAY_NAMES)}

WEEKMASK_WEEKDAYS = "Mon Tue Wed Thu Fri"
WEEKMASK_ALL = "Mon Tue Wed Thu Fri Sat Sun"

#: The interval conventions accepted by :meth:`Calendar.count` (I10 — ``"left"`` default).
_CLOSED_VALUES = ("left", "right", "both", "neither")

_Side = Literal["left", "right"]


def _sides(closed: str) -> tuple[_Side, _Side]:
    """The two ``searchsorted`` sides that implement an interval convention.

    Counting business days in an interval is the difference of two ``searchsorted``
    positions; which side each one takes is the *whole* of the convention. Keeping the
    mapping in one place is what stops `[a, b)` and `(a, b]` drifting apart.
    """
    if closed not in _CLOSED_VALUES:
        raise BetterCalendarError(
            f"Unknown interval convention {closed!r}. Use one of "
            f"{', '.join(repr(v) for v in _CLOSED_VALUES)}."
        )
    start: _Side = "right" if closed in ("right", "neither") else "left"
    end: _Side = "right" if closed in ("right", "both") else "left"
    return start, end


_EMPTY_HOLIDAYS: NDArray[np.datetime64] = np.empty(0, dtype="datetime64[D]")
_EMPTY_HOLIDAYS.setflags(write=False)

#: What ``Calendar(holidays=...)`` accepts. It is always stored as a normalised,
#: read-only ``datetime64[D]`` array, whatever it was given as.
HolidaysLike = Union[NDArray[np.datetime64], DateSeqLike, None]


def _normalise_weekmask(weekmask: str) -> str:
    """Canonicalise a weekmask so that equal calendars hash equal.

    Accepts the day-name form (``"Mon Tue Wed Thu Fri"``), the numpy 7-character binary
    form (``"1111100"``), and ``"all"``.
    """
    text = weekmask.strip()
    if text.lower() == "all":
        return WEEKMASK_ALL
    if len(text) == 7 and set(text) <= {"0", "1"}:
        selected = [index for index, flag in enumerate(text) if flag == "1"]
    else:
        selected = []
        for token in text.replace(",", " ").split():
            index = _DAY_INDEX.get(token[:3].lower())
            if index is None:
                raise BetterCalendarError(
                    f"Unknown day {token!r} in weekmask {weekmask!r}. Use day names "
                    f"('Mon Tue Wed Thu Fri'), the binary form ('1111100'), or 'all'."
                )
            selected.append(index)
    if not selected:
        raise BetterCalendarError(
            f"Weekmask {weekmask!r} selects no days, so the calendar would have no "
            f"business days at all. Name at least one day, or use 'all'."
        )
    return " ".join(_DAY_NAMES[index] for index in sorted(set(selected)))


def _normalise_holidays(holidays: Any) -> NDArray[np.datetime64]:
    """Coerce holidays to a sorted, unique, read-only ``datetime64[D]`` array.

    Read-only matters: the hash is derived from the buffer's bytes, so a caller mutating
    the array in place would silently corrupt every cache keyed on this calendar (I1).
    """
    if holidays is None:
        values = _EMPTY_HOLIDAYS
    elif isinstance(holidays, np.ndarray) and np.issubdtype(holidays.dtype, np.datetime64):
        values = holidays.astype("datetime64[D]")
    else:
        days = to_days(holidays) if len(holidays) else np.empty(0, dtype=np.int64)
        values = days_to_datetime64(np.asarray(days, dtype=np.int64))
    unique = np.unique(values)
    unique = np.ascontiguousarray(unique)
    unique.setflags(write=False)
    return unique


@dataclass(frozen=True, eq=False, init=False)
class Calendar:
    """A finite, immutable set of business days.

    ``__init__`` is written by hand rather than generated so that ``holidays`` can be
    *given* as any date-like sequence while always *reading back* as a normalised
    ``datetime64[D]`` array. A generated ``__init__`` would force those two types to be
    the same one, and either the call sites or the readers would have to lie.

    Attributes:
        name: Identifier, used in error messages and in derived composite names.
        holidays: Sorted, unique ``datetime64[D]`` array of non-business days that would
            otherwise be allowed by ``weekmask``.
        weekmask: Which weekdays can be business days. Day names, the numpy binary form,
            or ``"all"`` for a 24/7 calendar.
        bounds: Inclusive ``(first, last)`` day of the horizon. Queries outside raise
            :class:`~better_calendar.core.errors.OutOfBoundsError` (I2).
        tz: IANA timezone giving the calendar instant semantics; ``None`` means it has
            none, and projecting an aware timestamp onto it requires an explicit ``tz``.
        session_start: Local time at which a calendar day begins (§9).
        provider: Which upstream produced ``holidays``, if any.
        provider_version: The version of that upstream, for snapshot provenance (I8).

    Examples:
        >>> cal = Calendar("weekday")
        >>> cal.is_bday("2026-08-01")            # a Saturday
        False
        >>> cal.next_bday("2026-08-01")
        '2026-08-03'
        >>> cal.offset(date(2026, 7, 31), 1)
        datetime.date(2026, 8, 3)
    """

    name: str
    holidays: NDArray[np.datetime64]
    weekmask: str
    bounds: tuple[date, date]
    tz: str | None
    session_start: time
    provider: str | None
    provider_version: str | None

    def __init__(
        self,
        name: str,
        holidays: HolidaysLike = None,
        weekmask: str = WEEKMASK_WEEKDAYS,
        bounds: tuple[date, date] = DEFAULT_BOUNDS,
        tz: str | None = None,
        session_start: time = time(0, 0),
        provider: str | None = None,
        provider_version: str | None = None,
    ) -> None:
        first, last = bounds
        first = date(first.year, first.month, first.day)
        last = date(last.year, last.month, last.day)
        if last < first:
            raise BetterCalendarError(
                f"Calendar {name!r} has bounds ending {last.isoformat()} before they "
                f"start {first.isoformat()}. Pass bounds as (first_day, last_day)."
            )
        set_field = object.__setattr__
        set_field(self, "name", name)
        set_field(self, "holidays", _normalise_holidays(holidays))
        set_field(self, "weekmask", _normalise_weekmask(weekmask))
        set_field(self, "bounds", (first, last))
        set_field(self, "tz", tz)
        set_field(self, "session_start", session_start)
        set_field(self, "provider", provider)
        set_field(self, "provider_version", provider_version)

    # -- identity -----------------------------------------------------------

    @property
    def _key(self) -> tuple[Any, ...]:
        """The identity tuple two calendars must share to be considered equal."""
        cached = self.__dict__.get("_key_cache")
        if cached is None:
            digest = hashlib.sha1(self.holidays.tobytes(), usedforsecurity=False).hexdigest()
            cached = (
                self.name,
                self.weekmask,
                self.bounds,
                self.tz,
                self.session_start,
                digest,
            )
            self.__dict__["_key_cache"] = cached
        return cached

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Calendar):
            return NotImplemented
        return self._key == other._key

    def __hash__(self) -> int:
        return hash(self._key)

    def __repr__(self) -> str:
        return (
            f"Calendar({self.name!r}, weekmask={self.weekmask!r}, "
            f"holidays={len(self.holidays)}, "
            f"bounds=({self.bounds[0].isoformat()}, {self.bounds[1].isoformat()}))"
        )

    # -- the workhorse ------------------------------------------------------

    @property
    def _good(self) -> NDArray[np.int64]:
        """Sorted epoch-day numbers of every business day inside :attr:`bounds`.

        Materialised once per calendar and cached on the instance. ``cached_property``
        is not used because the class is frozen; writing straight into ``__dict__``
        sidesteps ``__setattr__`` without making the calendar mutable in any way callers
        can observe.
        """
        cached = self.__dict__.get("_good_cache")
        if cached is None:
            cached = self._build_good()
            self.__dict__["_good_cache"] = cached
        return cached

    def _build_good(self) -> NDArray[np.int64]:
        lo, hi = self._bounds_days
        all_days = np.arange(lo, hi + 1, dtype=np.int64)
        allowed = np.zeros(7, dtype=bool)
        for token in self.weekmask.split():
            allowed[_DAY_INDEX[token.lower()]] = True
        keep = allowed[weekday_of(all_days)]
        if self.holidays.size:
            holiday_days = datetime64_to_days(self.holidays)
            inside = holiday_days[(holiday_days >= lo) & (holiday_days <= hi)]
            # Direct indexing rather than np.isin: `all_days` is a contiguous range, so
            # the position of a holiday is known arithmetically.
            keep[inside - lo] = False
        good: NDArray[np.int64] = np.ascontiguousarray(all_days[keep])
        good.setflags(write=False)
        return good

    def good_days(
        self, start: date | None = None, end: date | None = None
    ) -> NDArray[np.int64]:
        """The calendar's good days as epoch day numbers, optionally clipped.

        The raw representation, exposed for the algebra (§6) and for callers doing their
        own numpy work. The returned array is read-only.

        Args:
            start: Inclusive lower clip, defaulting to the calendar's own lower bound.
            end: Inclusive upper clip, defaulting to the calendar's own upper bound.

        Returns:
            Sorted ``int64`` epoch days.

        Examples:
            >>> cal = Calendar("weekday", bounds=(date(2026, 8, 1), date(2026, 8, 7)))
            >>> cal.good_days()          # Mon 3rd through Fri 7th; the weekend is out
            array([20668, 20669, 20670, 20671, 20672])
        """
        days = self._good
        if start is None and end is None:
            return days
        lo = date_to_days(start) if start is not None else self._bounds_days[0]
        hi = date_to_days(end) if end is not None else self._bounds_days[1]
        return days[(days >= lo) & (days <= hi)]

    # -- bounds -------------------------------------------------------------

    @property
    def _bounds_days(self) -> tuple[int, int]:
        cached = self.__dict__.get("_bounds_days_cache")
        if cached is None:
            cached = (date_to_days(self.bounds[0]), date_to_days(self.bounds[1]))
            self.__dict__["_bounds_days_cache"] = cached
        return cached

    def _check_bounds(self, days: np.int64 | NDArray[np.int64]) -> None:
        lo, hi = self._bounds_days
        array = np.atleast_1d(np.asarray(days, dtype=np.int64))
        outside = (array < lo) | (array > hi)
        if outside.any():
            offender = days_to_date(int(array[outside][0]))
            raise OutOfBoundsError.for_date(offender.isoformat(), self.bounds, self.name)

    def _days(self, value: Any, *, tz: str | None = None) -> NDArray[np.int64]:
        """Convert an input to epoch days in the calendar's timezone, and bounds-check it."""
        days = to_days(value, tz=tz if tz is not None else self.tz)
        self._check_bounds(days)
        return np.atleast_1d(np.asarray(days, dtype=np.int64))

    @staticmethod
    def _is_seq(value: Any) -> bool:
        return kind_of(value) is Kind.SEQ

    def _restore(self, days: NDArray[np.int64], like: Any) -> Any:
        return from_days(days if self._is_seq(like) else days[0], like=like)

    # -- membership ---------------------------------------------------------

    def is_bday(self, value: Any, *, tz: str | None = None) -> Any:
        """Whether each date is a business day in this calendar.

        Args:
            value: A date-like scalar or sequence.
            tz: Timezone used to project aware inputs; defaults to :attr:`tz`.

        Returns:
            ``bool`` for a scalar, a ``bool`` array for a sequence.

        Examples:
            >>> cal = Calendar("weekday")
            >>> cal.is_bday("2026-07-31"), cal.is_bday("2026-08-01")
            (True, False)
            >>> cal.is_bday(["2026-07-31", "2026-08-01"])
            array([ True, False])
        """
        days = self._days(value, tz=tz)
        index = np.searchsorted(self._good, days)
        index = np.minimum(index, self._good.size - 1)
        result: NDArray[np.bool_] = self._good[index] == days
        return result if self._is_seq(value) else bool(result[0])

    # -- normalisation ------------------------------------------------------

    def _next_index(self, days: NDArray[np.int64], *, inclusive: bool) -> NDArray[np.int64]:
        index = np.searchsorted(self._good, days, side="left" if inclusive else "right")
        if (index >= self._good.size).any():
            raise OutOfBoundsError.for_date(
                days_to_date(int(days[index >= self._good.size][0])).isoformat(),
                self.bounds,
                self.name,
            )
        return np.asarray(index, dtype=np.int64)

    def _prev_index(self, days: NDArray[np.int64], *, inclusive: bool) -> NDArray[np.int64]:
        index = np.searchsorted(self._good, days, side="right" if inclusive else "left") - 1
        if (index < 0).any():
            raise OutOfBoundsError.for_date(
                days_to_date(int(days[index < 0][0])).isoformat(), self.bounds, self.name
            )
        return np.asarray(index, dtype=np.int64)

    def next_bday(self, value: Any, *, inclusive: bool = False, tz: str | None = None) -> Any:
        """The next business day on or after ``value``.

        Args:
            value: A date-like scalar or sequence.
            inclusive: If ``True``, a business day is returned unchanged.
            tz: Timezone used to project aware inputs; defaults to :attr:`tz`.

        Returns:
            The same type as ``value`` (I6).

        Examples:
            >>> cal = Calendar("weekday")
            >>> cal.next_bday("2026-08-01")
            '2026-08-03'
            >>> cal.next_bday("2026-07-31", inclusive=True)
            '2026-07-31'
        """
        days = self._days(value, tz=tz)
        return self._restore(self._good[self._next_index(days, inclusive=inclusive)], value)

    def prev_bday(self, value: Any, *, inclusive: bool = False, tz: str | None = None) -> Any:
        """The previous business day on or before ``value``.

        Args:
            value: A date-like scalar or sequence.
            inclusive: If ``True``, a business day is returned unchanged.
            tz: Timezone used to project aware inputs; defaults to :attr:`tz`.

        Returns:
            The same type as ``value`` (I6).

        Examples:
            >>> Calendar("weekday").prev_bday("2026-08-01")
            '2026-07-31'
        """
        days = self._days(value, tz=tz)
        return self._restore(self._good[self._prev_index(days, inclusive=inclusive)], value)

    def adjust(
        self, value: Any, roll: RollLike = Roll.FOLLOWING, *, tz: str | None = None
    ) -> Any:
        """Move a date to a nearby business day per an ISDA roll convention.

        This is the canonical date normaliser: ``adjust(d, "MF")`` is what a contractual
        date wants nine times out of ten.

        Args:
            value: A date-like scalar or sequence.
            roll: A :class:`~better_calendar.offsets.conventions.Roll`, full name, or
                short alias such as ``"MF"``.
            tz: Timezone used to project aware inputs; defaults to :attr:`tz`.

        Returns:
            The same type as ``value`` (I6).

        Raises:
            NotABusinessDayError: If ``roll`` is ``Roll.RAISE`` and a date is not good.

        Examples:
            >>> cal = Calendar("weekday")
            >>> cal.adjust("2026-08-01")                   # Saturday -> Monday
            '2026-08-03'
            >>> cal.adjust("2026-05-31", "MF")             # Sunday; forward would leave May
            '2026-05-29'
            >>> cal.adjust("2026-02-01", "MP")             # Sunday; back would leave February
            '2026-02-02'
            >>> cal.adjust("2026-08-01", Roll.NEAREST)     # Friday is one day away, Monday two
            '2026-07-31'
        """
        days = self._days(value, tz=tz)
        return self._restore(self._adjust_days(days, Roll.parse(roll)), value)

    def _adjust_days(self, days: NDArray[np.int64], roll: Roll) -> NDArray[np.int64]:
        if roll is Roll.NONE:
            return days
        if roll is Roll.RAISE:
            good = self._good[
                np.minimum(np.searchsorted(self._good, days), self._good.size - 1)
            ]
            bad = days[good != days]
            if bad.size:
                raise NotABusinessDayError.for_dates(
                    [days_to_date(int(d)).isoformat() for d in bad], self.name
                )
            return days
        if roll is Roll.FOLLOWING:
            return self._good[self._next_index(days, inclusive=True)]
        if roll is Roll.PRECEDING:
            return self._good[self._prev_index(days, inclusive=True)]

        # The remaining conventions all need both neighbours. Compute them once.
        forward = self._good[self._next_index(days, inclusive=True)]
        backward = self._good[self._prev_index(days, inclusive=True)]
        if roll is Roll.NEAREST:
            # Ties go forward, hence `<=` on the forward distance.
            return np.where(forward - days <= days - backward, forward, backward)

        # Modified variants: keep the result inside the original month. This is why the
        # month has to be recomputed from the *unadjusted* day, not from the neighbour.
        same_month = _month_index(forward) == _month_index(days)
        if roll is Roll.MODIFIED_FOLLOWING:
            return np.where(same_month, forward, backward)
        same_month_back = _month_index(backward) == _month_index(days)
        return np.where(same_month_back, backward, forward)

    # -- arithmetic ---------------------------------------------------------

    def offset(
        self,
        value: Any,
        n: int,
        *,
        roll: RollLike = Roll.FOLLOWING,
        tz: str | None = None,
    ) -> Any:
        """Move ``n`` business days from ``value``.

        The date is first normalised with ``roll``, then moved ``n`` good days — the same
        order ``numpy.busday_offset`` uses, so the two agree exactly.

        Args:
            value: A date-like scalar or sequence.
            n: Number of business days; may be negative or zero.
            roll: How to normalise ``value`` before moving.
            tz: Timezone used to project aware inputs; defaults to :attr:`tz`.

        Returns:
            The same type as ``value`` (I6).

        Raises:
            OutOfBoundsError: If the result would leave :attr:`bounds`.

        Examples:
            >>> cal = Calendar("weekday")
            >>> cal.offset("2026-07-31", 1)                    # Friday -> Monday
            '2026-08-03'
            >>> cal.offset("2026-08-01", 0)                    # Saturday -> Monday
            '2026-08-03'
            >>> cal.offset(date(2026, 8, 3), -1)
            datetime.date(2026, 7, 31)
        """
        days = self._days(value, tz=tz)
        parsed = Roll.parse(roll)
        base = self._adjust_days(days, parsed)
        index = np.searchsorted(self._good, base, side="left") + int(n)
        if ((index < 0) | (index >= self._good.size)).any():
            raise OutOfBoundsError.for_offset(n, self.bounds, self.name)
        return self._restore(self._good[index], value)

    def count(
        self,
        start: Any,
        end: Any,
        *,
        closed: str = "left",
        tz: str | None = None,
    ) -> Any:
        """Count business days between two dates, half-open ``[start, end)`` by default.

        The count is signed: ``count(b, a) == -count(a, b)`` for the ``"left"`` and
        ``"right"`` conventions, which is what makes ``count(d, offset(d, n)) == n`` hold
        for negative ``n`` too.

        Args:
            start: First date, or a sequence of them.
            end: Second date, or a sequence of them.
            closed: One of ``"left"``, ``"right"``, ``"both"``, ``"neither"`` (I10).
            tz: Timezone used to project aware inputs; defaults to :attr:`tz`.

        Returns:
            ``int`` for scalars, an ``int64`` array if either side is a sequence.

        Examples:
            >>> cal = Calendar("weekday")
            >>> cal.count("2026-07-27", "2026-08-01")          # Mon..Fri, Sat excluded
            5
            >>> cal.count("2026-07-27", "2026-07-31", closed="both")
            5
        """
        start_side, end_side = _sides(closed)
        first = self._days(start, tz=tz)
        last = self._days(end, tz=tz)
        result = np.searchsorted(self._good, last, side=end_side) - np.searchsorted(
            self._good, first, side=start_side
        )
        counts = np.asarray(result, dtype=np.int64)
        if self._is_seq(start) or self._is_seq(end):
            return counts
        return int(counts[0])

    # -- tenors ---------------------------------------------------------------

    def add_tenor(
        self,
        value: Any,
        tenor: str,
        *,
        roll: RollLike = Roll.NONE,
        eom: bool = False,
        tz: str | None = None,
    ) -> Any:
        """Add a tenor expression such as ``"3M"``, ``"2B"`` or ``"1Y+2B"``.

        Terms are applied **left to right**, and the order matters: ``"1M+2B"`` is not
        ``"2B+1M"`` in general. Month and year terms clamp to the end of the target month;
        ``eom`` additionally applies the end-of-month rule. See
        :mod:`better_calendar.offsets.tenor` for both.

        Business-day terms move through this calendar, rolling forward first if they start
        from a non-business day — the same order :meth:`offset` uses. ``roll`` is applied
        once, to the final result.

        Args:
            value: A date-like scalar or sequence.
            tenor: The tenor expression, case-insensitive.
            roll: How to adjust the final result; ``Roll.NONE`` by default, because a
                tenor is a period and adjusting it is a separate decision.
            eom: Apply the end-of-month rule to month and year terms.
            tz: Timezone used to project aware inputs; defaults to :attr:`tz`.

        Returns:
            The same type as ``value`` (I6).

        Raises:
            TenorParseError: If the expression does not match the grammar.

        Examples:
            >>> cal = Calendar("weekday")
            >>> cal.add_tenor("2026-01-31", "1M")            # clamped into February
            '2026-02-28'
            >>> cal.add_tenor("2026-02-28", "1M", eom=True)  # end-of-month rule
            '2026-03-31'
            >>> cal.add_tenor("2026-07-31", "2B")            # Friday, two business days
            '2026-08-04'
            >>> cal.add_tenor("2026-05-31", "1M", roll="MF") # land on a business day
            '2026-06-30'
        """
        from better_calendar.offsets.tenor import parse_tenor

        parsed = parse_tenor(tenor)
        days = self._days(value, tz=tz)
        for term in parsed.terms:
            days = self._apply_term(days, term.unit, term.count, eom=eom)
        return self._restore(self._adjust_days(days, Roll.parse(roll)), value)

    def _apply_term(
        self, days: NDArray[np.int64], unit: str, count: int, *, eom: bool
    ) -> NDArray[np.int64]:
        """Apply one tenor term to an array of epoch days."""
        if unit == "D":
            shifted = days + count
        elif unit == "W":
            shifted = days + 7 * count
        elif unit == "M":
            shifted = add_months(days, count, end_of_month=eom)
        elif unit == "Y":
            shifted = add_months(days, 12 * count, end_of_month=eom)
        else:  # "B" — the only unit that needs the calendar itself
            base = self._adjust_days(days, Roll.FOLLOWING)
            index = np.searchsorted(self._good, base, side="left") + count
            if ((index < 0) | (index >= self._good.size)).any():
                raise OutOfBoundsError.for_offset(f"{count}B", self.bounds, self.name)
            return np.asarray(self._good[index], dtype=np.int64)
        self._check_bounds(shifted)
        return np.asarray(shifted, dtype=np.int64)

    def bday(self, n: int = 1, *, roll: RollLike = Roll.FOLLOWING) -> Any:
        """A :class:`~better_calendar.offsets.bday.BDay` bound to this calendar.

        Args:
            n: Number of business days the offset moves.
            roll: How to normalise a non-business day before moving.

        Returns:
            An offset object usable as ``some_date + cal.bday(3)``.

        Examples:
            >>> from datetime import date
            >>> date(2026, 7, 31) + Calendar("weekday").bday(1)
            datetime.date(2026, 8, 3)
        """
        from better_calendar.offsets.bday import BDay

        return BDay(n, cal=self, roll=Roll.parse(roll))

    def to_pandas_offset(self) -> Any:
        """This calendar as a real :class:`pandas.offsets.CustomBusinessDay`.

        For pandas machinery that insists on a genuine ``DateOffset`` — ``date_range``,
        ``resample``, ``rolling`` with a frequency. It is markedly slower than
        :meth:`offset`, because pandas walks day by day rather than indexing into a sorted
        array, so reach for it only when interoperability demands it.

        **The two disagree when the starting date is not a business day.** ``offset``
        normalises first and then moves ``n`` days, which is what ``numpy.busday_offset``
        does; ``CustomBusinessDay`` treats the normalisation as the move, so adding one
        business day to a Saturday lands on Monday rather than Tuesday. Neither is wrong,
        but they are not interchangeable — start from a business day, or use
        :meth:`offset` and be explicit about ``roll``.

        Returns:
            A ``CustomBusinessDay`` with this calendar's weekmask and holidays.

        Raises:
            ProviderError: If pandas is not installed.

        Examples:
            >>> offset = Calendar("weekday").to_pandas_offset()
            >>> type(offset).__name__
            'CustomBusinessDay'
        """
        pandas = require_pandas("to_pandas_offset()")
        return pandas.offsets.CustomBusinessDay(
            weekmask=self.weekmask, holidays=list(self.holidays)
        )

    # -- introspection ------------------------------------------------------

    def bdays_between(
        self, start: Any, end: Any, *, closed: str = "left", tz: str | None = None
    ) -> Any:
        """The business days between two dates, half-open ``[start, end)`` by default.

        Args:
            start: First date.
            end: Second date.
            closed: One of ``"left"``, ``"right"``, ``"both"``, ``"neither"`` (I10).
            tz: Timezone used to project aware inputs; defaults to :attr:`tz`.

        Returns:
            A ``DatetimeIndex``, or a ``datetime64[D]`` array if pandas is absent.

        Examples:
            >>> len(Calendar("weekday").bdays_between("2026-07-27", "2026-08-01"))
            5
        """
        start_side, end_side = _sides(closed)
        first = int(self._days(start, tz=tz)[0])
        last = int(self._days(end, tz=tz)[0])
        lo = int(np.searchsorted(self._good, first, side=start_side))
        hi = int(np.searchsorted(self._good, last, side=end_side))
        return _as_index(self._good[lo:hi])

    def holidays_between(self, start: Any, end: Any, *, closed: str = "left") -> Any:
        """The holidays between two dates, half-open ``[start, end)`` by default.

        Only dates that ``weekmask`` would otherwise have allowed are listed: a holiday
        falling on a Sunday in a Mon-Fri calendar is not a business day either way.

        Args:
            start: First date.
            end: Second date.
            closed: One of ``"left"``, ``"right"``, ``"both"``, ``"neither"`` (I10).

        Returns:
            A ``DatetimeIndex``, or a ``datetime64[D]`` array if pandas is absent.

        Examples:
            >>> cal = Calendar("acme", holidays=["2026-07-30"])
            >>> len(cal.holidays_between("2026-07-01", "2026-08-01"))
            1
        """
        first = int(self._days(start)[0])
        last = int(self._days(end)[0])
        days = datetime64_to_days(self.holidays)
        lower = first if closed in ("left", "both") else first + 1
        upper = last if closed in ("right", "both") else last - 1
        return _as_index(days[(days >= lower) & (days <= upper)])

    def sessions(self) -> Any:
        """Every business day inside :attr:`bounds`.

        Returns:
            A ``DatetimeIndex``, or a ``datetime64[D]`` array if pandas is absent.

        Examples:
            >>> cal = Calendar("weekday", bounds=(date(2026, 1, 1), date(2026, 1, 31)))
            >>> len(cal.sessions())
            22
        """
        return _as_index(self._good)

    def describe(self) -> dict[str, Any]:
        """A provenance and shape summary, suitable for logging or a CLI.

        Returns:
            A plain dict; every value is JSON-serialisable.

        Examples:
            >>> Calendar("weekday").describe()["weekmask"]
            'Mon Tue Wed Thu Fri'
        """
        return {
            "name": self.name,
            "weekmask": self.weekmask,
            "bounds": [self.bounds[0].isoformat(), self.bounds[1].isoformat()],
            "tz": self.tz,
            "session_start": self.session_start.isoformat(),
            "holidays": int(self.holidays.size),
            "business_days": int(self._good.size),
            "provider": self.provider,
            "provider_version": self.provider_version,
            "hash": self._key[-1],
        }

    # -- derivation ---------------------------------------------------------

    def with_holidays(
        self, extra: DateLike | DateSeqLike, *, name: str | None = None
    ) -> Calendar:
        """A new calendar with ``extra`` added to :attr:`holidays` (I1 — never mutate).

        Args:
            extra: Dates to close, as a scalar or sequence.
            name: Name for the derived calendar; defaults to ``"<name>+"``.

        Returns:
            A new :class:`Calendar`.

        Examples:
            >>> cal = Calendar("weekday").with_holidays(["2026-07-31"])
            >>> cal.is_bday("2026-07-31")
            False
        """
        added = np.atleast_1d(np.asarray(to_days(extra), dtype=np.int64))
        merged = np.union1d(datetime64_to_days(self.holidays), added)
        return self._derive(name or f"{self.name}+", days_to_datetime64(merged))

    def without_holidays(
        self, dates: DateLike | DateSeqLike, *, name: str | None = None
    ) -> Calendar:
        """A new calendar with ``dates`` removed from :attr:`holidays`.

        Args:
            dates: Dates to reopen, as a scalar or sequence.
            name: Name for the derived calendar; defaults to ``"<name>-"``.

        Returns:
            A new :class:`Calendar`.

        Examples:
            >>> cal = Calendar("acme", holidays=["2026-07-31"]).without_holidays("2026-07-31")
            >>> cal.is_bday("2026-07-31")
            True
        """
        removed = np.atleast_1d(np.asarray(to_days(dates), dtype=np.int64))
        kept = np.setdiff1d(datetime64_to_days(self.holidays), removed)
        return self._derive(name or f"{self.name}-", days_to_datetime64(kept))

    def _derive(self, name: str, holidays: NDArray[np.datetime64]) -> Calendar:
        return Calendar(
            name=name,
            holidays=holidays,
            weekmask=self.weekmask,
            bounds=self.bounds,
            tz=self.tz,
            session_start=self.session_start,
            provider=self.provider,
            provider_version=self.provider_version,
        )

    @classmethod
    def from_good_days(
        cls,
        name: str,
        good: NDArray[np.int64],
        *,
        bounds: tuple[date, date],
        tz: str | None = None,
        session_start: time = time(0, 0),
    ) -> Calendar:
        """Build a calendar from an explicit set of good days.

        Used by the algebra (§6), where the result's good set is arbitrary and cannot be
        expressed by merging weekmasks. The weekmask is inferred as "every weekday that
        occurs at least once", and everything it allows but the good set omits becomes a
        holiday — a faithful, if verbose, encoding of the same set.

        Args:
            name: Name for the resulting calendar.
            good: Sorted, unique epoch-day numbers of the business days.
            bounds: Inclusive horizon of the result.
            tz: Timezone, if the operands agreed on one.
            session_start: Session start, if the operands agreed on one.

        Returns:
            A :class:`Calendar` whose ``_good`` equals ``good``.

        Examples:
            >>> import numpy as np
            >>> cal = Calendar.from_good_days(
            ...     "just-mondays",
            ...     np.array([20668, 20675], dtype=np.int64),   # 3 and 10 August 2026
            ...     bounds=(date(2026, 8, 1), date(2026, 8, 31)),
            ... )
            >>> cal.weekmask, int(cal.holidays.size)           # the other Mondays close
            ('Mon', 3)
        """
        good = np.ascontiguousarray(np.unique(np.asarray(good, dtype=np.int64)))
        lo, hi = date_to_days(bounds[0]), date_to_days(bounds[1])
        if good.size:
            present = np.unique(weekday_of(good))
            weekmask = " ".join(_DAY_NAMES[int(index)] for index in present)
        else:
            weekmask = WEEKMASK_WEEKDAYS
        allowed = np.zeros(7, dtype=bool)
        for token in weekmask.split():
            allowed[_DAY_INDEX[token.lower()]] = True
        all_days = np.arange(lo, hi + 1, dtype=np.int64)
        candidates = all_days[allowed[weekday_of(all_days)]]
        holidays = np.setdiff1d(candidates, good, assume_unique=True)
        return cls(
            name=name,
            holidays=days_to_datetime64(holidays),
            weekmask=weekmask,
            bounds=bounds,
            tz=tz,
            session_start=session_start,
        )

    # -- algebra (implemented in calendars.algebra, see §6) -----------------

    def __and__(self, other: Calendar) -> Calendar:
        from better_calendar.calendars.algebra import all_open

        return all_open([self, other])

    def __or__(self, other: Calendar) -> Calendar:
        from better_calendar.calendars.algebra import any_open

        return any_open([self, other])

    def __sub__(self, other: Calendar) -> Calendar:
        from better_calendar.calendars.algebra import difference

        return difference(self, other)

    def __xor__(self, other: Calendar) -> Calendar:
        from better_calendar.calendars.algebra import symmetric_difference

        return symmetric_difference(self, other)

    @staticmethod
    def all_open(calendars: Sequence[Calendar]) -> Calendar:
        """Good in **every** calendar — the settlement case. Verbose alias for ``&``.

        Args:
            calendars: Two or more calendars.

        Returns:
            A calendar whose good days are good in all operands.

        Examples:
            >>> a = Calendar("a", holidays=["2026-07-30"])
            >>> b = Calendar("b", holidays=["2026-07-31"])
            >>> Calendar.all_open([a, b]).is_bday("2026-07-30")
            False
        """
        from better_calendar.calendars.algebra import all_open

        return all_open(calendars)

    @staticmethod
    def any_open(calendars: Sequence[Calendar]) -> Calendar:
        """Good in **at least one** calendar. Verbose alias for ``|``.

        Args:
            calendars: Two or more calendars.

        Returns:
            A calendar whose good days are good in any operand.

        Examples:
            >>> a = Calendar("a", holidays=["2026-07-30"])
            >>> b = Calendar("b", holidays=["2026-07-31"])
            >>> Calendar.any_open([a, b]).is_bday("2026-07-30")
            True
        """
        from better_calendar.calendars.algebra import any_open

        return any_open(calendars)


def _month_index(days: NDArray[np.int64]) -> NDArray[np.int64]:
    """Months since the epoch, so that "same month" is one integer comparison."""
    months = days_to_datetime64(np.ascontiguousarray(days)).astype("datetime64[M]")
    return np.ascontiguousarray(months).view(np.int64)


def _as_index(days: NDArray[np.int64]) -> Any:
    """Return day numbers as a ``DatetimeIndex``, degrading to numpy if pandas is absent."""
    values = days_to_datetime64(np.ascontiguousarray(days))
    pandas = optional_pandas()
    if pandas is None:  # pragma: no cover - depends on the environment
        return values
    return pandas.DatetimeIndex(values)
