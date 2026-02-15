# Better Calendar

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
![Version](https://img.shields.io/badge/version-1.0.0-green.svg)
[![Downloads](https://pepy.tech/badge/better-calendar)](https://pepy.tech/project/better-calendar)

A unified Python library for managing business day calendars and holidays across different sources, such as exchanges, countries or risk-free rates.

- **Exchanges**: Trading calendars via `exchange-calendars` (XPAR, XNYS, XLON, etc.)
- **Countries**: National holidays via `workalendar` (FR, US, GB, etc.)
- **RFR**: Risk-free rate fixing calendars via `QuantLib` (ESTR, SOFR, etc.)

## Installation

```bash
pip install better-calendar
```

For development:

```bash
git clone https://github.com/yourusername/better-calendar.git
cd better-calendar
uv sync
```

## Quick Start

```python
from better_calendar import BetterCalendar
from datetime import date

# Initialize the hub
hub = BetterCalendar.default()

# Check if a date is a business day
calendar = hub.get_from_country("FR")
is_working = calendar.is_business_day(date(2026, 1, 1))  # False (New Year)

# Get all business days in a range
business_days = calendar.business_days(
    date(2026, 1, 1), 
    date(2026, 12, 31)
)

# Get all holidays (including weekends)
holidays = calendar.holidays(date(2026, 1, 1), date(2026, 12, 31))
```

## Core Features

### 1. Exchange Calendars

Access trading calendars for major stock exchanges:

```python
# Euronext Paris
xpar = hub.get_from_exchange("XPAR")
is_trading = xpar.is_business_day(date(2026, 12, 25))  # False (Christmas)

# New York Stock Exchange
xnys = hub.get_from_exchange("XNYS")
holidays = xnys.holidays(date(2026, 1, 1), date(2026, 12, 31))

# London Stock Exchange
xlon = hub.get_from_exchange("XLON")
business_days = xlon.business_days(date(2026, 1, 1), date(2026, 3, 31))
```

### 2. Country Calendars

Access national holiday calendars:

```python
# France
fr = hub.get_from_country("FR")
french_holidays = fr.holidays(date(2026, 1, 1), date(2026, 12, 31))

# United States
us = hub.get_from_country("US")
us_business_days = us.business_days(date(2026, 1, 1), date(2026, 12, 31))

# United Kingdom
gb = hub.get_from_country("GB")
is_working = gb.is_business_day(date(2026, 5, 4))  # May Day
```

### 3. RFR (Risk-Free Rate) Calendars

Access fixing calendars for reference rates:

```python
# Euro Short-Term Rate (€STR / ESTR)
estr = hub.get_from_rfr("ESTRON Index")
is_fixing_day = estr.is_business_day(date(2026, 12, 25))

# Secured Overnight Financing Rate (SOFR)
sofr = hub.get_from_rfr("SOFRRATE Index")
fixing_days = sofr.business_days(date(2026, 1, 1), date(2026, 12, 31))
```

### 4. Unified API

Navigate business days with a single interface:

```python
# Next business day
next_day = hub.next_business_day("country", "FR", date(2026, 1, 3))

# Previous business day
prev_day = hub.previous_business_day("exchange", "XPAR", date(2026, 1, 3))

# Offset by N business days
future_day = hub.offset_business_days("rfr", "ESTRON Index", date(2026, 1, 15), 10)
past_day = hub.offset_business_days("country", "FR", date(2026, 1, 15), -5)
```

## Advanced Usage

### Calendar Overrides

Add or remove specific holidays:

```python
# Add exceptional holiday (e.g., strike day)
xpar_with_strike = hub.with_overrides(
    "exchange", "XPAR",
    add_holidays=[date(2026, 5, 15)]
)

# Remove holiday (exceptional opening)
fr_special = hub.with_overrides(
    "country", "FR",
    remove_holidays=[date(2026, 1, 1)]
)

# Check the modified calendar
is_open = xpar_with_strike.is_business_day(date(2026, 5, 15))  # False
```

### Combined Calendars

Combine multiple calendars with intersection or union logic:

```python
# Intersection: business day only if ALL calendars are open
combined_strict = hub.combine([
    ("country", "FR"),
    ("country", "US")
], mode="intersection")
# Returns True only on days when both France AND US are working

# Union: business day if AT LEAST ONE calendar is open
combined_flexible = hub.combine([
    ("exchange", "XPAR"),
    ("exchange", "XNYS")
], mode="union")
# Returns True if Paris OR New York (or both) are open

# Mix different calendar types
multi_calendar = hub.combine([
    ("country", "FR"),
    ("exchange", "XPAR"),
    ("rfr", "ESTRON Index")
], mode="intersection")
```

### Visualization

Generate visual calendar heatmaps:

```python
# Plot a calendar for 2026
calendar = hub.get_from_country("FR")
calendar.plot(year=2026)

# Custom date range
calendar.plot(
    start=date(2026, 1, 1),
    end=date(2026, 6, 30),
    cmap="RdYlGn"
)
```

## Command Line Interface

The package includes a CLI tool (`bcal`) for quick calendar visualization:

```bash
# Display French calendar for 2026
bcal -c FR 2026

# Display Euronext Paris for March 2026
bcal -e XPAR 2026 3

# Current year (defaults to today)
bcal -c US

# Combine multiple calendars (intersection)
bcal -c FR -c US 2026

# Combine with union mode
bcal -e XPAR -e XNYS --mode union 2026 1

# RFR calendar
bcal -r "ESTRON Index" 2026

# Add custom holidays
bcal -c FR --add-holiday 2026-05-15 2026
```

### CLI Output Format

Business days are shown as regular numbers, holidays and weekends appear in brackets:

```
                        January 2026
 Mo  Tu  We  Th  Fr  Sa  Su 
             [ 1][ 2][ 3][ 4]
  5   6   7   8   9 [10][11]
 12  13  14  15  16 [17][18]
 19  20  21  22  23 [24][25]
 26  27  28  29  30 [31]
```

### CLI Options

- `-c, --country`: Country ISO code (e.g., FR, US, GB). Can be repeated.
- `-e, --exchange`: Exchange MIC code (e.g., XPAR, XNYS, XLON). Can be repeated.
- `-r, --rfr`: RFR ticker (e.g., "ESTRON Index"). Can be repeated.
- `-m, --mode`: Combination mode: `intersection` (default) or `union`.
- `--add-holiday`: Add custom holiday (format: YYYY-MM-DD). Can be repeated.
- `--remove-holiday`: Remove a holiday (format: YYYY-MM-DD). Can be repeated.

## Real-World Examples

### Financial Trading

Calculate settlement dates for cross-border transactions:

```python
from datetime import date

hub = BetterCalendar.default()

# T+2 settlement for both Paris and New York
trade_date = date(2026, 1, 15)
calendar = hub.combine([
    ("exchange", "XPAR"),
    ("exchange", "XNYS")
], mode="intersection")

settlement_date = calendar.offset_business_days(trade_date, 2)
print(f"Settlement: {settlement_date}")
```

### Interest Calculation

Calculate interest periods considering only business days:

```python
start = date(2026, 1, 1)
end = date(2026, 12, 31)

calendar = hub.get_from_country("FR")
business_days = calendar.business_days(start, end)

print(f"Business days in 2026: {len(business_days)}")
```

### Rate Fixing Availability

Check when reference rate fixings are published:

```python
# Check ESTR fixing availability
estr = hub.get_from_rfr("ESTRON Index")
fixing_date = date(2026, 12, 25)

if estr.is_business_day(fixing_date):
    print("ESTR fixing available")
else:
    # Get next available fixing date
    next_fixing = hub.next_business_day("rfr", "ESTRON Index", fixing_date)
    print(f"Next fixing: {next_fixing}")
```

## Supported Calendars

### Exchanges (via exchange-calendars)

Common exchange codes:
- `XPAR`: Euronext Paris
- `XNYS`: New York Stock Exchange
- `XLON`: London Stock Exchange
- `XHKG`: Hong Kong Stock Exchange
- `XTKS`: Tokyo Stock Exchange
- `XFRA`: Deutsche Börse (Frankfurt)

See [exchange-calendars documentation](https://github.com/gerrymanoim/exchange_calendars) for full list.

### Countries (via workalendar)

Common country codes:
- `FR`: France
- `US`: United States
- `GB`: United Kingdom
- `DE`: Germany
- `JP`: Japan
- `CN`: China

See [workalendar documentation](https://github.com/workalendar/workalendar) for full list.

### RFR Tickers (via QuantLib)

Supported reference rates:
- `ESTRON Index`: Euro Short-Term Rate (TARGET calendar)
- `SOFRRATE Index`: Secured Overnight Financing Rate (US calendar)
- Additional QuantLib calendars available

## Testing

Run the test suite:

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=better_calendar

# Run specific test
uv run pytest tests/test_calendar_hub.py::test_combined_calendars

# Run tests matching a pattern
uv run pytest -k "intersection"
```

## API Reference

### BetterCalendar

Main hub class for accessing calendars.

**Methods:**

- `default()`: Create hub with default adapters
- `get_from_exchange(code)`: Get exchange calendar
- `get_from_country(code)`: Get country calendar
- `get_from_rfr(ticker)`: Get RFR calendar
- `combine(calendars, mode)`: Combine multiple calendars
- `with_overrides(kind, code, add_holidays, remove_holidays)`: Create calendar with overrides
- `next_business_day(kind, code, date)`: Get next business day
- `previous_business_day(kind, code, date)`: Get previous business day
- `offset_business_days(kind, code, date, offset)`: Offset by N business days

### CalendarAdapter

Protocol defining the calendar interface.

**Methods:**

- `is_business_day(date)`: Check if date is a business day
- `business_days(start, end)`: Get all business days in range
- `holidays(start, end)`: Get all holidays (including weekends) in range
- `plot(year, start, end, cmap, figsize)`: Generate visual calendar

## Dependencies

- **exchange-calendars** (>=4.5): Trading calendars for global exchanges
- **workalendar** (>=17.0): National and regional holiday calendars
- **QuantLib** (>=1.41): Financial modeling library with calendar support
- **click** (>=8.1): Command-line interface creation
- **matplotlib** (>=3.9): Plotting library for visualizations
- **pandas** (>=2.3): Data manipulation for calendar operations

## Contributing

Contributions are welcome. Please ensure:

1. All tests pass: `uv run pytest`
2. Code follows existing style conventions
3. New features include tests
4. Documentation is updated

## License

MIT License

Copyright (c) 2026 Better Calendar Contributors

See [LICENSE](LICENSE) file for details.

## Related Projects

- [exchange-calendars](https://github.com/gerrymanoim/exchange_calendars): Trading calendar library
- [workalendar](https://github.com/workalendar/workalendar): Worldwide holidays and working days library
- [QuantLib](https://www.quantlib.org/): Quantitative finance library
- [pandas_market_calendars](https://github.com/rsheftel/pandas_market_calendars): Alternative market calendar library
