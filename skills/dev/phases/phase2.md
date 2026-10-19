# Phase 2 — Technical Breakdown & Project Initialization

---

## Command Output Rules

- Use `rtk gh ...` for every GitHub CLI operation in this phase.
- Use `rtk git ...` or `rtk proxy git ...` for every git operation in this phase.
- Broad GitHub scans must use `--json` with summary fields and `--jq` one-line output. Do not request PR/Issue bodies, commits, comments, files, or reviews during broad scans.
- Deep-read a full Issue/PR body only for the specific item being created, revised, or implemented.

---

## Architecture Decision Checkpoint (run for all modes, before task decomposition)

Before decomposing tasks, the following architecture decisions must be confirmed and recorded in `PROJECT_CONTEXT.md`.
**Do not proceed to task decomposition until all decisions are complete.**

For each decision: follow the user's preference if stated; **if the user has no preference, Tech Lead gives a recommendation with reasoning, adopts it, and continues — do not block the flow.**

```
Architecture Decision Checklist:
□ Auth scheme: [JWT / Session / None] + token storage method
□ API design spec: [endpoint naming convention / unified error format / pagination structure]
□ Database schema: [core tables and fields (draft level)]
□ Database migration: [is there existing data? Yes → must specify a migration framework (Python: Alembic / Node: Knex / Java: Flyway)]
□ Full-stack project: does it need an API Contract document? (OpenAPI / endpoint list)
□ Code style conventions: [naming rules / directory structure conventions]

Confirm all decisions with the user before proceeding to task decomposition.
```

**Update PROJECT_CONTEXT.md immediately after architecture decisions are confirmed — do not wait for Phase 5.**

---

## Full Mode (New Project / New Feature)

### For Architectural Changes: Run Change Impact Assessment First

When requirements conflict with existing architecture decisions in PROJECT_CONTEXT.md (e.g. replacing the auth system, rewriting a core module), **before task decomposition** you must:

1. Verify the PR target with `rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/resolve_repository.py" --repo-dir "<selected-worktree>" --operation pr --target <pullRequestRepository>`; then list affected merged PRs with a compact summary scan, e.g. `rtk gh pr list --repo github.com/<pullRequestRepository> --state merged --limit 20 --json number,title,mergedAt,headRefName --jq '.[] | "#\(.number) \(.headRefName) — \(.title)"'`, then deep-read only the likely affected PRs
2. **When Graft is available per `${CLAUDE_SKILL_DIR}/graft.md`, produce dependents/impact evidence from `rtk proxy graft callers <symbol> -d all --json` + freshness for full blast radius; else record `graph_evidence: unavailable` + cause and trace dependents manually with `rg`/`git grep`.**
3. **Record the change-impact assessment gate in `.agent/dev-state.md` with a Tech Lead ledger entry containing the required Graft evidence fields (`graft_version`, `graph_evidence`, `graph_evidence_cause`) so Phase 5 can aggregate causes across all gates including this one.**
4. Immediately before each creation, run `rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/resolve_repository.py" --repo-dir "<selected-worktree>" --operation issue --target <pushRepository>` and require exit 0; create it with `rtk gh issue create --repo github.com/<pushRepository>`. Create a fix Issue for each affected merged PR (label: `[Arch Change] Fix code affected by PR #N`)
4. Read open Issues with `rtk gh issue list --repo github.com/<pushRepository>`. Immediately before each close, edit, or comment, re-run the Issue operation check for that Issue's qualified repository; use `rtk gh issue close`, `edit`, or `comment` with `--repo github.com/<that repository>` and require the check to exit 0. If that repository differs from `pushRepository`, use `--allow-target-override` only for an explicitly assigned existing upstream Issue.
5. Immediately update the architecture decisions section of PROJECT_CONTEXT.md (do not wait for Phase 5)

### Execution Steps

1. Based on confirmed architecture decisions, decompose requirements into independent, parallelizable development tasks:
   - Completable by a single Agent independently
   - Has clear inputs, outputs, and completion criteria
   - Dependencies on other tasks are clear
   - **Identify cross-task shared infrastructure** (DB connection layer, auth middleware, shared utils, API client wrappers) — create a separate Issue for each, marking them as prerequisites for other tasks

