# Calendar data: how it is produced, frozen and released

This is the part of `better-calendar` that people are most often surprised by, so it gets
its own page. The short version:

> **Calendars are not computed when you ask a question, and not built when the package is
> published. They are committed files. A date can only change through a pull request
> somebody read.**

---

## Why freeze anything

Every Python holiday library — `exchange-calendars`, `holidays`, `QuantLib`,
`workalendar` — ships rules and tables that change between releases. That is correct
behaviour on their part: countries add holidays, exchanges announce closures, and mistakes
get fixed.

But it means a library that calls them at query time has this failure mode:

```
$ pip install --upgrade some-unrelated-package
   (which upgrades exchange-calendars as a transitive dependency)

$ python -c "print(settlement_date(trade))"
2027-06-01          # yesterday this printed 2027-05-31
```

Nothing in your repository changed. No test failed. The settlement date moved because a
package three levels down your dependency tree published a correction. In a back office,
that is the kind of thing you find out about from a counterparty.

So the data is **materialised once, committed, and read from disk**. The only way an answer
changes is a merged commit.

---

## The three moments

They are deliberately separate, and conflating them is what the design avoids.

### 1. Generation — rare, deliberate, by a human or by CI

```bash
uv sync --all-extras                     # the four provider packages
better-calendar snapshot --provider all  # about 45 seconds
git add src/better_calendar/data
git commit
```

This imports `exchange_calendars`, `holidays`, `QuantLib` and `workalendar`, materialises
every calendar over the requested horizon, and writes the data files. **This is the only
moment a provider is ever imported.**

### 2. Packaging — no computation at all

```bash
uv build
```

The already-committed files are copied into the wheel. `uv build` does not import a
provider, does not compute a holiday, and does not touch the network. The wheel is
about 1.7 MB, of which 1.6 MB is the 477 CSV files.

**This means publishing a release does not rebuild the calendars.** Whatever is committed
at the moment of the tag is exactly what ships. If the snapshot is six months stale, a
six-month-stale snapshot goes to PyPI. That is why the drift job exists.

### 3. Query — a file read

```python
bcal.get("XNYS")  # reads data/calendars/XNYS.csv, ~0.06 ms, memoised
```

Calendars load lazily, one file at a time, and are cached after the first lookup. A CI job
asserts that no provider module is in `sys.modules` even after resolving all 479
calendars.

---

## The file format

```
src/better_calendar/data/
├── manifest.json
└── calendars/
    ├── XNYS.csv
    ├── country-FR.csv
    ├── fin-TARGET2.csv
    └── … 474 more
```

Each `.csv` is one ISO date per line, sorted ascending, nothing else:

```
1970-01-01
1970-02-23
1970-03-27
…
```

`manifest.json` is the index, and carries the provenance the files deliberately do not
repeat 477 times:

```json
{
  "format": 1,
  "generated": "2026-08-01",
  "requested_bounds": ["1970-01-01", "2100-12-31"],
  "providers": {
    "exchange_calendars": "4.5.6",
    "python_holidays": "0.83",
    "quantlib": "1.43",
    "workalendar": "17.0.0"
  },
  "calendars": {
    "XNYS": {
      "provider": "exchange_calendars",
      "provider_version": "4.5.6",
      "upstream": "XNYS",
      "bounds": ["1970-01-01", "2100-12-31"],
      "weekmask": "Mon Tue Wed Thu Fri",
      "tz": "America/New_York",
      "session_start": "00:00:00",
      "holidays": 1227,
      "sha256": "…"
    }
  }
}
```

Nothing is loaded, or even looked for, unless the manifest names it. The `sha256` is what
the drift check compares.

### Why plain text and not Parquet

The entire point of freezing the data is that an upstream change arrives as a **reviewable
pull request**. Compare what a reviewer sees:

| Format | What the diff shows |
|---|---|
| Parquet / `.npz` | `Binary file src/better_calendar/data/holidays.parquet changed` |
| One date per line | `+ 2027-05-31` / `- 2027-06-01` under `XNYS.csv` |

The second is the thing a human needs. Text also keeps `numpy` the only mandatory
dependency — Parquet would require `pyarrow`, roughly 100 MB installed to read 100 KB of
integers, inherited by every consumer of the library.

The measured cost of text is 0.06 ms to parse one calendar, paid lazily and once.

---

## Bounds: what a calendar admits it does not know

A calendar's horizon is **what its source can actually answer for**, not what was asked for.
62 of the 477 calendars have a narrower horizon than 1970–2100, for two very different
reasons.

### The upstream refuses outright

`exchange-calendars` declares limits and raises outside them:

| Calendar | Horizon | Why |
|---|---|---|
| `XTKS` | 1997 → 2100 | Tokyo data starts in 1997 |
| `XHKG` | 1970 → 2049 | Hong Kong rules are only defined to 2049 |
| `XSHG` | 1990 → 2025 | the Shanghai exchange opened in December 1990 |

Snapshot generation clips to those limits and records them. Straightforward.

### The upstream degrades silently — the dangerous one

Easter can be computed from a rule. Chinese New Year, Rosh Hashanah and Eid cannot: they
are **tabulated**, and the tables end. What upstreams do not do is say so.

Here is QuantLib's Shanghai calendar, holidays per year:

```
2024: 20   2025: 18   2026: 19   2027: 1   2028: 0   2029: 1   2030: 1  …
```

Past 2026 it returns one holiday a year instead of eighteen — Chinese New Year, Labour Day
and National Day have all vanished — while continuing to answer "yes, that is a business
day" with complete confidence. Tel Aviv drops from 62 a year to 11, then to 0 after 2050.
Mumbai drops from 15 to 4.

