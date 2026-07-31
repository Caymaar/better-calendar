"""Python-version shims.

CLAUDE.md §1 targets Python >= 3.9 while describing the code in terms of 3.11
constructs (``enum.StrEnum``, ``typing.Self``, PEP 604 unions). This module is the
single place where that gap is bridged, so the rest of the package can be written
as if it ran on 3.11:

* :class:`StrEnum` — real ``enum.StrEnum`` on 3.11+, a ``(str, Enum)`` mixin below.
* :data:`DATACLASS_SLOTS` — ``{"slots": True}`` on 3.10+, ``{}`` below.
* ``Self`` is *not* shimmed: adding ``typing_extensions`` would mean a new runtime
  dependency (§14/§18). Methods that return their own class use a string forward
  reference instead, which behaves identically for callers and for ``mypy``.

Everything here is deliberately behaviour-preserving: on 3.11+ these are the real
stdlib objects, so no production semantics depend on the Python version.
"""

from __future__ import annotations

import enum
import sys
from typing import Any

__all__ = ["DATACLASS_SLOTS", "StrEnum"]


if sys.version_info >= (3, 11):
    StrEnum = enum.StrEnum
else:

    class StrEnum(str, enum.Enum):  # 3.9/3.10 backport of the 3.11 stdlib class
        """Backport of :class:`enum.StrEnum` for Python < 3.11.

        Members compare equal to, and format as, their string value.

        Examples:
            >>> class Colour(StrEnum):
            ...     RED = "red"
            >>> Colour.RED == "red"
            True
            >>> f"{Colour.RED}"
            'red'
        """

        __str__ = str.__str__
        __format__ = str.__format__  # type: ignore[assignment]  # matches 3.11 StrEnum

        def _generate_next_value_(  # type: ignore[override]  # matches 3.11 StrEnum
            name: str,  # enum passes the member name positionally
            start: int,
            count: int,
            last_values: list[Any],
        ) -> str:
            return name.lower()


#: Extra keyword arguments for ``@dataclass`` on hot types (§16 wants ``slots=True``).
DATACLASS_SLOTS: dict[str, Any] = {"slots": True} if sys.version_info >= (3, 10) else {}
