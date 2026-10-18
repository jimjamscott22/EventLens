"""Runs the real wevtutil. Only on Windows CI: it writes an event to the log."""

import os
import subprocess
import sys
import uuid

import pytest

from eventlens.sources import read_live

pytestmark = pytest.mark.skipif(
    not (sys.platform == "win32" and os.environ.get("CI")),
    reason="runs wevtutil and writes to the event log, so only on Windows CI",
)


def test_live_system_log_is_read_and_parsed():
    events = read_live("System", days=30, max_events=50)
    assert events
    assert all(e.provider and e.event_id for e in events)


def test_non_ascii_text_survives_a_live_read():
    text = "Caf\u00e9 \u00dcn\u00efc\u00f6d\u00e9 \u65e5\u672c\u8a9e"
    marker = f"EventLens {text} {uuid.uuid4().hex}"
    subprocess.run(
        [
            "eventcreate",
            "/L",
            "APPLICATION",
            "/T",
            "INFORMATION",
            "/ID",
            "777",
            "/SO",
            "EventLensTest",
            "/D",
            marker,
        ],
        check=True,
        capture_output=True,
    )
    events = read_live("Application", days=1, max_events=200)
    texts = [" ".join(e.data.values()) for e in events]
    assert any(marker in text for text in texts), texts[:5]
