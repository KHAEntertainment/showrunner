"""Focused checks for #196 lane L5: recovery admission, SC-9 records and
reconciliation.

One named test per acceptance criterion (AC1-AC10), plus a closed-list drift test
against docs/v2.2/contracts/sc-9.md and an AST side-effect-free test. SC-9 fixtures
under docs/v2.2/contracts/fixtures/sc-9/ are consumed read-only with no digest
pins; recovery-only cases live under tests/fixtures/recovery/.
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


def _input(**overrides):
    base = dict(checkpoint=_checkpoint(), event_identity="evt-1", event_kind=rc.EVENT_KIND_COMPACTION)
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
            (_input(paused=True, resume_over_pause=True), 2, "resume_overrides_pause"),
            (_input(sole_writer=False), 3, "second_writer"),
            (_input(rotation_due=True, event_kind=rc.EVENT_KIND_COMPACTION), 3, "compaction_counts_as_rotation"),
            (
                _input(
                    replay_attempted=True,
                    unknown_outcomes=("lost-1",),
                    obligations_before=_obligations(),
                    obligations_after=_obligations(worker_count=2),
                ),
                4,
                "unknown_effect_replay",
            ),
            (_input(managed_fallback=True), 5, "managed_to_standalone"),
            (_input(authority_renewed=True), 5, "authority_renewed_by_activity"),
            (_input(accounting_result="duplicate_compaction_count"), 6, "duplicate_compaction_count"),
        ]
        for state, expected_step, expected_reason in cases:
            res = rc.admit_recovery(state)
            self.assertFalse(res.ok, (expected_step, expected_reason))
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


class PausedRotationTests(unittest.TestCase):
    """AC3 — paused and rotation-due recovery."""

    def test_AC3_paused_stays_paused(self):
        res = rc.admit_recovery(_input(paused=True))
        self.assertTrue(res.may_proceed)
        self.assertEqual(res.value.admission_outcome, "pause_honored_recovery_only")

    def test_AC3_due_rotation_not_satisfied_by_compaction(self):
        res = rc.admit_recovery(_input(rotation_due=True, event_kind=rc.EVENT_KIND_COMPACTION))
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "compaction_counts_as_rotation")
        self.assertEqual(res.detail["step"], 3)

        # A proper rotation (lead handoff) applies the rotation.
        res = rc.admit_recovery(_input(rotation_due=True, event_kind=rc.EVENT_KIND_LEAD_HANDOFF))
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
        res = rc.admit_recovery(
            _input(replay_attempted=True, unknown_outcomes=("lost-1",))
        )
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "unknown_effect_replay")
        self.assertEqual(res.detail["step"], 4)


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
        ):
            res = rc.preserve_obligations(before, _obligations(**override))
            self.assertFalse(res.ok, override)
            self.assertEqual(res.reason, "obligations_changed")


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


class EvidenceReuseTests(unittest.TestCase):
    """AC9 — evidence reuse."""

    def test_AC9_evidence_reuse(self):
        existing = {"subject": "issue-1", "head": "abc", "definition_revision": "r1"}

        # Same-subject, same-head evidence is reused.
        res = rc.reuse_evidence("issue-1", "abc", "r1", existing=existing)
        self.assertTrue(res.detail["reusable"])

        # Pending CI never triggers local fallback.
        res = rc.reuse_evidence("issue-1", "abc", "r1", existing=existing, pending_ci=True)
        self.assertFalse(res.detail["fallback"])
        self.assertTrue(res.detail["pending_ci"])

        # A different head is stale and not reused.
        res = rc.reuse_evidence("issue-1", "def", "r1", existing=existing)
        self.assertFalse(res.detail["reusable"])
        self.assertEqual(res.detail["reason"], "stale_evidence")


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
