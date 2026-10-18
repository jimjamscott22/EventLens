"""Generate examples/sample_week.xml: one made-up week on a troubled PC.

Run from the repo root: uv run python examples/make_sample_week.py > examples/sample_week.xml
"""

import sys
from xml.sax.saxutils import escape

NS = "http://schemas.microsoft.com/win/2004/08/events/event"
LEVELS = {"critical": 1, "error": 2, "warning": 3, "info": 4}
out = []


def ev(time, provider, eid, level, channel, data=None, named=True, qualifiers=None):
    q = f' Qualifiers="{qualifiers}"' if qualifiers is not None else ""
    lines = [
        f'  <Event xmlns="{NS}">',
        "    <System>",
        f'      <Provider Name="{escape(provider)}"/>',
        f"      <EventID{q}>{eid}</EventID>",
        f"      <Level>{LEVELS[level]}</Level>",
        f'      <TimeCreated SystemTime="2026-{time}.0000000Z"/>',
        f"      <Channel>{channel}</Channel>",
        "      <Computer>TEST-PC</Computer>",
        "    </System>",
    ]
    if data:
        lines.append("    <EventData>")
        items = data.items() if named else [(None, v) for v in data]
        for name, value in items:
            attr = f' Name="{name}"' if name else ""
            lines.append(f"      <Data{attr}>{escape(value)}</Data>")
        lines.append("    </EventData>")
    lines.append("  </Event>")
    out.append("\n".join(lines))


def boot(time):
    ev(time, "Microsoft-Windows-Kernel-General", 12, "info", "System", {"MajorVersion": "10"})
    ev(time, "EventLog", 6005, "info", "System", qualifiers=32768)


def bluescreen(day, hh, mm):
    t = f"10-{day:02d}T{hh:02d}:{mm:02d}"
    boot(f"{t}:05")
    ev(
        f"{t}:20",
        "Microsoft-Windows-Kernel-Power",
        41,
        "critical",
        "System",
        {"BugcheckCode": "159", "BugcheckParameter1": "0x3", "PowerButtonTimestamp": "0"},
    )
    ev(
        f"{t}:31",
        "EventLog",
        6008,
        "error",
        "System",
        ["8:59:12 PM", "10/6/2026"],
        named=False,
        qualifiers=32768,
    )
    ev(
        f"{t[:-2]}{mm + 1:02d}:40",
        "Microsoft-Windows-WER-SystemErrorReporting",
        1001,
        "error",
        "System",
        [
            "0x0000009f (0x0000000000000003, 0xffffc206a1e5c060, "
            "0xfffff8017a27f750, 0xffffc206a9d1a010)",
            r"C:\WINDOWS\MEMORY.DMP",
            "a1b2c3d4",
        ],
        named=False,
        qualifiers=16384,
    )


# An app crash from before the 7-day window: must be filtered out.
ev(
    "09-20T12:00:00",
    "Application Error",
    1000,
    "error",
    "Application",
    ["oldapp.exe", "1.0.0.0", "5f000000", "oldapp.dll"],
    named=False,
    qualifiers=0,
)

boot("09-30T22:00:00")
bluescreen(1, 21, 2)
# Forced power-off: someone held the power button after a freeze.
boot("10-03T10:15:00")
ev(
    "10-03T10:15:12",
    "Microsoft-Windows-Kernel-Power",
    41,
    "critical",
    "System",
    {"BugcheckCode": "0", "PowerButtonTimestamp": "134041234560000000"},
)
ev(
    "10-03T10:15:30",
    "EventLog",
    6008,
    "error",
    "System",
    ["10:09:55 AM", "10/3/2026"],
    named=False,
    qualifiers=32768,
)
bluescreen(4, 18, 30)
bluescreen(6, 21, 2)

for d, h in [(2, 19), (3, 20), (5, 21), (6, 18), (7, 19)]:
    ev(
        f"10-{d:02d}T{h:02d}:40:00",
        "Application Error",
        1000,
        "error",
        "Application",
        [
            "game.exe",
            "1.2.0.0",
            "66a1b2c3",
            "d3d11.dll",
            "10.0.26100.1",
            "a1b2c3d4",
            "c0000005",
            "000000000001a2b3",
        ],
        named=False,
        qualifiers=0,
    )
ev(
    "10-05T09:12:00",
    "Application Error",
    1000,
    "error",
    "Application",
    {
        "AppName": "notepad.exe",
        "AppVersion": "11.2409.9.0",
        "ModuleName": "ntdll.dll",
        "ExceptionCode": "c0000374",
    },
)

