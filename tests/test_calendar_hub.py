# Pytest test suite showing how to use BetterCalendar and what to expect from:
#   - get_from_exchange (MIC codes -> exchange_calendars)
#   - get_from_country (ISO codes -> workalendar)
#   - get_from_rfr      (RFR tickers -> QuantLib calendars via mapping)
#
# Run:
#   pip install pytest exchange-calendars workalendar QuantLib
#   pytest -q
#
# Notes:
# - These tests are written to be robust across calendar version updates:
#   we assert invariants (weekends are off, Jan 1 is off for FR/TARGET/US-govies, etc.)
#   rather than exact full holiday lists.

from __future__ import annotations

from datetime import date, datetime, timedelta
import pytest

# Import your module (adjust import path to your project)
# from better_calendar import BetterCalendar, UnknownExchangeError, UnknownCountryError, UnknownRfrError
#
# If you named the file better_calendar.py and it's in the same folder:
from better_calendar import BetterCalendar, UnknownExchangeError, UnknownCountryError, UnknownRfrError


# -------------------------
# Dependency gates
# -------------------------
def _has_exchange_calendars() -> bool:
    try:
        import exchange_calendars  # noqa: F401
        return True
    except Exception:
        return False


def _has_workalendar() -> bool:
    try:
        import workalendar  # noqa: F401
        return True
    except Exception:
        return False


def _has_quantlib() -> bool:
    try:
        import QuantLib  # noqa: F401
        return True
    except Exception:
        return False


def _has_calplot() -> bool:
    try:
        import calplot  # noqa: F401
        import matplotlib  # noqa: F401
        return True
    except Exception:
        return False


EXCHANGE_OK = _has_exchange_calendars()
WORKALENDAR_OK = _has_workalendar()
QL_OK = _has_quantlib()
CALPLOT_OK = _has_calplot()


# -------------------------
# Fixtures
# -------------------------
@pytest.fixture(scope="session")
def hub() -> BetterCalendar:
    return BetterCalendar.default()


@pytest.fixture(scope="session")
def sample_range() -> tuple[date, date]:
    # A small range around New Year where we have very stable invariants:
    # - Jan 1 is a holiday in many calendars
    # - weekends exist (range contains weekends)
    return date(2026, 1, 1), date(2026, 1, 15)


# ============================================================
# 1) High-level usage patterns (examples as tests)
# ============================================================
def test_basic_usage_examples(hub: BetterCalendar, sample_range: tuple[date, date]) -> None:
    s, e = sample_range

    # Unified API works with date or datetime
    off_fr = hub.holidays("country", "FR", s, e)
    off_fr_dt = hub.holidays("country", "FR", datetime(2026, 1, 1, 12), datetime(2026, 1, 15, 18))
    assert off_fr == off_fr_dt

    # is_business_day
    assert hub.is_business_day("country", "FR", date(2026, 1, 3)) is False  # Saturday
    assert hub.is_business_day("country", "FR", date(2026, 1, 4)) is False  # Sunday

    # Next/prev business day helpers
    nb = hub.next_business_day("country", "FR", date(2026, 1, 3))  # Sat -> next business day (Mon or later)
    assert nb.weekday() < 5
    pb = hub.prev_business_day("country", "FR", date(2026, 1, 4))  # Sun -> prev business day (Fri or earlier)
    assert pb.weekday() < 5


# ============================================================
# 2) Country calendars (workalendar)
# ============================================================
@pytest.mark.skipif(not WORKALENDAR_OK, reason="workalendar not installed")
def test_country_fr_invariants(hub: BetterCalendar, sample_range: tuple[date, date]) -> None:
    s, e = sample_range
    cal = hub.get_from_country("fr")  # lower-case should work

    off = cal.holidays(s, e)
    bdays = cal.business_days(s, e)

    # Invariants:
    # - weekends are OFF
    assert date(2026, 1, 3) in off  # Saturday
    assert date(2026, 1, 4) in off  # Sunday

    # - Jan 1 is a legal holiday in France
    assert date(2026, 1, 1) in off

    # - business days must exclude weekends
    assert all(d.weekday() < 5 for d in bdays)

    # - holidays + business days partition the full range
    full = [d for d in _date_range(s, e)]
    assert sorted(off + bdays) == full
    assert set(off).isdisjoint(set(bdays))


