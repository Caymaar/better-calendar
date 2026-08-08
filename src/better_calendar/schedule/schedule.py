"""The one recurrence engine (§8).

Every dated rule this library generates is the same two decisions:

1. **how to cut** the window into periods — the ``every`` argument;
2. **what to take** from each period — the ``on`` argument.

:func:`schedule` is those two decisions and nothing else. The named helpers in
:mod:`~better_calendar.schedule.recurrence` and
:mod:`~better_calendar.schedule.generators` are one-line spellings of it::

    schedule(a, b, "M", "last FRI")                       # last Friday of each month
    schedule(a, b, "Q", "2 THU")                          # second Thursday of each quarter
    schedule(a, b, "M", "last B", cal="XNYS")             # last trading day of each month
    schedule(a, b, "M", "3 WED", months=(3, 6, 9, 12))    # IMM dates
    schedule(a, b, "6M", "edges", cal="XNYS", roll="MF")  # a coupon schedule

**Business days and calendar days are two independent axes**, and conflating them is
where the mistakes live:

* ``on="last B"`` *counts* business days — the last trading day of the month;
* ``roll=`` *moves* a result onto a business day — the last calendar day, pulled back.

They agree more often than not, which is exactly why the difference has to be written
down rather than inferred.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

import numpy as np
from numpy.typing import NDArray

from better_calendar.calendars.registry import CalendarLike, resolve
from better_calendar.core.epoch import date_to_days, days_to_date, weekday_of
from better_calendar.core.errors import BetterCalendarError, ScheduleError
from better_calendar.core.range import DateRange
from better_calendar.core.types import DateLike, days_to_index, to_date
from better_calendar.offsets.conventions import Roll, RollLike
from better_calendar.schedule._periods import month_of, period_bounds
from better_calendar.schedule.selector import Edges, Nth, SelectorLike, Unit, as_selector
from better_calendar.schedule.stubs import Stub, unadjusted_dates

__all__ = ["MISSING", "periods", "schedule"]

#: What to do when a period has no such occurrence — no fifth Friday, no thirty-first day.
MISSING = ("skip", "clamp", "raise")


def schedule(
    start: DateLike,
    end: DateLike,
    every: str = "M",
    on: SelectorLike | Sequence[SelectorLike] = "last",
    *,
    cal: CalendarLike = None,
    roll: RollLike = Roll.NONE,
    months: Iterable[int] | None = None,
    anchor_month: int | None = None,
    stub: Stub = "short_front",
    eom: bool = False,
    missing: str = "skip",
) -> Any:
    """Generate dates by cutting ``[start, end]`` into periods and picking from each.

    Args:
        start: First day of the window.
        end: Last day of the window, inclusive.
        every: How to cut. ``"D"``, ``"W"``, ``"M"``, ``"Q"``, ``"Y"``, or a multiple such
            as ``"3M"``. A bare unit aligns to the calendar; a multiple aligns to
            ``start``, so ``"Q"`` and ``"3M"`` are both three months and deliberately
            different.
        on: What to take. A selector string (``"last"``, ``"1st B"``, ``"2 THU"``,
            ``"edges"``), an :class:`~better_calendar.schedule.selector.Nth`, or a list of
            either — a list produces every match, sorted and de-duplicated.
        cal: The calendar. Needed by ``B`` selectors and by ``roll``; ``None`` means the
            plain Mon-Fri ``weekday`` calendar.
        roll: How to move each result onto a business day. ``Roll.NONE`` by default,
            because a recurrence is a calendar fact before it is a trading date.
        months: Restrict to periods starting in these calendar months. This is what makes
            IMM dates expressible: the third Wednesday, but only in March, June,
            September and December.
        anchor_month: The calendar month a ``"Q"`` or ``"Y"`` period ends in, for a fiscal
            year that is not the calendar one.
        stub: Only for ``on="edges"``. How to place a term that is not a whole number of
            periods; see :mod:`~better_calendar.schedule.stubs`.
        eom: Apply the end-of-month rule when stepping by months or years. Only for
            ``on="edges"``.
        missing: What to do when a period has no such occurrence — most Februaries have no
            fifth Friday, and no month has a thirty-second day. ``"skip"`` drops the
            period, ``"clamp"`` takes the nearest occurrence that does exist, ``"raise"``
            refuses.

    Returns:
        A ``DatetimeIndex`` (or a ``datetime64[D]`` array without pandas), sorted and
        clipped to ``[start, end]``.

    Raises:
        ScheduleError: On an unusable selector, stub or ``missing`` value, or on an option
            that does not apply to the selector in use.
        BetterCalendarError: If the window is inverted.

    Examples:
        >>> def show(index):
        ...     return list(index.strftime("%Y-%m-%d"))
        >>> show(schedule("2026-01-01", "2026-03-31", "M", "last FRI"))
        ['2026-01-30', '2026-02-27', '2026-03-27']
        >>> show(schedule("2026-01-01", "2026-12-31", "Q", "2 THU"))
        ['2026-01-08', '2026-04-09', '2026-07-09', '2026-10-08']
        >>> show(schedule("2026-01-01", "2026-03-31", "M", "last B", cal="XNYS"))
        ['2026-01-30', '2026-02-27', '2026-03-31']
        >>> # The thirty-first of each month, or the last day where there is none.
        >>> show(schedule("2026-01-01", "2026-04-30", "M", "31", missing="clamp"))
        ['2026-01-31', '2026-02-28', '2026-03-31', '2026-04-30']
        >>> # Two selectors at once.
        >>> show(schedule("2026-01-01", "2026-02-28", "M", ["1", "15"]))
        ['2026-01-01', '2026-01-15', '2026-02-01', '2026-02-15']
        >>> # A coupon schedule: the boundaries, with a stub and a roll convention.
        >>> show(schedule("2026-01-15", "2027-01-15", "6M", "edges", cal="XNYS", roll="MF"))
        ['2026-01-15', '2026-07-15', '2027-01-15']
    """
    if missing not in MISSING:
        raise ScheduleError(
            f"Unknown missing-occurrence policy {missing!r}. Use one of "
            f"{', '.join(repr(item) for item in MISSING)}."
        )
    window = _window(start, end)
    selectors = [as_selector(item) for item in _as_list(on)]

    if any(isinstance(item, Edges) for item in selectors):
        if len(selectors) > 1:
            raise ScheduleError(
                "on='edges' selects the period boundaries, so it cannot be combined with "
                "selectors that pick a day inside a period."
            )
        if months is not None:
            raise ScheduleError(
                "months= restricts which periods contribute a date, which has no meaning "
                "for on='edges': the boundaries span the whole term. Drop one of the two."
            )
        return _edges(window, every, cal, roll, stub=stub, eom=eom)

    calendar = resolve(cal)
    starts, ends = period_bounds(*window, every, anchor_month=anchor_month)
    if months is not None:
        keep = np.isin(month_of(starts), np.asarray(list(months), dtype=np.int64))
        starts, ends = starts[keep], ends[keep]

    found: list[NDArray[np.int64]] = []
    for selector in selectors:
        days, valid = _select(calendar, starts, ends, selector, missing)
        found.append(days[valid])
    collected = np.concatenate(found) if found else np.empty(0, dtype=np.int64)
    return _finish(collected, window, calendar, roll)


def periods(
    start: DateLike,
    end: DateLike,
    every: str = "M",
    on: SelectorLike | Sequence[SelectorLike] = "edges",
    **kwargs: Any,
) -> list[DateRange]:
    """The intervals between consecutive dates of :func:`schedule`.

    Half-open ``[start, end)``, so consecutive intervals tile without counting the
    boundary day twice (I10).

    Args:
        start: First day of the window.
        end: Last day of the window, inclusive.
        every: How to cut, as in :func:`schedule`.
        on: What to take, defaulting to the period boundaries.
        **kwargs: Anything :func:`schedule` accepts.

    Returns:
        One :class:`~better_calendar.core.range.DateRange` per interval.

    Examples:
        >>> [(str(p.start), str(p.end)) for p in periods("2026-01-15", "2027-01-15", "6M")]
        [('2026-01-15', '2026-07-15'), ('2026-07-15', '2027-01-15')]
        >>> len(periods("2026-01-01", "2026-12-31", "M", "last"))
        11
    """
    boundaries = [to_date(value) for value in schedule(start, end, every, on, **kwargs)]
    return [DateRange(first, second) for first, second in zip(boundaries, boundaries[1:])]


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _as_list(on: SelectorLike | Sequence[SelectorLike]) -> list[SelectorLike]:
    if isinstance(on, (str, Nth, Edges)):
        return [on]
    return list(on)


def _window(start: DateLike, end: DateLike) -> tuple[date, date]:
    first, last = to_date(start), to_date(end)
    if last < first:
        raise BetterCalendarError(
            f"The window ends {last.isoformat()} before it starts {first.isoformat()}. "
            f"Pass the earlier date first."
        )
    return first, last


def _edges(
    window: tuple[date, date],
    every: str,
    cal: CalendarLike,
    roll: RollLike,
    *,
    stub: Stub,
    eom: bool,
) -> Any:
    """The boundary selector: a coupon schedule rather than one date per period."""
    days = np.array(
        [date_to_days(day) for day in unadjusted_dates(*window, every, stub=stub, eom=eom)],
        dtype=np.int64,
    )
    parsed = Roll.parse(roll)
    if parsed is not Roll.NONE and days.size:
        days = np.asarray(resolve(cal)._adjust_days(days, parsed), dtype=np.int64)
    return days_to_index(days)


def _select(
    calendar: Any,
    starts: NDArray[np.int64],
    ends: NDArray[np.int64],
    selector: Nth | Edges,
    missing: str,
) -> tuple[NDArray[np.int64], NDArray[np.bool_]]:
    """One candidate day per period, plus whether that occurrence actually exists."""
    assert isinstance(selector, Nth)  # `edges` is handled before we get here
    if selector.unit is Unit.BUSINESS:
        return _select_business(calendar, starts, ends, selector.n, missing)
    if selector.unit is Unit.WEEKDAY:
        return _select_weekday(starts, ends, selector, missing)
    return _select_day(starts, ends, selector.n, missing)


def _resolve_missing(
    found: NDArray[np.int64],
    valid: NDArray[np.bool_],
    clamped: NDArray[np.int64],
    missing: str,
    what: str,
    starts: NDArray[np.int64],
) -> tuple[NDArray[np.int64], NDArray[np.bool_]]:
    """Apply the missing-occurrence policy to one selector's candidates."""
    if missing == "skip" or bool(valid.all()):
        return found, valid
    if missing == "clamp":
        return np.where(valid, found, clamped), np.ones_like(valid)
    offender = days_to_date(int(starts[~valid][0]))
    raise ScheduleError(
        f"The period starting {offender.isoformat()} has no {what}, and missing='raise' "
        f"forbids skipping it. Use missing='skip' to drop such periods, or "
        f"missing='clamp' to take the nearest occurrence that does exist."
    )


