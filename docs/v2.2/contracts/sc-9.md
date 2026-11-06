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
- `pause_honored_recovery_only` — accept: an owner pause is in force, so recovery proceeds while owner-paused work does not (l.477, "a plugin resume prompt wakes recovery, not owner-paused work"; the pause/resume coexistence case)
- `rotation_due_rotation_applied` — accept: a due rotation was applied, and the successor restored context and ran current-state checks (l.477 step 3; l.754, "paused/rotation-due recovery")
- `resume_overrides_pause` — reject: the resume resumes over an owner pause (l.548; l.477 step 2)
- `authority_renewed_by_activity` — reject: the resumed run's activity is treated as renewing existing authority (l.548, "authority renewal"; D2 l.240, "activity does not renew it")
- `unknown_effect_replay` — reject: a consequential action is repeated before an unknown prior outcome is reconciled (l.548, "unknown effect replay"; l.477 step 4)
- `compaction_counts_as_rotation` — reject: a compaction is treated as satisfying a due rotation (l.548, "compact-as-rotation"; l.477, "a due rotation is not satisfied by compacting again")
- `emergency_compaction_without_note` — reject: an emergency compaction produced no note, so there is no checkpoint identity or freshness to recover (l.471; l.477 step 1)
- `missing_note` — reject: the note is missing, so checkpoint identity and freshness cannot be recovered (l.477 step 1)

The five rejections named at l.548 map onto these lists: `resume_overrides_pause`, `duplicate_compaction_count` (in `event_accounting.result`), `authority_renewed_by_activity`, `unknown_effect_replay` and `compaction_counts_as_rotation`.

**Accepted example.** Restored context followed by current-state checks (l.548); and a checkpoint reference to a current note.

**Rejected example.** Stale note overriding a pause; duplicate compaction count; authority renewal; unknown-effect replay; compact-as-rotation (l.548).

**Edge cases.**

- stale note overriding pause → `reject`
- duplicate compaction count → `reject`
- authority renewal → `reject`
- unknown-effect replay → `reject`
- compact-as-rotation → `reject`
- emergency compaction without a note → `reject` (l.471)
- missing note → `reject` (l.477 step 1)
- pause and resume coexist → the pause is honored, so recovery runs and owner-paused work does not (l.477)

**Fixtures.**

- `fixtures/sc-9/accepted-restored-context-current-state-check.json` (accept — `recovery-receipt-v1`)
- `fixtures/sc-9/accepted-checkpoint-reference-current-note.json` (accept — `checkpoint-reference-v1`)
- `fixtures/sc-9/rejected-stale-note-overriding-pause.json` (reject — a stale note applied over an owner pause)
- `fixtures/sc-9/rejected-duplicate-compaction-count.json` (reject — the event is counted more than once)
- `fixtures/sc-9/rejected-authority-renewal.json` (reject — resumed activity is treated as renewing existing authority)
- `fixtures/sc-9/rejected-unknown-effect-replay.json` (reject — a consequential action is repeated before the unknown prior outcome is reconciled)
- `fixtures/sc-9/rejected-compact-as-rotation.json` (reject — a compaction is treated as satisfying a due rotation)

**Counterpart acceptance.** `pending` per consumer (P2, G3; I1 later). No compatibility inferred from silence (l.550).
