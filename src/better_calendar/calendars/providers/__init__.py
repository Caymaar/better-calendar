"""Upstream holiday providers (§5.3).

Providers are **build-time code**. They run when someone regenerates the committed
snapshot, never at import time and never when a query is answered (I8). Importing
``better_calendar`` must not import any of them, which is why nothing here is imported
from the package root and why every upstream import happens inside a function.

Each provider module exposes exactly:

* ``PROVIDER_NAME: str``
* ``version() -> str`` — the upstream package version
* ``available() -> list[CalendarSpec]`` — what it can build
* ``materialise(spec, bounds) -> Calendar``

A provider is free to return a calendar over a **narrower** horizon than the one asked
for: several upstreams refuse to answer outside their own limits (``exchange-calendars``
will not evaluate the Tokyo exchange before 1997, nor Hong Kong after 2049). Clipping and
recording the real bounds is the honest thing to do, and is exactly what I2 wants —
better a calendar that says "I do not know" than one that extrapolates.
"""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, time
from typing import TYPE_CHECKING, Any, Callable

from better_calendar._compat import DATACLASS_SLOTS
from better_calendar.core.errors import ProviderError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from types import ModuleType

    from better_calendar.calendars.base import Calendar

__all__ = [
    "DENSITY_CALIBRATION_YEARS",
    "PROVIDER_MODULES",
    "CalendarSpec",
    "clip_to_dense",
    "clip_to_observed",
    "load_provider",
    "provider_names",
    "require_upstream",
]

#: Provider name -> module implementing the protocol above.
PROVIDER_MODULES: dict[str, str] = {
    "exchange_calendars": "better_calendar.calendars.providers.exchange_calendars_",
    "python_holidays": "better_calendar.calendars.providers.python_holidays_",
    "quantlib": "better_calendar.calendars.providers.quantlib_",
    "workalendar": "better_calendar.calendars.providers.workalendar_",
}

#: Provider name -> (importable module, pip extra) for the actionable install hint.
_UPSTREAM: dict[str, tuple[str, str]] = {
    "exchange_calendars": ("exchange_calendars", "exchange"),
    "python_holidays": ("holidays", "holidays"),
    "quantlib": ("QuantLib", "quantlib"),
    "workalendar": ("workalendar", "workalendar"),
}


@dataclass(frozen=True, **DATACLASS_SLOTS)
class CalendarSpec:
    """One calendar a provider knows how to build.

    Attributes:
        identifier: The canonical id callers will use, e.g. ``"XNYS"``, ``"country:FR"``,
            ``"fin:TARGET2"``.
        provider: Name of the provider that owns it.
        upstream: Whatever the provider needs to look it up — a MIC, an ISO code, a
            QuantLib class-and-market pair. Opaque to everything except its own provider.
        tz: IANA timezone, when the calendar has meaningful instant semantics.
        session_start: Local time a calendar day begins (§9).
        extra: Provider-specific detail carried through to :func:`materialise`.

    Examples:
        >>> spec = CalendarSpec("XNYS", "exchange_calendars", "XNYS", tz="America/New_York")
        >>> spec.identifier, spec.provider
        ('XNYS', 'exchange_calendars')
    """

    identifier: str
    provider: str
    upstream: str
    tz: str | None = None
    session_start: time = time(0, 0)
    extra: tuple[tuple[str, str], ...] = field(default=())


def provider_names() -> list[str]:
    """Every provider name, in a stable order.

    Returns:
        Sorted provider names.

    Examples:
        >>> provider_names()
        ['exchange_calendars', 'python_holidays', 'quantlib', 'workalendar']
    """
    return sorted(PROVIDER_MODULES)


def load_provider(name: str) -> ModuleType:
    """Import a provider module by name.

    Args:
        name: One of :func:`provider_names`.

    Returns:
        The provider module.

    Raises:
        ProviderError: If ``name`` is not a known provider.

    Examples:
        >>> load_provider("quantlib").PROVIDER_NAME
        'quantlib'
    """
    target = PROVIDER_MODULES.get(name)
    if target is None:
        raise ProviderError(
            f"Unknown provider {name!r}. Known providers are {', '.join(provider_names())}."
        )
    return importlib.import_module(target)


def require_upstream(provider: str) -> ModuleType:
    """Import a provider's upstream package, or explain how to install it.

    Args:
        provider: The provider name, used to pick the right pip extra for the message.

    Returns:
        The upstream module.

    Raises:
        ProviderError: If the upstream is not installed.

    Examples:
        >>> require_upstream("quantlib").__name__
        'QuantLib'
    """
    module_name, extra = _UPSTREAM[provider]
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ProviderError.missing_dependency(
            module_name, extra, f"the {provider!r} provider", cause=exc
        ) from exc


