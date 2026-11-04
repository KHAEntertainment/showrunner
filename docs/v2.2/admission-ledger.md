---
title: "Showrunner v2.2 P0 — source, decision and requirement admission ledger"
kind: spec
comments: none
---

# Showrunner v2.2 P0 — source, decision and requirement admission ledger

Implements `KHAEntertainment/showrunner#183` (M1 package **P0-01**). Counterpart package **P0-02** is `KHAEntertainment/showrunner#184` (SC-1–SC-9 contract specifications and fixture provenance), which consumes this ledger's source/decision bindings.

This is a **text-only admission record**. It admits sources, decisions, holds and requirement destinations into the record. It admits no behavior.

---

## 0. Header — source revisions, tier record, limitations

### 0.1 Source revisions this ledger is bound to

| Role | Identity | Revision / digest |
| --- | --- | --- |
| Canonical plan (SDP) | `artifacts/v2-2-development-plan/index.md` (Showrunner task `6266293c-0b2c-4519-99ce-0832b63313f9`... see note) | SHA-256 `dae53a66f79f53d3ddedacff4c206fa034dcb5fbefde7fa1c0b86f4056529d81`, 789 lines |
| Initial source `main` | `KHAEntertainment/showrunner` | `83631ce10309a3c47479ff96df70e0e2ff7110f2` |
| Released Dev runtime | `~/.claude/plugins/cache/kha-marketplace/dev-skill/2.1.4/skills/dev` | `version: 2.1.4+upstream.3e87db0`; SKILL.md SHA-256 `6ce063307a2b60826e17093b54dca65cc82a7a7b2fd149ab60b79a997fe991df` |
| Evolving Dev source | `skills/dev/` in this worktree | tree at `83631ce10309a3c47479ff96df70e0e2ff7110f2`; SKILL.md SHA-256 `6ce063307a2b60826e17093b54dca65cc82a7a7b2fd149ab60b79a997fe991df` |
| Foreman scoped alias | `~/.claude/skills/foreman-showrunner/SKILL.md` | `version: 0.3.15`; SHA-256 `5d5b1265875de3221dc7360afb941fc306472dc082fbe0858b257b5a35064906` |
| Foreman release source | tag `v0.3.15` | commit `bdc298852aebf8d4e942246e3a3fdc194f732e71` |
| M1 charter | `artifacts/orchestration-workflow-foreman/charters/p0-baseline-and-contracts/index.md` | SHA-256 `bf297b61118da0e29fe39f7bed64645932127c6584abf2ecb0d90dd13399c3ee`, 124 lines |
| Standing rulings | `artifacts/orchestration-workflow-foreman/rulings/index.md` | SHA-256 `77b5a64ecafc0a407568b70bf7312da856e2fd98a1c33bf2f75abb958eea559c`, 31 lines |

> Note on the SDP path: the canonical SDP lives in the Showrunner epic `6266293c-edb0-48f6-b8f6-ddd561de1f05` at `artifacts/v2-2-development-plan/index.md`. The SDP itself cites a sibling Architect-task path for the Foreman runtime manifest (`d4441475-0b2c-4519-99ce-0832b63313f9`), which is the task that produced the Foreman manifests and the activation packet.

Every SDP line citation in this ledger is a line number **at revision `dae53a66…`** (789 lines). Recomputation of the digest was performed locally before authoring; it matches the value in `#183`, the M1 charter §7 and the activation packet `approval-scope.json`. If the SDP is re-pinned, this ledger stops and re-checks rather than citing a stale revision.

### 0.2 Risk tier record

| Field | Value |
| --- | --- |
| Path floor tier | **T0** — no behavior path, no executable, no runtime surface |
| Recorded tier | **T1** — raised by the M1 orchestrator for this lane (docs-only, one new file) |
| Review lane | one qualified independent review + Kilo (required reviewer) |
| QA lane | none (no declared acceptance check applies to a text-only record) |
| Dev 2.1.4 gates preserved | required Kilo, deterministic risk floors, CI ownership, current Dev 2.1.4 gates when later work is authorized |
| Ownership | exactly one new file: `docs/v2.2/admission-ledger.md` |

### 0.3 Limitations

- **Nothing was executed.** No test, fixture, validator, linter, installer, release check, live probe or network verification was run for this record. Every source below is labelled *inspected* or *installed*, never *verified* or *executed*.
- **Text-only admission.** This record admits sources, decisions, holds and destinations into the record. It admits no runtime behavior, installs nothing, changes no tracker item, and grants no authority.
- **Policy defaults are not proposed.** Pending policy — principally `completion-result-v1` and Architect C1–C5 — is recorded as pending. This ledger proposes no value, schema, field, threshold or default for it.
- **Tracker states are point-in-time.** Compact tracker summaries (number, title, state, milestone, labels) were read on 2026-11-04. Deep reads were limited to `#183`, `#132` and `#182`. Live tracker state wins over any statement here.
- **Milestone and issue IDs in the SDP are planning labels.** The SDP states that its planning milestone IDs do not create tracker milestones or assign work to live agents (SDP l.13). The M1–M6 milestones referenced below are real tracker milestones (`#8`–`#13`); the P0–P5 phase labels are planning labels.

### 0.4 Label vocabulary used throughout

| Label | Meaning |
| --- | --- |
| **inspected** | Read at the stated revision. Content was observed; nothing was run. |
| **not-run** | Identified and cited, but deliberately not executed or not inspected by this lane. |
| **installed** | Present on this machine at the stated path, with the stated digest. Installation does not imply adoption or that the payload behaves as specified. |
| **adopted** | Actually in use by a running seat or recorded workflow, with the cited evidence. |

"verified" and "executed" are not used for anything in this ledger.

---

## 1. Pins — source, runtime, alias, manifests, prerequisites

| # | Item | Identity | Digest / revision | Label | Basis |
| --- | --- | --- | --- | --- | --- |
| A1 | Canonical SDP | `artifacts/v2-2-development-plan/index.md` | SHA-256 `dae53a66…6529d81`, 789 lines | **inspected** | Recomputed locally; matches `#183`, charter §7, `approval-scope.json` |
| A2 | Initial source `main` | `KHAEntertainment/showrunner` | `83631ce10309a3c47479ff96df70e0e2ff7110f2` | **inspected** | Branch base of this lane's worktree; clean tree at authoring |
| A3 | Released Dev runtime | `~/.claude/plugins/cache/kha-marketplace/dev-skill/2.1.4/skills/dev` | `2.1.4+upstream.3e87db0`; SKILL.md SHA-256 `6ce06330…fe991df` | **installed** | Present at the plugin cache path; digest matches the activation packet's declared runtime |
| A4 | Released Dev runtime — adoption | same payload | — | **adopted** | M1 lead runs the released `/dev-skill:dev` 2.1.4 from the plugin cache path, never 2.2 source (activation ruling 2026-11-04; charter §9; `.foreman/project.json` → `orchestrator.workflow = "/dev-skill:dev"`) |
| A5 | Evolving Dev source | `skills/dev/` at `83631ce` | SKILL.md SHA-256 `6ce06330…fe991df`; `version: 2.1.4+upstream.3e87db0` | **inspected** | **Released runtime vs evolving source:** the source tree at `83631ce` and the released 2.1.4 runtime payload are byte-identical except for a `__pycache__` directory present only in the runtime cache. Source and runtime are the same payload; the source is *source only, not runtime policy* (charter §6). |
| A6 | Foreman scoped alias | `~/.claude/skills/foreman-showrunner/SKILL.md` | `version: 0.3.15`; SHA-256 `5d5b1265…0064906` | **installed** | Present at the alias destination; SKILL.md digest matches `expected-alias-payload.json` exactly |
| A7 | Foreman scoped alias — adoption | same | — | **adopted** | Running Foreman for showrunner (`/Users/bbrenner/foreman/showrunner/.foreman/state.md` → `foreman_agent_id: 0f4a8db9-ecec-4ae4-9338-860df3eeea65`, `harness: claude`, `model: opus`). Distinct from the shared `~/.claude/skills/foreman` and from the `foreman-next` alias, both left untouched |
| A8 | Foreman release source | tag `v0.3.15` | commit `bdc298852aebf8d4e942246e3a3fdc194f732e71` | **inspected** | Via `approval-scope.json` / `expected-alias-payload.json`. The live install was performed by the activation packet, not by this lane; this lane did not run the alias installer or load the alias |
| A9 | Foreman alias payload manifest | `activation/expected-alias-payload.json` | 42 files; `install_as: foreman-showrunner`; `invocation: /foreman-showrunner` | **inspected** | Records the exact transformed payload and the 8 files transformed for the alias |
| A10 | Showrunner runtime manifest | `artifacts/runtime-manifest/index.md` (Showrunner epic) | Revision 10, planning update 2026-11-03 | **inspected** | Implementation baseline `16e15390c835b13794d09a757747edf97cc17b05`; v2.1.4 reconciled at tag `v2.1.4` (`938ca99`) |
| A11 | Foreman runtime manifest | `d4441475-…/artifacts/product-direction/runtime-manifest/index.md` | as published in the Architect task | **inspected** | The SDP requires preserving its stable S:F:E:X / F:FM/FU identities (SDP l.36) |
| A12 | Plugin package metadata | `.claude-plugin/plugin.json` | `version: 2.1.4`; `skills: ["./skills/dev", "./skills/readme"]` | **inspected** | Confirms the marketplace channel ships both skills; manual installers still install `skills/dev` only (SDP l.22) |
| A13 | Worktree configuration | `.dev.json` | account `KHAEntertainment`; push/PR repo `KHAEntertainment/showrunner`; push remote `origin` | **inspected** | `resolve_repository.py --operation issue` → `status: ready`, `reason_code: target_confirmed` (exit 0) |
| A14 | M1 charter | `charters/p0-baseline-and-contracts/index.md` | SHA-256 `bf297b61…99c3ee`, 124 lines | **inspected** | Scope, holds, §7 standing rulings, §6 shared surfaces |
| A15 | Standing rulings | `rulings/index.md` | SHA-256 `77b5a64e…e559c`, 31 lines | **inspected** | Three rulings: activation bootstrap, policy holds, M1 partial GO |
| A16 | Activation packet receipts | `activation/execution-receipt.json`, `activation/approval-scope.json`, `activation/owner-approval.md.txt` | `execution-receipt.status = complete_startup_only_stopped_before_implementation`; `approval-scope.status = "DRAFT awaiting owner approval; no operations executed"` | **inspected** | The `pending_policy` clause is the basis for the pending `completion-result-v1` record in §3 |
| A17 | Activation P0 issue bodies | `activation/P0-01-issue-body.md.txt`, `activation/P0-02-issue-body.md.txt` | — | **inspected** | Confirms `#183` = P0-01 and `#184` = P0-02 identity used in §4 |
| A18 | Foreman project records | `/Users/bbrenner/foreman/showrunner/.foreman/project.json`, `state.md` | `schema: 1`; 5 shared surfaces; `memory.system: none` | **inspected** | Milestone IDs `#8`–`#13`, tracker `KHAEntertainment/showrunner`, epic `6266293c-…` |
| A19 | Tracker state summaries | 22 referenced issues, read compact (number, title, state, milestone, labels) | as of 2026-11-04 | **inspected** | Deep reads limited to `#183`, `#132`, `#182` |
| A20 | Handoff component | release `v0.1.0` @ `721c7086fff2140d051dd96c7098d8a922f9fd72`; `v0.2.1` current at 2026-11-03 | SDP l.38, l.455 | **not-run** | Cited from the SDP only. No install, no per-session load evidence, no adapter qualification collected here |
| A21 | Foreman staged source | `9acda87a0eb7fdfb4038d8d226df07c9eea16c1e` (0.3.12 staged) | SDP l.39 | **not-run** | Staged templates/procedures cited by the SDP; not inspected by this lane |
| A22 | Migration utility | `f712becf5bb957e8f6e4eaeafef706be5ac5bee3` | SDP l.40 | **not-run** | Cooperative prototype; not Foreman/production integration |
| A23 | Dev test suites, `scripts/validate_skill.py`, installer checks, CI workflows | `tests/`, `scripts/`, `.github/workflows/` | — | **not-run** | CI (Verification Gate) owns broad checks; this lane did not run or re-run them |
| A24 | Repository documents under shared-surface serialization | `PROJECT_CONTEXT.md`, `docs/architecture.md`, `docs/plans/**`, `docs/feature-log.md`, `skills/**`, `scripts/**`, installers, CI, version/changelog | — | **not-run** | Out of this lane's ownership (charter §6). Only `docs/v2.2/admission-ledger.md` is created |

