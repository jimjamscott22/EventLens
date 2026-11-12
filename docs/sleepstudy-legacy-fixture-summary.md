# Legacy SleepStudy fixture restoration

Recovered `tests/fixtures/sleepstudy_legacy.xml` from stash `6a4e94f` and
recorded its source, license, and sanitization in the
[fixture README](../tests/fixtures/README.md#legacy-sleepstudy-fixture).
The six legacy `ConnectedStandby` sessions provide a real sample for future
compatibility work. The current CLI rejects the fixture with exit code 2
because it expects `Duration` and the legacy file uses `CsDuration`.

The restoration includes the fixture and its provenance. Standalone reporting
and measurement validation are already covered by `c636df6`. Legacy parsing,
SleepStudy date filtering, and expanded per-session JSON remain future work.
