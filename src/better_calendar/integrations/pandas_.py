"""pandas interoperability: the ``.cal`` accessor (§12).

Importing this module registers a ``.cal`` accessor on ``Series``, ``DatetimeIndex`` and
``Index``, so calendar work reads as method chaining::

    import better_calendar.integrations.pandas_   # registers .cal

    trades["settles"] = trades["traded"].cal.offset(2, cal="XNYS")
    trades[trades["traded"].cal.is_bday(cal="XNYS")]

This module is **not** imported by ``better_calendar`` (§14 — the package root must not
import pandas). Import it explicitly, once, wherever you set your process up.

The accessor is a thin wrapper: every method forwards to the identically named
:class:`~better_calendar.calendars.base.Calendar` method, which is where the vectorised
work happens. It exists for readability, not speed — ``cal.offset(series, 2)`` and
``series.cal.offset(2)`` do exactly the same thing.
"""

from __future__ import annotations

from typing import Any

from better_calendar.calendars.registry import CalendarLike, resolve
from better_calendar.core._pandas import require_pandas
from better_calendar.offsets.conventions import Roll, RollLike

__all__ = ["CalendarAccessor", "register_accessors"]


class CalendarAccessor:
    """The ``.cal`` accessor on a pandas ``Series`` or ``Index``.

    Args:
        obj: The container the accessor is attached to.

    Examples:
        >>> import pandas as pd
        >>> register_accessors()
        >>> dates = pd.Series(pd.DatetimeIndex(["2026-07-31", "2026-08-01"]))
        >>> list(dates.cal.is_bday())
        [True, False]
        >>> list(dates.cal.offset(1).dt.strftime("%Y-%m-%d"))
        ['2026-08-03', '2026-08-04']
    """

    def __init__(self, obj: Any) -> None:
        self._obj = obj

    def is_bday(self, cal: CalendarLike = None, *, tz: str | None = None) -> Any:
        """Whether each value is a business day.

        Args:
            cal: A calendar, an identifier, or ``None`` for ``weekday``.
            tz: Timezone used to project aware values.

        Returns:
            A boolean container of the same shape.

        Examples:
            >>> import pandas as pd
            >>> register_accessors()
            >>> pd.DatetimeIndex(["2026-08-01"]).cal.is_bday().tolist()
            [False]
        """
        return self._wrap(resolve(cal).is_bday(self._obj, tz=tz))

    def offset(
        self,
        n: int,
        cal: CalendarLike = None,
        *,
        roll: RollLike = Roll.FOLLOWING,
        tz: str | None = None,
    ) -> Any:
        """Move every value ``n`` business days.

        Args:
            n: Number of business days; may be negative.
            cal: A calendar, an identifier, or ``None`` for ``weekday``.
            roll: How to normalise a non-business day before moving.
            tz: Timezone used to project aware values.

        Returns:
            A container of the same kind.

        Examples:
            >>> import pandas as pd
            >>> register_accessors()
            >>> list(pd.DatetimeIndex(["2026-07-31"]).cal.offset(1).strftime("%Y-%m-%d"))
            ['2026-08-03']
        """
        return self._wrap(resolve(cal).offset(self._obj, n, roll=roll, tz=tz))

    def adjust(
        self,
        roll: RollLike = Roll.FOLLOWING,
        cal: CalendarLike = None,
        *,
        tz: str | None = None,
    ) -> Any:
        """Move every value to a nearby business day per a roll convention.

        Args:
            roll: A :class:`~better_calendar.offsets.conventions.Roll` or short alias.
            cal: A calendar, an identifier, or ``None`` for ``weekday``.
            tz: Timezone used to project aware values.

        Returns:
            A container of the same kind.

        Examples:
            >>> import pandas as pd
            >>> register_accessors()
            >>> index = pd.DatetimeIndex(["2026-05-31"])
            >>> list(index.cal.adjust("MF").strftime("%Y-%m-%d"))
            ['2026-05-29']
        """
        return self._wrap(resolve(cal).adjust(self._obj, roll, tz=tz))

    def add_tenor(
        self,
        tenor: str,
        cal: CalendarLike = None,
        *,
        roll: RollLike = Roll.NONE,
        eom: bool = False,
        tz: str | None = None,
    ) -> Any:
        """Add a tenor expression to every value.

        Args:
            tenor: An expression such as ``"3M"`` or ``"1Y+2B"``.
            cal: A calendar, an identifier, or ``None`` for ``weekday``.
            roll: How to adjust the final result.
            eom: Apply the end-of-month rule to month and year terms.
            tz: Timezone used to project aware values.

        Returns:
            A container of the same kind.

        Examples:
            >>> import pandas as pd
            >>> register_accessors()
            >>> index = pd.DatetimeIndex(["2026-01-31"])
            >>> list(index.cal.add_tenor("1M").strftime("%Y-%m-%d"))
            ['2026-02-28']
        """
        return self._wrap(resolve(cal).add_tenor(self._obj, tenor, roll=roll, eom=eom, tz=tz))

    def count_to(
        self,
        end: Any,
        cal: CalendarLike = None,
        *,
        closed: str = "left",
        tz: str | None = None,
    ) -> Any:
        """Business days from each value to ``end``, half-open by default.

        Args:
            end: The other endpoint, scalar or aligned container.
            cal: A calendar, an identifier, or ``None`` for ``weekday``.
            closed: One of ``"left"``, ``"right"``, ``"both"``, ``"neither"``.
            tz: Timezone used to project aware values.

        Returns:
            An integer container of the same shape.

        Examples:
            >>> import pandas as pd
            >>> register_accessors()
            >>> pd.DatetimeIndex(["2026-07-27"]).cal.count_to("2026-08-01").tolist()
            [5]
        """
        return self._wrap(resolve(cal).count(self._obj, end, closed=closed, tz=tz))

    def _wrap(self, result: Any) -> Any:
        """Put a plain result back into the container the accessor was called on.

        Date-valued results already arrive as a ``DatetimeIndex`` (I6), and boolean or
        integer ones as numpy arrays; either way an ``Index`` caller wants them as they
        are, and a ``Series`` caller wants its own index and name back.
        """
        pandas = require_pandas("the .cal accessor")
        if isinstance(self._obj, pandas.Series):
            return pandas.Series(result, index=self._obj.index, name=self._obj.name)
        return result


def register_accessors() -> None:
    """Register ``.cal`` on ``Series`` and ``Index``. Idempotent.

    Called automatically when this module is imported; exposed so that a caller who
    imported it for something else can be explicit.

    Examples:
        >>> register_accessors()
        >>> register_accessors()          # registering twice is harmless
    """
    pandas = require_pandas("the .cal accessor")
    import warnings

    with warnings.catch_warnings():
        # pandas warns when an accessor name is re-registered, which is exactly what
        # idempotence means here.
        warnings.simplefilter("ignore")
        pandas.api.extensions.register_series_accessor("cal")(CalendarAccessor)
        pandas.api.extensions.register_index_accessor("cal")(CalendarAccessor)


register_accessors()