### 1.1 Prerequisite checkpoint (carried, not re-derived)

Recorded from P-DEP (SDP l.788) and the SDP §2 prerequisite checkpoint (l.46–l.51), both of which are **inspect-only** statements: a tracker state or a file on `main` is not proof that a dependency works.

| Prerequisite | SDP-recorded state | Label |
| --- | --- | --- |
| `#73` workspace inventory | Closed; delivered (files and sections confirmed on `main`, **not run**) | **inspected** |
| `#74` Situation A document-first | Closed; delivered (files and sections confirmed on `main`, **not run**) | **inspected** |
| `#85` workspace-panel prerequisites | Closed via PR #129; profile, validator and 3 ADRs delivered | **inspected** |
| `#84` advisory local review tools | Open; independent optional work; gates no phase, panel prerequisite, merge or release (SDP l.661–l.679) | **inspected** |
| `#77`, `#78` | Moved to O-PORTAL; open without a milestone | **inspected** |
| `#119`, `#126` | Merged | **inspected** |
| `#104` | Open without a milestone; release disposition is CUT-6, not an inferred authorization from the issue's existence (SDP l.51) | **inspected** |
| `#112` | Open in v2.2.0 / M5 | **inspected** |
| Panel bounded critiques (3) | **Open**; gate only the panel technical plan | **inspected** |
| Release tag | `v2.1.4` is the latest release (refreshed 2026-11-02), pinned in the central catalog by `KHAEntertainment/marketplace#46` | **inspected** |

---

## 2. Settled decisions — carried without re-asking

Each row is a decision the owner already settled. This lane **records** them; it does not re-ask, re-derive, narrow or re-open any of them. Line numbers are at SDP revision `dae53a66…`.

