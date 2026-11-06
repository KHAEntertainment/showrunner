"""Focused checks for #194 lane L3: gate inventory disposal, gate checks, the D2
merge-policy case set, SC-2 Begin/Continue and the D7.2 control record.

One test class per acceptance criterion (AC1-AC8). SC-2 and SC-4 contract
fixtures under docs/v2.2/contracts/fixtures/ are consumed read-only (no digest
pins). Lane fixtures live under tests/fixtures/authority/.
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "dev" / "scripts"
MODULE_PATH = SCRIPTS / "goal_authority.py"
DEV_DIR = ROOT / "skills" / "dev"
DOC_PATH = ROOT / "docs" / "v2.2" / "gate-inventory.md"
CONTRACT_FIXTURES = ROOT / "docs" / "v2.2" / "contracts" / "fixtures"
FIXTURES = ROOT / "tests" / "fixtures" / "authority"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gr = _load("goal_run", SCRIPTS / "goal_run.py")
ga = _load("goal_authority", MODULE_PATH)


def _fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _contract(sc, name):
    return json.loads((CONTRACT_FIXTURES / sc / name).read_text(encoding="utf-8"))


GRANT = _fixture("grant-valid.json")["grant"]
REQUEST = _fixture("merge-request-valid.json")["request"]
RECORD = _fixture("conformance-different-family.json")["record"]
HEAD = RECORD["head"]
NOW = "2099-01-01T12:00:00Z"
SC4_FAMILY_MAP = {
    (e["harness"], e["model"]): e["family"]
    for e in _fixture("sc4-family-map.json")["entries"]
}
ACK = _fixture("sc2-acknowledged-begin.json")["acknowledged"]
DELEGATED_RECORD = _fixture("delegated-record-valid.json")["record"]


def _grant(**changes):
    grant = copy.deepcopy(GRANT)
    grant.update(changes)
    return grant


def _request(**changes):
    request = copy.deepcopy(REQUEST)
    request.update(changes)
    return request


def _record(review_identity="keep", **changes):
    record = copy.deepcopy(RECORD)
    record.update(changes)
    review = [e for e in record["evidence"] if e["gate"] == "review"][0]
    if review_identity is None:
        review.pop("evaluator_identity", None)
    elif review_identity != "keep":
        review["evaluator_identity"] = review_identity
    return record


def _ledger(**changes):
    return ga.MergeLedger(run_id=GRANT["run_id"], **changes)


def _gates(record=None, **overrides):
    kwargs = dict(
        current_head=HEAD,
        destination_result={"status": "ready"},
        open_asks=[],
        external_review="clear",
        ci_required_checks="pass",
    )
    kwargs.update(overrides)
    return ga.check_gates(record if record is not None else _record(), **kwargs)


def _decide(grant=None, ledger=None, request=None, now=NOW, gates=None, mode=ga.MODE_STANDALONE):
    return ga.decide_merge(
        grant if grant is not None else _grant(),
        ledger if ledger is not None else _ledger(),
        request if request is not None else _request(),
        now,
        gates if gates is not None else _gates(),
        mode=mode,
    )


_CLEAN_CONTEXT_REVIEWER = {
    "agent_id": "synthetic-agent-r2",
    "harness": "synthetic-harness-a",
    "model": "synthetic-model-a2",
    "family": "family-a",
    "route_source": "clean_context_same_family",
}


# ---------------------------------------------------------------------------
# AC1 — gate inventory disposal
# ---------------------------------------------------------------------------


def _doc_rows():
    text = DOC_PATH.read_text(encoding="utf-8")
    section = text.split("## Gates", 1)[1]
    rows = []
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        rows.append(cells)
    return text, rows


class AC1GateInventory(unittest.TestCase):
    def test_ac1_every_group_has_a_disposed_gate(self):
        groups = {row.group for row in ga.GATE_INVENTORY}
        self.assertEqual(groups, set(range(1, 13)))
        self.assertEqual(set(ga.GROUPS), set(range(1, 13)))
        for row in ga.GATE_INVENTORY:
            with self.subTest(gate=row.gate_id):
                self.assertIn(row.disposition, ga.DISPOSITIONS)
                self.assertEqual(row.tier, ga.GROUPS[row.group][0])
                self.assertEqual(row.sdp_line, ga.GROUPS[row.group][1])
                self.assertTrue(195 <= row.sdp_line <= 208)
                self.assertEqual(row.delegable, row.disposition == ga.DELEGATED)
        ids = [row.gate_id for row in ga.GATE_INVENTORY]
        self.assertEqual(len(ids), len(set(ids)))

    def test_ac1_tier_c_rows_are_protected_and_not_delegable(self):
        tier_c = [row for row in ga.GATE_INVENTORY if row.tier == "C"]
        self.assertTrue(tier_c)
        for row in tier_c:
            with self.subTest(gate=row.gate_id):
                self.assertEqual(row.disposition, ga.PROTECTED)
                self.assertFalse(row.delegable)

    def test_ac1_tier_a_rows_are_preserved(self):
        for row in ga.GATE_INVENTORY:
            if row.tier == "A":
                with self.subTest(gate=row.gate_id):
                    self.assertEqual(row.disposition, ga.PRESERVED)

    def test_ac1_module_table_and_doc_agree(self):
        text, rows = _doc_rows()
        self.assertIn("audit disposals of SDP l.191–208 at pin 7177580c, not new delegations", text.splitlines()[2])
        self.assertEqual(len(rows), len(ga.GATE_INVENTORY))
        for cells, row in zip(rows, ga.GATE_INVENTORY):
            with self.subTest(gate=row.gate_id):
                gate_id, name, group, tier, disposition, delegable, condition, line, refs = cells
                self.assertEqual(gate_id.strip("`"), row.gate_id)
                self.assertEqual(name, row.name)
                self.assertEqual(int(group), row.group)
                self.assertEqual(tier, row.tier)
                self.assertEqual(disposition.strip("`"), row.disposition)
                self.assertEqual(delegable, "yes" if row.delegable else "no")
                self.assertEqual(condition, row.condition)
                self.assertEqual(int(line), row.sdp_line)
                self.assertEqual([r.strip().strip("`") for r in refs.split("; ")], list(row.dev_refs))
        doc_groups = re.findall(r"^\| (\d+) \| ([ABC]) \| (\d+) \|", text, re.M)
        self.assertEqual(
            [(int(g), t, int(l)) for g, t, l in doc_groups],
            [(g, ga.GROUPS[g][0], ga.GROUPS[g][1]) for g in sorted(ga.GROUPS)],
        )

    def test_ac1_dev_refs_name_existing_files_and_headings(self):
        for row in ga.GATE_INVENTORY:
            for ref in row.dev_refs:
                with self.subTest(gate=row.gate_id, ref=ref):
                    if ref == ga.DEV_REF_NONE:
                        continue
                    rel, heading = ref.split(" § ", 1)
                    path = DEV_DIR / rel
                    self.assertTrue(path.is_file(), f"missing {path}")
                    headings = [
                        re.sub(r"^#{1,6} ", "", line).strip()
                        for line in path.read_text(encoding="utf-8").splitlines()
                        if re.match(r"^#{1,6} ", line)
                    ]
                    self.assertIn(heading, headings)

    def test_ac1_gate_tied_to_unresolved_decision_is_rejected(self):
        result = ga.dispose_gate("express_issue_confirmation")
        self.assertEqual((result.outcome, result.reason), ("invalid", "unresolved_decision"))
        result = ga.dispose_gate("architecture_checkpoint", unresolved_decisions={"D7.2"})
        self.assertEqual(result.reason, "unresolved_decision")
        self.assertEqual(ga.proceed_unless_stopped("architecture_checkpoint", {"D7.2"}).reason, "unresolved_decision")
        self.assertTrue(ga.dispose_gate("architecture_checkpoint").may_proceed)
        self.assertEqual(ga.dispose_gate("no_such_gate").reason, "unknown_gate")


# ---------------------------------------------------------------------------
# AC2 — gate checks
# ---------------------------------------------------------------------------


class AC2GateChecks(unittest.TestCase):
    def test_ac2_current_head_pass_and_fail(self):
        self.assertTrue(ga.check_current_head(_record(), HEAD).may_proceed)
        self.assertEqual(ga.check_current_head(_record(), "sha256:" + "b" * 64).reason, "head_mismatch")
        self.assertEqual(ga.check_current_head(_record(), None).reason, "current_head_unknown")
        stale = _record()
        stale["evidence"][0]["head"] = "sha256:" + "c" * 64
        self.assertEqual(ga.check_current_head(stale, HEAD).reason, "stale_evidence_head")
        failed = _gates(current_head="sha256:" + "b" * 64)
        self.assertEqual(failed.outcome, "blocked")
        self.assertIn({"gate": "current_head", "reason": "head_mismatch"}, failed.detail["failures"])

    def test_ac2_destination_pass_and_fail(self):
        self.assertTrue(ga.check_destination({"status": "ready"}).may_proceed)
        for status in ("blocked", "mismatch", None, ""):
            with self.subTest(status=status):
                self.assertEqual(ga.check_destination({"status": status}).reason, "destination_not_verified")
        self.assertEqual(ga.check_destination(None).reason, "destination_not_verified")

    def test_ac2_qa_pass_skip_and_fail(self):
        self.assertTrue(ga.check_qa(_record()).may_proceed)
        skip = _record(gate_applicability="qa_trigger_below_threshold")
        skip["evidence"][0] = {"gate": "qa", "state": "valid-skip", "reason": "below QA trigger"}
        self.assertEqual(ga.check_qa(skip, qa_skip_allowed=True).detail, {"qa": "valid-skip"})
        self.assertEqual(ga.check_qa(skip, qa_skip_allowed=False).reason, "qa_skip_not_allowed")
        no_reason = copy.deepcopy(skip)
        no_reason["evidence"][0].pop("reason")
        self.assertEqual(ga.check_qa(no_reason, qa_skip_allowed=True).reason, "qa_skip_without_reason")
        for state, reason in (("pending", "qa_pending"), ("failed", "qa_failed")):
            with self.subTest(state=state):
                rec = _record()
                rec["evidence"][0] = {"gate": "qa", "state": state}
                self.assertEqual(ga.check_qa(rec).reason, reason)
        missing = _record()
        missing["evidence"] = missing["evidence"][1:]
        self.assertEqual(ga.check_qa(missing).reason, "qa_missing")

    def test_ac2_review_level_different_family_passes(self):
        result = ga.check_review_level(_record(), "pass")
        self.assertTrue(result.may_proceed, result)
        self.assertEqual(result.detail["route_source"], "different_family")

    def test_ac2_review_level_same_family_without_fallback_fails(self):
        same = dict(_CLEAN_CONTEXT_REVIEWER, route_source="same_family")
        self.assertEqual(ga.check_review_level(_record(same), "pass").reason, "route_not_qualifying")
        none = dict(_CLEAN_CONTEXT_REVIEWER, route_source="none")
        self.assertEqual(ga.check_review_level(_record(none), "pass").reason, "route_not_qualifying")
        claimed = dict(_CLEAN_CONTEXT_REVIEWER, route_source="different_family")
        self.assertEqual(ga.check_review_level(_record(claimed), "pass").reason, "route_family_mismatch")
        no_reason = ga.check_review_level(
            _record(_CLEAN_CONTEXT_REVIEWER), "pass",
            memory_disclosure=["claude-mem"], different_family_available=False,
        )
        self.assertEqual(no_reason.reason, "single_provider_reason_missing")

    def test_ac2_review_level_clean_context_fallback_passes(self):
        result = ga.check_review_level(
            _record(_CLEAN_CONTEXT_REVIEWER), "pass",
            single_provider_reason="Claude-native run; no second provider route",
            memory_disclosure=["claude-mem", "hindsight"],
            different_family_available=False,
        )
        self.assertTrue(result.may_proceed, result)
        self.assertEqual(result.detail["memory_isolation"], "not_demonstrated")
        unknown = ga.check_review_level(
            _record(_CLEAN_CONTEXT_REVIEWER), "pass",
            single_provider_reason="single provider", memory_disclosure="unknown",
            different_family_available=False,
        )
        self.assertTrue(unknown.may_proceed)

    def test_ac2_review_level_clean_context_refusals(self):
        base = dict(single_provider_reason="single provider", memory_disclosure=["claude-mem"])
        cases = (
            (dict(base, different_family_available=True), "different_family_available"),
            (dict(base), "different_family_available"),
            (dict(base, different_family_available=False, memory_disclosure=None), "memory_disclosure_missing"),
            (dict(base, different_family_available=False, memory_disclosure=[]), "memory_disclosure_missing"),
        )
        for kwargs, reason in cases:
            with self.subTest(reason=reason, kwargs=kwargs):
                self.assertEqual(ga.check_review_level(_record(_CLEAN_CONTEXT_REVIEWER), "pass", **kwargs).reason, reason)

    def test_ac2_review_level_missing_identity_fails(self):
        record = _record(None)
        self.assertEqual(ga.check_review_level(record, "pass").reason, "reviewer_identity_unknown")
        ledger_identity = {"agent_id": "synthetic-agent-r9", "harness": "h", "model": "m",
                           "family": "family-b", "route_source": "different_family"}
        self.assertTrue(ga.check_review_level(record, "pass", ledger_identity=ledger_identity).may_proceed)
        no_family = dict(RECORD["evidence"][1]["evaluator_identity"])
        no_family.pop("family")
        no_family["model"] = "deepseek:deepseek-v4-pro"
        result = ga.check_review_level(_record(no_family), "pass")
        self.assertEqual(result.reason, "family_unknown")
        self.assertEqual(result.detail["reviewer_family"], "unknown")
        mapped = ga.check_review_level(
            _record(no_family), "pass",
            family_map={("synthetic-harness-b", "deepseek:deepseek-v4-pro"): "deepseek"},
        )
        self.assertTrue(mapped.may_proceed)
        no_impl = _record()
        no_impl.pop("implementer_identity")
        self.assertEqual(ga.check_review_level(no_impl, "pass").reason, "implementer_identity_unknown")

    def test_ac2_review_level_requires_ci_and_distinct_reviewer(self):
        for ci in ("fail", "pending", None):
            with self.subTest(ci=ci):
                self.assertEqual(ga.check_review_level(_record(), ci).reason, "ci_required_checks_not_passed")
        same_agent = dict(RECORD["evidence"][1]["evaluator_identity"], agent_id="synthetic-agent-i1")
        self.assertEqual(ga.check_review_level(_record(same_agent), "pass").reason, "reviewer_is_implementer")

    def test_ac2_unresolved_ask_pass_and_fail(self):
        self.assertTrue(ga.check_unresolved_ask([]).may_proceed)
        self.assertEqual(ga.check_unresolved_ask(["ASK-1"]).reason, "unresolved_ask")
        self.assertEqual(ga.check_unresolved_ask(None).reason, "ask_state_unknown")

    def test_ac2_external_review_pass_and_fail(self):
        for state in ("clear", "not_applicable"):
            with self.subTest(state=state):
                self.assertTrue(ga.check_external_review(state).may_proceed)
        for state in ("pending", "incomplete", "blocking", "unknown"):
            with self.subTest(state=state):
                self.assertEqual(ga.check_external_review(state).reason, f"external_review_{state}")
        for state in ("ignored", "", None, "CLEAR"):
            with self.subTest(state=state):
                self.assertEqual(ga.check_external_review(state).reason, "external_review_unrecognized")

    def test_ac2_check_gates_accepts_and_names_each_failure(self):
        self.assertTrue(_gates().may_proceed)
        result = _gates(destination_result={"status": "blocked"}, open_asks=["ASK-1"], external_review="pending")
        self.assertEqual(result.reason, "gates_not_satisfied")
        self.assertEqual(
            {f["gate"]: f["reason"] for f in result.detail["failures"]},
            {"destination": "destination_not_verified", "ask": "unresolved_ask",
             "external_review": "external_review_pending"},
        )


# ---------------------------------------------------------------------------
# AC3 — D2 policy case set
# ---------------------------------------------------------------------------


class AC3MergePolicy(unittest.TestCase):
    def test_ac3_valid_grant_merges_bound_to_reviewed_head(self):
        result = _decide()
        self.assertEqual(result.outcome, "accept", result)
        self.assertEqual(result.value, {"merge_method": "squash", "match_head_commit": REQUEST["head"]})

    def test_ac3_missing_field_falls_back_to_confirm_each(self):
        for name in ga._GRANT_FIELDS:
            with self.subTest(field=name):
                grant = _grant()
                grant.pop(name)
                result = _decide(grant=grant)
                self.assertEqual((result.outcome, result.reason, result.detail), ("confirm_each", "missing_field", {"field": name}))

    def test_ac3_invalid_field_falls_back_to_confirm_each(self):
        cases = (
            ("eligible_issues", []),
            ("eligible_issues", ["OTHER/repo#1"]),
            ("eligible_issues", ["#1"]),
            ("eligible_issues", ["OWNER/synthetic-repo#1", "OWNER/synthetic-repo#1"]),
            ("max_merges", 0),
            ("max_merges", -1),
            ("max_merges", True),
            ("max_merges", "3"),
            ("expires_at", "2099-01-02T00:00:00"),
            ("expires_at", "tomorrow"),
            ("expires_at", 4102531200),
            ("authorized_by", {"who": "synthetic-owner", "at": "2099-01-01T00:00:00Z"}),
            ("repository", "synthetic-repo"),
            ("run_id", ""),
            ("excluded_actions", "force-push"),
        )
        for name, value in cases:
            with self.subTest(field=name, value=value):
                result = _decide(grant=_grant(**{name: value}))
                self.assertEqual((result.outcome, result.reason, result.detail["field"]), ("confirm_each", "invalid_field", name))

    def test_ac3_expired_at_or_after_expires_at(self):
        for now in ("2099-01-02T00:00:00Z", "2099-01-02T00:00:01Z", "2099-01-01T19:00:00-05:00"):
            with self.subTest(now=now):
                self.assertEqual(_decide(now=now).reason, "grant_expired")
        self.assertTrue(_decide(now="2099-01-01T23:59:59Z").may_proceed)
        self.assertTrue(_decide(grant=_grant(expires_at="2099-01-01T20:00:00-05:00"),
                                now="2099-01-02T00:59:59Z").may_proceed)

    def test_ac3_cap_reached_at_greater_or_equal(self):
        two = _ledger(consumed=((1, "a"), (2, "b")))
        self.assertTrue(_decide(ledger=two).may_proceed)
        three = _ledger(consumed=((1, "a"), (2, "b"), (3, "c")))
        result = _decide(ledger=three)
        self.assertEqual((result.outcome, result.reason), ("confirm_each", "cap_reached"))

    def test_ac3_unlisted_closing_issue_checks_all_links(self):
        result = _decide(request=_request(closing_issues=["OWNER/synthetic-repo#1", "OWNER/synthetic-repo#9"]))
        self.assertEqual((result.outcome, result.reason), ("confirm_each", "unlisted_closing_issue"))
        self.assertEqual(result.detail["issues"], ["OWNER/synthetic-repo#9"])
        self.assertEqual(_decide(request=_request(closing_issues=[])).reason, "no_eligible_closing_issue")
        self.assertTrue(_decide(request=_request(closing_issues=["OWNER/synthetic-repo#1", "OWNER/synthetic-repo#2"])).may_proceed)

    def test_ac3_changed_head_and_no_head_match(self):
        result = _decide(request=_request(reviewed_head="sha256:" + "d" * 64))
        self.assertEqual((result.outcome, result.reason), ("confirm_each", "head_changed"))
        result = _decide(request=_request(head_match_available=False))
        self.assertEqual((result.outcome, result.reason), ("confirm_each", "no_head_match"))
        self.assertEqual(_decide(request=_request(head_match_available=None)).reason, "no_head_match")

    def test_ac3_binding_changed(self):
        for name, value in (("base", "develop"), ("repository", "OWNER/other"), ("host", "ghe.example")):
            with self.subTest(field=name):
                result = _decide(request=_request(**{name: value}))
                self.assertEqual((result.outcome, result.reason, result.detail["field"]), ("confirm_each", "binding_changed", name))

    def test_ac3_revocation_recorded_before_next_merge(self):
        revoked = ga.revoke_grant(_ledger(), "2099-01-01T11:00:00Z")
        self.assertTrue(revoked.may_proceed)
        result = _decide(ledger=revoked.value)
        self.assertEqual((result.outcome, result.reason), ("confirm_each", "grant_revoked"))

    def test_ac3_restart_and_compaction_keep_grant(self):
        for transition in ("restart", "compaction"):
            with self.subTest(transition=transition):
                carried = ga.carry_grant(_grant(), _ledger(consumed=((5, "x"),)), transition)
                self.assertTrue(carried.may_proceed)
                self.assertEqual(carried.value.consumed, ((5, "x"),))
                self.assertTrue(_decide(ledger=carried.value).may_proceed)
        self.assertEqual(ga.carry_grant(_grant(run_id="synthetic-run-other"), _ledger(), "restart").reason,
                         "grant_run_mismatch")

    def test_ac3_takeover_with_and_without_custody(self):
        kept = ga.carry_grant(_grant(), _ledger(), "takeover", custody_passed=True)
        self.assertTrue(_decide(ledger=kept.value).may_proceed)
        for custody in (False, None):
            with self.subTest(custody=custody):
                lost = ga.carry_grant(_grant(), _ledger(), "takeover", custody_passed=custody)
                self.assertEqual(lost.detail["reason"], "takeover_without_custody")
                self.assertEqual(_decide(ledger=lost.value).reason, "grant_not_in_force")

    def test_ac3_multi_pr_each_merge_consumes_one_slot(self):
        ledger = _ledger()
        ledger = ga.record_merge(ledger, {"pr": 11, "outcome": "merged", "merge_sha": "aaa"}).value
        ledger = ga.record_merge(ledger, {"pr": 12, "outcome": "merged", "merge_sha": "bbb"}).value
        self.assertEqual(ledger.slots_used, 2)
        self.assertEqual(ledger.consumed, ((11, "aaa"), (12, "bbb")))
        third = _decide(ledger=ledger, request=_request(pr=13))
        self.assertTrue(third.may_proceed)
        self.assertEqual(third.detail["slot"], 3)

    def test_ac3_atomicity_failed_merge_and_replay(self):
        failed = ga.record_merge(_ledger(), {"pr": 11, "outcome": "failed"})
        self.assertEqual((failed.value.slots_used, failed.detail["slot_consumed"]), (0, False))
        first = ga.record_merge(_ledger(), {"pr": 11, "outcome": "merged", "merge_sha": "aaa"})
        replay = ga.record_merge(first.value, {"pr": 11, "outcome": "merged", "merge_sha": "aaa"})
        self.assertEqual(replay.value.slots_used, 1)
        self.assertTrue(replay.detail["replay"])
        self.assertEqual(ga.record_merge(first.value, {"pr": 11, "outcome": "merged", "merge_sha": "zzz"}).reason,
                         "conflicting_merge_record")
        self.assertEqual(ga.record_merge(_ledger(), {"pr": 11, "outcome": "merged"}).reason, "malformed_input")
        self.assertEqual(ga.record_merge(_ledger(), {"pr": 11, "outcome": "maybe"}).reason, "unknown_merge_outcome")

    def test_ac3_post_merge_failure_halts_merges_only(self):
        halted = ga.record_post_merge_failure(_ledger(), "OWNER/synthetic-repo#1", "post-merge-check-1").value
        self.assertTrue(halted.halted)
        self.assertEqual(halted.reopen_issues, ("OWNER/synthetic-repo#1",))
        result = _decide(ledger=halted, request=_request(pr=12, closing_issues=["OWNER/synthetic-repo#2"]))
        self.assertEqual((result.outcome, result.reason), ("blocked", "post_merge_failure_halt"))
        self.assertEqual(ga.check_action(halted, "merge").reason, "post_merge_failure_halt")
        for action in ("dispatch", "qa", "review", "fix"):
            with self.subTest(action=action):
                self.assertTrue(ga.check_action(halted, action).may_proceed)
        cleared = ga.clear_halt(halted, "triage-1").value
        self.assertTrue(_decide(ledger=cleared).may_proceed)

    def test_ac3_review_level_missing_on_one_pr_falls_back_for_that_merge_only(self):
        weak = _gates(_record(dict(_CLEAN_CONTEXT_REVIEWER, route_source="same_family")))
        self.assertEqual([f["gate"] for f in weak.detail["failures"]], ["review_level"])
        result = _decide(gates=weak)
        self.assertEqual((result.outcome, result.reason), ("confirm_each", "review_level_missing"))
        self.assertTrue(_decide(request=_request(pr=12)).may_proceed)

    def test_ac3_other_gate_failures_block_any_merge(self):
        result = _decide(gates=_gates(external_review="blocking"))
        self.assertEqual((result.outcome, result.reason), ("blocked", "gates_not_satisfied"))
        unevaluated = ga.decide_merge(_grant(), _ledger(), _request(), NOW, None)
        self.assertEqual((unevaluated.outcome, unevaluated.reason), ("blocked", "gates_not_evaluated"))

    def test_ac3_managed_mode_requires_foreman_grant(self):
        self.assertEqual(_decide(mode=ga.MODE_MANAGED).reason, "foreman_grant_missing")
        wrong = _request(foreman_grant={"pr": 11, "head": "sha256:" + "e" * 64})
        self.assertEqual(_decide(request=wrong, mode=ga.MODE_MANAGED).reason, "foreman_grant_missing")
        ok = _request(foreman_grant={"pr": 11, "head": REQUEST["head"]})
        self.assertTrue(_decide(request=ok, mode=ga.MODE_MANAGED).may_proceed)
        revoked = ga.revoke_grant(_ledger(), "2099-01-01T11:00:00Z").value
        self.assertEqual(_decide(ledger=revoked, request=ok, mode=ga.MODE_MANAGED).reason, "grant_revoked")

    def test_ac3_grant_never_grows_without_fresh_authority(self):
        for changes in (
            {"eligible_issues": GRANT["eligible_issues"] + ["OWNER/synthetic-repo#3"]},
            {"max_merges": 4},
            {"expires_at": "2099-01-03T00:00:00Z"},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(ga.amend_grant(_grant(), changes).reason, "grant_growth")
                self.assertEqual(ga.amend_grant(_grant(), changes, fresh_authority=GRANT["authorized_by"]).reason,
                                 "grant_growth")
                fresh = {"who": "synthetic-owner", "at": "2099-01-01T06:00:00Z", "instruction": "add Issue 3"}
                self.assertTrue(ga.amend_grant(_grant(), changes, fresh_authority=fresh).may_proceed)
        narrowed = ga.amend_grant(_grant(), {"max_merges": 1, "eligible_issues": ["OWNER/synthetic-repo#1"]})
        self.assertTrue(narrowed.may_proceed)
        self.assertEqual(narrowed.value["max_merges"], 1)
        self.assertEqual(ga.amend_grant(_grant(), {"base": "develop"}).reason, "unamendable_field")


# ---------------------------------------------------------------------------
# AC4 — SC-2 Begin / Continue
# ---------------------------------------------------------------------------


def _ctx(**changes):
    ctx = copy.deepcopy(ACK)
    ctx["result"] = "Continue"
    begin_changes = changes.pop("begin", None)
    ctx.update(changes)
    if begin_changes:
        ctx["begin"].update(begin_changes)
    return ctx


_SCOPE = {"targets": [ACK["target"]], "operations": ["merge"]}


def _ack_from_fixture(ctx):
    """Each SC-2 fixture carries its acknowledged Begin (sc-2.md, Fixture shape):
    the stored acknowledged context is the fixture's own bindings and begin
    record, with result Begin and no observation."""
    acknowledged = copy.deepcopy(ctx)
    acknowledged.pop("observation", None)
    acknowledged["result"] = "Begin"
    return acknowledged


def _new_begin_ctx(**changes):
    ctx = copy.deepcopy(ACK)
    ctx.pop("begin")
    ctx.update({"grant_id": "synthetic-grant-777", "grant_epoch": 2,
                "grant_expiry": "2099-01-02T00:00:00Z"})
    ctx.update(changes)
    return ctx


def _auth(ctx, **override):
    """An accepted authority bound to exactly the Begin's operation."""
    binding = {"actor": ctx["actor"], "run": ctx["run"], "operation": ctx["operation"], "target": ctx["target"],
               "head": ctx["head"], "grant_id": ctx.get("grant_id")}
    binding.update(override)
    return ga.bind_authority(gr.Result("accept"), **binding)


