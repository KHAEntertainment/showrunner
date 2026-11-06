#!/usr/bin/env python3
"""Goal-run authority: gate inventory disposal, gate checks, D2 merge policy,
SC-2 Begin/Continue and the D7.2 control record (Issue #194, lane L3).

Pure-stdlib, side-effect-free module: no network, no subprocess, no file writes
and no clock reads. Every time-dependent function takes ``now`` from the caller.
Nothing here persists state or grants authority by itself: authority comes only
from the owner's approval of a specific goal (SDP D2 l.248). The module checks
whether supplied evidence and a supplied grant permit an action, and says why
not when they do not.

Sources (SDP pin 7177580c): gate inventory l.191-210, D7.2 l.212-230, D2
contract l.232-248, SC-2 continuation fixture l.250, D2 settled l.252-284.
Contracts consumed read-only: ``docs/v2.2/contracts/sc-2.md`` and ``sc-4.md``.

Result shape and reason-code style follow ``goal_run.py`` (L1): this module
reuses its public ``Result`` and ``classify_question`` and copies the small
private helpers it needs (``_invalid``/``_accept`` style constructors and the
aware-datetime parser) instead of importing underscore names.

Outcome vocabulary (``Result.outcome``):

    ``accept``           the checked action may proceed
    ``invalid``          refused; ``reason`` carries a distinct reason code
    ``confirm_each``     no bounded authority for this merge: per-push owner
                         confirmation bound to the reviewed head is required
    ``safe_point_only``  an acknowledged operation may only reach a safe point
                         (finish or roll back the step in hand, then report)
    ``protected_stop``   H1-H5: escalate to the owner immediately
    ``blocked``          wait: a precondition (gate, veto acknowledgement,
                         answer, triage) is outstanding

``Result.may_proceed`` is true only for ``accept``.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

_GOAL_RUN_PATH = Path(__file__).resolve().with_name("goal_run.py")


def _load_goal_run():
    existing = sys.modules.get("goal_run")
    if existing is not None and hasattr(existing, "Result"):
        return existing
    spec = importlib.util.spec_from_file_location("goal_run", _GOAL_RUN_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_goal_run = _load_goal_run()
Result = _goal_run.Result
classify_question = _goal_run.classify_question

__all__ = [
    "Result",
    "GateRow",
    "GATE_INVENTORY",
    "GROUPS",
    "UNRESOLVED_DECISIONS",
    "FOREMAN_MARKS",
    "MergeLedger",
    "dispose_gate",
    "resolve_family",
    "evaluate_conformance",
    "check_current_head",
    "check_destination",
    "check_qa",
    "check_review_level",
    "check_unresolved_ask",
    "check_external_review",
    "check_gates",
    "validate_grant",
    "amend_grant",
    "carry_grant",
    "revoke_grant",
    "decide_merge",
    "record_merge",
    "record_post_merge_failure",
    "clear_halt",
    "check_action",
    "evaluate_authorization",
    "bind_authority",
    "check_begin",
    "check_continue",
    "validate_delegated_record",
    "step_boundary",
    "check_dependencies",
    "next_question",
    "route_question",
    "escalate",
    "proceed_unless_stopped",
]

ACCEPT = "accept"
INVALID = "invalid"
CONFIRM_EACH = "confirm_each"
SAFE_POINT_ONLY = "safe_point_only"
PROTECTED_STOP = "protected_stop"
BLOCKED = "blocked"

MODE_STANDALONE = "standalone"
MODE_MANAGED = "managed"

PRESERVED = "preserved_lead_owned"
DELEGATED = "delegated_d7_2"
SUPERSEDED = "superseded_interactive"
PROTECTED = "protected"
DISPOSITIONS = (PRESERVED, DELEGATED, SUPERSEDED, PROTECTED)

FAMILY_UNKNOWN = "unknown"
QUALIFYING_ROUTES = ("different_family", "clean_context_same_family")
ROUTE_SOURCES = ("different_family", "clean_context_same_family", "same_family", "none")

EVIDENCE_STATES = ("required", "valid-skip", "pending", "failed")
EXTERNAL_REVIEW_PASS = ("clear", "not_applicable")
PROTECTED_STOP_CATEGORIES = ("H1", "H2", "H3", "H4", "H5")
DEFAULT_MERGE_METHOD = "squash"
MAX_QUESTION_BATCH = 3

_QUALIFIED_ISSUE_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[0-9]+$")
_QUALIFIED_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)


# ---------------------------------------------------------------------------
# Small helpers (copied in style from goal_run; private names are not imported)
# ---------------------------------------------------------------------------


def _result(outcome: str, reason: str = "", value: Any = None, detail=None) -> Result:
    return Result(outcome, reason=reason, value=value, detail=dict(detail or {}))


def _accept(value: Any = None, detail=None) -> Result:
    return _result(ACCEPT, value=value, detail=detail)


def _invalid(reason: str, detail=None) -> Result:
    return _result(INVALID, reason=reason, detail=detail)


def _confirm_each(reason: str, detail=None) -> Result:
    return _result(CONFIRM_EACH, reason=reason, detail=detail)


def _blocked(reason: str, detail=None) -> Result:
    return _result(BLOCKED, reason=reason, detail=detail)


def _nonempty_str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_positive_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _aware(value) -> Optional[datetime]:
    """Return an aware ``datetime`` for an absolute, timezone-qualified value
    (ISO 8601 with ``Z`` or ``±HH:MM``, or an aware ``datetime``); ``None`` for a
    naive, malformed or missing value. Any offset is accepted: D2 asks for an
    absolute timezone-qualified time, not UTC specifically."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None and value.utcoffset() is not None else None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not _ISO_RE.fullmatch(text):
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


# ---------------------------------------------------------------------------
# 1. Gate inventory disposal (SDP l.191-210, disposed under D7.2 and D2)
# ---------------------------------------------------------------------------

GROUPS = {
    1: ("A", 197, "backend detection/adapter load; serial/parallel topology; worktree preparation and destination verification"),
    2: ("A", 198, "worker/QA/reviewer dispatch and worker-plan approval; tier-based QA floors (v2.1.3); prototype dispatch"),
    3: ("A", 199, "external-review observation/inspection/triage; static analysis, scope-drift checks, two-pass review, coverage audit, adversarial second opinion; final review rating"),
    4: ("A", 200, "post-merge coordination/verification/Issue reopening; retro, debt sweep, cleanup Issues, agent shutdown"),
    5: ("B", 201, "Phase 0 classification and verified setup proposal"),
    6: ("B", 202, "module lock, per-module questions/satisfied, scenario stress-test, PRD freeze"),
    7: ("B", 203, "architecture checkpoint, task list/dependency DAG, lightweight/express Issue confirmation"),
    8: ("B", 204, "review ASK disposition, COMMENT decisions, external-review re-requests, mid-run backend/topology changes"),
    9: ("C", 205, "tracked/invalid/conflicting .dev.json, conflicting first-time destinations, fork/upstream preset, new-repo owner/name/visibility"),
    10: ("C", 206, "merges, force-push, deletions including worktrees, tag pushes, releases, marketplace/formula publication"),
    11: ("C", 207, "external-review bypass, unknown trusted reviewer identities, cross-repo target overrides, nonstandard hotfix base, auth/credential anomalies"),
    12: ("C", 208, "product-intent ambiguity, scope beyond the goal, scenario opt-out"),
}

DEV_REF_NONE = "none (v2.2 new)"

# Decisions a gate's value may depend on that are not settled. A gate tied to
# one of these is never delegated: dispose_gate returns ``unresolved_decision``.
# D7.2 item 2 (SDP l.221) delegates confirmation of *lightweight* Issues only;
# the inventory row (l.203) also names express-mode Issue confirmation, which
# D7.2 does not settle.
UNRESOLVED_DECISIONS = frozenset({"express-issue-confirmation"})


@dataclass(frozen=True)
class GateRow:
    gate_id: str
    name: str
    group: int
    tier: str
    disposition: str
    delegable: bool
    condition: str
    sdp_line: int
    dev_refs: tuple
    decisions: tuple = ()

    def to_dict(self) -> dict:
        return {
            "gate_id": self.gate_id,
            "name": self.name,
            "group": self.group,
            "tier": self.tier,
            "disposition": self.disposition,
            "delegable": self.delegable,
            "condition": self.condition,
            "sdp_line": self.sdp_line,
            "dev_refs": list(self.dev_refs),
            "decisions": list(self.decisions),
        }


