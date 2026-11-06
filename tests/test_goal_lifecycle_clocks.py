"""Focused checks for #196 lane L7: D7.1 lifecycle clocks.

D7.1 (SDP l.518-533) is the owner's settled lifecycle-clock disposition, and
nothing in the merged code stated it. This lane states it as procedure in
``phases/goal.md``, gives the Dev's own context-reset count one additive
ledger home (``goal_run.context_resets``), and pins both with named tests
AC1-AC5: ledger-compat, count validation, the duplicate compaction that adds
no count, the doc assertions, and goal.md's structure.

``goal_run.py``, ``goal_recovery.py`` and ``goal_authority.py`` are imported
and called, never edited. This file reads no git history and imports no other
test module, so it holds under a shallow checkout and under any collection
order: ``tests/test_goal_recovery.py`` replaces the ``sys.modules`` entry for
``goal_recovery`` at import time, and a module that captured the earlier
object would then fail an ``isinstance`` check against the newer one.
"""

from __future__ import annotations

import copy
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "dev" / "scripts"
SKILL_DIR = ROOT / "skills" / "dev"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

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
TEMPLATE = SKILL_DIR / "templates" / "DEV_STATE_TEMPLATE.md"

# A Foreman clock value field would name the orchestrator clock or one of its
# prepare / retire / hard-stop values, or one of the two idle timers.
FOREMAN_CLOCK_FIELD = re.compile(
    r"foreman|orchestrat|prepare|retire|hard_?stop|idle|timer|clock|timeout|deadline",
    re.I,
)


def _sections(text: str) -> list[tuple[str, str]]:
    """Split markdown into (heading, body) pairs for every heading level."""
    parts = re.split(r"^(#{1,6} .*)$", text, flags=re.M)
    return [(parts[i].strip(), parts[i + 1]) for i in range(1, len(parts), 2)]


def _top_level_section(text: str, heading: str) -> str:
    """The body of the given top-level (``## ``) section."""
    match = re.search(
        rf"^{re.escape(heading)}\s*\n(.*?)(?=^## )", text, flags=re.M | re.S
    )
    assert match is not None, f"section not found: {heading}"
    return match.group(1)


def _goal_lifecycle_section() -> str:
    return _top_level_section(GOAL_MD.read_text(), "## Lifecycle clocks")


def _template_goal_run_section() -> str:
    return _top_level_section(
        TEMPLATE.read_text(), "## Goal run record schema (Issue #193)"
    )


def _template_lifecycle_counters_section() -> str:
    """The Lifecycle clock counters subsection of the goal-run schema."""
    section = _template_goal_run_section()
    match = re.search(
        r"\*\*Lifecycle clock counters \(Issue #196, D7\.1\)\.\*\*\s*(.*?)(?=\n\n\*\*|\Z)",
        section,
        re.S,
    )
    assert match is not None, "the lifecycle clock counters subsection is missing"
    return match.group(1)


# The five L6 recovery records, written as literal ledger records. They are
# literal on purpose: dev_state's own loader and another module can end up
# holding different goal_recovery module objects (tests/test_goal_recovery.py
# replaces the sys.modules entry at import time), so any call that isinstance-
# checks a goal_recovery class - obligations_to_record - depends on import
# order. Literal records have no module identity to disagree about.
L6_OBLIGATIONS = {
    "children": ["child-1"],
    "owed_replies": ["reply-1"],
    "original_request": "request-1",
    "responsible_party": "lead-1",
    "evidence": ["ev-1"],
    "consumed_allowances": ["allow-1"],
    "worker_count": 1,
    "defect_episode": 0,
    "defect_episode_ref": None,
    "fix_batch_count": 0,
    "owner_escalation": False,
}
L6_CUSTODY = {
    "prior_session_id": "lead-1",
    "current_session_id": "lead-1",
    "claim": None,
    "outcome": "accept",
    "reason": None,
    "previous_lead_liveness": None,
}
L6_EVENT_LEDGER = {"seen": ["evt-1"], "duplicates": {}}
L6_RECOVERY_RECEIPTS = {
    "compaction-event-1": {
        "run": "goal-roundtrip",
        "session": "lead-1",
        "event": "compaction-event-1",
        "adapter": "claude",
        "version": "checkpoint-reference-v1",
        "note_revision": "4f3c2a1",
        "freshness": "2026-11-06T12:00:00Z",
        "authoritative_refs": ["docs/plans/goal.md@4f3c2a1"],
        "coverage": "top_level",
        "degradation": None,
        "event_accounting": {"result": "counted_once"},
        "admission_outcome": "restored_then_current_state_check",
    }
}
L6_UNKNOWN_EFFECTS = {
    "pr42-merge": {"state": "unknown", "blocked": ["pr43-release"], "evidence": None},
}


