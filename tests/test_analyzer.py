from datetime import timedelta

from conftest import BASE_TIME

from eventlens.analyzer import analyze, classify_incident
from eventlens.catalog import Severity
from eventlens.models import Level

POWER = "Microsoft-Windows-Kernel-Power"
BUGCHECK = "Microsoft-Windows-WER-SystemErrorReporting"


def keys(analysis):
    return [f.rule.key for f in analysis.findings]


def finding(analysis, key):
    return next(f for f in analysis.findings if f.rule.key == key)


# --- Crash incidents ---


def test_crash_events_from_one_restart_are_one_incident(make_event):
    events = [
        make_event(POWER, 41, data={"BugcheckCode": "159"}),
        make_event("EventLog", 6008, minutes=0.5),
        make_event(BUGCHECK, 1001, minutes=2, data={"param1": "0x0000009f (0x3)"}),
    ]
    analysis = analyze(events)
    assert keys(analysis) == ["blue-screen"]
    crash = analysis.findings[0]
    assert crash.count == 1
    assert list(crash.details) == [
        "DRIVER_POWER_STATE_FAILURE (0x9F): a driver failed during sleep or wake"
    ]


def test_events_more_than_ten_minutes_apart_are_separate_incidents(make_event):
    events = [make_event(POWER, 41), make_event("EventLog", 6008, minutes=11)]
    assert finding(analyze(events), "power-loss").count == 2


def test_repeated_event_id_starts_a_new_incident(make_event):
    # Two restarts in quick succession: each writes its own Kernel-Power 41.
    events = [make_event(POWER, 41), make_event(POWER, 41, minutes=4)]
    assert finding(analyze(events), "power-loss").count == 2


def test_crash_events_from_different_computers_are_separate_incidents(make_event):
    # Two PCs, each with half of the evidence for one crash.
    events = [
        make_event(POWER, 41, computer="PC1"),
        make_event("EventLog", 6008, minutes=1, computer="PC2"),
    ]
    assert finding(analyze(events), "power-loss").count == 2


def test_blue_screen_evidence_stays_with_its_computer(make_event):
    events = [
        make_event(POWER, 41, computer="PC1", data={"BugcheckCode": "159"}),
        make_event("EventLog", 6008, minutes=1, computer="PC2"),
    ]
    analysis = analyze(events)
    assert finding(analysis, "blue-screen").count == 1
    assert finding(analysis, "power-loss").count == 1  # PC2 is not blamed on a blue screen


def test_computer_names_are_compared_ignoring_case(make_event):
    events = [
        make_event(POWER, 41, computer="Test-PC"),
        make_event("EventLog", 6008, minutes=1, computer="TEST-PC"),
    ]
    assert finding(analyze(events), "power-loss").count == 1


def test_incident_time_is_its_earliest_event(make_event):
    events = [make_event("EventLog", 6008, minutes=3), make_event(POWER, 41, minutes=1)]
    crash = analyze(events).findings[0]
    assert crash.first == crash.last == BASE_TIME + timedelta(minutes=1)


def test_kernel_power_bugcheck_code_alone_means_blue_screen(make_event):
    rule, detail = classify_incident([make_event(POWER, 41, data={"BugcheckCode": "308"})])
    assert rule.key == "blue-screen"
    assert detail == "Stop code 0x134"  # 308 in decimal, not in the stop code table


def test_bugcheck_event_without_code_is_still_a_blue_screen(make_event):
    rule, detail = classify_incident([make_event(BUGCHECK, 1001)])
    assert rule.key == "blue-screen"
    assert detail == "Stop code not recorded"


def test_bugcheck_event_code_wins_over_kernel_power(make_event):
    events = [
        make_event(POWER, 41, data={"BugcheckCode": "159"}),
        make_event(BUGCHECK, 1001, data={"param1": "0x00000124"}),
    ]
    _, detail = classify_incident(events)
    assert detail.startswith("WHEA_UNCORRECTABLE_ERROR (0x124)")


def test_power_button_means_forced_power_off(make_event):
    event = make_event(POWER, 41, data={"BugcheckCode": "0", "PowerButtonTimestamp": "1340"})
    rule, detail = classify_incident([event])
    assert (rule.key, detail) == ("forced-power-off", None)


def test_no_evidence_means_power_loss(make_event):
    event = make_event(POWER, 41, data={"BugcheckCode": "0", "PowerButtonTimestamp": "0"})
    assert classify_incident([event])[0].key == "power-loss"
    assert classify_incident([make_event("EventLog", 6008)])[0].key == "power-loss"


# --- Grouping, escalation, and ranking ---


