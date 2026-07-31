"""The library's only global state (§10).

``better_calendar`` refuses to guess a timezone for an aware input. That strictness
is correct but occasionally unwanted — a service that has already decided everything
is UTC does not want to thread ``tz="UTC"`` through every call. :data:`config` is the
documented, opt-in escape hatch, and the only mutable module-level state permitted
anywhere in the package.

Examples:
    >>> from better_calendar import config
    >>> config.default_tz is None            # off by default
    True
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Config", "config"]


@dataclass
class Config:
    """Process-wide defaults.

    Attributes:
        default_tz: IANA timezone used to project aware inputs onto a calendar day
            when neither the caller nor the calendar supplies one. ``None`` (the
            default) means such inputs raise
            :class:`~better_calendar.core.errors.AmbiguousTimezoneError` instead.

    Examples:
        >>> cfg = Config()
        >>> cfg.default_tz = "UTC"
        >>> cfg.default_tz
        'UTC'
    """

    default_tz: str | None = None


#: The process-wide configuration singleton.
config = Config()
