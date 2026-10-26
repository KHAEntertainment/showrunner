# Phase 4 — Code Review & Merge

---

## Command Output Rules

- Use `rtk gh ...` for PR review, PR merge, PR list, and PR diff, explicitly scoped with `--repo github.com/<github.pullRequestRepository from .dev.json>`. Scope Issue operations to their separately confirmed Issue repository, normally `github.pushRepository` (see `${CLAUDE_SKILL_DIR}/phases/repository-context.md`). Never rely on a cwd-derived default or an inherited `gh` repository default — an unscoped read can silently return evidence about the wrong PR.
- Use compact fields for broad PR scans. Do not request PR bodies, comments, commits, files, or reviews unless reviewing exactly one PR.
- Use `rtk git ...`, `rtk diff`, `rtk test`, `rtk lint`, `rtk npm`, `rtk go`, `rtk pytest`, or equivalent RTK wrappers for local checks.
- If an exact wrapper is unavailable, use `rtk proxy <command> ...`.

---

## Pre-Review Preparation

Use the absolute worktree path recorded for this PR as `<selected-worktree>` in checks below; do not infer it from the ambient directory. Run local Git operations and validation in that same worktree (explicit cwd or `rtk proxy git -C "<selected-worktree>" ...`). Keep GitHub commands scoped to the confirmed host and repository.

Before starting Review, read `PROJECT_CONTEXT.md` for code style conventions, architecture decisions, and the optional External Review Policy. Read `${CLAUDE_SKILL_DIR}/phases/external-review.md`; its observation should already be running from Phase 3.5.

For large or risky PRs, the Tech Lead may use parallel topology through the selected adapter for focused review lanes before making the final rating:
- `review-security`: security implications, secrets, auth, injection, unsafe shell/database calls
- `review-performance`: obvious performance regressions, query loops, concurrency risks
- `review-tests`: acceptance criteria coverage, regression coverage, test output quality

Review agents are advisory only. They must report findings to the Tech Lead and leave PR comments when instructed, but the Tech Lead owns APPROVE / REQUEST CHANGES / COMMENT and all merge decisions.

Before any dispatched independent review, load `${CLAUDE_SKILL_DIR}/agents/reviewer.md`. Require a reviewer agent ID distinct from implementation/fix workers and the QA agent (when a QA lane ran), no implementation ownership, the recorded current `headRefOid`, and clean worktree evidence before and after review.

For a T1 PR the internal reviewer is dispatched only as **Qualified review for T1** in `${CLAUDE_SKILL_DIR}/phases/external-review.md` directs: not when a qualified external review is complete at the current head, and otherwise (rate-limit breakpoint substitution, an unqualified provider, or no source) as that section's table states. T2 and T3 dispatch it as before. The Tech Lead's own checklist review and rating below run for every tier.

---

## Step 0 — Scope-Drift Gate

Resolve the PR's operation target first (`rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/resolve_repository.py" --repo-dir "<selected-worktree>" --operation pr --target <github.pullRequestRepository>` per `${CLAUDE_SKILL_DIR}/phases/repository-context.md`), then run `rtk gh pr diff [PR-number] --repo github.com/<that confirmed repository> --name-only` before any checklist.

- Files clearly outside the Issue and ownership map → mark Scope Drift and REQUEST CHANGES; require the worker to revert unrelated changes.
- Missing files or behavior required by an acceptance criterion → record a completeness failure.
- Scope matches → continue.

The Tech Lead may directly correct review/planning documentation only in a docs-only or related PR. Never directly fix implementation/test code while reviewing.

---

## Static Analysis Gate (run before human review)

Obtain the project's **Verification Gate** result recorded in `PROJECT_CONTEXT.md`
when present, from each check's recorded executor (see **Check Ownership and CI
Evidence** below: the checks assigned to CI are consumed from the `ci_runs`
record, not re-run); otherwise run these defaults:
- Python: `rtk proxy flake8` / `rtk proxy pylint` / `rtk mypy`; security scan: `rtk proxy bandit -r .` (if not installed: ask before installing, then use `rtk pip install bandit`)
- JavaScript: `rtk lint` or `rtk npx eslint`

