"""Characterization tests: pin the catalog contents against a JSON snapshot."""

import json
from pathlib import Path

import pytest

from eventlens.catalog import RULES, STOP_CODES, lookup

SNAPSHOT = json.loads(
    (Path(__file__).parent / "fixtures" / "catalog_snapshot.json").read_text(encoding="utf-8")
)


def _rule_dicts() -> list[dict]:
    return [
        {
            "key": r.key,
            "providers": list(r.providers),
            "event_ids": list(r.event_ids),
            "severity": r.severity.name.lower(),
            "escalate": (
                None if r.escalate is None else [r.escalate[0], r.escalate[1].name.lower()]
            ),
            "title": r.title,
            "meaning": r.meaning,
            "action": r.action,
            "detail_label": r.detail_label,
            "has_detail": r.detail is not None,
        }
        for r in RULES
    ]


def test_rules_match_snapshot():
    assert _rule_dicts() == SNAPSHOT["rules"]


def test_stop_codes_match_snapshot():
    current = {f"0x{code:X}": list(value) for code, value in STOP_CODES.items()}
    assert current == SNAPSHOT["stop_codes"]


@pytest.mark.parametrize(
    ("provider", "event_id", "data", "expected"),
    [
        ("disk", 7, {"param1": r"\Device\Harddisk0\DR0"}, r"\Device\Harddisk0\DR0"),
        ("disk", 51, {"param1": r"\Device\Harddisk1\DR1"}, r"\Device\Harddisk1\DR1"),
        ("Display", 4101, {"param1": "nvlddmkm"}, "nvlddmkm"),
        ("Ntfs", 55, {"DriveName": "C:"}, "C:"),
        ("Ntfs", 55, {}, None),
        ("Microsoft-Windows-Kernel-PnP", 219, {"DriverName": r"\Driver\foo"}, r"\Driver\foo"),
        ("Microsoft-Windows-DNS-Client", 1014, {"QueryName": "example.com"}, "example.com"),
        ("Application Hang", 1002, {"AppName": "a.exe"}, "a.exe"),
    ],
)
def test_detail_extraction_is_pinned(make_event, provider, event_id, data, expected):
    event = make_event(provider, event_id, data=data)
    assert lookup(event).detail(event) == expected
