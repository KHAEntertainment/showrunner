# SC-9 — context/resume (`checkpoint-reference-v1`, `recovery-receipt-v1`)

**Source revision.** Showrunner v2.2 SDP `fee134d9…` §8 l.548; H1 (l.479) for handoff qualification/fallback. Bound schema: handoff packet template `~/.claude/skills/foreman-showrunner/templates/HANDOFF_PACKET.md` (SHA-256 `bfcd4028a1be55a02ce173bcfe4cf0cd9666d1f6d0d80b153ad8403de23adf15`). Issue #184's body cites the superseded snapshot `dae53a66…`; this spec binds the current snapshot.

**Contracts.** `checkpoint-reference-v1` (a reference to a checkpoint) and `recovery-receipt-v1` (the result of a recovery admission).

**Semantic owner.** Handoff adapter owner + workflow recovery owner.

**Version owner.** This SDP owns the version identifier.

**Producer.** Handoff adapter events/notes; actual Dev recovery and Foreman pause/rotation/custody procedures.

**Consumers (package).** P2, G3 current; I1 later.

**Authoritative writer / one writer per ledger.** The lead writes the Dev ledger checkpoint; Foreman writes its own pause/rotation/custody records. `checkpoint-reference-v1` / `recovery-receipt-v1` are references/receipts — they introduce no new writable store. No claim that the adapter itself enforces workflow policy (l.548).

**Field table — `checkpoint-reference-v1`.** Meanings from the SDP only. A checkpoint reference records what a checkpoint is: the identity of the run/session/event it belongs to, the adapter and version that produced it, the note's revision and freshness, the authoritative references it carries, and the coverage/degradation the source recorded.

| Field | Type | Cardinality | Required/conditional | Meaning |
| --- | --- | --- | --- | --- |
| `run` / `session` / `event` | string | 1 | required | run, session, and event identity |
| `adapter` / `version` | record | 1 | required | adapter and version |
| `note_revision` / `freshness` | record | 1 | required | note revision and freshness |
| `authoritative_refs` | list | 1..* | required | authoritative references |
| `coverage` / `degradation` | record | 0..1 | conditional (condition not stated in the SDP; present only when the source records it (no default inferred)) | coverage and degradation |

**Field table — `recovery-receipt-v1`.** A recovery receipt **carries every `checkpoint-reference-v1` field above, unchanged**, and adds the two receipt fields below. No field is removed from either version.

| Field | Type | Cardinality | Required/conditional | Meaning |
| --- | --- | --- | --- | --- |
| `event_accounting` | record | 1 | required | event-accounting result |
| `admission_outcome` | enum | 1 | required | admission outcome |

**Closed value lists.** Three enumerated fields carry closed vocabularies, derived from SDP l.548 and the resume admission order at l.477. A value outside a list is not a member of that version.

`coverage` — the per-adapter coverage of the session the record belongs to (l.548, "per-adapter top-level/child/excluded coverage matrix"; l.471):

- `top_level` — the adapter covers the top-level session
- `child` — the adapter covers the child session
- `excluded` — the adapter excludes that session from coverage

`event_accounting.result` — how the event was counted (l.477 step 3, "count the actual event once"; l.548):

- `counted_once` — the event is counted exactly once
- `duplicate_compaction_count` — the event is counted more than once

`admission_outcome` — the result of the recovery admission:

- `restored_then_current_state_check` — accept: context restored, then current-state checks run (l.548 accepted example; l.477 steps 1–6)
- `fallback_ledger_recovery` — accept: no usable handoff note — handoff is missing or degraded, or an emergency compaction produced no note — so the lead recovers from the ledger checkpoint under the resume admission order and reports `continuity: fallback`; the run is still allowed and H1 adds no new hard stop (l.471; H1 l.486; l.477 step 1)
- `pause_honored_recovery_only` — accept: an owner pause is in force, so recovery proceeds while owner-paused work does not (l.477, "a plugin resume prompt wakes recovery, not owner-paused work"; the pause/resume coexistence case)
- `rotation_due_rotation_applied` — accept: a due rotation was applied, and the successor restored context and ran current-state checks (l.477 step 3; l.754, "paused/rotation-due recovery")
- `resume_overrides_pause` — reject: the resume resumes over an owner pause (l.548; l.477 step 2)
- `authority_renewed_by_activity` — reject: the resumed run's activity is treated as renewing existing authority (l.548, "authority renewal"; D2 l.239, "activity does not renew it")
- `unknown_effect_replay` — reject: a consequential action is repeated before an unknown prior outcome is reconciled (l.548, "unknown effect replay"; l.477 step 4)
- `compaction_counts_as_rotation` — reject: a compaction is treated as satisfying a due rotation (l.548, "compact-as-rotation"; l.477, "a due rotation is not satisfied by compacting again")
- `recovery_evidence_unavailable` — reject: there is no authoritative recovery evidence — no usable note and no usable ledger checkpoint — so the resume admission order has nothing to recover from (l.477 step 1; H1 l.486 falls back to a ledger checkpoint, so this applies only when that checkpoint is missing too)

The five rejections named at l.548 map onto these lists: `resume_overrides_pause`, `duplicate_compaction_count` (in `event_accounting.result`), `authority_renewed_by_activity`, `unknown_effect_replay` and `compaction_counts_as_rotation`.

**A missing note is not a rejection.** Handoff that is missing or degraded still allows the run: the lead recovers from the ledger checkpoint under the resume admission order and reports `continuity: fallback` (l.471; H1 l.486), so `fallback_ledger_recovery` is the outcome whenever a usable ledger checkpoint exists. A missing or failed note is reported through `degradation` together with `fallback_ledger_recovery`; it does not change `coverage`, which keeps the source's own top-level/child/excluded classification (l.475). An emergency compaction that produced no note is recorded the same way — it is the reason the note is missing, not a separate rejection — so its outcome is `fallback_ledger_recovery`. Only when neither a usable note nor a usable ledger checkpoint exists does `recovery_evidence_unavailable` apply.

**Accepted example.** Restored context followed by current-state checks (l.548); a checkpoint reference to a current note; and a missing or degraded handoff — no usable note — recovered from the ledger checkpoint (`continuity: fallback`, l.471; H1 l.486).

**Rejected example.** Stale note overriding a pause; duplicate compaction count; authority renewal; unknown-effect replay; compact-as-rotation (l.548); and a recovery with no authoritative evidence at all.

**Edge cases.**

- stale note overriding pause → `reject`
- duplicate compaction count → `reject`
- authority renewal → `reject`
- unknown-effect replay → `reject`
- compact-as-rotation → `reject`
- missing note, or an emergency compaction that produced no note → `fallback_ledger_recovery` (accept): the run is still allowed, the lead recovers from the ledger checkpoint and reports `continuity: fallback` (l.471; H1 l.486)
- no usable note and no usable ledger checkpoint → `recovery_evidence_unavailable` (reject)
- pause and resume coexist → the pause is honored, so recovery runs and owner-paused work does not (l.477)

**Fixtures.**

- `fixtures/sc-9/accepted-restored-context-current-state-check.json` (accept — `recovery-receipt-v1`)
- `fixtures/sc-9/accepted-checkpoint-reference-current-note.json` (accept — `checkpoint-reference-v1`)
- `fixtures/sc-9/accepted-missing-note-ledger-fallback.json` (accept — no usable handoff note; the run is still allowed and the lead recovers from the ledger checkpoint)
- `fixtures/sc-9/rejected-stale-note-overriding-pause.json` (reject — a stale note applied over an owner pause)
- `fixtures/sc-9/rejected-duplicate-compaction-count.json` (reject — the event is counted more than once)
- `fixtures/sc-9/rejected-authority-renewal.json` (reject — resumed activity is treated as renewing existing authority)
- `fixtures/sc-9/rejected-unknown-effect-replay.json` (reject — a consequential action is repeated before the unknown prior outcome is reconciled)
- `fixtures/sc-9/rejected-compact-as-rotation.json` (reject — a compaction is treated as satisfying a due rotation)

**Counterpart acceptance.** `pending` per consumer (P2, G3; I1 later). No compatibility inferred from silence (l.550).
