"""Focused checks for #196 lane L6: goal-run recovery wiring.

The merged goal_recovery.py (#224) is wired into goal.md (recovery procedure),
SKILL.md (recovery-anchor pointer), traycer.md (fail-closed takeover) and the
dev-state ledger (recovery keys). This file holds the named acceptance tests
AC1-AC7: ledger-compat, malformed records, round-trip, doc naming, the owner's
#196 cases through the documented path, the fail-closed takeover rule, and the
router/anchor invariants. goal_recovery.py is imported and called directly, never
edited.
"""

from __future__ import annotations

import copy
import dataclasses
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "dev" / "scripts"
SKILL_DIR = ROOT / "skills" / "dev"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import goal_recovery  # noqa: E402

from tests.test_dev_state import (  # noqa: E402
    armed_block,
    authority_block,
    goal_example,
    ledger_with,
    render_goal_run,
    run_validator,
)
import tests.test_dev_state as tds  # noqa: E402

dev_state = tds.dev_state

GOAL_MD = SKILL_DIR / "phases" / "goal.md"
SKILL_MD = SKILL_DIR / "SKILL.md"
TRAYCER_MD = SKILL_DIR / "backends" / "traycer.md"


def _section(text: str, heading: str) -> str:
    level = len(heading) - len(heading.lstrip("#"))
    start = text.index(heading + "\n")
    rest = text[start + len(heading) + 1:]
    stop = re.search(rf"^#{{1,{level}}} ", rest, re.M)
    return rest[: stop.start()] if stop else rest


def _set(block: dict, path: tuple, value) -> None:
    node = block
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value


def _checkpoint():
    result = goal_recovery.build_checkpoint_reference(
        run="goal-roundtrip",
        session="lead-1",
        event="compaction-event-1",
        adapter="claude",
        version="checkpoint-reference-v1",
        note_revision="4f3c2a1",
        freshness="2026-11-06T12:00:00Z",
        authoritative_refs=["docs/plans/goal.md@4f3c2a1"],
        coverage="top_level",
        degradation=None,
    )
    assert result.ok, result.reason
    return result.value


def _receipt():
    checkpoint = _checkpoint()
    result = goal_recovery.build_recovery_receipt(
        checkpoint, "counted_once", "restored_then_current_state_check"
    )
    assert result.ok, result.reason
    return result.value


def _obligations():
    return goal_recovery.Obligations(
        children=("child-1",),
        owed_replies=("reply-1",),
        original_request="request-1",
        responsible_party="lead-1",
        evidence=("ev-1",),
        consumed_allowances=("allow-1",),
        worker_count=1,
        defect_episode=0,
        fix_batch_count=0,
        owner_escalation=False,
    )


def recovery_block() -> dict:
    block = armed_block()
    block["obligations"] = dev_state.obligations_to_record(_obligations())
    block["custody"] = {
        "prior_session_id": "lead-1",
        "current_session_id": "lead-1",
        "claim": None,
        "outcome": "accept",
        "reason": None,
        "previous_lead_liveness": None,
    }
    block["event_ledger"] = {"seen": ["evt-1"], "duplicates": {}}
    block["recovery_receipts"] = {"compaction-event-1": _receipt().to_dict()}
    block["unknown_effects"] = {
        "pr42-merge": {"state": "unknown", "blocked": ["pr43-release"], "evidence": None},
    }
    return block


def _admit_input(ledger, event_identity="evt-1", **overrides):
    obligations = _obligations()
    base = dict(
        checkpoint=_checkpoint(),
        note_status="current",
        checkpoint_available=True,
        paused=False,
        outstanding_waits=(),
        protected_restrictions=(),
        event_identity=event_identity,
        event_kind="compaction",
        ledger=ledger,
        obligations_before=obligations,
        obligations_after=obligations,
        replay_attempted=False,
        unknown_outcomes=(),
        current_source="docs/plans/goal.md@4f3c2a1",
        approved_source="docs/plans/goal.md@4f3c2a1",
        charter_revision="rev",
        approved_charter_revision="rev",
        current_heads=("head-1",),
        recorded_heads=("head-1",),
        invalidation=(),
        authority_bindings=("lead-1",),
        policy=goal_recovery.BoundsPolicy(),
        counters=goal_recovery.RunCounters(),
        approval_time="2099-01-01T00:00:00Z",
        now="2099-01-01T10:00:00Z",
    )
    base.update(overrides)
    return goal_recovery.RecoveryInput(**base)


DEFECT_EPISODES_YAML = (
    "defect_episodes:\n"
    "  - id: ep-1\n"
    "    fix_batches: 2\n"
    "    bound: 2\n"
    "  - id: ep-2\n"
    "    fix_batches: 2\n"
    "    bound: 2\n"
)


# Review R2-3, verbatim: a `fix_batches:` line inside a diagnosis narrative.
NARRATIVE_SHADOW_YAML = (
    "defect_episodes:\n"
    "  - id: ep-1\n"
    "    fix_batches: 2\n"
    "    bound: 2\n"
    "    diagnoses:\n"
    "      - at: \"2026-11-06T12:00:00Z\"\n"
    "        what_failed: |\n"
    "          fix_batches: 0\n"
    "        decision: owner_decision\n"
    "        authorized_additional_batches: 0\n"
)


