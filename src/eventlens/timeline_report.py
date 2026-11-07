"""Render a Timeline for the text, Markdown, and JSON reports."""

from __future__ import annotations

import re
import textwrap
from datetime import datetime, timezone

from eventlens.timeline import Run, Timeline, format_uptime

WIDTH = 75
_SPECIAL = re.compile(r"([\\`*_\[\]<>|#~])")
_ENDINGS = {"clean": "shut down normally", "open": "still running or log ends"}


def _escape(text: str) -> str:
    return _SPECIAL.sub(r"\\\1", " ".join(text.split()))


def _ending(run: Run) -> str:
    if run.ended_by == "crash":
        return run.crash_title.lower() if run.crash_title else "unexpected shutdown"
    return _ENDINGS[run.ended_by]


def _summary(timeline: Timeline) -> str:
    runs, crashes = len(timeline.runs), len(timeline.crashes)
    text = f"{runs} start{'s' if runs != 1 else ''} in this period, {crashes} ended in a crash."
    longest = timeline.longest
    if longest is not None and longest.uptime is not None:
        text += f" Longest run: {format_uptime(longest.uptime)}."
    return text


def _lead_up_text(run: Run) -> str:
    return ", ".join(f"{count}x {title}" if count > 1 else title for title, count in run.lead_up)


def _recent(timeline: Timeline, top: int) -> list[Run]:
    return list(reversed(timeline.runs))[:top]


def _wrap(text: str, indent: int, hang: int = 0) -> list[str]:
    return textwrap.wrap(
        text,
        width=WIDTH,
        initial_indent=" " * indent,
        subsequent_indent=" " * (indent + hang),
        break_on_hyphens=False,
    )


def text_lines(timeline: Timeline, clock, top: int) -> list[str]:
    lines = ["Boots and uptime"]
    if not timeline.runs:
        lines.append("  No boot events found in this period.")
        return [*lines, ""]
    lines += _wrap(_summary(timeline), 2)
    shown = _recent(timeline, top)
    for run in shown:
        uptime = format_uptime(run.uptime) if run.uptime is not None else "unknown"
        head = f"- {clock.short(run.start)}: ran {uptime}, then {_ending(run)}"
        lines += _wrap(head, 2, 2)
        if run.crash_detail:
            lines += _wrap(run.crash_detail, 6)
        if run.lead_up:
            text = f"Just before: {_lead_up_text(run)}"
            lines += _wrap(text, 6, 2)
    hidden = len(timeline.runs) - len(shown)
    if hidden > 0:
        lines.append(f"  ...and {hidden} earlier")
    lines.append("")
    return lines


def markdown_lines(timeline: Timeline, clock, top: int) -> list[str]:
    lines = ["## Boots and uptime", ""]
    if not timeline.runs:
        return [*lines, "No boot events found in this period.", ""]
    lines += [_summary(timeline), ""]
    shown = _recent(timeline, top)
    for run in shown:
        uptime = format_uptime(run.uptime) if run.uptime is not None else "unknown"
        lines.append(f"- **{clock.short(run.start)}:** ran {uptime}, then {_escape(_ending(run))}")
        if run.crash_detail:
            lines.append(f"  - {_escape(run.crash_detail)}")
        if run.lead_up:
            lines.append(f"  - Just before: {_escape(_lead_up_text(run))}")
    hidden = len(timeline.runs) - len(shown)
    if hidden > 0:
        lines.append(f"- ...and {hidden} earlier")
    lines.append("")
    return lines


def _iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def json_data(timeline: Timeline) -> dict:
    return {
        "timeline": {
            "starts": len(timeline.runs),
            "crashes": len(timeline.crashes),
            "runs": [
                {
                    "computer": run.computer,
                    "start": _iso(run.start),
                    "end": _iso(run.end),
                    "uptime_seconds": int(run.uptime.total_seconds()) if run.uptime else None,
                    "ended_by": run.ended_by,
                    "crash": run.crash_title,
                    "crash_detail": run.crash_detail,
                    "before_crash": [{"title": t, "count": c} for t, c in run.lead_up],
                }
                for run in timeline.runs
            ],
        }
    }
