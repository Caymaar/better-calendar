"""M4: the committed snapshot, its integrity, and what it promises callers."""

from __future__ import annotations

import json
from datetime import date

import pytest

import better_calendar as bcal
from better_calendar.calendars.snapshot import (
    DATA_DIR,
    MANIFEST_NAME,
    SNAPSHOT_FORMAT,
    entry_for,
    load_calendar,
    load_manifest,
    snapshot_ids,
    write_snapshot,
)
from better_calendar.core.errors import BetterCalendarError, UnknownCalendarError

MANIFEST = load_manifest()


def test_a_snapshot_is_committed():
    assert MANIFEST, "no committed snapshot; run `better-calendar snapshot`"
    assert (DATA_DIR / MANIFEST_NAME).exists()


def test_manifest_declares_its_format():
    payload = json.loads((DATA_DIR / MANIFEST_NAME).read_text())
    assert payload["format"] == SNAPSHOT_FORMAT
    assert set(payload["providers"]) >= {
        "exchange_calendars",
        "python_holidays",
        "quantlib",
        "workalendar",
    }


def test_every_provider_contributed():
    """M4 is done when all four providers materialise, not just some."""
    providers = {entry.provider for entry in MANIFEST.values()}
    assert providers == {
        "exchange_calendars",
        "python_holidays",
        "quantlib",
        "workalendar",
    }


@pytest.mark.parametrize(
    "identifier",
    ["XNYS", "XLON", "XETR", "XPAR", "XTKS", "country:FR", "country:US", "country:US-NY"],
)
def test_the_calendars_named_in_the_spec_are_present(identifier):
    assert identifier in MANIFEST


@pytest.mark.parametrize(
    "identifier", ["fin:TARGET2", "fin:LNB", "fin:NYB", "rate:SOFR", "rate:TONA"]
)
def test_the_financial_calendars_are_present(identifier):
    assert identifier in MANIFEST


def test_every_manifest_entry_has_its_file_and_the_right_digest():
    """The digest is what the drift check compares; a stale one would hide a change."""
    import hashlib

    for identifier, entry in MANIFEST.items():
        path = DATA_DIR / "calendars" / entry.filename
        assert path.exists(), identifier
        text = path.read_text(encoding="utf-8")
        assert hashlib.sha256(text.encode()).hexdigest() == entry.sha256, identifier
        assert len(text.splitlines()) == entry.holidays, identifier


def test_no_orphan_files():
    listed = {entry.filename for entry in MANIFEST.values()}
    on_disk = {path.name for path in (DATA_DIR / "calendars").glob("*.csv")}
    assert on_disk == listed


def test_files_are_sorted_unique_iso_dates():
    for identifier in ("XNYS", "country:FR", "fin:TARGET2"):
        path = DATA_DIR / "calendars" / MANIFEST[identifier].filename
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines == sorted(lines) == sorted(set(lines))
        assert all(date.fromisoformat(line) for line in lines)


def test_bounds_are_recorded_honestly():
    """I2: a provider that cannot answer for a period must not claim it can."""
    # exchange-calendars refuses Tokyo before 1997 and Hong Kong after 2049.
    assert MANIFEST["XTKS"].bounds[0] == date(1997, 1, 1)
    assert MANIFEST["XHKG"].bounds[1] == date(2049, 12, 31)
    with pytest.raises(bcal.OutOfBoundsError):
        bcal.get("XTKS").is_bday("1996-12-31")
    with pytest.raises(bcal.OutOfBoundsError):
        bcal.get("XHKG").is_bday("2050-01-01")


def test_no_calendar_ends_on_a_run_of_empty_years():
    """A dead tail inside the bounds reads as "every day is a business day" (I2).

    Isolated empty years are legitimate — a year where every fixed holiday happened to
    fall on a weekend genuinely has no business-day holidays. A *run* of them at the end
    of the horizon is an upstream table that quietly ran out, which is what
    ``clip_to_dense`` exists to remove.
    """
    from collections import Counter

    offenders = []
    for identifier, entry in MANIFEST.items():
        if entry.holidays == 0:
            continue
        calendar = bcal.get(identifier)
        years = Counter(int(str(day)[:4]) for day in calendar.holidays.astype("datetime64[D]"))
        trailing = 0
        for year in reversed(range(entry.bounds[0].year, entry.bounds[1].year + 1)):
            if years.get(year, 0):
                break
            trailing += 1
        if trailing >= 3:
            offenders.append((identifier, trailing))
    assert offenders == []