class AC4BeginContinue(unittest.TestCase):
    def test_ac4_contract_fixtures_evaluate_to_expected_outcome(self):
        authority = gr.Result("accept")
        for name in sorted((CONTRACT_FIXTURES / "sc-2").glob("*.json")):
            with self.subTest(fixture=name.name):
                fixture = json.loads(name.read_text(encoding="utf-8"))
                ctx = fixture["input"]
                observed = ctx.get("observation", {}).get("observed_at")
                result = ga.evaluate_authorization(
                    ctx, acknowledged=_ack_from_fixture(ctx), scope={"targets": [ctx["target"]], "operations": [ctx["operation"]]},
                    authority=authority, now=observed,
                )
                expected = "accept" if fixture["expected_outcome"] == "accept" else "invalid"
                self.assertEqual(result.outcome, expected, result)
                if fixture["kind"] == "rejected":
                    self.assertEqual(result.reason, "replayed_begin")

    def test_ac4_continue_across_epoch_rotation_and_latest_start_expiry(self):
        rotated = ga.check_continue(_ctx(), ACK, now="2099-01-01T06:00:00Z")
        self.assertTrue(rotated.may_proceed)
        expired = ga.check_continue(_ctx(), ACK, now="2099-01-05T00:00:00Z")
        self.assertTrue(expired.may_proceed, expired)
        stale_begin = ga.check_begin(_new_begin_ctx(grant_epoch=1), scope=_SCOPE,
                                     authority=_auth(_new_begin_ctx(grant_epoch=1)), coordinator_epoch=2)
        self.assertEqual(stale_begin.reason, "stale_epoch")
        bad_epoch = ga.check_begin(_new_begin_ctx(grant_epoch="2"), scope=_SCOPE,
                                   authority=_auth(_new_begin_ctx(grant_epoch="2")), coordinator_epoch=2)
        self.assertEqual(bad_epoch.reason, "malformed_input")
        late_begin = ga.check_begin(_new_begin_ctx(), scope=_SCOPE, authority=_auth(_new_begin_ctx()),
                                    now="2099-01-03T00:00:00Z")
        self.assertEqual(late_begin.reason, "grant_expired")

    def test_ac4_replayed_begin_rejected(self):
        replay = copy.deepcopy(ACK)
        result = ga.check_begin(replay, scope=_SCOPE, authority=gr.Result("accept"))
        self.assertEqual(result.reason, "replayed_begin")
        again = _new_begin_ctx()
        result = ga.check_begin(again, scope=_SCOPE, authority=gr.Result("accept"),
                                acknowledged_grants=["synthetic-grant-777"])
        self.assertEqual(result.reason, "replayed_begin")

    def test_ac4_changed_binding_and_new_operation_rejected(self):
        cases = (
            (_ctx(head="sha256:" + "f" * 64), "changed_binding"),
            (_ctx(actor="synthetic-agent-999"), "changed_binding"),
            (_ctx(run="synthetic-run-999"), "changed_binding"),
            (_ctx(begin={"grant_id": "synthetic-grant-999"}), "changed_binding"),
            (_ctx(begin={"grant_start": "2099-01-01T01:00:00Z"}), "changed_binding"),
            (_ctx(target="OWNER/other-repo"), "changed_target"),
            (_ctx(operation="release"), "new_operation"),
            (_ctx(begin={"grant_state": "complete"}), "not_ongoing"),
        )
        for ctx, reason in cases:
            with self.subTest(reason=reason):
                self.assertEqual(ga.check_continue(ctx, ACK).reason, reason)

    def test_ac4_pause_restricts_to_safe_point(self):
        safe = ga.check_continue(_ctx(), ACK, paused=True)
        self.assertEqual((safe.outcome, safe.reason), ("safe_point_only", "paused"))
        self.assertEqual(ga.check_continue(_ctx(), ACK, paused=True, step="safe_point").outcome, "safe_point_only")
        new_work = ga.check_continue(_ctx(), ACK, paused=True, step="new_work")
        self.assertEqual((new_work.outcome, new_work.reason), ("invalid", "new_work_restricted"))
        begin = ga.check_begin(_new_begin_ctx(), scope=_SCOPE, authority=gr.Result("accept"), paused=True)
        self.assertEqual(begin.reason, "paused")

    def test_ac4_passed_finish_deadline_restricts_to_safe_point(self):
        result = ga.check_continue(_ctx(), ACK, now="2099-01-03T00:00:00Z", finish_deadline="2099-01-02T12:00:00Z")
        self.assertEqual((result.outcome, result.reason), ("safe_point_only", "finish_deadline_passed"))
        before = ga.check_continue(_ctx(), ACK, now="2099-01-02T11:00:00Z", finish_deadline="2099-01-02T12:00:00Z")
        self.assertTrue(before.may_proceed)
        self.assertEqual(
            ga.check_continue(_ctx(), ACK, now="2099-01-03T00:00:00Z", finish_deadline="2099-01-02T12:00:00Z",
                              step="new_work").reason,
            "new_work_restricted",
        )

    def test_ac4_begin_checks_scope_and_authority(self):
        ok = ga.check_begin(_new_begin_ctx(), scope=_SCOPE, authority=_auth(_new_begin_ctx()))
        self.assertTrue(ok.may_proceed, ok)
        self.assertEqual(ga.check_begin(_new_begin_ctx(target="OWNER/other"), scope=_SCOPE,
                                        authority=_auth(_new_begin_ctx())).reason, "out_of_scope")
        self.assertEqual(ga.check_begin(_new_begin_ctx(), scope=_SCOPE, authority=None).reason, "no_authority")
        self.assertEqual(ga.check_begin(_new_begin_ctx(), scope=_SCOPE,
                                        authority=gr.Result("invalid", reason="x")).reason, "no_authority")
        self.assertEqual(ga.check_begin(_new_begin_ctx(), scope=_SCOPE,
                                        authority=gr.Result("accept")).reason, "no_authority_binding")