| ID | Decision | SDP citation | Approval recorded in the SDP | Status |
| --- | --- | --- | --- | --- |
| **D1** | Canonical store and access — detector-selected canonical home; only approved plan revisions promoted via docs-only PR; one portable `plan_ref`; GitHub-addressable evidence references with digests; inaccessibility is *incomplete*, never a reason to create a duplicate plan | l.85–l.96; §14 l.777 | Owner approved option A, 2026-10-19; **not implemented** | SETTLED — carried |
| **D1** revisit note | Promotion location and native tracking settled under D6.5. Revisit trigger: the D6 native-tracking decision, or the first project that rejects promotion PRs. Owner: Dev planning | l.95, l.96 | — | Carried with its revisit note intact |
| **D2** | Merge authority — bounded per-run grant is the goal-run default; `confirm_each` otherwise; two independent review levels required; head-bound squash merge; grant never grows | l.252–l.284; §14 l.778 | Owner approved 2026-11-01; **not implemented** | SETTLED — carried |
| **D3** | Run bounds — 24 h run time; 8 agent dispatches per goal Issue; optional spend cap; 3 GV query tries; persisted counters; unknown usage recorded as `unknown`, never zero | l.286–l.307; §14 l.779 | Owner approved 2026-11-01; **not implemented** | SETTLED — carried |
| **D4.1** | Verifier packaging — one stdlib helper `skills/dev/scripts/verify_goal_completion.py` in the core Dev payload; offline fixtures; validator and install-test coverage | l.358–l.370; §14 l.780 | Owner approved 2026-10-19; **not implemented** | SETTLED — carried |
| **D4.2** | Shared evidence profile `completion-evidence-v1` — `pr_assurance` and `parent_acceptance` record types; six shared meanings; invalidation rules are part of the profile; SDP owns the version identifier | l.372–l.383; §14 l.780 | Owner approved 2026-10-19; **not implemented** | SETTLED — carried |
| **D4.3** | Initial goal scope and two safety rules — single-repository goals only (cross-repo rejected at arming); revert/reopen detection floor; distinct exit codes, only `verified` may be treated as success | l.385–l.395; §14 l.780 | Owner approved 2026-10-20; **not implemented** | SETTLED — carried |
| **D4.4** | Evaluator assignment and proof — machine-checkable → test; judgment-heavy → independent reviewer; human evaluator only on explicit owner request; fixed owner acceptance command; agents never post it | l.397–l.424; §14 l.780 | Owner approved 2026-10-21; **not implemented** | SETTLED — carried |
| **D5** | External and Linear plan provenance — tracker content is a supplied document; qualified identifier + revision + retrieval method + digest recorded; approval comes from Dev, not tracker status; collections frozen at intake; GitHub stays the execution record; no upstream polling | l.162–l.171; §14 l.781 | Owner approved 2026-11-03; **not implemented** | SETTLED — carried |
| **D6.1** | Planning entry, packaging and handoff — `/dev plan` entry and router; Phase 1.5 packaged inside the Dev skill; plan→Phase-2 handoff recommendation | l.98–l.107; §14 l.782 | Owner approved 2026-11-02; **not implemented** | SETTLED — carried |
| **D6.2** | PRD and Technical Plan — two documents, two jobs; PRD feeds the Technical Plan as locked input; same downstream `plan_ref` and approval rules | l.109–l.118; §14 l.782 | Owner approved 2026-11-02; **not implemented** | SETTLED — carried |
| **D6.3** | Supplied documents — Situation A; extract-before-asking; outside approval proposed as locked, never a skip; embedded directives recorded, not followed; source never rewritten | l.120–l.129; §14 l.782 | Owner approved 2026-11-02; **not implemented** | SETTLED — carried |
| **D6.4** | What planning records in `PROJECT_CONTEXT.md` — pointers not content; one index row for promoted plans; Current Status names the active plan; durable decisions keep their homes; no policy change without the user | l.131–l.140; §14 l.782 | Owner approved 2026-11-02; **not implemented** | SETTLED — carried |
| **D6.5** | Where plans live in the repository — drafts stay out of git; approved Technical Plans and feature PRDs promoted to `docs/plans/<YYYY-MM-DD>-<slug>.md`; `.agent/` added to gitignore guidance | l.142–l.151; §14 l.782 | Owner approved 2026-11-02; **not implemented** | SETTLED — carried |
| **D6.6** | Relation to `traycer-tech-plan` — Dev does not call it; its output enters as a supplied document; its ticket workflow is not followed; either path is the user's choice | l.153–l.160; §14 l.782 | Owner approved 2026-11-02; **not implemented** | SETTLED — carried |
| **D7.1** | Lifecycle clocks and idle timers — managed mode uses Foreman's orchestrator clock; standalone Dev has no mandatory clock; the owner's two-compaction rule means *prepare to hand over*; `#112` (60 min) and Foreman (4 h) idle timers stay separate | l.492–l.506; §14 l.783 | Owner approved 2026-10-24; **not implemented** | SETTLED — carried |
| **D7.2** | Gate delegation and run control — Tier A stays lead-owned, Tier C stays protected; Phase 0/Phase 2 engineering gates delegated; technical review decisions by second opinion + recorded disposition; per-run policy block, step-boundary veto, one-at-a-time questions (amended 2026-11-02, `#173`) | l.212–l.230; §14 l.783 | Owner approved 2026-10-25; **not implemented** | SETTLED — carried |
| **D8** | Reference investigation — no separate survey before G1; Foreman/handoff evidence reused for what it covers; the G3 pilot's harness-goal arm is the measured comparison; native workflow qualification → O-ADAPT; reference workflows are never invoked dependencies | l.309–l.317; §14 l.784 | Owner approved 2026-11-03 | SETTLED — carried |
| **D9.1–D9.7** | Panel interfaces — disposition settled: answered in the P4 panel technical plan after the three critiques, bound by L1, D4.2, D4.4 and D4's reader rules | l.562–l.592; §14 l.785 | Owner approved 2026-11-03 | SETTLED as a **disposition only** — the seven questions themselves are recorded at their own package (§3.2) |
| **H1** | Handoff qualification and fallback — qualify from the current handoff release; goal and managed runs declare a continuity strategy; Claude Code, OpenCode and Codex qualify by one test; visible ledger-checkpoint fallback reporting `continuity: fallback`; Dev never installs handoff | l.453–l.462; §14 l.787 | Owner approved 2026-11-03; **not implemented** | SETTLED — carried |
| **L1** | Lifecycle executable remainder — existing record/procedure coverage + v2.2 read contracts; full registration/history/successor-claim service deferred to O-LIFE; custody-gap assessment 2026-10-20 found no service needed, four narrow items routed in §7 | l.479–l.490; §14 l.786 | Owner approved 2026-10-19 | SETTLED — carried |
| **P-DEP** | Prerequisite dispositions — `#74`, `#73`, `#85` delivered (files and sections confirmed on `main`, **not run**); `#84` independent optional work; `#77`/`#78` → O-PORTAL; the three panel critiques stay open and gate only the panel technical plan | l.788 | Owner approved 2026-11-01 | SETTLED — carried |
| **CUT-4** | New G4/G4b/G5 stop-hook and classifier delivery deferred to O-STOP; existing handoff integration excluded | l.596–l.604; §14 l.774 | Owner approved 2026-10-19 | SETTLED — carried |
| **CUT-5** | Utility contracts now, unified CLI may follow repository integration; U1 is not a repository-integration prerequisite | l.618–l.632; §14 l.775 | Owner approved 2026-10-19 | SETTLED — carried |
| **CUT-6** | New `#104` live intake/post-merge sync deferred to O-TRACK; supported connections, supplied/exported intake, GitHub execution identity and the existing Foreman GitHub-to-Linear bridge retained | l.173–l.181; §14 l.776 | Owner approved 2026-10-19 | SETTLED — carried |
| **R-RET** | Retirement enforcement — retain Foreman's staged retirement policy and existing handoff procedures; deterministic cross-harness enforcement is a follow-up candidate, not an initial-merger prerequisite | l.430–l.436; §14 l.773 | Owner approved 2026-10-19 | SETTLED — carried |
| **D-DIST / U-GOV** | Holds and upkeep — keep the npm and migration holds; Homebrew retired (ADR-018); the npm path is expected through the U1 CLI (`#181`); liaison charters wait for an owner request | l.789 | Owner approved 2026-11-03 | SETTLED — carried |

### 2.1 D1 / D2 / D3 — resolution of the open question

The M1 lead raised whether D1/D2/D3 are settled, noting that charter §7 enumerates only D5–D8, H1, P-DEP and D9. **They are settled at SDP revision `dae53a66…`**, in the SDP body and in the §14 consolidated owner-decision table:

| ID | Body heading | §14 owner-decision row | Approval date | SDP status text |
| --- | --- | --- | --- | --- |
| D1 | l.85 `### D1 — Canonical store and access (settled)` | l.777 | 2026-10-19 | "Owner approved option A on 2026-10-19; not implemented." |
| D2 | l.252 `### D2 — Merge authority (settled)` | l.778 | 2026-11-01 | "Owner approved 2026-11-01; not implemented." |
| D3 | l.286 `### D3 — Run bounds (settled)` | l.779 | 2026-11-01 | "Owner approved 2026-11-01; not implemented." |

The charter's §7 table is a **summary of standing rulings**, and its own preamble says the SDP text governs and "these summaries do not narrow it". D1–D3 are therefore carried as settled **with the SDP citations above**, not as an inference from the omission. Charter §7 rows are also recorded for D5 (l.781), D6 (l.782), D7 (l.783), D8 (l.784), D9 (l.785), H1 (l.787) and P-DEP (l.788); the charter's line citations were checked against the pinned SDP and all eight match.

---

## 3. Pending and panel-gated items — recorded at their own package

### 3.1 `completion-result-v1` (D4 result record) and Architect C1–C5 — **PENDING owner approval**

| Field | Value |
| --- | --- |
| Item | The GV result record `completion-result-v1` (its serialization, its `purpose` field for readiness versus final completion, `run_id`, `plan_ref` and writer identity), and the Architect C1–C5 policy set |
| SDP status | **Open.** "Still open in D4: the GV result record (`completion-result-v1`) and its `purpose` field for readiness versus final completion, including `run_id`, `plan_ref` and writer identity (custody finding 3)" — l.381; also l.350, l.485, l.516, l.780 |
| SDP authority | l.13 — "Definitions of contract fields do not approve their policy values" |
| Charter | §2 criterion 2 — "D4 result-schema approval (`completion-result-v1`) remains pending; block only affected SC-3/GV implementation" |
| Ruling | `ruling-policy-holds-2026-11-04` — "Pending D4/C1–C5 policy and panel-specific gates stay pending; all existing holds remain." |
| Activation packet | `approval-scope.json` → `pending_policy`: "completion-result-v1/C1-C5 is not approved by activation. Keep SC-3 affected work blocked" |
| **Disposition in this ledger** | **PENDING owner approval.** Affected work is **SC-3 / GV implementation only** (P3, and SC-3 fixtures in P0-02). |
| **Default proposed?** | **No.** This ledger proposes no field, no serialization, no `purpose` value, no threshold and no fixture that could be read as an approved default. The SDP's own representation rule applies: "Never put operational policy values into examples and call them approved" (l.511). |

### 3.2 D9.1–D9.7 — panel interfaces, recorded at P4

| ID | Question | Recorded at | Constraint carried forward |
| --- | --- | --- | --- |
| D9.1 | Run discovery — distinguishing multiple active ledgers for one repository across worktrees, tasks and orchestrators; cross-host aggregation | **P4** (panel technical plan) | Repository slug alone is insufficient; never select a ledger by "latest file"; cross-host is not assumed (SDP l.570; owner direction l.566: the v2.2 panel shows runs on the machine it runs on and says plainly that other machines are not covered) |
| D9.2 | Concurrent leads and handoff | **P4** | One writer per run ledger remains binding (L1 custody finding 1) |
| D9.3 | Shared ledger contract | **P4** | One compatible profile and fixtures for lead validator, panel reader and verifier; no second canonical ledger; do not revive the superseded v3 JSON design |
| D9.4 | Completion display | **P4** | Verified completion is read only from a current GV result; the result record itself waits on `completion-result-v1` (l.568) |
| D9.5 | Acceptance and non-PR work | **P4** | An inbox acknowledgment is never acceptance; human acceptance needs the owner's acceptance command (D4.4) |
| D9.6 | Freshness and invalidation | **P4** | Preserve timestamps and explicit stale/unavailable states; never retain an unqualified success badge after known invalidation |
| D9.7 | Hooks, config and packaging | **P4** | Panel telemetry hooks and stop-decision hooks have different roles; the classifier does not move into core |

Gate: **D9 is answered in the P4 panel technical plan, which starts after the three bounded critiques** (SDP l.564; charter §7 row for `#184`). D9 is **not** answered here, and no D9 answer is proposed here.

### 3.3 The three panel bounded critiques — recorded at P4

| Item | SDP record | Status |
| --- | --- | --- |
| Critique 1 — payload / distribution | SDP l.553; §9 prerequisites | **Open** |
| Critique 2 — source reuse / migration | SDP l.553; §9 prerequisites | **Open** |
| Critique 3 — multi-harness behavior | SDP l.553; §9 prerequisites | **Open** |

