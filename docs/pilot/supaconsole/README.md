# SupaConsole pilot: owner setup checklist (documentation only)

This directory prepares the v2.1.3 SupaConsole pilot as drafts. **Nothing here is
applied.** Issue #159 (v2.1.3 P7) authorizes documentation only. No commit, PR or
setting change has been made on `KHAEntertainment/SupaConsole`, on any CodeRabbit
or Kilo configuration, or anywhere outside this repository. Every step below is an
**owner action, not performed here**, and every box is unchecked.

| File | Role |
| --- | --- |
| [`PROJECT_CONTEXT.draft.md`](PROJECT_CONTEXT.draft.md) | Draft `PROJECT_CONTEXT.md` for SupaConsole |
| [`dev.json.example`](dev.json.example) | Draft `.dev.json`; deliberately not named `.dev.json`, so no tool reads it as config |
| [`../../templates/coderabbit.fragment.yaml`](../../templates/coderabbit.fragment.yaml) | CodeRabbit `.coderabbit.yaml` fragment (provider strategy §4) |
| [`../../templates/REVIEW.fragment.md`](../../templates/REVIEW.fragment.md) | Kilo `REVIEW.md` fragment (provider strategy §3); not needed on SupaConsole, where Kilo is ignored |

Reviewer of record on SupaConsole: **CodeRabbit** (owner decision 2026-10-19). Kilo
is ignored there, so the Kilo fragment is a general template only.

## Facts re-read for this draft

All reads were read-only, through the GitHub API, on **2026-10-27**. They replace the
2026-10-19 figures in the planning documents. Re-check any of them before acting.

| Fact | Planning figure (2026-10-19) | Observed 2026-10-27 |
| --- | --- | --- |
| Visibility, default branch | public, `main` | public, `main` |
| `main` head | `b720c68` | `6f2b8c5` (2026-10-25); open PR #24 (T17) |
| CI workflow | job `build` with four commands | `.github/workflows/ci.yml`, job `build` on Node 22: `npm ci`, `npx prisma generate`, `npx tsc --noEmit`, `npm run lint` (= `eslint`), `npm test` (= `vitest run`) |
| Required check | `build`, strict, admin enforcement | unchanged: only `build`; strict; `enforce_admins` true; no required PR reviews |
| Issues | disabled | **enabled** (`has_issues` true); checked again at step 1 |
| `REVIEW.md`, `.coderabbit.yaml`, `PROJECT_CONTEXT.md`, `.dev.json` | none | none (all 404 on `main`) |
| `ops/e2e.sh` | `setup\|deploy\|verify\|delete` | present; usage line is `e2e.sh setup\|deploy\|verify\|delete` |

## Observed CodeRabbit evidence (not a qualification run)

Read from SupaConsole PRs on 2026-10-27. This is **observed evidence only**. It is
not the clean-PR completion qualification in step 6, and it does not satisfy it.

- **Auto-review is running.** CodeRabbit posted run comments on PRs #19, #20 and #24.
  The "Configuration used" line on #15, #16, #19 and #20 reads **Organization UI**
  (profile CHILL), not Repository UI or Repository YAML. No SupaConsole PR shows a
  "Review skipped" notice. PR #23 shows "Review failed: the pull request is closed"
  (it merged about two minutes after opening). PR #15 shows a rate-limited notice.
- **Submitted review objects exist.** The inspector counts a submitted review object
  at head as completion. CodeRabbit review objects by PR:
  `CHANGES_REQUESTED` on #8, #12, #13, #14, #17, #18 (twice), #20 and open PR #24
  (review commit equals the PR head `84b663e`); `CHANGES_REQUESTED` then `APPROVED` on #10;
  `APPROVED` on #11, #21 and #22. No review object on #9, #15, #16, #19, #23.
- **A clean PR got an APPROVED review bound to head.** Closed docs-only PRs #21 and
  #22 each received a CodeRabbit `APPROVED` review whose commit equals the PR head
  (`4b3c25d`, `4cabd88`). #11's `APPROVED` is bound to `2b594c4`, not its final head
  `b63f23f`, so it is stale at head. Both are single observations; read the
  completion route again on a real clean T1 PR (step 6).
- **The organization configuration appears to have request-changes behavior on.**
  Submitted `CHANGES_REQUESTED` and `APPROVED` reviews are consistent with it. The
  effective setting was not read from a settings page; this is inferred from review
  states. **Limitation:** the "Configuration used" line names the configuration
  source, not the policy content, and the effective `request_changes_workflow` and
  `auto_review.enabled` values were not read from the CodeRabbit settings, which this
  work does not touch.

### Conflict the owner must decide before committing any YAML

The CodeRabbit fragment sets `request_changes_workflow: false`. Without
`inheritance: true`, committing a `.coderabbit.yaml` replaces the organization UI
configuration. If the organization has request-changes on today, committing the
fragment as written would stop the `CHANGES_REQUESTED` and `APPROVED` review objects
that the evidence above shows, and a clean PR could be left with only a walkthrough
comment, which the inspector reports `pending`. The provider strategy calls
`request_changes_workflow: false` SupaConsole's approved setting, so this is a
conflict between that document and what the organization does now. The fragment is
left as written. **No YAML is needed for auto-review**, which already runs from the
organization UI. See step 5.

