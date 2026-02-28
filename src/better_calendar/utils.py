import re
import numpy as np
import datetime as dt
from typing import Union, Literal, Any

PandasTimestamp = Any
DateLike = Union[dt.date, dt.datetime, str, np.datetime64, PandasTimestamp, Any]
OutputType = Literal["date", "numpy", "datetime", "str", "pandas"]

def _parse_date_str(s: str, dayfirst: bool = True) -> dt.date:
    """
    Robust parsing of date strings without ambiguity.

    Rules:
        1. Only accept strings with exactly 3 numeric _components (whatever the separators are).
        2. The year must be the only 4-digit component, and it must be either the first or the last component.
        3. If the year is first, the format is obviously Y-M-D.
        4. If not, then the format is either D-M-Y or M-D-Y, and we use the dayfirst flag to disambiguate.
        5. Reject all other formats (e.g. no-separator "20250131" or "01-02-03" with two 2-digit _components) as ambiguous by design.

    Parameters  
    ----------
    s: str
        The date string to parse.
    dayfirst: bool, default True
        When parsing strings without a clear year-first format, interpret them as day-first (French style).
    
    Returns
    -------
    dt.date
        The parsed date.
    """
    s = s.strip()
    if not s:
        raise ValueError("Empty date string.")

    if re.fullmatch(r"\d{8}", s):
        raise ValueError(
            f"Ambiguous date string without separators: {s!r}. "
            "Please use a separator and a 4-digit year (e.g. '2025-01-31' or '31/01/2025')."
        )

    parts = re.findall(r"\d+", s)
    if len(parts) != 3:
        raise ValueError(
            f"Invalid date string: {s!r}. Expected exactly 3 numeric _components "
            "(e.g. '2025-01-31' or '31/01/2025')."
        )

    a, b, c = parts
    if len(a) == 4 and len(c) != 4:
        y, m, d = int(a), int(b), int(c)
    elif len(c) == 4 and len(a) != 4:
        y = int(c)
        if dayfirst:
            d, m = int(a), int(b)
        else:
            m, d = int(a), int(b)
    elif len(a) == 4 and len(c) == 4:
        raise ValueError(
            f"Ambiguous date string (two 4-digit _components): {s!r}. "
            "Please provide an unambiguous format with a single 4-digit year."
        )
    else:
        raise ValueError(
            f"Ambiguous date string: {s!r}. "
            "A 4-digit year must be either the first or the last component."
        )

    try:
        return dt.date(y, m, d)
    except ValueError as e:
        raise ValueError(f"Invalid calendar date parsed from {s!r}: (y={y}, m={m}, d={d}).") from e


def _to_internal_date(x: DateLike, *, dayfirst: bool = True) -> np.datetime64:
    """
    Convert various date-like inputs to internal np.datetime64[D] format.

    Supported input types :
        - np.datetime64 (will be converted to D precision)
        - datetime.date and datetime.datetime (time part ignored)
        - str (parsed robustly, see _parse_date_str)
        - pandas.Timestamp (if installed, time part ignored)

    Parameters
    ----------
    x: DateLike
        The input date to convert.
    dayfirst: bool, default True
        When parsing strings without a clear year-first format, interpret them as day-first.
        Example: 
            - If True, "01-02-2020" => 1st Feb 2020
            - If False, "01-02-2020" => Jan 2nd 2020.

    Returns
    -------
    np.datetime64
        The corresponding date in np.datetime64[D] format.
    """
    if isinstance(x, np.datetime64):
        return x.astype("datetime64[D]")
    if isinstance(x, dt.datetime):
        return np.datetime64(x.date()).astype("datetime64[D]")
    if isinstance(x, dt.date):
        return np.datetime64(x).astype("datetime64[D]")
    if isinstance(x, str):
        return np.datetime64(_parse_date_str(x, dayfirst=dayfirst)).astype("datetime64[D]")
    try:
        import pandas as pd
        if isinstance(x, pd.Timestamp):
            return np.datetime64(x.to_pydatetime().date()).astype("datetime64[D]")
    except Exception:
        pass
    if hasattr(x, "to_pydatetime"):
        try:
            py = x.to_pydatetime()
            if isinstance(py, dt.datetime):
                return np.datetime64(py.date()).astype("datetime64[D]")
        except Exception:
            pass
    raise ValueError(f"Unsupported date type: {type(x)}")

def _d64_to_pydate(d64: np.datetime64) -> dt.date:
    """
    Small helper to convert np.datetime64[D] to datetime.date,.

    Parameters
    ----------
    d64: np.datetime64
        The input date in np.datetime64[D] format.
    
    Returns
    -------
    dt.date
        The corresponding datetime.date.
    """
    s = np.datetime_as_string(d64.astype("datetime64[D]"), unit="D")
    return dt.date.fromisoformat(s)

def _from_internal_date(d64: np.datetime64, output: OutputType, *, str_sep: str = "-", dayfirst: bool = True):
    """
    Convert invertal date in np.datetime64[D] format to the desired output format.

    Parameters
    ----------
    d64: np.datetime64
        The input date in np.datetime64[D] format.
    output: OutputType
        The desired output format: "date", "numpy", "datetime", "str", or "pandas".
    str_sep: str, default "-"
        If output is "str", the separator to use between year, month, and day (default is "-").
    dayfirst: bool, default True
        When output is "str", whether to use day-first format (e.g. "01-02-2020" => 1st Feb 2020).
    """
    d64 = d64.astype("datetime64[D]")
    if output == "numpy":
        return d64
    if output == "date":
        return _d64_to_pydate(d64)
    if output == "datetime":
        return dt.datetime.combine(_d64_to_pydate(d64), dt.time())
    if output == "str":
        iso = np.datetime_as_string(d64, unit="D")
        if dayfirst:
            y, m, d = iso.split("-")
            iso = f"{d}-{m}-{y}"
        if str_sep == "-":
            return iso
        return iso.replace("-", str_sep)
    if output == "pandas":
        try:
            import pandas as pd
        except Exception as e:
            raise ImportError("pandas is required for output='pandas'") from e
        return pd.Timestamp(_d64_to_pydate(d64))
    raise ValueError(f"Unknown output type: {output!r}")