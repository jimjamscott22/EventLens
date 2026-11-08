"""Tests for the validating TOML catalog loader."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from eventlens.catalog import CatalogError, Severity, parse_catalog
from eventlens.models import Event, Level


def _event(data: dict[str, str]) -> Event:
    return Event(
        provider="p",
        event_id=1,
        level=Level.ERROR,
        time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        data=data,
    )


def RULE(key: str = "x", extra: str = "", **overrides: str) -> str:
    fields = {
        "key": f'"{key}"',
        "providers": '["Prov"]',
        "event_ids": "[1]",
        "severity": '"medium"',
        "title": '"T"',
        "meaning": '"M"',
    }
    fields.update(overrides)
    body = "\n".join(f"{k} = {v}" for k, v in fields.items() if v is not None)
    return f"[[rule]]\n{body}\n{extra}\n"


def test_minimal_rule_gets_defaults() -> None:
    (rule,) = parse_catalog(RULE()).rules
    assert rule.severity is Severity.MEDIUM
    assert rule.action == ""
    assert rule.detail is None
    assert rule.detail_label == "Details"
    assert rule.escalate is None


def test_escalate_is_parsed() -> None:
    text = RULE(extra='escalate = { count = 10, severity = "high" }')
    (rule,) = parse_catalog(text).rules
    assert rule.escalate == (10, Severity.HIGH)


def test_named_extractor() -> None:
    (rule,) = parse_catalog(RULE(extra='detail = "service"')).rules
    assert rule.detail is not None
    assert rule.detail(_event({"param1": "Print Spooler"})) == "Print Spooler"


def test_field_extractor_returns_first_non_empty_field() -> None:
    (rule,) = parse_catalog(RULE(extra='detail = { field = ["A", "B"] }')).rules
    assert rule.detail is not None
    assert rule.detail(_event({"A": " ", "B": "x"})) == "x"
    assert rule.detail(_event({})) is None


def test_stop_codes_parse() -> None:
    text = '[stop_codes]\n"0x0A" = { name = "NAME", hint = "hint" }\n'
    assert parse_catalog(text).stop_codes == {0x0A: ("NAME", "hint")}


@pytest.mark.parametrize(
    ("text", "pattern"),
    [
        (RULE(title=None), r"rule 'x'.*title"),
        (RULE() + RULE(event_ids="[2]"), r"rule 'x'.*Duplicate key"),
        (
            RULE("a", providers='["disk"]', event_ids="[7]")
            + RULE("b", providers='["Disk"]', event_ids="[7]"),
            r"rule 'b'.*Duplicate",
        ),
        (RULE(severity='"urgent"'), r"rule 'x'.*severity"),
        (RULE(extra='detail = "nope"'), r"rule 'x'.*extractor"),
        (RULE(extra="detail = { field = [] }"), r"rule 'x'.*field"),
        (
            RULE(extra='escalate = { count = 10, severity = "low" }'),
            r"rule 'x'.*escalate",
        ),
        (
            RULE(extra='escalate = { count = 1, severity = "high" }'),
            r"rule 'x'.*escalate",
        ),
        (RULE(extra='severty = "low"'), r"rule 'x'.*severty"),
        (RULE(title='"a — b"'), r"rule 'x'.*ASCII"),
        ('[stop_codes]\n"9F" = { name = "N", hint = "h" }\n', r"stop code '9F'"),
        (
            '[stop_codes]\n"0x0A" = { name = "N", hint = "h" }\n'
            '"0x0a" = { name = "N", hint = "h" }\n',
            r"stop code.*Duplicate",
        ),
        (
            '[stop_codes]\n"0x0A" = { name = "N", hint = "café" }\n',
            r"stop code '0x0A'.*ASCII",
        ),
    ],
)
def test_invalid_catalogs_name_the_entry(text: str, pattern: str) -> None:
    with pytest.raises(CatalogError, match=pattern):
        parse_catalog(text)


def test_catalog_error_is_a_value_error() -> None:
    assert issubclass(CatalogError, ValueError)


def test_bundled_catalog_has_23_rules_and_12_stop_codes() -> None:
    from eventlens import catalog

    assert len(catalog.RULES) == 23
    assert len(catalog.STOP_CODES) == 12


def _bundled_text() -> str:
    from importlib.resources import files

    return files("eventlens").joinpath("catalog.toml").read_text(encoding="utf-8")


def test_bundled_text_is_ascii() -> None:
    assert _bundled_text().isascii()


def test_crlf_checkout_loads_identically() -> None:
    text = _bundled_text()
    from dataclasses import replace

    def comparable(rules):
        # `{ field = [...] }` details build a fresh lambda per parse, so compare behaviour
        # separately from the data fields.
        return [(replace(r, detail=None), r.detail is None) for r in rules]

    crlf = parse_catalog(text.replace("\n", "\r\n")).rules
    assert comparable(crlf) == comparable(parse_catalog(text).rules)
