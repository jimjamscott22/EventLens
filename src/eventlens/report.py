"""Render an Analysis as a plain-text report (see SPEC.md section 7)."""

from __future__ import annotations

import textwrap
from datetime import datetime, timezone

from eventlens.analyzer import Analysis, Finding

WIDTH = 75
LABEL_WIDTH = 16
MAX_DETAILS = 3
RULE_LINE = "-" * WIDTH


class Clock:
    """Formats times in UTC or the local time zone."""

    def __init__(self, utc: bool) -> None:
        self.utc = utc

    def convert(self, moment: datetime) -> datetime:
        return moment.astimezone(timezone.utc if self.utc else None)

    def long(self, moment: datetime) -> str:
        local = self.convert(moment)
        return f"{local.day} {local:%b %Y %H:%M}"

    def short(self, moment: datetime) -> str:
        local = self.convert(moment)
        return f"{local.day} {local:%b %H:%M}"

    def zone(self, moment: datetime) -> str:
        return "UTC" if self.utc else (self.convert(moment).tzname() or "local time")


def _times(count: int) -> str:
    return "1 time" if count == 1 else f"{count:,} times"


def _labelled(label: str, text: str) -> list[str]:
    """Wrap ``text`` in a column next to ``label``."""
    return textwrap.wrap(
        text,
        width=WIDTH,
        initial_indent=f"{label + ':':<{LABEL_WIDTH}}",
        subsequent_indent=" " * LABEL_WIDTH,
        break_on_hyphens=False,
    )


def _detail_lines(finding: Finding, indent: int) -> list[str]:
    """One line per distinct detail, most common first, e.g. ``5x game.exe``."""
    top = finding.details.most_common(MAX_DETAILS)
    width = max(len(str(count)) for _, count in top)
    lines = []
    for detail, count in top:
        prefix = f"{count:>{width}}x "
        lines += textwrap.wrap(
            detail,
            width=WIDTH,
            initial_indent=" " * indent + prefix,
            subsequent_indent=" " * (indent + len(prefix)),
            break_on_hyphens=False,
        )
    rest = len(finding.details) - len(top)
    if rest:
        lines.append(" " * indent + f"...and {rest} more")
    return lines


def _sample_text(finding: Finding) -> str | None:
    sample = finding.sample
    if sample is None:
        return None
    data = ", ".join(f"{k}={v}" for k, v in sample.data.items() if v)
    text = f"{sample.provider} {sample.event_id}"
    if data:
        text += f" ({data})"
    return text if len(text) <= 300 else text[:297] + "..."


def _finding_block(finding: Finding, clock: Clock, verbose: bool) -> list[str]:
    left = f"{finding.severity.label:<9} {finding.rule.title}"
    right = _times(finding.count)
    if finding.last is not None:
        right += f", last {clock.short(finding.last)}"
    gap = WIDTH - len(left) - len(right)
    heading = f"{left}{' ' * gap}{right}" if gap >= 2 else f"{left}\n{' ' * 10}{right}"

    lines = [RULE_LINE, heading, RULE_LINE]
    if finding.details:
        details = _detail_lines(finding, LABEL_WIDTH)
        label = f"{finding.rule.detail_label + ':':<{LABEL_WIDTH}}"
        lines += [label + details[0][LABEL_WIDTH:], *details[1:]]
    lines += _labelled("What it means", finding.rule.meaning)
    if finding.rule.action:
        lines += _labelled("What to do", finding.rule.action)
    if verbose and (sample := _sample_text(finding)):
        lines += _labelled("Latest event", sample)
    lines.append("")
    return lines


def _normal_section(analysis: Analysis) -> list[str]:
    if not analysis.normal:
        return []
    lines = ["Normal activity (no action needed)"]
    for finding in analysis.normal:
        text = f"- {finding.rule.title}: {_times(finding.count)}"
        lines += textwrap.wrap(text, width=WIDTH, initial_indent="  ", subsequent_indent="    ")
        if finding.details:
            lines += _detail_lines(finding, indent=6)
    lines.append("")
    return lines


def _unrecognised_section(analysis: Analysis, top: int) -> list[str]:
    groups = analysis.unrecognised
    if not groups:
        return []
    shown = groups[:top]
    lines = [f"Not yet recognised (top {len(shown)} of {len(groups)} event types)"]
    for group in shown:
        name = f"{group.provider} {group.event_id} ({group.level.label})"
        count = _times(group.count)
        gap = max(2, WIDTH - 4 - len(name) - len(count))
        lines.append(f"  - {name}{' ' * gap}{count}")
    lines.append("")
    return lines


def _computer_text(computers: list[str]) -> str:
    if not computers:
        return "unknown computer"
    if len(computers) == 1:
        return computers[0]
    others = len(computers) - 1
    return f"{computers[0]} and {others} other{'s' if others > 1 else ''}"


def render(analysis: Analysis, top: int = 10, utc: bool = False, verbose: bool = False) -> str:
    """Return the full report as a string ending in a newline."""
    clock = Clock(utc)
    lines = [f"EventLens report for {_computer_text(analysis.computers)}"]

    if analysis.start is None or analysis.end is None:
        if analysis.events_read:
            lines.append(f"Events read: {analysis.events_read:,}")
            lines += ["", "No events found in this period. Try a larger --days value."]
        else:
            lines += ["", "No events found in the input."]
        return "\n".join(lines) + "\n"

    logs = ", ".join(analysis.channels) or "unknown"
    period = (
        f"{clock.long(analysis.start)} to {clock.long(analysis.end)} "
        f"({clock.zone(analysis.end)})"
    )
    lines += [
        f"Logs: {logs}",
        f"Period: {period}",
        f"Events read: {analysis.events_read:,} ({analysis.events_in_window:,} in this period)",
        "",
        f"Verdict: {analysis.verdict}",
        analysis.headline,
        "",
    ]
    for finding in analysis.problems:
        lines += _finding_block(finding, clock, verbose)
    lines += _normal_section(analysis)
    lines += _unrecognised_section(analysis, top)

    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"