def ledger_with_episodes(episodes_yaml: str, block_yaml: str) -> str:
    return (
        "---\nschema_version: 2\nrun_id: goal-test\nrun_status: active\n"
        + episodes_yaml
        + block_yaml
        + "next_action: dispatch\n---\n"
    )


def ledger_with_defect(block_yaml: str) -> str:
    return ledger_with_episodes(DEFECT_EPISODES_YAML, block_yaml)


EPISODES = [("ep-1", 2), ("ep-2", 2)]


class TestRecoveryLedgerCompat(unittest.TestCase):
    """AC1: goal_run: null, the exact L2 16-key block and the L4 20-key block
    validate unchanged, and _GOAL_RUN_STATE_KEYS equals the template's key set."""

    def test_goal_run_null_validates_unchanged(self):
        code, stdout, stderr = run_validator(ledger_with("goal_run: null\n"))
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)

    def test_l2_sixteen_key_block_never_reaches_recovery_code(self):
        block = armed_block()
        self.assertEqual(len(block), 16)

        def boom(*_a, **_k):
            raise AssertionError("goal_recovery code reached")

        saved = dev_state._load_goal_recovery_module
        dev_state._load_goal_recovery_module = boom
        try:
            dev_state.validate_goal_run(copy.deepcopy(block))
        finally:
            dev_state._load_goal_recovery_module = saved
        code, stdout, stderr = run_validator(ledger_with(render_goal_run(block)))
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)

    def test_l4_twenty_key_block_never_reaches_recovery_code(self):
        block = authority_block()
        self.assertEqual(len(block), 20)

        def boom(*_a, **_k):
            raise AssertionError("goal_recovery code reached")

        saved = dev_state._load_goal_recovery_module
        dev_state._load_goal_recovery_module = boom
        try:
            dev_state.validate_goal_run(copy.deepcopy(block))
        finally:
            dev_state._load_goal_recovery_module = saved
        code, stdout, stderr = run_validator(ledger_with(render_goal_run(block)))
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)

    def test_state_keys_equal_the_template_key_set(self):
        documented = set(re.findall(r"^  ([a-z_]+):", goal_example(), re.M))
        allowed = set(dev_state._GOAL_ASSIGNMENT_KEYS) | set(dev_state._GOAL_RUN_STATE_KEYS)
        self.assertEqual(documented, allowed)


class TestRecoveryRecordsValidate(unittest.TestCase):
    """AC2: valid recovery records validate; each malformed field fails with a
    named goal_run.<field> error, directly and via dev_state.py --validate."""

    def test_valid_recovery_records_validate(self):
        block = recovery_block()
        dev_state.validate_goal_run(copy.deepcopy(block))
        code, stdout, stderr = run_validator(ledger_with(render_goal_run(block)))
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)

    def test_malformed_records_fail_with_named_errors(self):
        cases = [
            (("obligations",), ["not", "a", "map"], "goal_run.obligations: must be a map"),
            (("obligations", "owed_replies"), [""],
             "goal_run.obligations.owed_replies: must be a list of non-empty strings"),
            (("obligations", "owed_replies"), ["reply-1", "   "],
             "goal_run.obligations.owed_replies: must be a list of non-empty strings"),
            (("obligations", "owed_replies"), ["reply-1", 5],
             "goal_run.obligations.owed_replies: must be a list of non-empty strings"),
            (("obligations", "worker_count"), "two",
             "goal_run.obligations.worker_count: must be an integer >= 0"),
            (("obligations", "owner_escalation"), "yes",
             "goal_run.obligations.owner_escalation: must be true or false"),
            (("obligations", "fix_batch_count"), 2,
             "goal_run.obligations.fix_batch_count: must be 0 when no defect episode is named"),
            (("obligations", "defect_episode_ref"), 5,
             "goal_run.obligations.defect_episode_ref: must be an episode id or null"),
            (("event_ledger", "seen"), ["evt-1", "evt-1"],
             "goal_run.event_ledger.seen: an event identity must not be counted twice"),
            (("event_ledger", "seen"), ["evt-1", 7],
             "goal_run.event_ledger.seen: must be a list of non-empty event identities"),
            (("event_ledger", "duplicates"), {"evt-1": 0},
             "goal_run.event_ledger.duplicates: evt-1 duplicate count must be a positive integer"),
            (("event_ledger", "duplicates"), {"evt-9": 1},
             "goal_run.event_ledger.duplicates: evt-9 is not a counted event"),
            (("custody", "claim"), "maybe",
             "goal_run.custody.claim: must be 'successor', 'takeover' or null"),
            (("custody", "outcome"), "maybe",
             "goal_run.custody.outcome: must be 'accept' or 'invalid'"),
            (("custody", "reason"), "some failure",
             "goal_run.custody.reason: must be null or empty when outcome is accept"),
            (("custody", "previous_lead_liveness"), "maybe",
             "goal_run.custody.previous_lead_liveness: must be 'live', 'unknown', 'ended' or null"),
            (("unknown_effects", "pr42-merge", "state"), "maybe",
             "goal_run.unknown_effects.pr42-merge.state: must be 'unknown' or 'resolved'"),
            (("unknown_effects", "pr42-merge", "blocked"), "pr43-release",
             "goal_run.unknown_effects.pr42-merge.blocked: must be a list of non-empty strings"),
        ]
        for path, value, expected in cases:
            with self.subTest(path=path, expected=expected):
                block = recovery_block()
                _set(block, path, value)
                with self.assertRaises(dev_state.GoalRunError) as raised:
                    dev_state.validate_goal_run(block)
                self.assertEqual(str(raised.exception), expected)
                code, _, stderr = run_validator(ledger_with(render_goal_run(block)))
                self.assertEqual(code, 1, stderr)
                self.assertIn(f"FAIL: {expected}", stderr)
                self.assertNotIn("Traceback", stderr)

    def test_unknown_effect_resolved_without_evidence_fails(self):
        block = recovery_block()
        _set(block, ("unknown_effects", "pr42-merge", "state"), "resolved")
        with self.assertRaises(dev_state.GoalRunError) as raised:
            dev_state.validate_goal_run(block)
        self.assertEqual(
            str(raised.exception),
            "goal_run.unknown_effects.pr42-merge: a resolved unknown effect needs evidence",
        )
        code, _, stderr = run_validator(ledger_with(render_goal_run(block)))
        self.assertEqual(code, 1)
        self.assertIn(
            "FAIL: goal_run.unknown_effects.pr42-merge: a resolved unknown effect needs evidence",
            stderr,
        )

    def test_resolved_effect_cannot_block_dependents(self):
        block = recovery_block()
        _set(block, ("unknown_effects", "pr42-merge", "state"), "resolved")
        _set(block, ("unknown_effects", "pr42-merge", "evidence"), "inspected pr42")
        with self.assertRaises(dev_state.GoalRunError) as raised:
            dev_state.validate_goal_run(block)
        self.assertEqual(
            str(raised.exception),
            "goal_run.unknown_effects.pr42-merge.blocked: a resolved effect cannot block dependents",
        )

    def test_rejection_outcome_receipt_fails(self):
        block = recovery_block()
        record = _receipt().to_dict()
        record["admission_outcome"] = "unknown_effect_replay"
        block["recovery_receipts"] = {"compaction-event-1": record}
        with self.assertRaises(dev_state.GoalRunError) as raised:
            dev_state.validate_goal_run(block)
        self.assertEqual(
            str(raised.exception),
            "goal_run.recovery_receipts.compaction-event-1: unknown_effect_replay",
        )