P-DEP records that "the three panel critiques stay open and gate **only** the panel technical plan" (l.788). The SDP is explicit that their completion has not been verified and that their status must not be inferred: "Do not restart a broad debate or infer that they were completed" (l.553). This ledger records them as open, at P4, with no inference about completion.

---

## 4. Mapping — retained SC / AC / prior requirements and deferrals

### 4.0 Rules applied to this table

1. **Tracker IDs are qualified.** Every *mapping* uses the fully qualified form `OWNER/REPO#N`. A **draft** ID never counts as a tracker ID; none appear below. Two short forms are used deliberately and are disambiguated here: (a) a short `#N` denotes an issue in `KHAEntertainment/showrunner` — the repository this ledger is bound to — while every other repository is always written qualified (`KHAEntertainment/marketplace#18`, `KHAEntertainment/marketplace#46`); (b) a `#N` immediately preceded by the word *milestone* is a tracker **milestone** number, not an issue number (the M1–M6 milestones are `#8`–`#13`; the v2.2.0 umbrella milestone is `#5`).
2. Where no qualified tracker ID exists, the row reads **"proposed — no tracker ID; owner intake required"** and names an **owner** and a **revisit** condition, per SDP l.644–l.647. "Later" alone is not sufficient.
3. Where the SDP approved a **no-further-work** rationale, the row carries that rationale **with its citation** and, where a residual obligation survives, the destination that keeps it visible.
4. **Parent and execution identity are preserved.** `#183` is P0-01; `#184` is P0-02 and consumes P0-01's bindings (activation packet `P0-02-issue-body.md.txt`; charter §4). Phases P0–P5 are planning labels; milestones `M1`–`M6` are tracker milestones `#8`–`#13`; `#132` is the v2.2.0 umbrella on milestone `#5`.
5. **Nothing is auto-added to a fixed goal.** A discovery or a milestone entry never enlarges an armed goal. New Issues enter the project backlog or a recorded amendment/new execution assignment (SDP l.23, l.648; charter §3). This ledger creates no Issue, adds no Issue to any goal set, and changes no milestone.

### 4.1 SC-1 – SC-9 (SDP l.514–l.522)

All nine contracts have a **P0 contract-specification package**: `KHAEntertainment/showrunner#184` (milestone M1 `#8`), which consumes this ledger's source/decision bindings. The delivery package and its owner are given per row.

| SC | Contract (SDP line) | P0 contract spec | Delivery package | Owner | Revisit / acceptance note |
| --- | --- | --- | --- | --- | --- |
| **SC-1** | identity/scope — Dev planning + backend adapter (l.514) | `KHAEntertainment/showrunner#184` | P1 | Dev planning owner | `assignment-v1`; P0 fixtures from the pinned charter/brief and Dev template; owner-bound values from settled D1 and D6 |
| **SC-2** | authority/continuation — Dev operation gates; Foreman grant owner for managed input (l.515) | `KHAEntertainment/showrunner#184` | P2 | Dev execution/recovery owner | `authorization-context-v1`; includes the Continue-after-rotation/start-expiry positive and the replayed-Begin negative (l.250) |
| **SC-3** | completion — GV owner (l.516) | `KHAEntertainment/showrunner#184` | P3 | GV owner | `completion-evidence-v1` (settled, D4.2) + `completion-result-v1` (**PENDING**, §3.1). Affected SC-3 work is blocked; no default proposed |
| **SC-4** | conformance — Dev workflow owner (l.517) | `KHAEntertainment/showrunner#184` | P2 | Dev workflow owner | `conformance-v1`; fixtures map the actual six-mark Foreman checklist to Dev applicability; counterpart receipt required before live I1 audit substitution |
| **SC-5** | provider/tool invocation — shared utility owner; domain owns verdict (l.518) | `KHAEntertainment/showrunner#184` | P1 | Shared utility owner | `provider-request-v1` / `provider-result-v1`; P1 absent/drift fallback and `needs_input`; no new service/SDK abstraction required merely to meet P1 |
| **SC-6** | records/config/tracker — each record owner; integration owner maps IDs (l.519) | `KHAEntertainment/showrunner#184` | P1 | Tracker integration owner | `project-binding-v1` + `record-link-v1`; P0 binds the actual config/bridge schemas; O-TRACK per-tracker operation/dedup/retry tests. Existing supported connections and the Foreman bridge are **not** removed by CUT-6 |
| **SC-7** | lifecycle/projection — source lead; panel/inventory own read adapters (l.520) | `KHAEntertainment/showrunner#184` | P4 | Source lead (Dev); panel and inventory own read adapters | `run-projection-v1` + `custody-reference-v1`; shared Python/Node fixtures in P4; pinned procedure/redacted history fixtures for I1; concurrent claim/replay tests required before O-LIFE adoption |
| **SC-8** | distribution/adoption — package/component maintainers (l.521) | `KHAEntertainment/showrunner#184` | P5 | Package/component maintainers | `component-receipt-v1`; P5 archive/install/path/catalog/backup tests; I1 package policy changes explicit; U1 later host independent of full Scout. Holds remain |
| **SC-9** | context/resume — handoff adapter + workflow recovery owner (l.522) | `KHAEntertainment/showrunner#184` | P2 | Handoff adapter owner + workflow recovery owner | `checkpoint-reference-v1` + `recovery-receipt-v1`; P2 per-adapter top-level/child/excluded coverage matrix; no claim that the adapter itself enforces workflow policy |

### 4.2 AC-01 – AC-09 (SDP l.719–l.727)

| AC | Required proof (owning phase) | Tracker mapping | Owner | Revisit / acceptance note |
| --- | --- | --- | --- | --- |
| **AC-01** planning/store (P1) | Artifact/native canonical plan, stable source/approval provenance, export single truth, direct plan/PRD distinction, document/foreign-plan intake, amendment invalidation, Phase 2/Issue/worker no-reask | **proposed — no tracker ID; owner intake required** | Dev planning owner | Revisit at M2 opening (milestone `#9`). Contract content: `KHAEntertainment/showrunner#184` (SC-1, SC-6). D1/D5/D6 decided |
| **AC-02** research/experience (P1) | Brownfield reaches a recommended plan without mandatory questions/fog exhaustion; consequential choices surfaced; provider read-only `needs_input`, pin/drift/missing fallback and A/B value evidence; C3 cost gate | **proposed — no tracker ID; owner intake required** | Dev planning/research owner | Revisit at M2 opening. C3 (neuroarxiv escalation) remains conditional on unresolved mechanism questions, C2 evidence/dogfood and separate cost approval (SDP l.84) |
| **AC-03** bounded execution (P2) | Every entry normalizes a frozen qualified scope; one loop in standalone/managed mode; no downgrade, unauthorized growth, infinite fix/retry cycle or false complete on exhaustion; protected H1–H4 bar | **proposed — no tracker ID; owner intake required** | Dev execution/recovery owner | Revisit at M3 opening (milestone `#10`). D2/D3/D7 decided |
| **AC-04** authority/gates (P2) | The entire historical gate inventory explicitly disposed; current-head/destination/QA/review/ASK/external-review checks; the D2 policy case set; all closing links/multi-PR and post-merge failure scope; veto and delayed question blocking | **proposed — no tracker ID; owner intake required** | Dev execution/recovery owner | Revisit at M3 opening. Gate inventory retained at SDP l.191–l.210 and disposed under D7.2; merge sketch under D2. Contract content: `#184` (SC-2, SC-4) |
| **AC-05** GV (P3) | Every positive/negative D4 case; multi-PR identity and qualified cross-repo identifiers, with cross-repository goals rejected at arming (D4.3); integrated criteria/evaluator evidence, fresh repo facts, readiness vs final closure, no writes; GV available and wired before G3 and rechecked at resume/pre-report | **proposed — no tracker ID; owner intake required** | GV owner | Revisit at M4 opening (milestone `#11`). **Blocked** on `completion-result-v1` pending owner approval (§3.1). Contract content: `#184` (SC-3) |
| **AC-06** continuity/lifecycle (P2) | SC-9 per-session load/child coverage; paused/rotation-due recovery, event dedup, unknown effect and owed replies, stale/emergency/missing/failed note and duplicate hook cases; P0/I1/O-LIFE lineage/custody claim evidence distinguished from same-session compaction | **proposed — no tracker ID; owner intake required** | Handoff adapter owner + workflow recovery owner | Revisit at M3 opening. Developing Codex/Pi adapters route to O-ADAPT and may not be claimed as parity (H1, D8) |
| **AC-07** panel (P4) | All restored UI/read-model/channel/config/board/source-lock/collector/15-degraded-state requirements; Python/Node schema conformance; 20 loss-free barrier rounds; separate concurrent runs and stale/inconclusive verification display | **proposed — no tracker ID; owner intake required** | Panel owner | Revisit at M5 opening (milestone `#12`). **Gated** by the three open panel critiques (§3.3) and by D9 answered in the P4 technical plan (§3.2). Contract content: `#184` (SC-7, SC-8) |
| **AC-08** inventory (P4) | Owned-inventory timeout **and** no open request, foreign report-only, unavailable listing refusal, distinct stop/archive/delete and safe custody transfer; managed timer conflict resolved not silently overridden | **`KHAEntertainment/showrunner#112`** (milestone M5 `#12`, OPEN) | Inventory owner (Dev) | Revisit at M5 opening. Depends on `#73` (CLOSED). D7.1 keeps the `#112` 60-minute and Foreman 4-hour timers separate; the managed timer conflict is resolved, not overridden. Contract content: `#184` (SC-7) |
| **AC-09** package/readiness (P5) | Manifested prerequisites, safe independent handoff adoption, package root/schema/version checks, tag/catalog/current-channel install/migration proof; supported standalone configuration works without coordinator/Scout/classifier/panel; developing adapters never falsely promoted; a static skill-layout check; the installer check confirms the manual installers and the plugin deliver the same suite | **Existing:** `KHAEntertainment/showrunner#182` (milestone M6 `#13`, OPEN) — suite namespace and README rename, including the validator and AC-09 layout/installer checks. **proposed — no tracker ID; owner intake required** for the P5 release-readiness package itself | Release/Dev integration owner; package/component maintainers | Revisit at M6 opening (milestone `#13`). D-DIST/U-GOV settled (l.789); Homebrew retired (ADR-018); npm path expected through the U1 CLI (`#181`) |

