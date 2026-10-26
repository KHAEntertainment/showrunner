---
schema_version: 2
ledger_profile: |
  The ledger is a YAML subset: maps, lists, and scalars only.
  No anchors
  No tags
  no flow syntax.
  Hand-editable without a parser. Strict enough for a fail-closed reader.
  Additive fields under schema_version: 2 are allowed; validators accept new keys.

# If validation fails: report the named error to the user and repair the ledger
execution:
  execution_backend: incomplete
  detection_status: incomplete
  detection_reason: not_checked
  backend_source: null
  identity_verification: null
  topology: serial
  skill_dir: null
  traycer_agent_id: null
  traycer_epic_id: null
lead:
  agent_id: null
  harness: null
  model: null
  profile: null
  profile_source: null
  reasoning_effort: null
  route_source: null
reviewer:
  agent_id: null
  harness: null
  model: null
  profile: null
  profile_source: null
  reasoning_effort: null
  route_source: null
workers: []
inventory: []
workspace_debt:
  gauge_status: null
  gauge_reason_code: null
  gauge_reason: null
  project: null
  backend: null
  observed_at: null
  counts: null
  threshold: null
  threshold_tripped: null
pull_requests: []
parent_acceptance: []
defect_episodes: []
blockers: []
run_id: null
run_status: null
  one of: active, blocked, recovering, complete, standby
lead_checkpoint: null
next_action: run_backend_detection
updated_at: null
---

# /dev Recovery Log

The Tech Lead is the sole writer of this file. Append a timestamped entry after every verified transition. Do not let workers edit the ledger.

## Execution record schema

Each `execution` entry records: `execution_backend`, `detection_status`, `detection_reason`, `backend_source`, `identity_verification`, `topology`, `skill_dir`, `traycer_agent_id`, and `traycer_epic_id`.

`skill_dir` is the absolute path `${CLAUDE_SKILL_DIR}` resolved to at dispatch time. Dispatched agents do not inherit `CLAUDE_SKILL_DIR`, so the lead substitutes this path into worker, QA, and reviewer prompts before sending them. Re-resolve it at the start of each run rather than trusting a stored value: the path changes when the Skill is reinstalled, and it is version-stamped when the Skill is installed as a plugin.

Allowed `backend_source` values: `null` (not yet resolved), `detected` (the detector chose `traycer` from identifiers in the environment), `supplied` (the detector chose `traycer` from identifiers in `.agent/traycer.env`), and `lead_resolved` (the lead overrode an `incomplete` result, e.g. `claude-native`).

Allowed `identity_verification` values, additive under `schema_version: 2`: `null` (not applicable or not yet verified; always the value for a `detected` identity), `self_source` (a `supplied` identity was verified only by comparison with the session's own self-identity source), `worktree_match` (verified only by the `agent list` row's `folderPaths` and `harnessId`, because the session has no self-identity source), and `self_source_and_worktree_match` (both checks passed). A `supplied` identity that passes neither is `incomplete` and is never recorded with a verification value. The checks are defined in Preflight step 3 of `${CLAUDE_SKILL_DIR}/backends/traycer.md`.

## Worker record schema

Each `workers` entry records: `role`, `issue`, `agent_id`, `harness`, `model`, `profile`, `profile_source`, `reasoning_effort`, `permission_mode`, `route_source`, `branch`, `base_oid`, `source_workspace`, `worktree`, `ownership`, `status`, `pr`, `communication_response_id`, `dispatched_by`, `dispatched_at`, `report_back`, `report_back_termination`, `report_back_cause`, `created_at`, and `updated_at`.

`dispatched_by` and `dispatched_at` are additive under `schema_version: 2` and are written in the same ledger write as `communication_response_id`. `dispatched_by` is the dispatching lead's agent id, taken from that lead's own verified `execution.traycer_agent_id` at the moment the assignment was sent, and `dispatched_at` is the UTC time `agent send` returned the response id. They are the only source of the previous lead's session id after a lead change, and the lead never fills them from a path guess, a directory name, or another agent's record. A worker entry written before these fields existed has neither; the swap-time evidence rule in `${CLAUDE_SKILL_DIR}/backends/traycer.md` then does not apply to that lane and its empty read stays `absent`.

Allowed status values: `planned`, `worktree_ready`, `active`, `blocked`, `pr_created`, `qa`, `review`, `complete`, `stopped`.

## Report-back record schema

`report_back` records whether the lane's report-back was observed and verified; `report_back_cause` records why it was not. The pair takes the same shape as `profile` / `profile_source` above — a value and the qualifier that explains it — rather than a nested record, which nothing else in a `workers` entry uses.

Allowed `report_back` values: `pending` (the lane has been dispatched and no report-back has been observed yet), `complete` (a reply correlated to `communication_response_id` carried all seven required sections), and `incomplete` (it did not).

