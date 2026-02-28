from typing import Any

CALENDAR_CODES = {
    # Trivial weekend-only calendar
    "DEFAULT": ("weekend", None),
    "WEEKEND": ("weekend", None),
    "WEEKENDS": ("weekend", None),
    "TRIVIAL": ("weekend", None),
    "NAIVE": ("weekend", None),

    # Country-based calendars (most used ones)
    "FR": ("country", "FR"),
    "DE": ("country", "DE"),
    "GB": ("country", "GB"),
    "UK": ("country", "GB"),
    "US": ("country", "US"),
    "CA": ("country", "CA"),
    "CH": ("country", "CH"),
    "IT": ("country", "IT"),
    "ES": ("country", "ES"),
    "NL": ("country", "NL"),
    "BE": ("country", "BE"),
    "JP": ("country", "JP"),

    "FRANCE" : ("country", "FR"),
    "GERMANY" : ("country", "DE"),
    "UNITED_KINGDOM" : ("country", "GB"),
    "UNITED_STATES" : ("country", "US"),
    "CANADA" : ("country", "CA"),
    "SWITZERLAND" : ("country", "CH"),
    "ITALY" : ("country", "IT"),
    "SPAIN" : ("country", "ES"),
    "NETHERLANDS" : ("country", "NL"),
    "BELGIUM" : ("country", "BE"),
    "JAPAN" : ("country", "JP"),

    # Exchange-based calendars
    "XPAR": ("exchange", "XPAR"),
    "PARIS": ("exchange", "XPAR"),
    "EURONEXT_PARIS": ("exchange", "XPAR"),

    "XNYS": ("exchange", "XNYS"),
    "NYSE": ("exchange", "XNYS"),
    "NASDAQ": ("exchange", "XNYS"),
    "NEW_YORK": ("exchange", "XNYS"),

    "XETR": ("exchange", "XETR"),
    "XETRA": ("exchange", "XETR"),
    "FRANKFURT": ("exchange", "XETR"),

    "XTSE": ("exchange", "XTSE"),
    "TORONTO": ("exchange", "XTSE"),
    "TSE": ("exchange", "XTSE"),

    "XTYO": ("exchange", "XTYO"),
    "TOKYO": ("exchange", "XTYO"),

    "XHKG": ("exchange", "XHKG"),
    "HONG_KONG": ("exchange", "XHKG"),

    # QuantLib calendars
    "EUR": ("quantlib", "TARGET"),
    "ESTR": ("quantlib", "TARGET"),
    "ESTER": ("quantlib", "TARGET"),
    "€STR": ("quantlib", "TARGET"),
    "€STER": ("quantlib", "TARGET"),
    "ESTRON INDEX": ("quantlib", "TARGET"),
    "ESTR INDEX": ("quantlib", "TARGET"),
    "€STRON INDEX": ("quantlib", "TARGET"),
    "ESTRON": ("quantlib", "TARGET"),

    "SOFR": ("quantlib", "US_GOVIES"),
    "SOFRRATE INDEX": ("quantlib", "US_GOVIES"),
    "SOFR INDEX": ("quantlib", "US_GOVIES"),
    "SOFRRATE": ("quantlib", "US_GOVIES"),

    "SONIA INDEX": ("quantlib", "SONIA"),
    "SONIO/N INDEX": ("quantlib", "SONIA"),
    "SONIA": ("quantlib", "SONIA"),
}

def _quantlib_mapping(calendar_code: str) -> Any:
    """
    Small helper to map calendar codes to QuantLib calendar objects and handle the import of QuantLib only when needed.

    Parameters
    ----------
    calendar_code: str
        The calendar code to map, which should be a key in the CALENDAR_CODES dictionary with provider_class "quantlib".
    
    Returns
    -------
    Any
        The corresponding QuantLib calendar object.
    """
    try:
        import QuantLib as ql
    except ImportError:
        raise ImportError("QuantLib is required to use QuantLib calendars. Please install it with 'pip install QuantLib-Python'.")
    
    if calendar_code == "TARGET":
        return ql.TARGET()
    if calendar_code == "US_GOVIES":
        return ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    if calendar_code == "SONIA":
        return ql.UnitedKingdom()