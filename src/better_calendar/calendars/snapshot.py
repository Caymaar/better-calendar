"""Reading and writing the committed holiday snapshots (§5.5).

Why snapshots exist. If ``bcal.get("XNYS")`` asked ``exchange-calendars`` at query time,
then a ``pip install --upgrade`` could move a settlement date with nobody deciding to.
That is what invariant I8 forbids. So the data is materialised once, committed, shipped
inside the wheel, and read from disk at runtime — the providers are not even installed on
the machines that consume this library.

Why plain text. The whole point of the weekly drift job (§5.5) is that an upstream change
arrives as a **reviewable** pull request. A Parquet or ``.npz`` blob turns that review
into "binary file changed"; one ISO date per line turns it into ``+2027-05-31`` /
``-2027-06-01``, which is the thing a human actually needs to see. Reading costs about
0.06 ms per calendar, and calendars load lazily, so the format costs nothing at runtime.
It also keeps ``numpy`` as the only dependency, which Parquet would not (§14, §18).

Layout::

    data/
    ├── manifest.json          provenance: provider, upstream version, bounds,
    │                          weekmask, tz, holiday count, sha256 per calendar
    └── calendars/
        ├── XNYS.csv           one ISO date per line, sorted, ascending
        ├── country-FR.csv
        └── fin-TARGET2.csv

The manifest is the index: nothing is loaded, or even looked for, unless it names it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, time
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from better_calendar._compat import DATACLASS_SLOTS
from better_calendar.core.errors import BetterCalendarError, UnknownCalendarError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from better_calendar.calendars.base import Calendar

__all__ = [
    "DATA_DIR",
    "MANIFEST_NAME",
    "SNAPSHOT_FORMAT",
    "SnapshotEntry",
    "load_calendar",
    "load_manifest",
    "snapshot_ids",
    "write_snapshot",
]

#: Where the committed snapshot lives inside the package.
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MANIFEST_NAME = "manifest.json"
CALENDARS_DIRNAME = "calendars"

#: Bumped only when the on-disk layout changes incompatibly.
SNAPSHOT_FORMAT = 1


@dataclass(frozen=True, **DATACLASS_SLOTS)
class SnapshotEntry:
    """One calendar's row in the manifest.

    Attributes:
        identifier: The canonical calendar id.
        provider: Which provider materialised it.
        provider_version: The upstream version it was materialised from (I8).
        upstream: The provider-specific key, kept so a regeneration is reproducible.
        bounds: The effective horizon, which may be narrower than the one requested.
        weekmask: Canonical weekmask string.
        tz: IANA timezone, or ``None``.
        session_start: Local time a calendar day begins.
        holidays: How many holidays the file holds.
        sha256: Digest of the file's bytes; this is what the drift check compares.

    Examples:
        >>> entry = SnapshotEntry(
        ...     "XNYS", "exchange_calendars", "4.5.6", "XNYS",
        ...     (date(1970, 1, 1), date(2050, 12, 31)),
        ...     "Mon Tue Wed Thu Fri", "America/New_York", time(0, 0), 1227, "abc",
        ... )
        >>> entry.filename
        'XNYS.csv'
    """

    identifier: str
    provider: str
    provider_version: str
    upstream: str
    bounds: tuple[date, date]
    weekmask: str
    tz: str | None
    session_start: time
    holidays: int
    sha256: str

    @property
    def filename(self) -> str:
        """The calendar's file name, with ``:`` replaced so Windows can hold it."""
        return f"{self.identifier.replace(':', '-').replace('/', '_')}.csv"

    def to_json(self) -> dict[str, Any]:
        """Serialise for the manifest.

        Returns:
            A JSON-ready dict with stable key order.
        """
        return {
            "provider": self.provider,
            "provider_version": self.provider_version,
            "upstream": self.upstream,
            "bounds": [self.bounds[0].isoformat(), self.bounds[1].isoformat()],
            "weekmask": self.weekmask,
            "tz": self.tz,
            "session_start": self.session_start.isoformat(),
            "holidays": self.holidays,
            "sha256": self.sha256,
        }

    @classmethod
    def from_json(cls, identifier: str, payload: dict[str, Any]) -> SnapshotEntry:
        """Rebuild an entry from its manifest row.

        Args:
            identifier: The calendar id this row is keyed by.
            payload: The row.

        Returns:
            The parsed entry.
        """
        first, last = payload["bounds"]
        hour, minute, second = (int(part) for part in payload["session_start"].split(":"))
        return cls(
            identifier=identifier,
            provider=payload["provider"],
            provider_version=payload["provider_version"],
            upstream=payload["upstream"],
            bounds=(date.fromisoformat(first), date.fromisoformat(last)),
            weekmask=payload["weekmask"],
            tz=payload["tz"],
            session_start=time(hour, minute, second),
            holidays=int(payload["holidays"]),
            sha256=payload["sha256"],
        )


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _render(holidays: Iterable[date]) -> str:
    """One ISO date per line, sorted, with a trailing newline. Nothing else.

    No header, no comments: every byte in this file has to survive a review diff, and
    provenance belongs in the manifest where it does not repeat 500 times.
    """
    days = sorted({day.isoformat() for day in holidays})
    return "".join(f"{day}\n" for day in days)


