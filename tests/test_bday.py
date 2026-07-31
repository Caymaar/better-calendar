"""M5: the BDay offset object and pandas interoperability (§7.2)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

import better_calendar as bcal
from better_calendar import BDay, Calendar, Roll, config
from better_calendar.core.errors import AmbiguousTimezoneError

PARIS = ZoneInfo("Europe/Paris")


@pytest.fixture(autouse=True)
def _reset_config():
    original = config.default_tz
    yield
    config.default_tz = original


# --- scalars -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (date(2026, 7, 31), date(2026, 8, 3)),
        (datetime(2026, 7, 31, 9, 30), datetime(2026, 8, 3, 9, 30)),
        (pd.Timestamp("2026-07-31 09:30"), pd.Timestamp("2026-08-03 09:30")),
        (np.datetime64("2026-07-31"), np.datetime64("2026-08-03")),
        ("2026-07-31", "2026-08-03"),
        ("20260731", "20260803"),
        (20260731, 20260803),
    ],
)
def test_addition_works_on_every_input_type(value, expected):
    result = value + BDay(1)
    assert result == expected
    assert type(result) is type(value)


def test_subtraction():
    assert date(2026, 8, 3) - BDay(1) == date(2026, 7, 31)
    assert "2026-08-03" - BDay(1) == "2026-07-31"


def test_the_motivating_example():
    """§17 M5: `date + BDay(5)` has to be correct."""
    assert date(2026, 7, 31) + BDay(5) == date(2026, 8, 7)


def test_zero_and_negative():
    assert date(2026, 7, 31) + BDay(0) == date(2026, 7, 31)
    assert date(2026, 8, 1) + BDay(0) == date(2026, 8, 3)  # Saturday rolls forward
    assert date(2026, 8, 3) + BDay(-1) == date(2026, 7, 31)


def test_arithmetic_on_the_offset_itself():
    assert BDay(2) * 3 == BDay(6)
    assert 3 * BDay(2) == BDay(6)
    assert -BDay(2) == BDay(-2)
    assert date(2026, 7, 31) + BDay(1) * 5 == date(2026, 8, 7)


def test_offset_is_frozen_and_hashable():
    assert {BDay(1), BDay(1)} == {BDay(1)}
    with pytest.raises(Exception, match=r"frozen|cannot assign"):
        BDay(1).n = 2  # type: ignore[misc]  # the point of the test


def test_named_calendar():
    assert "2026-07-02" + BDay(1, cal="XNYS") == "2026-07-06"  # 3 July closed
    assert "2026-07-02" + BDay(1) == "2026-07-03"  # plain weekday calendar


def test_calendar_object():
    holidays = Calendar("desk", holidays=["2026-08-03"])
    assert date(2026, 7, 31) + BDay(1, cal=holidays) == date(2026, 8, 4)


def test_roll_convention_is_honoured():
    assert date(2026, 8, 1) + BDay(0, roll=Roll.PRECEDING) == date(2026, 7, 31)
    assert date(2026, 8, 1) + BDay(0, roll=Roll.FOLLOWING) == date(2026, 8, 3)


def test_calendar_bday_factory():
    assert date(2026, 7, 31) + Calendar("weekday").bday(1) == date(2026, 8, 3)
    assert Calendar("weekday").bday(3).n == 3


# --- containers, the fragile part (§7.2) --------------------------------------


def test_datetime_index():
    index = pd.DatetimeIndex(["2026-07-31", "2026-08-03"])
    result = index + BDay(1)
    assert isinstance(result, pd.DatetimeIndex)
    assert list(result.strftime("%Y-%m-%d")) == ["2026-08-03", "2026-08-04"]


def test_series():
    series = pd.Series(pd.DatetimeIndex(["2026-07-31", "2026-08-03"]))
    result = series + BDay(1)
    assert isinstance(result, pd.Series)
    assert result.dtype.kind == "M"
    assert list(result.dt.strftime("%Y-%m-%d")) == ["2026-08-03", "2026-08-04"]


def test_the_motivating_container_example():
    """§17 M5: `series + BDay(5)` has to be correct too."""
    series = pd.Series(pd.DatetimeIndex(["2026-07-31"]))
    assert list((series + BDay(5)).dt.strftime("%Y-%m-%d")) == ["2026-08-07"]


def test_numpy_array():
    """Without __array_ufunc__ = None this would die inside numpy's ufunc machinery."""
    array = np.array(["2026-07-31", "2026-08-03"], dtype="datetime64[D]")
    result = array + BDay(1)
    assert list(pd.DatetimeIndex(result).strftime("%Y-%m-%d")) == ["2026-08-03", "2026-08-04"]


