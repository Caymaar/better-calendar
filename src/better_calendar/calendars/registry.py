"""Calendar lookup by identifier (§5.4).

Resolution order, applied in this order and documented as part of the public contract:

1. **Already a calendar.** A :class:`~better_calendar.calendars.base.Calendar` passes
   through untouched, and ``None`` means the default ``weekday`` calendar (§13).
2. **Explicitly registered.** Anything installed with :func:`register` wins, so an
   organisation can shadow a shipped calendar without forking it.
3. **Built in.** ``weekday`` and ``crypto:24x7``, which need no snapshot.
4. **Snapshot.** Provider-materialised calendars read from the committed data (I8). No
   provider is imported: the answer comes from a file that a human reviewed and merged.
5. **Alias.** ``aliases.toml`` maps a colloquial name onto a canonical id, which is then
   resolved from step 2 again. Chains are followed; cycles are rejected.

Anything unresolved raises
:class:`~better_calendar.core.errors.UnknownCalendarError` with did-you-mean suggestions.

Results are memoised. That is safe precisely because calendars are frozen (I1): two
callers holding the same object cannot interfere with each other.
"""

from __future__ import annotations

from datetime import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Union

from better_calendar.calendars._toml import read_table
from better_calendar.calendars.base import WEEKMASK_ALL, WEEKMASK_WEEKDAYS, Calendar
from better_calendar.calendars.snapshot import load_calendar, load_manifest, snapshot_ids
from better_calendar.core.epoch import DEFAULT_BOUNDS
from better_calendar.core.errors import BetterCalendarError, UnknownCalendarError

__all__ = [
    "DEFAULT_CALENDAR",
    "CalendarLike",
    "aliases",
    "describe",
    "get",
    "list_calendars",
    "register",
    "resolve",
    "unregister",
]

CalendarLike = Union[Calendar, str, None]

#: The calendar meant by ``cal=None`` in every free function (§13).
DEFAULT_CALENDAR = "weekday"

_ALIASES_PATH = Path(__file__).with_name("aliases.toml")


def _build_weekday() -> Calendar:
    return Calendar(
        name=DEFAULT_CALENDAR,
        weekmask=WEEKMASK_WEEKDAYS,
        bounds=DEFAULT_BOUNDS,
        tz=None,
        provider="builtin",
    )


def _build_crypto() -> Calendar:
    # A first-class 24/7 calendar (§9.2) so that crypto code uses the identical API,
    # and so `crypto:24x7 & XCME` is a meaningful thing to write for listed products.
    return Calendar(
        name="crypto:24x7",
        weekmask=WEEKMASK_ALL,
        bounds=DEFAULT_BOUNDS,
        tz="UTC",
        session_start=time(0, 0),
        provider="builtin",
    )


#: Built-in calendars, constructed lazily so importing the package stays cheap.
_BUILTINS: dict[str, Callable[[], Calendar]] = {
    DEFAULT_CALENDAR: _build_weekday,
    "crypto:24x7": _build_crypto,
}

_REGISTERED: dict[str, Calendar] = {}


@lru_cache(maxsize=1)
def aliases() -> dict[str, str]:
    """The alias table from ``aliases.toml``, keyed by lower-cased alias.

    Returns:
        A mapping of alias to canonical identifier.

    Examples:
        >>> aliases()["nyse"]
        'XNYS'
    """
    table = read_table(_ALIASES_PATH, "aliases")
    return {str(key).lower(): str(value) for key, value in table.items()}


def _canonicalise(name: str, *, _seen: list[str] | None = None) -> str:
    """Follow the alias chain to a canonical identifier, rejecting cycles."""
    seen = _seen if _seen is not None else []
    key = name.strip()
    if key.lower() in [s.lower() for s in seen]:
        raise BetterCalendarError(
            f"Alias cycle in aliases.toml: {' -> '.join([*seen, key])}. "
            f"Break the loop by pointing one of them at a canonical identifier."
        )
    target = aliases().get(key.lower())
    if target is None or target == key:
        return key
    return _canonicalise(target, _seen=[*seen, key])


def _known_names() -> list[str]:
    """Everything a user could plausibly have meant, for did-you-mean suggestions."""
    return sorted(
        {*_REGISTERED, *_BUILTINS, *snapshot_ids(), *aliases().keys(), *aliases().values()}
    )


def _resolve_step(name: str) -> Calendar | None:
    """One pass of the resolution order: registered, then built in, then snapshot."""
    if name in _REGISTERED:
        return _REGISTERED[name]
    if name in _BUILTINS:
        return _BUILTINS[name]()
    if name in load_manifest():
        return load_calendar(name)
    return None


@lru_cache(maxsize=512)
def _get_cached(name: str) -> Calendar:
    found = _resolve_step(name)
    if found is not None:
        return found

    canonical = _canonicalise(name)
    if canonical != name:
        # Recurse rather than resolve inline, so an alias and its target share one cache
        # entry — and therefore one object. `_canonicalise` has already rejected cycles.
        if _resolve_step(canonical) is not None:
            return _get_cached(canonical)
        raise UnknownCalendarError(
            f"Calendar {name!r} is a known alias for {canonical!r}, but {canonical!r} is "
            f"not in the committed snapshot. Regenerate it with `better-calendar "
            f"snapshot`, or install the calendar yourself with better_calendar.register()."
        )
    raise UnknownCalendarError.for_name(name, _known_names())