# ---------------------------------------------------------------------------
# AC5 — D7.2 control record
# ---------------------------------------------------------------------------


class AC5ControlRecord(unittest.TestCase):
    def test_ac5_complete_record_accepted_and_each_missing_field_rejected(self):
        self.assertTrue(ga.validate_delegated_record(DELEGATED_RECORD).may_proceed)
        for name in ga._DELEGATED_RECORD_FIELDS:
            for bad in (None, "", "   "):
                with self.subTest(field=name, value=bad):
                    record = dict(DELEGATED_RECORD)
                    if bad is None:
                        record.pop(name)
                    else:
                        record[name] = bad
                    result = ga.validate_delegated_record(record)
                    self.assertEqual((result.reason, result.detail.get("field")), ("missing_record_field", name))
        self.assertEqual(ga.validate_delegated_record(dict(DELEGATED_RECORD, gate="merge")).reason, "gate_not_delegable")
        self.assertEqual(ga.validate_delegated_record(dict(DELEGATED_RECORD, gate="express_issue_confirmation")).reason,
                         "unresolved_decision")

    def test_ac5_veto_stops_pending_work_and_needs_acknowledgement(self):
        pending = ["dispatch-lane-2", "merge-pr-11"]
        stop = [{"id": "msg-1", "kind": "stop"}]
        blocked = ga.step_boundary(pending, stop)
        self.assertEqual((blocked.outcome, blocked.reason), ("blocked", "veto_unacknowledged"))
        acked = ga.step_boundary(pending, stop, acknowledged_ids=["msg-1"])
        self.assertEqual(acked.value, {"continue": [], "stopped": pending, "revised": []})
        revise = [{"id": "msg-2", "kind": "revise", "targets": ["merge-pr-11"]}]
        self.assertEqual(ga.step_boundary(pending, revise).outcome, "blocked")
        revised = ga.step_boundary(pending, revise, acknowledged_ids=["msg-2"])
        self.assertEqual(revised.value, {"continue": ["dispatch-lane-2"], "stopped": [], "revised": ["merge-pr-11"]})
        self.assertEqual(ga.step_boundary(pending, []).value["continue"], pending)
        self.assertEqual(ga.step_boundary(pending, [{"id": "m", "kind": "chat"}]).reason, "malformed_message")
        self.assertEqual(ga.step_boundary(pending, ["stop everything"]).reason, "malformed_message")

    def test_ac5_dependent_action_waits_independent_proceeds(self):
        open_questions = [{"id": "q-scope", "question_kind": "scope"}]
        dependent = ga.check_dependencies({"id": "lane-3", "depends_on": ["q-scope"]}, open_questions)
        self.assertEqual((dependent.outcome, dependent.reason), ("blocked", "awaiting_answer"))
        independent = ga.check_dependencies({"id": "lane-4", "depends_on": []}, open_questions)
        self.assertTrue(independent.may_proceed)

    def test_ac5_questions_one_at_a_time_with_recommendation(self):
        queue = [
            {"id": "q1", "question_kind": "product", "recommendation": "ship A"},
            {"id": "q2", "question_kind": "scope", "recommendation": "defer B"},
            {"id": "q3", "question_kind": "engineering", "recommendation": "use stdlib"},
        ]
        first = ga.next_question(queue)
        self.assertEqual([q["id"] for q in first.value], ["q1"])
        self.assertEqual(ga.next_question(queue, outstanding=["q1"]).reason, "question_outstanding")
        batch = ga.next_question(queue, batch_requested=True)
        self.assertEqual([q["id"] for q in batch.value], ["q1", "q2"])
        bad = [{"id": "q4", "question_kind": "acceptance"}]
        self.assertEqual(ga.next_question(bad).reason, "missing_recommendation")

    def test_ac5_protected_stops_escalate_immediately(self):
        for category in ("H1", "H2", "H3", "H4", "H5"):
            with self.subTest(category=category):
                result = ga.escalate({"category": category})
                self.assertEqual((result.outcome, result.reason), ("protected_stop", category))
                self.assertTrue(result.detail["immediate"])
        self.assertEqual(ga.escalate({"category": "H6"}).reason, "not_protected_stop")

    def test_ac5_proceed_unless_stopped_refused_for_protected_gate(self):
        for gate in ("merge", "force_push", "external_review_bypass", "product_ask_disposition", "scenario_opt_out"):
            with self.subTest(gate=gate):
                self.assertEqual(ga.proceed_unless_stopped(gate).reason, "protected_gate")
        self.assertEqual(ga.proceed_unless_stopped("module_lock").reason, "not_delegated")
        self.assertEqual(ga.proceed_unless_stopped("two_pass_review").reason, "not_delegated")
        self.assertTrue(ga.proceed_unless_stopped("architecture_checkpoint").may_proceed)


