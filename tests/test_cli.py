from pathlib import Path

import pytest

from eventlens import __version__, cli
from eventlens.cli import main

ROOT = Path(__file__).parent.parent
SAMPLE_WEEK = str(ROOT / "examples" / "sample_week.xml")
SAMPLE_EVTX = str(Path(__file__).parent / "fixtures" / "application_small.evtx")


def test_file_report(capsys):
    assert main(["--file", SAMPLE_WEEK, "--utc"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("EventLens report for TEST-PC\n")
    assert "Verdict: Serious problems found." in out


def test_days_counts_back_from_newest_event_in_file(capsys):
    # The sample's newest event is 7 Oct 23:00, so one day back is 6 Oct 23:00.
    # An event sits exactly on that edge, and the window includes it.
    main(["--file", SAMPLE_WEEK, "--utc", "--days", "1"])
    out = capsys.readouterr().out
    assert "Period: 6 Oct 2026 23:00 to 7 Oct 2026 23:00 (UTC)" in out
    assert "Blue screen crash" not in out


def test_default_window_excludes_old_events(capsys):
    main(["--file", SAMPLE_WEEK, "--utc"])
    out = capsys.readouterr().out
    assert "Events read: 101 (98 in this period)" in out
    assert "oldapp.exe" not in out


def test_multiple_files_are_combined(capsys):
    assert main(["--file", SAMPLE_WEEK, "--file", SAMPLE_EVTX, "--days", "10000"]) == 0
    out = capsys.readouterr().out
    assert "TEST-PC and 1 other" in out
    assert "Events read: 118" in out


def test_evtx_file_report(capsys):
    assert main(["--file", SAMPLE_EVTX]) == 0
    assert "No significant problems found." in capsys.readouterr().out


def test_include_warnings(capsys):
    main(["--file", SAMPLE_WEEK, "--utc", "--include-warnings"])
    assert "e1iexpress 27 (Warning)" in capsys.readouterr().out


def test_missing_file_exits_2(capsys, tmp_path):
    assert main(["--file", str(tmp_path / "nope.evtx")]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "eventlens: error: File not found" in captured.err


def test_live_mode_off_windows_exits_2_with_hint(capsys, monkeypatch):
    monkeypatch.setattr(cli.sys, "platform", "linux")
    assert main([]) == 2
    assert "use --file" in capsys.readouterr().err.lower()


def test_live_mode_reads_each_channel(monkeypatch, capsys):
    calls = []

    def fake_read_live(channel, days, max_events):
        calls.append((channel, days, max_events))
        return []

    monkeypatch.setattr(cli, "read_live", fake_read_live)
    assert main(["--days", "3"]) == 0
    assert calls == [("System", 3, 5000), ("Application", 3, 5000)]

    calls.clear()
    main(["--channel", "Setup", "--max-events", "50"])
    assert calls == [("Setup", 7, 50)]


@pytest.mark.parametrize("flag", [["--channel", "System"], ["--max-events", "10"]])
def test_live_only_flags_are_rejected_with_files(flag, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--file", SAMPLE_WEEK, *flag])
    assert exc.value.code == 2
    assert "only apply to live logs" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["0", "-1", "abc"])
def test_days_must_be_positive(value, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--days", value])
    assert exc.value.code == 2


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"eventlens {__version__}"
