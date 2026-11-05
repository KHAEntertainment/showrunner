# SC-4 — conformance (`conformance-v1`)

**Source revision.** Showrunner v2.2 SDP `63124e80…` §8 l.543. Owner-bound values from settled D2 (gates, l.240–l.241) and D7.2 (gate delegation). Issue #184's body cites the superseded snapshot `dae53a66…`; this spec binds the current snapshot.

**Contract.** `conformance-v1` — the conformance/checklist record for one run or lane.

**Semantic owner.** Dev workflow owner.

**Version owner.** This SDP owns the version identifier.

**Producer.** Dev gate rules and the Foreman status checklist. P2/P3 supply the applicable records.

**Consumers (package).** P2, P3 (supply records); future supervisor, Scout (read).

**Authoritative writer / one writer per ledger.** The Dev lead is the sole writer of the Dev conformance record; Foreman keeps its own status checklist. `conformance-v1` is a projection that maps the actual six-mark Foreman checklist to Dev applicability (l.543); it introduces no new writable store.

**Field table.** Meanings from the SDP only.

| Field | Type | Cardinality | Required/conditional | Meaning |
| --- | --- | --- | --- | --- |
| `workflow` / `policy_revision` | reference + digest | 1 | required | workflow / policy revision |
| `run` / `lane` | string | 1 | required | the run or lane |
| `head` | reference | 1 | required | the head under check |
| `gate_applicability` | enum | 1 | required | which gates apply |
| `evidence` | list of evidence records | 1..* | required | each gate as `required` / `valid-skip` / `pending` / `failed` |
| `evaluator` | identity record | 1 | required | the evaluator |
| `report_ref` | reference | 1 | required | the report reference |

**Accepted example.** A documented skip below the QA triggers (l.543).

**Rejected example.** Missing mandatory QA or review; different-head evidence. Do not infer family diversity from a generic pass (l.543).

**Edge cases.**

- missing mandatory QA / review → `reject`
- different-head evidence → `reject`
- family diversity inferred from a generic pass → `reject` (l.543)

**Fixtures.**

- `fixtures/sc-4/accepted-documented-skip-below-qa.json` (accept)
- `fixtures/sc-4/rejected-missing-mandatory-qa.json` (reject)

**Counterpart acceptance.** `pending` per consumer (P2, P3; future supervisor, Scout). No compatibility inferred from silence (l.550).
