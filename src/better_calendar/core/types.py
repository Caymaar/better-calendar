"""Input conversion and output type preservation (§4), and the timezone policy (§10).

Timezone policy — the rule, in three lines:

1. **Naive means "already in the right frame."** The date part is taken literally; no
   conversion is performed.
2. **Aware means "an instant."** Projecting it onto a calendar day requires an explicit
   timezone — the calendar's, or one passed by the caller. A bare ``to_date(aware)``
   raises :class:`~better_calendar.core.errors.AmbiguousTimezoneError`.
3. **Offsets preserve wall-clock time and tzinfo.** They touch only the date part.
   ``datetime(2026,3,27,9,0,tz=Paris) + BDay(1)`` -> ``2026-03-30 09:00 Paris`` (which is
   +23h in absolute terms — that is correct and intended).

A global escape hatch exists for callers who don't want the strictness:
``bcal.config.default_tz = "UTC"`` (module-level, documented as opt-in, off by default).
This is the *only* piece of global state permitted in the library.

Type preservation lives here and nowhere else. :func:`to_days` collapses any supported
input to ``int64`` epoch days; :func:`from_days` rebuilds the caller's original type from
a day number plus the original object. Do not scatter ``isinstance`` ladders through the
rest of the codebase — extend :func:`kind_of` instead.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any, Union, cast, overload

import numpy as np
from numpy.typing import NDArray

from better_calendar._compat import StrEnum
from better_calendar.config import config
from better_calendar.core._pandas import (
    is_pandas_object,
    loaded_pandas,
    optional_pandas,
    require_pandas,
)
from better_calendar.core.epoch import date_to_days, days_to_date, days_to_datetime64
from better_calendar.core.errors import AmbiguousTimezoneError, BetterCalendarError

__all__ = [
    "DateLike",
    "DateSeqLike",
    "Kind",
    "from_days",
    "kind_of",
    "to_date",
    "to_datetime",
    "to_days",
    "to_timestamp",
]

# Runtime type aliases must be written with `Union`: PEP 604 syntax is evaluated eagerly
# here (it is not an annotation), and `date | datetime` is a TypeError before 3.10.
DateLike = Union[date, datetime, "np.datetime64", str, int]
# `Iterable` rather than only `Sequence`, so that `pandas.DatetimeIndex` and
# `pandas.Series` — the two containers callers reach for most — are accepted statically.
# It also matches `str`, which is why the scalar overload of `to_days` is declared first.
DateSeqLike = Union[Sequence[Any], Iterable[Any], "np.ndarray[Any, Any]"]

#: ISO-8601 subset we accept. Deliberately strict: `DD/MM/YYYY` and `MM/DD/YYYY` are
#: rejected because there is no way to tell them apart, and a wrong guess is silent.
#: Hand-rolled rather than delegated to `datetime.fromisoformat` because that function's
#: accepted grammar widened in 3.11 — we want one grammar on every supported Python.
_ISO_RE = re.compile(
    r"^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})"
    r"(?:[T ](?P<hour>\d{2}):(?P<minute>\d{2})"
    r"(?::(?P<second>\d{2})(?:\.(?P<micro>\d{1,6})\d*)?)?"
    r"(?P<tz>Z|z|[+-]\d{2}:?\d{2})?)?$"
)
_COMPACT_RE = re.compile(r"^(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})$")

#: ``datetime64`` units ordered coarse to fine. Anything coarser than a day cannot carry
#: a time of day, so results for those inputs come back as ``datetime64[D]``.
_UNITS_COARSER_THAN_DAY = frozenset({"Y", "M", "W"})


class Kind(StrEnum):
    """What a caller handed us, and therefore what we must hand back (I6).

    Examples:
        >>> kind_of(date(2026, 7, 31))
        <Kind.DATE: 'date'>
        >>> kind_of("2026-07-31")
        <Kind.STR: 'str'>
    """

    DATE = "date"
    DATETIME = "datetime"
    TIMESTAMP = "timestamp"
    NP = "np"
    STR = "str"
    INT = "int"
    SEQ = "seq"


def kind_of(value: object) -> Kind:
    """Classify an input for the purposes of type preservation.

    Args:
        value: Any supported date-like scalar or sequence.

    Returns:
        The :class:`Kind` describing it.

    Raises:
        BetterCalendarError: If the type is not supported.

    Examples:
        >>> kind_of(datetime(2026, 7, 31, 9, 30))
        <Kind.DATETIME: 'datetime'>
        >>> kind_of(20260731)
        <Kind.INT: 'int'>
        >>> kind_of([date(2026, 7, 31)])
        <Kind.SEQ: 'seq'>
    """
    # pandas Timestamp subclasses datetime, so it has to be tested first. The check is
    # free when pandas has never been imported (see core._pandas).
    if is_pandas_object(value, "Timestamp"):
        return Kind.TIMESTAMP
    if is_pandas_object(value, "DatetimeIndex", "Series", "Index"):
        return Kind.SEQ
    if isinstance(value, np.datetime64):
        return Kind.NP
    if isinstance(value, np.ndarray):
        return Kind.NP if value.ndim == 0 else Kind.SEQ
    if isinstance(value, datetime):
        return Kind.DATETIME
    if isinstance(value, date):
        return Kind.DATE
    if isinstance(value, str):
        return Kind.STR
    # bool is a subclass of int; `True` as a date is always a mistake.
    if isinstance(value, bool):
        raise BetterCalendarError(
            "bool is not a date. Pass a date, datetime, ISO-8601 string or a yyyymmdd int."
        )
    if isinstance(value, (int, np.integer)):
        return Kind.INT
    if isinstance(value, (list, tuple, range)) or (
        hasattr(value, "__iter__") and hasattr(value, "__len__")
    ):
        return Kind.SEQ
    raise BetterCalendarError(
        f"Cannot interpret {type(value).__name__} as a date. Supported inputs are "
        f"datetime.date, datetime.datetime, pandas.Timestamp, numpy.datetime64, "
        f"ISO-8601 strings, yyyymmdd ints, and sequences of those."
    )


# ---------------------------------------------------------------------------
# Timezone resolution
# ---------------------------------------------------------------------------


def _zone(name: str) -> tzinfo:
    """Look up an IANA zone, with an actionable error if the tz database is missing."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise BetterCalendarError(
            f"Unknown timezone {name!r}. Use an IANA name such as 'Europe/Paris'. "
            f"On systems without a tz database, install the 'tzdata' package."
        ) from exc