def test_matching_events_are_grouped_with_details(make_event):
    events = [
        make_event("Application Error", 1000, minutes=i, data={"param1": app})
        for i, app in enumerate(["a.exe", "a.exe", "b.exe"])
    ]
    crash = finding(analyze(events), "app-crash")
    assert crash.count == 3
    assert crash.details == {"a.exe": 2, "b.exe": 1}
    assert crash.first == BASE_TIME
    assert crash.last == BASE_TIME + timedelta(minutes=2)
    assert crash.sample.data["param1"] == "b.exe"


def test_frequent_events_escalate(make_event):
    events = [make_event("Application Error", 1000, minutes=i) for i in range(5)]
    assert finding(analyze(events), "app-crash").severity is Severity.HIGH
    assert finding(analyze(events[:4]), "app-crash").severity is Severity.MEDIUM


def test_findings_rank_by_severity_then_count_then_recency(make_event):
    events = [
        make_event("Microsoft-Windows-DNS-Client", 1014, level=Level.WARNING),  # low
        make_event("disk", 7),  # critical
        make_event("Service Control Manager", 7000, minutes=1),  # medium, 1 time
        make_event("Microsoft-Windows-WindowsUpdateClient", 20, minutes=5),  # medium, newer
        make_event("Microsoft-Windows-Kernel-PnP", 219),  # medium, 2 times
        make_event("Microsoft-Windows-Kernel-PnP", 219, minutes=1),
    ]
    assert keys(analyze(events)) == [
        "disk-bad-block",
        "driver-load-failed",
        "update-failed",
        "service-start-failed",
        "dns-timeout",
    ]


def test_events_before_the_window_are_dropped(make_event):
    events = [make_event("disk", 7, minutes=-1), make_event("disk", 7, minutes=1)]
    analysis = analyze(events, since=BASE_TIME)
    assert finding(analysis, "disk-bad-block").count == 1
    assert analysis.events_read == 2
    assert analysis.events_in_window == 1
    assert analysis.start == analysis.end == BASE_TIME + timedelta(minutes=1)


# --- Unrecognised events ---


def test_unrecognised_errors_are_grouped_and_sorted_by_count(make_event):
    events = [
        make_event("Other", 1),
        make_event("Other", 1, minutes=1),
        make_event("Rare", 2, level=Level.CRITICAL),
        make_event("Info", 3, level=Level.INFORMATION),
    ]
    groups = analyze(events).unrecognised
    assert [(g.provider, g.event_id, g.count) for g in groups] == [("Other", 1, 2), ("Rare", 2, 1)]


def test_unrecognised_warnings_need_opt_in(make_event):
    events = [make_event("Noisy", 27, level=Level.WARNING)]
    assert analyze(events).unrecognised == []
    assert analyze(events, include_warnings=True).unrecognised[0].provider == "Noisy"


def test_unrecognised_group_keeps_most_severe_level(make_event):
    events = [
        make_event("Mixed", 5, level=Level.ERROR),
        make_event("Mixed", 5, level=Level.CRITICAL, minutes=1),
    ]
    assert analyze(events).unrecognised[0].level is Level.CRITICAL


# --- Verdict and headline ---


def test_clean_logs(make_event):
    analysis = analyze([make_event("Info", 1, level=Level.INFORMATION)])
    assert analysis.verdict == "No significant problems found."
    assert analysis.headline == "Nothing in these logs needs attention."


def test_info_only_findings_are_not_problems(make_event):
    analysis = analyze([make_event("Microsoft-Windows-DistributedCOM", 10016)])
    assert analysis.verdict == "No significant problems found."
    assert analysis.problems == []
    assert [f.rule.key for f in analysis.normal] == ["dcom-10016"]


def test_minor_and_high_verdicts(make_event):
    minor = analyze([make_event("Microsoft-Windows-DNS-Client", 1014)])
    assert minor.verdict == "Minor issues found."
    assert minor.headline == "Top issue: website name lookups timed out (1 time)."
    high = analyze([make_event("Display", 4101)])
    assert high.verdict == "Problems found that need attention."


def test_crash_headline_counts_all_incidents(make_event):
    events = [
        make_event(POWER, 41, data={"BugcheckCode": "159"}),
        make_event(POWER, 41, minutes=60),
        make_event(POWER, 41, minutes=120, data={"BugcheckCode": "159"}),
    ]
    analysis = analyze(events)
    assert analysis.verdict == "Serious problems found."
    assert analysis.headline == (
        "This PC shut down unexpectedly 3 times, including 2 blue screen crashes."
    )


def test_crash_headline_singular(make_event):
    analysis = analyze([make_event(BUGCHECK, 1001)])
    assert analysis.headline == (
        "This PC shut down unexpectedly 1 time, including 1 blue screen crash."
    )


def test_computers_listed_most_common_first(make_event):
    events = [
        make_event("A", 1, computer="PC-2"),
        make_event("A", 1, computer="PC-1"),
        make_event("A", 1, computer="PC-1"),
    ]
    assert analyze(events).computers == ["PC-1", "PC-2"]
