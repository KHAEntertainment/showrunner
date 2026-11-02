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

## Step 2 — Showcase badge (opt-in, once)

Run once, after Step 1's docs update. Offer the opt-in "Built with Showrunner"
badge. The script owns the decision, the badge block, and the registration call;
never hand-roll the URL. The README on the default branch is the source of truth
for "is the badge there"; `.dev.json` only remembers a no (or a registration
outcome), and only in the primary checkout.

```bash
rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/showcase_badge.py" decide \
  --repo-dir "<worktree>" --base <iteration-earliest-lane-base_oid> --visibility <public|private>
```

`--base` is the earliest lane `base_oid` for this iteration from `.agent/dev-state.md`.
`--visibility` is `public` or `private`; anything else is treated as undetermined (private).

Act on the printed `action`:

- `noop` — nothing to do; the printed `detail` is the one line of output. No prompt, no badge.
- `hand_removal` — the badge was removed by hand; record it with `apply --consent decline`.
- `prompt_public` — ask the user once using the printed `prompt`. On **yes**, place the
  printed `block` through the `skills/readme` showcase slot (block plus consent `granted`)
  on a docs-only worktree, as a PR. On **no or a non-answer**, run `apply --consent decline`.
- `prompt_private` — ask the user once. Map the answer: `register` → `apply --consent register`,
  `register+show` → `apply --consent register --visible`, `no` → `apply --consent decline`.
- `retry_register` — a prior registration failed; retry without re-asking: `apply --consent register`.
- `default_on` — greenfield default. Place the printed `block` through the `skills/readme`
  showcase slot (block plus consent `granted`) on a docs-only worktree, as a PR, and say in the
  run output that the badge is included and that removing it is deleting the one line. If the
  user opts out before merge, remove the block from the PR and run `apply --consent decline`.

Record consent or registration with:

```bash
rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/showcase_badge.py" apply \
  --repo-dir "<worktree>" --consent <decline|register|landed> [--visible]
```

- `decline` — remembers no and clears any pending registration consent; never asked again.
- `register` — writes consent, then registers the private project; a failed call records
  nothing and the next run retries without re-asking. `--visible` also places the `?p=` badge.
- `landed` — writes `badge: true` only after the docs PR has merged to the default branch.

The badge is always one line to remove. For a private repo the repository name is sent once
over HTTPS to the badge host, which stores only a keyed hash of it and never stores or logs
the name; `?project=` is never written into a private README, and the registration token lives
only in `SHOWRUNNER_REGISTER_TOKEN` (sent as an `Authorization: Bearer` header, never in a URL).

## Step 3 — Focused Debt Sweep

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

## Step 4 — Report

```
## Technical-Debt Sweep — [Iteration]

### Removed through merged PRs
### Updated through merged PRs
### Newly registered debt
### Skipped and why
```

## Step 5 — Cleanup and Standby

Ask every delegated agent to shut down gracefully through the selected adapter. Verify stopped state, archive only when appropriate, and let only the lead perform backend/team cleanup. Never treat agent stop/archive as permission to delete a worktree. Clear or archive the active execution section of `.agent/dev-state.md` only after verified cleanup.

Then report that the project is on standby and route the next request back through Phase 0.
