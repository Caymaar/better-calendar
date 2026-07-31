"""Command-line interface (§5.5).

    better-calendar snapshot --provider all --bounds 1970-01-01:2099-12-31
    better-calendar diff                     # non-zero exit when dates moved
    better-calendar describe rate:SOFR
    better-calendar next XNYS 2026-07-31 +5
    better-calendar list --provider quantlib

``snapshot`` is the only command that imports a provider, and it is run by a person or by
CI — never at install time and never at query time (I8).

``diff`` is the load-bearing one. It regenerates the snapshot in memory against whatever
upstream versions are installed and compares it with what is committed. A changed date
exits non-zero so the scheduled CI job fails and opens a pull request; the reviewer then
sees the moved dates line by line, because the snapshot is plain text. An upstream
version bump that changes no date is reported but does not fail, since there is nothing
for a human to decide.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from better_calendar.calendars.providers import (
    load_provider,
    provider_names,
    upstream_version,
)
from better_calendar.calendars.snapshot import (
    DATA_DIR,
    SnapshotEntry,
    entry_for,
    load_manifest,
    write_snapshot,
)
from better_calendar.core.epoch import DEFAULT_BOUNDS
from better_calendar.core.errors import BetterCalendarError

__all__ = ["main"]

_ALL = "all"


def _parse_bounds(text: str) -> tuple[date, date]:
    """Parse the ``START:END`` bounds argument."""
    first, _, last = text.partition(":")
    if not last:
        raise BetterCalendarError(
            f"Cannot parse bounds {text!r}. Use START:END, for example "
            f"{DEFAULT_BOUNDS[0].isoformat()}:{DEFAULT_BOUNDS[1].isoformat()}."
        )
    try:
        return date.fromisoformat(first), date.fromisoformat(last)
    except ValueError as exc:
        raise BetterCalendarError(f"Cannot parse bounds {text!r}: {exc}.") from exc


def _selected_providers(name: str) -> list[str]:
    if name == _ALL:
        return provider_names()
    if name not in provider_names():
        raise BetterCalendarError(
            f"Unknown provider {name!r}. Use one of {', '.join(provider_names())}, or {_ALL!r}."
        )
    return [name]


def _materialise_all(
    providers: Sequence[str],
    bounds: tuple[date, date],
    only: set[str] | None,
    *,
    report: bool,
) -> tuple[dict[SnapshotEntry, str], dict[str, str]]:
    """Run every selected provider and collect entries plus upstream versions."""
    entries: dict[SnapshotEntry, str] = {}
    versions: dict[str, str] = {}
    for name in providers:
        module = load_provider(name)
        versions[name] = upstream_version(name)
        specs = [spec for spec in module.available() if only is None or spec.identifier in only]
        if report:
            print(f"{name} ({versions[name]}): {len(specs)} calendars", file=sys.stderr)
        for spec in specs:
            try:
                calendar = module.materialise(spec, bounds)
            except Exception as exc:  # upstreams raise anything
                # One upstream calendar refusing to build must not lose the other 400.
                # The skip is printed, and its absence shows up in the next `diff`.
                print(f"  skipped {spec.identifier}: {exc}", file=sys.stderr)
                continue
            entry, text = entry_for(calendar, spec.upstream)
            entries[entry] = text
    return entries, versions


def _cmd_snapshot(args: argparse.Namespace) -> int:
    bounds = _parse_bounds(args.bounds)
    only = set(args.only.split(",")) if args.only else None
    entries, versions = _materialise_all(
        _selected_providers(args.provider), bounds, only, report=True
    )
    directory = Path(args.output) if args.output else DATA_DIR
    write_snapshot(
        entries,
        directory,
        generated=date.today(),
        requested_bounds=bounds,
        provider_versions=versions,
    )
    total = sum(entry.holidays for entry in entries)
    print(f"wrote {len(entries)} calendars, {total} holidays, to {directory}")
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    committed = load_manifest()
    if not committed:
        print(
            "No committed snapshot to compare against. Generate one with "
            "`better-calendar snapshot`.",
            file=sys.stderr,
        )
        return 1
    bounds = _parse_bounds(args.bounds)
    only = set(args.only.split(",")) if args.only else None
    fresh, versions = _materialise_all(
        _selected_providers(args.provider), bounds, only, report=False
    )
    regenerated = {entry.identifier: entry for entry in fresh}

    # Only the calendars this run actually covered may be judged. Without this, a run
    # narrowed by --provider or --only would report every calendar it simply did not look
    # at as "removed", and the drift job would cry wolf on every invocation.
    in_scope = {
        name
        for name, entry in committed.items()
        if (args.provider == _ALL or entry.provider == args.provider)
        and (only is None or name in only)
    }
    common = set(regenerated) & in_scope
    added = sorted(set(regenerated) - in_scope)
    removed = sorted(in_scope - set(regenerated))
    changed = sorted(
        name for name in common if regenerated[name].sha256 != committed[name].sha256
    )
    version_only = sorted(
        name
        for name in common
        if regenerated[name].sha256 == committed[name].sha256
        and regenerated[name].provider_version != committed[name].provider_version
    )

    for name in added:
        print(f"added    {name} ({regenerated[name].holidays} holidays)")
    for name in removed:
        print(f"removed  {name}")
    for name in changed:
        before, after = committed[name].holidays, regenerated[name].holidays
        print(f"changed  {name}  {before} -> {after} holidays")
    for name in version_only:
        print(
            f"note     {name} regenerated from "
            f"{committed[name].provider_version} -> {regenerated[name].provider_version}, "
            f"no date moved"
        )

    if added or removed or changed:
        print(
            f"\n{len(added)} added, {len(removed)} removed, {len(changed)} changed. "
            f"Run `better-calendar snapshot` and review the diff before committing.",
            file=sys.stderr,
        )
        return 1
    print(f"snapshot is current ({len(common)} calendars, versions {versions})")
    return 0


def _cmd_describe(args: argparse.Namespace) -> int:
    from better_calendar.calendars.registry import describe

    print(json.dumps(describe(args.calendar), indent=2))
    return 0


def _cmd_next(args: argparse.Namespace) -> int:
    from better_calendar.calendars.registry import get

    calendar = get(args.calendar)
    print(calendar.offset(args.date, int(args.offset)))
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    from better_calendar.calendars.registry import list_calendars

    for name in list_calendars(provider=args.provider):
        print(name)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="better-calendar", description="Business-day calendars, snapshotted."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    default_bounds = f"{DEFAULT_BOUNDS[0].isoformat()}:{DEFAULT_BOUNDS[1].isoformat()}"

    snapshot = sub.add_parser("snapshot", help="regenerate the committed snapshot")
    snapshot.add_argument("--provider", default=_ALL, help=f"provider name, or {_ALL!r}")
    snapshot.add_argument("--bounds", default=default_bounds, help="START:END")
    snapshot.add_argument("--only", help="comma-separated calendar ids to limit the run")
    snapshot.add_argument("--output", help="write here instead of the packaged data dir")
    snapshot.set_defaults(func=_cmd_snapshot)

    diff = sub.add_parser("diff", help="compare a fresh materialisation with the committed one")
    diff.add_argument("--provider", default=_ALL, help=f"provider name, or {_ALL!r}")
    diff.add_argument("--bounds", default=default_bounds, help="START:END")
    diff.add_argument("--only", help="comma-separated calendar ids to limit the run")
    diff.set_defaults(func=_cmd_diff)

    describe = sub.add_parser("describe", help="show a calendar's provenance and shape")
    describe.add_argument("calendar")
    describe.set_defaults(func=_cmd_describe)

    nxt = sub.add_parser("next", help="offset a date by n business days")
    nxt.add_argument("calendar")
    nxt.add_argument("date")
    nxt.add_argument("offset", help="business days to move, e.g. +5 or -3")
    nxt.set_defaults(func=_cmd_next)

    listing = sub.add_parser("list", help="list resolvable calendars")
    listing.add_argument("--provider", help="restrict to one provider")
    listing.set_defaults(func=_cmd_list)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI.

    Args:
        argv: Arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        The process exit code.

    Examples:
        >>> main(["next", "weekday", "2026-07-31", "+1"])
        2026-08-03
        0
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler: Any = args.func
    try:
        return int(handler(args))
    except BetterCalendarError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