**Dependency vulnerability scan (mandatory):**
- Python: `rtk proxy pip-audit` (if not installed: ask before installing, then use `rtk pip install pip-audit`)
- Node.js: `rtk npm audit`

If static analysis reports significant errors (not nitpicks), send back to Worker Agent for fixes — do not proceed to human review.
If the dependency scans find High or Critical vulnerabilities, also send back and require dependency upgrades.

---

## Check Ownership and CI Evidence

**One executor per check.** The Verification Gate in `PROJECT_CONTEXT.md` assigns
each check definition, tested subject and environment to one executor, and its
ownership table is authoritative. CI owns the broad checks it assigns to CI.
Workers run focused implementation checks and any prerequisite the project
requires before a push. The lead, QA and the reviewer consume applicable
evidence and do not repeat an equivalent check solely because their role needs
a report. A justified bounded retry, a new target, and a distinct platform
check are not repetition.

**Consume CI evidence through `ci_runs[]`** (schema in
`${CLAUDE_SKILL_DIR}/templates/DEV_STATE_TEMPLATE.md`). A lane may cite a CI run
it read by id, never one it assumes. Evidence is applicable only when all hold:

- the run, job and attempt are retrievable (`rtk gh run view <run> --repo github.com/<confirmed pullRequestRepository> --json jobs`), and the conclusion is `success`;
- the job covers every required check the ownership table assigns to it;
- the **tested subject** is established. A `pull_request` checkout tests GitHub's temporary merge commit (`kind: merge_ref`), not the PR head: `gh run view` reports the PR head as `headSha`, so read the tested sha from the job's checkout step and record it as `tested_subject`, separate from `headRefOid`. A tested subject you cannot establish leaves applicability uncertain;
- the environment and the check-definition revision match what the ownership table requires; a new head, or a changed relevant check, dependency, policy or environment, requires a fresh assessment.

**CI outcomes.**

- Queued or in progress: the dependent verdict stays **pending** under the bounded wait policy that already applies to that route. Independent authorized work may continue. Pending CI never triggers local execution, and this section adds no timeout, retry allowance or bypass.
- Missing, skipped, cancelled, failed, incomplete or stale evidence, or uncertain applicability: required coverage is **incomplete** and is never read as a pass. A skipped Release Gate job on an ordinary PR is expected and is not passing evidence. A test failure is never relabeled an infrastructure failure. A failure already present on `main` is recorded as `baseline_failure` with the `main` run that proves it, and does not permit merge when the project requires the check.
- An optional check may be recorded `not_applicable` with a reason. A required check cannot disappear.

**Fallback.** A local full-gate run needs an approved fallback trigger, which may already exist in project or run policy, or a separate local project requirement. It also needs one designated executor, suitable coverage and environment, and the existing execution and resource limits (heavy runs serial and wrapped). A recorded reason alone is not authority. The executor records the reason, scope (the checks run), tested subject, environment and result. A local pass never replaces required CI or erases a known failure. With no eligible route, the verdict stays pending, blocked or inconclusive and the missing requirement is recorded.

**Preserved.** A mandatory pre-push requirement already in project policy, repository hooks, the fix-and-retest rules, and the post-merge verification below all stay in force until explicitly amended.

---

## Two-Pass Review

First classify whether a finding blocks delivery using the two passes below.
Only then choose how to handle blocking work:

- **DELEGATE-FIX**: a blocking finding has a clear fix, performed by a Worker Agent in its assigned worktree.
- **ASK**: resolving a potentially blocking finding requires clarification of intent, interface semantics, permissions, or tradeoffs; batch these questions.

An easy fix is not necessarily blocking. Record advisory findings with a rationale
and follow-up location in the existing debt records or issue tracker.

### Pass 1 — Critical (any unresolved failure blocks merge)

