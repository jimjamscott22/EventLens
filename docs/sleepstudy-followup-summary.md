# SleepStudy reconciliation follow-up

Updated README links after SPEC.md moved to docs/, and corrected the README and
specification M3 status to reflect merged PR #5.

Retained standalone SleepStudy mode and focused validation from the superseded
implementation, adapting them to PR #5's --sleepstudy flag, models, renderers and
existing thresholds. Standalone mode never reads event logs and has no event
verdict. Explicit --file/--channel still combines reports. Missing capacities,
charging, unknown power and non-idle states do not produce drain grades.

The existing stash was neither applied nor dropped. No duplicate parser,
rendering architecture, legacy fixture, old thresholds or obsolete summary was
restored. No commits or pushes were performed.

Validation: full suite 327 passed, 2 existing Windows integration tests skipped
on Python 3.13 in .venv/sleepstudy. Ruff passes and uv builds
dist/eventlens-0.1.0-py3-none-any.whl. Real-laptop battery data and cross-platform
CI were not exercised.
