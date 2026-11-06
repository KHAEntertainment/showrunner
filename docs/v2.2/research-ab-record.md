---
title: "Showrunner v2.2 P1 — C1/C2 A/B value evidence record"
kind: spec
comments: none
---

# Showrunner v2.2 P1 — C1/C2 A/B value evidence record

Implements `KHAEntertainment/showrunner#207` (M2 package **P1-02**), criterion 4 of the M2 charter §2. This is a **text-only evidence record**: it admits no behavior and grants no promotion. The three efforts below were run and are recorded as **inconclusive** (§8); no arm comparison, no totals and no ranking follow from them.

**Not an input to U1.** The six research notes (`artifacts/u1-research-ab/effort-{1,2,3}/{x,y}.md`) and the summaries (the three effort pages and `artifacts/u1-research-ab/quick-review`) are **not** inputs to U1. No U1 design, plan, Issue or decision may cite or rely on them (`ruling-207-ab-inconclusive-2026-11-06`).

## 1. Authority

| Source | Citation |
| --- | --- |
| Canonical plan (SDP) | `artifacts/v2-2-development-plan/index.md` (Showrunner task `6266293c-edb0-48f6-b8f6-ddd561de1f05`), SHA-256 `7177580c8429d6e5f8f07e6138de72506ac7a419e9697f5102f842d43a93315b`, 819 lines — **SDP l.81**: "Run the A/B value gate over three real planning efforts before superiority claims/promotion. Record consequential misses, repeated/low-value questions, rounds, time and user burden." |
| M2 charter | `charters/p1-planning-and-research/index.md` §2, criterion 4: "Three-real-effort A/B value evidence recorded before any superiority/promotion claim; C3 only on unresolved mechanisms, C2 evidence and separate cost approval or an explicit permitted disposition." |
| Owner ruling | `ruling-207-pin-2026-11-05` (2026-11-05) — the C2 pin `advise-project-approach`, directory digest `sha256:2386030e…896c`, is owner-confirmed and C2 may activate against it. |
| Owner ruling | `ruling-207-ab-u1-2026-11-05` (2026-11-05) — the efforts are set by owner ruling (open: q-207-l5b): **Effort 1 — U1 unified CLI**, **Effort 2 — U1 workspace panel**, **Effort 3 — U1 Scout tool**. It supersedes `ruling-207-ab-efforts-2026-11-05`. |
| Owner ruling | `ruling-207-ab-inconclusive-2026-11-06` (2026-11-06) — "q-207-l5c: option 2. Record all three as inconclusive and move on.. Revisit in a dedicated session after 2.2." and "Do not let any of the analysis affect the outcome of the 3 project components": all three efforts are recorded as inconclusive; no C2 value claim; revisit after v2.2. |

The three efforts are research runs on the existing U1 outline, and they run inside M2: no work slated for another milestone is fetched and pulled in here.

Every SDP line citation in this record is a line number **at revision `7177580c…`** (819 lines); the digest above was recomputed locally from that artifact before this record was written. If the SDP is re-pinned, this record stops and re-checks rather than citing a stale revision.

## 2. Rule — no claim before 3/3

**No superiority or promotion claim is made until all three efforts are recorded.** An effort that has not been run is `pending`, and `pending` is not evidence: until §5, §6 and §7 are each recorded for both arms, this record carries no comparison, no totals, no verdict and no promotion request. The comparison section (§8) stays empty until 3/3. 3/3 are recorded; the result is inconclusive (§8), so no claim follows.

## 3. Arms

| arm | Research path |
| --- | --- |
| **A** | C1 built-in research only — the read-only repository and primary-documentation lane; no pinned provider runs. |
| **B** | C1 + C2 pinned provider — C1 plus the owner-confirmed pinned `advise-project-approach` (`sha256:2386030e…896c`, `ruling-207-pin-2026-11-05`). |

