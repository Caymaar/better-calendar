"""M8: organisation-specific calendars from the configuration file (§5.6)."""

from __future__ import annotations

from datetime import date, time

import pytest

import better_calendar as bcal
from better_calendar.calendars.providers import custom
from better_calendar.calendars.registry import reload_config, unregister
from better_calendar.core.errors import BetterCalendarError, UnknownCalendarError

YAML_CONFIG = """
calendars:
  desk:paris:
    base: fin:TARGET2
    extra_holidays: ["2026-01-02", "2026-12-24"]
    remove_holidays: []
    tz: Europe/Paris
  desk:scratch:
    weekmask: "Sun Mon Tue Wed Thu"
    extra_holidays: ["2026-03-20"]
    bounds: ["2020-01-01", "2035-12-31"]
    tz: Asia/Dubai
  desk:fx:
    base: fin:NYB
    tz: America/New_York
    session_start: "17:00"
"""

TOML_CONFIG = """
[calendars."desk:paris"]
base = "fin:TARGET2"
extra_holidays = ["2026-01-02", "2026-12-24"]
tz = "Europe/Paris"
"""


@pytest.fixture
def configured(tmp_path, monkeypatch):
    """Point the library at a YAML config for the duration of a test."""

    def _write(text: str, name: str = "better-calendar.yaml"):
        path = tmp_path / name
        path.write_text(text)
        monkeypatch.setenv(custom.CONFIG_ENV_VAR, str(path))
        reload_config()
        return path

    yield _write
    monkeypatch.delenv(custom.CONFIG_ENV_VAR, raising=False)
    reload_config()


# --- composition, not forking -------------------------------------------------


def test_a_configured_calendar_composes_on_its_base(configured):
    configured(YAML_CONFIG)
    desk = bcal.get("desk:paris")
    base = bcal.get("fin:TARGET2")

    # Everything the base closes, the desk closes.
    assert desk.is_bday("2026-04-06") is False  # Easter Monday, from TARGET2
    # Plus its own days.
    assert desk.is_bday("2026-12-24") is False
    assert base.is_bday("2026-12-24") is True
    # And the base is untouched (I1).
    assert bcal.get("fin:TARGET2").is_bday("2026-12-24") is True


def test_configured_calendars_inherit_the_base_bounds_and_provider(configured):
    configured(YAML_CONFIG)
    desk = bcal.get("desk:paris")
    assert desk.bounds == bcal.get("fin:TARGET2").bounds
    assert desk.provider == "custom"
    assert desk.provider_version == "fin:TARGET2"
    assert desk.tz == "Europe/Paris"


def test_remove_holidays_reopens_a_day(configured):
    configured(
        """
calendars:
  desk:open-on-easter:
    base: fin:TARGET2
    remove_holidays: ["2026-04-06"]
"""
    )
    assert bcal.get("fin:TARGET2").is_bday("2026-04-06") is False
    assert bcal.get("desk:open-on-easter").is_bday("2026-04-06") is True


def test_a_calendar_can_be_built_without_a_base(configured):
    configured(YAML_CONFIG)
    scratch = bcal.get("desk:scratch")
    assert scratch.weekmask == "Mon Tue Wed Thu Sun"
    assert scratch.bounds == (date(2020, 1, 1), date(2035, 12, 31))
    assert scratch.is_bday("2026-08-02") is True  # a Sunday
    assert scratch.is_bday("2026-03-20") is False


def test_session_start_is_configurable(configured):
    configured(YAML_CONFIG)
    assert bcal.get("desk:fx").session_start == time(17, 0)
    assert bcal.get("desk:fx").session_of("2026-07-31 09:00") == date(2026, 7, 30)


# --- resolution order ----------------------------------------------------------


def test_a_configured_calendar_shadows_the_snapshot(configured):
    """A desk can take over a shipped identifier without touching any call site."""
    assert bcal.get("XNYS").is_bday("2026-11-27") is True
    configured(
        """
calendars:
  XNYS:
    base: XNYS
    extra_holidays: ["2026-11-27"]
"""
    )
    assert bcal.get("XNYS").is_bday("2026-11-27") is False
    assert bcal.get("NYSE").is_bday("2026-11-27") is False  # aliases follow