# ---------------------------------------------------------------------------
# AC6 — SC-4 contract fixtures
# ---------------------------------------------------------------------------


class AC6ConformanceFixtures(unittest.TestCase):
    def test_ac6_sc4_fixtures_evaluate_to_expected_outcome(self):
        names = sorted((CONTRACT_FIXTURES / "sc-4").glob("*.json"))
        self.assertGreaterEqual(len(names), 5)
        for name in names:
            with self.subTest(fixture=name.name):
                fixture = json.loads(name.read_text(encoding="utf-8"))
                result = ga.evaluate_conformance(fixture["input"], family_map=SC4_FAMILY_MAP)
                expected = "accept" if fixture["expected_outcome"] == "accept" else "invalid"
                self.assertEqual(result.outcome, expected, result)

    def test_ac6_rejection_reasons_match_the_fixture_cause(self):
        expected = {
            "rejected-missing-mandatory-qa.json": "missing_mandatory_qa",
            "rejected-different-head-evidence.json": "different_head_evidence",
            "rejected-inferred-family-diversity.json": "route_not_qualifying",
        }
        for name, reason in expected.items():
            with self.subTest(fixture=name):
                result = ga.evaluate_conformance(_contract("sc-4", name)["input"], family_map=SC4_FAMILY_MAP)
                self.assertEqual(result.reason, reason)

    def test_ac6_absent_identity_never_rejects_but_unknown_family_fails_review_level(self):
        skip = _contract("sc-4", "accepted-documented-skip-below-qa.json")["input"]
        self.assertTrue(ga.evaluate_conformance(skip).may_proceed)
        six = _contract("sc-4", "accepted-six-mark-mapping.json")["input"]
        unmapped = ga.evaluate_conformance(six)
        self.assertEqual((unmapped.reason, unmapped.detail["layer"]), ("family_unknown", "gate"))
        self.assertEqual(ga.check_review_level(six, "pass").reason, "family_unknown")
        self.assertTrue(ga.check_review_level(six, "pass", family_map=SC4_FAMILY_MAP).may_proceed)

    def test_ac6_shape_errors_are_distinct_from_gate_errors(self):
        broken = copy.deepcopy(RECORD)
        broken.pop("report_ref")
        result = ga.evaluate_conformance(broken)
        self.assertEqual((result.reason, result.detail["layer"]), ("missing_required_field", "shape"))
        self.assertTrue(ga.evaluate_conformance(RECORD).may_proceed)