## Owner checklist

Owner steps, none performed. Do them in order. Steps 1 to 6 come before task 1.

- [ ] **1. Confirm Issues are enabled on `KHAEntertainment/SupaConsole`.** Observed
  enabled on 2026-10-27, which reverses the planning figure. Re-check; if it was
  turned off again, enable it. Dev needs Issues for task Issues.
- [ ] **2. Sync the local SupaConsole checkout to `origin/main`.** The planning
  documents record `271b8cd` ten PRs behind `b720c68`; `main` is now `6f2b8c5`. Do
  this before any worktree is created from the checkout.
- [ ] **3. Commit `PROJECT_CONTEXT.md` to SupaConsole through a reviewed PR.** Start
  from [`PROJECT_CONTEXT.draft.md`](PROJECT_CONTEXT.draft.md), fill the bracketed
  fields, and re-check the Verification Gate against `ci.yml` at the time. The draft
  names `build` as the gate, `ops/e2e.sh verify` as the one acceptance check,
  `coderabbit` as the one required reviewer and `kilo` as ignored, and T2 paths
  `prisma/**` and `src/app/api/auth/**`. If the project has a requirement of its own,
  keep it alongside `coderabbit`. Merging this PR changes SupaConsole, so it is the
  owner's, not this Issue's.
- [ ] **4. Place `.dev.json` in the SupaConsole checkout.** Start from
  [`dev.json.example`](dev.json.example): `pushRepository` and `pullRequestRepository`
  are both `KHAEntertainment/SupaConsole`, no split repository. It is a local
  per-checkout file; keep it out of git, as it is excluded in the showrunner checkout.
- [ ] **5. Decide the CodeRabbit configuration source, and read it first.**
  Either leave the organization UI as the source and commit nothing (auto-review
  already runs, see the evidence above), or commit the YAML fragment. For the YAML,
  read the effective organization, UI and inheritance settings first, decide
  `inheritance`, and decide `request_changes_workflow` knowing the conflict above.
  Record the effective enabled setting where you can read it. If you cannot, record
  that limitation. Nothing in this checklist changes branch protection, enables
  auto-approval or disables a check.
- [ ] **6. Qualify the clean-PR completion route before task 1.** This is a settled
  prerequisite (owner decision 2026-10-20) and runs only when you authorize pilot
  setup.
  - Qualify the current-revision completion route for **both a findings PR and a
    clean PR**, from provider documentation or an observed PR. A submitted review
    object at head, or a head-bound review thread, completes. A clean PR that
    produces only a walkthrough or summary comment is reported `pending`, and every
    clean T1 PR would stall under the required-provider rule.
  - Record the observed completion object, or its absence, in the pilot record before
    launch. The evidence above is context for this step, not the result.
  - **If a clean PR has no inspectable completion object:** do not stretch the
    substitution rule. The substitution rule stays limited to the rate-limit
    breakpoint. Open a separate package for the owner, a narrow CodeRabbit-specific
    current-revision completion rule proposed on its own (as PR #119 was for Kilo),
    and bring it to the owner before adoption. It is not part of P7 or P3.
- [ ] **7. Install the Skill revision that carries P1 to P7.** P0 applies only on a
  Kilo route and is not needed here. The revision cannot be named before release.
  Record the installed revision in the ledger at prerequisite time.
- [ ] **8. Approve the pilot launch.** Launch needs its own approval. Task selection
  follows the pilot proposal: three naturally occurring T1 feature or fix tasks, none
  touching auth, migrations or destructive paths.

## Evidence to record on the first pilot PR

Record these in the ledger from the first PR, with their limitations stated:

- **Configuration-source evidence.** The "Configuration used" line from the PR's
  CodeRabbit comment (Organization UI, Repository UI or Repository YAML). **Limitation:**
  it identifies the configuration source, not which policy content loaded. A
  "Review skipped" notice means auto-review is disabled.
- **The effective enabled setting**, where it is accessible: whether auto-review is
  enabled. If it is not accessible, record that it was not.
- **The completion object observed:** a submitted review object (state, commit
  against the PR head) or head-bound review threads, or its absence.
- **The PR author login.** CodeRabbit may skip bot-authored PRs (`ignore_usernames`).
  Dev workers push as the owner's account today.
- **Completion timing**, from PR open to a completing CodeRabbit object at head.

## Safeguards and reversal

The pilot's safeguards are unchanged from the pilot proposal §6: the reduced
arm applies to T1 only, `build` is never waived, and the ledger and
post-merge verification rules stay. Restore the conservative arm for the affected
class on any failure condition in the pilot proposal §7 (a materially missed defect, unsound
evidence reuse, a required check waived, a host incident). Rollback keeps the
containment policy and the explicit-outcome vocabulary.

To undo what the owner applied: revert the SupaConsole PRs (`PROJECT_CONTEXT.md`, and
the YAML if committed); CodeRabbit then falls back to the organization UI
configuration. To undo this documentation: revert the P7 PR in this repository.

## What this Issue did and did not do

Did: wrote these five files and read SupaConsole through the GitHub API (read only).
Did not: change SupaConsole, enable or change Issues, change any CodeRabbit or Kilo
setting, run the clean-PR qualification, install the Skill, or launch the pilot.