def upstream_version(provider: str) -> str:
    """The installed version of a provider's upstream package.

    Args:
        provider: The provider name.

    Returns:
        The version string, or ``"unknown"`` if the package declares none.

    Examples:
        >>> upstream_version("quantlib").count(".") >= 1
        True
    """
    from importlib.metadata import PackageNotFoundError, version

    module_name, _ = _UPSTREAM[provider]
    require_upstream(provider)
    for candidate in (module_name, module_name.replace("_", "-")):
        try:
            return version(candidate)
        except PackageNotFoundError:
            continue
    return "unknown"  # pragma: no cover - every supported upstream declares a version


def clip_bounds(
    requested: tuple[date, date],
    lower: date | None,
    upper: date | None,
) -> tuple[date, date]:
    """Narrow the requested horizon to what an upstream will actually answer for.

    Args:
        requested: The horizon the caller asked for.
        lower: Earliest date the upstream supports, or ``None`` for no limit.
        upper: Latest date the upstream supports, or ``None`` for no limit.

    Returns:
        The intersected horizon.

    Raises:
        ProviderError: If the two do not overlap at all.

    Examples:
        >>> clip_bounds((date(1970, 1, 1), date(2050, 12, 31)), date(1997, 1, 1), None)
        (datetime.date(1997, 1, 1), datetime.date(2050, 12, 31))
    """
    first = max(requested[0], lower) if lower is not None else requested[0]
    last = min(requested[1], upper) if upper is not None else requested[1]
    if last < first:
        raise ProviderError(
            f"The requested horizon {requested[0]}..{requested[1]} does not overlap what "
            f"the upstream supports ({lower}..{upper}). Ask for a horizon inside it."
        )
    return first, last


def clip_to_observed(
    requested: tuple[date, date],
    holidays: Sequence[date],
) -> tuple[date, date]:
    """Narrow a horizon to the years an upstream actually produced holidays for.

    Some upstreams declare a wide range and then quietly return nothing outside a much
    narrower one — the ``holidays`` package advertises India from 1948 but only has data
    from 2001 to 2035, and ``workalendar``'s Chinese calendar is tabulated for a handful
    of years. Trusting the declaration would leave a calendar that answers "yes, that is a
    business day" for 1970 because it has never heard of any 1970 holiday. That is
    extrapolation wearing a disguise, and I2 forbids it.

    Every civil calendar observes at least New Year's Day, so a year with no holidays at
    all means no data rather than a year that genuinely had none.

    Args:
        requested: The horizon that was asked for.
        holidays: Every holiday the upstream produced for it.

    Returns:
        The horizon narrowed to whole years that produced at least one holiday. Returns
        ``requested`` unchanged when the upstream produced nothing at all, leaving the
        emptiness visible rather than silently collapsing the calendar to a point.

    Examples:
        >>> clip_to_observed(
        ...     (date(1970, 1, 1), date(2050, 12, 31)),
        ...     [date(2001, 1, 1), date(2035, 12, 25)],
        ... )
        (datetime.date(2001, 1, 1), datetime.date(2035, 12, 31))
    """
    if not holidays:
        return requested
    first_year = max(requested[0].year, min(day.year for day in holidays))
    last_year = min(requested[1].year, max(day.year for day in holidays))
    return (
        max(requested[0], date(first_year, 1, 1)),
        min(requested[1], date(last_year, 12, 31)),
    )


#: Years used to calibrate "how many holidays does this calendar normally have".
#:
#: The recent past is the one stretch every upstream covers properly, which makes it the
#: only trustworthy baseline. It is pinned rather than computed from today's date so that
#: two runs of ``better-calendar diff`` agree, and so the snapshot does not quietly change
#: on 1 January. Bump it every few years; the effect lands in a reviewed diff.
DENSITY_CALIBRATION_YEARS: tuple[int, int] = (2016, 2025)

#: A year holding less than this share of the reference density is treated as missing.
_DENSITY_RATIO = 0.5
#: Below this many calibration years, density says nothing and only emptiness is used.
_MIN_CALIBRATION_YEARS = 3


