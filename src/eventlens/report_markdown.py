"""Render an Analysis as Markdown for tickets and chat (see SPEC.md section 7.1)."""

from __future__ import annotations

import re

from eventlens.analyzer import Analysis, Finding
from eventlens.power import Battery
from eventlens.power_report import markdown_lines as power_lines
from eventlens.report import MAX_DETAILS, Clock, computer_text, times
from eventlens.sleepstudy import SleepStudy
from eventlens.timeline import Timeline
from eventlens.timeline_report import markdown_lines as timeline_lines

_SPECIAL = re.compile(r"([\\`*_\[\]<>|#~])")


def escape(text: str) -> str:
    """Make a value from the log safe to put in Markdown text."""
    return _SPECIAL.sub(r"\\\1", " ".join(text.split()))


def _details(finding: Finding) -> list[str]:
    top = finding.details.most_common(MAX_DETAILS)
    lines = [f"  - {count}x {escape(detail)}" for detail, count in top]
    rest = len(finding.details) - len(top)
    if rest:
        lines.append(f"  - ...and {rest} more")
    return lines


def _sample(finding: Finding) -> str | None:
    sample = finding.sample
    if sample is None:
        return None
    data = ", ".join(f"{k}={v}" for k, v in sample.data.items() if v)
    text = f"{sample.provider} {sample.event_id}" + (f" ({data})" if data else "")
    text = " ".join(text.split()).replace("`", "'")
    return text if len(text) <= 300 else text[:297] + "..."


def _finding_block(finding: Finding, clock: Clock, verbose: bool) -> list[str]:
    summary = times(finding.count)
    if finding.last is not None:
        summary += f", last {clock.short(finding.last)}"
    lines = [f"### {finding.severity.label}: {escape(finding.rule.title)} ({summary})", ""]
    if finding.details:
        lines += [f"- **{escape(finding.rule.detail_label)}:**", *_details(finding)]
    lines.append(f"- **What it means:** {finding.rule.meaning}")
    if finding.rule.action:
        lines.append(f"- **What to do:** {finding.rule.action}")
    if verbose and (sample := _sample(finding)):
        lines.append(f"- **Latest event:** `{sample}`")
    lines.append("")
    return lines


def _normal_section(analysis: Analysis) -> list[str]:
    if not analysis.normal:
        return []
    lines = ["## Normal activity (no action needed)", ""]
    for finding in analysis.normal:
        lines.append(f"- {escape(finding.rule.title)}: {times(finding.count)}")
        lines += _details(finding)
    lines.append("")
    return lines


def _unrecognised_section(analysis: Analysis, top: int) -> list[str]:
    groups = analysis.unrecognised
    if not groups:
        return []
    shown = groups[:top]
    lines = [f"## Not yet recognised (top {len(shown)} of {len(groups)} event types)", ""]
    for group in shown:
        name = escape(f"{group.provider} {group.event_id} ({group.level.label})")
        lines.append(f"- {name}: {times(group.count)}")
    lines.append("")
    return lines


def render_markdown(
    analysis: Analysis,
    top: int = 10,
    utc: bool = False,
    verbose: bool = False,
    batteries: list[Battery] | None = None,
    sleep: SleepStudy | None = None,
    timeline: Timeline | None = None,
) -> str:
    """Return the full report as Markdown ending in a newline."""
    clock = Clock(utc)
    lines = [f"# EventLens report for {escape(computer_text(analysis.computers))}", ""]

    if analysis.start is None or analysis.end is None:
        if analysis.events_read:
            lines += [
                f"**Events read:** {analysis.events_read:,}",
                "",
                "No events found in this period. Try a larger --days value.",
            ]
        else:
            lines.append("No events found in the input.")
        extra = power_lines(batteries, sleep)
        lines += ["", *extra] if extra else []
        return "\n".join(lines) + "\n"

    logs = ", ".join(analysis.channels) or "unknown"
    period = (
        f"{clock.long(analysis.start)} to {clock.long(analysis.end)} "
        f"({clock.zone(analysis.end)})"
    )
    lines += [
        f"- **Logs:** {escape(logs)}",
        f"- **Period:** {period}",
        f"- **Events read:** {analysis.events_read:,} "
        f"({analysis.events_in_window:,} in this period)",
        "",
        f"**Verdict:** {analysis.verdict}",
        "",
        analysis.headline,
        "",
    ]
    if analysis.problems:
        lines += ["## Problems", ""]
    for finding in analysis.problems:
        lines += _finding_block(finding, clock, verbose)
    lines += _normal_section(analysis)
    lines += _unrecognised_section(analysis, top)
    if timeline is not None:
        lines += timeline_lines(timeline, clock, top)
    lines += power_lines(batteries, sleep)

    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"
