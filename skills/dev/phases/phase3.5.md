# Phase 3.5 — QA Verification

---

## Quantitative Trigger

Run QA when any condition is true; otherwise record why QA was skipped and continue to Phase 4:

| Condition | QA required |
|---|---|
| Added or modified diff lines ≥ 50 | Yes |
| Modified files ≥ 3 | Yes |
| New external interface, API endpoint, or public function signature | Yes |
| Database schema change | Yes |
| Authentication or authorization logic | Yes |

Use compact diff statistics first. Do not substitute subjective judgment for these thresholds. The Tech Lead may also require QA for lower-volume but high-risk changes.

## Prepare the QA Lane

Use the absolute worktree path recorded for this PR as `<selected-worktree>` in checks below; do not infer it from the ambient directory. Run local Git operations and validation in that same worktree (explicit cwd or `rtk proxy git -C "<selected-worktree>" ...`). Keep GitHub commands scoped to the confirmed host and repository.

1. Resolve the PR's operation target first (`rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/resolve_repository.py" --repo-dir "<selected-worktree>" --operation pr --target <github.pullRequestRepository>` per `${CLAUDE_SKILL_DIR}/phases/repository-context.md`), then resolve the exact PR head branch and commit with `rtk gh pr view [N] --repo github.com/<that confirmed repository> --json headRefName,headRefOid --jq '{branch: .headRefName, head: .headRefOid}'`.
2. Record PR number, Issue number, head branch, `headRefOid`, and target commit in `.agent/dev-state.md`.
3. Read `${CLAUDE_SKILL_DIR}/phases/external-review.md`, resolve the repository policy, start its review deadline, and record expected/requested/observed reviewers. Do not wait here; continue QA while external review proceeds.
4. Load `${CLAUDE_SKILL_DIR}/agents/qa-agent.md` and fill every placeholder before dispatch.
5. Resolve and launch one distinct read-only QA identity through the selected adapter. Record its agent ID and route. Do not give QA implementation ownership.
6. Record `rtk proxy git -C "<selected-worktree>" status --short`, local `HEAD` (`rtk proxy git -C "<selected-worktree>" rev-parse HEAD`), and the PR `headRefOid` before and after the lane. Any tracked QA change, or either head differing from the recorded target commit, fails the lane and makes the adapter result incomplete.

The Tech Lead resolves the branch before dispatch; the QA agent must not guess it.

## Result Handling

### QA passes

Require a PR comment whose report lists an explicit outcome (`pass | fail | inconclusive | not_applicable`) for every acceptance criterion and every Verification Gate check, with its evaluator type, executor, evidence reference and reason, and the close-out `QA ✓ Pass — outcomes: [n] pass, 0 fail, 0 inconclusive, [n] not_applicable`. The lane passes only when every applicable criterion and required check is `pass` by its assigned evaluator and no material finding is unresolved. A required check or criterion is never `not_applicable`. A health score line is an optional diagnostic: its absence is valid, and it never decides the result. Continue to Phase 4.

### QA fails

1. Read the QA report and turn each `fail` outcome and each unresolved material finding into explicit fix instructions. Turn each `inconclusive` outcome into a request for the missing evidence or evaluator it names (CI evidence, infrastructure, an independent reviewer or a human); an `inconclusive` outcome is never read as a pass, and never fixed by relabeling it `not_applicable`.
2. Count the fix batch on its defect episode before dispatching it, following **Bounded remediation** in `${CLAUDE_SKILL_DIR}/phases/phase4.md`. Batch 3 requested without a diagnosis entry → dispatch refused by this SOP, and a QA failure never clears a blocker by hitting the cap. Only unresolved material findings and `fail` outcomes drive a batch; a request for missing evidence that changes no code is not a fix batch.
3. Re-dispatch a fix worker in the existing coding worktree when safe, or create and verify a replacement worktree when recovery is required.
4. Never rely on an `@mention` to reactivate a completed worker or QA session.
5. After fixes, reset completion to pending for the new head and run Phase 3.5 and Phase 4 using **Review after fixes** in `${CLAUDE_SKILL_DIR}/phases/phase4.md`. Retain old reports as historical evidence; bounded corrections may receive focused analysis with fresh final-head checks and reports.

Treat each QA turn as a read-only lane: it requires an unchanged checkout and an unchanged PR head and must leave zero tracked changes. QA reports evidence; it does not approve, merge, or modify code. A QA agent ID must differ from the implementation worker ID and the reviewer agent ID. A new push invalidates its approval for the new head; historical context may be reused in a fresh correction review.
