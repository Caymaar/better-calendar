# better-calendar

One place for date logic: business-day arithmetic, calendar-aware offsets, date
normalisation, recurrence generation and calendar composition.

A calendar is a sorted `int64` array of good days over a bounded horizon. Membership,
offsets, counting and set algebra all reduce to `searchsorted` and numpy set operations on
that array — so everything is O(log n) per element and vectorised.

```python
import better_calendar as bcal

bcal.adjust("2026-05-31", "MF")  # '2026-05-29'  Sunday; forward would leave May
bcal.offset("2026-07-31", 5)  # '2026-08-07'
bcal.count("2026-07-27", "2026-08-01")  # 5            half-open [start, end)
```

`numpy` is the only required dependency. Importing the package does not import pandas, and
answering a query never imports a holiday provider.

477 calendars ship in the wheel: 59 exchanges, 251 countries, 91 QuantLib settlement and
rate calendars, and 76 from workalendar.

## Install

```bash
pip install better-calendar                  # numpy only
pip install 'better-calendar[pandas]'        # DatetimeIndex / Timestamp output
pip install 'better-calendar[config]'        # read the organisation config file
pip install 'better-calendar[all]'           # every provider, for snapshot generation
```

Python 3.9+. The provider extras are only needed to *regenerate* the holiday snapshot;
using the shipped one needs nothing but numpy.

## What it gives you

### Type transparency

Whatever you pass in comes back out. `date` in, `date` out; `Timestamp` in, `Timestamp`
out; sequence in, `DatetimeIndex` out (a `datetime64[D]` array when pandas is absent).

```python
from datetime import date
import better_calendar as bcal

bcal.offset(date(2026, 7, 31), 1)  # datetime.date(2026, 8, 3)
bcal.offset("20260731", 1)  # '20260803'
bcal.offset(20260731, 1)  # 20260803
```

Accepted inputs: `date`, `datetime`, `pandas.Timestamp`, `numpy.datetime64`, ISO-8601
strings, the compact `"20260731"` form, and `yyyymmdd` ints. `DD/MM/YYYY` is rejected on
purpose — there is no way to tell it from `MM/DD/YYYY`, and a wrong guess is silent.

### Roll conventions

```python
from better_calendar import Roll

bcal.adjust("2026-08-01")  # '2026-08-03'  following
bcal.adjust("2026-05-31", Roll.MODIFIED_FOLLOWING)  # '2026-05-29'
bcal.adjust("2026-08-01", "P")  # '2026-07-31'  preceding
```

`NONE`, `FOLLOWING`, `PRECEDING`, `MODIFIED_FOLLOWING`, `MODIFIED_PRECEDING`, `NEAREST`
(ties go forward) and `RAISE`. Short ISDA aliases (`"F"`, `"MF"`, …) are accepted
case-insensitively everywhere.

### Calendar algebra

Operations are named after **business days**, never after holidays — because "union of
two calendars" means opposite things depending on which one the speaker has in mind.

```python
a & b  # good in BOTH        == union of the holiday sets   <- settlement
a | b  # good in AT LEAST ONE
a - b  # good in a, not in b
a ^ b  # good in exactly one

Calendar.all_open([a, b, c])  # verbose alias for &
Calendar.any_open([a, b, c])  # verbose alias for |
```

Composites are ordinary frozen `Calendar` objects, so they work in offsets and as cache
keys. Their bounds are the intersection of the operands', and they keep a timezone only if
every operand agrees on one. Heterogeneous weekmasks (Sun–Thu against Mon–Fri) fall out
correctly, because the implementation is set algebra on good days rather than merged
weekmask strings.

### Timezones

1. **Naive means "already in the right frame."** The date part is taken literally.
2. **Aware means "an instant."** Projecting it onto a calendar day needs an explicit
   timezone — the calendar's, or one you pass. A bare `to_date(aware)` raises.
3. **Offsets preserve wall-clock time and tzinfo.** `2026-03-27 09:00 Paris + 1 business
   day` is `2026-03-30 09:00 Paris`, which is +71h in absolute terms across the DST
   transition. That is intended.

The failure this exists to prevent:

```python
ts = pd.Timestamp("2026-07-31 23:30", tz="UTC")  # Friday
ts.date()  # 2026-07-31  Friday
ts.tz_convert("Europe/Paris").date()  # 2026-08-01  Saturday
```

Opt out with `bcal.config.default_tz = "UTC"` if your service has already decided
everything is UTC. It is the library's only global state.

### Named calendars

```python
bcal.get("XNYS")  # by MIC
bcal.get("NYSE")  # or by alias
bcal.offset("2026-07-02", 1, cal="XNYS")  # '2026-07-06', skipping 3 July
bcal.is_bday("2026-04-06", cal="EUR")  # False: Easter Monday, TARGET2 closed
bcal.list(provider="quantlib")  # what came from where
```

Identifiers are namespaced: a bare four-letter name is an ISO-10383 MIC (`XNYS`, `XPAR`),
and everything else is prefixed — `country:FR`, `fin:TARGET2`, `rate:SOFR`, `ql:` for any
QuantLib class and market, `wk:` for workalendar, `crypto:24x7`. Aliases live in one
declarative table, so `NYSE`, `TARGET`, `EUR` and `SONIA` all resolve.