@pytest.mark.skipif(not WORKALENDAR_OK, reason="workalendar not installed")
def test_unknown_country_raises(hub: BetterCalendar) -> None:
    with pytest.raises(UnknownCountryError):
        hub.get_from_country("ZZ")


# ============================================================
# 3) RFR calendars (QuantLib)
# ============================================================
@pytest.mark.skipif(not QL_OK, reason="QuantLib not installed")
@pytest.mark.parametrize(
    "ticker",
    [
        "ESTRON Index",
        "  estron   index  ",  # spacing normalization
        "€STRON Index",        # symbol normalization
    ],
)
def test_rfr_estr_target_invariants(hub: BetterCalendar, ticker: str, sample_range: tuple[date, date]) -> None:
    s, e = sample_range
    cal = hub.get_from_rfr(ticker)

    off = cal.holidays(s, e)
    bdays = cal.business_days(s, e)

    # TARGET calendar invariants
    assert date(2026, 1, 1) in off  # New Year is TARGET holiday
    assert date(2026, 1, 3) in off  # Saturday
    assert date(2026, 1, 4) in off  # Sunday
    assert all(d.weekday() < 5 for d in bdays)
    assert set(off).isdisjoint(set(bdays))


@pytest.mark.skipif(not QL_OK, reason="QuantLib not installed")
@pytest.mark.parametrize(
    "ticker",
    [
        "SOFRRATE Index",
        "SOFR Index",
        "  sofrRATE   index ",
    ],
)
def test_rfr_sofr_us_govies_invariants(hub: BetterCalendar, ticker: str, sample_range: tuple[date, date]) -> None:
    s, e = sample_range
    cal = hub.get_from_rfr(ticker)

    off = cal.holidays(s, e)
    bdays = cal.business_days(s, e)

    # US Govies/SIFMA proxy invariants
    assert date(2026, 1, 1) in off
    assert date(2026, 1, 3) in off
    assert date(2026, 1, 4) in off
    assert all(d.weekday() < 5 for d in bdays)
    assert set(off).isdisjoint(set(bdays))


def test_unknown_rfr_raises(hub: BetterCalendar) -> None:
    with pytest.raises(UnknownRfrError):
        hub.get_from_rfr("FOOBAR Index")


# ============================================================
# 4) Exchange calendars (exchange_calendars)
# ============================================================
@pytest.mark.skipif(not EXCHANGE_OK, reason="exchange-calendars not installed")
@pytest.mark.parametrize("mic", ["XPAR", "XNYS", "XLON"])
def test_exchange_calendar_invariants(hub: BetterCalendar, mic: str, sample_range: tuple[date, date]) -> None:
    s, e = sample_range
    cal = hub.get_from_exchange(mic)

    off = cal.holidays(s, e)
    bdays = cal.business_days(s, e)

    # Invariants for trading sessions:
    # - Weekends are OFF for most equity exchanges in exchange_calendars
    assert date(2026, 1, 3) in off  # Saturday
    assert date(2026, 1, 4) in off  # Sunday

    # - business days returned are actual session dates (should be weekdays)
    assert all(d.weekday() < 5 for d in bdays)

    # - Partition property
    full = [d for d in _date_range(s, e)]
    assert sorted(off + bdays) == full
    assert set(off).isdisjoint(set(bdays))


@pytest.mark.skipif(not EXCHANGE_OK, reason="exchange-calendars not installed")
def test_unknown_exchange_raises(hub: BetterCalendar) -> None:
    with pytest.raises(UnknownExchangeError):
        print(hub.get_from_exchange("XXXX"))


# ============================================================
# 5) Unified façade methods (kind/code) vs direct adapter usage
# ============================================================
@pytest.mark.skipif(not WORKALENDAR_OK, reason="workalendar not installed")
def test_unified_api_matches_direct_adapter_country(hub: BetterCalendar, sample_range: tuple[date, date]) -> None:
    s, e = sample_range

    direct = hub.get_from_country("FR").holidays(s, e)
    unified = hub.holidays("country", "FR", s, e)
    assert direct == unified

    direct_bd = hub.get_from_country("FR").business_days(s, e)
    unified_bd = hub.business_days("country", "FR", s, e)
    assert direct_bd == unified_bd


