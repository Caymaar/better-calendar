"""Organisation-specific calendars, composed on top of the shipped ones (§5.6).

A desk closes on 24 December; the euro area does not. That is a local fact, not something
``QuantLib`` is wrong about, and the answer is **never** to fork a provider calendar to
add it. Instead a configuration file composes on top::

    calendars:
      desk:paris:
        base: fin:TARGET2
        extra_holidays: ["2026-01-02", "2026-12-24"]
        remove_holidays: []
        tz: Europe/Paris

An entry may also build on **several** calendars at once, which is the usual shape for a
settlement calendar spanning two financial centres::

    calendars:
      desk:paris:
        base: [fin:TARGET2, fin:LNB]
        base_op: all_open          # business day in *both*; closed if either closes
        tz: Europe/Paris

``base_op`` is required whenever ``base`` lists more than one calendar, and is never
defaulted: ``all_open`` and ``any_open`` are exact opposites, and which one a desk means is
not something to guess on its behalf. See :mod:`better_calendar.calendars.algebra` for the
union/intersection trap this avoids.

The file is found at ``$BETTER_CALENDAR_CONFIG`` if that is set, otherwise
``./better-calendar.yaml`` (or ``.yml``, or ``better-calendar.toml``) in the working
directory. It is read once and memoised.

**On the format and its cost.** §5.6 specifies YAML, but reading YAML needs ``PyYAML``
and §14 keeps ``numpy`` the only mandatory dependency. So:

* **TOML** costs nothing on Python 3.11+, where ``tomllib`` is in the standard library.
* **YAML** always needs ``PyYAML``.
* Below 3.11 neither format is readable from a bare install, because ``tomllib`` does not
  exist there either. That is a real consequence of the 3.9 floor, not something to paper
  over.

``pip install 'better-calendar[config]'`` covers every case. Whatever is missing, the
error names the extra: a configuration file that is silently *not applied* would be far
worse than one that refuses to load.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from better_calendar.core.errors import BetterCalendarError, ProviderError

__all__ = ["CONFIG_ENV_VAR", "config_path", "load_overrides", "override_calendars"]

PROVIDER_NAME = "custom"

#: Environment variable naming the configuration file.
CONFIG_ENV_VAR = "BETTER_CALENDAR_CONFIG"

#: Filenames looked for in the working directory, in order.
_DEFAULT_NAMES = (
    "better-calendar.yaml",
    "better-calendar.yml",
    "better-calendar.toml",
)

_KNOWN_KEYS = frozenset(
    {
        "base",
        "base_op",
        "extra_holidays",
        "remove_holidays",
        "tz",
        "weekmask",
        "session_start",
        "bounds",
    }
)

#: Set operations a configured calendar may compose several bases with (§6). Both are
#: n-ary and order-independent. ``difference`` and ``symmetric_difference`` are absent on
#: purpose: they are binary and order-sensitive, which reads badly in a mapping where the
#: reader has no cue that order matters. Express those in Python.
_BASE_OPS = ("all_open", "any_open")


def config_path() -> Path | None:
    """The configuration file in effect, or ``None`` if there is none.

    Returns:
        The path, from ``$BETTER_CALENDAR_CONFIG`` or the working directory.

    Raises:
        BetterCalendarError: If the environment variable names a file that is not there.
            An explicitly configured path that does not exist is a mistake worth
            reporting, unlike the absence of a default one.

    Examples:
        >>> config_path() is None or config_path().exists()
        True
    """
    configured = os.environ.get(CONFIG_ENV_VAR)
    if configured:
        path = Path(configured)
        if not path.exists():
            raise BetterCalendarError(
                f"{CONFIG_ENV_VAR} points at {path}, which does not exist. Fix the "
                f"variable, or unset it to fall back on ./better-calendar.yaml."
            )
        return path
    for name in _DEFAULT_NAMES:
        candidate = Path.cwd() / name
        if candidate.exists():
            return candidate
    return None


def _read(path: Path) -> dict[str, Any]:
    """Parse the configuration file, whatever format it is in."""
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as exc:
            raise ProviderError.missing_dependency(
                "PyYAML", "config", f"reading the YAML configuration at {path}", cause=exc
            ) from exc
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise BetterCalendarError(f"Cannot parse {path}: {exc}.") from exc
        if not isinstance(loaded, dict):
            raise BetterCalendarError(
                f"{path} must contain a mapping at the top level, with a 'calendars' key."
            )
        return loaded

    import sys

    text = path.read_text(encoding="utf-8")
    if sys.version_info >= (3, 11):
        import tomllib

        try:
            return dict(tomllib.loads(text))
        except tomllib.TOMLDecodeError as exc:
            raise BetterCalendarError(f"Cannot parse {path}: {exc}.") from exc
    try:
        import tomli
    except ImportError as exc:
        raise ProviderError.missing_dependency(
            "tomli",
            "config",
            f"reading the TOML configuration at {path} on Python < 3.11, where tomllib "
            f"is not in the standard library",
            cause=exc,
        ) from exc
    try:
        return dict(tomli.loads(text))
    except tomli.TOMLDecodeError as exc:
        raise BetterCalendarError(f"Cannot parse {path}: {exc}.") from exc


@lru_cache(maxsize=4)
def load_overrides(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """The ``calendars:`` section of the configuration file.

    Args:
        path: The file to read; ``None`` discovers it via :func:`config_path`.

    Returns:
        Calendar identifier to its override specification. Empty when there is no file.

    Raises:
        BetterCalendarError: If the file is malformed, or names an unknown key.

    Examples:
        >>> isinstance(load_overrides(), dict)
        True
    """
    target = path if path is not None else config_path()
    if target is None:
        return {}
    payload = _read(target)
    section = payload.get("calendars", {})
    if not isinstance(section, dict):
        raise BetterCalendarError(
            f"The 'calendars' key in {target} must be a mapping of identifier to specification."
        )
    for name, spec in section.items():
        if not isinstance(spec, dict):
            raise BetterCalendarError(
                f"Calendar {name!r} in {target} must be a mapping, got {type(spec).__name__}."
            )
        unknown = set(spec) - _KNOWN_KEYS
        if unknown:
            raise BetterCalendarError(
                f"Calendar {name!r} in {target} has unknown keys "
                f"{', '.join(sorted(unknown))}. Known keys are "
                f"{', '.join(sorted(_KNOWN_KEYS))}."
            )
    return {str(name): dict(spec) for name, spec in section.items()}


def override_calendars(path: Path | None = None) -> list[str]:
    """The identifiers the configuration file defines.

    Args:
        path: The file to read; ``None`` discovers it.

    Returns:
        Sorted identifiers.

    Examples:
        >>> isinstance(override_calendars(), list)
        True
    """
    return sorted(load_overrides(path))


def build(name: str, path: Path | None = None) -> Any:
    """Materialise one configured calendar.

    Args:
        name: The identifier, which must be present in the configuration.
        path: The file to read; ``None`` discovers it.

    Returns:
        The composed :class:`~better_calendar.calendars.base.Calendar`.

    Raises:
        BetterCalendarError: If the calendar is not configured, if its ``base`` cannot be
            resolved, or if several bases are listed without a ``base_op`` saying how to
            combine them.

    Examples:
        >>> build("nothing:configured")
        Traceback (most recent call last):
        ...
        better_calendar.core.errors.BetterCalendarError: No calendar 'nothing:configured'
        is configured. Add it under the 'calendars' key of your configuration file.
    """
    from better_calendar.calendars.base import Calendar

    spec = load_overrides(path).get(name)
    if spec is None:
        raise BetterCalendarError(
            f"No calendar {name!r} is configured. Add it under the 'calendars' key of "
            f"your configuration file."
        )

    base, provenance = _resolve_base(name, spec)
    holidays = base.holidays
    extra = spec.get("extra_holidays") or []
    removed = spec.get("remove_holidays") or []
    composed = Calendar(
        name=name,
        holidays=holidays,
        weekmask=str(spec.get("weekmask", base.weekmask)),
        bounds=_bounds(spec.get("bounds"), base.bounds),
        tz=spec.get("tz", base.tz),
        session_start=_time(spec.get("session_start"), base.session_start),
        provider=PROVIDER_NAME,
        provider_version=provenance,
    )
    if extra:
        composed = composed.with_holidays(list(extra), name=name)
    if removed:
        composed = composed.without_holidays(list(removed), name=name)
    return composed


def _one_base(entry: str, base_name: str) -> Any:
    """Resolve a single name appearing in an entry's ``base``."""
    from better_calendar.calendars.registry import get, resolve_shipped

    if base_name == entry:
        # Adding a local closure to a public calendar: `XNYS: {base: XNYS, ...}`. The base
        # has to come from below the configuration layer, or this would find itself. The
        # test lives here, per name, because a list of bases may mention the entry too --
        # `XNYS: {base: [XNYS, fin:LNB], ...}` -- and comparing the whole `base` value
        # against the entry name would miss it and recurse until the stack runs out.
        shipped = resolve_shipped(entry)
        if shipped is None:
            raise BetterCalendarError(
                f"Calendar {entry!r} is configured with itself as its base, but no shipped "
                f"calendar of that name exists to build on. Name a different base, or drop "
                f"the 'base' key to build from scratch."
            )
        return shipped
    return get(base_name)


