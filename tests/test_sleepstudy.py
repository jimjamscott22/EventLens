import json
from pathlib import Path

import pytest

from eventlens.catalog import Severity
from eventlens.cli import main
from eventlens.power import parse_battery_report
from eventlens.sleepstudy import parse_sleepstudy
from eventlens.sources import SourceError

FIXTURES = Path(__file__).parent / "fixtures"
# Trimmed copies of reports made by powercfg on a real desktop PC (names removed).
DESKTOP_STUDY = FIXTURES / "sleepstudy_desktop.xml"
DESKTOP_BATTERY = FIXTURES / "battery_report_desktop.xml"
SAMPLE = Path(__file__).parent.parent / "examples" / "sample_week.xml"


def battery_study(tmp_path, entry=100000, exit_=99000, full=100000, ac="0"):
    """The desktop study turned into a laptop's: first session on battery."""
    text = DESKTOP_STUDY.read_text(encoding="utf-8")
    head, one, two = text.split("<ScenarioInstance ", 2)
    one = (
        one.replace('Ac="1"', f'Ac="{ac}"', 1)
        .replace('EntryRemainingCapacity="0"', f'EntryRemainingCapacity="{entry}"', 1)
        .replace('ExitRemainingCapacity="0"', f'ExitRemainingCapacity="{exit_}"', 1)
        .replace('EntryFullCapacity="0"', f'EntryFullCapacity="{full}"', 1)
    )
    path = tmp_path / "study.xml"
    path.write_text(
        head + "<ScenarioInstance " + one + "<ScenarioInstance " + two, encoding="utf-8"
    )
    return path


def test_parse_real_desktop_study():
    study = parse_sleepstudy(DESKTOP_STUDY)
    assert len(study.sessions) == 2
    first, second = study.sessions
    assert first.kind == "Screen Off"
    assert first.duration.total_seconds() == pytest.approx(729.2, abs=0.1)
    assert first.on_ac
    assert first.enter_reason == "Video Idle Timeout"
    assert first.exit_reason == "Input Mouse"
    assert [o.name for o in first.offenders] == [
        "Unidentified Driver (Sleep Idle State Disabled)"
    ]
    assert "claude.exe (Electron)" in [o.name for o in second.offenders]


def test_desktop_has_no_battery_drain_but_has_an_offender_finding():
    study = parse_sleepstudy(DESKTOP_STUDY)
    assert study.on_battery == []
    (finding,) = study.findings
    assert finding.severity == Severity.LOW
    assert "busy in 2 of 2 sessions" in finding.detail


@pytest.mark.parametrize(
    ("lost", "severity"),
    [(100, None), (300, Severity.MEDIUM), (1000, Severity.HIGH), (10000, Severity.HIGH)],
)
def test_drain_severity(tmp_path, lost, severity):
    # The first session is about 12 minutes: losing 0.1% of the battery is 0.5%/hour.
    study = parse_sleepstudy(battery_study(tmp_path, exit_=100000 - lost))
    drain = [f for f in study.findings if "drains" in f.title]
    assert [f.severity for f in drain] == ([severity] if severity else [])


def test_drain_rate_value(tmp_path):
    study = parse_sleepstudy(battery_study(tmp_path, exit_=99000))
    session = study.on_battery[0]
    # 1% of the battery over 729 seconds
    assert session.drain_percent_per_hour == pytest.approx(1 / (729.21 / 3600), rel=0.01)


def test_ac_session_has_no_drain(tmp_path):
    study = parse_sleepstudy(battery_study(tmp_path, exit_=50000, ac="1"))
    assert study.on_battery == []


def test_bad_files(tmp_path):
    bad = tmp_path / "bad.xml"
    bad.write_text("nope")
    with pytest.raises(SourceError):
        parse_sleepstudy(bad)
    wrong = tmp_path / "wrong.xml"
    wrong.write_text("<BatteryReport/>")
    with pytest.raises(SourceError, match="not a sleep study"):
        parse_sleepstudy(wrong)
    with pytest.raises(SourceError):
        parse_sleepstudy(tmp_path / "missing.xml")


def test_real_desktop_battery_report_has_no_battery():
    assert parse_battery_report(DESKTOP_BATTERY) == []


def test_text_report_for_desktop(capsys):
    args = ["--file", str(SAMPLE), "--battery-report", str(DESKTOP_BATTERY)]
    assert main([*args, "--sleepstudy", str(DESKTOP_STUDY)]) == 0
    out = capsys.readouterr().out
    assert "normal for a desktop PC" in out
    assert "Sleep and standby" in out
    assert "2 screen-off or standby sessions." in out
    assert all(len(line) <= 75 for line in out.splitlines())


def test_markdown_and_json(capsys):
    main(["--file", str(SAMPLE), "--sleepstudy", str(DESKTOP_STUDY), "--format", "markdown"])
    assert "## Sleep and standby" in capsys.readouterr().out
    main(["--file", str(SAMPLE), "--sleepstudy", str(DESKTOP_STUDY), "--format", "json"])
    doc = json.loads(capsys.readouterr().out)
    assert doc["sleep_study"]["sessions"] == 2
    assert doc["sleep_study"]["findings"][0]["severity"] == "low"
    assert "batteries" not in doc


def test_sleepstudy_does_not_change_exit_code(tmp_path):
    path = battery_study(tmp_path, exit_=50000)  # a HIGH drain finding
    base = ["--file", str(SAMPLE), "--fail-on", "critical"]
    assert main(base) == main([*base, "--sleepstudy", str(path)])


def test_bad_sleepstudy_exits_2(tmp_path, capsys):
    bad = tmp_path / "bad.xml"
    bad.write_text("nope")
    assert main(["--file", str(SAMPLE), "--sleepstudy", str(bad)]) == 2