def _row(gate_id, name, group, disposition, condition, dev_refs, decisions=()):
    tier, line, _ = GROUPS[group]
    return GateRow(
        gate_id=gate_id,
        name=name,
        group=group,
        tier=tier,
        disposition=disposition,
        delegable=disposition == DELEGATED,
        condition=condition,
        sdp_line=line,
        dev_refs=tuple(dev_refs),
        decisions=tuple(decisions),
    )


_A_KEEP = "Preserve existing lead-owned behavior and fail-closed detection; do not weaken verification."
_A_ROLE = "Preserve the existing lead role and the worker-plan gates."
_A_QUALITY = "Preserve quality gates and lead accountability; reviewer lanes remain advisory."
_A_POST = "Preserve existing responsibilities; merge authority remains separate under D2."
_B_SUPERSEDED = "Superseded as an autonomous delegation for v2.2: Phase 1 stays interactive; approved-input reuse; the user owns scenario opt-out."
_C_SETUP = "Protected setup/public-destination boundary; autonomous mode is not authorization."
_C_AUTH = "Explicit authority boundary; D2 alone addresses the bounded merge exception."
_C_APPROVAL = "Explicit approval or fail-closed handling; no implicit bypass from goal mode."
_C_USER = "User ownership; neither a plan nor a merge policy broadens the authorized goal."

GATE_INVENTORY = (
    # Group 1 — Tier A
    _row("backend_detection", "backend detection and adapter load", 1, PRESERVED, _A_KEEP,
         ["SKILL.md § Execution Backend and Topology Policy", "backends/contract.md § Common invariants"]),
    _row("topology", "serial/parallel topology", 1, PRESERVED, _A_KEEP,
         ["phases/phase3.md § Select Backend and Topology"]),
    _row("worktree_destination", "worktree preparation and destination verification", 1, PRESERVED, _A_KEEP,
         ["phases/phase3.md § Prepare Coding Worktrees",
          "phases/repository-context.md § Pre-write verification (run immediately before every push and every GitHub mutation)"]),
    # Group 2 — Tier A
    _row("lane_dispatch", "worker/QA/reviewer dispatch", 2, PRESERVED, _A_ROLE,
         ["phases/phase3.md § Dispatch Prompts", "phases/phase3.5.md § Prepare the QA Lane"]),
    _row("worker_plan_approval", "worker-plan approval (architecture/database/auth/interface/migration/refactor)", 2, PRESERVED, _A_ROLE,
         ["phases/phase3.md § Dispatch Prompts", "agents/worker-new.md § [Step 2: Design First]"]),
    _row("qa_tier_floor", "tier-based QA floors (v2.1.3)", 2, PRESERVED, _A_ROLE,
         ["phases/phase3.5.md § Risk Tiers"]),
    _row("prototype_dispatch", "prototype dispatch", 2, PRESERVED,
         "Interactive planning does not itself revoke existing prototype-dispatch behavior.",
         ["phases/phase1-prototyping.md § Step 4 — Dispatch"]),
    # Group 3 — Tier A
    _row("external_review_observation", "external-review observation", 3, PRESERVED, _A_QUALITY,
         ["phases/external-review.md § Start Observation in Phase 3.5"]),
    _row("external_review_inspection", "external-review inspection", 3, PRESERVED, _A_QUALITY,
         ["phases/external-review.md § Inspect One PR"]),
    _row("external_review_triage", "external-review triage", 3, PRESERVED, _A_QUALITY,
         ["phases/external-review.md § Triage Current-Head Findings"]),
    _row("static_analysis", "static analysis", 3, PRESERVED, _A_QUALITY,
         ["phases/phase4.md § Static Analysis Gate (run before human review)"]),
    _row("scope_drift", "scope-drift checks", 3, PRESERVED, _A_QUALITY,
         ["phases/phase4.md § Step 0 — Scope-Drift Gate"]),
    _row("two_pass_review", "two-pass review", 3, PRESERVED, _A_QUALITY,
         ["phases/phase4.md § Two-Pass Review"]),
    _row("coverage_audit", "coverage audit", 3, PRESERVED, _A_QUALITY,
         ["phases/phase4.md § Coverage-Path Audit"]),
    _row("adversarial_second_opinion", "adversarial second opinion", 3, PRESERVED, _A_QUALITY,
         ["phases/phase4.md § Adversarial Second Opinion"]),
    _row("final_review_rating", "final review rating", 3, PRESERVED, _A_QUALITY,
         ["phases/phase4.md § Review Rating"]),
    # Group 4 — Tier A
    _row("post_merge_coordination", "post-merge coordination", 4, PRESERVED, _A_POST,
         ["phases/phase4.md § Post-Merge: Affected PR Coordination (mandatory after every merge)"]),
    _row("post_merge_verification", "post-merge verification", 4, PRESERVED, _A_POST,
         ["phases/phase4.md § Post-Merge Verification (unconditional)"]),
    _row("issue_reopening", "Issue reopening", 4, PRESERVED, _A_POST,
         ["phases/phase4.md § Post-Merge Verification (unconditional)"]),
    _row("retro", "retro", 4, PRESERVED, _A_POST,
         ["phases/phase5.md § Step 1 — Retro"]),
    _row("debt_sweep", "debt sweep", 4, PRESERVED, _A_POST,
         ["phases/phase5.md § Step 3 — Focused Debt Sweep"]),
    _row("cleanup_issues", "cleanup Issues", 4, PRESERVED, _A_POST,
         ["phases/phase5.md § Deprecated implementation"]),
    _row("agent_shutdown", "agent shutdown", 4, PRESERVED, _A_POST,
         ["phases/phase5.md § Step 5 — Cleanup and Standby",
          "backends/traycer.md § Observation, shutdown, and recovery"]),
    # Group 5 — Tier B, settled under D7.2 item 1
    _row("phase0_classification", "Phase 0 classification", 5, DELEGATED,
         "Lead proceeds when the setup is verified and has exactly one candidate; conflicting candidates and Tier C setup boundaries come to the user (D7.2.1).",
         ["SKILL.md § Phase 0 — Entry Router"], ["D7.2"]),
    _row("verified_setup_proposal", "verified setup proposal", 5, DELEGATED,
         "Lead proceeds when the setup is verified and has exactly one candidate; conflicting candidates and Tier C setup boundaries come to the user (D7.2.1).",
         ["SKILL.md § Repository & Account Setup (run before any GitHub mutation)",
          "phases/repository-context.md § First invocation (run before any GitHub mutation, Phase 0)"], ["D7.2"]),
    # Group 6 — Tier B, superseded
    _row("module_lock", "module lock", 6, SUPERSEDED, _B_SUPERSEDED,
         ["phases/phase1.md § A.3 Lock the module list (mandatory handshake)"]),
    _row("per_module_questions", "per-module questions / satisfied", 6, SUPERSEDED, _B_SUPERSEDED,
         ["phases/phase1.md § B.1 Three-layer progressive questioning", "phases/phase1.md § Step C — Module switch gate"]),
    _row("scenario_stress_test", "scenario stress-test", 6, SUPERSEDED, _B_SUPERSEDED,
         ["phases/phase1.md § B.3 Scenario stress-test (mandatory before module close-out)"]),
    _row("prd_freeze", "PRD freeze", 6, SUPERSEDED, _B_SUPERSEDED,
         ["phases/phase1.md § Step D — All modules complete → freeze the PRD"]),
    # Group 7 — Tier B, settled under D7.2 item 2
    _row("architecture_checkpoint", "architecture checkpoint", 7, DELEGATED,
         "Engineering judgment is the lead's; a conflict with the approved plan or PROJECT_CONTEXT.md stops dependent work and surfaces (D7.2.2).",
         ["phases/phase2.md § Architecture Decision Checkpoint (run for all modes, before task decomposition)"], ["D7.2"]),
    _row("task_dag", "task list and dependency DAG", 7, DELEGATED,
         "Lead decides task order and the dependency graph; the transition to the frozen goal set records the Issues and their order (D7.2.2).",
         ["phases/phase2.md § Execution Steps"], ["D7.2"]),
    _row("lightweight_issue_confirmation", "lightweight Issue confirmation", 7, DELEGATED,
         "Only within the approved goal; product priority, scope and acceptance stay with the user (D7.2.2).",
         ["phases/phase2.md § Lightweight Mode (Small Change / Bug Fix)"], ["D7.2"]),
    _row("express_issue_confirmation", "express Issue confirmation", 7, PROTECTED,
         "Not delegated: D7.2.2 names only lightweight Issues. Existing user confirmation stays until the owner settles express mode.",
         ["phases/phase2.md § Express Mode (Emergency Hotfix)"], ["express-issue-confirmation"]),
    # Group 8 — Tier B, settled under D7.2 item 3
    _row("technical_ask_disposition", "technical review ASK disposition", 8, DELEGATED,
         "Lead resolves with a second opinion and a recorded disposition (D7.2.3).",
         ["phases/phase4.md § Two-Pass Review", "phases/phase4.md § Adversarial Second Opinion"], ["D7.2"]),
    _row("product_ask_disposition", "product review ASK disposition", 8, PROTECTED,
         "A product question stays with the user (D7.2.3).",
         ["phases/phase4.md § Two-Pass Review"]),
    _row("comment_decisions", "COMMENT decisions", 8, DELEGATED,
         "Technical comments: second opinion plus recorded disposition; product comments stay with the user (D7.2.3).",
         ["phases/phase4.md § Review Rating"], ["D7.2"]),
    _row("external_review_rerequest", "external-review re-requests", 8, DELEGATED,
         "Follow the project's review policy (v2.1.3 T1: CI plus one qualified review) (D7.2.3).",
         ["phases/external-review.md § Waiting and Explicit Decisions",
          "phases/external-review.md § Rate-limited review retries"], ["D7.2"]),
    _row("midrun_backend_change", "mid-run backend/topology change", 8, DELEGATED,
         "Recorded with a change notice; a detection failure still stops execution (D7.2.3).",
         ["SKILL.md § Execution Backend and Topology Policy"], ["D7.2"]),
    # Group 9 — Tier C
    _row("dev_json_tracked", "tracked .dev.json", 9, PROTECTED, _C_SETUP,
         ["phases/repository-context.md § First invocation (run before any GitHub mutation, Phase 0)"]),
    _row("dev_json_invalid", "invalid .dev.json", 9, PROTECTED, _C_SETUP,
         ["phases/repository-context.md § First invocation (run before any GitHub mutation, Phase 0)"]),
    _row("dev_json_conflicting", "conflicting .dev.json", 9, PROTECTED, _C_SETUP,
         ["phases/repository-context.md § First invocation (run before any GitHub mutation, Phase 0)"]),
    _row("first_time_destination_conflict", "conflicting first-time destinations", 9, PROTECTED, _C_SETUP,
         ["phases/repository-context.md § First invocation (run before any GitHub mutation, Phase 0)"]),
    _row("fork_upstream_preset", "fork/upstream preset", 9, PROTECTED, _C_SETUP,
         ["phases/repository-context.md § First invocation (run before any GitHub mutation, Phase 0)"]),
    _row("new_repo_identity", "new-repo owner/name/visibility", 9, PROTECTED, _C_SETUP,
         ["phases/repository-context.md § A genuinely new project (no remote yet)"]),
    # Group 10 — Tier C
    _row("merge", "merges", 10, PROTECTED,
         "Protected; the only exception is a D2 bounded per-run grant checked by decide_merge.",
         ["phases/phase4.md § Merge Order"]),
    _row("force_push", "force-push", 10, PROTECTED, _C_AUTH,
         ["phases/repository-context.md § Before a force-with-lease push (rebased branch)"]),
    _row("deletions", "deletions including worktrees", 10, PROTECTED, _C_AUTH,
         ["phases/phase5.md § Step 5 — Cleanup and Standby",
          "backends/traycer.md § Observation, shutdown, and recovery"]),
    _row("tag_push", "tag pushes", 10, PROTECTED, _C_AUTH,
         ["phases/repository-context.md § Before a release tag push"]),
    _row("release", "releases", 10, PROTECTED, _C_AUTH,
         ["phases/repository-context.md § Before a release tag push"]),
    _row("marketplace_publication", "marketplace/formula publication", 10, PROTECTED, _C_AUTH,
         [DEV_REF_NONE]),
    # Group 11 — Tier C
    _row("external_review_bypass", "external-review bypass", 11, PROTECTED, _C_APPROVAL,
         ["phases/external-review.md § Waiting and Explicit Decisions"]),
    _row("unknown_reviewer_identity", "unknown trusted reviewer identities", 11, PROTECTED, _C_APPROVAL,
         ["phases/external-review.md § Ask once about unknown review bots, record the answer"]),
    _row("cross_repo_override", "cross-repo target overrides", 11, PROTECTED, _C_APPROVAL,
         ["phases/repository-context.md § Before a PR or Issue operation"]),
    _row("nonstandard_hotfix_base", "nonstandard hotfix base", 11, PROTECTED, _C_APPROVAL,
         ["SKILL.md § Repository & Account Setup (run before any GitHub mutation)"]),
    _row("auth_anomaly", "auth/credential anomalies", 11, PROTECTED, _C_APPROVAL,
         ["phases/repository-context.md § Authentication support boundary"]),
    # Group 12 — Tier C
    _row("product_intent_ambiguity", "product-intent ambiguity", 12, PROTECTED, _C_USER,
         ["phases/phase1.md § A.1 Top-level questions (one at a time)"]),
    _row("scope_beyond_goal", "scope beyond the goal", 12, PROTECTED, _C_USER,
         ["phases/phase4.md § Step 0 — Scope-Drift Gate"]),
    _row("scenario_opt_out", "scenario opt-out", 12, PROTECTED, _C_USER,
         ["phases/phase1.md § B.3 Scenario stress-test (mandatory before module close-out)"]),
)

