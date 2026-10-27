# PROJECT_CONTEXT.md — SupaConsole (DRAFT for owner review)

> Draft only. It is not installed, and nothing reads it from this path. The owner
> copies it to `PROJECT_CONTEXT.md` at the root of `KHAEntertainment/SupaConsole`
> through a reviewed SupaConsole PR (owner step in [README.md](README.md)), after
> re-checking every bracketed or dated fact against SupaConsole `main`.
> Facts observed read-only on 2026-10-27.

## Repository Info

- **Repo URL**: https://github.com/KHAEntertainment/SupaConsole
- **Main branch**: `main`
- **Stack**: TypeScript, Next.js 15, Prisma, Vitest; Node.js 22 in CI
- **Created**: [owner fills in at adoption]

## Current Status

- **Last updated**: [owner fills in at adoption]
- **Current iteration goal**: [owner fills in at adoption: the T-series task backlog and the pilot task selection]
- **Open PRs**: see `gh pr list`
- **Known tech debt**: [owner fills in at adoption]

---

## Verification Gate

The commands of the CI `build` job (`.github/workflows/ci.yml`), in CI order after
`npm ci`. Replaces the language defaults in the Dev skill's `phases/phase4.md`.

- **Lint**: `npm run lint` (runs `eslint`)
- **Type check**: `npx tsc --noEmit`
- **Static analysis**: `npx prisma generate` (generates the Prisma client that the type check and tests need)
- **Dependency scan**: `n/a` — CI does not run one today. Recorded as `n/a` deliberately; reinstate `npm audit` only if the owner adds it to CI.
- **Tests**: `npm test` (runs `vitest run`)

**Check ownership.** One executor per check definition, tested subject and environment.

| Gate commands | Executor (owner) | Evidence consumers cite |
| --- | --- | --- |
| `npx prisma generate`, `npx tsc --noEmit`, `npm run lint`, `npm test` | PR CI: workflow `CI`, job `build` | run, job, attempt, and the tested subject (a PR checks out GitHub's temporary merge commit, not the PR head) |
| Focused checks for the change: the tests the diff touches | The worker | report-back commands and exit codes |

- `build` is the GitHub-required status check on `main` (strict, admin enforcement).
  It is never waived. A baseline failure is recorded, not excused.
- Worker, QA, reviewer and lead cite the `build` run instead of repeating the four
  commands. No mandatory worker pre-push gate exists in this policy.
- Local full-gate execution needs an approved fallback trigger and one designated
  executor, under the serial-run wrapper with host load recorded.

## Acceptance Checks

- **`acceptance:e2e-verify`**: definition `ops/e2e.sh verify` · executor `qa` (the acceptance lane) · environment `preview-vps` (the preview droplet, run after `ops/e2e.sh deploy`) · real or mocked `real` (Docker and the Supabase core stack; nothing mocked)

It runs only where the real dependencies live, never in CI. A task declares it
applicable only when its change reaches the paths that script exercises (register,
login, initialize and project creation, and the realtime and gateway checks).
When it does not apply, the PR record states that, rather than leaving it
silently unrun.

## Risk Tiers

The tier floors are defined in the Dev skill's `phases/phase3.5.md`. SupaConsole's
behavior lives in executable TypeScript, so the default behavior test applies and
no extra behavior paths are declared.

- **Behavior paths**: none (the defaults apply)
- **T2 paths**: `prisma/**`, `src/app/api/auth/**` (added to the plan-approval-list floor)
- **T3 paths**: none

Only the owner lowers a floor, and records it here with its date. No floor has been lowered.

## External Review Policy

- **Mode**: auto
- **Trusted reviewers**: coderabbit, kilo, github-copilot, gemini-code-assist, greptile, sourcery, qodo
- **Required reviewers**: coderabbit
- **Ignored reviewers**: kilo
- **Additional reviewer identities**: none
- **Pending reviewer decisions**: none
- **Default wait minutes**: 10
- **Allow automatic review requests**: `coderabbit` only

**CodeRabbit is the reviewer of record** (owner decision 2026-10-19). It is the one
required reviewer by default. SupaConsole records no additional reviewer
requirement of its own beyond the GitHub-required `build` check, which stays a hard
gate independent of this list. If the project later adds a requirement of its own
(an existing one, a platform one, or distinct justified expertise), it stays
required alongside `coderabbit`; this file never removes it.

`Ignored reviewers` removes a source from completion tracking only. A credible
material defect Kilo reports is still triaged by the lead under the materiality
rules.

A CodeRabbit review completes at head only through a submitted review object at
head or a head-bound review thread. The green `CodeRabbit` status, a skip comment
and a walkthrough or summary comment are not completion. The clean-PR case is
qualified before task 1 (README step 6). The substitution rule stays limited to
the rate-limit breakpoint, so a required `coderabbit` that has not completed at
head stays `pending` until it does or the owner amends this policy.

Automatic review requests are allowed for `coderabbit` only. The lead does not
request Kilo.