def l6_block() -> dict:
    """The exact L6 25-key block: the L4 20-key block plus the five recovery
    keys, written as literal ledger records."""
    block = copy.deepcopy(authority_block())
    block["obligations"] = copy.deepcopy(L6_OBLIGATIONS)
    block["custody"] = copy.deepcopy(L6_CUSTODY)
    block["event_ledger"] = copy.deepcopy(L6_EVENT_LEDGER)
    block["recovery_receipts"] = copy.deepcopy(L6_RECOVERY_RECEIPTS)
    block["unknown_effects"] = copy.deepcopy(L6_UNKNOWN_EFFECTS)
    return block


def _context_resets_block(measured, count) -> dict:
    block = armed_block()
    block["context_resets"] = {"measured": measured, "count": count}
    return block


class TestLifecycleClockLedgerCompat(unittest.TestCase):
    """AC1: goal_run: null and the exact L2 16-key, L4 20-key and L6 25-key
    blocks validate unchanged, and the key-pin equals the template's key set."""

    def test_goal_run_null_validates_unchanged(self):
        code, stdout, stderr = run_validator(ledger_with("goal_run: null\n"))
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)

    def _never_reaches_l7_code(self, block):
        """The L7 validator is a pure check with no import, so the pre-L7
        property is that it is handed no record to validate."""
        original = dev_state._validate_goal_context_resets
        observed = []

        def spy(record):
            observed.append(record.get("context_resets"))
            return original(record)

        dev_state._validate_goal_context_resets = spy
        try:
            dev_state.validate_goal_run(copy.deepcopy(block))
        finally:
            dev_state._validate_goal_context_resets = original
        self.assertEqual(observed, [None])

    def test_l2_sixteen_key_block_validates_unchanged(self):
        block = armed_block()
        self.assertEqual(len(block), 16)
        self._never_reaches_l7_code(block)
        code, stdout, stderr = run_validator(ledger_with(render_goal_run(block)))
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)

    def test_l4_twenty_key_block_validates_unchanged(self):
        block = authority_block()
        self.assertEqual(len(block), 20)
        self._never_reaches_l7_code(block)
        code, stdout, stderr = run_validator(ledger_with(render_goal_run(block)))
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)

    def test_l6_twenty_five_key_block_validates_unchanged(self):
        block = l6_block()
        self.assertEqual(len(block), 25)
        self._never_reaches_l7_code(block)
        code, stdout, stderr = run_validator(ledger_with(render_goal_run(block)))
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)

    def test_absent_and_null_context_resets_validate_unchanged(self):
        block = armed_block()
        self.assertNotIn("context_resets", block)
        dev_state.validate_goal_run(copy.deepcopy(block))
        nulls = copy.deepcopy(block)
        nulls["context_resets"] = None
        dev_state.validate_goal_run(nulls)
        code, stdout, stderr = run_validator(ledger_with(render_goal_run(nulls)))
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)

    def test_state_keys_equal_the_template_key_set(self):
        documented = set(re.findall(r"^  ([a-z_]+):", goal_example(), re.M))
        allowed = set(dev_state._GOAL_ASSIGNMENT_KEYS) | set(dev_state._GOAL_RUN_STATE_KEYS)
        self.assertEqual(documented, allowed)
        self.assertIn("context_resets", documented)


