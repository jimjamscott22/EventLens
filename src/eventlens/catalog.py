"""The catalog of Windows events EventLens knows how to explain.

Each ``Rule`` maps one or more (provider, event ID) pairs to a plain-English
title, meaning, and next step. Crash events (Kernel-Power 41, EventLog 6008,
and BugCheck 1001) are not rules: the analyzer combines them into incidents,
described by the ``BLUE_SCREEN``, ``FORCED_POWER_OFF``, and ``POWER_LOSS``
rules in this module. The ordinary rules and the blue screen stop codes live in
``catalog.toml``, which this module loads at import time.

All text is ASCII so the report prints on any Windows console.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from importlib.resources import files
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

# --- Sleep problems worked out from pairs of sleep, wake, and crash events ---

CRASH_WHILE_ASLEEP = Rule(
    key="crash-while-asleep",
    providers=(),
    event_ids=(),
    severity=Severity.HIGH,
    title="PC shut down unexpectedly while asleep",
    meaning=(
        "The PC went to sleep and never woke up normally: it later started from "
        "scratch after a crash or power loss. On a laptop the battery usually ran "
        "flat while asleep; otherwise the PC failed to resume."
    ),
    action=(
        "On a laptop, check the battery health and what drains it in sleep "
        "(run 'powercfg /sleepstudy /xml' and use --sleepstudy). If it keeps "
        "happening on mains power, update the BIOS, chipset, and graphics drivers, "
        "or turn off hybrid sleep and Fast Startup."
    ),
    detail_label="Asleep for",
)

WAKES_IMMEDIATELY = Rule(
    key="wakes-immediately",
    providers=(),
    event_ids=(),
    severity=Severity.MEDIUM,
    title="PC keeps waking up right after going to sleep",
    meaning=(
        "Something wakes the PC within a couple of minutes of every sleep, so it "
        "never rests. This wastes battery and can leave a laptop hot in a bag."
    ),
    action=(
        "Run 'powercfg /lastwake' in a command prompt to see what woke the PC. "
        "Unplug USB devices, and turn off wake permission for the mouse, network "
        "adapter, or timer it names in Device Manager or Power Options."
    ),
)

ROUTINE_SERVICE_ERRORS = Rule(
    key="routine-service-errors",
    providers=(),
    event_ids=(),
    severity=Severity.INFO,
    title="Services that log errors routinely",
    meaning=(
        "These services log errors as part of normal operation. They are listed "
        "here so they don't hide real service problems."
    ),
)

DERIVED_RULES = (CRASH_WHILE_ASLEEP, WAKES_IMMEDIATELY, ROUTINE_SERVICE_ERRORS)


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


# --- Loading a catalog from TOML ---


class CatalogError(ValueError):
    """The catalog text is invalid. Messages start with the offending entry."""


@dataclass(frozen=True)
class RoutineService:
    """A service whose stop or crash events are routine."""

    name: str
    reason: str
    rules: tuple[str, ...]


@dataclass(frozen=True)
class Catalog:
    rules: tuple[Rule, ...]
    stop_codes: dict[int, tuple[str, str]]
    routine_services: tuple[RoutineService, ...]


EXTRACTORS: dict[str, DetailFn] = {
    "first_param": _first_param,
    "service": _service,
    "app_crash": _app_crash,
    "app_hang": _app_hang,
    "dotnet_crash": _dotnet_crash,
    "windows_update": _windows_update,
    "planned_restart": _planned_restart,
}

_REQUIRED_RULE_FIELDS = ("key", "providers", "event_ids", "severity", "title", "meaning")
_OPTIONAL_RULE_FIELDS = ("action", "escalate", "detail", "detail_label")
_STOP_CODE_KEY = re.compile(r"0[xX][0-9A-Fa-f]+")


def _check_ascii(label: str, value: str, what: str) -> None:
    if not value.isascii():
        raise CatalogError(f"{label}: {what} must be ASCII")


def _severity(label: str, value: object, what: str = "severity") -> Severity:
    if not isinstance(value, str) or value.upper() not in Severity.__members__:
        names = ", ".join(n.lower() for n in Severity.__members__)
        raise CatalogError(f"{label}: {what} must be one of {names}, got {value!r}")
    return Severity[value.upper()]


def _text(label: str, table: dict, name: str, default: str | None = None) -> str:
    value = table.get(name, default)
    if not isinstance(value, str):
        raise CatalogError(f"{label}: {name} must be a string")
    _check_ascii(label, value, name)
    return value


def _detail(label: str, value: object) -> DetailFn | None:
    if value is None:
        return None
    if isinstance(value, str):
        if value not in EXTRACTORS:
            known = ", ".join(sorted(EXTRACTORS))
            raise CatalogError(f"{label}: unknown detail extractor {value!r} (known: {known})")
        return EXTRACTORS[value]
    if isinstance(value, dict) and set(value) == {"field"}:
        names = value["field"]
        if (
            not isinstance(names, list)
            or not names
            or not all(isinstance(n, str) and n for n in names)
        ):
            raise CatalogError(f"{label}: detail field must be a non-empty list of names")
        for name in names:
            _check_ascii(label, name, "detail field name")
        field_names = tuple(names)
        return lambda event: field(event, *field_names)
    raise CatalogError(f"{label}: detail must be an extractor name or {{ field = [names] }}")


def _parse_rule(index: int, table: object) -> Rule:
    if not isinstance(table, dict):
        raise CatalogError(f"rule #{index + 1}: must be a table")
    raw_key = table.get("key")
    label = f"rule {raw_key!r}" if isinstance(raw_key, str) else f"rule #{index + 1}"
    for name in _REQUIRED_RULE_FIELDS:
        if name not in table:
            raise CatalogError(f"{label}: missing required field {name}")
    unknown = sorted(set(table) - set(_REQUIRED_RULE_FIELDS) - set(_OPTIONAL_RULE_FIELDS))
    if unknown:
        raise CatalogError(f"{label}: unknown field {', '.join(unknown)}")

    key = _text(label, table, "key")
    providers = table["providers"]
    if not isinstance(providers, list) or not all(isinstance(p, str) for p in providers):
        raise CatalogError(f"{label}: providers must be a list of strings")
    for provider in providers:
        _check_ascii(label, provider, "providers")
    event_ids = table["event_ids"]
    if not isinstance(event_ids, list) or not all(
        isinstance(i, int) and not isinstance(i, bool) for i in event_ids
    ):
        raise CatalogError(f"{label}: event_ids must be a list of integers")
    severity = _severity(label, table["severity"])

    escalate = None
    if "escalate" in table:
        spec = table["escalate"]
        if not isinstance(spec, dict) or set(spec) != {"count", "severity"}:
            raise CatalogError(f"{label}: escalate must be {{ count, severity }}")
        count = spec["count"]
        if not isinstance(count, int) or isinstance(count, bool) or count < 2:
            raise CatalogError(f"{label}: escalate count must be an integer of at least 2")
        target = _severity(label, spec["severity"], "escalate severity")
        if target <= severity:
            raise CatalogError(f"{label}: escalate severity must be above the rule's severity")
        escalate = (count, target)

    return Rule(
        key=key,
        providers=tuple(providers),
        event_ids=tuple(event_ids),
        severity=severity,
        title=_text(label, table, "title"),
        meaning=_text(label, table, "meaning"),
        action=_text(label, table, "action", ""),
        escalate=escalate,
        detail=_detail(label, table.get("detail")),
        detail_label=_text(label, table, "detail_label", "Details"),
    )


def _parse_stop_codes(table: object) -> dict[int, tuple[str, str]]:
    if not isinstance(table, dict):
        raise CatalogError("stop_codes: must be a table")
    codes: dict[int, tuple[str, str]] = {}
    for raw, entry in table.items():
        label = f"stop code {raw!r}"
        if not _STOP_CODE_KEY.fullmatch(raw):
            raise CatalogError(f"{label}: key must be hex like 0x0A")
        code = int(raw, 16)
        if code in codes:
            raise CatalogError(f"{label}: Duplicate stop code 0x{code:X}")
        if not isinstance(entry, dict) or set(entry) != {"name", "hint"}:
            raise CatalogError(f"{label}: must be {{ name, hint }}")
        codes[code] = (_text(label, entry, "name"), _text(label, entry, "hint"))
    return codes


_DEFAULT_SERVICE_RULES = ("service-start-failed", "service-crashed")


def _parse_routine_services(raw: object, rule_keys: set[str]) -> tuple[RoutineService, ...]:
    if not isinstance(raw, list) or not all(isinstance(t, dict) for t in raw):
        raise CatalogError("catalog: routine_service must be an array of tables")
    services: list[RoutineService] = []
    for i, table in enumerate(raw):
        name = table.get("name")
        if not isinstance(name, str) or not name:
            raise CatalogError(f"routine_service #{i + 1}: name must be a non-empty string")
        label = f"routine_service {name!r}"
        _check_ascii(label, name, "name")
        unknown = sorted(set(table) - {"name", "reason", "rules"})
        if unknown:
            raise CatalogError(f"{label}: unknown field {', '.join(unknown)}")
        if "reason" not in table:
            raise CatalogError(f"{label}: missing required field reason")
        reason = _text(label, table, "reason")
        rules = _DEFAULT_SERVICE_RULES
        if "rules" in table:
            listed = table["rules"]
            if (
                not isinstance(listed, list)
                or not listed
                or not all(isinstance(k, str) for k in listed)
            ):
                raise CatalogError(f"{label}: rules must be a non-empty list of rule keys")
            for key in listed:
                if key not in rule_keys:
                    raise CatalogError(f"{label}: unknown rule {key!r}")
            rules = tuple(listed)
        services.append(RoutineService(name=name, reason=reason, rules=rules))
    return tuple(services)


def parse_catalog(text: str) -> Catalog:
    """Parse and validate catalog TOML. Raises ``CatalogError`` naming the bad entry."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise CatalogError(f"catalog: invalid TOML: {exc}") from exc
    unknown = sorted(set(data) - {"rule", "stop_codes", "routine_service"})
    if unknown:
        raise CatalogError(f"catalog: unknown top-level key {', '.join(unknown)}")
    raw_rules = data.get("rule", [])
    if not isinstance(raw_rules, list):
        raise CatalogError("catalog: rule must be an array of tables")

    rules: list[Rule] = []
    seen_keys: set[str] = set()
    for i, raw in enumerate(raw_rules):
        rule = _parse_rule(i, raw)
        label = f"rule {rule.key!r}"
        if rule.key in seen_keys:
            raise CatalogError(f"{label}: Duplicate key")
        seen_keys.add(rule.key)
        rules.append(rule)
        try:
            _build_index(tuple(rules))
        except ValueError as exc:
            raise CatalogError(f"{label}: {exc}") from exc

    return Catalog(
        rules=tuple(rules),
        stop_codes=_parse_stop_codes(data.get("stop_codes", {})),
        routine_services=_parse_routine_services(data.get("routine_service", []), seen_keys),
    )


_CATALOG = parse_catalog(files("eventlens").joinpath("catalog.toml").read_text(encoding="utf-8"))
RULES: tuple[Rule, ...] = _CATALOG.rules
STOP_CODES: dict[int, tuple[str, str]] = _CATALOG.stop_codes
ROUTINE_SERVICES: tuple[RoutineService, ...] = _CATALOG.routine_services
_INDEX = _build_index(RULES)


def routine_service_for(
    rule: Rule,
    detail: str | None,
    services: tuple[RoutineService, ...] = ROUTINE_SERVICES,
) -> RoutineService | None:
    """Return the routine-service entry for a service event, or None."""
    if detail is None:
        return None
    wanted = detail.strip().casefold()
    for service in services:
        if rule.key in service.rules and service.name.casefold() == wanted:
            return service
    return None


def event_key(event: Event) -> tuple[str, int]:
    """The case-insensitive (provider, event ID) key used for lookups."""
    return (event.provider.lower(), event.event_id)


def lookup(event: Event) -> Rule | None:
    """Return the catalog rule for an event, or None if it isn't recognised."""
    return _INDEX.get(event_key(event))
