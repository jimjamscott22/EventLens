# EventLens specification

Status: **draft for review**. Version: v1 (milestone M1).

## 1. What EventLens is

EventLens is a command-line tool that reads Windows event logs and explains, in plain English, what went wrong on a machine: crashes, unexpected shutdowns, failing hardware, misbehaving apps and services, and failed updates.

Windows already records all of this, but Event Viewer shows thousands of entries with cryptic sources and numeric IDs, and most of them are harmless. EventLens picks out the ones that matter, groups repeats, and says what each one means and what to do about it.

### Who it's for

- **Someone troubleshooting their own PC** ("why does my laptop keep restarting?") who doesn't want to read raw logs.
- **Someone helping a friend or family member**, who can ask them to export a log and send it over, then run EventLens on Mac, Linux, or Windows.
- **IT support / helpdesk** staff who need a fast first read of a machine before digging deeper.

### Goals (v1)

1. Produce a clear, ranked report of problems from the System and Application logs.
2. Explain each problem in plain language with a concrete next step.
3. Work on exported logs on any OS; read live logs on Windows.
4. Never change the machine: EventLens only reads.
5. Run fully offline with no telemetry.

### Non-goals (v1)

- Fixing problems automatically.
- Real-time monitoring or a background service.
- A graphical interface.
- Power diagnostics (`powercfg` battery, sleep, and energy reports). Planned for milestone M3, see §10.
- The Security log (needs admin rights and is mostly about sign-ins, not faults). Planned for M5.
- Explaining every possible event. v1 covers a curated catalog (§6) and lists anything else as unrecognised.

## 2. Inputs

| Input | How | Windows | macOS / Linux |
| --- | --- | --- | --- |
| Exported `.evtx` file | `--file PATH` | Yes | Yes |
| Event Viewer `.xml` export (UTF-8 or UTF-16) | `--file PATH` | Yes | Yes |
| Live log channels | default when no `--file` is given | Yes | No, exits with a hint to use `--file` |

Already built in `sources.py` (milestone M0).

- `--file` can be repeated to combine logs, for example a System and an Application export.
- Live mode reads the `System` and `Application` channels by default, through `wevtutil`. It needs no admin rights.
- Damaged `.evtx` records are skipped and the count is shown as a warning.
- `.evtx` files contain no readable message text (Windows builds it at display time), so explanations come from the catalog, keyed by provider and event ID, never from message text.

## 3. Command line

```
eventlens [--file PATH]... [--channel NAME]... [--days N] [--max-events N]
          [--include-warnings] [--top N] [--utc] [--verbose] [--version]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--file PATH` | none (live mode) | Read an exported `.evtx` or `.xml` file. Repeatable. |
| `--channel NAME` | `System`, `Application` | Live mode only: which channels to read. Repeatable. |
| `--days N` | 7 | Only look at the last N days. For live logs this counts back from now. For files it counts back from the newest event in the file, so an export made last month still gives a useful report. |
| `--max-events N` | 5000 per channel | Live mode only: cap on events read, newest first. |
| `--include-warnings` | off | Also list unrecognised **warnings** in the "Not yet recognised" section (errors and critical events are always listed). |
| `--top N` | 10 | Maximum number of unrecognised event types to list. |
| `--utc` | off | Show times in UTC instead of the local time zone. |
| `--verbose` | off | Show extra detail: a sample of raw event data for each finding. |
| `--version` | | Print the version and exit. |

Running `eventlens` with no arguments on Windows analyses the live System and Application logs for the last 7 days.

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Report produced (whether or not problems were found). |
| 2 | Bad arguments, unreadable input, or live mode on a non-Windows OS. |

Exit codes based on findings (for scripts, such as `--fail-on high`) are planned for M2.

## 4. How analysis works

```
sources.py  ->  analyzer.py  ->  report.py
 (events)     (findings via       (text)
               catalog.py)
```