_GATES_BY_ID = {row.gate_id: row for row in GATE_INVENTORY}


def dispose_gate(gate_id, unresolved_decisions: Optional[Iterable[str]] = None) -> Result:
    """Return the disposal row for ``gate_id``. ``unresolved_decisions`` adds to
    the module's ``UNRESOLVED_DECISIONS``; a gate whose value depends on any of
    them is refused with ``unresolved_decision`` and is never delegated."""
    row = _GATES_BY_ID.get(gate_id)
    if row is None:
        return _invalid("unknown_gate", {"gate": gate_id})
    pending = set(UNRESOLVED_DECISIONS) | set(unresolved_decisions or ())
    blocking = sorted(set(row.decisions) & pending)
    if blocking:
        return _invalid("unresolved_decision", {"gate": gate_id, "decisions": blocking})
    return _accept(row)


# ---------------------------------------------------------------------------
# 2. Identity, family and SC-4 conformance
# ---------------------------------------------------------------------------


def resolve_family(identity, family_map: Optional[Mapping] = None) -> str:
    """Model family from an explicit ``family`` member, or from the caller's
    ``family_map`` keyed by ``(harness, model)``. The text before ':' in a model
    id is a provider/route prefix, never a family, so nothing is guessed:
    anything else is ``unknown``."""
    if not isinstance(identity, Mapping):
        return FAMILY_UNKNOWN
    explicit = identity.get("family")
    if _nonempty_str(explicit):
        return explicit.strip()
    if family_map:
        mapped = family_map.get((identity.get("harness"), identity.get("model")))
        if _nonempty_str(mapped):
            return mapped.strip()
    return FAMILY_UNKNOWN