class TestContextResetCountValidation(unittest.TestCase):
    """AC2: the count shape is closed. A measured count is an integer >= 0; an
    unmeasured count is `unknown`, never 0. Every malformation fails with a
    named goal_run.<field> error, directly and via dev_state.py --validate."""

    def _assert_named_failure(self, block, expected):
        with self.assertRaises(dev_state.GoalRunError) as raised:
            dev_state.validate_goal_run(copy.deepcopy(block))
        self.assertEqual(str(raised.exception), expected)
        code, _, stderr = run_validator(ledger_with(render_goal_run(block)))
        self.assertEqual(code, 1)
        self.assertIn(f"FAIL: {expected}", stderr)
        self.assertNotIn("Traceback", stderr)
        self.assertNotIn("malformed block", stderr)

    def test_measured_counts_validate(self):
        for count in (0, 1, 7):
            block = _context_resets_block(True, count)
            dev_state.validate_goal_run(copy.deepcopy(block))
            code, stdout, stderr = run_validator(ledger_with(render_goal_run(block)))
            self.assertEqual(code, 0, stderr)
            self.assertIn("OK:", stdout)

    def test_unmeasured_unknown_validates(self):
        block = _context_resets_block(False, "unknown")
        dev_state.validate_goal_run(copy.deepcopy(block))
        code, stdout, stderr = run_validator(ledger_with(render_goal_run(block)))
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)

    def test_zero_when_unmeasured_is_refused(self):
        self._assert_named_failure(
            _context_resets_block(False, 0),
            "goal_run.context_resets.count: unmeasured context resets must be unknown, never 0",
        )

    def test_any_other_number_when_unmeasured_is_refused(self):
        self._assert_named_failure(
            _context_resets_block(False, 2),
            "goal_run.context_resets.count: unmeasured context resets must be unknown, never a number",
        )

    def test_unknown_when_measured_is_refused(self):
        self._assert_named_failure(
            _context_resets_block(True, "unknown"),
            "goal_run.context_resets.count: measured context resets must be an integer >= 0",
        )

    def test_negative_bool_and_wrong_types_are_refused(self):
        for count in (-1, True, False, 1.5, "two", None, [1]):
            with self.subTest(count=count):
                self._assert_named_failure(
                    _context_resets_block(True, count),
                    "goal_run.context_resets.count: measured context resets must be an integer >= 0",
                )

    def test_bool_is_not_an_unmeasured_count(self):
        self._assert_named_failure(
            _context_resets_block(False, True),
            "goal_run.context_resets.count: unmeasured context resets must be unknown, never a number",
        )

    def test_string_count_when_unmeasured_is_refused(self):
        self._assert_named_failure(
            _context_resets_block(False, "two"),
            "goal_run.context_resets.count: unmeasured context resets must be unknown",
        )

    def test_non_boolean_measured_is_refused(self):
        self._assert_named_failure(
            _context_resets_block("yes", 0),
            "goal_run.context_resets.measured: must be true or false",
        )

    def test_unknown_field_is_refused(self):
        block = _context_resets_block(True, 0)
        block["context_resets"]["foreman_clock"] = 4
        self._assert_named_failure(
            block, "goal_run.context_resets.foreman_clock: unknown context_resets field"
        )

    def test_missing_fields_are_refused(self):
        block = armed_block()
        block["context_resets"] = {"count": 0}
        self._assert_named_failure(
            block, "goal_run.context_resets.measured: missing required field"
        )
        block = armed_block()
        block["context_resets"] = {"measured": True}
        self._assert_named_failure(
            block, "goal_run.context_resets.count: missing required field"
        )

    def test_non_map_is_refused(self):
        block = armed_block()
        block["context_resets"] = 3
        self._assert_named_failure(block, "goal_run.context_resets: must be a map")

    def test_empty_map_is_refused(self):
        block = armed_block()
        block["context_resets"] = {}
        self._assert_named_failure(
            block, "goal_run.context_resets.measured: missing required field"
        )

    def test_empty_string_count_is_refused(self):
        self._assert_named_failure(
            _context_resets_block(True, ""),
            "goal_run.context_resets.count: measured context resets must be an integer >= 0",
        )
        self._assert_named_failure(
            _context_resets_block(False, ""),
            "goal_run.context_resets.count: unmeasured context resets must be unknown",
        )


