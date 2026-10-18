"""Render the top of a real EventLens report as docs/images/report.png.

The text in the picture is the actual output of the command shown in it; this
script runs EventLens and draws that output inside a terminal-style window.
Nothing is typed by hand and no colour is added, because EventLens does not
produce colour yet.

Run from the repo root (Playwright is only needed for this script, so it is
not a project dependency):

    uv run --with playwright python docs/make_report_image.py

If Playwright cannot find a browser, point CHROMIUM_PATH at a Chromium or
Chrome executable.
"""

import html
import os
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images" / "report.png"
COMMAND = ["eventlens", "--file", "examples/sample_week.xml", "--utc"]
FONT = "'DejaVu Sans Mono', 'Liberation Mono', Menlo, Consolas, monospace"

PAGE = """<!doctype html>
<meta charset="utf-8">
<style>
  body {{ margin: 0; padding: 28px; background: #eef0f3; width: max-content; }}
  .window {{ background: #1e2127; border-radius: 10px; overflow: hidden;
             box-shadow: 0 8px 30px rgba(0,0,0,.25); }}
  .bar {{ background: #2d3139; padding: 10px 14px; display: flex; align-items: center;
          gap: 8px; font: 13px {font}; color: #9aa3b2; }}
  .dot {{ width: 12px; height: 12px; border-radius: 50%; }}
  pre {{ margin: 0; padding: 18px 22px 22px; font: 15px/1.4 {font}; color: #d7dce5; }}
  .prompt {{ color: #7ec699; }}
  .cut {{ color: #7d8696; }}
</style>
<div class="window">
  <div class="bar">
    <span class="dot" style="background:#ff5f56"></span>
    <span class="dot" style="background:#ffbd2e"></span>
    <span class="dot" style="background:#27c93f"></span>
    <span style="margin-left:8px">EventLens</span>
  </div>
  <pre><span class="prompt">$</span> uv run {command}
{report}
<span class="cut">... (the report continues with the other findings)</span></pre>
</div>
"""


def report_lines() -> list[str]:
    result = subprocess.run(
        [sys.executable, "-m", *COMMAND],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    lines = result.stdout.splitlines()
    # Stop before the third finding so the picture ends on a whole block.
    third = next(i for i, line in enumerate(lines) if line.startswith("HIGH"))
    return lines[: third - 1]


def main() -> None:
    page = PAGE.format(
        font=FONT,
        command=html.escape(" ".join(COMMAND)),
        report=html.escape("\n".join(report_lines())),
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH"))
        tab = browser.new_page(device_scale_factor=2)
        tab.set_content(page)
        tab.locator("body").screenshot(path=str(OUT))
        browser.close()
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