@pytest.mark.parametrize(
    ("identifier", "last_year"),
    [
        # QuantLib tabulates lunar, Hebrew and Islamic holidays; the tables end, and the
        # calendar does not say so. See providers.clip_to_dense.
        ("ql:China.SSE", 2026),
        ("ql:Israel.TASE", 2025),
        ("ql:India.NSE", 2026),
    ],
)
def test_tabulated_calendars_stop_where_their_data_does(identifier, last_year):
    assert MANIFEST[identifier].bounds[1].year == last_year
    with pytest.raises(bcal.OutOfBoundsError):
        bcal.get(identifier).is_bday(f"{last_year + 1}-06-15")


def test_rule_based_calendars_keep_the_full_horizon():
    """The density clip must not touch calendars whose rules genuinely extend."""
    for identifier in ("fin:TARGET2", "rate:SOFR", "fin:LNB", "country:FR", "country:US"):
        assert MANIFEST[identifier].bounds[1] == date(2100, 12, 31), identifier


# --- reading -----------------------------------------------------------------


def test_load_calendar_carries_provenance():
    calendar = load_calendar("XNYS")
    assert calendar.provider == "exchange_calendars"
    assert calendar.provider_version
    assert calendar.tz == "America/New_York"


def test_load_unknown_calendar_suggests():
    with pytest.raises(UnknownCalendarError, match="Did you mean"):
        load_calendar("XNYZ")


def test_registry_resolves_snapshot_calendars():
    assert bcal.get("XNYS").name == "XNYS"
    assert bcal.get("NYSE") is bcal.get("XNYS")  # alias, memoised
    assert bcal.get("EUR").name == "fin:TARGET2"
    assert bcal.get("SONIA").name == "fin:LNB"


def test_snapshot_ids_and_listing_agree():
    assert set(snapshot_ids()) <= set(bcal.list())
    assert set(bcal.list()) == set(snapshot_ids()) | {"weekday", "crypto:24x7"}


def test_describe_reports_provenance():
    info = bcal.describe("rate:SOFR")
    assert info["provider"] == "quantlib"
    assert info["canonical"] == "rate:SOFR"
    assert info["holidays"] > 0


# --- writing -----------------------------------------------------------------


def test_write_and_read_round_trip(tmp_path):
    calendar = bcal.Calendar(
        "desk:demo",
        holidays=["2026-12-24", "2026-01-02"],
        provider="test",
        provider_version="0",
        bounds=(date(2026, 1, 1), date(2026, 12, 31)),
    )
    entry, text = entry_for(calendar, "demo")
    assert text == "2026-01-02\n2026-12-24\n"  # sorted, one per line
    write_snapshot(
        {entry: text},
        tmp_path,
        generated=date(2026, 7, 31),
        requested_bounds=(date(2026, 1, 1), date(2026, 12, 31)),
        provider_versions={"test": "0"},
    )
    reloaded = load_calendar("desk:demo", tmp_path)
    assert reloaded == calendar
    load_manifest.cache_clear()


def test_write_removes_stale_files(tmp_path):
    first = bcal.Calendar("a", holidays=["2026-01-01"])
    second = bcal.Calendar("b", holidays=["2026-01-01"])
    generated = date(2026, 7, 31)
    bounds = (date(2026, 1, 1), date(2026, 12, 31))
    write_snapshot(
        dict([entry_for(first, "a"), entry_for(second, "b")]),
        tmp_path,
        generated=generated,
        requested_bounds=bounds,
        provider_versions={},
    )
    assert {p.name for p in (tmp_path / "calendars").iterdir()} == {"a.csv", "b.csv"}
    write_snapshot(
        dict([entry_for(first, "a")]),
        tmp_path,
        generated=generated,
        requested_bounds=bounds,
        provider_versions={},
    )
    assert {p.name for p in (tmp_path / "calendars").iterdir()} == {"a.csv"}
    load_manifest.cache_clear()


def test_corrupt_file_is_reported_actionably(tmp_path):
    calendar = bcal.Calendar("x", holidays=["2026-01-01"])
    entry, text = entry_for(calendar, "x")
    write_snapshot(
        {entry: text},
        tmp_path,
        generated=date(2026, 7, 31),
        requested_bounds=(date(2026, 1, 1), date(2026, 12, 31)),
        provider_versions={},
    )
    (tmp_path / "calendars" / "x.csv").write_text("not-a-date\n")
    with pytest.raises(BetterCalendarError, match=r"corrupt.*Regenerate"):
        load_calendar("x", tmp_path)
    load_manifest.cache_clear()


def test_future_format_is_refused(tmp_path):
    (tmp_path / MANIFEST_NAME).write_text(json.dumps({"format": 99, "calendars": {}}))
    with pytest.raises(BetterCalendarError, match="format 99"):
        load_manifest(tmp_path)
    load_manifest.cache_clear()


def test_missing_snapshot_is_not_an_error(tmp_path):
    assert load_manifest(tmp_path) == {}
    load_manifest.cache_clear()
