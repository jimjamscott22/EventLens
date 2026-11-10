# M5 Catalog Data File Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the 23 catalog rules and the stop-code table into a bundled `catalog.toml`, and report services that log errors routinely as a separate Info finding instead of a High "Service stopped unexpectedly".

**Architecture:** `catalog.py` keeps `Rule`, `Severity`, `lookup()` and its whole public surface, but builds `RULES`, `STOP_CODES` and a new `ROUTINE_SERVICES` by parsing `catalog.toml` (stdlib `tomllib`, read through `importlib.resources`). Detail extraction is a named registry plus a generic `{ field = [...] }` form. The analyzer diverts routine-service events into one derived Info rule, `routine-service-errors`. Crash and sleep rules stay in Python.

**Tech Stack:** Python 3.11+, `tomllib`, `importlib.resources`, pytest, ruff, uv. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-08-m5-catalog-data-file-design.md`

## Global Constraints

- Python `>=3.11`; use stdlib `tomllib`; add no dependencies.
- Run everything with uv: `uv run pytest`, `uv run ruff check` (line length 100).
- All catalog text is ASCII (title, meaning, action, stop-code names and hints, routine-service reasons).
- Everything importable from `eventlens.catalog` today stays importable: `Rule`, `Severity`, `RULES`, `STOP_CODES`, `lookup`, `event_key`, `describe_stop_code`, `parse_stop_code`, `field`, `CRASH_EVENTS`, `KERNEL_POWER_41`, `BUGCHECK_1001`, the incident and derived rules.
- Rule wording, severities and escalation are copied verbatim from the current `catalog.py`. The migration is behaviour-neutral.
- `tests/fixtures/sample_week_report.txt` and `.md` stay byte-identical. Never set `EVENTLENS_UPDATE_GOLDEN`.
- JSON `schema_version` stays 1.
- Read `catalog.toml` as UTF-8 explicitly (Windows default encoding is not UTF-8).
- Commit messages end with these two lines:
  ```
  Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01EGEYGEnmqQXEJ58HTrrEQJ
  ```
- Work on branch `claude/vibrant-brahmagupta-s6qp7l`; it already has draft PR jimjamscott22/eventlens#6, so pushes update that PR.

## Review Focus

Inputs the spec implies but no obvious test covers, most likely first. Each has a test in the task named.

1. A routine service whose name differs from the entry in case or padding, for example `"  interactive services detection "`. Expected: still routine. (Task 5)
2. A service-timeout event (7009) for a routine service, where the name is in `param2` and `param1` is the timeout. Expected: routine, not "Service failed to start". (Task 5)
3. A log containing only routine service events. Expected: no problems, verdict "No significant problems found.", `--fail-on low` exits 0. (Task 5)
4. A contributor pastes a smart quote or em dash into `catalog.toml`. Expected: `CatalogError` naming that rule's key, not a mojibake report. (Task 2)
5. `catalog.toml` checked out with CRLF line endings on Windows. Expected: identical rules. (Task 3)

## File Structure

- `src/eventlens/catalog.toml` (create): all data. Rules, stop codes, routine services.
- `src/eventlens/catalog.py` (modify): `Rule`/`Severity`, the extractor registry, the TOML loader and validation, `lookup`, derived and incident rules. The Python rule literals are deleted.
- `src/eventlens/analyzer.py` (modify): divert routine-service events. Nothing else.
- `tests/fixtures/catalog_snapshot.json` (create): frozen copy of today's catalog, for the parity test.
- `tests/test_catalog_parity.py` (create), `tests/test_catalog_loader.py` (create), `tests/test_routine_services.py` (create).
- `README.md`, `docs/SPEC.md` (modify): docs.

Renderers (`report*.py`) and `cli.py` are not touched. Info findings already render in the "Normal activity" section, which prints a finding's title, count and detail lines but not its `meaning`. So the routine-service `reason` travels in the detail string.

---

### Task 1: Pin today's catalog before moving it

**Files:**
- Create: `tests/fixtures/catalog_snapshot.json`
- Create: `tests/test_catalog_parity.py`

**Interfaces:**
- Consumes: `eventlens.catalog.RULES`, `STOP_CODES`, `lookup`
- Produces: a snapshot test that stays green through Tasks 2 to 3 and fails if any rule or stop code drifts

- [ ] **Step 1: Generate the snapshot from the current Python catalog.** Run a one-off `uv run python` snippet (not committed) that writes `tests/fixtures/catalog_snapshot.json`: `{"rules": [...], "stop_codes": {...}}`. Each rule object has `key`, `providers` (list), `event_ids` (list), `severity` (lowercase name), `escalate` (`[count, "severity"]` or `null`), `title`, `meaning`, `action`, `detail_label`, `has_detail` (bool). Keep `RULES` order. `stop_codes` maps `f"0x{code:X}"` to `[name, hint]`. Write it with `indent=2`. Check it holds 23 rules and 12 stop codes.

- [ ] **Step 2: Write `tests/test_catalog_parity.py`** with `test_rules_match_snapshot` (rebuild the same list of dicts from `RULES` and assert equal to the fixture's `rules`), `test_stop_codes_match_snapshot` (same for `STOP_CODES`), and `test_detail_extraction_is_pinned`, parametrized over `(provider, event_id, data, expected)`:

  ```python
  ("disk", 7, {"param1": r"\Device\Harddisk0\DR0"}, r"\Device\Harddisk0\DR0"),
  ("disk", 51, {"param1": r"\Device\Harddisk1\DR1"}, r"\Device\Harddisk1\DR1"),
  ("Display", 4101, {"param1": "nvlddmkm"}, "nvlddmkm"),
  ("Ntfs", 55, {"DriveName": "C:"}, "C:"),
  ("Ntfs", 55, {}, None),
  ("Microsoft-Windows-Kernel-PnP", 219, {"DriverName": r"\Driver\foo"}, r"\Driver\foo"),
  ("Microsoft-Windows-DNS-Client", 1014, {"QueryName": "example.com"}, "example.com"),
  ("Application Hang", 1002, {"AppName": "a.exe"}, "a.exe"),
  ```
  Each case builds the event with the `make_event` fixture and asserts `lookup(event).detail(event) == expected`.

- [ ] **Step 3: Run `uv run pytest tests/test_catalog_parity.py -v`.** Expected: all PASS against the unchanged code (these are characterization tests).

- [ ] **Step 4: Commit** `tests: pin the current catalog before moving it to TOML`.

---

### Task 2: TOML loader with validation

**Files:**
- Modify: `src/eventlens/catalog.py` (add; leave the existing rule literals alone)
- Create: `tests/test_catalog_loader.py`

**Interfaces:**
- Consumes: `Rule`, `Severity`, `DetailFn`, `field`, and the existing helper extractors `_first_param`, `_service`, `_app_crash`, `_app_hang`, `_dotnet_crash`, `_windows_update`, `_planned_restart`
- Produces:
  - `class CatalogError(ValueError)`
  - `@dataclass(frozen=True) class RoutineService: name: str; reason: str; rules: tuple[str, ...]`
  - `@dataclass(frozen=True) class Catalog: rules: tuple[Rule, ...]; stop_codes: dict[int, tuple[str, str]]; routine_services: tuple[RoutineService, ...]`
  - `EXTRACTORS: dict[str, DetailFn]` with keys `first_param`, `service`, `app_crash`, `app_hang`, `dotnet_crash`, `windows_update`, `planned_restart`
  - `parse_catalog(text: str) -> Catalog`. In this task `routine_services` is always `()`.

**Format.** Top-level keys are `rule` (array of tables), `stop_codes` (table), `routine_service` (array of tables, parsed in Task 4). Rule fields: required `key`, `providers`, `event_ids`, `severity`, `title`, `meaning`; optional `action`, `escalate = { count, severity }`, `detail` (a name string or `{ field = [names] }`), `detail_label`. Stop codes: `"0x0A" = { name = "...", hint = "..." }`.

**Error format.** Every `CatalogError` message starts with the entry: `rule 'KEY': <problem>` or `stop code 'KEY': <problem>`.

- [ ] **Step 1: Write the failing tests** in `tests/test_catalog_loader.py`, using a small `RULE` TOML string helper and inline text:
  - `test_minimal_rule_gets_defaults`: parsed rule has `severity is Severity.MEDIUM`, `action == ""`, `detail is None`, `detail_label == "Details"`, `escalate is None`.
  - `test_escalate_is_parsed`: `escalate = { count = 10, severity = "high" }` gives `rule.escalate == (10, Severity.HIGH)`.
  - `test_named_extractor`: `detail = "service"` on a rule makes `rule.detail(event) == "Print Spooler"` for an event with `param1="Print Spooler"`.
  - `test_field_extractor_returns_first_non_empty_field`: `detail = { field = ["A", "B"] }` returns `"x"` for data `{"A": " ", "B": "x"}`, and `None` for `{}`.
  - `test_stop_codes_parse`: `"0x0A"` becomes key `0x0A` with value `("NAME", "hint")`.
  - `test_invalid_catalogs_name_the_entry`, parametrized over `(toml, pattern)` with `pytest.raises(CatalogError, match=pattern)`:
    - missing `title` → `r"rule 'x'.*title"`
    - two rules with the same `key` → `r"rule 'x'.*Duplicate key"`
    - rule `b` reusing `("Disk", 7)` that rule `a` already has under `"disk"` → `r"rule 'b'.*Duplicate"` (provider match is case-insensitive)
    - `severity = "urgent"` → `r"rule 'x'.*severity"`
    - `detail = "nope"` → `r"rule 'x'.*extractor"`
    - `detail = { field = [] }` → `r"rule 'x'.*field"`
    - `escalate` severity not above base → `r"rule 'x'.*escalate"`
    - `escalate` count of 1 → `r"rule 'x'.*escalate"`
    - unknown field `severty = "low"` → `r"rule 'x'.*severty"`
    - title containing an em dash (`—`) → `r"rule 'x'.*ASCII"` (Review Focus 4)
    - stop code key `"9F"` → `r"stop code '9F'"`
    - `"0x0A"` and `"0x0a"` together → `r"stop code.*Duplicate"`
    - non-ASCII stop-code hint → `r"stop code '0x0A'.*ASCII"`
  - `test_catalog_error_is_a_value_error`: `issubclass(CatalogError, ValueError)`.

- [ ] **Step 2: Run `uv run pytest tests/test_catalog_loader.py -v`.** Expected: FAIL (`CatalogError` / `parse_catalog` not defined).

- [ ] **Step 3: Implement `parse_catalog`** and the types above in `catalog.py`. Approach: `tomllib.loads`, then validate each rule and stop code into the dataclasses. Reuse `_build_index` for the duplicate-ID check, but catch its `ValueError` and re-raise `CatalogError` prefixed with the later rule's key. Reject unknown rule fields. `EXTRACTORS` maps names to the existing helper functions; the field form wraps `field(event, *names)`. Do not change the existing `RULES` literals or `_INDEX` yet.

- [ ] **Step 4: Run `uv run pytest tests/test_catalog_loader.py tests/test_catalog.py -v` and `uv run ruff check`.** Expected: PASS, no lint errors.

- [ ] **Step 5: Commit** `catalog: add a validating TOML loader`.

---

### Task 3: Move the data into `catalog.toml`

**Files:**
- Create: `src/eventlens/catalog.toml`
- Modify: `src/eventlens/catalog.py`
- Modify: `tests/test_catalog_loader.py` (add bundled-file tests)

**Interfaces:**
- Consumes: `parse_catalog`, `EXTRACTORS` from Task 2
- Produces: `RULES`, `STOP_CODES` and `_INDEX` built from the bundled file; `_CATALOG: Catalog` module constant for Task 4

- [ ] **Step 1: Write the bundled-file tests** in `tests/test_catalog_loader.py`:
  - `test_bundled_catalog_has_23_rules_and_12_stop_codes`: `len(catalog.RULES) == 23`, `len(catalog.STOP_CODES) == 12`.
  - `test_bundled_text_is_ascii`: the text of `files("eventlens") / "catalog.toml"` satisfies `.isascii()`.
  - `test_crlf_checkout_loads_identically`: `parse_catalog(text.replace("\n", "\r\n")).rules == parse_catalog(text).rules` (Review Focus 5). `tomllib` normalizes CRLF, so this should hold.

  Run them now; expected FAIL (no `catalog.toml` yet).

- [ ] **Step 2: Write `src/eventlens/catalog.toml`.** One `[[rule]]` per current rule, in the current order, and a `[stop_codes]` table. Copy title, meaning and action exactly; the strings are implicit concatenations in Python, so join them into single TOML basic strings (use `"""` with line-ending `\` for long ones). Map the detail lambdas as follows:
  - `_first_param` → `detail = "first_param"` (rules `disk-bad-block`, `disk-paging-error`, `display-reset`)
  - `_app_crash` → `"app_crash"`, `_app_hang` → `"app_hang"`, `_dotnet_crash` → `"dotnet_crash"`, `_service` → `"service"` (both service rules), `_windows_update` → `"windows_update"`, `_planned_restart` → `"planned_restart"`
  - `ntfs-corruption` → `detail = { field = ["DriveName"] }`, `driver-load-failed` → `{ field = ["DriverName"] }`, `dns-timeout` → `{ field = ["QueryName"] }`

- [ ] **Step 3: Switch `catalog.py` to the file.** Add `_CATALOG = parse_catalog(files("eventlens").joinpath("catalog.toml").read_text(encoding="utf-8"))`. Set `RULES = _CATALOG.rules` and `STOP_CODES = _CATALOG.stop_codes`. Delete the Python `RULES` literal, the `STOP_CODES` literal, and any helper no longer referenced outside `EXTRACTORS`. Keep `_UPDATE_DRIVERS` and the incident and derived rules. Update the module docstring to say rules live in `catalog.toml`.

- [ ] **Step 4: Run the whole suite and lint:** `uv run pytest -q` and `uv run ruff check`. Expected: everything PASS, including `tests/test_catalog_parity.py` (this is the parity proof) and the golden report tests with no regeneration.

- [ ] **Step 5: Run the wheel smoke test:** `uv build --wheel && scripts/smoke_test.sh dist/eventlens-*.whl`. Expected: `All smoke tests passed.` (proves `catalog.toml` ships in the wheel).

- [ ] **Step 6: Commit** `catalog: move rules and stop codes into catalog.toml`.

---

### Task 4: Routine-service data and the derived rule

**Files:**
- Modify: `src/eventlens/catalog.toml`
- Modify: `src/eventlens/catalog.py`
- Modify: `tests/test_catalog_loader.py`

**Interfaces:**
- Consumes: `parse_catalog`, `RoutineService`, `_CATALOG`
- Produces:
  - `ROUTINE_SERVICES: tuple[RoutineService, ...]`
  - `routine_service_for(rule: Rule, detail: str | None, services: tuple[RoutineService, ...] = ROUTINE_SERVICES) -> RoutineService | None`: matches when `rule.key` is in the entry's `rules` and `detail.strip().casefold()` equals `name.casefold()`; returns `None` for a `None` detail.
  - `ROUTINE_SERVICE_ERRORS: Rule` (key `"routine-service-errors"`, `Severity.INFO`, title `"Services that log errors routinely"`, meaning `"These services log errors as part of normal operation. They are listed here so they don't hide real service problems."`, no action), added to `DERIVED_RULES`.

- [ ] **Step 1: Write the failing tests** in `tests/test_catalog_loader.py`:
  - `test_seed_routine_service`: `ROUTINE_SERVICES` has exactly one entry, with `name == "Interactive Services Detection"`, `reason == "This Windows service logs a service error as part of normal operation."`, `rules == ("service-start-failed", "service-crashed")`.
  - `test_routine_service_rules_default_to_the_two_service_rules`: a parsed `[[routine_service]]` with no `rules` gets that tuple.
  - `test_routine_service_for_matches_ignoring_case_and_padding`: for the `service-crashed` rule, `"  interactive SERVICES detection "` returns the entry.
  - `test_routine_service_for_misses`: returns `None` for another service name, for `None`, and for the `app-crash` rule with the routine name.
  - `test_entry_limited_to_one_rule`: parse a catalog with `rules = ["service-crashed"]` and call `routine_service_for(start_failed_rule, name, parsed.routine_services)`; expect `None`, while `service-crashed` matches.
  - `test_routine_service_validation`: unknown rule key → `r"routine_service 'X'.*unknown rule"`; missing `reason` → `r"routine_service 'X'.*reason"`; non-ASCII `reason` → `r"routine_service 'X'.*ASCII"`.
  - `test_derived_rule_is_registered`: `ROUTINE_SERVICE_ERRORS in DERIVED_RULES` and its severity is INFO. (The existing `test_every_rule_is_explained` already checks ASCII.)

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement.** Extend `parse_catalog` to fill `Catalog.routine_services` with the validation above (error prefix `routine_service 'NAME': ...`; check `rules` entries against the parsed rule keys). Add the seed `[[routine_service]]` to `catalog.toml`. Add `ROUTINE_SERVICES`, `routine_service_for`, `ROUTINE_SERVICE_ERRORS` and extend `DERIVED_RULES`.

- [ ] **Step 4: Run `uv run pytest -q` and `uv run ruff check`.** Expected: PASS.

- [ ] **Step 5: Commit** `catalog: add routine-service entries and the Info rule`.

---

### Task 5: Divert routine services in the analyzer

**Files:**
- Modify: `src/eventlens/analyzer.py` (the recognised-rule branch of `analyze`, and the `catalog` import)
- Create: `tests/test_routine_services.py`

**Interfaces:**
- Consumes: `routine_service_for`, `ROUTINE_SERVICE_ERRORS`, `ROUTINE_SERVICES`
- Produces: `analyze()` puts a matching event into `Finding(ROUTINE_SERVICE_ERRORS)` with the detail string `f"{entry.name}: {entry.reason}"`, and not into the normal rule's finding.

Test helpers in the new file: `SCM = "Service Control Manager"`, `ISD = "Interactive Services Detection"`; `run_with(monkeypatch, events, *args)` copied from `tests/test_fail_on.py` (patches `cli.read_file`, calls `main(["--file", "x.evtx", *args])`).

- [ ] **Step 1: Write the failing tests** in `tests/test_routine_services.py`:
  - `test_routine_events_become_one_info_finding`: 10 events `(SCM, 7034, data={"param1": ISD})` give finding keys `{"routine-service-errors"}`, `finding.count == 10`, details exactly `{f"{ISD}: {reason}": 10}` where `reason` comes from `ROUTINE_SERVICES[0]`, and no `service-crashed` finding.
  - `test_real_service_failures_are_unchanged`: 2 events for `"Print Spooler"` give a `service-crashed` finding with count 2, severity HIGH, and no routine finding.
  - `test_mixed_log_splits_with_counts_that_add_up`: 3 ISD events plus 2 Print Spooler events give `service-crashed` count 2 (details `{"Print Spooler": 2}`) and routine count 3.
  - `test_name_matching_ignores_case_and_padding` (Review Focus 1): data `"  interactive services detection "` is routine.
  - `test_service_timeout_uses_the_second_field` (Review Focus 2): `(SCM, 7009, data={"param1": "30000", "param2": ISD})` is routine and no `service-start-failed` finding exists.
  - `test_event_without_a_service_name_is_never_routine`: `(SCM, 7034)` with no data gives a `service-crashed` finding with count 1.
  - `test_routine_only_log_is_not_a_problem` (Review Focus 3): `analysis.problems == []`, `analysis.verdict == "No significant problems found."`, the routine finding is in `analysis.normal`.
  - `test_routine_only_log_passes_fail_on` (Review Focus 3): `run_with(monkeypatch, events, "--fail-on", "low") == 0`.
  - `test_real_failure_still_trips_fail_on_alongside_routine_events`: ISD events plus one Print Spooler event, `--fail-on high` returns 1.
  - Output tests via `run_with` and `capsys` (ISD events only): text output contains `"Services that log errors routinely: 10 times"` and the ISD name and reason; `--format markdown` contains `"- Services that log errors routinely: 10 times"`; `--format json` parses with `findings == []`, `normal[0]["id"] == "routine-service-errors"`, `normal[0]["count"] == 10`, `schema_version == 1`.

- [ ] **Step 2: Run `uv run pytest tests/test_routine_services.py -v`.** Expected: FAIL (events still land in `service-crashed`).

- [ ] **Step 3: Implement in `analyzer.analyze`.** In the `rule is not None` branch, compute `detail` as today, then call `routine_service_for(rule, detail)`. If it matches, add the event to `finding_for(ROUTINE_SERVICE_ERRORS)` with the detail string above; otherwise add to the rule's finding as before. No other analyzer change.

- [ ] **Step 4: Run `uv run pytest -q` and `uv run ruff check`.** Expected: PASS; the golden reports are unchanged.

- [ ] **Step 5: Commit** `analyzer: report routine services as an Info finding`.

---

### Task 6: Docs and cleanup

**Files:**
- Modify: `README.md`
- Modify: `docs/SPEC.md`

- [ ] **Step 1: README.** Remove the *Interactive Services Detection* bullet from "Known limitations"; keep the "events outside the catalog" bullet and fix the "31 event types" sentence's link to point at `catalog.toml`. In "How it works" change `catalog.py` to `catalog.toml` in the diagram and step 2. Tick M5 in the roadmap and say more events and the Security log remain open. Replace the stale "266 automated tests" with the real count from `uv run pytest -q`. Add a short "Adding an event" section: the TOML shape with one example rule, the seven named extractors and the `{ field = [...] }` form, how to add a routine service, and "run `uv run pytest`; a malformed entry fails with a message naming it".

- [ ] **Step 2: `docs/SPEC.md`.** In the M5 roadmap row (line 319) mark the data file and routine-services parts done and note that more events and the optional Security log are still planned.

- [ ] **Step 3: Verify.** Run `uv run pytest -q`, `uv run ruff check`, and the wheel smoke test from Task 3 Step 5. Expected: all pass.

- [ ] **Step 4: Commit** `docs: document the catalog data file and mark M5 done`, then push the branch.

---

## Self-Review

- **Spec coverage:** 3.1 file shape and 3.2 extractors → Tasks 2 and 3; 3.3 loader and every listed validation → Task 2 (plus routine-service validation in Task 4); 3.4 routine services, seed, default rules, derived rule and output → Tasks 4 and 5; 3.5 packaging → Task 3 Step 5; section 4 tests → Tasks 1 to 5 (the real-log check stays manual, noted below); section 5 docs → Task 6.
- **Additions beyond the spec:** rejecting unknown rule fields (Task 2), so a typo like `severty` fails loudly instead of being ignored. The routine-service `reason` is carried in the detail string because the text and Markdown "Normal activity" sections don't print `meaning`.
- **Type consistency:** `Catalog`, `RoutineService`, `EXTRACTORS`, `parse_catalog`, `routine_service_for` and `ROUTINE_SERVICE_ERRORS` use the same names and signatures wherever they appear.
- **Manual check, not in CI:** if the 2017 evtx sample is available, confirm *Interactive Services Detection* is no longer the top issue and mention the result in the PR.
