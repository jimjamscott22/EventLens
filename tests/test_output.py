import json
from pathlib import Path

import pytest

from eventlens import cli
from eventlens.cli import main

ROOT = Path(__file__).parent.parent
SAMPLE_WEEK = str(ROOT / "examples" / "sample_week.xml")


def test_output_writes_the_report_to_the_file_and_not_to_stdout(capsys, tmp_path):
    target = tmp_path / "report.txt"
    assert main(["--file", SAMPLE_WEEK, "--utc", "--output", str(target)]) == 0
    assert capsys.readouterr().out == ""

    assert main(["--file", SAMPLE_WEEK, "--utc"]) == 0
    assert target.read_text(encoding="utf-8") == capsys.readouterr().out


@pytest.mark.parametrize("fmt", ["text", "json", "markdown"])
def test_output_works_with_every_format(capsys, tmp_path, fmt):
    target = tmp_path / "report"
    assert main(["--file", SAMPLE_WEEK, "--format", fmt, "--output", str(target)]) == 0
    content = target.read_text(encoding="utf-8")
    assert "EventLens report for TEST-PC" in content or json.loads(content)["computers"]


def test_output_overwrites_an_existing_file(tmp_path):
    target = tmp_path / "report.txt"
    target.write_text("old contents " * 1000, encoding="utf-8")
    assert main(["--file", SAMPLE_WEEK, "--utc", "--output", str(target)]) == 0
    assert "old contents" not in target.read_text(encoding="utf-8")


def test_output_is_utf8_whatever_the_console_uses(make_event, monkeypatch, tmp_path):
    event = make_event("Application Error", 1000, data={"param1": "café日本.exe"})
    monkeypatch.setattr(cli, "read_file", lambda path: [event])
    target = tmp_path / "report.md"
    assert main(["--file", "x.evtx", "--format", "markdown", "--output", str(target)]) == 0
    assert "café日本.exe" in target.read_bytes().decode("utf-8")


def test_output_file_never_contains_color_codes(tmp_path):
    target = tmp_path / "report.txt"
    assert main(["--file", SAMPLE_WEEK, "--color", "always", "--output", str(target)]) == 0
    assert "\x1b" not in target.read_text(encoding="utf-8")


def test_unwritable_output_exits_2_with_a_message(capsys, tmp_path):
    target = tmp_path / "missing-folder" / "report.txt"
    assert main(["--file", SAMPLE_WEEK, "--output", str(target)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "eventlens: error: could not write the report to" in captured.err
    assert "missing-folder" in captured.err


def test_output_that_is_a_folder_exits_2(capsys, tmp_path):
    assert main(["--file", SAMPLE_WEEK, "--output", str(tmp_path)]) == 2
    assert "could not write the report" in capsys.readouterr().err