### 4.3 Prior requirements, retained work and deferrals (SDP l.731–l.753, l.755)

| # | Prior requirement (SDP line) | Disposition carried | Tracker mapping | Owner | Revisit |
| --- | --- | --- | --- | --- | --- |
| 1 | WP-0 credits; WP-E hook refusal; WP-R release (l.731) | Retain adopted credits and co-install caveats; fail-closed refusal/no bypass; existing release/catalog workflow | **proposed — no tracker ID; owner intake required** (P1/P5) | Dev integration owner / release owner | P1 and P5 openings. AC-02/04/09; A7 |
| 2 | WP-A1, WP-A2, WP-A3, original planning headline, no v2.1.2 intrusion (l.732) | Retain and revise to preparatory integration scope | **proposed — no tracker ID; owner intake required** (P1) | Dev planning owner | M2 opening. AC-01/02; D1/D5/D6 |
| 3 | Backend detector/artifact output, native tracking/promotion, amendments, direct Traycer production, session/harness provenance (l.733) | Retain settled routing; exact output/lifecycle decisions still open | **proposed — no tracker ID; owner intake required** (P0/P1). Contract content: `KHAEntertainment/showrunner#184` (SC-1, SC-6) | Dev planning owner | M2 opening. D1/D6.5 settle promotion to `docs/plans/<YYYY-MM-DD>-<slug>.md` |
| 4 | WP-B1 ticket/fog/frontier machinery and mandatory per-turn/zero-fog approval/assertions (l.734) | **Rejected as default.** Stale rules/cases removed from reconciled docs. Opt-in reassessment → O-PLAN | **Approved no-further-work rationale for v2.2** (SDP l.734): rejected as default; no implied revival. Residual obligation (reconciled docs) → row 21 (A3/A4). Reassessment destination: **O-PLAN**, `KHAEntertainment/showrunner#173` | Planning owner (O-PLAN) | Revisit only after concrete dogfood misses, a recorded user opt-in and a bounded value comparison (l.698) |
| 5 | WP-B2 tracker map (l.735) | **Already deferred.** No competing Foreman map | **Approved no-further-work rationale for v2.2** (SDP l.735). Destination: **O-PLAN**, `KHAEntertainment/showrunner#173` | Planning owner (O-PLAN) | Same O-PLAN trigger as row 4 |
| 6 | WP-C1, WP-C2, WP-C3 (l.736) | Retain built-in research and pinned optional provider; C3 separately conditional, not a full Scout dependency | **proposed — no tracker ID; owner intake required** (P1) | Dev planning/research owner | M2 opening. AC-02; SC-5. C3 needs separate cost approval |
| 7 | WP-G1, plan→freeze→execute→report; source/PRD/Issue/milestone entry (l.737) | One bounded executor, two input modes; interactive phases remain | **proposed — no tracker ID; owner intake required** (P2) | Dev execution owner | M3 opening. AC-03/04; D2/D3/D7 |
| 8 | WP-G2/GV (l.738) | Advance contracts; required read-only stdlib verifier remains in core | **`KHAEntertainment/showrunner#184`** for the P0 contract and fixture provenance; **proposed — no tracker ID; owner intake required** for P3 delivery | GV owner | P0 exit, then M4 opening. AC-05; D4 approved. `completion-result-v1` pending (§3.1) |
| 9 | WP-G3 pilot (l.739) | Retain standalone pilot of declared configuration with handoff; prepare managed fixtures but make no live adapter claim | **proposed — no tracker ID; owner intake required** (P3) | GV / pilot owner | M4 opening. AC-03/05/06; safety bar unchanged |
| 10 | WP-G4, WP-G4b, WP-G5 and the Respan shortlist (l.740) | **Approved no-further-work rationale for v2.2 delivery** (SDP l.740, CUT-4 approved l.774): the delivery is deferred; Clef family / Jev direction preserved **without activation** | **Approved no-further-work rationale** with citation (CUT-4, l.774). Destination: **O-STOP** — **proposed — no tracker ID; owner intake required** | Dev safety/utility owner | O-STOP adoption: protected-stop tests, compatible hooks, shadow/eval evidence and the G5 threshold (l.692). No activation from this plan |
| 11 | Gate sketch Tier A/B/C and merge-sketch details (l.741) | Entire inventory and carried policy retained in §5; unresolved gates/policy values not delegated | **proposed — no tracker ID; owner intake required** (P0/P2) | Dev integration owner | M3 opening. AC-04; D2/D7. Gate inventory at l.191–l.210 |
| 12 | Cross-harness autonomy survey (l.742) | **Approved no-further-work rationale** (SDP l.742; D8 settled l.784): no separate survey before G1; reference workflows are evidence, never invoked dependencies | **Approved no-further-work rationale** with citation (D8, l.784). Native workflow qualification → **O-ADAPT** — **proposed — no tracker ID; owner intake required** | Backend/handoff owner | O-ADAPT: adapter evidence/authority first, post-merger minimal-tooling dogfood after I1 (l.696) |
| 13 | Restored workspace panel, `#85` and the bounded critiques (l.743) | Full scope retained | `#85` — **CLOSED** (`KHAEntertainment/showrunner#85`, milestone v2.1.2), delivered via PR #129. Panel delivery: **proposed — no tracker ID; owner intake required** (P4). Coordinator views → I1 | Panel owner | M5 opening; **gated** by the three open critiques (§3.3) and D9 (§3.2). AC-07 |
| 14 | `#112` / `#73` inventory (l.744) | Retain ownership/timeouts and safe unavailable handling | **`KHAEntertainment/showrunner#112`** (OPEN, M5 `#12`); `#73` — **CLOSED** | Inventory owner | M5 opening. AC-08; D7 policy applicability |
| 15 | D5 / `#104` broader Linear intake/sync (l.745) | Supplied/current capability and existing bridge compatibility retained; approved CUT-6 new-live-work deferral → O-TRACK; D5 provenance settled | **`KHAEntertainment/showrunner#104`** (OPEN, unplaced) — **proposed — no tracker ID; owner intake required** for the O-TRACK preparation package | Tracker integration owner | O-TRACK adoption gates new functionality; later scope, operations, timing and implementation need approval. AC-01/09; SC-6 |
| 16 | Shared utility and dedicated-installer direction (l.746) | Approved CUT-5: contract preparation → P0/P5; U1 independent of full Scout may follow I1; dedicated npm installer stays held under O-DIST; Homebrew retired (ADR-018) | **`KHAEntertainment/showrunner#153`** (OPEN, unplaced — "U1: Unified Showrunner CLI"). Contract content: `KHAEntertainment/showrunner#184` (SC-5/6/8) | Shared utility / distribution owners | U1 may follow integration; required before claiming a unified utility experience. Later implementation, packaging and release timing need approval |
| 17 | Structured lifecycle registration/status/history/successor/dashboard ambition (l.747) | Partial existing record/procedure satisfaction; explicit v2.2 contracts/read projection; remaining executable service deferred to O-LIFE (L1 settled) | **proposed — no tracker ID; owner intake required** (O-LIFE) | Lifecycle owner | O-LIFE adoption: concurrent claims/history/retention/authorization tests required. Section 7; AC-06/07; L1 |
| 18 | Handoff addition (l.748) | Shared, independently packaged continuity → P2; developing adapters → O-ADAPT | **proposed — no tracker ID; owner intake required** (P2). Contract content: `KHAEntertainment/showrunner#184` (SC-9) | Handoff owner | M3 opening. AC-06; outside CUT-4 |
| 19 | Homebrew retirement / npm / npx earlier follow-up (l.749) | Homebrew retired by ADR-018 on 2026-11-01, superseding the earlier hold; npm and npx reactivation stays O-DIST and is **not** a release requirement | **Approved no-further-work rationale** for Homebrew (SDP l.749; ADR-018; `#70` and `#67` closed as not planned, l.647). npm path → **`KHAEntertainment/showrunner#181`** (OPEN, unplaced) | Distribution owner | O-DIST: only on explicit reactivation; U1 interface/compatibility and separate migration policy. No publication |
| 20 | A1/A2 (l.750) | Approved D4 resolves design defects, **not implemented proof** | **proposed — no tracker ID; owner intake required** (P3). Contract content: `KHAEntertainment/showrunner#184` | GV owner | M4 opening. AC-05 |
| 21 | A3/A4 (l.751) | Rewrite stale repository plans and conflicting payload authority/planning wording **after authorization**; reuse vetted reconciliation work | **proposed — no tracker ID; owner intake required** (P0/P1/P2) | Dev integration owner | M2/M3 opening. AC-01/04. `docs/plans/**`, `PROJECT_CONTEXT.md` and `docs/architecture.md` are a **serialized shared surface** (charter §6) — Foreman go required; the Dev routing/review/authorization-policy surface is not edited by this lane |
| 22 | A5 (l.752) | Mixed prerequisites remain an explicit checkpoint; no waived dependencies | **`KHAEntertainment/showrunner#183`** — this ledger (P0-01). P0 receipt required | M1 orchestrator | P0 exit. Recorded in §1.1 |
| 23 | A6/A7 (l.753) | `#112` retained; new `#104` live delivery deferred under CUT-6; central catalog/release procedure retained | **`KHAEntertainment/showrunner#112`**, **`KHAEntertainment/showrunner#104`**, and the cross-repo catalog item **`KHAEntertainment/marketplace#18`** (README drift, tracked under `#132`) | Inventory owner; tracker integration owner; release owner | M4/M5 openings and O-TRACK. AC-08/09; existing bridge compatibility preserved |
| 24 | Old acceptance bullets 1–12, mapped in their original order (l.755) | Retained as a crosswalk onto AC-01–AC-07/AC-09; the full D4 negative suite and the panel source gates are retained, not replaced by these labels | **proposed — no tracker ID; owner intake required** — resolved by the AC rows in §4.2 | Dev integration owner | Resolved when the AC destination packages open (M2–M6) |