def _route_verdict(
    reviewer_identity,
    implementer_identity,
    family_map=None,
    single_provider_reason=None,
    memory_disclosure=None,
    different_family_available=None,
) -> Result:
    """Does a recorded reviewer identity meet a D2 independent-review route
    (SDP l.264-268) against the implementer's family? An identity missing
    ``agent_id``, ``harness`` or ``model`` is unknown and never qualifies."""
    if not _identity_complete(reviewer_identity):
        return _invalid("reviewer_identity_unknown")
    if not _identity_complete(implementer_identity):
        return _invalid("implementer_identity_unknown")
    route = reviewer_identity.get("route_source")
    if route not in ROUTE_SOURCES:
        return _invalid("route_unknown", {"route_source": route})
    if route not in QUALIFYING_ROUTES:
        return _invalid("route_not_qualifying", {"route_source": route})
    if implementer_identity["agent_id"] == reviewer_identity["agent_id"]:
        return _invalid("reviewer_is_implementer")
    reviewer_family = resolve_family(reviewer_identity, family_map)
    implementer_family = resolve_family(implementer_identity, family_map)
    if reviewer_family == FAMILY_UNKNOWN or implementer_family == FAMILY_UNKNOWN:
        return _invalid(
            "family_unknown",
            {"reviewer_family": reviewer_family, "implementer_family": implementer_family},
        )
    if route == "different_family":
        if reviewer_family == implementer_family:
            return _invalid("route_family_mismatch", {"family": reviewer_family})
        return _accept(detail={"route_source": route})
    # clean_context_same_family
    if reviewer_family != implementer_family:
        return _invalid("route_family_mismatch", {"route_source": route})
    if different_family_available is not False:
        return _invalid("different_family_available")
    if not _nonempty_str(single_provider_reason):
        return _invalid("single_provider_reason_missing")
    if not _valid_memory_disclosure(memory_disclosure):
        return _invalid("memory_disclosure_missing")
    return _accept(
        detail={
            "route_source": route,
            "memory_isolation": "not_demonstrated",
            "memory_disclosure": memory_disclosure,
        }
    )


def _valid_memory_disclosure(value) -> bool:
    if value == "unknown":
        return True
    if isinstance(value, (list, tuple)) and value:
        return all(_nonempty_str(v) for v in value)
    return False


_IDENTITY_MEMBERS = ("agent_id", "harness", "model")


def _identity_complete(identity) -> bool:
    """A usable identity names ``agent_id``, ``harness`` and ``model``."""
    return isinstance(identity, Mapping) and all(_nonempty_str(identity.get(k)) for k in _IDENTITY_MEMBERS)


_SC4_REQUIRED = ("workflow", "policy_revision", "run", "lane", "head", "gate_applicability",
                 "evidence", "marks", "evaluator", "report_ref")
_SC4_MARK_COUNT = 6
# The six Foreman checklist marks (sc-4.md, Foreman mark -> Dev applicability).
FOREMAN_MARKS = (
    "workflow phase reported",
    "acceptance lane",
    "independent review",
    "post-merge record for every merge",
    "seat receipts current",
    "lane upkeep",
)


def _marks_shape(marks) -> Result:
    if not isinstance(marks, (list, tuple)) or len(marks) != _SC4_MARK_COUNT:
        return _invalid("marks_incomplete", {"layer": "shape"})
    seen = []
    for mark in marks:
        if not isinstance(mark, Mapping):
            return _invalid("marks_malformed", {"layer": "shape"})
        name = mark.get("foreman_mark")
        if not _nonempty_str(name) or name.strip().lower() not in FOREMAN_MARKS:
            return _invalid("marks_malformed", {"layer": "shape", "foreman_mark": name})
        if not _nonempty_str(mark.get("dev_applicability")):
            return _invalid("marks_malformed", {"layer": "shape", "foreman_mark": name, "field": "dev_applicability"})
        if mark.get("state") not in EVIDENCE_STATES:
            return _invalid("marks_malformed", {"layer": "shape", "foreman_mark": name, "field": "state"})
        seen.append(name.strip().lower())
    if sorted(seen) != sorted(FOREMAN_MARKS):
        return _invalid("marks_malformed", {"layer": "shape", "reason": "each Foreman mark exactly once"})
    return _accept()


def _sc4_shape(record) -> Result:
    if not isinstance(record, Mapping):
        return _invalid("malformed_record", {"layer": "shape"})
    for name in _SC4_REQUIRED:
        if name not in record or record[name] in (None, "", [], {}):
            return _invalid("missing_required_field", {"layer": "shape", "field": name})
    if not isinstance(record["evidence"], (list, tuple)) or not isinstance(record["marks"], (list, tuple)):
        return _invalid("malformed_record", {"layer": "shape"})
    for entry in record["evidence"]:
        if not isinstance(entry, Mapping) or not _nonempty_str(entry.get("gate")):
            return _invalid("malformed_evidence", {"layer": "shape"})
        state = entry.get("state")
        if state not in EVIDENCE_STATES:
            return _invalid("unknown_evidence_state", {"layer": "shape", "gate": entry.get("gate")})
        if state == "required" and not (_nonempty_str(entry.get("evaluator")) and _nonempty_str(entry.get("report_ref"))):
            return _invalid("required_evidence_unnamed", {"layer": "shape", "gate": entry["gate"]})
        if state == "valid-skip" and not _nonempty_str(entry.get("reason")):
            return _invalid("skip_without_reason", {"layer": "shape", "gate": entry["gate"]})
    return _marks_shape(record["marks"])


def _evidence_for(record, gate: str):
    entries = [e for e in record.get("evidence", ()) if isinstance(e, Mapping) and e.get("gate") == gate]
    return entries[0] if entries else None


def evaluate_conformance(record, family_map: Optional[Mapping] = None, implementer_identity=None) -> Result:
    """Evaluate an SC-4 ``conformance-v1`` record: ``accept`` or ``invalid``
    (the fixtures' ``reject``). Absence of ``evaluator_identity`` never rejects
    the record (it is resolved later against the ledger); a *recorded*
    identity is authoritative: malformed, it rejects, and a recorded review
    identity must meet a D2 route. ``implementer_identity`` is the producer's
    ledger identity, used only when the record carries none."""
    shape = _sc4_shape(record)
    if not shape.may_proceed:
        return shape
    for key in ("evaluator_identity", "implementer_identity"):
        if key in record and not _identity_complete(record[key]):
            return _invalid(f"{key}_malformed", {"layer": "gate"})
    if "evaluator_identity" in record and record["evaluator_identity"].get("route_source") not in ROUTE_SOURCES:
        return _invalid("evaluator_identity_malformed", {"layer": "gate", "field": "route_source"})
    head = record["head"]
    for entry in record["evidence"]:
        entry_head = entry.get("head")
        if entry_head is not None and entry_head != head:
            return _invalid("different_head_evidence", {"layer": "gate", "gate": entry["gate"]})
    qa = _evidence_for(record, "qa")
    if qa is None:
        return _invalid("missing_mandatory_qa", {"layer": "gate"})
    if record["gate_applicability"] == "qa_required" and qa.get("state") != "required":
        return _invalid("missing_mandatory_qa", {"layer": "gate", "state": qa.get("state")})
    if qa.get("state") in ("pending", "failed"):
        return _invalid("qa_not_satisfied", {"layer": "gate", "state": qa.get("state")})
    review = _evidence_for(record, "review")
    if review is None or review.get("state") != "required":
        return _invalid("missing_mandatory_review", {"layer": "gate"})
    if "evaluator_identity" in review:
        verdict = _route_verdict(
            review.get("evaluator_identity"),
            record["implementer_identity"] if "implementer_identity" in record else implementer_identity,
            family_map=family_map,
            single_provider_reason=record.get("single_provider_reason"),
            memory_disclosure=record.get("memory_disclosure"),
            different_family_available=record.get("different_family_available"),
        )
        if not verdict.may_proceed:
            return _invalid(verdict.reason, {"layer": "gate", **verdict.detail})
    return _accept()


# ---------------------------------------------------------------------------
# 2b. Gate checks for one PR at its current head (D2 contract l.240-241)
# ---------------------------------------------------------------------------


def check_current_head(record, current_head) -> Result:
    if not _nonempty_str(current_head):
        return _invalid("current_head_unknown")
    if not isinstance(record, Mapping) or record.get("head") != current_head:
        return _invalid("head_mismatch", {"reviewed": (record or {}).get("head") if isinstance(record, Mapping) else None,
                                          "current": current_head})
    for entry in record.get("evidence", ()):
        if isinstance(entry, Mapping) and entry.get("head") not in (None, current_head):
            return _invalid("stale_evidence_head", {"gate": entry.get("gate")})
    return _accept()


