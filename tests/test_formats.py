import json
import os
from pathlib import Path

import pytest

from eventlens import __version__
from eventlens.analyzer import analyze
from eventlens.cli import main
from eventlens.report_json import render_json
from eventlens.report_markdown import render_markdown

ROOT = Path(__file__).parent.parent
SAMPLE_WEEK = ROOT / "examples" / "sample_week.xml"
GOLDEN_MD = Path(__file__).parent / "fixtures" / "sample_week_report.md"


def run_json(capsys, *extra):
    assert main(["--file", str(SAMPLE_WEEK), "--format", "json", *extra]) == 0
    return json.loads(capsys.readouterr().out)


# --- JSON ---------------------------------------------------------------


def test_json_top_level_fields(capsys):
    doc = run_json(capsys)
    assert doc["schema_version"] == 1
    assert doc["eventlens_version"] == __version__
    assert doc["computers"] == ["TEST-PC"]
    assert doc["channels"] == ["Application", "System"]
    assert doc["events_read"] == 101
    assert doc["events_in_window"] == 98
    assert doc["verdict"] == "Serious problems found."
    assert doc["headline"].startswith("This PC shut down unexpectedly 4 times")
    assert doc["period"] == {"start": "2026-10-01T00:00:00Z", "end": "2026-10-07T23:00:00Z"}


def test_json_finding_fields(capsys):
    doc = run_json(capsys)
    blue = next(f for f in doc["findings"] if f["title"] == "Blue screen crash")
    assert blue["id"]
    assert blue["severity"] == "critical"
    assert blue["count"] == 3
    assert blue["first"].endswith("Z") and blue["last"] == "2026-10-06T21:02:20Z"
    assert blue["meaning"] and blue["action"]
    assert blue["details"][0]["count"] == 3
    assert "DRIVER_POWER_STATE_FAILURE" in blue["details"][0]["detail"]
    assert "sample" not in blue


def test_json_findings_are_problems_and_normal_is_separate(capsys):
    doc = run_json(capsys)
    assert all(f["severity"] != "info" for f in doc["findings"])
    assert doc["normal"]
    assert all(f["severity"] == "info" for f in doc["normal"])


def test_json_lists_every_unrecognised_group_whatever_top_says(capsys):
    doc = run_json(capsys, "--top", "1")
    assert len(doc["unrecognised"]) == 3
    assert set(doc["unrecognised"][0]) == {"provider", "event_id", "level", "count", "last"}


def test_json_lists_every_detail(make_event):
    # The text report shows 3 details and "...and N more"; JSON keeps them all.
    events = [
        make_event("Application Error", 1000, minutes=i, data={"param1": f"app{i}.exe"})
        for i in range(5)
    ]
    doc = json.loads(render_json(analyze(events)))
    assert len(doc["findings"][0]["details"]) == 5


def test_json_verbose_adds_the_raw_sample(capsys):
    doc = run_json(capsys, "--verbose")
    blue = next(f for f in doc["findings"] if f["title"] == "Blue screen crash")
    assert set(blue["sample"]) == {"provider", "event_id", "time", "data"}


def test_json_times_are_utc_whatever_utc_flag_says(capsys):
    assert run_json(capsys, "--utc")["period"] == run_json(capsys)["period"]


def test_json_with_no_events():
    doc = json.loads(render_json(analyze([])))
    assert doc["period"] is None
    assert doc["findings"] == [] and doc["normal"] == [] and doc["unrecognised"] == []
    assert doc["events_read"] == 0


def test_json_ends_with_newline(make_event):
    assert render_json(analyze([make_event("disk", 7)])).endswith("\n")


def test_json_is_pure_ascii_so_no_console_or_redirect_encoding_can_damage_it(make_event):
    # A redirected stdout on Windows often uses a legacy code page. Non-ASCII
    # text is escaped (\uXXXX), so the bytes are the same in every encoding
    # and a JSON parser still gets the original text back.
    name = "caf\u00e9\u65e5\u672c\U0001f600.exe"
    event = make_event("Application Error", 1000, data={"param1": name})
    text = render_json(analyze([event]))
    assert text.isascii()
    assert json.loads(text)["findings"][0]["details"][0]["detail"] == name


# --- Markdown -----------------------------------------------------------


def test_sample_week_markdown_matches_golden_file(capsys):
    """Regenerate after an intended change with:
    EVENTLENS_UPDATE_GOLDEN=1 uv run pytest tests/test_formats.py
    """
    assert main(["--file", str(SAMPLE_WEEK), "--utc", "--format", "markdown"]) == 0
    output = capsys.readouterr().out
    if os.environ.get("EVENTLENS_UPDATE_GOLDEN"):
        GOLDEN_MD.write_text(output, encoding="utf-8", newline="\n")
    assert output == GOLDEN_MD.read_text(encoding="utf-8")


def test_markdown_structure(capsys):
    main(["--file", str(SAMPLE_WEEK), "--utc", "--format", "markdown"])
    out = capsys.readouterr().out
    assert out.startswith("# EventLens report for TEST-PC\n")
    assert "**Verdict:** Serious problems found." in out
    assert "### CRITICAL: Blue screen crash" in out
    assert "## Normal activity (no action needed)" in out
    assert "## Not yet recognised" in out


def test_markdown_escapes_values_from_the_log(make_event):
    events = [
        make_event(
            "Application Error", 1000, data={"param1": "my_app*[x](http://e.com)|<b>\nnew.exe"}
        )
    ]
    out = render_markdown(analyze(events))
    assert "my\\_app\\*\\[x\\](http://e.com)\\|\\<b\\> new.exe" in out
    assert "\nnew.exe" not in out


def test_markdown_with_no_events():
    assert render_markdown(analyze([])) == (
        "# EventLens report for unknown computer\n\nNo events found in the input.\n"
    )


def test_markdown_honours_utc_flag(make_event):
    out = render_markdown(analyze([make_event("disk", 7)]), utc=True)
    assert "(UTC)" in out


def test_markdown_top_limits_unrecognised(capsys):
    main(["--file", str(SAMPLE_WEEK), "--utc", "--format", "markdown", "--top", "1"])
    assert "Not yet recognised (top 1 of 3 event types)" in capsys.readouterr().out


# --- CLI ----------------------------------------------------------------


def test_default_format_is_text(capsys):
    main(["--file", str(SAMPLE_WEEK), "--utc"])
    assert capsys.readouterr().out.startswith("EventLens report for TEST-PC\nLogs:")


def test_unknown_format_is_an_argument_error(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--file", str(SAMPLE_WEEK), "--format", "html"])
    assert exc.value.code == 2