def clip_to_dense(
    requested: tuple[date, date],
    holidays: Sequence[date],
) -> tuple[date, date]:
    """Clip the horizon where an upstream's holiday data collapses.

    Lunar, Hebrew and Islamic holidays cannot be derived from a rule the way Easter can;
    upstreams tabulate them, and the tables end. What they do **not** do is say so. Past
    its table, QuantLib's Shanghai calendar drops from eighteen holidays a year to one —
    Chinese New Year simply disappears — its Tel Aviv calendar from sixty-two to zero, and
    its Mumbai calendar from fifteen to four, while all three keep answering "yes, that is
    a business day" with complete confidence. That is the silent extrapolation I2 exists
    to prevent, and :func:`clip_to_observed` does not catch it: the degraded years are not
    empty, merely wrong.

    So each calendar's annual holiday count is compared against its own norm, measured
    over :data:`DENSITY_CALIBRATION_YEARS`. A trailing run of years holding less than half
    that is dropped from the horizon.

    Only the trailing edge is clipped. Countries *gain* holidays over time, so a sparse
    early period is usually real history rather than missing data; a sparse late period
    never is.

    This is a heuristic, and it is deliberately one that fails visibly: the bounds it
    produces are written to the manifest, so a clip that moves shows up in the snapshot
    diff for a human to accept or reject — the same review path as a moved date.

    Args:
        requested: The horizon that was asked for.
        holidays: Every holiday the upstream produced for it.

    Returns:
        The horizon with any collapsed tail removed.

    Examples:
        >>> # Two holidays a year through 2025, then the table runs out.
        >>> dense = [date(year, month, 1) for year in range(2000, 2026) for month in (1, 5)]
        >>> clip_to_dense((date(2000, 1, 1), date(2050, 12, 31)), dense)
        (datetime.date(2000, 1, 1), datetime.date(2025, 12, 31))
    """
    if not holidays:
        return requested
    counts = dict.fromkeys(range(requested[0].year, requested[1].year + 1), 0)
    for day in holidays:
        if day.year in counts:
            counts[day.year] += 1

    first, last = DENSITY_CALIBRATION_YEARS
    calibration = [count for year, count in counts.items() if first <= year <= last]
    if len(calibration) < _MIN_CALIBRATION_YEARS:
        return clip_to_observed(requested, holidays)

    threshold = max(1.0, _median(calibration) * _DENSITY_RATIO)
    dense_years = [year for year, count in counts.items() if count >= threshold]
    if not dense_years:
        return clip_to_observed(requested, holidays)
    return clip_to_observed(
        (requested[0], min(requested[1], date(max(dense_years), 12, 31))), holidays
    )


def _median(values: Sequence[int]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2


def build_calendar(
    spec: CalendarSpec,
    bounds: tuple[date, date],
    weekmask: str,
    holidays: Any,
    provider_version: str,
) -> Calendar:
    """Assemble the :class:`Calendar` a provider's ``materialise`` should return.

    Args:
        spec: The spec being materialised.
        bounds: The effective (already clipped) horizon.
        weekmask: Which weekdays can be business days.
        holidays: Non-business days inside ``bounds`` that ``weekmask`` would allow.
        provider_version: The upstream version, recorded for provenance (I8).

    Returns:
        The materialised calendar.

    Examples:
        >>> spec = CalendarSpec("demo", "quantlib", "TARGET")
        >>> cal = build_calendar(
        ...     spec, (date(2026, 1, 1), date(2026, 12, 31)), "Mon Tue Wed Thu Fri",
        ...     ["2026-01-01"], "1.43",
        ... )
        >>> cal.is_bday("2026-01-01")
        False
    """
    from better_calendar.calendars.base import Calendar

    return Calendar(
        name=spec.identifier,
        holidays=holidays,
        weekmask=weekmask,
        bounds=bounds,
        tz=spec.tz,
        session_start=spec.session_start,
        provider=spec.provider,
        provider_version=provider_version,
    )


def weekmask_from_weekdays(business_weekdays: Any) -> str:
    """Build a canonical weekmask from the set of weekdays that are business days.

    Args:
        business_weekdays: Iterable of ``date.weekday()`` indices (Monday = 0).

    Returns:
        The numpy-style binary weekmask, which :class:`Calendar` canonicalises further.

    Examples:
        >>> weekmask_from_weekdays({0, 1, 2, 3, 4})
        '1111100'
        >>> weekmask_from_weekdays({6, 0, 1, 2, 3})       # a Sun-Thu working week
        '1111001'
    """
    selected = {int(day) for day in business_weekdays}
    return "".join("1" if index in selected else "0" for index in range(7))


_Materialiser = Callable[[CalendarSpec, "tuple[date, date]"], "Calendar"]
