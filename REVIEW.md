# REVIEW.md

## What matters in this repository

- `skills/dev/` is the only shipped artifact. Its Markdown is runtime behavior: agents follow it literally. Review a wording change in `skills/dev/phases/`, `agents/`, or `backends/` as a behavior change, not as copy-editing.
- Payload files refer to siblings as `${CLAUDE_SKILL_DIR}/<relpath>`. A hardcoded path in `skills/dev/` is a defect.
- `skills/dev/scripts/resolve_repository.py` is the pre-write safety gate for every push, PR, Issue, and tag write. Any change that lets a write proceed without a `ready` verdict is the most serious class of bug here.
- Push refspecs use a fully qualified source, `refs/heads/<branch>:refs/heads/<branch>`. An unqualified source let a branch named `+feature` force-push past a lease (PR #115). The lease path also refuses the remote default branch.
- `skills/dev/scripts/inspect_external_reviews.py` must never report `clear` without review evidence at the current head. A green status check alone is not evidence (PR #23). A requested-changes verdict blocks (PR #28).
- Python under `scripts/` and `skills/dev/scripts/` is stdlib-only (ADR-005). Graft is the sole, optional, gate-time exception.
- The offline gate makes no network calls. `scripts/check_central_catalog.py` is network-bound on purpose and stays outside `scripts/verify.sh`.
- `en/` and `zh/` are historical upstream trees and are never installed. Fork changes belong in `skills/dev/`. Fork changelog entries belong in `CHANGELOG.custom.md`, not `CHANGELOG.md`.
- The skill version in `skills/dev/SKILL.md` frontmatter must match `.claude-plugin/plugin.json`. A release that moves the central marketplace entry changes `source.url` and `ref` together (`docs/RELEASING.md`).
- `install.sh` and `install.ps1` are parallel installers. `tests/test-install.ps1` is the only coverage `install.ps1` has.

## Severity calibration

- Critical: a weakened or bypassed guard in `resolve_repository.py`. That covers target or account checks, lease verification, refspec construction, and default-branch refusal.
- Critical: the review inspector returning `clear` or `ready` on missing, stale, or non-head evidence.
- Critical: a third-party import, or a network call, added to a gate script or a core workflow script.
- Critical: a policy rule removed from `skills/dev/` prose with no replacement, for example a never-force-push rule or a pre-write check.
- Warning: a new `reason_code` with no entry in `skills/dev/phases/repository-context.md`.
- Warning: two `skills/dev/` documents that now contradict each other, for example a push command in `agents/worker-fix.md` that differs from `phases/repository-context.md`.
- Warning: a behavior change in one installer with no matching change, or no test, for the other.
- Warning: a new script branch or refusal path with no unittest that exercises it.
- Warning: a PR that changes `install.sh`, `install.ps1` or `tests/test-install.*` whose installer checks are skipped. The suites never ran on it.
- Do not flag shell lint or PowerShell syntax errors. `shellcheck`, `bash -n` and a PowerShell parse check run in CI and fail first.
- Do not flag skipped `Bash installer`, `PowerShell installer` or `Strict plugin validation` checks on other PRs. The installer suites run only on release tags or with the `run-installer-tests` label (`PROJECT_CONTEXT.md`, CI Workflows).
- Do not flag CJK characters, absolute home-directory paths, required-file manifest gaps, frontmatter keys, version mismatches, or a `bin/` directory at the root. `scripts/validate_skill.py`, `scripts/check_version_sync.py`, and `scripts/check_plugin_root.sh` enforce these in CI.
- Do not flag Python formatting or naming. No formatter is configured, and style is not gated.
- Do not flag `en/`, `zh/`, `CHANGELOG.md`, or released entries in `CHANGELOG.custom.md`. They are historical records.
- Do not flag the old `claude-dev-skill` URL in `tests/` fixtures or in `UPSTREAM.md`. Those are intentional upstream or rejection fixtures.
- Do not flag `docs/plans/`. Planning documents are not shipped.

## Verification expectations

- Script changes need a unittest in `tests/` that asserts the observable verdict or output, not that a mock was called.
- Git behavior is tested against local temporary repositories and bare remotes, never the network (`tests/test_force_with_lease_push.py` is the pattern).
- A new refusal path needs a test that reaches the refusal.
- A safety fix needs a regression test that fails when the fix is reverted.
- When a documented command must match what a script emits, a test should pin the two together (`DocumentedPushCommandTests`).
- Validator changes need tests in `tests/test_validate_skill.py` for both cases: inputs that must fail and inputs that must pass, including the placeholders `/Users/<name>` and `$HOME`.
- Installer changes need `tests/test-install.sh`, and `tests/test-install.ps1` when `install.ps1` is touched.
- The full gate is `bash scripts/verify.sh --require-all`.

## Security and performance

- Subprocess calls pass argument lists. `shell=True` is a Critical finding in `skills/dev/scripts/`.
- Values that reach `git` or `gh` argv, such as branch names, refs, and repository slugs, need validation before use. Leading `-` and leading `+` both have changed git semantics before.
- Never weaken a check because it is slow. A safety check runs once per write, so its cost does not matter.

## Review summary and comment style

- Lead with the highest-severity finding. Put one issue in each comment, naming `file:line` and the concrete failure: what input reaches which wrong outcome.
- For prose changes, quote the old and new instruction, then say what an agent would now do differently.
- State the behavior ("this pushes without a lease when the branch starts with `+`"). Do not hint at it ("consider validating input").
- Do not restate the diff. Do not praise.
