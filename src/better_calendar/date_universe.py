import numpy as np
import datetime as dt
from typing import Dict
from dataclasses import dataclass, field


@dataclass()
class DateUniverse:
    """
    Structure representing the static information about a calendar :
        1. Non-lazy fields (built at init):
            - Start and end date of the calendar : np.datetime64
            - Contiguous days in the calendar : np.ndarray
        2. Lazy fields (built on demand and cached):
            - Weekday as int (Monday=1, Sunday=7) : np.ndarray
            - Month (1 to 12) : np.ndarray
            - Month unique key starting in 1970 (0 for Jan 1970, 1 for Feb 1970, etc.) : np.ndarray
            - Quarter (1 to 4) : np.ndarray
            - Semester (1 to 2) : np.ndarray
            - Week (1 to 53) : np.ndarray
            - Year : np.ndarray

    This structure is immutable after construction.
    By default, only the "naked" calendar is built as the array of contiguous days between start and end.
    The other fields are built lazily on demand (through the properties), as they can be more costly to compute.

    All dates are stored as np.datetime64 for efficiency.
    As this structure is purely core logic, it is a standalone class and we suppose that the input dates are already in np.datetime64 format.
    """
    start: np.datetime64
    end: np.datetime64

    days: np.ndarray = field(init=False)
    _cache: Dict[str, np.ndarray] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self.start64 = np.datetime64(self.start)
        self.end64 = np.datetime64(self.end)

        n_days = int((self.end64 - self.start64) / np.timedelta64(1, "D")) + 1
        self.days = self.start64 + np.arange(n_days, dtype="int64").astype("timedelta64[D]")

    def __len__(self) -> int:
        return int(self.days.shape[0])

    def locate(self, d64: np.datetime64) -> int:
        """Return index i such that days[i] == d64. Raises OutOfRangeError if outside."""
        i = int((d64 - self.start64) / np.timedelta64(1, "D"))
        if i < 0 or i >= len(self):
            raise ValueError(f"Date {d64} outside universe [{self.start64}, {self.end64}]")
        return i

    @property
    def weekday(self) -> np.ndarray:
        key = "weekday"
        if key not in self._cache:
            days_int = self.days.astype("datetime64[D]").astype("int64")
            wd = ((days_int + 3) % 7 + 1).astype("uint8")
            self._cache[key] = wd
        return self._cache[key]

    @property
    def year(self) -> np.ndarray:
        key = "year"
        if key not in self._cache:
            y = self.days.astype("datetime64[Y]").astype("int64") + 1970
            self._cache[key] = y.astype("int32")
        return self._cache[key]

    @property
    def iso_year(self) -> np.ndarray:
        key = "iso_year"
        if key not in self._cache:
            iso_years = []
            for d64 in self.days:
                s = np.datetime_as_string(d64, unit="D")
                py = dt.date.fromisoformat(s)
                iso_years.append(py.isocalendar().year)
            self._cache[key] = np.array(iso_years, dtype="int32")
        return self._cache[key]
    
    @property
    def month(self) -> np.ndarray:
        key = "month"
        if key not in self._cache:
            months = self.days.astype("datetime64[M]")
            years_as_months = self.days.astype("datetime64[Y]").astype("datetime64[M]")
            m = (months - years_as_months).astype("int64") + 1
            self._cache[key] = m.astype("uint8")
        return self._cache[key]

    @property
    def month_key(self) -> np.ndarray:
        key = "month_key"
        if key not in self._cache:
            mk = (self.year.astype("int64") * 12 + (self.month.astype("int64") - 1)).astype("int64")
            self._cache[key] = mk.astype("int64")
        return self._cache[key]

    @property
    def quarter(self) -> np.ndarray:
        key = "quarter"
        if key not in self._cache:
            q = ((self.month.astype("int64") - 1) // 3 + 1).astype("uint8")
            self._cache[key] = q
        return self._cache[key]

    @property
    def semester(self) -> np.ndarray:
        key = "semester"
        if key not in self._cache:
            s = ((self.month.astype("int64") - 1) // 6 + 1).astype("uint8")
            self._cache[key] = s
        return self._cache[key]

    @property
    def week(self) -> np.ndarray:
        key = "iso_week"
        if key not in self._cache:
            weeks = []
            for d64 in self.days:
                s = np.datetime_as_string(d64, unit="D")
                py = dt.date.fromisoformat(s)
                weeks.append(py.isocalendar().week)
            self._cache[key] = np.array(weeks, dtype="uint8")
        return self._cache[key]