Neither the declared bounds nor a search for empty years catches this: the degraded years
are not empty, merely **wrong**.

So generation compares each calendar's annual holiday count against its own norm, measured
over a pinned recent window, and drops any trailing run below half of it. The result:

| Calendar | Clipped at | Was returning |
|---|---|---|
| `ql:China.SSE` | 2026 | 1 holiday/year instead of ~18 |
| `ql:Israel.TASE` | 2025 | 11, then 0, instead of ~62 |
| `ql:India.NSE` | 2026 | 4 instead of ~15 |
| `ql:SaudiArabia.Tadawul` | 2029 | 1 instead of ~9 |

Verified to clip exactly the affected calendars and to leave every rule-based one
(`fin:TARGET2`, `rate:SOFR`, `country:FR`, …) at the full horizon.

This is a heuristic, and it is deliberately one that fails **visibly**: the bounds it
produces are written to the manifest, so a clip that moves shows up in the snapshot diff for
a human to accept or reject — the same review path as a moved date.

---

## How an upstream correction reaches you

```
exchange-calendars publishes 4.6.0
        │
        ▼
weekly CI job (snapshot-drift.yml)
  uv sync --all-extras --upgrade
  better-calendar diff
        │
        ├─ no date moved  ──▶  exit 0, nothing happens
        │
        └─ a date moved   ──▶  exit 1
                                  │
                                  ▼
                       better-calendar snapshot
                       open a pull request
                                  │
                                  ▼
                    you read the diff:
                          XNYS.csv
                        + 2027-05-31
                        - 2027-06-01
                                  │
                                  ▼
                    merge (or don't) ──▶ new release
```

The same check also runs on every pull request, so a change to the providers or to the
committed data cannot be merged without the two agreeing.

`diff` distinguishes two cases:

- **a date moved** → non-zero exit, the job opens a PR;
- **the upstream version changed but no date moved** → reported as a note, exit 0. There is
  nothing for a human to decide.

### What this does *not* protect against

If an exchange announces a closure and the upstream package has not published it yet, this
library does not have it either. There is no mechanism here for hand-coding a holiday rule,
and that is a deliberate non-goal — hand-coded rules rot silently and disagree with the
source everyone else uses.

Two honest options in the meantime: wait for the upstream release, or add a local override
(next section).

---

## Adding your own closures

A desk closes on 24 December; the euro area does not. That is a local fact, not a QuantLib
error.

**Never fork a provider calendar for it.** A fork stops receiving upstream corrections, and
nothing will tell you.

Compose on top instead, in `./better-calendar.yaml` or wherever `$BETTER_CALENDAR_CONFIG`
points:

```yaml
calendars:
  desk:paris:
    base: fin:TARGET2
    extra_holidays: ["2026-01-02", "2026-12-24"]
    remove_holidays: []
    tz: Europe/Paris
```

`bcal.get("desk:paris")` then resolves like any other calendar, inherits everything TARGET2
closes, and keeps receiving upstream corrections to that base.

When the desk settles across two centres, `base` takes a list and `base_op` says how to
combine them:

```yaml
calendars:
  desk:eurgbp:
    base: [fin:TARGET2, fin:LNB]
    base_op: all_open              # good in *both*; closed as soon as either closes
    tz: Europe/Paris
```

`base_op` is required as soon as `base` names more than one calendar, and is never
defaulted. `all_open` and `any_open` are exact opposites, and which one a desk means is not
something to guess on its behalf — the same trap the algebra chapter spells out. Both
operands keep receiving upstream corrections, which is the whole point of not flattening
their holidays into `extra_holidays` by hand.

Naming an entry after a shipped calendar **shadows** it, so a whole codebase picks up the
local version without a single call site changing:

```yaml
calendars:
  XNYS:
    base: XNYS                       # the shipped one, resolved beneath the config layer
    extra_holidays: ["2026-11-27"]
```

Or programmatically, for calendars built at runtime:

```python
desk = bcal.get("XNYS").with_holidays(["2026-11-27"], name="desk:us")
bcal.register("desk:us", desk)
```

TOML works identically to YAML. Reading either format needs the `config` extra on
Python < 3.11; on 3.11+ TOML costs nothing because `tomllib` is in the standard library. A
configuration file that cannot be read **raises** rather than being silently ignored — a
closure that is quietly not applied is far worse than one that refuses to load.

---

## Regenerating, in practice

```bash
# Everything, against the currently installed upstream versions
better-calendar snapshot --provider all

# One provider
better-calendar snapshot --provider quantlib

# A few calendars, over a narrower horizon, into a scratch directory
better-calendar snapshot --only XNYS,XPAR --bounds 2020-01-01:2040-12-31 --output /tmp/snap

# Check without writing — this is what CI runs
better-calendar diff
better-calendar diff --provider quantlib --only fin:TARGET2,rate:SOFR
```

Generation is deterministic: two runs against the same upstream versions produce
byte-identical files, which is what makes `diff` meaningful. A test asserts it.

One calendar failing to build does not lose the other 476 — the failure is printed and the
calendar is skipped, and its absence shows up in the next `diff` as a removal.

### Before releasing

```bash
better-calendar diff            # must exit 0
uv run pytest                   # includes the oracle tests
uv build
```

If `diff` is not clean, regenerate, read the diff, and commit it as its own reviewable
change **before** tagging a release. Publishing a stale snapshot is not an error the
packaging step can catch for you.
