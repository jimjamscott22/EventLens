import io
import re
from pathlib import Path

import pytest

from eventlens import color
from eventlens.analyzer import analyze
from eventlens.catalog import Severity
from eventlens.cli import main
from eventlens.color import paint, should_color
from eventlens.report import render
from eventlens.sources import read_file

ROOT = Path(__file__).parent.parent
SAMPLE_WEEK = ROOT / "examples" / "sample_week.xml"
ANSI = re.compile(r"\x1b\[[0-9;]*m")


class FakeStream(io.StringIO):
    def __init__(self, tty: bool) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def sample_analysis():
    return analyze(read_file(SAMPLE_WEEK), include_warnings=True)


# --- painting -----------------------------------------------------------


def test_paint_wraps_text_in_an_escape_sequence_and_resets():
    assert paint("x", Severity.HIGH) == "\x1b[31mx\x1b[0m"


def test_every_severity_has_its_own_style():
    styles = {paint("x", severity) for severity in Severity}
    assert len(styles) == len(Severity)


def test_colored_report_has_escapes_but_the_same_layout():
    analysis = sample_analysis()
    plain = render(analysis, utc=True, verbose=True)
    colored = render(analysis, utc=True, verbose=True, color=True)
    assert "\x1b[" in colored
    assert ANSI.sub("", colored) == plain


def test_plain_report_has_no_escapes():
    assert "\x1b" not in render(sample_analysis(), utc=True)


def test_severity_label_and_verdict_are_colored():
    colored = render(sample_analysis(), utc=True, color=True)
    assert f"Verdict: {paint('Serious problems found.', Severity.CRITICAL)}" in colored
    assert paint("CRITICAL", Severity.CRITICAL) + " " in colored
    assert paint("LOW", Severity.LOW) in colored


# --- deciding whether to color -----------------------------------------


def test_never_and_always_ignore_the_terminal():
    assert should_color("never", FakeStream(tty=True), {}, "linux") is False
    assert should_color("always", FakeStream(tty=False), {}, "linux") is True


def test_always_beats_no_color():
    assert should_color("always", FakeStream(tty=False), {"NO_COLOR": "1"}, "linux") is True


def test_auto_colors_a_terminal():
    assert should_color("auto", FakeStream(tty=True), {"TERM": "xterm"}, "linux") is True


def test_auto_does_not_color_a_pipe_or_file():
    assert should_color("auto", FakeStream(tty=False), {"TERM": "xterm"}, "linux") is False


def test_auto_respects_no_color():
    assert should_color("auto", FakeStream(tty=True), {"NO_COLOR": "1"}, "linux") is False


def test_auto_ignores_an_empty_no_color():
    assert should_color("auto", FakeStream(tty=True), {"NO_COLOR": ""}, "linux") is True


def test_auto_does_not_color_a_dumb_terminal():
    assert should_color("auto", FakeStream(tty=True), {"TERM": "dumb"}, "linux") is False


@pytest.mark.parametrize("vt_works", [True, False])
def test_auto_on_windows_needs_the_console_to_accept_escapes(monkeypatch, vt_works):
    monkeypatch.setattr(color, "_enable_windows_vt", lambda: vt_works)
    assert should_color("auto", FakeStream(tty=True), {}, "win32") is vt_works


def test_auto_on_windows_does_not_touch_the_console_when_piped(monkeypatch):
    def boom():
        raise AssertionError("must not be called")

    monkeypatch.setattr(color, "_enable_windows_vt", boom)
    assert should_color("auto", FakeStream(tty=False), {}, "win32") is False


def test_always_on_windows_still_tries_to_enable_escapes(monkeypatch):
    calls = []
    monkeypatch.setattr(color, "_enable_windows_vt", lambda: calls.append(1) or False)
    assert should_color("always", FakeStream(tty=True), {}, "win32") is True
    assert calls == [1]


# --- command line -------------------------------------------------------


def test_cli_does_not_color_by_default_when_piped(capsys):
    main(["--file", str(SAMPLE_WEEK), "--utc"])
    assert "\x1b" not in capsys.readouterr().out


def test_cli_color_always(capsys):
    assert main(["--file", str(SAMPLE_WEEK), "--utc", "--color", "always"]) == 0
    out = capsys.readouterr().out
    assert "\x1b[" in out
    assert out.startswith("EventLens report for TEST-PC\n")


def test_cli_color_never_beats_a_terminal(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdout.isatty", lambda: True, raising=False)
    main(["--file", str(SAMPLE_WEEK), "--utc", "--color", "never"])
    assert "\x1b" not in capsys.readouterr().out


@pytest.mark.parametrize("fmt", ["json", "markdown"])
def test_cli_color_only_applies_to_text(capsys, fmt):
    main(["--file", str(SAMPLE_WEEK), "--format", fmt, "--color", "always"])
    assert "\x1b" not in capsys.readouterr().out


def test_cli_rejects_unknown_color_mode():
    with pytest.raises(SystemExit) as exc:
        main(["--file", str(SAMPLE_WEEK), "--color", "rainbow"])
    assert exc.value.code == 2
