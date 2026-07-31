# CLAUDE.md — `better-calendar`

Instructions for Claude Code working in this repository. Read this file in full before
writing any code. When a decision in this document conflicts with your instinct, follow
this document; if you believe the document is wrong, say so explicitly and wait rather
than silently deviating.

---

## 1. What this project is

`better-calendar` is a Python library that centralises **all date logic** used across our
infrastructure: business-day arithmetic, calendar-aware offsets, date normalisation,
recurrence/schedule generation, and calendar composition — for plain civil calendars,
exchange calendars, country calendars, and financial settlement / risk-free-rate
calendars.

- **Distribution name:** `better-calendar`
- **Import package:** `better_calendar`
- **Conventional alias:** `import better_calendar as bcal`
- **Python:** `>= 3.9` (we use `StrEnum`, `Self`, and PEP 604 unions freely)
- **Layout:** `src/` layout (`src/better_calendar/…`)

The mental model, in one sentence: **a calendar is a sorted `int64` array of good days**
(days since the Unix epoch) over a bounded horizon. Offsets, counting, membership, and
set algebra all reduce to `searchsorted` and numpy set operations on that array.

### 1.1 Design goals

1. **One place for date logic.** Callers should never hand-roll a `while d.weekday() > 4`
   loop again.
2. **Type transparency.** The library accepts `date`, `datetime`, `pd.Timestamp`,
   `np.datetime64`, ISO strings, and `yyyymmdd` ints — and returns the *same type it was
   given*.
3. **Correct by construction, loud on ambiguity.** No silent timezone coercion, no silent
   out-of-range extrapolation, no silent `.date()` on an aware timestamp.
4. **Deterministic in production.** Upgrading an upstream holiday package must never
   silently move a settlement date. Holiday data is snapshotted and versioned in-repo.
5. **Light core.** `numpy` is the only mandatory runtime dependency. Everything else is an
   extra.

### 1.2 Non-goals (do not build these)

- Reimplementing holiday rules. We *never* hand-code "third Monday of January is MLK
  day". We consume upstream providers and snapshot their output.
- OHLCV bar construction, resampling of trade data, tick storage, latency modelling.
  This library answers *"which calendar day / session is this, and when does it start and
  end"*. It hands anchors to pandas/polars; it does not do the aggregation.
- Full intraday session modelling (`is_open`, `next_open`, lunch breaks, early closes) —
  see §9. Deliberately deferred.
- Day-count fractions (ACT/360, 30/360, …) — deferred to v1.1. Do not add in v1.
- Unbounded date ranges, mutable calendars, implicit global state.

---

## 2. Non-negotiable invariants

These are the load-bearing decisions. Violating any of them is a bug, even if tests pass.

| # | Invariant |
|---|---|
| I1 | `Calendar` is frozen, hashable, and safe to use as a cache key. No mutation, ever. |
| I2 | Every calendar has explicit finite `bounds`. Any query outside them raises `OutOfBoundsError`. Never extrapolate. |
| I3 | A naive `datetime` is a *label*, not an instant: its date part is taken literally, with no conversion. |
| I4 | An aware timestamp is an *instant*: projecting it onto a calendar day requires an explicit timezone (from the calendar or from the caller). Never call `.date()` on an aware object. |
| I5 | Offsets change only the date part. Wall-clock time and tzinfo are preserved across DST transitions. |
| I6 | Output type matches input type. `date` in → `date` out; `Timestamp` in → `Timestamp` out; sequence in → `DatetimeIndex` out (or `np.ndarray[datetime64[D]]` if pandas is absent). |
| I7 | Every public scalar function also accepts arrays and is vectorised. No Python loops over dates in the hot path. |
| I8 | Holiday data at runtime comes from a committed snapshot, not from a live provider call. |
| I9 | Calendar set operations are named after **business days**, never after holidays (see §6). |
| I10 | Half-open intervals `[start, end)` are the default everywhere. Any other convention must be an explicit named argument. |

---

## 3. Core representation

`src/better_calendar/core/epoch.py`

The canonical internal type is `int64` days since `1970-01-01`. Conversions to and from
`numpy.datetime64[D]` are views, not copies.

