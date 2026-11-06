"""Focused checks for #193 lane L1: the goal-run normalizer, D3 run bounds and
G2 turn-end markers.

One named test per acceptance criterion (AC1-AC8). SC-1 fixtures under
docs/v2.2/contracts/fixtures/sc-1/ are consumed read-only; the two non-conforming
fixtures (rejected-bare-ambiguous-issue-id.json and rejected-missing-managed-source.json)
are replaced by conforming equivalents under tests/fixtures/goal/.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "skills" / "dev" / "scripts" / "goal_run.py"
SC1_FIXTURES = ROOT / "docs" / "v2.2" / "contracts" / "fixtures" / "sc-1"
GOAL_FIXTURES = ROOT / "tests" / "fixtures" / "goal"

_SHA_A = "sha256:1111111111111111111111111111111111111111111111111111111111111111"
_SHA_B = "sha256:2222222222222222222222222222222222222222222222222222222222222222"
_SHA_E = "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"

_REPO = "OWNER/synthetic-repo"
_ISSUE_1 = "OWNER/synthetic-repo#1"
_ISSUE_2 = "OWNER/synthetic-repo#2"


def _load_module():
    spec = importlib.util.spec_from_file_location("goal_run", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gr = _load_module()


def _lead(agent_id="synthetic-agent-001"):
    return {"agent_id": agent_id, "harness": "opencode", "model": "deepseek:deepseek-v4-pro"}


def _plan_ref(approved=_SHA_B, origin="docs/plans/2099-01-01-synthetic-plan.md"):
    return {
        "origin": origin,
        "source_revision": _SHA_A,
        "approved_revision": approved,
        "approval": {
            "authority": _lead("synthetic-owner"),
            "evidence": {
                "reference": "OWNER/synthetic-repo@0123456789abcdef0123456789abcdef01234567",
                "digest": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
            },
        },
        "producer": {"session": "synthetic-session-001", "harness": "opencode"},
    }


def _entry(kind="plan", mode="standalone", fixed_issues=None, **overrides):
    entry = {
        "kind": kind,
        "repo": _REPO,
        "run": "synthetic-run-l1",
        "mode": mode,
        "lead": _lead(),
        "plan_ref": _plan_ref(),
        "source": "docs/plans/2099-01-01-synthetic-plan.md@%s" % _SHA_B,
        "approval_revision": _SHA_B,
    }
    if kind != "milestone":
        entry["fixed_issues"] = fixed_issues if fixed_issues is not None else [_ISSUE_1]
    if mode == "managed":
        entry["coordinator"] = _lead("synthetic-coordinator")
        entry["charter_revision"] = "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
        entry["contract_refs"] = []
    entry.update(overrides)
    return entry


class NormalizeEntryTests(unittest.TestCase):
    def test_ac1_entry_kinds_normalize_same_record(self):
        expected_issues = (_ISSUE_1,)
        results = {}
        for kind in ("plan", "prd", "issue"):
            result = gr.normalize_entry(_entry(kind=kind))
            self.assertTrue(result.ok, kind)
            self.assertEqual(result.value.fixed_issues, expected_issues, kind)
            results[kind] = result.value

        milestone_result = gr.normalize_entry(
            _entry(kind="milestone"), resolved_issues=[_ISSUE_1]
        )
        self.assertTrue(milestone_result.ok)
        results["milestone"] = milestone_result.value

        for kind, assignment in results.items():
            self.assertEqual(assignment.fixed_issues, expected_issues, kind)
            self.assertEqual(assignment.repo, _REPO, kind)
            self.assertEqual(assignment.mode, "standalone", kind)

        # The milestone snapshot does not grow when a later Issue appears.
        later = gr.normalize_entry(
            _entry(kind="milestone"), resolved_issues=[_ISSUE_1, _ISSUE_2]
        )
        self.assertEqual(later.value.fixed_issues, (_ISSUE_1, _ISSUE_2))
        self.assertEqual(results["milestone"].fixed_issues, (_ISSUE_1,))

    def test_ac2_each_arming_refusal_has_distinct_reason(self):
        cases = {
            "empty_issue_set": _entry(fixed_issues=[]),
            "cross_repo_issue": _entry(fixed_issues=["OTHER/repo#1"]),
            "bare_ambiguous_issue_id": _entry(fixed_issues=["184"]),
            "duplicate_issue": _entry(fixed_issues=[_ISSUE_1, _ISSUE_1]),
            "managed_missing_bindings": _entry(
                mode="managed", coordinator=None, charter_revision=None,
                contract_refs=None,
            ),
            "unsupported_major_version": _entry(version="assignment-v2"),
            "missing_required_field": _entry(source=None),
            "malformed_input": "not-a-dict",
        }
        for expected_reason, entry in cases.items():
            with self.subTest(case=expected_reason):
                result = gr.normalize_entry(entry)
                self.assertEqual(result.outcome, "invalid")
                self.assertEqual(result.reason, expected_reason)

        # Non-PR goal is refused before arming.
        armed = gr.arm(_entry(), deliverable_type="doc")
        self.assertEqual(armed.outcome, "invalid")
        self.assertEqual(armed.reason, "non_pr_goal")

    def test_ac6_sc1_fixtures_consumed_read_only(self):
        for name in ("accepted-structured-plan-ref", "accepted-two-distinct-runs"):
            fixture = json.loads((SC1_FIXTURES / (name + ".json")).read_text())
            result = gr.normalize_entry(fixture["input"])
            self.assertTrue(result.ok, name)
            self.assertEqual(result.value.mode, "standalone", name)

        rejected = {
            "rejected-approval-revision-mismatch": "approval_revision_mismatch",
            "rejected-machine-path-plan-ref": "machine_specific_path",
        }
        for name, reason in rejected.items():
            fixture = json.loads((SC1_FIXTURES / (name + ".json")).read_text())
            result = gr.normalize_entry(fixture["input"])
            self.assertFalse(result.ok, name)
            self.assertEqual(result.reason, reason, name)

        equivalents = {
            "bare-ambiguous-issue-id": "bare_ambiguous_issue_id",
            "missing-managed-source": "managed_missing_bindings",
        }
        for name, reason in equivalents.items():
            fixture = json.loads((GOAL_FIXTURES / (name + ".json")).read_text())
            result = gr.normalize_entry(fixture["input"])
            self.assertFalse(result.ok, name)
            self.assertEqual(result.reason, reason, name)


class FrozenScopeTests(unittest.TestCase):
    def test_ac3_mode_change_and_scope_growth_rejected(self):
        standalone = gr.normalize_entry(_entry(mode="standalone")).value
        managed = gr.normalize_entry(_entry(mode="managed")).value

        self.assertEqual(
            gr.guard_frozen_scope(managed, mode="standalone").reason,
            "managed_to_standalone",
        )
        self.assertEqual(
            gr.guard_frozen_scope(standalone, mode="managed").reason,
            "standalone_to_managed",
        )
        self.assertEqual(
            gr.guard_frozen_scope(standalone, fixed_issues=[_ISSUE_1, _ISSUE_2]).reason,
            "scope_growth",
        )

        self.assertTrue(gr.guard_frozen_scope(standalone).ok)
        self.assertTrue(gr.guard_frozen_scope(managed).ok)


class BoundsTests(unittest.TestCase):
    def test_ac4_defaults_narrowing_and_tightening(self):
        policy = gr.apply_policy().value
        self.assertEqual(policy.run_time_hours, 24.0)
        self.assertEqual(policy.dispatch_cap_per_issue, 8)
        self.assertEqual(policy.gv_retries, 3)
        self.assertIsNone(policy.spend_cap)

        narrowed = gr.apply_policy(
            goal={"run_time_hours": 12.0, "dispatch_cap_per_issue": 4}
        )
        self.assertTrue(narrowed.ok)
        self.assertEqual(narrowed.value.run_time_hours, 12.0)
        self.assertEqual(narrowed.value.dispatch_cap_per_issue, 4)

        widened = gr.apply_policy(goal={"run_time_hours": 48.0})
        self.assertEqual(widened.outcome, "invalid")
        self.assertEqual(widened.reason, "goal_widening")

        tightened = gr.apply_policy(
            goal={"run_time_hours": 12.0},
            coordinator={"run_time_hours": 6.0},
            mode="managed",
        )
        self.assertTrue(tightened.ok)
        self.assertEqual(tightened.value.run_time_hours, 6.0)

        loosened = gr.apply_policy(
            goal={"run_time_hours": 12.0},
            coordinator={"run_time_hours": 20.0},
            mode="managed",
        )
        self.assertEqual(loosened.outcome, "invalid")
        self.assertEqual(loosened.reason, "coordinator_loosening")

    def test_ac4_limit_reached_incomplete(self):
        policy = gr.apply_policy().value

        run_time = gr.evaluate_limits(
            policy, gr.RunCounters(), "2026-11-06T00:00:00Z", "2026-11-07T00:00:01Z"
        )
        self.assertEqual(run_time.outcome, "incomplete")
        self.assertEqual(run_time.reason, "run_time_exceeded")

        counters = gr.RunCounters()
        for i in range(8):
            gr.account_dispatch(counters, _ISSUE_1, "req-%d" % i)
        gr.account_dispatch(counters, _ISSUE_2, "req-sibling")
        dispatch = gr.evaluate_limits(
            policy, counters, "2026-11-06T00:00:00Z", "2026-11-06T01:00:00Z"
        )
        self.assertEqual(dispatch.outcome, "incomplete")
        self.assertEqual(dispatch.reason, "dispatch_cap_exceeded")
        self.assertIn(_ISSUE_1, dispatch.detail["incomplete_issues"])
        self.assertIn(_ISSUE_2, dispatch.detail["continue_issues"])

        dependent = gr.evaluate_limits(
            policy,
            counters,
            "2026-11-06T00:00:00Z",
            "2026-11-06T01:00:00Z",
            dependencies={_ISSUE_2: [_ISSUE_1]},
        )
        self.assertIn(_ISSUE_2, dependent.detail["incomplete_issues"])

        spend_policy = gr.apply_policy(goal={"spend_cap": 10.0}).value
        over_spend = gr.evaluate_limits(
            spend_policy,
            gr.RunCounters(spend=25.0),
            "2026-11-06T00:00:00Z",
            "2026-11-06T01:00:00Z",
        )
        self.assertEqual(over_spend.outcome, "incomplete")
        self.assertEqual(over_spend.reason, "spend_cap_exceeded")

        unknown_usage = gr.evaluate_limits(
            spend_policy,
            gr.RunCounters(spend=gr.USAGE_UNKNOWN),
            "2026-11-06T00:00:00Z",
            "2026-11-06T01:00:00Z",
        )
        self.assertEqual(unknown_usage.outcome, "complete")

    def test_ac4_resume_and_extension_do_not_reset_counters(self):
        counters = gr.RunCounters()
        gr.account_dispatch(counters, _ISSUE_1, "req-1")
        gr.account_dispatch(counters, _ISSUE_1, "req-2")
        self.assertEqual(counters.dispatch_count(_ISSUE_1), 2)

        policy = gr.apply_policy().value
        gr.evaluate_limits(policy, counters, "2026-11-06T00:00:00Z", "2026-11-06T01:00:00Z")
        self.assertEqual(counters.dispatch_count(_ISSUE_1), 2)

        extended = gr.extend_limit(policy, "dispatch_cap_per_issue", 12)
        self.assertTrue(extended.ok)
        self.assertEqual(extended.value.dispatch_cap_per_issue, 12)
        self.assertEqual(counters.dispatch_count(_ISSUE_1), 2)


class MarkerTests(unittest.TestCase):
    def test_ac5_hard_stop_h1_through_h5(self):
        for level in range(1, 6):
            with self.subTest(level=level):
                result = gr.parse_turn_end_marker(
                    "HARD-STOP: H%d \u2014 stop reason" % level
                )
                self.assertEqual(result.outcome, "protected_stop")
                self.assertEqual(result.reason, "hard_stop_h%d" % level)
                self.assertEqual(result.detail["level"], "H%d" % level)

    def test_ac5_wake_valid_mismatch_and_pause(self):
        valid = gr.parse_turn_end_marker(
            "WAKE: 2026-11-06T12:00:00Z \u2014 resume",
            next_wake_at="2026-11-06T12:00:00Z",
            next_action="resume",
        )
        self.assertTrue(valid.ok)
        self.assertEqual(valid.detail["action"], "resume")

        mismatch = gr.parse_turn_end_marker(
            "WAKE: 2026-11-06T12:00:00Z \u2014 resume",
            next_wake_at="2026-11-06T13:00:00Z",
            next_action="resume",
        )
        self.assertEqual(mismatch.outcome, "invalid")
        self.assertEqual(mismatch.reason, "wake_mismatch")

        paused = gr.parse_turn_end_marker(
            "WAKE: 2026-11-06T12:00:00Z \u2014 resume",
            next_wake_at="2026-11-06T12:00:00Z",
            next_action="resume",
            paused=True,
        )
        self.assertEqual(paused.outcome, "invalid")
        self.assertEqual(paused.reason, "wake_during_pause")

    def test_ac5_goal_complete_is_a_claim_not_verified(self):
        claim = gr.parse_turn_end_marker(
            "GOAL-COMPLETE: %s" % _ISSUE_1, expected_source=_ISSUE_1
        )
        self.assertEqual(claim.outcome, "claim_requires_gv")
        self.assertFalse(claim.detail["verified"])

        wrong = gr.parse_turn_end_marker(
            "GOAL-COMPLETE: OWNER/synthetic-repo#9", expected_source=_ISSUE_1
        )
        self.assertEqual(wrong.outcome, "invalid")
        self.assertEqual(wrong.reason, "wrong_source")

    def test_ac5_malformed_and_multiple_markers(self):
        not_last = gr.parse_turn_end_marker(
            "HARD-STOP: H1 \u2014 early\nplain prose on the last line"
        )
        self.assertEqual(not_last.reason, "marker_not_last")

        two_markers = gr.parse_turn_end_marker(
            "HARD-STOP: H1 \u2014 a HARD-STOP: H2 \u2014 b"
        )
        self.assertEqual(two_markers.reason, "multiple_markers")

        malformed = gr.parse_turn_end_marker("HARD-STOP: H9 \u2014 out of range")
        self.assertEqual(malformed.reason, "malformed_marker")

        no_marker = gr.parse_turn_end_marker("")
        self.assertEqual(no_marker.reason, "no_marker")


class CorrelationTests(unittest.TestCase):
    def test_ac8_dispatch_idempotency(self):
        counters = gr.RunCounters()
        first = gr.account_dispatch(counters, _ISSUE_1, "req-abc")
        second = gr.account_dispatch(counters, _ISSUE_1, "req-abc")
        self.assertTrue(first.detail["counted"])
        self.assertFalse(second.detail["counted"])
        self.assertEqual(counters.dispatch_count(_ISSUE_1), 1)

    def test_ac8_context_only_cannot_grow_scope(self):
        assignment = gr.normalize_entry(_entry()).value
        before = assignment.fixed_issues
        rejected = gr.classify_input(
            {"kind": "context", "add_issues": [_ISSUE_2]}
        )
        self.assertEqual(rejected.outcome, "invalid")
        self.assertEqual(rejected.reason, "context_only_scope_change")
        self.assertEqual(assignment.fixed_issues, before)

        accepted = gr.classify_input({"kind": "context"})
        self.assertEqual(accepted.detail["classification"], "context_only")

    def test_ac8_handback_record(self):
        handback = gr.make_handback("req-xyz", "out_of_scope")
        self.assertEqual(handback.value.reference, "req-xyz")
        self.assertEqual(handback.value.reason, "out_of_scope")
        self.assertEqual(handback.value.disposition, "pending")

    def test_ac8_question_classification(self):
        self.assertEqual(
            gr.classify_question({"question_kind": "engineering"}).detail["resolution"],
            "lead",
        )
        for kind in ("product", "scope", "acceptance"):
            self.assertEqual(
                gr.classify_question({"question_kind": kind}).detail["resolution"],
                "user",
                kind,
            )
        self.assertEqual(gr.classify_question({}).detail["resolution"], "user")
        self.assertEqual(
            gr.classify_question({"question_kind": "gibberish"}).detail["resolution"],
            "user",
        )


class SideEffectTests(unittest.TestCase):
    def test_ac7_no_side_effects_and_compiles(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        for forbidden in (
            "import subprocess",
            "import socket",
            "import urllib",
            "import requests",
            "import http",
            "import os",
            "open(",
        ):
            self.assertNotIn(forbidden, source)
        compile(source, str(MODULE_PATH), "exec")


if __name__ == "__main__":
    unittest.main()
