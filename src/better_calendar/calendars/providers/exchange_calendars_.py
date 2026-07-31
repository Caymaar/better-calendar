"""Exchange calendars from ``exchange-calendars``, keyed by ISO-10383 MIC (§5.3).

This upstream is the authority on when an exchange actually held a session, including
one-off closures (hurricanes, state funerals, exchange outages) that no rule reproduces.
It hands us *sessions*, not holidays, which is the better direction: we derive the
weekmask and the holiday list from the sessions rather than guessing either.

Several of these calendars refuse to be evaluated outside their own limits — Tokyo not
before 1997, Hong Kong not after 2049. Those limits are respected and recorded rather
than papered over (I2).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

import numpy as np

from better_calendar.calendars.providers import (
    CalendarSpec,
    build_calendar,
    clip_bounds,
    require_upstream,
    upstream_version,
    weekmask_from_weekdays,
)
from better_calendar.core.epoch import date_to_days, days_to_datetime64, weekday_of

if TYPE_CHECKING:  # pragma: no cover - typing only
    from better_calendar.calendars.base import Calendar

__all__ = ["PROVIDER_NAME", "available", "materialise", "version"]

PROVIDER_NAME = "exchange_calendars"

#: A four-letter uppercase key is an ISO-10383 MIC and gets no namespace prefix (§5.4).
#: Everything else the upstream ships (``us_futures``, ``24/7``, ``CMES``) is namespaced,
#: so that a bare identifier always means "this is a MIC".
_MIC_LENGTH = 4


def version() -> str:
    """The installed ``exchange-calendars`` version.

    Returns:
        The version string.

    Examples:
        >>> version().count(".") >= 1
        True
    """
    return upstream_version(PROVIDER_NAME)


def _identifier(key: str) -> str:
    if len(key) == _MIC_LENGTH and key.isupper() and key.isalpha():
        return key
    return f"exchange:{key}"


def available() -> list[CalendarSpec]:
    """Every exchange calendar the upstream can build.

    Returns:
        Specs for each canonical calendar, sorted by identifier. Upstream aliases
        (``NYSE`` -> ``XNYS``) are not included: they belong in ``aliases.toml``.

    Examples:
        >>> specs = available()
        >>> "XNYS" in {spec.identifier for spec in specs}
        True
    """
    upstream = require_upstream(PROVIDER_NAME)
    factories = upstream.calendar_utils._default_calendar_factories
    specs = []
    for key in factories:
        # Instantiating is the only way to read `tz`, and the upstream memoises, so the
        # cost is paid once per calendar for the whole snapshot run.
        try:
            calendar = upstream.get_calendar(key)
        except Exception:  # a broken upstream calendar must not stop the run
            continue
        zone = getattr(calendar, "tz", None)
        specs.append(
            CalendarSpec(
                identifier=_identifier(key),
                provider=PROVIDER_NAME,
                upstream=key,
                tz=str(zone) if zone is not None else None,
            )
        )
    return sorted(specs, key=lambda spec: spec.identifier)


def materialise(spec: CalendarSpec, bounds: tuple[date, date]) -> Calendar:
    """Build one exchange calendar over ``bounds``, clipped to the upstream's limits.

    Args:
        spec: The spec to build, from :func:`available`.
        bounds: The requested horizon.

    Returns:
        The materialised calendar, whose ``bounds`` may be narrower than requested.

    Examples:
        >>> spec = CalendarSpec("XNYS", PROVIDER_NAME, "XNYS")
        >>> cal = materialise(spec, (date(2026, 1, 1), date(2026, 12, 31)))
        >>> cal.is_bday("2026-07-03")            # Independence Day, observed
        False
    """
    upstream = require_upstream(PROVIDER_NAME)
    factory = upstream.calendar_utils._default_calendar_factories[spec.upstream]
    effective = clip_bounds(
        bounds, _as_date(factory.bound_min()), _as_date(factory.bound_max())
    )

    # `side` is deliberately not passed: it controls whether session open/close times are
    # inclusive, which we do not care about, and the round-the-clock calendars reject the
    # value regular ones default to.
    calendar = upstream.get_calendar(
        spec.upstream,
        start=effective[0].isoformat(),
        end=effective[1].isoformat(),
    )
    sessions = np.ascontiguousarray(calendar.sessions.values.astype("datetime64[D]")).view(
        np.int64
    )

    lo, hi = date_to_days(effective[0]), date_to_days(effective[1])
    every_day = np.arange(lo, hi + 1, dtype=np.int64)
    # The weekmask is whichever weekdays the exchange actually traded on, not an
    # assumption: Tel Aviv runs Sunday to Thursday, and several venues have changed.
    business_weekdays = np.unique(weekday_of(sessions)) if sessions.size else np.arange(5)
    weekmask = weekmask_from_weekdays(business_weekdays.tolist())
    allowed = np.zeros(7, dtype=bool)
    allowed[business_weekdays] = True
    candidates = every_day[allowed[weekday_of(every_day)]]
    holidays = np.setdiff1d(candidates, sessions, assume_unique=True)

    return build_calendar(spec, effective, weekmask, days_to_datetime64(holidays), version())


def _as_date(value: Any) -> date | None:
    """Coerce an upstream bound (a ``Timestamp`` or ``None``) to a plain date."""
    if value is None:
        return None
    return date(value.year, value.month, value.day)
