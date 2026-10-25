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

Each `pull_requests` entry records: `number`, `issue`, `branch`, `headRefOid`, `qa_status`, `qa_agent_id`, `internal_review_status`, `reviewer_agent_id`, `external_review_state`, `external_review_payload_snapshots`, `expected_reviewers`, `requested_reviewers`, `observed_reviewers`, `pending_reviewers`, `completed_reviewers`, `external_findings`, `unresolved_actionable_findings`, `review_deadline`, `wait_extensions`, `approved_review_requests`, `consecutive_rate_limits`, `external_reviewer_unavailable`, `external_review_substitutions`, `approved_bypasses`, `review_debt`, `required_checks`, `ci_runs`, `blockers`, `updated_at`, and `next_action`.

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

`ci_runs` is additive under `schema_version: 2`: a ledger written without it stays valid, and a reader that finds it absent treats CI coverage as not yet recorded, never as passing. It is an append-only list on each `pull_requests` entry, and the lead, as sole ledger writer, fills it from `gh run view` output and the job's checkout step, never from inference. One entry records one job attempt: `run`, `job` (the workflow's `name:` value), `attempt`, `definition_ref` and `definition_rev` (the workflow file and its blob revision, so a changed check invalidates reuse), `tested_subject`, `environment`, `conclusion`, `url`, `observed_at`, `covers` (the gate commands the job ran), and `applicability`.

`tested_subject` is `{sha, kind, head, base_oid}` and is never the same field as `headRefOid`. `headRefOid` is the source head the author pushed. `tested_subject.sha` is the commit CI actually checked out: for a `pull_request` run, GitHub's temporary merge commit of the head onto the base (`kind: merge_ref`); for a run on a pushed commit, that commit (`kind: head`). Recording the merge ref as the head would claim a tree nobody tested. `applicability` is `established` only when the run, job and attempt are retrievable, `covers` includes every required command the ownership table in `PROJECT_CONTEXT.md` assigns to the job, the tested subject is known, and the environment and `definition_rev` match; otherwise it is `uncertain`, and uncertain coverage is incomplete, never a pass. A new head or a changed check starts a new entry; it does not edit an old one.

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
        definition_ref: .github/workflows/ci.yml#skill
        definition_rev: 2ab2b59
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
        applicability: established
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
