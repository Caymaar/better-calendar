# Reference

Every public function, what it does, and the design decisions behind the ones that are
easy to get wrong.

- [The model in one page](#the-model-in-one-page)
- [Dependencies](#dependencies)
- [Where the calendar data comes from](#where-the-calendar-data-comes-from)
- [Calendar identifiers](#calendar-identifiers)
- [API reference](#api-reference)
- [Invariants](#invariants)

---

## The model in one page

**A calendar is a sorted `int64` array of good days over a bounded horizon.**

Days are counted from 1970-01-01. Membership, offsets, counting and set algebra all reduce
to `numpy.searchsorted` on that array, so every operation is O(log n) per element and
vectorised. Nothing loops over dates.

Four consequences worth internalising:

| | |
|---|---|
| **Calendars are frozen** | They never mutate, which makes them safe as cache keys and safe to share between threads. Deriving one returns a new object. |
| **Horizons are finite** | Outside its bounds a calendar raises `OutOfBoundsError` rather than extrapolating. The horizon is what the upstream source can *actually* answer for, which is sometimes narrower than 1970–2100. |
| **Types are preserved** | `date` in, `date` out. `Timestamp` in, `Timestamp` out. A sequence comes back as a `DatetimeIndex`. |
| **Intervals are half-open** | `[start, end)` everywhere. Any other convention has to be named explicitly. |

---

## Dependencies

### What you must install

**`numpy>=1.24`. That is the entire mandatory runtime dependency.**

Not pandas. Not a holiday provider. Importing `better_calendar` imports neither, and a
CI job asserts it on every commit.

```python
import sys, better_calendar as bcal

assert "pandas" not in sys.modules  # holds
assert "exchange_calendars" not in sys.modules  # holds, even after 479 lookups
```

### Optional extras

| Extra | Packages | What it unlocks |
|---|---|---|
| `pandas` | `pandas>=2.0` | `DatetimeIndex` / `Timestamp` output, `session_bounds`, `grid`, `at_times`, the `.cal` accessor. Without it, multi-date results degrade to `datetime64[D]` arrays. |
| `config` | `PyYAML>=6.0`, `tomli` (Python < 3.11) | Reading the organisation configuration file. |
| `exchange` | `exchange-calendars>=4.5` | **Regenerating** exchange snapshots. Never needed to use them. |
| `holidays` | `holidays>=0.40` | Regenerating country snapshots. |
| `quantlib` | `QuantLib>=1.32` | Regenerating settlement and rate snapshots. |
| `workalendar` | `workalendar>=17.0` | Regenerating the fallback snapshots. |
| `all` | all of the above | A full development install. |

```bash
pip install better-calendar                # numpy only — 477 calendars work
pip install 'better-calendar[pandas]'      # DatetimeIndex output
pip install 'better-calendar[all]'         # to regenerate the data
```

The four provider packages are **build-time only**. They run when somebody regenerates the
snapshot; they are never imported to answer a question. That is the point of the next
section.

### Why the core is kept this light

A date library ends up in the dependency tree of everything: pricing, risk, reporting,
schedulers. Every mandatory dependency it carries is one every consumer inherits, and every
version constraint it declares is one that can conflict. `numpy` is already there in
practice; `pandas`, `QuantLib` and `exchange-calendars` are not, and pulling them in
uninvited would make the library harder to adopt than the loop it replaces.

---

## Where the calendar data comes from

### The problem

If `bcal.get("XNYS")` asked `exchange-calendars` at query time, then upgrading that package
could move a settlement date **with nobody deciding to**. A back office recalculates, a
date shifts by a day, and the change is invisible because nothing in your repository
changed.

### The answer: freeze it

Holiday data is materialised once, committed to the repository, shipped inside the wheel,
and read from disk. Three moments, deliberately separate:

| When | What happens | Triggered by |
|---|---|---|
| **Rarely, deliberately** | `better-calendar snapshot` imports the four upstream packages, materialises every calendar, and writes the data files. **You commit the result.** | a person, or the drift job |
| **At build time** | The already-committed files are copied into the wheel. **No computation, no provider import.** | `uv build` |
| **At query time** | A local file is read, about 0.06 ms per calendar, loaded lazily. | the user |

So publishing a release does **not** rebuild the calendars. Whatever is committed at tag
time is exactly what ships. If the snapshot is stale, a stale snapshot ships — which is why
the drift job below exists.

### The layout

```
src/better_calendar/data/
├── manifest.json          provenance per calendar: provider, upstream version,
│                          bounds, weekmask, tz, holiday count, sha256
└── calendars/
    ├── XNYS.csv           one ISO date per line, sorted ascending
    ├── country-FR.csv
    └── fin-TARGET2.csv
```

477 calendars, about 1.7 MB in the wheel.

### Why plain text rather than Parquet

The whole point of freezing the data is that an upstream change arrives as a **reviewable
pull request**. A Parquet or `.npz` blob renders as `Binary file changed` and the reviewer
has to run a tool to see anything. One ISO date per line renders as:

```diff
  XNYS.csv
+ 2027-05-31
- 2027-06-01
```

which is the thing a human actually needs to see. Text also keeps `numpy` the only
dependency, where Parquet would require `pyarrow` — roughly 100 MB installed to read
100 KB of integers.

### How an upstream correction reaches you

```
exchange-calendars publishes a new version
        ↓
weekly CI job installs the latest upstreams,
regenerates in memory, compares against the committed files
        ↓
a date moved → non-zero exit → a pull request is opened
        ↓
a human reads the diff and merges (or does not)
        ↓
a new release of better-calendar
```

Upgrading a provider on your own machine changes nothing. The only way a date moves is a
merged pull request.

**Corollary, worth stating plainly:** if an exchange announces a closure that the upstream
package has not yet published, this library does not have it either. Wait for the upstream,
or add a local override (below). The library never hand-codes a holiday rule.

### Honest bounds

A calendar's horizon is what its source can actually answer for. Two distinct reasons it
may be narrower than requested:

**1. The upstream refuses.** `exchange-calendars` will not evaluate Tokyo before 1997, nor
Hong Kong after 2049.

**2. The upstream degrades silently — the dangerous one.** Lunar, Hebrew and Islamic
holidays cannot be derived from a rule the way Easter can; upstreams tabulate them, and the
tables end **without any signal**. Past 2026, QuantLib's Shanghai calendar returns one
holiday a year instead of eighteen — Chinese New Year simply gone — while still answering
"yes, business day" with complete confidence.

Snapshot generation detects that collapse by comparing each calendar's annual holiday count
against its own norm, and clips the horizon. You get `OutOfBoundsError` instead of a wrong
answer. 62 of the 477 calendars have a narrowed horizon for one of these two reasons, and
each one is recorded in the manifest so a change shows up in review.

### Commands

```bash
better-calendar snapshot --provider all      # regenerate; commit the result
better-calendar snapshot --only XNYS,XPAR    # just a few
better-calendar diff                         # non-zero exit if a date moved
better-calendar describe rate:SOFR           # provenance as JSON
better-calendar next XNYS 2026-07-31 +5
better-calendar list --provider quantlib
```

---

## Calendar identifiers

Namespaced, so a bare name can only mean one thing.

| Form | Meaning | Count | Source |
|---|---|---|---|
| `XNYS`, `XPAR`, `XTKS` | ISO-10383 MIC, no prefix | 59 | `exchange-calendars` |
| `country:FR`, `country:US-NY` | ISO-3166 civil calendars | 251 | `holidays` |
| `fin:TARGET2`, `fin:NYB`, `fin:LNB` | Named settlement centres | 12 | `QuantLib` |
| `rate:SOFR`, `rate:ESTR`, `rate:SONIA` | Risk-free-rate calendars | 6 | `QuantLib` |
| `ql:UnitedStates.NYSE` | Any QuantLib class and market | 79 | `QuantLib` |
| `wk:FR` | Fallback civil calendars | 76 | `workalendar` |
| `crypto:24x7` | Always open, UTC | 1 | built in |
| `weekday` | Monday–Friday, no holidays | 1 | built in |

Aliases live in one declarative table and resolve to the same object as their target:
`NYSE`, `NASDAQ`, `TARGET`, `EUR`, `GBP`, `USD`, `JPY`, `CHF`, `CAD`, `SONIA`, `ESTR`,
`CRYPTO`, and every currency in the settlement-lag table.

An unknown name raises `UnknownCalendarError` with did-you-mean suggestions.

**Country calendars are not settlement calendars.** `country:US` is what the United States
observes as public holidays; `fin:NYB` is when money moves in New York; `XNYS` is when the
exchange trades. They are three different questions with three different answers — do not
substitute one for another.

### Resolution order

1. Already a `Calendar` — passes through untouched. `None` means `weekday`.
2. Registered with `register()`.
3. Defined in the organisation configuration file.
4. Built in (`weekday`, `crypto:24x7`).
5. The committed snapshot.
6. An alias, then resolve again from step 2.

### Organisation-specific calendars

A desk closes on 24 December; the euro area does not. **Never fork a provider calendar** for
that — a fork silently stops receiving upstream corrections. Compose on top instead, in
`./better-calendar.yaml` or wherever `$BETTER_CALENDAR_CONFIG` points:

```yaml
calendars:
  desk:paris:
    base: fin:TARGET2
    extra_holidays: ["2026-01-02", "2026-12-24"]
    remove_holidays: []
    tz: Europe/Paris

  # Naming an entry after a shipped calendar shadows it, so existing call sites pick
  # up the local version with no code change.
  XNYS:
    base: XNYS
    extra_holidays: ["2026-11-27"]

  # A desk settling across two centres: `base` takes a list, `base_op` says how to
  # combine them. Required as soon as there is more than one, and never defaulted —
  # the two readings are exact opposites (see Calendar algebra).
  desk:eurgbp:
    base: [fin:TARGET2, fin:LNB]
    base_op: all_open        # good in *both*; closed as soon as either closes
    tz: Europe/Paris
```

| Key | Meaning |
|---|---|
| `base` | One identifier, or a list of them. Omit to build from scratch. |
| `base_op` | `all_open` or `any_open`. **Required** with a list, rejected without one. |
| `extra_holidays` / `remove_holidays` | Local closures and reopenings, applied on top. |
| `tz`, `session_start`, `weekmask`, `bounds` | Override what the base provides. |

A composite base follows the algebra rules: bounds are the **intersection** of the
operands', and `tz` / `session_start` are dropped unless every operand agrees — set them on
the entry when the desk needs instant semantics. `difference` and `symmetric_difference`
are not available here, being binary and order-sensitive; compose those in Python, where
the operand order is visible.

TOML works identically. Reading either format needs the `config` extra on Python < 3.11; on
3.11+ TOML costs nothing. A configuration file that cannot be read raises rather than being
silently ignored — a closure that is quietly *not applied* is far worse than one that
refuses to load.

---

## API reference

Everything below is exported from the package root: `import better_calendar as bcal`.

### Conversion and types

| Function | Returns |
|---|---|
| `to_date(value, tz=None)` | `datetime.date` |
| `to_datetime(value, tz=None)` | `datetime.datetime`, preserving time and tzinfo |
| `to_timestamp(value, tz=None)` | `pandas.Timestamp` |

Accepted inputs: `date`, `datetime`, `pandas.Timestamp`, `numpy.datetime64`, ISO-8601
strings, the compact `"20260731"` form, `yyyymmdd` integers, and sequences of any of those.

Parsing is strict on purpose. `DD/MM/YYYY` and `MM/DD/YYYY` are **rejected**, because there
is no way to tell them apart and a wrong guess is silent. An integer is read as `yyyymmdd`
and never as a Unix timestamp.

### Business-day arithmetic

| Function | Description |
|---|---|
| `is_bday(value, cal=, tz=)` | `bool`, or a `bool` array for a sequence |
| `next_bday(value, cal=, inclusive=False)` | next business day on or after |
| `prev_bday(value, cal=, inclusive=False)` | previous business day on or before |
| `adjust(value, roll, cal=, tz=)` | move onto a business day per a roll convention |
| `offset(value, n, cal=, roll=, tz=)` | move `n` business days |
| `count(start, end, cal=, closed="left")` | count business days, **signed** |
| `sessions(cal=)` | every business day inside the calendar's bounds |

`count` being signed is what makes `count(d, offset(d, n)) == n` hold for negative `n` too.

`closed` accepts `"left"` (the default, `[a, b)`), `"right"`, `"both"`, `"neither"`.

### Roll conventions — `Roll`

| Member | Short | Behaviour |
|---|---|---|
| `NONE` | | leave unadjusted |
| `FOLLOWING` | `"F"` | next business day |
| `PRECEDING` | `"P"` | previous business day |
| `MODIFIED_FOLLOWING` | `"MF"` | forward, unless that leaves the month — then back |
| `MODIFIED_PRECEDING` | `"MP"` | back, unless that leaves the month — then forward |
| `NEAREST` | `"N"` | whichever is closer; ties go forward |
| `RAISE` | | raise `NotABusinessDayError` |

Short aliases are accepted case-insensitively everywhere a roll is taken.

> **`offset` normalises first, then moves**, matching `numpy.busday_offset`. So `offset` on
> a Saturday with `n=1` and `roll=FOLLOWING` lands on Tuesday, not Monday. `pandas`'
> `CustomBusinessDay` counts the normalisation as the move and lands on Monday. Neither is
> wrong; they are not interchangeable. See `to_pandas_offset` below.

### Calendars — `Calendar`

Frozen, hashable, safe as a cache key.

| Attribute | |
|---|---|
| `name` | identifier |
| `holidays` | sorted, unique, read-only `datetime64[D]` array |
| `weekmask` | which weekdays can be business days |
| `bounds` | inclusive `(first, last)` horizon |
| `tz` | IANA timezone, or `None` for no instant semantics |
| `session_start` | local time a calendar day begins |
| `provider`, `provider_version` | provenance |

Methods mirror the free functions above, plus:

| Method | Description |
|---|---|
| `good_days(start=None, end=None)` | the raw `int64` array, read-only |
| `bdays_between(a, b, closed=)` | the business days in an interval |
| `holidays_between(a, b, closed=)` | the holidays in an interval |
| `describe()` | provenance and shape as a plain dict |
| `with_holidays(extra)` / `without_holidays(dates)` | derive a **new** calendar |
| `bday(n=1, roll=)` | a `BDay` bound to this calendar |
| `to_pandas_offset()` | a real `pandas.offsets.CustomBusinessDay` |
| `session_of`, `session_bounds`, `grid` | see Sessions |

### Registry

| Function | Description |
|---|---|
| `get(name)` | resolve an identifier or alias; memoised |
| `list(provider=None)` | every resolvable identifier |
| `describe(name)` | provenance dict, plus the requested and canonical names |
| `register(name, calendar, overwrite=False)` | install your own |
| `unregister(name)` | remove it |
| `resolve(cal)` | coerce a `Calendar \| str \| None` — what every `cal=` argument uses |
| `reload_config()` | re-read the organisation configuration file |

### Calendar algebra

Operations are named after **business days**, never after holidays. This matters more than
it sounds: "the union of two calendars" means the opposite thing depending on which the
speaker has in mind.

| Expression | Meaning |
|---|---|
| `a & b` | good in **both** — which is the **union of the holiday sets**. The settlement case. |
| `a \| b` | good in at least one |
| `a - b` | good in `a`, not in `b` |
| `a ^ b` | good in exactly one |
| `Calendar.all_open([a, b, c])` | verbose alias for `&` |
| `Calendar.any_open([a, b, c])` | verbose alias for `\|` |

A cash flow between New York and the euro area can only move on a day **both** centres are
open. That is `a & b`. Somebody describing it as "the union of the calendars" is thinking in
holidays and would reach for `|` — hence the verbose aliases, which read unambiguously in
review.

Composites are ordinary `Calendar` objects. Their bounds are the intersection of the
operands'; they keep a timezone only if every operand declares the same one. The
implementation is numpy set algebra on good days, never a merge of weekmask strings, which
is why crossing a Sunday–Thursday calendar with a Monday–Friday one works for free.

### Offsets — `BDay`

```python
date(2026, 7, 31) + BDay(1)  # datetime.date(2026, 8, 3)
"2026-07-02" + BDay(1, cal="XNYS")  # '2026-07-06'
date(2026, 8, 3) - BDay(1)
BDay(2) * 3 == BDay(6)
-BDay(2) == BDay(-2)
series + BDay(3, cal="XNYS")  # works; see below
```

`cal.offset(series, 3)` is the recommended form for containers — same answer, shorter path,
no operator dispatch. `BDay` is for the places where an offset *object* reads best: a
default argument, a configuration value.

### Tenors

`add_tenor(value, tenor, cal=, roll=Roll.NONE, eom=False)`

Grammar, case-insensitive:

```
tenor := term (('+' | '-') term)*
term  := ['-'] INT unit
unit  := 'D' | 'B' | 'W' | 'M' | 'Y'
```

`D` calendar days, `B` business days, `W` seven calendar days, `M`/`Y` calendar months and
years. `parse_tenor(text)` exposes the parsed structure and is memoised.

**Terms apply left to right, and the order matters.** `"1M+2B"` is not `"2B+1M"`: a month
added to a Friday and a month added to the following Tuesday land in different weeks.

**Two month-end rules, which must never be conflated:**

| | |
|---|---|
| **Clamping** | Unconditional. 31 January + 1M = 28 February, because 31 February does not exist. |
| **The end-of-month rule** | Opt-in via `eom=True`. If the start is the *last day* of its month, the result is the last day of the target month. 28 February + 1M is 28 March normally, 31 March with `eom=True`. |

Conflating them is where the off-by-one-day bugs live, which is why they are separate
mechanisms with separate tests.

A tenor's default roll is `NONE`: a tenor is a *period*, and adjusting the result is a
separate decision.

### Settlement lags

| Function | Description |
|---|---|
| `spot(value, currency, cal=None, roll=)` | the settlement date |
| `spot_lag(currency)` | the lag in business days |
| `SPOT_LAG` | the read-only table |

The default calendar comes from the currency through the alias table: `EUR` uses
`fin:TARGET2`, `GBP` uses `fin:LNB`. Pass `cal=` for a cross-currency trade that must settle
in two centres at once:

```python
bcal.spot(trade_date, "EUR", cal=bcal.get("EUR") & bcal.get("USD"))
```

These are **money-market deposit** conventions — a property of a single currency, which is
why sterling is T+0. FX spot is a property of the *pair* and is deliberately out of scope.
The table lives in `data/spot_lags.toml` so a desk can correct a row without a release, and
is read-only at runtime because mutating it would silently move every later settlement date.

### Recurrences and schedules

Every dated rule is **two independent decisions**: how to cut the window into periods, and
what to take from each one.

```python
schedule(start, end, every="M", on="last", *,
         cal=None, roll=Roll.NONE, months=None, anchor_month=None,
         stub="short_front", eom=False, missing="skip")
```

**`every` — how to cut.** `"D"`, `"W"`, `"M"`, `"Q"`, `"Y"`, or a multiple such as `"3M"`.
A bare unit aligns to the calendar; a multiple anchors on `start`. So `"Q"` and `"3M"` are
both three months long and deliberately different — the first is a property of the calendar,
the second of your start date. There is no separate `anchor` parameter because the choice is
already carried by the frequency string.

**`on` — what to take.**

| Selector | Meaning |
|---|---|
| `"1"`, `"first"`, `"15"`, `"last"`, `"-2"` | the n-th **calendar day** |
| `"1 B"`, `"last B"`, `"-3 B"` | the n-th **business day** |
| `"2 THU"`, `"last FRI"`, `"-2 WED"` | the n-th **weekday** |
| `"edges"` | the period **boundaries** — one date more than there are periods |
| a list of any of the above | all of them, sorted and de-duplicated |
| `Nth(-1, FRI)`, `Nth(1, "B")`, `Nth(-1)` | the typed equivalent, for code rather than config |

Negative counts from the end throughout. Ordinal suffixes are cosmetic: `"2 THU"` and
`"2nd THU"` parse identically. `parse_selector(text)` exposes the parsed form.

**`missing` — when a period has no such occurrence.** Most Februaries have no fifth Friday,
and no month has a thirty-second day.

| Value | Behaviour |
|---|---|
| `"skip"` | drop the period. The default, because raising would make the API unusable over any real span. |
| `"clamp"` | take the nearest occurrence that does exist. Makes "the 31st of each month" a one-liner. |
| `"raise"` | refuse, naming the offending period. |

**Business days and calendar days are two independent axes.** `on="last B"` *counts*
business days; `roll=` *moves* a result onto one. They agree more often than not, which is
exactly why the difference has to be written down rather than inferred.

**One more semantic:** the occurrence is found inside the *whole period*, then filtered to
the window. "The last Friday of January" is a property of January, not of your query — so
asking from the 15th still returns the 30th.

#### Named shortcuts

Each is a one-line spelling of the engine, and a test pins every equivalence.

| Function | Equivalent |
|---|---|
| `nth_weekday(a, b, n, weekday, freq=)` | `schedule(a, b, freq, Nth(n, weekday))` |
| `last_weekday(a, b, weekday, freq=)` | `schedule(a, b, freq, Nth(-1, weekday))` |
| `nth_day(a, b, n, freq=)` | `schedule(a, b, freq, Nth(n))` |
| `nth_business_day(a, b, n, cal=, freq=)` | `schedule(a, b, freq, Nth(n, "B"), cal=cal)` |
| `month_ends(a, b)` | `schedule(a, b, "M", "last")` |
| `month_ends(a, b, cal=)` | `schedule(a, b, "M", "last B", cal=cal)` |
| `quarter_ends(a, b, anchor_month=3)` | `schedule(a, b, "Q", "last", anchor_month=…)` |
| `year_ends(a, b, anchor_month=12)` | `schedule(a, b, "Y", "last", anchor_month=…)` |
| `imm_dates(a, b)` | `schedule(a, b, "M", "3 WED", months=(3, 6, 9, 12))` |
| `option_expiries(a, b, cal=)` | `schedule(a, b, "M", "3 FRI", cal=cal, roll="P")` |

IMM dates are the third Wednesday of the quarter's **last month**, not of the quarter —
different dates, and easy to get wrong.

#### Coupon schedules

`on="edges"` returns the period boundaries, with stub handling for terms that do not divide
evenly:

```python
schedule("2026-02-28", "2027-08-31", "6M", "edges", eom=True)
# contractual dates — no calendar involved at all

schedule("2026-02-28", "2027-08-31", "6M", "edges", eom=True, cal="XNYS", roll="MF")
# when it actually pays

periods("2026-01-15", "2027-01-15", "3M", cal="XNYS", roll="MF")
# the accrual intervals, as DateRange objects
```

**Nothing lets the calendar in until you pass `roll`.** That separation is the load-bearing
decision of the module. A downstream system holding a trade booked last year needs to know
its 15 March coupon is the same contractual date as yours, even if a holiday moved when it
pays. If contractual dates depended on holiday data, regenerating a snapshot would make the
*contract* appear to change.

| Stub | Behaviour |
|---|---|
| `short_front` | an extra, shorter first period. The default and the common market convention. |
| `long_front` | the remainder is absorbed into the first regular period |
| `short_back` | an extra, shorter final period |
| `long_back` | absorbed into the last regular period |
| `none` | refuse: the term must be a whole number of periods |

A *front* stub anchors the regular grid on the **end** date and generates backwards; a
*back* stub on the **start** and forwards. That is what makes coupons land on maturity
rather than drifting away from it. Dates are always measured from the anchor, never stepped
iteratively — otherwise 31 January would slip to 28 February and then stay on the 28th for
the life of the trade.

### Weekday constants

`MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, `SUN` — an `IntEnum` (`Weekday`) matching
`datetime.date.weekday()`, so Monday is 0 and they work anywhere the standard library
expects a weekday index.

### Intervals — `DateRange`

Frozen: `start`, `end`, `closed`. Supports `in`, iteration, `len()`, plus
`business_days(cal)`, `overlaps`, `intersection`, `split(freq)`, `first_day`, `last_day`,
`is_empty()`.

### Sessions

A calendar day is the interval `[session_start, session_start + 24h)` in the calendar's
timezone — local midnight for ordinary calendars, `00:00` UTC for crypto, `17:00` New York
for FX.

| Function | Description |
|---|---|
| `session_of(instant, cal=, tz=)` | which calendar day an instant belongs to |
| `session_bounds(day, cal=, tz=)` | the half-open UTC interval that day covers |
| `cal.grid(start, end, step, tz=)` | timestamps anchored on `session_start` |
| `at_times(days, times, tz="UTC")` | cross a set of days with times of day |

`session_of` is the answer to the timezone trap below. `grid` prevents the classic
mis-anchored resample: a four-hour grid built from UTC midnight cuts a Tokyo or Paris
session in the wrong places. `grid` covers sessions only, so an exchange grid has no
weekend points, and it fills each session independently so a clock change shortens that one
session rather than shifting everything after it.

`session_bounds` reports 23- and 25-hour sessions across daylight-saving transitions rather
than normalising them away. Code that assumes 24 hours is the code this exists to correct.

**Deliberately absent:** `is_open`, `next_open`, `next_close`, lunch breaks, early closes,
trading-minute indexes. An `is_open()` returning `is_bday()` would be false for every
exchange with an opening bell. The distinction is reserved as two protocols, `DayCalendar`
(satisfied today) and `SessionCalendar` (satisfied by nothing yet).

### Timezone policy

1. **Naive means "already in the right frame."** The date part is taken literally; no
   conversion happens.
2. **Aware means "an instant."** Projecting it onto a calendar day requires an explicit
   timezone — the calendar's, one you pass, or `config.default_tz`. There is no silent
   fallback; a bare `to_date(aware)` raises `AmbiguousTimezoneError`.
3. **Offsets preserve wall-clock time and tzinfo.** `2026-03-27 09:00 Paris + 1 business
   day` is `2026-03-30 09:00 Paris` — 71 hours in absolute terms across the transition, and
   that is correct.

The failure this exists to prevent:

```python
ts = pd.Timestamp("2026-07-31 23:30", tz="UTC")
ts.date()  # 2026-07-31  Friday
ts.tz_convert("Europe/Paris").date()  # 2026-08-01  Saturday
```

`.date()` answers according to whichever zone the timestamp happens to be carrying. In a
pipeline where a `tz_convert` sits three functions higher, the answer changes without
anybody deciding. `session_of` makes you name the frame.

`config.default_tz` is the documented opt-in escape hatch for services that have already
decided everything is UTC. It is the library's only global state.

### pandas integration

Importing `better_calendar.integrations.pandas_` registers a `.cal` accessor on `Series`
and `Index`:

```python
trades["settles"] = trades["traded"].cal.offset(2, cal="XNYS")
trades["open"] = trades["traded"].cal.is_bday("XNYS")
```

It is a thin wrapper — `cal.offset(series, 2)` and `series.cal.offset(2)` do the same work.
The package root never imports it, so pandas stays optional.

### Errors

Everything raised inherits from `BetterCalendarError`, and every message says what was
wrong **and** what to do about it.

| Exception | Raised when |
|---|---|
| `OutOfBoundsError` | a date falls outside a calendar's horizon; the message includes the bounds |
| `AmbiguousTimezoneError` | an aware input with no timezone to resolve it |
| `UnknownCalendarError` | an identifier resolves to nothing; includes did-you-mean suggestions |
| `NotABusinessDayError` | `Roll.RAISE` and the date is not a business day |
| `TenorParseError` | a malformed tenor; highlights the offending substring |
| `ScheduleError` | a bad selector, stub, or `missing` policy |
| `ProviderError` | a missing optional package; includes the `pip install` hint |

---

## Invariants

The load-bearing decisions. Violating any of them is a bug, even if tests pass.

| # | |
|---|---|
| I1 | `Calendar` is frozen, hashable and safe as a cache key. No mutation, ever. |
| I2 | Every calendar has explicit finite bounds. Any query outside them raises. Never extrapolate. |
| I3 | A naive `datetime` is a *label*: its date part is taken literally, with no conversion. |
| I4 | An aware timestamp is an *instant*: projecting it onto a calendar day requires an explicit timezone. |
| I5 | Offsets change only the date part. Wall-clock time and tzinfo survive DST transitions. |
| I6 | Output type matches input type; a sequence comes back as a `DatetimeIndex`. |
| I7 | Every public scalar function also accepts arrays and is vectorised. |
| I8 | Holiday data at runtime comes from a committed snapshot, never from a live provider call. |
| I9 | Calendar set operations are named after business days, never after holidays. |
| I10 | Half-open `[start, end)` is the default everywhere. |

---

## Testing

The library is meant to be trusted blindly by downstream systems, so correctness evidence
matters more than coverage percentage.

- **Oracle tests** compare the committed snapshot against live `QuantLib`,
  `exchange-calendars` and `holidays` **day for day over each calendar's full horizon** —
  plus the four roll conventions and business-day counts. Marked `oracle`, skipped cleanly
  without the extras.
- **Property tests** (Hypothesis) cover `count(d, offset(d, n)) == n`, offset round trips,
  `adjust` idempotence, algebra containment, commutativity and associativity, and type
  preservation across every public function.
- **Golden tests** pin 29 February, the 1970 and 2100 edges, non-Monday-Friday weekmasks,
  and the DST weekends in Paris and New York.
- **Drift** runs `better-calendar diff` in CI, weekly on a schedule and on every pull
  request.
- **Doctests** run as part of the suite, so every example in the docstrings is executed.
- **Packaging** is checked against a real built wheel: a bare Python 3.9 install with numpy
  alone must answer for `XNYS`, add tenors, offset by `BDay` and attribute sessions.
- **Notebooks** are re-executed in CI, because documentation that no longer runs is worse
  than none.