1. **Read** events from every input into `Event` objects (built).
2. **Filter** to the time window (`--days`).
3. **Match** each event against the catalog by provider name (case-insensitive, with aliases) and event ID.
4. **Group** matched events into **findings**: one finding per catalog entry. Each finding keeps a count, first and last time seen, and a tally of distinct details (such as which app crashed).
5. **Combine crash events into incidents** (see §5).
6. **Rank** findings by severity, then count, then most recent.
7. **Collect unrecognised events**: errors and critical events not in the catalog, grouped by provider and ID (plus warnings with `--include-warnings`).
8. **Render** the report.

### Severity levels

| Severity | Meaning | Examples |
| --- | --- | --- |
| Critical | Crashes, data loss risk, or failing hardware. Act now. | Blue screens, disk bad blocks, fatal hardware errors, file system corruption |
| High | Something is broken and affects the user. | Repeated app crashes, services crashing, display driver resets, low memory |
| Medium | Worth fixing, not urgent. | Failed updates, a driver that didn't load, disk nearly full |
| Low | Minor or often transient. | DNS timeouts, occasional corrected hardware errors |
| Info | Normal or harmless, shown so the user isn't alarmed by it. | Planned restarts, DCOM 10016 |

A catalog entry can **escalate** by one level when it happens often (for example, corrected memory errors go from Low to High at 10 or more in the window). The thresholds are set per entry in the catalog.

### Verdict

The report opens with one line based on the most severe finding:

| Worst finding | Verdict |
| --- | --- |
| Critical | "Serious problems found." |
| High | "Problems found that need attention." |
| Medium or Low | "Minor issues found." |
| Info or none | "No significant problems found." |

The verdict is followed by a one-sentence headline built from the top finding, for example "This PC crashed 3 times in the last 7 days."

## 5. Crash incidents

A single crash usually leaves several events, written when the machine comes back up:

- **Kernel-Power 41**: "rebooted without cleanly shutting down"
- **EventLog 6008**: "the previous shutdown was unexpected"
- **WER-SystemErrorReporting 1001**: "rebooted from a bugcheck" (blue screen only)

Listing these as three separate problems would triple-count one crash. Instead, any of these events within **10 minutes** of each other form one **incident**, which is classified like this:

| Evidence | Incident type | Plain-English cause |
| --- | --- | --- |
| A 1001 event, or Kernel-Power 41 with `BugcheckCode` ≠ 0 | **Blue screen crash** | Windows hit a fatal error and stopped. The stop code (§6.1) points to the likely cause. |
| Kernel-Power 41 with `PowerButtonTimestamp` ≠ 0 | **Forced power-off** | Someone held the power button, usually because the PC froze. |
| Otherwise | **Sudden power loss or hard freeze** | Power was cut, or the PC locked up so hard Windows couldn't record why. |

Incidents appear in the report as one finding per type (for example "Blue screen crash, 3 times"), with each stop code tallied in the details.

## 6. v1 event catalog

The catalog lives in `catalog.py` as Python data. Each entry has: provider name(s), event ID, severity, optional escalation threshold, title, "what it means", "what to do", and an optional function that pulls details from the event data.

