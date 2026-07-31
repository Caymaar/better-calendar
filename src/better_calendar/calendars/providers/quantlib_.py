"""Settlement and risk-free-rate calendars from ``QuantLib`` (§5.3).

QuantLib is the reference for *settlement* calendars — when money can actually move
between two centres — and it distinguishes markets that other sources collapse: in the
United States alone, the Federal Reserve, the government bond market (SIFMA, which is
what SOFR follows), the NYSE and plain settlement are four different calendars with four
different holiday lists.

Calendars are exposed twice. Every class-and-market pair is reachable under ``ql:``, and
the ones with a name people actually use get it from ``quantlib_map.toml``: ``fin:NYB``,
``rate:SOFR``. That table maps names onto QuantLib classes and encodes no holiday rules.
"""

from __future__ import annotations

import inspect
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from better_calendar.calendars._toml import read_table
from better_calendar.calendars.providers import (
    CalendarSpec,
    build_calendar,
    clip_bounds,
    clip_to_dense,
    require_upstream,
    upstream_version,
    weekmask_from_weekdays,
)
from better_calendar.core.errors import ProviderError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from better_calendar.calendars.base import Calendar

__all__ = ["PROVIDER_NAME", "available", "materialise", "version"]

PROVIDER_NAME = "quantlib"

_MAP_PATH = Path(__file__).with_name("quantlib_map.toml")

#: Not real calendars: one is user-configured, one composes others, and two are trivial.
_SKIP = frozenset({"BespokeCalendar", "JointCalendar", "Calendar", "NullCalendar"})

#: QuantLib numbers weekdays Sunday = 1 .. Saturday = 7; Python numbers them Monday = 0.
_QL_WEEKDAYS = (2, 3, 4, 5, 6, 7, 1)


def version() -> str:
    """The installed ``QuantLib`` version.

    Returns:
        The version string.

    Examples:
        >>> version().count(".") >= 1
        True
    """
    return upstream_version(PROVIDER_NAME)


@lru_cache(maxsize=1)
def named_calendars() -> dict[str, str]:
    """The ``fin:`` / ``rate:`` name table from ``quantlib_map.toml``.

    Returns:
        Identifier to ``Class`` or ``Class.Market``.

    Examples:
        >>> named_calendars()["fin:TARGET2"]
        'TARGET'
        >>> named_calendars()["rate:SOFR"]
        'UnitedStates.SOFR'
    """
    return {str(key): str(value) for key, value in read_table(_MAP_PATH, "calendars").items()}


def _classes(upstream: Any) -> dict[str, Any]:
    """Every concrete QuantLib calendar class, by name."""
    found = {}
    for name in dir(upstream):
        candidate = getattr(upstream, name)
        if (
            inspect.isclass(candidate)
            and issubclass(candidate, upstream.Calendar)
            and name not in _SKIP
        ):
            found[name] = candidate
    return found


def _markets(calendar_class: Any) -> list[str]:
    """The market constants a QuantLib calendar class declares, if any."""
    return sorted(
        name
        for name in dir(calendar_class)
        if name[:1].isupper() and isinstance(getattr(calendar_class, name, None), int)
    )


def available() -> list[CalendarSpec]:
    """Every settlement calendar this provider can build.

    Returns:
        One spec per QuantLib class and market under the ``ql:`` namespace, plus the
        named ``fin:`` and ``rate:`` calendars.

    Examples:
        >>> ids = {spec.identifier for spec in available()}
        >>> {"fin:TARGET2", "rate:SOFR", "ql:UnitedStates.NYSE"} <= ids
        True
    """
    upstream = require_upstream(PROVIDER_NAME)
    specs = []
    for name, calendar_class in _classes(upstream).items():
        markets = _markets(calendar_class)
        targets = [f"{name}.{market}" for market in markets] if markets else [name]
        specs += [CalendarSpec(f"ql:{target}", PROVIDER_NAME, target) for target in targets]
    specs += [
        CalendarSpec(identifier, PROVIDER_NAME, target)
        for identifier, target in named_calendars().items()
    ]
    return sorted(specs, key=lambda spec: spec.identifier)


def _instantiate(upstream: Any, target: str) -> Any:
    """Build the QuantLib calendar named by ``Class`` or ``Class.Market``."""
    class_name, _, market = target.partition(".")
    classes = _classes(upstream)
    if class_name not in classes:
        raise ProviderError(
            f"QuantLib has no calendar class {class_name!r}. Fix the entry in "
            f"quantlib_map.toml, or check which classes this QuantLib version ships."
        )
    calendar_class = classes[class_name]
    if not market:
        return calendar_class()
    if not hasattr(calendar_class, market):
        raise ProviderError(
            f"QuantLib's {class_name} has no market {market!r}; it offers "
            f"{', '.join(_markets(calendar_class)) or 'none'}. Fix quantlib_map.toml."
        )
    return calendar_class(getattr(calendar_class, market))


def materialise(spec: CalendarSpec, bounds: tuple[date, date]) -> Calendar:
    """Build one settlement calendar over ``bounds``, clipped to QuantLib's date range.

    Args:
        spec: The spec to build, from :func:`available`.
        bounds: The requested horizon.

    Returns:
        The materialised calendar.

    Examples:
        >>> spec = CalendarSpec("fin:TARGET2", PROVIDER_NAME, "TARGET")
        >>> cal = materialise(spec, (date(2026, 1, 1), date(2026, 12, 31)))
        >>> cal.is_bday("2026-04-06")            # Easter Monday, TARGET2 closed
        False
    """
    upstream = require_upstream(PROVIDER_NAME)
    calendar = _instantiate(upstream, spec.upstream)
    limits = upstream.Date.minDate(), upstream.Date.maxDate()
    effective = clip_bounds(bounds, _to_date(limits[0]), _to_date(limits[1]))

    business_weekdays = [
        index for index, ql_day in enumerate(_QL_WEEKDAYS) if not calendar.isWeekend(ql_day)
    ]
    weekmask = weekmask_from_weekdays(business_weekdays)

    # `holidayList` already excludes weekends, which is exactly the set Calendar wants:
    # a holiday falling on a Sunday is not a business day either way.
    listed = upstream.Calendar.holidayList(
        calendar, _to_ql(upstream, effective[0]), _to_ql(upstream, effective[1]), False
    )
    holidays = [_to_date(day) for day in listed]
    # Lunar and Hebrew tables end without saying so; see clip_to_dense.
    effective = clip_to_dense(effective, holidays)
    holidays = [day for day in holidays if day <= effective[1]]
    return build_calendar(spec, effective, weekmask, holidays, version())


def _to_ql(upstream: Any, value: date) -> Any:
    return upstream.Date(value.day, value.month, value.year)


def _to_date(value: Any) -> date:
    return date(value.year(), int(value.month()), value.dayOfMonth())