def _rebuild_receipt(record: dict):
    checkpoint = goal_recovery.build_checkpoint_reference(
        run=record["run"],
        session=record["session"],
        event=record["event"],
        adapter=record["adapter"],
        version=record["version"],
        note_revision=record["note_revision"],
        freshness=record["freshness"],
        authoritative_refs=record["authoritative_refs"],
        coverage=record.get("coverage"),
        degradation=record.get("degradation"),
    )
    assert checkpoint.ok, checkpoint.reason
    return goal_recovery.build_recovery_receipt(
        checkpoint.value,
        record["event_accounting"]["result"],
        record["admission_outcome"],
    ).value


class TestRecoveryRoundTrip(unittest.TestCase):
    """AC3: records produced by goal_recovery.py validate through dev_state.py
    and rebuild equal."""

    def _round_trip(self, block):
        text = ledger_with(render_goal_run(block))
        parsed = dev_state.parse_goal_run_block(text)
        self.assertEqual(parsed, block)
        dev_state.validate_goal_run(parsed)
        code, stdout, stderr = run_validator(text)
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)
        return parsed

    def test_obligations_round_trip(self):
        obligations = _obligations()
        record = dev_state.obligations_to_record(obligations)
        block = recovery_block()
        block["obligations"] = record
        parsed = self._round_trip(block)
        rebuilt = dev_state.obligations_from_record(parsed["obligations"])
        self.assertEqual(rebuilt, obligations)
        self.assertEqual(dev_state.obligations_to_record(rebuilt), record)

    def test_event_ledger_round_trip(self):
        ledger = goal_recovery.EventLedger(seen=("evt-1",), duplicates={})
        record = dev_state.event_ledger_to_record(ledger)
        block = recovery_block()
        block["event_ledger"] = record
        parsed = self._round_trip(block)
        rebuilt = dev_state.event_ledger_from_record(parsed["event_ledger"])
        self.assertEqual(rebuilt, ledger)
        self.assertEqual(dev_state.event_ledger_to_record(rebuilt), record)

    def test_receipt_and_checkpoint_round_trip(self):
        receipt = _receipt()
        record = receipt.to_dict()
        block = recovery_block()
        block["recovery_receipts"] = {"compaction-event-1": record}
        parsed = self._round_trip(block)
        check = goal_recovery.validate_sc9_record(
            "recovery-receipt-v1", parsed["recovery_receipts"]["compaction-event-1"]
        )
        self.assertTrue(check.ok, check.reason)
        rebuilt = _rebuild_receipt(parsed["recovery_receipts"]["compaction-event-1"])
        self.assertEqual(rebuilt, receipt)


