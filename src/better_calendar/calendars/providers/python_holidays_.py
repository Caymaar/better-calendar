"""Civil calendars from the ``holidays`` package, keyed by ISO-3166 code (§5.3).

These are *public holiday* calendars — what the country observes — not settlement or
exchange calendars. They answer "is this a working day in France", which is a different
question from "does TARGET2 settle" and a very different one from "is Euronext Paris
open". Do not substitute one for another.

The upstream also knows each country's weekend, which is not always Saturday and Sunday:
Israel rests Friday and Saturday. That is read from the upstream rather than assumed.
"""

from __future__ import annotations

import warnings
from datetime import date
from typing import TYPE_CHECKING

from better_calendar.calendars.providers import (
    CalendarSpec,
    build_calendar,
    clip_bounds,
    clip_to_dense,
    require_upstream,
    upstream_version,
    weekmask_from_weekdays,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from better_calendar.calendars.base import Calendar

__all__ = ["PROVIDER_NAME", "available", "materialise", "version"]

PROVIDER_NAME = "python_holidays"

_ISO_ALPHA2_LENGTH = 2

#: Subdivisions worth shipping. The upstream exposes thousands; snapshotting all of them
#: would multiply the committed data by an order of magnitude for calendars nobody has
#: asked for. Anything missing can be added here, or built locally with `register()`.
_SUBDIVISIONS: tuple[tuple[str, str], ...] = (("US", "NY"),)


def version() -> str:
    """The installed ``holidays`` version.

    Returns:
        The version string.

    Examples:
        >>> version().count(".") >= 1
        True
    """
    return upstream_version(PROVIDER_NAME)


def available() -> list[CalendarSpec]:
    """Every civil calendar this provider can build.

    Returns:
        Specs for each ISO-3166-1 alpha-2 country, plus the shipped subdivisions.
        Three-letter and long-form upstream aliases are skipped.

    Examples:
        >>> {spec.identifier for spec in available()} >= {"country:FR", "country:US"}
        True
    """
    upstream = require_upstream(PROVIDER_NAME)
    specs = [
        CalendarSpec(f"country:{code}", PROVIDER_NAME, code)
        for code in upstream.list_supported_countries()
        if len(code) == _ISO_ALPHA2_LENGTH and code.isupper()
    ]
    specs += [
        CalendarSpec(
            f"country:{country}-{subdivision}",
            PROVIDER_NAME,
            country,
            extra=(("subdivision", subdivision),),
        )
        for country, subdivision in _SUBDIVISIONS
    ]
    return sorted(specs, key=lambda spec: spec.identifier)


def materialise(spec: CalendarSpec, bounds: tuple[date, date]) -> Calendar:
    """Build one civil calendar over ``bounds``.

    Args:
        spec: The spec to build, from :func:`available`.
        bounds: The requested horizon. This upstream is rule-based and has no limits of
            its own, so the horizon is honoured exactly.

    Returns:
        The materialised calendar.

    Examples:
        >>> spec = CalendarSpec("country:FR", PROVIDER_NAME, "FR")
        >>> cal = materialise(spec, (date(2026, 1, 1), date(2026, 12, 31)))
        >>> cal.is_bday("2026-07-14")            # Bastille Day
        False
    """
    upstream = require_upstream(PROVIDER_NAME)
    subdivision = dict(spec.extra).get("subdivision")
    years = range(bounds[0].year, bounds[1].year + 1)

    # The upstream warns, rather than raises, when the requested years run past its data.
    # That is precisely the condition handled below by narrowing the bounds, so the
    # warning is noise here — and turning it into an error would abort the snapshot run.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        entries = upstream.country_holidays(spec.upstream, subdiv=subdivision, years=years)
        # `weekend` is a set of `date.weekday()` indices; the week is its complement.
        weekend = {int(day) for day in getattr(entries, "weekend", {5, 6})}
        declared = clip_bounds(
            bounds,
            _year_start(getattr(entries, "start_year", None)),
            _year_end(getattr(entries, "end_year", None)),
        )
        holidays = sorted(
            day
            for day in entries
            if declared[0] <= day <= declared[1] and day.weekday() not in weekend
        )

    weekmask = weekmask_from_weekdays(day for day in range(7) if day not in weekend)
    effective = clip_to_dense(declared, holidays)
    holidays = [day for day in holidays if effective[0] <= day <= effective[1]]
    return build_calendar(spec, effective, weekmask, holidays, version())


def _year_start(year: int | None) -> date | None:
    return date(int(year), 1, 1) if year is not None else None


def _year_end(year: int | None) -> date | None:
    return date(int(year), 12, 31) if year is not None else None