| Provider | ID | Title | Severity |
| --- | --- | --- | --- |
| Microsoft-Windows-Kernel-Power | 41 | Unexpected restart (part of a crash incident, §5) | Critical |
| EventLog | 6008 | Unexpected shutdown (part of a crash incident) | Critical |
| Microsoft-Windows-WER-SystemErrorReporting | 1001 | Blue screen crash (part of a crash incident) | Critical |
| Microsoft-Windows-WHEA-Logger | 18 | Fatal processor hardware error | Critical |
| Microsoft-Windows-WHEA-Logger | 17, 19 | Corrected hardware error (PCIe / processor) | Low, High at 10+ |
| Microsoft-Windows-WHEA-Logger | 47 | Corrected memory error | Low, High at 10+ |
| disk | 7 | Bad block on a drive | Critical |
| disk | 51 | Drive error during paging | High |
| disk | 153 | Drive operation had to be retried | Medium, High at 10+ |
| Ntfs, Microsoft-Windows-Ntfs | 55 | File system corruption detected | Critical |
| Display | 4101 | Display driver stopped responding and recovered | High |
| Application Error | 1000 | App crashed (detail: app name and faulting module) | Medium, High at 5+ |
| Application Hang | 1002 | App stopped responding (detail: app name) | Medium, High at 5+ |
| .NET Runtime | 1026 | .NET app crashed with an unhandled error | Medium, High at 5+ |
| Service Control Manager | 7000, 7009 | Service failed to start / timed out (detail: service name) | Medium |
| Service Control Manager | 7023, 7031, 7034 | Service stopped unexpectedly (detail: service name) | High |
| Microsoft-Windows-WindowsUpdateClient | 20 | Windows Update failed to install (detail: update title, error code) | Medium |
| Microsoft-Windows-Resource-Exhaustion-Detector | 2004 | PC ran low on memory | High |
| Microsoft-Windows-Kernel-PnP | 219 | A driver failed to load (detail: device) | Medium |
| srv | 2013 | A disk is nearly full | Medium |
| Microsoft-Windows-DNS-Client | 1014 | Website name lookups timed out | Low |
| User32 | 1074 | Planned restart or shutdown (detail: which program requested it) | Info |
| Microsoft-Windows-DistributedCOM | 10016 | DCOM permission warning: harmless, safe to ignore | Info |

### 6.1 Blue screen stop codes

Stop codes are shown by name with a short hint. Codes not listed are shown as hex.

| Code | Name | Hint |
| --- | --- | --- |
| 0x0A | IRQL_NOT_LESS_OR_EQUAL | Usually a faulty driver |
| 0x1A | MEMORY_MANAGEMENT | Often faulty RAM; run Windows Memory Diagnostic |
| 0x3B | SYSTEM_SERVICE_EXCEPTION | Driver or system file problem |
| 0x50 | PAGE_FAULT_IN_NONPAGED_AREA | Faulty driver, RAM, or antivirus |
| 0x7E | SYSTEM_THREAD_EXCEPTION_NOT_HANDLED | A driver crashed |
| 0x9F | DRIVER_POWER_STATE_FAILURE | A driver failed during sleep or wake |
| 0xD1 | DRIVER_IRQL_NOT_LESS_OR_EQUAL | A network, storage, or graphics driver crashed |
| 0xEF | CRITICAL_PROCESS_DIED | A core Windows process stopped; check the disk and system files |
| 0x116 | VIDEO_TDR_FAILURE | Graphics driver or GPU problem |
| 0x124 | WHEA_UNCORRECTABLE_ERROR | Hardware fault: CPU, RAM, overheating, or overclocking |
| 0x133 | DPC_WATCHDOG_VIOLATION | A driver or SSD firmware hung |
| 0x139 | KERNEL_SECURITY_CHECK_FAILURE | Driver, RAM, or corrupt system files |

Kernel-Power 41 stores the code in decimal (`159`) and 1001 stores it as text (`0x0000009f`). Both are normalised to the same form.

## 7. Report format

Plain text, about 80 columns wide, readable when pasted into an email or ticket. No colour in v1 (planned for M2).

Sample, from a week with three blue screens, a flaky app, and a failed update:

```
EventLens report for TEST-PC
Logs: System, Application   Period: 1 Oct 2026 08:00 to 7 Oct 2026 21:14 (BST)
Events read: 4,812

Verdict: Serious problems found.
This PC crashed 3 times in the last 7 days.

---------------------------------------------------------------------------
CRITICAL  Blue screen crash                    3 times, last 6 Oct 21:02
---------------------------------------------------------------------------
What happened:  Windows hit a fatal error and restarted.
Stop codes:     DRIVER_POWER_STATE_FAILURE (0x9F) x3
What it means:  A driver didn't respond in time while the PC was going to
                sleep or waking up.
What to do:     Update your graphics, Wi-Fi, and chipset drivers from the
                PC maker's website. If it keeps happening, try turning off
                Fast Startup.

---------------------------------------------------------------------------
HIGH      App crashed                          6 times, last 7 Oct 19:40
---------------------------------------------------------------------------
Details:        game.exe x5 (module: d3d11.dll), notepad.exe x1
What it means:  These programs closed unexpectedly.
What to do:     Update the app. Crashes in a graphics module such as
                d3d11.dll often go away after a graphics driver update.

---------------------------------------------------------------------------
MEDIUM    Windows Update failed to install     2 times, last 5 Oct 03:00
---------------------------------------------------------------------------
Details:        2026-10 Cumulative Update (KB5049999), error 0x800f0922
What to do:     Restart and run Windows Update again. If it keeps failing,
                run the Windows Update troubleshooter.

Normal activity (no action needed)
  - 2 planned restarts, requested by TrustedInstaller.exe (Windows Update)
  - 41 DCOM 10016 warnings: harmless, safe to ignore

Not yet recognised (top 3 of 3 error types)
  - Microsoft-Windows-Bits-Client 16392     4 times
  - nvlddmkm 14                             2 times
  - Microsoft-Windows-Kernel-EventTracing 2 1 time
```