```python
DAY_ORIGIN: Final = date(1970, 1, 1)
MIN_YEAR: Final[int] = 1970
MAX_YEAR: Final[int] = 2100  # single knob; easy to raise later
DEFAULT_BOUNDS: Final = (date(MIN_YEAR, 1, 1), date(MAX_YEAR, 12, 31))
```

`MAX_YEAR` must be referenced everywhere; no literal `2100` anywhere else in the codebase.

---

## 4. Type layer

`src/better_calendar/core/types.py`

```python
DateLike = date | datetime | pd.Timestamp | np.datetime64 | str | int
DateSeqLike = Sequence[DateLike] | np.ndarray | pd.DatetimeIndex | pd.Series


class Kind(StrEnum):
    DATE = "date"
    DATETIME = "datetime"
    TIMESTAMP = "timestamp"
    NP = "np"
    STR = "str"
    INT = "int"
    SEQ = "seq"


def kind_of(x: object) -> Kind: ...
def to_days(
    x: DateLike | DateSeqLike, *, tz: str | None = None
) -> np.int64 | NDArray[np.int64]: ...
def from_days(days, *, like: object) -> Any: ...  # restores the caller's type


def to_date(x: DateLike, *, tz: str | None = None) -> date: ...
def to_datetime(x: DateLike, *, tz: str | None = None) -> datetime: ...
def to_timestamp(x: DateLike, *, tz: str | None = None) -> pd.Timestamp: ...
```

Parsing rules — be strict, ambiguity is a bug factory:

- `str`: ISO-8601 only (`"2026-07-31"`, `"2026-07-31T14:30:00+02:00"`) plus the compact
  form `"20260731"`. **Reject** `DD/MM/YYYY` and `MM/DD/YYYY` with a clear error message.
- `int`: interpreted as `yyyymmdd`. Reject anything that doesn't parse as such (this
  guards against someone passing a Unix timestamp by accident).
- `np.datetime64`: any unit; truncated to `[D]` for date-valued operations.

Type preservation is implemented by a single `from_days(days, like=original_input)`
helper. Do not scatter isinstance ladders through the codebase — the dispatcher lives in
this module and nowhere else. Provide `@overload` signatures on every public function so
that `mypy --strict` propagates the input type to the return type.

---

## 5. Calendars

`src/better_calendar/calendars/base.py`

```python
@dataclass(frozen=True, slots=True)
class Calendar:
    name: str
    holidays: NDArray[np.datetime64]  # [D], sorted, unique
    weekmask: str = "Mon Tue Wed Thu Fri"  # also accept "all" for 24/7
    bounds: tuple[date, date] = DEFAULT_BOUNDS
    tz: str | None = None  # IANA name; None means "no instant semantics"
    session_start: time = time(0, 0)  # see §9
    provider: str | None = None
    provider_version: str | None = None

    @cached_property
    def _good(self) -> NDArray[np.int64]:  # sorted good days, the workhorse
        ...
```

Hashing: derive from `(name, weekmask, bounds, tz, session_start, sha1(holidays.tobytes()))`.
Two calendars built from the same snapshot must hash equal.

### 5.1 Core methods

```python
# membership & normalisation
is_bday(d)                       -> bool | NDArray[bool]
next_bday(d, *, inclusive=False) -> same-type-as-d
prev_bday(d, *, inclusive=False) -> same-type-as-d
adjust(d, roll=Roll.FOLLOWING)   -> same-type-as-d       # the normaliser

# arithmetic
offset(d, n, *, roll=Roll.FOLLOWING) -> same-type-as-d   # n business days
bday(n=1)                            -> BDay             # pandas-like offset object
count(a, b, *, closed="left")        -> int | NDArray[int64]
bdays_between(a, b, *, closed="left")-> DatetimeIndex

# tenors
add_tenor(d, tenor, *, roll=Roll.NONE, eom=False) -> same-type-as-d

# introspection
holidays_between(a, b) -> DatetimeIndex
sessions()             -> DatetimeIndex   # all good days within bounds
describe()             -> dict

# composition (see §6)
__and__, __or__, __sub__, __xor__
with_holidays(extra) / without_holidays(dates) -> Calendar   # returns a NEW calendar
```

