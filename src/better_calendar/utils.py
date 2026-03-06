import re
import numpy as np
import datetime as dt
from typing import Union, Literal, Any

PandasTimestamp = Any
DateLike = Union[dt.date, dt.datetime, str, np.datetime64, PandasTimestamp, Any]
OutputType = Literal["date", "numpy", "datetime", "pandas", "str"]  # str is for custom strftime formats (e.g. "%Y-%m-%d")

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

def _to_internal_date(x: DateLike, *, input_format: str = "%d-%m-%Y") -> np.datetime64:
    """
    Convert various date-like inputs to internal np.datetime64[D] format.

    Supported input types :
        - np.datetime64 (will be converted to D precision)
        - datetime.date and datetime.datetime (time part ignored)
        - str (parsed using input_format)
        - pandas.Timestamp (if installed, time part ignored)

    Parameters
    ----------
    x: DateLike
        The input date to convert.
    input_format: str, default "%d-%m-%Y"
        The strftime format to use when parsing string inputs.
        Examples: "%d-%m-%Y" for "31-01-2025", "%Y-%m-%d" for "2025-01-31".

    Returns
    -------
    np.datetime64
        The corresponding date in np.datetime64[D] format.
    """
    if isinstance(x, np.datetime64):
        return x.astype("datetime64[D]")
    
    if isinstance(x, dt.datetime):
        return np.datetime64(x.date(), "D")
    
    if isinstance(x, dt.date):
        return np.datetime64(x, "D")
    
    if isinstance(x, str):
        try:
            parsed_date = dt.datetime.strptime(x.strip(), input_format).date()
            return np.datetime64(parsed_date, "D")
        except ValueError as e:
            raise ValueError(
                f"Cannot parse date string {x!r} with format {input_format!r}. "
                f"Original error: {e}"
            ) from e
    
    # Try pandas.Timestamp
    try:
        import pandas as pd
        if isinstance(x, pd.Timestamp):
            return np.datetime64(x.date(), "D")
    except ImportError:
        pass
    
    # Fallback: try to_pydatetime method
    if hasattr(x, "to_pydatetime"):
        try:
            py = x.to_pydatetime()
            if isinstance(py, dt.datetime):
                return np.datetime64(py.date(), "D")
        except Exception:
            pass
    
    raise ValueError(f"Unsupported date type: {type(x).__name__}. Expected date-like object.")

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

def _from_internal_date(d64: np.datetime64, output: OutputType):
    """
    Convert internal date in np.datetime64[D] format to the desired output format.

    Parameters
    ----------
    d64: np.datetime64
        The input date in np.datetime64[D] format.
    output: OutputType
        The desired output format: "date", "numpy", "datetime", "pandas", or a strftime format string (e.g. "%Y-%m-%d").
    """
    d64 = d64.astype("datetime64[D]")
    if output == "numpy":
        return d64
    if output == "date":
        return _d64_to_pydate(d64)
    if output == "datetime":
        return dt.datetime.combine(_d64_to_pydate(d64), dt.time())
    if output == "pandas":
        try:
            import pandas as pd
        except Exception as e:
            raise ImportError("pandas is required for output='pandas'") from e
        return pd.Timestamp(_d64_to_pydate(d64))
    
    # Si output n'est pas un des types prédéfinis, on le traite comme un format strftime
    if isinstance(output, str):
        py_date = _d64_to_pydate(d64)
        return py_date.strftime(output)
    
    raise ValueError(f"Unknown output type: {output!r}")