@pytest.mark.skipif(not QL_OK, reason="QuantLib not installed")
def test_add_business_days_moves_to_business_day(hub: BetterCalendar) -> None:
    # Pick a weekend and ensure we land on a business day
    d = date(2026, 1, 3)  # Saturday
    out = hub.add_business_days("rfr", "ESTRON Index", d, 1)
    assert out > d
    assert hub.is_business_day("rfr", "ESTRON Index", out) is True


# ============================================================
# 6) Documentation-by-test: "how should I use it?"
# ============================================================
@pytest.mark.skipif(not (WORKALENDAR_OK and EXCHANGE_OK and QL_OK), reason="needs all deps installed")
def test_showcase_end_to_end(hub: BetterCalendar) -> None:
    """
    This test is intentionally a mini "tutorial":

    1) Country public holidays: FR
    2) Exchange trading holidays: XPAR
    3) RFR fixing calendars: ESTRON Index (TARGET), SOFRRATE Index (US Govies)

    Use case: you want OFF dates in a month, then compute next business day for settlement.
    """
    s = date(2026, 3, 1)
    e = date(2026, 3, 31)

    off_fr = hub.holidays("country", "FR", s, e)
    off_xpar = hub.holidays("exchange", "XPAR", s, e)
    off_estr = hub.holidays("rfr", "ESTRON Index", s, e)
    off_sofr = hub.holidays("rfr", "SOFRRATE Index", s, e)

    # Basic sanity: all lists contain weekends
    assert any(d.weekday() >= 5 for d in off_fr)
    assert any(d.weekday() >= 5 for d in off_xpar)
    assert any(d.weekday() >= 5 for d in off_estr)
    assert any(d.weekday() >= 5 for d in off_sofr)

    # Example: "spot settlement" logic needs next business day under a given calendar
    trade_date = date(2026, 3, 7)  # Saturday
    settle_fr = hub.next_business_day("country", "FR", trade_date)
    settle_xpar = hub.next_business_day("exchange", "XPAR", trade_date)
    settle_estr = hub.next_business_day("rfr", "ESTRON Index", trade_date)

    assert settle_fr.weekday() < 5
    assert settle_xpar.weekday() < 5
    assert settle_estr.weekday() < 5


# ============================================================
# 7) Override calendars (custom adjustments)
# ============================================================
@pytest.mark.skipif(not EXCHANGE_OK, reason="exchange-calendars not installed")
def test_override_add_holiday(hub: BetterCalendar) -> None:
    """Test adding custom holidays (e.g., strike day)."""

    # Normal calendar
    normal_day = date(2026, 5, 15)  # Assume this is normally a business day
    
    # With override
    xpar_with_strike = hub.with_overrides(
        "exchange", "XPAR",
        add_holidays=[normal_day]
    )
    
    # The override should make it a holiday
    assert not xpar_with_strike.is_business_day(normal_day)
    
    # Summary should show the override
    from better_calendar import OverrideCalendarAdapter
    if isinstance(xpar_with_strike, OverrideCalendarAdapter):
        summary = xpar_with_strike.get_overrides_summary()
        assert normal_day in summary["added_holidays"]


@pytest.mark.skipif(not WORKALENDAR_OK, reason="workalendar not installed")
def test_override_remove_holiday(hub: BetterCalendar) -> None:
    """Test removing holidays (e.g., exceptional opening)."""
    # Jan 1 2026 is normally a holiday
    new_year = date(2026, 1, 1)
    
    # Normal FR calendar
    fr = hub.get_from_country("FR")
    assert not fr.is_business_day(new_year)
    
    # With exceptional opening
    fr_exceptional = hub.with_overrides(
        "country", "FR",
        remove_holidays=[new_year]
    )
    
    # Should now be a business day
    assert fr_exceptional.is_business_day(new_year)


