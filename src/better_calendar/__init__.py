"""better-calendar — one place for date logic.

A calendar is a sorted ``int64`` array of good days over a bounded horizon; membership,
offsets, counting and set algebra are all ``searchsorted`` on that array.

Examples:
    >>> import better_calendar as bcal
    >>> bcal.adjust("2026-05-31", "MF")          # Sunday; rolling forward would leave May
    '2026-05-29'
    >>> bcal.offset("2026-07-31", 5)
    '2026-08-07'
    >>> bcal.count("2026-07-27", "2026-08-01")   # half-open [start, end)
    5

Importing this module does **not** import pandas, and it does not import any holiday
provider (§14). Only ``numpy`` is required.
"""

from __future__ import annotations

from better_calendar.calendars.algebra import all_open, any_open
from better_calendar.calendars.base import Calendar
from better_calendar.calendars.registry import (
    describe,
    get,
    list_calendars,
    register,
    resolve,
    unregister,
)
from better_calendar.config import Config, config
from better_calendar.core.epoch import DEFAULT_BOUNDS, MAX_YEAR, MIN_YEAR
from better_calendar.core.errors import (
    AmbiguousTimezoneError,
    BetterCalendarError,
    NotABusinessDayError,
    OutOfBoundsError,
    ProviderError,
    ScheduleError,
    TenorParseError,
    UnknownCalendarError,
)
from better_calendar.core.range import DateRange
from better_calendar.core.types import to_date, to_datetime, to_timestamp
from better_calendar.functions import (
    adjust,
    count,
    is_bday,
    next_bday,
    offset,
    prev_bday,
    sessions,
)
from better_calendar.offsets.conventions import Roll

#: ``bcal.list()`` deliberately shadows the builtin inside this namespace (§13); the
#: unshadowed name stays available as ``list_calendars`` for callers who dislike that.
list = list_calendars

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_BOUNDS",
    "MAX_YEAR",
    "MIN_YEAR",
    "AmbiguousTimezoneError",
    "BetterCalendarError",
    "Calendar",
    "Config",
    "DateRange",
    "NotABusinessDayError",
    "OutOfBoundsError",
    "ProviderError",
    "Roll",
    "ScheduleError",
    "TenorParseError",
    "UnknownCalendarError",
    "__version__",
    "adjust",
    "all_open",
    "any_open",
    "config",
    "count",
    "describe",
    "get",
    "is_bday",
    "list",
    "list_calendars",
    "next_bday",
    "offset",
    "prev_bday",
    "register",
    "resolve",
    "sessions",
    "to_date",
    "to_datetime",
    "to_timestamp",
    "unregister",
]
