"""M3: identifier resolution, memoisation and registration (§5.4)."""

from __future__ import annotations

import contextlib
from datetime import time

import pytest

import better_calendar as bcal
from better_calendar import Calendar
from better_calendar.calendars.registry import aliases, resolve, unregister
from better_calendar.core.errors import BetterCalendarError, UnknownCalendarError


@pytest.fixture
def _cleanup():
    yield
    for name in ("desk:test", "XNYS"):
        with contextlib.suppress(UnknownCalendarError):
            unregister(name)


def test_builtin_weekday():
    cal = bcal.get("weekday")
    assert cal.weekmask == "Mon Tue Wed Thu Fri"
    assert cal.tz is None
    assert cal.provider == "builtin"


def test_builtin_crypto():
    cal = bcal.get("crypto:24x7")
    assert cal.weekmask == "Mon Tue Wed Thu Fri Sat Sun"
    assert cal.tz == "UTC"
    assert cal.session_start == time(0, 0)
    assert cal.is_bday("2026-08-01") is True


def test_get_is_memoised():
    assert bcal.get("weekday") is bcal.get("weekday")


def test_list_and_describe():
    assert bcal.list() == ["crypto:24x7", "weekday"]
    assert bcal.list(provider="builtin") == ["crypto:24x7", "weekday"]
    assert bcal.list(provider="quantlib") == []
    info = bcal.describe("weekday")
    assert info["requested"] == "weekday"
    assert info["canonical"] == "weekday"
    assert info["provider"] == "builtin"


def test_unknown_name_suggests_a_close_match():
    with pytest.raises(UnknownCalendarError, match=r"Did you mean: 'weekday'"):
        bcal.get("weekdya")


def test_unknown_name_without_a_close_match():
    with pytest.raises(UnknownCalendarError, match="No similar name is registered"):
        bcal.get("zzzzzzzzzz")


def test_alias_without_a_snapshot_says_so():
    """`NYSE` is a known alias for `XNYS`, which milestone M4 will materialise."""
    with pytest.raises(UnknownCalendarError, match="known alias for 'XNYS'"):
        bcal.get("NYSE")


def test_alias_chains_are_followed():
    with pytest.raises(UnknownCalendarError, match="known alias for 'fin:TARGET2'"):
        bcal.get("ESTR")  # ESTR -> rate:ESTR -> fin:TARGET2


def test_alias_table_is_case_insensitive():
    assert aliases()["nyse"] == "XNYS"
    with pytest.raises(UnknownCalendarError, match="known alias for 'XNYS'"):
        bcal.get("nyse")


@pytest.mark.usefixtures("_cleanup")
def test_alias_resolves_to_a_registered_calendar():
    bcal.register("XNYS", Calendar("XNYS", holidays=["2026-07-03"]))
    assert bcal.get("NYSE").name == "XNYS"
    assert bcal.get("NYSE").is_bday("2026-07-03") is False


@pytest.mark.usefixtures("_cleanup")
def test_register_and_unregister():
    cal = Calendar("desk:test", holidays=["2026-07-31"])
    bcal.register("desk:test", cal)
    assert bcal.get("desk:test") is cal
    assert "desk:test" in bcal.list()
    unregister("desk:test")
    with pytest.raises(UnknownCalendarError):
        bcal.get("desk:test")


@pytest.mark.usefixtures("_cleanup")
def test_register_refuses_to_shadow_silently():
    bcal.register("desk:test", Calendar("desk:test"))
    with pytest.raises(BetterCalendarError, match="already registered"):
        bcal.register("desk:test", Calendar("desk:test"))
    bcal.register("desk:test", Calendar("desk:test", holidays=["2026-07-31"]), overwrite=True)
    assert bcal.get("desk:test").is_bday("2026-07-31") is False


@pytest.mark.usefixtures("_cleanup")
def test_register_invalidates_the_memo():
    bcal.register("desk:test", Calendar("desk:test"))
    first = bcal.get("desk:test")
    bcal.register("desk:test", Calendar("desk:test", holidays=["2026-07-31"]), overwrite=True)
    assert bcal.get("desk:test") is not first


def test_register_rejects_non_calendars():
    with pytest.raises(BetterCalendarError, match="takes a Calendar"):
        bcal.register("desk:bad", "not a calendar")  # type: ignore[arg-type]


def test_resolve_accepts_all_three_forms():
    assert resolve(None).name == "weekday"
    assert resolve("crypto:24x7").name == "crypto:24x7"
    cal = Calendar("inline")
    assert resolve(cal) is cal


def test_free_functions_resolve_strings():
    assert bcal.is_bday("2026-08-01") is False
    assert bcal.is_bday("2026-08-01", cal="crypto:24x7") is True
    assert bcal.offset("2026-07-31", 1, cal=bcal.get("weekday")) == "2026-08-03"