@pytest.mark.skipif(not WORKALENDAR_OK, reason="workalendar not installed")
def test_override_both_add_and_remove(hub: BetterCalendar) -> None:
    """Test both adding and removing holidays."""
    fr = hub.get_from_country("FR")
    
    add_date = date(2026, 3, 16)  # Monday, normally business day
    remove_date = date(2026, 1, 1)  # Normally holiday
    
    # Before override
    assert fr.is_business_day(add_date)
    assert not fr.is_business_day(remove_date)
    
    # Apply both overrides
    fr_custom = hub.with_overrides(
        "country", "FR",
        add_holidays=[add_date],
        remove_holidays=[remove_date]
    )
    
    # After override
    assert not fr_custom.is_business_day(add_date)
    assert fr_custom.is_business_day(remove_date)


# ============================================================
# 8) Combined calendars (intersection/union)
# ============================================================
@pytest.mark.skipif(not WORKALENDAR_OK, reason="workalendar not installed")
def test_combined_intersection_two_countries(hub: BetterCalendar) -> None:
    """Test intersection: business day only if ALL calendars are open."""
    # Combine FR and US
    combined = hub.combine([
        ("country", "FR"),
        ("country", "US")
    ], mode="intersection")
    
    s, e = date(2026, 1, 1), date(2026, 1, 31)
    
    fr_bdays = set(hub.get_from_country("FR").business_days(s, e))
    us_bdays = set(hub.get_from_country("US").business_days(s, e))
    combined_bdays = set(combined.business_days(s, e))
    
    # Intersection: only days where BOTH are open
    expected = fr_bdays & us_bdays
    assert combined_bdays == expected


@pytest.mark.skipif(not WORKALENDAR_OK, reason="workalendar not installed")
def test_combined_union_two_countries(hub: BetterCalendar) -> None:
    """Test union: business day if ANY calendar is open."""
    # Combine FR and US with union
    combined = hub.combine([
        ("country", "FR"),
        ("country", "US")
    ], mode="union")
    
    s, e = date(2026, 1, 1), date(2026, 1, 15)
    
    fr_bdays = set(hub.get_from_country("FR").business_days(s, e))
    us_bdays = set(hub.get_from_country("US").business_days(s, e))
    combined_bdays = set(combined.business_days(s, e))
    
    # Union: days where AT LEAST ONE is open
    expected = fr_bdays | us_bdays
    assert combined_bdays == expected


@pytest.mark.skipif(not (QL_OK and WORKALENDAR_OK), reason="needs QuantLib and workalendar")
def test_combined_rfr_and_country(hub: BetterCalendar) -> None:
    """Test combining different calendar types (RFR + country)."""

    # Combine SOFR and FR
    combined = hub.combine([
        ("rfr", "SOFRRATE Index"),
        ("country", "FR")
    ], mode="intersection")
    
    s, e = date(2026, 7, 1), date(2026, 7, 31)
    
    combined_bdays = combined.business_days(s, e)
    
    # Should have some business days
    assert len(combined_bdays) > 0
    
    # All combined business days must be business days in both calendars
    sofr = hub.get_from_rfr("SOFRRATE Index")
    fr = hub.get_from_country("FR")
    
    for d in combined_bdays:
        assert sofr.is_business_day(d)
        assert fr.is_business_day(d)


@pytest.mark.skipif(not EXCHANGE_OK, reason="exchange-calendars not installed")
def test_combined_three_exchanges(hub: BetterCalendar) -> None:
    """Test combining multiple (3+) calendars."""
    # Day is business day only if Paris, New York AND London are all open
    combined = hub.combine([
        ("exchange", "XPAR"),
        ("exchange", "XNYS"),
        ("exchange", "XLON")
    ], mode="intersection")
    
    s, e = date(2026, 1, 1), date(2026, 1, 31)
    combined_bdays = set(combined.business_days(s, e))
    
    # Get individual calendars
    xpar_bdays = set(hub.get_from_exchange("XPAR").business_days(s, e))
    xnys_bdays = set(hub.get_from_exchange("XNYS").business_days(s, e))
    xlon_bdays = set(hub.get_from_exchange("XLON").business_days(s, e))
    
    # Intersection of all three
    expected = xpar_bdays & xnys_bdays & xlon_bdays
    assert combined_bdays == expected


def test_combined_calendar_invalid_mode(hub: BetterCalendar) -> None:
    """Test that invalid mode raises an error."""
    from better_calendar import CalendarError
    
    with pytest.raises(CalendarError, match="Invalid mode"):
        hub.combine([
            ("country", "FR"),
            ("country", "US")
        ], mode="invalid_mode")