class TestDuplicateCompactionAddsNoCount(unittest.TestCase):
    """AC3: through goal_recovery.account_event, a first compaction is
    counted_once and a duplicate notice of it adds no count, so the documented
    count rises by one only.

    The module comes from dev_state's own loader, never from a module-level
    import, so this test uses the same goal_recovery object dev_state will
    validate with, whatever order the suite is collected in."""

    @staticmethod
    def recovery():
        return dev_state._load_goal_recovery_module()

    def test_first_compaction_is_counted_once(self):
        recovery = self.recovery()
        ledger = recovery.EventLedger(seen=(), duplicates={})
        result = recovery.account_event(ledger, "compaction-1", "compaction")
        self.assertEqual(result.outcome, "accept")
        self.assertEqual(result.detail["result"], "counted_once")
        self.assertTrue(result.detail["counted"])
        self.assertFalse(result.detail["duplicate"])

    def test_duplicate_notice_adds_no_count(self):
        recovery = self.recovery()
        ledger = recovery.EventLedger(seen=(), duplicates={})
        first = recovery.account_event(ledger, "compaction-1", "compaction")
        second = recovery.account_event(first.value, "compaction-1", "compaction")
        self.assertEqual(second.outcome, "accept")
        self.assertFalse(second.detail["counted"])
        self.assertTrue(second.detail["duplicate"])
        # The count rises by one only: the identity is still counted once.
        counted = sum(
            1 for identity in second.value.seen if identity == "compaction-1"
        )
        self.assertEqual(counted, 1)

    def test_double_counted_identity_is_refused(self):
        recovery = self.recovery()
        ledger = recovery.EventLedger(
            seen=("compaction-1", "compaction-1"), duplicates={}
        )
        result = recovery.account_event(ledger, "compaction-1", "compaction")
        self.assertEqual(result.outcome, "invalid")
        self.assertEqual(result.reason, "duplicate_compaction_count")

    def test_two_notices_of_one_compaction_yield_a_count_of_one(self):
        """The documented rule: raise the count only on counted_once. Two
        notices of one compaction therefore record a count of 1, and that
        ledger validates."""
        recovery = self.recovery()
        ledger = recovery.EventLedger(seen=(), duplicates={})
        count = 0
        for _notice in range(2):
            result = recovery.account_event(ledger, "compaction-1", "compaction")
            ledger = result.value
            if result.detail["result"] == "counted_once" and result.detail["counted"]:
                count += 1
        self.assertEqual(count, 1)
        block = _context_resets_block(True, count)
        dev_state.validate_goal_run(copy.deepcopy(block))
        code, stdout, stderr = run_validator(ledger_with(render_goal_run(block)))
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)

    def test_both_texts_guard_the_count_on_counted_true(self):
        """A duplicate notice also returns `counted_once`, so both texts must
        name `counted: true` as part of the guard, not the result alone."""
        for label, text in (
            ("goal.md", _goal_lifecycle_section()),
            ("template", _template_lifecycle_counters_section()),
        ):
            with self.subTest(text=label):
                self.assertIn("counted_once", text)
                self.assertIn("counted: true", text)