# ---------------------------------------------------------------------------
# AC7 — owner reference cases (ruling-m3-deepseek-references-2026-11-06)
# ---------------------------------------------------------------------------


class AC7OwnerReferenceCases(unittest.TestCase):
    def test_ac7_replayed_begin_and_changed_target_rejected(self):
        self.assertEqual(ga.check_begin(copy.deepcopy(ACK), scope=_SCOPE, authority=gr.Result("accept")).reason,
                         "replayed_begin")
        self.assertEqual(ga.check_continue(_ctx(target="OWNER/other-repo"), ACK).reason, "changed_target")

    def test_ac7_bounded_continue_accepted_across_rotation_and_expiry(self):
        for name in ("accepted-continue-epoch-rotation.json", "accepted-continue-latest-start-expiry.json"):
            with self.subTest(fixture=name):
                ctx = _contract("sc-2", name)["input"]
                now = ctx.get("observation", {}).get("observed_at")
                self.assertTrue(ga.check_continue(ctx, _ack_from_fixture(ctx), now=now).may_proceed)

    def test_ac7_unrestricted_new_work_during_pause_prevented(self):
        self.assertEqual(ga.check_continue(_ctx(), ACK, paused=True, step="new_work").reason, "new_work_restricted")
        self.assertEqual(ga.check_begin(_new_begin_ctx(), scope=_SCOPE, authority=gr.Result("accept"),
                                        paused=True).reason, "paused")

    def test_ac7_no_manufactured_approval_review_or_full_suite(self):
        # CI required checks plus one qualifying independent review are enough:
        # check_gates takes no owner-approval, second-review or local full-suite input.
        gates = _gates()
        self.assertTrue(gates.may_proceed)
        merge = _decide(gates=gates)
        self.assertEqual(merge.outcome, "accept")
        self.assertNotIn("owner_confirmation", merge.detail)
        import inspect
        params = set(inspect.signature(ga.check_gates).parameters)
        self.assertFalse(params & {"owner_approval", "second_review", "full_suite", "local_full_suite"})

    def test_ac7_lead_keeps_delegated_engineering_decisions(self):
        self.assertEqual(ga.route_question({"question_kind": "engineering"}).value, "lead")
        self.assertEqual(ga.route_question({"question_kind": "product"}).value, "user")
        self.assertEqual(ga.route_question({}).value, "user")
        for gate in ("architecture_checkpoint", "task_dag", "technical_ask_disposition", "comment_decisions"):
            with self.subTest(gate=gate):
                self.assertTrue(ga.proceed_unless_stopped(gate).may_proceed)
        self.assertEqual(ga.dispose_gate("final_review_rating").value.disposition, ga.PRESERVED)
        engineering_only = [{"id": "q", "question_kind": "engineering", "recommendation": "x"}]
        self.assertEqual(ga.next_question(engineering_only).value, [])


