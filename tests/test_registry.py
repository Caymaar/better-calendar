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
    assert bcal.list(provider="builtin") == ["crypto:24x7", "weekday"]
    assert {"weekday", "crypto:24x7", "XNYS", "fin:TARGET2"} <= set(bcal.list())
    assert "fin:TARGET2" in bcal.list(provider="quantlib")
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


def test_alias_resolves_through_the_snapshot():
    assert bcal.get("NYSE").name == "XNYS"


def test_an_alias_and_its_target_share_one_object():
    """Memoisation has to survive the alias hop, or every alias loads a second copy."""
    assert bcal.get("NYSE") is bcal.get("XNYS")


def test_alias_chains_are_followed():
    # ESTR -> rate:ESTR -> fin:TARGET2, and the euro short-term rate does follow TARGET2.
    assert bcal.get("ESTR") is bcal.get("fin:TARGET2")


def test_alias_table_is_case_insensitive():
    assert aliases()["nyse"] == "XNYS"
    assert bcal.get("nyse") is bcal.get("XNYS")


def test_an_alias_to_something_unsnapshotted_says_which():
    bcal.register("zzz:alias-target-missing", Calendar("zzz:alias-target-missing"))
    unregister("zzz:alias-target-missing")
    with pytest.raises(UnknownCalendarError, match="No similar name is registered"):
        bcal.get("zzz:alias-target-missing")


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
