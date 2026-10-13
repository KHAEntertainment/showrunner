#!/usr/bin/env bash
# Invoke directly; the shebang fixes the interpreter regardless of interactive shell.
set -uo pipefail

failed=0
not_run=0
passed=0
skipped=0
# Every skip records what it leaves unverified, so the terminal line can name
# the gap instead of reporting a bare pass over untested code.
skipped_notes=()

# printf, not cat: usage must still print when PATH holds no external tools.
usage() {
    printf '%s\n' \
        'Usage: scripts/verify.sh [--require-all]' \
        '' \
        '  --require-all   Treat any skipped check as a failure (exit non-zero).' \
        '                  Equivalent to VERIFY_REQUIRE_ALL=1. Intended for CI and' \
        '                  release checks, where "not run" must not read as "passed".' \
        '' \
        'By default an optional skip still exits 0, but the terminal line names the' \
        'skip and what it leaves unverified.'
}

run_check() {
    local name=$1 code
    shift
    printf '\nRUN: %s\n' "$name"
    "$@"
    code=$?
    case "$code" in
        0) printf 'PASSED: %s (exit %s)\n' "$name" "$code"; passed=$((passed + 1)) ;;
        # Heuristic: a checked program can itself legitimately exit 126/127.
        # Always fail the gate, but report these separately as execution failures.
        126|127) printf 'NOT RUN (did-not-run): %s (exit %s)\n' "$name" "$code"; not_run=$((not_run + 1)) ;;
        *) printf 'FAILED: %s (exit %s)\n' "$name" "$code"; failed=$((failed + 1)) ;;
    esac
}

# record_skip <reported reason> <what stays unverified>
record_skip() {
    printf '\nSKIPPED: %s\n' "$1"
    skipped=$((skipped + 1))
    skipped_notes+=("$2")
}

# report_summary [require_all] -- prints the summary and terminal line, and
# returns the gate's exit status. A skip never hides behind a bare GATE PASSED.
report_summary() {
    local require_all=${1:-0} note notes=""

    printf '\nSUMMARY: %s passed, %s failed, %s did-not-run, %s optional skipped\n' \
        "$passed" "$failed" "$not_run" "$skipped"

    if (( failed > 0 || not_run > 0 )); then
        printf 'GATE FAILED\n'
        return 1
    fi

    if (( skipped > 0 )); then
        for note in "${skipped_notes[@]}"; do
            [[ -n $notes ]] && notes+="; "
            notes+="$note"
        done
        if (( require_all )); then
            printf 'GATE FAILED (strict): %s skipped - %s\n' "$skipped" "$notes"
            return 1
        fi
        printf 'GATE PASSED WITH %s SKIPPED - %s\n' "$skipped" "$notes"
        return 0
    fi

    printf 'GATE PASSED\n'
    return 0
}

require_all=0
[[ ${VERIFY_REQUIRE_ALL:-0} == 1 ]] && require_all=1
while (( $# > 0 )); do
    case "$1" in
        --require-all) require_all=1 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'verify.sh: unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." || exit 1

run_check 'ShellCheck' shellcheck install.sh tests/test-install.sh tests/migration-scratch.sh scripts/check_plugin_root.sh scripts/verify.sh
run_check 'Installer syntax' bash -n install.sh
run_check 'Verification script syntax' bash -n scripts/verify.sh
run_check 'Skill validation' python3 scripts/validate_skill.py
export PYTHONDONTWRITEBYTECODE=1
run_check 'Python tests' python3 -m unittest discover -s tests -p 'test_*.py'
run_check 'Bash installer tests' bash tests/test-install.sh
run_check 'Plugin root' scripts/check_plugin_root.sh
run_check 'Version sync' python3 scripts/check_version_sync.py
# Both Claude CLI checks are recorded in PROJECT_CONTEXT.md's Verification Gate,
# and CI runs them together behind the same guard. Running them as a pair here
# keeps this script's coverage equal to the recorded gate: `tag --dry-run` was
# missing, so a lane running this script believed it had run the whole gate
# while one recorded command had never executed. A machine without the CLI now
# reports one named skip instead of one check failing while its sibling is
# silently never considered.
if command -v claude >/dev/null 2>&1; then
    run_check 'Claude plugin validation' claude plugin validate . --strict
    # `claude plugin tag --dry-run` refuses to run against a dirty tree, so it
    # can only execute on a clean checkout. Running it unconditionally would
    # fail the gate for every worker mid-change and teach everyone to ignore a
    # red gate. A named skip keeps it usable; CI checks out clean, where it
    # always runs, and --require-all fails on the skip either way. An
    # unreadable git status errs toward running the check, never toward
    # skipping it.
    if [[ -n $(git status --porcelain 2>/dev/null) ]]; then
        record_skip \
            'Claude plugin tag dry run (uncommitted changes; exit n/a)' \
            'claude plugin tag --dry-run did not run; release tagging is unverified until the tree is clean'
    else
        run_check 'Claude plugin tag (dry run)' claude plugin tag --dry-run .
    fi
else
    record_skip \
        'Claude packaging checks (claude CLI absent; exit n/a)' \
        'claude plugin validate --strict and claude plugin tag --dry-run did not run; packaging is unverified against the Claude Code CLI'
fi

if command -v pwsh >/dev/null 2>&1; then
    run_check 'PowerShell installer tests' pwsh tests/test-install.ps1
elif [[ ${OS:-} == Windows_NT ]]; then
    run_check 'PowerShell installer tests' pwsh tests/test-install.ps1
else
    record_skip \
        'PowerShell installer tests (pwsh absent; optional off Windows; exit n/a)' \
        'PowerShell installer tests did not run; install.ps1 is unverified'
fi

report_summary "$require_all"
exit $?
