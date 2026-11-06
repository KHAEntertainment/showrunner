#!/usr/bin/env python3
"""Issue #194 lane L4: the policy docs wire goal_authority.py as it behaves.

The D2 and D7.2 behavior itself is tested in tests/test_goal_authority.py. These
tests pin the link between the changed docs (phase4.md, goal.md,
reply-contract.md, external-review.md) and that behavior: every function and
outcome the docs name exists, every gate row the docs dispose matches
GATE_INVENTORY, and each D2 case yields the outcome the docs state when the
ledger is persisted through dev_state.py between steps, as the docs say.
"""

import copy
import inspect
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEV_DIR = ROOT / "skills" / "dev"
SCRIPTS = DEV_DIR / "scripts"
FIXTURES = ROOT / "tests" / "fixtures" / "authority"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import dev_state  # noqa: E402

PHASE4 = (DEV_DIR / "phases" / "phase4.md").read_text(encoding="utf-8")
GOAL = (DEV_DIR / "phases" / "goal.md").read_text(encoding="utf-8")
REPLY = (DEV_DIR / "reply-contract.md").read_text(encoding="utf-8")
EXTERNAL = (DEV_DIR / "phases" / "external-review.md").read_text(encoding="utf-8")

REAL_OUTCOMES = ("accept", "invalid", "confirm_each", "safe_point_only", "protected_stop", "blocked")
DECIDE_MERGE_OUTCOMES = ("accept", "confirm_each", "blocked", "invalid")
DEV_STATE_HELPERS = ("merge_ledger_to_record", "merge_ledger_from_record")
FUNCTION_PREFIXES = (
    "check_", "record_", "validate_", "decide_", "revoke_", "carry_", "clear_",
    "dispose_", "proceed_", "amend_", "merge_ledger_",
)


def GA():
    """The goal_authority module dev_state uses, resolved at call time so a
    module reloaded by another test file never mixes classes."""
    return dev_state._load_goal_authority_module()


def _fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def section(text, heading):
    """The body under ``heading`` up to the next heading of the same or a higher level."""
    level = len(heading) - len(heading.lstrip("#"))
    start = text.index(heading + "\n")
    rest = text[start + len(heading) + 1:]
    stop = re.search(rf"^#{{1,{level}}} ", rest, re.M)
    return rest[: stop.start()] if stop else rest


MERGE_GRANT = section(PHASE4, "### Goal runs: bounded merge grant (D2)")
TWO_PASS = section(PHASE4, "## Two-Pass Review")
RATING = section(PHASE4, "## Review Rating")
MERGE_ORDER = section(PHASE4, "## Merge Order")
GOAL_STEP7 = section(GOAL, "## 7. Merges and gate disposition (D2, D7.2)")
GOAL_GOVERN = section(GOAL, "## Where the existing Dev gates govern")
REPLY_D2 = next(p for p in REPLY.split("\n\n") if p.startswith("**Goal-run merges under a D2 grant"))
EXTERNAL_ROWS = section(EXTERNAL, "## Goal-run gate inventory rows")
ASK_BULLET = next(line for line in TWO_PASS.splitlines() if line.startswith("- **ASK in a goal run"))
COMMENT_LINE = next(line for line in RATING.splitlines() if "gate: comment_decisions" in line)

CHANGED_TEXT = {
    "phase4 merge grant": MERGE_GRANT,
    "phase4 ASK": ASK_BULLET,
    "phase4 COMMENT": COMMENT_LINE,
    "goal step 7": GOAL_STEP7,
    "goal govern": GOAL_GOVERN,
    "reply D2.6": REPLY_D2,
    "external rows": EXTERNAL_ROWS,
}


def outcome_bullet(outcome):
    """The phase4 step-3 bullet that states what ``outcome`` means."""
    lines = [line for line in MERGE_GRANT.splitlines() if line.lstrip().startswith(f"- `{outcome}`:")]
    assert len(lines) == 1, outcome
    return lines[0]