```
□ Scope Drift
  Verify modified files against the Issue and ownership map.

□ SQL and shell safety
  Reject concatenated SQL/shell input, unsafe eval, or unparameterized raw queries.

□ Secrets and sensitive logging
  Reject hardcoded credentials/tokens or logging of secrets.

□ Authentication/authorization boundaries
  Verify every new entry point enforces the intended identity and permission rules; ASK when intent is unclear.

□ Race conditions and side effects
  Trace concurrent calls to state-changing functions; ASK when locking/atomicity requirements are unclear.

□ Feature completeness
  Map every acceptance criterion to implementation evidence.

□ Error handling
  Trace DB/API/file failures; DELEGATE-FIX obvious omissions and ASK when failure semantics are ambiguous.

□ Tests and migrations
  Block when the project has a test framework but the new behavior has no tests, or when schema changes bypass the approved migration framework/rollback path.
```

### Pass 2 — Informational (record unless it exposes a Pass 1 defect)

```
□ Coverage gaps on non-critical paths
□ Magic numbers and configuration hardcoding
□ Dead code and unused imports
□ N+1 queries, looped I/O, or other performance smells
□ Style consistency with PROJECT_CONTEXT.md
□ Migration downgrade quality
```

Immediately before each review submission, re-run `rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/resolve_repository.py" --repo-dir "<selected-worktree>" --operation pr --target <confirmed pullRequestRepository>` and require exit 0. Use `rtk gh pr review --repo github.com/<confirmed pullRequestRepository>` for concrete findings. Batch ASK items rather than interrupting one at a time.

Before dispatching a fix batch, consolidate findings already available from QA,
internal review, and external review. Dispatch confirmed blockers together.
Do not wait indefinitely for another review source to join the batch or delay
urgent security/data-loss containment. Once the batch is ready, avoid extra
commits solely for advisory cleanup. New material evidence can still require a fix.
Count every batch on its defect episode and follow **Bounded remediation** below before dispatching it.

## Coverage-Path Audit

Trace each changed entry point and show which paths have executed tests versus static evidence:

```
Coverage Audit — [PR title]
changed: src/auth.py

  register()
    ├── valid input → 201             [executed test]
    ├── duplicate email → 409         [executed test]
    ├── invalid format → 400          [missing test]
    └── database unavailable → 500    [static evidence only]
```

- Missing Critical-path tests block when a test framework exists.
- Missing non-critical paths are Pass 2 findings unless they reveal an acceptance-criteria gap.
- **When Graft is available per `${CLAUDE_SKILL_DIR}/graft.md`, produce callers-of/dependents evidence from `rtk proxy graft callers <symbol> -d N --json` + freshness to augment static evidence; else record `graph_evidence: unavailable` + cause and trace dependents manually with `rg`/`git grep`. Graph output = static evidence, never execution confirmation.**

## Adversarial Second Opinion

Trigger a focused read-only reviewer when any ASK finding remains. Give it only the uncertain findings and relevant diff sections. Require an independent judgment on whether the issue is real, its severity, and the recommended resolution. Skip this step when all findings are clearly passed or DELEGATE-FIX.

Launch and observe it through the selected adapter. If its identity, route, response correlation, target head, or clean-worktree result cannot be verified, mark internal review `incomplete` and do not merge.

---

## Review Rating

Before assigning a rating, rerun the external-review inspector, triage every active current-head trusted-reviewer finding and every finding of a completed current-head substitute review, and verify that the PR's current `headRefOid` still matches `.agent/dev-state.md`.

If the head changed, invalidate QA, internal review, and external-review completion
for the new head, retain historical evidence, and follow **Review after fixes**
below before rating the PR.