### 5.2 Complexity requirements

| Method | Required implementation |
|---|---|
| `is_bday` | `searchsorted` + equality check |
| `offset` | `_good[searchsorted(_good, d) + n]`, with bounds check |
| `count` | difference of two `searchsorted` results |
| `adjust` | `searchsorted` + month-boundary check for the modified variants |

All must be O(log n) per element and fully vectorised. If you find yourself writing a
`for` loop over dates outside of provider materialisation code, stop and reconsider.

### 5.3 Providers

`src/better_calendar/calendars/providers/`

All four are in scope for v1. Providers are **build-time** code: they run during snapshot
generation, not at import time or query time.

| Module | Upstream | Owns |
|---|---|---|
| `exchange_calendars_.py` | `exchange-calendars` | Exchange calendars by ISO-10383 MIC (`XNYS`, `XLON`, `XETR`, `XPAR`, `XTKS`, …) |
| `python_holidays_.py` | `holidays` | Civil calendars by ISO-3166-1/-2 (`country:FR`, `country:US-NY`) |
| `quantlib_.py` | `QuantLib` | Financial centres and RFR calendars (`fin:TARGET2`, `rate:SOFR`, …) |
| `workalendar_.py` | `workalendar` | Fallback for regions the others miss, and lunar/religious calendars |

Each provider module exposes exactly:

```python
PROVIDER_NAME: str


def version() -> str: ...  # upstream package version
def available() -> list[CalendarSpec]: ...  # what this provider can build
def materialise(spec: CalendarSpec, bounds) -> Calendar: ...
```

Providers are imported lazily and only by the snapshot tooling. Importing
`better_calendar` must not import any of them. Guard every import and raise
`ProviderError` with an actionable install hint if the extra is missing.

### 5.4 Identifier scheme and registry

`src/better_calendar/calendars/registry.py`

Namespaced canonical IDs, plus an alias table:

```
XNYS, XLON, XETR, XPAR, XTKS      # ISO 10383 MIC, no prefix
country:FR, country:US, country:US-NY
fin:TARGET2, fin:LNB, fin:NYB
rate:ESTR   -> fin:TARGET2
rate:SOFR   -> QuantLib UnitedStates(GovernmentBond)   # SIFMA
rate:SONIA  -> UK settlement
rate:TONA, rate:SARON, rate:CORRA
crypto:24x7                        # always-open, see §9
```

Aliases live in a single declarative table (`aliases.toml`), never scattered in code:
`NYSE → XNYS`, `TARGET → fin:TARGET2`, `EUR → fin:TARGET2`, `FR → country:FR`.

```python
bcal.get("XNYS")            -> Calendar
bcal.list(provider="quantlib") -> list[str]
bcal.describe("rate:SOFR")  -> dict   # provenance, version, bounds, holiday count
bcal.register(name, calendar)         # for org-specific calendars
```

Resolution order is explicit and documented. `get()` results are memoised
(`functools.lru_cache`) — this is safe because calendars are frozen.

Unknown names raise `UnknownCalendarError` with **did-you-mean suggestions**
(`difflib.get_close_matches`).

### 5.5 Snapshots and determinism

`src/better_calendar/calendars/snapshot.py`, data in `src/better_calendar/data/`.

Snapshot files are Parquet, one row per (calendar, holiday), with a sidecar manifest
recording provider, provider version, bounds, generation date, and a content hash.
Snapshots are **committed to the repo** and shipped in the wheel.

CLI:

```
better-calendar snapshot --provider all --bounds 1970-01-01:2100-12-31
better-calendar diff                     # compare regenerated vs committed; non-zero exit on change
better-calendar describe rate:SOFR
better-calendar next XNYS 2026-07-31 +5
```

`diff` runs in CI as a scheduled job so that upstream changes surface as a reviewable PR
rather than a silent production behaviour change. This is a hard requirement, not a
nice-to-have.

### 5.6 Organisation-specific overrides

