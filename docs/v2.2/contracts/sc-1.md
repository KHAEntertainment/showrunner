# SC-1 — identity/scope (`assignment-v1`)

**Source revision.** Showrunner v2.2 SDP `7177580c…` §8 l.540 (snapshot SHA-256 `7177580c8429d6e5f8f07e6138de72506ac7a419e9697f5102f842d43a93315b`, 819 lines). Owner-bound values from settled D1 (l.85) and D6.5 (l.142). Issue #184's body cites the superseded snapshot `dae53a66…`; the earlier snapshot `fee134d9…` is superseded by `7177580c…` (re-pinned 2026-11-05).

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
| `origin` | reference | 1 | required | canonical plan location — a Traycer artifact in the current epic (portable form `traycer-artifact:<epic-id>/<artifact-path>`, below) or a native Markdown document (SDP l.79; D1 l.89) |
| `source_revision` | digest | 1 | required | digest of the input the plan was drafted from (frozen PRD or supplied document; the D6.2.3 PRD-first route names the PRD as source), SDP l.115, l.129 |
| `approved_revision` | digest | 1 | required | the approved plan revision as an immutable digest (SDP l.79; D1 l.90) |
| `approval.authority` | identity record | 1 | required | who approved the plan (SDP l.79) |
| `approval.evidence` | reference + digest | 1 | required | GitHub-addressable approval evidence — commit SHA, PR review id, or a retained snapshot/digest (SDP l.79; D1 l.91) |
| `producer.session` | string (session id) | 1 | required | the producing session (SDP l.79) |
| `producer.harness` | string (harness) | 1 | required | the producing harness (SDP l.79) |

**Traycer-artifact origin form (2026-11-06, #218).** When the canonical plan is a Traycer artifact in the current epic (SDP l.79; D1 l.89), `plan_ref.origin` is written `traycer-artifact:<epic-id>/<artifact-path>`: the epic id, then the artifact's path relative to that epic's artifacts root (for example `traycer-artifact:synthetic-epic/synthetic-plan/index.md`). The form names no host and no machine path — never `~/`, a leading `/`, or a drive letter — and the scheme prefix keeps it distinct from a repository-relative document path. The SDP fixes the location, not a syntax; this is the narrowest portable spelling. It identifies the canonical home only: readers without Traycer, or on another host, resolve the plan through `source`, the promoted repository copy at `approved_revision` (D1 l.90).

**Invariant — v1 specification correction (D4), 2026-11-05.** When an assignment runs from an approved plan, the top-level `approval_revision` MUST equal `plan_ref.approved_revision` (the same digest), and the top-level `source` names the promoted plan copy at that revision (SDP D1 l.90). `plan_ref.source_revision` is the revision of the input the plan was drafted from (PRD or supplied document; D6.2.3/D6.3.6, SDP l.115, l.129), so it may differ from both. A mismatch between `approval_revision` and `plan_ref.approved_revision` is invalid (the SC-1 "changed approval" rejected example, l.540).

**Accepted example.** Two distinct runs in the same repository; an explicitly bounded charter subset (l.540); a Traycer-artifact `plan_ref.origin` in the portable form (SDP l.79).

**Rejected example.** Bare ambiguous Issue IDs; changed approval; missing managed source; auto-admitted new milestone Issue (l.540); a machine-specific path in `plan_ref` or `source` (SDP l.79).

**Edge cases.**

- unsupported major version → `invalid`
- ambiguous identity (bare Issue ID) → `invalid`
- required field missing → `invalid`
- malformed input → `invalid`
- additive optional field → common-reader fixture, not silent parser leniency (l.536)
- machine-specific path in `plan_ref` or `source` → `invalid`
- `approval_revision` ≠ `plan_ref.approved_revision` → `invalid`

**Fixtures.**

- `fixtures/sc-1/accepted-two-distinct-runs.json` (accept)
- `fixtures/sc-1/rejected-bare-ambiguous-issue-id.json` (reject)
- `fixtures/sc-1/rejected-missing-managed-source.json` (reject)
- `fixtures/sc-1/accepted-structured-plan-ref.json` (accept)
- `fixtures/sc-1/rejected-machine-path-plan-ref.json` (reject)
- `fixtures/sc-1/rejected-approval-revision-mismatch.json` (reject)
- `fixtures/sc-1/accepted-traycer-artifact-origin.json` (accept)

**Counterpart acceptance.** `pending` per consumer (P1, P2, GV, panel (U1); I1 later). No compatibility inferred from silence (l.550).

**Revision note.** v1 specification correction (pre-implementation; no consumer shipped; counterpart acceptance pending), 2026-11-05, M2 L0b (defects D-SC1-1, D-SC5-1). Consumers listed unchanged.