- `blocking` external review, or a completed, current-head substitute review with a blocking finding → REQUEST CHANGES.
- A `pending` whose only open seats are filled by a completed, current-head substitution routes as `clear` per **Rate-limit breakpoint** in the external-review gate, provided no finding, the substitute's included, is blocking or awaiting disposition; a substitute at an older head does not count.
- Any other `pending`, or `incomplete`, external review → do not merge; follow the explicit waiting/approval choices in the external-review gate.
- `clear` or `not_applicable` → continue to the internal rating below. This is not a substitute for the internal checklist.
- T1 review lane: a qualified external review complete at the current head with every active finding triaged is the T1 independent review, so the internal reviewer is not dispatched and the record names the source (`internal_review_status: not_dispatched`; see **Qualified review for T1**). A provider that is unqualified for any reason other than a rate limit past the breakpoint never reads as `clear`: a required provider stays `pending` or `incomplete`, and the internal reviewer may perform the review role. A credible material defect from an ignored or non-required source is still triaged by the lead.

Must give one explicit rating:

- **APPROVE**: Pass 1 is clear, all blocking DELEGATE-FIX findings assigned to this PR are resolved, external review is `clear` or `not_applicable` (a `pending` routed as `clear` by a completed, current-head substitution counts), and only recorded non-blocking Pass 2 findings remain
  → re-run `.dev.json` pre-write verification (`${CLAUDE_SKILL_DIR}/phases/repository-context.md`) against `github.pullRequestRepository` immediately before merging, then `rtk gh pr merge --repo github.com/<that repository> --squash`; immediately re-run the Issue operation check before closing the corresponding Issue, using its own qualified `(repository, number)` identity — `Closes OWNER/REPO#N` when it differs from the PR's repository — and verify the actual closure rather than assuming the merge did it

- **REQUEST CHANGES**: any Pass 1 failure, confirmed Scope Drift, or unresolved ASK item
  → list each issue and expected fix in comments
  → re-dispatch Worker Agent to make changes
  → count the batch and apply **Bounded remediation** below before dispatching it
  → **after fixes, run Phase 3.5 (QA) + Phase 4 (Review) using Review after fixes below**

- **COMMENT**: questions that don't block the merge (decide after user confirmation)

---

## Review after fixes

Every push invalidates approval for the previous head, not the historical record.
Both QA and internal review must issue fresh results for the new head:

1. Pin the current `headRefOid` and each lane's last reviewed base. Read the full
   diff between them, including intervening commits, and reconcile every known
   finding. A push alone does not resolve or supersede a finding. If there is no
   usable prior review/base, perform the full review.
2. For a bounded correction within the agreed scope, focus internal QA and review
   on changed behavior, affected callers/invariants, and regression evidence.
   Reopen the full review if scope, interfaces, architecture, a safety boundary,
   or material dependencies changed, or if the affected scope is uncertain.
3. Obtain the full required Verification Gate result at the final head from each
   check's recorded executor: CI evidence for the checks CI owns (a result from an
   earlier head is stale), the designated executor's run for any other. Keep QA and
   reviewer identities distinct from implementation and each other, with a clean
   checkout and an unchanged head during each turn.
4. Each lane's fresh report names its reviewed base, target head, review scope,
   executed checks and remaining findings. Prior reports may inform analysis but
   cannot stand in for current test results or approval.
5. Re-run the external-review inspector and verify the head immediately before the
   final rating. Internal delta review does not satisfy external review.
   Current-head evidence and explicit bypass rules in
   `${CLAUDE_SKILL_DIR}/phases/external-review.md` still apply.

Record base/target, review scope and outcome in the existing timestamped recovery
entries in `.agent/dev-state.md`. Complete the correction review when these
steps pass; do not reopen unrelated settled analysis without new evidence.

## Bounded remediation

Every fix batch is counted on a defect episode, so a remediation loop is bounded and the bound cannot be reset by a new head, a worker swap, a lead handoff or a related PR. The fields are in the **Defect episode record schema** in `${CLAUDE_SKILL_DIR}/templates/DEV_STATE_TEMPLATE.md`.

