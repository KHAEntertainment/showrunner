# SC-2 — authority/continuation (`authorization-context-v1`)

**Source revision.** Showrunner v2.2 SDP `fee134d9…` §8 l.541 and §5 l.250 (SC-2 continuation compatibility fixture). Owner-bound values from settled D2 (l.232–l.250) and D3 (l.809). Issue #184's body cites the superseded snapshot `dae53a66…`; this spec binds the current snapshot.

**Contract.** `authorization-context-v1` — the read projection of an operation's authority and continuation context. Separate `Begin` and `Continue` results (l.541).

**Semantic owner.** Dev execution/recovery owner (Dev operation gates); Foreman grant owner for managed input.

**Version owner.** This SDP owns the version identifier.

**Producer.** Dev operation gates (pre-write checks, staged grant/pause/custody procedures); Foreman grant owner for managed input.

**Consumers (package).** P2; I1, O-DB, O-STOP later.

**Authoritative writer / one writer per ledger.** Dev policy and pre-write checks are the Dev-side authority; the Foreman grant owner is the managed-input authority. `authorization-context-v1` is a read projection — it introduces no new writable store and grants no authority by itself (D2 l.248).

**Field table.** Meanings from the SDP only.

| Field | Type | Cardinality | Required/conditional | Meaning |
| --- | --- | --- | --- | --- |
| `policy_ref` | reference | 1 | required | policy document reference |
| `policy_revision` | reference + digest | 1 | required | policy revision |
| `actor` | agent id (string) | 1 | required | the acting agent |
| `run` | string (run id) | 1 | required | the run |
| `operation` | string | 1 | required | the operation name |
| `target` | qualified reference | 1 | required | operation target (repo / PR / Issue) |
| `head` | reference | 1 | required | the head being operated on |
| `grant_id` | string | 0..1 | conditional (granted operation) | grant identifier |
| `grant_kind` | enum | 0..1 | conditional (where required, l.541) | grant kind |
| `grant_holder` | agent id (string) | 0..1 | conditional (where required, l.541) | grant holder |
| `grant_epoch` | number | 0..1 | conditional (where required, l.541) | grant epoch |
| `grant_state` | enum | 0..1 | conditional (where required, l.541) | grant state |
| `grant_start` | time | 0..1 | conditional (where required, l.541) | start time |
| `grant_expiry` | time | 0..1 | conditional (where required, l.541) | expiry time |
| `grant_finish` | time | 0..1 | conditional (where required, l.541) | finish time |
| `pause_ref` | reference | 0..1 | conditional (condition not stated in the SDP; present only when the source records it (no default inferred)) | pause reference |
| `budget_ref` | reference | 0..1 | conditional (condition not stated in the SDP; present only when the source records it (no default inferred)) | budget reference |
| `result` | enum (`Begin` / `Continue`) | 1 | required | separate Begin/Continue results |

**Accepted example.** A currently permitted exact operation after all quality gates; an already-begun safe completion (Continue) (l.541).

**Rejected example.** APPROVE alone; replayed Begin; stale head/grant; paused new work; unlisted scope; renewed budget on rotation (l.541).

**SC-2 continuation fixture (l.250).** After an acknowledged Begin, the same open in-progress operation may Continue across coordinator epoch rotation or its original latest-start expiry. Continue checks stable ID/holder/bindings/started-at and ongoing state; it must not reapply epoch or latest-start expiry as another admission check. Pause or passed finish deadline restricts it to reaching a safe point. Accept that bounded continuation; reject a replayed Begin, changed binding, new operation, or unrestricted new work during pause. A generic stale-grant rejection is insufficient (l.552) — it must not accidentally prohibit an acknowledged operation from reaching safety.

**Fixture shape.** Each SC-2 fixture carries the acknowledged Begin (a `begin` sub-record with `grant_id`/`grant_kind`/`grant_holder`/`grant_epoch`/`grant_state`/`grant_start`/`grant_expiry`) and, for the two accepted cases, an `observation` proving the condition: a `coordinator_epoch` newer than `grant_epoch` (rotation), or an `observed_at` after `grant_expiry` (latest-start expiry). The rejected case keeps `actor`/`run`/`operation`/`target`/`head` and every `begin` binding identical to a valid acknowledged Begin, so the **only** reason to reject is the replayed `Begin`.

**Edge cases.**

- Continue across epoch rotation → `accept`
- Continue after original latest-start expiry → `accept`
- replayed Begin → `reject`
- generic stale-grant rejection that blocks a safe acknowledged Continue → insufficient (l.552)

**Fixtures.**

- `fixtures/sc-2/accepted-continue-epoch-rotation.json` (accept)
- `fixtures/sc-2/accepted-continue-latest-start-expiry.json` (accept)
- `fixtures/sc-2/rejected-replayed-begin.json` (reject)

**Counterpart acceptance.** `pending` per consumer (P2; I1, O-DB, O-STOP later). No compatibility inferred from silence (l.550).
