"""Focused checks for #196 lane L5: recovery admission, SC-9 records and
reconciliation.

One named test per acceptance criterion (AC1-AC10), plus a closed-list drift test
against docs/v2.2/contracts/sc-9.md, an AST side-effect-free test, and per-branch
refusal tests for every closed-list and gate helper. SC-9 fixtures under
docs/v2.2/contracts/fixtures/sc-9/ are consumed read-only with no digest pins;
recovery-only cases live under tests/fixtures/recovery/.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "dev" / "scripts"
GOAL_RUN = SCRIPTS / "goal_run.py"
GOAL_RECOVERY = SCRIPTS / "goal_recovery.py"
SC9_MD = ROOT / "docs" / "v2.2" / "contracts" / "sc-9.md"
SC9_FIXTURES = ROOT / "docs" / "v2.2" / "contracts" / "fixtures" / "sc-9"
RECOVERY_FIXTURES = ROOT / "tests" / "fixtures" / "recovery"

_ZEROS = "sha256:" + "0" * 64
_APPROVAL = "2099-01-01T00:00:00Z"
_NOW = "2099-01-01T10:00:00Z"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gr = _load("goal_run", GOAL_RUN)
rc = _load("goal_recovery", GOAL_RECOVERY)


def _checkpoint(coverage="top_level", degradation=None, authoritative_refs=None):
    return rc.build_checkpoint_reference(
        run="synthetic-run-l5",
        session="synthetic-session-l5",
        event="synthetic-event-l5",
        adapter="synthetic-adapter",
        version="v0.2.1",
        note_revision=_ZEROS,
        freshness="2099-01-02T00:00:00Z",
        authoritative_refs=authoritative_refs or ["docs/plans/synthetic-plan.md"],
        coverage=coverage,
        degradation=degradation,
    ).value


def _obligations(**overrides):
    base = dict(
        children=("child-1",),
        owed_replies=("reply-1",),
        original_request="request-1",
        responsible_party="lead-1",
        evidence=("ev-1",),
        consumed_allowances=("allow-1",),
        worker_count=1,
        defect_episode=1,
        fix_batch_count=0,
        owner_escalation=False,
    )
    base.update(overrides)
    return rc.Obligations(**base)


def _policy(**overrides):
    return rc.BoundsPolicy(**overrides)


def _counters(**overrides):
    return rc.RunCounters(**overrides)


def _armed_scope():
    return rc.ArmedRun(
        assignment=gr.Assignment(
            repo="KHAEntertainment/showrunner",
            run="run-1",
            mode="standalone",
            lead={"agent_id": "a", "harness": "h", "model": "m"},
            plan_ref={"origin": "p", "source_revision": "r", "approved_revision": "r"},
            source="p@r",
            approval_revision="r",
            fixed_issues=("KHAEntertainment/showrunner#1",),
        ),
        policy=_policy(),
    )


def _input(**overrides):
    base = dict(
        checkpoint=_checkpoint(),
        note_status=rc.NOTE_CURRENT,
        checkpoint_available=True,
        outstanding_waits=(),
        protected_restrictions=(),
        event_identity="evt-1",
        event_kind=rc.EVENT_KIND_COMPACTION,
        ledger=rc.EventLedger(),
        obligations_before=_obligations(),
        obligations_after=_obligations(),
        current_source="docs/plans/synthetic-plan.md@rev",
        charter_revision="rev",
        current_heads=("head-1",),
        invalidation=(),
        policy=_policy(),
        counters=_counters(),
        approval_time=_APPROVAL,
        now=_NOW,
        authority_bindings=("lead-1",),
    )
    base.update(overrides)
    return rc.RecoveryInput(**base)


class ResumeOrderTests(unittest.TestCase):
    """AC1 — resume admission order."""

    def test_AC1_resume_order(self):
        # Clean recovery passes all six steps in order and records step 6.
        result = rc.admit_recovery(_input())
        self.assertTrue(result.may_proceed, result.reason)
        self.assertEqual(result.detail["step"], 6)
        self.assertEqual(result.value.admission_outcome, "restored_then_current_state_check")

        # A failure at each step stops there and names the step.
        cases = [
            (_input(checkpoint=None), 1, "missing_required_field"),
            (_input(note_status="stale", paused=True), 1, "resume_overrides_pause"),
            (_input(note_status="missing", checkpoint_available=False), 1, "recovery_evidence_unavailable"),
            (_input(paused=True, resume_over_pause=True), 2, "resume_overrides_pause"),
            (_input(outstanding_waits=None), 2, "missing_required_field"),
            (_input(sole_writer=False), 3, "second_writer"),
            (_input(rotation_due=True, event_kind=rc.EVENT_KIND_COMPACTION), 3, "compaction_counts_as_rotation"),
            (_input(rotation_due=True, event_kind=rc.EVENT_KIND_WAKE), 3, "rotation_not_evidenced"),
            (_input(ledger=rc.EventLedger(seen=("evt-1", "evt-1"))), 3, "duplicate_compaction_count"),
            (_input(replay_attempted=True, unknown_outcomes=("lost-1",)), 4, "unknown_effect_replay"),
            (_input(obligations_before=None), 4, "missing_required_field"),
            (_input(obligations_after=_obligations(worker_count=2)), 4, "obligations_changed"),
            (_input(current_source=None), 4, "missing_required_field"),
            (_input(scope=_armed_scope(), fixed_issues=("KHAEntertainment/showrunner#2",)), 4, "scope_growth"),
            (_input(managed_fallback=True), 5, "managed_to_standalone"),
            (_input(authority_renewed=True), 5, "authority_renewed_by_activity"),
            (_input(authority_revoked=True), 5, "authority_revoked"),
            (_input(authority_expired=True), 5, "authority_expired"),
            (_input(policy=None), 5, "missing_required_field"),
            (_input(now="2099-01-02T10:00:00Z"), 5, "run_time_exceeded"),
        ]
        for state, expected_step, expected_reason in cases:
            res = rc.admit_recovery(state)
            self.assertFalse(res.ok, (expected_step, expected_reason, res.detail))
            self.assertEqual(res.detail["step"], expected_step, res.reason)
            self.assertEqual(res.reason, expected_reason, res.detail)

    def test_AC1_pause_wakes_recovery_only_and_no_fallback(self):
        # A resume prompt during an owner pause wakes recovery only, no task work.
        res = rc.admit_recovery(_input(paused=True))
        self.assertTrue(res.may_proceed)
        self.assertEqual(res.value.admission_outcome, "pause_honored_recovery_only")
        self.assertEqual(res.detail["step"], 6)

        # Managed-to-standalone fallback is rejected (no fallback path).
        res = rc.admit_recovery(_input(managed_fallback=True))
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "managed_to_standalone")
        self.assertEqual(res.detail["step"], 5)


class LimitGateTests(unittest.TestCase):
    """F1/C1 — step 5 checks ``limits.outcome == "complete"``, not ``.ok``."""

    def test_run_time_limit_rejected_at_step_5(self):
        res = rc.admit_recovery(_input(now="2099-01-02T10:00:00Z"))
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "run_time_exceeded")
        self.assertEqual(res.detail["step"], 5)

    def test_spend_cap_rejected_at_step_5(self):
        res = rc.admit_recovery(
            _input(policy=_policy(spend_cap=50), counters=_counters(spend=100))
        )
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "spend_cap_exceeded")
        self.assertEqual(res.detail["step"], 5)

    def test_dispatch_cap_rejected_at_step_5_with_issue_eligibility(self):
        res = rc.admit_recovery(
            _input(
                policy=_policy(dispatch_cap_per_issue=8),
                counters=_counters(dispatch_counts={"issue-a": 8, "issue-b": 2}),
            )
        )
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "dispatch_cap_exceeded")
        self.assertEqual(res.detail["step"], 5)
        self.assertEqual(res.detail["incomplete_issues"], ["issue-a"])
        self.assertEqual(res.detail["continue_issues"], ["issue-b"])


class SC9RecordTests(unittest.TestCase):
    """AC2 — SC-9 records."""

    def test_AC2_sc9_fixtures_evaluate_to_expected_outcome(self):
        for path in sorted(SC9_FIXTURES.glob("*.json")):
            fixture = json.loads(path.read_text())
            record_type = fixture["version"]
            res = rc.validate_sc9_record(record_type, fixture["input"])
            actual = "reject" if res.outcome == "invalid" else "accept"
            self.assertEqual(actual, fixture["expected_outcome"], path.name)

    def test_AC2_built_records_validate(self):
        cp = _checkpoint(coverage="child")
        self.assertTrue(cp is not None)
        res = rc.validate_sc9_record(rc.VERSION_CHECKPOINT_REFERENCE, cp.to_dict())
        self.assertTrue(res.may_proceed, res.reason)

        receipt = rc.build_recovery_receipt(cp, "counted_once", "restored_then_current_state_check")
        self.assertTrue(receipt.may_proceed, receipt.reason)
        res = rc.validate_sc9_record(rc.VERSION_RECOVERY_RECEIPT, receipt.value.to_dict())
        self.assertTrue(res.may_proceed, res.reason)

    def test_AC2_invalid_records(self):
        # Out-of-list coverage value.
        res = rc.validate_sc9_record(
            rc.VERSION_CHECKPOINT_REFERENCE,
            {**_checkpoint().to_dict(), "coverage": "everything"},
        )
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "out_of_list_value")

        # Missing required field (authoritative_refs).
        data = _checkpoint().to_dict()
        del data["authoritative_refs"]
        res = rc.validate_sc9_record(rc.VERSION_CHECKPOINT_REFERENCE, data)
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "missing_required_field")

        # Unknown major version.
        res = rc.validate_sc9_record("checkpoint-reference-v9", _checkpoint().to_dict())
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "unsupported_major_version")

        # Out-of-list admission_outcome.
        res = rc.build_recovery_receipt(_checkpoint(), "counted_once", "not_a_real_outcome")
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "out_of_list_value")


class MalformedEnumTests(unittest.TestCase):
    """F7 — type-check enum values before set membership (never a TypeError)."""

    def test_coverage_malformed_values(self):
        for value in (["top_level"], {"x": 1}, 5):
            res = rc.validate_sc9_record(
                rc.VERSION_CHECKPOINT_REFERENCE,
                {**_checkpoint().to_dict(), "coverage": value},
            )
            self.assertFalse(res.ok, value)
            self.assertEqual(res.reason, "malformed_input", value)

    def test_event_accounting_result_malformed_values(self):
        for value in (["counted_once"], {"x": 1}, None, 5):
            res = rc.build_recovery_receipt(
                _checkpoint(), value, "restored_then_current_state_check"
            )
            self.assertFalse(res.ok, value)
            self.assertEqual(res.reason, "malformed_input", value)

    def test_admission_outcome_malformed_values(self):
        for value in (["restored_then_current_state_check"], {"x": 1}, None, 5):
            res = rc.build_recovery_receipt(_checkpoint(), "counted_once", value)
            self.assertFalse(res.ok, value)
            self.assertEqual(res.reason, "malformed_input", value)

    def test_validate_sc9_record_enum_malformed_values(self):
        receipt = _checkpoint().to_dict()
        receipt["event_accounting"] = {"result": ["counted_once"]}
        res = rc.validate_sc9_record(rc.VERSION_RECOVERY_RECEIPT, receipt)
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "malformed_input")

        receipt = _checkpoint().to_dict()
        receipt["event_accounting"] = {"result": "counted_once"}
        receipt["admission_outcome"] = {"x": 1}
        res = rc.validate_sc9_record(rc.VERSION_RECOVERY_RECEIPT, receipt)
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "malformed_input")


class PausedRotationTests(unittest.TestCase):
    """AC3 — paused and rotation-due recovery."""

    def test_AC3_paused_stays_paused(self):
        res = rc.admit_recovery(_input(paused=True))
        self.assertTrue(res.may_proceed)
        self.assertEqual(res.value.admission_outcome, "pause_honored_recovery_only")

    def test_AC3_due_rotation_requires_real_evidence(self):
        # A compaction is never a rotation.
        res = rc.admit_recovery(_input(rotation_due=True, event_kind=rc.EVENT_KIND_COMPACTION))
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "compaction_counts_as_rotation")
        self.assertEqual(res.detail["step"], 3)

        # A wake with rotation due but no rotation evidence is refused.
        res = rc.admit_recovery(_input(rotation_due=True, event_kind=rc.EVENT_KIND_WAKE))
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "rotation_not_evidenced")
        self.assertEqual(res.detail["step"], 3)

        # A lead-handoff label alone (no successor/transfer/custody) is refused.
        res = rc.admit_recovery(_input(rotation_due=True, event_kind=rc.EVENT_KIND_LEAD_HANDOFF))
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "rotation_not_evidenced")

        # A pending transfer (not acknowledged) is refused.
        res = rc.admit_recovery(
            _input(
                rotation_due=True,
                event_kind=rc.EVENT_KIND_LEAD_HANDOFF,
                successor="lead-2",
            )
        )
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "rotation_transfer_pending")

        # A conflicting transfer is refused.
        res = rc.admit_recovery(
            _input(
                rotation_due=True,
                event_kind=rc.EVENT_KIND_LEAD_HANDOFF,
                successor="lead-2",
                transfer_acknowledged=True,
                native_session_id="session-002",
                transfer_conflict=True,
            )
        )
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "rotation_transfer_conflict")

        # A genuine rotation applies the rotation.
        res = rc.admit_recovery(
            _input(
                rotation_due=True,
                event_kind=rc.EVENT_KIND_LEAD_HANDOFF,
                successor="lead-2",
                transfer_acknowledged=True,
                native_session_id="session-002",
            )
        )
        self.assertTrue(res.may_proceed)
        self.assertEqual(res.value.admission_outcome, "rotation_due_rotation_applied")

    def test_AC3_coverage_top_level_and_child_recorded_excluded_not_counted(self):
        res = rc.evaluate_coverage({"top": "top_level", "child-session": "child", "skip": "excluded"})
        self.assertTrue(res.may_proceed)
        self.assertEqual(set(res.detail["covered"]), {"top", "child-session"})
        self.assertEqual(res.detail["excluded"], ["skip"])


class EventDedupTests(unittest.TestCase):
    """AC4 — event dedup and accounting."""

    def test_AC4_duplicate_events_counted_once(self):
        for kind in (rc.EVENT_KIND_COMPACTION, rc.EVENT_KIND_HOOK_DELIVERY, rc.EVENT_KIND_LEAD_HANDOFF):
            first = rc.account_event(rc.EventLedger(), "evt", kind)
            self.assertTrue(first.may_proceed)
            self.assertTrue(first.detail["counted"])
            self.assertEqual(first.detail["count"], 1)

            second = rc.account_event(first.value, "evt", kind)
            self.assertTrue(second.may_proceed)
            self.assertFalse(second.detail["counted"])
            self.assertEqual(second.detail["count"], 1)
            self.assertEqual(second.detail["result"], "counted_once")
            self.assertTrue(second.detail["duplicate"])
            # The counter is unchanged by the duplicate.
            self.assertEqual(second.value.count("evt"), 1)

    def test_AC4_authority_renewal_rejected(self):
        res = rc.admit_recovery(_input(authority_renewed=True))
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "authority_renewed_by_activity")


class UnknownEffectTests(unittest.TestCase):
    """AC5 — unknown effect."""

    def test_AC5_unknown_effect(self):
        # Lost response -> inspect destination first, dependent action blocked.
        res = rc.reconcile_unknown_effect("unknown")
        self.assertTrue(res.may_proceed)
        self.assertEqual(res.detail["action"], "inspect_destination_first")
        self.assertTrue(res.detail["blocked"])

        # Repeating the action before reconciliation is rejected.
        res = rc.reconcile_unknown_effect("unknown", retry=True)
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "unknown_effect_replay")

        # Reconciled outcome unblocks.
        res = rc.reconcile_unknown_effect("resolved")
        self.assertTrue(res.may_proceed)
        self.assertFalse(res.detail["blocked"])

    def test_AC5_admit_recovery_replay_rejected_at_step_4(self):
        res = rc.admit_recovery(_input(replay_attempted=True, unknown_outcomes=("lost-1",)))
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "unknown_effect_replay")
        self.assertEqual(res.detail["step"], 4)

    def test_AC5_unknown_outcomes_restrict_admission(self):
        # An unknown outcome, without replay, still restricts admission.
        res = rc.admit_recovery(_input(unknown_outcomes=("lost-1",)))
        self.assertTrue(res.may_proceed, res.reason)
        self.assertEqual(res.detail["step"], 6)
        # The unknown identities are kept, dependent actions are blocked, and the
        # action is inspect-destination-first (eligibility limited).
        self.assertEqual(res.detail["unknown_outcomes"], ("lost-1",))
        self.assertTrue(res.detail["dependent_actions_blocked"])
        self.assertEqual(res.detail["eligibility"], "inspection_and_independent")
        self.assertEqual(res.detail["action"], "inspect_destination_first")

    def test_AC5_dependent_action_withheld(self):
        # A dependent action is blocked while an outcome is unknown.
        res = rc.reconcile_unknown_effect("unknown")
        self.assertTrue(res.detail["blocked"])
        res = rc.reconcile_unknown_effect("unknown", retry=True)
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "unknown_effect_replay")


class ObligationsTests(unittest.TestCase):
    """AC6 — owed replies and children preserved."""

    def test_AC6_obligations_preserved(self):
        before = _obligations()
        # Recovery, a duplicate event and a lead handoff leave obligations unchanged.
        self.assertTrue(rc.preserve_obligations(before, before).may_proceed)

        # A new worker is not created.
        res = rc.preserve_obligations(before, _obligations(worker_count=2))
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "obligations_changed")
        self.assertIn("worker_count", res.detail["changed"])

        # No defect-episode reset, no extra fix batch, no automatic escalation.
        for override in (
            {"defect_episode": 0},
            {"fix_batch_count": 1},
            {"owner_escalation": True},
            {"owed_replies": ()},
            {"children": ()},
            {"original_request": "request-2"},
            {"responsible_party": "lead-2"},
            {"evidence": ("ev-2",)},
            {"consumed_allowances": ("allow-2",)},
        ):
            res = rc.preserve_obligations(before, _obligations(**override))
            self.assertFalse(res.ok, override)
            self.assertEqual(res.reason, "obligations_changed")

    def test_AC6_end_to_end_obligations_unchanged(self):
        before = _obligations()
        # Recovery (compaction) preserves obligations.
        res = rc.admit_recovery(_input(obligations_before=before, obligations_after=before))
        self.assertTrue(res.may_proceed, res.reason)

        # A genuine lead handoff preserves obligations.
        res = rc.admit_recovery(
            _input(
                rotation_due=True,
                event_kind=rc.EVENT_KIND_LEAD_HANDOFF,
                successor="lead-2",
                transfer_acknowledged=True,
                native_session_id="session-002",
                obligations_before=before,
                obligations_after=before,
            )
        )
        self.assertTrue(res.may_proceed, res.reason)
        self.assertEqual(res.value.admission_outcome, "rotation_due_rotation_applied")

        # A duplicate event preserves obligations.
        dup = rc.account_event(rc.EventLedger(), "evt-1", rc.EVENT_KIND_COMPACTION)
        res = rc.admit_recovery(
            _input(
                ledger=dup.value,
                obligations_before=before,
                obligations_after=before,
            )
        )
        self.assertTrue(res.may_proceed, res.reason)

        # A change is caught end-to-end.
        res = rc.admit_recovery(
            _input(
                obligations_before=before,
                obligations_after=_obligations(worker_count=2),
            )
        )
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "obligations_changed")
        self.assertEqual(res.detail["step"], 4)


class NoteCaseTests(unittest.TestCase):
    """AC7 — note cases."""

    def test_AC7_note_cases(self):
        fixture = json.loads((RECOVERY_FIXTURES / "note-cases.json").read_text())
        for case in fixture["cases"]:
            res = rc.classify_note(
                case["note_status"],
                paused=case["paused"],
                checkpoint_available=case["checkpoint_available"],
            )
            if case.get("expected_reject"):
                self.assertFalse(res.ok, case["name"])
                self.assertEqual(res.reason, case["expected_outcome"], case["name"])
            else:
                self.assertTrue(res.may_proceed, case["name"])
                self.assertEqual(res.value, case["expected_outcome"], case["name"])
            if "expected_continuity" in case:
                self.assertEqual(res.detail["continuity"], case["expected_continuity"], case["name"])
                self.assertEqual(res.detail["degradation"], case["expected_degradation"], case["name"])


class LineageCustodyTests(unittest.TestCase):
    """AC8 — lineage and custody vs same-session compaction."""

    def test_AC8_lineage_cases(self):
        fixture = json.loads((RECOVERY_FIXTURES / "lineage-cases.json").read_text())
        for case in fixture["cases"]:
            res = rc.classify_lineage(
                case["prior_session_id"], case["current_session_id"], claim=case["claim"]
            )
            self.assertTrue(res.may_proceed, case["name"])
            self.assertEqual(res.value, case["expected_value"], case["name"])
            self.assertEqual(res.detail["custody"], case["expected_custody"], case["name"])

    def test_AC8_custody_unknown_without_session_id(self):
        res = rc.classify_lineage("session-001", None)
        self.assertEqual(res.value, "custody_unknown")

    def test_AC8_contradictory_claim_refused(self):
        res = rc.classify_lineage("session-001", "session-001", claim="successor")
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "lineage_claim_conflict")

        res = rc.classify_lineage("session-001", "session-002", claim=("successor", "takeover"))
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "lineage_claim_conflict")

    def test_AC8_developing_adapters_never_parity(self):
        for adapter in (rc.ADAPTER_CODEX, rc.ADAPTER_PI):
            res = rc.qualify_adapter(
                adapter,
                native_session_id="session-001",
                load_evidence_session="session-001",
                build_qualified=True,
                event_coverage=True,
                child_exclusions=True,
            )
            self.assertFalse(res.detail["supported"], adapter)
            self.assertFalse(res.detail["parity"], adapter)

    def test_AC8_qualified_route_and_foreign_load_marker(self):
        qualified = rc.qualify_adapter(
            rc.ADAPTER_OPENCODE,
            native_session_id="session-001",
            load_evidence_session="session-001",
            build_qualified=True,
            event_coverage=True,
            child_exclusions=True,
        )
        self.assertTrue(qualified.detail["supported"])

        # A global last-loaded marker for another session is not load proof.
        foreign = rc.qualify_adapter(
            rc.ADAPTER_OPENCODE,
            native_session_id="session-001",
            load_evidence_session="session-999",
            build_qualified=True,
            event_coverage=True,
            child_exclusions=True,
        )
        self.assertFalse(foreign.detail["supported"])
        self.assertEqual(foreign.detail["reason"], "foreign_last_loaded_marker")

    def test_qualify_adapter_refusal_branches(self):
        # Unknown adapter.
        res = rc.qualify_adapter("unknown-adapter")
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "malformed_input")

        # No load evidence.
        res = rc.qualify_adapter(rc.ADAPTER_CLAUDE)
        self.assertTrue(res.may_proceed)
        self.assertFalse(res.detail["supported"])
        self.assertEqual(res.detail["reason"], "no_load_evidence")

        # Unqualified route (load evidence present but not all qualifiers).
        res = rc.qualify_adapter(
            rc.ADAPTER_OPENCODE,
            native_session_id="session-001",
            load_evidence_session="session-001",
            build_qualified=False,
        )
        self.assertTrue(res.may_proceed)
        self.assertFalse(res.detail["supported"])
        self.assertEqual(res.detail["reason"], "unqualified")


class EvidenceReuseTests(unittest.TestCase):
    """AC9 — evidence reuse."""

    def test_AC9_evidence_reuse(self):
        existing = {"subject": "issue-1", "head": "abc", "definition_revision": "r1"}

        # Same-subject, same-head evidence is reused.
        res = rc.reuse_evidence("issue-1", "abc", "r1", existing=existing)
        self.assertTrue(res.detail["reusable"])

        # Pending CI never triggers local fallback; reusable stays True.
        res = rc.reuse_evidence("issue-1", "abc", "r1", existing=existing, pending_ci=True)
        self.assertFalse(res.detail["fallback"])
        self.assertTrue(res.detail["pending_ci"])
        self.assertTrue(res.detail["reusable"])

        # A different head is stale and not reused.
        res = rc.reuse_evidence("issue-1", "def", "r1", existing=existing)
        self.assertFalse(res.detail["reusable"])
        self.assertEqual(res.detail["reason"], "stale_evidence")

    def test_AC9_pending_ci_keeps_reusable_for_matching_evidence(self):
        existing = {"subject": "issue-1", "head": "abc", "definition_revision": "r1"}
        res = rc.reuse_evidence("issue-1", "abc", "r1", existing=existing, pending_ci=True)
        self.assertTrue(res.detail["reusable"])
        self.assertFalse(res.detail["fallback"])

    def test_AC9_changed_definition_not_reused(self):
        existing = {"subject": "issue-1", "head": "abc", "definition_revision": "r1"}
        res = rc.reuse_evidence("issue-1", "abc", "r2", existing=existing, pending_ci=True)
        self.assertFalse(res.detail["reusable"])
        self.assertEqual(res.detail["reason"], "stale_evidence")

    def test_reuse_evidence_refusal_branches(self):
        # Invalid subject.
        res = rc.reuse_evidence("", "abc", "r1")
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "malformed_input")

        # No evidence.
        res = rc.reuse_evidence("issue-1", "abc", "r1")
        self.assertTrue(res.may_proceed)
        self.assertFalse(res.detail["reusable"])
        self.assertEqual(res.detail["reason"], "no_evidence")
        self.assertIn("fallback", res.detail)

        # Non-dict existing.
        res = rc.reuse_evidence("issue-1", "abc", "r1", existing=["not-a-dict"])
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "malformed_input")

        # Different subject.
        res = rc.reuse_evidence(
            "issue-2", "abc", "r1", existing={"subject": "issue-1", "head": "abc", "definition_revision": "r1"}
        )
        self.assertTrue(res.may_proceed)
        self.assertFalse(res.detail["reusable"])
        self.assertEqual(res.detail["reason"], "different_subject")
        self.assertIn("fallback", res.detail)


class CoverageTests(unittest.TestCase):
    """evaluate_coverage refusal branches."""

    def test_evaluate_coverage_refusal_branches(self):
        # Non-dict map.
        res = rc.evaluate_coverage(["top_level"])
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "malformed_input")

        # Out-of-list value.
        res = rc.evaluate_coverage({"s": "everything"})
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "out_of_list_value")

        # Non-string value (malformed, never a TypeError).
        res = rc.evaluate_coverage({"s": ["top_level"]})
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "malformed_input")


class HelperRefusalBranchTests(unittest.TestCase):
    """Kilo W1-W8 — every refusal branch of each helper."""

    def test_account_event_refusal_branches(self):
        self.assertFalse(rc.account_event("not-a-ledger", "evt", "compaction").ok)
        self.assertFalse(rc.account_event(rc.EventLedger(), "", "compaction").ok)
        self.assertFalse(rc.account_event(rc.EventLedger(), "evt", "nope").ok)
        self.assertFalse(rc.account_event(rc.EventLedger(), "evt", ["compaction"]).ok)
        # Double-counted ledger.
        res = rc.account_event(rc.EventLedger(seen=("evt", "evt")), "evt", "compaction")
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "duplicate_compaction_count")

    def test_classify_note_refusal_branches(self):
        self.assertFalse(rc.classify_note("not-a-status").ok)
        self.assertFalse(rc.classify_note(["missing"]).ok)

    def test_reconcile_unknown_effect_refusal_branches(self):
        self.assertFalse(rc.reconcile_unknown_effect("not-an-outcome").ok)
        self.assertFalse(rc.reconcile_unknown_effect(["unknown"]).ok)

    def test_classify_lineage_refusal_branches(self):
        self.assertFalse(rc.classify_lineage("s1", "s2", claim="bogus").ok)

    def test_admit_recovery_degraded_checkpoint(self):
        res = rc.admit_recovery(
            _input(note_status="missing", checkpoint=_checkpoint(degradation="no_note"))
        )
        self.assertTrue(res.may_proceed, res.reason)
        self.assertEqual(res.value.admission_outcome, "fallback_ledger_recovery")
        self.assertEqual(res.value.checkpoint.degradation, "no_note")
        self.assertEqual(res.value.checkpoint.coverage, "top_level")
        self.assertEqual(res.detail["continuity"], "fallback")


class ImportByPathTests(unittest.TestCase):
    """M2 — goal_recovery is importable by path with no pre-registered goal_run."""

    def test_importable_by_path_without_preregistered_goal_run(self):
        saved_goal_run = sys.modules.get("goal_run")
        sys.modules.pop("goal_run", None)
        try:
            spec = importlib.util.spec_from_file_location("goal_recovery_by_path", GOAL_RECOVERY)
            mod = importlib.util.module_from_spec(spec)
            sys.modules["goal_recovery_by_path"] = mod
            spec.loader.exec_module(mod)
            self.assertTrue(hasattr(mod, "admit_recovery"))
            self.assertTrue(hasattr(mod, "classify_note"))
        finally:
            if saved_goal_run is not None:
                sys.modules["goal_run"] = saved_goal_run


class SideEffectTests(unittest.TestCase):
    """AC10 — no side effects, stdlib only."""

    FORBIDDEN_IMPORTS = {"socket", "subprocess", "urllib", "http", "shutil", "os", "time", "datetime"}
    FORBIDDEN_CALLS = {"open", "os.system"}
    FORBIDDEN_ATTRS = {
        "datetime.now",
        "datetime.utcnow",
        "time.time",
        "time.monotonic",
        "time.sleep",
    }
    FORBIDDEN_METHODS = {"write", "write_text", "write_bytes"}

    def test_AC10_module_is_pure(self):
        source = GOAL_RECOVERY.read_text()
        # Syntax is clean (py_compile equivalent).
        compile(source, str(GOAL_RECOVERY), "exec")

        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    self.assertNotIn(root, self.FORBIDDEN_IMPORTS, alias.name)
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn(node.module, self.FORBIDDEN_IMPORTS, node.module)
            elif isinstance(node, ast.Call):
                name = self._call_name(node.func)
                self.assertNotIn(name, self.FORBIDDEN_CALLS, name)
                if isinstance(node.func, ast.Attribute) and node.func.attr in self.FORBIDDEN_METHODS:
                    self.fail("forbidden file write: .%s" % node.func.attr)
                if name in self.FORBIDDEN_ATTRS:
                    self.fail("forbidden time call: %s" % name)
            elif isinstance(node, ast.Attribute):
                owner = self._attr_owner(node)
                if owner in ("datetime", "time") and node.attr in ("now", "utcnow", "time", "monotonic", "sleep"):
                    self.fail("forbidden clock read: %s.%s" % (owner, node.attr))

    @staticmethod
    def _call_name(func):
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return "%s.%s" % (func.value.id if isinstance(func.value, ast.Name) else "?", func.attr)
        return "?"

    @staticmethod
    def _attr_owner(node):
        return node.value.id if isinstance(node.value, ast.Name) else "?"


class ClosedListDriftTests(unittest.TestCase):
    """Closed lists in sc-9.md must equal the module constants (no drift)."""

    def test_closed_lists_match_sc9_md(self):
        text = SC9_MD.read_text()
        self.assertEqual(
            self._parse_list(text, "`coverage` —"),
            rc.COVERAGE_VALUES,
        )
        self.assertEqual(
            self._parse_list(text, "`event_accounting.result` —"),
            rc.EVENT_ACCOUNTING_RESULTS,
        )
        self.assertEqual(
            self._parse_list(text, "`admission_outcome` —"),
            rc.ADMISSION_OUTCOMES,
        )

    @staticmethod
    def _parse_list(text, heading):
        lines = text.splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith(heading))
        values = set()
        for line in lines[start:]:
            match = re.match(r"^- `([a-z_]+)` —", line)
            if match:
                values.add(match.group(1))
            elif values and line.strip() == "":
                break
            elif values and not line.startswith("- "):
                break
        return values


if __name__ == "__main__":
    unittest.main()
