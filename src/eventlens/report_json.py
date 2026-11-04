"""Render an Analysis as JSON for scripts (see SPEC.md section 7.2)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from eventlens import __version__
from eventlens.analyzer import Analysis, Finding
from eventlens.models import Event
from eventlens.power import Battery

SCHEMA_VERSION = 1


def _iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sample(event: Event) -> dict:
    return {
        "provider": event.provider,
        "event_id": event.event_id,
        "time": _iso(event.time),
        "data": dict(event.data),
    }


def _finding(finding: Finding, verbose: bool) -> dict:
    result = {
        "id": finding.rule.key,
        "severity": finding.severity.name.lower(),
        "title": finding.rule.title,
        "count": finding.count,
        "first": _iso(finding.first),
        "last": _iso(finding.last),
        "details": [
            {"detail": detail, "count": count} for detail, count in finding.details.most_common()
        ],
        "meaning": finding.rule.meaning,
        "action": finding.rule.action,
    }
    if verbose and finding.sample is not None:
        result["sample"] = _sample(finding.sample)
    return result


def render_json(
    analysis: Analysis, verbose: bool = False, batteries: list[Battery] | None = None
) -> str:
    """Return the report as JSON ending in a newline.

    Unlike the text report, this lists every detail and every unrecognised
    event type, and always uses UTC. The output is pure ASCII (non-ASCII text
    is written as \\uXXXX escapes), so a console or redirect that uses a
    legacy code page, common on Windows, can't change what a parser reads.
    """
    period = None
    if analysis.start is not None and analysis.end is not None:
        period = {"start": _iso(analysis.start), "end": _iso(analysis.end)}
    document = {
        "schema_version": SCHEMA_VERSION,
        "eventlens_version": __version__,
        "computers": analysis.computers,
        "channels": analysis.channels,
        "period": period,
        "events_read": analysis.events_read,
        "events_in_window": analysis.events_in_window,
        "verdict": analysis.verdict,
        "headline": analysis.headline,
        "findings": [_finding(f, verbose) for f in analysis.problems],
        "normal": [_finding(f, verbose) for f in analysis.normal],
        "unrecognised": [
            {
                "provider": group.provider,
                "event_id": group.event_id,
                "level": group.level.name.lower(),
                "count": group.count,
                "last": _iso(group.last),
            }
            for group in analysis.unrecognised
        ],
    }
    if batteries is not None:
        document["batteries"] = [
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
    return json.dumps(document, indent=2) + "\n"
