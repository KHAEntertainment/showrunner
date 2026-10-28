# PROJECT_CONTEXT.md — Index File

> This is the master index — it only routes, it does not pile up content.
> Detailed content is spread across sub-documents in `docs/`.
> The `/dev` skill reads this file at every Phase to restore context.

---

## Repository Info

- **Repo URL**: https://github.com/KHAEntertainment/showrunner
- **Main branch**: `main` (maintained customized distribution)
- **Mirror branch**: `master` (upstream mirror, retained for comparison — never release from it)
- **Upstream**: https://github.com/hnaymyh123-henry/claude-dev-skill
- **Created**: fork maintained since 2026-08-26

## What this project is

A maintained English fork of an upstream Claude Code Skill. The canonical shipped
artifact is `skills/dev/` — 23 files of Markdown plus four stdlib-only Python
scripts. The repository is therefore **content-first**: almost every change is
prose that an agent reads at runtime, not code that executes. `en/` and `zh/` are
historical upstream command trees and are never installed.

See [UPSTREAM.md](UPSTREAM.md) for the fork/merge procedure and
[docs/AUDIT.md](docs/AUDIT.md) for the upstream-vs-fork feature matrix.

---

## Sub-document Index

| File | Content | Update timing |
|------|---------|---------------|
| `docs/architecture.md` | Architecture Decision Records for packaging and distribution | Immediately when a decision is made |
| `docs/feature-log.md` | Completed features (PR number, merge date) and known tech debt | Every Phase 5 round |
| `docs/dogfooding.md` | Evidence-anchored operational lessons from running `/dev` on this repo | After each `/dev` round that surfaces a new durable lesson |
| `docs/RELEASING.md` | Version sites, tag scheme, and the release procedure | When the release process changes |
| `docs/AUDIT.md` | Upstream-vs-fork feature matrix and risk register | On each upstream merge |
| `docs/glossary.md` | — not used; this project has no domain terminology layer | n/a |
| `docs/api-contracts.md` | — not used; no network API surface | n/a |
| `docs/tech-stack.md` | — folded into the Tech Stack section below (too thin for its own file) | n/a |
| `docs/style-guide.md` | — folded into the Conventions section below | n/a |

---

## Tech Stack

- **Payload**: Markdown (the Skill itself) + Python 3.10+ stdlib-only scripts
- **Installer**: Bash (`install.sh`) and PowerShell (`install.ps1`)
- **Tests**: Python `unittest` (`tests/test_*.py`) + Bash assertion suite (`tests/test-install.sh`) + PowerShell suite (`tests/test-install.ps1`). No per-suite counts are recorded here on purpose: every test-only PR changes them, so the numbers were stale within one release and a stale count reads as a real one. The suites are the gate — the Verification Gate below names the commands, and each suite's assertions are pinned in its own file.
- **No third-party runtime or build dependencies at install-time or in core workflow behavior.** This is a deliberate constraint — see ADR-005. Optional gate-time tooling such as Graft (`@nanonets/graft@0.18.0`) for code-graph evidence at gates per `skills/dev/graft.md` is explicitly excluded from this constraint.

Runtime prerequisites for the Skill (not for installing it): `rtk`, `gh`, `git`, Python 3, optionally Traycer CLI/Host, optionally Graft (`@nanonets/graft@0.18.0`) for code-graph evidence at gates per `skills/dev/graft.md` (optional, gate-time only).

---

## Conventions

- Everything in `skills/dev/` refers to siblings as `${CLAUDE_SKILL_DIR}/<relpath>` — never a hardcoded path.
- `scripts/validate_skill.py` is the gatekeeper: a 27-path required manifest, frontmatter keys, a forbidden-token list, and a required-policy token allowlist. Adding prose is safe; removing policy tokens fails the build.
- No CJK characters anywhere in the payload (enforced by the validator).
- No absolute home-directory paths anywhere in shipped Markdown — the payload, `en/`, `zh/`, and root-level docs alike (enforced by the validator, which tolerates `en/`/`zh/` being absent from a release archive).
- `bin/` must never exist at repo root — Claude Code plugin auto-discovery would add it to the Bash tool PATH.