# ---------------------------------------------------------------------------
# Fix batch 1 — review round 1 findings B1-B9 (reviewer repro inputs)
# ---------------------------------------------------------------------------

HEAD_B = "sha256:" + "b" * 64


class FixBatch1Regressions(unittest.TestCase):
    def test_b1_decide_merge_requires_aware_now(self):
        result = _decide(grant=_grant(expires_at="2099-01-01T11:00:00Z"), now=None)
        self.assertEqual((result.outcome, result.reason), ("confirm_each", "now_missing"))
        naive = _decide(now="2099-01-01T12:00:00")
        self.assertEqual((naive.outcome, naive.reason), ("confirm_each", "now_not_timezone_qualified"))
        self.assertEqual(_decide(grant=_grant(expires_at="2099-01-01T11:00:00Z")).reason, "grant_expired")

    def test_b2_gate_result_from_another_head_is_stale(self):
        result = _decide(request=_request(head=HEAD_B, reviewed_head=HEAD_B))
        self.assertEqual((result.outcome, result.reason), ("blocked", "stale_gate_result"))
        self.assertEqual(_gates().detail["checked_head"], HEAD)
        self.assertEqual(_gates(external_review="pending").detail["checked_head"], HEAD)
        # Composed across a head change: re-checking at the new head with evidence for it merges.
        record_b = _record(head=HEAD_B)
        for entry in record_b["evidence"]:
            if "head" in entry:
                entry["head"] = HEAD_B
        gates_b = _gates(record_b, current_head=HEAD_B)
        self.assertTrue(gates_b.may_proceed, gates_b)
        merged = _decide(request=_request(head=HEAD_B, reviewed_head=HEAD_B), gates=gates_b)
        self.assertEqual(merged.value["match_head_commit"], HEAD_B)
        # Old evidence re-checked at the new head is refused by the gates themselves.
        self.assertIn({"gate": "current_head", "reason": "head_mismatch"},
                      _gates(current_head=HEAD_B).detail["failures"])

    def test_b3_finish_deadline_is_bound_to_the_acknowledged_begin(self):
        ack = copy.deepcopy(ACK)
        ack["begin"]["grant_finish"] = "2099-01-02T12:00:00Z"
        same = _ctx(begin={"grant_finish": "2099-01-02T12:00:00Z"})
        dropped = _ctx()
        extended = _ctx(begin={"grant_finish": "2099-01-09T00:00:00Z"})
        self.assertEqual(ga.check_continue(dropped, ack, now="2099-01-03T00:00:00Z").reason, "changed_binding")
        self.assertEqual(ga.check_continue(extended, ack, now="2099-01-03T00:00:00Z").reason, "changed_binding")
        after = ga.check_continue(same, ack, now="2099-01-03T00:00:00Z")
        self.assertEqual((after.outcome, after.reason), ("safe_point_only", "finish_deadline_passed"))
        self.assertEqual(ga.check_continue(same, ack, now="2099-01-03T00:00:00Z", step="new_work").reason,
                         "new_work_restricted")
        later_caller = ga.check_continue(same, ack, now="2099-01-03T00:00:00Z", finish_deadline="2099-01-09T00:00:00Z")
        self.assertEqual(later_caller.outcome, "safe_point_only")
        self.assertTrue(ga.check_continue(same, ack, now="2099-01-02T11:00:00Z").may_proceed)

    def test_b4_acknowledged_begin_is_validated_before_comparison(self):
        for name in ("grant_id", "grant_kind", "grant_epoch", "grant_start", "grant_holder"):
            with self.subTest(missing=name):
                ack = copy.deepcopy(ACK)
                ack["begin"][name] = None
                ctx = _ctx(begin={name: None})
                result = ga.check_continue(ctx, ack)
                self.assertEqual((result.reason, result.detail["field"]),
                                 ("acknowledged_begin_invalid", f"begin.{name}"))
        typed = copy.deepcopy(ACK)
        typed["begin"]["grant_epoch"] = "1"
        self.assertEqual(ga.check_continue(_ctx(begin={"grant_epoch": "1"}), typed).reason, "acknowledged_begin_invalid")
        done = copy.deepcopy(ACK)
        done["begin"]["grant_state"] = "complete"
        result = ga.check_continue(_ctx(), done)
        self.assertEqual((result.reason, result.detail["source"]), ("not_ongoing", "acknowledged"))
        # A valid Continue still never re-applies epoch or latest-start admission.
        self.assertTrue(ga.check_continue(_ctx(), ACK, now="2099-01-05T00:00:00Z").may_proceed)

    def test_b5_begin_requires_exact_binding(self):
        ctx = _new_begin_ctx(grant_holder="synthetic-agent-999")
        self.assertEqual(ga.check_begin(ctx, scope=_SCOPE, authority=_auth(ctx)).reason, "holder_mismatch")
        ctx = _new_begin_ctx()
        self.assertEqual(ga.check_begin(ctx, scope=_SCOPE, authority=gr.Result("accept")).reason,
                         "no_authority_binding")
        for field, value in (("actor", "synthetic-agent-999"), ("run", "synthetic-run-999"),
                             ("target", "OWNER/other"), ("head", HEAD_B), ("grant_id", "synthetic-grant-999")):
            with self.subTest(field=field):
                result = ga.check_begin(ctx, scope=_SCOPE, authority=_auth(ctx, **{field: value}))
                self.assertEqual((result.reason, result.detail["field"]), ("authority_binding_mismatch", field))
        self.assertTrue(ga.check_begin(_new_begin_ctx(grant_holder=ctx["actor"]), scope=_SCOPE,
                                       authority=_auth(ctx)).may_proceed)
        import inspect
        params = set(inspect.signature(ga.check_begin).parameters)
        self.assertFalse(params & {"owner_approval", "approval", "second_review"})

    def test_b6_identity_fails_closed_and_recorded_identity_is_authoritative(self):
        ledger_identity = {"agent_id": "synthetic-agent-r9", "harness": "h", "model": "m",
                           "family": "family-b", "route_source": "different_family"}
        for member in ("agent_id", "harness", "model"):
            with self.subTest(missing=member):
                partial = dict(RECORD["evidence"][1]["evaluator_identity"])
                partial.pop(member)
                self.assertEqual(ga.check_review_level(_record(partial), "pass").reason, "reviewer_identity_unknown")
        for malformed in ({}, None, "synthetic-agent-r1"):
            with self.subTest(malformed=malformed):
                record = _record()
                record["evidence"][1]["evaluator_identity"] = malformed
                result = ga.check_review_level(record, "pass", ledger_identity=ledger_identity)
                self.assertEqual(result.reason, "reviewer_identity_unknown")
        self.assertTrue(ga.check_review_level(_record(None), "pass", ledger_identity=ledger_identity).may_proceed)
        bad_impl = _record(implementer_identity={"agent_id": "synthetic-agent-i1"})
        self.assertEqual(ga.check_review_level(bad_impl, "pass", implementer_identity=RECORD["implementer_identity"]).reason,
                         "implementer_identity_unknown")
        self.assertEqual(ga.evaluate_conformance(bad_impl).reason, "implementer_identity_malformed")
        legacy = _contract("sc-4", "accepted-documented-skip-below-qa.json")["input"]
        self.assertTrue(ga.evaluate_conformance(legacy).may_proceed)

    def test_b7_merge_gate_path_validates_review_evidence_shape(self):
        record = _record()
        record["evidence"][1].pop("evaluator")
        self.assertEqual(ga.check_review_level(record, "pass").reason, "review_unnamed")
        gates = _gates(record)
        failures = {f["gate"]: f["reason"] for f in gates.detail["failures"]}
        self.assertEqual(failures["record_shape"], "required_evidence_unnamed")
        self.assertEqual(failures["review_level"], "review_unnamed")
        merge = _decide(gates=gates)
        self.assertEqual((merge.outcome, merge.reason), ("blocked", "gates_not_satisfied"))
        no_report = _record()
        no_report["evidence"][1]["report_ref"] = ""
        self.assertEqual(_decide(gates=_gates(no_report)).reason, "gates_not_satisfied")

    def test_b8_marks_contract_enforced(self):
        bad_marks = (
            [None] * 6,
            RECORD["marks"][:5],
            RECORD["marks"][:5] + [RECORD["marks"][0]],
            RECORD["marks"][:5] + [dict(RECORD["marks"][5], foreman_mark="something else")],
            RECORD["marks"][:5] + [dict(RECORD["marks"][5], state="done")],
            RECORD["marks"][:5] + [dict(RECORD["marks"][5], dev_applicability="")],
        )
        for marks in bad_marks:
            with self.subTest(marks=str(marks)[:60]):
                record = _record(marks=copy.deepcopy(marks))
                result = ga.evaluate_conformance(record)
                self.assertEqual(result.outcome, "invalid")
                self.assertIn(result.reason, ("marks_malformed", "marks_incomplete"))
                self.assertEqual(result.detail["layer"], "shape")
                self.assertEqual(_decide(gates=_gates(record)).reason, "gates_not_satisfied")
        self.assertTrue(ga.evaluate_conformance(RECORD).may_proceed)

    def test_b9_revision_needs_targets_before_release(self):
        pending = ["dispatch-lane-2", "merge-pr-11"]
        for message in ({"id": "m", "kind": "revise"},
                        {"id": "m", "kind": "revise", "targets": []},
                        {"id": "m", "kind": "revise", "targets": "merge-pr-11"},
                        {"id": "m", "kind": "revise", "targets": [""]}):
            with self.subTest(message=message):
                result = ga.step_boundary(pending, [message], acknowledged_ids=["m"])
                self.assertEqual(result.reason, "malformed_message")
        unknown = ga.step_boundary(pending, [{"id": "m", "kind": "revise", "targets": ["lane-9"]}],
                                   acknowledged_ids=["m"])
        self.assertEqual(unknown.value["continue"], pending)
        self.assertEqual(unknown.detail["unknown_targets"], ["lane-9"])