def test_register_still_wins_over_the_configuration(configured):
    configured(YAML_CONFIG)
    assert bcal.get("desk:paris").is_bday("2026-12-24") is False
    bcal.register("desk:paris", bcal.Calendar("desk:paris"), overwrite=True)
    try:
        assert bcal.get("desk:paris").is_bday("2026-12-24") is True
    finally:
        unregister("desk:paris")
        reload_config()


def test_configured_calendars_are_listed_and_described(configured):
    configured(YAML_CONFIG)
    assert "desk:paris" in bcal.list()
    assert bcal.list(provider="custom") == ["desk:fx", "desk:paris", "desk:scratch"]
    assert bcal.describe("desk:paris")["provider"] == "custom"


def test_configured_names_appear_in_did_you_mean(configured):
    configured(YAML_CONFIG)
    with pytest.raises(UnknownCalendarError, match=r"'desk:paris'"):
        bcal.get("desk:pariss")


# --- formats -------------------------------------------------------------------


def test_toml_needs_no_extra(configured):
    configured(TOML_CONFIG, name="better-calendar.toml")
    assert bcal.get("desk:paris").is_bday("2026-12-24") is False


def test_yaml_and_toml_agree(configured):
    configured(YAML_CONFIG)
    from_yaml = bcal.get("desk:paris")
    configured(TOML_CONFIG, name="better-calendar.toml")
    assert bcal.get("desk:paris").good_days().tolist() == from_yaml.good_days().tolist()


def test_the_shipped_example_parses(tmp_path, monkeypatch):
    """The example file has to actually work, or it is worse than no example."""
    import shutil
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "better-calendar.yaml.example"
    target = tmp_path / "better-calendar.yaml"
    shutil.copy(source, target)
    monkeypatch.setenv(custom.CONFIG_ENV_VAR, str(target))
    reload_config()
    try:
        assert set(custom.override_calendars()) >= {"desk:paris", "desk:gulf", "desk:fx"}
        assert bcal.get("desk:gulf").weekmask == "Mon Tue Wed Thu Sun"
        assert bcal.get("desk:us-equities").is_bday("2026-11-27") is False
    finally:
        monkeypatch.delenv(custom.CONFIG_ENV_VAR, raising=False)
        reload_config()


# --- failure modes --------------------------------------------------------------


def test_a_missing_configured_path_is_reported(monkeypatch):
    monkeypatch.setenv(custom.CONFIG_ENV_VAR, "/nowhere/better-calendar.yaml")
    custom.load_overrides.cache_clear()
    try:
        with pytest.raises(BetterCalendarError, match="does not exist"):
            custom.config_path()
    finally:
        monkeypatch.delenv(custom.CONFIG_ENV_VAR, raising=False)
        reload_config()


def test_no_configuration_is_not_an_error():
    assert custom.load_overrides(None) == {} or isinstance(custom.load_overrides(None), dict)


def test_unknown_keys_are_refused(configured):
    """A typo in a key must not be silently ignored — the closure would go unapplied."""
    configured(
        """
calendars:
  desk:typo:
    base: fin:TARGET2
    extra_holiday: ["2026-12-24"]
"""
    )
    with pytest.raises(BetterCalendarError, match="unknown keys"):
        bcal.get("desk:typo")


def test_a_bad_base_is_reported(configured):
    configured(
        """
calendars:
  desk:broken:
    base: no:such:calendar
"""
    )
    with pytest.raises(UnknownCalendarError):
        bcal.get("desk:broken")


def test_a_malformed_session_start_is_reported(configured):
    configured(
        """
calendars:
  desk:broken:
    session_start: "five o'clock"
"""
    )
    with pytest.raises(BetterCalendarError, match="session_start"):
        bcal.get("desk:broken")


def test_a_malformed_bounds_is_reported(configured):
    configured(
        """
calendars:
  desk:broken:
    bounds: "2026"
"""
    )
    with pytest.raises(BetterCalendarError, match="bounds"):
        bcal.get("desk:broken")