def _resolve_tz(tz: str | None) -> str | None:
    """Caller-supplied timezone, falling back to the opt-in global default (§10)."""
    return tz if tz is not None else config.default_tz


def _project_aware(value: datetime, tz: str | None) -> date:
    """Project an aware instant onto a calendar day in ``tz`` (I4 — never bare .date())."""
    resolved = _resolve_tz(tz)
    if resolved is None:
        raise AmbiguousTimezoneError.for_value(value.isoformat())
    shifted = value.astimezone(_zone(resolved))
    return date(shifted.year, shifted.month, shifted.day)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _parse_string(text: str) -> datetime:
    """Parse the accepted ISO-8601 subset, or the compact ``yyyymmdd`` form.

    Returns a ``datetime`` whose ``tzinfo`` is set only if the text carried an offset.
    """
    compact = _COMPACT_RE.match(text)
    if compact is not None:
        return datetime(int(compact["year"]), int(compact["month"]), int(compact["day"]))
    match = _ISO_RE.match(text)
    if match is None:
        raise BetterCalendarError(
            f"Cannot parse date string {text!r}. Accepted formats are ISO-8601 "
            f"('2026-07-31', '2026-07-31T14:30:00+02:00') and the compact form "
            f"'20260731'. Ambiguous formats like DD/MM/YYYY and MM/DD/YYYY are rejected "
            f"on purpose — convert them yourself so the intended order is explicit."
        )
    offset = match["tz"]
    tzinfo_value: timezone | None = None
    if offset is not None:
        if offset in ("Z", "z"):
            tzinfo_value = timezone.utc
        else:
            sign = 1 if offset[0] == "+" else -1
            digits = offset[1:].replace(":", "")
            minutes = sign * (int(digits[:2]) * 60 + int(digits[2:]))
            tzinfo_value = timezone(timedelta(minutes=minutes))
    try:
        return datetime(
            int(match["year"]),
            int(match["month"]),
            int(match["day"]),
            int(match["hour"] or 0),
            int(match["minute"] or 0),
            int(match["second"] or 0),
            int((match["micro"] or "").ljust(6, "0") or 0),
            tzinfo=tzinfo_value,
        )
    except ValueError as exc:
        raise BetterCalendarError(f"Invalid date string {text!r}: {exc}.") from exc