def _select_day(
    starts: NDArray[np.int64], ends: NDArray[np.int64], n: int, missing: str
) -> tuple[NDArray[np.int64], NDArray[np.bool_]]:
    found = starts + (n - 1) if n > 0 else ends + (n + 1)
    valid = (found >= starts) & (found <= ends)
    return _resolve_missing(
        found, valid, np.clip(found, starts, ends), missing, f"day {n}", starts
    )


def _select_weekday(
    starts: NDArray[np.int64],
    ends: NDArray[np.int64],
    selector: Nth,
    missing: str,
) -> tuple[NDArray[np.int64], NDArray[np.bool_]]:
    target = int(selector.weekday or 0)
    first = starts + (target - weekday_of(starts)) % 7
    last = ends - (weekday_of(ends) - target) % 7
    found = first + 7 * (selector.n - 1) if selector.n > 0 else last + 7 * (selector.n + 1)
    valid = (found >= starts) & (found <= ends)
    # Clamping a weekday means the nearest occurrence that does exist: the last one when
    # you asked for a fifth Friday in a four-Friday month, the first when counting back.
    clamped = np.where(found > ends, last, np.where(found < starts, first, found))
    return _resolve_missing(found, valid, clamped, missing, str(selector), starts)


def _select_business(
    calendar: Any,
    starts: NDArray[np.int64],
    ends: NDArray[np.int64],
    n: int,
    missing: str,
) -> tuple[NDArray[np.int64], NDArray[np.bool_]]:
    good = calendar.good_days()
    low = np.searchsorted(good, starts, side="left")
    high = np.searchsorted(good, ends, side="right")
    index = low + (n - 1) if n > 0 else high + n

    has_any = high > low
    valid = has_any & (index >= low) & (index < high)
    limit = max(good.size - 1, 0)
    found = np.where(valid, good[np.clip(index, 0, limit)], 0)

    # A period holding no business day at all cannot be clamped into one.
    clamped_index = np.clip(index, low, np.maximum(high - 1, low))
    clamped = np.where(has_any, good[np.clip(clamped_index, 0, limit)], 0)
    days, resolved = _resolve_missing(
        found, valid, clamped, missing, f"business day {n}", starts
    )
    return days, resolved & has_any


def _finish(
    days: NDArray[np.int64],
    window: tuple[date, date],
    calendar: Any,
    roll: RollLike,
) -> Any:
    """Adjust, clip to the window, sort and de-duplicate."""
    found = np.asarray(days, dtype=np.int64)
    parsed = Roll.parse(roll)
    if parsed is not Roll.NONE and found.size:
        found = np.atleast_1d(np.asarray(calendar._adjust_days(found, parsed), dtype=np.int64))
    low, high = date_to_days(window[0]), date_to_days(window[1])
    return days_to_index(np.unique(found[(found >= low) & (found <= high)]))
