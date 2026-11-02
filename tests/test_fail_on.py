from pathlib import Path

import pytest

from eventlens import cli
from eventlens.cli import EXIT_FINDINGS, main

ROOT = Path(__file__).parent.parent
SAMPLE_WEEK = str(ROOT / "examples" / "sample_week.xml")

DNS = ("Microsoft-Windows-DNS-Client", 1014)  # Low
DCOM = ("Microsoft-Windows-DistributedCOM", 10016)  # Info
MEMORY = ("Microsoft-Windows-WHEA-Logger", 47)  # Low, High at 10+
DISK_BAD_BLOCK = ("disk", 7)  # Critical
UNKNOWN = ("Some-Provider", 9999)  # not in the catalog


def run_with(monkeypatch, events, *args):
    monkeypatch.setattr(cli, "read_file", lambda path: events)
    return main(["--file", "x.evtx", *args])


def test_exit_code_for_findings_is_1():
    assert EXIT_FINDINGS == 1


def test_without_the_flag_problems_do_not_change_the_exit_code(capsys):
    assert main(["--file", SAMPLE_WEEK]) == 0


@pytest.mark.parametrize("level", ["critical", "high", "medium", "low"])
def test_sample_week_fails_at_every_level(capsys, level):
    # It has a finding of each severity.
    assert main(["--file", SAMPLE_WEEK, "--fail-on", level]) == 1


def test_report_is_still_printed_when_failing(capsys):
    assert main(["--file", SAMPLE_WEEK, "--fail-on", "low"]) == 1
    assert "Verdict: Serious problems found." in capsys.readouterr().out


def test_finding_at_the_threshold_fails(make_event, monkeypatch):
    events = [make_event(*DNS)]
    assert run_with(monkeypatch, events, "--fail-on", "low") == 1


def test_finding_below_the_threshold_passes(make_event, monkeypatch):
    events = [make_event(*DNS)]
    assert run_with(monkeypatch, events, "--fail-on", "medium") == 0


def test_finding_above_the_threshold_fails(make_event, monkeypatch):
    events = [make_event(*DISK_BAD_BLOCK)]
    assert run_with(monkeypatch, events, "--fail-on", "low") == 1


def test_info_findings_never_fail(make_event, monkeypatch):
    events = [make_event(*DCOM, minutes=i) for i in range(50)]
    assert run_with(monkeypatch, events, "--fail-on", "low") == 0


def test_unrecognised_events_never_fail(make_event, monkeypatch):
    events = [make_event(*UNKNOWN, minutes=i) for i in range(50)]
    assert run_with(monkeypatch, events, "--fail-on", "low") == 0


def test_escalated_severity_is_what_counts(make_event, monkeypatch):
    few = [make_event(*MEMORY, minutes=i) for i in range(9)]
    many = [make_event(*MEMORY, minutes=i) for i in range(10)]
    assert run_with(monkeypatch, few, "--fail-on", "high") == 0
    assert run_with(monkeypatch, many, "--fail-on", "high") == 1


def test_no_events_passes(monkeypatch):
    assert run_with(monkeypatch, [], "--fail-on", "low") == 0


@pytest.mark.parametrize("fmt", ["json", "markdown"])
def test_works_with_every_format(capsys, fmt):
    assert main(["--file", SAMPLE_WEEK, "--format", fmt, "--fail-on", "high"]) == 1
    assert capsys.readouterr().out


def test_report_is_still_written_to_the_output_file(tmp_path):
    target = tmp_path / "report.txt"
    assert main(["--file", SAMPLE_WEEK, "--fail-on", "high", "--output", str(target)]) == 1
    assert "Verdict: Serious problems found." in target.read_text(encoding="utf-8")


def test_an_unwritable_output_is_still_an_error_not_a_finding(tmp_path, capsys):
    target = tmp_path / "missing-folder" / "report.txt"
    assert main(["--file", SAMPLE_WEEK, "--fail-on", "high", "--output", str(target)]) == 2


@pytest.mark.parametrize("value", ["info", "severe", "HIGH", ""])
def test_unknown_severity_is_an_argument_error(value, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--file", SAMPLE_WEEK, "--fail-on", value])
    assert exc.value.code == 2