class TestObligationsCanonicalEpisode(unittest.TestCase):
    """R1-2/R2-1: the obligations snapshot binds to the canonical top-level
    defect_episodes record by 1-based ordinal + id, never a second counter."""

    def obligations(self, ordinal, ref, batches) -> dict:
        block = recovery_block()
        block["obligations"]["defect_episode"] = ordinal
        block["obligations"]["defect_episode_ref"] = ref
        block["obligations"]["fix_batch_count"] = batches
        return block

    def assert_named_failure(self, block, expected):
        with self.assertRaises(dev_state.GoalRunError) as raised:
            dev_state.validate_goal_run(copy.deepcopy(block), list(EPISODES))
        self.assertEqual(str(raised.exception), expected)
        code, _, stderr = run_validator(ledger_with_defect(render_goal_run(block)))
        self.assertEqual(code, 1)
        self.assertIn(f"FAIL: {expected}", stderr)
        self.assertNotIn("Traceback", stderr)

    def test_named_episode_with_matching_ordinal_ref_count_validates(self):
        block = self.obligations(1, "ep-1", 2)
        dev_state.validate_goal_run(copy.deepcopy(block), list(EPISODES))
        code, stdout, stderr = run_validator(ledger_with_defect(render_goal_run(block)))
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)

    def test_second_episode_ordinal_and_ref_validate(self):
        block = self.obligations(2, "ep-2", 2)
        dev_state.validate_goal_run(copy.deepcopy(block), list(EPISODES))
        code, stdout, stderr = run_validator(ledger_with_defect(render_goal_run(block)))
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)

    def test_mismatched_count_fails_directly_and_via_cli(self):
        self.assert_named_failure(
            self.obligations(1, "ep-1", 0),
            "goal_run.obligations.fix_batch_count: must equal the episode's fix_batches (2)",
        )

    def test_ref_ordinal_mismatch_fails(self):
        self.assert_named_failure(
            self.obligations(2, "ep-1", 2),
            "goal_run.obligations.defect_episode_ref: ep-1 does not match the episode at ordinal 2 (ep-2)",
        )

    def test_ordinal_out_of_range_fails(self):
        self.assert_named_failure(
            self.obligations(3, "ep-3", 2),
            "goal_run.obligations.defect_episode: 3 is not a recorded defect episode",
        )

    def test_null_ref_with_nonzero_ordinal_fails(self):
        self.assert_named_failure(
            self.obligations(1, None, 2),
            "goal_run.obligations.defect_episode_ref: must name the episode when defect_episode is non-zero",
        )

    def test_zero_ordinal_requires_null_ref(self):
        self.assert_named_failure(
            self.obligations(0, "ep-1", 0),
            "goal_run.obligations.defect_episode_ref: must be null when defect_episode is 0",
        )

    def test_zero_ordinal_requires_zero_count(self):
        self.assert_named_failure(
            self.obligations(0, None, 2),
            "goal_run.obligations.fix_batch_count: must be 0 when no defect episode is named",
        )

    def test_non_default_episode_round_trips_losslessly(self):
        obligations = goal_recovery.Obligations(
            children=("child-1",),
            owed_replies=("reply-1",),
            original_request="request-1",
            responsible_party="lead-1",
            evidence=("ev-1",),
            consumed_allowances=("allow-1",),
            worker_count=1,
            defect_episode=2,
            fix_batch_count=2,
            owner_escalation=False,
        )
        record = dev_state.obligations_to_record(obligations, list(EPISODES))
        self.assertEqual(record["defect_episode"], 2)
        self.assertEqual(record["defect_episode_ref"], "ep-2")
        block = recovery_block()
        block["obligations"] = record
        text = ledger_with_defect(render_goal_run(block))
        parsed = dev_state.parse_goal_run_block(text)
        episodes = dev_state.parse_defect_episodes(text)
        dev_state.validate_goal_run(parsed, episodes)
        rebuilt = dev_state.obligations_from_record(parsed["obligations"], episodes)
        self.assertEqual(rebuilt, obligations)
        self.assertEqual(rebuilt.defect_episode, 2)
        code, stdout, stderr = run_validator(text)
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)

    def test_changed_episode_is_not_equal_after_round_trip(self):
        ep1 = goal_recovery.Obligations(defect_episode=1, fix_batch_count=2)
        ep2 = goal_recovery.Obligations(defect_episode=2, fix_batch_count=2)
        rec1 = dev_state.obligations_to_record(ep1)
        rec1["defect_episode_ref"] = "ep-1"
        rec2 = dev_state.obligations_to_record(ep2)
        rec2["defect_episode_ref"] = "ep-2"
        self.assertNotEqual(rec1["defect_episode"], rec2["defect_episode"])
        self.assertEqual(dev_state.obligations_from_record(rec1, list(EPISODES)), ep1)
        self.assertEqual(dev_state.obligations_from_record(rec2, list(EPISODES)), ep2)
        changed = goal_recovery.preserve_obligations(ep1, ep2)
        self.assertFalse(changed.ok)
        self.assertEqual(changed.reason, "obligations_changed")
        self.assertIn("defect_episode", changed.detail["changed"])
        admitted = goal_recovery.admit_recovery(_admit_input(
            goal_recovery.EventLedger(), obligations_before=ep1, obligations_after=ep2
        ))
        self.assertFalse(admitted.ok)
        self.assertEqual(admitted.reason, "obligations_changed")
        self.assertEqual(admitted.detail["step"], 4)
        self.assertEqual(admitted.detail["changed"], ["defect_episode"])

    def test_narrative_shadow_is_not_read_as_the_counter(self):
        """R2-3: the false lower count in the narrative never validates."""
        shadowed = self.obligations(1, "ep-1", 0)
        text = ledger_with_episodes(NARRATIVE_SHADOW_YAML, render_goal_run(shadowed))
        episodes = dev_state.parse_defect_episodes(text)
        self.assertEqual([(e.id, e.fix_batches, e.bound) for e in episodes], [("ep-1", 2, 2)])
        self.assertIn("          fix_batches: 0", episodes[0].body)
        expected = "goal_run.obligations.fix_batch_count: must equal the episode's fix_batches (2)"
        with self.assertRaises(dev_state.GoalRunError) as raised:
            dev_state.validate_goal_run(dev_state.parse_goal_run_block(text), episodes)
        self.assertEqual(str(raised.exception), expected)
        code, _, stderr = run_validator(text)
        self.assertEqual(code, 1)
        self.assertIn(f"FAIL: {expected}", stderr)
        self.assertNotIn("Traceback", stderr)
        honest = ledger_with_episodes(
            NARRATIVE_SHADOW_YAML, render_goal_run(self.obligations(1, "ep-1", 2))
        )
        code, stdout, stderr = run_validator(honest)
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)

    def test_unsupported_episode_shapes_fail_closed(self):
        """R2-3: duplicate or ambiguous fields and unsupported shapes are named
        errors, never a silently missed or shadowed counter."""
        cases = (
            ("defect_episodes:\n  - fix_batches: 2\n    id: ep-1\n",
             "defect_episodes: each episode must open with '- id:' (line 6)"),
            ("defect_episodes:\n  - id: ep-1\n    fix_batches: 2\n    fix_batches: 0\n",
             "defect_episodes: duplicate fix_batches for episode ep-1 (line 8)"),
            ("defect_episodes:\n  - id: ep-1\n    id: ep-2\n    fix_batches: 2\n",
             "defect_episodes: duplicate id for episode ep-1 (line 7)"),
            ("defect_episodes:\n  - id: ep-1\n   fix_batches: 2\n",
             "defect_episodes: unexpected indentation on line 7",
             "unexpected indentation on line 6"),
            ("defect_episodes:\n  - id: ep-1\n    fix_batches: two\n",
             "defect_episodes: fix_batches for episode ep-1 must be an integer >= 0 (line 7)"),
            ("defect_episodes:\n  - id: ep-1\n    fix_batches: 2\n  - id: ep-1\n    fix_batches: 2\n",
             "defect_episodes: duplicate episode id ep-1"),
            ("defect_episodes: [ep-1]\n",
             "defect_episodes: must be a block list of episodes (line 5)",
             "flow mapping syntax detected on line 4"),
        )
        block = render_goal_run(self.obligations(1, "ep-1", 2))
        for episodes_yaml, expected, *cli in cases:
            with self.subTest(expected=expected):
                text = ledger_with_episodes(episodes_yaml, block)
                with self.assertRaises(dev_state.GoalRunError) as raised:
                    dev_state.parse_defect_episodes(text)
                self.assertEqual(str(raised.exception), expected)
                code, _, stderr = run_validator(text)
                self.assertEqual(code, 1)
                # Two shapes are refused earlier, by the flat frontmatter reader.
                self.assertIn(f"FAIL: {cli[0] if cli else expected}", stderr)
                self.assertNotIn("Traceback", stderr)


