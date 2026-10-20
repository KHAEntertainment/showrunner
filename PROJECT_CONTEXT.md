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

- **Last updated**: 2026-10-20
- **Current iteration goal**: v2.1.2 is the release. Every v2.1.2 milestone PR is merged (#118, #119, #121, #122, #123, #125, #127, #128, #129) and it publishes when the `v2.1.2` tag is created; no tag SHA is recorded here until the tag exists. v2.1.2 content: rate-limit breakpoint follow-ups (#69), wider external-reviewer identities with the Kilo gate and ask-once contract (#82, #117), REVIEW.md severity calibration (#120), PowerShell 7 requirement and git stderr in `install.ps1` (#51), Phase 1 document-first mode (#56, #74), assignment envelopes naming the lead's open questions (#34), lane close-out and the workspace-debt gauge (#73), multi-account routing docs (#75), and the ledger profile with `dev_state.py --validate` plus three ADRs (#85). v2.1.1 remains released: tag `v2.1.1` (annotated `00ef967` on `4a0e699`, PR #66) is published, and the Homebrew formula is bumped to v2.1.1 at `homebrew-tap@7acd583`. `brew install` works; `brew test` fails and is tracked as #70.
- **Architecture decisions this round**: ADR-011 adds Graft as a pinned optional code-graph evidence source and narrows ADR-005's no-third-party-dependencies rule to install time and the core workflow. ADR-012 routes child harnesses through the provider-neutral assignment envelope behind a capability checklist and moves ADR-009's authorship-lint reclassification to its point of use (#38 resolved). #17 remains deferred. ADR-014 moves distribution to the central KHA Entertainment marketplace (`dev-skill@kha-marketplace`, catalog repository `KHAEntertainment/marketplace`) and retires this repository's own `.claude-plugin/marketplace.json` (#79); the central entry is verified against the tag at release time, outside the offline gate.
- **Next iteration**: **v2.1.3**, placed by the owner (2026-10-19) between the v2.1.2 release and the v2.2.0 merger-preparation work; tracked in GitHub milestone v2.1.3 (#6). Scope is the progress-first, reduced-duplication verification plan from the Dev/Showrunner architecture investigation: one execution owner per check definition, tested subject and environment, with CI owning its assigned broad checks and other roles consuming applicable evidence; deterministic risk tiers in place of the size-only QA trigger; a T1 lane set of CI plus one qualified independent review (project-required multi-source policies stay valid); explicit per-criterion and per-check outcomes with the health score demoted to an optional diagnostic; fix batches counted on a defect-episode reference with lead diagnosis before batch 3; additive ledger evidence fields at the shared profile `completion-evidence-v1` (agreed with Foreman 2026-10-19) with a policy-bounded local containment rule; and the SupaConsole pilot setup with CodeRabbit as reviewer of record. Seven prose-plus-template packages (P1 to P7), P1 and P4 first, implemented Issue-to-PR under the Dev skill; no Issues are filed yet. No owner decisions remain open for v2.1.3 (container isolation is a later managed-project improvement outside it). Then v2.2.0: the `docs/plans/` Technical Planning and goal-mode plans target v2.2.0. The v2.1.2 phase plan (Phases 1–7) is delivered by the merged PRs above.
- **Open PRs**: see `gh pr list`.
- **Known tech debt**: see the bottom of `docs/feature-log.md`

---

## Verification Gate

The exact commands worker, QA, and reviewer must all run. Replaces the language
defaults in `${CLAUDE_SKILL_DIR}/phases/phase4.md`.

- **Lint**: `shellcheck install.sh tests/test-install.sh tests/migration-scratch.sh scripts/check_plugin_root.sh`
- **Type check**: `n/a` — no typed surface
- **Static analysis**: `bash -n install.sh` and `python3 scripts/validate_skill.py`
- **Dependency scan**: `n/a` — the project declares no third-party dependencies and ships no dependency manifest, so there is nothing to scan. Reinstate `pip-audit` when PyPI packaging lands and a manifest exists. Recorded as `n/a` deliberately rather than listing a command that exits 127, which would train everyone to ignore a failing gate.
- **Tests**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py'`, `bash tests/test-install.sh`, and — on Windows, or any runner with PowerShell — `pwsh tests/test-install.ps1`. The PowerShell suite is the only coverage `install.ps1` has; a gate that omits it can pass green while the Windows installer is broken.
- **Packaging**: `scripts/check_plugin_root.sh` and `python3 scripts/check_version_sync.py`. CI then attempts `claude plugin validate . --strict` and `claude plugin tag --dry-run .`; if the Claude Code CLI cannot be installed, it records that reason and instead fails closed on malformed JSON or missing required `name` or `version` fields in `plugin.json`. The plugin catalog is no longer hosted here (ADR-014), so these checks run with it absent; the central catalog entry is verified separately at release time by scripts/check_central_catalog.py (network, so deliberately not part of the offline gate; see docs/RELEASING.md). On a developer machine with Claude Code available, run the two Claude commands as well.

A change is not complete until every command above exits clean.

---

## CI Workflows

Where GitHub Actions runs the gate above (Issue #133). Local runs of `scripts/verify.sh` are unchanged.

- **Verification Gate** (`.github/workflows/ci.yml`): every PR and every push to `main`. Skill validation and Python tests; Bash syntax, ShellCheck and a PowerShell parse check of `install.ps1` and `tests/test-install.ps1`; packaging.
- **Release Gate** (`.github/workflows/release-gate.yml`): the installer suites, Bash on ubuntu and macOS and PowerShell on Windows. It runs only on a plain `vX.Y.Z` tag push (not `-rc` tags), from the Actions tab (`workflow_dispatch`), or on a PR labeled `run-installer-tests`. On any other PR the `Bash installer` and `PowerShell installer` checks show as skipped. That is expected and is not a failure, but it is also not passing evidence.
- **Lead duty**: when a PR changes `install.sh`, `install.ps1`, `tests/test-install.sh` or `tests/test-install.ps1`, add the `run-installer-tests` label before the merge gate (`gh pr edit N --add-label run-installer-tests`) and wait for both installer jobs to pass. The Release Gate is the only place `tests/test-install.ps1` runs on Windows. Remove the label after they pass so later pushes do not re-run them.
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
