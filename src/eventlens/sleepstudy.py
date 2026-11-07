"""Sleep and standby problems from a ``powercfg /sleepstudy /xml`` file (SPEC.md section 12).

Create the file on the Windows PC (in an administrator prompt) with::

    powercfg /sleepstudy /xml /output sleepstudy.xml

Each ``ScenarioInstance`` in the file is one stretch with the screen off or the
PC in standby. Times are in 100-nanosecond ticks. Capacities are in mWh and are
zero on a PC with no battery, such as a desktop.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from eventlens.catalog import Severity
from eventlens.sources import SourceError, parse_time

# Sessions shorter than this are too short to judge (Windows doesn't track them either).
MIN_SESSION = timedelta(minutes=10)
# Battery drain per hour while idle, as a percent of a full charge. A rule of thumb.
DRAIN_MEDIUM = 1.0
DRAIN_HIGH = 3.0
# An offender must be busy this much of a session, at a high activity level, to count.
OFFENDER_MIN_PERCENT = 10.0
# Blockers that describe the PC being idle rather than a culprit.
NOT_CULPRITS = frozenset({"system idle"})


@dataclass(frozen=True)
class Offender:
    name: str
    percent: float  # of the session it was active


@dataclass(frozen=True)
class Session:
    kind: str  # "Screen Off", "Standby"...
    start: datetime
    duration: timedelta
    on_ac: bool
    entry_capacity: int
    exit_capacity: int
    full_capacity: int
    enter_reason: str
    exit_reason: str
    offenders: tuple[Offender, ...]

    @property
    def drain_percent_per_hour(self) -> float | None:
        """None when the session was on AC power, on a PC with no battery, or too short."""
        if self.on_ac or self.full_capacity <= 0 or self.duration < MIN_SESSION:
            return None
        lost = max(self.entry_capacity - self.exit_capacity, 0)
        hours = self.duration.total_seconds() / 3600
        return lost / self.full_capacity * 100 / hours


@dataclass(frozen=True)
class SleepFinding:
    severity: Severity
    title: str
    detail: str
    action: str


@dataclass(frozen=True)
class SleepStudy:
    sessions: list[Session]

    @property
    def on_battery(self) -> list[Session]:
        return [s for s in self.sessions if s.drain_percent_per_hour is not None]

    @property
    def findings(self) -> list[SleepFinding]:
        found = [f for f in (self._drain_finding(), self._offender_finding()) if f]
        return sorted(found, key=lambda f: -f.severity)

    def _drain_finding(self) -> SleepFinding | None:
        sessions = self.on_battery
        if not sessions:
            return None
        worst = max(sessions, key=lambda s: s.drain_percent_per_hour or 0)
        rate = worst.drain_percent_per_hour or 0
        if rate >= DRAIN_HIGH:
            severity = Severity.HIGH
        elif rate >= DRAIN_MEDIUM:
            severity = Severity.MEDIUM
        else:
            return None
        names = ", ".join(o.name for o in worst.offenders[:2])
        detail = (
            f"Worst: {rate:.1f}% of the battery per hour while idle, on "
            f"{worst.start:%d %b %H:%M} UTC for {_minutes(worst.duration)} minutes"
        )
        if names:
            detail += f" (busy: {names})"
        return SleepFinding(
            severity,
            "Battery drains quickly while the PC is idle",
            detail,
            "Close programs before closing the lid, unplug USB devices, and check "
            "'powercfg /requests' for what keeps the PC awake. Update the Wi-Fi and "
            "chipset drivers.",
        )

    def _offender_finding(self) -> SleepFinding | None:
        totals: dict[str, list[float]] = {}
        for session in self.sessions:
            for offender in session.offenders:
                totals.setdefault(offender.name, []).append(offender.percent)
        if not totals:
            return None
        ranked = sorted(totals.items(), key=lambda item: (-len(item[1]), -max(item[1])))
        lines = [
            f"{name}: busy in {len(values)} of {len(self.sessions)} sessions "
            f"(up to {max(values):.0f}% of the time)"
            for name, values in ranked[:3]
        ]
        on_battery = any(s.offenders for s in self.on_battery)
        return SleepFinding(
            Severity.MEDIUM if on_battery else Severity.LOW,
            "Programs or drivers kept the PC busy while the screen was off",
            "; ".join(lines),
            "Close or update the programs named above. Run 'powercfg /requests' in an "
            "administrator prompt to see what is asking Windows to stay awake.",
        )


def _minutes(duration: timedelta) -> int:
    return round(duration.total_seconds() / 60)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _int(node: ET.Element, name: str) -> int:
    try:
        return int(node.get(name, "0"))
    except ValueError:
        return 0


def _reason(text: str) -> str:
    """'0x20 (Input Mouse)' -> 'Input Mouse'."""
    if "(" in text and text.endswith(")"):
        return text[text.index("(") + 1 : -1]
    return text


def _offenders(scenario: ET.Element) -> tuple[Offender, ...]:
    """The innermost blockers that were busy a lot of the session.

    Blockers nest ("Power Requests" holds the program making the request), so
    only the innermost are kept: they are the ones that name a culprit.
    """
    found: dict[str, float] = {}
    for node in scenario.iter():
        if _local(node.tag) != "Blocker" or node.get("ActivityLevel") != "high":
            continue
        if any(_local(child.tag) == "Blocker" for child in node):
            continue
        try:
            percent = float(node.get("ScenarioActiveTimePercent", "0"))
        except ValueError:
            continue
        name = node.get("Name", "").strip()
        if name and name.lower() not in NOT_CULPRITS and percent >= OFFENDER_MIN_PERCENT:
            found[name] = max(percent, found.get(name, 0.0))
    return tuple(Offender(n, p) for n, p in sorted(found.items(), key=lambda i: -i[1]))


def parse_sleepstudy(path: Path) -> SleepStudy:
    """Read the sessions from a ``powercfg /sleepstudy /xml`` file."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise SourceError(f"could not read {path}: {exc.strerror or exc}") from exc
    try:
        root = ET.fromstring(data.lstrip(b"\xef\xbb\xbf"))
    except ET.ParseError as exc:
        raise SourceError(f"{path} is not a valid sleep study report: {exc}") from exc
    if _local(root.tag) != "SleepStudy":
        raise SourceError(f"{path} is not a sleep study report (made by powercfg /sleepstudy /xml)")

    sessions = []
    for node in root.iter():
        if _local(node.tag) != "ScenarioInstance":
            continue
        try:
            start = parse_time(node.get("TimeStamp", ""))
        except ValueError:
            continue
        sessions.append(
            Session(
                kind=node.get("Type", "").strip() or "Unknown",
                start=start,
                duration=timedelta(microseconds=_int(node, "Duration") / 10),
                on_ac=node.get("Ac") == "1",
                entry_capacity=_int(node, "EntryRemainingCapacity"),
                exit_capacity=_int(node, "ExitRemainingCapacity"),
                full_capacity=_int(node, "EntryFullCapacity") or _int(node, "FullChargeCapacity"),
                enter_reason=_reason(node.get("CsEnterReason", "")),
                exit_reason=_reason(node.get("CsExitReason", "")),
                offenders=_offenders(node),
            )
        )
    return SleepStudy(sorted(sessions, key=lambda s: s.start))
