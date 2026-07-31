from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from better_calendar import Calendar
from better_calendar.core.epoch import DEFAULT_BOUNDS

SMALL_BOUNDS = (date(2020, 1, 1), date(2030, 12, 31))


@pytest.fixture
def weekday() -> Calendar:
    return Calendar("weekday", bounds=DEFAULT_BOUNDS)


@pytest.fixture
def small() -> Calendar:
    """A Mon-Fri calendar over a narrow horizon, for cheap boundary tests."""
    return Calendar("small", bounds=SMALL_BOUNDS)


@pytest.fixture
def gulf() -> Calendar:
    """A Sun-Thu calendar, so algebra is exercised across disagreeing weekends."""
    return Calendar("gulf", weekmask="Sun Mon Tue Wed Thu", bounds=SMALL_BOUNDS)


@pytest.fixture
def holiday_cal() -> Calendar:
    return Calendar(
        "holiday",
        holidays=np.array(["2026-07-30", "2026-08-03"], dtype="datetime64[D]"),
        bounds=SMALL_BOUNDS,
    )