### 4.4 Named post-v2.2 destinations (SDP l.689–l.700)

| Destination | Scope | Tracker mapping | Owner | Revisit / gate |
| --- | --- | --- | --- | --- |
| **I1** — Foreman repository integration | Package/namespace, actual producer adapter, current bridge compatibility, live managed mode, supervisory panel projection | **proposed — no tracker ID; owner intake required** | Dev/Foreman integration owners | Starts only after V2-R, counterpart agreement and explicit merger authority. RI-R requires actual live contract/fixture evidence, single writer/custody and package compatibility |
| **U1** — Common utility host and component management | Supported human/agent interactions, discovery/config/status, install/update management | **`KHAEntertainment/showrunner#153`** (OPEN, unplaced) | Utility/distribution owners | Not a repository-integration prerequisite; required before claiming a unified utility experience. Host must work without full Scout. CUT-5: later implementation/packaging/release timing need approval |
| **U2** — Shared intelligence and Scout modules | Deterministic intake/evidence/delivery; shared provider/redaction/budget infrastructure with domain-specific decisions | **proposed — no tracker ID; owner intake required** | Scout + Dev conformance owners | After U1 interfaces plus Scout design/authority/store decisions. Optional-module adoption gate, not V2-R or RI-R |
| **O-STOP** — Optional stop/compliance adapters | G4/G4b/G5 staged hook/decision adapters, shared GV, redaction/eval logs | **proposed — no tracker ID; owner intake required** (CUT-4 deferral, l.774) | Dev safety + utility owners | ADOPT requires protected-stop tests, compatible hooks, shadow/eval evidence and the G5 threshold. No activation from this plan |
| **O-TRACK** — Live tracker interoperability | New `#104` live intake/post-merge sync deferred under CUT-6; SC-6 identity/provenance/writer/dedup/retry/authority contracts | **`KHAEntertainment/showrunner#104`** (OPEN, unplaced) + **proposed — no tracker ID; owner intake required** for the O-TRACK preparation package | Tracker integration owner | ADOPT gates new write paths; no tracker writes authorized. Existing supported connections and the Foreman GitHub-to-Linear bridge remain |
| **O-LIFE** — Structured lifecycle operations | Session registration/status API, historical lineage, successor claims, read projections | **proposed — no tracker ID; owner intake required** | Lifecycle owner | Concurrent claims/history/retention/authorization tests required before adoption. Blocks advertising automated lifecycle operations, not V2-R/RI-R if existing custody gates pass |
| **O-DB** — Migration safety integration | Common grant mapping, synthetic-LOW fix, collector/Cloud/rehearsal/recovery/authority/writer controls | **proposed — no tracker ID; owner intake required** | Existing migration utility owner + designated DB execution owner | Requires explicit lifting of the relevant holds and its own acceptance. Blocks only this component's production adoption |
| **O-ADAPT** — Additional harness and minimal-tooling dogfood | Developing Codex/Pi coverage; later native/minimal-tooling workflow qualification | **proposed — no tracker ID; owner intake required** | Backend/handoff owners | Adapter evidence/authority first; post-merger minimal-tooling dogfood after I1. Blocks claims for each unsupported route, nothing else |
| **O-DIST** — Held distribution reconsideration | Dedicated npm installer channel, only on explicit reactivation; U1 interface/compatibility and separate migration policy | **`KHAEntertainment/showrunner#181`** (OPEN, unplaced) | Distribution owner | No V2-R/RI-R prerequisite. `#181` is deferred until after v2.2.0; its expected form is the U1 CLI's npm package (`#153`), not a skills-only `npx skills` channel. D-DIST/U-GOV settled (l.789) |
| **O-PLAN** — Opt-in deeper planning assessment | B1/B2 experiment only after concrete dogfood misses, recorded user opt-in and a bounded value comparison | **`KHAEntertainment/showrunner#173`** (OPEN, unplaced) | Planning owner | No V2-R/RI-R gate. Also holds `#173` (fresh plan reviewers), scheduled after v2.2; its fixtures, pilot and memory-isolation requirement stay with it |
| **O-PORTAL** — Spotify Portal integration | `#78` org-context evidence source; `#77` read-diversion route check | **`KHAEntertainment/showrunner#78`** and **`KHAEntertainment/showrunner#77`** (both OPEN, unplaced) | Dev research owner | Outside v2.2; blocks nothing in V2-R or RI-R. `#78`'s pinned CLI version and ADR number are dated, so its spec is refreshed first. Revisit: a working Portal CLI release, or the first Dev host with a read-diverting hook |
| **O-SEC** — Optional security-audit companion | Cloudflare-derived `s`ecurity-audit companion with opt-in workflow gates, shipped under the `dev` namespace | **`KHAEntertainment/showrunner#172`** (OPEN, unplaced) | Dev security owner | Outside v2.2; blocks nothing in V2-R or RI-R. Removed from the v2.2.0 milestone by owner decision 2026-11-02. Revisit: the owner schedules it after V2-R. Before scheduling: packaging/install under CUT-5/U1, the weekly upstream monitor's authority, whether a required security result is a `checks` entry, whether a required security gate blocks a bounded merge (D2), and whether its lanes count toward D3's dispatch cap |

---

## 5. Reconciliation — `#132` umbrella and `#182` namespace design input

### 5.1 `#132` — v2.2.0 release tracker (umbrella)

| Field | Recorded value |
| --- | --- |
| Qualified ID | `KHAEntertainment/showrunner#132` |
| State | OPEN · milestone `v2.2.0` (`#5`) · label `enhancement` |
| Role | **Umbrella / release tracker.** "This release tracker stays in v2.2.0 as the umbrella." It consolidates the planning view; closing it means each tracker's PR has landed and v2.2.0 can be cut. It blocks nothing else. |
| Identity preserved | `#132` is the v2.2.0 umbrella on milestone `#5`. It is **not** a fixed-goal issue and is **not** an execution target for this lane. |
| M1 membership it names | "M1 admission Issues: `#183` and `#184`." — this ledger is `#183` (P0-01); `#184` (P0-02) consumes it |
| Milestone structure it names | M1 baseline/contracts, M2 planning/research, M3 executor/continuity, M4 GV/pilot, M5 panel/inventory, M6 release readiness — matching tracker milestones `#8`–`#13` and the charter's tracker record |
| Umbrella-milestone contents read on 2026-11-04 | `#132` OPEN, `#84` OPEN, `#59` OPEN, `#43` OPEN, `#37` OPEN, `#17` OPEN, `#133` CLOSED (6 open / 1 closed on milestone `#5`) |
| Items `#132` references outside M1–M6 | `#17` (bug, P2 — read-only AST guard residual bypass), `#37`, `#43`, `#59`, `#84`, `#112` (→ M5 `#12`), `#116` (→ M6 `#13`), `#124` (→ M6 `#13`), and the cross-repo `KHAEntertainment/marketplace#18` (marketplace README drift) |
| Disposition | **Retained as the umbrella.** No new Issue is filed under it by this ledger, and nothing in it is added to a fixed goal. |

### 5.2 `#182` — namespace design input

