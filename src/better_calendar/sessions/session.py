"""Intraday-lite: attributing instants to calendar days (§9).

This is **not** a session engine, and deliberately so. What it does is answer the one
question that turns out to matter constantly: *which calendar day does this instant belong
to?* A calendar day is the interval ``[session_start, session_start + 24h)`` expressed in
the calendar's timezone — local midnight for ordinary calendars, ``00:00`` UTC for crypto,
``17:00`` New York for FX. One field, no complexity.

That single definition covers the bulk of real intraday-adjacent work: funding times,
expiry attribution, which trading day a fill belongs to, where a daily bar starts and
ends. It is also the answer to the timezone trap in §10 — ``ts.date()`` on an aware
timestamp silently answers in whatever zone the timestamp happens to carry, while
:func:`session_of` makes you say which frame you mean.

**What is deliberately missing**: ``is_open``, ``next_open``, ``next_close``, lunch
breaks, early closes, trading-minute indexes. §9.3 is explicit that ``is_open()`` must not
exist on the day calendar returning ``is_bday()`` — that is false for any exchange with
trading hours, and it would be discovered the hard way. The split is expressed here as two
protocols: :class:`DayCalendar`, which :class:`~better_calendar.calendars.base.Calendar`
satisfies today, and :class:`SessionCalendar`, which nothing satisfies yet.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING, Any

import numpy as np

from better_calendar.calendars.registry import CalendarLike, resolve
from better_calendar.core._pandas import require_pandas
from better_calendar.core.epoch import date_to_days, days_to_date
from better_calendar.core.errors import AmbiguousTimezoneError, BetterCalendarError
from better_calendar.core.types import (
    DateLike,
    Kind,
    days_to_index,
    kind_of,
    to_date,
    to_datetime,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from typing import Protocol

    from better_calendar.calendars.base import Calendar

    class DayCalendar(Protocol):
        """What a calendar answers about whole days. Satisfied today.

        Everything in v1 is expressed against this protocol.
        """

        def is_bday(self, value: Any, *, tz: str | None = ...) -> Any:
            """Whether each date is a business day."""
            ...

        def session_of(self, value: Any, *, tz: str | None = ...) -> Any:
            """Which calendar day an instant belongs to."""
            ...

    class SessionCalendar(DayCalendar, Protocol):
        """What a calendar would answer about trading hours. Satisfied by nothing.

        Reserved so that ``is_open`` never lands on :class:`DayCalendar` meaning
        ``is_bday`` — the two are different questions and conflating them is wrong for
        every exchange that has an opening bell (§9.3). When this is needed, adapt
        ``exchange-calendars`` behind it.
        """

        def is_open(self, instant: Any) -> Any:
            """Whether the market is actually trading at this instant."""
            ...


__all__ = ["at_times", "grid", "session_bounds", "session_of"]

#: Units accepted by :func:`grid`, as seconds. ``min`` rather than ``m`` on purpose:
#: pandas learned the hard way that ``m`` reads as "month" to half its users.
_STEP_UNITS = {"h": 3600, "min": 60, "s": 1}

_UTC = timezone.utc


def _zone(name: str) -> Any:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise BetterCalendarError(
            f"Unknown timezone {name!r}. Use an IANA name such as 'Europe/Paris'. "
            f"On systems without a tz database, install the 'tzdata' package."
        ) from exc


def _resolve_zone(calendar: Calendar, tz: str | None, what: str) -> str:
    """The timezone to read instants in, or an actionable refusal."""
    from better_calendar.config import config

    chosen = tz or calendar.tz or config.default_tz
    if chosen is None:
        raise AmbiguousTimezoneError(
            f"{what} needs a timezone: calendar {calendar.name!r} declares none, so there "
            f"is no frame to read an instant in. Pass tz=..., use a calendar that has one, "
            f"or set better_calendar.config.default_tz. A composite calendar loses its "
            f"timezone when its operands disagree, which is usually the cause."
        )
    return chosen


def session_of(value: Any, *, cal: CalendarLike = None, tz: str | None = None) -> Any:
    """The calendar day an instant belongs to.

    A day runs from :attr:`~better_calendar.calendars.base.Calendar.session_start` for
    twenty-four hours, so with an FX-style ``17:00`` start an instant at 09:00 belongs to
    the session that opened the previous evening.

    Naive inputs are read literally in the resolved timezone (I3); aware ones are
    converted into it first (I4). Either way the timezone has to come from somewhere —
    the argument, the calendar, or the global default — and there is no silent fallback.

    Args:
        value: An instant, or a sequence of them.
        cal: The calendar whose session definition applies; ``None`` for ``weekday``,
            which declares no timezone and so requires ``tz``.
        tz: Timezone to read instants in; defaults to the calendar's own.

    Returns:
        A :class:`datetime.date` for a scalar, a ``DatetimeIndex`` for a sequence. The
        result is a *day label*, not an instant, so it is deliberately not timezone-aware.

    Raises:
        AmbiguousTimezoneError: If no timezone can be resolved.

    Examples:
        >>> from better_calendar import Calendar
        >>> import pandas as pd
        >>> ts = pd.Timestamp("2026-07-31 23:30", tz="UTC")   # Friday in UTC
        >>> session_of(ts, cal=Calendar("utc", tz="UTC"))
        datetime.date(2026, 7, 31)
        >>> session_of(ts, cal=Calendar("paris", tz="Europe/Paris"))   # Saturday there
        datetime.date(2026, 8, 1)
        >>> fx = Calendar("fx", tz="America/New_York", session_start=time(17, 0))
        >>> session_of(pd.Timestamp("2026-07-31 09:00", tz="America/New_York"), cal=fx)
        datetime.date(2026, 7, 30)
    """
    calendar = resolve(cal)
    zone = _resolve_zone(calendar, tz, "session_of")
    if kind_of(value) is Kind.SEQ:
        days = np.fromiter(
            (date_to_days(_session_day(item, zone, calendar.session_start)) for item in value),
            dtype=np.int64,
            count=len(value),
        )
        return days_to_index(days)
    return _session_day(value, zone, calendar.session_start)


def _session_day(value: Any, zone: str, session_start: time) -> date:
    """One instant's session day, in ``zone``."""
    moment = to_datetime(value, tz=zone)
    if moment.tzinfo is not None:
        moment = moment.astimezone(_zone(zone))
    local = moment.replace(tzinfo=None)
    # The session that contains this instant opened at the most recent session_start.
    if local.time() < session_start:
        return (local - timedelta(days=1)).date()
    return local.date()