def check_destination(destination_result) -> Result:
    """The caller supplies the ``.dev.json`` pre-write verification result for
    this merge, re-run at the last moment; only ``ready`` passes."""
    status = destination_result.get("status") if isinstance(destination_result, Mapping) else destination_result
    if status == "ready":
        return _accept()
    return _invalid("destination_not_verified", {"status": status})


def check_qa(record, qa_skip_allowed: bool = False) -> Result:
    """Current-head QA pass, or a valid recorded skip when the tier floor allows
    one (caller passes ``qa_skip_allowed`` from the recorded risk tier)."""
    if not isinstance(record, Mapping):
        return _invalid("qa_missing")
    qa = _evidence_for(record, "qa")
    if qa is None:
        return _invalid("qa_missing")
    if qa.get("head") not in (None, record.get("head")):
        return _invalid("qa_stale_head")
    state = qa.get("state")
    if state == "required":
        if _nonempty_str(qa.get("evaluator")) and _nonempty_str(qa.get("report_ref")):
            return _accept(detail={"qa": "pass"})
        return _invalid("qa_unnamed")
    if state == "valid-skip":
        if not _nonempty_str(qa.get("reason")):
            return _invalid("qa_skip_without_reason")
        if not qa_skip_allowed or record.get("gate_applicability") == "qa_required":
            return _invalid("qa_skip_not_allowed")
        return _accept(detail={"qa": "valid-skip"})
    if state == "pending":
        return _invalid("qa_pending")
    if state == "failed":
        return _invalid("qa_failed")
    return _invalid("qa_missing")


def check_review_level(
    record,
    ci_required_checks,
    *,
    ledger_identity=None,
    implementer_identity=None,
    family_map=None,
    single_provider_reason=None,
    memory_disclosure=None,
    different_family_available=None,
) -> Result:
    """D2 review-level rule (SDP l.262-269): CI required checks pass, plus an
    independent review by a qualifying route. The review entry must carry the
    SC-4 ``required`` shape (evaluator and report). Identity comes from the
    review entry's ``evaluator_identity`` when that key is present — recorded
    identities are authoritative, so a malformed one fails and is never
    replaced — and from the caller's ledger identity only when the key is
    absent. A missing or incomplete identity is ``unknown`` and fails this
    rule (never the record shape). The implementer works the same way."""
    if ci_required_checks != "pass":
        return _invalid("ci_required_checks_not_passed", {"ci": ci_required_checks})
    if not isinstance(record, Mapping):
        return _invalid("review_missing")
    review = _evidence_for(record, "review")
    if review is None or review.get("state") != "required":
        return _invalid("review_missing")
    if not (_nonempty_str(review.get("evaluator")) and _nonempty_str(review.get("report_ref"))):
        return _invalid("review_unnamed")
    if review.get("head") not in (None, record.get("head")):
        return _invalid("review_stale_head")
    reviewer = review["evaluator_identity"] if "evaluator_identity" in review else ledger_identity
    implementer = record["implementer_identity"] if "implementer_identity" in record else implementer_identity
    return _route_verdict(
        reviewer,
        implementer,
        family_map=family_map,
        single_provider_reason=single_provider_reason,
        memory_disclosure=memory_disclosure,
        different_family_available=different_family_available,
    )


def check_unresolved_ask(open_asks) -> Result:
    if open_asks is None:
        return _invalid("ask_state_unknown")
    asks = list(open_asks)
    if asks:
        return _invalid("unresolved_ask", {"asks": asks})
    return _accept()


def check_external_review(state) -> Result:
    """Only ``clear`` and ``not_applicable`` pass; every other state fails with
    its own reason (``external_review_<state>``)."""
    if state in EXTERNAL_REVIEW_PASS:
        return _accept(detail={"external_review": state})
    if state in ("pending", "incomplete", "blocking", "unknown"):
        return _invalid(f"external_review_{state}")
    return _invalid("external_review_unrecognized", {"state": state})


def check_gates(
    record,
    *,
    current_head,
    destination_result,
    open_asks,
    external_review,
    ci_required_checks,
    qa_skip_allowed=False,
    ledger_identity=None,
    implementer_identity=None,
    family_map=None,
    single_provider_reason=None,
    memory_disclosure=None,
    different_family_available=None,
) -> Result:
    """Run every gate check for one PR. ``accept`` only when all pass; otherwise
    ``blocked`` with reason ``gates_not_satisfied`` and the failing gates in
    ``detail['failures']`` (``[{gate, reason}]``). ``detail['checked_head']``
    names the head these results are for; ``decide_merge`` refuses a result
    checked at another head. No owner approval, extra review or local
    full-suite run is asked for beyond these inputs."""
    checks = (
        ("record_shape", _sc4_shape(record)),
        ("current_head", check_current_head(record, current_head)),
        ("destination", check_destination(destination_result)),
        ("qa", check_qa(record, qa_skip_allowed)),
        ("review_level", check_review_level(
            record, ci_required_checks,
            ledger_identity=ledger_identity,
            implementer_identity=implementer_identity,
            family_map=family_map,
            single_provider_reason=single_provider_reason,
            memory_disclosure=memory_disclosure,
            different_family_available=different_family_available,
        )),
        ("ask", check_unresolved_ask(open_asks)),
        ("external_review", check_external_review(external_review)),
    )
    failures = [{"gate": name, "reason": res.reason} for name, res in checks if not res.may_proceed]
    detail = {name: res.detail for name, res in checks if res.may_proceed and res.detail}
    if failures:
        return _blocked("gates_not_satisfied", {"failures": failures, "checked_head": current_head})
    detail["checked_head"] = current_head
    return _accept(detail=detail)


# ---------------------------------------------------------------------------
# 3. D2 merge policy (contract l.232-248; settled l.252-284)
# ---------------------------------------------------------------------------

_GRANT_FIELDS = ("run_id", "host", "repository", "base", "eligible_issues",
                 "max_merges", "expires_at", "authorized_by", "excluded_actions")


@dataclass(frozen=True)
class MergeLedger:
    """Per-run merge record. Immutable: every change returns a new ledger.
    ``consumed`` holds one ``(pr, merge_sha)`` per successful merge."""

    run_id: str
    consumed: tuple = ()
    revoked_at: Optional[str] = None
    halted: bool = False
    halt_ref: Optional[str] = None
    reopen_issues: tuple = ()
    grant_in_force: bool = True

    @property
    def slots_used(self) -> int:
        return len(self.consumed)


def validate_grant(grant, now=None) -> Result:
    """Check a bounded grant's fields. Any missing or invalid field falls back to
    ``confirm_each`` naming the field. With ``now``, an expired grant (at or
    after ``expires_at``) is ``confirm_each`` / ``grant_expired``."""
    if not isinstance(grant, Mapping):
        return _confirm_each("missing_field", {"field": "grant"})
    for name in _GRANT_FIELDS:
        if name not in grant or grant[name] is None:
            return _confirm_each("missing_field", {"field": name})
    for name in ("run_id", "host", "base"):
        if not _nonempty_str(grant[name]):
            return _confirm_each("invalid_field", {"field": name})
    repo = grant["repository"]
    if not (isinstance(repo, str) and _QUALIFIED_REPO_RE.fullmatch(repo)):
        return _confirm_each("invalid_field", {"field": "repository"})
    issues = grant["eligible_issues"]
    if (
        not isinstance(issues, (list, tuple))
        or not issues
        or len(set(issues)) != len(issues)
        or not all(isinstance(i, str) and _QUALIFIED_ISSUE_RE.fullmatch(i) and i.split("#")[0] == repo for i in issues)
    ):
        return _confirm_each("invalid_field", {"field": "eligible_issues"})
    if not _is_positive_int(grant["max_merges"]):
        return _confirm_each("invalid_field", {"field": "max_merges"})
    expires = _aware(grant["expires_at"])
    if expires is None:
        return _confirm_each("invalid_field", {"field": "expires_at"})
    auth = grant["authorized_by"]
    if not (
        isinstance(auth, Mapping)
        and _nonempty_str(auth.get("who"))
        and _aware(auth.get("at")) is not None
        and _nonempty_str(auth.get("instruction"))
    ):
        return _confirm_each("invalid_field", {"field": "authorized_by"})
    if not isinstance(grant["excluded_actions"], (list, tuple)):
        return _confirm_each("invalid_field", {"field": "excluded_actions"})
    method = grant.get("merge_method", DEFAULT_MERGE_METHOD)
    if not _nonempty_str(method):
        return _confirm_each("invalid_field", {"field": "merge_method"})
    if now is not None:
        current = _aware(now)
        if current is None:
            return _invalid("now_not_timezone_qualified")
        if current >= expires:
            return _confirm_each("grant_expired", {"expires_at": grant["expires_at"]})
    return _accept()