def get(name: str) -> Calendar:
    """Resolve a calendar identifier.

    Args:
        name: A canonical identifier (``"weekday"``, ``"crypto:24x7"``, ``"XNYS"``) or an
            alias from ``aliases.toml`` (``"NYSE"``, ``"TARGET"``).

    Returns:
        The corresponding :class:`~better_calendar.calendars.base.Calendar`. The same
        object is returned for repeated calls, which is safe because calendars are frozen.

    Raises:
        UnknownCalendarError: If the name resolves to nothing, with close matches listed.

    Examples:
        >>> get("weekday").weekmask
        'Mon Tue Wed Thu Fri'
        >>> get("weekday") is get("weekday")            # memoised
        True
        >>> get("crypto:24x7").tz
        'UTC'
    """
    if not isinstance(name, str):
        raise BetterCalendarError(
            f"get() takes a calendar identifier, got {type(name).__name__}. "
            f"Use better_calendar.calendars.registry.resolve() to accept a Calendar too."
        )
    return _get_cached(name)


def resolve(cal: CalendarLike) -> Calendar:
    """Coerce the ``cal=`` argument accepted by every free function into a calendar.

    Args:
        cal: A :class:`~better_calendar.calendars.base.Calendar`, an identifier, or
            ``None`` for the default ``weekday`` calendar.

    Returns:
        The resolved calendar.

    Examples:
        >>> resolve(None).name
        'weekday'
        >>> resolve("crypto:24x7").name
        'crypto:24x7'
    """
    if cal is None:
        return get(DEFAULT_CALENDAR)
    if isinstance(cal, Calendar):
        return cal
    return get(cal)


def register(name: str, calendar: Calendar, *, overwrite: bool = False) -> None:
    """Install an organisation-specific calendar under ``name``.

    Args:
        name: The identifier callers will use.
        calendar: The calendar to install.
        overwrite: Allow replacing an existing registration.

    Raises:
        BetterCalendarError: If ``name`` is taken and ``overwrite`` is ``False``.

    Examples:
        >>> from better_calendar import Calendar
        >>> register("desk:demo", Calendar("desk:demo", holidays=["2026-07-31"]))
        >>> get("desk:demo").is_bday("2026-07-31")
        False
        >>> unregister("desk:demo")
    """
    if not isinstance(calendar, Calendar):
        raise BetterCalendarError(
            f"register() takes a Calendar, got {type(calendar).__name__}. "
            f"Build one with better_calendar.Calendar(...) first."
        )
    if name in _REGISTERED and not overwrite:
        raise BetterCalendarError(
            f"Calendar {name!r} is already registered. Pass overwrite=True to replace it, "
            f"or pick a different name."
        )
    _REGISTERED[name] = calendar
    _get_cached.cache_clear()


def unregister(name: str) -> None:
    """Remove a calendar installed with :func:`register`.

    Args:
        name: The identifier to remove.

    Raises:
        UnknownCalendarError: If nothing is registered under that name.

    Examples:
        >>> from better_calendar import Calendar
        >>> register("desk:tmp", Calendar("desk:tmp"))
        >>> unregister("desk:tmp")
    """
    if name not in _REGISTERED:
        raise UnknownCalendarError.for_name(name, sorted(_REGISTERED))
    del _REGISTERED[name]
    _get_cached.cache_clear()


def list_calendars(*, provider: str | None = None) -> list[str]:
    """Every resolvable calendar identifier.

    Args:
        provider: Restrict to calendars materialised by this provider, for example
            ``"builtin"``.

    Returns:
        Sorted identifiers.

    Examples:
        >>> {"weekday", "crypto:24x7"} <= set(list_calendars())
        True
        >>> list_calendars(provider="builtin")
        ['crypto:24x7', 'weekday']
    """
    names = sorted({*_BUILTINS, *_REGISTERED, *snapshot_ids()})
    if provider is None:
        return names
    # The manifest already knows each snapshot calendar's provider, so filtering does not
    # have to read (and parse) every calendar file just to answer the question.
    manifest = load_manifest()
    return [
        name
        for name in names
        if (manifest[name].provider if name in manifest else get(name).provider) == provider
    ]


def describe(name: str) -> dict[str, Any]:
    """Provenance and shape of a calendar, by identifier.

    Args:
        name: A canonical identifier or an alias.

    Returns:
        The dict from :meth:`~better_calendar.calendars.base.Calendar.describe`, plus the
        identifier that was asked for and the canonical one it resolved to.

    Examples:
        >>> info = describe("weekday")
        >>> info["requested"], info["canonical"], info["provider"]
        ('weekday', 'weekday', 'builtin')
    """
    calendar = get(name)
    info = calendar.describe()
    info["requested"] = name
    info["canonical"] = _canonicalise(name)
    return info