def bullet_reasons(outcome):
    return set(re.findall(r"`([a-z_]+)`", outcome_bullet(outcome).split(":", 1)[1]))


class AC4DocsNameRealFunctionsAndOutcomes(unittest.TestCase):
    def test_called_and_named_functions_exist(self):
        ga = GA()
        public = set(ga.__all__) | set(DEV_STATE_HELPERS)
        for label, text in CHANGED_TEXT.items():
            calls = set(re.findall(r"`([a-z_][a-z0-9_]*)\(", text))
            named = {t for t in re.findall(r"`([a-z_][a-z0-9_]*)`", text) if t.startswith(FUNCTION_PREFIXES)}
            for name in calls | named:
                with self.subTest(doc=label, name=name):
                    self.assertIn(name, public)
                    module = dev_state if name in DEV_STATE_HELPERS else ga
                    self.assertTrue(callable(getattr(module, name)))

    def test_merge_procedure_names_every_d2_function(self):
        for name in ("check_gates", "decide_merge", "record_merge", "record_post_merge_failure",
                     "clear_halt", "revoke_grant", "carry_grant", "check_action"):
            with self.subTest(name=name):
                self.assertIn(f"`{name}", MERGE_GRANT)
        for name in ("check_gates", "decide_merge", "record_merge", "record_post_merge_failure",
                     "clear_halt", "revoke_grant", "carry_grant", "validate_delegated_record",
                     "dispose_gate", "proceed_unless_stopped"):
            with self.subTest(goal=name):
                self.assertIn(f"`{name}", GOAL_STEP7)

    def test_outcomes_named_are_real(self):
        for label, text in CHANGED_TEXT.items():
            for word in ("accept", "confirm_each", "blocked", "invalid", "protected_stop",
                         "safe_point_only", "auto_after_gates", "deny", "reject", "approve"):
                if f"`{word}`" in text:
                    with self.subTest(doc=label, outcome=word):
                        self.assertIn(word, REAL_OUTCOMES)

    def test_decide_merge_outcomes_are_exactly_its_real_ones(self):
        stated = {o for o in REAL_OUTCOMES if re.search(rf"^\s*- `{o}`:", MERGE_GRANT, re.M)}
        self.assertEqual(stated, set(DECIDE_MERGE_OUTCOMES))
        for text in (MERGE_GRANT, GOAL_STEP7, REPLY_D2):
            self.assertNotIn("protected_stop", text)
            self.assertNotIn("safe_point_only", text)

    def test_stated_reasons_are_reasons_decide_merge_can_return(self):
        ga = GA()
        source = inspect.getsource(ga.decide_merge) + inspect.getsource(ga.validate_grant)
        for outcome in ("confirm_each", "blocked", "invalid"):
            helper = {"confirm_each": "_confirm_each", "blocked": "_blocked", "invalid": "_invalid"}[outcome]
            produced = set(re.findall(rf'{helper}\("([a-z_]+)"', source))
            with self.subTest(outcome=outcome):
                self.assertTrue(bullet_reasons(outcome))
                self.assertLessEqual(bullet_reasons(outcome), produced)
        # validate_grant's own "now" refusal surfaces from decide_merge as confirm_each.
        decide_only = set(re.findall(r'_confirm_each\("([a-z_]+)"', inspect.getsource(ga.decide_merge)))
        self.assertLessEqual(decide_only, bullet_reasons("confirm_each") | {"now_not_timezone_qualified"})

    def test_goal_md_names_no_goal_recovery_call(self):
        self.assertNotIn("goal_recovery", GOAL)
        for name in ("reconcile", "resume_admission", "admit_resume"):
            self.assertNotIn(f"`{name}", GOAL_STEP7)

    def test_goal_md_keeps_recovery_and_gv_placeholders(self):
        self.assertIn("- **Recovery and resume** after a restart, compaction or lead change", GOAL_GOVERN)
        self.assertIn("- **GV:** completion stays a claim", GOAL_GOVERN)
        self.assertNotIn("**Merges and gate disposition:**", GOAL_GOVERN)

    def test_express_issue_confirmation_is_never_described_as_delegated(self):
        for name, text in (("phase4", PHASE4), ("goal", GOAL), ("reply", REPLY), ("external", EXTERNAL)):
            for line in text.splitlines():
                if re.search(r"express", line, re.I):
                    with self.subTest(doc=name, line=line[:80]):
                        self.assertNotRegex(line.lower(), r"delegat|proceed unless stopped")
        ga = GA()
        self.assertIn("express-issue-confirmation", ga.UNRESOLVED_DECISIONS)
        disposed = ga.dispose_gate("express_issue_confirmation")
        self.assertEqual((disposed.outcome, disposed.reason), ("invalid", "unresolved_decision"))
        self.assertFalse(ga.proceed_unless_stopped("express_issue_confirmation").may_proceed)

    def test_proceed_unless_stopped_refuses_protected_gates_as_goal_md_states(self):
        self.assertIn("(`invalid` / `protected_gate`)", GOAL_STEP7)
        ga = GA()
        for gate in ("merge", "product_ask_disposition", "external_review_bypass", "unknown_reviewer_identity"):
            with self.subTest(gate=gate):
                result = ga.proceed_unless_stopped(gate)
                self.assertEqual((result.outcome, result.reason), ("invalid", "protected_gate"))
        for gate in ("technical_ask_disposition", "comment_decisions", "external_review_rerequest"):
            with self.subTest(gate=gate):
                self.assertTrue(ga.proceed_unless_stopped(gate).may_proceed)


