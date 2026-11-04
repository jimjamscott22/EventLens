import json
from pathlib import Path

import pytest

from eventlens.analyzer import analyze
from eventlens.catalog import Severity, lookup
from eventlens.cli import main
from eventlens.power import Battery, parse_battery_report
from eventlens.sources import SourceError

FIXTURE = Path(__file__).parent / "fixtures" / "battery_report.xml"
SAMPLE = Path(__file__).parent.parent / "examples" / "sample_week.xml"


def test_parse_battery_report():
    (battery,) = parse_battery_report(FIXTURE)
    assert battery == Battery("DELL 7XXYZ12", 50000, 27000, 612)
    assert battery.wear_percent == 46
    assert battery.health_percent == 54
    assert battery.severity == Severity.MEDIUM


@pytest.mark.parametrize(
    ("full", "severity"),
    [(100, Severity.INFO), (81, Severity.INFO), (79, Severity.LOW),
     (59, Severity.MEDIUM), (39, Severity.HIGH), (0, Severity.HIGH)],
)
def test_wear_thresholds(full, severity):
    assert Battery("b", 100, full).severity == severity


def test_capacity_above_design_is_zero_wear():
    assert Battery("b", 100, 110).wear_percent == 0


def test_bad_files(tmp_path):
    bad = tmp_path / "bad.xml"
    bad.write_text("not xml")
    with pytest.raises(SourceError):
        parse_battery_report(bad)
    empty = tmp_path / "empty.xml"
    empty.write_text("<BatteryReport><Batteries/></BatteryReport>")
    with pytest.raises(SourceError, match="no battery"):
        parse_battery_report(empty)
    with pytest.raises(SourceError):
        parse_battery_report(tmp_path / "missing.xml")


@pytest.mark.parametrize(
    ("provider", "event_id", "key"),
    [
        ("Microsoft-Windows-Kernel-Processor-Power", 37, "cpu-throttled"),
        ("Microsoft-Windows-Kernel-Power", 42, "sleep"),
        ("Microsoft-Windows-Kernel-Power", 507, "wake"),
        ("Microsoft-Windows-Power-Troubleshooter", 1, "wake"),
    ],
)
def test_power_events_are_recognised(make_event, provider, event_id, key):
    assert lookup(make_event(provider, event_id)).key == key


def test_sleep_events_are_normal_activity(make_event):
    events = [make_event("Microsoft-Windows-Kernel-Power", 42, minutes=i) for i in range(3)]
    analysis = analyze(events)
    assert analysis.problems == []
    assert analysis.normal[0].count == 3


def test_text_report_has_battery_section(capsys):
    assert main(["--file", str(SAMPLE), "--battery-report", str(FIXTURE)]) == 0
    out = capsys.readouterr().out
    assert "Battery health" in out
    flat = " ".join(out.split())
    assert "54% of original capacity (27,000 of 50,000 mWh), 612 charge cycles" in flat
    assert all(len(line) <= 75 for line in out.splitlines())


def test_markdown_and_json_battery(capsys):
    main(["--file", str(SAMPLE), "--battery-report", str(FIXTURE), "--format", "markdown"])
    assert "## Battery health" in capsys.readouterr().out
    main(["--file", str(SAMPLE), "--battery-report", str(FIXTURE), "--format", "json"])
    doc = json.loads(capsys.readouterr().out)
    assert doc["batteries"][0]["wear_percent"] == 46
    assert doc["batteries"][0]["severity"] == "medium"


def test_no_battery_report_leaves_output_unchanged(capsys):
    main(["--file", str(SAMPLE), "--format", "json"])
    assert "batteries" not in json.loads(capsys.readouterr().out)


def test_bad_battery_report_exits_2(tmp_path, capsys):
    bad = tmp_path / "bad.xml"
    bad.write_text("nope")
    assert main(["--file", str(SAMPLE), "--battery-report", str(bad)]) == 2
    assert "error" in capsys.readouterr().err
