#!/usr/bin/env python3
"""Recovery admission, SC-9 records and reconciliation (Issue #196, lane L5).

Pure-stdlib, side-effect-free module: no network, no subprocess, no file writes,
no clock reads, no hook installation. Every time-dependent step takes ``now`` (and
``approval_time`` where needed) as explicit caller-supplied values. Nothing here
persists state or grants authority; the lead is the sole ledger writer and this
module returns records, it never writes them.

Imports from the frozen merged L1 module ``goal_run.py`` (read-only): ``Result``,
``RunCounters``, ``BoundsPolicy``, ``ArmedRun``, ``evaluate_limits`` and
``guard_frozen_scope``. Its ``Result`` shape and reason-code style are reused; no
goal_run logic is duplicated and no private (leading-underscore) name is imported
or copied — this module needs none.

Stable public API:

    Result                          (reused from goal_run)
    CheckpointReference             frozen ``checkpoint-reference-v1`` record (to_dict)
    RecoveryReceipt                 frozen ``recovery-receipt-v1`` record (to_dict)
    EventLedger                     frozen event-accounting ledger
    Obligations                     frozen obligations snapshot (children, owed replies, ...)
    RecoveryInput                   frozen inputs to ``admit_recovery``

    build_checkpoint_reference(...) -> Result[CheckpointReference]
    build_recovery_receipt(...) -> Result[RecoveryReceipt]
    validate_sc9_record(record_type, record) -> Result
    account_event(ledger, identity, kind) -> Result[EventLedger]
    preserve_obligations(before, after) -> Result
    classify_note(note_status, *, paused=False, checkpoint_available=False) -> Result
    reconcile_unknown_effect(outcome, *, retry=False) -> Result
    classify_lineage(prior_session_id, current_session_id, claim=None) -> Result
    qualify_adapter(adapter, ...) -> Result
    reuse_evidence(subject, head, definition_revision, ...) -> Result
    evaluate_coverage(coverage_map) -> Result
    admit_recovery(state) -> Result[RecoveryReceipt]

Reason codes (``Result.reason``) are part of the interface. Recovery codes:
``unsupported_major_version``, ``missing_required_field``, ``out_of_list_value``,
``malformed_input``, ``resume_overrides_pause``, ``authority_renewed_by_activity``,
``unknown_effect_replay``, ``compaction_counts_as_rotation``,
``recovery_evidence_unavailable``, ``duplicate_compaction_count``,
``managed_to_standalone``, ``second_writer``, ``obligations_changed``,
``scope_growth`` (reused from goal_run).

``admit_recovery`` implements the SDP l.477 resume admission order as one ordered
evaluator. Each step fails closed; a failure returns ``Result("invalid")`` whose
``detail["step"]`` names the step (1-6) and never runs later steps.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from types import MappingProxyType
from typing import Any, Optional

from goal_run import (
    ArmedRun,
    BoundsPolicy,
    Result,
    RunCounters,
    evaluate_limits,
    guard_frozen_scope,
)

__all__ = [
    "Result",
    "CheckpointReference",
    "RecoveryReceipt",
    "EventLedger",
    "Obligations",
    "RecoveryInput",
    "VERSION_CHECKPOINT_REFERENCE",
    "VERSION_RECOVERY_RECEIPT",
    "COVERAGE_VALUES",
    "EVENT_ACCOUNTING_RESULTS",
    "ADMISSION_OUTCOME_ACCEPT",
    "ADMISSION_OUTCOME_REJECT",
    "ADMISSION_OUTCOMES",
    "EVENT_KINDS",
    "NOTE_STATUSES",
    "build_checkpoint_reference",
    "build_recovery_receipt",
    "validate_sc9_record",
    "account_event",
    "preserve_obligations",
    "classify_note",
    "reconcile_unknown_effect",
    "classify_lineage",
    "qualify_adapter",
    "reuse_evidence",
    "evaluate_coverage",
    "admit_recovery",
]

# SC-9 record type identifiers (the two contract versions).
VERSION_CHECKPOINT_REFERENCE = "checkpoint-reference-v1"
VERSION_RECOVERY_RECEIPT = "recovery-receipt-v1"
_RECORD_TYPES = (VERSION_CHECKPOINT_REFERENCE, VERSION_RECOVERY_RECEIPT)

# Closed value lists (sc-9.md l.36-l.59). Values outside a list are invalid.
COVERAGE_VALUES = frozenset({"top_level", "child", "excluded"})
EVENT_ACCOUNTING_RESULTS = frozenset({"counted_once", "duplicate_compaction_count"})
ADMISSION_OUTCOME_ACCEPT = frozenset(
    {
        "restored_then_current_state_check",
        "fallback_ledger_recovery",
        "pause_honored_recovery_only",
        "rotation_due_rotation_applied",
    }
)
ADMISSION_OUTCOME_REJECT = frozenset(
    {
        "resume_overrides_pause",
        "authority_renewed_by_activity",
        "unknown_effect_replay",
        "compaction_counts_as_rotation",
        "recovery_evidence_unavailable",
    }
)
ADMISSION_OUTCOMES = ADMISSION_OUTCOME_ACCEPT | ADMISSION_OUTCOME_REJECT

# Event kinds that recovery deduplicates by identity (SDP l.477 step 3).
EVENT_KIND_COMPACTION = "compaction"
EVENT_KIND_WAKE = "wake"
EVENT_KIND_RESTART = "restart"
EVENT_KIND_HOOK_DELIVERY = "hook_delivery"
EVENT_KIND_LEAD_HANDOFF = "lead_handoff"
EVENT_KINDS = frozenset(
    {
        EVENT_KIND_COMPACTION,
        EVENT_KIND_WAKE,
        EVENT_KIND_RESTART,
        EVENT_KIND_HOOK_DELIVERY,
        EVENT_KIND_LEAD_HANDOFF,
    }
)

# Note statuses for ``classify_note``.
NOTE_CURRENT = "current"
NOTE_STALE = "stale"
NOTE_MISSING = "missing"
NOTE_FAILED = "failed"
NOTE_EMERGENCY_NO_NOTE = "emergency_no_note"
NOTE_STATUSES = frozenset(
    {NOTE_CURRENT, NOTE_STALE, NOTE_MISSING, NOTE_FAILED, NOTE_EMERGENCY_NO_NOTE}
)

# Degradation labels recorded on a fallback receipt when the note is unusable.
_DEGRADATION_BY_STATUS = {
    NOTE_STALE: "stale_note",
    NOTE_MISSING: "no_note",
    NOTE_FAILED: "failed_note",
    NOTE_EMERGENCY_NO_NOTE: "no_note",
}
# Degradations that make a checkpoint evidence fallback-eligible (degraded note).
_DEGRADED = frozenset({"stale_note", "no_note", "failed_note"})

# Adapters and their qualification classes (H1 l.483-l.485, l.471-l.473).
ADAPTER_CLAUDE = "claude"
ADAPTER_OPENCODE = "opencode"
ADAPTER_CODEX = "codex"
ADAPTER_PI = "pi"
_ADAPTERS = (ADAPTER_CLAUDE, ADAPTER_OPENCODE, ADAPTER_CODEX, ADAPTER_PI)
# Developing (Codex) and owner-reported (Pi) adapters are never parity.
_DEVELOPING_ADAPTERS = frozenset({ADAPTER_CODEX, ADAPTER_PI})


def _invalid(reason: str, detail: Optional[dict] = None) -> Result:
    return Result("invalid", reason=reason, detail=detail or {})


def _accept(value: Any = None, detail: Optional[dict] = None) -> Result:
    return Result("accept", value=value, detail=detail or {})


@dataclass(frozen=True)
class CheckpointReference:
    """Frozen ``checkpoint-reference-v1`` record (sc-9.md field table)."""

    run: str
    session: str
    event: str
    adapter: str
    version: str
    note_revision: str
    freshness: str
    authoritative_refs: tuple
    coverage: Optional[str] = None
    degradation: Optional[str] = None

    def to_dict(self) -> dict:
        """Return a plain JSON-safe dict; the record itself stays immutable."""
        return {
            "run": self.run,
            "session": self.session,
            "event": self.event,
            "adapter": self.adapter,
            "version": self.version,
            "note_revision": self.note_revision,
            "freshness": self.freshness,
            "authoritative_refs": list(self.authoritative_refs),
            "coverage": self.coverage,
            "degradation": self.degradation,
        }


@dataclass(frozen=True)
class RecoveryReceipt:
    """Frozen ``recovery-receipt-v1`` record: a checkpoint reference plus the two
    receipt fields (sc-9.md). No checkpoint field is removed."""

    checkpoint: CheckpointReference
    event_accounting_result: str
    admission_outcome: str

    def to_dict(self) -> dict:
        """Return a plain JSON-safe dict; the record itself stays immutable."""
        data = self.checkpoint.to_dict()
        data["event_accounting"] = {"result": self.event_accounting_result}
        data["admission_outcome"] = self.admission_outcome
        return data


@dataclass(frozen=True)
class EventLedger:
    """Frozen event-accounting ledger. ``seen`` holds the event identities counted
    once; ``duplicates`` counts re-deliveries per identity. No method mutates."""

    seen: tuple = ()
    duplicates: Mapping = field(default_factory=lambda: MappingProxyType({}))

    def count(self, identity: str) -> int:
        return 1 if identity in self.seen else 0

    def duplicate_count(self, identity: str) -> int:
        return self.duplicates.get(identity, 0)


@dataclass(frozen=True)
class Obligations:
    """Frozen obligations snapshot that recovery, a duplicate event and a lead
    handoff must preserve unchanged (SDP l.477 step 4; issue #196 AC-06)."""

    children: tuple = ()
    owed_replies: tuple = ()
    original_request: str = ""
    responsible_party: str = ""
    evidence: tuple = ()
    consumed_allowances: tuple = ()
    worker_count: int = 0
    defect_episode: int = 0
    fix_batch_count: int = 0
    owner_escalation: bool = False


@dataclass(frozen=True)
class RecoveryInput:
    """Frozen inputs to ``admit_recovery``. All fields optional; each maps to the
    resume-admission step that consumes it (see docstring of ``admit_recovery``)."""

    checkpoint: Optional[CheckpointReference] = None  # step 1
    paused: bool = False  # step 2
    resume_over_pause: bool = False  # step 2 (stale note applied over a pause)
    event_identity: str = ""  # step 3
    event_kind: str = EVENT_KIND_COMPACTION  # step 3
    ledger: EventLedger = field(default_factory=EventLedger)  # step 3
    rotation_due: bool = False  # step 3
    native_session_id: Optional[str] = None  # step 3 custody
    sole_writer: bool = True  # step 3
    accounting_result: str = "counted_once"  # step 6 record
    obligations_before: Optional[Obligations] = None  # step 4
    obligations_after: Optional[Obligations] = None  # step 4
    replay_attempted: bool = False  # step 4
    unknown_outcomes: tuple = ()  # step 4
    scope: Optional[ArmedRun] = None  # step 4 scope growth
    fixed_issues: tuple = ()  # step 4
    managed_fallback: bool = False  # step 5
    authority_renewed: bool = False  # step 5
    policy: Optional[BoundsPolicy] = None  # step 5
    counters: Optional[RunCounters] = None  # step 5
    approval_time: Any = None  # step 5
    now: Any = None  # step 5


def _validate_checkpoint_dict_fields(record: dict) -> Result:
    for field_name in (
        "run",
        "session",
        "event",
        "adapter",
        "version",
        "note_revision",
        "freshness",
    ):
        value = record.get(field_name)
        if value is None or value == "":
            return _invalid("missing_required_field", {"field": field_name})
        if not isinstance(value, str):
            return _invalid("malformed_input", {"field": field_name})

    refs = record.get("authoritative_refs")
    if not isinstance(refs, (list, tuple)) or not refs:
        return _invalid("missing_required_field", {"field": "authoritative_refs"})
    for ref in refs:
        if not isinstance(ref, str) or not ref:
            return _invalid("malformed_input", {"field": "authoritative_refs"})

    coverage = record.get("coverage")
    if coverage is not None and coverage not in COVERAGE_VALUES:
        return _invalid("out_of_list_value", {"field": "coverage", "value": coverage})

    degradation = record.get("degradation")
    if degradation is not None and not isinstance(degradation, str):
        return _invalid("malformed_input", {"field": "degradation"})

    return _accept()


def _validate_checkpoint_object(checkpoint: CheckpointReference) -> Result:
    if not isinstance(checkpoint, CheckpointReference):
        return _invalid("malformed_input", {"field": "checkpoint"})
    return _validate_checkpoint_dict_fields(checkpoint.to_dict())


def build_checkpoint_reference(
    run,
    session,
    event,
    adapter,
    version,
    note_revision,
    freshness,
    authoritative_refs,
    coverage=None,
    degradation=None,
) -> Result:
    """Build and validate a ``checkpoint-reference-v1`` record. Required fields,
    non-empty authoritative references and the ``coverage`` closed list are
    enforced; invalid input yields ``Result`` with outcome ``invalid``."""
    check = _validate_checkpoint_dict_fields(
        {
            "run": run,
            "session": session,
            "event": event,
            "adapter": adapter,
            "version": version,
            "note_revision": note_revision,
            "freshness": freshness,
            "authoritative_refs": authoritative_refs,
            "coverage": coverage,
            "degradation": degradation,
        }
    )
    if not check.ok:
        return check
    return _accept(
        value=CheckpointReference(
            run=run,
            session=session,
            event=event,
            adapter=adapter,
            version=version,
            note_revision=note_revision,
            freshness=freshness,
            authoritative_refs=tuple(authoritative_refs),
            coverage=coverage,
            degradation=degradation,
        )
    )


def build_recovery_receipt(
    checkpoint: CheckpointReference, event_accounting_result, admission_outcome
) -> Result:
    """Build and validate a ``recovery-receipt-v1`` record. Every checkpoint field
    is validated unchanged, then the two receipt fields are checked against their
    closed lists. Never raises."""
    if not isinstance(checkpoint, CheckpointReference):
        return _invalid("malformed_input", {"field": "checkpoint"})
    check = _validate_checkpoint_object(checkpoint)
    if not check.ok:
        return check
    if event_accounting_result not in EVENT_ACCOUNTING_RESULTS:
        return _invalid(
            "out_of_list_value",
            {"field": "event_accounting.result", "value": event_accounting_result},
        )
    if admission_outcome not in ADMISSION_OUTCOMES:
        return _invalid(
            "out_of_list_value", {"field": "admission_outcome", "value": admission_outcome}
        )
    return _accept(
        value=RecoveryReceipt(
            checkpoint=checkpoint,
            event_accounting_result=event_accounting_result,
            admission_outcome=admission_outcome,
        )
    )


def validate_sc9_record(record_type, record) -> Result:
    """Validate a SC-9 record against the sc-9.md field tables and closed lists.

    ``record_type`` is ``checkpoint-reference-v1`` or ``recovery-receipt-v1``;
    ``record`` is the record dict. Unknown major version, missing required field or
    out-of-list value yields ``invalid``. A receipt additionally rejects
    ``duplicate_compaction_count`` and every rejection ``admission_outcome``.
    """
    if record_type not in _RECORD_TYPES:
        return _invalid("unsupported_major_version", {"version": record_type})
    if not isinstance(record, dict):
        return _invalid("malformed_input", {"field": "record"})

    check = _validate_checkpoint_dict_fields(record)
    if not check.ok:
        return check

    if record_type == VERSION_CHECKPOINT_REFERENCE:
        return _accept()

    event_accounting = record.get("event_accounting")
    if not isinstance(event_accounting, dict):
        return _invalid("missing_required_field", {"field": "event_accounting"})
    result = event_accounting.get("result")
    if result not in EVENT_ACCOUNTING_RESULTS:
        return _invalid("out_of_list_value", {"field": "event_accounting.result", "value": result})

    outcome = record.get("admission_outcome")
    if outcome not in ADMISSION_OUTCOMES:
        return _invalid("out_of_list_value", {"field": "admission_outcome", "value": outcome})

    if result == "duplicate_compaction_count":
        return _invalid("duplicate_compaction_count")
    if outcome in ADMISSION_OUTCOME_REJECT:
        return _invalid(outcome)
    return _accept()


def account_event(ledger: EventLedger, identity: str, kind: str) -> Result:
    """Count one event (compaction, wake, restart, duplicate hook delivery, lead
    handoff) once by identity. A duplicate identity is recorded as a duplicate and
    changes no counter; the accounting result stays ``counted_once``. Returns a new
    ledger; the input ledger is never mutated."""
    if not isinstance(ledger, EventLedger):
        return _invalid("malformed_input", {"field": "ledger"})
    if not isinstance(identity, str) or not identity:
        return _invalid("malformed_input", {"field": "identity"})
    if kind not in EVENT_KINDS:
        return _invalid("out_of_list_value", {"field": "kind", "value": kind})

    if identity in ledger.seen:
        new_duplicates = dict(ledger.duplicates)
        new_duplicates[identity] = new_duplicates.get(identity, 0) + 1
        next_ledger = EventLedger(
            seen=ledger.seen,
            duplicates=MappingProxyType(new_duplicates),
        )
        return _accept(
            value=next_ledger,
            detail={
                "counted": False,
                "count": 1,
                "result": "counted_once",
                "duplicate": True,
                "duplicate_count": new_duplicates[identity],
            },
        )

    next_ledger = EventLedger(seen=ledger.seen + (identity,), duplicates=ledger.duplicates)
    return _accept(
        value=next_ledger,
        detail={"counted": True, "count": 1, "result": "counted_once", "duplicate": False},
    )


def preserve_obligations(before: Obligations, after: Obligations) -> Result:
    """Assert that obligations survive recovery, a duplicate event or a lead
    handoff unchanged: children, owed replies, the original request, the
    responsible party, evidence, consumed allowances, worker count, defect episode
    and fix-batch count are all compared; a difference is ``obligations_changed``
    naming every changed field. No new worker, no episode reset, no extra fix
    batch and no automatic owner escalation are all implied by equality."""
    if not isinstance(before, Obligations) or not isinstance(after, Obligations):
        return _invalid("malformed_input", {"field": "obligations"})
    if before == after:
        return _accept(detail={"preserved": True})
    changed = [
        f.name for f in fields(Obligations) if getattr(before, f.name) != getattr(after, f.name)
    ]
    return _invalid("obligations_changed", {"changed": changed})


def classify_note(note_status, *, paused: bool = False, checkpoint_available: bool = False) -> Result:
    """Classify the handoff note for admission (sc-9.md note cases). A stale note
    applied over an owner pause is ``resume_overrides_pause`` (reject). A missing,
    failed or emergency-without-note handoff with a usable ledger checkpoint is
    ``fallback_ledger_recovery`` (accept) with ``degradation`` set and
    ``continuity: fallback``. With neither a usable note nor a usable ledger
    checkpoint the outcome is ``recovery_evidence_unavailable`` (reject)."""
    if note_status not in NOTE_STATUSES:
        return _invalid("out_of_list_value", {"field": "note_status", "value": note_status})

    if note_status == NOTE_CURRENT:
        return _accept(
            value="restored_then_current_state_check",
            detail={"continuity": None, "degradation": None},
        )

    if note_status == NOTE_STALE and paused:
        return _invalid("resume_overrides_pause", {"note_status": note_status})

    if checkpoint_available:
        degradation = _DEGRADATION_BY_STATUS[note_status]
        return _accept(
            value="fallback_ledger_recovery",
            detail={"continuity": "fallback", "degradation": degradation},
        )

    return _invalid("recovery_evidence_unavailable", {"note_status": note_status})


def reconcile_unknown_effect(outcome, *, retry: bool = False) -> Result:
    """Reconcile a consequential action whose response was lost (issue #196 AC-06,
    item 4). An unresolved outcome stays ``unknown``: recovery returns
    ``inspect_destination_first`` (never ``retry``) and every dependent action is
    blocked. Repeating the action before reconciliation is
    ``unknown_effect_replay`` (reject). A reconciled outcome unblocks."""
    if outcome not in ("unknown", "resolved"):
        return _invalid("out_of_list_value", {"field": "outcome", "value": outcome})

    if retry and outcome == "unknown":
        return _invalid("unknown_effect_replay")

    if outcome == "unknown":
        return _accept(detail={"action": "inspect_destination_first", "blocked": True})

    return _accept(detail={"action": "continue", "blocked": False})


def classify_lineage(prior_session_id, current_session_id, claim=None) -> Result:
    """Distinguish a same-session compaction from a lineage/custody claim. Custody
    is ``unknown`` when no native session id is supplied. With a new session id the
    claim may be ``successor`` or ``takeover``; without a claim it is a bare
    lineage claim (new session)."""
    if current_session_id is None or current_session_id == "":
        return _accept(value="custody_unknown", detail={"custody": "unknown"})

    if prior_session_id is not None and current_session_id == prior_session_id:
        return _accept(
            value="same_session_compaction",
            detail={"custody": "known", "lineage": "same_session"},
        )

    if claim in ("successor", "takeover"):
        return _accept(value=claim, detail={"custody": "known", "lineage": claim})

    if claim is None:
        return _accept(value="lineage_claim", detail={"custody": "known", "lineage": "new_session"})

    return _invalid("malformed_input", {"field": "claim", "value": claim})


def qualify_adapter(
    adapter,
    *,
    native_session_id=None,
    load_evidence_session=None,
    build_qualified: bool = False,
    event_coverage: bool = False,
    child_exclusions: bool = False,
) -> Result:
    """Qualify an adapter route (H1 l.483-l.485, l.471-l.473). Codex (developing)
    and Pi (owner-reported, O-ADAPT) are never reported as supported/parity. A
    Claude/OpenCode route is supported only by actual build, per-session load
    evidence (a load marker for another session is not proof), event coverage and
    child exclusions."""
    if adapter not in _ADAPTERS:
        return _invalid("malformed_input", {"field": "adapter", "value": adapter})

    if adapter in _DEVELOPING_ADAPTERS:
        route = "O-ADAPT" if adapter == ADAPTER_PI else "developing"
        return _accept(
            detail={"adapter": adapter, "supported": False, "parity": False, "route": route}
        )

    if load_evidence_session is None or load_evidence_session == "":
        return _accept(
            detail={
                "adapter": adapter,
                "supported": False,
                "parity": False,
                "reason": "no_load_evidence",
            }
        )

    if native_session_id is None or load_evidence_session != native_session_id:
        return _accept(
            detail={
                "adapter": adapter,
                "supported": False,
                "parity": False,
                "reason": "foreign_last_loaded_marker",
            }
        )

    supported = bool(build_qualified and event_coverage and child_exclusions)
    return _accept(
        detail={
            "adapter": adapter,
            "supported": supported,
            "parity": supported,
            "reason": None if supported else "unqualified",
        }
    )


def reuse_evidence(subject, head, definition_revision, *, existing=None, pending_ci: bool = False) -> Result:
    """Decide whether verification evidence is reusable (AC-06 evidence reuse).
    Pending CI is never a local-fallback trigger. Evidence for the same subject at
    the same head and definition revision is reused; a different head or definition
    is stale and not reused."""
    if not isinstance(subject, str) or not subject:
        return _invalid("malformed_input", {"field": "subject"})

    if pending_ci:
        return _accept(
            detail={"reusable": False, "fallback": False, "pending_ci": True}
        )

    if existing is None:
        return _accept(detail={"reusable": False, "reason": "no_evidence"})

    if not isinstance(existing, dict):
        return _invalid("malformed_input", {"field": "existing"})

    if existing.get("subject") != subject:
        return _accept(detail={"reusable": False, "reason": "different_subject"})
    if existing.get("head") != head or existing.get("definition_revision") != definition_revision:
        return _accept(detail={"reusable": False, "reason": "stale_evidence"})

    return _accept(detail={"reusable": True, "reused": existing})


def evaluate_coverage(coverage_map) -> Result:
    """Validate and partition a per-adapter coverage map into covered (top-level or
    child) and excluded sessions. Excluded sessions are not counted as covered. A
    value outside the ``coverage`` closed list is invalid."""
    if not isinstance(coverage_map, dict):
        return _invalid("malformed_input", {"field": "coverage_map"})

    covered, excluded = [], []
    for session, value in coverage_map.items():
        if value not in COVERAGE_VALUES:
            return _invalid("out_of_list_value", {"field": "coverage", "value": value, "session": session})
        if value == "excluded":
            excluded.append(session)
        else:
            covered.append(session)

    return _accept(detail={"covered": covered, "excluded": excluded})


def _resolve_outcome(state: RecoveryInput) -> str:
    if state.paused:
        return "pause_honored_recovery_only"
    if state.rotation_due:
        return "rotation_due_rotation_applied"
    if state.checkpoint is not None and state.checkpoint.degradation in _DEGRADED:
        return "fallback_ledger_recovery"
    return "restored_then_current_state_check"


def admit_recovery(state: RecoveryInput) -> Result:
    """Run the SDP l.477 resume admission order as one ordered evaluator. Each step
    fails closed; a failure returns ``Result("invalid")`` with ``detail["step"]``
    naming the step (1-6), and no later step runs.

    Step 1 recover checkpoint identity/freshness/authoritative references;
    step 2 read owner pause before task action (a stale note over a pause rejects);
    step 3 count the event once and check sole writer, rotation and custody;
    step 4 reload scope/heads preserving children, owed replies and unknown
    outcomes (replay before reconciliation rejects); step 5 recheck budgets and
    authority with no managed-to-standalone fallback; step 6 record the recovery
    and continue only eligible work.
    """
    if not isinstance(state, RecoveryInput):
        return _invalid("malformed_input", {"field": "state"})

    # Step 1
    if state.checkpoint is None:
        return _invalid("missing_required_field", {"step": 1, "field": "checkpoint"})
    step1 = _validate_checkpoint_object(state.checkpoint)
    if not step1.ok:
        return _invalid(step1.reason, {**step1.detail, "step": 1})

    # Step 2
    if state.paused and state.resume_over_pause:
        return _invalid("resume_overrides_pause", {"step": 2})

    # Step 3
    if not state.sole_writer:
        return _invalid("second_writer", {"step": 3})
    if state.rotation_due and state.event_kind == EVENT_KIND_COMPACTION:
        return _invalid("compaction_counts_as_rotation", {"step": 3})
    step3 = account_event(state.ledger, state.event_identity, state.event_kind)
    if not step3.ok:
        return _invalid(step3.reason, {**step3.detail, "step": 3})
    next_ledger = step3.value
    custody = "unknown" if (state.native_session_id is None or state.native_session_id == "") else "known"

    # Step 4
    if state.replay_attempted and state.unknown_outcomes:
        return _invalid("unknown_effect_replay", {"step": 4})
    if state.obligations_before is not None and state.obligations_after is not None:
        step4 = preserve_obligations(state.obligations_before, state.obligations_after)
        if not step4.ok:
            return _invalid(step4.reason, {**step4.detail, "step": 4})
    if state.scope is not None and state.fixed_issues:
        scope_check = guard_frozen_scope(state.scope, fixed_issues=list(state.fixed_issues))
        if not scope_check.ok:
            return _invalid(scope_check.reason, {**scope_check.detail, "step": 4})

    # Step 5
    if state.managed_fallback:
        return _invalid("managed_to_standalone", {"step": 5})
    if state.authority_renewed:
        return _invalid("authority_renewed_by_activity", {"step": 5})
    if state.policy is not None and state.counters is not None:
        limits = evaluate_limits(state.policy, state.counters, state.approval_time, state.now)
        if not limits.ok:
            return _invalid(limits.reason, {**limits.detail, "step": 5})

    # Step 6
    if state.accounting_result == "duplicate_compaction_count":
        return _invalid("duplicate_compaction_count", {"step": 6})
    outcome = _resolve_outcome(state)
    receipt = build_recovery_receipt(state.checkpoint, state.accounting_result, outcome)
    if not receipt.ok:
        return _invalid(receipt.reason, {**receipt.detail, "step": 6})

    return _accept(
        value=receipt.value,
        detail={
            "step": 6,
            "custody": custody,
            "event_counted": step3.detail.get("counted"),
            "ledger": next_ledger,
            "admission_outcome": outcome,
        },
    )