Allowed `report_back_termination` values: `null` (no bounded read has been performed yet), `completed` (the transport declared the reply complete), `stalled` (a page returned no new content, or a cursor that did not advance), `page_cap` (the adapter's page or re-read cap was reached), and `time_bound` (the adapter's time bound elapsed). These are the four conditions named in the report-back enforcement section of `${CLAUDE_SKILL_DIR}/backends/contract.md`, under one set of names for the contract, both adapters, and this ledger.

**Every bounded read records how it ended, including one that found no correlated reply.** Absence is established by reading, not instead of reading, so a lane recorded `absent` ran a read that terminated somehow, and that condition is evidence. `null` means only that no read has been performed — the same situation as `report_back: pending`, never the outcome of a read.

Allowed `report_back_cause` values: `null` when `report_back` is `pending` or `complete`, and otherwise exactly one of `absent`, `malformed`, or `truncated`, as defined in that same section. **A `report_back: incomplete` with a null cause is an invalid record.** The verdict only says the lane is unverified; the cause is the sole field that selects the remedy, so a verdict without one records that something failed while discarding what to do about it.

**Derive `report_back` and `report_back_cause` from termination, reply correlation, and section presence.** The lead uses those observed inputs to select the row below; the verdict and cause must match that row:

| Correlated reply | `report_back_termination` | Sections present | `report_back` | `report_back_cause` |
|---|---|---|---|---|
| not yet read | `null` | not examined | `pending` | `null` |
| not observed | `stalled`, `page_cap`, `time_bound` | not examined | `incomplete` | `truncated` |
| not observed | `completed` | not examined | `incomplete` | `absent` |
| observed | `stalled`, `page_cap`, `time_bound` | not judged | `incomplete` | `truncated` |
| observed | `completed` | any missing | `incomplete` | `malformed` |
| observed | `completed` | all seven | `complete` | `null` |

The mapping is total, so every observation has exactly one row, and any pairing not in this table is an invalid record — `absent` beside a cut read, `malformed` beside a stall, or any non-null cause beside `report_back: complete`.

**The swap-time evidence rule adds no row.** After a lead change, `${CLAUDE_SKILL_DIR}/backends/traycer.md` may let a message in the previous lead's transcript count as the correlated reply; that only decides the first column's "observed" or "not observed", and the table above applies to the result unchanged. The rule never upgrades a cut read: a read that ended `stalled`, `page_cap`, or `time_bound` is `truncated` here as everywhere.

**`absent` requires a `completed` read.** A read cut short by a stall, the page cap, or the time bound that found no correlated reply has not established absence; the reply may lie past the cut. That record is `truncated`, and the remedy is to re-read before concluding anything about the lane. Reading "no reply seen so far" as "no reply exists" would be this contract's own defect — a partial absence of signal taken as a positive finding — committed by the ledger that exists to prevent it.

On an `absent` record the termination is not colour but the evidence for the claim: `completed` is what distinguishes "the transport said that is everything, and the reply was not in it" from "we stopped looking." Without it, `absent` is an assertion with nothing behind it.

The termination condition is kept because the cause is lossy on purpose. `truncated` covers three conditions that share one remedy — re-read — so the cause is sufficient to decide what to do next and insufficient to see a pattern across lanes. A transport that stalls on every lane and one that rarely hits the time bound are the same `truncated` in the cause and distinguishable only here.

`pending` is not a cosmetic default. Without it, a lane that reported cleanly and a lane nobody ever observed occupy the same absence in the ledger — which is the failure this field exists to make visible, one level up. A lane is never `complete` by never having been looked at.

## Pull request record schema

Each `pull_requests` entry records: `number`, `issue`, `branch`, `headRefOid`, `qa_status`, `qa_agent_id`, `internal_review_status`, `reviewer_agent_id`, `external_review_state`, `external_review_payload_snapshots`, `expected_reviewers`, `requested_reviewers`, `observed_reviewers`, `pending_reviewers`, `completed_reviewers`, `external_findings`, `unresolved_actionable_findings`, `review_deadline`, `wait_extensions`, `approved_review_requests`, `consecutive_rate_limits`, `external_reviewer_unavailable`, `external_review_substitutions`, `approved_bypasses`, `review_debt`, `required_checks`, `ci_runs`, `defect_episode_ref`, `blockers`, `updated_at`, and `next_action`.

`external_review_payload_snapshots` is an append-only list of `{observed_at, headRefOid, path}` records, one per gate run, including disposition reruns. Each path points to the verbatim raw current-PR JSON saved by `--payload-snapshot` before inspection. Keep every snapshot unchanged, including its original formatting; do not replace it with a summary, diff, or interpretation. A missing or failed snapshot is an evidence failure, not a successful observation. The lead records the failure and resolves it before accepting the gate result.

