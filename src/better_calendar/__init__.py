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
    add_tenor,
    adjust,
    count,
    is_bday,
    next_bday,
    offset,
    prev_bday,
    sessions,
    spot,
)
from better_calendar.offsets.bday import BDay
from better_calendar.offsets.conventions import Roll
from better_calendar.offsets.spot import SPOT_LAG, spot_lag
from better_calendar.offsets.tenor import Tenor, parse_tenor
from better_calendar.schedule.generators import (
    imm_dates,
    month_ends,
    option_expiries,
    quarter_ends,
    year_ends,
)
from better_calendar.schedule.recurrence import (
    FRI,
    MON,
    SAT,
    SUN,
    THU,
    TUE,
    WED,
    Weekday,
    last_weekday,
    nth_business_day,
    nth_day,
    nth_weekday,
)
from better_calendar.schedule.schedule import periods, schedule
from better_calendar.schedule.selector import EDGES, Nth, parse_selector
from better_calendar.sessions.session import at_times, session_bounds, session_of

#: ``bcal.list()`` deliberately shadows the builtin inside this namespace (§13); the
#: unshadowed name stays available as ``list_calendars`` for callers who dislike that.
list = list_calendars

__version__ = "1.0.1"

__all__ = [
    "DEFAULT_BOUNDS",
    "EDGES",
    "FRI",
    "MAX_YEAR",
    "MIN_YEAR",
    "MON",
    "SAT",
    "SPOT_LAG",
    "SUN",
    "THU",
    "TUE",
    "WED",
    "AmbiguousTimezoneError",
    "BDay",
    "BetterCalendarError",
    "Calendar",
    "Config",
    "DateRange",
    "NotABusinessDayError",
    "Nth",
    "OutOfBoundsError",
    "ProviderError",
    "Roll",
    "ScheduleError",
    "Tenor",
    "TenorParseError",
    "UnknownCalendarError",
    "Weekday",
    "__version__",
    "add_tenor",
    "adjust",
    "all_open",
    "any_open",
    "at_times",
    "config",
    "count",
    "describe",
    "get",
    "imm_dates",
    "is_bday",
    "last_weekday",
    "list",
    "list_calendars",
    "month_ends",
    "next_bday",
    "nth_business_day",
    "nth_day",
    "nth_weekday",
    "offset",
    "option_expiries",
    "parse_selector",
    "parse_tenor",
    "periods",
    "prev_bday",
    "quarter_ends",
    "register",
    "resolve",
    "schedule",
    "session_bounds",
    "session_of",
    "sessions",
    "spot",
    "spot_lag",
    "to_date",
    "to_datetime",
    "to_timestamp",
    "unregister",
    "year_ends",
]
