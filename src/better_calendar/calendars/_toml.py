"""Reading the flat string tables this package ships as TOML.

``tomllib`` only entered the standard library in 3.11, and CLAUDE.md §14/§18 forbid
adding a runtime dependency (which ``tomli`` would be) without asking. The data files we
read — :mod:`aliases.toml`, and later the spot-lag table — are flat tables of scalars, so
below 3.11 a strict reader for exactly that subset does the job without changing the file
format or the on-disk source of truth.

On 3.11+ the real ``tomllib`` is used, so the shipped files are always validated by a
conforming parser in CI.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Union

from better_calendar.core.errors import BetterCalendarError

__all__ = ["read_table"]

Scalar = Union[str, int, bool]

_SECTION_RE = re.compile(r"^\[(?P<name>[A-Za-z0-9_.-]+)\]$")
_ENTRY_RE = re.compile(
    r"^(?P<key>[A-Za-z0-9_-]+|\"[^\"]+\")\s*=\s*"
    r"(?P<value>\"[^\"]*\"|true|false|-?\d+)$"
)


def _parse_minimal(text: str, source: Path) -> dict[str, dict[str, Scalar]]:
    """Parse the flat ``[section] key = scalar`` subset, rejecting anything richer."""
    tables: dict[str, dict[str, Scalar]] = {}
    current: dict[str, Scalar] = {}
    tables[""] = current
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        section = _SECTION_RE.match(line)
        if section is not None:
            current = tables.setdefault(section["name"], {})
            continue
        entry = _ENTRY_RE.match(line)
        if entry is None:
            raise BetterCalendarError(
                f"{source}:{number}: cannot parse {raw.strip()!r}. This file is read by "
                f"a deliberately minimal TOML reader on Python < 3.11, which supports "
                f"only '[section]' headers and 'key = scalar' entries."
            )
        key = entry["key"].strip('"')
        value = entry["value"]
        if value.startswith('"'):
            current[key] = value[1:-1]
        elif value in ("true", "false"):
            current[key] = value == "true"
        else:
            current[key] = int(value)
    return tables


def read_table(path: Path, section: str) -> dict[str, Scalar]:
    """Read one flat table out of a shipped TOML file.

    Args:
        path: The file to read.
        section: The table name, for example ``"aliases"``.

    Returns:
        The section's key/value pairs, or an empty dict if the section is absent.

    Raises:
        BetterCalendarError: If the file is missing or not parseable.

    Examples:
        >>> from pathlib import Path
        >>> table = read_table(Path(__file__).with_name("aliases.toml"), "aliases")
        >>> table["NYSE"]
        'XNYS'
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BetterCalendarError(
            f"Cannot read {path}: {exc}. The file ships inside the wheel; a missing one "
            f"means a broken install — reinstall better-calendar."
        ) from exc

    if sys.version_info >= (3, 11):
        import tomllib

        try:
            parsed = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise BetterCalendarError(f"Cannot parse {path}: {exc}.") from exc
        table = parsed.get(section, {})
    else:
        table = _parse_minimal(text, path).get(section, {})
    return dict(table)
