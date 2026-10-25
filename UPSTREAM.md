# Upstream Maintenance

This repository maintains a customized English personal Skill while retaining upstream history.

## Tracking upstream

Showrunner is detached from upstream's GitHub fork network (owner decision,
2026-10-24). It is a standalone repository. Upstream history stays in the
`master` mirror and in the merged ancestry of `main`.

- **Remote.** Upstream is tracked by the `upstream` Git remote below. Add it in
  a fresh clone with
  `git remote add upstream https://github.com/hnaymyh123-henry/claude-dev-skill.git`.
- **Notification.** The owner's GitHub account watches upstream for releases
  only (Watch → Custom → Releases). A release notification is the signal to
  run the Sync Procedure below.
- **Cadence.** Upstream last shipped `v1.3.0` on 2026-05-27, the commit already
  merged as the first audited merge below. An occasional `git fetch upstream`
  is enough; no scheduled sync job exists.
- **Port log.** Record anything upstream ships that is worth porting under
  [Port log](#port-log), whether or not it is merged yet.

## Remotes

- `origin`: `https://github.com/KHAEntertainment/showrunner.git`
- `upstream`: `https://github.com/hnaymyh123-henry/claude-dev-skill.git`
- `main`: maintained customized distribution
- `master`: upstream mirror retained for comparison

## Provenance

- Installed-era base: `3abcd9a75d3032e12a499afb464b56695a424cb9`
- First audited merge: `3e87db0c71ff51ad19c932a6849777e66398f556`
- Canonical maintained artifact: `skills/dev/`
- Historical upstream references: `en/` and `zh/`

## Divergences from upstream

Additive edits to upstream-owned files under `skills/dev/`, recorded so a later
upstream merge re-applies or drops each one deliberately instead of leaving it
to conflict resolution. A merge must leave every upstream file exactly as
upstream ships it wherever this list says nothing about it.

- `skills/dev/phases/phase1.md` — new `### B.0 Document-first mode (Situation A
  only)` subsection at the head of Step B. When the Entry Routing test for
  Situation A held, the lead reads the supplied document first and drafts that
  module's decisions as a proposed locked list, each item citing the document
  section it came from, presents the gap list beside it with both counts, and
  asks only the gaps, one question at a time with a recommended answer. B.1–B.4,
  Steps A, C and D, Situation B, the Top-level Anchoring Principles and the B.3
  stress-test are unchanged; a document-settled item is reopened by the user at
  the Step C gate rather than silently locked, and the document itself is never
  rewritten. One sentence on Situation A's routing entry and one Prohibited
  Behaviors bullet accompany it. Upstream content is otherwise untouched
  (v2.1.2, #74).

## Port log

Upstream changes worth porting, newest first. Each entry names the upstream tag
or commit, what it changes, and the decision: `ported` (with the PR),
`deferred` (with the reason), or `declined` (with the reason).

- `v1.3.0` (`3e87db0`, 2026-05-27): module-progressive Phase 1 and prototyping
  sub-agents. `ported`: the first audited merge.

## Sync Procedure

1. Check out `main`, fetch `upstream`, and inspect new tags/commits.
2. Compare both upstream language trees; do not assume English parity.
3. Update `docs/AUDIT.md` with newly discovered behavior and conflicts.
4. Merge the upstream commit with `--no-ff` to preserve ancestry.
5. Selectively translate relevant behavior into `skills/dev/`; never release directly from `en/` or `zh/`.
6. Preserve RTK, `.agent/dev-state.md`, the implementation/test no-lead-code rule, pre-created worktrees, Agent Teams ownership, specialist QA/review lanes, and lead-owned cleanup.
7. Run `scripts/validate_skill.py`, Bash syntax checks, ShellCheck, installer tests, isolated discovery, and `/dev` loading smoke tests.
8. Record the upstream commit in `CHANGELOG.custom.md` and the release tag.

Do not run the default installer while an active Claude Code session depends on the legacy global command. Use an explicit temporary `--target` for validation, then wait for an intentional swap window.
