"""Regression coverage retained from the superseded standalone implementation."""

import json
from dataclasses import replace
from datetime import timedelta

import pytest
from test_sleepstudy import DESKTOP_STUDY, battery_study

from eventlens.cli import main
from eventlens.sleepstudy import parse_sleepstudy
from eventlens.sources import SourceError


@pytest.mark.parametrize("fmt", ["text", "markdown", "json"])
def test_standalone_does_not_read_logs(monkeypatch, capsys, fmt):
    def forbidden(*args, **kwargs):
        pytest.fail("read event logs in standalone mode")

    monkeypatch.setattr("eventlens.cli._read_events", forbidden)
    assert main(["--sleepstudy", str(DESKTOP_STUDY), "--format", fmt, "--fail-on", "low"]) == 0
    out = capsys.readouterr().out
    assert "Verdict:" not in out
    assert "No events found" not in out
    if fmt == "json":
        doc = json.loads(out)
        assert doc["report_type"] == "sleep_diagnostics"
        assert "verdict" not in doc
        assert doc["sleep_study"]["sessions"] == 2
    elif fmt == "text":
        assert all(len(line) <= 75 for line in out.splitlines())


@pytest.mark.parametrize("option", ["--timeline", "--max-events"])
def test_standalone_rejects_event_only_options(option):
    args = ["--sleepstudy", str(DESKTOP_STUDY), option]
    if option == "--max-events":
        args.append("5")
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2


def test_explicit_channel_still_reads_logs(monkeypatch, capsys):
    calls = []

    def live(channel, **kwargs):
        calls.append(channel)
        return []

    monkeypatch.setattr("eventlens.cli.read_live", live)
    assert main(["--sleepstudy", str(DESKTOP_STUDY), "--channel", "System"]) == 0
    assert calls == ["System"]
    assert "Sleep and standby" in capsys.readouterr().out


@pytest.mark.parametrize(
    "changes",
    [
        {"entry_capacity": None},
        {"exit_capacity": None},
        {"full_capacity": None},
        {"full_capacity": 0},
        {"full_capacity": -1},
        {"exit_capacity": -1},
        {"entry_capacity": 50, "exit_capacity": 100},
        {"on_ac": True},
        {"duration": timedelta(0)},
        {"kind": "Active"},
        {"kind": "Shutdown"},
    ],
)
def test_unknown_or_ineligible_drain(tmp_path, changes):
    session = parse_sleepstudy(battery_study(tmp_path)).sessions[0]
    assert replace(session, **changes).drain_percent_per_hour is None


def test_missing_capacity_does_not_become_zero(tmp_path):
    path = battery_study(tmp_path)
    path.write_text(path.read_text().replace('ExitRemainingCapacity="99000"', ""))
    session = parse_sleepstudy(path).sessions[0]
    assert session.exit_capacity is None
    assert session.drain_percent_per_hour is None


def test_unknown_power_source_not_graded(tmp_path):
    path = battery_study(tmp_path, ac="unknown")
    assert parse_sleepstudy(path).sessions[0].drain_percent_per_hour is None


@pytest.mark.parametrize("duration", ["-1", "bad", "1" * 400])
def test_invalid_duration_is_source_error(tmp_path, duration):
    path = tmp_path / "invalid.xml"
    text = DESKTOP_STUDY.read_text(encoding="utf-8")
    import re

    text = re.sub(r' Duration="[^"]*"', f' Duration="{duration}"', text)
    path.write_text(text, encoding="utf-8")
    with pytest.raises(SourceError):
        parse_sleepstudy(path)


def test_standalone_output_file(tmp_path):
    output = tmp_path / "report.json"
    assert (
        main(["--sleepstudy", str(DESKTOP_STUDY), "--format", "json", "--output", str(output)]) == 0
    )
    assert json.loads(output.read_text())["sleep_study"]["sessions"] == 2