Rules:

- Times are shown in the local time zone of the machine running EventLens, with the zone name, unless `--utc` is passed.
- Each finding shows at most 3 distinct details plus "and N more".
- The "Normal activity" and "Not yet recognised" sections are left out when empty.
- If no events are in the window, the report says so and suggests a larger `--days`.

## 8. Privacy and safety

- EventLens only reads logs. It never writes to them, changes settings, or runs anything except `wevtutil` (read-only queries).
- No network access, no telemetry.
- Reports can contain the computer name, app names, and file paths. The README will remind users of this before they share a report.

## 9. Code layout and testing

| Module | Role | Status |
| --- | --- | --- |
| `models.py` | `Event`, `Level` | Built |
| `sources.py` | Read `.evtx`, `.xml`, and live logs | Built |
| `catalog.py` | Event catalog and stop codes | M1 |
| `analyzer.py` | Filtering, matching, grouping, incidents, ranking | M1 |
| `report.py` | Text rendering | M1 |
| `cli.py` | Argument parsing, exit codes, logging setup | M1 |

Testing:

- Unit tests for each module with pytest.
- An XML fixture with at least one event for every catalog entry, plus crash incidents of each type.
- A golden-file test comparing the full report for a fixed fixture, with times shown in UTC so the test is stable.
- CLI tests for the arguments, exit codes, and the non-Windows live-mode message.
- CI runs everything on Windows, macOS, and Linux (built in M0).

No new runtime dependencies are planned for M1: `argparse` and the standard library are enough.

## 10. Roadmap

| Milestone | Scope | Status |
| --- | --- | --- |
| **M0 Foundation** | uv project, event model, `.evtx`/`.xml`/live readers, tests, cross-platform CI | Done |
| **M1 Core report** | Catalog, analyzer, crash incidents, text report, CLI (this spec) | Next |
| **M2 Output options** | `--format json` and `markdown`, colour in terminals, `--output FILE`, `--fail-on SEVERITY` exit codes | Planned |
| **M3 Power diagnostics** | Parse `powercfg /batteryreport /xml` (battery wear and capacity history), `/sleepstudy` and sleep/wake events (Kernel-Power 42, 107, 506, 507) to explain battery drain and failed sleep | Planned |
| **M4 Timeline** | Boot and shutdown sessions (Kernel-General 12/13, EventLog 6005/6006), uptime, and "what happened in the minutes before each crash" | Planned |
| **M5 Catalog growth** | Move the catalog to a data file (TOML) so new events can be added without code; more events; optional Security log | Planned |
| **M6 Distribution** | Publish to PyPI (`uvx eventlens`), plus a standalone Windows `.exe` for people without Python | Planned |

## 11. Open questions

1. **Power diagnostics timing.** The README promises power diagnostics, but this spec puts them in M3 so v1 can ship sooner. Should any of it move into v1?
2. **Crash incident window.** Is 10 minutes the right gap for grouping crash events? A slow boot can push 6008 a few minutes after 41.
3. **Default time window.** Is 7 days the right default, or should it be 30?
4. **Report times.** Local time zone of the machine running EventLens (proposed), or the time zone of the machine the log came from? An `.evtx` file doesn't record its time zone, so the second option would need a `--tz` flag.