def amend_grant(grant, changes, fresh_authority=None) -> Result:
    """A grant never grows on its own. Adding Issues, raising the cap or
    extending expiry needs ``fresh_authority`` (a new owner authorization
    record); narrowing is always allowed."""
    base = validate_grant(grant)
    if not base.may_proceed:
        return base
    if not isinstance(changes, Mapping):
        return _invalid("malformed_input")
    allowed = {"eligible_issues", "max_merges", "expires_at"}
    if set(changes) - allowed:
        return _invalid("unamendable_field", {"fields": sorted(set(changes) - allowed)})
    grows = []
    if "eligible_issues" in changes and set(changes["eligible_issues"]) - set(grant["eligible_issues"]):
        grows.append("eligible_issues")
    if "max_merges" in changes and _is_positive_int(changes["max_merges"]) and changes["max_merges"] > grant["max_merges"]:
        grows.append("max_merges")
    if "expires_at" in changes:
        new_exp, old_exp = _aware(changes["expires_at"]), _aware(grant["expires_at"])
        if new_exp is not None and new_exp > old_exp:
            grows.append("expires_at")
    amended = dict(grant)
    amended.update(changes)
    if grows:
        if not (
            isinstance(fresh_authority, Mapping)
            and _nonempty_str(fresh_authority.get("who"))
            and _aware(fresh_authority.get("at")) is not None
            and _nonempty_str(fresh_authority.get("instruction"))
            and fresh_authority != grant["authorized_by"]
        ):
            return _invalid("grant_growth", {"fields": grows})
        amended["authorized_by"] = dict(fresh_authority)
    checked = validate_grant(amended)
    if not checked.may_proceed:
        return _invalid("amendment_invalid", {"cause": checked.reason, **checked.detail})
    return _accept(amended, {"grew": grows})


def carry_grant(grant, ledger: MergeLedger, transition, custody_passed=None) -> Result:
    """Grant lifetime across a run transition (D2 item 7): ``restart`` and
    ``compaction`` of the same run keep it; ``takeover`` keeps it only when the
    custody check passed; any other run does not inherit it."""
    if not isinstance(ledger, MergeLedger):
        return _invalid("malformed_input")
    if not isinstance(grant, Mapping) or grant.get("run_id") != ledger.run_id:
        return _invalid("grant_run_mismatch")
    if transition in ("restart", "compaction"):
        return _accept(ledger)
    if transition == "takeover":
        if custody_passed is True:
            return _accept(ledger)
        return _accept(replace(ledger, grant_in_force=False), {"reason": "takeover_without_custody"})
    return _invalid("unknown_transition", {"transition": transition})


def revoke_grant(ledger: MergeLedger, at) -> Result:
    """Record a revocation (a user stop). It takes effect before the next merge."""
    if not isinstance(ledger, MergeLedger) or _aware(at) is None:
        return _invalid("malformed_input")
    return _accept(replace(ledger, revoked_at=at, grant_in_force=False))


def _merge_key(pr, merge_sha):
    return (pr, merge_sha)


def decide_merge(grant, ledger: MergeLedger, request, now, gates: Result, mode=MODE_STANDALONE) -> Result:
    """Decide one automatic merge under a bounded grant.

    ``gates`` is the ``check_gates`` result for this PR at its current head.
    ``now`` is required and must be timezone-qualified: a merge is never
    authorized without checking expiry. Returns ``accept`` (with the merge
    method and ``match_head_commit``), ``confirm_each`` (no bounded authority
    for this merge; the owner may confirm it per push), ``blocked`` (gates, a
    stale gate result or a post-merge halt prevent any merge) or ``invalid``.
    """
    if not isinstance(ledger, MergeLedger) or not isinstance(request, Mapping):
        return _invalid("malformed_input")
    if ledger.halted:
        return _blocked("post_merge_failure_halt", {"halt_ref": ledger.halt_ref})
    if not isinstance(gates, Result):
        return _blocked("gates_not_evaluated")
    checked_head = gates.detail.get("checked_head")
    if not _nonempty_str(checked_head) or checked_head != request.get("head"):
        return _blocked("stale_gate_result", {"checked_head": checked_head, "head": request.get("head")})
    failures = list(gates.detail.get("failures", ())) if not gates.may_proceed else []
    if not gates.may_proceed and (not failures or any(f.get("gate") != "review_level" for f in failures)):
        return _blocked("gates_not_satisfied", {"failures": failures})
    if mode == MODE_MANAGED:
        foreman = request.get("foreman_grant")
        if not (
            isinstance(foreman, Mapping)
            and foreman.get("pr") == request.get("pr")
            and foreman.get("head") == request.get("head")
        ):
            return _invalid("foreman_grant_missing")
    elif mode != MODE_STANDALONE:
        return _invalid("unknown_mode", {"mode": mode})
    if now is None:
        return _confirm_each("now_missing", {"field": "now"})
    if _aware(now) is None:
        return _confirm_each("now_not_timezone_qualified", {"field": "now"})
    if ledger.revoked_at is not None:
        return _confirm_each("grant_revoked", {"revoked_at": ledger.revoked_at})
    if not ledger.grant_in_force:
        return _confirm_each("grant_not_in_force")
    valid = validate_grant(grant, now)
    if not valid.may_proceed:
        return valid
    if grant["run_id"] != ledger.run_id or request.get("run_id") != grant["run_id"]:
        return _confirm_each("grant_run_mismatch")
    for name in ("host", "repository", "base"):
        if request.get(name) != grant[name]:
            return _confirm_each("binding_changed", {"field": name})
    if ledger.slots_used >= grant["max_merges"]:
        return _confirm_each("cap_reached", {"used": ledger.slots_used, "max_merges": grant["max_merges"]})
    issues = request.get("closing_issues")
    if not isinstance(issues, (list, tuple)) or not issues:
        return _confirm_each("no_eligible_closing_issue")
    unlisted = [i for i in issues if i not in grant["eligible_issues"]]
    if unlisted:
        return _confirm_each("unlisted_closing_issue", {"issues": unlisted})
    head = request.get("head")
    if not _nonempty_str(head) or request.get("reviewed_head") != head or request.get("reviewed_head") != checked_head:
        return _confirm_each("head_changed", {"reviewed": request.get("reviewed_head"), "current": head})
    if request.get("head_match_available") is not True:
        return _confirm_each("no_head_match")
    if failures:
        return _confirm_each("review_level_missing", {"failures": failures})
    return _accept(
        {"merge_method": grant.get("merge_method", DEFAULT_MERGE_METHOD), "match_head_commit": head},
        {"slot": ledger.slots_used + 1, "max_merges": grant["max_merges"]},
    )


def record_merge(ledger: MergeLedger, event) -> Result:
    """Record a merge attempt. Only ``outcome: merged`` with a merge SHA
    consumes a slot, keyed by ``(pr, merge_sha)``; a failed merge consumes
    none; replaying the same record never consumes twice."""
    if not isinstance(ledger, MergeLedger) or not isinstance(event, Mapping):
        return _invalid("malformed_input")
    pr = event.get("pr")
    if not _is_positive_int(pr):
        return _invalid("malformed_input", {"field": "pr"})
    outcome = event.get("outcome")
    if outcome == "failed":
        return _accept(ledger, {"slot_consumed": False})
    if outcome != "merged":
        return _invalid("unknown_merge_outcome", {"outcome": outcome})
    sha = event.get("merge_sha")
    if not _nonempty_str(sha):
        return _invalid("malformed_input", {"field": "merge_sha"})
    key = _merge_key(pr, sha)
    if key in ledger.consumed:
        return _accept(ledger, {"slot_consumed": False, "replay": True})
    if any(k[0] == pr for k in ledger.consumed):
        return _invalid("conflicting_merge_record", {"pr": pr})
    return _accept(replace(ledger, consumed=ledger.consumed + (key,)), {"slot_consumed": True})


