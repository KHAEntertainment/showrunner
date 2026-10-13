"""Opt-in `--force-with-lease <oid>` for the pre-write push check, Issue #105.

Local bare repositories stand in for the GitHub remote, so the real
`git ls-remote` and `git push --dry-run --force-with-lease=...` run end to end.
Remote URL observations and the transport account boundary are patched exactly
as in `test_physical_push_safety.py`; no test touches the network.

Every refusal asserts three things: exit code 2, an `incomplete` verdict with
the expected `reason_code`, and no actionable push target in the verdict.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RESOLVER = ROOT / "skills" / "dev" / "scripts" / "resolve_repository.py"
SPEC = importlib.util.spec_from_file_location("resolve_repository", RESOLVER)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

CANONICAL = "KHAEntertainment/claude-dev-skill"
ORIGIN_HTTPS = "https://github.com/KHAEntertainment/claude-dev-skill.git"
BRANCH = "feature"
REF = f"refs/heads/{BRANCH}"
VERIFIED = {"status": "verified", "reason_code": "account_matches", "reason": "test account"}


def _git(*args: str, cwd: Path) -> str:
    done = subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)
    return done.stdout.strip()


def _rev(repo: Path, ref: str) -> str | None:
    done = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", ref], capture_output=True, text=True)
    return done.stdout.strip() or None


def _verdict(
    checkout: Path,
    *,
    lease: str | None = None,
    operation: str | None = None,
    extra: list[str] | None = None,
    assigned_branch: str | None = BRANCH,
    print_remote: bool = False,
    account: dict[str, str] = VERIFIED,
) -> tuple[int, str, dict[str, object] | None]:
    """Run the real CLI. Returns (exit code, stdout, parsed verdict or None)."""
    config_path = checkout / ".dev.json"
    if config_path.exists():
        config_path.unlink()
    config = MODULE.dev_config.build_config(
        host="github.com", account="KHAEntertainment", push_repository=CANONICAL,
        pull_request_repository=CANONICAL, push_remote="origin")
    MODULE.dev_config.create_config(config_path, config)
    MODULE.dev_config.ensure_excluded(checkout)
    _git("config", "remote.pushDefault", "origin", cwd=checkout)
    argv = ["resolver", "--repo-dir", str(checkout)]
    if operation is not None:
        argv += ["--operation", operation]
    if assigned_branch is not None:
        argv += ["--assigned-branch", assigned_branch]
    if lease is not None:
        # `=` form: argparse would read a leading-dash value as another option.
        argv += [f"--force-with-lease={lease}"]
    if print_remote:
        argv += ["--print-push-remote"]
    argv += extra or []
    output = io.StringIO()
    with patch.object(sys, "argv", argv), contextlib.redirect_stdout(output), \
            contextlib.redirect_stderr(io.StringIO()), \
            patch.object(MODULE, "collect_remotes", return_value=({"origin": [ORIGIN_HTTPS]}, {})), \
            patch.object(MODULE, "collect_gh_default", return_value=None), \
            patch.object(MODULE, "collect_verified_name", return_value=CANONICAL), \
            patch.object(MODULE, "verify_https_account", return_value=account), \
            patch.object(MODULE, "verify_gh_cli_login", return_value=VERIFIED):
        code = MODULE.main()
    text = output.getvalue()
    try:
        verdict = json.loads(text)
    except json.JSONDecodeError:
        verdict = None
    return code, text, verdict


class LeaseFixture(unittest.TestCase):
    """A remote with `feature` pushed once, and a clone on `feature`."""

    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.bare = self.root / "intended.git"
        _git("init", "--bare", "-q", str(self.bare), cwd=self.root)
        self.clone = self.root / "work"
        _git("clone", "-q", str(self.bare), str(self.clone), cwd=self.root)
        _git("config", "user.email", "test@example.com", cwd=self.clone)
        _git("config", "user.name", "Test", cwd=self.clone)
        _git("checkout", "-q", "-B", "main", cwd=self.clone)
        self.base = self.commit(self.clone, "base.txt")
        _git("push", "-q", "origin", "HEAD:refs/heads/main", cwd=self.clone)
        _git("checkout", "-q", "-b", BRANCH, cwd=self.clone)
        self.remote_head = self.commit(self.clone, "feature.txt")
        _git("push", "-q", "origin", f"HEAD:{REF}", cwd=self.clone)

    def commit(self, repo: Path, filename: str) -> str:
        (repo / filename).write_text(filename + "\n", encoding="utf-8")
        _git("add", filename, cwd=repo)
        _git("commit", "-q", "-m", filename, cwd=repo)
        return _git("rev-parse", "HEAD", cwd=repo)

    def rebase_onto_new_main(self) -> str:
        """Advance `main`, then rebase `feature` onto it: now a non-fast-forward."""
        _git("checkout", "-q", "main", cwd=self.clone)
        self.commit(self.clone, "main2.txt")
        _git("push", "-q", "origin", "HEAD:refs/heads/main", cwd=self.clone)
        _git("checkout", "-q", BRANCH, cwd=self.clone)
        _git("rebase", "-q", "main", cwd=self.clone)
        rebased = _git("rev-parse", "HEAD", cwd=self.clone)
        self.assertNotEqual(self.remote_head, rebased)
        done = subprocess.run(
            ["git", "-C", str(self.clone), "merge-base", "--is-ancestor", self.remote_head, rebased])
        self.assertEqual(1, done.returncode, "precondition: a rebase must make the push non-fast-forward")
        return rebased

    def move_remote_head(self) -> str:
        """Someone else pushes to `feature` from a second clone."""
        other = self.root / "other"
        _git("clone", "-q", str(self.bare), str(other), cwd=self.root)
        _git("config", "user.email", "test@example.com", cwd=other)
        _git("config", "user.name", "Test", cwd=other)
        _git("checkout", "-q", BRANCH, cwd=other)
        sha = self.commit(other, "theirs.txt")
        _git("push", "-q", "origin", f"HEAD:{REF}", cwd=other)
        return sha

    def assertNotReady(self, code, verdict, reason_code: str) -> None:
        self.assertEqual(2, code)
        self.assertIsNotNone(verdict)
        self.assertEqual("incomplete", verdict["status"])
        self.assertEqual(reason_code, verdict["reason_code"])
        self.assertIsNone(verdict.get("effective_push_remote"))
        self.assertIsNone(verdict.get("remote"))
        self.assertNotIn("dry_run", verdict)

    def assertRemoteUntouched(self) -> None:
        self.assertEqual(self.remote_head, _rev(self.bare, REF))


class LeaseReadyTests(LeaseFixture):
    def test_rebased_branch_with_current_lease_is_ready_and_prints_the_remote(self) -> None:
        self.rebase_onto_new_main()
        code, text, _ = _verdict(self.clone, lease=self.remote_head, print_remote=True)
        self.assertEqual((0, "origin\n"), (code, text))

        code, _, verdict = _verdict(self.clone, lease=self.remote_head)
        self.assertEqual(0, code)
        self.assertEqual("ready", verdict["status"])
        self.assertEqual("origin", verdict["effective_push_remote"])
        self.assertEqual(f"--force-with-lease={REF}:{self.remote_head}", verdict["dry_run"]["lease"])
        self.assertEqual(f"{REF}:{REF}", verdict["dry_run"]["refspec"])
        self.assertRemoteUntouched()

    def test_ready_verdict_supports_the_real_lease_push_and_only_it(self) -> None:
        rebased = self.rebase_onto_new_main()
        code, _, verdict = _verdict(self.clone, lease=self.remote_head)
        self.assertEqual(0, code)
        self.assertRemoteUntouched()

        lease = verdict["dry_run"]["lease"]
        _git("push", "-q", lease, verdict["effective_push_remote"], verdict["dry_run"]["refspec"], cwd=self.clone)
        self.assertEqual(rebased, _rev(self.bare, REF))

    def test_the_lease_still_protects_the_real_push_if_the_remote_moves_after_the_check(self) -> None:
        self.rebase_onto_new_main()
        code, _, verdict = _verdict(self.clone, lease=self.remote_head)
        self.assertEqual(0, code)
        theirs = self.move_remote_head()

        done = subprocess.run(
            ["git", "push", verdict["dry_run"]["lease"], "origin", verdict["dry_run"]["refspec"]],
            cwd=str(self.clone), capture_output=True, text=True)
        self.assertNotEqual(0, done.returncode)
        self.assertEqual(theirs, _rev(self.bare, REF), "the stale lease must not overwrite their push")

    def test_fast_forward_push_is_ready_with_and_without_the_flag(self) -> None:
        self.commit(self.clone, "more.txt")
        code, _, verdict = _verdict(self.clone)
        self.assertEqual((0, "ready"), (code, verdict["status"]))
        self.assertNotIn("lease", verdict["dry_run"])

        code, _, verdict = _verdict(self.clone, lease=self.remote_head)
        self.assertEqual((0, "ready"), (code, verdict["status"]))
        self.assertEqual(f"--force-with-lease={REF}:{self.remote_head}", verdict["dry_run"]["lease"])

    def test_no_op_push_is_ready_with_the_lease(self) -> None:
        code, _, verdict = _verdict(self.clone, lease=self.remote_head)
        self.assertEqual((0, "ready"), (code, verdict["status"]))

    def test_multiple_push_urls_must_all_be_at_the_lease(self) -> None:
        second = self.root / "second.git"
        _git("init", "--bare", "-q", str(second), cwd=self.root)
        _git("push", "-q", str(second), f"{self.remote_head}:{REF}", cwd=self.clone)
        _git("remote", "set-url", "--push", "origin", str(self.bare), cwd=self.clone)
        _git("remote", "set-url", "--add", "--push", "origin", str(second), cwd=self.clone)
        self.rebase_onto_new_main()

        code, _, verdict = _verdict(self.clone, lease=self.remote_head)
        self.assertEqual((0, "ready"), (code, verdict["status"]))

        # The second push URL's branch moves on: the lease no longer holds there.
        other = self.root / "second-clone"
        _git("clone", "-q", str(second), str(other), cwd=self.root)
        _git("config", "user.email", "test@example.com", cwd=other)
        _git("config", "user.name", "Test", cwd=other)
        _git("checkout", "-q", BRANCH, cwd=other)
        moved = self.commit(other, "second-only.txt")
        _git("push", "-q", "origin", f"HEAD:{REF}", cwd=other)

        code, _, verdict = _verdict(self.clone, lease=self.remote_head)
        self.assertNotReady(code, verdict, "lease_mismatch")
        self.assertIn("push URL 2 of 2", verdict["reason"])
        self.assertIn(moved, verdict["reason"])


class LeaseRefusalTests(LeaseFixture):
    def test_rebased_branch_without_the_flag_is_still_dry_run_failed(self) -> None:
        self.rebase_onto_new_main()
        code, _, verdict = _verdict(self.clone)
        self.assertNotReady(code, verdict, "dry_run_failed")
        self.assertRemoteUntouched()

    def test_stale_lease_is_refused_and_names_both_oids(self) -> None:
        self.rebase_onto_new_main()
        theirs = self.move_remote_head()
        code, _, verdict = _verdict(self.clone, lease=self.remote_head)
        self.assertNotReady(code, verdict, "lease_mismatch")
        self.assertIn(self.remote_head, verdict["reason"])
        self.assertIn(theirs, verdict["reason"])
        self.assertEqual(theirs, _rev(self.bare, REF))

    def test_a_stale_local_remote_tracking_ref_cannot_make_a_wrong_lease_pass(self) -> None:
        """`origin/feature` locally still equals the lease, but the remote moved: the live read wins."""
        self.rebase_onto_new_main()
        theirs = self.move_remote_head()
        self.assertEqual(self.remote_head, _rev(self.clone, "refs/remotes/origin/feature"))
        code, _, verdict = _verdict(self.clone, lease=self.remote_head)
        self.assertNotReady(code, verdict, "lease_mismatch")
        self.assertIn(theirs, verdict["reason"])

    def test_lease_of_an_unrelated_but_well_formed_oid_is_refused(self) -> None:
        code, _, verdict = _verdict(self.clone, lease=self.base)
        self.assertNotReady(code, verdict, "lease_mismatch")
        self.assertIn(self.base, verdict["reason"])
        self.assertIn(self.remote_head, verdict["reason"])

    def test_malformed_leases_are_refused_before_any_remote_contact(self) -> None:
        bad = {
            "abbreviated": self.remote_head[:12],
            "uppercase": self.remote_head.upper(),
            "ref name": "refs/heads/feature",
            "empty": "",
            "padded": f" {self.remote_head}",
            "trailing newline": f"{self.remote_head}\n",
            "too long": self.remote_head + "0",
            "non-hex": "g" * 40,
        }
        for label, value in bad.items():
            with self.subTest(label), patch.object(MODULE, "read_command", side_effect=AssertionError("no git")):
                code, _, verdict = _verdict(self.clone, lease=value)
                self.assertNotReady(code, verdict, "invalid_lease_oid")

    def test_all_zero_lease_cannot_match_an_existing_branch(self) -> None:
        code, _, verdict = _verdict(self.clone, lease="0" * 40)
        self.assertNotReady(code, verdict, "lease_mismatch")
        self.assertRemoteUntouched()

    def test_branch_missing_on_the_remote_is_refused(self) -> None:
        _git("push", "-q", "origin", f":{REF}", cwd=self.clone)
        self.assertIsNone(_rev(self.bare, REF))
        code, _, verdict = _verdict(self.clone, lease=self.remote_head)
        self.assertNotReady(code, verdict, "lease_branch_missing")

    def test_unreachable_remote_is_refused(self) -> None:
        missing = self.root / "gone.git"
        _git("remote", "set-url", "--push", "origin", str(missing), cwd=self.clone)
        code, _, verdict = _verdict(self.clone, lease=self.remote_head)
        self.assertNotReady(code, verdict, "remote_unreachable")

    def test_ls_remote_error_is_refused(self) -> None:
        def failing(command, cwd):
            return (128, "fatal: unable to access remote") if "ls-remote" in command else (0, "")

        result = MODULE.verify_branch_and_dry_run(
            self.clone, remote="origin", assigned_branch=BRANCH, lease_oid=self.remote_head,
            dry_run_runner=failing)
        self.assertEqual(("incomplete", "remote_unreachable"), (result["status"], result["reason_code"]))
        self.assertNotIn("remote", result)

    def test_unparseable_or_ambiguous_ls_remote_output_is_refused(self) -> None:
        cases = {
            "garbage head": f"not-a-sha\t{REF}\n",
            "two heads": f"{self.remote_head}\t{REF}\n{self.base}\t{REF}\n",
            "only a different ref": f"{self.remote_head}\trefs/remotes/x/feature\n",
            "empty": "",
        }
        expected = {
            "garbage head": "remote_head_unresolved",
            "two heads": "remote_head_unresolved",
            "only a different ref": "lease_branch_missing",
            "empty": "lease_branch_missing",
        }
        for label, output in cases.items():
            with self.subTest(label):
                def fake(command, cwd, output=output):
                    return (0, output)

                result = MODULE.verify_branch_and_dry_run(
                    self.clone, remote="origin", assigned_branch=BRANCH, lease_oid=self.remote_head,
                    dry_run_runner=fake)
                self.assertEqual(("incomplete", expected[label]), (result["status"], result["reason_code"]))

    def test_remote_moving_between_the_check_and_the_dry_run_is_dry_run_failed(self) -> None:
        calls: list[list[str]] = []

        def fake(command, cwd):
            calls.append(command)
            if "ls-remote" in command:
                return (0, f"{self.remote_head}\t{REF}\n")
            return (1, "! [rejected] (stale info)")

        result = MODULE.verify_branch_and_dry_run(
            self.clone, remote="origin", assigned_branch=BRANCH, lease_oid=self.remote_head,
            dry_run_runner=fake)
        self.assertEqual(("incomplete", "dry_run_failed"), (result["status"], result["reason_code"]))
        self.assertNotIn("remote", result)
        self.assertEqual(2, len(calls))

    def test_no_push_url_is_refused(self) -> None:
        with patch.object(MODULE, "read_command", return_value=(1, "")):
            result = MODULE.verify_branch_lease(
                self.clone, remote="origin", ref=REF, lease_oid=self.remote_head)
        self.assertEqual("push_url_unavailable", result["reason_code"])


class LeaseApplicabilityTests(LeaseFixture):
    def test_lease_is_refused_for_every_other_operation_and_mode(self) -> None:
        cases = {
            "pr": dict(operation="pr", extra=["--target", CANONICAL]),
            "issue": dict(operation="issue", extra=["--target", CANONICAL]),
            "tag push": dict(assigned_branch=None, extra=["--dest-ref", "refs/tags/v9.9.9", f"--tag-target={self.base}"]),
            "fixture": dict(extra=["--fixture", str(self.root / "fixture.json")]),
            "check-gh-account": dict(extra=["--mode", "check-gh-account"]),
            "check-https-account": dict(extra=["--mode", "check-https-account", "--url", ORIGIN_HTTPS]),
            "check-ssh-account": dict(extra=["--mode", "check-ssh-account", "--url", "git@github.com:a/b.git"]),
        }
        for label, kwargs in cases.items():
            with self.subTest(label):
                code, _, verdict = _verdict(self.clone, lease=self.remote_head, **kwargs)
                self.assertNotReady(code, verdict, "lease_not_applicable")

    def test_lease_requires_an_assigned_branch(self) -> None:
        code, _, verdict = _verdict(self.clone, lease=self.remote_head, assigned_branch=None)
        self.assertNotReady(code, verdict, "lease_not_applicable")

    def test_lease_on_the_wrong_checkout_branch_is_refused_by_the_existing_guard(self) -> None:
        _git("checkout", "-q", "main", cwd=self.clone)
        code, _, verdict = _verdict(self.clone, lease=self.remote_head)
        self.assertNotReady(code, verdict, "branch_mismatch")

    def test_lease_cannot_redirect_the_destination(self) -> None:
        code, _, verdict = _verdict(self.clone, lease=self.remote_head, extra=["--dest-ref", "refs/heads/main"])
        self.assertNotReady(code, verdict, "destination_mismatch")

    def test_lease_does_not_bypass_repository_identity(self) -> None:
        wrong = MODULE.dev_config.build_config(
            host="github.com", account="KHAEntertainment", push_repository="someone/else",
            pull_request_repository="someone/else", push_remote="origin")
        with patch.object(MODULE.dev_config, "build_config", return_value=wrong):
            code, _, verdict = _verdict(self.clone, lease=self.remote_head)
        self.assertEqual(2, code)
        self.assertEqual("incomplete", verdict["status"])
        self.assertNotEqual("dry_run_confirmed", verdict.get("reason_code"))
        self.assertIsNone(verdict.get("effective_push_remote"))

    def test_lease_does_not_bypass_the_transport_account_check(self) -> None:
        self.rebase_onto_new_main()
        mismatch = {"status": "incomplete", "reason_code": "account_mismatch", "reason": "no"}
        code, _, verdict = _verdict(self.clone, lease=self.remote_head, account=mismatch)
        self.assertNotReady(code, verdict, "account_mismatch")

    def test_no_verify_access_stays_refused_with_a_lease(self) -> None:
        code, _, verdict = _verdict(self.clone, lease=self.remote_head, extra=["--no-verify-access"])
        self.assertNotReady(code, verdict, "verification_required")


class PlusPrefixedBranchTests(LeaseFixture):
    """A valid branch named `+feature` must never be read by Git as a forced refspec.

    The emitted refspec names the source as `refs/heads/+feature`; unqualified,
    `+feature:refs/heads/+feature` means "force-push local `feature`", which
    overrode a stale lease in a real push.
    """

    PLUS = "+feature"
    PLUS_REF = "refs/heads/+feature"

    def setUp(self) -> None:
        super().setUp()
        # `feature` (from LeaseFixture) stays checked out as a distinct local branch.
        _git("checkout", "-q", "-b", self.PLUS, self.base, cwd=self.clone)
        self.plus_remote_head = self.commit(self.clone, "plus.txt")
        _git("push", "-q", "origin", f"{self.PLUS_REF}:{self.PLUS_REF}", cwd=self.clone)
        self.assertNotEqual(self.plus_remote_head, _rev(self.clone, "refs/heads/feature"))

    def verdict(self, **kwargs):
        return _verdict(self.clone, assigned_branch=self.PLUS, **kwargs)

    def push(self, verdict, *, lease: bool) -> subprocess.CompletedProcess:
        command = ["git", "push"]
        if lease:
            command.append(verdict["dry_run"]["lease"])
        command += [verdict["effective_push_remote"], verdict["dry_run"]["refspec"]]
        return subprocess.run(command, cwd=str(self.clone), capture_output=True, text=True)

    def test_no_lease_refspec_is_not_a_forced_refspec_and_names_the_qualified_source(self) -> None:
        self.commit(self.clone, "plus2.txt")
        code, _, verdict = self.verdict()
        self.assertEqual((0, "ready"), (code, verdict["status"]))
        refspec = verdict["dry_run"]["refspec"]
        self.assertFalse(refspec.startswith("+"), refspec)
        self.assertEqual(f"{self.PLUS_REF}:{self.PLUS_REF}", refspec)

        done = self.push(verdict, lease=False)
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual(_rev(self.clone, self.PLUS_REF), _rev(self.bare, self.PLUS_REF))
        self.assertEqual(self.remote_head, _rev(self.bare, REF), "the distinct local `feature` must not be pushed")

    def test_stale_lease_still_rejects_the_real_push_of_the_emitted_refspec(self) -> None:
        other = self.root / "other-plus"
        _git("clone", "-q", str(self.bare), str(other), cwd=self.root)
        _git("config", "user.email", "test@example.com", cwd=other)
        _git("config", "user.name", "Test", cwd=other)
        _git("checkout", "-q", "-b", "theirs", self.plus_remote_head, cwd=other)
        self.assertEqual(self.plus_remote_head, _git("rev-parse", "HEAD", cwd=other))

        code, _, verdict = self.verdict(lease=self.plus_remote_head)
        self.assertEqual((0, "ready"), (code, verdict["status"]), "the lease holds at check time")
        refspec = verdict["dry_run"]["refspec"]
        self.assertFalse(refspec.startswith("+"), refspec)
        self.assertEqual(f"{self.PLUS_REF}:{self.PLUS_REF}", refspec)

        theirs = self.commit(other, "theirs-plus.txt")
        _git("push", "-q", "origin", f"HEAD:{self.PLUS_REF}", cwd=other)

        done = self.push(verdict, lease=True)
        self.assertNotEqual(0, done.returncode, "a stale lease must reject the push")
        self.assertNotIn("forced update", done.stderr)
        self.assertEqual(theirs, _rev(self.bare, self.PLUS_REF), "the moved commit must survive")
        self.assertEqual(self.remote_head, _rev(self.bare, REF))

    def test_plus_branch_lease_mismatch_is_still_refused(self) -> None:
        code, _, verdict = self.verdict(lease=self.remote_head)
        self.assertNotReady(code, verdict, "lease_mismatch")
        self.assertIn(self.plus_remote_head, verdict["reason"])

    def test_ordinary_branch_still_emits_a_qualified_refspec_and_pushes(self) -> None:
        _git("checkout", "-q", BRANCH, cwd=self.clone)
        self.commit(self.clone, "ordinary.txt")
        code, _, verdict = _verdict(self.clone)
        self.assertEqual((0, "ready"), (code, verdict["status"]))
        self.assertEqual(f"{REF}:{REF}", verdict["dry_run"]["refspec"])
        done = self.push(verdict, lease=False)
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual(_rev(self.clone, REF), _rev(self.bare, REF))


class NeverBareForceTests(LeaseFixture):
    def test_every_git_command_run_for_a_lease_check_is_free_of_a_bare_force(self) -> None:
        self.rebase_onto_new_main()
        seen: list[list[str]] = []
        real = MODULE.read_command

        def spy(command, *args, **kwargs):
            seen.append(list(command))
            return real(command, *args, **kwargs)

        with patch.object(MODULE, "read_command", side_effect=spy):
            code, _, verdict = _verdict(self.clone, lease=self.remote_head)
        self.assertEqual((0, "ready"), (code, verdict["status"]))
        pushes = [c for c in seen if c[:2] == ["git", "push"]]
        self.assertEqual(1, len(pushes))
        self.assertEqual(
            ["git", "push", "--dry-run", f"--force-with-lease={REF}:{self.remote_head}", "origin", f"{REF}:{REF}"],
            pushes[0])
        for command in seen:
            self.assertNotIn("--force", command)
            self.assertNotIn("-f", command)
            self.assertFalse([a for a in command if a.startswith("+")], "no forced refspec")

    def test_without_the_flag_the_dry_run_command_is_unchanged(self) -> None:
        seen: list[list[str]] = []
        real = MODULE.read_command

        def spy(command, *args, **kwargs):
            seen.append(list(command))
            return real(command, *args, **kwargs)

        with patch.object(MODULE, "read_command", side_effect=spy):
            _verdict(self.clone)
        pushes = [c for c in seen if c[:2] == ["git", "push"]]
        self.assertEqual([["git", "push", "--dry-run", "origin", f"{REF}:{REF}"]], pushes)
        self.assertFalse([c for c in seen if "ls-remote" in c], "no remote head read without a lease")

    def test_bare_force_and_its_prefixes_are_not_accepted_flags(self) -> None:
        for flag in ("--force", "--force-with", "-f"):
            with self.subTest(flag):
                argv = ["resolver", "--repo-dir", str(self.clone), "--assigned-branch", BRANCH, flag, self.remote_head]
                with patch.object(sys, "argv", argv), contextlib.redirect_stderr(io.StringIO()), \
                        self.assertRaises(SystemExit) as raised:
                    MODULE.main()
                self.assertEqual(2, raised.exception.code)

    def test_a_lease_flag_without_a_value_is_not_accepted(self) -> None:
        argv = ["resolver", "--repo-dir", str(self.clone), "--assigned-branch", BRANCH, "--force-with-lease"]
        with patch.object(sys, "argv", argv), contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit) as raised:
            MODULE.main()
        self.assertEqual(2, raised.exception.code)


if __name__ == "__main__":
    unittest.main()
