# SC-7 — lifecycle/projection (`run-projection-v1`, `custody-reference-v1`)

**Source revision.** Showrunner v2.2 SDP `63124e80…` §8 l.546. Bound schemas: Dev `schema_version: 2` state (`skills/dev/templates/DEV_STATE_TEMPLATE.md`), Foreman sessions/packets/epoch/logs (`~/.claude/skills/foreman-showrunner/templates/FOREMAN_STATE_TEMPLATE.md`, SHA-256 `acfd05c47757a1eaffc019889645e6f910c5067fcad95ea8a05f6b6f09e11204`). Issue #184's body cites the superseded snapshot `dae53a66…`; this spec binds the current snapshot.

**Contracts.** `run-projection-v1` (a read projection of run lifecycle) and `custody-reference-v1` (custody references).

**Semantic owner.** Source lead (Dev); the panel and inventory own their read adapters.

**Version owner.** This SDP owns the version identifier.

**Producer.** Dev schema-v2 state, Foreman sessions/packets/epoch/logs, board records.

**Consumers (package).** P4 and #112 read; I1, O-LIFE later.

**Authoritative writer / one writer per ledger.** Dev is the sole writer of Dev state; Foreman writes its own sessions/packets; the board owns notes/presence. `run-projection-v1` / `custody-reference-v1` are read projections with **separate fields and no synthetic global phase** (l.546); they introduce no new writable store.

**Scope boundary (Q2).** This spec records only the fields/examples the SDP already states at l.546. It answers **none** of D9.1–D9.7 — same-repo discovery, YAML/evidence version tolerance, completion trigger/cache, the human acceptance channel, invalidation/offline behavior, hook/config precedence, cross-host scope, and the 15 degraded cases are all deferred to the P4 panel technical plan (SDP §14 l.811). No D9 item is answered here.

**Field table.** Meanings from the SDP only.

| Field | Type | Cardinality | Required/conditional | Meaning |
| --- | --- | --- | --- | --- |
| `source` | string | 1 | required | source of the projection |
| `version` | string | 0..1 | conditional (null when `source` is explicitly `unknown`) | source schema version — never a fabricated value for an unresolvable source (l.546) |
| `freshness` | time | 0..1 | conditional (null when `source` is explicitly `unknown`) | freshness timestamp — reported `unknown`, never satisfied, when it cannot be read or ordered |
| `run` / `session` / `seat` | string | 1 | required | run, session, and seat identity |
| `lifecycle` | enum | 1 | required | lifecycle state |
| `predecessor` | reference | 0..1 | conditional | predecessor |
| `successor` | reference | 0..1 | conditional | successor |
| `epoch` | number | 0..1 | conditional | epoch |
| `obligations` | list | 0..* | conditional | obligations |
| `heartbeat` | time | 0..1 | conditional | heartbeat |
| `report_verdict` | record | 0..1 | conditional | report verdict |
| `verification` | record | 0..1 | conditional | verification |
| `next_action` | string | 0..1 | conditional | next action |

**Accepted example.** Distinct concurrent runs; an explicit unknown source (l.546).

**Rejected example.** Two active writers; stale successor claims; idle inferred done; deleting worktrees from archival; note acknowledgment as acceptance (l.546).

**Edge cases.**

- two active writers → `reject`
- idle inferred done → `reject`
- stale successor claims → `reject`
- deleting worktrees from archival → `reject`
- note acknowledgment as acceptance → `reject`

**Fixtures.**

- `fixtures/sc-7/accepted-distinct-concurrent-runs.json` (accept)
- `fixtures/sc-7/accepted-explicit-unknown-source.json` (accept)
- `fixtures/sc-7/rejected-two-active-writers.json` (reject)
- `fixtures/sc-7/rejected-idle-inferred-done.json` (reject)

**Counterpart acceptance.** `pending` per consumer (P4, #112; I1, O-LIFE later). No compatibility inferred from silence (l.550).
