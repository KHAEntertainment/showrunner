# PROJECT_CONTEXT.md — Index File

> This is the master index — it only routes, it does not pile up content.
> Detailed content is spread across sub-documents in `docs/`, each kept to 100–200 lines.
> The `/dev` skill reads this file at every Phase to restore context.

---

## Repository Info

- **Repo URL**: https://github.com/[owner]/[repo]
- **Main branch**: main
- **Created**: YYYY-MM-DD

---

## Sub-document Index

| File | Content | Update timing |
|------|---------|---------------|
| `docs/glossary.md` | Canonical domain terminology table (with avoid words) | Append item by item during Phase 1 word-precision pass; correct in later Phases when term drift is detected |
| `docs/tech-stack.md` | Language, framework, database, test framework, dependency versions | When tech choices change |
| `docs/architecture.md` | Architecture Decision Records (ADRs), auth scheme, API conventions, migration plan | Update immediately when an architecture decision is made |
| `docs/api-contracts.md` | Endpoint list, request/response formats, error codes (for frontend-backend split projects) | When endpoints are added/modified |
| `docs/style-guide.md` | Naming conventions, directory structure, error handling conventions, comment conventions | When conventions change |
| `docs/feature-log.md` | List of completed features (PR number, merge date) | Update every Phase 5 round |

---

## Current Status (the only part of this file that needs frequent updates)

- **Last updated**: YYYY-MM-DD
- **Current iteration goal**: [description of features to complete this round]
- **Open PRs**: #N [description], #M [description]
- **Known tech debt**: see the bottom of `docs/feature-log.md`

---

## Risk Tiers (optional)

Omit this section to use the floors in `${CLAUDE_SKILL_DIR}/phases/phase3.5.md` as written: only executable files make a diff behavioral, and the T2 and T3 floors are the defaults named there. Declare paths only where the project's behavior lives somewhere an executable-file test would miss (for example, a project whose behavior is its prompt or SOP files), or where it needs a stricter floor.

- **Behavior paths**: none (a diff touching nothing here and no executable file is T0)
- **T2 paths**: none (added to the plan-approval-list floor)
- **T3 paths**: none (added to the critical-path floor)

A declared path raises a tier; it never lowers one. Lowering a floor is an owner decision: record the owner's change here with its date, and the lead applies it only from this record.

---

## Execution Routing Policy (optional)

Omit this section to use the selected backend's lead route. Configure only roles that need an override.

```yaml
implementation:
  harness: codex
  model: gpt-5
  profile: null
  reasoning_effort: high
  permission_mode: full_access
fix: {}
prototype: {}
qa:
  harness: codex
  permission_mode: supervised
review:
  harness: codex
  permission_mode: supervised
```

Route precedence is explicit project role → workspace `.traycer/agent-selection-guide.md` → Traycer global selection guide → lead route. `/dev` validates harness, model, profile, reasoning effort, and permission mode before launch. When lead fallback omits a profile, Traycer intentionally uses `last_used`; record `traycer_last_used` in `.agent/dev-state.md`.

Do not configure a fictional read-only permission mode. QA/review are read-only SOP roles and must prove they leave no tracked changes. V1 does not route by cost, rate limits, or performance guesses.

---

## External Review Policy (optional)

Omit this section to use the `/dev` defaults shown below.

- **Mode**: auto
- **Trusted reviewers**: coderabbit, kilo, github-copilot, gemini-code-assist, greptile, sourcery, qodo
- **Required reviewers**: none
- **Ignored reviewers**: none
- **Additional reviewer identities**: none
- **Pending reviewer decisions**: none
- **Default wait minutes**: 10
- **Allow automatic review requests**: false

Required reviewers: a T1 PR needs one qualified independent review source by default, either a named external provider or, when none is listed, the internal reviewer; the `Required reviewers` line lists a provider only when the project wants that provider to gate every PR. List more than one only when project policy requires it (an existing requirement, a platform requirement, or distinct justified expertise); the policy is valid with several entries, each must be trusted and have an identity mapping, and each is tracked to completion at the current head. See **Qualified review for T1** in `${CLAUDE_SKILL_DIR}/phases/external-review.md`.