def _resolve_base(name: str, spec: dict[str, Any]) -> tuple[Any, str | None]:
    """The calendar an entry composes on top of, and the provenance string recording it.

    Args:
        name: The identifier of the entry being built.
        spec: Its specification, as read from the configuration file.

    Returns:
        The base calendar -- an empty ``weekday`` one when the entry declares no base --
        and the string stored as ``provider_version``, or ``None`` when built from scratch.

    Raises:
        BetterCalendarError: If ``base``/``base_op`` are malformed or inconsistent.
    """
    from better_calendar.calendars.algebra import all_open, any_open
    from better_calendar.calendars.base import Calendar

    declared = spec.get("base")
    op = spec.get("base_op")

    if not declared:
        if op is not None:
            raise BetterCalendarError(
                f"Calendar {name!r} sets 'base_op' but has no 'base' to apply it to. Add a "
                f"'base' listing the calendars to combine, or drop 'base_op'."
            )
        return Calendar(name), None

    if isinstance(declared, str):
        if op is not None:
            raise BetterCalendarError(
                f"Calendar {name!r} sets 'base_op' but its 'base' names a single calendar, "
                f"{declared!r}, so there is nothing to combine. Drop 'base_op', or list "
                f"several calendars under 'base'."
            )
        return _one_base(name, declared), declared

    if not isinstance(declared, (list, tuple)):
        raise BetterCalendarError(
            f"Calendar {name!r} has a 'base' of type {type(declared).__name__}. Give either "
            f"one calendar identifier, or a list of them together with 'base_op'."
        )

    names = [str(item) for item in declared]
    if len(names) < 2:
        raise BetterCalendarError(
            f"Calendar {name!r} lists {len(names)} calendar(s) under 'base'. Combining needs "
            f"at least two; write 'base: {names[0] if names else '<calendar>'}' on its own "
            f"to build on a single one."
        )

    # Required, never defaulted. The two readings of "combine these calendars" are exact
    # opposites -- see the union/intersection trap in calendars.algebra -- and guessing one
    # would silently pick a settlement convention on the caller's behalf.
    if op is None:
        raise BetterCalendarError(
            f"Calendar {name!r} combines {len(names)} calendars under 'base' but does not say "
            f"how. Add 'base_op: all_open' for days that are business days in *every* one "
            f"(the settlement case, closed as soon as any of them closes), or "
            f"'base_op: any_open' for days that are business days in *at least one*."
        )
    if op not in _BASE_OPS:
        raise BetterCalendarError(
            f"Calendar {name!r} has base_op {op!r}, which is not a known operation. Use one "
            f"of {', '.join(_BASE_OPS)}. For 'a but not b' or 'exactly one of a and b', "
            f"compose the calendars in Python, where the operand order is visible."
        )

    operands = [_one_base(name, item) for item in names]
    combined = all_open(operands) if op == "all_open" else any_open(operands)
    separator = " & " if op == "all_open" else " | "
    return combined, separator.join(names)


def _bounds(value: Any, default: tuple[Any, Any]) -> tuple[Any, Any]:
    from datetime import date

    if not value:
        return default
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise BetterCalendarError(
            f"'bounds' must be a two-element list [first, last], got {value!r}."
        )
    return tuple(  # type: ignore[return-value]  # length checked just above
        item if isinstance(item, date) else date.fromisoformat(str(item)) for item in value
    )


def _time(value: Any, default: Any) -> Any:
    from datetime import time

    if value is None:
        return default
    if isinstance(value, time):
        return value
    parts = str(value).split(":")
    if len(parts) not in (2, 3) or not all(part.isdigit() for part in parts):
        raise BetterCalendarError(
            f"'session_start' must look like 'HH:MM' or 'HH:MM:SS', got {value!r}."
        )
    hour, minute, second = (*(int(part) for part in parts), 0)[:3]
    return time(hour, minute, second)
