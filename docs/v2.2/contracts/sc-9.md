# SC-9 — context/resume (`checkpoint-reference-v1`, `recovery-receipt-v1`)

**Source revision.** Showrunner v2.2 SDP `fee134d9…` §8 l.548; H1 (l.479) for handoff qualification/fallback. Bound schema: handoff packet template `~/.claude/skills/foreman-showrunner/templates/HANDOFF_PACKET.md` (SHA-256 `bfcd4028a1be55a02ce173bcfe4cf0cd9666d1f6d0d80b153ad8403de23adf15`). Issue #184's body cites the superseded snapshot `dae53a66…`; this spec binds the current snapshot.

**Contracts.** `checkpoint-reference-v1` (a reference to a checkpoint) and `recovery-receipt-v1` (the result of a recovery admission).

**Semantic owner.** Handoff adapter owner + workflow recovery owner.

**Version owner.** This SDP owns the version identifier.

**Producer.** Handoff adapter events/notes; actual Dev recovery and Foreman pause/rotation/custody procedures.

**Consumers (package).** P2, G3 current; I1 later.

**Authoritative writer / one writer per ledger.** The lead writes the Dev ledger checkpoint; Foreman writes its own pause/rotation/custody records. `checkpoint-reference-v1` / `recovery-receipt-v1` are references/receipts — they introduce no new writable store. No claim that the adapter itself enforces workflow policy (l.548).

**Field table.** Meanings from the SDP only.

| Field | Type | Cardinality | Required/conditional | Meaning |
| --- | --- | --- | --- | --- |
| `run` / `session` / `event` | string | 1 | required | run, session, and event identity |
| `adapter` / `version` | record | 1 | required | adapter and version |
| `note_revision` / `freshness` | record | 1 | required | note revision and freshness |
| `authoritative_refs` | list | 1..* | required | authoritative references |
| `coverage` / `degradation` | record | 0..1 | conditional (condition not stated in the SDP; present only when the source records it (no default inferred)) | coverage and degradation |
| `event_accounting` | record | 1 | required | event-accounting result |
| `admission_outcome` | enum | 1 | required | admission outcome |

**Accepted example.** Restored context followed by current-state checks (l.548).

**Rejected example.** Stale note overriding a pause; duplicate compaction count; authority renewal; unknown-effect replay; compact-as-rotation (l.548).

**Edge cases.**

- stale note overriding pause → `reject`
- duplicate compaction count → `reject`
- authority renewal → `reject`
- unknown-effect replay → `reject`
- compact-as-rotation → `reject`

**Fixtures.**

- `fixtures/sc-9/accepted-restored-context-current-state-check.json` (accept)
- `fixtures/sc-9/rejected-stale-note-overriding-pause.json` (reject)

**Counterpart acceptance.** `pending` per consumer (P2, G3; I1 later). No compatibility inferred from silence (l.550).
