import os
from datetime import datetime, timezone
from pathlib import Path

from eventlens.analyzer import analyze
from eventlens.cli import main
from eventlens.models import Level
from eventlens.report import WIDTH, render

ROOT = Path(__file__).parent.parent
SAMPLE_WEEK = ROOT / "examples" / "sample_week.xml"
GOLDEN = Path(__file__).parent / "fixtures" / "sample_week_report.txt"


def test_sample_week_report_matches_golden_file(capsys):
    """The whole report for examples/sample_week.xml, compared line by line.

    After an intended change to the report, regenerate the golden file with:
        EVENTLENS_UPDATE_GOLDEN=1 uv run pytest tests/test_report.py
    """
    assert main(["--file", str(SAMPLE_WEEK), "--utc"]) == 0
    output = capsys.readouterr().out
    if os.environ.get("EVENTLENS_UPDATE_GOLDEN"):
        GOLDEN.write_text(output, encoding="utf-8", newline="\n")
    assert output == GOLDEN.read_text(encoding="utf-8")


def test_report_lines_fit_the_width(capsys):
    main(["--file", str(SAMPLE_WEEK), "--utc", "--include-warnings", "--verbose"])
    for line in capsys.readouterr().out.splitlines():
        assert len(line) <= WIDTH, line


def test_no_events_at_all():
    expected = "EventLens report for unknown computer\n\nNo events found in the input.\n"
    assert render(analyze([])) == expected


def test_no_events_in_window(make_event):
    since = datetime(2030, 1, 1, tzinfo=timezone.utc)
    text = render(analyze([make_event("disk", 7)], since=since))
    assert "Events read: 1" in text
    assert "Try a larger --days value." in text


def test_details_are_capped_with_a_remainder_line(make_event):
    events = [
        make_event("Application Error", 1000, minutes=i, data={"param1": f"app{i}.exe"})
        for i in range(5)
    ]
    text = render(analyze(events), utc=True)
    assert "...and 2 more" in text
    assert text.count("1x app") == 3


def test_detail_counts_are_aligned(make_event):
    events = [
        make_event("Application Error", 1000, minutes=i, data={"param1": "big.exe"})
        for i in range(12)
    ] + [make_event("Application Error", 1000, data={"param1": "small.exe"})]
    text = render(analyze(events), utc=True)
    assert "Details:        12x big.exe\n                 1x small.exe\n" in text


def test_unrecognised_list_respects_top(make_event):
    events = [make_event(f"Provider{i}", i) for i in range(4)]
    text = render(analyze(events), top=2, utc=True)
    assert "Not yet recognised (top 2 of 4 event types)" in text
    assert text.count("(Error)") == 2


def test_verbose_shows_latest_event(make_event):
    events = [make_event("Display", 4101, data={"param1": "nvlddmkm"})]
    assert "Latest event:" not in render(analyze(events), utc=True)
    assert "Latest event:   Display 4101 (param1=nvlddmkm)" in render(
        analyze(events), utc=True, verbose=True
    )


def test_multiple_computers_are_summarised(make_event):
    events = [make_event("A", 1, computer=name, level=Level.INFORMATION) for name in "XYZ"]
    assert render(analyze(events)).startswith("EventLens report for X and 2 others\n")


def test_utc_and_local_time_labels(make_event):
    events = [make_event("A", 1, level=Level.INFORMATION)]
    assert "(UTC)" in render(analyze(events), utc=True)
    assert "Period: " in render(analyze(events), utc=False)