# ---------------------------------------------------------------------------
# Fix batch 2 — review round 2 residuals R2-B5 and R2-B8 (reviewer repro inputs)
# ---------------------------------------------------------------------------


class FixBatch2Regressions(unittest.TestCase):
    def test_r2_b5_operation_is_a_required_exact_binding(self):
        c = _new_begin_ctx()
        auth = _auth(c)
        c["operation"] = "release"
        result = ga.check_begin(c, scope={"targets": [c["target"]], "operations": ["merge", "release"]},
                                authority=auth)
        self.assertEqual((result.outcome, result.reason, result.detail["field"]),
                         ("invalid", "authority_binding_mismatch", "operation"))
        ctx = _new_begin_ctx()
        unbound_op = gr.Result("accept", detail={"binding": {
            "actor": ctx["actor"], "run": ctx["run"], "target": ctx["target"], "head": ctx["head"],
            "grant_id": ctx["grant_id"]}})
        missing = ga.check_begin(ctx, scope=_SCOPE, authority=unbound_op)
        self.assertEqual((missing.reason, missing.detail["field"]), ("authority_binding_missing", "operation"))
        for empty in ("", None):
            with self.subTest(operation=empty):
                bound = _auth(ctx, operation=empty)
                self.assertEqual((bound.outcome, bound.reason, bound.detail["field"]),
                                 ("invalid", "authority_binding_missing", "operation"))
                self.assertEqual(ga.check_begin(ctx, scope=_SCOPE, authority=bound).reason, "no_authority")
        import inspect
        self.assertIs(inspect.signature(ga.bind_authority).parameters["operation"].default, inspect.Parameter.empty)
        self.assertTrue(ga.check_begin(ctx, scope=_SCOPE, authority=_auth(ctx)).may_proceed)

    def test_r2_b8_mark_state_must_agree_with_its_evidence(self):
        r = _record()
        r["marks"][2]["state"] = "failed"
        result = ga.evaluate_conformance(r)
        self.assertEqual((result.outcome, result.reason), ("invalid", "mark_evidence_mismatch"))
        self.assertEqual((result.detail["foreman_mark"], result.detail["cause"]), ("independent review", "disagrees"))
        merge = _decide(gates=_gates(r))
        self.assertEqual((merge.outcome, merge.reason), ("blocked", "gates_not_satisfied"))
        self.assertIn({"gate": "record_shape", "reason": "mark_evidence_mismatch"}, _gates(r).detail["failures"])

    def test_r2_b8_missing_or_ambiguous_mark_evidence(self):
        no_post = _record()
        no_post["evidence"] = [e for e in no_post["evidence"] if e["gate"] != "post_merge"]
        result = ga.evaluate_conformance(no_post)
        self.assertEqual((result.reason, result.detail["cause"], result.detail["foreman_mark"]),
                         ("mark_evidence_mismatch", "missing", "post-merge record for every merge"))
        twice = _record()
        twice["evidence"].append(dict(twice["evidence"][0]))
        result = ga.evaluate_conformance(twice)
        self.assertEqual((result.reason, result.detail["cause"], result.detail["gate"]),
                         ("mark_evidence_mismatch", "ambiguous", "qa"))
        self.assertEqual(_decide(gates=_gates(twice)).reason, "gates_not_satisfied")
        # A missing mandatory QA entry stays the single missing-evidence defect (sc-4.md).
        no_qa = _record()
        no_qa["evidence"] = no_qa["evidence"][1:]
        self.assertEqual(ga.evaluate_conformance(no_qa).reason, "missing_mandatory_qa")
        # Record-field marks have no evidence entry and are not resolved against one.
        record_marks = _record()
        record_marks["marks"][0]["state"] = "pending"
        record_marks["marks"][4]["state"] = "pending"
        self.assertTrue(ga.evaluate_conformance(record_marks).may_proceed)