Accepted reviews apply only to the recorded `headRefOid`. After any push, reset QA,
internal review, and external-review completion to pending for the new head;
retain earlier reports as historical evidence. Record each correction review's
base, target, scope and outcome in the timestamped recovery entries, following
**Review after fixes** in `${CLAUDE_SKILL_DIR}/phases/phase4.md`.

For external-review waits, use `approved_review_requests` and recovery entries to
record the reviewer, request time, target head, attempts used and remaining budget.
Keep `review_deadline` and `next_action` current with the deadline and next
observation/retry time. Follow `${CLAUDE_SKILL_DIR}/phases/external-review.md`;
polling, acknowledgements and new pushes do not renew an unfinished wait episode.

Keep `consecutive_rate_limits` per reviewer current while retrying and carry it across heads; only a completed review or an explicit non-rate-limit decline from that reviewer resets it to 0, and reaching 3 triggers the rate-limit breakpoint in `${CLAUDE_SKILL_DIR}/phases/external-review.md`. When the breakpoint fires, `external_reviewer_unavailable` records, per reviewer, `rate_limited`, the count, and the head; when no qualifying family is available it is the ledger record of the still-`pending` gate. Each `external_review_substitutions` entry records `external_reviewer_unavailable: rate_limited`, the substituted reviewer, the `consecutive_rate_limits` count, the substitute identity, the model families of the substitute, the implementation worker, the QA lane, and the internal reviewer, the reviewed `headRefOid`, the substitute's verdict, and the PR comment URL. A substitution is a completed review, not an `approved_bypasses` or `review_debt` entry.

Each `approved_bypasses` / `review_debt` entry must record the reason, approver, timestamp, and the exact unreviewed commit range that no reviewer saw — `<reviewed-head>..<merged-head>` when a review completed at that head, or `<base-head>..<merged-head>` when no review ever completed on the PR (there is no reviewed head to anchor the range, so every commit is unreviewed) — the PR number alone is not sufficient.

## CI evidence record schema (Issue #134)

`ci_runs` is additive under `schema_version: 2`: a ledger written without it stays valid, and a reader that finds it absent treats CI coverage as not yet recorded, never as passing. It is an append-only list on each `pull_requests` entry, and the lead, as sole ledger writer, fills it from `gh run view` output and the job's checkout step, never from inference. One entry records one job attempt: `run`, `job` (the workflow's `name:` value), `attempt`, `definition_ref` (`ref`, the workflow file and job, and `rev`, its blob revision, so a changed check invalidates reuse), `tested_subject`, `environment`, `conclusion`, `url`, `observed_at`, `covers` (the gate commands the job ran), and `applicability` (`to`, `established`, `note`). These spellings follow the approved evidence profile in the evidence record schema below.

`tested_subject` is `{sha, kind, head, base_oid}` and is never the same field as `headRefOid`. `headRefOid` is the source head the author pushed. `tested_subject.sha` is the commit CI actually checked out: for a `pull_request` run, GitHub's temporary merge commit of the head onto the base (`kind: merge_ref`); for a run on a pushed commit, that commit (`kind: head`). Recording the merge ref as the head would claim a tree nobody tested. `applicability.to` names the source head the run applies to. `applicability.established` is `true` only when the run, job and attempt are retrievable, `covers` includes every required command the ownership table in `PROJECT_CONTEXT.md` assigns to the job, the tested subject is known, and the environment and `definition_ref.rev` match; otherwise it is `false`, and uncertain coverage is incomplete, never a pass. `applicability.note` states the basis in one line. A new head or a changed check starts a new entry; it does not edit an old one.

Worked example: the source head is `4e683b4`, but the job tested the merge commit `7a0b5d1`, built on the base `b720c68`.

```yaml
pull_requests:
  - number: 142
    issue: 141
    branch: feat/141-example
    headRefOid: 4e683b4
    base_oid: b720c68
    ci_runs:
      - run: 123
        job: Skill validation
        attempt: 1
        definition_ref:
          ref: .github/workflows/ci.yml#skill
          rev: 2ab2b59
        tested_subject:
          sha: 7a0b5d1
          kind: merge_ref
          head: 4e683b4
          base_oid: b720c68
        environment: ubuntu-latest, python 3.x
        conclusion: success
        url: https://github.com/OWNER/REPO/actions/runs/123
        observed_at: 2026-10-24T15:02:11Z
        covers: python3 scripts/validate_skill.py, python3 -m unittest discover -s tests
        applicability:
          to: 4e683b4
          established: true
          note: every required command ran on the merge ref of the head onto the then-current base
```

## Defect episode record schema (Issue #150)