class TestForemanClocksDistinctFrom112(unittest.TestCase):
    """AC4: the goal.md Lifecycle clocks section states D7.1 a), b) and c) and
    cites the SDP; the ledger template holds no Foreman clock value field."""

    def setUp(self):
        self.section = _goal_lifecycle_section()

    def test_section_is_a_top_level_section(self):
        headings = [h for h, _ in _sections(GOAL_MD.read_text())]
        self.assertIn("## Lifecycle clocks", headings)
        self.assertNotIn("### Lifecycle clocks", headings)

    def test_managed_mode_uses_the_foreman_orchestrator_clock(self):
        for text in (
            "Foreman's orchestrator clock",
            "prepare, retire at a clean point, hard stop",
            "Foreman owns those values",
            "Dev does not copy or override them",
            "records its own reset count in the ledger",
            "`context_resets`",
            "The ledger holds no Foreman clock value",
        ):
            with self.subTest(text=text):
                self.assertIn(text, self.section)

    def test_standalone_has_no_mandatory_clock(self):
        for text in (
            "There is no mandatory clock",
            "reports the total in its status and final reports",
            "at the second count tells the user once",
            "continues unless the user says otherwise",
            "No count stops a standalone run by itself",
            "prepare to hand over, never a hard stop",
        ):
            with self.subTest(text=text):
                self.assertIn(text, self.section)

    def test_the_two_idle_timers_stay_separate(self):
        for text in (
            "#112",
            "60 minutes",
            "4 hours",
            "neither replaces the other",
            "Neither acts on agents its owner did not spawn",
            "not implemented",
        ):
            with self.subTest(text=text):
                self.assertIn(text, self.section)

    def test_section_cites_the_sdp(self):
        self.assertIn("SDP l.518–533", self.section)

    def test_dev_never_computes_enforces_or_acts_on_a_timer(self):
        for text in (
            "Dev computes", "Dev enforces", "Dev acts on", "Dev applies",
            "Dev owns the clock", "Dev runs the timer", "Dev uses the timer",
            "Dev's timer",
        ):
            with self.subTest(text=text):
                self.assertNotIn(text, self.section)
        # The separation is stated, and nothing here acts on either timer.
        self.assertIn("nothing here acts on it", self.section)
        self.assertIn("Neither acts on agents its owner did not spawn", self.section)
        self.assertIn("They mean different things, neither replaces the other", self.section)

    def test_dev_bounds_are_not_presented_as_the_foreman_clock(self):
        self.assertIn("run_time_hours", self.section)
        self.assertIn("next_wake_at", self.section)
        self.assertIn("They are not Foreman's clock", self.section)

    def test_template_has_no_foreman_clock_value_field(self):
        documented = set(re.findall(r"^\s*([a-z_][a-z0-9_]*):", goal_example(), re.M))
        self.assertEqual(
            [name for name in sorted(documented) if FOREMAN_CLOCK_FIELD.search(name)],
            [],
        )
        rows = re.findall(
            r"^\|\s*`([a-z_][a-z0-9_]*)`\s*\|",
            _template_goal_run_section(),
            re.M,
        )
        self.assertTrue(rows, "the goal-run schema documents no field table")
        self.assertEqual(
            [name for name in sorted(set(rows)) if FOREMAN_CLOCK_FIELD.search(name)],
            [],
        )


class TestGoalMdLifecycleSection(unittest.TestCase):
    """AC5: goal.md carries exactly one Lifecycle clocks section, sitting
    immediately before the governance section, and the section names no
    runtime call.

    These checks are history-free on purpose. A test pinned to a historical
    base SHA breaks on a shallow checkout, and after the merge it runs on
    every later main, where the diff keeps growing. The byte-identical-to-base
    evidence for goal_run.py, goal_recovery.py and goal_authority.py is in the
    PR body instead."""

    def setUp(self):
        self.sections = _sections(GOAL_MD.read_text())

    def test_exactly_one_lifecycle_clocks_heading(self):
        headings = [heading for heading, _ in self.sections]
        self.assertEqual(headings.count("## Lifecycle clocks"), 1)
        self.assertNotIn("### Lifecycle clocks", headings)

    def test_section_sits_immediately_before_the_governance_section(self):
        headings = [heading for heading, _ in self.sections]
        index = headings.index("## Lifecycle clocks")
        self.assertEqual(
            headings[index + 1], "## Where the existing Dev gates govern"
        )

    def test_section_is_not_empty(self):
        self.assertTrue(_goal_lifecycle_section().strip())

    def test_section_names_no_runtime_call(self):
        section = _goal_lifecycle_section()
        for name in ("goal_run", "goal_recovery", "goal_authority"):
            with self.subTest(name=name):
                self.assertNotIn(name, section)
        for token in re.findall(r"`([^`\n]+)`", section):
            with self.subTest(token=token):
                self.assertNotIn("(", token)


if __name__ == "__main__":
    unittest.main()