def _parse(text: str, identifier: str) -> np.ndarray[Any, Any]:
    """Parse a snapshot file into a ``datetime64[D]`` array."""
    lines = [line for line in text.splitlines() if line]
    if not lines:
        return np.empty(0, dtype="datetime64[D]")
    try:
        return np.array(lines, dtype="datetime64[D]")
    except ValueError as exc:
        raise BetterCalendarError(
            f"The snapshot for {identifier!r} is corrupt: {exc}. Regenerate it with "
            f"`better-calendar snapshot`, or reinstall better-calendar."
        ) from exc


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@lru_cache(maxsize=8)
def load_manifest(directory: Path | None = None) -> dict[str, SnapshotEntry]:
    """Read the snapshot index.

    Args:
        directory: Snapshot root; defaults to the one shipped in the package.

    Returns:
        Calendar identifier to :class:`SnapshotEntry`. Empty when no snapshot has been
        generated yet, which is a normal state and not an error.

    Raises:
        BetterCalendarError: If the manifest exists but cannot be read.

    Examples:
        >>> isinstance(load_manifest(), dict)
        True
    """
    root = directory if directory is not None else DATA_DIR
    path = root / MANIFEST_NAME
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BetterCalendarError(
            f"Cannot read the snapshot manifest at {path}: {exc}. Regenerate it with "
            f"`better-calendar snapshot`, or reinstall better-calendar."
        ) from exc
    if int(payload.get("format", 0)) != SNAPSHOT_FORMAT:
        raise BetterCalendarError(
            f"The snapshot at {root} uses format {payload.get('format')}, but this "
            f"version of better-calendar reads format {SNAPSHOT_FORMAT}. Upgrade the "
            f"library, or regenerate the snapshot with `better-calendar snapshot`."
        )
    return {
        identifier: SnapshotEntry.from_json(identifier, row)
        for identifier, row in payload.get("calendars", {}).items()
    }


def snapshot_ids(directory: Path | None = None) -> list[str]:
    """Every calendar identifier the snapshot holds.

    Args:
        directory: Snapshot root; defaults to the one shipped in the package.

    Returns:
        Sorted identifiers.

    Examples:
        >>> isinstance(snapshot_ids(), list)
        True
    """
    return sorted(load_manifest(directory))


