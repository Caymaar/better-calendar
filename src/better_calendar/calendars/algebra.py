"""Calendar set operations (§6).

**Read this before touching anything here.** "Union of two calendars" means opposite
things depending on whether the speaker is thinking in *business days* or in *holidays*,
and getting it backwards produces settlement dates that are wrong by a day and look
plausible. This library resolves the ambiguity by naming every operation after **business
days**, never after holidays (I9).

Worked example. Let ``XNYS`` be closed on 2026-07-03 (US Independence Day observed) and
``fin:TARGET2`` be open that day; let ``fin:TARGET2`` be closed on 2026-04-06 (Easter
Monday) and ``XNYS`` be open.

===========================  ===================  ==============================
Expression                   2026-07-03 is        2026-04-06 is
===========================  ===================  ==============================
``XNYS & TARGET2``           **not** a good day   **not** a good day
``XNYS | TARGET2``           a good day           a good day
``XNYS - TARGET2``           not a good day       a good day
``XNYS ^ TARGET2``           a good day           a good day
===========================  ===================  ==============================

So ``a & b`` — good in *both* — is the **union of the two holiday sets**. That is the
common settlement case: a cash flow between New York and the euro area can only move on a
day both centres are open. Someone describing that as "the union of the calendars" is
thinking in holidays, and would reach for ``|``. Hence the verbose aliases
:func:`all_open` and :func:`any_open`, which read unambiguously in a code review.

Implementation is numpy set algebra on the good-day arrays. It must stay that way:
merging weekmask strings and holiday lists gives the wrong answer as soon as the operands
disagree on the weekend (a Sun-Thu Gulf calendar against a Mon-Fri one), whereas set
operations on good days handle it for free.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import time

import numpy as np
from numpy.typing import NDArray

from better_calendar.calendars.base import Calendar
from better_calendar.core.errors import BetterCalendarError

__all__ = ["all_open", "any_open", "difference", "symmetric_difference"]


def _operands(calendars: Sequence[Calendar], operation: str) -> list[Calendar]:
    items = list(calendars)
    if len(items) < 2:
        raise BetterCalendarError(
            f"{operation} needs at least two calendars, got {len(items)}. "
            f"Pass the operands as a sequence, for example {operation}([a, b])."
        )
    return items


def _common_bounds(calendars: Sequence[Calendar], name: str) -> tuple[object, object]:
    """Intersection of the operands' horizons — a composite cannot answer beyond them."""
    first = max(cal.bounds[0] for cal in calendars)
    last = min(cal.bounds[1] for cal in calendars)
    if last < first:
        raise BetterCalendarError(
            f"Cannot build {name}: the operands' bounds do not overlap "
            f"({', '.join(f'{c.name} {c.bounds[0]}..{c.bounds[1]}' for c in calendars)}). "
            f"Rebuild them over a common horizon first."
        )
    return first, last


def _common_tz(calendars: Sequence[Calendar]) -> str | None:
    """A composite keeps a timezone only if every operand agrees on it (§6).

    Otherwise it has no meaningful instant semantics, and ``session_of`` on it must fail
    loudly rather than pick one arbitrarily.
    """
    zones = {cal.tz for cal in calendars}
    return zones.pop() if len(zones) == 1 else None


def _common_session_start(calendars: Sequence[Calendar]) -> time:
    starts = {cal.session_start for cal in calendars}
    return starts.pop() if len(starts) == 1 else time(0, 0)


def _clip(cal: Calendar, lo: object, hi: object) -> NDArray[np.int64]:
    """The operand's good days restricted to the composite's horizon."""
    return cal.good_days(lo, hi)  # type: ignore[arg-type]  # dates, built by _common_bounds


def _combine(
    calendars: Sequence[Calendar],
    good: NDArray[np.int64],
    name: str,
    bounds: tuple[object, object],
) -> Calendar:
    return Calendar.from_good_days(
        name,
        good,
        bounds=bounds,  # type: ignore[arg-type]  # dates, built by _common_bounds
        tz=_common_tz(calendars),
        session_start=_common_session_start(calendars),
    )


def all_open(calendars: Sequence[Calendar]) -> Calendar:
    """Good in **every** operand. Equivalent to ``a & b``; the settlement case.

    Args:
        calendars: Two or more calendars.

    Returns:
        A composite whose good days are good in all operands, with bounds equal to the
        intersection of theirs and a deterministic derived name.

    Examples:
        >>> a = Calendar("a", holidays=["2026-07-30"])
        >>> b = Calendar("b", holidays=["2026-07-31"])
        >>> composite = all_open([a, b])
        >>> composite.name
        '(a & b)'
        >>> composite.is_bday("2026-07-30"), composite.is_bday("2026-07-29")
        (False, True)
    """
    items = _operands(calendars, "all_open")
    name = "(" + " & ".join(cal.name for cal in items) + ")"
    bounds = _common_bounds(items, name)
    good = _clip(items[0], *bounds)
    for cal in items[1:]:
        good = np.intersect1d(good, _clip(cal, *bounds), assume_unique=True)
    return _combine(items, good, name, bounds)


def any_open(calendars: Sequence[Calendar]) -> Calendar:
    """Good in **at least one** operand. Equivalent to ``a | b``.

    Args:
        calendars: Two or more calendars.

    Returns:
        A composite whose good days are good in any operand.

    Examples:
        >>> a = Calendar("a", holidays=["2026-07-30"])
        >>> b = Calendar("b", holidays=["2026-07-31"])
        >>> any_open([a, b]).is_bday("2026-07-30")
        True
    """
    items = _operands(calendars, "any_open")
    name = "(" + " | ".join(cal.name for cal in items) + ")"
    bounds = _common_bounds(items, name)
    good = _clip(items[0], *bounds)
    for cal in items[1:]:
        good = np.union1d(good, _clip(cal, *bounds))
    return _combine(items, good, name, bounds)


def difference(left: Calendar, right: Calendar) -> Calendar:
    """Good in ``left`` but **not** in ``right``. Equivalent to ``a - b``.

    Args:
        left: The calendar to keep good days from.
        right: The calendar whose good days are removed.

    Returns:
        A composite of the remaining days.

    Examples:
        >>> a = Calendar("a")
        >>> b = Calendar("b", holidays=["2026-07-31"])
        >>> only = difference(a, b).sessions()   # the one day a is open and b is not
        >>> len(only), only[0].strftime("%Y-%m-%d")
        (1, '2026-07-31')
    """
    name = f"({left.name} - {right.name})"
    bounds = _common_bounds([left, right], name)
    good = np.setdiff1d(_clip(left, *bounds), _clip(right, *bounds), assume_unique=True)
    return _combine([left, right], good, name, bounds)


def symmetric_difference(left: Calendar, right: Calendar) -> Calendar:
    """Good in **exactly one** of the two. Equivalent to ``a ^ b``.

    Args:
        left: First calendar.
        right: Second calendar.

    Returns:
        A composite of the days good in one operand but not the other.

    Examples:
        >>> a = Calendar("a", holidays=["2026-07-30"])
        >>> b = Calendar("b", holidays=["2026-07-31"])
        >>> composite = symmetric_difference(a, b)
        >>> composite.is_bday("2026-07-30"), composite.is_bday("2026-07-29")
        (True, False)
    """
    name = f"({left.name} ^ {right.name})"
    bounds = _common_bounds([left, right], name)
    good = np.setxor1d(_clip(left, *bounds), _clip(right, *bounds), assume_unique=True)
    return _combine([left, right], good, name, bounds)
