import pytest

from eventlens import catalog
from eventlens.catalog import (
    CRASH_EVENTS,
    INCIDENT_RULES,
    RULES,
    Severity,
    describe_stop_code,
    lookup,
    parse_stop_code,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("159", 0x9F),
        ("0x0000009f", 0x9F),
        ("0x0000009f (0x0000000000000003, 0xffffc206a1e5c060)", 0x9F),
        ("0X124", 0x124),
        ("0", 0),
        ("", None),
        ("   ", None),
        (None, None),
        ("not a code", None),
    ],
)
def test_parse_stop_code(value, expected):
    assert parse_stop_code(value) == expected


def test_describe_known_stop_code():
    assert describe_stop_code(0x9F) == (
        "DRIVER_POWER_STATE_FAILURE (0x9F): a driver failed during sleep or wake"
    )


def test_describe_unknown_stop_code_falls_back_to_hex():
    assert describe_stop_code(0xABC) == "Stop code 0xABC"


@pytest.mark.parametrize("rule", RULES + INCIDENT_RULES, ids=lambda r: r.key)
def test_every_rule_is_explained(rule):
    assert rule.title and rule.meaning
    if rule.severity > Severity.INFO:
        assert rule.action, "problems need a 'what to do'"
    # Plain ASCII so the report prints on any Windows console.
    for text in (rule.title, rule.meaning, rule.action):
        assert text.isascii()


@pytest.mark.parametrize(
    ("provider", "event_id", "rule"),
    [(p, i, r) for r in RULES for p in r.providers for i in r.event_ids],
    ids=lambda v: v.key if hasattr(v, "key") else str(v),
)
def test_every_catalog_entry_is_matched(make_event, provider, event_id, rule):
    assert lookup(make_event(provider, event_id)) is rule


def test_rule_keys_are_unique():
    keys = [rule.key for rule in RULES + INCIDENT_RULES]
    assert len(keys) == len(set(keys))


def test_crash_events_are_not_catalog_rules(make_event):
    for provider, event_id in CRASH_EVENTS:
        assert lookup(make_event(provider, event_id)) is None


def test_duplicate_catalog_entries_are_rejected():
    rule = RULES[0]
    with pytest.raises(ValueError, match="Duplicate"):
        catalog._build_index((rule, rule))


def test_lookup_ignores_provider_case(make_event):
    assert lookup(make_event("APPLICATION ERROR", 1000)).key == "app-crash"


def test_lookup_supports_provider_aliases(make_event):
    assert lookup(make_event("Ntfs", 55)).key == "ntfs-corruption"
    assert lookup(make_event("Microsoft-Windows-Ntfs", 55)).key == "ntfs-corruption"


def test_lookup_unknown_event(make_event):
    assert lookup(make_event("Something-Else", 1)) is None


def test_escalation():
    rule = next(r for r in RULES if r.key == "whea-memory")
    assert rule.severity_for(9) is Severity.LOW
    assert rule.severity_for(10) is Severity.HIGH


def test_rules_without_escalation_keep_their_severity():
    rule = next(r for r in RULES if r.key == "disk-bad-block")
    assert rule.severity_for(1000) is Severity.CRITICAL


# --- Detail extractors ---


def detail_for(event):
    rule = lookup(event)
    return rule.detail(event)


def test_app_crash_detail_with_classic_unnamed_fields(make_event):
    event = make_event(
        "Application Error",
        1000,
        data={"param1": "game.exe", "param2": "1.0", "param3": "x", "param4": "d3d11.dll"},
    )
    assert detail_for(event) == "game.exe (module: d3d11.dll)"


def test_app_crash_detail_with_named_fields(make_event):
    event = make_event(
        "Application Error", 1000, data={"AppName": "notepad.exe", "ModuleName": "ntdll.dll"}
    )
    assert detail_for(event) == "notepad.exe (module: ntdll.dll)"


def test_app_crash_detail_without_module(make_event):
    assert detail_for(make_event("Application Error", 1000, data={"param1": "a.exe"})) == "a.exe"


def test_app_crash_detail_missing(make_event):
    assert detail_for(make_event("Application Error", 1000)) is None


def test_dotnet_detail(make_event):
    event = make_event(
        ".NET Runtime",
        1026,
        data={"param1": "Application: Tool.exe\nFramework Version: v4.0.30319"},
    )
    assert detail_for(event) == "Tool.exe"


def test_windows_update_detail(make_event):
    event = make_event(
        "Microsoft-Windows-WindowsUpdateClient",
        20,
        data={"updateTitle": "KB123", "errorCode": "0x800f0922"},
    )
    assert detail_for(event) == "KB123, error 0x800f0922"


def test_planned_restart_detail(make_event):
    event = make_event(
        "User32",
        1074,
        data={
            "param1": r"C:\Windows\servicing\TrustedInstaller.exe (TEST-PC)",
            "param5": "restart",
        },
    )
    assert detail_for(event) == "restart requested by TrustedInstaller.exe"


def test_service_detail(make_event):
    event = make_event("Service Control Manager", 7031, data={"param1": "Print Spooler"})
    assert detail_for(event) == "Print Spooler"


def test_service_timeout_detail_uses_second_field(make_event):
    event = make_event(
        "Service Control Manager", 7009, data={"param1": "30000", "param2": "Print Spooler"}
    )
    assert detail_for(event) == "Print Spooler"