def load_calendar(identifier: str, directory: Path | None = None) -> Calendar:
    """Build a calendar from the committed snapshot, without touching any provider.

    Args:
        identifier: The calendar id.
        directory: Snapshot root; defaults to the one shipped in the package.

    Returns:
        The calendar, with its provenance fields populated from the manifest.

    Raises:
        UnknownCalendarError: If the snapshot holds no such calendar.
        BetterCalendarError: If the file is missing or corrupt.

    Examples:
        >>> ids = snapshot_ids()
        >>> not ids or load_calendar(ids[0]).provider is not None
        True
    """
    from better_calendar.calendars.base import Calendar

    root = directory if directory is not None else DATA_DIR
    manifest = load_manifest(directory)
    entry = manifest.get(identifier)
    if entry is None:
        raise UnknownCalendarError.for_name(identifier, manifest)

    path = root / CALENDARS_DIRNAME / entry.filename
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BetterCalendarError(
            f"The manifest lists {identifier!r} but {path} is missing: {exc}. The "
            f"snapshot is inconsistent — regenerate it with `better-calendar snapshot`."
        ) from exc

    return Calendar(
        name=identifier,
        holidays=_parse(text, identifier),
        weekmask=entry.weekmask,
        bounds=entry.bounds,
        tz=entry.tz,
        session_start=entry.session_start,
        provider=entry.provider,
        provider_version=entry.provider_version,
    )


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def entry_for(calendar: Calendar, upstream: str) -> tuple[SnapshotEntry, str]:
    """Turn a materialised calendar into a manifest entry and its file contents.

    Args:
        calendar: A freshly materialised calendar.
        upstream: The provider-specific key it was built from.

    Returns:
        The entry and the text to write.

    Examples:
        >>> from better_calendar import Calendar
        >>> entry, text = entry_for(
        ...     Calendar("demo", holidays=["2026-01-01"], provider="p",
        ...              provider_version="1"), "demo"
        ... )
        >>> text.splitlines()
        ['2026-01-01']
    """
    days = calendar.holidays.astype("datetime64[D]").astype(date).tolist()
    text = _render(days if isinstance(days, list) else [days])
    entry = SnapshotEntry(
        identifier=calendar.name,
        provider=calendar.provider or "unknown",
        provider_version=calendar.provider_version or "unknown",
        upstream=upstream,
        bounds=calendar.bounds,
        weekmask=calendar.weekmask,
        tz=calendar.tz,
        session_start=calendar.session_start,
        holidays=int(calendar.holidays.size),
        sha256=_digest(text),
    )
    return entry, text


def write_snapshot(
    entries: dict[SnapshotEntry, str],
    directory: Path,
    *,
    generated: date,
    requested_bounds: tuple[date, date],
    provider_versions: dict[str, str],
) -> None:
    """Write a complete snapshot to ``directory``, replacing whatever was there.

    Stale calendar files are removed, so a calendar disappearing upstream shows up in the
    diff as a deletion rather than lingering forever.

    Args:
        entries: Manifest entries mapped to their file contents.
        directory: Snapshot root to write into.
        generated: The generation date recorded in the manifest.
        requested_bounds: The horizon that was asked for, before per-calendar clipping.
        provider_versions: Provider name to upstream version.

    Examples:
        >>> import tempfile
        >>> from better_calendar import Calendar
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     entry, text = entry_for(Calendar("demo", holidays=["2026-01-01"]), "demo")
        ...     write_snapshot(
        ...         {entry: text}, Path(tmp), generated=date(2026, 7, 31),
        ...         requested_bounds=(date(1970, 1, 1), date(2026, 12, 31)),
        ...         provider_versions={},
        ...     )
        ...     sorted(p.name for p in (Path(tmp) / "calendars").iterdir())
        ['demo.csv']
    """
    calendars_dir = directory / CALENDARS_DIRNAME
    calendars_dir.mkdir(parents=True, exist_ok=True)

    keep = set()
    for entry, text in entries.items():
        (calendars_dir / entry.filename).write_text(text, encoding="utf-8")
        keep.add(entry.filename)
    for stale in calendars_dir.iterdir():
        if stale.name not in keep and stale.suffix == ".csv":
            stale.unlink()

    payload = {
        "format": SNAPSHOT_FORMAT,
        "generated": generated.isoformat(),
        "requested_bounds": [
            requested_bounds[0].isoformat(),
            requested_bounds[1].isoformat(),
        ],
        "providers": dict(sorted(provider_versions.items())),
        "calendars": {
            entry.identifier: entry.to_json()
            for entry in sorted(entries, key=lambda item: item.identifier)
        },
    }
    (directory / MANIFEST_NAME).write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    load_manifest.cache_clear()