A YAML file (path from `BETTER_CALENDAR_CONFIG` or `./better-calendar.yaml`) composes on
top of base calendars. Never fork a provider calendar to add a local closure.

```yaml
calendars:
  desk:paris:
    base: fin:TARGET2
    extra_holidays: ["2026-01-02", "2026-12-24"]
    remove_holidays: []
    tz: Europe/Paris
```

---

## 6. Calendar algebra

`src/better_calendar/calendars/algebra.py`

**This is the single most bug-prone area of the library because of vocabulary.** "Union
of two calendars" means opposite things depending on whether the speaker is thinking in
business days or in holidays. We resolve it by naming everything in terms of **business
days**, and by providing verbose aliases that read unambiguously in code review.

```python
a & b  # good in BOTH calendars   (== union of holidays)   <- the common settlement case
a | b  # good in AT LEAST ONE
a - b  # good in a, not good in b
a ^ b  # good in exactly one

Calendar.all_open([a, b, c])  # verbose alias for &
Calendar.any_open([a, b, c])  # verbose alias for |
```

Implementation is `np.intersect1d` / `np.union1d` / `np.setdiff1d` on `_good`. This
handles heterogeneous weekmasks (Sun–Thu vs Mon–Fri) for free — do **not** implement
algebra by merging weekmask strings and holiday lists.

Composite calendars:

- are ordinary `Calendar` instances (frozen, hashable, reusable in offsets);
- get `bounds` = intersection of operand bounds;
- get `name` = a deterministic derived string, e.g. `"(XNYS & fin:TARGET2)"`;
- get `tz = None` unless all operands agree — a composite of calendars in different zones
  has no meaningful instant semantics, and `session_of` on it must raise.

Add a docstring on the module that spells out the union/intersection trap with a worked
example. Future readers will need it.

---

## 7. Offsets, roll conventions, tenors

`src/better_calendar/offsets/`

### 7.1 Roll conventions

```python
class Roll(StrEnum):
    NONE = "none"  # leave unadjusted
    FOLLOWING = "following"  # "F"
    PRECEDING = "preceding"  # "P"
    MODIFIED_FOLLOWING = "modified_following"  # "MF" — stay in month
    MODIFIED_PRECEDING = "modified_preceding"  # "MP"
    NEAREST = "nearest"  # "N" — ties go forward
    RAISE = "raise"  # error if not a business day
```

Accept the short aliases (`"MF"`, `"F"`, …) case-insensitively at every API boundary via a
`Roll.parse()` classmethod. `adjust(d, Roll.MODIFIED_FOLLOWING)` is the canonical date
normaliser and should be presented as such in the docs.

### 7.2 The `BDay` object

```python
class BDay:
    def __init__(
        self, n: int = 1, cal: Calendar | str | None = None, roll: Roll = Roll.FOLLOWING
    ): ...
    def __radd__(self, other): ...
    def __rsub__(self, other): ...
    def __mul__(self, k: int) -> BDay: ...
    def __neg__(self) -> BDay: ...
```

`date + BDay(3)` works natively (Python falls through to `__radd__`). `pd.Timestamp` also
falls through correctly.

**Known subtlety — document it and test it:** `Series + BDay(n)` and
`DatetimeIndex + BDay(n)` are fragile because pandas attempts to broadcast unknown
objects. Handle this by implementing `__radd__` to detect pandas containers and dispatch
to the vectorised path, and by documenting `cal.offset(series, n)` as the recommended,
fastest form. Also ship `cal.to_pandas_offset()` returning a real
`pd.offsets.CustomBusinessDay` for interop with pandas machinery that requires a genuine
`DateOffset` (`resample`, `date_range`), while noting it is slower.

### 7.3 Tenors

`src/better_calendar/offsets/tenor.py`. Formal grammar, case-insensitive:

```
tenor := term (('+' | '-') term)*
term  := ['-'] INT unit
unit  := 'D' | 'B' | 'W' | 'M' | 'Y'
```

- `D` calendar days, `B` business days (requires a calendar), `W` = 7 calendar days,
  `M`/`Y` calendar months/years.