1. **Open or reuse the episode.** An episode is one underlying defect or finding family. Before the first fix batch, the lead opens an entry in `defect_episodes[]` and sets `defect_episode_ref` on the PR. A related PR for the same episode carries the same `defect_episode_ref` and continues the episode's count. An unrelated defect opens a new episode.
2. **Count the batch.** The lead increments `fix_batches` in the same ledger write that records the dispatch. Provider retry budgets stay separate: `consecutive_rate_limits` is never counted as a fix batch.
3. **Batches 1 and 2 are automatic.** Consolidate findings from CI, review and acceptance and dispatch them together, as above. Only material findings drive a fix batch. Advisory findings go to the debt log and never produce a batch, an automatic Issue or a PR.
4. **Batch 3 needs a diagnosis.** Batch 3 requested without a diagnosis entry → dispatch refused by this SOP. A fix batch beyond the episode's bound is refused until a diagnosis entry covers it, and no worker is dispatched. Before it, the lead appends an entry to the episode's `diagnoses` and a timestamped recovery entry in `.agent/dev-state.md` that record what failed, whether the fix is narrowed, whether a targeted specialist is dispatched, and whether a bounded extension is authorized.
5. **A diagnosis authorizes only what it names.** A diagnosis authorizes only the named additional batch count, never unlimited rounds. The episode's limit is `bound` plus the sum of `authorized_additional_batches`; reaching it again needs a new diagnosis. Consequential intent, authority or risk decisions go to the owner and are recorded as `owner_decision`.
6. **A cap never clears a blocker.** A cap never clears a blocker and never escalates by itself. When the limit is reached with a blocker open, the blocker stays open, the PR stays unmerged under REQUEST CHANGES, and the lead's next action is the diagnosis.

## Merge Order

Merge in dependency order: infrastructure Issue PRs merge first; dependent PRs wait until prerequisites are merged.

Update `PROJECT_CONTEXT.md` after all PRs are merged through a docs-only worktree/PR (completed features list, current status).

---

## Post-Merge: Affected PR Coordination (mandatory after every merge)