`defect_episodes` is additive under `schema_version: 2`: a ledger written without it, or a `pull_requests` entry written without `defect_episode_ref`, stays valid, and a reader that finds either absent treats the fix-batch count as not yet recorded, never as zero batches used. It is a top-level list in the lead's ledger, and the lead, as sole ledger writer, fills it; no second counter store exists. The procedure that reads and writes it is **Bounded remediation** in `${CLAUDE_SKILL_DIR}/phases/phase4.md`.

One entry records one defect episode: `id`, `opened_at`, `prs` (the PR numbers in the episode), `fix_batches`, `bound`, and `diagnoses`. `fix_batches` counts dispatched fix batches and is incremented in the same ledger write that records the dispatch. `bound` is the number of automatic batches and defaults to 2. Each `diagnoses` entry records `at`, `what_failed`, `decision`, and `authorized_additional_batches`.

Allowed `decision` values: `narrowed_fix`, `targeted_specialist`, `bounded_extension`, and `owner_decision`. `authorized_additional_batches` is the named number of further batches the diagnosis authorizes: a positive integer for the first three values, and 0 for `owner_decision`, which records that the lead found a consequential intent, authority or risk decision that belongs to the owner. A fix batch may be dispatched only while `fix_batches` is below `bound` plus the sum of `authorized_additional_batches` over `diagnoses`. A diagnosis never authorizes an open-ended number of batches.

`defect_episode_ref` on a `pull_requests` entry is the `id` of its episode. Every PR in the same episode carries the same `defect_episode_ref`, so the count carries across heads, worker swaps, lead handoffs and related PRs. `consecutive_rate_limits` is a provider retry budget and is never counted in `fix_batches`.

Worked example: PR 150 and its related PR 153 share episode `ep-1`. Batches 1 and 2 were automatic, the lead wrote one diagnosis authorizing one more batch, and batch 3 has been dispatched, so the episode has used its whole bound. A fourth batch needs a new diagnosis.

```yaml
defect_episodes:
  - id: ep-1
    opened_at: 2026-10-24T15:02:11Z
    prs:
      - 150
      - 153
    fix_batches: 3
    bound: 2
    diagnoses:
      - at: 2026-10-24T17:40:00Z
        what_failed: batches 1 and 2 fixed the parser but the same acceptance criterion failed again on the new head
        decision: narrowed_fix
        authorized_additional_batches: 1
pull_requests:
  - number: 150
    issue: 150
    branch: feat/150-example
    headRefOid: 4e683b4
    defect_episode_ref: ep-1
  - number: 153
    issue: 150
    branch: fix/150-follow-up
    headRefOid: 9c1d2e7
    defect_episode_ref: ep-1
```

## Post-merge verification record schema

Each merged PR gets one post-merge verification record, appended as a
timestamped recovery entry once the lead completes the unconditional check in
`${CLAUDE_SKILL_DIR}/phases/phase4.md`. A record holds `merge_sha`,
`tested_subject` (the `{sha, kind, head, base_oid}` the CI evidence recorded, per
the CI evidence record schema above), `gate_result`, and `criteria_verdict`.

`gate_result` is `applies_verbatim` when the merge commit's tree hash matched
the tree hash of the recorded `tested_subject`, so the Verification Gate result
on record for that subject carries over rather than being re-run, or
`rerun_pass` / `rerun_fail` when the tree hashes differed (or no tested subject
was recorded) and the full recorded gate result was obtained for `main` at the
merge commit: CI's `push` run on `main`, or the one designated executor's run.
A match against the PR head's tree is not a match: the head is not what CI
tested.

`criteria_verdict` is `confirmed` when every acceptance criterion of the
closed Issue was re-read against the merged code and held, or `unmet` when at
least one did not — paired with an `unmet_criteria` list naming the specific
criteria and the Issue number reopened against them.

**Auto-closure by a merge keyword is never evidence of completion.** This
record is what actually establishes `criteria_verdict`, not the Issue's
closed/open state.

When the merge used the external-review bypass, this record cross-references
that PR's `review_debt` entry above rather than restating its commit-range
rule.

Under Issue #155 the same record is also written as one `post_merge` entry on
the merged PR's `pull_requests` entry, carrying per-check and per-criterion
outcomes at the merge sha, each with `basis: fresh | reused`; the fields are
defined in the evidence record schema below.

## Evidence record schema (Issue #155)

The evidence fields are additive under `schema_version: 2`. A ledger written
without them stays valid, and a reader that finds them absent treats the
evidence as not yet recorded, never as passing. They produce records at the
shared profile `completion-evidence-v1`, the evidence interface approved on
2026-10-19 (reconciliation report §2). This template does not change that
profile's meanings or its version; a version change is a shared owner decision,
and fields marked private sit outside the profile and never change it. The
ledger is block-style YAML, so every flow map in the approved example is
written here as a block map with the same names.

