"""The catalog of Windows events EventLens knows how to explain.

Each ``Rule`` maps one or more (provider, event ID) pairs to a plain-English
title, meaning, and next step. Crash events (Kernel-Power 41, EventLog 6008,
and BugCheck 1001) are not rules: the analyzer combines them into incidents,
described by the ``BLUE_SCREEN``, ``FORCED_POWER_OFF``, and ``POWER_LOSS``
rules at the bottom of this module.

All text is ASCII so the report prints on any Windows console.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from pathlib import PureWindowsPath

from eventlens.models import Event


class Severity(IntEnum):
    """How urgent a finding is. Higher is more severe."""

    INFO = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    @property
    def label(self) -> str:
        return self.name


DetailFn = Callable[[Event], "str | None"]


@dataclass(frozen=True)
class Rule:
    """How to explain one kind of event."""

    key: str
    providers: tuple[str, ...]
    event_ids: tuple[int, ...]
    severity: Severity
    title: str
    meaning: str
    action: str = ""
    # (count, severity): use ``severity`` once the event happens ``count``+ times.
    escalate: tuple[int, Severity] | None = None
    detail: DetailFn | None = None
    detail_label: str = "Details"

    def severity_for(self, count: int) -> Severity:
        if self.escalate is not None and count >= self.escalate[0]:
            return max(self.severity, self.escalate[1])
        return self.severity


# --- Helpers for pulling details out of event data ---


def field(event: Event, *names: str) -> str | None:
    """Return the first non-empty data field among ``names``.

    Classic events have unnamed fields (``param1``, ``param2``...), while newer
    Windows versions name them, so callers list both spellings.
    """
    for name in names:
        value = event.data.get(name, "").strip()
        if value:
            return value
    return None


def _app_crash(event: Event) -> str | None:
    app = field(event, "AppName", "param1")
    if app is None:
        return None
    module = field(event, "ModuleName", "param4")
    return f"{app} (module: {module})" if module else app


def _app_hang(event: Event) -> str | None:
    return field(event, "AppName", "param1")


_DOTNET_APP = re.compile(r"Application:\s*(\S+)")


def _dotnet_crash(event: Event) -> str | None:
    text = field(event, "param1") or event.message
    match = _DOTNET_APP.search(text)
    return match.group(1) if match else None


def _service(event: Event) -> str | None:
    # 7009 puts the timeout in param1 and the service name in param2.
    if event.event_id == 7009:
        return field(event, "param2")
    return field(event, "param1")


def _windows_update(event: Event) -> str | None:
    title = field(event, "updateTitle")
    code = field(event, "errorCode")
    if title and code:
        return f"{title}, error {code}"
    return title


def _planned_restart(event: Event) -> str | None:
    process = field(event, "param1")
    if process is None:
        return None
    # "C:\Windows\servicing\TrustedInstaller.exe (TEST-PC)" -> "TrustedInstaller.exe"
    name = PureWindowsPath(process.split(" (")[0]).name or process
    kind = field(event, "param5") or "restart or shutdown"
    return f"{kind} requested by {name}"


def _first_param(event: Event) -> str | None:
    return field(event, "param1")


# --- Blue screen stop codes ---

STOP_CODES: dict[int, tuple[str, str]] = {
    0x0A: ("IRQL_NOT_LESS_OR_EQUAL", "usually a faulty driver"),
    0x1A: ("MEMORY_MANAGEMENT", "often faulty RAM; run Windows Memory Diagnostic"),
    0x3B: ("SYSTEM_SERVICE_EXCEPTION", "a driver or system file problem"),
    0x50: ("PAGE_FAULT_IN_NONPAGED_AREA", "a faulty driver, RAM, or antivirus"),
    0x7E: ("SYSTEM_THREAD_EXCEPTION_NOT_HANDLED", "a driver crashed"),
    0x9F: ("DRIVER_POWER_STATE_FAILURE", "a driver failed during sleep or wake"),
    0xD1: (
        "DRIVER_IRQL_NOT_LESS_OR_EQUAL",
        "a network, storage, or graphics driver crashed",
    ),
    0xEF: (
        "CRITICAL_PROCESS_DIED",
        "a core Windows process stopped; check the disk and system files",
    ),
    0x116: ("VIDEO_TDR_FAILURE", "a graphics driver or GPU problem"),
    0x124: (
        "WHEA_UNCORRECTABLE_ERROR",
        "a hardware fault: CPU, RAM, overheating, or overclocking",
    ),
    0x133: ("DPC_WATCHDOG_VIOLATION", "a driver or SSD firmware hung"),
    0x139: ("KERNEL_SECURITY_CHECK_FAILURE", "a driver, RAM, or corrupt system files"),
}


def parse_stop_code(value: str | None) -> int | None:
    """Normalise a stop code from either crash event into an int.

    Kernel-Power 41 stores it in decimal (``"159"``); BugCheck 1001 stores it
    as hex text, often followed by parameters (``"0x0000009f (0x3, ...)"``).
    """
    if not value:
        return None
    token = value.strip().split()[0] if value.strip() else ""
    try:
        if token.lower().startswith("0x"):
            return int(token, 16)
        return int(token)
    except ValueError:
        return None


def describe_stop_code(code: int) -> str:
    """Return e.g. ``"DRIVER_POWER_STATE_FAILURE (0x9F): a driver failed..."``."""
    hex_code = f"0x{code:X}"
    known = STOP_CODES.get(code)
    if known is None:
        return f"Stop code {hex_code}"
    name, hint = known
    return f"{name} ({hex_code}): {hint}"


# --- The catalog ---

_UPDATE_DRIVERS = (
    "Update the drivers (graphics, Wi-Fi, chipset, storage) from the PC or "
    "motherboard maker's website and install all Windows updates."
)

RULES: tuple[Rule, ...] = (
    Rule(
        key="whea-fatal",
        providers=("Microsoft-Windows-WHEA-Logger",),
        event_ids=(18,),
        severity=Severity.CRITICAL,
        title="Fatal processor hardware error",
        meaning=(
            "The processor reported an error it could not recover from. This "
            "points to failing hardware, overheating, or unstable overclocking."
        ),
        action=(
            "Undo any overclocking, check that fans and vents are clean, and "
            "update the BIOS/UEFI. If it keeps happening, the CPU, RAM, or "
            "motherboard may need replacing."
        ),
    ),
    Rule(
        key="whea-corrected",
        providers=("Microsoft-Windows-WHEA-Logger",),
        event_ids=(17, 19),
        severity=Severity.LOW,
        escalate=(10, Severity.HIGH),
        title="Corrected hardware error",
        meaning=(
            "A hardware component (usually a PCIe device or the processor) had "
            "an error that was fixed automatically. A few are normal; many in a "
            "short time suggest a device is starting to fail."
        ),
        action=(
            "If this appears often, update the BIOS/UEFI and chipset drivers, "
            "and reseat or test recently added hardware."
        ),
    ),
    Rule(
        key="whea-memory",
        providers=("Microsoft-Windows-WHEA-Logger",),
        event_ids=(47,),
        severity=Severity.LOW,
        escalate=(10, Severity.HIGH),
        title="Corrected memory error",
        meaning=(
            "The RAM returned bad data that was corrected automatically. "
            "Repeated errors are an early sign of failing memory."
        ),
        action=(
            "Run Windows Memory Diagnostic. If errors continue, reseat or "
            "replace the RAM sticks."
        ),
    ),
    Rule(
        key="disk-bad-block",
        providers=("disk",),
        event_ids=(7,),
        severity=Severity.CRITICAL,
        title="Bad block on a drive",
        meaning="Part of a drive can no longer be read reliably. Data on it is at risk.",
        action=(
            "Back up your files now. Then check the drive's health (for example "
            "with CrystalDiskInfo or the maker's tool) and plan to replace it."
        ),
        detail=_first_param,
        detail_label="Drive",
    ),
    Rule(
        key="disk-paging-error",
        providers=("disk",),
        event_ids=(51,),
        severity=Severity.HIGH,
        title="Drive error during paging",
        meaning=(
            "Windows hit an error while moving memory to or from a drive. This "
            "can mean a failing drive or a loose cable."
        ),
        action=(
            "Back up your files, check the drive's health, and reseat its cable "
            "if it's a desktop PC."
        ),
        detail=_first_param,
        detail_label="Drive",
    ),
    Rule(
        key="disk-retried",
        providers=("disk",),
        event_ids=(153,),
        severity=Severity.MEDIUM,
        escalate=(10, Severity.HIGH),
        title="Drive operation had to be retried",
        meaning=(
            "A read or write to a drive took too long and had to be tried "
            "again. Occasional retries happen; many suggest a drive problem."
        ),
        action=(
            "Update the storage driver and drive firmware, and check the "
            "drive's health. Back up if retries are frequent."
        ),
    ),
    Rule(
        key="ntfs-corruption",
        providers=("Ntfs", "Microsoft-Windows-Ntfs"),
        event_ids=(55,),
        severity=Severity.CRITICAL,
        title="File system corruption detected",
        meaning="The structure of the file system on a drive is damaged.",
        action=(
            "Back up your files, then run 'chkdsk /f' on the affected drive "
            "from an administrator command prompt and restart."
        ),
        detail=lambda e: field(e, "DriveName"),
        detail_label="Drive",
    ),
    Rule(
        key="display-reset",
        providers=("Display",),
        event_ids=(4101,),
        severity=Severity.HIGH,
        title="Display driver stopped responding and recovered",
        meaning=(
            "The graphics driver froze and Windows restarted it. You may have "
            "seen the screen go black or flicker."
        ),
        action=(
            "Install the latest graphics driver from NVIDIA, AMD, or Intel. If "
            "it happens in games, check GPU temperatures and undo overclocking."
        ),
        detail=_first_param,
        detail_label="Driver",
    ),
    Rule(
        key="app-crash",
        providers=("Application Error",),
        event_ids=(1000,),
        severity=Severity.MEDIUM,
        escalate=(5, Severity.HIGH),
        title="App crashed",
        meaning="These programs closed unexpectedly.",
        action=(
            "Update or reinstall the app. Crashes in a graphics module such as "
            "d3d11.dll or a GPU driver file often go away after a graphics "
            "driver update."
        ),
        detail=_app_crash,
    ),
    Rule(
        key="app-hang",
        providers=("Application Hang",),
        event_ids=(1002,),
        severity=Severity.MEDIUM,
        escalate=(5, Severity.HIGH),
        title="App stopped responding",
        meaning="These programs froze and were closed.",
        action=(
            "Update the app. If many different apps hang, check for a full "
            "disk, low memory, or a failing drive."
        ),
        detail=_app_hang,
    ),
    Rule(
        key="dotnet-crash",
        providers=(".NET Runtime",),
        event_ids=(1026,),
        severity=Severity.MEDIUM,
        escalate=(5, Severity.HIGH),
        title=".NET app crashed with an unhandled error",
        meaning="A program built on .NET hit an error it didn't handle and closed.",
        action="Update or reinstall the app, and install .NET updates through Windows Update.",
        detail=_dotnet_crash,
    ),
    Rule(
        key="service-start-failed",
        providers=("Service Control Manager",),
        event_ids=(7000, 7009),
        severity=Severity.MEDIUM,
        title="Service failed to start",
        meaning="A background service didn't start, or took too long to start.",
        action=(
            "If the service belongs to software you use, reinstall or update "
            "it. If it belongs to software you've removed, it's safe to ignore."
        ),
        detail=_service,
        detail_label="Services",
    ),
    Rule(
        key="service-crashed",
        providers=("Service Control Manager",),
        event_ids=(7023, 7031, 7034),
        severity=Severity.HIGH,
        title="Service stopped unexpectedly",
        meaning="A background service crashed or stopped with an error.",
        action=(
            "Update or reinstall the software the service belongs to. For "
            "Windows services, install updates and run 'sfc /scannow' from an "
            "administrator command prompt."
        ),
        detail=_service,
        detail_label="Services",
    ),
    Rule(
        key="update-failed",
        providers=("Microsoft-Windows-WindowsUpdateClient",),
        event_ids=(20,),
        severity=Severity.MEDIUM,
        title="Windows Update failed to install",
        meaning="An update downloaded but could not be installed.",
        action=(
            "Restart and run Windows Update again. If it keeps failing, run the "
            "Windows Update troubleshooter or search for the error code."
        ),
        detail=_windows_update,
        detail_label="Updates",
    ),
    Rule(
        key="low-memory",
        providers=("Microsoft-Windows-Resource-Exhaustion-Detector",),
        event_ids=(2004,),
        severity=Severity.HIGH,
        title="PC ran low on memory",
        meaning=(
            "Windows nearly ran out of memory, which makes apps slow, freeze, "
            "or crash."
        ),
        action=(
            "Close programs you aren't using, check Task Manager for one using "
            "far more memory than expected, and make sure the page file is "
            "enabled. Adding RAM helps if this happens often."
        ),
    ),
    Rule(
        key="driver-load-failed",
        providers=("Microsoft-Windows-Kernel-PnP",),
        event_ids=(219,),
        severity=Severity.MEDIUM,
        title="A driver failed to load",
        meaning="A device driver didn't load at startup, so the device may not work.",
        action=(
            "Check Device Manager for devices with a warning icon and update "
            "their drivers. If everything works, this is usually harmless."
        ),
        detail=lambda e: field(e, "DriverName"),
        detail_label="Devices",
    ),
    Rule(
        key="disk-full",
        providers=("srv",),
        event_ids=(2013,),
        severity=Severity.MEDIUM,
        title="A disk is nearly full",
        meaning="A drive is at or near capacity, which can cause errors and slowdowns.",
        action="Free up space with Disk Cleanup or Storage Sense, or move files elsewhere.",
    ),
    Rule(
        key="dns-timeout",
        providers=("Microsoft-Windows-DNS-Client",),
        event_ids=(1014,),
        severity=Severity.LOW,
        title="Website name lookups timed out",
        meaning=(
            "The PC couldn't look up some website names in time. Brief network "
            "drops cause this and it's usually harmless."
        ),
        action=(
            "If websites often fail to load, restart your router, or try a "
            "different DNS server."
        ),
        detail=lambda e: field(e, "QueryName"),
        detail_label="Names",
    ),
    Rule(
        key="planned-restart",
        providers=("User32",),
        event_ids=(1074,),
        severity=Severity.INFO,
        title="Planned restart or shutdown",
        meaning="A program or person asked Windows to restart or shut down.",
        detail=_planned_restart,
    ),
    Rule(
        key="dcom-10016",
        providers=("Microsoft-Windows-DistributedCOM",),
        event_ids=(10016,),
        severity=Severity.INFO,
        title="DCOM permission warnings (harmless, safe to ignore)",
        meaning=(
            "Windows components log these routinely. Microsoft says they don't "
            "affect how the PC works."
        ),
    ),
)

# --- Crash incidents (see SPEC.md section 5) ---

# Events written after an unexpected shutdown, keyed by (provider, event ID).
KERNEL_POWER_41 = ("microsoft-windows-kernel-power", 41)
UNEXPECTED_SHUTDOWN_6008 = ("eventlog", 6008)
BUGCHECK_1001 = ("microsoft-windows-wer-systemerrorreporting", 1001)
CRASH_EVENTS = frozenset({KERNEL_POWER_41, UNEXPECTED_SHUTDOWN_6008, BUGCHECK_1001})

BLUE_SCREEN = Rule(
    key="blue-screen",
    providers=(),
    event_ids=(),
    severity=Severity.CRITICAL,
    title="Blue screen crash",
    meaning="Windows hit a fatal error and restarted.",
    action=(
        "Use the hint for each stop code above. "
        + _UPDATE_DRIVERS
        + " If crashes continue, run Windows Memory Diagnostic."
    ),
    detail_label="Stop codes",
)

FORCED_POWER_OFF = Rule(
    key="forced-power-off",
    providers=(),
    event_ids=(),
    severity=Severity.CRITICAL,
    title="Forced power-off",
    meaning=(
        "Someone held the power button to turn the PC off, usually because it "
        "had frozen."
    ),
    action=(
        "If the PC froze, " + _UPDATE_DRIVERS[0].lower() + _UPDATE_DRIVERS[1:]
        + " Check temperatures if freezes happen under load."
    ),
)

POWER_LOSS = Rule(
    key="power-loss",
    providers=(),
    event_ids=(),
    severity=Severity.CRITICAL,
    title="Sudden power loss or hard freeze",
    meaning=(
        "The PC turned off without warning: either the power was cut, or it "
        "locked up so hard that Windows couldn't record why."
    ),
    action=(
        "Check the power cable, power strip, and (for laptops) the battery. If "
        "the power didn't go out, treat it as a freeze: "
        + _UPDATE_DRIVERS[0].lower() + _UPDATE_DRIVERS[1:]
    ),
)

INCIDENT_RULES = (BLUE_SCREEN, FORCED_POWER_OFF, POWER_LOSS)


def _build_index(rules: tuple[Rule, ...]) -> dict[tuple[str, int], Rule]:
    index: dict[tuple[str, int], Rule] = {}
    for rule in rules:
        for provider in rule.providers:
            for event_id in rule.event_ids:
                key = (provider.lower(), event_id)
                if key in index:
                    raise ValueError(f"Duplicate catalog entry for {key}")
                index[key] = rule
    return index


_INDEX = _build_index(RULES)


def event_key(event: Event) -> tuple[str, int]:
    """The case-insensitive (provider, event ID) key used for lookups."""
    return (event.provider.lower(), event.event_id)


def lookup(event: Event) -> Rule | None:
    """Return the catalog rule for an event, or None if it isn't recognised."""
    return _INDEX.get(event_key(event))