- Month/year addition clamps to end of month (`31 Jan + 1M = 28/29 Feb`).
- `eom=True` applies the **end-of-month rule**: if the start date is the last day of its
  month, the result is the last day of its month. This is separate from clamping and is a
  classic source of off-by-one-day errors — test it explicitly.
- Terms are applied **left to right** (`"1M+2B"` ≠ `"2B+1M"` in general). Say so in the
  docstring.
- Parse failures raise `TenorParseError` showing the offending substring.

Cache parsed tenors (`lru_cache`) — they arrive from configs in hot loops.

### 7.4 Spot lags

`SPOT_LAG: dict[str, int]` mapping currency → settlement lag in business days
(`EUR: 2, USD: 2, GBP: 0, CAD: 1, TRY: 0, …`), with `spot(d, ccy, cal=...)`. Keep the
table in a data file, not in code. Small, high value, frequently asked for.

---

## 8. Schedules and recurrences

`src/better_calendar/schedule/`

Two levels: direct functions for the common cases, a `Schedule` class for coupon-style
generation.

```python
MON, TUE, WED, THU, FRI, SAT, SUN  # IntEnum matching date.weekday(), 0 = Monday

nth_weekday(start, end, n, weekday, *, freq="M", cal=None, roll=Roll.NONE)
last_weekday(start, end, weekday, *, freq="M", ...)      # == nth_weekday(n=-1)
nth_business_day(start, end, n, *, freq="M", cal)
nth_day(start, end, n, *, freq="M", cal=None, roll=Roll.NONE)

month_ends(start, end, *, cal=None)      # calendar or business month ends
quarter_ends(start, end, *, cal=None, anchor_month=3)
year_ends(start, end, *, cal=None)

imm_dates(start, end)                    # 3rd Wednesday of Mar/Jun/Sep/Dec
option_expiries(start, end, *, cal)      # 3rd Friday, adjusted
```

Conventions:

- `n` is 1-based; **negative `n` counts from the end** (`n=-1` is "last", `n=-2`
  "second to last"). This is the whole point of the API — make it work everywhere.
- `freq` accepts `"D" | "W" | "M" | "Q" | "Y"` and multiples (`"3M"`, `"6M"`).
- If the requested occurrence doesn't exist in a period (e.g. the 5th Friday of February),
  it is **skipped silently**, and this is documented. Do not raise.
- Return type follows `start`'s type (I6); sequences come back as `DatetimeIndex`.

The two examples that motivated this library must appear verbatim in the README and in
the doctests:

```python
last_weekday("2026-01-01", "2026-12-31", FRI)  # last Friday of each month
nth_weekday("2026-01-01", "2026-12-31", 2, THU, freq="Q")  # 2nd Thursday of each quarter
```

### 8.1 `Schedule`

```python
@dataclass(frozen=True)
class Schedule:
    start: DateLike
    end: DateLike
    freq: str = "6M"
    cal: Calendar | str | None = None
    roll: Roll = Roll.MODIFIED_FOLLOWING
    stub: Literal["short_front", "long_front", "short_back", "long_back", "none"] = (
        "short_front"
    )
    eom: bool = False

    def unadjusted(self) -> DatetimeIndex: ...
    def dates(self) -> DatetimeIndex: ...  # adjusted
    def periods(self) -> list[DateRange]: ...
```

**Critical architectural rule:** generation happens in two strictly separated stages —
(1) produce unadjusted dates by pure calendar rules, (2) apply `cal.adjust(...)`. The
unadjusted schedule must be reproducible with no calendar at all. Never interleave the
two; downstream systems need to reconcile unadjusted schedules across calendar versions.

### 8.2 `DateRange`

`src/better_calendar/core/range.py` — a small frozen value object: `start`, `end`,
`closed`; supports `in`, iteration, `len()`, `business_days(cal)`, `overlaps`,
`intersection`, `split(freq)`.

---

## 9. Sessions ("intraday-lite")

We are **not** building a session engine in v1. We *are* making three decisions now
because they are expensive to retrofit.

