import json
import numpy as np
import datetime as dt
from typing import Tuple, Tuple, Union, Iterable, Optional, List, Dict

from .utils import DateLike, OutputType
from .date_universe import DateUniverse
from .mapping import CALENDAR_CODES, _quantlib_mapping
from .utils import _to_internal_date, _from_internal_date
from .providers import ExchangeMaskBuilder, QuantLibMaskBuilder, CountryMaskBuilder, DefaultMaskBuilder


class Calendar:
    """
    Structure representing a business calendar.

    It is defined by :
        - A DateUniverse : static information about the calendar (contiguous days, weekdays, months, etc.)
        - A boolean mask of the same length as the universe, where True indicates a business day.

    Data source :
        - Exchange calendars from pandas_market_calendars (e.g. XPAR, XNY, etc.)
        - Country calendars from workalendar (e.g. FR, US, etc.)
        - QuantLib calendars (e.g. ql.UnitedStates(), ql.France(), etc.)
    """

    def __init__(self,
                 calendar_code: Union[str, Iterable[str]] = "DEFAULT",
                 start_date: DateLike = "1970-01-01",
                 end_date: DateLike = "2100-12-31",
                 *,
                 date_type: OutputType = "date",
                 multiple_calendars_mode: str = "union",
                 day_first: bool = True,
                 str_sep: str = "-"):
        """
        Parameters
        ----------
        calendar_code: str or Iterable[str], default "DEFAULT"
            The code of the calendar to build, see the documentation for the list of available codes.
            If "DEFAULT", builds a simple calendar will only weekends as non-business days.
            It also accepts an iterable of codes, in which case the resulting calendar is the union or intersection of the corresponding calendars.
        start_date: DateLike, default "1970-01-01"
            The start date of the calendar. Can be any date-like object (str, datetime, date, np.datetime64, etc.).
        end_date: DateLike, default "2100-12-31"
            The end date of the calendar. Can be any date-like object (str, datetime, date, np.datetime64, etc.).
        date_type: OutputType, default "date"
            The default output type for methods that return dates. Can be "date", "numpy", "datetime", "str", or "pandas".
        multiple_calendars_mode: str, default "union"
            If calendar_code is an iterable of codes, whether to take the "union" (a day is a business day if it's a business day in at least one calendar)
            or the "intersection" (a day is a business day if it's a business day in all calendars) of the corresponding calendars.
        day_first: bool, default True
            When output is "str", whether to use day-first format (e.g. "01-02-2020" => 1st Feb 2020).
        str_sep: str, default "-"
            When output is "str", the separator to use between year, month, and day (default is "-").
        """
        self.dayfirst = day_first
        self.str_sep = str_sep
        self.output = date_type

        self.calendar_code = calendar_code
        self.multiple_calendars_mode = multiple_calendars_mode

        self.start_date: np.datetime64 = _to_internal_date(start_date, dayfirst=day_first)
        self.end_date: np.datetime64 = _to_internal_date(end_date, dayfirst=day_first)
        
        self.universe = DateUniverse(start=self.start_date, end=self.end_date)
        self.business_mask: np.ndarray = self._create_mask()
        self.business_position: np.ndarray = np.flatnonzero(self.business_mask).astype("int64")
    
    # ---------------------------------------
    # |            Helper methods           |
    # ---------------------------------------

    def _create_mask(self) -> np.ndarray:
        """
        Create the business day mask for this calendar based on the calendar code and the universe.

        Returns
        -------
        np.ndarray
            A boolean array of the same length as the universe, where True indicates a business day.
        """
        if isinstance(self.calendar_code, str):
            codes = [self.calendar_code]
        else:
            codes = list(self.calendar_code)

        if len(codes) == 0:
            raise ValueError("At least one calendar code must be provided.")
        
        masks = []
        final_mask = None
        for code in codes:

            if not code in CALENDAR_CODES:
                raise ValueError(f"Unknown calendar code: {code}")
            
            provider_class, provider_code = CALENDAR_CODES[code]
            if provider_class == "exchange":
                builder = ExchangeMaskBuilder(exchange_code=provider_code)
            elif provider_class == "quantlib":
                builder = QuantLibMaskBuilder(ql_calendar=_quantlib_mapping(provider_code))
            elif provider_class == "country":
                builder = CountryMaskBuilder(country_code=provider_code)
            elif provider_class == "weekend":
                builder = DefaultMaskBuilder()
            else:
                raise ValueError(f"Unknown provider class: {provider_class}")
            
            mask = builder.build_mask(self.universe)
            masks.append(mask)
        
        if self.multiple_calendars_mode == "union":
            final_mask = np.logical_or.reduce(masks)
        elif self.multiple_calendars_mode == "intersection":
            final_mask = np.logical_and.reduce(masks)
        else:
            raise ValueError(f"Unknown multiple_calendars_mode: {self.multiple_calendars_mode}, please choose 'union' or 'intersection'.")

        return final_mask
    
    def _range_indices(self, start: Optional[DateLike], end: Optional[DateLike]) -> tuple[int, int]:
        """
        Give the start and end indices corresponding to the given start and end dates.

        Parameters
        ----------
        start: Optional[DateLike]
            The start date. If None, uses the calendar start date.
        end: Optional[DateLike]
            The end date. If None, uses the calendar end date.

        Returns
        -------
        tuple[int, int]
            The start and end indices corresponding to the given start and end dates.
        """
        s = self.universe.start64 if start is None else _to_internal_date(start, dayfirst=self.dayfirst)
        e = self.universe.end64 if end is None else _to_internal_date(end, dayfirst=self.dayfirst)
        i0 = self.universe.locate(s)
        i1 = self.universe.locate(e)
        if i1 < i0:
            raise ValueError("end < start")
        return i0, i1

    def _select_in_groups(self, pos: np.ndarray, key: np.ndarray, which: Union[str, int]) -> np.ndarray:
        """
        Select positions in pos corresponding to the first/last/all/nth occurrence of each group defined by key.

        Parameters
        ----------
        pos: np.ndarray
            The positions to select from.
        key: np.ndarray
            The key defining the groups. Must be the same length as pos.
        which: str or int
            Whether to select the "first"/"last"/"all" occurrence of each group or the "nth" occurrence (input as an integer).

        Returns
        -------
        np.ndarray
            The selected positions in pos.
        """
        if pos.size == 0:
            return pos

        if which == "all":
            return pos
        
        starts = np.empty(pos.size, dtype=bool)
        starts[0] = True
        starts[1:] = key[1:] != key[:-1]
        start_idx = np.flatnonzero(starts)

        if which == "first":
            return pos[start_idx]

        end_idx = np.r_[start_idx[1:] - 1, pos.size - 1]

        if which == "last":
            return pos[end_idx]

        if isinstance(which, int) and which >= 1:
            nth = start_idx + (which - 1)
            valid = nth <= end_idx
            return pos[nth[valid]]

        raise ValueError("which must be 'first', 'last', 'all' or an int >= 1")

    def _inclusive_flags(self, inclusive: str) -> Tuple[bool, bool]:
        """
        Convert the inclusive string to boolean flags for start and end inclusion.

        Parameters
        ----------
        inclusive: str
            Whether to include the start and/or end date in the count. Can be "both", "neither", "start", or "end".

        Returns
        -------
        Tuple[bool, bool]
            A tuple of two booleans indicating whether to include the start and end date in the count.
        """
        inc = inclusive.lower()
        if inc == "both":
            return True, True
        if inc == "left":
            return True, False
        if inc == "right":
            return False, True
        if inc == "none":
            return False, False
        raise ValueError("inclusive must be one of: 'both', 'left', 'right', 'none'")

    # ---------------------------------------
    # |          Public API methods         |
    # ---------------------------------------

    # --------------------------------
    # 0. Override an existing calendar
    # --------------------------------

    def override(self,
                 new_business_days: Optional[Iterable[DateLike]],
                 new_non_business_days: Optional[Iterable[DateLike]] = None) -> None:
        """
        Override the business days of this calendar with new business days.

        Parameters
        ----------
        new_business_days: Optional[Iterable[DateLike]]
            The new business days to use.
        new_non_business_days: Optional[Iterable[DateLike]]
            The new non-business days to use.
        """
        override_mask = np.zeros(len(self.universe), dtype=bool)

        if new_business_days is not None:
            new_business_days = [_to_internal_date(d, dayfirst=self.dayfirst) for d in new_business_days]
            for d in new_business_days:
                i = self.universe.locate(d)
                override_mask[i] = True

        if new_non_business_days is not None:
            new_non_business_days = [_to_internal_date(d, dayfirst=self.dayfirst) for d in new_non_business_days]
            for d in new_non_business_days:
                i = self.universe.locate(d)
                override_mask[i] = False

        self.business_mask = np.where(override_mask, True, self.business_mask)
        self.business_position = np.flatnonzero(self.business_mask).astype("int64")

    # ----------------------------------------
    # 1. Static information about the calendar
    # ----------------------------------------

    def __len__(self) -> int:
        """Return the number of days in the calendar."""
        return len(self.universe)
    
    def week_day(self, day: DateLike) -> int:
        """
        Return the weekday of the given date (Monday=1, ..., Sunday=7).

        Parameters
        ----------
        day: DateLike
            The input date for which to return the weekday. Can be any date-like object (str, datetime, date, np.datetime64, etc.).

        Returns
        -------
        int
            The weekday of the given date from 1 to 7.
        """
        d64 = _to_internal_date(day, dayfirst=self.dayfirst)
        i = self.universe.locate(d64)
        return self.universe.weekday[i]
    
    def week_number(self, day: DateLike) -> int:
        """
        Return the week number of the given date (1 to 53).

        Parameters
        ----------
        day: DateLike
            The input date for which to return the week number. Can be any date-like object (str, datetime, date, np.datetime64, etc.).

        Returns
        -------
        int
            The week number of the given date from 1 to 53.
        """
        d64 = _to_internal_date(day, dayfirst=self.dayfirst)
        i = self.universe.locate(d64)
        return self.universe.week[i]
    
    def quarter(self, day: DateLike) -> int:
        """
        Return the quarter of the given date (1 to 4).

        Parameters
        ----------
        day: DateLike
            The input date for which to return the quarter. Can be any date-like object (str, datetime, date, np.datetime64, etc.).

        Returns
        -------
        int
            The quarter of the given date from 1 to 4.
        """
        d64 = _to_internal_date(day, dayfirst=self.dayfirst)
        i = self.universe.locate(d64)
        return self.universe.quarter[i]
    
    def semester(self, day: DateLike) -> int:
        """
        Return the semester of the given date (1 or 2).

        Parameters
        ----------
        day: DateLike
            The input date for which to return the semester. Can be any date-like object (str, datetime, date, np.datetime64, etc.).

        Returns
        -------
        int
            The semester of the given date (1 or 2).
        """
        d64 = _to_internal_date(day, dayfirst=self.dayfirst)
        i = self.universe.locate(d64)
        return self.universe.semester[i]
    
    # ------------------------------------------------
    # 2. Basic business / non-business day information
    # ------------------------------------------------

    def is_business(self, day: DateLike) -> bool:
        """
        Return whether the given date is a business day.

        Parameters
        ----------
        day: DateLike
            The input date for which to check if it's a business day. Can be any date-like object (str, datetime, date, np.datetime64, etc.).

        Returns
        -------
        bool
            True if the given date is a business day, False otherwise.
        """
        d64 = _to_internal_date(day, dayfirst=self.dayfirst)
        i = self.universe.locate(d64)
        return bool(self.business_mask[i])
    
    def is_non_business(self, day: DateLike) -> bool:
        """
        Return whether the given date is a non-business day.

        Parameters
        ----------
        day: DateLike
            The input date for which to check if it's a non-business day. Can be any date-like object (str, datetime, date, np.datetime64, etc.).

        Returns
        -------
        bool
            True if the given date is a non-business day, False otherwise.
        """
        return not self.is_business(day)
    
    def is_weekend(self, day: DateLike) -> bool:
        """
        Return whether the given date is a weekend (Saturday or Sunday).

        Parameters
        ----------
        day: DateLike
            The input date for which to check if it's a weekend. Can be any date-like object (str, datetime, date, np.datetime64, etc.).

        Returns
        -------
        bool
            True if the given date is a weekend, False otherwise.
        """
        d64 = _to_internal_date(day, dayfirst=self.dayfirst)
        i = self.universe.locate(d64)
        return bool(self.universe.weekday[i] >= 6)
    
    def is_weekday(self, day: DateLike) -> bool:
        """
        Return whether the given date is a weekday (Monday to Friday).

        Parameters
        ----------
        day: DateLike
            The input date for which to check if it's a weekday. Can be any date-like object (str, datetime, date, np.datetime64, etc.).

        Returns
        -------
        bool
            True if the given date is a weekday, False otherwise.
        """
        return not self.is_weekend(day)
    
    def is_holiday(self, day: DateLike) -> bool:
        """
        Return whether the given date is a holiday (non-business day that is not a weekend).

        Parameters
        ----------
        day: DateLike
            The input date for which to check if it's a holiday. Can be any date-like object (str, datetime, date, np.datetime64, etc.).

        Returns
        -------
        bool
            True if the given date is a holiday, False otherwise.
        """
        return self.is_non_business(day) and not self.is_weekend(day)
    
    def business_days(self, start_date: Optional[DateLike] = None, end_date: Optional[DateLike] = None) -> List[OutputType]:
        """
        Return the list of business days between the given start and end dates.

        Parameters
        ----------
        start_date: Optional[DateLike]
            The start date of the range. If None, uses the calendar start date.
        end_date: Optional[DateLike]
            The end date of the range. If None, uses the calendar end date.

        Returns
        -------
        List[OutputType]
            The list of business days in the given range, in the output format selected at calendar construction.
        """
        start_date = self.start_date if start_date is None else _to_internal_date(start_date, dayfirst=self.dayfirst)
        end_date = self.end_date if end_date is None else _to_internal_date(end_date, dayfirst=self.dayfirst)

        i0, i1 = self._range_indices(start_date, end_date)
        pos = self.business_position
        left = np.searchsorted(pos, i0, side="left")
        right = np.searchsorted(pos, i1, side="right")
        out64 = self.universe.days[pos[left:right]]

        return [_from_internal_date(d, self.output, str_sep=self.str_sep, dayfirst=self.dayfirst) for d in out64]
    
    def non_business_days(self, start_date: Optional[DateLike] = None, end_date: Optional[DateLike] = None) -> List[OutputType]:
        """
        Return the list of non-business days between the given start and end dates.

        Parameters
        ----------
        start_date: Optional[DateLike]
            The start date of the range. If None, uses the calendar start date.
        end_date: Optional[DateLike]
            The end date of the range. If None, uses the calendar end date.

        Returns
        -------
        List[OutputType]
            The list of non-business days in the given range, in the output format selected at calendar construction.
        """
        i0, i1 = self._range_indices(start_date, end_date)
        all_pos = np.arange(i0, i1 + 1)
        bus_pos = self.business_position
        mask = np.isin(all_pos, bus_pos, assume_unique=True, invert=True)
        out64 = self.universe.days[all_pos[mask]]

        return [_from_internal_date(d, self.output, str_sep=self.str_sep, dayfirst=self.dayfirst) for d in out64]
    
    def days_between(self,
                     start_date: Optional[DateLike] = None,
                     end_date: Optional[DateLike] = None,
                     *,
                     type: str = "calendar",
                     inclusive: str = "both") -> int:
        """
        Counts the number of days between the given start and end dates, either in calendar days or business days, and with different inclusion options.

        Parameters
        ----------
        start_date: Optional[DateLike]
            The start date of the range. If None, uses the calendar start date.
        end_date: Optional[DateLike]
            The end date of the range. If None, uses the calendar end date.
        type: str, default "calendar"
            Whether to count "calendar" days or "business" days.
        inclusive: str, default "both"
            Whether to include the start and/or end date in the count. Can be "both", "neither", "start", or "end".    
        """
        if start_date is None:
            start_date = self.start_date
        if end_date is None:
            end_date = self.end_date

        d1 = _to_internal_date(start_date, dayfirst=self.dayfirst)
        d2 = _to_internal_date(end_date, dayfirst=self.dayfirst)
        i1 = self.universe.locate(d1)
        i2 = self.universe.locate(d2)

        if i2 < i1:
            raise ValueError("Please ensure that end_date >= start_date.")

        inc_start, inc_end = self._inclusive_flags(inclusive)

        if type == "calendar":
            cnt = (i2 - i1 + 1)
            if not inc_start:
                cnt -= 1
            if not inc_end:
                cnt -= 1
            return max(cnt, 0)

        if type == "business":
            bpos = self.business_position
            left_side = "left" if inc_start else "right"
            right_side = "right" if inc_end else "left"

            left = np.searchsorted(bpos, i1, side=left_side)
            right = np.searchsorted(bpos, i2, side=right_side)
            return int(max(right - left, 0))

        raise ValueError("type must be 'calendar' or 'business'")

    # -------------------------
    # 3. Business day offseting
    # -------------------------

    def offset_business_days(self, day: DateLike, n: int) -> OutputType:
        """
        Return the date obtained by offsetting the given date by n business days.
        The offset can be positive (forward) or negative (backward) but it is always a strict offset.

        This method uses numpy.searchsorted to achieve O(log n) complexity to be more efficient than a naive O(n) loop.

        Parameters
        ----------
        day: DateLike
            The input date to offset. Can be any date-like object (str, datetime, date, np.datetime64, etc.).
        n: int
            The number of business days to offset. Can be positive (forward) or negative (backward).

        Returns
        -------
        OutputType
            The resulting date in the wanted output format selected at calendar construction.
        """
        d64 = _to_internal_date(day, dayfirst=self.dayfirst)
        if d64 < self.start_date or d64 > self.end_date:
            raise ValueError(f"Date {day} is outside the calendar range [{self.start_date}, {self.end_date}].")
        
        i = self.universe.locate(d64)
        return_day = None

        if n == 0:
            return_day = d64
        elif n > 0:
            k = np.searchsorted(self.business_position, i, side="right") + (n - 1)
            if k >= len(self.business_position):
                raise ValueError(f"Offset of {n} business days from {day} goes beyond the calendar end date {self.end_date}.")
            return_day = self.universe.days[self.business_position[k]]
        else:
            k = np.searchsorted(self.business_position, i, side="left") + n
            if k < 0:
                raise ValueError(f"Offset of {n} business days from {day} goes beyond the calendar start date {self.start_date}.")
            return_day = self.universe.days[self.business_position[k]]

        return _from_internal_date(return_day, self.output, str_sep=self.str_sep, dayfirst=self.dayfirst)
        
    def next_business_day(self, day: DateLike) -> OutputType:
        """
        Return the next business day after the given date.

        Parameters
        ----------
        day: DateLike
            The input date for which to find the next business day. Can be any date-like object (str, datetime, date, np.datetime64, etc.).

        Returns
        -------
        OutputType
            The next business day in the output format selected at calendar construction.
        """
        return self.offset_business_days(day, 1)
    
    def previous_business_day(self, day: DateLike) -> OutputType:
        """
        Return the previous business day before the given date.

        Parameters
        ----------
        day: DateLike
            The input date for which to find the previous business day. Can be any date-like object (str, datetime, date, np.datetime64, etc.).

        Returns
        -------
        OutputType
            The previous business day in the output format selected at calendar construction.
        """
        return self.offset_business_days(day, -1)

    # -------------------------------------------------
    # 4. Scheduling : business-based and calendar-based
    # -------------------------------------------------

    def schedule_business(self,
                          *,
                          frequency: str,
                          which: Union[str, int] = "first",
                          start_date: Optional[DateLike] = None,
                          end_date: Optional[DateLike] = None) -> List[OutputType]:
        """
        Create a schedule (= grid/list of dates) based on business days.
        Examples :
            - schedule_business(frequency="M", which="last") => last business day of each month
            - schedule_business(frequency="Q", which=2) => 2nd business day of each quarter
            - schedule_business(frequency="W", which="last") => last business days of each week
            - schedule_business(frequency="Y", which="first", start_date="2010-01-01", end_date="2020-12-31") => first business day of each year between 2010 and 2020.

        Parameters
        ----------
        frequency: str
            The frequency of the schedule, "W" for weekly, "M" for monthly, "Q" for quarterly, "S" for semesterly, "Y" for yearly.
        which: str, default "first"
            Wether to take the "first"/"last"/"all" business day(s) of the period defined by the frequency or the "nth" business day of the period (input as an integer).
        start_date: Optional[DateLike]
            The start date of the schedule. If None, uses the calendar start date.
        end_date: Optional[DateLike]
            The end date of the schedule. If None, uses the calendar end date.

        Returns
        -------
        List[OutputType]
            The list of scheduled dates in the output format selected at calendar construction.
        """
        i0, i1 = self._range_indices(start_date, end_date)

        bpos = self.business_position
        left = np.searchsorted(bpos, i0, side="left")
        right = np.searchsorted(bpos, i1, side="right")
        pos = bpos[left:right]

        if pos.size == 0:
            return []

        if frequency == "M" or frequency == "month" or frequency == "Month" or frequency == "MONTH":
            key = self.universe.month_key[pos]
        elif frequency == "Q" or frequency == "quarter" or frequency == "Quarter" or frequency == "QUARTER":
            key = (self.universe.year[pos].astype("int64") * 10 + self.universe.quarter[pos].astype("int64"))
        elif frequency == "S" or frequency == "semester" or frequency == "Semester" or frequency == "SEMESTER":
            key = (self.universe.year[pos].astype("int64") * 10 + self.universe.semester[pos].astype("int64"))
        elif frequency == "W" or frequency == "week" or frequency =="Week" or frequency == "WEEK":
            key = (self.universe.iso_year[pos].astype("int64") * 100 + self.universe.week[pos].astype("int64"))
        elif frequency == "Y" or frequency == "year" or frequency == "Year" or frequency == "YEAR":
            key = self.universe.year[pos]
        else:
            raise ValueError("freq must be 'M', 'W', 'Q', 'S' or 'Y' (or their lowercase/uppercase variants)")

        sel = self._select_in_groups(pos, key, which)
        out64 = self.universe.days[sel]

        return [_from_internal_date(d, self.output, str_sep=self.str_sep, dayfirst=self.dayfirst) for d in out64]

    def schedule_calendar(self,
                          *,
                          frequency: str,
                          week_day: Optional[int] = 1,
                          which: Union[str, int] = "first",
                          start_date: Optional[DateLike] = None,
                          end_date: Optional[DateLike] = None) -> List[OutputType]:
        """
        Create a schedule (= grid/list of dates) based on calendar days.
        Examples :
            - schedule_calendar(frequency="W", week_day=5, which="last") => last Friday of each week
            - schedule_calendar(frequency="M", week_day=1, which=2) => 2nd Monday of each month
            - schedule_calendar(frequency="Q", week_day=3, which="all") => all Wednesdays of each quarter
            - schedule_calendar(frequency="Y", week_day=7, which="first", start_date="2010-01-01", end_date="2020-12-31") => first Sunday of each year between 2010 and 2020.
        
        Parameters
        ----------
        frequency: str
            The frequency of the schedule, "W" for weekly, "M" for monthly, "Q" for quarterly, "S" for semesterly, "Y" for yearly.
        week_day: int, default 1
            The weekday number (1-7) to schedule. Default is Monday (1).
        which: str, default "first"
            Wether to take the "first"/"last"/"all" day(s) of the period defined by the frequency or the "nth" day of the period (input as an integer).
        start_date: Optional[DateLike]
            The start date of the schedule. If None, uses the calendar start date.
        end_date: Optional[DateLike]
            The end date of the schedule. If None, uses the calendar end date.

        Returns
        -------
        List[OutputType]
            The list of scheduled dates in the output format selected at calendar construction.
        """
        i0, i1 = self._range_indices(start_date, end_date)
        pos = np.arange(i0, i1 + 1, dtype="int64")

        if week_day is not None:
            pos = pos[self.universe.weekday[pos] == week_day]

        if pos.size == 0:
            return []

        if which != "all":
            if frequency == "M" or frequency == "month" or frequency == "Month" or frequency == "MONTH":
                key = self.universe.month_key[pos]
            elif frequency == "Q" or frequency == "quarter" or frequency == "Quarter" or frequency == "QUARTER":
                key = (self.universe.year[pos].astype("int64") * 10 + self.universe.quarter[pos].astype("int64"))
            elif frequency == "S" or frequency == "semester" or frequency == "Semester" or frequency == "SEMESTER":
                key = (self.universe.year[pos].astype("int64") * 10 + self.universe.semester[pos].astype("int64"))
            elif frequency == "W" or frequency == "week" or frequency =="Week" or frequency == "WEEK":
                key = (self.universe.iso_year[pos].astype("int64") * 100 + self.universe.week[pos].astype("int64"))
            elif frequency == "Y" or frequency == "year" or frequency == "Year" or frequency == "YEAR":
                key = self.universe.year[pos]
            else:
                raise ValueError("freq must be 'M', 'W', 'Q', 'S' or 'Y' (or their lowercase/uppercase variants)")

            pos = self._select_in_groups(pos, key, which)

        return [_from_internal_date(d, self.output, str_sep=self.str_sep, dayfirst=self.dayfirst) for d in self.universe.days[pos]]
    
    # -------------------------------------------------
    # 5. Visualization, information and export methods
    # -------------------------------------------------

    def summary(self) -> None:
        """
        Print a summary of the calendar, including the calendar code, the date range, the number of business days, and the percentage of business days.
        """
        total_days = len(self.universe)
        business_days = self.business_mask.sum()
        non_business_days = total_days - business_days
        business_percentage = business_days / total_days * 100

        print(f"Calendar code: {self.calendar_code}")
        if len(self.calendar_code) > 1:
            print(f"Multiple calendars aggregation : {self.multiple_calendars_mode}")
        print(f"Date range: {self.start_date} to {self.end_date}")
        print(f"Total days: {total_days}")
        print(f"Business days: {business_days} ({business_percentage:.2f}%)")
        print(f"Non-business days: {non_business_days} ({100 - business_percentage:.2f}%)")

    def export(self, file_path: str, start_date: Optional[DateLike] = None, end_date: Optional[DateLike] = None) -> None:
        """
        Export calendar information to a file.
        
        Accepted file formats:
            - CSV (.csv)
            - JSON (.json)
            - Excel (.xlsx)
            - Parquet (.parquet)

        Parameters
        ----------
        file_path: str
            The path of the file to export to, must end with the appropriate extension (.csv, .json, .xlsx).
        start_date: Optional[DateLike]
            The start date of the range to export. If None, uses the calendar start date.
        end_date: Optional[DateLike]
            The end date of the range to export. If None, uses the calendar end date.
        """
        if not file_path.endswith((".csv", ".json", ".xlsx", ".parquet")):
            raise ValueError("file_path must end with .csv, .json, .xlsx or .parquet")
        
        i0, i1 = self._range_indices(start_date, end_date)
        data = {
            "date": self.universe.days[i0:i1 + 1],
            "is_business_day": self.business_mask[i0:i1 + 1],
            "weekday": self.universe.weekday[i0:i1 + 1],
            "week": self.universe.week[i0:i1 + 1],
            "month": self.universe.month[i0:i1 + 1],
            "quarter": self.universe.quarter[i0:i1 + 1],
            "semester": self.universe.semester[i0:i1 + 1],
        }
        if file_path.endswith(".json"):
            data["date"] = [str(d) for d in data["date"]]
            with open(file_path, "w") as f:
                json.dump(data, f, indent=4)
        else:
            try:
                import pandas as pd
            except ImportError:
                raise ImportError("Pandas is required to export to CSV, Excel or Parquet. Please install it with 'pip install pandas'.")
            df = pd.DataFrame(data)
            if file_path.endswith(".csv"):
                df.to_csv(file_path, index=False)
            elif file_path.endswith(".xlsx"):
                df.to_excel(file_path, index=False)
            elif file_path.endswith(".parquet"):
                df.to_parquet(file_path, index=False)
        
            
    def plot(self, start_date: Optional[DateLike] = None, end_date: Optional[DateLike] = None) -> None:
        """
        Print a visual representation of the calendar for the given date range.

        Parameters
        ----------
        start_date: Optional[DateLike]
            The start date of the range to show. If None, uses the calendar start date.
        end_date: Optional[DateLike]
            The end date of the range to show. If None, uses the calendar end date.
        """
        try:
            import matplotlib.pyplot as plt
            from matplotlib.patches import Rectangle
        except Exception as e:
            raise ImportError(
                "matplotlib is required for Calendar.show(). "
                "Install it with: pip install matplotlib"
            ) from e

        def _days_in_month(year: int, month: int) -> int:
            if month == 12:
                d0 = dt.date(year, 12, 1)
                d1 = dt.date(year + 1, 1, 1)
            else:
                d0 = dt.date(year, month, 1)
                d1 = dt.date(year, month + 1, 1)
            return (d1 - d0).days


        def _plot_month_waffle(ax, year: int, month: int, flags: np.ndarray, title: str, Rectangle):

            ax.set_aspect("equal")
            ax.set_xlim(0, 7)
            ax.set_ylim(0, 6)
            ax.invert_yaxis()
            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_title(title, fontsize=9, pad=2)

            offset = dt.date(year, month, 1).weekday()
            ndays = int(flags.shape[0])

            edge = (0.75, 0.75, 0.75)
            lw = 0.5

            for d in range(1, ndays + 1):
                v = int(flags[d - 1])
                if v == -1:
                    continue

                k = offset + (d - 1)
                row = k // 7
                col = k % 7
                if row >= 6:
                    continue

                face = "white" if v == 1 else "red"
                rect = Rectangle((col, row), 1.0, 1.0, facecolor=face, edgecolor=edge, linewidth=lw)
                ax.add_patch(rect)

            for spine in ax.spines.values():
                spine.set_visible(False)

        i0, i1 = self._range_indices(start_date, end_date)
        years = self.universe.year[i0:i1 + 1]
        months = self.universe.month[i0:i1 + 1]
        days64 = self.universe.days[i0:i1 + 1]
        mask = self.business_mask[i0:i1 + 1]

        uniq_years = np.unique(years)
        n_years = int(uniq_years.size)

        if n_years > 25:
            raise ValueError(
                f"Too many years to display ({n_years}). "
                "Please narrow start_date/end_date for show()."
            )

        ym_to_flags: Dict[Tuple[int, int], np.ndarray] = {}
        for y in uniq_years:
            y = int(y)
            for m in range(1, 13):
                ndays = _days_in_month(y, m)
                ym_to_flags[(y, m)] = np.full(ndays, -1, dtype=np.int8)

        d_in_month = (days64 - days64.astype("datetime64[M]")).astype("timedelta64[D]").astype("int64") + 1
        for j in range(days64.shape[0]):
            y = int(years[j])
            m = int(months[j])
            d = int(d_in_month[j])
            ym_to_flags[(y, m)][d - 1] = 1 if bool(mask[j]) else 0

        fig_w = 12 * 1.1
        fig_h = n_years * 1.6
        fig, axes = plt.subplots(
            nrows=n_years,
            ncols=12,
            figsize=(fig_w, fig_h),
            constrained_layout=True,
        )

        if n_years == 1:
            axes = np.expand_dims(axes, axis=0)

        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        for r, y in enumerate(uniq_years):
            y = int(y)
            axes[r, 0].set_ylabel(str(y), rotation=0, labelpad=30, va="center", fontsize=11)

            for c, m in enumerate(range(1, 13)):
                ax = axes[r, c]
                flags = ym_to_flags[(y, m)]
                _plot_month_waffle(ax, y, m, flags, month_names[c], Rectangle)

        plt.show()