def test_series_subtraction():
    series = pd.Series(pd.DatetimeIndex(["2026-08-03"]))
    assert list((series - BDay(1)).dt.strftime("%Y-%m-%d")) == ["2026-07-31"]


def test_empty_container():
    empty = pd.DatetimeIndex([])
    assert len(empty + BDay(1)) == 0


def test_container_matches_the_recommended_form():
    """`series + BDay(n)` and `cal.offset(series, n)` must not disagree."""
    series = pd.Series(pd.date_range("2026-01-01", "2026-12-31", freq="D"))
    calendar = bcal.get("XNYS")
    pd.testing.assert_series_equal(
        series + BDay(3, cal="XNYS"), pd.Series(calendar.offset(series, 3))
    )


# --- timezones (I4, I5) -------------------------------------------------------


def test_tz_aware_container_needs_a_timezone():
    """I4: an instant plus a calendar with no timezone is genuinely ambiguous."""
    index = pd.DatetimeIndex(["2026-03-27 09:00"]).tz_localize("Europe/Paris")
    with pytest.raises(AmbiguousTimezoneError):
        _ = index + BDay(1)


def test_tz_aware_container_with_a_timezone_aware_calendar():
    index = pd.DatetimeIndex(["2026-03-27 09:00"]).tz_localize("Europe/Paris")
    result = index + BDay(1, cal=Calendar("paris", tz="Europe/Paris"))
    assert str(result.tz) == "Europe/Paris"
    # I5: Friday to Monday across the spring transition keeps the wall clock at 09:00.
    assert list(result.strftime("%Y-%m-%d %H:%M")) == ["2026-03-30 09:00"]


def test_tz_aware_container_with_the_global_default():
    index = pd.DatetimeIndex(["2026-03-27 09:00"]).tz_localize("Europe/Paris")
    config.default_tz = "Europe/Paris"
    assert list((index + BDay(1)).strftime("%Y-%m-%d %H:%M")) == ["2026-03-30 09:00"]


def test_scalar_wall_clock_survives_dst():
    before = datetime(2026, 3, 27, 9, 0, tzinfo=PARIS)
    after = before + BDay(1, cal=Calendar("paris", tz="Europe/Paris"))
    assert (after.hour, after.tzinfo) == (9, PARIS)
    elapsed = after.astimezone(timezone.utc) - before.astimezone(timezone.utc)
    assert elapsed == timedelta(hours=71)


# --- CustomBusinessDay interop ------------------------------------------------


def test_to_pandas_offset_agrees_from_a_business_day():
    calendar = bcal.get("XNYS")
    offset = calendar.to_pandas_offset()
    assert isinstance(offset, pd.offsets.CustomBusinessDay)
    for start in ("2026-07-02", "2026-07-31", "2026-12-24", "2026-11-25"):
        assert calendar.is_bday(start)
        assert pd.Timestamp(start) + offset == pd.Timestamp(calendar.offset(start, 1))


@pytest.mark.parametrize(
    ("start", "ours", "pandas_"),
    [("2026-08-01", "2026-08-04", "2026-08-03"), ("2026-07-03", "2026-07-07", "2026-07-06")],
)
def test_to_pandas_offset_differs_from_a_non_business_day(start, ours, pandas_):
    """Pinned, because it is a real difference and callers have to know about it.

    We normalise then move, as numpy.busday_offset does. CustomBusinessDay counts the
    normalisation as the move.
    """
    calendar = bcal.get("XNYS")
    assert not calendar.is_bday(start)
    assert calendar.offset(start, 1) == ours
    assert pd.Timestamp(start) + calendar.to_pandas_offset() == pd.Timestamp(pandas_)


def test_to_pandas_offset_drives_date_range():
    calendar = bcal.get("XNYS")
    generated = pd.date_range("2026-07-01", "2026-07-10", freq=calendar.to_pandas_offset())
    ours = calendar.bdays_between("2026-07-01", "2026-07-11")
    assert list(generated.strftime("%Y-%m-%d")) == list(ours.strftime("%Y-%m-%d"))


# --- the .cal accessor --------------------------------------------------------