TWO_BATCH_EPISODES_YAML = (
    "defect_episodes:\n"
    "  - id: ep-1\n"
    "    opened_at: 2026-11-06T10:00:00Z\n"
    "    fix_batches: 2\n"
    "    bound: 2\n"
    "    diagnoses:\n"
    "      - at: 2026-11-06T12:00:00Z\n"
    "        what_failed: |\n"
    "          batches 1 and 2 did not clear the criterion\n"
    "        decision: lead_diagnosis\n"
    "        authorized_additional_batches: 0\n"
)


class TestDuplicateHandoffKeepsTheCanonicalEpisode(unittest.TestCase):
    """R2-1 binding regression: after two fix batches, a duplicate recovery or
    lead handoff leaves the canonical episode's identity, fix_batches, bound and
    diagnoses unchanged, and grants no extra batch."""

    def ledger(self, obligations, event_ledger) -> str:
        block = recovery_block()
        episodes = dev_state.parse_defect_episodes(
            ledger_with_episodes(TWO_BATCH_EPISODES_YAML, "")
        )
        block["obligations"] = dev_state.obligations_to_record(obligations, episodes)
        block["event_ledger"] = dev_state.event_ledger_to_record(event_ledger)
        return ledger_with_episodes(TWO_BATCH_EPISODES_YAML, render_goal_run(block))

    def test_duplicate_recovery_and_handoff_leave_the_episode_unchanged(self):
        snapshot = dataclasses.replace(_obligations(), defect_episode=1, fix_batch_count=2)
        first = goal_recovery.admit_recovery(_admit_input(
            goal_recovery.EventLedger(), obligations_before=snapshot, obligations_after=snapshot
        ))
        self.assertTrue(first.ok, first.reason)
        before_text = self.ledger(snapshot, first.detail["ledger"])
        before = dev_state.parse_defect_episodes(before_text)
        self.assertEqual([(e.id, e.fix_batches, e.bound) for e in before], [("ep-1", 2, 2)])

        ledger = first.detail["ledger"]
        handoff = dict(
            successor="lead-2", transfer_acknowledged=True, native_session_id="lead-2-session"
        )
        for kind, extra in (("compaction", {}), ("lead_handoff", handoff)):
            with self.subTest(kind=kind):
                parsed = dev_state.parse_goal_run_block(before_text)
                restored = dev_state.obligations_from_record(parsed["obligations"], before)
                self.assertEqual(restored, snapshot)
                again = goal_recovery.admit_recovery(_admit_input(
                    ledger, event_kind=kind,
                    obligations_before=restored, obligations_after=restored, **extra,
                ))
                self.assertTrue(again.ok, again.reason)
                self.assertFalse(again.detail["event_counted"])
                ledger = again.detail["ledger"]
                after_text = self.ledger(restored, ledger)
                after = dev_state.parse_defect_episodes(after_text)
                self.assertEqual(after, before)
                parsed_after = dev_state.parse_goal_run_block(after_text)
                dev_state.validate_goal_run(parsed_after, after)
                self.assertEqual(parsed_after["obligations"], parsed["obligations"])
                code, stdout, stderr = run_validator(after_text)
                self.assertEqual(code, 0, stderr)
                self.assertIn("OK:", stdout)

        for reset in (
            dataclasses.replace(snapshot, fix_batch_count=0),
            dataclasses.replace(snapshot, defect_episode=0, fix_batch_count=0),
        ):
            with self.subTest(reset=reset):
                refused = goal_recovery.admit_recovery(_admit_input(
                    ledger, obligations_before=snapshot, obligations_after=reset
                ))
                self.assertFalse(refused.ok)
                self.assertEqual(refused.reason, "obligations_changed")
                self.assertEqual(refused.detail["step"], 4)


