"""M4: the command-line interface, including the drift check that guards I8."""

from __future__ import annotations

import json
from datetime import date

import pytest

from better_calendar.calendars.snapshot import load_manifest
from better_calendar.cli import main


def test_describe(capsys):
    assert main(["describe", "XNYS"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["provider"] == "exchange_calendars"
    assert payload["holidays"] > 0


def test_describe_unknown_is_actionable(capsys):
    assert main(["describe", "XNYZ"]) == 2
    assert "Did you mean" in capsys.readouterr().err


def test_next(capsys):
    assert main(["next", "XNYS", "2026-07-31", "+5"]) == 0
    assert capsys.readouterr().out.strip() == "2026-08-07"


def test_next_backwards(capsys):
    assert main(["next", "fin:TARGET2", "2026-04-07", "-1"]) == 0
    # 6 April 2026 is Easter Monday, so the previous good day is the Thursday before.
    assert capsys.readouterr().out.strip() == "2026-04-02"


def test_next_out_of_bounds_is_actionable(capsys):
    assert main(["next", "XTKS", "1990-01-02", "+1"]) == 2
    assert "outside the bounds" in capsys.readouterr().err


def test_list(capsys):
    assert main(["list", "--provider", "quantlib"]) == 0
    names = capsys.readouterr().out.split()
    assert "fin:TARGET2" in names
    assert all(load_manifest()[name].provider == "quantlib" for name in names)


def test_bad_bounds_are_actionable(capsys):
    assert main(["snapshot", "--bounds", "nonsense"]) == 2
    assert "Use START:END" in capsys.readouterr().err


def test_unknown_provider_is_actionable(capsys):
    assert main(["snapshot", "--provider", "bloomberg"]) == 2
    assert "Unknown provider" in capsys.readouterr().err


# --- snapshot and drift ------------------------------------------------------


@pytest.mark.oracle
def test_snapshot_writes_a_readable_tree(tmp_path, capsys):
    code = main(
        [
            "snapshot",
            "--provider",
            "quantlib",
            "--only",
            "fin:TARGET2,fin:NYB",
            "--bounds",
            "2020-01-01:2030-12-31",
            "--output",
            str(tmp_path),
        ]
    )
    capsys.readouterr()
    assert code == 0
    load_manifest.cache_clear()
    manifest = load_manifest(tmp_path)
    assert set(manifest) == {"fin:TARGET2", "fin:NYB"}
    assert manifest["fin:TARGET2"].bounds == (date(2020, 1, 1), date(2030, 12, 31))
    assert (tmp_path / "calendars" / "fin-TARGET2.csv").exists()
    load_manifest.cache_clear()


@pytest.mark.oracle
def test_snapshot_is_deterministic(tmp_path, capsys):
    """Two runs must produce byte-identical files, or `diff` is meaningless."""
    args = ["snapshot", "--provider", "quantlib", "--only", "fin:TARGET2", "--output"]
    main([*args, str(tmp_path / "a")])
    main([*args, str(tmp_path / "b")])
    capsys.readouterr()
    first = (tmp_path / "a" / "calendars" / "fin-TARGET2.csv").read_bytes()
    second = (tmp_path / "b" / "calendars" / "fin-TARGET2.csv").read_bytes()
    assert first == second
    load_manifest.cache_clear()


@pytest.mark.oracle
def test_diff_is_clean_against_the_committed_snapshot(capsys):
    """§5.5: the committed snapshot must match what the installed upstreams produce.

    A failure here means either the snapshot is stale, or an upstream moved a date. Both
    want the same response: regenerate, read the diff, and merge it deliberately.
    """
    code = main(["diff", "--provider", "quantlib", "--only", "fin:TARGET2,rate:SOFR,fin:LNB"])
    out = capsys.readouterr()
    assert code == 0, out.out + out.err


@pytest.mark.oracle
def test_diff_reports_a_narrowed_horizon(capsys):
    """Asking for a shorter horizon must show up as changed, not pass silently."""
    code = main(
        [
            "diff",
            "--provider",
            "quantlib",
            "--only",
            "fin:TARGET2",
            "--bounds",
            "2020-01-01:2030-12-31",
        ]
    )
    out = capsys.readouterr()
    assert code == 1
    assert "changed  fin:TARGET2" in out.out
