# SC-4 — conformance (`conformance-v1`)

**Source revision.** Showrunner v2.2 SDP `fee134d9…` §8 l.543. Owner-bound values from settled D2 (gates, l.240–l.241) and D7.2 (gate delegation). Foreman checklist source: `~/.claude/skills/foreman-showrunner/templates/STATUS_UPDATE.md` l.26–32 (Workflow conformance table). Issue #184's body cites the superseded snapshot `dae53a66…`; this spec binds the current snapshot.

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
| `evaluator_identity` | record | 0..1 | optional (additive in v1) | the evaluator's identity: `agent_id`, `harness`, `model`, `route_source` (below) |
| `report_ref` | reference | 1 | required | the report reference |

**Additive optional fields (v1).** Two optional fields are added to `conformance-v1`. Both are additive, so a reader that does not know them reads the record exactly as it did before (representation rule, l.536).

- `evaluator_identity` — the recorded identity of an evaluator and the route under which its independence is established: `{agent_id, harness, model, route_source}`. It is usable on the top-level evaluator and on an evidence entry, and it is optional at both levels. `route_source` is `different_family` (a qualified reviewer from a different model family, D2 l.265), `clean_context_same_family` (a separate agent with a clean context window on a single-provider run, D2 l.266) or `none` (no independence route is claimed). The field lets a consumer check the independent-review route from the record instead of inferring it: D2 l.262–l.269 makes the lead check the harness, model and agent identities in the ledger, and l.543 forbids inferring family diversity from a generic pass. When `evaluator_identity` is absent the record claims no route, and an independent-review mark is not satisfied by an inferred one — a reviewer that cannot be shown to meet either route does not count (D2 l.268).
- `head` (evidence entry) — the head the entry was recorded for. It is optional; when it is absent the entry is read as applying to the record's `head`, so entries written before the field existed are unchanged. When it is present it must name the record's `head`; evidence recorded for another head is rejected (l.543).

Common-reader coverage for both fields is required by the representation rule (l.536) and is carried by `fixtures/common/additive-optional-evaluator-identity-common-reader.json`.

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
- independent-review mark met with no recorded reviewer identity → `reject` (l.543; D2 l.268 — a reviewer that cannot be shown to meet either route does not count)

**Fixtures.**

- `fixtures/sc-4/accepted-documented-skip-below-qa.json` (accept — documented skip below the QA triggers; maps all six Foreman marks)
- `fixtures/sc-4/accepted-six-mark-mapping.json` (accept — all six Foreman marks mapped to Dev applicability, QA met and the reviewer route recorded)
- `fixtures/sc-4/rejected-missing-mandatory-qa.json` (reject — the mandatory QA gate applies and no QA evidence is recorded)
- `fixtures/sc-4/rejected-different-head-evidence.json` (reject — evidence recorded for a head other than the record's `head`)
- `fixtures/sc-4/rejected-inferred-family-diversity.json` (reject — the independent-review mark is met by a generic pass with no reviewer identity)
- `fixtures/common/additive-optional-evaluator-identity-common-reader.json` (common reader — a v1 reader that ignores the optional fields reads the record identically)

**Counterpart acceptance.** `pending` per consumer (P2, P3; future supervisor, Scout). No compatibility inferred from silence (l.550).
