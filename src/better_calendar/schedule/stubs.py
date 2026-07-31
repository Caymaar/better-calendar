"""Stub handling for coupon schedules (§8.1).

A schedule rarely divides evenly. Six-monthly coupons between 15 March 2026 and 15 January
2030 leave ten months over, and the *stub* is what you do with the remainder:

===============  ==========================================================
``short_front``  an extra, shorter first period. The default, and the common
                 market convention.
``long_front``   the remainder is absorbed into the first regular period,
                 making it longer than the rest.
``short_back``   an extra, shorter final period.
``long_back``    the remainder is absorbed into the last regular period.
``none``         refuse: the term must be a whole number of periods, and it
                 is an error if it is not.
===============  ==========================================================

Which end the regular periods are measured from follows from the choice: a *front* stub
means the regular grid is anchored on the **end** date and generated backwards, a *back*
stub anchors on the **start** and generates forwards. That is what makes coupon dates land
on the maturity date rather than drifting away from it.

Everything here is pure date arithmetic. No calendar is consulted, deliberately — see
:class:`~better_calendar.schedule.schedule.Schedule` for why that separation matters.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from better_calendar.core._freq import Freq, parse_freq
from better_calendar.core.epoch import add_months, date_to_days, days_to_date
from better_calendar.core.errors import ScheduleError

__all__ = ["STUBS", "Stub", "unadjusted_dates"]

Stub = str

#: The stub conventions, in the order §8.1 lists them.
STUBS: tuple[str, ...] = ("short_front", "long_front", "short_back", "long_back", "none")

_MONTHS_PER_UNIT = {"M": 1, "Q": 3, "Y": 12}
_DAYS_PER_UNIT = {"D": 1, "W": 7}


def _step(anchor: date, freq: Freq, steps: int, *, eom: bool) -> date:
    """``anchor`` advanced by ``steps`` whole periods.

    Always measured from the anchor rather than from the previous date. Stepping
    iteratively would let 31 January drift to 28 February and then stay on the 28th
    forever; measuring from the anchor keeps every date on the 31st where the month allows.
    """
    if freq.unit in _MONTHS_PER_UNIT:
        months = freq.multiple * _MONTHS_PER_UNIT[freq.unit] * steps
        source = np.array([date_to_days(anchor)], dtype=np.int64)
        return days_to_date(int(add_months(source, months, end_of_month=eom)[0]))
    return anchor + timedelta(days=freq.multiple * _DAYS_PER_UNIT[freq.unit] * steps)


def unadjusted_dates(
    start: date, end: date, freq: str, *, stub: Stub = "short_front", eom: bool = False
) -> list[date]:
    """The unadjusted schedule dates from ``start`` to ``end``, inclusive of both.

    Pure calendar arithmetic: no business days, no holidays, no roll convention. The
    result is reproducible from these arguments alone, which is the point.

    Args:
        start: First date of the schedule.
        end: Last date of the schedule.
        freq: Period length, such as ``"6M"`` or ``"3M"``.
        stub: One of :data:`STUBS`.
        eom: Apply the end-of-month rule when stepping by months or years.

    Returns:
        The schedule dates, ascending, always beginning at ``start`` and ending at ``end``.

    Raises:
        ScheduleError: If ``stub`` is unknown, if the dates are the wrong way round, or if
            ``stub="none"`` and the term is not a whole number of periods.

    Examples:
        >>> from datetime import date
        >>> def show(*args, **kwargs):
        ...     return [d.isoformat() for d in unadjusted_dates(*args, **kwargs)]
        >>> show(date(2026, 1, 15), date(2027, 1, 15), "6M")
        ['2026-01-15', '2026-07-15', '2027-01-15']
        >>> # A five-month term at a quarterly frequency leaves two months over.
        >>> show(date(2026, 1, 15), date(2026, 6, 15), "3M")
        ['2026-01-15', '2026-03-15', '2026-06-15']
        >>> show(date(2026, 1, 15), date(2026, 6, 15), "3M", stub="short_back")
        ['2026-01-15', '2026-04-15', '2026-06-15']
    """
    if stub not in STUBS:
        raise ScheduleError(f"Unknown stub convention {stub!r}. Use one of {', '.join(STUBS)}.")
    if end < start:
        raise ScheduleError(
            f"The schedule ends {end.isoformat()} before it starts {start.isoformat()}. "
            f"Pass the earlier date as `start`."
        )
    if end == start:
        return [start]

    parsed = parse_freq(freq)
    if stub in ("short_front", "long_front", "none"):
        regular = _generate_backwards(start, end, parsed, eom=eom)
    else:
        regular = _generate_forwards(start, end, parsed, eom=eom)

    exact = regular and regular[0] == start and regular[-1] == end
    if stub == "none":
        if not exact:
            raise ScheduleError(
                f"{start.isoformat()} to {end.isoformat()} is not a whole number of "
                f"{freq} periods, and stub='none' forbids a stub. Choose a stub "
                f"convention, or move one of the dates."
            )
        return regular
    if exact:
        return regular
    return _attach_stub(start, end, regular, stub)


def _generate_backwards(start: date, end: date, freq: Freq, *, eom: bool) -> list[date]:
    """Regular dates measured back from ``end``, stopping once they reach ``start``."""
    dates = [end]
    step = 1
    while True:
        moment = _step(end, freq, -step, eom=eom)
        if moment < start:
            break
        dates.append(moment)
        if moment == start:
            break
        step += 1
    dates.reverse()
    return dates


def _generate_forwards(start: date, end: date, freq: Freq, *, eom: bool) -> list[date]:
    """Regular dates measured forward from ``start``, stopping once they reach ``end``."""
    dates = [start]
    step = 1
    while True:
        moment = _step(start, freq, step, eom=eom)
        if moment > end:
            break
        dates.append(moment)
        if moment == end:
            break
        step += 1
    return dates


def _attach_stub(start: date, end: date, regular: list[date], stub: Stub) -> list[date]:
    """Fold the leftover period into the schedule according to ``stub``."""
    if stub == "short_front":
        return [start, *regular]
    if stub == "long_front":
        # Absorb the remainder into the first regular period by dropping its opening date.
        # With only one regular date there is nothing to absorb into but the term itself.
        return [start, *regular[1:]] if len(regular) > 1 else [start, end]
    if stub == "short_back":
        return [*regular, end]
    return [*regular[:-1], end] if len(regular) > 1 else [start, end]
