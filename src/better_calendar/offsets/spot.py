"""Currency settlement lags (§7.4).

``spot(d, "EUR")`` answers "if I trade today, when does it settle" — two business days
later in the TARGET2 calendar. Small, and asked for constantly.

The lags live in ``data/spot_lags.toml`` rather than in code, so that a desk whose
convention differs can correct a row without a release. They are **money-market deposit**
conventions, a property of a single currency; FX spot is a property of the *pair* and is
deliberately out of scope — see the comments in that file.

The default calendar for a currency comes from the alias table: ``EUR`` resolves to
``fin:TARGET2``, ``GBP`` to ``fin:LNB``, and so on. Pass ``cal=`` to override, which is
what you want for a cross-currency trade that has to settle in two centres at once::

    spot(trade_date, "EUR", cal=bcal.get("EUR") & bcal.get("USD"))
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from better_calendar.calendars._toml import read_table
from better_calendar.calendars.registry import CalendarLike, resolve
from better_calendar.core.errors import BetterCalendarError, UnknownCalendarError
from better_calendar.offsets.conventions import Roll, RollLike

__all__ = ["SPOT_LAG", "spot", "spot_lag"]

_LAGS_PATH = Path(__file__).resolve().parent.parent / "data" / "spot_lags.toml"


def _load_lags() -> dict[str, int]:
    return {
        str(key).upper(): int(value) for key, value in read_table(_LAGS_PATH, "lags").items()
    }


#: Currency code to settlement lag in business days.
#:
#: A read-only mapping rather than the bare ``dict`` of §7.4: the table is shared process
#: state, and a caller mutating it would silently change every later settlement date.
#: Edit ``data/spot_lags.toml`` instead, or pass ``cal=``/the lag explicitly.
SPOT_LAG: Mapping[str, int] = MappingProxyType(_load_lags())


def spot_lag(currency: str) -> int:
    """The settlement lag for a currency, in business days.

    Args:
        currency: An ISO-4217 code, case-insensitive.

    Returns:
        The lag in business days.

    Raises:
        BetterCalendarError: If the currency is not in the table.

    Examples:
        >>> spot_lag("EUR"), spot_lag("gbp"), spot_lag("CAD")
        (2, 0, 1)
    """
    code = str(currency).upper()
    if code not in SPOT_LAG:
        raise BetterCalendarError(
            f"No settlement lag known for currency {code!r}. Known currencies are "
            f"{', '.join(sorted(SPOT_LAG))}. Add a row to data/spot_lags.toml, or pass "
            f"the lag yourself with cal.offset(date, lag)."
        )
    return SPOT_LAG[code]


def spot(
    value: Any,
    currency: str,
    *,
    cal: CalendarLike = None,
    roll: RollLike = Roll.FOLLOWING,
    tz: str | None = None,
) -> Any:
    """The settlement date for a trade in ``currency`` on ``value``.

    Args:
        value: The trade date, as a scalar or sequence.
        currency: An ISO-4217 code, case-insensitive.
        cal: The settlement calendar. ``None`` resolves the currency through the alias
            table, so ``"EUR"`` uses ``fin:TARGET2``.
        roll: How to normalise the trade date before counting business days.
        tz: Timezone used to project aware inputs.

    Returns:
        The same type as ``value`` (I6).

    Raises:
        BetterCalendarError: If the currency has no known lag, or no default calendar.

    Examples:
        >>> spot("2026-07-31", "EUR")          # Friday, T+2 in TARGET2
        '2026-08-04'
        >>> spot("2026-07-31", "GBP")          # sterling settles same day
        '2026-07-31'
        >>> spot("2026-07-31", "CAD")          # T+1, but 3 August is the Civic Holiday
        '2026-08-04'
    """
    lag = spot_lag(currency)
    calendar = resolve(cal) if cal is not None else _default_calendar(currency)
    return calendar.offset(value, lag, roll=roll, tz=tz)


def _default_calendar(currency: str) -> Any:
    """The settlement calendar a currency implies, via the alias table."""
    code = str(currency).upper()
    try:
        return resolve(code)
    except UnknownCalendarError as exc:
        raise BetterCalendarError(
            f"No default settlement calendar for {code!r}: the alias table does not map "
            f"it onto one. Pass cal=... explicitly, or add the alias to aliases.toml."
        ) from exc