class AC5DocRowsTraceToGateInventory(unittest.TestCase):
    EXPECTED = {
        "external_review_rerequest": "delegated_d7_2",
        "external_review_bypass": "protected",
        "unknown_reviewer_identity": "protected",
        "technical_ask_disposition": "delegated_d7_2",
        "comment_decisions": "delegated_d7_2",
        "product_ask_disposition": "protected",
        "merge": "protected",
    }

    def rows(self):
        return {row.gate_id: row for row in GA().GATE_INVENTORY}

    def test_expected_dispositions_match_gate_inventory(self):
        rows = self.rows()
        for gate, disposition in self.EXPECTED.items():
            with self.subTest(gate=gate):
                self.assertEqual(rows[gate].disposition, disposition)
        self.assertIn("D2 bounded per-run grant", rows["merge"].condition)

    def test_external_review_table_rows_match_inventory(self):
        table = {}
        for line in EXTERNAL_ROWS.splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) == 3 and cells[0].startswith("`") and cells[0] != "`Gate id`":
                table[cells[0].strip("`")] = cells[1].strip("`")
        self.assertEqual(table, {
            "external_review_rerequest": "delegated_d7_2",
            "external_review_bypass": "protected",
            "unknown_reviewer_identity": "protected",
        })
        rows = self.rows()
        for gate, disposition in table.items():
            with self.subTest(gate=gate):
                self.assertEqual(rows[gate].disposition, disposition)

    def test_external_review_protected_rows_fail_closed(self):
        bypass = next(line for line in EXTERNAL_ROWS.splitlines() if "`external_review_bypass`" in line)
        self.assertIn("never implies a bypass", bypass)
        self.assertIn("explicit approval", bypass)
        unknown = next(line for line in EXTERNAL_ROWS.splitlines() if "`unknown_reviewer_identity`" in line)
        self.assertIn("fail closed", unknown)
        rerequest = next(line for line in EXTERNAL_ROWS.splitlines() if "`external_review_rerequest`" in line)
        self.assertIn("project's review policy", rerequest)

    def test_phase4_d7_2_rows_match_inventory(self):
        self.assertIn("`gate: technical_ask_disposition`", ASK_BULLET)
        self.assertIn("(`product_ask_disposition`, protected)", ASK_BULLET)
        self.assertIn("stays with the user", ASK_BULLET)
        self.assertIn("`gate: comment_decisions`", COMMENT_LINE)
        self.assertIn("product comment still waits for user confirmation", COMMENT_LINE)
        self.assertIn("merges stay protected (gate `merge`)", MERGE_GRANT)
        self.assertIn("APPROVE alone never merges", MERGE_GRANT)

    def test_changed_rows_sit_in_the_sections_inventory_dev_refs_name(self):
        rows = self.rows()
        located = {
            "technical_ask_disposition": ("phases/phase4.md § Two-Pass Review", TWO_PASS, ASK_BULLET),
            "product_ask_disposition": ("phases/phase4.md § Two-Pass Review", TWO_PASS, ASK_BULLET),
            "comment_decisions": ("phases/phase4.md § Review Rating", RATING, COMMENT_LINE),
            "merge": ("phases/phase4.md § Merge Order", MERGE_ORDER, MERGE_GRANT.strip()),
        }
        for gate, (ref, body, text) in located.items():
            with self.subTest(gate=gate):
                self.assertIn(ref, rows[gate].dev_refs)
                self.assertIn(text, body)

    def test_merge_procedure_is_goal_run_only(self):
        self.assertIn("This subsection applies only inside a goal run", MERGE_GRANT)
        self.assertIn("Outside one, Phase 4 merge behavior is unchanged", MERGE_GRANT)
        self.assertIn("or outside a goal run), the confirmation above stands", REPLY_D2)

    def test_reply_contract_d2_6_amendment(self):
        self.assertIn("a valid bounded grant in force counts as the confirmation", REPLY_D2)
        self.assertIn("notice for each merge and each failure", REPLY_D2)
        self.assertIn("waits for no acknowledgement", REPLY_D2)
        self.assertIn("never a force-push, deletion or bypass", REPLY_D2)


