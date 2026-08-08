# Notebooks

Six notebooks covering the whole public API, each self-contained and runnable. They are
committed **with their outputs**, so they read directly on GitHub without running anything
— and a CI job re-executes them, because documentation that no longer runs is worse than
no documentation.

| # | Notebook | Contents |
|---|---|---|
| 01 | [Getting started](01-getting-started.ipynb) | `adjust` / `offset` / `count`, type transparency, strict parsing, the seven roll conventions, intervals, bounds, vectorisation measured |
| 02 | [Calendars and algebra](02-calendars-and-algebra.ipynb) | registry, aliases, provenance, non-standard weekmasks, `& \| - ^` and the vocabulary trap, composites, deriving |
| 03 | [Offsets, tenors and settlement](03-offsets-tenors-settlement.ipynb) | `BDay` on scalars and containers, pandas interop and where it diverges, the `.cal` accessor, tenor grammar, clamping vs the EOM rule, settlement lags |
| 04 | [Recurrences and schedules](04-recurrences-and-schedules.ipynb) | the `schedule` engine, the `every` and `on` grammars, `missing=`, IMM dates, expiries, `on="edges"` and the unadjusted/adjusted separation, stubs |
| 05 | [Timezones and sessions](05-timezones-and-sessions.ipynb) | the `.date()` bug, naive vs aware, wall clock across a DST transition, `session_of`, `session_bounds`, `grid` against the mis-anchored resample, `at_times` |
| 06 | [Snapshots and overrides](06-snapshots-and-overrides.ipynb) | why the data is frozen, format and manifest, honest bounds, upstream drift, the CLI, organisation calendars |

## Running them

```bash
uv sync --all-extras          # includes jupyter and the providers
uv run jupyter lab notebooks/
```

Notebooks 02 and 06 use the provider extras for their drift and diff sections; everything
else runs on a bare install.

## Where to start

- **New to the library**: 01, then 02.
- **Pricing or back office**: 03 and 04.
- **Intraday or multi-timezone work**: 05, in full.
- **Explaining to an auditor where the data comes from**: 06, and
  [docs/calendar-data.md](../docs/calendar-data.md).

## A note

Writing these notebooks surfaced two real defects: two aliases pointed at calendars absent
from the snapshot, and nine currencies in the settlement-lag table had no settlement
calendar at all. Both are fixed, and each now has a test that stops it coming back. That is
what writing documentation by executing it is for.
