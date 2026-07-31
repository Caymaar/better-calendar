# better-calendar

One place for date logic: business-day arithmetic, calendar-aware offsets, date
normalisation, recurrence generation and calendar composition.

A calendar is a sorted `int64` array of good days over a bounded horizon. Membership,
offsets, counting and set algebra all reduce to `searchsorted` and numpy set operations on
that array — so everything is O(log n) per element and vectorised.

```python
import better_calendar as bcal

bcal.adjust("2026-05-31", "MF")          # '2026-05-29'  Sunday; forward would leave May
bcal.offset("2026-07-31", 5)             # '2026-08-07'
bcal.count("2026-07-27", "2026-08-01")   # 5            half-open [start, end)
```

`numpy` is the only required dependency. Importing the package does not import pandas.

## Status

Pre-1.0, built milestone by milestone (see `.claude/CLAUDE.md` §17).

| Milestone | Scope | State |
|---|---|---|
| M0 | Scaffolding, ruff / mypy --strict / pytest / CI | done |
| M1 | `core/`: epoch, type conversion and preservation, errors, `DateRange` | done |
| M2 | `Calendar`: membership, roll conventions, offsets, counting | done |
| M3 | Algebra, registry, `weekday` and `crypto:24x7` calendars | done |
| M4 | Providers, snapshots, CLI | not started |
| M5 | `BDay`, tenors, spot lags, pandas interop | not started |
| M6 | Schedules and recurrences | not started |
| M7 | Sessions (`session_of`, `session_bounds`, `grid`) | not started |
| M8 | Docs, YAML overrides, packaging, 1.0 | not started |

Until M4 lands, only `weekday` and `crypto:24x7` resolve. Named calendars such as `XNYS`
or `fin:TARGET2` are recognised as aliases and rejected with an explanatory error rather
than a bare "unknown calendar".

## Install

```bash
pip install better-calendar                  # numpy only
pip install 'better-calendar[pandas]'        # DatetimeIndex / Timestamp output
pip install 'better-calendar[all]'           # every provider, for snapshot generation
```

Python 3.9+.

## What it gives you

### Type transparency

Whatever you pass in comes back out. `date` in, `date` out; `Timestamp` in, `Timestamp`
out; sequence in, `DatetimeIndex` out (a `datetime64[D]` array when pandas is absent).

```python
from datetime import date
import better_calendar as bcal

bcal.offset(date(2026, 7, 31), 1)        # datetime.date(2026, 8, 3)
bcal.offset("20260731", 1)               # '20260803'
bcal.offset(20260731, 1)                 # 20260803
```

Accepted inputs: `date`, `datetime`, `pandas.Timestamp`, `numpy.datetime64`, ISO-8601
strings, the compact `"20260731"` form, and `yyyymmdd` ints. `DD/MM/YYYY` is rejected on
purpose — there is no way to tell it from `MM/DD/YYYY`, and a wrong guess is silent.

### Roll conventions

```python
from better_calendar import Roll

bcal.adjust("2026-08-01")                     # '2026-08-03'  following
bcal.adjust("2026-05-31", Roll.MODIFIED_FOLLOWING)   # '2026-05-29'
bcal.adjust("2026-08-01", "P")                # '2026-07-31'  preceding
```

`NONE`, `FOLLOWING`, `PRECEDING`, `MODIFIED_FOLLOWING`, `MODIFIED_PRECEDING`, `NEAREST`
(ties go forward) and `RAISE`. Short ISDA aliases (`"F"`, `"MF"`, …) are accepted
case-insensitively everywhere.

### Calendar algebra

Operations are named after **business days**, never after holidays — because "union of
two calendars" means opposite things depending on which one the speaker has in mind.

```python
a & b        # good in BOTH        == union of the holiday sets   <- settlement
a | b        # good in AT LEAST ONE
a - b        # good in a, not in b
a ^ b        # good in exactly one

Calendar.all_open([a, b, c])   # verbose alias for &
Calendar.any_open([a, b, c])   # verbose alias for |
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
ts = pd.Timestamp("2026-07-31 23:30", tz="UTC")   # Friday
ts.date()                                          # 2026-07-31  Friday
ts.tz_convert("Europe/Paris").date()               # 2026-08-01  Saturday
```

Opt out with `bcal.config.default_tz = "UTC"` if your service has already decided
everything is UTC. It is the library's only global state.

### Bounds

Every calendar has an explicit finite horizon (1970-01-01 to 2100-12-31 by default) and
raises `OutOfBoundsError` outside it. Nothing is ever extrapolated.

## Development

```bash
uv sync --all-extras
uv run pytest          # tests + doctests
uv run ruff check .
uv run mypy
```

Doctests run as part of the suite, so every example in this README and in the docstrings
is executed in CI. Roll conventions, membership and counting are cross-validated against
`numpy.busday_offset` over a ten-year horizon; `QuantLib` and `exchange-calendars` join as
oracles at M4.