ev(
    "10-02T19:38:00",
    "Display",
    4101,
    "warning",
    "System",
    ["nvlddmkm", ""],
    named=False,
    qualifiers=0,
)
ev(
    "10-06T20:58:00",
    "Display",
    4101,
    "warning",
    "System",
    ["nvlddmkm", ""],
    named=False,
    qualifiers=0,
)

ev(
    "10-04T11:00:00",
    "Service Control Manager",
    7031,
    "error",
    "System",
    {
        "param1": "Print Spooler",
        "param2": "1",
        "param3": "5000",
        "param4": "1",
        "param5": "Restart the service",
    },
    qualifiers=49152,
)

for d in (4, 5):
    ev(
        f"10-{d:02d}T03:00:00",
        "Microsoft-Windows-WindowsUpdateClient",
        20,
        "error",
        "System",
        {
            "errorCode": "0x800f0922",
            "updateTitle": "2026-10 Cumulative Update for Windows 11 (KB5049999)",
            "updateGuid": "{00000000-0000-0000-0000-000000000000}",
            "updateRevisionNumber": "1",
        },
    )

for d in (2, 4, 6):
    ev(
        f"10-{d:02d}T14:00:00",
        "Microsoft-Windows-WHEA-Logger",
        47,
        "warning",
        "System",
        {"ErrorSource": "2", "ErrorType": "9"},
    )

for d, name in [
    (1, "www.example.com"),
    (3, "update.example.net"),
    (5, "www.example.com"),
    (7, "mail.example.org"),
]:
    ev(
        f"10-{d:02d}T08:30:00",
        "Microsoft-Windows-DNS-Client",
        1014,
        "warning",
        "System",
        {"QueryName": name, "AddressLength": "128"},
    )

for d in (4, 5):
    ev(
        f"10-{d:02d}T03:05:00",
        "User32",
        1074,
        "info",
        "System",
        [
            r"C:\Windows\servicing\TrustedInstaller.exe (TEST-PC)",
            "TEST-PC",
            "Operating System: Upgrade (Planned)",
            "0x80020003",
            "restart",
            "",
            r"NT AUTHORITY\SYSTEM",
        ],
        named=False,
        qualifiers=32768,
    )

for i in range(41):
    ev(
        f"10-{1 + i % 7:02d}T{(i * 7) % 24:02d}:{i % 60:02d}:00",
        "Microsoft-Windows-DistributedCOM",
        10016,
        "error",
        "System",
        {"param1": "application-specific"},
        qualifiers=0,
    )

# Not in the catalog: should appear under "Not yet recognised".
for d in (1, 3, 5, 7):
    ev(
        f"10-{d:02d}T12:00:00",
        "Microsoft-Windows-Bits-Client",
        16392,
        "error",
        "System",
        {"name": "job"},
    )
ev(
    "10-02T19:37:00",
    "nvlddmkm",
    14,
    "error",
    "System",
    ["\\Device\\Video3"],
    named=False,
    qualifiers=0,
)
ev(
    "10-06T20:57:00",
    "nvlddmkm",
    14,
    "error",
    "System",
    ["\\Device\\Video3"],
    named=False,
    qualifiers=0,
)
ev(
    "10-03T07:00:00",
    "Microsoft-Windows-Kernel-EventTracing",
    2,
    "error",
    "System",
    {"SessionName": "ReadyBoot"},
)
# Unrecognised warnings: only listed with --include-warnings.
for d in (2, 4, 6):
    ev(
        f"10-{d:02d}T09:00:00",
        "e1iexpress",
        27,
        "warning",
        "System",
        ["Intel(R) Ethernet Connection"],
        named=False,
    )

# Ordinary information noise.
for d in range(1, 8):
    ev(
        f"10-{d:02d}T23:00:00",
        "Microsoft-Windows-Kernel-General",
        16,
        "info",
        "System",
        {"HiveName": "x"},
    )
ev("10-07T21:14:00", "Microsoft-Windows-Winlogon", 7001, "info", "System", {"UserSid": "S-1-5-21"})

out.sort(key=lambda s: s.split('SystemTime="')[1][:19])
sys.stdout.write(
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<!-- A made-up week on a troubled PC, for trying EventLens. -->\n"
    "<Events>\n"
    + "\n".join(out)
    + "\n</Events>\n"
)