`Ignored reviewers` takes precedence over every other setting. Additional identities use `reviewer=login` or `reviewer=login,check-app-slug`. Automatic review requests can consume reviewer credits; enable them per reviewer only when intentionally desired. The `Pending reviewer decisions` line records unknown bots the user has chosen to decide later (login + date); the lead does not re-ask a login already listed there, and the inspector continues to surface it as evidence until the user revisits the decision.

---

## Verification Gate (optional)

Record the exact lint / type-check / static-analysis / dependency-scan / test
commands for this project so the worker, QA, and reviewer all run the same
gate. Omit this section to fall back to the language defaults in
`${CLAUDE_SKILL_DIR}/phases/phase4.md`.

- **Lint**: [command]
- **Type check**: [command, or `n/a`]
- **Static analysis**: [command, or `n/a`]
- **Dependency scan**: [command] (mandatory — Python `pip-audit` / Node `npm audit`)
- **Tests**: [command]

## Acceptance Checks (optional)

List the project's acceptance checks: the checks that exercise a delivered
behavior end to end rather than a gate command. Each entry becomes a `checks`
entry on the PR record in `${CLAUDE_SKILL_DIR}/templates/DEV_STATE_TEMPLATE.md`,
so name its id, its definition and the executor that runs it once. Omit this
section when the project declares none.

- **[id, e.g. `acceptance:e2e-verify`]**: definition [command or script, e.g. `ops/e2e.sh verify`] · executor [`ci` / `qa` / `worker`] · environment [e.g. `preview-vps`] · real or mocked [`real` / `mocked`, with what is mocked]

---

## .gitignore Guidance at Init

Prototype artifacts produced during Phase 1 do not enter git by default. Add to `.gitignore`:
```
prototypes/
PRD-draft.md
```

`PRD-draft.md` is the draft used while Phase 1 is in progress; it is renamed to `PRD.md` only after the Step D freeze, and only then enters git. The user can selectively `git add` individual high-value prototypes from `prototypes/`.

---

## Sub-document Templates

When initializing a new project, create the following files under the `docs/` directory:

**`docs/glossary.md`**
```markdown
# Glossary

> Canonical domain terminology locked during Phase 1 word-precision.
> The main conversation and all Phases must use the canonical terms; do not use the near-synonyms listed under _Avoid_.

## Terms

**<term>**: <one-line definition; describe "what it is," not "what it does">
_Avoid_: <replaced near-synonyms, comma separated>

**<term>**: <definition>
_Avoid_: <near-synonyms>

## Relations

- One <term A> is associated with multiple <term B>
- <term C> belongs to <term A>

## Flagged Ambiguities

- "<original wording>" was once used to refer to both <term X> and <term Y> — resolution: they are distinct concepts.
```



**`docs/tech-stack.md`**
```markdown
# Tech Stack

## Language & Runtime
- Python 3.11 / Node.js 20 / ...

## Framework
- FastAPI / Express / ...

## Database
- PostgreSQL / SQLite / ...

## Test Framework
- pytest / Jest / None

## Key Dependency Versions
- [package]: [version]
```

**`docs/architecture.md`**
```markdown
# Architecture Decisions

## Auth Scheme
- Scheme: JWT, stored in HttpOnly Cookie
- Decision time: YYYY-MM-DD, PR #N

## API Design Conventions
- Error format: `{"error_code": "...", "message": "..."}`
- Pagination: `?page=&size=`

## Database Migration
- Framework: Alembic (existing data) / None (brand new project)

## [Append new decisions in this format]
- Scheme: ...
- Decision time: ..., PR #N
- Background: ...
```

**`docs/style-guide.md`**
```markdown
# Style Guide

## Naming Conventions
- Python: snake_case for variables/functions, PascalCase for class names

## Directory Structure
src/
  routers/    # API routing layer
  services/   # Business logic layer
  models/     # Data models
  utils/      # Utility functions
tests/

## Error Handling Conventions
- Always raise HTTPException; no business logic in the routing layer
```

**`docs/feature-log.md`**
```markdown
# Feature Log

## Completed
- [feature name] (PR #N, merged YYYY-MM-DD)

## Known Tech Debt
- [description] (source: PR #N, recorded: YYYY-MM-DD)
```
