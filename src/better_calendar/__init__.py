"""
better_calendar.py

Concrete adapters + final BetterCalendar to retrieve OFF days (holidays + weekends)
from:
  - exchanges (MIC codes like XNYS, XPAR, XLON...) via exchange_calendars
  - countries (ISO like FR, US, GB...) via workalendar
  - RFR tickers (Bloomberg-style like "ESTRON Index", "SOFRRATE Index") via QuantLib calendars

Install:
  pip install exchange-calendars workalendar QuantLib

Notes:
  - Exchange calendars: real trading sessions (can include early closes, etc.). We return OFF *dates*.
  - Country calendars: legal/public holidays (not exchange-specific).
  - RFR calendars: fixing/publication business-day conventions (e.g., €STR ~ TARGET, SOFR ~ US Govies/SIFMA proxy).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Dict, Iterable, List, Literal, Protocol, Tuple, Union, Optional


# =========================
# Errors
# =========================
class CalendarError(Exception):
    pass


class UnknownExchangeError(CalendarError):
    pass


class UnknownCountryError(CalendarError):
    pass


class UnknownRfrError(CalendarError):
    pass


class MissingDependencyError(CalendarError):
    pass


# =========================
# Protocol (common API)
# =========================
class CalendarAdapter(Protocol):
    name: str

    def holidays(self, start: date, end: date) -> List[date]:
        """OFF dates in [start, end] inclusive. Must include weekends."""
        ...

    def is_business_day(self, d: date) -> bool:
        ...

    def business_days(self, start: date, end: date) -> List[date]:
        ...


InputKind = Literal["exchange", "country", "rfr"]
DateLike = Union[date, datetime]


# =========================
# Helpers
# =========================
def _to_date(x: DateLike) -> date:
    return x.date() if isinstance(x, datetime) else x


def _daterange(start: date, end: date) -> Iterable[date]:
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def _norm_key(s: str) -> str:
    return " ".join(s.strip().upper().split())


def _norm_rfr_key(s: str) -> str:
    # Normalize weird symbols / spacing in BBG tickers (e.g. €STRON Index)
    return _norm_key(s.replace("€", "E"))


def _create_calendar_plot(
    calendar_adapter,
    year: Optional[int] = None,
    start: Optional[date] = None,
    end: Optional[date] = None,
    cmap: Optional[str] = None,
    figsize: Tuple[int, int] = (20, 4),
    **kwargs
):
    """
    Create a beautiful calendar heatmap visualization.
    
    Args:
        calendar_adapter: A CalendarAdapter instance
        year: Year to plot (mutually exclusive with start/end)
        start: Start date (mutually exclusive with year)
        end: End date (mutually exclusive with year)
        cmap: Colormap name (default: custom green-red gradient)
        figsize: Figure size (width, height)
        **kwargs: Additional arguments for customization
    
    Returns:
        Matplotlib figure and axes
    
    Example:
        fig, ax = calendar.plot(year=2026)
        fig, ax = calendar.plot(start=date(2026, 1, 1), end=date(2026, 6, 30))
    """
    try:
        import pandas as pd # noqa
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        import calendar as pycal
    except ImportError as e:
        raise MissingDependencyError(
            "matplotlib and pandas are required for plotting. "
            "Install: pip install matplotlib pandas"
        ) from e
    
    # Determine date range
    if year is not None:
        if start is not None or end is not None:
            raise ValueError("Specify either 'year' or 'start'/'end', not both")
        start = date(year, 1, 1)
        end = date(year, 12, 31)
    elif start is None or end is None:
        # Default to current year
        from datetime import datetime as dt
        current_year = dt.now().year
        start = date(current_year, 1, 1)
        end = date(current_year, 12, 31)
    
    # Get business days
    bdays_list = calendar_adapter.business_days(start, end)
    bdays_set = set(bdays_list)
    
    # Create figure with better styling
    plt.style.use('default')
    fig, ax = plt.subplots(figsize=figsize, facecolor='white')
    
    # Prepare data: organize by week
    current = start
    weeks = []
    week = []
    
    # Start with the first day of the week
    while current.weekday() != 0:  # 0 = Monday
        current = current - timedelta(days=1)
        
    end_check = end
    while end_check.weekday() != 6:  # 6 = Sunday
        end_check = end_check + timedelta(days=1)
    
    while current <= end_check:
        if current.weekday() == 0 and week:
            weeks.append(week)
            week = []
        
        if start <= current <= end:
            is_bday = current in bdays_set
            week.append((current, is_bday))
        else:
            week.append((None, None))
        
        current = current + timedelta(days=1)
    
    if week:
        weeks.append(week)
    
    # Create the grid
    cell_width = 1
    cell_height = 1
    gap = 0.1
    
    month_positions = []
    
    for week_idx, week in enumerate(weeks):
        for day_idx, (day, is_bday) in enumerate(week):
            x = week_idx * (cell_width + gap)
            y = (6 - day_idx) * (cell_height + gap)
            
            if day is None:
                continue
            
            # Determine color
            if is_bday:
                color = '#66BB6A'  # Green
                edge_color = '#4CAF50'
            else:
                if day.weekday() >= 5:  # Weekend
                    color = '#FF7043'  # Orange
                    edge_color = '#F4511E'
                else:  # Holiday on weekday
                    color = '#EF5350'  # Red
                    edge_color = '#E53935'
            
            # Draw cell
            rect = mpatches.Rectangle(
                (x, y), cell_width, cell_height,
                facecolor=color,
                edgecolor=edge_color,
                linewidth=1.5,
                alpha=0.9
            )
            ax.add_patch(rect)
            
            # Add day number
            if day.day == 1 or (week_idx == 0 and day_idx == 0):
                ax.text(
                    x + cell_width/2, y + cell_height/2,
                    str(day.day),
                    ha='center', va='center',
                    fontsize=7,
                    color='white',
                    weight='bold',
                    fontfamily='sans-serif'
                )
            
            # Track month boundaries
            if day.day == 1:
                month_positions.append((week_idx, day.month, day.year))
    
    # Add month labels
    for pos, month, yr in month_positions:
        month_name = pycal.month_abbr[month]
        x = pos * (cell_width + gap) + cell_width/2
        ax.text(
            x, -0.5,
            month_name if yr == start.year else f"{month_name} {yr}",
            ha='center', va='top',
            fontsize=11,
            weight='bold',
            fontfamily='sans-serif',
            color='#424242'
        )
    
    # Add day labels
    day_labels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    for i, label in enumerate(day_labels):
        y = (6 - i) * (cell_height + gap) + cell_height/2
        ax.text(
            -0.5, y, label,
            ha='right', va='center',
            fontsize=10,
            fontfamily='sans-serif',
            color='#616161'
        )
    
    # Set axis limits and remove spines
    ax.set_xlim(-2, len(weeks) * (cell_width + gap))
    ax.set_ylim(-1.5, 7 * (cell_height + gap))
    ax.set_aspect('equal')
    ax.axis('off')
    
    # Add title
    title = f"{calendar_adapter.name}"
    if year:
        title += f" — {year}"
    else:
        title += f" — {start.strftime('%b %Y')} to {end.strftime('%b %Y')}"
    
    ax.text(
        0.5, 1.02, title,
        transform=ax.transAxes,
        ha='center', va='bottom',
        fontsize=16,
        weight='bold',
        fontfamily='sans-serif',
        color='#212121'
    )
    
    # Add legend
    legend_elements = [
        mpatches.Patch(facecolor='#66BB6A', edgecolor='#4CAF50', label='Business Day'),
        mpatches.Patch(facecolor='#EF5350', edgecolor='#E53935', label='Holiday (Weekday)'),
        mpatches.Patch(facecolor='#FF7043', edgecolor='#F4511E', label='Weekend')
    ]
    ax.legend(
        handles=legend_elements,
        loc='upper right',
        frameon=True,
        fancybox=True,
        shadow=True,
        fontsize=9,
        ncol=3
    )
    
    # Add statistics
    total_days = (end - start).days + 1
    n_bdays = len(bdays_list)
    n_holidays = total_days - n_bdays
    
    stats_text = f"{n_bdays} business days  |  {n_holidays} off days  |  {n_bdays/total_days*100:.1f}% working rate"
    ax.text(
        0.5, -0.02, stats_text,
        transform=ax.transAxes,
        ha='center', va='top',
        fontsize=10,
        fontfamily='monospace',
        color='#757575',
        style='italic'
    )
    
    plt.tight_layout()
    
    return fig, ax


# =========================
# Adapter: Exchange calendars (exchange_calendars)
# =========================
@dataclass(frozen=True)
class ExchangeCalendarAdapter:
    """
    Uses exchange_calendars to infer business sessions.
    MIC code examples:
      XNYS, XNAS, XPAR, XLON, XTKS, XHKG, XSWX...
    """
    mic: str
    name: str = ""

    def __post_init__(self):
        object.__setattr__(self, "mic", _norm_key(self.mic))
        if not self.name:
            object.__setattr__(self, "name", f"exchange:{self.mic}")

        # Lazy import check
        try:
            import exchange_calendars  # noqa: F401
        except Exception as e:
            raise MissingDependencyError(
                "exchange_calendars is required for ExchangeCalendarAdapter. "
                "Install: pip install exchange-calendars"
            ) from e
        
        # Validate MIC code exists (fail fast)
        _ = self._cal

    @property
    def _cal(self):
        import exchange_calendars as xcals
        # Raises if unknown
        return xcals.get_calendar(self.mic)

    @lru_cache(maxsize=512)
    def _session_dates(self, start: date, end: date) -> Tuple[date, ...]:
        # exchange_calendars returns sessions as tz-aware timestamps.
        # We only need date part.
        import pandas as pd  # exchange_calendars depends on pandas
        cal = self._cal
        # Inclusive: sessions_in_range expects timestamps; easiest: use pd.Timestamp
        s = pd.Timestamp(start)
        e = pd.Timestamp(end)
        sessions = cal.sessions_in_range(s, e)
        # sessions is DatetimeIndex with tz; convert to python date
        return tuple(ts.date() for ts in sessions.to_pydatetime())

    def is_business_day(self, d: date) -> bool:
        # Business day = trading session exists that date
        # (This ignores half-days vs full-days; that's usually fine for "off dates".)
        return d in self._session_dates(d, d)

    def business_days(self, start: date, end: date) -> List[date]:
        return list(self._session_dates(start, end))

    def holidays(self, start: date, end: date) -> List[date]:
        # OFF = all dates in range minus session dates
        sessions = set(self._session_dates(start, end))
        return [d for d in _daterange(start, end) if d not in sessions]

    def plot(self, year: Optional[int] = None, start: Optional[date] = None, 
             end: Optional[date] = None, **kwargs):
        """Create a calendar heatmap visualization.
        
        Args:
            year: Year to plot (mutually exclusive with start/end)
            start: Start date (mutually exclusive with year)
            end: End date (mutually exclusive with year)
            **kwargs: Additional arguments passed to calplot
        
        Returns:
            Matplotlib figure and axes
        """
        return _create_calendar_plot(self, year=year, start=start, end=end, **kwargs)


# =========================
# Adapter: Country public holidays (workalendar)
# =========================
@dataclass(frozen=True)
class CountryCalendarAdapter:
    """
    Uses workalendar registry.

    ISO examples:
      FR, US, GB, DE, JP...

    Workalendar supports many countries + subdivisions; this adapter uses the *country*
    default class (no subdivision). If you need regions (e.g., US-CA), we can extend.
    """
    iso: str
    name: str = ""

    def __post_init__(self):
        object.__setattr__(self, "iso", _norm_key(self.iso))
        if not self.name:
            object.__setattr__(self, "name", f"country:{self.iso}")

        try:
            import workalendar  # noqa: F401
        except Exception as e:
            raise MissingDependencyError(
                "workalendar is required for CountryCalendarAdapter. "
                "Install: pip install workalendar"
            ) from e

        # Validate ISO in registry now (fail fast)
        _ = self._cal  # triggers resolution

    @property
    def _cal(self):
        from workalendar.registry import registry
        # Registry keys are like "FR", "UnitedStates", etc.
        # Workalendar provides ISO-based registry lookup: registry.get(iso)
        cal_cls = registry.get(self.iso)
        if cal_cls is None:
            raise UnknownCountryError(f"Unknown/unsupported country ISO code in workalendar: {self.iso!r}")
        return cal_cls()

    @lru_cache(maxsize=512)
    def _holidays_year(self, year: int) -> Tuple[date, ...]:
        # workalendar returns (date, label)
        return tuple(d for (d, _label) in self._cal.holidays(year))

    def is_business_day(self, d: date) -> bool:
        if d.weekday() >= 5:
            return False
        return d not in set(self._holidays_year(d.year))

    def business_days(self, start: date, end: date) -> List[date]:
        return [d for d in _daterange(start, end) if self.is_business_day(d)]

    def holidays(self, start: date, end: date) -> List[date]:
        # OFF includes weekends + legal holidays
        off: List[date] = []
        for d in _daterange(start, end):
            if not self.is_business_day(d):
                off.append(d)
        return off

    def plot(self, year: Optional[int] = None, start: Optional[date] = None, 
             end: Optional[date] = None, **kwargs):
        """Create a calendar heatmap visualization.
        
        Args:
            year: Year to plot (mutually exclusive with start/end)
            start: Start date (mutually exclusive with year)
            end: End date (mutually exclusive with year)
            **kwargs: Additional arguments passed to calplot
        
        Returns:
            Matplotlib figure and axes
        """
        return _create_calendar_plot(self, year=year, start=start, end=end, **kwargs)


# =========================
# Adapter: QuantLib calendars (for RFRs)
# =========================
@dataclass(frozen=True)
class QuantLibCalendarAdapter:
    """
    Wraps a QuantLib.Calendar and exposes date-based business rules.
    """
    ql_calendar_name: str
    name: str = ""
    _variant: Optional[str] = None  # if you want e.g. UnitedStates(GovernmentBond)

    def __post_init__(self):
        if not self.name:
            object.__setattr__(self, "name", f"ql:{self.ql_calendar_name}")

        try:
            import QuantLib as ql  # noqa: F401
        except Exception as e:
            raise MissingDependencyError(
                "QuantLib-Python is required for QuantLibCalendarAdapter. "
                "Install: pip install QuantLib"
            ) from e

        _ = self._cal  # validate construction

    @property
    def _cal(self):
        import QuantLib as ql

        key = self.ql_calendar_name.strip().upper()

        if key in {"TARGET", "TARGET2"}:
            return ql.TARGET()

        if key in {"UNITEDSTATES", "US"}:
            # Default market if not specified
            return ql.UnitedStates()

        if key in {"US_GOVIES", "USGOVIES", "US_GOVERNMENT_BOND", "GOVERNMENTBOND"}:
            # Proxy for SIFMA US government securities business day
            return ql.UnitedStates(ql.UnitedStates.GovernmentBond)

        if key in {"UNITEDKINGDOM", "UK"}:
            return ql.UnitedKingdom()

        if key in {"JAPAN", "JP"}:
            return ql.Japan()

        if key in {"GERMANY", "DE"}:
            return ql.Germany()

        if key in {"FRANCE", "FR"}:
            return ql.France()

        # Extend here as needed; QuantLib offers many calendars.
        raise CalendarError(f"Unknown QuantLib calendar spec: {self.ql_calendar_name!r}")

    @staticmethod
    def _to_ql_date(d: date):
        import QuantLib as ql
        return ql.Date(d.day, d.month, d.year)

    def is_business_day(self, d: date) -> bool:
        qld = self._to_ql_date(d)
        return self._cal.isBusinessDay(qld)

    def business_days(self, start: date, end: date) -> List[date]:
        return [d for d in _daterange(start, end) if self.is_business_day(d)]

    def holidays(self, start: date, end: date) -> List[date]:
        return [d for d in _daterange(start, end) if not self.is_business_day(d)]

    def plot(self, year: Optional[int] = None, start: Optional[date] = None, 
             end: Optional[date] = None, **kwargs):
        """Create a calendar heatmap visualization.
        
        Args:
            year: Year to plot (mutually exclusive with start/end)
            start: Start date (mutually exclusive with year)
            end: End date (mutually exclusive with year)
            **kwargs: Additional arguments passed to calplot
        
        Returns:
            Matplotlib figure and axes
        """
        return _create_calendar_plot(self, year=year, start=start, end=end, **kwargs)


# =========================
# Adapter: Override Calendar (custom adjustments)
# =========================
@dataclass(frozen=True)
class OverrideCalendarAdapter:
    """
    Wraps an existing CalendarAdapter and applies custom overrides.
    
    Use cases:
      - Add extra holidays (strikes, national mourning, etc.)
      - Remove holidays (special working days)
    
    Example:
        base = hub.get_from_exchange("XPAR")
        adjusted = OverrideCalendarAdapter(
            base_calendar=base,
            add_holidays=[date(2026, 5, 15)],  # strike day
            remove_holidays=[date(2026, 1, 2)]  # exceptional opening
        )
    """
    base_calendar: CalendarAdapter
    add_holidays: Tuple[date, ...] = ()
    remove_holidays: Tuple[date, ...] = ()
    name: str = ""

    def __post_init__(self):
        # Convert lists to tuples for immutability
        if isinstance(self.add_holidays, list):
            object.__setattr__(self, "add_holidays", tuple(self.add_holidays))
        if isinstance(self.remove_holidays, list):
            object.__setattr__(self, "remove_holidays", tuple(self.remove_holidays))
        
        if not self.name:
            suffix = []
            if self.add_holidays:
                suffix.append(f"+{len(self.add_holidays)}")
            if self.remove_holidays:
                suffix.append(f"-{len(self.remove_holidays)}")
            suffix_str = f" [{', '.join(suffix)}]" if suffix else ""
            object.__setattr__(self, "name", f"{self.base_calendar.name}{suffix_str}")

    def is_business_day(self, d: date) -> bool:
        # If explicitly added as holiday, it's not a business day
        if d in self.add_holidays:
            return False
        # If explicitly removed from holidays, it becomes a business day
        if d in self.remove_holidays:
            return True
        # Otherwise, use base calendar
        return self.base_calendar.is_business_day(d)

    def business_days(self, start: date, end: date) -> List[date]:
        return [d for d in _daterange(start, end) if self.is_business_day(d)]

    def holidays(self, start: date, end: date) -> List[date]:
        return [d for d in _daterange(start, end) if not self.is_business_day(d)]

    def get_overrides_summary(self) -> Dict[str, List[date]]:
        """Return a summary of all overrides applied."""
        return {
            "added_holidays": sorted(self.add_holidays),
            "removed_holidays": sorted(self.remove_holidays),
        }

    def plot(self, year: Optional[int] = None, start: Optional[date] = None, 
             end: Optional[date] = None, **kwargs):
        """Create a calendar heatmap visualization.
        
        Args:
            year: Year to plot (mutually exclusive with start/end)
            start: Start date (mutually exclusive with year)
            end: End date (mutually exclusive with year)
            **kwargs: Additional arguments passed to calplot
        
        Returns:
            Matplotlib figure and axes
        """
        return _create_calendar_plot(self, year=year, start=start, end=end, **kwargs)


# =========================
# Adapter: Combined Calendar (intersection/union)
# =========================
@dataclass(frozen=True)
class CombinedCalendarAdapter:
    """
    Combines multiple CalendarAdapters using intersection or union logic.
    
    Modes:
      - "intersection": A day is a business day only if ALL calendars are open
      - "union": A day is a business day if AT LEAST ONE calendar is open
    
    Example:
        # Business day only if both US and Europe are open
        comb = CombinedCalendarAdapter(
            calendars=[sofr_cal, estr_cal],
            mode="intersection"
        )
        
        # Business day if either market is open
        comb_union = CombinedCalendarAdapter(
            calendars=[xpar_cal, xnys_cal],
            mode="union"
        )
    """
    calendars: Tuple[CalendarAdapter, ...]
    mode: str = "intersection"
    name: str = ""

    def __post_init__(self):
        # Convert list to tuple for immutability
        if isinstance(self.calendars, list):
            object.__setattr__(self, "calendars", tuple(self.calendars))
        
        if not self.calendars:
            raise CalendarError("CombinedCalendarAdapter requires at least one calendar")
        
        if self.mode not in {"intersection", "union"}:
            raise CalendarError(f"Invalid mode: {self.mode!r}. Must be 'intersection' or 'union'")
        
        if not self.name:
            cal_names = [cal.name for cal in self.calendars]
            combined_name = f"combined[{self.mode}]({', '.join(cal_names)})"
            object.__setattr__(self, "name", combined_name)

    def is_business_day(self, d: date) -> bool:
        if self.mode == "union":
            # Business day if ANY calendar is open
            return any(cal.is_business_day(d) for cal in self.calendars)
        else:  # intersection
            # Business day if ALL calendars are open
            return all(cal.is_business_day(d) for cal in self.calendars)

    def business_days(self, start: date, end: date) -> List[date]:
        return [d for d in _daterange(start, end) if self.is_business_day(d)]

    def holidays(self, start: date, end: date) -> List[date]:
        return [d for d in _daterange(start, end) if not self.is_business_day(d)]

    def plot(self, year: Optional[int] = None, start: Optional[date] = None, 
             end: Optional[date] = None, **kwargs):
        """Create a calendar heatmap visualization.
        
        Args:
            year: Year to plot (mutually exclusive with start/end)
            start: Start date (mutually exclusive with year)
            end: End date (mutually exclusive with year)
            **kwargs: Additional arguments passed to calplot
        
        Returns:
            Matplotlib figure and axes
        """
        return _create_calendar_plot(self, year=year, start=start, end=end, **kwargs)


# =========================
# BetterCalendar (final class)
# =========================
class BetterCalendar:
    """
    Final façade class.

    Usage:
        hub = BetterCalendar.default()

        off = hub.get_from_exchange("XPAR").holidays(date(2026,1,1), date(2026,12,31))
        off = hub.get_from_country("FR").holidays(date(2026,1,1), date(2026,12,31))
        off = hub.get_from_rfr("ESTRON Index").holidays(date(2026,1,1), date(2026,12,31))
    """

    def __init__(
        self,
        exchange_adapters: Dict[str, CalendarAdapter],
        country_adapters: Dict[str, CalendarAdapter],
        rfr_adapters: Dict[str, CalendarAdapter],
    ):
        self._ex = {_norm_key(k): v for k, v in exchange_adapters.items()}
        self._cty = {_norm_key(k): v for k, v in country_adapters.items()}
        self._rfr = {_norm_rfr_key(k): v for k, v in rfr_adapters.items()}

    # ---------- factories
    @classmethod
    def default(cls) -> "BetterCalendar":
        """
        Builds a practical default mapping:
          - exchanges: created on-demand in get_from_exchange
          - countries: created on-demand in get_from_country
          - RFRs: explicit mapping ticker -> QuantLib calendar
        """
        return cls(exchange_adapters={}, country_adapters={}, rfr_adapters=_default_rfr_map())

    # ---------- supported lists
    def supported_rfrs(self) -> List[str]:
        return sorted(self._rfr.keys())

    def supported_exchanges(self) -> List[str]:
        # We allow dynamic exchange creation; return those already instantiated
        return sorted(self._ex.keys())

    def supported_countries(self) -> List[str]:
        # We allow dynamic country creation; return those already instantiated
        return sorted(self._cty.keys())

    # ---------- getters
    def get_from_exchange(self, exchange_code: str) -> CalendarAdapter:
        key = _norm_key(exchange_code)
        if key not in self._ex:
            # Create adapter on-demand. If unknown MIC, exchange_calendars will raise.
            try:
                self._ex[key] = ExchangeCalendarAdapter(key)
            except Exception as e:
                # Rewrap for nicer error surface
                raise UnknownExchangeError(f"Unknown/unsupported exchange code: {exchange_code!r}") from e
        return self._ex[key]

    def get_from_country(self, iso_code: str) -> CalendarAdapter:
        key = _norm_key(iso_code)
        if key not in self._cty:
            try:
                self._cty[key] = CountryCalendarAdapter(key)
            except UnknownCountryError:
                raise
            except Exception as e:
                raise UnknownCountryError(f"Unknown/unsupported country ISO: {iso_code!r}") from e
        return self._cty[key]

    def get_from_rfr(self, ticker: str) -> CalendarAdapter:
        key = _norm_rfr_key(ticker)
        try:
            return self._rfr[key]
        except KeyError:
            raise UnknownRfrError(f"Unknown/unsupported RFR ticker: {ticker!r} (normalized={key!r})")

    # ---------- unified convenience API
    def holidays(self, kind: InputKind, code: str, start: DateLike, end: DateLike) -> List[date]:
        cal = self._resolve(kind, code)
        return cal.holidays(_to_date(start), _to_date(end))

    def business_days(self, kind: InputKind, code: str, start: DateLike, end: DateLike) -> List[date]:
        cal = self._resolve(kind, code)
        return cal.business_days(_to_date(start), _to_date(end))

    def is_business_day(self, kind: InputKind, code: str, d: DateLike) -> bool:
        cal = self._resolve(kind, code)
        return cal.is_business_day(_to_date(d))

    def add_business_days(self, kind: InputKind, code: str, d: DateLike, n: int) -> date:
        cal = self._resolve(kind, code)
        cur = _to_date(d)
        step = 1 if n >= 0 else -1
        remaining = abs(n)
        while remaining > 0:
            cur = cur + timedelta(days=step)
            if cal.is_business_day(cur):
                remaining -= 1
        return cur

    def next_business_day(self, kind: InputKind, code: str, d: DateLike) -> date:
        return self.add_business_days(kind, code, d, 1)

    def prev_business_day(self, kind: InputKind, code: str, d: DateLike) -> date:
        return self.add_business_days(kind, code, d, -1)

    # ---------- combined and override calendars
    def combine(
        self,
        entries: List[Tuple[InputKind, str]],
        mode: str = "intersection"
    ) -> CalendarAdapter:
        """
        Combine multiple calendars using intersection or union logic.
        
        Args:
            entries: List of (kind, code) tuples to combine
            mode: "intersection" (all must be open) or "union" (any can be open)
        
        Returns:
            CombinedCalendarAdapter
        
        Example:
            # Business day only if both US and Europe are open
            comb = hub.combine([
                ("rfr", "SOFRRATE Index"),
                ("rfr", "ESTRON Index")
            ], mode="intersection")
            
            # Business day if either Paris or New York is open
            comb = hub.combine([
                ("exchange", "XPAR"),
                ("exchange", "XNYS")
            ], mode="union")
        """
        cals: List[CalendarAdapter] = []
        for kind, code in entries:
            cals.append(self._resolve(kind, code))
        return CombinedCalendarAdapter(calendars=cals, mode=mode)

    def with_overrides(
        self,
        kind: InputKind,
        code: str,
        add_holidays: Optional[List[date]] = None,
        remove_holidays: Optional[List[date]] = None
    ) -> CalendarAdapter:
        """
        Apply custom overrides to a calendar.
        
        Args:
            kind: Calendar kind (exchange, country, rfr)
            code: Calendar code
            add_holidays: Extra dates to mark as holidays
            remove_holidays: Dates to mark as business days (override base calendar)
        
        Returns:
            OverrideCalendarAdapter
        
        Example:
            # XPAR with strike day and exceptional opening
            cal = hub.with_overrides(
                "exchange", "XPAR",
                add_holidays=[date(2026, 5, 15)],  # strike
                remove_holidays=[date(2026, 1, 2)]  # exceptional opening
            )
        """
        base_cal = self._resolve(kind, code)
        return OverrideCalendarAdapter(
            base_calendar=base_cal,
            add_holidays=tuple(add_holidays or []),
            remove_holidays=tuple(remove_holidays or [])
        )

    # ---------- internal
    def _resolve(self, kind: InputKind, code: str) -> CalendarAdapter:
        if kind == "exchange":
            return self.get_from_exchange(code)
        if kind == "country":
            return self.get_from_country(code)
        if kind == "rfr":
            return self.get_from_rfr(code)
        raise CalendarError(f"Unknown kind: {kind!r}")


# =========================
# Default RFR mapping (Bloomberg tickers -> QuantLib calendars)
# =========================
def _default_rfr_map() -> Dict[str, CalendarAdapter]:
    """
    You can expand this mapping as you need.

    Bloomberg conventions vary (and desks often have aliases), so we include a few
    common variants.

    €STR:
      - ESTRON Index (often used for €STR O/N)
    SOFR:
      - SOFRRATE Index (often used for SOFR O/N)
    """
    # €STR uses TARGET business days
    estr_cal = QuantLibCalendarAdapter("TARGET", name="rfr:ESTR(TARGET)")

    # SOFR uses US Govies/SIFMA business days (proxy via QuantLib UnitedStates(GovernmentBond))
    sofr_cal = QuantLibCalendarAdapter("US_GOVERNMENT_BOND", name="rfr:SOFR(US-Govies)")

    # Add more RFRs if you want:
    # SONIA -> UnitedKingdom() (note: SONIA is UK money markets; some shops use UK settlement calendar)
    sonia_cal = QuantLibCalendarAdapter("UNITEDKINGDOM", name="rfr:SONIA(UK)")

    # SARON -> Switzerland calendar exists in QuantLib but not wired above; add if needed
    # TONAR -> Japan, etc.

    mapping: Dict[str, CalendarAdapter] = {
        # €STR
        "ESTRON INDEX": estr_cal,
        "ESTR INDEX": estr_cal,
        "€STRON INDEX": estr_cal,  # normalized by _norm_rfr_key anyway
        "ESTRON": estr_cal,
        "ESTR": estr_cal,

        # SOFR
        "SOFRRATE INDEX": sofr_cal,
        "SOFR INDEX": sofr_cal,
        "SOFRRATE": sofr_cal,
        "SOFR": sofr_cal,

        # SONIA (optional but useful)
        "SONIA INDEX": sonia_cal,
        "SONIO/N INDEX": sonia_cal,  # example alias; normalize will keep slash -> you can add more if needed
        "SONIA": sonia_cal,
    }

    # Normalize keys the same way BetterCalendar does
    return {_norm_rfr_key(k): v for k, v in mapping.items()}