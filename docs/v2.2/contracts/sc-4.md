# SC-4 — conformance (`conformance-v1`)

**Source revision.** Showrunner v2.2 SDP `fee134d9…` §8 l.543. Owner-bound values from settled D2 (gates, l.240–l.241) and D7.2 (gate delegation). Foreman checklist source: `~/.claude/skills/foreman-showrunner/templates/STATUS_UPDATE.md` l.26–34 (Workflow conformance table; lane upkeep at l.34). Issue #184's body cites the superseded snapshot `dae53a66…`; this spec binds the current snapshot.

**Contract.** `conformance-v1` — the conformance/checklist record for one run or lane.

**Semantic owner.** Dev workflow owner.

**Version owner.** This SDP owns the version identifier.

**Producer.** Dev gate rules and the Foreman status checklist. P2/P3 supply the applicable records.

**Consumers (package).** P2, P3 (supply records); future supervisor, Scout (read).

**Authoritative writer / one writer per ledger.** The Dev lead is the sole writer of the Dev conformance record; Foreman keeps its own status checklist. `conformance-v1` maps the actual six-mark Foreman checklist to Dev applicability (l.543); it introduces no new writable store. A satisfied process mark does not grant merge/completion authority (STATUS_UPDATE.md l.32).

**Field table.** Meanings from the SDP only; required/conditional are source- and interface-dependent (STATUS_UPDATE.md l.28 → SDP D2 l.240–l.241).

| Field | Type | Cardinality | Required/conditional | Meaning |
| --- | --- | --- | --- | --- |
| `workflow` / `policy_revision` | reference + digest | 1 | required | workflow / policy revision |
| `run` / `lane` | string | 1 | required | the run or lane |
| `head` | reference | 1 | required | the head under check |
| `gate_applicability` | enum | 1 | required | which gates apply to this run/lane (e.g. `qa_trigger_below_threshold`) |
| `evidence` | list of gate records | 1..* | required | one record per applicable gate; entry shape depends on the gate's `state` (below) |
| `marks` | list of `{foreman_mark, dev_applicability, state}` | 1..* | required | the six Foreman checklist marks (STATUS_UPDATE.md l.28; lane upkeep at l.34) mapped to Dev applicability |
| `evaluator` | identity record | 1 | required | the conformance evaluator |
| `evaluator_identity` | record | 0..1 | optional (additive in v1) | the conformance evaluator's identity: `agent_id`, `harness`, `model`, `route_source` (below) |
| `implementer_identity` | record | 0..1 | optional (additive in v1) | the implementing agent's identity: `agent_id`, `harness`, `model` — the family the independent-review route is measured against |
| `report_ref` | reference | 1 | required | the report reference |

**Additive optional fields (v1).** Three optional fields are added to `conformance-v1`. All are additive, so a reader that does not know them reads the record exactly as it did before (representation rule, l.536).

- `evaluator_identity` — the recorded identity of an evaluator and the route under which its independence is established: `{agent_id, harness, model, route_source}`. It is usable on the top-level evaluator and on an evidence entry, and it is optional at both levels. The top-level `evaluator_identity` is the conformance evaluator's identity — it carries the seat-receipts mark — and it is **not** the independent-review gate identity; the independent-review identity is the one on the review evidence entry. `route_source` is `different_family` (a qualified reviewer from a different model family than the implementer, D2 l.265), `clean_context_same_family` (a separate agent with a clean context window on a single-provider run, D2 l.266), `same_family` (the same model family as the implementer, without the clean-context single-provider route) or `none` (no independence route is claimed). Only `different_family` and `clean_context_same_family` are qualifying routes.
  - **The family comparison is against the implementer.** "Different family" means different from the agent that implemented the change (D2 l.265) — never different from the lead or the conformance evaluator. The implementer's identity is resolved from the optional top-level `implementer_identity` when the record carries one, and otherwise from the producer's identity record — for Dev, the ledger's lane entry, which D2 l.269 requires the lead to check. The conformance evaluator's own family is never a substitute.
  - **Absence never rejects.** A v1 record without `evaluator_identity` stays valid. Its independent-review mark is established through the existing `evaluator` and `report_ref` references, which a consumer resolves against the producer's identity record (D2 l.269). The optional field adds a checkable route; it never becomes a requirement, and a reader that does not know it reads the record identically (l.536).
  - **A recorded identity must qualify.** When an identity *is* recorded for the independent-review gate, it is authoritative for that gate: if it meets neither D2 route — the same family as the implementer without the clean-context single-provider fallback, or no route at all — the independent-review mark is not satisfied and the record is rejected. A reviewer that cannot be shown to meet either route does not count (D2 l.268), and family diversity is never inferred from a generic pass (l.543).