def _parse_int(value: int) -> date:
    """Interpret an int as ``yyyymmdd``, rejecting anything that is not one."""
    number = int(value)
    match = _COMPACT_RE.match(str(number))
    if match is None:
        raise BetterCalendarError(
            f"Cannot interpret {number} as a date. Ints are read as yyyymmdd "
            f"(for example 20260731); this guards against Unix timestamps being passed "
            f"by accident. Pass a datetime.date or an ISO-8601 string instead."
        )
    try:
        return date(int(match["year"]), int(match["month"]), int(match["day"]))
    except ValueError as exc:
        raise BetterCalendarError(f"Invalid yyyymmdd int {number}: {exc}.") from exc


# ---------------------------------------------------------------------------
# to_days
# ---------------------------------------------------------------------------


def _scalar_to_days(value: object, kind: Kind, tz: str | None) -> int:
    """Collapse a supported scalar to epoch days, applying the §10 timezone policy."""
    if kind is Kind.STR:
        value = _parse_string(str(value))
        kind = Kind.DATETIME
    elif kind is Kind.INT:
        return date_to_days(_parse_int(cast(int, value)))

    if kind is Kind.NP:
        as_day = np.asarray(value, dtype="datetime64[D]")
        if np.isnat(as_day):
            raise BetterCalendarError(
                "NaT is not a date. Filter missing values out before calling into "
                "better_calendar, so that the gap stays visible in your own code."
            )
        return int(as_day.astype(np.int64))

    if kind in (Kind.DATETIME, Kind.TIMESTAMP):
        moment: datetime = value  # type: ignore[assignment]  # narrowed by kind
        if moment.tzinfo is not None:
            return date_to_days(_project_aware(moment, tz))
        # Naive is a label, not an instant (I3): take the date part literally.
        return date_to_days(date(moment.year, moment.month, moment.day))

    if kind is Kind.DATE:
        return date_to_days(cast(date, value))

    raise BetterCalendarError(f"{kind} is not a scalar kind.")


def _seq_to_days(value: object, tz: str | None) -> NDArray[np.int64]:
    """Vectorised conversion for sequences, with fast paths for the array types."""
    pandas = loaded_pandas()
    if pandas is not None and isinstance(value, (pandas.Series, pandas.Index)):
        index = pandas.DatetimeIndex(value)
        if index.tz is not None:
            resolved = _resolve_tz(tz)
            if resolved is None:
                raise AmbiguousTimezoneError.for_value(f"{type(value).__name__}[tz={index.tz}]")
            index = index.tz_convert(resolved).tz_localize(None)
        if index.hasnans:
            raise BetterCalendarError(
                "NaT is not a date. Filter missing values out before calling into "
                "better_calendar, so that the gap stays visible in your own code."
            )
        return np.ascontiguousarray(index.values.astype("datetime64[D]")).view(np.int64)

    if isinstance(value, np.ndarray) and np.issubdtype(value.dtype, np.datetime64):
        as_days = value.astype("datetime64[D]")
        if np.isnat(as_days).any():
            raise BetterCalendarError(
                "NaT is not a date. Filter missing values out before calling into "
                "better_calendar, so that the gap stays visible in your own code."
            )
        return np.ascontiguousarray(as_days).view(np.int64)

    items = list(cast("Sequence[Any]", value))
    if not items:
        return np.empty(0, dtype=np.int64)
    return np.fromiter(
        (_scalar_to_days(item, kind_of(item), tz) for item in items),
        dtype=np.int64,
        count=len(items),
    )


@overload
def to_days(value: DateLike, *, tz: str | None = ...) -> np.int64: ...
@overload
def to_days(value: DateSeqLike, *, tz: str | None = ...) -> NDArray[np.int64]: ...


