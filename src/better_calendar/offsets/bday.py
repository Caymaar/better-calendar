"""A pandas-like business-day offset object (§7.2).

``some_date + BDay(3)`` reads well and works on every input type the library accepts,
because Python falls through to :meth:`BDay.__radd__` for any left operand that does not
know what a ``BDay`` is.

Containers are the awkward part, and §7.2 flags it. When you write ``series + BDay(3)``,
pandas does *not* hand us the Series: it unwraps to the underlying ``DatetimeArray``,
calls our ``__radd__`` with that, and then tries to rebuild a Series from whatever comes
back — so the return value has to be something pandas can wrap, and it must carry the
timezone if the input had one. numpy is worse: without ``__array_ufunc__ = None`` it would
try to broadcast the offset elementwise and fail inside the ufunc machinery. Both are
handled here, and both are tested.

``cal.offset(series, 3)`` remains the recommended form. It is the same answer by a
shorter path, with no operator dispatch to reason about, and it is what you want in a hot
loop. ``BDay`` is for the places where an offset *object* is what reads best — a default
argument, a configuration value, something multiplied by a quantity.

For pandas machinery that demands a genuine ``DateOffset`` (``date_range``, ``resample``),
use :meth:`~better_calendar.calendars.base.Calendar.to_pandas_offset` instead; ``BDay`` is
deliberately not a ``DateOffset`` subclass.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from better_calendar._compat import DATACLASS_SLOTS
from better_calendar.calendars.registry import CalendarLike, resolve
from better_calendar.offsets.conventions import Roll, RollLike

__all__ = ["BDay"]


@dataclass(frozen=True, **DATACLASS_SLOTS)
class BDay:
    """An offset of ``n`` business days in a given calendar.

    Attributes:
        n: How many business days to move; may be negative or zero.
        cal: A calendar, an identifier resolved through the registry, or ``None`` for the
            default ``weekday`` calendar.
        roll: How to normalise a non-business day before moving, matching
            :meth:`~better_calendar.calendars.base.Calendar.offset`.

    Examples:
        >>> from datetime import date
        >>> date(2026, 7, 31) + BDay(1)            # Friday to Monday
        datetime.date(2026, 8, 3)
        >>> date(2026, 8, 3) - BDay(1)
        datetime.date(2026, 7, 31)
        >>> "2026-07-31" + BDay(5, cal="XNYS")     # skips Independence Day
        '2026-08-07'
        >>> BDay(1) * 3
        BDay(n=3, cal=None, roll=<Roll.FOLLOWING: 'following'>)
        >>> -BDay(2)
        BDay(n=-2, cal=None, roll=<Roll.FOLLOWING: 'following'>)
    """

    n: int = 1
    cal: CalendarLike = None
    roll: RollLike = Roll.FOLLOWING

    # numpy would otherwise try to broadcast this object into its ufunc machinery and
    # fail; opting out sends `ndarray + BDay(n)` to __radd__ instead. The priority keeps
    # us ahead of numpy for the same reason.
    __array_ufunc__ = None
    __array_priority__ = 1000

    def _shift(self, other: Any, sign: int) -> Any:
        return resolve(self.cal).offset(other, sign * self.n, roll=self.roll)

    def __radd__(self, other: Any) -> Any:
        return self._shift(other, 1)

    def __add__(self, other: Any) -> Any:
        return self._shift(other, 1)

    def __rsub__(self, other: Any) -> Any:
        return self._shift(other, -1)

    def __mul__(self, factor: int) -> BDay:
        return BDay(self.n * int(factor), self.cal, self.roll)

    def __rmul__(self, factor: int) -> BDay:
        return self.__mul__(factor)

    def __neg__(self) -> BDay:
        return BDay(-self.n, self.cal, self.roll)
