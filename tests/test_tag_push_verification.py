"""Release tag push verification (`--tag-target`), Issue #71.

Local bare repositories stand in for the GitHub remote, so the real
`git ls-remote`, `git show-ref`, and `git push --dry-run` run end to end. The
remote URL observations and the transport/`gh` account boundaries are patched,
exactly as in `test_physical_push_safety.py`; no test touches the network.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
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
VERIFIED = {"status": "verified", "reason_code": "account_matches", "reason": "test account"}
GH_REJECTED = {"status": "incomplete", "reason_code": "account_mismatch", "reason": "gh is someone else"}


def _git(*args: str, cwd: Path) -> str:
    done = subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)
    return done.stdout.strip()


def _rev(repo: Path, ref: str) -> str | None:
    done = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", ref], capture_output=True, text=True)
    return done.stdout.strip() or None


def _tag_verdict(
    checkout: Path,
    *,
    tag_target: str | None,
    dest_ref: str | None = "refs/tags/v9.9.9",
    assigned_branch: str | None = None,
    expected: str = CANONICAL,
    push_remotes: dict[str, list[str]] | None = None,
    account: dict[str, str] = VERIFIED,
    gh_login: dict[str, str] = VERIFIED,
    print_remote: bool = False,
) -> tuple[int, str, dict[str, object] | None]:
    """Run the real CLI. Returns (exit code, stdout, parsed verdict or None)."""
    config_path = checkout / ".dev.json"
    if config_path.exists():
        config_path.unlink()
    config = MODULE.dev_config.build_config(
        host="github.com", account="KHAEntertainment", push_repository=expected,
        pull_request_repository=expected, push_remote="origin")
    MODULE.dev_config.create_config(config_path, config)
    MODULE.dev_config.ensure_excluded(checkout)
    _git("config", "remote.pushDefault", "origin", cwd=checkout)
    argv = ["resolver", "--repo-dir", str(checkout)]
    if tag_target is not None:
        # `=` form: argparse would read a leading-dash value as another option.
        argv += [f"--tag-target={tag_target}"]
    if dest_ref is not None:
        argv += ["--dest-ref", dest_ref]
    if assigned_branch is not None:
        argv += ["--assigned-branch", assigned_branch]
    if print_remote:
        argv += ["--print-push-remote"]
    output = io.StringIO()
    with patch.object(sys, "argv", argv), contextlib.redirect_stdout(output), \
            contextlib.redirect_stderr(io.StringIO()), \
            patch.object(MODULE, "collect_remotes", return_value=({"origin": [ORIGIN_HTTPS]}, push_remotes or {})), \
            patch.object(MODULE, "collect_gh_default", return_value=None), \
            patch.object(MODULE, "collect_verified_name", return_value=CANONICAL), \
            patch.object(MODULE, "verify_https_account", return_value=account), \
            patch.object(MODULE, "verify_gh_cli_login", return_value=gh_login):
        code = MODULE.main()
    text = output.getvalue()
    try:
        verdict = json.loads(text)
    except json.JSONDecodeError:
        verdict = None
    return code, text, verdict


class TagPushFixture(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.bare = self.make_bare("intended.git")
        self.clone = self.root / "work"
        _git("clone", "-q", str(self.bare), str(self.clone), cwd=self.root)
        _git("config", "user.email", "test@example.com", cwd=self.clone)
        _git("config", "user.name", "Test", cwd=self.clone)
        _git("checkout", "-q", "-B", "main", cwd=self.clone)
        self.main_sha = self.commit(self.clone, "one.txt")
        _git("push", "-q", "origin", "HEAD:refs/heads/main", cwd=self.clone)
        # The clone's remote-tracking ref is now fresh at `main_sha`.

    def make_bare(self, name: str) -> Path:
        bare = self.root / name
        _git("init", "--bare", "-q", str(bare), cwd=self.root)
        _git("symbolic-ref", "HEAD", "refs/heads/main", cwd=bare)
        # `git tag -a` run in a bare repo needs a tagger identity; never rely on a global one.
        _git("config", "user.email", "test@example.com", cwd=bare)
        _git("config", "user.name", "Test", cwd=bare)
        return bare

    def commit(self, repo: Path, filename: str) -> str:
        (repo / filename).write_text(filename + "\n", encoding="utf-8")
        _git("add", filename, cwd=repo)
        _git("commit", "-q", "-m", filename, cwd=repo)
        return _git("rev-parse", "HEAD", cwd=repo)

    def advance_remote_main(self) -> str:
        """Move the remote `main` forward from a second clone, leaving `self.clone` stale."""
        other = self.root / "other"
        _git("clone", "-q", str(self.bare), str(other), cwd=self.root)
        _git("config", "user.email", "test@example.com", cwd=other)
        _git("config", "user.name", "Test", cwd=other)
        sha = self.commit(other, "two.txt")
        _git("push", "-q", "origin", "HEAD:refs/heads/main", cwd=other)
        return sha

    def assertNotReady(self, code, verdict, reason_code: str) -> None:
        self.assertEqual(2, code)
        self.assertEqual("incomplete", verdict["status"])
        self.assertEqual(reason_code, verdict["reason_code"])
        self.assertIsNone(verdict.get("effective_push_remote"))


class TagPushReadyTests(TagPushFixture):
    def test_detached_clean_checkout_is_ready_and_prints_the_remote(self) -> None:
        _git("checkout", "-q", "--detach", cwd=self.clone)
        self.assertEqual("", _git("branch", "--show-current", cwd=self.clone))

        code, text, _ = _tag_verdict(self.clone, tag_target=self.main_sha, print_remote=True)
        self.assertEqual((0, "origin\n"), (code, text))

        code, _, verdict = _tag_verdict(self.clone, tag_target="HEAD")
        self.assertEqual(0, code)
        self.assertEqual("ready", verdict["status"])
        self.assertEqual("origin", verdict["effective_push_remote"])
        self.assertEqual(
            {"name": "v9.9.9", "target": self.main_sha, "default_branch": "main"}, verdict["tag"])

    def test_ready_verdict_supports_the_real_tag_push(self) -> None:
        _git("checkout", "-q", "--detach", cwd=self.clone)
        code, _, verdict = _tag_verdict(self.clone, tag_target=self.main_sha)
        self.assertEqual(0, code)
        self.assertIsNone(_rev(self.bare, "refs/tags/v9.9.9"), "the check itself must not create the tag")

        _git("tag", "-a", "v9.9.9", "-m", "release", self.main_sha, cwd=self.clone)
        self.assertEqual(self.main_sha, _git("rev-parse", "v9.9.9^{commit}", cwd=self.clone))
        _git("push", "-q", verdict["effective_push_remote"], "refs/tags/v9.9.9", cwd=self.clone)
        self.assertEqual(self.main_sha, _rev(self.bare, "refs/tags/v9.9.9^{commit}"))

    def test_linked_worktree_on_another_branch_is_ready(self) -> None:
        worktree = self.root / "linked"
        _git("worktree", "add", "-q", "-b", "task/other", str(worktree), self.main_sha, cwd=self.clone)
        self.commit(worktree, "task.txt")
        code, _, verdict = _tag_verdict(worktree, tag_target=self.main_sha)
        self.assertEqual((0, "ready"), (code, verdict["status"]))

    def test_does_not_trust_a_stale_local_origin_main(self) -> None:
        """The local remote-tracking ref still equals the target, but the remote
        has moved on. The live read must win, so the tag is refused."""
        remote_tip = self.advance_remote_main()
        self.assertEqual(self.main_sha, _rev(self.clone, "refs/remotes/origin/main"))

        code, _, verdict = _tag_verdict(self.clone, tag_target=self.main_sha)
        self.assertNotReady(code, verdict, "target_mismatch")
        self.assertIn(self.main_sha, verdict["reason"])
        self.assertIn(remote_tip, verdict["reason"])
        self.assertIn("`main`", verdict["reason"])

    def test_multiple_push_urls_must_all_agree(self) -> None:
        second = self.make_bare("second.git")
        _git("push", "-q", str(second), "HEAD:refs/heads/main", cwd=self.clone)
        _git("remote", "set-url", "--push", "origin", str(self.bare), cwd=self.clone)
        _git("remote", "set-url", "--add", "--push", "origin", str(second), cwd=self.clone)

        code, _, verdict = _tag_verdict(self.clone, tag_target=self.main_sha)
        self.assertEqual((0, "ready"), (code, verdict["status"]))

        # The second URL's default branch moves on: now they disagree.
        other = self.root / "second-clone"
        _git("clone", "-q", str(second), str(other), cwd=self.root)
        _git("config", "user.email", "test@example.com", cwd=other)
        _git("config", "user.name", "Test", cwd=other)
        self.commit(other, "extra.txt")
        _git("push", "-q", "origin", "HEAD:refs/heads/main", cwd=other)

        code, _, verdict = _tag_verdict(self.clone, tag_target=self.main_sha)
        self.assertNotReady(code, verdict, "target_mismatch")
        self.assertIn("push URL 2 of 2", verdict["reason"])

    def test_tag_on_only_the_second_push_url_is_refused(self) -> None:
        second = self.make_bare("second.git")
        _git("push", "-q", str(second), "HEAD:refs/heads/main", cwd=self.clone)
        _git("tag", "v9.9.9", self.main_sha, cwd=second)
        _git("remote", "set-url", "--push", "origin", str(self.bare), cwd=self.clone)
        _git("remote", "set-url", "--add", "--push", "origin", str(second), cwd=self.clone)
        code, _, verdict = _tag_verdict(self.clone, tag_target=self.main_sha)
        self.assertNotReady(code, verdict, "tag_exists_remote")
        self.assertIn("push URL 2 of 2", verdict["reason"])


class TagPushRefusalTests(TagPushFixture):
    def test_tag_that_exists_locally_is_refused(self) -> None:
        _git("tag", "v9.9.9", self.main_sha, cwd=self.clone)
        code, _, verdict = _tag_verdict(self.clone, tag_target=self.main_sha)
        self.assertNotReady(code, verdict, "tag_exists_local")

    def test_tag_that_exists_on_the_remote_is_refused_even_when_annotated(self) -> None:
        _git("tag", "-a", "v9.9.9", "-m", "already released", self.main_sha, cwd=self.bare)
        self.assertIsNone(_rev(self.clone, "refs/tags/v9.9.9"), "precondition: not known locally")
        code, _, verdict = _tag_verdict(self.clone, tag_target=self.main_sha)
        self.assertNotReady(code, verdict, "tag_exists_remote")

    def test_unreachable_remote_fails_closed(self) -> None:
        _git("remote", "set-url", "origin", str(self.root / "does-not-exist.git"), cwd=self.clone)
        code, _, verdict = _tag_verdict(self.clone, tag_target=self.main_sha)
        self.assertNotReady(code, verdict, "remote_unreachable")

    def test_remote_without_a_resolvable_default_branch_fails_closed(self) -> None:
        _git("symbolic-ref", "HEAD", "refs/heads/no-such-branch", cwd=self.bare)
        code, _, verdict = _tag_verdict(self.clone, tag_target=self.main_sha)
        self.assertNotReady(code, verdict, "default_branch_unresolved")

    def test_unparseable_tag_targets_are_refused(self) -> None:
        for target in ("", "not-a-revision", "-x", "--help", "0" * 40, "refs/heads/nope"):
            with self.subTest(target=target):
                code, _, verdict = _tag_verdict(self.clone, tag_target=target)
                self.assertNotReady(code, verdict, "invalid_tag_target")

    def test_non_tag_destinations_are_refused(self) -> None:
        for dest in (None, "refs/heads/main", "main", "refs/tags/", "refs/tags/-x", "refs/tags/a..b", "refs/tags/a b"):
            with self.subTest(dest=dest):
                code, _, verdict = _tag_verdict(self.clone, tag_target=self.main_sha, dest_ref=dest)
                self.assertNotReady(code, verdict, "invalid_tag_destination")

    def test_assigned_branch_cannot_be_combined_with_tag_mode(self) -> None:
        # An empty value is still "given": it must not slip through as if absent.
        for branch in ("main", ""):
            with self.subTest(assigned_branch=branch):
                code, _, verdict = _tag_verdict(self.clone, tag_target=self.main_sha, assigned_branch=branch)
                self.assertNotReady(code, verdict, "conflicting_arguments")

    def test_verification_refusal_prints_nothing_under_print_push_remote(self) -> None:
        _git("tag", "v9.9.9", self.main_sha, cwd=self.clone)
        code, text, _ = _tag_verdict(self.clone, tag_target=self.main_sha, print_remote=True)
        self.assertEqual((2, ""), (code, text))

    def test_argument_validation_failures_print_the_json_verdict_under_print_push_remote(self) -> None:
        cases = (
            ({"tag_target": "not-a-revision"}, "invalid_tag_target"),
            ({"tag_target": self.main_sha, "dest_ref": "refs/heads/main"}, "invalid_tag_destination"),
            ({"tag_target": self.main_sha, "assigned_branch": "main"}, "conflicting_arguments"),
        )
        for kwargs, reason_code in cases:
            with self.subTest(reason_code=reason_code):
                code, text, verdict = _tag_verdict(self.clone, print_remote=True, **kwargs)
                self.assertEqual(2, code)
                self.assertEqual(reason_code, verdict["reason_code"])
                self.assertEqual("incomplete", verdict["status"])

    def test_dry_run_failure_through_the_runner_seam_is_refused(self) -> None:
        calls: list[list[str]] = []

        def runner(command: list[str], cwd: Path) -> tuple[int, str]:
            calls.append(command)
            if command[:3] == ["git", "push", "--dry-run"]:
                return 1, ""
            return MODULE.read_command(command, cwd=cwd, merge_stderr=False)

        result = MODULE.verify_tag_push(
            self.clone, remote="origin", tag_name="v9.9.9", target=self.main_sha, runner=runner)
        self.assertEqual(("incomplete", "dry_run_failed"), (result["status"], result["reason_code"]))
        self.assertEqual(
            ["git", "push", "--dry-run", "origin", f"{self.main_sha}:refs/tags/v9.9.9"], calls[-1])
        self.assertTrue(any(call[:3] == ["git", "ls-remote", "--symref"] for call in calls))

    def test_unreadable_local_tag_state_fails_closed(self) -> None:
        real = MODULE.read_command

        def failing_show_ref(command, **kwargs):
            if command[:2] == ["git", "show-ref"]:
                return 128, ""
            return real(command, **kwargs)

        with patch.object(MODULE, "read_command", side_effect=failing_show_ref):
            result = MODULE.verify_tag_push(self.clone, remote="origin", tag_name="v9.9.9", target=self.main_sha)
        self.assertEqual(("incomplete", "local_tag_check_failed"), (result["status"], result["reason_code"]))

    def test_unknown_remote_has_no_push_url_and_fails_closed(self) -> None:
        result = MODULE.verify_tag_push(self.clone, remote="no-such-remote", tag_name="v9.9.9", target=self.main_sha)
        self.assertEqual(("incomplete", "push_url_unavailable"), (result["status"], result["reason_code"]))


class TagPushKeepsIdentityChecksTests(TagPushFixture):
    def test_wrong_repository_identity_is_still_refused_in_tag_mode(self) -> None:
        code, _, verdict = _tag_verdict(
            self.clone, tag_target=self.main_sha, expected="hnaymyh123-henry/claude-dev-skill")
        self.assertNotReady(code, verdict, "expected_mismatch")

    def test_transport_account_mismatch_is_still_refused_in_tag_mode(self) -> None:
        rejected = {"status": "incomplete", "reason_code": "account_mismatch", "reason": "wrong credential"}
        code, _, verdict = _tag_verdict(self.clone, tag_target=self.main_sha, account=rejected)
        self.assertNotReady(code, verdict, "account_mismatch")

    def test_gh_login_mismatch_is_refused_in_tag_mode(self) -> None:
        code, _, verdict = _tag_verdict(self.clone, tag_target=self.main_sha, gh_login=GH_REJECTED)
        self.assertNotReady(code, verdict, "account_mismatch")
        self.assertIn("gh is someone else", verdict["reason"])

    def test_conflicting_branch_push_remote_fails_closed_in_tag_mode(self) -> None:
        """Documented known refusal: a `branch.<current>.pushRemote` naming a
        different remote than `.dev.json` fails closed; run from a detached checkout."""
        _git("remote", "add", "upstream", str(self.make_bare("up.git")), cwd=self.clone)
        _git("config", "branch.main.pushRemote", "upstream", cwd=self.clone)
        code, _, verdict = _tag_verdict(
            self.clone, tag_target=self.main_sha, push_remotes=None)
        self.assertEqual(2, code)
        self.assertEqual("incomplete", verdict["status"])
        _git("checkout", "-q", "--detach", cwd=self.clone)
        code, _, verdict = _tag_verdict(self.clone, tag_target=self.main_sha)
        self.assertEqual((0, "ready"), (code, verdict["status"]))


class BranchPushUnchangedTests(TagPushFixture):
    """AC4: without `--tag-target`, every branch-push verdict is exactly as before."""

    def _branch_verdict(self, **kwargs):
        return _tag_verdict(self.clone, tag_target=None, dest_ref=kwargs.pop("dest_ref", None), **kwargs)

    def test_branch_push_from_the_wrong_branch_is_rejected_with_the_exact_verdict(self) -> None:
        _git("checkout", "-q", "-b", "wrong-branch", cwd=self.clone)
        code, text, verdict = self._branch_verdict(assigned_branch="main")
        self.assertEqual(2, code)
        self.assertEqual(
            {
                "effective_push_remote": None,
                "reason": "the ledger assigns `main` but the checkout is on `wrong-branch`",
                "reason_code": "branch_mismatch",
                "remote": None,
                "repository": None,
                "status": "incomplete",
            },
            {key: verdict[key] for key in (
                "effective_push_remote", "reason", "reason_code", "remote", "repository", "status")},
        )
        self.assertNotIn("tag", verdict)

    def test_branch_push_from_a_detached_checkout_is_still_rejected(self) -> None:
        _git("checkout", "-q", "--detach", cwd=self.clone)
        code, _, verdict = self._branch_verdict(assigned_branch="main")
        self.assertNotReady(code, verdict, "branch_unavailable")

    def test_tag_destination_without_tag_target_is_still_destination_mismatch(self) -> None:
        code, _, verdict = self._branch_verdict(assigned_branch="main", dest_ref="refs/tags/v9.9.9")
        self.assertNotReady(code, verdict, "destination_mismatch")

    def test_branch_push_without_assigned_branch_still_needs_it(self) -> None:
        code, _, verdict = self._branch_verdict(assigned_branch=None)
        self.assertEqual(2, code)
        self.assertEqual("missing_argument", verdict["reason_code"])
        self.assertEqual("--assigned-branch is required for --operation push", verdict["reason"])

    def test_ready_branch_push_has_no_tag_key_and_the_same_dry_run_shape(self) -> None:
        code, _, verdict = self._branch_verdict(assigned_branch="main")
        self.assertEqual((0, "ready"), (code, verdict["status"]))
        self.assertEqual({"remote": "origin", "refspec": "refs/heads/main:refs/heads/main"}, verdict["dry_run"])
        self.assertNotIn("tag", verdict)


class ReleaseDocPinTests(unittest.TestCase):
    def _step3(self) -> str:
        text = (ROOT / "docs" / "RELEASING.md").read_text(encoding="utf-8")
        match = re.search(r"3\. \*\*Tag and push\.\*\*(.*?)\n4\. \*\*", text, re.DOTALL)
        self.assertIsNotNone(match, "RELEASING.md step 3 not found")
        return match.group(1)

    def test_step_3_runs_the_check_before_tagging_and_pushing(self) -> None:
        step = self._step3()
        check = step.index("resolve_repository.py")
        for token in ("--operation push", "--dest-ref refs/tags/", "--tag-target", "--print-push-remote"):
            self.assertIn(token, step)
        tag = step.index("git tag -a")
        push = step.index('git push "$remote" refs/tags/')
        self.assertLess(check, tag)
        self.assertLess(tag, push)
        self.assertIn("exit 1", step[check:tag], "a not-ready verdict must stop the release")

    def test_step_3_tags_the_verified_commit_and_confirms_the_peeled_commit(self) -> None:
        step = self._step3()
        self.assertIn('git tag -a vX.Y.Z -m "dev-skill X.Y.Z" "$sha"', step)
        self.assertIn("^{commit}", step)
        self.assertNotIn("v2.0.0", step, "step 3 must use vX.Y.Z placeholders, not a literal release")

    def test_repository_context_documents_tag_mode(self) -> None:
        text = (ROOT / "skills" / "dev" / "phases" / "repository-context.md").read_text(encoding="utf-8")
        self.assertIn("### Before a release tag push", text)
        for token in ("--tag-target", "--dest-ref refs/tags/", "ls-remote --symref", "detached"):
            self.assertIn(token, text)
        section = text[text.index("### Before a release tag push"):text.index("### Before a PR or Issue operation")]
        for code in ("invalid_tag_target", "invalid_tag_destination", "conflicting_arguments", "tag_exists_local",
                     "local_tag_check_failed", "push_url_unavailable", "remote_unreachable",
                     "default_branch_unresolved", "target_mismatch", "tag_exists_remote", "dry_run_failed"):
            self.assertIn(f"`{code}`", section)
        # The wording must not claim the list is exhaustive or enumerate per-check stdout behavior.
        flat = " ".join(section.split())
        self.assertIn("add these 11 reason codes", flat)
        self.assertIn("keep their existing codes", flat)
        self.assertIn("gate on the exit status, never on stdout", flat)
        self.assertNotIn("one of 11 reason codes", flat)
        self.assertNotIn("print nothing on stdout", flat)

    def test_step_4_queries_the_exact_ref_on_the_pushed_remote(self) -> None:
        text = (ROOT / "docs" / "RELEASING.md").read_text(encoding="utf-8")
        match = re.search(r"4\. \*\*Verify the tag resolves\.\*\*(.*?)\n5\. \*\*", text, re.DOTALL)
        self.assertIsNotNone(match)
        step = match.group(1)
        self.assertIn('--exit-code "$remote" refs/tags/vX.Y.Z', step)
        self.assertIn('= "$sha"', step)
        self.assertNotIn("| grep", step, "grep treats the dots as wildcards: v2.1.2 would match v2.1.20")
        self.assertNotIn("origin", step, "step 4 must query the remote step 3 pushed to, not a hardcoded one")
        self.assertNotIn("v2.0.0", step)


if __name__ == "__main__":
    unittest.main()
