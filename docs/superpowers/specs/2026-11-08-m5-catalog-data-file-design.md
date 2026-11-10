# M5: Catalog in a data file, with routine-noise handling

Status: design, awaiting review
Date: 2026-11-08
Scope: milestone M5 only. M6 (PyPI and a standalone Windows `.exe`) is a separate spec.

## 1. Goal

Two outcomes:

1. **A contributor can add or change an event by editing one TOML file.** No Python change is needed for the common case.
2. **A service that logs errors routinely stops dominating the report.** The README's known limitation is that *Interactive Services Detection* logged a service error 10 times on a real 2017 log, and EventLens reported it as a **High** "Service stopped unexpectedly" and made it the top issue. After this change it is reported as routine noise at **Info** and can't drive the verdict or `--fail-on`.

### Decisions already made

- **Bundled file only.** One `catalog.toml` ships inside the package. There is no `--catalog PATH` option and no user-supplied overrides.
- **Not in scope:** new events beyond the ones already in the catalog, and the optional Security log. These were part of the old M5 roadmap line but weren't requested. They become easy to add once this lands.

## 2. Non-goals

- Changing any existing rule's wording, severity or escalation. The migration must be behaviour-neutral.
- Moving the derived rules to data. The crash incidents (`BLUE_SCREEN`, `FORCED_POWER_OFF`, `POWER_LOSS`) and the sleep rules (`CRASH_WHILE_ASLEEP`, `WAKES_IMMEDIATELY`) stay in Python, because their detection is code and moving only their text would not let anyone add an event.
- Seeding the routine-services list with services we have no evidence for.

## 3. Design

### 3.1 `catalog.toml`

A new file, `src/eventlens/catalog.toml`, holds:

- every rule currently in `catalog.RULES` (the 23 rules from `whea-fatal` to `dcom-10016`),
- the stop-code table (`STOP_CODES`),
- the routine-services list (section 3.4).

Rule shape:

```toml
[[rule]]
key = "whea-corrected"
providers = ["Microsoft-Windows-WHEA-Logger"]
event_ids = [17, 19]
severity = "low"
escalate = { count = 10, severity = "high" }
title = "Corrected hardware error"
meaning = "..."
action = "..."
detail = "..."            # optional, see 3.2
detail_label = "Drive"    # optional, default "Details"
```

Severity is the lowercase name of a `Severity` member. `escalate`, `detail`, `detail_label` and `action` are optional, with the same defaults as the `Rule` dataclass today. All text stays ASCII, as the module docstring requires.

Stop codes:

```toml
[stop_codes]
"0x0A" = { name = "IRQL_NOT_LESS_OR_EQUAL", hint = "usually a faulty driver" }
```

Keys are hex strings so they read the same as in Microsoft's documentation.

### 3.2 Detail extractors

Rules use Python lambdas today to pull a drive, service, app or update out of an event. TOML can't hold those, so there are two forms:

- **Named extractor:** `detail = "service"`. `catalog.py` keeps a small registry of named extractors: `first_param`, `service`, `app_crash`, `app_hang`, `dotnet_crash`, `windows_update` and `planned_restart`. These are the existing helper functions, renamed into the registry and otherwise unchanged.
- **Field extractor:** `detail = { field = ["DriveName"] }`. It returns the first non-empty data field among the listed names, the same behaviour as the existing `field()` helper. This covers the rules that use a one-line lambda (`ntfs-corruption`, `driver-load-failed`, `dns-timeout`).

Anything that needs real logic becomes a new named extractor in Python, and that is the one remaining case where an event needs a code change. The extractor names and what they do are documented in the README's "Adding an event" section.

### 3.3 Loader

`catalog.py` loads the file once at import with `tomllib` and `importlib.resources.files("eventlens")`. That makes it work from an installed wheel and from a PyInstaller bundle in M6. The public surface does not change: `Rule`, `Severity`, `RULES`, `STOP_CODES`, `lookup`, `event_key`, `describe_stop_code`, `parse_stop_code`, `CRASH_EVENTS` and the derived rules are still importable from `eventlens.catalog`. So `analyzer.py`, `timeline.py`, `report*.py` and the tests need no import changes.

**Validation.** The loader raises `CatalogError` with the entry's key and the problem. Checks:

- missing required field (`key`, `providers`, `event_ids`, `severity`, `title`, `meaning`)
- duplicate rule `key`
- duplicate (provider, event ID), already checked today by `_build_index`
- unknown severity name
- unknown named extractor, or a malformed field extractor
- `escalate` whose severity is not above the base severity, or whose count is below 2
- a malformed stop code key
- a routine-services entry that names a rule that doesn't exist (section 3.4)
- non-ASCII text

### 3.4 Routine-noise handling

A new top-level table in `catalog.toml`:

```toml
[[routine_service]]
name = "Interactive Services Detection"
reason = "This Windows service logs a service error as part of normal operation."
rules = ["service-start-failed", "service-crashed"]   # optional, this is the default
```

- `name` is matched case-insensitively against the service name the existing `service` extractor already pulls out of the event. No new event parsing.
- `rules` limits which rules the entry applies to. The default is the two service rules above.
- **Seed entry:** *Interactive Services Detection* only.

**Behaviour in the analyzer.** When an event matches a rule listed in an entry's `rules` and its extracted service name matches that entry, it is **not** added to the normal finding. It goes into one separate finding with the new rule key `routine-service-errors`, severity Info, title "Services that log errors routinely", listing each service with its count and the entry's `reason`.

Consequences:

- Real service failures keep their severity, count, ordering and escalation exactly as before.
- Routine ones stay visible, so nothing is hidden, but they rank at the bottom and cannot raise the verdict or trip `--fail-on`.
- If every service event in a log is routine, the High "Service stopped unexpectedly" finding no longer appears at all.
- An event with no extractable service name is never treated as routine.

`routine-service-errors` is a derived rule defined in Python (like the sleep rules), since its content is assembled from the matches. The `reason` text comes from the data file.

**Output.** The finding appears in text, Markdown and JSON like any other Info finding. JSON gets no schema change beyond one more finding, so `schema_version` stays at 1.

### 3.5 Packaging

`catalog.toml` has to ship in the wheel. `uv_build` includes non-Python files inside the module directory by default (checked: a probe `.toml` placed there appears in the built wheel), and the smoke test (CI builds the wheel and runs the installed command) will prove it. If it doesn't, the smoke test fails, so this can't regress silently.

## 4. Testing

- **Migration parity.** Before the move, snapshot the current rules (fields, escalation, stop codes, and detail output on a set of sample events) from the Python catalog. A test checks the TOML-built catalog gives identical results. After the migration lands, the snapshot becomes a pinned fixture that still guards against accidental edits.
- **Golden report.** The existing saved report for the sample week must stay byte-identical with no regeneration.
- **Loader validation.** One test per validation failure in 3.3, using small in-memory TOML strings, asserting the error names the entry.
- **Bundled file test.** The shipped `catalog.toml` loads cleanly, so a bad contributor edit fails CI.
- **Routine services.**
  - a routine service goes to the Info finding and not to the service rule
  - a real service still reports as before
  - a mixed log splits correctly, with counts that add up
  - matching is case-insensitive
  - no service name means not routine
  - an entry limited to one rule doesn't affect the other
  - the verdict and `--fail-on` ignore the routine finding
  - text, Markdown and JSON output include it
- **Real-log check.** If the 2017 sample log is available locally, confirm *Interactive Services Detection* is no longer the top issue. It is not in the repo, so this is a manual check, mentioned in the PR.
- CI (ruff, pytest on 3 OSes and 2 Pythons, wheel smoke test) must pass.

## 5. Documentation

- README: remove the *Interactive Services Detection* known-limitation bullet, update the "31 event types" and file references, tick M5 in the roadmap, and add a short "Adding an event" section covering the TOML shape, the extractor names, and how to run the tests.
- `docs/SPEC.md`: mark M5 done, with a line saying more events and the Security log are still open.
- The `catalog.py` module docstring: say that rules now live in `catalog.toml`.

## 6. Risks

- **Behaviour drift during the move.** Mitigated by the parity test and the byte-identical golden report.
- **Wrong list entry.** A service wrongly marked routine would hide a real fault at Info. Mitigated by seeding a single entry with evidence, and by keeping routine events visible in their own finding instead of dropping them.
- **Missing data file in a build.** Mitigated by the wheel smoke test. M6 adds the same check for the `.exe`.
- **Python 3.11 minimum.** `tomllib` is in the standard library from 3.11, and the project already requires 3.11 or later, so there's no new dependency.

## 7. Out of scope, for later

- `--catalog PATH` for user-supplied rules.
- More events and the Security log.
- Moving the crash and sleep rule text to data.
- M6: PyPI publishing and the standalone `.exe`.
