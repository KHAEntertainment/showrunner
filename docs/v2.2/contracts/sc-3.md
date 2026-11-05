# SC-3 — completion (`completion-evidence-v1`, `completion-result-v1`)

**Source revision.** Showrunner v2.2 SDP `63124e80…` §8 l.542, D4.2 (l.372), D4.5 (l.426–l.450). Reconciled with the Foreman Architect response `~/.traycer/epics/d4441475-0b2c-4519-99ce-0832b63313f9/artifacts/foreman-coordination/completion-result-v1-response/index.md` (SHA-256 `de1301ba9ceb24e93487e381c580a31c5ec7dc643ae9d8289c953d1140756aef`, 41 lines), labelled **proposed reconciliation — the owner-approved form is SDP D4.5**. Issue #184's body cites the superseded snapshot `dae53a66…`; this spec binds the current snapshot.

**Status.** **Settled** — `completion-result-v1` is owner-approved (2026-11-04) and SC-3 reads it as settled (ledger §3.1, §2 D4.5 row). This spec records the settled policy; it is **not implemented** and proposes no default beyond it.

**Non-goals (Issue #184 AC3, stated explicitly).** Neither readiness nor this Issue approval creates an execution-Issue closure gate or a cross-repository GV fallback. D4.5 §3 readiness is Dev-only in v1 (l.439): no consumer may require a readiness or final GV result before an execution Issue closes; Foreman's merged-but-open sweep closes from Dev's post-merge criterion evidence and never invokes GV.

**Contracts.**

1. `completion-evidence-v1` (settled, D4.2, l.372) — two record types: a PR record (`scope: pr_assurance`) states assurance at one recorded revision; a parent-acceptance record (`scope: parent_acceptance`) states acceptance of a parent objective across contributing PRs. Neither carries the GV result; the parent record may only point to it through `goal_completion_ref`. `assurance` is never goal completion (l.376).
2. `completion-result-v1` (settled, D4.5, l.426) — the GV result GV prints and the Dev lead records as sole writer. GV stays read-only.

**Semantic owner.** GV owner.

**Version owner.** This SDP owns the version identifier, beside `completion-evidence-v1` (l.428).

**Producer.** GV (read-only); the Dev lead is the sole writer of the result (l.430).

**Consumers (package).** P3 (wires GV before G3), pilot, resume, panel; future Foreman audit/hooks.

**Authoritative writer / one writer per ledger.** The Dev lead is the sole writer of the GV result record. The parent-acceptance record's `goal_completion_ref` points to it. No new store, schema authority, or shared writable ledger (l.428, l.383).

**Field table — `completion-result-v1` (D4.5 meanings).** Meanings from the SDP only; spelling is Dev's (l.432).

| Field | Type | Cardinality | Required/conditional | Meaning |
| --- | --- | --- | --- | --- |
| `profile_version` | string | 1 | required | result-profile version; missing/unknown → `unknown` (l.445) |
| `result_id` | string | 1 | required | result identifier |
| `run_id` | string | 1 | required | the run |
| `plan_ref` | reference | 1 | required | plan reference |
| `goal.repository` | qualified identifier | 1 | required | the single repository |
| `goal.parent` | tracker-qualified parent | 0..1 | conditional (managed parent acceptance; standalone may omit) | parent objective |
| `goal.fixed_issues` | frozen qualified Issue set | 1..* | required | the frozen Issue set |
| `goal.frozen_at` | time | 1 | required | freeze time |
| `evidence_profile` | reference | 1 | required | the evidence profile (`completion-evidence-v1`) |
| `consumed_inputs` | list of reference/revision/digest | 1..* | required | each consumed input with reference, revision or recorded time, and digest (l.443) |
| `purpose` | enum (`final` / `readiness`) | 1 | required | `final` returns `verified`/`not_complete`/`inconclusive`; `readiness` returns `evidence_ready`/`not_ready`/`inconclusive`, **never `verified`** (l.433) |
| `repository_facts.observed_at` | time | 1 | required | fresh read time |
| `criteria[]` | per-criterion record | 1..* | required | at `criteria_ref`: evaluator, `met`/`unmet`/`inconclusive`, reason code, accepted proof (l.435) |
| `outcome` | enum | 1 | required | outcome within its purpose's vocabulary |
| `reason_codes` | list | 0..* | conditional (when not `verified`) | each naming affected Issues/PRs/criteria (l.436) |
| `producer` | record | 1 | required | helper + Skill revision; invoker role/ID/harness; consumer context; `recorded_by: lead` (l.437) |
| `supersedes` | lineage reference | 0..* | conditional | lineage chain per `(run_id, purpose)` (l.438) |

**Accepted example.** `final` only for complete, consistent, fresh closed-Issue proof (l.542).

**Rejected example.** Readiness on an open Issue read as goal-complete; unrelated PR; missing integrated acceptance; inaccessible attestation (l.542).

**Edge cases.**

- `purpose: readiness` returning `verified` → `unusable` (l.433, l.445)
- outcome outside its purpose's vocabulary → `unusable` (l.445)
- missing/unknown `profile_version` → `unknown` (l.445)
- cross-repository / non-PR goal → rejected at goal arming, no result produced (D4.3 l.389, D4.5 §5 l.449)

**Fixtures.**

- `fixtures/sc-3/accepted-final-verified-completion.json` (accept)
- `fixtures/sc-3/unusable-readiness-never-verified.json` (unusable)
- `fixtures/sc-3/unusable-outcome-outside-vocabulary.json` (unusable)
- `fixtures/sc-3/unknown-missing-profile-version.json` (unknown)
- `fixtures/sc-3/rejected-cross-repo-goal-at-arming.json` (reject)

**Counterpart acceptance.** `pending` per consumer (P3, pilot, resume, panel; future Foreman audit/hooks). No compatibility inferred from silence (l.550).