class AC6D2CasesThroughTheDocumentedPath(unittest.TestCase):
    """Each D2 case, with the MergeLedger persisted through dev_state between
    steps (as phase4 says), yields the outcome phase4 step 3 states for it."""

    NOW = "2099-01-01T12:00:00Z"

    def setUp(self):
        self.grant = _fixture("grant-valid.json")["grant"]
        self.request = _fixture("merge-request-valid.json")["request"]
        self.record = _fixture("conformance-different-family.json")["record"]

    def persist(self, ledger):
        return dev_state.merge_ledger_from_record(dev_state.merge_ledger_to_record(ledger))

    def ledger(self, **changes):
        return self.persist(GA().MergeLedger(run_id=self.grant["run_id"], **changes))

    def gates(self, **overrides):
        kwargs = dict(
            current_head=self.record["head"],
            destination_result={"status": "ready"},
            open_asks=[],
            external_review="clear",
            ci_required_checks="pass",
        )
        kwargs.update(overrides)
        return GA().check_gates(copy.deepcopy(self.record), **kwargs)

    def decide(self, grant="default", ledger=None, request=None, now=None, gates=None, mode="standalone"):
        return GA().decide_merge(
            self.grant if grant == "default" else grant,
            ledger if ledger is not None else self.ledger(),
            dict(self.request, **(request or {})),
            now or self.NOW,
            gates if gates is not None else self.gates(),
            mode=mode,
        )

    def assert_documented(self, result, outcome, reason=None):
        self.assertEqual(result.outcome, outcome, result)
        self.assertIn(outcome, DECIDE_MERGE_OUTCOMES)
        outcome_bullet(outcome)
        if reason is not None:
            self.assertEqual(result.reason, reason)
            self.assertIn(reason, bullet_reasons(outcome))

    def test_valid_grant_accepts_bound_to_head(self):
        result = self.decide()
        self.assert_documented(result, "accept")
        self.assertEqual(result.value["match_head_commit"], self.request["head"])
        self.assertIn("--match-head-commit <match_head_commit>", outcome_bullet("accept"))

    def test_missing_grant_falls_back_to_confirmation(self):
        self.assert_documented(self.decide(grant=None), "confirm_each", "missing_field")
        self.assertIn("every merge uses per-push confirmation", MERGE_GRANT)

    def test_expired(self):
        self.assert_documented(self.decide(now="2099-01-02T00:00:00Z"), "confirm_each", "grant_expired")

    def test_cap_reached(self):
        full = self.ledger(consumed=((1, "a"), (2, "b"), (3, "c")))
        self.assert_documented(self.decide(ledger=full), "confirm_each", "cap_reached")

    def test_unlisted_closing_issue(self):
        request = {"closing_issues": ["OWNER/synthetic-repo#1", "OWNER/synthetic-repo#9"]}
        self.assert_documented(self.decide(request=request), "confirm_each", "unlisted_closing_issue")

    def test_changed_head_and_stale_gate_result(self):
        other = "sha256:" + "d" * 64
        self.assert_documented(self.decide(request={"reviewed_head": other}), "confirm_each", "head_changed")
        self.assert_documented(self.decide(request={"head": other, "reviewed_head": other}),
                               "blocked", "stale_gate_result")

    def test_revocation_recorded_before_next_merge(self):
        revoked = self.persist(GA().revoke_grant(self.ledger(), "2099-01-01T11:00:00Z").value)
        self.assert_documented(self.decide(ledger=revoked), "confirm_each", "grant_revoked")

    def test_restart_keeps_grant_takeover_without_custody_does_not(self):
        ga = GA()
        used = self.ledger(consumed=((5, "x"),))
        for transition in ("restart", "compaction"):
            with self.subTest(transition=transition):
                carried = self.persist(ga.carry_grant(self.grant, used, transition).value)
                self.assert_documented(self.decide(ledger=carried), "accept")
        lost = self.persist(ga.carry_grant(self.grant, used, "takeover", custody_passed=False).value)
        self.assert_documented(self.decide(ledger=lost), "confirm_each", "grant_not_in_force")

    def test_atomicity_replay_consumes_one_slot(self):
        ga = GA()
        event = {"pr": 11, "outcome": "merged", "merge_sha": "aaa"}
        first = self.persist(ga.record_merge(self.ledger(), event).value)
        replay = ga.record_merge(first, event)
        self.assertTrue(replay.detail["replay"])
        self.assertEqual(self.persist(replay.value).slots_used, 1)
        failed = ga.record_merge(self.ledger(), {"pr": 11, "outcome": "failed"})
        self.assertEqual(failed.value.slots_used, 0)
        self.assertIn("replaying the same PR and merge SHA consumes nothing", MERGE_GRANT)

    def test_post_merge_failure_halts_until_clear_halt(self):
        ga = GA()
        halted = self.persist(ga.record_post_merge_failure(self.ledger(), "OWNER/synthetic-repo#1", "fail-1").value)
        request = {"pr": 12, "closing_issues": ["OWNER/synthetic-repo#2"]}
        self.assert_documented(self.decide(ledger=halted, request=request), "blocked", "post_merge_failure_halt")
        self.assertTrue(ga.check_action(halted, "dispatch").may_proceed)
        cleared = self.persist(ga.clear_halt(halted, "triage-1").value)
        self.assert_documented(self.decide(ledger=cleared, request=request), "accept")

    def test_failing_gate_blocks_and_managed_needs_coordinator_grant(self):
        self.assert_documented(self.decide(gates=self.gates(external_review="pending")),
                               "blocked", "gates_not_satisfied")
        self.assert_documented(self.decide(mode="managed"), "invalid", "foreman_grant_missing")


if __name__ == "__main__":
    unittest.main()
