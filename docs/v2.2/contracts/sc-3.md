# SC-3 — completion (`completion-evidence-v1`, `completion-result-v1`)

**Source revision.** Showrunner v2.2 SDP `fee134d9…` §8 l.542, D4.2 (l.372–l.383), D4.5 (l.426–l.450). Reconciled with the Foreman Architect response `~/.traycer/epics/d4441475-0b2c-4519-99ce-0832b63313f9/artifacts/foreman-coordination/completion-result-v1-response/index.md` (SHA-256 `de1301ba9ceb24e93487e381c580a31c5ec7dc643ae9d8289c953d1140756aef`, 41 lines), labelled **proposed reconciliation — the owner-approved form is SDP D4.5**. Issue #184's body cites the superseded snapshot `dae53a66…`; this spec binds the current snapshot.

**Status.** **Settled** — `completion-result-v1` is owner-approved (2026-11-04) and SC-3 reads it as settled (ledger §3.1, §2 D4.5 row). This spec records the settled policy; it is **not implemented** and proposes no default beyond it.

**Non-goals (Issue #184 AC3, stated explicitly).** Neither readiness nor this Issue approval creates an execution-Issue closure gate or a cross-repository GV fallback. D4.5 §3 readiness is Dev-only in v1 (l.439): no consumer may require a readiness or final GV result before an execution Issue closes; Foreman's merged-but-open sweep closes from Dev's post-merge criterion evidence and never invokes GV.

**Contracts.**

1. `completion-evidence-v1` (settled, D4.2, l.372) — two record types (below). Neither carries the GV result; the parent record may only point to it through `goal_completion_ref`. `assurance` is never goal completion (l.376).
2. `completion-result-v1` (settled, D4.5, l.426) — the GV result GV prints and the Dev lead records as sole writer. GV stays read-only.

**Semantic owner.** GV owner.

**Version owner.** This SDP owns the version identifier, beside `completion-evidence-v1` (l.428).

**Producer.** GV (read-only); the Dev lead is the sole writer of the result (l.430).

**Consumers (package).** P3 (wires GV before G3), pilot, resume, panel (U1); future Foreman audit/hooks.

**Authoritative writer / one writer per ledger.** The Dev lead is the sole writer of the GV result record. The parent-acceptance record's `goal_completion_ref` points to it. No new store, schema authority, or shared writable ledger (l.428, l.383).

## `completion-evidence-v1` — record types (D4.2)

Normative fixture source: the [v2.1.3 cross-project reconciliation report §2](~/.traycer/epics/6266293c-edb0-48f6-b8f6-ddd561de1f05/artifacts/v2-1-3-progress-first-verification/cross-project-reconciliation-report/index.md) (SHA-256 `0e24709b5efc58036644435392a317dc751583cfb5f7b692e4df527a81686a11`), named by SDP l.374. Bound schema: `skills/dev/templates/DEV_STATE_TEMPLATE.md` l.265–l.357 (`schema_version: 2`).

### `pr_assurance` record (DEV_STATE_TEMPLATE l.265–l.343)

| Field | Type | Cardinality | Required/conditional | Meaning |
| --- | --- | --- | --- | --- |
| `profile_version` | string | 1 | required | `completion-evidence-v1` |
| `scope` | enum (`pr_assurance`) | 1 | required | record type |
| `repository` | `OWNER/REPO` | 1 | required | the repository |
| `issue` | `OWNER/REPO#N` | 1 | required | the Issue, qualified |
| `parent_ref` | qualified parent / `linear:KEY-N` | 0..1 | conditional (null for standalone single-PR) | parent objective |
| `criteria_ref` | `sha256:<digest>` | 1 | required | approved acceptance content only, never status prose |
| `criteria_ids` | list | 1..* | required | criteria IDs qualified by revision |
| `policy_ref` | `{ref, rev}` | 1 | required | policy reference + revision |
| `base_oid` | reference | 1 | required | base commit |
| `target_branch` | string | 1 | required | destination branch |
| `headRefOid` | reference | 1 | required | head commit |
| `checks` | list | 1..* | required | per-check `{id, definition_ref{ref,rev}, executor, tested_subject, environment, real_vs_mocked, outcome, evidence_ref, observed_at}` |
| `criteria` | list | 1..* | required | per-criterion `{id, evaluator{type,id}, outcome, evidence_ref, reason}` |
| `demonstrated` | `{what, where, revision, how}` | 0..1 | conditional (`unverified` scalar otherwise) | demonstration |
| `assurance` | `{outcome, reason, revision, observed_at, current, stale_reason}` | 1 | required | lead-derived result; `pass` only when every criterion passes and no unresolved material finding |
| `post_merge` | list | 0..* | conditional (after merge) | `{merge_sha, merged_at, tested_vs_merged, action, run, gate_result, criteria_verdict, checks, criteria}` |
| `integrated` | `{current, history}` | 1 | required | `current` null until merge and after any withdrawal |
| `limitations` | list | 0..* | conditional (empty when none) | provenance limitations |
| `host_load_at_launch` | private | 0..1 | conditional (private) | host load average at heavy-run launch |

### `parent_acceptance` record (DEV_STATE_TEMPLATE l.347–l.358)

| Field | Type | Cardinality | Required/conditional | Meaning |
| --- | --- | --- | --- | --- |
| `profile_version` | string | 1 | required | `completion-evidence-v1` |
| `scope` | enum (`parent_acceptance`) | 1 | required | record type |
| `parent` | qualified parent | 1 | required | parent objective |
| `mode` | enum (`standalone`) | 1 | required | standalone mode |
| `criteria_ref` | `sha256:<digest>` | 1 | required | current approved revision |
| `criteria_map` | list (old ID → new ID) | 0..* | conditional (on amendment) | amendment ID mapping |
| `amendment` | `{from, to, changed, approved_by, recorded_by, at}` | 0..1 | conditional | authorized amendment |
| `contributions` | list of `{pr, issue, criteria, assurance, integrated}` | 1..* | required | one entry per contributing PR |
| `criteria` | list | 1..* | required | per-criterion outcomes |
| `outcome` | enum | 1 | required | acceptance outcome |
| `reason` | string | 0..1 | conditional (when not pass) | reason |
| `observed_at` | time | 1 | required | observation time |
| `goal_completion_ref` | reference | 0..1 | conditional (null until a result exists) | points to — never carries — the GV result |

Managed-mode references (`mode: managed`, `managed`, `assignment_ref`, `parent_mapping`) belong to the same profile and are not written by this Skill version (l.356–l.358).

**Invalidation rules (normative report §2 l.165).** Each event invalidates the affected assurance, which becomes non-current (`current: false` with a `stale_reason`) and is never reused, and each carries its own event-specific transition:

- **New head** → every `check` and criterion outcome is re-assessed; reuse only when `definition_ref.rev`, inputs and environment are unchanged, keeping the old run's tested subject and time.
- **Merged tree ≠ tested tree** → full required gate rerun on the integrated target; a scoped recheck never replaces it.
- **`criteria_ref` change / amendment** → affected criteria `inconclusive`, tests and evaluator judgment reassessed against the new intent regardless of file changes, with an explicit `criteria_map`.
- **Changed check definition, dependency or environment** → affected checks `inconclusive`.
- **Rollback** → `integrated.current` withdrawn for that target, history retained (never the withdrawal itself).
- **Reopened Issue** → affected acceptance withdrawn even though code may remain on the branch.
- **Expired preview** → `demonstrated` marked `expired`.

Historical `assurance.outcome` is preserved with `current: false` (DEV_STATE_TEMPLATE l.318–320). These are the D4.2 meanings (l.378); this spec does not change them.

## `completion-result-v1` — field table (D4.5 meanings)

Meanings from the SDP only; spelling is Dev's (l.432).

| Field | Type | Cardinality | Required/conditional | Meaning |
| --- | --- | --- | --- | --- |
| `profile_version` | string | 1 | required | result-profile version; missing/unknown → `unknown` (l.445) |
| `result_id` | string | 1 | required | result identifier |
| `run_id` | string | 1 | required | the run |
| `plan_ref` | reference + revision | 1 | required | plan reference (revision-qualified) |
| `goal.repository` | qualified identifier | 1 | required | the single repository |
| `goal.parent` | tracker-qualified parent | 0..1 | conditional (managed parent acceptance; standalone may omit) | parent objective |
| `goal.fixed_issues` | frozen qualified Issue set | 1..* | required | the frozen Issue set |
| `goal.frozen_at` | time | 1 | required | freeze time |
| `evidence_profile` | reference | 1 | required | the evidence profile (`completion-evidence-v1`) |
| `consumed_inputs` | list of reference/revision/recorded-time/digest | 1..* | required | each consumed input with reference, revision or recorded time, and digest (l.443); includes the merged-tree gate result and the per-criterion identity/evaluator/proof, each bound to the tested subject (D4.4 l.410) |
| `purpose` | enum (`final` / `readiness`) | 1 | required | `final` returns `verified`/`not_complete`/`inconclusive`; `readiness` returns `evidence_ready`/`not_ready`/`inconclusive`, **never `verified`** (l.433) |
| `repository_facts` | record + `observed_at` | 1 | required | fresh repository facts: PRs with state, merge revision, destination branch and reachability from that branch (D4.3 l.390–392), closed Issues, and integrated acceptance with its record/revision (l.434) |
| `criteria[]` | per-criterion record | 1..* | required | at `criteria_ref`: evaluator, `met`/`unmet`/`inconclusive`, reason code, and accepted proof — `{conclusion, definition, tested_subject}` bound to the tested subject (l.435; D4.4 l.410) |
| `outcome` | enum | 1 | required | outcome within its purpose's vocabulary |
| `reason_codes` | list | 0..* | conditional (when not `verified`) | each naming affected Issues/PRs/criteria (l.436) |
| `producer` | record | 1 | required | helper + Skill revision; invoker role/ID/harness; consumer context; `recorded_by: lead` (l.437) |
| `supersedes` | lineage reference | 0..* | conditional | lineage chain per `(run_id, purpose)` (l.438) |

## D4.5 reader rules (l.441–l.448)

1. **Identity and coverage (l.441).** A usable `final` result names the run, `plan_ref`, the frozen qualified Issue set, every required revision-qualified criterion with its assigned evaluator and proof, the repository facts read, each consumed input, the verifier revision and the recording lead. An `inconclusive` result names the inputs it could not read. No native identity data is invented.
2. **Goal match (l.442).** For managed parent acceptance, the result matches the assigned run, plan and criteria revision, the tracker-qualified parent and the mapped frozen Issue set, with no work omitted and no assignment expanded. A standalone goal may omit `goal.parent`.
3. **Freshness binds to inputs (l.443).** Each consumed input is an identifiable, retained snapshot with its own revision and time. Attaching a result to the parent record, and other bookkeeping writes, never invalidate that result. A later evidence, criteria, repository, approved-source or withdrawal change does. Freshness that cannot be read or ordered is `unknown`, never satisfied.
4. **Foreman reads, Dev computes (l.444).** Dev produces and resolves snapshots and digests. Foreman compares opaque references, revisions and declared times. It adds no canonicalizer, watcher, polling or GV run, and asks the orchestrator for a fresh result when one is stale. The result duplicates no managed field.
5. **Unusable records (l.445).** A missing or unknown `profile_version` is `unknown` and goes back to Dev. An outcome outside its purpose's vocabulary, or `verified` with any criterion not `met` or any blocking reason, makes the record unusable. An exit code never substitutes for the recorded result.
6. **Contradiction compares like with like (l.446).** A result contradicts the parent record only when both describe the same subject, revision and observation context. An earlier pass followed by a withdrawal and a later negative result is history. Progress counts come from the evidence records, not GV's per-criterion lines.
7. **Lineage and retention (l.447).** `supersedes` chains per `(run_id, purpose)`. A result that `goal_completion_ref` points to, or that a Foreman audit or closure comment cites, stays resolvable with its consumed inputs through ledger trimming, for the life of the parent and after acceptance.
8. **Revert limit (l.448).** Merge reachability does not detect an ordinary revert. A revert not yet recorded in the ledger is caught only by D4.3's best-effort revert scanning.

## Goals GV cannot cover (O-1, l.449)

A cross-repository parent or non-PR work is rejected at goal arming (D4.3, D4.4) and uses the ordinary workflow; no GV result is produced or fabricated. Its parent record carries no `goal_completion_ref`. Foreman may accept that parent under its existing charter and evidence authority, and its status update says plainly that this is not GV-verified completion. **A supported goal cannot be relabeled not-applicable when its result is missing, stale, failing or inconclusive.** The panel and any automatic verified-completion reader keep requiring a current GV result. Cross-repository support stays deferred until a cross-repository parent record and a D4.2 profile version change are approved. No not-applicable field is added to `completion-evidence-v1`.

**Accepted example.** `final` only for complete, consistent, fresh closed-Issue proof (l.542).

**Rejected example.** Readiness on an open Issue read as goal-complete; unrelated PR; missing integrated acceptance; inaccessible attestation (l.542).

**Edge cases.**

- `purpose: readiness` returning `verified` → `unusable` (l.433, l.445)
- outcome outside its purpose's vocabulary → `unusable` (l.445)
- missing/unknown `profile_version` → `unknown` (l.445)
- cross-repository / non-PR goal → rejected at goal arming, no result produced (D4.3 l.389, D4.5 §5 l.449)

**Fixtures.**

- `fixtures/sc-3/accepted-final-verified-completion.json` (accept — `completion-result-v1`)
- `fixtures/sc-3/unusable-readiness-never-verified.json` (unusable)
- `fixtures/sc-3/unusable-outcome-outside-vocabulary.json` (unusable)
- `fixtures/sc-3/unknown-missing-profile-version.json` (unknown)
- `fixtures/sc-3/rejected-cross-repo-goal-at-arming.json` (reject)
- `fixtures/sc-3/evidence-accepted-pr-assurance.json` (accept — `pr_assurance`)
- `fixtures/sc-3/evidence-rejected-pr-assurance-noncurrent-no-stale-reason.json` (reject)
- `fixtures/sc-3/evidence-accepted-parent-acceptance.json` (accept — `parent_acceptance`)
- `fixtures/sc-3/evidence-rejected-parent-acceptance-carries-result.json` (reject)

**Counterpart acceptance.** `pending` per consumer (P3, pilot, resume, panel (U1); future Foreman audit/hooks). No compatibility inferred from silence (l.550).