Each arm records **its locator result** (`present` / `not_available` / `drift` / `error`, with `cause`) and **its SC-5 result** (`finding` / `needs_input` / `not_available` / `drift` / `error`, with its `question` or `cause`), separately, as `skills/dev/research.md` requires. In arm A the locator is not run at all, because arm A is C1 only.

## 4. Recording rule

- **Measured values only.** Every cell carries an observed value or an explicit "not run" / "unknown". An estimate, a projection, or a number remembered after the fact is not a measurement and is not recorded as one.
- **"not run" and "unknown" stay explicit.** An effort that did not run, or a value that was not observed, is written as such — never left blank, never inferred from the other arm, and never back-filled later from memory. "unknown" is a recorded value, not a gap.
- **A C2 fallback is recorded as a fallback, never as a B-arm result.** A `not_available` / `drift` / `error` locator verdict, or a provider fallback, is written in the C2 column as that fallback with its cause. It is never counted as a finding and never becomes a B-arm measurement.
- **Blind review.** The owner reviews both outputs per effort blind (labelled X/Y), and the A/B key is revealed after review.
- **Blinding.** Before the review page goes out, only the provenance lines that would name the arm are stripped, and the record says that this was done.
- One row per arm per effort. The `arm` column names the row; the metric columns are exactly the ten named below, in the same order, in every effort table.

### Controlled sources

Both arms use the same source set, so the arms differ only in whether C2 runs:

- **showrunner repo revision** — read-only; the same revision in both arms.
- **U1 outline revision** — the same revision in both arms.
- **primary-source scope** — official docs and public repositories with their own docs.

No blogs, forums or aggregators in either arm. If arm B's provider reaches beyond that scope, the record says so and the output is not filtered. Each effort's evidence records the source set and its revisions.

## 5. Effort 1 — U1 unified CLI

Scope: research only over the existing U1 outline (the foreman epic artifact `u1-binary-components-phase`): nothing designed or built, the U1 page not edited, no U1 Issues filed.

source set and revisions: showrunner `1f9c65d`; U1 outline `artifacts/u1-binary-components-phase` sha256 `c7522cdd…335e` (74 lines); primary-source scope = official docs and public repositories with their own docs. Source overreach (disclosed, not filtered): arm A — v2.2 plan + epic artifacts (u1-cli-issue-draft, runtime-manifest, scout-tool, migration-safety-runner) + tracker #153/#181; arm B — tracker #153/#181/#182/#184; provider SKILL.md (expected for C2). Blinding: no arm-naming lines needed stripping; host frontmatter hidden at render only.

**Status: recorded — inconclusive**

Owner review: not judged; the owner could not assess either note, because no note matched the owner's intended shape for the component (ruling-207-ab-inconclusive-2026-11-06). The owner did look at a foreman summary page, `artifacts/u1-research-ab/quick-review`. Key revealed after owner ruling, 2026-11-06: X = arm B, Y = arm A.

| arm | date | plan_ref (origin / approved revision) | consequential misses | repeated or low-value questions | rounds | wall time | user burden (owner review minutes) | C2 locator + result | evidence links | recorder |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 2026-11-05 | n/a — research only | not judged: owner could not assess; no note matched the owner's intended shape for the component (ruling-207-ab-inconclusive-2026-11-06) | not judged: owner could not assess; no note matched the owner's intended shape for the component (ruling-207-ab-inconclusive-2026-11-06) | 5 | ~13–14 min | not judged: owner could not assess; no note matched the owner's intended shape for the component (ruling-207-ab-inconclusive-2026-11-06) | not run — arm A is C1 only | `artifacts/u1-research-ab/effort-1/index.html`, `artifacts/u1-research-ab/effort-1/y.md` | 525c4a0c-7fe7-40c7-936f-a4ce3d572579 (M2 orchestrator, successor) |
| B | 2026-11-05 | n/a — research only | not judged: owner could not assess; no note matched the owner's intended shape for the component (ruling-207-ab-inconclusive-2026-11-06) | not judged: owner could not assess; no note matched the owner's intended shape for the component (ruling-207-ab-inconclusive-2026-11-06) | 5 | ~5 min | not judged: owner could not assess; no note matched the owner's intended shape for the component (ruling-207-ab-inconclusive-2026-11-06) | locator present (~/.agents/skills/advise-project-approach, exit 0); SC-5 result finding; no fallback, no needs_input | `artifacts/u1-research-ab/effort-1/index.html`, `artifacts/u1-research-ab/effort-1/x.md` | 525c4a0c-7fe7-40c7-936f-a4ce3d572579 (M2 orchestrator, successor) |

