# SC-1 — identity/scope (`assignment-v1`)

**Source revision.** Showrunner v2.2 SDP `63124e80…` §8 l.540 (snapshot SHA-256 `63124e802cb0452f586617b8b913e563941fc700ea7c93efa2dac35db7baddfb`). Owner-bound values from settled D1 (l.85) and D6.5 (l.142). Issue #184's body cites the superseded snapshot `dae53a66…`; this spec binds the current snapshot (see `index.md`).

**Contract.** `assignment-v1` — the identity/scope read projection for one assignment.

**Semantic owner.** Dev planning owner (Dev planning + backend adapter).

**Version owner.** This SDP owns the version identifier; Dev produces records at the named version (D4.2 version-ownership rule, l.379).

**Producer.** Dev planning + backend adapter (l.540).

**Consumers (package).** P1 (primary — normalizes the same semantics in both backends); P2, GV, panel consume; I1 (live coordinator) later.

**Authoritative writer / one writer per ledger.** The Tech Lead is the sole writer of the Dev ledger (`skills/dev/templates/DEV_STATE_TEMPLATE.md`, `schema_version: 2`). Foreman/board keep their own separate schemas. `assignment-v1` is a projection/interface over these sources — it is not a replacement for any source schema and introduces no new writable store. Read/normalize only (l.540).

**Field table.** Meanings from the SDP only.

| Field | Type | Cardinality | Required/conditional | Meaning |
| --- | --- | --- | --- | --- |
| `project` / `repo` | qualified identifier (`OWNER/REPO`) | 1 | required | the target GitHub host + owner/repository |
| `run` | string (run id) | 1 | required | the run this assignment belongs to |
| `mode` | enum | 1 | required | execution mode (`goal` / `managed` / `standalone`) |
| `lead` | identity record | 1 | required | lead agent identity (agent id / harness / model) |
| `plan_ref` | reference | 1 | required | portable plan reference (D1 l.89–l.90) |
| `source` | reference | 1 | required | source document reference |
| `approval_revision` | reference + digest | 1 | required | the approval revision of the source |
| `fixed_issues` | list of qualified Issue IDs | 1..* | required | the frozen qualified Issue set (`OWNER/REPO#N`) |
| `coordinator` | identity record | 0..1 | conditional (managed only) | the coordinating agent |
| `charter_revision` | reference + digest | 0..1 | conditional (managed only) | the charter revision |
| `contract_refs` | list of references | 0..* | conditional (managed only) | contract references |

**Accepted example.** Two distinct runs in the same repository; an explicitly bounded charter subset (l.540).

**Rejected example.** Bare ambiguous Issue IDs; changed approval; missing managed source; auto-admitted new milestone Issue (l.540).

**Edge cases.**

- unsupported major version → `invalid`
- ambiguous identity (bare Issue ID) → `invalid`
- required field missing → `invalid`
- malformed input → `invalid`
- additive optional field → common-reader fixture, not silent parser leniency (l.536)

**Fixtures.**

- `fixtures/sc-1/accepted-two-distinct-runs.json` (accept)
- `fixtures/sc-1/rejected-bare-ambiguous-issue-id.json` (reject)
- `fixtures/sc-1/rejected-missing-managed-source.json` (reject)

**Counterpart acceptance.** `pending` per consumer (P1, P2, GV, panel; I1 later). No compatibility inferred from silence (l.550).