**One record per PR.** A `pull_requests` entry that carries
`profile_version: completion-evidence-v1` is the PR record
(`scope: pr_assurance`). It keeps every field of the pull request record schema
above, including `ci_runs` with its `tested_subject` and `defect_episode_ref`,
and adds:

- Identity: `profile_version`, `scope`, `repository` (`OWNER/REPO`), `issue`
  written qualified as `OWNER/REPO#N`, `parent_ref` (a qualified parent such as
  `OWNER/REPO#N` or `linear:KEY-N`; null is allowed for a standalone single-PR
  delivery), `criteria_ref`, `criteria_ids`, and `policy_ref` (`ref`, `rev`).
- Subject: `base_oid` and `target_branch` beside the existing `headRefOid`.
- Observation: `checks` and `criteria`, below.
- Progress: `demonstrated`, `assurance`, `post_merge`, and `integrated`, below.
- Provenance: `limitations` (a list, empty when none) and the private
  `host_load_at_launch`.

`criteria_ref` is `sha256:<digest>` of the **approved acceptance content only**,
extracted from the Issue body at approval, never the Issue's status prose.
Consumers treat it as opaque and never recompute it; they compare revisions by
reference and by the `amendment` chain. `criteria_ids` lists the criteria this PR
contributes to as stable IDs qualified by that revision (`AC-2@9f3c`).
**Criteria edited after approval mark the affected outcomes `inconclusive`.**
When the Issue's approved acceptance content no longer digests to the recorded
`criteria_ref`, every affected `criteria` and `post_merge` criterion outcome
becomes `inconclusive` until its tests and evaluator judgment are reassessed
against the new intent, whatever files changed. An authorized amendment records
the new `criteria_ref` with an explicit `criteria_map` and `amendment` on the
parent-acceptance record below. An amended criterion is never retired through
`not_applicable`.

Each `checks` entry records `id`, `definition_ref` (`ref` and its blob `rev`, so
a changed definition invalidates reuse), `executor` (`ci`, `worker:<agent_id>`,
`qa:<agent_id>`, `reviewer:<agent_id>`, or `provider:<name>`), `tested_subject`
(the sha the executor actually ran), `environment` (`ci`, `ci:<runner>`,
`host:<id>`, or a named environment such as a preview), `real_vs_mocked` for an
acceptance check, `outcome`, `evidence_ref`, and `observed_at`. Each `criteria`
entry records `id`, `evaluator` (`type` and `id`), `outcome`, `evidence_ref`, and
`reason` when the outcome is not `pass`. Outcomes use the vocabulary of the QA
outcome model in `${CLAUDE_SKILL_DIR}/agents/qa-agent.md`: `pass`, `fail`,
`inconclusive`, `not_applicable`. A required check or criterion is never
`not_applicable`. `evidence_ref` is durable: a run, job and attempt, a review id,
or a PR comment with its retained snapshot. An `evidence_ref` that only names a
local path the consumer cannot reach makes that outcome `inconclusive`.

`demonstrated` is `{what, where, revision, how}` or the scalar `unverified`. It
records Working: a demonstration at an identified revision and environment. A
demonstration satisfies a criterion only when that criterion's assigned evaluator
is `demonstration`. An expired preview marks it `expired`.

`assurance` is the lead-derived PR/slice result and records `outcome` (`pass`,
`fail`, `pending`, `inconclusive`, or `unknown`), `reason`, `revision`,
`observed_at`, `current`, and `stale_reason`. It is `pass` only when every
contributed criterion passes by its assigned evaluator and no material finding is
unresolved at `revision`. `current: false` with a `stale_reason` marks an
assurance whose revision no longer applies (a new head, a withdrawn integration,
or an invalidated input), and a non-current assurance is never reused. No
`verified` boolean existed in this ledger before `assurance`, so it replaces
none. **The PR record carries no goal-completion field.** Goal completion is the
completion verifier's result type, kept in its own record.

Each `post_merge` entry records `merge_sha`, `merged_at`, `tested_vs_merged`
(`same` or `differs`), `action` (`applies_verbatim` or
`full_required_gate_rerun`), `run` (the rerun's run, job, attempt,
`tested_subject` and `conclusion`, when one ran), the existing `gate_result` and
`criteria_verdict`, and per-item `checks` and `criteria`. Each per-item entry
records `id`, `at` (the merge sha), `outcome`, `basis` (`fresh` or `reused`), and
`evidence_ref`; a `reused` entry also records a `justification` naming the diff
that shows the item's inputs, definition and environment are unchanged. **A reuse
without a stated basis or justification is `inconclusive` at the merge sha**, and
parent acceptance cannot count it. Reuse never replaces the full required gate
rerun when the merged tree differs from the tested tree.