---

## Current Status

- **Last updated**: 2026-10-27
- **Current iteration goal**: v2.1.3 is the release. Every v2.1.3 milestone package is merged: P1 #134 (#146), P2 #149 (#151, also resolves #107), P3 #154 (#156), P4 #135 (#147), P5 #150 (#152), P6 #155 (#157), P7 #159 (#160). It publishes when the `v2.1.3` tag is created; no tag SHA is recorded here until the tag exists. v2.1.3 content: the progress-first verification plan from the Dev/Showrunner architecture investigation: one executor per check with CI-owned broad checks consumed as evidence; deterministic risk tiers in place of the size-only QA trigger; a T1 lane set of one qualified independent review with QA only for a declared acceptance check; explicit per-criterion and per-check outcomes with the health score as an optional diagnostic; fix batches bounded per defect episode with lead diagnosis before batch 3; additive ledger evidence fields at the shared profile `completion-evidence-v1` (agreed with Foreman 2026-10-19) with an honest resource policy; and the SupaConsole pilot setup drafts and provider fragments (documentation only). Also in v2.1.3: the installer tests moved to the tag-gated Release Gate (#133), installer and validator test gaps closed (#138, #141), and upstream tracked as a remote after leaving the GitHub fork network (#148). v2.1.2 remains released: tag `v2.1.2` is published and the central catalog pins it. The Homebrew formula is bumped to v2.1.1 at `homebrew-tap@7acd583`; `brew install` works; `brew test` fails and is tracked as #70.
- **Architecture decisions this round**: ADR-011 adds Graft as a pinned optional code-graph evidence source and narrows ADR-005's no-third-party-dependencies rule to install time and the core workflow. ADR-012 routes child harnesses through the provider-neutral assignment envelope behind a capability checklist and moves ADR-009's authorship-lint reclassification to its point of use (#38 resolved). #17 remains deferred. ADR-014 moves distribution to the central KHA Entertainment marketplace (`dev-skill@kha-marketplace`, catalog repository `KHAEntertainment/marketplace`) and retires this repository's own `.claude-plugin/marketplace.json` (#79); the central entry is verified against the tag at release time, outside the offline gate.
- **Next iteration**: v2.2.0, the merger-preparation work: the `docs/plans/` Technical Planning and goal-mode plans target it. The SupaConsole pilot runs on the released v2.1.3 once the owner completes the setup checklist in `docs/pilot/supaconsole/README.md` and approves the launch; the clean-PR CodeRabbit completion qualification comes first. Container isolation is a later managed-project improvement outside v2.1.3.
- **Open PRs**: see `gh pr list`.
- **Known tech debt**: see the bottom of `docs/feature-log.md`

---

## Verification Gate

The commands that make up the gate. Replaces the language defaults in
`${CLAUDE_SKILL_DIR}/phases/phase4.md`. Each command has one executor, named in
the ownership table below; no role re-runs a command another owner already ran
at an applicable tested subject and environment.

- **Lint**: `shellcheck install.sh tests/test-install.sh tests/migration-scratch.sh scripts/check_plugin_root.sh`
- **Type check**: `n/a` — no typed surface
- **Static analysis**: `bash -n install.sh` and `python3 scripts/validate_skill.py`
- **Dependency scan**: `n/a` — the project declares no third-party dependencies and ships no dependency manifest, so there is nothing to scan. Reinstate `pip-audit` when PyPI packaging lands and a manifest exists. Recorded as `n/a` deliberately rather than listing a command that exits 127, which would train everyone to ignore a failing gate.
- **Tests**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py'`, `bash tests/test-install.sh`, and — on Windows, or any runner with PowerShell — `pwsh tests/test-install.ps1`. The PowerShell suite is the only coverage `install.ps1` has; a gate that omits it can pass green while the Windows installer is broken.
- **Packaging**: `scripts/check_plugin_root.sh` and `python3 scripts/check_version_sync.py`. CI then attempts `claude plugin validate . --strict` and `claude plugin tag --dry-run .`; if the Claude Code CLI cannot be installed, it records that reason and instead fails closed on malformed JSON or missing required `name` or `version` fields in `plugin.json`. The plugin catalog is no longer hosted here (ADR-014), so these checks run with it absent; the central catalog entry is verified separately at release time by scripts/check_central_catalog.py (network, so deliberately not part of the offline gate; see docs/RELEASING.md). On a developer machine with Claude Code available, run the two Claude commands as well.

A change is not complete until every command above has exited clean at its owner's run, per the table below.

**Check ownership** (Issue #134). One executor per check definition, tested subject and environment. The job names are the `name:` values in the workflow files.

| Gate commands | Executor (owner) | Evidence consumers cite |
| --- | --- | --- |
| `python3 scripts/validate_skill.py`, the Python `unittest` discovery | PR CI: Verification Gate workflow, job `Skill validation` | run, job, attempt |
| `bash -n install.sh`, `shellcheck` over the shell scripts, the PowerShell parse check of `install.ps1` and `tests/test-install.ps1` | PR CI: Verification Gate workflow, job `Shell validation` | run, job, attempt |
| `scripts/check_plugin_root.sh`, `python3 scripts/check_version_sync.py`, the source-archive check, the `claude plugin` manifest validation or its fail-closed JSON fallback | PR CI: Verification Gate workflow, job `Packaging validation` | run, job, attempt |
| `bash tests/test-install.sh`, `pwsh tests/test-install.ps1`, strict `claude plugin validate . --strict` | Release Gate workflow, jobs `Bash installer (ubuntu-latest)`, `Bash installer (macos-latest)`, `PowerShell installer`, `Strict plugin validation`; runs on a `vX.Y.Z` tag, from the Actions tab, or on a PR the lead labels `run-installer-tests` | run, job, attempt |
| Focused checks for the change: the tests the diff touches, and any prerequisite this policy requires before a push | The worker, within this policy | report-back commands and exit codes |

- **Verification Gate jobs run on every PR and on `main`.** Worker, QA, reviewer and lead cite the run, job and attempt, plus the tested subject (the PR checks out GitHub's temporary merge commit, not the PR head). They do not repeat the jobs above.
- **Release Gate jobs are skipped on an ordinary PR.** A skipped job is not passing evidence. A PR that changes `install.sh`, `install.ps1` or an installer test gets the label; no lane runs the installer suites locally by role.
- **No mandatory worker pre-push gate exists in this policy today.** If this file later records a pre-push requirement, workers keep it until this file explicitly amends it.
- **Local full-gate execution** needs an approved fallback trigger or a separate project requirement, plus one designated executor (see Check Ownership and CI Evidence in the Dev skill's phases/phase4.md).

---

## CI Workflows

Where GitHub Actions runs the gate above (Issue #133). Local runs of `scripts/verify.sh` are unchanged.

- **Verification Gate** (`.github/workflows/ci.yml`): every PR and every push to `main`. Skill validation and Python tests; Bash syntax, ShellCheck and a PowerShell parse check of `install.ps1` and `tests/test-install.ps1`; packaging.
- **Release Gate** (`.github/workflows/release-gate.yml`): the installer suites, Bash on ubuntu and macOS and PowerShell on Windows, plus `Strict plugin validation` (the pinned Claude Code CLI with no fallback; the Verification Gate's packaging job falls back to a JSON check when the CLI cannot be installed). It runs only on a plain `vX.Y.Z` tag push (not `-rc` tags), from the Actions tab (`workflow_dispatch`), or on a PR labeled `run-installer-tests`. On any other PR the `Bash installer`, `PowerShell installer` and `Strict plugin validation` checks show as skipped. That is expected and is not a failure, but it is also not passing evidence.
- **Lead duty**: when a PR changes `install.sh`, `install.ps1`, `tests/test-install.sh` or `tests/test-install.ps1`, add the `run-installer-tests` label before the merge gate (`gh pr edit N --add-label run-installer-tests`) and wait for every Release Gate job to pass. The Release Gate is the only place `tests/test-install.ps1` runs on Windows. Remove the label after they pass so later pushes do not re-run them.
- **Release duty**: after pushing the release tag, wait for the Release Gate run on that tag to pass before bumping the central catalog (`docs/RELEASING.md` step 4).

---

## External Review Policy

- **Mode**: auto
- **Trusted reviewers**: coderabbit, kilo, github-copilot, gemini-code-assist, greptile, sourcery, qodo
- **Required reviewers**: kilo
- **Ignored reviewers**: coderabbit (summary only; its walkthrough comments are not review evidence)
- **Additional reviewer identities**: none
- **Pending reviewer decisions**: none
- **Default wait minutes**: 10
- **Allow automatic review requests**: `kilo` only

**Kilo is the reviewer of record.** Kilo has no comment command. Its documented triggers are PR opened, new commits pushed, PR reopened, and draft marked ready (kilo.ai/docs/automate/code-reviews/github). The lead may use **PR opened**, **new commits pushed**, and **draft marked ready** without explicit approval (each is a deliberate review moment). **PR reopened** is a non-code-changing re-request that is also covered by this automatic allowance, so a Kilo summary that lands while the PR is closed does not need an extra approval to fire when the PR is reopened.

**CodeRabbit is summary/walkthrough-only.** Its walkthrough comments are not review evidence; the inspector ignores it (`--ignored-reviewer coderabbit`). The lead does not post `@coderabbitai review` requests here. This is a deliberate narrowing: Kilo is the reviewer that produces a verdict, and CodeRabbit's role is reduced to a summary the maintainer reads directly. Removing CodeRabbit from `Trusted reviewers` was rejected because the Kilo summary evidence path is a separate mechanism, and an ignored-but-not-trusted reviewer still surfaces walkthrough comments the maintainer wants to see.

The lead reads Kilo's verdict from the `<!-- kilo-review -->` summary comment, per the **Kilo summary evidence** path in `phases/external-review.md`. Kilo's `<!-- kilo-review -->` summary comment that follows the ordering rule (chronological or check-completed) satisfies the external-review gate on its own. CodeRabbit's walkthrough comments do not satisfy the gate, and an active CodeRabbit finding is not raised as a blocking finding.

---

## Risk Tiers

The tier floors are defined in `skills/dev/phases/phase3.5.md`. This repository's behavior is its SOP and scripts, so declared paths are needed: without them a Markdown-only edit to the SOP would read as nonbehavioral.

- **Behavior paths**: `skills/dev/` (a diff touching nothing under it and no executable file is T0)
- **T2 paths**: `skills/dev/backends/`, `skills/dev/phases/` (added to the plan-approval-list floor)
- **T3 paths**: `skills/dev/scripts/resolve_repository.py`, `.github/workflows/release-gate.yml`, release and tag paths, the review-gate policy (`skills/dev/phases/external-review.md`, `REVIEW.md`), and secrets (added to the critical-path floor)

Only the owner lowers a floor, and records it here with its date. No floor has been lowered.

---

## Execution Routing Policy

The agent selection guide governs role routing. This file records only
project-specific exceptions, and there are none. Do not restate the guide's
model or harness choices here, even to agree with them: a route recorded in this
section outranks the guide in the adapter's resolution order, so anything
written here silently overrides newer policy, and a copy made today becomes a
stale override the moment the guide changes. That is why this section stays
empty.

One constraint does belong here, because it is a property of this project rather
than a routing preference: **the lead runs on the harness that invokes `/dev`:
Claude Code on either backend, or Codex or OpenCode under the Traycer backend
only (ADR-013).** Worker, QA, and reviewer assignments are provider-neutral and
may run on whichever harness and model the selection guide selects for them.
