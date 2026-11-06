"""A timeline of boots and shutdowns, with uptime and what led up to each crash.

Boots are Kernel-General 12 and EventLog 6005. Clean shutdowns are
Kernel-General 13 and EventLog 6006. A run that ends without a shutdown event
before the next boot is a crash, and the problems logged in the minutes before
it are listed (SPEC.md section 13).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from eventlens.analyzer import _group_incidents, classify_incident
from eventlens.catalog import CRASH_EVENTS, event_key, lookup
from eventlens.models import Event, Level

BOOT_EVENTS = {("microsoft-windows-kernel-general", 12), ("eventlog", 6005)}
SHUTDOWN_EVENTS = {("microsoft-windows-kernel-general", 13), ("eventlog", 6006)}
# Two events this close together describe the same boot or shutdown.
SAME_MOMENT = timedelta(minutes=2)
# How far back from a crash to look for warnings and errors.
LEAD_UP = timedelta(minutes=5)
MAX_LEAD_UP_ITEMS = 5


@dataclass
class Run:
    """One stretch from a boot to the next shutdown or crash."""

    computer: str
    start: datetime
    end: datetime | None  # None: still running, or the log ends first
    ended_by: str  # "clean", "crash", or "open"
    crash_title: str | None = None
    crash_detail: str | None = None
    lead_up: list[tuple[str, int]] = field(default_factory=list)

    @property
    def uptime(self) -> timedelta | None:
        return None if self.end is None else self.end - self.start


@dataclass
class Timeline:
    runs: list[Run]  # oldest first

    @property
    def crashes(self) -> list[Run]:
        return [r for r in self.runs if r.ended_by == "crash"]

    @property
    def longest(self) -> Run | None:
        finished = [r for r in self.runs if r.uptime is not None]
        return max(finished, key=lambda r: r.uptime or timedelta(0), default=None)


def _moments(events: list[Event], keys: set[tuple[str, int]]) -> list[datetime]:
    """Times of the given events, with near-duplicates (one boot writes two) merged."""
    times = sorted(e.time for e in events if event_key(e) in keys)
    merged: list[datetime] = []
    for time in times:
        if not merged or time - merged[-1] > SAME_MOMENT:
            merged.append(time)
    return merged


def format_uptime(span: timedelta) -> str:
    minutes = int(span.total_seconds() // 60)
    days, rest = divmod(minutes, 24 * 60)
    hours, mins = divmod(rest, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {mins:02d}m"
    return f"{mins}m"


def _title(event: Event) -> str:
    rule = lookup(event)
    return rule.title if rule else f"{event.provider} {event.event_id}"


def _lead_up(
    events: list[Event], crash_time: datetime, boot_time: datetime
) -> list[tuple[str, int]]:
    """The commonest warnings and errors in the minutes before ``crash_time``."""
    titles: Counter[str] = Counter()
    for event in events:
        if crash_time - LEAD_UP <= event.time < boot_time and event.level <= Level.WARNING:
            if event_key(event) not in CRASH_EVENTS:
                titles[_title(event)] += 1
    return titles.most_common(MAX_LEAD_UP_ITEMS)


def _computer_runs(computer: str, events: list[Event], since: datetime | None) -> list[Run]:
    events = sorted(events, key=lambda e: e.time)
    boots = [b for b in _moments(events, BOOT_EVENTS) if since is None or b >= since]
    shutdowns = _moments(events, SHUTDOWN_EVENTS)
    crash_events = [e for e in events if event_key(e) in CRASH_EVENTS]
    incidents = _group_incidents(crash_events)

    runs = []
    for index, start in enumerate(boots):
        next_boot = boots[index + 1] if index + 1 < len(boots) else None
        limit = next_boot or datetime.max.replace(tzinfo=start.tzinfo)
        clean = [s for s in shutdowns if start < s < limit]
        if clean:
            runs.append(Run(computer, start, clean[-1], "clean"))
        elif next_boot is None:
            last = events[-1].time if events else start
            runs.append(Run(computer, start, max(last, start), "open"))
        else:
            before = [e.time for e in events if start <= e.time < next_boot]
            end = max(before, default=start)
            run = Run(computer, start, end, "crash")
            nearby = [
                i
                for i in incidents
                if next_boot - SAME_MOMENT <= i[0].time <= next_boot + timedelta(minutes=10)
            ]
            if nearby:
                rule, detail = classify_incident(nearby[0])
                run.crash_title, run.crash_detail = rule.title, detail
            run.lead_up = _lead_up(events, end, next_boot)
            runs.append(run)
    return runs


def build_timeline(events: list[Event], since: datetime | None = None) -> Timeline:
    """Build the boot and shutdown timeline. Boots before ``since`` are left out."""
    # Names that differ only in case are one computer, as in the main analysis.
    by_computer: dict[str, list[Event]] = {}
    for event in events:
        by_computer.setdefault(event.computer.lower(), []).append(event)
    runs: list[Run] = []
    for computer_events in by_computer.values():
        name = Counter(e.computer for e in computer_events).most_common(1)[0][0]
        runs += _computer_runs(name, computer_events, since)
    return Timeline(sorted(runs, key=lambda r: r.start))