def record_post_merge_failure(ledger: MergeLedger, issue, ref) -> Result:
    """A post-merge failure halts all remaining automatic merges until triage
    and flags the Issue for reopening; non-merge work continues."""
    if not isinstance(ledger, MergeLedger) or not _nonempty_str(issue) or not _nonempty_str(ref):
        return _invalid("malformed_input")
    reopen = ledger.reopen_issues if issue in ledger.reopen_issues else ledger.reopen_issues + (issue,)
    return _accept(replace(ledger, halted=True, halt_ref=ref, reopen_issues=reopen))


def clear_halt(ledger: MergeLedger, triage_ref) -> Result:
    if not isinstance(ledger, MergeLedger) or not _nonempty_str(triage_ref):
        return _invalid("malformed_input")
    if not ledger.halted:
        return _accept(ledger)
    return _accept(replace(ledger, halted=False, halt_ref=None), {"triage_ref": triage_ref})


def check_action(ledger: MergeLedger, action_kind) -> Result:
    """A halt stops automatic merges only; other work proceeds."""
    if not isinstance(ledger, MergeLedger):
        return _invalid("malformed_input")
    if action_kind == "merge" and ledger.halted:
        return _blocked("post_merge_failure_halt", {"halt_ref": ledger.halt_ref})
    return _accept()


# ---------------------------------------------------------------------------
# 4. SC-2 Begin / Continue (authorization-context-v1; SDP l.248, l.250)
# ---------------------------------------------------------------------------

_SC2_REQUIRED = ("policy_ref", "policy_revision", "actor", "run", "operation", "target", "head", "result")
_SC2_BINDINGS = ("actor", "run", "operation", "target", "head", "policy_ref", "policy_revision")
_BEGIN_BINDINGS = ("grant_id", "grant_kind", "grant_holder", "grant_epoch", "grant_start", "grant_finish")
_AUTHORITY_BINDINGS = ("actor", "run", "target", "head")


def _sc2_shape(ctx) -> Result:
    if not isinstance(ctx, Mapping):
        return _invalid("malformed_input")
    for name in _SC2_REQUIRED:
        if not ctx.get(name):
            return _invalid("missing_required_field", {"field": name})
    if ctx["result"] not in ("Begin", "Continue"):
        return _invalid("unknown_result", {"result": ctx["result"]})
    return _accept()


def bind_authority(authority: Result, *, actor, run, target, head, grant_id=None, operation=None) -> Result:
    """Attach the operation bindings an authority check covered (pure: returns
    a new ``Result``). ``check_begin`` accepts only a bound authority whose
    bindings match the Begin exactly. A refused authority is returned as is."""
    if not (isinstance(authority, Result) and authority.may_proceed):
        return authority
    binding = {"actor": actor, "run": run, "target": target, "head": head}
    if grant_id is not None:
        binding["grant_id"] = grant_id
    if operation is not None:
        binding["operation"] = operation
    return Result(authority.outcome, reason=authority.reason, value=authority.value,
                  detail={**authority.detail, "binding": binding})


def _check_authority_binding(ctx, authority) -> Result:
    if not (isinstance(authority, Result) and authority.may_proceed):
        return _invalid("no_authority")
    binding = authority.detail.get("binding")
    if not isinstance(binding, Mapping):
        return _invalid("no_authority_binding")
    for name in _AUTHORITY_BINDINGS:
        if not _nonempty_str(binding.get(name)) or binding.get(name) != ctx.get(name):
            return _invalid("authority_binding_mismatch", {"field": name})
    if "operation" in binding and binding["operation"] != ctx.get("operation"):
        return _invalid("authority_binding_mismatch", {"field": "operation"})
    if ("grant_id" in binding or "grant_id" in ctx) and binding.get("grant_id") != ctx.get("grant_id"):
        return _invalid("authority_binding_mismatch", {"field": "grant_id"})
    return _accept()


def check_begin(ctx, *, scope, authority, paused=False, acknowledged_grants=(), now=None,
                coordinator_epoch=None) -> Result:
    """Begin a new operation: exact binding, no pause, current scope and
    authority. ``authority`` must be an accepted ``Result`` carrying the
    bindings it checked (see ``bind_authority``); a bare accept is not a
    binding. No further approval is requested. A Begin for an
    already-acknowledged grant is a replay."""
    shape = _sc2_shape(ctx)
    if not shape.may_proceed:
        return shape
    if ctx["result"] != "Begin":
        return _invalid("not_a_begin")
    begin = ctx.get("begin")
    grant_id = (begin or {}).get("grant_id") if isinstance(begin, Mapping) else ctx.get("grant_id")
    if isinstance(begin, Mapping) or (grant_id and grant_id in set(acknowledged_grants)):
        return _invalid("replayed_begin", {"grant_id": grant_id})
    if paused:
        return _invalid("paused")
    if "grant_holder" in ctx and ctx["grant_holder"] != ctx["actor"]:
        return _invalid("holder_mismatch")
    if not isinstance(scope, Mapping):
        return _invalid("scope_unknown")
    if ctx["target"] not in tuple(scope.get("targets", ())):
        return _invalid("out_of_scope", {"target": ctx["target"]})
    if ctx["operation"] not in tuple(scope.get("operations", ())):
        return _invalid("operation_out_of_scope", {"operation": ctx["operation"]})
    bound = _check_authority_binding(ctx, authority)
    if not bound.may_proceed:
        return bound
    if coordinator_epoch is not None and ctx.get("grant_epoch") is not None:
        epoch = ctx["grant_epoch"]
        if not (_is_int(epoch) and _is_int(coordinator_epoch)):
            return _invalid("malformed_input", {"field": "grant_epoch"})
        if epoch < coordinator_epoch:
            return _invalid("stale_epoch")
    if now is not None and ctx.get("grant_expiry") is not None:
        current, expiry = _aware(now), _aware(ctx["grant_expiry"])
        if current is None or expiry is None:
            return _invalid("malformed_input", {"field": "grant_expiry"})
        if current >= expiry:
            return _invalid("grant_expired")
    return _accept(detail={"result": "Begin"})


def _validate_acknowledged(acknowledged) -> Result:
    """The stored acknowledged Begin must be complete and typed, and its
    operation still ongoing, before anything is compared against it."""
    if not isinstance(acknowledged, Mapping) or not isinstance(acknowledged.get("begin"), Mapping):
        return _invalid("no_acknowledged_begin")
    if acknowledged.get("result") != "Begin":
        return _invalid("acknowledged_begin_invalid", {"field": "result"})
    for name in _SC2_BINDINGS:
        if not _nonempty_str(acknowledged.get(name)):
            return _invalid("acknowledged_begin_invalid", {"field": name})
    ack = acknowledged["begin"]
    for name in ("grant_id", "grant_kind", "grant_holder"):
        if not _nonempty_str(ack.get(name)):
            return _invalid("acknowledged_begin_invalid", {"field": f"begin.{name}"})
    if not _is_int(ack.get("grant_epoch")):
        return _invalid("acknowledged_begin_invalid", {"field": "begin.grant_epoch"})
    if _aware(ack.get("grant_start")) is None:
        return _invalid("acknowledged_begin_invalid", {"field": "begin.grant_start"})
    if "grant_finish" in ack and _aware(ack["grant_finish"]) is None:
        return _invalid("acknowledged_begin_invalid", {"field": "begin.grant_finish"})
    if ack["grant_holder"] != acknowledged["actor"]:
        return _invalid("acknowledged_begin_invalid", {"field": "begin.grant_holder"})
    if ack.get("grant_state") != "in_progress":
        return _invalid("not_ongoing", {"grant_state": ack.get("grant_state"), "source": "acknowledged"})
    return _accept()