## 6. Effort 2 — U1 workspace panel

Scope: research only over the existing U1 outline (the foreman epic artifact `u1-binary-components-phase`): nothing designed or built, the U1 page not edited, no U1 Issues filed.

source set and revisions: showrunner `1f9c65d`; U1 outline `artifacts/u1-binary-components-phase` sha256 `c7522cdd…335e` (74 lines); primary-source scope = official docs and public repositories with their own docs. Source overreach (disclosed, not filtered): arm A — local non-public agent-dashboard checkout @23e5396; v2.2 plan; v2.1.2 panel decision + critique briefing; 3687337d final deliverable. arm B — v2.2 plan + v2.1.2 panel artifacts + 3687337d design/debate artifacts; saw the agent-dashboard checkout exists, did not read it. Blinding: no arm-naming lines needed stripping; host frontmatter hidden at render only.

**Status: recorded — inconclusive**

Owner review: not judged; the owner could not assess either note, because no note matched the owner's intended shape for the component (ruling-207-ab-inconclusive-2026-11-06). The owner did look at a foreman summary page, `artifacts/u1-research-ab/quick-review`. Key revealed after owner ruling, 2026-11-06: X = arm B, Y = arm A.

| arm | date | plan_ref (origin / approved revision) | consequential misses | repeated or low-value questions | rounds | wall time | user burden (owner review minutes) | C2 locator + result | evidence links | recorder |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 2026-11-05 | n/a — research only | not judged: owner could not assess; no note matched the owner's intended shape for the component (ruling-207-ab-inconclusive-2026-11-06) | not judged: owner could not assess; no note matched the owner's intended shape for the component (ruling-207-ab-inconclusive-2026-11-06) | 5 | ~5–6 min (approx) | not judged: owner could not assess; no note matched the owner's intended shape for the component (ruling-207-ab-inconclusive-2026-11-06) | not run — arm A is C1 only | `artifacts/u1-research-ab/effort-2/index.html`, `artifacts/u1-research-ab/effort-2/y.md` | 525c4a0c-7fe7-40c7-936f-a4ce3d572579 (M2 orchestrator, successor) |
| B | 2026-11-05 | n/a — research only | not judged: owner could not assess; no note matched the owner's intended shape for the component (ruling-207-ab-inconclusive-2026-11-06) | not judged: owner could not assess; no note matched the owner's intended shape for the component (ruling-207-ab-inconclusive-2026-11-06) | 3 | ~20 min incl. report | not judged: owner could not assess; no note matched the owner's intended shape for the component (ruling-207-ab-inconclusive-2026-11-06) | locator present (~/.agents/skills/advise-project-approach, exit 0); SC-5 result finding; no fallback, no needs_input | `artifacts/u1-research-ab/effort-2/index.html`, `artifacts/u1-research-ab/effort-2/x.md` | 525c4a0c-7fe7-40c7-936f-a4ce3d572579 (M2 orchestrator, successor) |

## 7. Effort 3 — U1 Scout tool

Scope: research only over the existing U1 outline (the foreman epic artifact `u1-binary-components-phase`): nothing designed or built, the U1 page not edited, no U1 Issues filed.