`integrated` records `current` (`branch`, `merge_sha`, `revision`, or null) and
`history`, a list of `{branch, merge_sha, integrated_at, withdrawn_at, reason}`.
`current` is null until merge and after any withdrawal; a rollback withdraws
`current` and keeps the history entry.

`host_load_at_launch` (private) is the host's load average when the lane
launched a local heavy run under the resource policy in
`${CLAUDE_SKILL_DIR}/backends/contract.md`, or null when no local heavy run
happened.

**Parent acceptance is a separate record.** `parent_acceptance` is a top-level
list. Each entry records `profile_version`, `scope: parent_acceptance`,
`parent`, `mode` (`standalone`), `criteria_ref` (the current approved revision),
`criteria_map` (old ID to new ID), `amendment` (`from`, `to`, `changed`,
`approved_by`, `recorded_by`, `at`), `contributions` (one entry per PR:
`pr`, `issue`, `criteria`, `assurance`, `integrated`), `criteria`, `outcome`,
`reason`, `observed_at`, and `goal_completion_ref`. In standalone mode the owner
approves an amendment and the lead records it. `goal_completion_ref` only points
to the verifier's result and is null until one exists; the parent record never
carries that result. Managed-mode references (`mode: managed`, `managed`,
`assignment_ref`, `parent_mapping`) belong to the same profile and are not
written by this version of the Skill.

Worked example (the approved §2 records, block style): PR 23 was tested on
GitHub's merge ref, merged after the base had advanced, and later reverted.

