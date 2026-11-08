import json

from eventlens import cli
from eventlens.analyzer import analyze
from eventlens.catalog import ROUTINE_SERVICES, RULES
from eventlens.cli import main

SCM = "Service Control Manager"
ISD = "Interactive Services Detection"


def run_with(monkeypatch, events, *args):
    monkeypatch.setattr(cli, "read_file", lambda path: events)
    return main(["--file", "x.evtx", *args])


def isd_events(make_event, count=10):
    return [make_event(SCM, 7034, minutes=i, data={"param1": ISD}) for i in range(count)]


def by_key(analysis):
    return {f.rule.key: f for f in analysis.findings}


def test_routine_events_become_one_info_finding(make_event):
    found = by_key(analyze(isd_events(make_event)))
    assert set(found) == {"routine-service-errors"}
    finding = found["routine-service-errors"]
    assert finding.count == 10
    reason = ROUTINE_SERVICES[0].reason
    assert dict(finding.details) == {f"{ISD}: {reason}": 10}
    assert "service-crashed" not in found


def test_real_service_failures_are_unchanged(make_event):
    events = [make_event(SCM, 7034, minutes=i, data={"param1": "Print Spooler"}) for i in range(2)]
    found = by_key(analyze(events))
    assert found["service-crashed"].count == 2
    assert found["service-crashed"].severity.name == "HIGH"
    assert "routine-service-errors" not in found


def test_mixed_log_splits_with_counts_that_add_up(make_event):
    events = isd_events(make_event, 3) + [
        make_event(SCM, 7034, minutes=20 + i, data={"param1": "Print Spooler"}) for i in range(2)
    ]
    found = by_key(analyze(events))
    assert found["service-crashed"].count == 2
    assert dict(found["service-crashed"].details) == {"Print Spooler": 2}
    assert found["routine-service-errors"].count == 3


def test_name_matching_ignores_case_and_padding(make_event):
    events = [make_event(SCM, 7034, data={"param1": "  interactive services detection "})]
    assert set(by_key(analyze(events))) == {"routine-service-errors"}


def test_service_timeout_uses_the_second_field(make_event):
    events = [make_event(SCM, 7009, data={"param1": "30000", "param2": ISD})]
    found = by_key(analyze(events))
    assert "routine-service-errors" in found
    assert "service-start-failed" not in found


def test_event_without_a_service_name_is_never_routine(make_event):
    found = by_key(analyze([make_event(SCM, 7034)]))
    assert found["service-crashed"].count == 1
    assert "routine-service-errors" not in found


def test_routine_only_log_is_not_a_problem(make_event):
    analysis = analyze(isd_events(make_event))
    assert analysis.problems == []
    assert analysis.verdict == "No significant problems found."
    assert [f.rule.key for f in analysis.normal] == ["routine-service-errors"]


def test_routine_only_log_passes_fail_on(make_event, monkeypatch):
    assert run_with(monkeypatch, isd_events(make_event), "--fail-on", "low") == 0


def test_real_failure_still_trips_fail_on_alongside_routine_events(make_event, monkeypatch):
    events = isd_events(make_event) + [
        make_event(SCM, 7034, minutes=30, data={"param1": "Print Spooler"})
    ]
    assert run_with(monkeypatch, events, "--fail-on", "high") == 1


def test_text_output_lists_the_routine_service(make_event, monkeypatch, capsys):
    run_with(monkeypatch, isd_events(make_event))
    out = capsys.readouterr().out
    assert "Services that log errors routinely: 10 times" in out
    assert ISD in out
    assert ROUTINE_SERVICES[0].reason in " ".join(out.split())


def test_markdown_output_lists_the_routine_service(make_event, monkeypatch, capsys):
    run_with(monkeypatch, isd_events(make_event), "--format", "markdown")
    assert "- Services that log errors routinely: 10 times" in capsys.readouterr().out


def test_json_output_puts_it_under_normal(make_event, monkeypatch, capsys):
    run_with(monkeypatch, isd_events(make_event), "--format", "json")
    data = json.loads(capsys.readouterr().out)
    assert data["findings"] == []
    assert data["normal"][0]["id"] == "routine-service-errors"
    assert data["normal"][0]["count"] == 10
    assert data["schema_version"] == 1


def test_bundled_routine_services_name_existing_rules():
    keys = {rule.key for rule in RULES}
    for entry in ROUTINE_SERVICES:
        assert set(entry.rules) <= keys