def session_bounds(day: DateLike, *, cal: CalendarLike = None, tz: str | None = None) -> Any:
    """The half-open UTC interval a calendar day covers.

    Across a daylight-saving transition the interval is twenty-three or twenty-five hours
    long. That is not a bug to be normalised away: the session really is shorter or longer
    that day, and code that assumes 24h is the code this function exists to correct.

    Args:
        day: The calendar day.
        cal: The calendar whose session definition applies; ``None`` for ``weekday``.
        tz: Timezone the session is defined in; defaults to the calendar's own.

    Returns:
        ``(start, end)`` as UTC ``pandas.Timestamp`` objects, half-open ``[start, end)``.

    Raises:
        AmbiguousTimezoneError: If no timezone can be resolved.
        ProviderError: If pandas is not installed.

    Examples:
        >>> from better_calendar import Calendar
        >>> paris = Calendar("paris", tz="Europe/Paris")
        >>> first, last = session_bounds("2026-07-31", cal=paris)
        >>> str(first), str(last)
        ('2026-07-30 22:00:00+00:00', '2026-07-31 22:00:00+00:00')
        >>> # The spring transition makes this session an hour short.
        >>> first, last = session_bounds("2026-03-29", cal=paris)
        >>> last - first
        Timedelta('0 days 23:00:00')
    """
    pandas = require_pandas("session_bounds()")
    calendar = resolve(cal)
    zone = _resolve_zone(calendar, tz, "session_bounds")
    info = _zone(zone)
    first_day = to_date(day)
    opens = datetime.combine(first_day, calendar.session_start, tzinfo=info)
    closes = datetime.combine(
        first_day + timedelta(days=1), calendar.session_start, tzinfo=info
    )
    return (
        pandas.Timestamp(opens.astimezone(_UTC)),
        pandas.Timestamp(closes.astimezone(_UTC)),
    )


def _parse_step(text: str) -> timedelta:
    """Parse a grid step such as ``"4h"``, ``"15min"`` or ``"30s"``."""
    cleaned = text.strip().lower()
    for unit in ("min", "h", "s"):
        if cleaned.endswith(unit):
            number = cleaned[: -len(unit)].strip() or "1"
            try:
                amount = int(number)
            except ValueError as exc:
                raise BetterCalendarError(
                    f"Cannot parse grid step {text!r}: {number!r} is not a whole number. "
                    f"Use forms like '4h', '15min' or '30s'."
                ) from exc
            if amount <= 0:
                raise BetterCalendarError(
                    f"Cannot use grid step {text!r}: it must be positive, since zero or "
                    f"less would never advance."
                )
            return timedelta(seconds=amount * _STEP_UNITS[unit])
    raise BetterCalendarError(
        f"Cannot parse grid step {text!r}. Use a whole number followed by 'h', 'min' or "
        f"'s', for example '4h'. Minutes are spelled 'min' so that 'm' cannot be read as "
        f"months."
    )