def to_days(
    value: DateLike | DateSeqLike, *, tz: str | None = None
) -> np.int64 | NDArray[np.int64]:
    """Collapse any supported input to ``int64`` days since 1970-01-01.

    Scalars return a ``numpy.int64``; sequences return an ``int64`` array. Naive inputs
    are read literally (I3); aware inputs are projected onto a calendar day in ``tz``,
    falling back to :data:`better_calendar.config.default_tz` (I4).

    Args:
        value: A date-like scalar or a sequence of them.
        tz: IANA timezone used to project aware inputs. Ignored for naive inputs.

    Returns:
        Epoch day numbers.

    Raises:
        AmbiguousTimezoneError: If the input is aware and no timezone is available.
        BetterCalendarError: If the input cannot be interpreted as a date.

    Examples:
        >>> int(to_days("2026-07-31"))
        20665
        >>> to_days([date(2026, 7, 31), 20260801])
        array([20665, 20666])
        >>> int(to_days("2026-07-31T23:30:00+00:00", tz="Europe/Paris"))  # next day there
        20666
    """
    kind = kind_of(value)
    if kind is Kind.SEQ:
        return _seq_to_days(value, tz)
    return np.int64(_scalar_to_days(value, kind, tz))


# ---------------------------------------------------------------------------
# from_days
# ---------------------------------------------------------------------------


def _numpy_from_days(days: int, like: np.datetime64) -> np.datetime64:
    """Rebuild a ``datetime64``, preserving the original unit and time of day (I5)."""
    unit = np.datetime_data(like.dtype)[0]
    day = np.datetime64(int(days), "D")
    if unit in _UNITS_COARSER_THAN_DAY or unit == "D":
        return day if unit == "D" else day.astype(like.dtype)
    time_of_day = like - like.astype("datetime64[D]").astype(like.dtype)
    return np.datetime64(day.astype(like.dtype) + time_of_day)


def _string_from_days(days: int, like: str) -> str:
    """Rebuild a string in the same shape the caller used."""
    if _COMPACT_RE.match(like):
        return days_to_date(days).strftime("%Y%m%d")
    parsed = _parse_string(like)
    result_date = days_to_date(days)
    if parsed.time() == datetime.min.time() and parsed.tzinfo is None and "T" not in like:
        return result_date.isoformat()
    return parsed.replace(
        year=result_date.year, month=result_date.month, day=result_date.day
    ).isoformat()


def _seq_from_days(days: NDArray[np.int64], like: object) -> Any:
    """Rebuild a sequence, preserving time of day and tz when the input carried them.

    The day delta is measured against the input's *wall-clock* days, so a DST transition
    inside the offset does not move the clock (I5).
    """
    pandas = loaded_pandas()
    if pandas is not None and isinstance(like, (pandas.Series, pandas.Index)):
        index = pandas.DatetimeIndex(like)
        zone = index.tz
        wall = index.tz_localize(None) if zone is not None else index
        carries_time = bool((wall != wall.normalize()).any())
        if zone is not None or carries_time:
            source = np.ascontiguousarray(wall.values.astype("datetime64[D]")).view(np.int64)
            shifted = wall + pandas.to_timedelta(days - source, unit="D")
            return shifted.tz_localize(zone) if zone is not None else shifted
        return pandas.DatetimeIndex(days_to_datetime64(days))

    module = optional_pandas()
    if module is None:  # I6 explicitly allows degrading to numpy when pandas is absent.
        return days_to_datetime64(days)
    return module.DatetimeIndex(days_to_datetime64(days))


def from_days(days: Any, *, like: object) -> Any:
    """Rebuild the caller's original type from epoch day numbers (I6).

    This is the single dispatcher for type preservation. Scalar results keep the original
    time of day and ``tzinfo``, so offsets move only the date part (I5).

    Args:
        days: An epoch day number, or an ``int64`` array of them.
        like: The original input, whose type (and time of day) is reproduced.

    Returns:
        A value of the same type as ``like``.

    Examples:
        >>> from_days(20666, like=date(2026, 7, 31))
        datetime.date(2026, 8, 1)
        >>> from_days(20666, like="2026-07-31")
        '2026-08-01'
        >>> from_days(20666, like=20260731)
        20260801
        >>> from_days(20666, like=datetime(2026, 7, 31, 9, 30))  # wall clock preserved
        datetime.datetime(2026, 8, 1, 9, 30)
    """
    kind = kind_of(like)
    if kind is Kind.SEQ:
        return _seq_from_days(np.asarray(days, dtype=np.int64), like)

    number = int(days)
    result_date = days_to_date(number)
    if kind is Kind.DATE:
        return result_date
    if kind in (Kind.DATETIME, Kind.TIMESTAMP):
        # `.replace` keeps the wall clock and the tzinfo object, which is exactly the
        # DST-safe behaviour I5 mandates: +1 business day across a transition is +23h or
        # +25h in absolute terms, and that is the intended answer.
        return cast(datetime, like).replace(
            year=result_date.year, month=result_date.month, day=result_date.day
        )
    if kind is Kind.NP:
        return _numpy_from_days(number, cast(np.datetime64, like))
    if kind is Kind.STR:
        return _string_from_days(number, str(like))
    if kind is Kind.INT:
        return result_date.year * 10000 + result_date.month * 100 + result_date.day
    raise BetterCalendarError(f"Cannot rebuild a value of kind {kind}.")