1. **`session_start` on `Calendar`.** A calendar day is the interval
   `[session_start, session_start + 24h)` expressed in `Calendar.tz`. Local midnight for
   ordinary calendars, `00:00 UTC` for crypto, `17:00 America/New_York` for FX. One
   field, no complexity.

2. **A first-class 24/7 calendar** (`crypto:24x7`): `weekmask="all"`, no holidays,
   `tz="UTC"`, `session_start=time(0,0)`. Trivial to build, and it guarantees that crypto
   code uses the identical API. It also makes `bcal.get("crypto:24x7") & bcal.get("XCME")`
   meaningful for CME-listed crypto products.

3. **Split protocols.** `DayCalendar` (v1) and `SessionCalendar` (later, adds
   open/close/breaks/early closes). **Do not put `is_open()` on the base class returning
   `is_bday()`.** That is false for any exchange with trading hours and it will be
   discovered the hard way.

Ship in v1 (cheap, high value):

```python
cal.session_of(ts, *, tz=None) -> date        # instant -> calendar day. The key function.
cal.session_bounds(day)        -> tuple[Timestamp, Timestamp]   # UTC, half-open
cal.grid(start, end, "4h")     -> DatetimeIndex  # aligned on session_start, NOT on UTC midnight
at_times(rule, ["00:00","08:00","16:00"], tz="UTC")  # recurrence + times-of-day
```

`session_of` is the answer to the timezone trap in §10 and solves the bulk of real
intraday-adjacent problems (funding times, expiry attribution, daily bar boundaries).
`grid` prevents the classic mis-anchored resample.

Explicitly deferred: `is_open`, `next_open`, `next_close`, lunch breaks, early closes,
trading-minute indexes. When needed, adapt `exchange-calendars` behind `SessionCalendar`.

---

## 10. Timezone policy

The rule, in three lines. Put this verbatim in the module docstring of
`core/types.py` and in the docs.

1. **Naive means "already in the right frame."** The date part is taken literally; no
   conversion is performed.
2. **Aware means "an instant."** Projecting it onto a calendar day requires an explicit
   timezone — the calendar's, or one passed by the caller. A bare `to_date(aware)` raises
   `AmbiguousTimezoneError`.
3. **Offsets preserve wall-clock time and tzinfo.** They touch only the date part.
   `datetime(2026,3,27,9,0,tz=Paris) + BDay(1)` → `2026-03-30 09:00 Paris` (which is +23h
   in absolute terms — that is correct and intended).

The motivating failure, which must be a test:

```python
ts = pd.Timestamp("2026-07-31 23:30", tz="UTC")  # Friday
ts.date()  # 2026-07-31  Friday
ts.tz_convert("Europe/Paris").date()  # 2026-08-01  Saturday
```

A global escape hatch exists for callers who don't want the strictness:
`bcal.config.default_tz = "UTC"` (module-level, documented as opt-in, off by default).
This is the *only* piece of global state permitted in the library.

---

## 11. Errors

`src/better_calendar/core/errors.py`

```
BetterCalendarError                 (base; everything we raise inherits from it)
├── OutOfBoundsError                (date outside calendar bounds — include the bounds in the message)
├── AmbiguousTimezoneError          (aware input, no tz resolution available)
├── UnknownCalendarError            (with did-you-mean suggestions)
├── NotABusinessDayError            (Roll.RAISE)
├── TenorParseError                 (with the offending substring highlighted)
├── ScheduleError                   (bad stub/freq combination)
└── ProviderError                   (missing extra, or upstream failure — include the pip install hint)
```

Every error message must state what was wrong **and** what the caller should do. No bare
`ValueError` anywhere in public code paths.

---

## 12. Repository layout

