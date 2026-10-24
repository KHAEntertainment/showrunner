"""Exercise the real gate entrypoint with isolated tool stand-ins, never recurse."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify.sh"

ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# A stub tool records the ordered argv it was called with and then exits.
# Each call appends one JSON array - the program the gate invoked plus its
# arguments, in order - to the log. A stub exits 0 whatever it is asked to
# do, so a gate command with the wrong argument order is invisible unless the
# argv is written down: `python3 -m unittest -s tests discover` is rejected
# by real unittest, but the stub accepts it and a token-set comparison cannot
# tell the two orders apart (Issue #141, F6).
#
# The program name is baked into each stub because a shell script cannot see
# how it was invoked; the arguments come from `"$@"`, which is exactly what
# the gate passed.
_STUB_TEMPLATE = r"""#!/bin/bash
__log__={log}
__json__={program}
for __arg__ in "$@"; do
    __esc__=${{__arg__//\\/\\\\}}
    __esc__=${{__esc__//\"/\\\"}}
    __esc__=${{__esc__//$'\n'/\\n}}
    __esc__=${{__esc__//$'\r'/\\r}}
    __esc__=${{__esc__//$'\t'/\\t}}
    __json__+=,"\"$__esc__\""
done
printf '[%s]\n' "$__json__" >> "$__log__"
{body}
exit {status}
"""


def _stub_script(log: Path, program: str, *, status: int = 0, body: str = "") -> str:
    """A stub tool that records its ordered argv, then exits with `status`."""
    return _STUB_TEMPLATE.format(
        log=shlex.quote(str(log)),
        program=shlex.quote(json.dumps(program)),
        status=status,
        body=body,
    )


def _recorded_invocations(log: Path) -> list[list[str]]:
    """The ordered argv of every stub call, as recorded in the log."""
    if not log.exists():
        return []
    return [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class GateResult:
    """The gate's outcome plus the ordered argv every stub tool received.

    `invocations` is the log the stubs wrote: one JSON array per call, in the
    order the gate made them. It is what makes a malformed gate command
    visible - only the argv a stub was handed can tell
    `unittest discover -s tests` from `unittest -s tests discover`.
    """

    def __init__(self, completed, invocations):
        self.returncode = completed.returncode
        self.stdout = completed.stdout
        self.stderr = completed.stderr
        self.invocations = invocations


def recorded_gate_commands(text=None):
    """Commands recorded under `## Verification Gate` in PROJECT_CONTEXT.md.

    Only the `- **Label**:` bullets carry commands; the section's prose does
    not. Within a bullet, `n/a` is the file's own no-command sentinel, and a
    real command always names a program with arguments or a path - the bare
    identifiers in these bullets are prose (manifest field names, a tool named
    as future work), not things to run.

    The recorded format forbids indented Markdown continuation lines under a
    bullet (Issue #31): a command wrapped onto one is invisible to this parser,
    so the format is constrained instead of teaching the parser to follow
    continuations. Any non-blank, indented line in the section - whether or
    not it carries a command - is rejected outright, naming the rule, rather
    than silently skipped.
    """
    if text is None:
        text = (ROOT / "PROJECT_CONTEXT.md").read_text(encoding="utf-8")
    section = re.search(r"^## Verification Gate$(.*?)(?=^## |\Z)", text, re.M | re.S)
    if section is None:
        raise AssertionError("PROJECT_CONTEXT.md has no '## Verification Gate' section")
    commands = []
    for line in section.group(1).splitlines():
        if line.startswith("- **"):
            for span in re.findall(r"`([^`]+)`", line):
                if span != "n/a" and (" " in span or "/" in span):
                    commands.append(span)
            continue
        if line.strip() and (line[0] == " " or line[0] == "\t"):
            raise AssertionError(
                "PROJECT_CONTEXT.md Verification Gate has an indented "
                f"continuation line ({line.strip()!r}); keep every gate "
                "command on its own '- **Label**:' bullet line"
            )
    return commands


def gate_check_invocations(script):
    """Each `run_check` line in verify.sh, tokenised as ['run_check', label, *argv]."""
    return [
        shlex.split(line.strip())
        for line in script.splitlines()
        if line.strip().startswith("run_check ")
    ]


class GateHarness:
    """Runs the real gate entrypoint against stub tools. Mixin, not a TestCase."""

    def run_gate(self, *, shellcheck=None, executable=True, pwsh=False, windows=False,
                 claude=True, git_dirty=False, args=(), env_extra=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            shutil.copy2(SCRIPT, root / "scripts" / "verify.sh")
            binaries = root / "tools"
            binaries.mkdir()
            log = root / "invocations.log"
            stubs = ["bash", "python3", "dirname"] + (["claude"] if claude else [])
            for name in stubs:
                path = binaries / name
                if name == "dirname":
                    path.symlink_to(shutil.which("dirname"))
                else:
                    path.write_text(_stub_script(log, name))
                    path.chmod(0o755)
            check = root / "scripts" / "check_plugin_root.sh"
            check.write_text(_stub_script(log, "scripts/check_plugin_root.sh"))
            check.chmod(0o755)
            if shellcheck is not None:
                tool = binaries / "shellcheck"
                tool.write_text(_stub_script(log, "shellcheck", status=shellcheck))
                tool.chmod(0o755 if executable else 0o644)
            if pwsh:
                tool = binaries / "pwsh"
                tool.write_text(_stub_script(log, "pwsh"))
                tool.chmod(0o755)
            if git_dirty:
                # Absent git reports nothing and the tag check runs; a dirty
                # tree is the case that has to skip with a reason.
                tool = binaries / "git"
                tool.write_text(
                    _stub_script(log, "git", body="echo ' M scripts/verify.sh'")
                )
                tool.chmod(0o755)
            # Pin strict mode off unless a case asks for it, so an ambient
            # VERIFY_REQUIRE_ALL in the caller's environment cannot change
            # what these assertions are measuring.
            env = {**os.environ, "PATH": str(binaries), "OS": "Windows_NT" if windows else "Linux",
                   "VERIFY_REQUIRE_ALL": "0"}
            env.update(env_extra or {})
            completed = subprocess.run(
                ["/bin/bash", str(root / "scripts" / "verify.sh"), *args],
                cwd="/", env=env, text=True, capture_output=True, check=False,
            )
            return GateResult(completed, _recorded_invocations(log))

    def terminal_line(self, result):
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        return lines[-1] if lines else ""


class VerifyScriptTests(GateHarness, unittest.TestCase):
    def test_all_checks_pass(self):
        result = self.run_gate(shellcheck=0, pwsh=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("11 passed, 0 failed, 0 did-not-run, 0 optional skipped", result.stdout)
        self.assertIn("GATE PASSED", result.stdout)

    def test_missing_check_cannot_pass_when_all_executed_checks_pass(self):
        result = self.run_gate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NOT RUN (did-not-run): ShellCheck (exit 127)", result.stdout)
        self.assertIn("9 passed, 0 failed, 1 did-not-run", result.stdout)
        self.assertNotIn("GATE PASSED", result.stdout)

    def test_nonexecutable_check_did_not_run(self):
        result = self.run_gate(shellcheck=0, executable=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NOT RUN (did-not-run): ShellCheck (exit 126)", result.stdout)
        self.assertIn("9 passed, 0 failed, 1 did-not-run", result.stdout)

    def test_real_failure_is_failed_and_later_checks_still_run(self):
        result = self.run_gate(shellcheck=1)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FAILED: ShellCheck (exit 1)", result.stdout)
        self.assertNotIn("NOT RUN", result.stdout)
        self.assertIn("PASSED: Claude plugin validation (exit 0)", result.stdout)
        self.assertIn("9 passed, 1 failed, 0 did-not-run", result.stdout)

    def test_absent_optional_powershell_skip_is_visible(self):
        result = self.run_gate(shellcheck=0)
        self.assertEqual(result.returncode, 0)
        self.assertIn("SKIPPED: PowerShell installer tests (pwsh absent; optional off Windows; exit n/a)", result.stdout)
        self.assertIn("1 optional skipped", result.stdout)

    def test_powershell_is_required_on_windows(self):
        result = self.run_gate(shellcheck=0, windows=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NOT RUN (did-not-run): PowerShell installer tests (exit 127)", result.stdout)
        self.assertNotIn("SKIPPED", result.stdout)


class VerifyScriptGateCoverageTests(GateHarness, unittest.TestCase):
    """verify.sh must run every command PROJECT_CONTEXT.md records as the gate.

    QA is told a single entry point may stand in for the recorded gate. That is
    only true while the entry point covers it. `claude plugin tag --dry-run .`
    was recorded but not in this script, so a lane running verify.sh saw
    `GATE PASSED` having skipped a recorded command. Fixing that one omission
    without this test leaves the same gap available the next time a command is
    added to the gate and not to the script, which is how this one arrived.
    """

    def test_verify_script_runs_every_recorded_gate_command(self):
        commands = recorded_gate_commands()
        # Instrument guards. A parser that extracts nothing would make coverage
        # vacuously complete, which is the failure mode this test exists to
        # catch one layer down.
        self.assertTrue(commands, "parsed no commands from the recorded gate")
        self.assertIn(
            "python3 scripts/validate_skill.py",
            commands,
            "the gate parser lost a known command; it has drifted, not passed",
        )
        invocations = gate_check_invocations(SCRIPT.read_text(encoding="utf-8"))
        self.assertTrue(invocations, "parsed no run_check invocations from verify.sh")

        missing = []
        for command in commands:
            # Exact string matching is too brittle to bind on: verify.sh adds
            # operands (it shellchecks itself too) and sets the unittest env var
            # on its own line. Match on the program plus every recorded token
            # instead, so extra arguments are fine and a dropped check is not.
            tokens = [t for t in shlex.split(command) if not ENV_ASSIGNMENT.match(t)]
            if not any(
                len(call) > 2 and call[2] == tokens[0] and set(tokens) <= set(call[2:])
                for call in invocations
            ):
                missing.append(command)
        self.assertEqual(
            missing,
            [],
            "PROJECT_CONTEXT.md records these gate commands but scripts/verify.sh "
            f"never runs them: {missing}",
        )

    def test_claude_checks_skip_together_and_name_what_is_unverified(self):
        result = self.run_gate(shellcheck=0, pwsh=True, claude=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SKIPPED: Claude packaging checks", result.stdout)
        self.assertIn("packaging is unverified", self.terminal_line(result))
        # Both recorded commands are named, so neither is silently forgotten.
        self.assertIn("claude plugin validate --strict", self.terminal_line(result))
        self.assertIn("claude plugin tag --dry-run", self.terminal_line(result))

    def test_dirty_tree_skips_the_tag_check_by_name(self):
        # The command cannot run against a dirty tree. It must say so rather
        # than failing the gate for every worker mid-change, and rather than
        # vanishing without a note.
        result = self.run_gate(shellcheck=0, pwsh=True, git_dirty=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SKIPPED: Claude plugin tag dry run", result.stdout)
        self.assertIn("release tagging is unverified", self.terminal_line(result))
        self.assertNotEqual(self.terminal_line(result), "GATE PASSED")

    def test_dirty_tree_skip_still_fails_under_strict(self):
        result = self.run_gate(
            shellcheck=0, pwsh=True, git_dirty=True, args=("--require-all",)
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("GATE FAILED (strict)", self.terminal_line(result))

    def test_absent_claude_cli_fails_the_gate_under_strict(self):
        result = self.run_gate(
            shellcheck=0, pwsh=True, claude=False, args=("--require-all",)
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("GATE FAILED (strict)", self.terminal_line(result))


class RecordedGateFormatTests(unittest.TestCase):
    """The recorded gate format forbids indented continuation lines (#31).

    QA on PR #30 found that a gate command on an indented continuation line
    was invisible to `recorded_gate_commands()`: the coverage test passed
    (0 missing) even though the same command on its own bullet line was
    correctly caught. These tests exercise the parser directly against
    synthetic gate text, so they do not depend on PROJECT_CONTEXT.md's
    current content (which has no continuation lines today).
    """

    def test_command_on_indented_continuation_line_is_rejected(self):
        text = (
            "## Verification Gate\n\n"
            "- **Lint**: `shellcheck install.sh`\n"
            "  and also `python3 scripts/extra_check.py`\n"
            "- **Tests**: `python3 -m unittest discover -s tests`\n"
        )
        with self.assertRaises(AssertionError) as failure:
            recorded_gate_commands(text)
        self.assertIn("continuation line", str(failure.exception))

    def test_single_line_bullets_continue_to_parse_unchanged(self):
        text = (
            "## Verification Gate\n\n"
            "The exact commands worker, QA, and reviewer must all run.\n\n"
            "- **Lint**: `shellcheck install.sh`\n"
            "- **Type check**: `n/a` — no typed surface\n"
            "- **Tests**: `python3 -m unittest discover -s tests`\n\n"
            "A change is not complete until every command above exits clean.\n"
        )
        self.assertEqual(
            recorded_gate_commands(text),
            ["shellcheck install.sh", "python3 -m unittest discover -s tests"],
        )


class VerifyScriptSkipReportingTests(GateHarness, unittest.TestCase):
    """A skipped check must not hide behind a bare GATE PASSED (Issue #22 req 3)."""

    SKIP_NOTE = "PowerShell installer tests did not run; install.ps1 is unverified"

    def test_all_clear_terminal_line_is_bare_gate_passed(self):
        self.assertEqual(
            self.terminal_line(self.run_gate(shellcheck=0, pwsh=True)),
            "GATE PASSED",
        )

    def test_skip_terminal_line_names_the_skip_and_what_is_unverified(self):
        result = self.run_gate(shellcheck=0)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            self.terminal_line(result),
            f"GATE PASSED WITH 1 SKIPPED - {self.SKIP_NOTE}",
        )

    def test_skip_terminal_line_differs_from_all_clear(self):
        # The point of the change: the two outcomes cannot be confused.
        self.assertNotEqual(
            self.terminal_line(self.run_gate(shellcheck=0)),
            self.terminal_line(self.run_gate(shellcheck=0, pwsh=True)),
        )

    def test_skip_still_exits_zero_by_default(self):
        # Skips stay non-fatal by default; a gate people stop running is worse.
        self.assertEqual(self.run_gate(shellcheck=0).returncode, 0)


class VerifyScriptStrictModeTests(GateHarness, unittest.TestCase):
    """--require-all / VERIFY_REQUIRE_ALL turn any skip into a failure."""

    def test_require_all_flag_fails_on_skip(self):
        result = self.run_gate(shellcheck=0, args=("--require-all",))
        self.assertEqual(result.returncode, 1)
        self.assertIn("GATE FAILED (strict)", self.terminal_line(result))
        self.assertIn("install.ps1 is unverified", self.terminal_line(result))

    def test_require_all_env_var_fails_on_skip(self):
        result = self.run_gate(shellcheck=0, env_extra={"VERIFY_REQUIRE_ALL": "1"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("GATE FAILED (strict)", self.terminal_line(result))

    def test_strict_mode_passes_when_nothing_is_skipped(self):
        result = self.run_gate(shellcheck=0, pwsh=True, args=("--require-all",))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.terminal_line(result), "GATE PASSED")

    def test_real_failure_still_reads_as_gate_failed_under_strict(self):
        # A genuine failure must not be relabelled as a skip.
        result = self.run_gate(shellcheck=1, args=("--require-all",))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.terminal_line(result), "GATE FAILED")

    def test_unknown_argument_is_rejected_before_any_check_runs(self):
        result = self.run_gate(shellcheck=0, args=("--nope",))
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown argument", result.stderr)
        self.assertNotIn("RUN:", result.stdout)

    def test_help_exits_zero_without_running_checks(self):
        result = self.run_gate(shellcheck=0, args=("--help",))
        self.assertEqual(result.returncode, 0)
        self.assertIn("--require-all", result.stdout)
        self.assertNotIn("RUN:", result.stdout)


class VerifyScriptCommandOrderTests(GateHarness, unittest.TestCase):
    """The gate must run each check's command exactly as recorded (Issue #141 F6).

    The stub tools exit 0 whatever they are asked to do, so a gate command
    with the wrong argument order reads as a pass. These tests assert the
    ordered argv each stub actually received, which is the only place the
    order is still visible.

    The stubs are the only thing on PATH, so the real unittest discovery
    cannot run here; `test_harness_never_launches_the_real_suite` keeps it
    that way.
    """

    def test_shellcheck_command_argv(self):
        result = self.run_gate(shellcheck=0, pwsh=True)
        self.assertIn(
            [
                "shellcheck",
                "install.sh",
                "tests/test-install.sh",
                "tests/migration-scratch.sh",
                "scripts/check_plugin_root.sh",
                "scripts/verify.sh",
            ],
            result.invocations,
        )

    def test_installer_syntax_command_argv(self):
        # `bash install.sh -n` would run the installer instead of checking
        # its syntax. The stub exits 0 either way, so only the argv tells
        # the two apart.
        result = self.run_gate(shellcheck=0, pwsh=True)
        self.assertIn(["bash", "-n", "install.sh"], result.invocations)

    def test_verification_script_syntax_command_argv(self):
        result = self.run_gate(shellcheck=0, pwsh=True)
        self.assertIn(["bash", "-n", "scripts/verify.sh"], result.invocations)

    def test_skill_validation_command_argv(self):
        result = self.run_gate(shellcheck=0, pwsh=True)
        self.assertIn(["python3", "scripts/validate_skill.py"], result.invocations)

    def test_unittest_discovery_command_argv(self):
        result = self.run_gate(shellcheck=0, pwsh=True)
        self.assertIn(
            ["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
            result.invocations,
        )

    def test_bash_installer_tests_command_argv(self):
        result = self.run_gate(shellcheck=0, pwsh=True)
        self.assertIn(["bash", "tests/test-install.sh"], result.invocations)

    def test_plugin_root_command_argv(self):
        result = self.run_gate(shellcheck=0, pwsh=True)
        self.assertIn(["scripts/check_plugin_root.sh"], result.invocations)

    def test_version_sync_command_argv(self):
        result = self.run_gate(shellcheck=0, pwsh=True)
        self.assertIn(["python3", "scripts/check_version_sync.py"], result.invocations)

    def test_claude_packaging_commands_argv(self):
        result = self.run_gate(shellcheck=0, pwsh=True)
        self.assertIn(
            ["claude", "plugin", "validate", ".", "--strict"], result.invocations
        )
        self.assertIn(
            ["claude", "plugin", "tag", "--dry-run", "."], result.invocations
        )

    def test_powershell_installer_tests_command_argv(self):
        result = self.run_gate(shellcheck=0, pwsh=True)
        self.assertIn(["pwsh", "tests/test-install.ps1"], result.invocations)

    def test_gate_steps_run_in_the_recorded_order(self):
        result = self.run_gate(shellcheck=0, pwsh=True)
        expected = [
            [
                "shellcheck",
                "install.sh",
                "tests/test-install.sh",
                "tests/migration-scratch.sh",
                "scripts/check_plugin_root.sh",
                "scripts/verify.sh",
            ],
            ["bash", "-n", "install.sh"],
            ["bash", "-n", "scripts/verify.sh"],
            ["python3", "scripts/validate_skill.py"],
            ["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
            ["bash", "tests/test-install.sh"],
            ["scripts/check_plugin_root.sh"],
            ["python3", "scripts/check_version_sync.py"],
            ["claude", "plugin", "validate", ".", "--strict"],
            ["claude", "plugin", "tag", "--dry-run", "."],
            ["pwsh", "tests/test-install.ps1"],
        ]
        positions = []
        for argv in expected:
            self.assertIn(argv, result.invocations, f"the gate never ran {argv}")
            positions.append(result.invocations.index(argv))
        self.assertEqual(
            positions,
            sorted(positions),
            "the gate ran its steps out of the recorded order",
        )

    def test_dirty_tree_does_not_run_the_tag_command(self):
        # The tag check cannot run against a dirty tree; the argv log shows
        # it was skipped rather than run and failed.
        result = self.run_gate(shellcheck=0, pwsh=True, git_dirty=True)
        self.assertIn(
            ["claude", "plugin", "validate", ".", "--strict"], result.invocations
        )
        self.assertNotIn(
            ["claude", "plugin", "tag", "--dry-run", "."], result.invocations
        )

    def test_harness_never_launches_the_real_suite(self):
        # PATH holds only the stubs, so the real unittest discovery cannot
        # start. Real unittest announces itself in its summary; if that ever
        # shows up here the harness stopped being isolated.
        result = self.run_gate(shellcheck=0, pwsh=True)
        self.assertNotIn("Ran ", result.stdout)
        self.assertNotIn("Ran ", result.stderr)
