# Phase 3.5 — QA Verification

---

## Risk Tiers

This section is the single statement of the rule that decides whether Phase 3.5 runs. The Phase 0 router in `SKILL.md` mirrors only the last column, and `scripts/validate_skill.py` fails when the two disagree. No size threshold (changed lines, file count, interface or schema change) decides anything: a tier floor is a property of the paths and kinds of file the diff touches.

| Tier | Floor | Lane set | Phase 3.5 |
|---|---|---|---|
| T0 nonbehavioral | The diff touches no executable file and nothing under the project's declared behavior paths | CI + lead review; no reviewer lane, no acceptance lane | skip |
| T1 ordinary | Default: any diff that matches no higher floor and is not T0 | CI + one qualified independent review + post-merge verification; acceptance lane only if a declared acceptance check applies | run |
| T2 elevated | The plan-approval list in `${CLAUDE_SKILL_DIR}/phases/phase3.md` (architecture, databases, auth, shared interfaces, migrations, broad refactors), or any path the project declares as a T2 path | Current T2 protections, unchanged | run |
| T3 critical | `resolve_repository.py` (repository and push/PR target resolution), destructive migrations, review-gate policy, release and tag paths, secrets, or any path the project declares as a T3 path | Full current cycle; only the owner lowers a T3 floor, never the lead | run |

Rules:

- The tier is the highest floor the diff matches, computed from the diff's file list (`rtk gh pr diff <PR> --name-only` or `rtk proxy git diff --name-only`). Record the tier, the matching floor and the evidence (the paths) in `.agent/dev-state.md` before deciding whether Phase 3.5 runs.
- An executable file is any file the project runs, installs or builds from: source code, scripts, installers, CI workflow definitions, and package or build manifests. Declared behavior paths are paths the project names in `PROJECT_CONTEXT.md` **Risk Tiers** (see `${CLAUDE_SKILL_DIR}/templates/PROJECT_CONTEXT_TEMPLATE.md`); a project that declares none has only executable files as its behavior surface.
- The rule applies to every router path, Emergency Hotfix included. There is no per-path exemption.
- Discovery raises the tier. A raised tier adds its checks to the same PR; evidenced work is not restarted.
- Lowering a floor is an owner decision recorded in `PROJECT_CONTEXT.md`. The lead never lowers a floor, and never reads an undeclared path as T0 to save a lane.
- During the T1 pilot the T1 lane set above is the target and is implemented separately. Until it lands, T1 keeps the current lanes (this Phase, then the Phase 4 review), and T2 and T3 keep their current protections unchanged.

When the tier is T0, record why Phase 3.5 was skipped (the tier and the paths that placed it there) and continue to Phase 4. The Tech Lead may raise a tier for a change whose risk the floors do not capture; the lead may not lower one.

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
2. Re-dispatch a fix worker in the existing coding worktree when safe, or create and verify a replacement worktree when recovery is required.
3. Never rely on an `@mention` to reactivate a completed worker or QA session.
4. After fixes, reset completion to pending for the new head and run Phase 3.5 and Phase 4 using **Review after fixes** in `${CLAUDE_SKILL_DIR}/phases/phase4.md`. Retain old reports as historical evidence; bounded corrections may receive focused analysis with fresh final-head checks and reports.

Treat each QA turn as a read-only lane: it requires an unchanged checkout and an unchanged PR head and must leave zero tracked changes. QA reports evidence; it does not approve, merge, or modify code. A QA agent ID must differ from the implementation worker ID and the reviewer agent ID. A new push invalidates its approval for the new head; historical context may be reused in a fresh correction review.