class TestRecoveryDocNaming(unittest.TestCase):
    """AC4: the docs name only real goal_recovery public functions/outcomes; the
    recovery section no longer says "existing Dev gates govern" for recovery."""

    def setUp(self):
        self.goal = GOAL_MD.read_text(encoding="utf-8")
        self.traycer = TRAYCER_MD.read_text(encoding="utf-8")

    def test_docs_name_only_real_goal_recovery_api(self):
        public = set(goal_recovery.__all__)
        for text in (self.goal, SKILL_MD.read_text(), self.traycer):
            for name in set(re.findall(r"`([a-z_][a-z0-9_]*)`", text)) & public:
                self.assertTrue(callable(getattr(goal_recovery, name)), name)
        for name in (
            "admit_recovery",
            "account_event",
            "preserve_obligations",
            "classify_note",
            "reconcile_unknown_effect",
            "reuse_evidence",
            "classify_lineage",
        ):
            self.assertIn(name, public)
            self.assertTrue(callable(getattr(goal_recovery, name)), name)

    def test_recovery_section_drops_the_placeholder(self):
        section = _section(self.goal, "## Recovery and resume")
        self.assertNotIn("existing Dev gates govern", section)
        self.assertNotIn("existing recovery procedure", section)
        for name in (
            "admit_recovery",
            "account_event",
            "preserve_obligations",
            "classify_note",
            "reconcile_unknown_effect",
            "reuse_evidence",
        ):
            self.assertIn(f"`{name}`", section)

    def test_restate_owed_replies_first_precedes_admit_recovery(self):
        section = _section(self.goal, "## Recovery and resume")
        self.assertLess(
            section.index("Restate owed replies first"), section.index("`admit_recovery`")
        )

    def test_gv_placeholder_and_l4_merge_step_unchanged(self):
        govern = _section(self.goal, "## Where the existing Dev gates govern")
        self.assertIn("- **GV:** completion stays a claim", govern)
        step7 = _section(self.goal, "## 7. Merges and gate disposition (D2, D7.2)")
        self.assertIn("`decide_merge(", step7)
        self.assertIn("`carry_grant`", step7)

    def test_express_issue_confirmation_not_described_as_delegated(self):
        section = _section(self.goal, "## Recovery and resume")
        self.assertNotIn("express", section.lower())


