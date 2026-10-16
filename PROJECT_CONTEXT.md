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
- **Tests**: Python `unittest` (36 tests) + Bash assertion suite (9 assertions) + PowerShell suite (5 assertions)
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

- **Last updated**: 2026-09-29
- **Current iteration goal**: v2.1.2. v2.1.1 is released: tag `v2.1.1` (annotated `00ef967` on `4a0e699`, PR #66) is published, the marketplace install was verified against it in a scratch `CLAUDE_CONFIG_DIR` (installed `skills/dev` identical to `git archive v2.1.1`, reporting `2.1.1+upstream.3e87db0`), and the Homebrew formula is bumped to v2.1.1 at `homebrew-tap@7acd583`. `brew install` works; `brew test` fails and is tracked as #70. v2.1.1 content: child-harness capability checklist (#58, #38), lead-to-user reply contract (#54), post-merge verification (#26), git-staged installs (#44), scoped external-review bypass (#33), external-review rate-limit breakpoint (#48), test-coverage gaps (#31, #25), home-path leak guard (#42), Graft evidence adapter (#57), dogfooding distillation (#40), README integrations (#50), and Homebrew tap docs (#39).
- **Architecture decisions this round**: ADR-011 adds Graft as a pinned optional code-graph evidence source and narrows ADR-005's no-third-party-dependencies rule to install time and the core workflow. ADR-012 routes child harnesses through the provider-neutral assignment envelope behind a capability checklist and moves ADR-009's authorship-lint reclassification to its point of use (#38 resolved). #17 remains deferred. ADR-014 moves distribution to the central KHA Entertainment marketplace (`dev-skill@kha-marketplace`, catalog repository `KHAEntertainment/marketplace`) and retires this repository's own `.claude-plugin/marketplace.json` (#79); the central entry is verified against the tag at release time, outside the offline gate.
- **Next iteration**: work the v2.1.2 milestone in its planned phase order. Real-project testing of v2.1.1 is done (2026-09-29); its findings are #73, #74, #75, and #82.
  - **Phase 1**, in order: #72 (this status correction) → #76 (orchestrator portability: Codex and OpenCode leads under the Traycer backend) → #70 (Homebrew formula test).
  - **Phase 2**, after #70: #67 → #71 (release-procedure hardening), then #79 (move the dev-skill listing to the central KHA Entertainment marketplace).
  - **Phase 3**, after #72: #69 → #82 (review gate), #56 + #53 (validator and prose follow-ups), #34 (assignment envelopes), #74 (Phase 1 document-first mode), then #73 (workspace debt).
  - **Phase 4**, after #76: #51 (`install.ps1` PowerShell version).
  - **Phase 5**, verification experiments whenever the environment allows: #37 with #75 (multi-account routing), #43, #59; #17 stays deferred.
  - **Phase 6**, after #69 and #82: #84 (CodeRabbit CLI advisory review plane).
  - **Phase 7**, after #84 and #73: #85 (ledger profile, `dev_state.py --validate`, three ADRs).
  - Then the v2.1.2 release. The `docs/plans/` Technical Planning and goal-mode plans target v2.2.0.
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
