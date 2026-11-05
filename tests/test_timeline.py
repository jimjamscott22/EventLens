import json
from datetime import timedelta
from pathlib import Path

from eventlens.cli import main
from eventlens.models import Level
from eventlens.timeline import build_timeline, format_uptime

SAMPLE = Path(__file__).parent.parent / "examples" / "sample_week.xml"
KG = "Microsoft-Windows-Kernel-General"
KP = "Microsoft-Windows-Kernel-Power"


def boot(make_event, minutes):
    return [
        make_event(KG, 12, minutes=minutes, level=Level.INFORMATION),
        make_event("EventLog", 6005, minutes=minutes, level=Level.INFORMATION),
    ]


def test_one_boot_writes_two_events_but_counts_once(make_event):
    timeline = build_timeline(boot(make_event, 0))
    assert len(timeline.runs) == 1


def test_clean_shutdown(make_event):
    events = [
        *boot(make_event, 0),
        make_event(KG, 13, minutes=120, level=Level.INFORMATION),
        make_event("EventLog", 6006, minutes=120, level=Level.INFORMATION),
        *boot(make_event, 130),
    ]
    first, second = build_timeline(events).runs
    assert first.ended_by == "clean"
    assert first.uptime == timedelta(minutes=120)
    assert second.ended_by == "open"


def test_crash_run_has_kind_and_lead_up(make_event):
    events = [
        *boot(make_event, 0),
        make_event("Display", 4101, minutes=96, level=Level.WARNING),
        make_event("Display", 4101, minutes=97, level=Level.WARNING),
        make_event("Application Error", 1000, minutes=50),  # too early to count
        make_event("Some", 5, minutes=98, level=Level.INFORMATION),  # not a problem
        *boot(make_event, 100),
        make_event(KP, 41, minutes=100.2, level=Level.CRITICAL, data={"BugcheckCode": "159"}),
    ]
    first, _ = build_timeline(events).runs
    assert first.ended_by == "crash"
    assert first.crash_title == "Blue screen crash"
    assert "DRIVER_POWER_STATE_FAILURE" in first.crash_detail
    assert first.lead_up == [("Display driver stopped responding and recovered", 2)]
    assert first.uptime == timedelta(minutes=98)


def test_crash_events_are_not_their_own_lead_up(make_event):
    events = [
        *boot(make_event, 0),
        *boot(make_event, 10),
        make_event(KP, 41, minutes=10.1, level=Level.CRITICAL, data={"BugcheckCode": "0"}),
    ]
    first, _ = build_timeline(events).runs
    assert first.lead_up == []
    assert first.crash_title == "Sudden power loss or hard freeze"


def test_computers_are_separate(make_event):
    events = [
        make_event(KG, 12, minutes=0, level=Level.INFORMATION, computer="A"),
        make_event(KG, 12, minutes=5, level=Level.INFORMATION, computer="B"),
        make_event(KG, 13, minutes=60, level=Level.INFORMATION, computer="A"),
    ]
    runs = {r.computer: r for r in build_timeline(events).runs}
    assert runs["A"].ended_by == "clean"
    assert runs["B"].ended_by == "open"


def test_since_drops_earlier_boots(make_event):
    events = [*boot(make_event, 0), *boot(make_event, 300)]
    timeline = build_timeline(events, since=events[0].time + timedelta(minutes=100))
    assert len(timeline.runs) == 1


def test_format_uptime():
    assert format_uptime(timedelta(minutes=5)) == "5m"
    assert format_uptime(timedelta(minutes=125)) == "2h 05m"
    assert format_uptime(timedelta(days=2, hours=3)) == "2d 3h"


def test_text_report(capsys):
    assert main(["--file", str(SAMPLE), "--utc", "--timeline"]) == 0
    out = capsys.readouterr().out
    assert "Boots and uptime" in out
    assert "4 starts in this period, 3 ended in a crash." in out
    assert "blue screen crash" in out
    assert "Just before:" in out
    assert all(len(line) <= 75 for line in out.splitlines())


def test_timeline_is_off_by_default(capsys):
    main(["--file", str(SAMPLE), "--utc"])
    assert "Boots and uptime" not in capsys.readouterr().out


def test_markdown_and_json(capsys):
    main(["--file", str(SAMPLE), "--timeline", "--format", "markdown"])
    assert "## Boots and uptime" in capsys.readouterr().out
    main(["--file", str(SAMPLE), "--timeline", "--format", "json"])
    doc = json.loads(capsys.readouterr().out)
    assert doc["timeline"]["starts"] == 4
    assert doc["timeline"]["crashes"] == 3
    run = doc["timeline"]["runs"][0]
    assert run["ended_by"] == "crash"
    assert run["crash"] == "Forced power-off"
    assert run["uptime_seconds"] > 0


def test_top_limits_runs(capsys):
    main(["--file", str(SAMPLE), "--timeline", "--top", "2", "--utc"])
    assert "...and 2 earlier" in capsys.readouterr().out
