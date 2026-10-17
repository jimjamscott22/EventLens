"""Turn a list of events into ranked findings (see SPEC.md section 4)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from eventlens.catalog import (
    BLUE_SCREEN,
    BUGCHECK_1001,
    CRASH_EVENTS,
    FORCED_POWER_OFF,
    INCIDENT_RULES,
    KERNEL_POWER_41,
    POWER_LOSS,
    Rule,
    Severity,
    describe_stop_code,
    event_key,
    lookup,
    parse_stop_code,
)
from eventlens.catalog import (
    field as data_field,
)
from eventlens.models import Event, Level

# Crash events this close together come from the same unexpected shutdown.
INCIDENT_WINDOW = timedelta(minutes=10)


@dataclass
class Finding:
    """One kind of problem, with every occurrence grouped together."""

    rule: Rule
    count: int = 0
    first: datetime | None = None
    last: datetime | None = None
    details: Counter[str] = field(default_factory=Counter)
    sample: Event | None = None

    def add(self, time: datetime, detail: str | None, sample: Event) -> None:
        self.count += 1
        if self.first is None or time < self.first:
            self.first = time
        if self.last is None or time >= self.last:
            self.last = time
            self.sample = sample
        if detail:
            self.details[detail] += 1

    @property
    def severity(self) -> Severity:
        return self.rule.severity_for(self.count)


@dataclass
class UnrecognisedGroup:
    """Events of one (provider, ID) that the catalog doesn't explain yet."""

    provider: str
    event_id: int
    level: Level
    count: int = 0
    last: datetime | None = None


@dataclass
class Analysis:
    findings: list[Finding]
    unrecognised: list[UnrecognisedGroup]
    events_read: int
    events_in_window: int
    start: datetime | None
    end: datetime | None
    computers: list[str]
    channels: list[str]

    @property
    def problems(self) -> list[Finding]:
        return [f for f in self.findings if f.severity > Severity.INFO]

    @property
    def normal(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == Severity.INFO]

    @property
    def worst(self) -> Severity:
        return max((f.severity for f in self.findings), default=Severity.INFO)

    @property
    def verdict(self) -> str:
        worst = self.worst
        if worst == Severity.CRITICAL:
            return "Serious problems found."
        if worst == Severity.HIGH:
            return "Problems found that need attention."
        if worst > Severity.INFO:
            return "Minor issues found."
        return "No significant problems found."

    @property
    def headline(self) -> str:
        incidents = {
            f.rule.key: f.count for f in self.findings if f.rule.key in _INCIDENT_KEYS
        }
        total = sum(incidents.values())
        if total:
            sentence = f"This PC shut down unexpectedly {_times(total)}"
            blue = incidents.get(BLUE_SCREEN.key, 0)
            if blue:
                sentence += f", including {blue} blue screen crash"
                sentence += "es" if blue != 1 else ""
            return sentence + "."
        problems = self.problems
        if problems:
            top = problems[0]
            return f"Top issue: {top.rule.title.lower()} ({_times(top.count)})."
        return "Nothing in these logs needs attention."


_INCIDENT_KEYS = {rule.key for rule in INCIDENT_RULES}


def _times(count: int) -> str:
    return "1 time" if count == 1 else f"{count} times"


def _group_incidents(events: list[Event]) -> list[list[Event]]:
    """Split crash events into incidents, one per unexpected shutdown.

    An incident starts with its earliest event and takes in later events
    within ``INCIDENT_WINDOW``. Each restart writes each crash event at most
    once, so a repeated event ID always starts a new incident.
    """
    incidents: list[list[Event]] = []
    for event in sorted(events, key=lambda e: e.time):
        current = incidents[-1] if incidents else None
        if (
            current is not None
            and event.time - current[0].time <= INCIDENT_WINDOW
            and event_key(event) not in {event_key(e) for e in current}
        ):
            current.append(event)
        else:
            incidents.append([event])
    return incidents


def _nonzero(value: str | None) -> bool:
    return bool(value) and value.strip() not in ("0", "")


def classify_incident(events: list[Event]) -> tuple[Rule, str | None]:
    """Decide what kind of crash an incident was, and its stop code if any."""
    by_key = {event_key(e): e for e in events}
    bugcheck = by_key.get(BUGCHECK_1001)
    power = by_key.get(KERNEL_POWER_41)

    code = None
    if bugcheck is not None:
        code = parse_stop_code(data_field(bugcheck, "param1"))
    if code is None and power is not None:
        code = parse_stop_code(data_field(power, "BugcheckCode")) or None

    if bugcheck is not None or code:
        detail = describe_stop_code(code) if code else "Stop code not recorded"
        return BLUE_SCREEN, detail
    if power is not None and _nonzero(data_field(power, "PowerButtonTimestamp")):
        return FORCED_POWER_OFF, None
    return POWER_LOSS, None


def _sort_key(finding: Finding) -> tuple:
    last = finding.last.timestamp() if finding.last else 0
    return (-finding.severity, -finding.count, -last)


def analyze(
    events: Iterable[Event],
    since: datetime | None = None,
    include_warnings: bool = False,
) -> Analysis:
    """Group events into findings.

    ``since`` drops events older than that time. ``include_warnings`` also
    lists unrecognised warnings, not just unrecognised errors.
    """
    all_events = list(events)
    window = [e for e in all_events if since is None or e.time >= since]

    findings: dict[str, Finding] = {}
    crash_events: list[Event] = []
    unrecognised: dict[tuple[str, int], UnrecognisedGroup] = {}
    shown_levels = {Level.CRITICAL, Level.ERROR}
    if include_warnings:
        shown_levels.add(Level.WARNING)

    def finding_for(rule: Rule) -> Finding:
        return findings.setdefault(rule.key, Finding(rule))

    for event in window:
        if event_key(event) in CRASH_EVENTS:
            crash_events.append(event)
            continue
        rule = lookup(event)
        if rule is not None:
            detail = rule.detail(event) if rule.detail else None
            finding_for(rule).add(event.time, detail, event)
        elif event.level in shown_levels:
            key = event_key(event)
            group = unrecognised.get(key)
            if group is None:
                group = unrecognised[key] = UnrecognisedGroup(
                    event.provider, event.event_id, event.level
                )
            group.count += 1
            group.level = min(group.level, event.level)
            if group.last is None or event.time > group.last:
                group.last = event.time

    for incident in _group_incidents(crash_events):
        rule, detail = classify_incident(incident)
        finding_for(rule).add(incident[0].time, detail, incident[0])

    times = [e.time for e in window]
    return Analysis(
        findings=sorted(findings.values(), key=_sort_key),
        unrecognised=sorted(
            unrecognised.values(),
            key=lambda g: (-g.count, -(g.last.timestamp() if g.last else 0)),
        ),
        events_read=len(all_events),
        events_in_window=len(window),
        start=min(times, default=None),
        end=max(times, default=None),
        computers=[c for c, _ in Counter(e.computer for e in window if e.computer).most_common()],
        channels=sorted({e.channel for e in window if e.channel}),
    )