### Tenors

```python
bcal.add_tenor("2026-01-31", "1M")  # '2026-02-28'  clamped
bcal.add_tenor("2026-02-28", "1M", eom=True)  # '2026-03-31'  end-of-month rule
bcal.add_tenor("2026-07-31", "1Y+2B", cal="XNYS")  # '2027-08-04'
```

Grammar: `term (('+' | '-') term)*` where a term is `[-] INT unit` and the units are `D`
calendar days, `B` business days, `W` weeks, `M` months, `Y` years. Terms apply **left to
right**, and the order matters — `"1M+2B"` is not `"2B+1M"`.

Two month-end rules, deliberately kept apart because conflating them is where the
off-by-one-day bugs live. **Clamping** is unconditional: 31 January plus a month is 28
February, because 31 February does not exist. **The end-of-month rule** is opt-in: with
`eom=True`, a date that is the last of its month lands on the last of the target month.

### Offsets as objects

```python
from better_calendar import BDay

date(2026, 7, 31) + BDay(5)  # datetime.date(2026, 8, 7)
"2026-07-02" + BDay(1, cal="XNYS")  # '2026-07-06'
series + BDay(3, cal="XNYS")  # works, but see below
```

`cal.offset(series, 3)` is the recommended form for containers — same answer, shorter
path. `BDay` exists for the places an offset *object* reads best. For pandas machinery
that demands a real `DateOffset` (`date_range`, `resample`), use
`cal.to_pandas_offset()`; note that it and `cal.offset` disagree when the start is not a
business day, because pandas counts the normalisation as the move and we do not.

Importing `better_calendar.integrations.pandas_` registers a `.cal` accessor:

```python
trades["settles"] = trades["traded"].cal.offset(2, cal="XNYS")
```

### Recurrences

The two questions that motivated the library:

```python
from better_calendar import FRI, THU

bcal.last_weekday("2026-01-01", "2026-12-31", FRI)  # last Friday of each month
bcal.nth_weekday("2026-01-01", "2026-12-31", 2, THU, freq="Q")  # 2nd Thursday of each quarter
```

`n` is 1-based and **negative counts from the end** — `-1` is "last", `-2` "second to
last". If a period has no such occurrence (February rarely has a fifth Friday) it is
skipped silently rather than raising, because raising would make the API unusable over
any real span.

```python
bcal.nth_day("2026-01-01", "2026-03-31", -1)  # last calendar day
bcal.nth_business_day("2026-01-01", "2026-03-31", 1, cal="XNYS")
bcal.month_ends("2026-01-01", "2026-03-31")  # 31 Jan, 28 Feb, 31 Mar
bcal.month_ends("2026-01-01", "2026-03-31", cal="XNYS")  # 30 Jan, 27 Feb, 31 Mar
bcal.quarter_ends("2026-01-01", "2026-12-31", anchor_month=2)  # a fiscal year
bcal.imm_dates("2026-01-01", "2026-12-31")  # 3rd Wed of Mar/Jun/Sep/Dec
bcal.option_expiries("2026-01-01", "2026-12-31", cal="XNYS")  # 3rd Fri, adjusted back
```

Passing `cal` to `month_ends` changes the *question*, not just the answer: without one you
get the last calendar day, with one the last business day.

### Schedules

```python
schedule = Schedule("2026-02-28", "2026-08-31", freq="3M", cal="XNYS", eom=True)

schedule.unadjusted()  # ['2026-02-28', '2026-05-31', '2026-08-31']
schedule.dates()  # ['2026-02-27', '2026-05-29', '2026-08-31']
schedule.periods()  # [DateRange(...), DateRange(...)]
```

Generation is **two strictly separated stages**, and this is the load-bearing design
decision. `unadjusted()` is pure calendar arithmetic — no calendar, no holidays, no roll
convention. Only `dates()` applies `cal.adjust`.

The reason is reconciliation. A downstream system holding a trade booked last year needs
to know its 15 March coupon is the same contractual date as ours, even if a holiday moved
when it actually pays. If the unadjusted schedule depended on holiday data, regenerating a
snapshot would make the *contract* appear to change.

Stubs handle terms that do not divide evenly: `short_front` (the default), `long_front`,
`short_back`, `long_back`, or `none` to refuse. A *front* stub anchors the regular grid on
the end date and generates backwards, so coupons land on maturity rather than drifting
away from it.

### Settlement

```python
bcal.spot("2026-07-31", "EUR")  # '2026-08-04'  T+2 in TARGET2
bcal.spot("2026-07-31", "GBP")  # '2026-07-31'  sterling settles same day
bcal.spot("2026-07-31", "CAD")  # '2026-08-04'  T+1, but Toronto is closed on the 3rd
```

Lags are money-market deposit conventions and live in `data/spot_lags.toml`, so a desk
can correct a row without a release. FX spot is a property of the *pair*, not of a
currency, and is deliberately out of scope.

### Sessions

