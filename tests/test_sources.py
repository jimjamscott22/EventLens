from datetime import datetime, timezone
from pathlib import Path

import pytest

from eventlens import sources
from eventlens.models import Level
from eventlens.sources import (
    SourceError,
    parse_events_xml,
    parse_time,
    read_file,
    read_live,
)

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_XML = FIXTURES / "sample_events.xml"
SAMPLE_EVTX = FIXTURES / "application_small.evtx"

EVENT = """
<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
  <System>
    <Provider Name="{provider}"/>
    <EventID>{event_id}</EventID>
    <Level>2</Level>
    <TimeCreated SystemTime="2026-10-01T00:00:00Z"/>
  </System>
</Event>
"""


# --- Timestamps ---


def test_parse_time_trims_windows_seven_digit_fraction():
    parsed = parse_time("2026-10-01T08:15:30.1234567Z")
    assert parsed == datetime(2026, 10, 1, 8, 15, 30, 123456, tzinfo=timezone.utc)


def test_parse_time_without_zone_is_treated_as_utc():
    assert parse_time("2026-10-01T08:15:30").tzinfo == timezone.utc


def test_parse_time_converts_offsets_to_utc():
    parsed = parse_time("2026-10-01T10:00:00+02:00")
    assert parsed == datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)


# --- XML parsing ---


def test_xml_export_parses_valid_events_and_skips_malformed_ones():
    events = read_file(SAMPLE_XML)
    assert [(e.provider, e.event_id) for e in events] == [
        ("Microsoft-Windows-Kernel-Power", 41),
        ("EventLog", 6008),
        ("Application Error", 1000),
    ]


def test_xml_event_fields():
    power = read_file(SAMPLE_XML)[0]
    assert power.level is Level.CRITICAL
    assert power.channel == "System"
    assert power.computer == "TEST-PC"
    assert power.data["BugcheckCode"] == "159"
    assert power.message.startswith("The system has rebooted")
    assert power.is_problem


def test_event_id_qualifiers_are_ignored():
    assert read_file(SAMPLE_XML)[1].event_id == 6008


def test_unnamed_data_fields_get_positional_names():
    crash = read_file(SAMPLE_XML)[2]
    assert crash.data == {"param1": "game.exe", "param2": "1.2.0.0"}


def test_bare_wevtutil_stream_without_root_element():
    stream = EVENT.format(provider="A", event_id=1) + EVENT.format(provider="B", event_id=2)
    events = parse_events_xml(stream)
    assert [(e.provider, e.event_id) for e in events] == [("A", 1), ("B", 2)]


def test_empty_input_gives_no_events():
    assert parse_events_xml("") == []
    assert parse_events_xml('<?xml version="1.0"?>\n') == []


def test_invalid_xml_raises_source_error():
    with pytest.raises(SourceError, match="Could not parse"):
        parse_events_xml("<Event><System>")


def test_xml_that_is_neither_utf8_nor_utf16_raises_source_error(tmp_path):
    path = tmp_path / "truncated.xml"
    # Invalid UTF-8, and an odd number of bytes is invalid UTF-16.
    path.write_bytes(b"\xff\xfe<\x00E\x00\xff")
    with pytest.raises(SourceError, match="not a UTF-8 or UTF-16 text file"):
        read_file(path)


def test_unreadable_xml_raises_source_error(tmp_path, monkeypatch):
    path = tmp_path / "locked.xml"
    path.write_text("<Events/>")

    def deny(self):
        raise PermissionError("Permission denied")

    monkeypatch.setattr(Path, "read_bytes", deny)
    with pytest.raises(SourceError, match="Could not read"):
        read_file(path)


def test_utf16_xml_export(tmp_path):
    path = tmp_path / "export.xml"
    path.write_text(SAMPLE_XML.read_text(encoding="utf-8"), encoding="utf-16")
    assert len(read_file(path)) == 3


# --- .evtx files (must pass on Windows, macOS, and Linux) ---


def test_evtx_file_is_read_on_any_platform():
    events = read_file(SAMPLE_EVTX)
    assert len(events) == 17
    first = events[0]
    assert (first.provider, first.event_id) == ("SecurityCenter", 1)
    assert first.level is Level.INFORMATION
    assert first.channel == "Application"
    assert first.computer == "DESKTOP-0HIJB49"
    assert first.time == datetime(2021, 3, 31, 23, 51, 45, 18767, tzinfo=timezone.utc)


def test_evtx_extension_is_case_insensitive(tmp_path):
    path = tmp_path / "APP.EVTX"
    path.write_bytes(SAMPLE_EVTX.read_bytes())
    assert len(read_file(path)) == 17


def test_non_evtx_file_with_evtx_extension_raises_source_error(tmp_path):
    path = tmp_path / "fake.evtx"
    path.write_text("not an event log")
    with pytest.raises(SourceError, match="not a readable .evtx file"):
        read_file(path)


class FakeRecords:
    """Mimics the real parser's iterator, which raises for a damaged record
    and then carries on with the next one."""

    def __init__(self, items):
        self.items = list(items)

    def __iter__(self):
        return self

    def __next__(self):
        if not self.items:
            raise StopIteration
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_unreadable_evtx_records_are_skipped_and_logged(monkeypatch, caplog):
    good = {"data": EVENT.format(provider="Good", event_id=1)}
    items = [good, RuntimeError("Failed to parse chunk header"), {"data": "<Event"}, good]

    class FakeParser:
        def __init__(self, path):
            pass

        def records(self):
            return FakeRecords(items)

    monkeypatch.setattr(sources, "PyEvtxParser", FakeParser)
    with caplog.at_level("WARNING", logger="eventlens.sources"):
        events = sources.read_evtx(Path("damaged.evtx"))
    assert [e.provider for e in events] == ["Good", "Good"]
    assert "Skipped 2 unreadable record(s)" in caplog.text


# --- Errors ---


def test_missing_file_raises_source_error(tmp_path):
    with pytest.raises(SourceError, match="File not found"):
        read_file(tmp_path / "missing.evtx")


def test_directory_is_not_treated_as_a_file(tmp_path):
    with pytest.raises(SourceError, match="File not found"):
        read_file(tmp_path)


def test_live_reading_explains_it_needs_windows(monkeypatch):
    monkeypatch.setattr(sources.sys, "platform", "linux")
    with pytest.raises(SourceError, match="only works on Windows"):
        read_live("System", days=7, max_events=100)