2. **For new projects**, establish a real default branch before creating worktrees:

   1. Before creating, verify the CLI account: `rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/resolve_repository.py" --repo-dir "<selected-project-root>" --mode check-gh-account --account <confirmed github.account>`. Create and clone the repository using the full confirmed identity, never a bare project name: `GH_HOST=github.com rtk gh repo create <github.pushRepository> --private --add-readme --clone`. This establishes `main` without a direct lead-session push.
   2. Enter the clone and verify readiness with `rtk git status --short`, `rtk git branch --show-current`, and `rtk git rev-parse HEAD`. Require `main`, a real commit, and a clean tree.
   3. If Phase 0's setup produced a confirmed `.dev.json` at a pre-Git project root, move it into this clone now and re-run its pre-write verification (`${CLAUDE_SKILL_DIR}/phases/repository-context.md`) before any further write — the actual remote/repository/Git identity must now be confirmed, not just the earlier intent. If no confirmed config exists yet, run first-invocation setup here before continuing. When the pre-Git `dev_config.py create` ran with `--no-exclude`, re-run `rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/dev_config.py" exclude` immediately after this `git init` so the file is covered by the repository-local exclude file before any project files are staged; `dev_config.py status` must report `valid`, not `not_ignored`.
   4. Create a docs-only bootstrap branch/worktree. In that worktree, create `PROJECT_CONTEXT.md` from `${CLAUDE_SKILL_DIR}/templates/PROJECT_CONTEXT_TEMPLATE.md`; add `API_CONTRACT.md` when required; submit and merge the bootstrap PR before implementation work starts.
   5. Immediately before each Issue or milestone mutation, require exit 0 from `rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/resolve_repository.py" --repo-dir "<selected-worktree>" --operation issue --target <github.pushRepository>`; use `--repo github.com/<github.pushRepository>` for Issue commands and `gh api --hostname github.com repos/<github.pushRepository>/milestones` for milestones. Create Issue #1 containing the frozen PRD (title: `[PRD] Product Requirements Document`), scoped to `github.pushRepository` from `.dev.json` — plugin-created task Issues default to the push repository, not the PR destination.
   6. Create one Issue per development task using the template below, scoped the same way, then create a milestone linking all Issues.

   Do not create coding worktrees until the bootstrap PR is merged and `origin/main` contains the project context.

3. **For existing projects**:
   - Read `PROJECT_CONTEXT.md` to restore context
   - Create Issues for new requirements (use the Issue template below), explicitly scoped to `github.pushRepository` per `${CLAUDE_SKILL_DIR}/phases/repository-context.md` (`rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/resolve_repository.py" --repo-dir "<selected-worktree>" --operation issue --target <github.pushRepository>`, then `rtk gh issue create --repo github.com/<that repository>`)
   - Immediately before updating the milestone, re-run the Issue operation check and use `gh api --hostname github.com repos/<github.pushRepository>/milestones/<number>`

4. Present the task list for user confirmation using the explicit dependency format:
   ```
   Task List (N total):

   [Infrastructure Layer — must complete first, other tasks depend on it]
   □ Issue #1 [Infrastructure task] — output: xxx — blocks: #3, #4, #5

   [Parallel Development Layer]
   □ Issue #3 [Feature A] — output: xxx — depends on: #1 — can parallel with #4
   □ Issue #4 [Feature B] — output: xxx — depends on: #1 — can parallel with #3

   [Closing Layer — after all features complete]
   □ Issue #6 [Integration] — depends on: #3, #4, #5
   ```

5. **Enter Phase 3 after user confirms priorities/order**

---

## Express Mode (Emergency Hotfix)

**Skip the architecture decision checkpoint. Skip QA (Phase 3.5).**

1. Immediately before creating, require exit 0 from `rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/resolve_repository.py" --repo-dir "<selected-worktree>" --operation issue --target <github.pushRepository>`, then `rtk gh issue create --repo github.com/<github.pushRepository>`. Create one Hotfix Issue directly, scoped to `github.pushRepository` per `${CLAUDE_SKILL_DIR}/phases/repository-context.md`, title format: `[Hotfix] [incident description]`
2. Acceptance criteria only needs to cover: incident reproduction path + fix verification
3. Present the Issue to the user for confirmation, then **immediately enter Phase 3 (single Agent, using `worker-fix.md`)**
4. After PR is merged, **must run the affected PR coordination step** (see Phase 4 merge section)

---

## Lightweight Mode (Small Change / Bug Fix)

1. Immediately before creating, require exit 0 from `rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/resolve_repository.py" --repo-dir "<selected-worktree>" --operation issue --target <github.pushRepository>`, then `rtk gh issue create --repo github.com/<github.pushRepository>`. Create one Issue directly (use the Issue template below), scoped to `github.pushRepository` per `${CLAUDE_SKILL_DIR}/phases/repository-context.md`
2. No task decomposition or milestone needed
3. Present the Issue to the user for confirmation, then **immediately enter Phase 3 (single Agent)**

---

## Refactoring Mode

Refactoring tasks must satisfy:
1. Issue acceptance criteria use the **dual-dimension format**:
   - Structural metric: `[file/module] lines/dependencies/complexity → target value` (e.g. `utils.py lines → no more than 200`)
   - Regression metric: `full test pass rate → 100%, no new lint errors`
2. Refactoring Issues **must be placed in the Infrastructure Layer**; all feature Issues that depend on the refactored module are marked as depending on it, **must not be parallelized**; feature Issues that do NOT depend on the refactored module may run in parallel
3. Worker Agent uses `worker-fix.md`; self-check must focus on: no breaking changes to any existing callers

---

## Issue Template

```markdown
## Task Description
[Background and goal]

## Acceptance Criteria (engineering-verifiable format)
Each criterion must follow: [trigger condition] → [expected response/state/side effect]
Example: POST /auth/register with existing email → returns 409, body contains error_code

- [ ] [trigger 1] → [expected result 1]
- [ ] [trigger 2] → [expected result 2]
- [ ] [edge case: empty input / extreme value] → [expected result]
- [ ] [if test framework exists: all tests pass, no regression]

## Architecture Constraint Reference
[Reference relevant decisions from PROJECT_CONTEXT.md or API_CONTRACT.md]

## Technical Notes
[Key implementation constraints or considerations]

## Out of Scope
[Explicit exclusions to prevent scope creep]
```
