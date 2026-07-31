"""Fallback civil calendars from ``workalendar`` (§5.3).

This provider covers the regions the others miss, and the lunar and religious calendars
``workalendar`` models well. Everything it offers is namespaced ``wk:``, so it is always
obvious which upstream answered — and so a second opinion on a country the ``holidays``
package also covers is available without either shadowing the other.

"Fallback" is about *resolution priority*, not about coverage: the registry resolves a
plain ``country:FR`` through the ``holidays`` package, and ``wk:FR`` is there for when
you want to compare the two, or when you trust this upstream more for a given region.
"""

from __future__ import annotations

import warnings
from datetime import date
from typing import TYPE_CHECKING, Any

from better_calendar.calendars.providers import (
    CalendarSpec,
    build_calendar,
    clip_to_dense,
    require_upstream,
    upstream_version,
    weekmask_from_weekdays,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from better_calendar.calendars.base import Calendar

__all__ = ["PROVIDER_NAME", "available", "materialise", "version"]

PROVIDER_NAME = "workalendar"


def version() -> str:
    """The installed ``workalendar`` version.

    Returns:
        The version string.

    Examples:
        >>> version().count(".") >= 1
        True
    """
    return upstream_version(PROVIDER_NAME)


def available() -> list[CalendarSpec]:
    """Every region this provider covers.

    Returns:
        Specs under the ``wk:`` namespace, sorted by identifier.

    Examples:
        >>> specs = available()
        >>> all(spec.identifier.startswith("wk:") for spec in specs)
        True
        >>> "wk:FR" in {spec.identifier for spec in specs}
        True
    """
    require_upstream(PROVIDER_NAME)
    from workalendar.registry import registry

    return sorted(
        (CalendarSpec(f"wk:{code}", PROVIDER_NAME, code) for code in registry.get_calendars()),
        key=lambda spec: spec.identifier,
    )


def materialise(spec: CalendarSpec, bounds: tuple[date, date]) -> Calendar:
    """Build one fallback civil calendar over ``bounds``.

    Args:
        spec: The spec to build, from :func:`available`.
        bounds: The requested horizon. ``workalendar`` is rule-based and honours it
            exactly, though a rule may legitimately produce nothing for early years.

    Returns:
        The materialised calendar.

    Examples:
        >>> spec = CalendarSpec("wk:FR", PROVIDER_NAME, "FR")
        >>> cal = materialise(spec, (date(2026, 1, 1), date(2026, 12, 31)))
        >>> cal.is_bday("2026-07-14")            # Bastille Day
        False
    """
    require_upstream(PROVIDER_NAME)
    from workalendar.registry import registry

    calendar = registry.get_calendars()[spec.upstream]()
    weekend = {int(day) for day in getattr(calendar, "WEEKEND_DAYS", (5, 6))}
    business_weekdays = [day for day in range(7) if day not in weekend]
    weekmask = weekmask_from_weekdays(business_weekdays)

    holidays = set()
    # Lunar and religious calendars warn that they are tabulated for a limited span; that
    # is handled by narrowing the bounds below, so the warning itself is noise here.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for year in range(bounds[0].year, bounds[1].year + 1):
            for day, _label in _year_holidays(calendar, year):
                if bounds[0] <= day <= bounds[1] and day.weekday() not in weekend:
                    holidays.add(day)

    observed = sorted(holidays)
    effective = clip_to_dense(bounds, observed)
    kept = [day for day in observed if effective[0] <= day <= effective[1]]
    return build_calendar(spec, effective, weekmask, kept, version())


def _year_holidays(calendar: Any, year: int) -> list[tuple[date, str]]:
    """One year of holidays, tolerating the years an upstream rule cannot express.

    Lunar and religious calendars are tabulated rather than computed, so they run out
    at some point. A year the upstream cannot answer for is skipped: the alternative is
    a snapshot run that dies on one country out of seventy.
    """
    try:
        return list(calendar.holidays(year))
    except Exception:  # upstream raises a wide variety here
        return []
