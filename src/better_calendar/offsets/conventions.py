"""ISDA-style roll conventions (§7.1).

``adjust(d, Roll.MODIFIED_FOLLOWING)`` is the canonical date normaliser: it is what you
reach for when a contractual date lands on a weekend or a holiday and has to be moved to
a real business day without leaving the month.
"""

from __future__ import annotations

from typing import Union

from better_calendar._compat import StrEnum
from better_calendar.core.errors import BetterCalendarError

__all__ = ["Roll", "RollLike"]


class Roll(StrEnum):
    """How to move a date that is not a business day.

    Members:
        NONE: Leave the date unadjusted.
        FOLLOWING: Move forward to the next business day (``"F"``).
        PRECEDING: Move back to the previous business day (``"P"``).
        MODIFIED_FOLLOWING: Forward, unless that leaves the month — then back (``"MF"``).
        MODIFIED_PRECEDING: Back, unless that leaves the month — then forward (``"MP"``).
        NEAREST: Whichever is closer; ties go forward (``"N"``).
        RAISE: Raise :class:`~better_calendar.core.errors.NotABusinessDayError`.

    Examples:
        >>> Roll.parse("mf")
        <Roll.MODIFIED_FOLLOWING: 'modified_following'>
        >>> Roll.parse(Roll.NEAREST)
        <Roll.NEAREST: 'nearest'>
    """

    NONE = "none"
    FOLLOWING = "following"
    PRECEDING = "preceding"
    MODIFIED_FOLLOWING = "modified_following"
    MODIFIED_PRECEDING = "modified_preceding"
    NEAREST = "nearest"
    RAISE = "raise"

    @classmethod
    def parse(cls, value: RollLike) -> Roll:
        """Coerce a roll convention from its member, full name, or short alias.

        Args:
            value: A :class:`Roll`, a full name (``"modified_following"``), or a short
                ISDA alias (``"MF"``). Matching is case-insensitive.

        Returns:
            The corresponding member.

        Raises:
            BetterCalendarError: If the value names no known convention.

        Examples:
            >>> Roll.parse("F") is Roll.FOLLOWING
            True
            >>> Roll.parse("Modified_Preceding") is Roll.MODIFIED_PRECEDING
            True
        """
        if isinstance(value, Roll):
            return value
        if isinstance(value, str):
            key = value.strip().lower()
            if key in _SHORT_ALIASES:
                return _SHORT_ALIASES[key]
            for member in cls:
                if member.value == key:
                    return member
        raise BetterCalendarError(
            f"Unknown roll convention {value!r}. Use a Roll member, a full name "
            f"({', '.join(m.value for m in cls)}), or a short alias "
            f"({', '.join(sorted(_SHORT_ALIASES))})."
        )


#: Short ISDA aliases, accepted case-insensitively at every API boundary.
_SHORT_ALIASES = {
    "f": Roll.FOLLOWING,
    "p": Roll.PRECEDING,
    "mf": Roll.MODIFIED_FOLLOWING,
    "mp": Roll.MODIFIED_PRECEDING,
    "n": Roll.NEAREST,
}

RollLike = Union[Roll, str]
