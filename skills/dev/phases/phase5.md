# Phase 5 — Retro & Technical-Debt Sweep

Trigger after all iteration PRs are merged. Complete the retro before the debt sweep; skip neither step.

---

## Step 1 — Retro

Produce:

```
## Retro — [Project] / [Iteration]
### Completed
### Known Issues
### Deferred
### Post-Merge Verification
### External-Review Bypasses
### Graft Evidence Availability
### Recommended Next Priorities
```

Report the count of external-review bypasses used this round under `External-Review Bypasses`, reported explicitly, including `0` when none occurred — so repeated bypass is visible as a pattern across rounds, not only per PR.

Under `External-Review Bypasses`, also report the count of rate-limit breakpoint substitutions this round (the `external_review_substitutions` entries in `.agent/dev-state.md`), again including `0` when none occurred. Keep it separate from the bypass count: a substitution is a completed review, not a bypass, and the count shows how often a reviewer's rate limits forced the breakpoint.

Under `Graft Evidence Availability`, report the count of gates run this round where `graph_evidence: unavailable` was recorded (from `.agent/dev-state.md` worker entries **and Phase 2 Tech Lead change-impact assessment gates**), broken down by cause (`not_installed`, `version_mismatch`, `build_failed`, `unparseable_output`, `query_failure`). Include `0` when none occurred.

Under `Post-Merge Verification`, list the post-merge verification records from `.agent/dev-state.md` for every PR merged this round (gate result and acceptance-criteria verdict) — read them, do not repeat the check itself; the procedure that produces them is `${CLAUDE_SKILL_DIR}/phases/phase4.md`'s unconditional post-merge step.

Update the current-status section of `PROJECT_CONTEXT.md` and the completed list in `docs/feature-log.md`. After repository initialization, make these tracked documentation changes in a docs-only worktree and PR; never push directly to main.

## Step 2 — Focused Debt Sweep

Limit the scan to directories changed in this iteration and their immediate callers/dependencies. Do not run an unbounded whole-repository sweep.

### Dead documentation

- Identify documents whose referenced feature or module no longer exists.
- Delete provably dead documents or update still-useful documents with `Last verified: YYYY-MM-DD`.
- When uncertain, record the item in the technical-debt section of `docs/feature-log.md`; do not present a guess as verified.
- Apply tracked document cleanup only through the docs-only worktree/PR path.

### Deprecated implementation

Inspect changed implementation files for:

```
□ Commented-out code blocks of at least three lines
□ Functions/classes with no callers after repository-wide reference verification
□ Fully resolved feature flags with constant branches
□ TODO/FIXME markers that are already resolved or need a follow-up Issue
```

The Tech Lead must not delete or edit implementation/test code. Immediately before creating a cleanup Issue, require exit 0 from `rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/resolve_repository.py" --repo-dir "<selected-worktree>" --operation issue --target <github.pushRepository>`, then use `rtk gh issue create --repo github.com/<github.pushRepository>`. Create a narrowly scoped cleanup Issue, explicitly scoped to `github.pushRepository` per `${CLAUDE_SKILL_DIR}/phases/repository-context.md`, prepare a verified worker worktree, and dispatch `worker-fix.md`. Require tests and a cleanup PR before merge.

### Known broken features outside the iteration

Register them in `docs/feature-log.md` using:

`[Description] (source: PR #N, recorded: YYYY-MM-DD, target: next iteration/TBD)`

Do not delete untested implementation outside the iteration scope.

## Step 3 — Report

```
## Technical-Debt Sweep — [Iteration]

### Removed through merged PRs
### Updated through merged PRs
### Newly registered debt
### Skipped and why
```

## Step 4 — Cleanup and Standby

Ask every delegated agent to shut down gracefully through the selected adapter. Verify stopped state, archive only when appropriate, and let only the lead perform backend/team cleanup. Never treat agent stop/archive as permission to delete a worktree. Clear or archive the active execution section of `.agent/dev-state.md` only after verified cleanup.

Then report that the project is on standby and route the next request back through Phase 0.