def test_cal_accessor():
    import better_calendar.integrations.pandas_  # noqa: F401  # registers .cal

    series = pd.Series(pd.DatetimeIndex(["2026-07-31", "2026-08-01"]))
    assert list(series.cal.is_bday()) == [True, False]
    assert list(series.cal.offset(1).dt.strftime("%Y-%m-%d")) == ["2026-08-03", "2026-08-04"]
    # 1 August is a Saturday; rolling forward stays inside August, so MF does not go back.
    assert list(series.cal.adjust("MF").dt.strftime("%Y-%m-%d")) == ["2026-07-31", "2026-08-03"]
    assert list(series.cal.add_tenor("1M").dt.strftime("%Y-%m-%d")) == [
        "2026-08-31",
        "2026-09-01",
    ]


def test_cal_accessor_on_an_index():
    import better_calendar.integrations.pandas_  # noqa: F401

    index = pd.DatetimeIndex(["2026-07-27"])
    # `.cal` is registered at runtime, so a static checker cannot know about it.
    assert list(index.cal.count_to("2026-08-01")) == [5]  # type: ignore[attr-defined]
    offset = index.cal.offset(1, "XNYS")  # type: ignore[attr-defined]
    assert list(offset.strftime("%Y-%m-%d")) == ["2026-07-28"]


def test_cal_accessor_preserves_series_index_and_name():
    import better_calendar.integrations.pandas_  # noqa: F401

    series = pd.Series(pd.DatetimeIndex(["2026-07-31"]), index=["a"], name="traded")
    result = series.cal.offset(1)
    assert list(result.index) == ["a"]
    assert result.name == "traded"


def test_importing_better_calendar_does_not_register_the_accessor():
    """§14: the package root must not import pandas, so it cannot register anything."""
    import subprocess
    import sys

    code = (
        "import better_calendar, pandas as pd; "
        "print(hasattr(pd.Series(dtype='datetime64[ns]'), 'cal'))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "False"


# --- spot lags ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("currency", "expected"),
    [("EUR", 2), ("USD", 2), ("GBP", 0), ("CAD", 1), ("TRY", 0), ("chf", 2)],
)
def test_spot_lags_match_the_spec(currency, expected):
    assert bcal.spot_lag(currency) == expected


def test_spot_uses_the_currency_calendar():
    # 3 August 2026 is the Civic Holiday in Toronto but an ordinary Monday elsewhere.
    assert bcal.spot("2026-07-31", "CAD") == "2026-08-04"
    assert bcal.spot("2026-07-31", "GBP") == "2026-07-31"
    assert bcal.spot("2026-07-31", "EUR") == "2026-08-04"


def test_spot_accepts_an_explicit_calendar():
    both = bcal.get("EUR") & bcal.get("USD")
    assert bcal.spot("2026-07-01", "EUR", cal=both) == "2026-07-06"  # skips 3 July


def test_spot_preserves_type_and_vectorises():
    assert bcal.spot(date(2026, 7, 31), "EUR") == date(2026, 8, 4)
    result = bcal.spot(["2026-07-31", "2026-08-03"], "EUR")
    assert list(result.strftime("%Y-%m-%d")) == ["2026-08-04", "2026-08-05"]


def test_unknown_currency_is_actionable():
    with pytest.raises(bcal.BetterCalendarError, match="No settlement lag known"):
        bcal.spot_lag("XYZ")


def test_spot_lag_table_is_read_only():
    with pytest.raises(TypeError):
        bcal.SPOT_LAG["EUR"] = 99  # type: ignore[index]  # the point of the test


def test_every_currency_has_a_usable_settlement_calendar():
    """A spot lag whose calendar cannot answer for the present is a trap, not data.

    This caught nine currencies with no alias at all, plus ILS and CNH, whose QuantLib
    settlement calendars are tabulated and stop before today.
    """
    from datetime import date

    unusable = {}
    for currency in bcal.SPOT_LAG:
        try:
            calendar = bcal.get(currency)
        except bcal.UnknownCalendarError:
            unusable[currency] = "no calendar"
            continue
        if calendar.bounds[1] < date(2035, 12, 31):
            unusable[currency] = f"horizon ends {calendar.bounds[1]}"
    assert unusable == {}


def test_spot_answers_for_every_currency_in_the_table():
    for currency in bcal.SPOT_LAG:
        assert bcal.spot("2026-07-31", currency)