| Field | Recorded value |
| --- | --- |
| Qualified ID | `KHAEntertainment/showrunner#182` |
| State | OPEN · milestone `M6 — 2.2 release readiness` (`#13`) · label `enhancement` |
| Title | Move the suite to the `dev` namespace and rename the README skill to `/dev:readme-authoring` |
| Role | **Namespace design input** for this ledger. It is the v2.2 package work that carries the owner direction recorded at SDP l.647 (suite naming under the `dev` namespace) and l.648 (installer coverage) into an executable acceptance set. |
| Identity preserved | `#182` sits in **M6** (`#13`), not in M1. It is **not** part of this lane's scope and is **not** added to any fixed goal. It is referenced here as the tracker home for a requirement the SDP retains (AC-09, suite layout and installer checks). |
| Scope it carries | Plugin rename `dev-skill` → `dev` with install migration and central catalog entry; `skills/readme` → `skills/readme-authoring`; Phase 5 badge slot and `showcase_badge.py` (`readme_skill_missing`) find the README skill by suite name; manual installers install the whole suite with a `dev-` folder prefix where there is no plugin namespace; validator and release checks cover each suite skill |
| Related IDs it names | `#163` (CLOSED, v2.1.4 — the README skill it renames), `#181` (npm install path, deferred → O-DIST), `#132` (umbrella) |
| Out of scope (its own text) | Foreman, Architect and Scout names arrive with repository integration (I1) |
| Design-time caveat carried | "How the `dev` namespace loads in Claude Code, and the exact prefix form on harnesses without namespaces, are confirmed at design time, not assumed." — confirmed at design time, not here |
| Disposition | **Retained as a qualified tracker destination.** AC-09's suite-layout and installer-coverage obligations map to `#182`. No other change to `#182` is proposed or implied by this ledger. |

---

## 6. Holds and dispositions

### 6.1 Both hold lists are carried — no list is selected over the other

The M1 lead flagged that `#183` AC4 and charter §4 list different held items. **Both are recorded here.** Every disagreement is listed explicitly in §6.2 rather than resolved by this lane.

**List A — `#183` AC4 ("retain explicit holds for `#37`/`#43`/`#59`/`#173`/`#175` and deferred `#181`/U1/O-\*")**

| ID | Hold as stated in `#183` AC4 | Live tracker state (2026-11-04) | Owner | Revisit / release condition |
| --- | --- | --- | --- | --- |
| `KHAEntertainment/showrunner#37` | Explicit hold | OPEN · milestone `v2.2.0` (`#5`) · labels `enhancement`, `P2` | Dev push-account verification owner | "Held until the user discusses it; do not schedule before that" (`#132`). Needs an SSH key registered for KHAEntertainment on this machine to actually run |
| `KHAEntertainment/showrunner#43` | Explicit hold | OPEN · milestone `v2.2.0` (`#5`) · labels `enhancement`, `P3` | Planning/experimentation owner | "Parked on v2.2.0; the run touches global OpenCode config and needs the user OK to start" (`#132`) |
| `KHAEntertainment/showrunner#59` | Explicit hold | OPEN · milestone `v2.2.0` (`#5`) · labels `enhancement`, `P3` | Dev conformance owner | "Effectively closed as scoped" — Kimi/Qwen switched off in Traycer and removed from the agent selection guide; kept open as a placeholder for any future non-default provider probe; not on a v2.2 critical path (`#132`) |
| `KHAEntertainment/showrunner#173` | Explicit hold | OPEN · unplaced · label `enhancement` | Planning owner | Held until v2.2 ships (charter §7 policy-holds row: "`#173` extra EGM work held until v2.2 ships"). Destination **O-PLAN** (l.698); removed from the v2.2.0 milestone by owner decision 2026-11-02 |
| `KHAEntertainment/showrunner#175` | Explicit hold | OPEN · unplaced · label `enhancement` | Owner | **Strictly held** (charter §4: "`#175` (strictly held)"; policy-holds row: "`#175` strictly held"). Label on the issue: "[ON HOLD: OWNER AUTHORIZATION REQUIRED]". No destination named in the SDP; not listed in the O-\* destinations |
| `KHAEntertainment/showrunner#181` | Explicit **deferral** | OPEN · unplaced · label `enhancement` | Distribution owner | Deferred until after v2.2.0 (owner decision 2026-11-02). Destination **O-DIST** (l.697); expected form is the U1 CLI's npm package (`#153`), not a skills-only `npx skills` channel |
| **U1** | Explicit deferral | — | Shared utility / distribution owners | CUT-5 approved (l.775): contracts now, CLI may follow integration. U1 is **not** a repository-integration prerequisite; required before claiming a unified utility experience. Tracker home: `KHAEntertainment/showrunner#153` |
| **O-\*** | Explicit deferrals | — | Per destination (§4.4) | O-STOP, O-TRACK, O-LIFE, O-DB, O-ADAPT, O-DIST, O-PLAN, O-PORTAL, O-SEC, U2, I1 |

**List B — M1 charter §4 ("Held, unplaced: `#77`, `#78`, `#104`, `#153`, `#172`, `#173` (held until v2.2 ships), `#175` (strictly held), `#181`")**

| ID | Charter §4 disposition | Live tracker state | Destination | Owner | Revisit |
| --- | --- | --- | --- | --- | --- |
| `KHAEntertainment/showrunner#77` | Held, unplaced | OPEN · unplaced | **O-PORTAL** (l.699) | Dev research owner | Revisit: a working Portal CLI release, or the first Dev host with a read-diverting hook. Outside v2.2; blocks nothing in V2-R/RI-R |
| `KHAEntertainment/showrunner#78` | Held, unplaced | OPEN · unplaced | **O-PORTAL** (l.699) | Dev research owner | Its pinned CLI version and ADR number are dated, so the spec is refreshed first. Owner-reported 2026-11-01: the Portal CLI is broken, fixes pending from Spotify, so the integration cannot be tested |
| `KHAEntertainment/showrunner#104` | Held, unplaced | OPEN · unplaced | **O-TRACK** (l.693) | Tracker integration owner | CUT-6 approved (l.776): new live intake/post-merge sync deferred. Release disposition is CUT-6, **not** an inferred authorization from the issue's existence (SDP l.51). ADOPT gates new write paths |
| `KHAEntertainment/showrunner#153` | Held, unplaced | OPEN · unplaced · label `enhancement` | **U1** (l.690) | Shared utility / distribution owners | CUT-5: contracts defined during merger preparation; actual CLI implementation, packaging and release timing need later approval. U1 may follow I1 |
| `KHAEntertainment/showrunner#172` | Held, unplaced | OPEN · unplaced · label `enhancement` | **O-SEC** (l.700) | Dev security owner | Outside v2.2; blocks nothing in V2-R/RI-R. Removed from the v2.2.0 milestone by owner decision 2026-11-02. Revisit: the owner schedules it after V2-R. Pre-scheduling conditions at l.700 |
| `KHAEntertainment/showrunner#173` | Held until v2.2 ships | OPEN · unplaced | **O-PLAN** (l.698) | Planning owner | Scheduled after v2.2; fixtures, pilot and memory-isolation requirement stay with O-PLAN |
| `KHAEntertainment/showrunner#175` | Strictly held | OPEN · unplaced | **No destination named in the SDP** | Owner | Requires owner authorization. Not among the named post-v2.2 destinations (l.689–l.700) |
| `KHAEntertainment/showrunner#181` | Held | OPEN · unplaced | **O-DIST** (l.697) | Distribution owner | Deferred until after v2.2.0; expected form is the U1 CLI's npm package (`#153`) |

### 6.2 Explicit disagreements between the two lists

Recorded, not resolved. Resolution is an owner/foreman matter; this lane neither picks a list nor relaxes a hold.

| # | Disagreement | List A (`#183` AC4) | List B (charter §4) | Live tracker | What this ledger does |
| --- | --- | --- | --- | --- | --- |
| **D-a** | `#37`, `#43`, `#59` hold status | Listed as **explicit holds** | **Absent** from the held list | All three **OPEN** in milestone `v2.2.0` (`#5`) with `P2`/`P3` labels | Carries both readings. Records that `#132` describes `#37` as held pending user discussion, `#43` as parked pending user OK, and `#59` as effectively closed as scoped. **Does not** assert that these are held, nor that they are not |
| **D-b** | `#77`, `#78`, `#104`, `#153`, `#172` hold status | **Absent** | Listed as **held, unplaced** | All five **OPEN** and unplaced | Carries both readings; each is mapped to its named destination (§6.1 List B, §4.4) so the obligation stays visible. **Does not** extend or remove the charter hold |
| **D-c** | `#173` | Explicit hold | Held until v2.2 ships | OPEN, unplaced | **Consistent.** Both readings recorded; the charter's "until v2.2 ships" condition is carried with it |
| **D-d** | `#175` | Explicit hold | Strictly held | OPEN, unplaced | **Consistent.** Both recorded as the strictest hold in either list; no destination named in the SDP |
| **D-e** | `#181` | Explicit **deferral** | **Held** | OPEN, unplaced | Terminology differs (deferral vs hold). Carried as one deferred item in **O-DIST** with the deferral condition "until after v2.2.0". Both terms recorded |
| **D-f** | Placement of `#37`, `#43`, `#59`, `#84`, `#17` | Not mentioned | Not mentioned, but the charter's placement list assigns `#112`→M5, `#116`/`#124`/`#182`→M6, `#132`→milestone `#5` | All five remain in milestone `v2.2.0` (`#5`) with **no** M1–M6 milestone | **Recorded as an unstated placement gap**: these Issues sit in the umbrella milestone only. The M1–M6 milestone structure does not cover them. Not resolved here — no milestone change is made or proposed |
| **D-g** | `#132`'s own framing | AC4 requires reconciling `#132` as umbrella | §4: "`#132` stays the v2.2.0 umbrella (milestone `#5`)" | OPEN, milestone `v2.2.0` (`#5`) | **Consistent.** Both recorded |

