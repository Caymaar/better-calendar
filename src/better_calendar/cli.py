"""
CLI pour visualiser les calendriers.

Inspiré du CLI de trading_calendars/tcal mais adapté pour better_calendar.
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from typing import List, Optional

import click

from . import BetterCalendar, CalendarAdapter


MONTHS = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'
]

WEEKDAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']


def render_month(calendar: CalendarAdapter, year: int, month: int, print_year: bool = False) -> str:
    """
    Render a single month calendar.
    
    Args:
        calendar: Calendar adapter to use
        year: Year to render
        month: Month to render (1-12)
        print_year: Whether to include year in title
    
    Returns:
        String representation of the month
    """
    lines = []
    
    # Title
    title = MONTHS[month - 1]
    if print_year:
        title += f' {year}'
    lines.append(f'{title:^28}'.rstrip())
    
    # Weekday headers (Mo to Su) - each column is 4 characters wide
    header = ''.join(f' {day} ' for day in WEEKDAYS)
    lines.append(header.rstrip())
    
    # Get all dates in month
    if month == 12:
        last_day = 31
    else:
        # Find last day of month
        from calendar import monthrange
        last_day = monthrange(year, month)[1]
    
    first_date = date(year, month, 1)
    
    # Start with appropriate spacing (Monday = 0, Sunday = 6)
    # Each day column is 4 characters wide
    weekday = first_date.weekday()  # Monday = 0
    current_line = ' ' * (4 * weekday)
    
    for day in range(1, last_day + 1):
        d = date(year, month, day)
        
        # Check if it's a business day
        if calendar.is_business_day(d):
            # Business day - no brackets
            day_str = f' {day:2} '
        else:
            # Holiday/weekend - with brackets
            day_str = f'[{day:2}]'
        
        current_line += day_str
        
        # New line after Sunday (weekday 6)
        if d.weekday() == 6:  # Sunday
            lines.append(current_line)
            current_line = ''
    
    # Add last line if not empty
    if current_line:
        lines.append(current_line)
    
    return '\n'.join(lines)


def concat_months(month_strings: List[str], width: int = 28) -> str:
    """
    Concatenate multiple month strings horizontally.
    
    Args:
        month_strings: List of month string representations
        width: Width of each month column
    
    Returns:
        Horizontally concatenated months
    """
    as_lines = [s.splitlines() for s in month_strings]
    max_lines = max(len(lines) for lines in as_lines)
    
    # Pad all to same height
    for lines in as_lines:
        missing_lines = max_lines - len(lines)
        if missing_lines:
            lines.extend([' ' * width] * missing_lines)
    
    # Concatenate horizontally
    rows = []
    for row_parts in zip(*as_lines):
        row_parts = list(row_parts)
        for n, row_part in enumerate(row_parts):
            missing_space = width - len(row_part)
            if missing_space:
                row_parts[n] = row_part + ' ' * missing_space
        rows.append('   '.join(row_parts))
    
    return '\n'.join(row.rstrip() for row in rows)


def render_year(calendar: CalendarAdapter, year: int) -> str:
    """
    Render a full year calendar (3 months per row).
    
    Args:
        calendar: Calendar adapter to use
        year: Year to render
    
    Returns:
        String representation of the full year
    """
    # Generate all 12 months
    month_strings = []
    for row in range(4):
        row_months = []
        for col in range(3):
            month = row * 3 + col + 1
            row_months.append(render_month(calendar, year, month, print_year=False))
        month_strings.append(row_months)
    
    # Build output
    output = [f'{year:^88}\n'.rstrip()]
    output.append('\n\n'.join(concat_months(ms, 28) for ms in month_strings))
    
    return '\n'.join(output)


@click.command()
@click.argument('year', type=int, required=False)
@click.argument('month', type=int, required=False)
@click.option('-c', '--country', multiple=True, help='Country ISO code (e.g., FR, US, GB)')
@click.option('-e', '--exchange', multiple=True, help='Exchange MIC code (e.g., XPAR, XNYS, XLON)')
@click.option('-r', '--rfr', multiple=True, help='RFR ticker (e.g., "ESTRON Index", "SOFRRATE Index")')
@click.option('-m', '--mode', type=click.Choice(['intersection', 'union']), default='intersection',
              help='Combination mode when multiple calendars specified')
@click.option('--add-holiday', multiple=True, type=str, 
              help='Add custom holiday (format: YYYY-MM-DD)')
@click.option('--remove-holiday', multiple=True, type=str,
              help='Remove holiday (format: YYYY-MM-DD)')
def main(year: Optional[int], month: Optional[int], country: tuple, exchange: tuple, 
         rfr: tuple, mode: str, add_holiday: tuple, remove_holiday: tuple):
    """
    Display a calendar showing business days and holidays.
    
    Business days are shown as regular numbers.
    Holidays/weekends are shown in brackets [like this].
    
    Examples:
    
        # Show French calendar for 2026
        chub -c FR 2026
        
        # Show January 2026 for French calendar
        chub -c FR 2026 1
        
        # Combine French and US calendars (intersection)
        chub -c FR -c US --mode intersection 2026
        
        # Show Paris stock exchange
        chub -e XPAR 2026
        
        # Show €STR calendar
        chub -r "ESTRON Index" 2026
        
        # Mix different types with union
        chub -c FR -e XPAR --mode union 2026
        
        # Add a custom holiday (strike day)
        chub -c FR --add-holiday 2026-05-15 2026
    """
    # Initialize hub
    hub = BetterCalendar.default()
    
    # Validate we have at least one calendar
    if not (country or exchange or rfr):
        click.echo("Error: Must specify at least one calendar (--country, --exchange, or --rfr)", err=True)
        click.echo("Use --help for more information", err=True)
        sys.exit(1)
    
    # Default to current year/month if not specified
    if year is None:
        now = datetime.now()
        year = now.year
        if month is None:
            month = None  # Show full year
    
    # Build list of calendars to combine
    calendar_entries = []
    
    for c in country:
        calendar_entries.append(('country', c))
    
    for e in exchange:
        calendar_entries.append(('exchange', e))
    
    for r in rfr:
        calendar_entries.append(('rfr', r))
    
    try:
        # Get the calendar
        if len(calendar_entries) == 1:
            # Single calendar
            kind, code = calendar_entries[0]
            calendar = hub._resolve(kind, code)
        else:
            # Multiple calendars - combine
            calendar = hub.combine(calendar_entries, mode=mode)
        
        # Apply overrides if any
        if add_holiday or remove_holiday:
            add_dates = [datetime.strptime(d, '%Y-%m-%d').date() for d in add_holiday]
            remove_dates = [datetime.strptime(d, '%Y-%m-%d').date() for d in remove_holiday]
            
            from . import OverrideCalendarAdapter
            calendar = OverrideCalendarAdapter(
                base_calendar=calendar,
                add_holidays=tuple(add_dates),
                remove_holidays=tuple(remove_dates)
            )
        
        # Render calendar
        if month is not None:
            # Single month
            output = render_month(calendar, year, month, print_year=True)
        else:
            # Full year
            output = render_year(calendar, year)
        
        click.echo(output)
        
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