def check_continue(ctx, acknowledged, *, paused=False, now=None, finish_deadline=None, step=None) -> Result:
    """Continue an acknowledged operation. Checks stable id, holder, bindings,
    started-at and ongoing state; never re-applies epoch rotation or
    latest-start expiry. During pause or after a passed finish deadline only
    reaching a safe point is allowed (``safe_point_only``); new work is refused.

    ``acknowledged`` is the stored context of the acknowledged Begin (top-level
    bindings plus its ``begin`` record); it is validated first. The finish
    deadline is the one stored on the acknowledged Begin (``grant_finish`` is
    an immutable binding); a caller's ``finish_deadline`` can only make it
    earlier, never later. ``step`` is ``None``/``"safe_point"`` (finish or
    roll back the step in hand) or ``"new_work"``."""
    shape = _sc2_shape(ctx)
    if not shape.may_proceed:
        return shape
    if ctx["result"] != "Continue":
        return _invalid("not_a_continue")
    stored = _validate_acknowledged(acknowledged)
    if not stored.may_proceed:
        return stored
    begin = ctx.get("begin")
    if not isinstance(begin, Mapping):
        return _invalid("no_acknowledged_begin")
    ack_begin = acknowledged["begin"]
    if ctx["operation"] != acknowledged.get("operation"):
        return _invalid("new_operation", {"operation": ctx["operation"]})
    if ctx["target"] != acknowledged.get("target"):
        return _invalid("changed_target", {"target": ctx["target"]})
    for name in _SC2_BINDINGS:
        if ctx.get(name) != acknowledged.get(name):
            return _invalid("changed_binding", {"field": name})
    for name in _BEGIN_BINDINGS:
        if (name in begin) != (name in ack_begin) or begin.get(name) != ack_begin.get(name):
            return _invalid("changed_binding", {"field": f"begin.{name}"})
    if begin.get("grant_holder") != ctx["actor"]:
        return _invalid("holder_mismatch")
    if begin.get("grant_state") != "in_progress":
        return _invalid("not_ongoing", {"grant_state": begin.get("grant_state")})
    if step not in (None, "safe_point", "new_work"):
        return _invalid("unknown_step", {"step": step})
    deadlines = []
    if "grant_finish" in ack_begin:
        deadlines.append(_aware(ack_begin["grant_finish"]))
    if finish_deadline is not None:
        caller_deadline = _aware(finish_deadline)
        if caller_deadline is None:
            return _invalid("malformed_input", {"field": "finish_deadline"})
        deadlines.append(caller_deadline)
    finish_passed = False
    if deadlines:
        current = _aware(now)
        if current is None:
            return _invalid("malformed_input", {"field": "now"})
        finish_passed = current >= min(deadlines)
    if paused or finish_passed:
        cause = "paused" if paused else "finish_deadline_passed"
        if step == "new_work":
            return _invalid("new_work_restricted", {"cause": cause})
        return _result(SAFE_POINT_ONLY, reason=cause, detail={"result": "Continue"})
    return _accept(detail={"result": "Continue"})


def evaluate_authorization(ctx, *, acknowledged=None, scope=None, authority=None, paused=False,
                           now=None, finish_deadline=None, step=None, acknowledged_grants=()) -> Result:
    """Dispatch an SC-2 context to ``check_begin`` or ``check_continue``."""
    shape = _sc2_shape(ctx)
    if not shape.may_proceed:
        return shape
    if ctx["result"] == "Begin":
        return check_begin(ctx, scope=scope, authority=authority, paused=paused,
                           acknowledged_grants=acknowledged_grants, now=now)
    return check_continue(ctx, acknowledged, paused=paused, now=now,
                          finish_deadline=finish_deadline, step=step)


# ---------------------------------------------------------------------------
# 5. D7.2 control record (SDP l.224-230)
# ---------------------------------------------------------------------------

_DELEGATED_RECORD_FIELDS = ("gate", "decision", "reasoning", "evidence_pointer", "reversal_path")


def validate_delegated_record(record, unresolved_decisions=None) -> Result:
    """A delegated-gate record names the gate, decision, reasoning, evidence
    pointer and reversal path; the gate must be one D7.2 actually delegates."""
    if not isinstance(record, Mapping):
        return _invalid("malformed_input")
    for name in _DELEGATED_RECORD_FIELDS:
        if not _nonempty_str(record.get(name)):
            return _invalid("missing_record_field", {"field": name})
    disposed = dispose_gate(record["gate"], unresolved_decisions)
    if not disposed.may_proceed:
        return disposed
    if not disposed.value.delegable:
        return _invalid("gate_not_delegable", {"gate": record["gate"], "disposition": disposed.value.disposition})
    return _accept(disposed.value)


def step_boundary(pending, messages, acknowledged_ids=()) -> Result:
    """At a step boundary, a user message stops (``kind: stop``) or revises
    (``kind: revise`` with ``targets``) pending work. Until the lead has
    acknowledged every message, nothing continues (``blocked``)."""
    pending = list(pending or ())
    raw = list(messages or ())
    if any(not isinstance(m, Mapping) for m in raw):
        return _invalid("malformed_message")
    msgs = raw
    if any(not _nonempty_str(m.get("id")) or m.get("kind") not in ("stop", "revise") for m in msgs):
        return _invalid("malformed_message")
    for m in msgs:
        if m["kind"] == "revise":
            targets = m.get("targets")
            if not isinstance(targets, (list, tuple)) or not targets or not all(_nonempty_str(t) for t in targets):
                return _invalid("malformed_message", {"message": m["id"], "field": "targets"})
    unacked = [m["id"] for m in msgs if m["id"] not in set(acknowledged_ids)]
    if unacked:
        return _blocked("veto_unacknowledged", {"messages": unacked})
    stopped, revised = [], []
    if any(m["kind"] == "stop" for m in msgs):
        stopped = list(pending)
    else:
        targets = {t for m in msgs for t in m["targets"]}
        revised = [p for p in pending if p in targets]
    remaining = [p for p in pending if p not in stopped and p not in revised]
    unknown = sorted({t for m in msgs if m["kind"] == "revise" for t in m["targets"]} - set(pending))
    return _accept({"continue": remaining, "stopped": stopped, "revised": revised},
                   {"unknown_targets": unknown} if unknown else None)


def check_dependencies(action, open_questions) -> Result:
    """Work that depends on an unanswered user-owned question waits; independent
    work continues."""
    if not isinstance(action, Mapping) or not _nonempty_str(action.get("id")):
        return _invalid("malformed_input")
    open_ids = {q.get("id") for q in (open_questions or ()) if isinstance(q, Mapping)}
    waiting = [d for d in (action.get("depends_on") or ()) if d in open_ids]
    if waiting:
        return _blocked("awaiting_answer", {"questions": waiting})
    return _accept()


def route_question(question) -> Result:
    """Engineering questions are the lead's (delegated); product, scope and
    acceptance — and any unknown kind — are user-owned (``goal_run``)."""
    classified = classify_question(question)
    return _accept(classified.detail.get("resolution"), classified.detail)


def next_question(queue, outstanding=(), batch_requested=False) -> Result:
    """Ask user-owned questions one at a time, each with a recommendation; a
    small batch only when the user asked for one. While a question is
    outstanding, the next one waits."""
    if list(outstanding or ()):
        return _blocked("question_outstanding", {"outstanding": list(outstanding)})
    user_owned = [q for q in (queue or ()) if route_question(q).value == "user"]
    if not user_owned:
        return _accept([])
    for q in user_owned:
        if not isinstance(q, Mapping) or not _nonempty_str(q.get("recommendation")):
            return _invalid("missing_recommendation", {"question": q.get("id") if isinstance(q, Mapping) else None})
    size = MAX_QUESTION_BATCH if batch_requested else 1
    return _accept(user_owned[:size])


def escalate(stop) -> Result:
    """H1-H5 protected stops escalate immediately."""
    category = stop.get("category") if isinstance(stop, Mapping) else stop
    if category in PROTECTED_STOP_CATEGORIES:
        return _result(PROTECTED_STOP, reason=category, detail={"immediate": True})
    return _invalid("not_protected_stop", {"category": category})


def proceed_unless_stopped(gate_id, unresolved_decisions=None) -> Result:
    """"Proceed unless stopped" applies only to gates D7.2 delegates."""
    disposed = dispose_gate(gate_id, unresolved_decisions)
    if not disposed.may_proceed:
        return disposed
    row = disposed.value
    if row.disposition == PROTECTED:
        return _invalid("protected_gate", {"gate": gate_id})
    if not row.delegable:
        return _invalid("not_delegated", {"gate": gate_id, "disposition": row.disposition})
    return _accept(row)