- `implementer_identity` — the implementing agent's identity: `{agent_id, harness, model}`. It is optional and top-level only. It makes the independent-review family comparison self-checking: with it, a consumer compares the reviewer's recorded model family against the implementer's without leaving the record. When it is absent, the implementer's identity is resolved from the producer's identity record instead, and the record is still valid.
- `head` (evidence entry) — the head the entry was recorded for. It is optional; when it is absent the entry is read as applying to the record's `head`, so entries written before the field existed are unchanged. When it is present it must name the record's `head`; evidence recorded for another head is rejected (l.543).

Common-reader coverage for these fields is required by the representation rule (l.536) and is carried by `fixtures/common/additive-optional-evaluator-identity-common-reader.json`.

**Reading a `marks[]` entry.** Each entry carries the Foreman mark, its Dev gate applicability (the mapping table below) and the mark's own `state`, drawn from the same vocabulary as the evidence states: `required`, `valid-skip`, `pending`, `failed`. A mark whose applicability is carried by the record's own fields — workflow phase reported (`workflow`/`policy_revision`, `run`/`lane`/`head`) and seat receipts current (the evaluator and its optional `evaluator_identity`) — has no separate evidence entry; a mark whose applicability is carried by a gate has exactly one evidence entry, and the mark's state is read from that entry. The absence of that entry for an applicable gate is itself the missing-evidence defect, not a second defect. The accepted fixtures map all six marks.

**Gate-kind-dependent `evidence` entry shape.** Each `evidence[]` entry carries `{gate, state}` plus state-dependent fields:

- `state: required` → `evaluator` + `report_ref` are required (a mandatory gate must name its evaluator and report).
- `state: valid-skip` → `reason` is required (a documented skip must state why, D2 l.240); no evaluator is required.
- `state: pending` / `state: failed` → no evaluator is required yet; `failed` names the failing evidence.

An entry may also carry the optional `head` and the optional `evaluator_identity` (above).

**Foreman mark → Dev applicability** (STATUS_UPDATE.md l.28 → SDP D2 l.240–l.241). A `marks[]` entry maps a Foreman checklist mark to its Dev gate applicability and the mark's own `state` (`required` / `valid-skip` / `pending` / `failed`).

**Foreman checklist → Dev applicability** (STATUS_UPDATE.md l.28 → SDP D2 l.240–l.241).

| Foreman mark (STATUS_UPDATE.md l.28 for the five conformance columns; l.34 for lane upkeep) | Dev gate applicability |
| --- | --- |
| Workflow phase reported | `workflow`/`policy_revision` + `run`/`lane`/`head` recorded in `conformance-v1` |
| Acceptance lane | current-head QA, or a valid recorded skip (D2 l.240) |
| Independent review | independent review — different model family, or clean-context same family on a single-provider run (D2 l.265) |
| Post-merge record for every merge | post-merge record + gate evidence at the applicable tree (D2 l.242) |
| Seat receipts current | lead/seat identity + custody (L1 custody finding 2) |
| Lane upkeep | lane lifecycle / obligations (D7.1) |

**Accepted example.** A documented skip below the QA triggers (l.543); and the full six-mark Foreman checklist mapped to Dev applicability, with the QA gate met and the reviewer identity recorded.

**Rejected example.** Missing mandatory QA or review; different-head evidence. Do not infer family diversity from a generic pass (l.543).

**Edge cases.**

- missing mandatory QA / review → `reject`
- different-head evidence → `reject` (the evidence entry's optional `head` names another head)
- family diversity inferred from a generic pass → `reject` (l.543)
- independent-review mark met by a recorded identity that meets neither D2 route → `reject` (l.543; D2 l.268 — a reviewer that cannot be shown to meet either route does not count), where the family is measured against the implementer and never against the conformance evaluator; a *missing* `evaluator_identity` never rejects on its own — the mark is resolved against the producer's identity record

**Fixtures.**

- `fixtures/sc-4/accepted-documented-skip-below-qa.json` (accept — documented skip below the QA triggers; maps all six Foreman marks; the legacy review entry carries no recorded identity)
- `fixtures/sc-4/accepted-six-mark-mapping.json` (accept — all six Foreman marks mapped to Dev applicability, QA met and the reviewer route recorded; the reviewer's family is compared with the implementer's, not the lead's)
- `fixtures/sc-4/rejected-missing-mandatory-qa.json` (reject — the mandatory QA gate applies and no QA evidence is recorded)
- `fixtures/sc-4/rejected-different-head-evidence.json` (reject — evidence recorded for a head other than the record's `head`)
- `fixtures/sc-4/rejected-inferred-family-diversity.json` (reject — the recorded reviewer is in the implementer's model family without the clean-context single-provider route, so it meets neither D2 route)
- `fixtures/common/additive-optional-evaluator-identity-common-reader.json` (common reader — a v1 reader that ignores the optional fields reads the record identically, and removing them leaves the outcome unchanged)

**Counterpart acceptance.** `pending` per consumer (P2, P3; future supervisor, Scout). No compatibility inferred from silence (l.550).