```yaml
pull_requests:
  - number: 23
    profile_version: completion-evidence-v1
    scope: pr_assurance
    repository: KHAEntertainment/SupaConsole
    issue: KHAEntertainment/SupaConsole#41
    parent_ref: KHAEntertainment/SupaConsole#40
    criteria_ref: sha256:9f3c
    criteria_ids:
      - AC-1@9f3c
      - AC-2@9f3c
    policy_ref:
      ref: PROJECT_CONTEXT.md#verification-gate
      rev: 3c1e9a0
    headRefOid: 4e683b4
    base_oid: b720c68
    target_branch: main
    ci_runs:
      - run: 123
        job: build
        attempt: 1
        definition_ref:
          ref: .github/workflows/ci.yml#build
          rev: 2ab2b59
        tested_subject:
          sha: 7a0b5d1
          kind: merge_ref
          head: 4e683b4
          base_oid: b720c68
        environment: "ubuntu-latest / node 22 / prisma generate, tsc --noEmit, eslint, vitest run"
        conclusion: success
        url: https://github.com/KHAEntertainment/SupaConsole/actions/runs/123
        observed_at: 2026-10-20T15:02:11Z
        applicability:
          to: 4e683b4
          established: true
          note: "all four required commands ran; merge ref of head onto the then-current base"
    checks:
      - id: build
        definition_ref:
          ref: .github/workflows/ci.yml#build
          rev: 2ab2b59
        executor: ci
        tested_subject: 7a0b5d1
        environment: ci
        outcome: pass
        evidence_ref: "run 123 attempt 1"
        observed_at: 2026-10-20T15:02:11Z
      - id: acceptance:e2e-verify
        definition_ref:
          ref: "ops/e2e.sh verify"
          rev: 9d2c044
        executor: qa:7a1c
        tested_subject: 4e683b4
        environment: preview-vps
        real_vs_mocked: real
        outcome: pass
        evidence_ref:
          comment: "https://github.com/KHAEntertainment/SupaConsole/pull/23#issuecomment-991"
          snapshot: evidence/23/e2e-verify-4e683b4.txt
        observed_at: 2026-10-20T15:40:00Z
    criteria:
      - id: AC-1@9f3c
        evaluator:
          type: test
          id: "vitest src/app/api/projects/rename.test.ts"
        outcome: pass
        evidence_ref: "run 123 attempt 1"
      - id: AC-2@9f3c
        evaluator:
          type: demonstration
          id: worker:9b2
        outcome: pass
        evidence_ref: "PR body demonstration, revision 4e683b4"
    review:
      source: coderabbit
      qualified: true
      head: 4e683b4
      evidence_ref:
        review_id: 2201
        thread_heads:
          - 4e683b4
      unresolved_material: 0
      observed_at: 2026-10-20T15:30:00Z
    defect_episode_ref: ep-1
    demonstrated:
      what: "POST /api/projects/:id/rename returns 200 and the new slug"
      where: worker dev server
      revision: 4e683b4
      how: curl output in PR body
    assurance:
      outcome: pass
      reason: "all contributed criteria pass by assigned evaluator; no unresolved material finding"
      revision: 4e683b4
      observed_at: 2026-10-20T15:45:00Z
      current: false
      stale_reason: "integration withdrawn 2026-10-23 (revert e5a0c3b); outcome stands at revision 4e683b4 only and is not reusable"
    post_merge:
      - merge_sha: d44f1e0
        merged_at: 2026-10-20T16:10:00Z
        tested_vs_merged: differs
        action: full_required_gate_rerun
        run:
          run: 130
          job: build
          attempt: 1
          tested_subject:
            sha: d44f1e0
            kind: head
          conclusion: success
          observed_at: 2026-10-20T16:25:00Z
        gate_result: rerun_pass
        criteria_verdict: confirmed
        checks:
          - id: build
            at: d44f1e0
            outcome: pass
            basis: fresh
            evidence_ref: "run 130 attempt 1"
          - id: acceptance:e2e-verify
            at: d44f1e0
            outcome: pass
            basis: reused
            justification: "git diff 4e683b4..d44f1e0 -- src/app/api/projects/ prisma/ ops/ is empty (base advance touched docs/ only); definition rev 9d2c044 unchanged; preview-vps ran 4e683b4 whose rename path is byte-identical"
            evidence_ref: "issuecomment-991 + snapshot evidence/23/e2e-verify-4e683b4.txt"
        criteria:
          - id: AC-1@9f3c
            at: d44f1e0
            outcome: pass
            basis: fresh
            evaluator:
              type: test
            evidence_ref: "run 130 attempt 1 (vitest re-executed on the merged tree)"
          - id: AC-2@9f3c
            at: d44f1e0
            outcome: pass
            basis: reused
            evaluator:
              type: demonstration
              id: worker:9b2
            justification: "same empty diff on the rename path; demonstration at 4e683b4 applies"
            evidence_ref: "PR body demonstration, revision 4e683b4"
    integrated:
      current: null
      history:
        - branch: main
          merge_sha: d44f1e0
          integrated_at: 2026-10-20T16:10:00Z
          withdrawn_at: 2026-10-23T09:12:00Z
          reason: "reverted by e5a0c3b after Issue #40 reopened"
    limitations: []
    host_load_at_launch: null
parent_acceptance:
  - profile_version: completion-evidence-v1
    scope: parent_acceptance
    parent: KHAEntertainment/SupaConsole#40
    mode: standalone
    criteria_ref: sha256:b17e
    criteria_map:
      AC-1@9f3c: AC-1@b17e
      AC-2@9f3c: AC-2@b17e
      AC-3@9f3c: AC-3@b17e
      AC-4@9f3c: AC-4@b17e
    amendment:
      from: sha256:9f3c
      to: sha256:b17e
      changed:
        - AC-3
      approved_by: owner
      recorded_by: lead
      at: 2026-10-21T10:00:00Z
    contributions:
      - pr: 23
        issue: KHAEntertainment/SupaConsole#41
        criteria:
          - AC-1
          - AC-2
        assurance:
          outcome: pass
          revision: 4e683b4
          current: false
        integrated: withdrawn
      - pr: 24
        issue: KHAEntertainment/SupaConsole#42
        criteria:
          - AC-3
          - AC-4
        assurance:
          outcome: pending
          revision: 1f9e77c
        integrated: null
    criteria:
      - id: AC-1@b17e
        evaluator:
          type: test
        outcome: inconclusive
        reason: "contribution PR 23 integration withdrawn 2026-10-23; re-establish at a current revision"
      - id: AC-2@b17e
        evaluator:
          type: demonstration
        outcome: inconclusive
        reason: same withdrawal
      - id: AC-3@b17e
        evaluator:
          type: independent_reviewer
          id: reviewer lane
        outcome: inconclusive
        reason: "criterion amended 2026-10-21; tests and evaluator judgment to be reassessed against the new intent; PR 24 pending"
      - id: AC-4@b17e
        evaluator:
          type: human
          id: owner
        outcome: pending
        reason: human evaluation not yet performed
    outcome: not_complete
    reason: "2 of 4 criteria withdrawn by rollback, 1 amended and unassessed, 1 awaiting its human evaluator"
    observed_at: 2026-10-23T09:30:00Z
    goal_completion_ref: null
```

The digests are shortened for the example. `review` is the approved example's
review record, carried here verbatim; the Skill's review fields remain those of
the pull request record schema above. Where Dev spelling differs from the
approved example, the meanings map as follows:

| Approved example | Dev ledger field |
|---|---|
| `pull_request` | the entry's existing `number` |
| `fix_batches` (private) | the `fix_batches` of the episode named by `defect_episode_ref` |
| `tier` (private) | the risk tier the lead records for the PR |

## Inventory record schema (Issue #73)

`inventory` is additive under `schema_version: 2`. Per the 2026-10-13 scope
amendment, the inventory **is** the scope boundary: every agent, worktree,
read-only review checkout, and background shell the lead creates gets one
row, and cleanup acts only on inventory rows. Off-inventory objects are
report-only and never stop/archived by the lead. Each `inventory` row holds
`id`, `kind`, `pr`, `role`, `created_at`, `state`, and the kind-specific
fields below.

