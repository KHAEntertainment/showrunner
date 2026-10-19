#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import errno
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "skills" / "dev" / "scripts" / "inspect_external_reviews.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "external_reviews"

SPEC = importlib.util.spec_from_file_location("external_reviews", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def policy(*, required: set[str] | None = None, ignored: set[str] | None = None):
    return MODULE.ReviewerPolicy(
        identities={name: set(values) for name, values in MODULE.DEFAULT_IDENTITIES.items()},
        check_markers={name: set(values) for name, values in MODULE.DEFAULT_CHECK_MARKERS.items()},
        required=required or set(),
        ignored=ignored or set(),
    )


def inspect_fixture(name: str, *, dispositions: dict[str, str] | None = None, review_policy=None):
    current, threads, recent = MODULE.load_fixture(FIXTURES / name)
    return MODULE.inspect(current, threads, recent, review_policy or policy(), dispositions or {})


def comments_selection_block(query: str) -> str:
    """Extract the `comments(first:100){...}` selection set from the
    `fetch_threads` GraphQL query, brace-matching so nested selections
    (`author{login}`, `commit{oid}`, ...) do not truncate it early.
    """
    marker = "comments(first:100){"
    start = query.index(marker) + len(marker) - 1
    depth = 0
    for index in range(start, len(query)):
        if query[index] == "{":
            depth += 1
        elif query[index] == "}":
            depth -= 1
            if depth == 0:
                return query[start : index + 1]
    raise AssertionError("unbalanced braces in comments selection")


class ExternalReviewInspectorTests(unittest.TestCase):
    def test_submitted_head_thread_comment_completes(self):
        current, _, recent = MODULE.load_fixture(FIXTURES / "green-check-no-review.json")
        current["statusCheckRollup"] = []
        current["reviews"] = []
        threads = [{"id": "submitted", "comments": {"nodes": [{"author": {"login": "coderabbitai"}, "state": "SUBMITTED", "commit": {"oid": "current-head"}, "body": "finding"}]}}]
        result = MODULE.inspect(current, threads, recent, policy(), {"submitted": "advisory"})
        self.assertEqual(result["state"], "clear")
        self.assertEqual(result["completed_on_head"], ["coderabbit"])
        self.assertEqual(result["stale_reviewers"], [])

    def test_pending_head_thread_comment_does_not_complete(self):
        current, _, recent = MODULE.load_fixture(FIXTURES / "green-check-no-review.json")
        current["statusCheckRollup"] = []
        current["reviews"] = [{"id": "old", "author": {"login": "coderabbitai"}, "state": "CHANGES_REQUESTED", "commit": {"oid": "old-head"}}]
        threads = [{"id": "draft", "comments": {"nodes": [{"author": {"login": "coderabbitai"}, "state": "PENDING", "commit": {"oid": "current-head"}, "body": "draft"}]}}]
        result = MODULE.inspect(current, threads, recent, policy(), {"draft": "advisory"})
        self.assertEqual(result["state"], "pending")
        self.assertEqual(result["completed_on_head"], [])
        self.assertEqual(result["stale_reviewers"], ["coderabbit"])

    def test_inactive_head_thread_comments_do_not_erase_stale_review(self):
        current, _, recent = MODULE.load_fixture(FIXTURES / "green-check-no-review.json")
        current["statusCheckRollup"] = []
        current["reviews"] = [{"id": "old", "author": {"login": "coderabbitai"}, "state": "CHANGES_REQUESTED", "commit": {"oid": "old-head"}}]
        for resolved, outdated, minimized in ((True, False, False), (False, True, False), (False, False, True)):
            with self.subTest(resolved=resolved, outdated=outdated, minimized=minimized):
                threads = [{"id": "thread", "isResolved": resolved, "isOutdated": outdated,
                            "comments": {"nodes": [{"author": {"login": "coderabbitai"},
                            "commit": {"oid": "current-head"}, "isMinimized": minimized}]}}]
                result = MODULE.inspect(current, threads, recent, policy(), {})
                self.assertEqual(result["state"], "pending")
                self.assertEqual(result["stale_reviewers"], ["coderabbit"])

    def test_thread_comment_order_cannot_hide_active_finding(self):
        current, _, recent = MODULE.load_fixture(FIXTURES / "green-check-no-review.json")
        for nodes in (
            [{"author": {"login": "coderabbitai"}, "state": "SUBMITTED", "commit": {"oid": "current-head"}, "body": "visible"},
             {"author": {"login": "coderabbitai"}, "state": "SUBMITTED", "commit": {"oid": "current-head"}, "isMinimized": True, "body": "hidden"}],
            [{"author": {"login": "coderabbitai"}, "state": "SUBMITTED", "commit": {"oid": "current-head"}, "isMinimized": True, "body": "hidden"},
             {"author": {"login": "coderabbitai"}, "state": "SUBMITTED", "commit": {"oid": "current-head"}, "body": "visible"}],
        ):
            result = MODULE.inspect(current, [{"id": "thread", "comments": {"nodes": nodes}}], recent, policy(), {})
            self.assertEqual(result["state"], "pending")
            self.assertEqual(len(result["untriaged_findings"]), 1)

    def test_full_nested_comment_page_is_incomplete(self):
        current, _, recent = MODULE.load_fixture(FIXTURES / "green-check-no-review.json")
        comments = [{"author": {"login": "coderabbitai"}, "commit": {"oid": "current-head"}}] * 100
        result = MODULE.inspect(current, [{"id": "full", "comments": {"nodes": comments}}], recent, policy(), {})
        self.assertEqual(result["state"], "incomplete")
        self.assertIn("page limit", result["errors"][0])

    def test_older_unsubmitted_reviews_remain_pending_without_stale_claim(self):
        current, threads, recent = MODULE.load_fixture(FIXTURES / "green-check-no-review.json")
        for with_check in (True, False):
            if not with_check:
                current["statusCheckRollup"] = []
            for state in ("PENDING", "DISMISSED", None, "UNKNOWN", "CHANGES_REQUESTED"):
                with self.subTest(state=state, with_check=with_check):
                    current["reviews"] = [{
                        "id": "older", "author": {"login": "coderabbitai"},
                        "state": state, "commit": {"oid": "older-head"},
                    }]
                    result = MODULE.inspect(current, threads, recent, policy(), {})
                    self.assertEqual(result["state"], "pending")
                    self.assertEqual(result["pending_reviewers"], ["coderabbit"])
                    self.assertEqual(result["completed_on_head"], [])
                    submitted = state == "CHANGES_REQUESTED"
                    self.assertEqual(result["stale_reviewers"], ["coderabbit"] if submitted else [])
                    reasons = result["pending_reasons"]["coderabbit"]
                    if submitted:
                        self.assertIn("submitted review at an earlier head requested changes", reasons)
                    else:
                        # Stricter than matching one literal: no stale reason of
                        # any wording may appear for an unsubmitted state.
                        self.assertFalse(any("earlier head" in reason for reason in reasons))
                        self.assertTrue(any("no " in reason for reason in reasons))

    def test_unsubmitted_head_review_does_not_erase_old_objection(self):
        result = inspect_fixture("unsubmitted-review-at-head.json")
        self.assertEqual(result["state"], "pending")
        self.assertEqual(result["completed_on_head"], [])
        self.assertEqual(result["stale_reviewers"], ["coderabbit"])

    def test_only_explicit_submitted_states_count(self):
        current, threads, recent = MODULE.load_fixture(FIXTURES / "unsubmitted-review-at-head.json")
        review = current["reviews"][-1]
        for state in (None, "", "UNKNOWN", "PENDING", "DISMISSED"):
            with self.subTest(state=state):
                review["state"] = state
                result = MODULE.inspect(current, threads, recent, policy(), {})
                self.assertEqual(result["state"], "pending")
                self.assertEqual(result["stale_reviewers"], ["coderabbit"])
        del review["state"]
        self.assertEqual(MODULE.inspect(current, threads, recent, policy(), {})["state"], "pending")
        for state in ("COMMENTED", "APPROVED", "CHANGES_REQUESTED"):
            with self.subTest(state=state):
                review["state"] = state
                review["submittedAt"] = "2026-09-08T20:00:00Z"
                result = MODULE.inspect(current, threads, recent, policy(), {})
                self.assertEqual(result["completed_on_head"], ["coderabbit"])
                self.assertEqual(result["stale_reviewers"], [])

    def test_failed_snapshot_write_leaves_no_partial_and_retry_succeeds(self):
        raw = ' { "number": 21, "headRefOid": "head" }\n'
        original = MODULE.tempfile.NamedTemporaryFile
        def disk_full_file(*args, **kwargs):
            output = original(*args, **kwargs)
            real_write = output.write
            def partial_write(value):
                real_write(value[:12])
                output.flush()
                raise OSError(errno.ENOSPC, "disk full")
            output.write = partial_write
            return output
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "payload.json"
            with mock.patch.object(MODULE.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, raw, "")):
                with mock.patch.object(MODULE.tempfile, "NamedTemporaryFile", side_effect=disk_full_file):
                    with self.assertRaisesRegex(MODULE.InspectionError, "disk full"):
                        MODULE.fetch_pr("owner/repo", 21, snapshot)
                self.assertFalse(snapshot.exists())
                self.assertEqual(list(Path(directory).iterdir()), [])
                MODULE.fetch_pr("owner/repo", 21, snapshot)
                self.assertEqual(snapshot.read_text(), raw)
                self.assertEqual(list(Path(directory).iterdir()), [snapshot])

    def test_green_check_preserves_stale_review(self):
        result = inspect_fixture("green-check-stale-review.json")
        self.assertEqual(result["state"], "pending", result)
        self.assertEqual(result["stale_reviewers"], ["coderabbit"])
        self.assertEqual(result["completed_on_head"], [])

    def test_green_check_without_review_is_pending(self):
        result = inspect_fixture("green-check-no-review.json")
        self.assertEqual(result["state"], "pending")
        self.assertEqual(result["completed_on_head"], [])
        self.assertEqual(result["check_only_reviewers"], ["coderabbit"])
        self.assertIn("no submitted review or review thread", result["pending_reasons"]["coderabbit"][0])
        self.assertEqual(result["parked_comments"], [{
            "reviewer": "coderabbit",
            "url": "https://github.com/example/project/pull/21#issuecomment-1",
        }])

    def test_check_only_comment_detection_is_body_independent(self):
        current, threads, recent = MODULE.load_fixture(FIXTURES / "green-check-no-review.json")
        for body in (None, "", "rate limit", "Review complete", "unrelated"):
            with self.subTest(body=body):
                current["comments"][0]["body"] = body
                result = MODULE.inspect(current, threads, recent, policy(), {})
                self.assertEqual(result["state"], "pending")
                self.assertEqual(len(result["parked_comments"]), 1)
        current["comments"] = None
        result = MODULE.inspect(current, threads, recent, policy(), {})
        self.assertEqual(result["parked_comments"], [])
        self.assertEqual(result["state"], "pending")

    def test_green_check_with_real_head_review_clears(self):
        current, threads, recent = MODULE.load_fixture(FIXTURES / "green-check-stale-review.json")
        current["reviews"].append({"id": "new-review", "author": {"login": "coderabbitai"},
                                   "state": "COMMENTED", "submittedAt": "2026-09-08T12:00:00Z",
                                   "commit": {"oid": "current-head"}})
        result = MODULE.inspect(current, threads, recent, policy(), {})
        self.assertEqual(result["state"], "clear")
        self.assertEqual(result["check_only_reviewers"], [])
        self.assertEqual(result["stale_reviewers"], [])

    def test_green_check_with_head_thread_counts_as_evidence(self):
        current, threads, recent = MODULE.load_fixture(FIXTURES / "green-check-no-review.json")
        threads = [{"id": "thread", "comments": [{"author": {"login": "coderabbitai"},
                    "state": "SUBMITTED", "commit": {"oid": "current-head"}, "body": "Finding"}]}]
        result = MODULE.inspect(current, threads, recent, policy(), {"thread": "advisory"})
        self.assertEqual(result["state"], "clear")
        self.assertEqual(result["completed_on_head"], ["coderabbit"])

    def test_failed_or_pending_status_is_not_completion(self):
        current, threads, recent = MODULE.load_fixture(FIXTURES / "green-check-stale-review.json")
        for status, state in (("PENDING", "pending"), ("FAILURE", "incomplete")):
            with self.subTest(status=status):
                current["statusCheckRollup"][0]["state"] = status
                result = MODULE.inspect(current, threads, recent, policy(), {})
                self.assertEqual(result["state"], state)
                self.assertEqual(result["completed_on_head"], [])
                self.assertEqual(result["stale_reviewers"], ["coderabbit"])

    def test_payload_snapshot_preserves_exact_response_and_cannot_overwrite(self):
        raw = ' { "headRefOid": "head", "comments": [] }\n'
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "payload.json"
            with mock.patch.object(MODULE.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, raw, "")):
                value = MODULE.fetch_pr("owner/repo", 1, snapshot)
                self.assertEqual(value, json.loads(raw))
                self.assertEqual(snapshot.read_text(), raw)
                with self.assertRaises(MODULE.InspectionError):
                    MODULE.fetch_pr("owner/repo", 1, snapshot)
                self.assertEqual(snapshot.read_text(), raw)

    def test_dependency_failure_is_not_empty_success(self):
        with mock.patch.object(MODULE.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "permission denied")):
            with self.assertRaisesRegex(MODULE.InspectionError, "permission denied"):
                MODULE.fetch_pr("owner/repo", 1)

    def test_no_reviewer_is_not_applicable(self):
        result = inspect_fixture("no-reviewer.json")
        self.assertEqual(result["state"], "not_applicable")
        self.assertEqual(result["expected_reviewers"], [])

    def test_all_default_reviewers_clear_on_current_head(self):
        result = inspect_fixture("trusted-clear.json")
        self.assertEqual(result["state"], "clear")
        self.assertEqual(result["expected_reviewers"], ["coderabbit", "github-copilot", "kilo"])
        self.assertEqual(result["pending_reviewers"], [])

    def test_copilot_comment_requires_triage(self):
        result = inspect_fixture("copilot-unresolved.json")
        self.assertEqual(result["state"], "pending")
        self.assertEqual(result["untriaged_findings"][0]["id"], "copilot-finding-1")
        self.assertIn("github-copilot", result["pending_reviewers"])

    def test_active_finding_body_is_bounded(self):
        current, threads, recent = MODULE.load_fixture(FIXTURES / "copilot-unresolved.json")
        result = MODULE.inspect(current, threads, recent, policy(), {}, max_body_chars=20)
        body = result["findings"][0]["body"]
        self.assertEqual(len(body), 20)
        self.assertTrue(body.endswith("…"))

    def test_copilot_author_login_without_bot_suffix_is_trusted(self):
        current, threads, recent = MODULE.load_fixture(FIXTURES / "no-reviewer.json")
        current["reviews"] = [
            {
                "id": "copilot-review",
                "author": {"login": "copilot-pull-request-reviewer"},
                "state": "COMMENTED",
                "submittedAt": "2026-09-08T12:00:00Z",
                "commit": {"oid": "head-10"},
            }
        ]
        result = MODULE.inspect(current, threads, recent, policy(), {})
        self.assertEqual(result["state"], "clear")
        self.assertEqual(result["observed_reviewers"], ["github-copilot"])

    def test_advisory_and_blocking_dispositions(self):
        advisory = inspect_fixture(
            "copilot-unresolved.json", dispositions={"copilot-finding-1": "advisory"}
        )
        self.assertEqual(advisory["state"], "clear")
        blocking = inspect_fixture(
            "copilot-unresolved.json", dispositions={"copilot-finding-1": "blocking"}
        )
        self.assertEqual(blocking["state"], "blocking")
        self.assertEqual(blocking["blocking_findings"][0]["reviewer"], "github-copilot")

    def test_false_positive_clears_with_recorded_disposition(self):
        result = inspect_fixture(
            "copilot-unresolved.json", dispositions={"copilot-finding-1": "false_positive"}
        )
        self.assertEqual(result["state"], "clear")

    def test_stale_copilot_review_is_pending(self):
        result = inspect_fixture("copilot-stale.json")
        self.assertEqual(result["state"], "pending")
        self.assertEqual(result["stale_reviewers"], ["github-copilot"])

    def test_current_review_supersedes_older_review_from_same_reviewer(self):
        current, threads, recent = MODULE.load_fixture(FIXTURES / "no-reviewer.json")
        current["reviews"] = [
            {"id": "old", "state": "COMMENTED", "author": {"login": "kilocode-bot"}, "submittedAt": "2026-09-08T11:00:00Z", "commit": {"oid": "old-head"}},
            {"id": "new", "state": "COMMENTED", "author": {"login": "kilocode-bot"}, "submittedAt": "2026-09-08T12:00:00Z", "commit": {"oid": "head-10"}},
        ]
        result = MODULE.inspect(current, threads, recent, policy(), {})
        self.assertEqual(result["state"], "clear")
        self.assertEqual(result["stale_reviewers"], [])

    def test_recent_pr_evidence_marks_reviewer_expected(self):
        result = inspect_fixture("recent-coderabbit.json")
        self.assertEqual(result["state"], "pending")
        self.assertEqual(result["recently_observed_reviewers"], ["coderabbit"])

    def test_required_and_ignored_precedence(self):
        required = inspect_fixture(
            "no-reviewer.json", review_policy=policy(required={"github-copilot"})
        )
        self.assertEqual(required["state"], "pending")
        ignored = inspect_fixture(
            "copilot-unresolved.json",
            review_policy=policy(required={"github-copilot"}, ignored={"github-copilot"}),
        )
        self.assertEqual(ignored["state"], "not_applicable")

    def test_failed_check_without_findings_is_incomplete(self):
        result = inspect_fixture("failed-check.json")
        self.assertEqual(result["state"], "incomplete")
        self.assertIn("without readable", result["errors"][0])

    def test_unknown_bot_is_reported_but_not_trusted(self):
        result = inspect_fixture("unknown-bot.json")
        self.assertEqual(result["state"], "not_applicable")
        self.assertEqual(result["unknown_bot_identities"], ["excellent-review-bot[bot]"])

    def test_ordinary_review_named_check_is_not_reported_as_bot(self):
        result = inspect_fixture("ordinary-review-check.json")
        self.assertEqual(result["state"], "not_applicable")
        self.assertEqual(result["unknown_bot_identities"], [])

    def test_fixture_pages_are_flattened(self):
        result = inspect_fixture("paginated-threads.json")
        self.assertEqual(result["state"], "clear")
        self.assertEqual(len(result["findings"]), 2)

    def test_custom_identity_is_detected(self):
        custom_policy = policy()
        custom_policy.identities["acme-review"] = {"acme-reviewer[bot]"}
        current, threads, recent = MODULE.load_fixture(FIXTURES / "no-reviewer.json")
        current["reviewRequests"] = [{"login": "acme-reviewer[bot]"}]
        result = MODULE.inspect(current, threads, recent, custom_policy, {})
        self.assertEqual(result["state"], "pending")
        self.assertIn("acme-review", result["expected_reviewers"])

    def test_kilo_hyphenated_bot_login_is_trusted(self):
        current, threads, recent = MODULE.load_fixture(FIXTURES / "no-reviewer.json")
        current["reviewRequests"] = [{"login": "kilo-code-bot"}]
        result = MODULE.inspect(current, threads, recent, policy(), {})
        self.assertEqual(result["state"], "pending")
        self.assertEqual(result["observed_reviewers"], ["kilo"])
        self.assertEqual(result["unknown_bot_identities"], [])

    def test_zero_recent_pr_limit_makes_no_github_request(self):
        with mock.patch.object(MODULE, "run_json") as run_json:
            self.assertEqual(MODULE.fetch_recent("owner/repo", 1, 0), [])
            run_json.assert_not_called()

    def test_cli_accepts_dispositions(self):
        with tempfile.TemporaryDirectory() as directory:
            dispositions = Path(directory) / "dispositions.json"
            dispositions.write_text(json.dumps({"copilot-finding-1": "advisory"}), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--fixture",
                    str(FIXTURES / "copilot-unresolved.json"),
                    "--dispositions",
                    str(dispositions),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["state"], "clear")

    def test_cli_trusted_reviewer_filter_overrides_defaults(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--fixture",
                str(FIXTURES / "trusted-clear.json"),
                "--trusted-reviewer",
                "github-copilot",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["state"], "clear")
        self.assertEqual(result["expected_reviewers"], ["github-copilot"])
        self.assertEqual(result["unknown_bot_identities"], [])

    def test_cli_rejects_required_reviewer_that_is_not_trusted(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--fixture",
                str(FIXTURES / "no-reviewer.json"),
                "--trusted-reviewer",
                "coderabbit",
                "--required-reviewer",
                "github-copilot",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(json.loads(completed.stdout)["state"], "incomplete")

    def test_additional_identity_also_matches_check_context(self):
        identities = {name: set(values) for name, values in MODULE.DEFAULT_IDENTITIES.items()}
        markers = {name: set(values) for name, values in MODULE.DEFAULT_CHECK_MARKERS.items()}
        MODULE.parse_identity("acme=acme-review-app", identities, markers)
        custom_policy = MODULE.ReviewerPolicy(
            identities=identities,
            check_markers=markers,
            required=set(),
            ignored=set(),
        )
        current, threads, recent = MODULE.load_fixture(FIXTURES / "no-reviewer.json")
        current["statusCheckRollup"] = [
            {"context": "acme-review-app", "state": "PENDING"}
        ]
        result = MODULE.inspect(current, threads, recent, custom_policy, {})
        self.assertEqual(result["state"], "pending")
        self.assertEqual(result["observed_reviewers"], ["acme"])

    def test_malformed_fixture_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "bad.json"
            fixture.write_text("not-json", encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--fixture", str(fixture)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(json.loads(completed.stdout)["state"], "incomplete")

    # Issue #82: new reviewer identities and the #117 Kilo summary path.
    # These tests pin the public surface — `DEFAULT_IDENTITIES`,
    # `DEFAULT_CHECK_MARKERS`, the `<!-- kilo-review -->` ordering rule,
    # the four Kilo fixture cases, the `github-actions[bot]` exclusion,
    # and the ask-once contract. They are deliberately split so a
    # regression in one path fails one named test rather than a
    # kitchen-sink "new reviewers work" assertion.

    def test_issue_82_default_identities_include_confirmed_reviewers(self):
        # Every confirmed login in the Issue #82 table must map to a
        # built-in reviewer. Adding a reviewer without a confirmed
        # login is a defect, and the test names the expected pair so a
        # renamed login fails loudly.
        expected = {
            "gemini-code-assist": {"gemini-code-assist", "gemini-code-assist[bot]"},
            "greptile": {"greptile-apps", "greptile-apps[bot]"},
            "sourcery": {"sourcery-ai", "sourcery-ai[bot]"},
            "qodo": {
                "qodo-code-review",
                "qodo-code-review[bot]",
                "qodo-free-for-open-source-projects",
                "qodo-free-for-open-source-projects[bot]",
            },
        }
        for reviewer, logins in expected.items():
            with self.subTest(reviewer=reviewer):
                self.assertIn(reviewer, MODULE.DEFAULT_IDENTITIES)
                self.assertEqual(MODULE.DEFAULT_IDENTITIES[reviewer], logins)

    def test_issue_82_github_actions_bot_is_not_a_default_reviewer(self):
        # `github-actions[bot]` is shared by every workflow and is not a
        # stable identity, so it must not appear in `DEFAULT_IDENTITIES`
        # for any reviewer. A workflow that wants to be trusted installs
        # a dedicated bot account and is added per-repo under
        # `Additional reviewer identities`.
        all_logins = {
            login
            for logins in MODULE.DEFAULT_IDENTITIES.values()
            for login in logins
        }
        self.assertNotIn("github-actions", all_logins)
        self.assertNotIn("github-actions[bot]", all_logins)

    def test_issue_82_each_new_reviewer_login_is_trusted(self):
        # Round-trip each new login through the policy. This is the
        # call site a real `--identity` block would exercise, so a
        # typo in a login fails here rather than at the next PR.
        for reviewer, logins in (
            ("gemini-code-assist", ["gemini-code-assist", "gemini-code-assist[bot]"]),
            ("greptile", ["greptile-apps", "greptile-apps[bot]"]),
            ("sourcery", ["sourcery-ai", "sourcery-ai[bot]"]),
            (
                "qodo",
                [
                    "qodo-code-review",
                    "qodo-code-review[bot]",
                    "qodo-free-for-open-source-projects",
                    "qodo-free-for-open-source-projects[bot]",
                ],
            ),
        ):
            for login in logins:
                with self.subTest(reviewer=reviewer, login=login):
                    current, threads, recent = MODULE.load_fixture(
                        FIXTURES / "no-reviewer.json"
                    )
                    current["reviewRequests"] = [{"login": login}]
                    result = MODULE.inspect(current, threads, recent, policy(), {})
                    self.assertEqual(result["state"], "pending")
                    self.assertEqual(result["observed_reviewers"], [reviewer])
                    self.assertEqual(result["unknown_bot_identities"], [])

    def test_issue_82_new_check_markers_route_to_their_reviewer(self):
        # Each verified check marker must route a CheckRun to the
        # matching reviewer key, so a real check on a PR is mapped to
        # the right name in `observed_reviewers` and the right verdict
        # in the gate. The markers are the only thing that
        # distinguishes two reviewers that both ship a CheckRun under
        # similar names. Only reviewers with a verified producing
        # check are tested here: Greptile (verified on
        # b-editor/beutl#3095, app slug `greptile-apps`, check name
        # "Greptile Review") and Sourcery (verified on
        # linuxdeepin/dde-daemon#1280, app slug `sourcery-ai`, check
        # name "Sourcery review"). Gemini and Qodo have no verified
        # producing check; their markers are deliberately absent
        # from `DEFAULT_CHECK_MARKERS`, and a check that names
        # either must be reported, not auto-routed.
        for reviewer, marker in (
            ("greptile", "Greptile Review"),
            ("sourcery", "Sourcery review"),
        ):
            with self.subTest(reviewer=reviewer, marker=marker):
                current, threads, recent = MODULE.load_fixture(
                    FIXTURES / "no-reviewer.json"
                )
                current["statusCheckRollup"] = [{"name": marker, "state": "PENDING"}]
                result = MODULE.inspect(current, threads, recent, policy(), {})
                self.assertEqual(result["observed_reviewers"], [reviewer])

    def test_issue_82_gemini_and_qodo_check_markers_are_not_added(self):
        # Gemini and Qodo have no verified producing check. Their
        # apps grant `checks: read` only, so a check that names
        # either must NOT auto-route to a reviewer. The login is
        # trusted (PR comments are a known signal), but the check
        # marker is deliberately absent: a future vendor that
        # publishes a check must add a marker with evidence, not
        # borrow one.
        for marker in (
            "Gemini Code Assist",
            "Gemini Code Assist Review",
            "Qodo Code Review",
            "Qodo",
        ):
            with self.subTest(marker=marker):
                current, threads, recent = MODULE.load_fixture(
                    FIXTURES / "no-reviewer.json"
                )
                current["statusCheckRollup"] = [{"name": marker, "state": "PENDING"}]
                result = MODULE.inspect(current, threads, recent, policy(), {})
                self.assertEqual(result["observed_reviewers"], [])
                self.assertNotIn("gemini-code-assist", result["observed_reviewers"])
                self.assertNotIn("qodo", result["observed_reviewers"])

    def test_issue_82_rate_limit_breakpoint_against_new_reviewer(self):
        # #48: the rate-limit breakpoint is reviewer-agnostic, so it
        # must fire the same way against a newly added reviewer. We
        # model Greptile here because Issue #82 names it as the
        # representative case for "published check, real rate limit".
        # The check fails; the inspector surfaces the failure with a
        # distinct reason, and the reviewer is marked pending, not
        # completed — so the lead can route to the breakpoint or the
        # retry path without reading the generic
        # "trusted review check failed" error.
        current, threads, recent = MODULE.load_fixture(FIXTURES / "no-reviewer.json")
        current["statusCheckRollup"] = [
            {
                "name": "Greptile",
                "status": "COMPLETED",
                "conclusion": "FAILURE",
                "description": "Greptile review failed: Assistant request was rate limited.",
                "app": {"slug": "greptile-apps"},
            }
        ]
        custom_policy = policy(required={"greptile"})
        result = MODULE.inspect(current, threads, recent, custom_policy, {})
        self.assertEqual(result["state"], "pending")
        self.assertIn("greptile", result["pending_reviewers"])
        # The rate-limit reason names the reviewer, not the generic
        # "trusted review check failed without readable current-head
        # findings" message. That message is the inspector's own error
        # list, not a pending reason.
        reasons = result["pending_reasons"]["greptile"]
        self.assertTrue(
            any("rate-limit" in reason for reason in reasons),
            f"no rate-limit reason for greptile: {reasons}",
        )
        self.assertFalse(result["errors"])

    def test_issue_82_m3_success_check_mentioning_rate_limit_clears(self):
        # M3 (QA round 1): a SUCCESS Kilo check whose description
        # mentions a past rate-limit (e.g. "previous attempt was rate
        # limited; this run retried") must NOT be misclassified as a
        # rate-limit failure. The current run is a clear verdict, and
        # vendor retry history is not actionable infrastructure
        # evidence. The QA probe `s8` exercises this case.
        current, threads, recent = MODULE.load_fixture(
            FIXTURES / "kilo-summary-clear-at-head.json"
        )
        current["statusCheckRollup"][0]["description"] = (
            "Code review completed successfully "
            "(previous attempt was rate limited; this run retried)"
        )
        result = MODULE.inspect(current, threads, recent, policy(), {})
        self.assertEqual(result["state"], "clear", result)
        self.assertEqual(result["completed_on_head"], ["kilo"])
        self.assertFalse(result["errors"])

    def test_issue_82_m3_failed_check_with_rate_limit_is_rate_limited(self):
        # M3 positive: a FAILED Kilo check whose output names a
        # rate-limit is the rate-limit signal the #48 breakpoint
        # counts. This is the existing kilo-rate-limited-failed-check
        # behavior; the M3 fix is that SUCCESS no longer
        # misclassifies. A FAILED check must still trip the rate-
        # limit path.
        result = inspect_fixture("kilo-rate-limited-failed-check.json")
        self.assertEqual(result["state"], "pending", result)
        self.assertIn("kilo", result["pending_reviewers"])
        reasons = result["pending_reasons"]["kilo"]
        self.assertTrue(
            any("rate-limit" in reason for reason in reasons),
            f"no rate-limit reason: {reasons}",
        )

    def test_issue_82_n2_fetch_path_supplies_updated_at(self):
        # N2: the Kilo summary path consumes `updatedAt` to bind
        # an edited-in-place summary to the head's run. The
        # `gh pr view --json comments` shape does NOT carry
        # `updatedAt`, so the live path must fetch it from the
        # REST issues/comments endpoint and merge it in. This
        # test asserts the fetch path supplies `updatedAt` and
        # that it is the value the inspector uses.
        captured: list[list[str]] = []
        rest_payload = [
            {
                "id": 6157807446,
                "node_id": "IC_kwDOUEhYLs8AAAABbwivVg",
                "created_at": "2026-10-14T00:03:43Z",
                "updated_at": "2026-10-14T00:26:26Z",
            }
        ]

        def fake_run_json(command, **kwargs):
            captured.append(list(command))
            return rest_payload

        with mock.patch.object(MODULE, "run_json", side_effect=fake_run_json):
            metadata = MODULE.fetch_pr_comments_with_metadata(
                "owner/repo", 118
            )
        # The mapping is keyed by both `id` and `node_id` so the
        # caller can match a `gh pr view` comment by either.
        self.assertIn("6157807446", metadata)
        self.assertIn("IC_kwDOUEhYLs8AAAABbwivVg", metadata)
        record = metadata["6157807446"]
        self.assertEqual(record["createdAt"], "2026-10-14T00:03:43Z")
        self.assertEqual(record["updatedAt"], "2026-10-14T00:26:26Z")
        # Transport contract: the call must use GET with the
        # issues/comments endpoint and `--paginate`.
        argv = captured[0]
        self.assertIn("--method", argv, argv)
        method_idx = argv.index("--method")
        self.assertEqual(argv[method_idx + 1], "GET", argv)
        self.assertIn("issues/118/comments", " ".join(argv), argv)
        self.assertIn("--paginate", argv, argv)

    def test_issue_82_n2_augment_merges_metadata_into_comments(self):
        # N2 integration: `augment_comments_with_metadata` merges
        # REST timestamps into the gh-shaped comments and records
        # a provenance block under `_restMeta`. The gh `createdAt`
        # is preserved as a fallback; the REST `updatedAt` is
        # populated where gh had none.
        current = {
            "comments": [
                {
                    "id": "IC_kwDOUEhYLs8AAAABbwivVg",
                    "author": {"login": "kilo-code-bot"},
                    "createdAt": "2026-10-14T00:03:43Z",
                }
            ]
        }

        def fake_run_json(command, **kwargs):
            return [
                {
                    "id": 6157807446,
                    "node_id": "IC_kwDOUEhYLs8AAAABbwivVg",
                    "created_at": "2026-10-14T00:03:43Z",
                    "updated_at": "2026-10-14T00:26:26Z",
                    # F1: body must be present so the record can
                    # be paired. A record without body is marked
                    # incoherent and not used as evidence.
                    "body": "<!-- kilo-review -->\n**Status:** No Issues Found | **Recommendation:** Merge\n",
                }
            ]

        with mock.patch.object(MODULE, "run_json", side_effect=fake_run_json):
            result = MODULE.augment_comments_with_metadata(
                current, "owner/repo", 118
            )
        comment = result["comments"][0]
        self.assertEqual(comment["updatedAt"], "2026-10-14T00:26:26Z")
        self.assertEqual(comment["createdAt"], "2026-10-14T00:03:43Z")
        # Provenance is recorded so a test or a follow-up reader
        # can see which values came from REST.
        self.assertEqual(
            comment["_restMeta"]["updated_at"], "2026-10-14T00:26:26Z"
        )
        self.assertEqual(
            comment["_restMeta"]["created_at"], "2026-10-14T00:03:43Z"
        )
        self.assertIn("issues/118/comments", comment["_restMeta"]["source"])

    def test_issue_82_n2_fallback_when_rest_fails(self):
        # N2 fail-closed: a REST failure leaves the gh values
        # intact. The edited-in-place case (where gh lacks
        # `updatedAt`) then fails closed to `pending`, matching
        # the B1 invariant.
        current = {
            "comments": [
                {
                    "id": "IC_kwDOUEhYLs8AAAABbwivVg",
                    "createdAt": "2026-10-14T00:03:43Z",
                }
            ]
        }

        def fake_run_json(command, **kwargs):
            raise MODULE.InspectionError("network down")

        with mock.patch.object(MODULE, "run_json", side_effect=fake_run_json):
            result = MODULE.augment_comments_with_metadata(
                current, "owner/repo", 118
            )
        # No REST metadata is recorded; the gh `createdAt`
        # remains and `updatedAt` is absent.
        self.assertNotIn("updatedAt", result["comments"][0])
        self.assertNotIn("_restMeta", result["comments"][0])

    def test_f1_rest_edit_metadata_promotes_coherent_body_only(self):
        # F1 (Codex round-3): if Kilo edits the comment in place
        # between the `gh pr view` read and the REST read, the
        # inspector must bind the NEW body to the NEW edit time —
        # never the OLD body to the NEW time. The gh comment has
        # an old "No Issues Found | Merge" body; the REST record
        # for the same id carries a new "Issues Found | Request
        # Changes" body and a fresh `updated_at`. Production
        # enrichment must use the REST body + REST timestamps
        # together, so the verdict is `pending` (untriaged),
        # not `clear`.
        current = {
            "number": 114,
            "headRefOid": "91e1cb4a71d1a1ee90b6b27e36d27c0dac1b96f8",
            "reviewRequests": [],
            "reviews": [],
            "latestReviews": [],
            "statusCheckRollup": [
                {
                    "id": 200,
                    "name": "Kilo Code Review",
                    "status": "COMPLETED",
                    "conclusion": "SUCCESS",
                    "startedAt": "2026-10-13T23:20:05Z",
                    "completedAt": "2026-10-13T23:25:48Z",
                    "app": None,
                }
            ],
            "comments": [
                {
                    "id": "IC_same-comment",
                    "author": {"login": "kilo-code-bot"},
                    "createdAt": "2025-01-01T00:00:00Z",
                    "body": (
                        "<!-- kilo-review -->\n"
                        "<!-- previous head summary -->\n"
                        "**Status:** No Issues Found | **Recommendation:** Merge\n"
                    ),
                }
            ],
        }
        rest_record = {
            "id": 42,
            "node_id": "IC_same-comment",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2026-10-13T23:25:50Z",
            "body": (
                "<!-- kilo-review -->\n"
                "**Status:** Issues Found | **Recommendation:** Request Changes\n"
            ),
            "user": {"login": "kilo-code-bot[bot]"},
        }

        def fake_run_json(command, **kwargs):
            return [rest_record]

        with mock.patch.object(MODULE, "run_json", side_effect=fake_run_json):
            MODULE.augment_comments_with_metadata(
                current, "KHAEntertainment/showrunner", 114
            )
        # F1: the comment body must be the REST body (Issues
        # Found), not the gh body (No Issues Found).
        self.assertIn("Issues Found", current["comments"][0]["body"])
        self.assertNotIn("No Issues Found", current["comments"][0]["body"])
        # F1: the timestamps come from the same REST record.
        self.assertEqual(current["comments"][0]["updatedAt"], "2026-10-13T23:25:50Z")
        # F1: the verdict is pending (untriaged), not clear.
        result = MODULE.inspect(current, [], [], policy(), {})
        self.assertEqual(result["state"], "pending", result)
        self.assertIn("kilo", result["completed_on_head"])
        self.assertEqual(len(result["untriaged_findings"]), 1)

    def test_f1_incomplete_rest_record_marks_comment_not_evidence(self):
        # F1 fail-closed: when the REST record cannot be paired
        # (missing body or missing timestamps), the comment is
        # marked `_incoherent` and the inspector treats it as
        # not evidence — the gate stays pending, never clear.
        current = {
            "number": 114,
            "headRefOid": "91e1cb4a71d1a1ee90b6b27e36d27c0dac1b96f8",
            "reviewRequests": [],
            "reviews": [],
            "latestReviews": [],
            "statusCheckRollup": [
                {
                    "id": 200,
                    "name": "Kilo Code Review",
                    "status": "COMPLETED",
                    "conclusion": "SUCCESS",
                    "startedAt": "2026-10-13T23:20:05Z",
                    "completedAt": "2026-10-13T23:25:48Z",
                    "app": None,
                }
            ],
            "comments": [
                {
                    "id": "IC_partial",
                    "author": {"login": "kilo-code-bot"},
                    "createdAt": "2026-10-13T23:25:34Z",
                    "body": (
                        "<!-- kilo-review -->\n"
                        "**Status:** No Issues Found | **Recommendation:** Merge\n"
                    ),
                }
            ],
        }
        # REST record has updated_at but NO body — cannot pair.
        rest_record = {
            "id": 43,
            "node_id": "IC_partial",
            "created_at": "2026-10-13T23:25:34Z",
            "updated_at": "2026-10-13T23:26:00Z",
            "body": None,
        }

        def fake_run_json(command, **kwargs):
            return [rest_record]

        with mock.patch.object(MODULE, "run_json", side_effect=fake_run_json):
            MODULE.augment_comments_with_metadata(
                current, "KHAEntertainment/showrunner", 114
            )
        # F1: the comment is marked incoherent.
        self.assertTrue(current["comments"][0].get("_incoherent"))
        # F1: the inspector treats it as not evidence.
        result = MODULE.inspect(current, [], [], policy(), {})
        self.assertEqual(result["state"], "pending", result)
        self.assertNotIn("kilo", result["completed_on_head"])
        self.assertIn("kilo", result["pending_reviewers"])

    def test_f2_rest_run_used_as_one_whole_record(self):
        # F2 (Codex round-3): when the gh rollup and REST
        # disagree (a new run was created between the two
        # reads), the selected latest REST run is used as one
        # WHOLE record — id, status, conclusion, started/
        # completed, output all from that run. Never
        # field-by-field merge. The reproduction: gh rollup has
        # an older SUCCESS; REST has a newer FAILURE with a
        # rate-limit output. The merged record must be the
        # FAILURE record entirely, so the inspector reports
        # `pending` with the rate-limit reason, not `clear`.
        current = {
            "number": 114,
            "headRefOid": "91e1cb4a71d1a1ee90b6b27e36d27c0dac1b96f8",
            "reviewRequests": [],
            "reviews": [],
            "latestReviews": [],
            "statusCheckRollup": [
                {
                    # gh rollup: older SUCCESS, no id, no output.
                    "name": "Kilo Code Review",
                    "status": "COMPLETED",
                    "conclusion": "SUCCESS",
                    "startedAt": "2026-10-13T23:20:05Z",
                    "completedAt": "2026-10-13T23:25:48Z",
                    "app": None,
                }
            ],
            "comments": [
                {
                    "id": "IC_kilo",
                    "author": {"login": "kilo-code-bot"},
                    "createdAt": "2026-10-13T23:25:34Z",
                    "body": (
                        "<!-- kilo-review -->\n"
                        "**Status:** No Issues Found | **Recommendation:** Merge\n"
                    ),
                }
            ],
        }
        # REST: newer FAILURE run with rate-limit output.
        latest_rest = {
            "id": 300,
            "name": "Kilo Code Review",
            "status": "completed",
            "conclusion": "failure",
            "started_at": "2026-10-13T23:30:00Z",
            "completed_at": "2026-10-13T23:35:00Z",
            "output": {"summary": "Assistant request was rate limited"},
        }

        def fake_run_json(command, **kwargs):
            return {"check_runs": [latest_rest]}

        with mock.patch.object(MODULE, "run_json", side_effect=fake_run_json):
            MODULE.augment_checks_with_output(current, "KHAEntertainment/showrunner")
        merged = current["statusCheckRollup"][0]
        # F2: the merged record is the REST record entirely —
        # not a hybrid of REST id/output with gh SUCCESS/times.
        self.assertEqual(merged["id"], 300)
        self.assertEqual(merged["conclusion"], "failure")
        self.assertEqual(merged["startedAt"], "2026-10-13T23:30:00Z")
        self.assertEqual(merged["completedAt"], "2026-10-13T23:35:00Z")
        self.assertEqual(
            merged["output"]["summary"], "Assistant request was rate limited"
        )
        # F2: the verdict is pending with the rate-limit reason,
        # not clear (which the buggy field-by-field merge gave).
        result = MODULE.inspect(current, [], [], policy(), {})
        self.assertEqual(result["state"], "pending", result)
        self.assertNotIn("kilo", result["completed_on_head"])
        reasons = result["pending_reasons"].get("kilo", [])
        self.assertTrue(
            any("rate-limit" in r for r in reasons),
            f"expected rate-limit reason, got: {reasons}",
        )

    def test_issue_82_qa_n1_latest_kilo_run_decides_success_then_failed(self):
        # QA-N1: when TWO Kilo check runs exist on the head SHA, the
        # LATEST (by `started_at` DESC with `id` DESC tie-break) is
        # the one that decides. Order 1: SUCCESS first, FAILED
        # second (i.e. the FAILED is newer). The FAILED run decides
        # and the older SUCCESS must NOT clear.
        current, threads, recent = MODULE.load_fixture(
            FIXTURES / "kilo-summary-clear-at-head.json"
        )
        # Two Kilo runs on the head. First is the older SUCCESS.
        current["statusCheckRollup"] = [
            {
                "id": 100,
                "name": "Kilo Code Review",
                "status": "COMPLETED",
                "conclusion": "SUCCESS",
                "startedAt": "2026-10-13T23:20:05Z",
                "completedAt": "2026-10-13T23:25:48Z",
                "app": None,
            },
            {
                "id": 200,
                "name": "Kilo Code Review",
                "status": "COMPLETED",
                "conclusion": "FAILURE",
                "startedAt": "2026-10-13T23:30:00Z",
                "completedAt": "2026-10-13T23:35:00Z",
                "app": None,
            },
        ]
        # The comment was created during the SUCCESS run, but the
        # FAILED run is now the latest. The comment is NOT bound to
        # the FAILED run's `startedAt`, so it does not clear.
        result = MODULE.inspect(current, threads, recent, policy(), {})
        self.assertEqual(result["state"], "pending", result)
        self.assertNotIn("kilo", result["completed_on_head"])
        # Both runs are consumed, so no generic check_failed error.
        self.assertEqual(result["errors"], [])

    def test_issue_82_qa_n1_latest_kilo_run_decides_failed_then_success(self):
        # QA-N1 order 2: FAILED first (older), SUCCESS second
        # (newer). The SUCCESS decides and the older FAILED must
        # NOT fall through to the generic `check_failed` path and
        # produce a self-contradictory `incomplete`.
        current, threads, recent = MODULE.load_fixture(
            FIXTURES / "kilo-summary-clear-at-head.json"
        )
        # The summary's `createdAt`/`updatedAt` must bind to the
        # NEWER (SUCCESS) run's `startedAt`. The older FAILED run
        # is consumed but must not gate.
        current["comments"][0]["createdAt"] = "2026-10-13T23:21:00Z"
        current["statusCheckRollup"] = [
            {
                "id": 100,
                "name": "Kilo Code Review",
                "status": "COMPLETED",
                "conclusion": "FAILURE",
                "startedAt": "2026-10-13T22:48:19Z",
                "completedAt": "2026-10-13T22:59:16Z",
                "app": None,
                "output": {
                    "title": "Kilo Code Review failed",
                    "summary": "Review failed: Assistant request was rate limited",
                },
            },
            {
                "id": 200,
                "name": "Kilo Code Review",
                "status": "COMPLETED",
                "conclusion": "SUCCESS",
                "startedAt": "2026-10-13T23:20:05Z",
                "completedAt": "2026-10-13T23:25:48Z",
                "app": None,
            },
        ]
        result = MODULE.inspect(current, threads, recent, policy(), {})
        # The latest run is SUCCESS, the comment is bound to it
        # (createdAt 23:21:00 >= startedAt 23:20:05), so the
        # verdict is `clear`.
        self.assertEqual(result["state"], "clear", result)
        self.assertEqual(result["completed_on_head"], ["kilo"])
        # Both runs are consumed. The older FAILED run must NOT
        # produce a generic check_failed error.
        self.assertEqual(result["errors"], [])

    def test_issue_82_qa_n1_both_orders_consume_all_runs(self):
        # QA-N1 invariant: whichever order the Kilo runs appear
        # in the rollup, both are consumed (no generic error) and
        # the LATEST decides. The test flips the rollup order and
        # asserts the same result either way.
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                current, threads, recent = MODULE.load_fixture(
                    FIXTURES / "kilo-summary-clear-at-head.json"
                )
                current["comments"][0]["createdAt"] = "2026-10-13T23:21:00Z"
                runs = [
                    {
                        "id": 100,
                        "name": "Kilo Code Review",
                        "status": "COMPLETED",
                        "conclusion": "FAILURE",
                        "startedAt": "2026-10-13T22:48:19Z",
                        "completedAt": "2026-10-13T22:59:16Z",
                        "app": None,
                        "output": {
                            "title": "Kilo Code Review failed",
                            "summary": "Review failed: Assistant request was rate limited",
                        },
                    },
                    {
                        "id": 200,
                        "name": "Kilo Code Review",
                        "status": "COMPLETED",
                        "conclusion": "SUCCESS",
                        "startedAt": "2026-10-13T23:20:05Z",
                        "completedAt": "2026-10-13T23:25:48Z",
                        "app": None,
                    },
                ]
                current["statusCheckRollup"] = list(reversed(runs)) if reverse else runs
                result = MODULE.inspect(current, threads, recent, policy(), {})
                # Latest run is the SUCCESS (200) either way.
                self.assertEqual(result["state"], "clear", result)
                self.assertEqual(result["completed_on_head"], ["kilo"])
                self.assertEqual(result["errors"], [])

    def test_issue_82_n1_transport_contract_uses_get_method(self):
        # N1: the live REST call to fetch a check's `output` must
        # use `--method GET` with the `check_name` in the URL's
        # query string. `gh api` defaults to POST whenever
        # request parameters are supplied (via `-f`/`-F`), and a
        # POST to the check-runs endpoint would silently create
        # or mutate a check run. The test asserts the exact argv.
        # The listing also passes `filter=all` so older runs on
        # the same head are visible (the default `filter=latest`
        # hides them — QA-N1).
        captured: list[list[str]] = []

        def fake_run_json(command, **kwargs):
            captured.append(list(command))
            return {"id": 1, "name": "Kilo Code Review", "output": {"summary": "ok"}}

        with mock.patch.object(MODULE, "run_json", side_effect=fake_run_json):
            MODULE.fetch_check_output("owner/repo", "deadbeef", "Kilo Code Review")
        self.assertEqual(len(captured), 1)
        argv = captured[0]
        # Must contain `--method` and `GET` as separate argv entries.
        self.assertIn("--method", argv, argv)
        method_idx = argv.index("--method")
        self.assertEqual(argv[method_idx + 1], "GET", argv)
        # Must NOT use `-f` or `-F` for query parameters (that
        # would force POST).
        self.assertNotIn("-f", argv, argv)
        self.assertNotIn("-F", argv, argv)
        # The URL must carry the check_name and filter=all in its
        # query string, URL-encoded.
        url = next((a for a in argv if "check-runs" in a), "")
        self.assertIn("check_name=Kilo+Code+Review", url.replace("%20", "+"), argv)
        self.assertIn("filter=all", url, argv)

    def test_issue_82_n1_transport_contract_batch_uses_get_method(self):
        # N1 for the batch (A1) fetch: the same GET-method rule
        # applies to `fetch_check_outputs_for_head`. The endpoint
        # returns every run on the head SHA (filter=all) and we
        # filter to the names we care about locally.
        captured: list[list[str]] = []

        def fake_run_json(command, **kwargs):
            captured.append(list(command))
            return {"check_runs": []}

        with mock.patch.object(MODULE, "run_json", side_effect=fake_run_json):
            MODULE.fetch_check_outputs_for_head(
                "owner/repo", "deadbeef", {"Kilo Code Review"}
            )
        self.assertEqual(len(captured), 1)
        argv = captured[0]
        self.assertIn("--method", argv, argv)
        method_idx = argv.index("--method")
        self.assertEqual(argv[method_idx + 1], "GET", argv)
        self.assertNotIn("-f", argv, argv)
        self.assertNotIn("-F", argv, argv)
        url = next((a for a in argv if "check-runs" in a), "")
        self.assertIn("filter=all", url, argv)

    def test_issue_82_m3_unrelated_check_mentioning_rate_limit_does_not_route(self):
        # s7: a non-trusted check (here: github-actions unit
        # tests) whose output mentions a rate-limit phrase is not
        # part of the rate-limit signal. The `is_rate_limited_check`
        # gate is invoked only after `reviewer_for_check`
        # confirms the check is from a trusted reviewer, so a
        # github-actions check with "rate limit reached" in its
        # output stays out of the rate-limited reviewer set.
        current, threads, recent = MODULE.load_fixture(
            FIXTURES / "kilo-summary-clear-at-head.json"
        )
        current["statusCheckRollup"].append(
            {
                "name": "unit-tests",
                "app": {"slug": "github-actions"},
                "status": "COMPLETED",
                "conclusion": "FAILURE",
                "startedAt": "2026-10-14T05:00:00Z",
                "completedAt": "2026-10-14T05:06:00Z",
                "description": "3 tests failed",
                "output": {
                    "summary": (
                        "FAILED tests/test_backoff.py::test_retry\n"
                        "AssertionError: expected 'rate limit reached' "
                        "in log, got 'ok'\n"
                    )
                },
            }
        )
        result = MODULE.inspect(current, threads, recent, policy(), {})
        self.assertEqual(result["state"], "clear", result)
        self.assertEqual(result["completed_on_head"], ["kilo"])
        self.assertEqual(result["errors"], [])

    def test_issue_82_b5_rate_limited_reviewer_with_completed_review_is_pending(self):
        # B5: a current-head Greptile COMMENTED review PLUS a
        # failed rate-limited Greptile check must NOT clear. The
        # review is valid evidence, but the rate-limit is a
        # separate signal that the lead's retry or breakpoint path
        # must see. The state is `pending` with a rate-limit
        # reason; the completed review is still recorded in
        # `completed_on_head` for the lead's audit.
        current, threads, recent = MODULE.load_fixture(FIXTURES / "no-reviewer.json")
        current["reviews"] = [
            {
                "id": "greptile-review",
                "author": {"login": "greptile-apps[bot]"},
                "state": "COMMENTED",
                "submittedAt": "2026-10-13T23:24:00Z",
                "commit": {"oid": current["headRefOid"]},
            }
        ]
        current["statusCheckRollup"] = [
            {
                "name": "Greptile Review",
                "status": "COMPLETED",
                "conclusion": "FAILURE",
                "description": "Greptile review failed: Assistant request was rate limited.",
                "app": {"slug": "greptile-apps"},
            }
        ]
        custom_policy = policy(required={"greptile"})
        result = MODULE.inspect(current, threads, recent, custom_policy, {})
        # The state is `pending`, not `clear`. The rate-limit
        # reason overrides the completed review: the lead must
        # decide whether to retry or take the breakpoint.
        self.assertEqual(result["state"], "pending", result)
        self.assertIn("greptile", result["pending_reviewers"])
        # The completed review is still recorded so the lead's
        # audit trail sees both signals.
        self.assertIn("greptile", result["completed_on_head"])
        reasons = result["pending_reasons"]["greptile"]
        self.assertTrue(
            any("rate-limit" in reason for reason in reasons),
            f"no rate-limit reason for greptile: {reasons}",
        )
        self.assertFalse(result["errors"])

    def test_issue_82_unknown_bot_still_surfaced_not_trusted(self):
        # Unknown bots must remain evidence, not trust, even after the
        # default identity set widens. A future vendor that names
        # itself `super-review-bot[bot]` is surfaced in
        # `unknown_bot_identities` and never auto-routes to a reviewer.
        current, threads, recent = MODULE.load_fixture(FIXTURES / "no-reviewer.json")
        current["reviews"] = [
            {
                "id": "unknown-review",
                "author": {"login": "super-review-bot[bot]"},
                "state": "COMMENTED",
                "submittedAt": "2026-09-08T12:00:00Z",
                "commit": {"oid": "head-10"},
            }
        ]
        result = MODULE.inspect(current, threads, recent, policy(), {})
        self.assertEqual(result["state"], "not_applicable")
        self.assertEqual(result["unknown_bot_identities"], ["super-review-bot[bot]"])
        self.assertNotIn("super-review-bot", result["observed_reviewers"])

    def test_issue_117_kilo_summary_edited_in_place_fixture_clears(self):
        # PR #118 real shape: summary was created BEFORE the head's
        # Kilo run started (00:03:43Z) and edited in place DURING the
        # run (00:26:26Z, two seconds after the run completed at
        # 00:26:24Z). The `updatedAt` is the binding timestamp when
        # the comment was edited in place.
        result = inspect_fixture("kilo-summary-edited-in-place.json")
        self.assertEqual(result["state"], "clear", result)
        self.assertEqual(result["completed_on_head"], ["kilo"])
        self.assertEqual(result["errors"], [])

    def test_issue_117_kilo_summary_clear_at_head(self):
        # The PR #114 shape: Kilo check succeeded, summary comment
        # posted during the check run, status line `No Issues Found`.
        # Inspector routes as `clear` with Kilo in
        # `completed_on_head` — the exact case the Issue #117 scope
        # comment names as the acceptance criterion.
        result = inspect_fixture("kilo-summary-clear-at-head.json")
        self.assertEqual(result["state"], "clear", result)
        self.assertEqual(result["completed_on_head"], ["kilo"])
        self.assertEqual(result["pending_reviewers"], [])
        self.assertEqual(result["errors"], [])

    def test_issue_117_kilo_summary_stale_does_not_complete(self):
        # A Kilo summary from a previous run predates the Kilo check
        # for the current head SHA, and the Kilo check has not
        # completed. The summary is not promoted to a clear verdict;
        # Kilo is pending with a reason the lead can act on.
        result = inspect_fixture("kilo-summary-stale.json")
        self.assertEqual(result["state"], "pending", result)
        self.assertNotIn("kilo", result["completed_on_head"])
        self.assertIn("kilo", result["pending_reviewers"])
        self.assertEqual(result["errors"], [])

    def test_issue_117_kilo_summary_with_issues_is_untriaged(self):
        # B2+B3: a Kilo summary that names issues is NOT a clear
        # verdict (B2), but it IS review completion (B3) — Kilo
        # counts in `completed_on_head` regardless. The summary is
        # surfaced as an untriaged current-head finding the lead
        # can disposition through the existing `blocking` /
        # `advisory` / `false_positive` path. Until then the gate
        # is `pending` (untriaged).
        result = inspect_fixture("kilo-summary-with-issues.json")
        self.assertEqual(result["state"], "pending", result)
        # B3: the summary IS review completion, so Kilo is in
        # `completed_on_head` even though the gate is pending on
        # the untriaged finding.
        self.assertIn("kilo", result["completed_on_head"])
        self.assertEqual(len(result["untriaged_findings"]), 1)
        self.assertEqual(result["untriaged_findings"][0]["reviewer"], "kilo")

    def test_issue_117_kilo_rate_limited_check_has_distinct_pending_reason(self):
        # A failed Kilo check whose description names the rate-limit
        # phrase stays not-clear and is reported with a distinct
        # pending reason. The gate is `pending`, not `incomplete`,
        # because the rate-limit signal is known and the lead's retry
        # path is unambiguous.
        result = inspect_fixture("kilo-rate-limited-failed-check.json")
        self.assertEqual(result["state"], "pending", result)
        self.assertNotIn("kilo", result["completed_on_head"])
        self.assertIn("kilo", result["pending_reviewers"])
        reasons = result["pending_reasons"]["kilo"]
        self.assertTrue(
            any("rate-limit" in reason for reason in reasons),
            f"no rate-limit reason for kilo: {reasons}",
        )
        # The generic "trusted review check failed" error must not
        # appear; the rate-limit case has its own reason and the
        # state must be `pending`, not `incomplete`.
        self.assertFalse(
            any("trusted review check failed" in error for error in result["errors"]),
            result["errors"],
        )

    def test_issue_117_kilo_summary_completed_check_satisfies_ordering(self):
        # B1: the Kilo check COMPLETED with SUCCESS, and the comment
        # was posted during the run (`createdAt >= startedAt`). The
        # PR #114 shape — summary comment at 23:25:34Z, check
        # completed at 23:25:48Z.
        current, threads, recent = MODULE.load_fixture(
            FIXTURES / "kilo-summary-clear-at-head.json"
        )
        # Reorder: comment predates the check by a small margin.
        current["comments"][0]["createdAt"] = "2026-10-13T23:21:00Z"
        # Check started at 23:20:05 and completed at 23:25:48.
        result = MODULE.inspect(current, threads, recent, policy(), {})
        self.assertEqual(result["state"], "clear", result)
        self.assertEqual(result["completed_on_head"], ["kilo"])

    def test_issue_117_kilo_summary_edited_in_place_satisfies_ordering(self):
        # B1: the comment was UPDATED after the head's Kilo run
        # started (PR #118: summary created 00:03:43Z, updated
        # 00:26:26Z; head da0e3d0's run started 00:22:51Z and
        # completed 00:26:24Z). The `updatedAt` is the binding
        # timestamp when the comment was edited in place; the
        # original `createdAt` predates the run.
        current, threads, recent = MODULE.load_fixture(
            FIXTURES / "kilo-summary-clear-at-head.json"
        )
        current["comments"][0]["createdAt"] = "2026-10-14T00:03:43Z"
        current["comments"][0]["updatedAt"] = "2026-10-14T00:26:26Z"
        # Re-time the Kilo check to match PR #118's head da0e3d0
        # run, so `updatedAt >= startedAt` and the run succeeded.
        current["statusCheckRollup"][0]["startedAt"] = "2026-10-14T00:22:51Z"
        current["statusCheckRollup"][0]["completedAt"] = "2026-10-14T00:26:24Z"
        current["statusCheckRollup"][0]["conclusion"] = "SUCCESS"
        result = MODULE.inspect(current, threads, recent, policy(), {})
        self.assertEqual(result["state"], "clear", result)
        self.assertEqual(result["completed_on_head"], ["kilo"])

    def test_issue_117_old_summary_with_completed_head_check_does_not_clear(self):
        # B1 negative: a year-old summary comment is paired with a
        # newly-completed SUCCESS Kilo check. The old `createdAt`
        # predates the new head's `startedAt`, so the comment
        # cannot be bound to this run. The state must be `pending`
        # and Kilo must NOT be in `completed_on_head`, regardless
        # of the check's success.
        current, threads, recent = MODULE.load_fixture(
            FIXTURES / "kilo-summary-clear-at-head.json"
        )
        current["comments"][0]["createdAt"] = "2025-01-01T00:00:00Z"
        current["comments"][0]["updatedAt"] = None
        # Kilo check completes SUCCESS, but it is a different
        # head's run from the year-old comment.
        result = MODULE.inspect(current, threads, recent, policy(), {})
        self.assertEqual(result["state"], "pending", result)
        self.assertNotIn("kilo", result["completed_on_head"])
        self.assertIn("kilo", result["pending_reviewers"])

    def test_issue_117_failed_check_does_not_clear_summary(self):
        # B1 boundary: a Kilo check that COMPLETED with a non-
        # `success` conclusion (FAILURE, TIMED_OUT, NEUTRAL,
        # SKIPPED, etc.) does not license a clear summary, even
        # when the comment's `createdAt` is at or after the run's
        # `startedAt`. The previous implementation admitted any
        # non-empty `completedAt`.
        for conclusion in ("FAILURE", "TIMED_OUT", "NEUTRAL", "SKIPPED", "ACTION_REQUIRED"):
            with self.subTest(conclusion=conclusion):
                current, threads, recent = MODULE.load_fixture(
                    FIXTURES / "kilo-summary-clear-at-head.json"
                )
                current["statusCheckRollup"][0]["conclusion"] = conclusion
                result = MODULE.inspect(current, threads, recent, policy(), {})
                self.assertEqual(result["state"], "pending", result)
                self.assertNotIn("kilo", result["completed_on_head"])

    def test_issue_117_malformed_timestamp_does_not_clear(self):
        # B1 timestamp sub-finding: a comment whose `createdAt`
        # is malformed (e.g. `zzzz`) must not be allowed to
        # silently satisfy the ordering compare via a truthy
        # non-empty string. The parse_iso8601 gate fails closed,
        # so Kilo is pending and the gate is `pending`.
        current, threads, recent = MODULE.load_fixture(
            FIXTURES / "kilo-summary-clear-at-head.json"
        )
        current["comments"][0]["createdAt"] = "zzzz"
        current["comments"][0]["updatedAt"] = None
        result = MODULE.inspect(current, threads, recent, policy(), {})
        self.assertEqual(result["state"], "pending", result)
        self.assertNotIn("kilo", result["completed_on_head"])
        self.assertIn("kilo", result["pending_reviewers"])

    def test_issue_117_no_issues_found_with_request_changes_does_not_clear(self):
        # B2+B3: a summary with `Status: No Issues Found` but
        # `Recommendation: Request Changes` is NOT a clear verdict
        # (B2), but it IS review completion (B3) — Kilo counts in
        # `completed_on_head`. The summary is surfaced as an
        # untriaged current-head finding the lead must disposition.
        # Until then the gate is `pending` (untriaged).
        current, threads, recent = MODULE.load_fixture(
            FIXTURES / "kilo-summary-clear-at-head.json"
        )
        current["comments"][0]["body"] = current["comments"][0]["body"].replace(
            "Recommendation:** Merge", "Recommendation:** Request Changes"
        )
        result = MODULE.inspect(current, threads, recent, policy(), {})
        self.assertEqual(result["state"], "pending", result)
        # B3: the summary IS review completion, so Kilo is in
        # `completed_on_head` even though the gate is pending on
        # the untriaged finding.
        self.assertIn("kilo", result["completed_on_head"])
        self.assertEqual(len(result["untriaged_findings"]), 1)
        self.assertEqual(result["untriaged_findings"][0]["reviewer"], "kilo")

    def test_issue_117_summary_finding_can_be_dispositioned_as_blocking(self):
        # B3: a summary with findings IS review completion; the
        # finding's disposition then decides the gate exactly as
        # any reviewer's finding would:
        #   - blocking → gate is `blocking`;
        #   - advisory or false_positive on every finding → gate
        #     is `clear` when nothing else is open;
        #   - untriaged → gate is `pending`.
        current, threads, recent = MODULE.load_fixture(
            FIXTURES / "kilo-summary-with-issues.json"
        )
        for disposition, expected_state, expected_completed, expected_blocking in (
            ("blocking", "blocking", ["kilo"], 1),
            ("advisory", "clear", ["kilo"], 0),
            ("false_positive", "clear", ["kilo"], 0),
        ):
            with self.subTest(disposition=disposition):
                result = MODULE.inspect(
                    current,
                    threads,
                    recent,
                    policy(),
                    {"kilo-summary-issues": disposition},
                )
                self.assertEqual(result["state"], expected_state, result)
                self.assertEqual(result["completed_on_head"], expected_completed)
                self.assertEqual(len(result["blocking_findings"]), expected_blocking)
                self.assertEqual(result["untriaged_findings"], [])
                self.assertIn("kilo", result["observed_reviewers"])

    def test_issue_117_kilo_ignored_does_not_consume_summary(self):
        # When Kilo is in the `ignored` set, the summary path is a
        # no-op: no completion, no finding, no pending reason. A repo
        # that has explicitly turned Kilo off must not see Kilo
        # review evidence at all.
        result = inspect_fixture(
            "kilo-summary-clear-at-head.json",
            review_policy=policy(ignored={"kilo"}),
        )
        self.assertEqual(result["state"], "not_applicable")
        self.assertNotIn("kilo", result["observed_reviewers"])

    def test_issue_82_ask_once_contract_for_unknown_bot(self):
        # The ask-once contract: the inspector surfaces an unknown bot
        # in `unknown_bot_identities` and never silently trusts it.
        # The SOP-level "do not re-ask a recorded login" rule is
        # pinned by `phases/external-review.md` and by the
        # `test_ask_once_*` tests in `test_backend_contract.py`
        # (added in B6 fix round 1). Here we pin the inspector
        # side: the surface that drives the SOP exists and is
        # stable, and a previously-seen unknown bot is recorded
        # in `unknown_bot_identities` regardless of the comment
        # shape.
        current, threads, recent = MODULE.load_fixture(FIXTURES / "no-reviewer.json")
        current["comments"] = [
            {
                "id": "unknown-comment",
                "author": {"login": "brand-new-reviewer[bot]"},
                "body": "Looks good to me.",
                "url": "https://github.com/example/project/pull/21#issuecomment-2",
            }
        ]
        result = MODULE.inspect(current, threads, recent, policy(), {})
        self.assertEqual(result["state"], "not_applicable")
        self.assertEqual(
            result["unknown_bot_identities"], ["brand-new-reviewer[bot]"]
        )
        # The inspector must NOT promote the unknown bot to a
        # reviewer under any name, even if the comment is
        # submitted-shaped.
        self.assertNotIn("brand-new-reviewer", result["observed_reviewers"])


class VerdictRegressionTests(unittest.TestCase):
    def make(self, states):
        current, threads, recent = MODULE.load_fixture(FIXTURES / "green-check-no-review.json")
        current["statusCheckRollup"] = []
        current["reviews"] = [{"author":{"login":"coderabbitai"},"state":s,"commit":{"oid":"current-head"},"submittedAt":t} for s,t in states]
        return MODULE.inspect(current, threads, recent, policy(), {})
    def test_changes_requested_blocks(self): self.assertEqual(self.make([("CHANGES_REQUESTED","2026-09-08T20:00:00Z")])["state"], "blocking")
    def test_approved_clears(self): self.assertEqual(self.make([("APPROVED","2026-09-08T20:00:00Z")])["state"], "clear")
    def test_commented_clears(self): self.assertEqual(self.make([("COMMENTED","2026-09-08T20:00:00Z")])["state"], "clear")
    def test_dismissed_pending(self): self.assertEqual(self.make([("DISMISSED","2026-09-08T20:00:00Z")])["state"], "pending")
    def test_approval_after_rejection_clears(self): self.assertEqual(self.make([("CHANGES_REQUESTED","2026-09-08T19:00:00Z"),("APPROVED","2026-09-08T20:00:00Z")])["state"], "clear")
    def test_rejection_after_approval_blocks(self): self.assertEqual(self.make([("APPROVED","2026-09-08T19:00:00Z"),("CHANGES_REQUESTED","2026-09-08T20:00:00Z")])["state"], "blocking")
    def test_rejection_with_green_check_blocks(self):
        current, _, recent = MODULE.load_fixture(FIXTURES / "green-check-no-review.json")
        current["reviews"] = [{"author":{"login":"coderabbitai"},"state":"CHANGES_REQUESTED","commit":{"oid":"current-head"},"submittedAt":"2026-09-08T20:00:00Z"}]
        self.assertEqual(MODULE.inspect(current, [], recent, policy(), {})["state"], "blocking")
    def test_rejection_with_failing_check_stays_blocking_with_errors(self):
        current, _, recent = MODULE.load_fixture(FIXTURES / "green-check-no-review.json")
        current["reviews"] = [{"author":{"login":"coderabbitai"},"state":"CHANGES_REQUESTED","commit":{"oid":"current-head"},"submittedAt":"2026-09-08T20:00:00Z"}]
        current["statusCheckRollup"] = [{"name":"CodeRabbit","status":"failure","conclusion":"failure"}]
        result = MODULE.inspect(current, [], recent, policy(), {})
        self.assertEqual(result["state"], "blocking")
        self.assertTrue(result["errors"])

    def test_errors_without_rejection_stay_incomplete(self):
        current, _, recent = MODULE.load_fixture(FIXTURES / "green-check-no-review.json")
        current["statusCheckRollup"] = [{"name":"CodeRabbit","status":"failure","conclusion":"failure"}]
        result = MODULE.inspect(current, [], recent, policy(), {})
        self.assertEqual(result["state"], "incomplete")

    def head_review(self, state, submitted_at="__omit__"):
        """One submitted review at head, with submittedAt controllable per case."""
        current, _, recent = MODULE.load_fixture(FIXTURES / "green-check-no-review.json")
        current["statusCheckRollup"] = []
        review = {
            "author": {"login": "coderabbitai"},
            "state": state,
            "commit": {"oid": "current-head"},
        }
        if submitted_at != "__omit__":
            review["submittedAt"] = submitted_at
        current["reviews"] = [review]
        return MODULE.inspect(current, [], recent, policy(), {})

    def assert_unorderable(self, result):
        """A review with no usable timestamp never establishes completion."""
        self.assertNotEqual(result["state"], "clear")
        self.assertNotIn("coderabbit", result["completed_on_head"])
        self.assertIn(
            "submittedAt",
            " ".join(result["pending_reasons"].get("coderabbit", [])),
        )

    def test_approval_at_head_with_valid_timestamp_still_clears(self):
        result = self.head_review("APPROVED", "2026-09-08T20:00:00Z")
        self.assertEqual(result["state"], "clear")
        self.assertEqual(result["completed_on_head"], ["coderabbit"])

    def test_approval_at_head_with_missing_timestamp_is_not_completion(self):
        self.assert_unorderable(self.head_review("APPROVED"))

    def test_approval_at_head_with_null_timestamp_is_not_completion(self):
        self.assert_unorderable(self.head_review("APPROVED", None))

    def test_approval_at_head_with_empty_timestamp_is_not_completion(self):
        self.assert_unorderable(self.head_review("APPROVED", ""))

    def test_approval_at_head_with_blank_timestamp_is_not_completion(self):
        self.assert_unorderable(self.head_review("APPROVED", "   "))

    def test_comment_at_head_with_missing_timestamp_is_not_completion(self):
        self.assert_unorderable(self.head_review("COMMENTED"))

    def test_rejection_at_head_with_missing_timestamp_still_blocks(self):
        # Fail closed both ways: an unorderable verdict cannot clear the gate,
        # and it cannot soften a rejection we already read either.
        result = self.head_review("CHANGES_REQUESTED")
        self.assertEqual(result["state"], "blocking")
        self.assertEqual(result["blocking_reviewers"], ["coderabbit"])

    def test_untimestamped_approval_cannot_override_earlier_rejection(self):
        current, _, recent = MODULE.load_fixture(FIXTURES / "green-check-no-review.json")
        current["statusCheckRollup"] = []
        current["reviews"] = [
            {"author":{"login":"coderabbitai"},"state":"CHANGES_REQUESTED","commit":{"oid":"current-head"},"submittedAt":"2026-09-08T19:00:00Z"},
            {"author":{"login":"coderabbitai"},"state":"APPROVED","commit":{"oid":"current-head"}},
        ]
        result = MODULE.inspect(current, [], recent, policy(), {})
        self.assertEqual(result["state"], "blocking")
        self.assertEqual(result["blocking_reviewers"], ["coderabbit"])

    def stale_review(self, state):
        """One submitted review at an earlier head."""
        current, _, recent = MODULE.load_fixture(FIXTURES / "green-check-no-review.json")
        current["statusCheckRollup"] = []
        current["reviews"] = [{
            "author": {"login": "coderabbitai"},
            "state": state,
            "submittedAt": "2026-09-08T12:00:00Z",
            "commit": {"oid": "old-head"},
        }]
        result = MODULE.inspect(current, [], recent, policy(), {})
        return result, " ".join(result["pending_reasons"]["coderabbit"])

    def test_stale_rejection_reason_names_the_rejection(self):
        result, reasons = self.stale_review("CHANGES_REQUESTED")
        self.assertEqual(result["state"], "pending")
        self.assertIn("submitted review at an earlier head requested changes", reasons)

    def test_stale_approval_reason_names_the_approval(self):
        result, reasons = self.stale_review("APPROVED")
        self.assertEqual(result["state"], "pending")
        self.assertIn("submitted review at an earlier head approved", reasons)

    def test_stale_rejection_and_approval_read_differently(self):
        # Issue #29: these were byte-identical, so a lead recording a bypass
        # could not say which kind of stale review they were waiving.
        _, rejection = self.stale_review("CHANGES_REQUESTED")
        _, approval = self.stale_review("APPROVED")
        self.assertNotEqual(rejection, approval)

    def test_stale_verdicts_do_not_change_merge_behaviour(self):
        # Reporting only: both stay pending, exactly as before.
        rejection, _ = self.stale_review("CHANGES_REQUESTED")
        approval, _ = self.stale_review("APPROVED")
        self.assertEqual(rejection["state"], "pending")
        self.assertEqual(approval["state"], "pending")
        self.assertEqual(rejection["stale_reviewers"], ["coderabbit"])
        self.assertEqual(approval["stale_reviewers"], ["coderabbit"])

    def test_stale_comment_reason_names_the_comment(self):
        _, reasons = self.stale_review("COMMENTED")
        self.assertIn("submitted review at an earlier head commented", reasons)

    def test_older_rejection_is_pending(self):
        current, threads, recent = MODULE.load_fixture(FIXTURES / "green-check-no-review.json")
        current["statusCheckRollup"] = []
        current["reviews"] = [{"author":{"login":"coderabbitai"},"state":"CHANGES_REQUESTED","commit":{"oid":"old-head"}}]
        self.assertEqual(MODULE.inspect(current, threads, recent, policy(), {})["state"], "pending")


class LiveFetchThreadsTests(unittest.TestCase):
    """fetch_threads() is the one path a fully green suite never touched
    (Issue #25): every test above reaches inspect() through load_fixture()
    and never calls fetch_threads at all, so replacing it with `return []`
    left every test green. These exercise it directly against a stubbed
    run_json -- no network access -- so the #23 guards (nested pagination,
    the comment `state` field) cannot be silently removed again unnoticed.
    """

    def query_from(self, command):
        for index, token in enumerate(command):
            if token == "-f" and index + 1 < len(command) and command[index + 1].startswith("query="):
                return command[index + 1][len("query="):]
        raise AssertionError(f"no query= argument found in {command}")

    def test_fetch_threads_paginates_across_outer_thread_pages(self):
        # Two outer pages of review threads. Replacing fetch_threads with
        # `return []`, or dropping the outer pageInfo.hasNextPage loop,
        # would return zero or one thread instead of two.
        page_one = {
            "data": {"repository": {"pullRequest": {"reviewThreads": {
                "nodes": [{"id": "thread-1", "comments": {"nodes": [], "pageInfo": {"hasNextPage": False}}}],
                "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
            }}}}
        }
        page_two = {
            "data": {"repository": {"pullRequest": {"reviewThreads": {
                "nodes": [{"id": "thread-2", "comments": {"nodes": [], "pageInfo": {"hasNextPage": False}}}],
                "pageInfo": {"hasNextPage": False, "endCursor": ""},
            }}}}
        }
        responses = [page_one, page_two]
        calls = []

        def fake_run_json(command, **kwargs):
            calls.append(command)
            return responses.pop(0)

        with mock.patch.object(MODULE, "run_json", side_effect=fake_run_json):
            threads = MODULE.fetch_threads("owner/repo", 7)

        self.assertEqual([thread["id"] for thread in threads], ["thread-1", "thread-2"])
        self.assertEqual(len(calls), 2)
        self.assertIn("cursor=cursor-1", calls[1])

    def test_fetch_threads_query_selects_state_and_nested_page_guard_fields(self):
        response = {
            "data": {"repository": {"pullRequest": {"reviewThreads": {
                "nodes": [],
                "pageInfo": {"hasNextPage": False, "endCursor": ""},
            }}}}
        }
        captured = {}

        def fake_run_json(command, **kwargs):
            captured["command"] = command
            return response

        with mock.patch.object(MODULE, "run_json", side_effect=fake_run_json):
            MODULE.fetch_threads("owner/repo", 7)

        query = self.query_from(captured["command"])
        block = comments_selection_block(query)
        tokens = block.split()
        self.assertIn("state", tokens, block)
        self.assertIn("pageInfo{hasNextPage}", tokens, block)

    def test_fetch_threads_raises_when_nested_comment_page_is_full(self):
        response = {
            "data": {"repository": {"pullRequest": {"reviewThreads": {
                "nodes": [{
                    "id": "thread-full",
                    "comments": {
                        "nodes": [{"id": f"c{i}"} for i in range(100)],
                        "pageInfo": {"hasNextPage": True},
                    },
                }],
                "pageInfo": {"hasNextPage": False, "endCursor": ""},
            }}}}
        }
        with mock.patch.object(MODULE, "run_json", return_value=response):
            with self.assertRaisesRegex(MODULE.InspectionError, "exceed the fetched page"):
                MODULE.fetch_threads("owner/repo", 7)

    def test_fetch_threads_comment_state_reaches_submitted_state_gate(self):
        def comment(state):
            return {
                "id": "c1", "body": "finding", "url": "https://example/pr/7#c1",
                "state": state, "author": {"login": "coderabbitai"},
                "commit": {"oid": "head-sha"},
            }

        def response_for(state):
            return {
                "data": {"repository": {"pullRequest": {"reviewThreads": {
                    "nodes": [{
                        "id": "thread-1", "isResolved": False, "isOutdated": False,
                        "comments": {"nodes": [comment(state)], "pageInfo": {"hasNextPage": False}},
                    }],
                    "pageInfo": {"hasNextPage": False, "endCursor": ""},
                }}}}
            }

        current = {
            "number": 7, "headRefOid": "head-sha", "reviews": [], "comments": [],
            "reviewRequests": [], "statusCheckRollup": [],
        }

        with mock.patch.object(MODULE, "run_json", return_value=response_for("SUBMITTED")):
            submitted_threads = MODULE.fetch_threads("owner/repo", 7)
        submitted_result = MODULE.inspect(current, submitted_threads, [], policy(), {"thread-1": "advisory"})
        self.assertEqual(submitted_result["completed_on_head"], ["coderabbit"])
        self.assertEqual(submitted_result["state"], "clear")

        with mock.patch.object(MODULE, "run_json", return_value=response_for("PENDING")):
            pending_threads = MODULE.fetch_threads("owner/repo", 7)
        pending_result = MODULE.inspect(current, pending_threads, [], policy(), {"thread-1": "advisory"})
        self.assertEqual(pending_result["completed_on_head"], [])
        self.assertEqual(pending_result["state"], "pending")


if __name__ == "__main__":
    unittest.main()