A calendar day is the interval `[session_start, session_start + 24h)` in the calendar's
timezone — local midnight for ordinary calendars, `00:00` UTC for crypto, `17:00` New York
for FX. That one definition answers the question that actually comes up: *which day does
this instant belong to?*

```python
ts = pd.Timestamp("2026-07-31 23:30", tz="UTC")

bcal.session_of(ts, cal="XNYS")  # date(2026, 7, 31)
bcal.session_of(ts, tz="Europe/Paris")  # date(2026, 8, 1)  already Saturday there

paris = bcal.get("XPAR")
paris.session_bounds("2026-03-29")  # 23 hours long: the clocks went forward
paris.grid("2026-07-31", "2026-07-31", "4h")  # anchored on session_start, not UTC midnight
bcal.at_times(bcal.imm_dates("2026-01-01", "2026-12-31"), ["08:00", "16:00"])
```

A session really is 23 or 25 hours long across a daylight-saving transition, and that is
reported rather than normalised away — code that assumes 24 hours is the code this exists
to correct. (European transitions fall on Sundays, so an exchange session rarely spans
one; a 24/7 or `session_start`-shifted calendar does.)

`grid` is what prevents the classic mis-anchored resample: a four-hour grid built from UTC
midnight cuts a Tokyo or Paris session in the wrong places.

Deliberately **not** here: `is_open`, `next_open`, lunch breaks, early closes. `is_open()`
returning `is_bday()` would be false for every exchange with an opening bell, so the day
calendar simply does not have it.

### Organisation-specific calendars

A desk closes on 24 December; the euro area does not. Never fork a provider calendar for
that — compose on top of it in `./better-calendar.yaml`, or wherever
`$BETTER_CALENDAR_CONFIG` points:

```yaml
calendars:
  desk:paris:
    base: fin:TARGET2
    extra_holidays: ["2026-01-02", "2026-12-24"]
    tz: Europe/Paris
```

`bcal.get("desk:paris")` then resolves like any other calendar. Naming an entry after a
shipped calendar (`XNYS: {base: XNYS, extra_holidays: [...]}`) shadows it, so existing call
sites pick up the local version with no code change. See `better-calendar.yaml.example`.

TOML works identically. Reading either format needs the `config` extra on Python < 3.11;
on 3.11+ TOML costs nothing.

### Bounds

Every calendar has an explicit finite horizon and raises `OutOfBoundsError` outside it.
Nothing is ever extrapolated — and the horizon is what the upstream can actually answer
for, not what was asked:

```python
bcal.get("XTKS").bounds  # (1997-01-01, 2100-12-31)  Tokyo data starts in 1997
bcal.get("XHKG").bounds  # (1970-01-01, 2049-12-31)  Hong Kong data ends in 2049
bcal.get("ql:Israel.TASE")  # stops in 2025: the Hebrew calendar table ends there
```

That last one matters. Lunar, Hebrew and Islamic holidays are tabulated rather than
derived, and upstream tables end **without saying so** — past its table, QuantLib's
Shanghai calendar quietly drops from eighteen holidays a year to one, and keeps answering
"yes, business day" with total confidence. Snapshot generation detects that collapse and
clips the horizon, so you get `OutOfBoundsError` instead of a wrong answer.

### Where the data comes from

Holiday data is **snapshotted**, not computed at query time. Upgrading
`exchange-calendars` can never silently move a settlement date, because runtime never
calls it — it reads a file that a human reviewed and merged.

```bash
better-calendar snapshot --provider all    # regenerate; run rarely, commit the result
better-calendar diff                       # non-zero exit if any date moved
better-calendar describe rate:SOFR         # provenance: provider, version, bounds, hash
better-calendar next XNYS 2026-07-31 +5
```

The snapshot is one ISO date per line, one file per calendar, so a weekly CI job that
regenerates against the latest upstreams opens a pull request showing exactly which dates
changed — `+2027-05-31` / `-2027-06-01` — rather than "binary file changed".

## Development

```bash
uv sync --all-extras
uv run pytest          # tests + doctests
uv run ruff check .
uv run mypy
```

## Design notes

Ten invariants hold throughout, and the ones worth knowing before you read any code:

- **Frozen and hashable.** Calendars never mutate, which is what makes them safe as cache
  keys and safe to share between threads.
- **Finite bounds, never extrapolated.** Outside the horizon you get `OutOfBoundsError`,
  including where an upstream's own data quietly runs out.
- **Output type matches input type.** `date` in, `date` out, all the way through.
- **Half-open `[start, end)` by default.** Any other convention has to be named.
- **Set operations are named after business days, never holidays.** `a & b` is "good in
  both", which is the union of the holiday sets — the vocabulary trap that makes this
  worth stating twice.

Doctests run as part of the suite, so every example in the docstrings is executed in CI.
Roll conventions, membership and counting are cross-validated against `numpy.busday_offset`
over a ten-year horizon, and the committed snapshot is checked day-for-day against live
`QuantLib`, `exchange-calendars` and `holidays` over each calendar's full horizon. Those
tests are marked `oracle` and skip cleanly without the provider extras.
