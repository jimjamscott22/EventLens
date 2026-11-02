#!/usr/bin/env bash
# Smoke-test an installed EventLens: run the real command on the sample log
# and check each output option and exit code.
#
# Usage: scripts/smoke_test.sh PATH_TO_WHEEL
#
# CI runs this on Windows, macOS, and Linux after building the wheel. It
# installs the wheel in an isolated environment, so it catches packaging and
# entry-point problems that the unit tests can't.
set -euo pipefail

if [ $# -ne 1 ]; then
    echo "usage: $0 PATH_TO_WHEEL" >&2
    exit 2
fi

wheel="$1"
sample="examples/sample_week.xml"
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

eventlens() {
    uvx --quiet --from "$wheel" eventlens "$@"
}

failures=0
fail() {
    echo "FAIL: $1" >&2
    failures=$((failures + 1))
}
pass() {
    echo "ok:   $1"
}

# expect_exit NAME CODE ARGS...: run eventlens, check the exit code, and save
# its output to $workdir/out for the checks that follow.
expect_exit() {
    local name="$1" want="$2"
    shift 2
    local got=0
    eventlens "$@" >"$workdir/out" 2>"$workdir/err" || got=$?
    if [ "$got" -eq "$want" ]; then
        pass "$name (exit $got)"
    else
        fail "$name: expected exit $want, got $got"
        cat "$workdir/err" >&2
    fi
}

# expect_text NAME PATTERN FILE: check that FILE contains the fixed text.
expect_text() {
    if grep -qF -- "$2" "$3"; then
        pass "$1"
    else
        fail "$1: missing '$2'"
    fi
}

expect_exit "version" 0 --version
expect_text "version text" "eventlens " "$workdir/out"

expect_exit "text report" 0 --file "$sample" --utc
expect_text "text verdict" "Verdict: Serious problems found." "$workdir/out"
if grep -q $'\033' "$workdir/out"; then
    fail "text report has colour codes when piped"
else
    pass "no colour codes when piped"
fi

expect_exit "forced colour" 0 --file "$sample" --utc --color always
if grep -q $'\033\\[' "$workdir/out"; then
    pass "--color always adds colour codes"
else
    fail "--color always added no colour codes"
fi

expect_exit "json report" 0 --file "$sample" --format json
expect_text "json schema version" '"schema_version": 1' "$workdir/out"
expect_text "json blue screen finding" '"title": "Blue screen crash"' "$workdir/out"

expect_exit "markdown report" 0 --file "$sample" --utc --format markdown
expect_text "markdown title" "# EventLens report for TEST-PC" "$workdir/out"
expect_text "markdown finding" "### CRITICAL: Blue screen crash" "$workdir/out"

expect_exit "output file" 0 --file "$sample" --utc --output "$workdir/report.txt"
if [ -s "$workdir/report.txt" ] && [ ! -s "$workdir/out" ]; then
    pass "--output wrote the file and printed nothing"
else
    fail "--output: file empty or something was printed"
fi
expect_text "output file content" "Verdict: Serious problems found." "$workdir/report.txt"

expect_exit "fail-on finds a problem" 1 --file "$sample" --utc --fail-on critical
expect_text "fail-on still prints the report" "Verdict: Serious problems found." "$workdir/out"
expect_exit "fail-on passes when nothing is that severe" 0 \
    --file "$sample" --utc --days 1 --fail-on critical

expect_exit "missing file is an error" 2 --file "$workdir/does-not-exist.evtx"
expect_exit "unwritable output is an error" 2 \
    --file "$sample" --output "$workdir/no-such-folder/report.txt"

if [ "$failures" -ne 0 ]; then
    echo "$failures smoke test check(s) failed" >&2
    exit 1
fi
echo "All smoke tests passed."