```
better-calendar/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── better-calendar.yaml.example
├── src/better_calendar/
│   ├── __init__.py            # curated public API; see §13
│   ├── config.py
│   ├── core/
│   │   ├── types.py           # conversion + type preservation
│   │   ├── epoch.py           # int64 <-> date, MAX_YEAR
│   │   ├── range.py           # DateRange
│   │   └── errors.py
│   ├── calendars/
│   │   ├── base.py            # Calendar
│   │   ├── algebra.py         # & | - ^
│   │   ├── registry.py        # get / list / describe / register
│   │   ├── aliases.toml
│   │   ├── snapshot.py
│   │   └── providers/
│   │       ├── exchange_calendars_.py
│   │       ├── python_holidays_.py
│   │       ├── quantlib_.py
│   │       ├── workalendar_.py
│   │       └── custom.py      # YAML overrides
│   ├── offsets/
│   │   ├── bday.py
│   │   ├── conventions.py     # Roll
│   │   ├── tenor.py
│   │   └── spot.py
│   ├── schedule/
│   │   ├── recurrence.py      # nth_weekday & friends
│   │   ├── generators.py      # imm_dates, option_expiries
│   │   ├── stubs.py
│   │   └── schedule.py        # Schedule
│   ├── sessions/
│   │   └── session.py         # session_of, session_bounds, grid, at_times
│   ├── integrations/
│   │   └── pandas_.py         # .cal accessor, to_pandas_offset
│   ├── data/                  # committed snapshots + spot lags
│   └── cli.py
└── tests/
```

---

## 13. Public API surface

`__init__.py` exports a deliberately small, curated set. Everything else is reachable via
submodules but is not part of the stability contract.

```python
from better_calendar import (
    Calendar,
    get,
    list,
    describe,
    register,
    BDay,
    Roll,
    adjust,
    offset,
    count,
    add_tenor,
    spot,
    Schedule,
    DateRange,
    nth_weekday,
    last_weekday,
    nth_business_day,
    nth_day,
    month_ends,
    quarter_ends,
    year_ends,
    imm_dates,
    option_expiries,
    to_date,
    to_datetime,
    to_timestamp,
    session_of,
    session_bounds,
    MON,
    TUE,
    WED,
    THU,
    FRI,
    SAT,
    SUN,
    MAX_YEAR,
    config,
)
```

Free functions (`adjust`, `offset`, `count`, …) take `cal: Calendar | str | None` as a
keyword argument and resolve strings through the registry. `None` means "the default
calendar" — a plain Mon–Fri weekday calendar with no holidays, named `weekday`.

---

## 14. Dependencies

```toml
dependencies = ["numpy>=1.24"]

[project.optional-dependencies]
pandas   = ["pandas>=2.0"]
exchange = ["exchange-calendars>=4.5"]
holidays = ["holidays>=0.40"]
quantlib = ["QuantLib>=1.32"]
workalendar = ["workalendar>=17.0"]
all = [...]
dev = ["pytest", "pytest-cov", "hypothesis", "ruff", "mypy", "pre-commit"]
```

Rules:

- Importing `better_calendar` must not import pandas. Use a lazy accessor; degrade
  gracefully to numpy arrays when pandas is absent (I6 allows this).
- Never add a runtime dependency without asking first.
- Providers are build-time only (§5.3).

---

## 15. Testing strategy

Tests are not an afterthought here — this library will be trusted blindly by downstream
systems, so correctness evidence matters more than coverage percentage.

**a) Oracle tests.** `QuantLib` and `exchange-calendars` are authoritative. Cross-validate
our calendars and our roll conventions against them over the full 1970–2100 horizon.
Mark with `@pytest.mark.oracle`; skip cleanly when the extra is absent; run in full CI.

**b) Property-based tests** (Hypothesis). At minimum:

```
count(d, offset(d, n)) == n                       for any good day d, any n in bounds
offset(offset(d, n), -n) == d                     for good d
adjust(adjust(d, r), r) == adjust(d, r)           idempotence, all r
is_bday(adjust(d, r))                             for r != NONE
(a & b) ⊆ a  and  (a & b) ⊆ b                     algebra
a | b == b | a  ;  (a | b) | c == a | (b | c)     commutativity, associativity
add_tenor(d, "1M+(-1M)") round-trips where unambiguous
type(f(x)) is type(x)                             type preservation, all public functions
```

**c) Golden tests.** Committed CSV fixtures of known-tricky dates: TARGET2 Easter
sequences, US Good Friday (NYSE closed, SIFMA half-day), Japanese Golden Week, Islamic
calendar shifts, 29 Feb, the DST weekends, year boundaries at 1970 and 2100.

