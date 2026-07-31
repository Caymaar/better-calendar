"""Exception hierarchy (CLAUDE.md §11).

Every error states **what was wrong** and **what the caller should do**. No bare
``ValueError`` is raised from a public code path.

    BetterCalendarError
    ├── OutOfBoundsError
    ├── AmbiguousTimezoneError
    ├── UnknownCalendarError
    ├── NotABusinessDayError
    ├── TenorParseError
    ├── ScheduleError
    └── ProviderError
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable, Sequence
from datetime import date

__all__ = [
    "AmbiguousTimezoneError",
    "BetterCalendarError",
    "NotABusinessDayError",
    "OutOfBoundsError",
    "ProviderError",
    "ScheduleError",
    "TenorParseError",
    "UnknownCalendarError",
]


class BetterCalendarError(Exception):
    """Base class for everything ``better_calendar`` raises.

    Catching this catches every library-originated failure and nothing else.

    Examples:
        >>> issubclass(OutOfBoundsError, BetterCalendarError)
        True
    """


class OutOfBoundsError(BetterCalendarError):
    """A date fell outside a calendar's finite bounds (I2). Never extrapolate.

    Examples:
        >>> from datetime import date
        >>> raise OutOfBoundsError.for_date(
        ...     date(2040, 1, 1), (date(2020, 1, 1), date(2030, 12, 31)), "desk:paris"
        ... )
        Traceback (most recent call last):
        ...
        better_calendar.core.errors.OutOfBoundsError: 2040-01-01 is outside the bounds
        of calendar 'desk:paris' (2020-01-01 to 2030-12-31, inclusive). Rebuild the
        calendar with wider `bounds`, or raise MAX_YEAR in better_calendar.core.epoch.
    """

    @classmethod
    def for_date(
        cls,
        value: object,
        bounds: tuple[date, date],
        calendar_name: str,
    ) -> OutOfBoundsError:
        """Build the error for a single offending value."""
        return cls(
            f"{value} is outside the bounds of calendar {calendar_name!r} "
            f"({bounds[0].isoformat()} to {bounds[1].isoformat()}, inclusive). "
            f"Rebuild the calendar with wider `bounds`, or raise MAX_YEAR in "
            f"better_calendar.core.epoch."
        )

    @classmethod
    def for_offset(
        cls,
        n: object,
        bounds: tuple[date, date],
        calendar_name: str,
    ) -> OutOfBoundsError:
        """Build the error for an offset that walked off the end of the good-day array."""
        return cls(
            f"Offsetting by {n} business days leaves the bounds of calendar "
            f"{calendar_name!r} ({bounds[0].isoformat()} to {bounds[1].isoformat()}). "
            f"Use a smaller offset, or rebuild the calendar with wider `bounds`."
        )


class AmbiguousTimezoneError(BetterCalendarError):
    """An aware input was given with no timezone to project it onto a calendar day (I4).

    Examples:
        >>> raise AmbiguousTimezoneError.for_value("2026-07-31 23:30+00:00")
        Traceback (most recent call last):
        ...
        better_calendar.core.errors.AmbiguousTimezoneError: '2026-07-31 23:30+00:00' is
        timezone-aware, so it denotes an instant rather than a calendar day, and the day
        it falls on depends on the timezone you read it in. Pass `tz=...`, use a calendar
        that declares a `tz`, or set better_calendar.config.default_tz.
    """

    @classmethod
    def for_value(cls, value: object) -> AmbiguousTimezoneError:
        """Build the error for an aware value that could not be resolved."""
        return cls(
            f"{value!r} is timezone-aware, so it denotes an instant rather than a "
            f"calendar day, and the day it falls on depends on the timezone you read it "
            f"in. Pass `tz=...`, use a calendar that declares a `tz`, or set "
            f"better_calendar.config.default_tz."
        )


class UnknownCalendarError(BetterCalendarError):
    """A calendar identifier could not be resolved, with did-you-mean suggestions.

    Examples:
        >>> raise UnknownCalendarError.for_name("weekdya", ["weekday", "crypto:24x7"])
        Traceback (most recent call last):
        ...
        better_calendar.core.errors.UnknownCalendarError: Unknown calendar 'weekdya'.
        Did you mean: 'weekday'? Use better_calendar.list() to see everything available.
    """

    @classmethod
    def for_name(cls, name: str, known: Iterable[str]) -> UnknownCalendarError:
        """Build the error, appending close matches from ``known``."""
        matches = difflib.get_close_matches(name, sorted(known), n=3, cutoff=0.6)
        hint = (
            f"Did you mean: {', '.join(repr(m) for m in matches)}? "
            if matches
            else "No similar name is registered. "
        )
        return cls(
            f"Unknown calendar {name!r}. {hint}"
            f"Use better_calendar.list() to see everything available."
        )


class NotABusinessDayError(BetterCalendarError):
    """``Roll.RAISE`` was requested and the date is not a good day.

    Examples:
        >>> from datetime import date
        >>> raise NotABusinessDayError.for_dates([date(2026, 8, 1)], "weekday")
        Traceback (most recent call last):
        ...
        better_calendar.core.errors.NotABusinessDayError: 2026-08-01 is not a business
        day in calendar 'weekday' and roll=Roll.RAISE forbids adjusting it. Pass a
        different roll convention (for example Roll.MODIFIED_FOLLOWING) to move it to a
        nearby business day.
    """

    @classmethod
    def for_dates(cls, values: Sequence[object], calendar_name: str) -> NotABusinessDayError:
        """Build the error, naming at most three offending dates."""
        shown = ", ".join(str(v) for v in values[:3])
        more = f" (and {len(values) - 3} more)" if len(values) > 3 else ""
        return cls(
            f"{shown}{more} is not a business day in calendar {calendar_name!r} and "
            f"roll=Roll.RAISE forbids adjusting it. Pass a different roll convention "
            f"(for example Roll.MODIFIED_FOLLOWING) to move it to a nearby business day."
        )


class TenorParseError(BetterCalendarError):
    """A tenor string did not match the grammar of §7.3, showing the offending part."""

    @classmethod
    def for_text(cls, text: str, offending: str, reason: str) -> TenorParseError:
        """Build the error, highlighting ``offending`` inside ``text``."""
        return cls(
            f"Cannot parse tenor {text!r}: {reason} at {offending!r}. "
            f"Expected terms like '3M', '2B', '-1Y+2B' with units D, B, W, M or Y."
        )


class ScheduleError(BetterCalendarError):
    """A schedule was requested with an inconsistent stub/frequency combination."""


class ProviderError(BetterCalendarError):
    """An optional upstream is missing or failed, with the install hint to fix it.

    Examples:
        >>> raise ProviderError.missing_dependency("pandas", "pandas", "DatetimeIndex output")
        Traceback (most recent call last):
        ...
        better_calendar.core.errors.ProviderError: DatetimeIndex output needs the
        'pandas' package, which is not installed. Install it with:
        pip install 'better-calendar[pandas]'
    """

    @classmethod
    def missing_dependency(
        cls,
        package: str,
        extra: str,
        feature: str,
        cause: BaseException | None = None,
    ) -> ProviderError:
        """Build the error for a missing optional dependency."""
        error = cls(
            f"{feature} needs the {package!r} package, which is not installed. "
            f"Install it with: pip install 'better-calendar[{extra}]'"
        )
        if cause is not None:
            error.__cause__ = cause
        return error
