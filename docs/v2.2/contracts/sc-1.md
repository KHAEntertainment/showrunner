# SC-1 — identity/scope (`assignment-v1`)

**Source revision.** Showrunner v2.2 SDP `fee134d9…` §8 l.540 (snapshot SHA-256 `fee134d938f2678f057653b161bd9606ee9e18161e8fc34dc362387d23b94bcd`). Owner-bound values from settled D1 (l.85) and D6.5 (l.142). Issue #184's body cites the superseded snapshot `dae53a66…`; this spec binds the current snapshot (see `index.md`).

L0b revision (2026-11-05) cites SDP `7177580c…`; l.540/544/545 unchanged from `fee134d9`.

**Contract.** `assignment-v1` — the identity/scope read projection for one assignment.

**Semantic owner.** Dev planning owner (Dev planning + backend adapter).

**Version owner.** This SDP owns the version identifier; Dev produces records at the named version (D4.2 version-ownership rule, l.379).

**Producer.** Dev planning + backend adapter (l.540).

**Consumers (package).** P1 (primary — normalizes the same semantics in both backends); P2, GV, panel (U1) consume; I1 (live coordinator) later.

**Authoritative writer / one writer per ledger.** The Tech Lead is the sole writer of the Dev ledger (`skills/dev/templates/DEV_STATE_TEMPLATE.md`, `schema_version: 2`). Foreman/board keep their own separate schemas. `assignment-v1` is a projection/interface over these sources — it is not a replacement for any source schema and introduces no new writable store. Read/normalize only (l.540).

**Field table.** Meanings from the SDP only.

| Field | Type | Cardinality | Required/conditional | Meaning |
| --- | --- | --- | --- | --- |
| `project` / `repo` | qualified identifier (`OWNER/REPO`) | 1 | required | the target GitHub host + owner/repository |
| `run` | string (run id) | 1 | required | the run this assignment belongs to |
| `mode` | enum | 1 | required | execution mode (`standalone` / `managed`; SDP l.23–l.28) |
| `lead` | identity record | 1 | required | lead agent identity (agent id / harness / model) |
| `plan_ref` | record (see sub-table) | 1 | required | portable plan reference carrying origin, source/approved revisions, approval and producer provenance (SDP l.79; D1 l.89–l.90) |
| `source` | reference | 1 | required | source document reference |
| `approval_revision` | reference + digest | 1 | required | the approval revision of the source |
| `fixed_issues` | list of qualified Issue IDs | 1..* | required | the frozen qualified Issue set (`OWNER/REPO#N`) |
| `coordinator` | identity record | 0..1 | conditional (managed only) | the coordinating agent |
| `charter_revision` | reference + digest | 0..1 | conditional (managed only) | the charter revision |
| `contract_refs` | list of references | 0..* | conditional (managed only) | contract references |

`mode` has exactly two values — `standalone` and `managed` (SDP l.23–l.28). A goal run is not a third mode: goal-run identity is a merge-authority concept (D2 l.256) carried by SC-2, not by the assignment mode. No `goal` value is invented here.

**`plan_ref` sub-table.** `plan_ref` is a structured record, not an opaque reference (SDP l.79). It carries plan provenance without requiring machine-specific paths; every revision is GitHub-addressable (D1 l.89–l.91).

| Field | Type | Cardinality | Required | Meaning |
| --- | --- | --- | --- | --- |
| `origin` | reference | 1 | required | canonical plan location — a Traycer artifact in the current epic or a native Markdown document (SDP l.79; D1 l.89) |
| `source_revision` | digest | 1 | required | the source plan revision as an immutable digest (SDP l.79; D1 l.90) |
| `approved_revision` | digest | 1 | required | the approved plan revision as an immutable digest (SDP l.79; D1 l.90) |
| `approval.authority` | identity record | 1 | required | who approved the plan (SDP l.79) |
| `approval.evidence` | reference + digest | 1 | required | GitHub-addressable approval evidence — commit SHA, PR review id, or a retained snapshot/digest (SDP l.79; D1 l.91) |
| `producer.session` | string (session id) | 1 | required | the producing session (SDP l.79) |
| `producer.harness` | string (harness) | 1 | required | the producing harness (SDP l.79) |

**Accepted example.** Two distinct runs in the same repository; an explicitly bounded charter subset (l.540).

**Rejected example.** Bare ambiguous Issue IDs; changed approval; missing managed source; auto-admitted new milestone Issue (l.540); a machine-specific path in `plan_ref` or `source` (SDP l.79).

**Edge cases.**

- unsupported major version → `invalid`
- ambiguous identity (bare Issue ID) → `invalid`
- required field missing → `invalid`
- malformed input → `invalid`
- additive optional field → common-reader fixture, not silent parser leniency (l.536)
- machine-specific path in `plan_ref` or `source` → `invalid`

**Fixtures.**

- `fixtures/sc-1/accepted-two-distinct-runs.json` (accept)
- `fixtures/sc-1/rejected-bare-ambiguous-issue-id.json` (reject)
- `fixtures/sc-1/rejected-missing-managed-source.json` (reject)
- `fixtures/sc-1/accepted-structured-plan-ref.json` (accept)
- `fixtures/sc-1/rejected-machine-path-plan-ref.json` (reject)

**Counterpart acceptance.** `pending` per consumer (P1, P2, GV, panel (U1); I1 later). No compatibility inferred from silence (l.550).

**Revision note.** v1 specification correction (pre-implementation; no consumer shipped; counterpart acceptance pending), 2026-11-05, M2 L0b (defects D-SC1-1, D-SC5-1). Consumers listed unchanged.