def test_combined_calendar_empty_list(hub: BetterCalendar) -> None:
    """Test that empty calendar list raises an error."""
    from better_calendar import CalendarError
    
    with pytest.raises(CalendarError, match="at least one calendar"):
        hub.combine([], mode="intersection")


# ============================================================
# 9) Complex scenarios combining overrides and combinations
# ============================================================
@pytest.mark.skipif(not WORKALENDAR_OK, reason="workalendar not installed")
def test_override_then_combine(hub: BetterCalendar) -> None:
    """Test applying overrides then combining calendars."""
    # Create two calendars with overrides
    strike_day = date(2026, 5, 15)
    
    fr_with_strike = hub.with_overrides(
        "country", "FR",
        add_holidays=[strike_day]
    )
    
    us = hub.get_from_country("US")
    
    # Combine them
    from better_calendar import CombinedCalendarAdapter
    combined = CombinedCalendarAdapter(
        calendars=[fr_with_strike, us],
        mode="intersection"
    )
    
    # The strike day should affect the combined calendar
    # (if it was a business day in US, it won't be in combined)
    if us.is_business_day(strike_day):
        assert not combined.is_business_day(strike_day)


# ============================================================
# 10) Plotting functionality
# ============================================================
@pytest.mark.skipif(not (EXCHANGE_OK and CALPLOT_OK), reason="exchange-calendars and calplot not installed")
def test_plot_exchange_calendar_year(hub: BetterCalendar) -> None:
    """Test plotting an exchange calendar for a full year."""
    xpar = hub.get_from_exchange("XPAR")
    fig, ax = xpar.plot(year=2026)
    
    # Should return figure and axes
    assert fig is not None
    assert ax is not None


@pytest.mark.skipif(not (WORKALENDAR_OK and CALPLOT_OK), reason="workalendar and calplot not installed")
def test_plot_country_calendar_custom_range(hub: BetterCalendar) -> None:
    """Test plotting a country calendar with custom date range."""
    fr = hub.get_from_country("FR")
    fig, ax = fr.plot(start=date(2026, 1, 1), end=date(2026, 6, 30))
    
    # Should return figure and axes
    assert fig is not None
    assert ax is not None


@pytest.mark.skipif(not (QL_OK and CALPLOT_OK), reason="QuantLib and calplot not installed")
def test_plot_rfr_calendar(hub: BetterCalendar) -> None:
    """Test plotting an RFR calendar."""
    estr = hub.get_from_rfr("ESTRON Index")
    fig, ax = estr.plot(year=2026)
    
    # Should return figure and axes
    assert fig is not None
    assert ax is not None


@pytest.mark.skipif(not (WORKALENDAR_OK and CALPLOT_OK), reason="workalendar and calplot not installed")
def test_plot_combined_calendar(hub: BetterCalendar) -> None:
    """Test plotting a combined calendar."""
    combined = hub.combine([
        ("country", "FR"),
        ("country", "US")
    ], mode="intersection")
    fig, ax = combined.plot(year=2026)
    
    # Should return figure and axes
    assert fig is not None
    assert ax is not None


@pytest.mark.skipif(not (WORKALENDAR_OK and CALPLOT_OK), reason="workalendar and calplot not installed")
def test_plot_override_calendar(hub: BetterCalendar) -> None:
    """Test plotting a calendar with overrides."""
    fr_custom = hub.with_overrides(
        "country", "FR",
        add_holidays=[date(2026, 5, 15)]
    )
    fig, ax = fr_custom.plot(year=2026)
    
    # Should return figure and axes
    assert fig is not None
    assert ax is not None


@pytest.mark.skipif(not (WORKALENDAR_OK and CALPLOT_OK), reason="workalendar and calplot not installed")
def test_plot_invalid_params(hub: BetterCalendar) -> None:
    """Test that providing both year and start/end raises an error."""
    fr = hub.get_from_country("FR")
    
    with pytest.raises(ValueError, match="either 'year' or 'start'/'end'"):
        fr.plot(year=2026, start=date(2026, 1, 1))


# -------------------------
# local helper
# -------------------------
def _date_range(s: date, e: date):
    cur = s
    while cur <= e:
        yield cur
        cur += timedelta(days=1)