**d) Snapshot drift.** `better-calendar diff` in CI (§5.5).

**e) Boundary tests.** Every operation at `MIN_YEAR` and `MAX_YEAR` edges must raise
`OutOfBoundsError` rather than return garbage.

**f) Doctests.** All public docstrings carry runnable examples; run them in CI.

---

## 16. Coding conventions

- `ruff` (lint + format) and `mypy --strict` both clean. No `# type: ignore` without a
  comment justifying it.
- Full type annotations, `@overload` on anything that preserves input type.
- Google-style docstrings with an `Examples:` section on every public callable.
- No abbreviations in public names (`business_days_between`, not `bdb`). Internal helpers
  may be terse.
- Frozen dataclasses by default; `slots=True` on hot types.
- No logging in the hot path. No `print`. No mutable default arguments.
- Comments explain *why*, not *what*. The union/intersection trap, the EOM rule, and the
  DST/wall-clock choice each deserve a real comment where implemented.
- Conventional Commits.

---

## 17. Build order

Work through these in sequence. Do not start a milestone before the previous one is green
and committed.

| M | Scope | Done when |
|---|---|---|
| **M0** | Repo scaffolding: `pyproject.toml`, `src/` layout, ruff/mypy/pytest/pre-commit, CI skeleton | `pytest` and `mypy --strict` run clean on an empty package |
| **M1** | `core/`: `epoch`, `types` (conversion + preservation), `errors`, `range` | Round-trip property tests pass for all six input kinds |
| **M2** | `calendars/base.py`: `Calendar`, `_good`, `is_bday`, `next/prev`, `adjust`, `offset`, `count` — with a hardcoded weekday calendar only | Complexity requirements met; oracle test vs `np.busday_offset` passes |
| **M3** | `calendars/algebra.py` + `registry.py` + a `weekday` and `crypto:24x7` calendar | Algebra property tests pass; `get()` memoises correctly |
| **M4** | Providers + `snapshot.py` + committed snapshots + `cli.py` (`snapshot`, `diff`, `describe`, `next`) | All four providers materialise 1970–2100; oracle tests vs QuantLib pass |
| **M5** | `offsets/`: `Roll`, `BDay`, tenors, spot lags, pandas interop | `date + BDay(5)` and `series + BDay(5)` both correct; tenor grammar fully tested incl. EOM |
| **M6** | `schedule/`: recurrences, generators, `Schedule` with stubs | The two motivating examples in §8 work; unadjusted/adjusted separation verified |
| **M7** | `sessions/`: `session_of`, `session_bounds`, `grid`, `at_times` | The §10 UTC/Paris failure case is covered by a test |
| **M8** | Docs, README, YAML overrides, packaging, 1.0 tag | Doctests green, README examples runnable |

---

## 18. Working agreements

- **Ask before deviating.** If a requirement here turns out to be impractical, say so and
  propose an alternative. Do not quietly implement something different.
- **Ask before adding a runtime dependency.** Always.
- **Never hand-code a holiday rule.** If a provider lacks a calendar we need, add a YAML
  override or open the question — do not encode Easter arithmetic by hand.
- **Prefer deleting to deprecating** while pre-1.0.
- Keep `MAX_YEAR` as the single knob for the horizon; never hardcode the year.
- When touching §6 (algebra), §7.3 (EOM), or §10 (timezones), re-read the relevant section
  first. Those three are where correctness is most fragile.

---

## 19. Glossary

| Term | Meaning here |
|---|---|
| **Good day** | A day that is a business day in a given calendar. |
| **Session** | The interval `[session_start, session_start + 24h)` in the calendar's tz that a timestamp is attributed to. |
| **Roll / adjust** | Moving a date to a nearby business day per an ISDA convention. |
| **Unadjusted schedule** | Dates produced by pure calendar rules, before any roll convention is applied. |
| **Stub** | A first or last accrual period shorter or longer than the regular frequency. |
| **Snapshot** | Committed, versioned materialisation of an upstream provider's holiday data. |
| **Tenor** | A textual period expression such as `3M`, `2B`, `1Y+2B`. |
