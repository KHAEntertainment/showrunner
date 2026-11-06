---
title: "Showrunner v2.2 P1 — C1/C2 A/B value evidence record"
kind: spec
comments: none
---

# Showrunner v2.2 P1 — C1/C2 A/B value evidence record

Implements `KHAEntertainment/showrunner#207` (M2 package **P1-02**), criterion 4 of the M2 charter §2. This is a **text-only evidence record**: it admits no behavior, grants no promotion, and starts empty. Every effort below is `pending` until it is actually run.

## 1. Authority

| Source | Citation |
| --- | --- |
| Canonical plan (SDP) | `artifacts/v2-2-development-plan/index.md` (Showrunner task `6266293c-edb0-48f6-b8f6-ddd561de1f05`), SHA-256 `7177580c8429d6e5f8f07e6138de72506ac7a419e9697f5102f842d43a93315b`, 819 lines — **SDP l.81**: "Run the A/B value gate over three real planning efforts before superiority claims/promotion. Record consequential misses, repeated/low-value questions, rounds, time and user burden." |
| M2 charter | `charters/p1-planning-and-research/index.md` §2, criterion 4: "Three-real-effort A/B value evidence recorded before any superiority/promotion claim; C3 only on unresolved mechanisms, C2 evidence and separate cost approval or an explicit permitted disposition." |
| Owner ruling | `ruling-207-pin-2026-11-05` (2026-11-05) — the C2 pin `advise-project-approach`, directory digest `sha256:2386030e…896c`, is owner-confirmed and C2 may activate against it. |
| Owner ruling | `ruling-207-ab-u1-2026-11-05` (2026-11-05) — the efforts are set by owner ruling (open: q-207-l5b): **Effort 1 — U1 unified CLI**, **Effort 2 — U1 workspace panel**, **Effort 3 — U1 Scout tool**. It supersedes `ruling-207-ab-efforts-2026-11-05`. |

The three efforts are research runs on the existing U1 outline, and they run inside M2: no work slated for another milestone is fetched and pulled in here.

Every SDP line citation in this record is a line number **at revision `7177580c…`** (819 lines); the digest above was recomputed locally from that artifact before this record was written. If the SDP is re-pinned, this record stops and re-checks rather than citing a stale revision.

## 2. Rule — no claim before 3/3

**No superiority or promotion claim is made until all three efforts are recorded.** An effort that has not been run is `pending`, and `pending` is not evidence: until §5, §6 and §7 are each recorded for both arms, this record carries no comparison, no totals, no verdict and no promotion request. The comparison section (§8) stays empty until 3/3.

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

source set and revisions: not run — record the showrunner repo revision, the U1 outline revision and the primary-source scope here

**Status: pending**

| arm | date | plan_ref (origin / approved revision) | consequential misses | repeated or low-value questions | rounds | wall time | user burden (owner review minutes) | C2 locator + result | evidence links | recorder |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | not run | not run | not run | not run | not run | not run | not run | not run — arm A is C1 only | not run | not run |
| B | not run | not run | not run | not run | not run | not run | not run | not run | not run | not run |

## 6. Effort 2 — U1 workspace panel

Scope: research only over the existing U1 outline (the foreman epic artifact `u1-binary-components-phase`): nothing designed or built, the U1 page not edited, no U1 Issues filed.

source set and revisions: not run — record the showrunner repo revision, the U1 outline revision and the primary-source scope here

**Status: pending**

| arm | date | plan_ref (origin / approved revision) | consequential misses | repeated or low-value questions | rounds | wall time | user burden (owner review minutes) | C2 locator + result | evidence links | recorder |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | not run | not run | not run | not run | not run | not run | not run | not run — arm A is C1 only | not run | not run |
| B | not run | not run | not run | not run | not run | not run | not run | not run | not run | not run |

## 7. Effort 3 — U1 Scout tool

Scope: research only over the existing U1 outline (the foreman epic artifact `u1-binary-components-phase`): nothing designed or built, the U1 page not edited, no U1 Issues filed.

source set and revisions: not run — record the showrunner repo revision, the U1 outline revision and the primary-source scope here

**Status: pending**

| arm | date | plan_ref (origin / approved revision) | consequential misses | repeated or low-value questions | rounds | wall time | user burden (owner review minutes) | C2 locator + result | evidence links | recorder |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | not run | not run | not run | not run | not run | not run | not run | not run — arm A is C1 only | not run | not run |
| B | not run | not run | not run | not run | not run | not run | not run | not run | not run | not run |

## 8. Comparison

Empty until 3/3. The comparison is written only when §5, §6 and §7 are each recorded for both arms. Until then this section records nothing: no table, no totals, no ranking of the arms, no superiority claim and no promotion request.

## 9. What this record does not do

- It does not claim that C2 is superior to C1, and it does not request that C2 be promoted, made default, or made a dependency of the research lane.
- It does not run C3. C3 stays conditional on unresolved mechanism questions, C2 evidence and separate cost approval.
- It does not design or build anything for U1, edit the U1 page, or file U1 Issues: each effort is research over the existing outline only.
- It does not filter arm B's output when the provider reaches beyond the primary-source scope: the record discloses that it did.
- It does not install anything, spend provider budget, or write a not-run effort up as a done one.
