import numpy as np
import datetime as dt
from typing import Any
from dataclasses import dataclass
from abc import ABC, abstractmethod


def _d64_to_pos(days64: np.ndarray, start64: np.datetime64) -> np.ndarray:
    """Convert array of datetime64[D] to integer positions relative to start64."""
    days64 = days64.astype("datetime64[D]")
    pos = (days64 - start64).astype("timedelta64[D]").astype("int64")
    return pos

class AbstractMaskBuilder(ABC):
    """
    Abstract base class for mask builders related to a specific package or calendar source.
    """
    @abstractmethod
    def build_mask(self, universe) -> np.ndarray:
        """
        Build a boolean mask of the same length as the universe, where True indicates a business day.

        Parameters
        ----------
        universe: DateUniverse
            The DateUniverse for which to build the mask.
        """
        pass

class DefaultMaskBuilder(AbstractMaskBuilder):
    """
    Default business mask builder, where business days are simply those that are not Saturdays or Sundays.
    """
    def build_mask(self, universe) -> np.ndarray:
        """
        Build a boolean mask of the same length as the universe, where True indicates a business day.

        Parameters
        ----------
        universe: DateUniverse
            The DateUniverse for which to build the mask.

        Returns
        -------
        np.ndarray
            A boolean array of the same length as the universe, where True indicates a business day.
        """
        wd = universe.weekday
        mask = (wd != 6) & (wd != 7)
        return mask
    
@dataclass(frozen=True)
class ExchangeMaskBuilder(AbstractMaskBuilder):
    """
    Business mask builder based on market exchange calendars from the pandas_market_calendars package.

    Specific documention : https://pandas-market-calendars.readthedocs.io/en/latest
    Primary data source : https://www.tradinghours.com

    Attributes
    ----------
    exchange_code: str
        Code of the exchange calendar to use, e.g. "XNYS" for NYSE, "XPAR" for Euronext Paris, etc.
    """
    exchange_code: str

    def build_mask(self, universe) -> np.ndarray:
        """
        Build a boolean mask of the same length as the universe, where True indicates a business day.

        Parameters
        ----------
        universe: DateUniverse
            The DateUniverse for which to build the mask.

        Returns
        -------
        np.ndarray
            A boolean array of the same length as the universe, where True indicates a business day.
        """
        try:
            import pandas_market_calendars as mcal
        except Exception as e:
            raise ValueError(
                "pandas_market_calendars is required to use exchange calendars. "
                "Install extra: pip install better-calendar[exchange]"
            ) from e

        cal = mcal.get_calendar(self.exchange_code)

        start_s = np.datetime_as_string(universe.start64, unit="D")
        end_s = np.datetime_as_string(universe.end64, unit="D")

        sched = cal.schedule(start_date=start_s, end_date=end_s)

        idx = sched.index
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert(None)
        idx = idx.normalize()

        sess64 = idx.values.astype("datetime64[D]")
        pos = _d64_to_pos(sess64, universe.start64)

        mask = np.zeros(len(universe), dtype=bool)
        ok = (pos >= 0) & (pos < len(universe))
        mask[pos[ok]] = True

        return mask


@dataclass(frozen=True)
class QuantLibMaskBuilder:
    """
    Business mask builder based on QuantLib calendars from the QuantLib package.

    Specific documentation : https://quantlib-python-docs.readthedocs.io/en/latest/dates.html#calendar

    Attributes
    ----------
    ql_calendar: Any
        An instance of a QuantLib calendar, e.g. ql.UnitedStates(), ql.France(), etc.
    """
    ql_calendar: Any

    def build_mask(self, universe) -> np.ndarray:
        """
        Build a boolean mask of the same length as the universe, where True indicates a business day.

        Parameters
        ----------
        universe: DateUniverse
            The DateUniverse for which to build the mask.
        """
        try:
            import QuantLib as ql
        except Exception as e:
            raise ValueError(
                "QuantLib package is required for quantlib calendars. "
                "Install extra: pip install better-calendar[quantlib]"
            ) from e

        cal = self.ql_calendar
        mask = np.zeros(len(universe), dtype=bool)

        for i, d64 in enumerate(universe.days):
            s = np.datetime_as_string(d64, unit="D")
            py = dt.date.fromisoformat(s)
            qd = ql.Date(py.day, py.month, py.year)
            mask[i] = bool(cal.isBusinessDay(qd))

        return mask


@dataclass(frozen=True)
class CountryMaskBuilder:
    """
    Business mask builder based on country calendars from the workalendar package.

    Specific documentation : https://pypi.org/project/workalendar/
    """
    country_code: str

    def build_mask(self, universe) -> np.ndarray:
        """
        Build a boolean mask of the same length as the universe, where True indicates a business day.

        Parameters
        ----------
        universe: DateUniverse
            The DateUniverse for which to build the mask.
        """
        try:
            from workalendar.registry import registry
        except Exception as e:
            raise ValueError(
                "workalendar is required for country calendars. "
                "Install extra: pip install better-calendar[country]"
            ) from e

        code = self.country_code.upper()

        cal = registry.get(code)
        if cal is None:
            try:
                keys = sorted(registry.get_calendars().keys())
                sample = ", ".join(keys[:20])
            except Exception:
                sample = ""
            raise ValueError(f"Unknown workalendar country code '{code}'. Available sample: {sample}")

        mask = np.zeros(len(universe), dtype=bool)
        for i, d64 in enumerate(universe.days):
            s = np.datetime_as_string(d64, unit="D")
            py = dt.date.fromisoformat(s)
            mask[i] = bool(cal().is_working_day(day=py))

        return mask