# ---------------------------------------------------------------------------
# Scalar converters
# ---------------------------------------------------------------------------


def to_date(value: DateLike, *, tz: str | None = None) -> date:
    """Convert any supported scalar to a :class:`datetime.date`.

    Args:
        value: A date-like scalar.
        tz: IANA timezone used to project an aware input onto a calendar day.

    Returns:
        The calendar day the input denotes.

    Raises:
        AmbiguousTimezoneError: If the input is aware and no timezone is available.

    Examples:
        >>> to_date("20260731")
        datetime.date(2026, 7, 31)
        >>> to_date(datetime(2026, 7, 31, 23, 30))          # naive: read literally
        datetime.date(2026, 7, 31)
        >>> to_date("2026-07-31T23:30:00Z", tz="Europe/Paris")
        datetime.date(2026, 8, 1)
    """
    return days_to_date(int(to_days(value, tz=tz)))


def to_datetime(value: DateLike, *, tz: str | None = None) -> datetime:
    """Convert any supported scalar to a :class:`datetime.datetime`.

    Time of day and ``tzinfo`` are preserved when the input carries them; date-only
    inputs become naive midnight. When ``tz`` is given and the input is aware, the result
    is converted to that zone.

    Args:
        value: A date-like scalar.
        tz: IANA timezone to convert an aware input into.

    Returns:
        The input as a ``datetime``.

    Examples:
        >>> to_datetime(date(2026, 7, 31))
        datetime.datetime(2026, 7, 31, 0, 0)
        >>> to_datetime("2026-07-31T14:30:00")
        datetime.datetime(2026, 7, 31, 14, 30)
    """
    kind = kind_of(value)
    if kind is Kind.STR:
        moment = _parse_string(str(value))
    elif kind is Kind.TIMESTAMP:
        moment = datetime.fromisoformat(cast(Any, value).isoformat())
    elif kind is Kind.DATETIME:
        moment = cast(datetime, value)
    else:
        day = to_date(value, tz=tz)
        return datetime(day.year, day.month, day.day)

    if moment.tzinfo is not None:
        resolved = _resolve_tz(tz)
        if resolved is not None:
            return moment.astimezone(_zone(resolved))
    return moment


def to_timestamp(value: DateLike, *, tz: str | None = None) -> Any:
    """Convert any supported scalar to a :class:`pandas.Timestamp`.

    Args:
        value: A date-like scalar.
        tz: IANA timezone to convert an aware input into.

    Returns:
        A ``pandas.Timestamp`` (pandas is imported on demand).

    Raises:
        ProviderError: If pandas is not installed.

    Examples:
        >>> to_timestamp(date(2026, 7, 31))
        Timestamp('2026-07-31 00:00:00')
    """
    pandas = require_pandas("Timestamp output")
    return pandas.Timestamp(to_datetime(value, tz=tz))


def bounds_as_days(bounds: tuple[date, date]) -> tuple[int, int]:
    """Convert a ``(start, end)`` bounds pair to inclusive epoch day numbers.

    Args:
        bounds: Inclusive first and last day of a calendar's horizon.

    Returns:
        The pair as epoch day numbers.

    Examples:
        >>> bounds_as_days((date(1970, 1, 1), date(1970, 1, 31)))
        (0, 30)
    """
    return date_to_days(bounds[0]), date_to_days(bounds[1])