# ---------------------------------------------------------------------------
# AC8 — no side effects
# ---------------------------------------------------------------------------

_ALLOWED_IMPORTS = {"__future__", "importlib", "importlib.util", "re", "sys", "dataclasses", "datetime",
                    "pathlib", "typing", "json"}
_FORBIDDEN_NAMES = {"open", "eval", "exec", "input", "print", "__import__"}
_FORBIDDEN_ATTRS = {
    ("datetime", "now"), ("datetime", "utcnow"), ("datetime", "today"), ("date", "today"),
    ("time", "time"), ("time", "monotonic"), ("time", "sleep"), ("time", "perf_counter"),
    ("os", "system"), ("os", "popen"), ("os", "remove"), ("os", "unlink"), ("os", "makedirs"),
}
_FORBIDDEN_METHODS = {"write_text", "write_bytes", "mkdir", "unlink", "rmdir", "touch", "rename",
                      "replace_file", "urlopen", "Popen", "run", "check_output", "copyfile", "rmtree", "move"}


class AC8NoSideEffects(unittest.TestCase):
    def setUp(self):
        self.source = MODULE_PATH.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def test_ac8_imports_are_stdlib_allowlist_only(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(alias.name, _ALLOWED_IMPORTS)
            elif isinstance(node, ast.ImportFrom):
                self.assertIn(node.module, _ALLOWED_IMPORTS)

    def test_ac8_no_io_clock_or_process_calls(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    self.assertNotIn(func.id, _FORBIDDEN_NAMES, ast.dump(node)[:80])
                elif isinstance(func, ast.Attribute):
                    self.assertNotIn(func.attr, _FORBIDDEN_METHODS, ast.dump(node)[:80])
                    if isinstance(func.value, ast.Name):
                        self.assertNotIn((func.value.id, func.attr), _FORBIDDEN_ATTRS)
        for word in ("socket", "subprocess", "urllib", "shutil", "http.client", "os.system"):
            with self.subTest(word=word):
                self.assertNotIn(f"import {word}", self.source)

    def test_ac8_compiles_cleanly(self):
        compile(self.source, str(MODULE_PATH), "exec")

    def test_ac8_inputs_are_not_mutated(self):
        grant, request, record = _grant(), _request(), _record()
        before = (copy.deepcopy(grant), copy.deepcopy(request), copy.deepcopy(record))
        _decide(grant=grant, request=request, gates=_gates(record))
        ga.evaluate_conformance(record)
        self.assertEqual((grant, request, record), before)


if __name__ == "__main__":
    unittest.main()
