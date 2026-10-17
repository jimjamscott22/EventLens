"""Read events from exported XML files or live from Windows via wevtutil."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from eventlens.models import Event, Level

NS = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}

DEFAULT_CHANNELS = ("System", "Application")

_XML_DECL = re.compile(r"^\s*<\?xml[^>]*\?>", re.IGNORECASE)
# Windows timestamps carry 7 fractional digits; Python accepts at most 6.
_FRACTION = re.compile(r"\.(\d{6})\d+")


class SourceError(Exception):
    """Raised when events cannot be read."""


def parse_time(value: str) -> datetime:
    """Parse a Windows SystemTime string into an aware UTC datetime."""
    cleaned = _FRACTION.sub(r".\1", value.strip())
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    parsed = datetime.fromisoformat(cleaned)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _text(element: ET.Element | None) -> str:
    return (element.text or "").strip() if element is not None else ""


def _parse_event(node: ET.Element) -> Event | None:
    system = node.find("e:System", NS)
    if system is None:
        return None

    provider_node = system.find("e:Provider", NS)
    provider = ""
    if provider_node is not None:
        provider = provider_node.get("Name") or provider_node.get("EventSourceName") or ""

    try:
        event_id = int(_text(system.find("e:EventID", NS)))
    except ValueError:
        return None

    try:
        level = Level.from_value(int(_text(system.find("e:Level", NS)) or 4))
    except ValueError:
        level = Level.INFORMATION

    time_node = system.find("e:TimeCreated", NS)
    raw_time = time_node.get("SystemTime", "") if time_node is not None else ""
    try:
        time = parse_time(raw_time)
    except ValueError:
        return None

    data: dict[str, str] = {}
    for index, item in enumerate(node.iterfind("e:EventData/e:Data", NS), start=1):
        data[item.get("Name") or f"param{index}"] = _text(item)

    message = _text(node.find("e:RenderingInfo/e:Message", NS))

    return Event(
        provider=provider,
        event_id=event_id,
        level=level,
        time=time,
        channel=_text(system.find("e:Channel", NS)),
        computer=_text(system.find("e:Computer", NS)),
        message=message,
        data=data,
    )


def parse_events_xml(text: str) -> list[Event]:
    """Parse events from XML.

    Accepts a file with an ``<Events>`` root element, or the bare stream of
    ``<Event>`` elements that ``wevtutil qe`` prints by default.
    """
    body = _XML_DECL.sub("", text, count=1).strip()
    if not body:
        return []
    if not body.startswith("<Events"):
        body = f"<Events>{body}</Events>"
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise SourceError(f"Could not parse event XML: {exc}") from exc

    events = []
    for node in root.iter(f"{{{NS['e']}}}Event"):
        event = _parse_event(node)
        if event is not None:
            events.append(event)
    return events


def _run_wevtutil(args: list[str]) -> str:
    exe = shutil.which("wevtutil")
    if exe is None:
        raise SourceError(
            "wevtutil was not found. Live reading only works on Windows; "
            "use --file with an exported .xml log instead."
        )
    result = subprocess.run(
        [exe, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise SourceError(f"wevtutil failed: {detail}")
    return result.stdout


def read_file(path: Path) -> list[Event]:
    """Read events from an exported log file (.xml, or .evtx on Windows)."""
    if not path.exists():
        raise SourceError(f"File not found: {path}")
    if path.suffix.lower() == ".evtx":
        output = _run_wevtutil(
            ["qe", str(path), "/lf:true", "/f:RenderedXml", "/e:Events"]
        )
        return parse_events_xml(output)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        # Event Viewer sometimes saves XML as UTF-16.
        text = path.read_text(encoding="utf-16")
    return parse_events_xml(text)


def read_live(channel: str, days: int, max_events: int) -> list[Event]:
    """Query a live Windows event log channel for the last ``days`` days."""
    if sys.platform != "win32":
        raise SourceError(
            "Reading live event logs only works on Windows. "
            "Use --file to analyse an exported .xml log on this machine."
        )
    milliseconds = days * 24 * 60 * 60 * 1000
    query = f"*[System[TimeCreated[timediff(@SystemTime) <= {milliseconds}]]]"
    output = _run_wevtutil(
        [
            "qe",
            channel,
            f"/q:{query}",
            "/f:RenderedXml",
            "/rd:true",
            f"/c:{max_events}",
            "/e:Events",
        ]
    )
    return parse_events_xml(output)