### 6.3 Holds that apply to this lane itself

| Hold | Source | Effect on this lane |
| --- | --- | --- |
| Bootstrap-only activation GO; no workers, implementation, tests, PRs, merges or pilot | `ruling-activation-bootstrap-2026-11-04` | Narrowed by `ruling-m1-partial-go-2026-11-04`: "Approve M1 for the read-only step and `#183` now". This lane is the `#183` read-only step, extended by the lead's own assignment to a docs-only PR. No other hold is lifted by this ledger |
| No worker dispatch, source/specification edits, tests/probes, PRs, merges, releases or installs | Charter §4 | This lane creates **one new documentation file** and one PR. It dispatches no worker, runs no test or probe, and merges nothing |
| Pending D4/C1–C5 policy and panel-specific gates stay pending; all existing holds remain | `ruling-policy-holds-2026-11-04` | `completion-result-v1` recorded as pending (§3.1); D9 and the three critiques recorded at P4 (§3.2, §3.3) |
| Serialized shared surfaces (Dev routing/review/authorization policy; project policy and architecture record; payload validation/installers/release metadata; assignment/evidence/ledger interfaces; panel hooks/read model) | Charter §6 | This lane touches **none** of them. `docs/v2.2/admission-ledger.md` is a new path outside every serialized surface |
| Required Kilo, deterministic risk floors, CI ownership, current Dev 2.1.4 gates | `#183` scope; charter §6 | Preserved unchanged. This lane lowers no floor and adds no CI obligation |
| Scope/acceptance changes return to the owner | `#183` scope; charter §6 | The only deviations are recorded in §9 and reported to the lead |

---

## 7. No-auto-addition and execution-identity statement

- **Nothing is auto-added to a fixed goal.** No Issue is added to any goal set, milestone or milestone candidate by this ledger. A discovery or a later milestone entry never enlarges an armed Dev goal; new work enters the project backlog or a recorded amendment/new execution assignment (SDP l.23, l.648; charter §3).
- **Parent and execution identity is preserved.** `#183` = P0-01 (this ledger). `#184` = P0-02, which consumes P0-01's source/decision bindings. `#132` = v2.2.0 umbrella on milestone `#5`; it is a consolidation view, not an execution target. `#182` = namespace design input on M6 (`#13`), outside this lane.
- **Draft IDs are not tracker IDs.** No draft, plan-phase or local placeholder identifier is used as a tracker ID anywhere in this ledger. Every `OWNER/REPO#N` reference is a live issue in `KHAEntertainment/showrunner` (or `KHAEntertainment/marketplace#18`).
- **This ledger grants no authority.** It admits no implementation, no merge, no install, no release, no catalog action, no provider, no tracker write, and no hold removal. It does not modify `#183`, `#184`, `#132`, `#182` or any other tracker item.

---

## 8. Coverage index

Every token family the SDP retains at this revision, and where this ledger records it. The ad-hoc coverage-check output is attached to the PR body for `#183`.

| Token family | SDP location | Recorded in |
| --- | --- | --- |
| `D1`, `D2`, `D3` | l.85, l.252, l.286; l.777–l.779 | §2, §2.1 |
| `D4.1`–`D4.4`, `completion-result-v1`, `completion-evidence-v1` | l.358–l.424, l.350, l.381, l.516, l.780 | §2, §3.1 |
| `D5` | l.162, l.781 | §2 |
| `D6.1`–`D6.6` | l.98–l.160, l.782 | §2 |
| `D7.1`, `D7.2` | l.492, l.212, l.783 | §2 |
| `D8` | l.309, l.784 | §2 |
| `D9.1`–`D9.7` | l.562–l.592, l.785 | §2, §3.2 |
| `H1` | l.453, l.787 | §2 |
| `L1` | l.479, l.786 | §2 |
| `P-DEP` | l.788 | §1.1, §2 |
| `CUT-4`, `CUT-5`, `CUT-6` | l.596, l.618, l.173; l.774–l.776 | §2, §4.3 |
| `R-RET` | l.430, l.773 | §2 |
| `D-DIST` / `U-GOV` | l.789 | §2, §6.1 |
| `SC-1`–`SC-9` | l.514–l.522 | §4.1 |
| `AC-01`–`AC-09` | l.719–l.727 | §4.2 |
| Prior-requirement rows and old acceptance bullets 1–12 | l.731–l.755 | §4.3 |
| `WP-0`, `WP-A1`, `WP-A2`, `WP-A3`, `WP-B1`, `WP-B2`, `WP-C1`, `WP-C2`, `WP-C3`, `WP-E`, `WP-G1`, `WP-G2`, `WP-G3`, `WP-G4`, `WP-G4b`, `WP-G5`, `WP-R` | l.731–l.740 | §4.3 |
| `A1`–`A7` | l.750–l.753 | §4.3 |
| `I1`, `U1`, `U2`, `O-STOP`, `O-TRACK`, `O-LIFE`, `O-DB`, `O-ADAPT`, `O-DIST`, `O-PLAN`, `O-PORTAL`, `O-SEC` | l.689–l.700 | §4.4, §6.1 |
| `#17`, `#37`, `#43`, `#59`, `#73`, `#74`, `#77`, `#78`, `#84`, `#85`, `#104`, `#112`, `#116`, `#124`, `#132`, `#153`, `#163`, `#172`, `#173`, `#175`, `#181`, `#182`, `#183`, `#184` | tracker | §1.1, §4.2, §4.3, §5, §6.1 |
| `KHAEntertainment/marketplace#18`, `KHAEntertainment/marketplace#46` | tracker / SDP l.46 | §4.3 row 23, §1.1 |
| `KHAEntertainment/handoff` (v0.1.0, v0.2.1) | l.38, l.455 | §1 A20, §4.3 row 18 |

---

## 9. Deviations and known limitations of this record

1. **No `docs/v2.2/` subtree existed before this file.** The repository's `docs/` directory is flat (`AUDIT.md`, `RELEASING.md`, `architecture.md`, `backends.md`, `badges.md`, `dogfooding.md`, `feature-log.md`, `guarantees.md`, `install.md`, plus `assets/`, `pilot/`, `plans/`, `templates/`). This ledger introduces the first version-scoped subtree. The repository convention for **promoted plans** is `docs/plans/<YYYY-MM-DD>-<slug>.md` (D6.5, SDP l.142) — and `docs/plans/**` is a **serialized shared surface** (charter §6, "Project policy and architecture record"). The admission ledger is a receipt/traceability record, not a promoted plan, so `docs/v2.2/admission-ledger.md` is used: it keeps the record off every serialized path. The new-subtree pattern is a deviation from the flat `docs/` layout and is recorded here for the owner.
2. **Tracker states are as of 2026-11-04** and can move. The live tracker wins over any statement in this ledger.
3. **Charter §7 does not enumerate D1–D3.** They are carried as settled on the strength of the SDP body headings and the §14 owner-decision table (see §2.1). This is a difference in the charter's *summary*, not doubt about the SDP.
4. **The two hold lists disagree** and this ledger does not resolve them (§6.2). No hold is relaxed, tightened or extended here.
5. **Milestone `#5` (v2.2.0) contains Issues that no M1–M6 milestone covers** (`#17`, `#37`, `#43`, `#59`, `#84`). Recorded as gap **D-f**; no milestone change is made or proposed.
6. **Nothing was executed.** Every claim in this ledger maps to a read. No test, fixture, validator, installer, release check, live probe or CI job was run by this lane.
7. **`docs/v2.2/` is a new path with no repository precedent** — see deviation 1. If the owner prefers a different location, this file moves as a single path change with no content edit.

---

## 10. Provenance of this document

| Field | Value |
| --- | --- |
| Authored by | M1 `#183` implementer (Traycer agent `ca9e3448-20ac-455c-a1a6-ed38e3122621`), under lead `51759e69-6339-4c53-b998-c7c2907466df` |
| Issue | `KHAEntertainment/showrunner#183` (M1 package P0-01) |
| Branch | `docs/183-v2.2-p0-admission-ledger`, based on `83631ce10309a3c47479ff96df70e0e2ff7110f2` |
| Canonical source | SDP SHA-256 `dae53a66f79f53d3ddedacff4c206fa034dcb5fbefde7fa1c0b86f4056529d81`, 789 lines |
| Authority | `ruling-m1-partial-go-2026-11-04` (M1 read-only step and `#183` approved); `ruling-policy-holds-2026-11-04`; `ruling-activation-bootstrap-2026-11-04` (narrowed) |
| Scope | One new documentation file. No implementation, no execution, no tracker mutation, no authority grant |