def grid(
    start: DateLike,
    end: DateLike,
    step: str,
    *,
    cal: CalendarLike = None,
    tz: str | None = None,
) -> Any:
    """Regular timestamps inside each session, anchored on ``session_start``.

    This is the function that prevents the classic mis-anchored resample. A four-hour grid
    built by pandas from UTC midnight cuts a Tokyo or New York session in the wrong places;
    one built here begins each session at its own opening instant, which is what a bar
    boundary is supposed to mean.

    Only sessions — the calendar's business days — are covered, so an exchange grid has no
    points at the weekend, and a ``crypto:24x7`` grid is continuous. Each session is filled
    independently, so a daylight-saving transition shortens or lengthens that one session
    instead of shifting every later point.

    Args:
        start: First day to cover.
        end: Last day to cover, inclusive.
        step: Grid step — ``"4h"``, ``"15min"``, ``"30s"``.
        cal: The calendar whose sessions are gridded; ``None`` for ``weekday``.
        tz: Timezone the sessions are defined in; defaults to the calendar's own.

    Returns:
        A UTC-aware ``DatetimeIndex``.

    Raises:
        AmbiguousTimezoneError: If no timezone can be resolved.
        ProviderError: If pandas is not installed.

    Examples:
        >>> from better_calendar import Calendar
        >>> paris = Calendar("paris", tz="Europe/Paris")
        >>> list(grid("2026-07-31", "2026-07-31", "6h", cal=paris).strftime("%m-%d %H:%M%z"))
        ['07-30 22:00+0000', '07-31 04:00+0000', '07-31 10:00+0000', '07-31 16:00+0000']
        >>> # A weekend has no sessions, so the grid simply skips it.
        >>> len(grid("2026-08-01", "2026-08-02", "6h", cal=paris))
        0
    """
    pandas = require_pandas("grid()")
    calendar = resolve(cal)
    zone = _resolve_zone(calendar, tz, "grid")
    width = _parse_step(step)

    first, last = to_date(start), to_date(end)
    sessions = calendar.good_days(first, last)
    points: list[Any] = []
    for day_number in sessions.tolist():
        opens, closes = session_bounds(days_to_date(day_number), cal=calendar, tz=zone)
        moment = opens
        while moment < closes:
            points.append(moment)
            moment = moment + width
    return pandas.DatetimeIndex(points, tz="UTC")


def at_times(
    days: Iterable[DateLike],
    times: Sequence[str],
    *,
    tz: str = "UTC",
) -> Any:
    """Cross a set of days with a set of times of day.

    The companion to the recurrence rules: generate the days with
    :func:`~better_calendar.schedule.recurrence.nth_weekday` and friends, then attach the
    times a process actually runs at.

    Args:
        days: The days, typically a ``DatetimeIndex`` from a recurrence function.
        times: Times of day as ``"HH:MM"`` or ``"HH:MM:SS"``.
        tz: IANA timezone the times are expressed in.

    Returns:
        A timezone-aware ``DatetimeIndex``, sorted, one entry per day and time.

    Raises:
        BetterCalendarError: If a time cannot be parsed.
        ProviderError: If pandas is not installed.

    Examples:
        >>> import better_calendar as bcal
        >>> fixings = at_times(bcal.imm_dates("2026-01-01", "2026-06-30"), ["08:00", "16:00"])
        >>> list(fixings.strftime("%Y-%m-%d %H:%M%z"))
        ['2026-03-18 08:00+0000', '2026-03-18 16:00+0000',
         '2026-06-17 08:00+0000', '2026-06-17 16:00+0000']
    """
    pandas = require_pandas("at_times()")
    parsed = [_parse_time(text) for text in times]
    if not parsed:
        raise BetterCalendarError(
            "at_times() needs at least one time of day. Pass something like ['08:00']."
        )
    info = _zone(tz)
    moments = [
        datetime.combine(to_date(day), moment, tzinfo=info) for day in days for moment in parsed
    ]
    return pandas.DatetimeIndex(sorted(moments)).tz_convert(tz)


def _parse_time(text: str) -> time:
    """Parse ``"HH:MM"`` or ``"HH:MM:SS"``."""
    parts = str(text).strip().split(":")
    if len(parts) not in (2, 3) or not all(part.isdigit() for part in parts):
        raise BetterCalendarError(
            f"Cannot parse time of day {text!r}. Use 'HH:MM' or 'HH:MM:SS'."
        )
    hour, minute, second = (*(int(part) for part in parts), 0)[:3]
    try:
        return time(hour, minute, second)
    except ValueError as exc:
        raise BetterCalendarError(f"Invalid time of day {text!r}: {exc}.") from exc
