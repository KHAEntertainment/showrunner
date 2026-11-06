#!/usr/bin/env python3
"""Goal-run normalizer, D3 bounds and G2 turn-end markers (Issue #193, lane L1).

Pure-stdlib, side-effect-free module: no network, no subprocess, no file writes,
and no clock reads. Every time-dependent function takes ``now`` and any
approval/reference time as explicit UTC arguments supplied by the caller (ISO
8601 strings or ``datetime`` objects). Nothing here persists state or grants
authority; the owner/lead authority rules are the caller's responsibility.

Stable public API (frozen once this PR is up; lanes L3 authority and L5 recovery
import it):

    Result                          outcome/reason/value/detail envelope
    Assignment                      frozen ``assignment-v1`` record
    ArmedRun                        frozen scope + mode + D3 policy block
    Handback                        correlated handback record
    BoundsPolicy                    D3 run-bounds policy (defaults, narrowed only)
    RunCounters                     monotonic per-run counters (never reset)

    normalize_entry(entry, resolved_issues=None) -> Result[Assignment]
    arm(entry, resolved_issues=None, deliverable_type=None,
        project_policy=None, goal=None, coordinator=None) -> Result[ArmedRun]
    guard_frozen_scope(scope, mode=None, fixed_issues=None) -> Result

    apply_policy(project_policy=None, goal=None, coordinator=None,
                 mode="standalone") -> Result[BoundsPolicy]
    account_dispatch(counters, issue, request_id) -> Result
    evaluate_limits(policy, counters, approval_time, now,
                    dependencies=None) -> Result
    extend_limit(policy, field, new_value) -> Result[BoundsPolicy]

    parse_turn_end_marker(text, expected_source=None, next_wake_at=None,
                          next_action=None, paused=False) -> Result

    classify_input(payload) -> Result
    classify_question(question) -> Result
    make_handback(request_ref, reason, disposition="pending") -> Result[Handback]

Result outcome vocabulary:

    ``accept``             normalization/arming/guard/classify success
    ``invalid``            refusal; ``reason`` carries a distinct reason code
    ``unavailable``        reserved for later lanes (GV unreadable input); not
                           emitted here
    ``complete``           no limit reached / a run step finished whole
    ``incomplete``         a limit was reached; ``reason`` names it
    ``claim_requires_gv``  a GOAL-COMPLETE marker was parsed (a claim, never
                           verified)
    ``protected_stop``     a HARD-STOP H1-H5 marker was parsed (immediate
                           escalation; H5 is unrecoverable after finite retries)

Reason codes (``Result.reason``) are part of the interface. The arming-refusal
codes are: ``empty_issue_set``, ``cross_repo_issue``, ``bare_ambiguous_issue_id``,
``duplicate_issue``, ``non_pr_goal``, ``managed_missing_bindings``,
``unsupported_major_version``, ``malformed_input``, ``missing_required_field``,
``approval_revision_mismatch``, ``machine_specific_path``, ``missing_resolved_issues``.
Guard codes: ``managed_to_standalone``, ``standalone_to_managed``, ``scope_growth``.
Bounds codes: ``goal_widening``, ``coordinator_loosening``, ``run_time_exceeded``,
``spend_cap_exceeded``, ``dispatch_cap_exceeded``, ``no_limit_to_extend``,
``not_an_extension``, ``unknown_limit_field``. Marker codes: ``no_marker``,
``marker_not_last``, ``multiple_markers``, ``malformed_marker``, ``wrong_source``,
``wake_mismatch``, ``wake_during_pause``. Input codes: ``unknown_input_kind``,
``context_only_scope_change``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Optional

__all__ = [
    "Result",
    "Assignment",
    "ArmedRun",
    "Handback",
    "BoundsPolicy",
    "RunCounters",
    "USAGE_UNKNOWN",
    "normalize_entry",
    "arm",
    "guard_frozen_scope",
    "apply_policy",
    "account_dispatch",
    "evaluate_limits",
    "extend_limit",
    "parse_turn_end_marker",
    "classify_input",
    "classify_question",
    "make_handback",
]

VERSION = "assignment-v1"
MODE_STANDALONE = "standalone"
MODE_MANAGED = "managed"
DELIVERABLE_PR = "pr"
USAGE_UNKNOWN = "unknown"

_ENTRY_KINDS = ("plan", "prd", "issue", "milestone")
_QUALIFIED_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[0-9]+$")
_QUALIFIED_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_MACHINE_PATH_RE = re.compile(r"^(~/|/|[A-Za-z]:[\\/])")

_HARD_STOP_RE = re.compile(r"^HARD-STOP: H([1-5]) \u2014 (.+)$")
_WAKE_RE = re.compile(r"^WAKE: (.+?) \u2014 (.+)$")
_GOAL_COMPLETE_RE = re.compile(r"^GOAL-COMPLETE: (.+)$")

# D3 defaults (SDP D3 l.286-307).
DEFAULT_RUN_TIME_HOURS = 24.0
DEFAULT_DISPATCH_CAP_PER_ISSUE = 8
DEFAULT_GV_RETRIES = 3
DEFAULT_SPEND_CAP: Optional[float] = None

_EXTENDABLE_LIMITS = frozenset(
    {"run_time_hours", "dispatch_cap_per_issue", "gv_retries", "spend_cap"}
)


@dataclass(frozen=True)
class Result:
    """Outcome envelope. ``outcome`` is one of the documented vocabulary values."""

    outcome: str
    reason: str = ""
    value: Any = None
    detail: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.outcome != "invalid"


@dataclass(frozen=True)
class Assignment:
    """Frozen ``assignment-v1`` record (SC-1 field table)."""

    repo: str
    run: str
    mode: str
    lead: dict
    plan_ref: dict
    source: str
    approval_revision: str
    fixed_issues: tuple
    coordinator: Optional[dict] = None
    charter_revision: Optional[str] = None
    contract_refs: tuple = ()


@dataclass(frozen=True)
class BoundsPolicy:
    """D3 run-bounds policy. Defaults from the project, narrowed only."""

    run_time_hours: float = DEFAULT_RUN_TIME_HOURS
    dispatch_cap_per_issue: int = DEFAULT_DISPATCH_CAP_PER_ISSUE
    gv_retries: int = DEFAULT_GV_RETRIES
    spend_cap: Optional[float] = DEFAULT_SPEND_CAP


@dataclass(frozen=True)
class ArmedRun:
    """Frozen scope + mode + D3 policy block for one armed goal run."""

    assignment: Assignment
    policy: BoundsPolicy


@dataclass(frozen=True)
class Handback:
    """Correlated handback record: an out-of-scope request returned to the lead."""

    reference: str
    reason: str
    disposition: str = "pending"


@dataclass
class RunCounters:
    """Monotonic per-run counters. No method here ever resets or decrements a
    counter, so resume/wake/compaction/restart/lead-change never renew one."""

    dispatch_counts: dict = field(default_factory=dict)
    dispatch_request_ids: dict = field(default_factory=dict)
    spend: Any = None  # a number, USAGE_UNKNOWN, or None (unmeasured)

    def dispatch_count(self, issue: str) -> int:
        return self.dispatch_counts.get(issue, 0)


def _invalid(reason: str, detail: Optional[dict] = None) -> Result:
    return Result("invalid", reason=reason, detail=detail or {})


def _accept(value: Any = None, detail: Optional[dict] = None) -> Result:
    return Result("accept", value=value, detail=detail or {})


def _is_machine_path(value: str) -> bool:
    return bool(_MACHINE_PATH_RE.match(value))


def _parse_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def normalize_entry(entry, resolved_issues=None) -> Result:
    """Normalize a plan / PRD / Issue / milestone entry to one ``assignment-v1``
    record. ``resolved_issues`` is the caller-supplied resolved Issue list for a
    milestone entry (never a live query); it is frozen into ``fixed_issues``."""
    if not isinstance(entry, dict):
        return _invalid("malformed_input")

    kind = entry.get("kind")
    if kind is not None and kind not in _ENTRY_KINDS:
        return _invalid("malformed_input", {"field": "kind"})

    version = entry.get("version", VERSION)
    if version != VERSION:
        return _invalid("unsupported_major_version", {"version": version})

    repo = entry.get("repo") or entry.get("project")
    if not repo:
        return _invalid("missing_required_field", {"field": "repo"})
    if not isinstance(repo, str) or not _QUALIFIED_REPO_RE.match(repo):
        return _invalid("malformed_input", {"field": "repo"})

    mode = entry.get("mode")
    if mode not in (MODE_STANDALONE, MODE_MANAGED):
        if mode is None:
            return _invalid("missing_required_field", {"field": "mode"})
        return _invalid("malformed_input", {"field": "mode"})

    for field_name in ("run", "lead", "plan_ref", "source", "approval_revision"):
        if entry.get(field_name) in (None, ""):
            return _invalid("missing_required_field", {"field": field_name})

    lead = entry.get("lead")
    if not isinstance(lead, dict):
        return _invalid("malformed_input", {"field": "lead"})

    plan_ref = entry.get("plan_ref")
    if not isinstance(plan_ref, dict):
        return _invalid("malformed_input", {"field": "plan_ref"})
    plan_ref_result = _validate_plan_ref(plan_ref)
    if not plan_ref_result.ok:
        return plan_ref_result

    source = entry.get("source")
    if not isinstance(source, str) or _is_machine_path(source):
        return _invalid("machine_specific_path", {"field": "source"})

    approval_revision = entry.get("approval_revision")
    if not isinstance(approval_revision, str):
        return _invalid("malformed_input", {"field": "approval_revision"})
    if approval_revision != plan_ref.get("approved_revision"):
        return _invalid("approval_revision_mismatch")

    if kind == "milestone":
        if resolved_issues is None:
            return _invalid("missing_resolved_issues")
        issue_list = resolved_issues
    else:
        issue_list = entry.get("fixed_issues")

    scope_result = _validate_fixed_issues(issue_list, repo)
    if not scope_result.ok:
        return scope_result
    fixed_issues = scope_result.value

    coordinator = None
    charter_revision = None
    contract_refs = ()
    if mode == MODE_MANAGED:
        coordinator = entry.get("coordinator")
        charter_revision = entry.get("charter_revision")
        contract_refs = entry.get("contract_refs")
        if coordinator is None or not isinstance(coordinator, dict):
            return _invalid("managed_missing_bindings", {"field": "coordinator"})
        if not charter_revision:
            return _invalid("managed_missing_bindings", {"field": "charter_revision"})
        if not isinstance(contract_refs, list):
            return _invalid("managed_missing_bindings", {"field": "contract_refs"})

    assignment = Assignment(
        repo=repo,
        run=entry.get("run"),
        mode=mode,
        lead=dict(lead),
        plan_ref=plan_ref,
        source=source,
        approval_revision=approval_revision,
        fixed_issues=tuple(fixed_issues),
        coordinator=dict(coordinator) if coordinator is not None else None,
        charter_revision=charter_revision,
        contract_refs=tuple(contract_refs),
    )
    return _accept(value=assignment)


def _validate_plan_ref(plan_ref: dict) -> Result:
    for field_name in ("origin", "source_revision", "approved_revision"):
        if plan_ref.get(field_name) in (None, ""):
            return _invalid("missing_required_field", {"field": "plan_ref." + field_name})
    origin = plan_ref.get("origin")
    if _is_machine_path(origin):
        return _invalid("machine_specific_path", {"field": "plan_ref.origin"})
    approval = plan_ref.get("approval")
    if not isinstance(approval, dict):
        return _invalid("missing_required_field", {"field": "plan_ref.approval"})
    for field_name in ("authority", "evidence"):
        if approval.get(field_name) in (None, ""):
            return _invalid(
                "missing_required_field", {"field": "plan_ref.approval." + field_name}
            )
    producer = plan_ref.get("producer")
    if not isinstance(producer, dict):
        return _invalid("missing_required_field", {"field": "plan_ref.producer"})
    for field_name in ("session", "harness"):
        if producer.get(field_name) in (None, ""):
            return _invalid(
                "missing_required_field", {"field": "plan_ref.producer." + field_name}
            )
    return _accept()


def _validate_fixed_issues(issue_list, repo: str) -> Result:
    if not isinstance(issue_list, list) or not issue_list:
        return _invalid("empty_issue_set")
    seen = set()
    for issue in issue_list:
        if not isinstance(issue, str) or not _QUALIFIED_ID_RE.match(issue):
            return _invalid("bare_ambiguous_issue_id", {"issue": issue})
        if issue in seen:
            return _invalid("duplicate_issue", {"issue": issue})
        seen.add(issue)
        owner_repo = issue.rsplit("#", 1)[0]
        if owner_repo != repo:
            return _invalid("cross_repo_issue", {"issue": issue, "repo": repo})
    return _accept(value=list(issue_list))


def arm(
    entry,
    resolved_issues=None,
    deliverable_type=None,
    project_policy=None,
    goal=None,
    coordinator=None,
) -> Result:
    """Arm a goal run: refuse a non-PR goal, normalize the entry, and apply the
    D3 policy block. Returns a frozen ``ArmedRun`` on success."""
    deliverable = (
        deliverable_type
        if deliverable_type is not None
        else entry.get("deliverable_type", DELIVERABLE_PR)
    )
    if deliverable != DELIVERABLE_PR:
        return _invalid("non_pr_goal", {"deliverable_type": deliverable})

    normalized = normalize_entry(entry, resolved_issues=resolved_issues)
    if not normalized.ok:
        return normalized

    policy_result = apply_policy(
        project_policy=project_policy,
        goal=goal,
        coordinator=coordinator,
        mode=normalized.value.mode,
    )
    if not policy_result.ok:
        return policy_result

    return _accept(value=ArmedRun(assignment=normalized.value, policy=policy_result.value))


def guard_frozen_scope(scope, mode=None, fixed_issues=None) -> Result:
    """Reject a mid-run mode change or Issue addition beyond ``fixed_issues``.

    ``scope`` is an ``Assignment`` or ``ArmedRun``. Distinct reason codes for
    managed->standalone, standalone->managed, and post-freeze scope growth."""
    assignment = scope.assignment if isinstance(scope, ArmedRun) else scope

    if mode is not None and mode != assignment.mode:
        if assignment.mode == MODE_MANAGED and mode == MODE_STANDALONE:
            return _invalid("managed_to_standalone")
        if assignment.mode == MODE_STANDALONE and mode == MODE_MANAGED:
            return _invalid("standalone_to_managed")
        return _invalid("mode_change")

    if fixed_issues is not None:
        current = set(assignment.fixed_issues)
        proposed = set(fixed_issues)
        if not proposed <= current:
            return _invalid(
                "scope_growth", {"added": sorted(proposed - current)}
            )

    return _accept()


def apply_policy(
    project_policy=None, goal=None, coordinator=None, mode=MODE_STANDALONE
) -> Result:
    """Build a ``BoundsPolicy``. Project defaults may be narrowed by the goal;
    in managed mode a coordinator may tighten further but never loosen."""
    project = project_policy if isinstance(project_policy, dict) else {}
    policy = BoundsPolicy(
        run_time_hours=project.get("run_time_hours", DEFAULT_RUN_TIME_HOURS),
        dispatch_cap_per_issue=project.get(
            "dispatch_cap_per_issue", DEFAULT_DISPATCH_CAP_PER_ISSUE
        ),
        gv_retries=project.get("gv_retries", DEFAULT_GV_RETRIES),
        spend_cap=project.get("spend_cap", DEFAULT_SPEND_CAP),
    )

    if isinstance(goal, dict):
        narrowed = _narrow(policy, goal)
        if not narrowed.ok:
            return _invalid("goal_widening", {"field": narrowed.reason})
        policy = narrowed.value

    if isinstance(coordinator, dict):
        if mode != MODE_MANAGED:
            return _invalid("coordinator_loosening", {"field": "mode_not_managed"})
        tightened = _narrow(policy, coordinator)
        if not tightened.ok:
            return _invalid("coordinator_loosening", {"field": tightened.reason})
        policy = tightened.value

    return _accept(value=policy)


def _narrow(policy: BoundsPolicy, overrides: dict) -> Result:
    for field_name, value in overrides.items():
        if field_name == "spend_cap":
            current = policy.spend_cap
            if value is None:
                return _invalid("spend_cap")
            if current is None:
                policy = replace(policy, spend_cap=value)
            elif value > current:
                return _invalid("spend_cap")
            else:
                policy = replace(policy, spend_cap=value)
        elif field_name in ("run_time_hours", "dispatch_cap_per_issue", "gv_retries"):
            current = getattr(policy, field_name)
            if not isinstance(value, (int, float)):
                return _invalid(field_name)
            if value > current:
                return _invalid(field_name)
            policy = replace(policy, **{field_name: value})
        else:
            return _invalid(field_name)
    return _accept(value=policy)


def account_dispatch(counters: RunCounters, issue: str, request_id: str) -> Result:
    """Record one agent dispatch, keyed by ``(issue, request_id)``. A duplicate
    request_id counts once and creates no second dispatch."""
    seen = counters.dispatch_request_ids.setdefault(issue, set())
    if request_id in seen:
        return _accept(
            detail={"counted": False, "count": counters.dispatch_count(issue)}
        )
    seen.add(request_id)
    new_count = counters.dispatch_count(issue) + 1
    counters.dispatch_counts[issue] = new_count
    return _accept(detail={"counted": True, "count": new_count})


def evaluate_limits(
    policy: BoundsPolicy,
    counters: RunCounters,
    approval_time,
    now,
    dependencies=None,
) -> Result:
    """Evaluate D3 limits. ``approval_time`` and ``now`` are explicit UTC
    arguments. Returns ``complete`` when no limit is reached, else ``incomplete``
    naming the limit. Unknown usage never stops the run. Per-Issue dispatch cap
    marks only that Issue incomplete; siblings continue unless ``dependencies``
    maps an Issue to the Issues it depends on."""
    approval_dt = _parse_dt(approval_time)
    now_dt = _parse_dt(now)
    elapsed_hours = (now_dt - approval_dt).total_seconds() / 3600.0
    if elapsed_hours > policy.run_time_hours:
        return _invalid_limit(
            "run_time_exceeded",
            {"elapsed_hours": elapsed_hours, "limit": policy.run_time_hours},
        )

    if policy.spend_cap is not None and isinstance(counters.spend, (int, float)):
        if counters.spend > policy.spend_cap:
            return _invalid_limit(
                "spend_cap_exceeded",
                {"spend": counters.spend, "limit": policy.spend_cap},
            )

    incomplete = {
        issue
        for issue, count in counters.dispatch_counts.items()
        if count >= policy.dispatch_cap_per_issue
    }
    if incomplete and isinstance(dependencies, dict):
        changed = True
        while changed:
            changed = False
            for issue, deps in dependencies.items():
                if issue in incomplete:
                    continue
                if incomplete & set(deps):
                    incomplete.add(issue)
                    changed = True

    issues = list(counters.dispatch_counts.keys())
    if incomplete:
        return _invalid_limit(
            "dispatch_cap_exceeded",
            {
                "cap": policy.dispatch_cap_per_issue,
                "incomplete_issues": sorted(incomplete),
                "continue_issues": sorted(set(issues) - incomplete),
            },
        )

    return Result(
        "complete",
        detail={
            "issues": issues,
            "dispatch_counts": dict(counters.dispatch_counts),
            "spend": counters.spend,
        },
    )


def _invalid_limit(reason: str, detail: dict) -> Result:
    return Result("incomplete", reason=reason, detail=detail)


def extend_limit(policy: BoundsPolicy, field: str, new_value) -> Result:
    """Raise a limit (owner authority only, enforced by the caller). Counters are
    held separately and never touched, so a used counter is preserved."""
    if field not in _EXTENDABLE_LIMITS:
        return _invalid("unknown_limit_field", {"field": field})
    current = getattr(policy, field)
    if current is None:
        return _invalid("no_limit_to_extend", {"field": field})
    if not isinstance(new_value, (int, float)) or new_value <= current:
        return _invalid("not_an_extension", {"field": field, "current": current})
    return _accept(value=replace(policy, **{field: new_value}))


def parse_turn_end_marker(
    text,
    expected_source=None,
    next_wake_at=None,
    next_action=None,
    paused=False,
) -> Result:
    """Parse the G2 turn-end contract. Only the last nonempty line counts; it must
    match exactly one marker. Returns ``protected_stop`` for HARD-STOP H1-H5,
    ``claim_requires_gv`` for GOAL-COMPLETE (never verified), or ``accept`` for a
    valid WAKE matching persisted state."""
    if not isinstance(text, str):
        return _invalid("malformed_marker")

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return _invalid("no_marker")

    for line in lines[:-1]:
        if _marker_kind(line) is not None:
            return _invalid("marker_not_last")

    last = lines[-1]
    marker_count = sum(last.count(token) for token in _MARKER_TOKENS)
    if marker_count > 1:
        return _invalid("multiple_markers")

    kind = _marker_kind(last)
    if kind == "hard_stop":
        match = _HARD_STOP_RE.fullmatch(last)
        level = int(match.group(1))
        return Result(
            "protected_stop",
            reason="hard_stop_h%d" % level,
            detail={"level": "H%d" % level, "reason": match.group(2).strip()},
        )
    if kind == "wake":
        match = _WAKE_RE.fullmatch(last)
        wake_at = match.group(1).strip()
        action = match.group(2).strip()
        if paused:
            return _invalid("wake_during_pause")
        if wake_at != next_wake_at or action != next_action:
            return _invalid("wake_mismatch")
        return _accept(detail={"wake_at": wake_at, "action": action})
    if kind == "goal_complete":
        match = _GOAL_COMPLETE_RE.fullmatch(last)
        source = match.group(1).strip()
        if expected_source is not None and source != expected_source:
            return _invalid("wrong_source", {"source": source})
        return Result(
            "claim_requires_gv",
            value=source,
            detail={"source": source, "verified": False},
        )
    return _invalid("malformed_marker")


_MARKER_TOKENS = ("HARD-STOP:", "WAKE:", "GOAL-COMPLETE:")


def _marker_kind(line: str):
    if _HARD_STOP_RE.fullmatch(line):
        return "hard_stop"
    if _WAKE_RE.fullmatch(line):
        return "wake"
    if _GOAL_COMPLETE_RE.fullmatch(line):
        return "goal_complete"
    return None


def classify_input(payload) -> Result:
    """Classify a correlated input. ``payload`` carries an explicit ``kind``
    (``context`` | ``work`` | ``question``) and, for questions, ``question_kind``.
    A context-only input cannot add an Issue or change acceptance."""
    if not isinstance(payload, dict):
        return _invalid("malformed_input")
    kind = payload.get("kind")
    if kind not in ("context", "work", "question"):
        return _invalid("unknown_input_kind", {"kind": kind})

    if kind == "context":
        add_issues = payload.get("add_issues") or []
        change_acceptance = bool(payload.get("change_acceptance"))
        if add_issues or change_acceptance:
            return _invalid("context_only_scope_change")
        return _accept(detail={"classification": "context_only"})

    if kind == "work":
        return _accept(detail={"classification": "authorized_work"})

    question_result = classify_question(payload)
    if question_result.detail.get("resolution") == "lead":
        return _accept(detail={"classification": "lead_resolvable"})
    return _accept(detail={"classification": "user_owned"})


def classify_question(question) -> Result:
    """Classify a question by its explicit ``question_kind``. Never guess from
    prose. ``engineering`` is lead-resolvable; ``product``/``scope``/``acceptance``
    and any missing or unknown kind are user-owned (fail closed)."""
    if not isinstance(question, dict):
        return _accept(detail={"resolution": "user", "kind": None, "fail_closed": True})
    question_kind = question.get("question_kind")
    if question_kind == "engineering":
        return _accept(detail={"resolution": "lead", "kind": question_kind})
    if question_kind in ("product", "scope", "acceptance"):
        return _accept(detail={"resolution": "user", "kind": question_kind})
    return _accept(
        detail={"resolution": "user", "kind": question_kind, "fail_closed": True}
    )


def make_handback(request_ref, reason, disposition="pending") -> Result:
    """Return an out-of-scope request to the lead as a correlated handback record.
    Never escalates to the owner on its own and never grows ``fixed_issues``."""
    return _accept(
        value=Handback(reference=request_ref, reason=reason, disposition=disposition)
    )