source set and revisions: showrunner `1f9c65d`; U1 outline `artifacts/u1-binary-components-phase` sha256 `c7522cdd…335e` (74 lines); primary-source scope = official docs and public repositories with their own docs. Source overreach (disclosed, not filtered): arm A — tracker #153/#104; did NOT read the d4441475 package (its own gap 1). arm B — filename-only `ls`/`find` of ~/housekeeping/scout-tool (no file opened). Both arms — scout-tool record + its post-2.2-handoff, allowed as outline context by a lead clarification sent equally to both arms. Blinding: no arm-naming lines needed stripping; host frontmatter hidden at render only.

**Status: recorded — inconclusive**

Owner review: not judged; the owner could not assess either note, because no note matched the owner's intended shape for the component (ruling-207-ab-inconclusive-2026-11-06). The owner did look at a foreman summary page, `artifacts/u1-research-ab/quick-review`. Key revealed after owner ruling, 2026-11-06: X = arm A, Y = arm B.

| arm | date | plan_ref (origin / approved revision) | consequential misses | repeated or low-value questions | rounds | wall time | user burden (owner review minutes) | C2 locator + result | evidence links | recorder |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 2026-11-05 | n/a — research only | not judged: owner could not assess; no note matched the owner's intended shape for the component (ruling-207-ab-inconclusive-2026-11-06) | not judged: owner could not assess; no note matched the owner's intended shape for the component (ruling-207-ab-inconclusive-2026-11-06) | 3 | ~20 min | not judged: owner could not assess; no note matched the owner's intended shape for the component (ruling-207-ab-inconclusive-2026-11-06) | not run — arm A is C1 only | `artifacts/u1-research-ab/effort-3/index.html`, `artifacts/u1-research-ab/effort-3/x.md` | 525c4a0c-7fe7-40c7-936f-a4ce3d572579 (M2 orchestrator, successor) |
| B | 2026-11-05 | n/a — research only | not judged: owner could not assess; no note matched the owner's intended shape for the component (ruling-207-ab-inconclusive-2026-11-06) | not judged: owner could not assess; no note matched the owner's intended shape for the component (ruling-207-ab-inconclusive-2026-11-06) | 5 | ~8+ min | not judged: owner could not assess; no note matched the owner's intended shape for the component (ruling-207-ab-inconclusive-2026-11-06) | locator present (~/.agents/skills/advise-project-approach, exit 0); SC-5 result finding; no fallback, no needs_input | `artifacts/u1-research-ab/effort-3/index.html`, `artifacts/u1-research-ab/effort-3/y.md` | 525c4a0c-7fe7-40c7-936f-a4ce3d572579 (M2 orchestrator, successor) |

## 8. Comparison

All three efforts are recorded (3/3) and the comparison is **inconclusive**. The owner could not judge any effort, so no owner-judgement metric exists to compare. The record makes no claim either way about C2's value: not superior, not inferior. C2 stays optional and is not promoted, made default or made a dependency. Rounds and wall time are recorded per arm but are not a value signal on their own and are not compared here. The A/B value question is to be revisited in a dedicated session after v2.2 ships (`ruling-207-ab-inconclusive-2026-11-06`). No table, no totals, no ranking.

## 9. What this record does not do

- It does not claim that C2 is superior to C1, and it does not request that C2 be promoted, made default, or made a dependency of the research lane.
- It does not run C3. C3 stays conditional on unresolved mechanism questions, C2 evidence and separate cost approval.
- It does not design or build anything for U1, edit the U1 page, or file U1 Issues: each effort is research over the existing outline only.
- It is not an input to U1: the six research notes and the summaries (the three effort pages and `artifacts/u1-research-ab/quick-review`) are not inputs to U1, and no U1 design, plan, Issue or decision may cite or rely on them (`ruling-207-ab-inconclusive-2026-11-06`).
- It does not filter arm B's output when the provider reaches beyond the primary-source scope: the record discloses that it did.
- It does not install anything, spend provider budget, or write a not-run effort up as a done one.