class TestOwnerCasesThroughTheDocumentedPath(unittest.TestCase):
    """AC5: the owner's #196 cases through the documented path, calling
    goal_recovery directly (no edits to it), linked to the doc sentences."""

    def setUp(self):
        self.goal = GOAL_MD.read_text(encoding="utf-8")

    def test_lost_response_inspects_destination_and_never_replays(self):
        section = _section(self.goal, "## Recovery and resume")
        self.assertIn("`reconcile_unknown_effect`", section)
        self.assertIn("never replayed", section)
        unresolved = goal_recovery.reconcile_unknown_effect("unknown")
        self.assertTrue(unresolved.ok)
        self.assertEqual(unresolved.detail["action"], "inspect_destination_first")
        self.assertTrue(unresolved.detail["blocked"])
        replay = goal_recovery.reconcile_unknown_effect("unknown", retry=True)
        self.assertFalse(replay.ok)
        self.assertEqual(replay.reason, "unknown_effect_replay")

    def test_duplicate_event_keeps_original_obligations(self):
        section = _section(self.goal, "## Recovery and resume")
        self.assertIn("`account_event`", section)
        self.assertIn("`preserve_obligations`", section)
        self.assertIn("never re-account the same delivery", section)
        ledger = goal_recovery.EventLedger()
        first = goal_recovery.account_event(ledger, "evt-1", "compaction")
        self.assertTrue(first.detail["counted"])
        second = goal_recovery.account_event(first.value, "evt-1", "compaction")
        self.assertTrue(second.ok)
        self.assertFalse(second.detail["counted"])
        self.assertTrue(second.detail["duplicate"])
        before = after = _obligations()
        preserved = goal_recovery.preserve_obligations(before, after)
        self.assertTrue(preserved.ok)
        changed = goal_recovery.preserve_obligations(
            before, goal_recovery.Obligations(worker_count=2)
        )
        self.assertFalse(changed.ok)
        self.assertEqual(changed.reason, "obligations_changed")

    def test_admit_recovery_counts_once_then_records_a_duplicate(self):
        first = goal_recovery.admit_recovery(_admit_input(goal_recovery.EventLedger()))
        self.assertTrue(first.ok, first.reason)
        self.assertTrue(first.detail["event_counted"])
        self.assertEqual(first.detail["ledger"].seen, ("evt-1",))
        self.assertEqual(dict(first.detail["ledger"].duplicates), {})

        second = goal_recovery.admit_recovery(_admit_input(first.detail["ledger"]))
        self.assertTrue(second.ok, second.reason)
        self.assertFalse(second.detail["event_counted"])
        self.assertEqual(dict(second.detail["ledger"].duplicates), {"evt-1": 1})

    def test_pending_ci_is_not_a_local_fallback_trigger(self):
        section = _section(self.goal, "## Recovery and resume")
        self.assertIn("`reuse_evidence`", section)
        self.assertIn("pending CI", section)
        result = goal_recovery.reuse_evidence(
            "subject-1", "head-1", "rev-1", pending_ci=True
        )
        self.assertTrue(result.ok)
        self.assertFalse(result.detail["fallback"])

    def test_stale_note_never_overrides_pause(self):
        section = _section(self.goal, "## Recovery and resume")
        self.assertIn("`classify_note`", section)
        self.assertIn("never overrides a pause", section)
        stale_over_pause = goal_recovery.classify_note("stale", paused=True)
        self.assertFalse(stale_over_pause.ok)
        self.assertEqual(stale_over_pause.reason, "resume_overrides_pause")

    def test_nothing_renewed_two_automatic_batches_then_lead_diagnosis(self):
        section = _section(self.goal, "## Recovery and resume")
        self.assertIn("Two automatic fix batches, then lead diagnosis", section)
        self.assertIn("never resets the defect episode", section)