After a PR is merged into main, immediately, all scoped to the confirmed `github.pullRequestRepository` (per `${CLAUDE_SKILL_DIR}/phases/repository-context.md`; verify before this scan and re-run the operation check immediately before each subsequent mutation; never reuse the merge's check):

1. `rtk gh pr list --repo github.com/<confirmed pullRequestRepository> --state open --json number,title,headRefName,updatedAt --jq '.[] | "#\(.number) \(.headRefName) — \(.title)"'` — list open PRs compactly
2. Compare this merge's file list against each open PR's modified files (`rtk gh pr diff <PR-number> --repo github.com/<confirmed pullRequestRepository> --name-only`). Check one PR at a time; do not dump all diffs into the conversation.
3. Open PRs with file overlap → immediately re-run `rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/resolve_repository.py" --repo-dir "<selected-worktree>" --operation pr --target <confirmed pullRequestRepository>` and require exit 0, then comment (`rtk gh pr comment <PR-number> --repo github.com/<confirmed pullRequestRepository> ...`): `This PR overlaps files with the just-merged #N. Please rebase: rtk git fetch origin && rtk proxy git rebase origin/main`
4. Open PRs with logical dependencies (e.g. this refactor changed module paths or interface signatures) → re-run the same check immediately before each notification and use the same explicit repository scope.

---

## Post-Merge Verification (unconditional)

Owner: the lead. Runs after every merge to `main`, for every PR, regardless of
how clean pre-merge review looked. This is not a merge gate: it never blocks
delivery, and its only outputs are a `.agent/dev-state.md` ledger entry or a
reopened Issue. Pre-merge review answers whether the PR looked right; this
step answers whether what actually landed on `main` is right, and whether the
Issue it closed is actually done — a question five clean pre-merge lanes can
each answer "yes" to individually while it stays unasked.

1. **Verify the merged tree.** Compare the merge commit's tree hash against
   the tree hash of the **actual tested subject** recorded in `ci_runs[]` —
   not the PR head's tree, which CI did not test: `rtk proxy git -C
   "<selected-worktree>" rev-parse <merge-sha>^{tree}` against the recorded
   `tested_subject.sha^{tree}`. Under the default pull-request checkout the
   tested subject is GitHub's temporary merge commit (`kind: merge_ref`); fetch
   it if it is not already local. A tested subject that was never recorded or
   cannot be fetched counts as unequal.
   - Equal → the Verification Gate result already on record for that tested
     subject applies verbatim to `main`; record that equivalence rather than
     re-running the gate.
   - Unequal (the base advanced after the run, a squash that picked up late
     changes, a non-fast-forward merge commit, or any other divergence) →
     obtain the full recorded Verification Gate result for `main` at the merge
     commit: the `push` run of the Verification Gate workflow on `main` is CI's
     evidence for it, read by run id once it has completed; if no applicable
     run exists, the one-executor fallback rules above apply.
     A scoped recheck never replaces the full gate here.
2. **Re-check the closed Issue's acceptance criteria against the merged
   code.** Read each criterion and confirm it against what actually shipped
   on `main`, not against the PR description or the review that preceded
   merge. Confirm every criterion, or reopen the Issue naming the specific
   unmet items.

   **Auto-closure by a merge keyword is never evidence of completion.**
   GitHub closing an Issue because a merged PR said `Closes #N` records that
   a merge happened, not that the criteria were met.
3. **Record the result.** Append `merge_sha`, `tested_subject`, `gate_result`, and
   `criteria_verdict` (with the reopen list when unmet) to the post-merge
   verification record in `.agent/dev-state.md`, per the schema in
   `${CLAUDE_SKILL_DIR}/templates/DEV_STATE_TEMPLATE.md`.
4. **If the merge used the external-review bypass**, this record inherits
   that bypass's debt rather than restating it: cross-reference the recorded
   `review_debt` entry and the commit-range rule in
   `${CLAUDE_SKILL_DIR}/phases/external-review.md` instead of naming the
   range again here.
5. **Lane close-out (unconditional).** Once the post-merge verification
   record is appended, retire the lane's resources in the same turn so a
   later lead always finds an empty shelf. The inventory recorded under
   `${CLAUDE_SKILL_DIR}/templates/DEV_STATE_TEMPLATE.md` `inventory` (one
   row per agent, worktree, read-only review checkout, and background shell
   the lead created) is the scope: cleanup acts on those rows, never on
   anything off the inventory. Concretely, in this turn and without asking:
   - Archive the lane's worker, QA, and reviewer agents via
     `rtk proxy python3 ${CLAUDE_SKILL_DIR}/scripts/traycer_cli.py agent archive --id <id>`. Archiving is
     reversible: a later message unarchives and wakes the same transcript
     and checklist context, so a re-review needs no new agent.
   - Stop any background shells the lane owns whose work is done (the
     `shells` inventory rows whose `state` is `running`).
   - Remove the lead-created detached review checkouts whose `git status`
     shows a clean worktree (no staged or unstaged changes, no untracked
     paths the lane touched). The path is the `worktree-path` already in
     the inventory row; removal runs in the same turn as the archive, not
     later.
   - **Mark the lane's worktree landed-eligible** in its inventory row by
     flipping `state` to `landed-eligible` (the gauge records this in
     `counts.worktrees.landed_eligible`). Deleting the worktree is still
     the user-approved consolidation batch's job — a single approval per
     review-tier row, never the lead's — so the lane worktree stays on
     disk and the lead's only write here is the inventory row's state.
   Agents the lead did not spawn stay out of this step: they appear in
   the cleanup line under `Not mine` and are never stopped or archived
   by the lead. A lane that has not yet merged is not a candidate here;
   its inventory rows keep their pre-merge state until the merge lands
   and the post-merge check has been recorded.
6. **Quote the gauge and write the cleanup line.** Run
   `python3 ${CLAUDE_SKILL_DIR}/scripts/workspace_debt.py` from the lane
   worktree, read the `counts.worktrees.landed_eligible` and
   `counts.agents.active_not_mine` fields, and emit the fixed-shape
   `Cleanup:` line described in § 7 of `${CLAUDE_SKILL_DIR}/reply-contract.md`.
   The script reports `status: unavailable` and `counts: null` when the
   CLI is broken or scoped out; never quote a zero from a null report.
