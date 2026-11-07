"""Render the power sections of a report: battery health and the sleep study.

These sections are shown after the event findings. They don't change the
verdict or the ``--fail-on`` exit code.
"""

from __future__ import annotations

import re
import textwrap

from eventlens.power import Battery
from eventlens.sleepstudy import SleepFinding, SleepStudy

WIDTH = 75
_SPECIAL = re.compile(r"([\\`*_\[\]<>|#~])")

NO_BATTERY = "No battery found in the report (normal for a desktop PC)."


def _escape(text: str) -> str:
    return _SPECIAL.sub(r"\\\1", " ".join(text.split()))


def _facts(battery: Battery) -> str:
    facts = (
        f"{battery.health_percent}% of original capacity "
        f"({battery.full_charge_capacity:,} of {battery.design_capacity:,} mWh)"
    )
    if battery.cycle_count:
        facts += f", {battery.cycle_count:,} charge cycles"
    return facts


def _sleep_summary(sleep: SleepStudy) -> str:
    count = len(sleep.sessions)
    if not count:
        return "No screen-off or standby sessions in the report."
    text = f"{count} screen-off or standby session{'s' if count != 1 else ''}"
    if sleep.on_battery:
        text += f", {len(sleep.on_battery)} on battery"
    return text + "."


def _wrap(text: str, indent: str = "  ", more: str = "    ") -> list[str]:
    return textwrap.wrap(
        text, width=WIDTH, initial_indent=indent, subsequent_indent=more, break_on_hyphens=False
    )


def text_lines(batteries: list[Battery] | None, sleep: SleepStudy | None) -> list[str]:
    lines: list[str] = []
    if batteries is not None:
        lines.append("Battery health")
        if not batteries:
            lines += _wrap(NO_BATTERY)
        for battery in batteries:
            lines += _wrap(f"- {battery.name}: {_facts(battery)}")
            lines += _wrap(f"{battery.summary} {battery.advice}".rstrip(), "    ", "    ")
        lines.append("")
    if sleep is not None:
        lines.append("Sleep and standby")
        lines += _wrap(_sleep_summary(sleep))
        for finding in sleep.findings:
            lines += _wrap(f"- {finding.severity.label}: {finding.title}")
            lines += _wrap(finding.detail, "    ", "    ")
            lines += _wrap(f"What to do: {finding.action}", "    ", "      ")
        lines.append("")
    return lines


def markdown_lines(batteries: list[Battery] | None, sleep: SleepStudy | None) -> list[str]:
    lines: list[str] = []
    if batteries is not None:
        lines += ["## Battery health", ""]
        if not batteries:
            lines.append(f"- {NO_BATTERY}")
        for battery in batteries:
            lines.append(f"- **{_escape(battery.name)}:** {_facts(battery)}")
            lines.append(f"  - {battery.summary} {battery.advice}".rstrip())
        lines.append("")
    if sleep is not None:
        lines += ["## Sleep and standby", "", _sleep_summary(sleep), ""]
        for finding in sleep.findings:
            lines.append(f"- **{finding.severity.label}: {_escape(finding.title)}**")
            lines.append(f"  - {_escape(finding.detail)}")
            lines.append(f"  - **What to do:** {_escape(finding.action)}")
        if sleep.findings:
            lines.append("")
    return lines


def _finding_json(finding: SleepFinding) -> dict:
    return {
        "severity": finding.severity.name.lower(),
        "title": finding.title,
        "detail": finding.detail,
        "action": finding.action,
    }


def json_data(batteries: list[Battery] | None, sleep: SleepStudy | None) -> dict:
    """Extra top-level JSON fields; only the inputs that were given appear."""
    data: dict = {}
    if batteries is not None:
        data["batteries"] = [
            {
                "name": b.name,
                "severity": b.severity.name.lower(),
                "design_capacity_mwh": b.design_capacity,
                "full_charge_capacity_mwh": b.full_charge_capacity,
                "wear_percent": b.wear_percent,
                "cycle_count": b.cycle_count,
                "summary": b.summary,
                "action": b.advice,
            }
            for b in batteries
        ]
    if sleep is not None:
        data["sleep_study"] = {
            "sessions": len(sleep.sessions),
            "sessions_on_battery": len(sleep.on_battery),
            "findings": [_finding_json(f) for f in sleep.findings],
        }
    return data
