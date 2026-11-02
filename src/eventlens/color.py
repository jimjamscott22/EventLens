"""ANSI colour for the text report (see SPEC.md section 7)."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from typing import TextIO

from eventlens.catalog import Severity

COLOR_MODES = ("auto", "always", "never")

_RESET = "\x1b[0m"
_STYLES = {
    Severity.CRITICAL: "1;31",  # bold red
    Severity.HIGH: "31",  # red
    Severity.MEDIUM: "33",  # yellow
    Severity.LOW: "36",  # cyan
    Severity.INFO: "2",  # dim
}

_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
_STD_OUTPUT_HANDLE = -11


def paint(text: str, severity: Severity) -> str:
    """Wrap ``text`` in the colour for ``severity``."""
    return f"\x1b[{_STYLES[severity]}m{text}{_RESET}"


def _enable_windows_vt() -> bool:
    """Ask the Windows console to understand ANSI escapes. True if it does."""
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.GetStdHandle(_STD_OUTPUT_HANDLE)
    mode = ctypes.c_uint32()
    if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        return False
    return bool(kernel32.SetConsoleMode(handle, mode.value | _ENABLE_VIRTUAL_TERMINAL_PROCESSING))


def should_color(
    mode: str,
    stream: TextIO,
    env: Mapping[str, str],
    platform: str = sys.platform,
) -> bool:
    """Decide whether to colour output written to ``stream``.

    ``always`` and ``never`` are taken at their word. ``auto`` colours only a
    terminal, and not when NO_COLOR is set (https://no-color.org) or the
    terminal is "dumb". On Windows it also needs the console to accept escapes.
    """
    if mode == "never":
        return False
    if mode == "always":
        if platform == "win32" and stream.isatty():
            _enable_windows_vt()
        return True
    if env.get("NO_COLOR") or env.get("TERM") == "dumb" or not stream.isatty():
        return False
    if platform == "win32":
        return _enable_windows_vt()
    return True
