"""Command-line interface (see SPEC.md section 3)."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

from eventlens import __version__
from eventlens.analyzer import analyze
from eventlens.models import Event
from eventlens.report import render
from eventlens.sources import DEFAULT_CHANNELS, SourceError, read_file, read_live

DEFAULT_DAYS = 7
DEFAULT_MAX_EVENTS = 5000
DEFAULT_TOP = 10

EXIT_OK = 0
EXIT_ERROR = 2


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a whole number, got {value!r}") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be 1 or more, got {number}")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eventlens",
        description=(
            "Explain what went wrong on a Windows PC, in plain English, from its "
            "event logs. With no --file, reads the live System and Application "
            "logs (Windows only)."
        ),
    )
    parser.add_argument(
        "--file",
        action="append",
        type=Path,
        metavar="PATH",
        help="exported .evtx or .xml log to read; repeat to combine logs",
    )
    parser.add_argument(
        "--channel",
        action="append",
        metavar="NAME",
        help="live mode only: log channel to read (default: System and Application)",
    )
    parser.add_argument(
        "--days",
        type=_positive_int,
        default=DEFAULT_DAYS,
        metavar="N",
        help=(
            f"only look at the last N days (default: {DEFAULT_DAYS}); for files, "
            "counted back from the newest event in the file"
        ),
    )
    parser.add_argument(
        "--max-events",
        type=_positive_int,
        metavar="N",
        help=f"live mode only: newest events to read per channel (default: {DEFAULT_MAX_EVENTS})",
    )
    parser.add_argument(
        "--include-warnings",
        action="store_true",
        help="also list unrecognised warnings, not just errors",
    )
    parser.add_argument(
        "--top",
        type=_positive_int,
        default=DEFAULT_TOP,
        metavar="N",
        help=f"most unrecognised event types to list (default: {DEFAULT_TOP})",
    )
    parser.add_argument("--utc", action="store_true", help="show times in UTC")
    parser.add_argument(
        "--verbose", action="store_true", help="show the latest raw event for each finding"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _read_events(args: argparse.Namespace) -> tuple[list[Event], datetime]:
    """Read every input. Returns the events and the time the window ends at."""
    now = datetime.now(timezone.utc)
    if args.file:
        events = [event for path in args.file for event in read_file(path)]
        newest = max((e.time for e in events), default=now)
        return events, newest

    channels = args.channel or list(DEFAULT_CHANNELS)
    max_events = args.max_events or DEFAULT_MAX_EVENTS
    events = [
        event
        for channel in channels
        for event in read_live(channel, days=args.days, max_events=max_events)
    ]
    return events, now


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.file and (args.channel or args.max_events):
        parser.error("--channel and --max-events only apply to live logs, not --file")

    logging.basicConfig(format="eventlens: warning: %(message)s", level=logging.WARNING)
    # Event data can contain any character; never crash on a console that
    # can't display one.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(errors="replace")

    try:
        events, window_end = _read_events(args)
    except SourceError as exc:
        print(f"eventlens: error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    analysis = analyze(
        events,
        since=window_end - timedelta(days=args.days),
        include_warnings=args.include_warnings,
    )
    sys.stdout.write(render(analysis, top=args.top, utc=args.utc, verbose=args.verbose))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
