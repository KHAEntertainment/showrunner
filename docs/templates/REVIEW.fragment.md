# Kilo `REVIEW.md` fragment (template, not installed)

A reviewed-diff candidate for a repository whose reviewer of record is Kilo.
The Skill does not install it and nothing reads this file as configuration.
A repository adopts it by a reviewed PR that copies the text between the two
marker lines into that repository's own `REVIEW.md`. Source: v2.1.3 provider
strategy §3, verified 2026-10-19.

## Placement

- Keep the combined `REVIEW.md` under Kilo's 10,000-character limit by
  construction. Kilo truncates beyond it and notes the truncation in its
  footer. If this fragment plus the project file would not fit, shorten the
  generic fragment, never the project's domain or safety rules.
- For a repository with no `REVIEW.md`, this fragment plus a short "What
  matters here" section is the whole file.
- Provider guidance is advisory text, not enforcement.
- This repository's own `REVIEW.md` already carries the product-first framing
  and its Critical/Warning definitions; keep those and its "Review summary and
  comment style" section when merging. The fragment omits a "Summary" section
  on purpose: Kilo's summary format is fixed and such an instruction would be
  ignored or truncated.

## Activation limits

- Kilo reads `REVIEW.md` from the base branch, so the file takes effect for a
  PR only after it is merged to the base.
- `REVIEW.md` cannot override Kilo's read-only mode, non-interactive
  execution, diff-line rules or output format.
- "Use REVIEW.md" is a dashboard toggle. Repository contents cannot prove it
  is on. The first PR's Kilo summary footer (truncation note, sub-agent usage)
  identifies which configuration source applied, not which policy content
  loaded. Verify the enabled setting where it is accessible; otherwise record
  the limitation.
- Kilo skips bot-opened PRs by default. Dev workers push as the owner's
  account today, so the skip does not bite; record the PR author login on the
  first PR.
- Kilo has no comment command. Its re-triggers are PR opened, new commits
  pushed, PR reopened and draft marked ready.
- Sub-agent defaults are 0 (tiny), up to 1 (small) and 6 (medium and larger).
  The fragment restrains coverage-only delegation; it does not assume fewer
  sub-agents improves yield or latency. Record sub-agent counts from the
  summary footer where present.

<!-- BEGIN FRAGMENT: copy from the next line -->
# Product-first review guidance

Review this PR for its stated purpose and the acceptance criteria in the linked
Issue. Distinguish PR correctness from parent-feature completion; missing
parent context or runtime evidence is a limitation to state, not completion.

Prioritize incorrect behavior, regressions, acceptance violations,
security and data-integrity risks, and serious resource or concurrency
defects. Give the concrete failure or credible technical reasoning. Unsafe
or impractical reproduction does not make a material defect advisory.

Optional coverage, style, unrelated refactoring and speculative performance
ideas are advisory. A missing test blocks only for a check this repository
requires or for an explained material risk. Do not invent acceptance
requirements.

Judge changed assertions, skips, fixtures and mocks against the intended
behavior. Unit isolation is legitimate; mocking away the integration the PR
claims to verify does not establish it. A test correction must explain the
wrong prior expectation.

Use the repository's CI result for the checks it ran. Do not repeat enforced
lint or format findings unless enforcement is defective. CI is not functional
acceptance; do not request expensive test infrastructure without a specific
risk or requirement.

Advisory comments are not mandatory separate PRs. The orchestrator owns
triage; scope and acceptance changes belong to the owner.

## Sub-agents

Review straightforward changes directly. Small security or authority changes
are still risky. Use one sub-agent for one distinct unresolved material risk;
add specialists only for genuinely separate domains. No coverage-only
delegation. Sub-agents are read-only; the primary reviewer verifies their
evidence, deduplicates, and owns the result.
<!-- END FRAGMENT: copy up to the previous line -->
