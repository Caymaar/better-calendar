"""Tenor expressions such as ``3M``, ``2B``, ``1Y+2B`` (§7.3).

Grammar, case-insensitive::

    tenor := term (('+' | '-') term)*
    term  := ['-'] INT unit
    unit  := 'D' | 'B' | 'W' | 'M' | 'Y'

``D`` is calendar days, ``B`` business days (which needs a calendar), ``W`` is seven
calendar days, ``M`` and ``Y`` are calendar months and years.

**Terms are applied left to right, and the order matters.** ``"1M+2B"`` adds a month and
then moves two business days; ``"2B+1M"`` moves two business days and then adds a month.
They are not the same date in general, because a month added to a Friday and a month added
to the following Tuesday land in different weeks.

Two separate rules govern month arithmetic, and conflating them is a classic source of
off-by-one-day errors:

* **Clamping** always applies. 31 January plus one month is 28 or 29 February, because
  31 February does not exist. Nothing optional about it.
* **The end-of-month rule** is opt-in via ``eom=True``. If the date a month-or-year term
  starts from is the last day of its month, the result is the last day of *its* month.
  So 28 February 2026 plus ``1M`` is 28 March normally, and 31 March with ``eom=True``.
  The rule is checked per term, following the left-to-right application above.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from better_calendar._compat import DATACLASS_SLOTS
from better_calendar.core.errors import TenorParseError

__all__ = ["Tenor", "TenorTerm", "parse_tenor"]

#: One term: an optional sign, a count, and a unit letter.
_TERM_RE = re.compile(r"(?P<sign>[+-]?)(?P<count>\d+)(?P<unit>[DBWMY])")

UNITS = frozenset("DBWMY")


@dataclass(frozen=True, **DATACLASS_SLOTS)
class TenorTerm:
    """A single signed term of a tenor.

    Attributes:
        count: The signed number of units.
        unit: One of ``D``, ``B``, ``W``, ``M``, ``Y``.

    Examples:
        >>> parse_tenor("-3M").terms[0]
        TenorTerm(count=-3, unit='M')
    """

    count: int
    unit: str


@dataclass(frozen=True, **DATACLASS_SLOTS)
class Tenor:
    """A parsed tenor expression.

    Attributes:
        terms: The terms, in the order they must be applied.
        text: The original text, kept for error messages and round-tripping.

    Examples:
        >>> tenor = parse_tenor("1Y+2B")
        >>> tenor.terms
        (TenorTerm(count=1, unit='Y'), TenorTerm(count=2, unit='B'))
        >>> tenor.needs_calendar
        True
        >>> parse_tenor("3M").needs_calendar
        False
    """

    terms: tuple[TenorTerm, ...]
    text: str

    @property
    def needs_calendar(self) -> bool:
        """Whether any term is a business-day term, and so requires a calendar."""
        return any(term.unit == "B" for term in self.terms)

    def __str__(self) -> str:
        return self.text


@lru_cache(maxsize=512)
def parse_tenor(text: str) -> Tenor:
    """Parse a tenor expression.

    Results are memoised: tenors arrive from configuration files inside hot loops, and
    the same handful of strings is parsed over and over.

    Args:
        text: The expression, for example ``"3M"``, ``"2B"``, ``"1Y+2B"``, ``"-1M"``.

    Returns:
        The parsed :class:`Tenor`.

    Raises:
        TenorParseError: If the text does not match the grammar, naming the offending
            substring.

    Examples:
        >>> parse_tenor("6m").terms
        (TenorTerm(count=6, unit='M'),)
        >>> parse_tenor("1Y-2B").terms
        (TenorTerm(count=1, unit='Y'), TenorTerm(count=-2, unit='B'))
        >>> parse_tenor("2W")
        Tenor(terms=(TenorTerm(count=2, unit='W'),), text='2W')
        >>> parse_tenor("3Q")
        Traceback (most recent call last):
        ...
        better_calendar.core.errors.TenorParseError: Cannot parse tenor '3Q': unknown
        unit at '3Q'. Expected terms like '3M', '2B', '-1Y+2B' with units D, B, W, M or Y.
    """
    raw = text.strip()
    if not raw:
        raise TenorParseError.for_text(text, text, "the expression is empty")

    upper = raw.upper()
    terms: list[TenorTerm] = []
    position = 0

    while position < len(upper):
        operator = 1
        if terms:
            character = upper[position]
            if character not in "+-":
                raise TenorParseError.for_text(
                    text, upper[position:], "expected '+' or '-' between terms"
                )
            operator = -1 if character == "-" else 1
            position += 1

        match = _TERM_RE.match(upper, position)
        if match is None or match.start() != position:
            remainder = upper[position:] or "end of expression"
            reason = (
                "unknown unit"
                if any(character.isalpha() for character in remainder)
                else "expected a count followed by a unit"
            )
            raise TenorParseError.for_text(text, remainder, reason)

        sign = -1 if match["sign"] == "-" else 1
        terms.append(TenorTerm(operator * sign * int(match["count"]), match["unit"]))
        position = match.end()

    return Tenor(tuple(terms), raw)