class TestTakeoverFailClosed(unittest.TestCase):
    """AC6: the fail-closed takeover rule is stated and classify_lineage backs it."""

    def test_traycer_md_states_the_fail_closed_rule(self):
        text = TRAYCER_MD.read_text(encoding="utf-8")
        self.assertIn("**Goal-run takeover (fail closed).**", text)
        self.assertIn("`classify_lineage`", text)
        self.assertIn("A live or unknown previous lead blocks the takeover", text)
        self.assertIn(
            "verified ended previous lead with a valid `successor` or `takeover` claim may proceed",
            text,
        )
        self.assertIn("`previous_lead_liveness`", text)
        self.assertIn("`agent list`", text)

    def test_classify_lineage_distinguishes_custody(self):
        unknown = goal_recovery.classify_lineage("old-1", None, None)
        self.assertTrue(unknown.ok)
        self.assertEqual(unknown.value, "custody_unknown")
        takeover = goal_recovery.classify_lineage("old-1", "new-1", "takeover")
        self.assertTrue(takeover.ok)
        self.assertEqual(takeover.value, "takeover")
        conflict = goal_recovery.classify_lineage("old-1", "old-1", "takeover")
        self.assertFalse(conflict.ok)
        self.assertEqual(conflict.reason, "lineage_claim_conflict")

    def custody(self, prior, current, claim, outcome, liveness) -> dict:
        block = recovery_block()
        block["custody"] = {
            "prior_session_id": prior,
            "current_session_id": current,
            "claim": claim,
            "outcome": outcome,
            "reason": None,
            "previous_lead_liveness": liveness,
        }
        return block

    def assert_takeover_failure(self, block, expected):
        with self.assertRaises(dev_state.GoalRunError) as raised:
            dev_state.validate_goal_run(copy.deepcopy(block))
        self.assertEqual(str(raised.exception), expected)
        code, _, stderr = run_validator(ledger_with(render_goal_run(block)))
        self.assertEqual(code, 1)
        self.assertIn(f"FAIL: {expected}", stderr)
        self.assertNotIn("Traceback", stderr)

    def test_live_or_unknown_previous_lead_blocks_takeover(self):
        expected = "goal_run.custody.previous_lead_liveness: a takeover needs the previous lead verified ended"
        for liveness in ("live", "unknown", None):
            with self.subTest(liveness=liveness):
                self.assert_takeover_failure(
                    self.custody("old-1", "new-1", "takeover", "accept", liveness), expected
                )

    def test_takeover_needs_an_explicit_claim(self):
        expected = "goal_run.custody.claim: a takeover needs an explicit custody claim"
        self.assert_takeover_failure(
            self.custody("old-1", "new-1", None, "accept", "ended"), expected
        )

    def test_accept_needs_nonempty_session_ids(self):
        for prior, current, field in (
            (None, "new-1", "prior_session_id"),
            ("old-1", None, "current_session_id"),
            (None, None, "prior_session_id"),
        ):
            with self.subTest(prior=prior, current=current):
                expected = f"goal_run.custody.{field}: accept needs nonempty prior and current session ids"
                self.assert_takeover_failure(
                    self.custody(prior, current, "takeover", "accept", "ended"), expected
                )

    def test_same_session_resume_with_a_claim_is_refused(self):
        expected = "goal_run.custody.claim: a same-session resume cannot carry a custody claim"
        self.assert_takeover_failure(
            self.custody("lead-1", "lead-1", "takeover", "accept", "ended"), expected
        )

    def test_review_r2_2_counterexamples_are_refused(self):
        """The four records that validated at fa77b23 (direct and CLI exit 0)."""
        cases = (
            ((None, "new", "takeover", "accept", "live"),
             "goal_run.custody.prior_session_id: accept needs nonempty prior and current session ids"),
            ((None, None, "takeover", "accept", None),
             "goal_run.custody.prior_session_id: accept needs nonempty prior and current session ids"),
            (("old", None, "takeover", "accept", "ended"),
             "goal_run.custody.current_session_id: accept needs nonempty prior and current session ids"),
            (("old", "new", None, "accept", "ended"),
             "goal_run.custody.claim: a takeover needs an explicit custody claim"),
        )
        for args, expected in cases:
            with self.subTest(args=args):
                self.assert_takeover_failure(self.custody(*args), expected)

    def test_known_ended_takeover_with_either_claim_validates(self):
        for claim in ("successor", "takeover"):
            with self.subTest(claim=claim):
                block = self.custody("old", "new", claim, "accept", "ended")
                dev_state.validate_goal_run(copy.deepcopy(block))
                code, stdout, stderr = run_validator(ledger_with(render_goal_run(block)))
                self.assertEqual(code, 0, stderr)
                self.assertIn("OK:", stdout)

    def test_custody_unknown_is_recordable_only_as_not_accepted(self):
        block = self.custody("old", None, None, "invalid", None)
        block["custody"]["reason"] = "custody_unknown"
        dev_state.validate_goal_run(copy.deepcopy(block))
        code, stdout, stderr = run_validator(ledger_with(render_goal_run(block)))
        self.assertEqual(code, 0, stderr)

    def test_refused_lineage_must_carry_the_classify_lineage_reason(self):
        block = self.custody("old", "old", "takeover", "invalid", None)
        block["custody"]["reason"] = "something else"
        self.assert_takeover_failure(block, "goal_run.custody.reason: does not match classify_lineage")
        block["custody"]["reason"] = "lineage_claim_conflict"
        dev_state.validate_goal_run(copy.deepcopy(block))

    def test_verified_ended_previous_lead_proceeds(self):
        block = self.custody("old-1", "new-1", "takeover", "accept", "ended")
        dev_state.validate_goal_run(copy.deepcopy(block))
        code, stdout, stderr = run_validator(ledger_with(render_goal_run(block)))
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)

    def test_same_session_resume_needs_no_liveness(self):
        block = self.custody("lead-1", "lead-1", None, "accept", None)
        dev_state.validate_goal_run(copy.deepcopy(block))
        code, stdout, stderr = run_validator(ledger_with(render_goal_run(block)))
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)


class TestRouterAndSkillAnchor(unittest.TestCase):
    """AC7: the router still reads seven request types; the SKILL.md recovery
    anchor is exactly the pointer line."""

    def test_router_still_has_seven_request_types(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        lines = text.splitlines()
        header = "| Type | Criteria | Path |"
        start = lines.index(header)
        rows = []
        for line in lines[start + 2:]:
            if not line.startswith("|"):
                break
            rows.append(line)
        self.assertEqual(len(rows), 7)

    def test_skill_anchor_points_goal_runs_at_goal_recovery_section(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertIn(
            "For a goal run, recovery follows the **Recovery and resume** section of "
            "the goal-run phase.",
            text,
        )
        self.assertIn("The lead is the sole ledger writer.", text)


if __name__ == "__main__":
    unittest.main()