Allowed `kind` values: `agent`, `worktree`, `review_checkout`, `shell`. The
`agent` and `worktree` kinds read their primary id from the underlying
Traycer object (`agent.id`, `worktree.worktreePath`); the others use a
locally minted id (`review:<path>`, `shell:<hostid>:<name>`).

Allowed `state` values, by kind:

- `agent`: `planned`, `active`, `report-back-pending`, `report-back-complete`, `report-back-incomplete`, `archived-on-accept`, `archived-on-closeout`, `foreign-idle`, `foreign-archived`. The two `foreign` states name agents the lead did not spawn; cleanup rows in those states never appear in a `Not mine` entry of the reply-contract cleanup line without a separate row write.
- `worktree`: `in-progress`, `review-only`, `landed-eligible`, `landed-eligible-and-approved`, `cleaned`, `foreign`. `landed-eligible` flips automatically after the lane's post-merge verification record lands; transition to `landed-eligible-and-approved` happens only after the user approves the row in a consolidation batch.
- `review_checkout`: `in-use`, `clean`, `removed`.
- `shell`: `running`, `stopped`, `exited`.

Allowed `pr` values: a PR number (int) or `null` when no PR is associated.
A row whose `pr` matches a `pull_requests[].number` is part of that PR's
lane; rows with `pr: null` are non-PR work (research lanes, scratch
checkouts).

`role` is the lane role (the same vocabulary `workers[].role` carries) so
a postmortem can join inventory rows to lanes without a second lookup.
`created_at` is the UTC time the row was first written and never changes
after that. Removing a worktree still goes through the wrapper's
`worktree delete --path`, after user approval, with review-tier rows
approved one at a time — that rule lives with the cleanup line in
`reply-contract.md` and a row's `state` cannot reach `cleaned` without
that approval.

## Workspace-debt gauge record (Issue #73)

`workspace_debt` is additive under `schema_version: 2`. It is the snapshot
side of Issue #73: the inventory is the row-by-row ledger, `workspace_debt`
is the single-shot gauge result so the lead's reply-contract cleanup line
has a number to quote without re-running the script every turn.

A `workspace_debt` entry holds `gauge_status`, `gauge_reason_code`,
`gauge_reason`, `project`, `backend`, `observed_at`, `counts`, `threshold`,
and `threshold_tripped`.

`gauge_status` is the JSON status from
`python3 ${CLAUDE_SKILL_DIR}/scripts/workspace_debt.py`: `ok` when the
gauge ran, or `unavailable` when any fault path fired (missing CLI,
timeout, unparseable output, `incomplete` backend). When
`gauge_status: unavailable`, `counts` is `null` and is recorded as `null`
in the ledger — never rewritten to a placeholder zero. Two `unavailable`
runs are recorded as two readings, never collapsed into one. A zero count
means the gauge measured zero; a null count means the gauge did not
measure.

`gauge_reason_code` and `gauge_reason` mirror the script's `reason_code`
and `reason` so a later lead can fault-trace an `unavailable` record
without re-running the gauge. `project` is the `OWNER/REPO` from
`.dev.json`; `backend` is `traycer`, `claude-native`, or `unavailable`.

`observed_at` is the UTC time the gauge ran. `counts` mirrors the
script's `counts` object verbatim: the `worktrees` and `agents`
breakdowns, including `tier_null` and `landed_eligible`, are recorded
exactly as the gauge returned them. Downstream consumers do not
recompute: a row's `counts.worktrees.total` is always the value the
gauge measured at `observed_at`, not a derived view. Removal of a row's
worktree still updates the row's `state`, never its `counts`.

`threshold` is the per-project workspace-debt threshold (an integer
worktree count, default `5`) at which the lead appends the threshold
debt line in § 7.1 of `reply-contract.md`. `threshold_tripped` is the
derived boolean (`counts.worktrees.total > threshold` OR
`counts.agents.active_not_mine > 0` OR `gauge_status: unavailable`), set
by the lead at the same time the threshold debt line is emitted. The
field is `null` when `counts` is `null` (an unavailable gauge is itself
a trip, but the boolean is recorded after `counts` is filled in).

The gauge and the inventory are not interchangeable: the inventory is
the *rows* the lead authored and now owns; `workspace_debt` is a
single observation across the project's Traycer state, including rows
the lead did not author (the ones whose `kind: agent` `parentId` does
not match this lead). The reply-contract cleanup line names inventory
rows under `Still open` and gauge totals under the threshold debt
line; merging them would make the line dishonest about ownership.

## Recovery entries

### YYYY-MM-DDTHH:MM:SSZ — event

- Verified state:
- Evidence:
- Transition:
- Next action:

# If validation fails: report the named error to the user and repair the ledger
