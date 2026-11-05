# Research (C1 / C2)

Phase 1.5 Step 2 fills the research gaps a Technical Plan still has open after
intake (D6.3). Research is **read-only** and its synthesis is **lead-owned**:
the lead decides what a finding means for the plan; a research step never
writes, installs, mutates anything over the network, or spends provider budget
without the lead's explicit, scoped approval.

Two lanes supply evidence:

- **C1 — the built-in read-only research lane.** The lead dispatches a read-only
  research agent (see `${CLAUDE_SKILL_DIR}/agents/researcher.md`) against the
  repository and primary documentation. The lead owns the synthesis.
- **C2 — an optional pinned `advise-project-approach`.** The lead runs the L3
  locator (`${CLAUDE_SKILL_DIR}/scripts/locate_pinned_skill.py`) with the pin
  below. Only a `present` result may be used as a provider.

## Evidence order

Repository and primary documentation first; broader or community sources only
when relevant and under the applicable approval.
Read-only throughout: no writes, no installs, no network-mutating calls, no provider cost.

## C2 — the pinned provider

The pin below is **proposed — the owner confirms it before C2 is used**.

- **skill**: `advise-project-approach`
- **commit**: none (unversioned local copy at `~/.agents/skills/advise-project-approach`)
- **directory digest**: `sha256:2386030e843dd13158bf7fb7e129715718bf36c2e29c73e3f9249fc22404896c`

The digest was computed with the locator's own digest function
(`${CLAUDE_SKILL_DIR}/scripts/locate_pinned_skill.py` `directory_digest`) over the
read-only copy at `~/.agents/skills/advise-project-approach`.

When the lead runs the locator, pass `--commit none` for this pin. The locator
records and echoes the commit without verifying it — only the directory digest
is checked against the pin — so `none` is the honest value for a copy with no
VCS metadata.

The lead runs the locator with this pin each time C2 is considered. The result
is interpreted in SC-5 shape (`docs/v2.2/contracts/sc-5.md`):

- **`present`** → the provider may be used, recorded as `result.type: finding`.
- **`not_available` / `drift` / `error`** → a visible fallback to C1: the `cause` is shown to the user and recorded, and the step proceeds with C1.
- Never install, update, or fetch the pinned provider automatically.
- A fallback is never reported as a completed research step.

## Provider `needs_input`

A provider `needs_input` returns to the lead, who answers from evidence or
escalates only genuinely user-owned choices. Provider question counts and
templates never become the user script: a question the lead cannot answer from
evidence is a gap, surfaced one at a time with a recommendation, not a script.

## Out of scope here

- **Wayfinder B1/B2** are not default and never auto-run because installed.
- **C3 (neuroarxiv)** is conditional and not invoked here: it stays a separate,
  cost-approved escalation for unresolved mechanism questions.

## Recording (SC-5 shape)

Each provider result is recorded per source in the Technical Plan's research
section: provider/model/route, source digest, result type, `cause` or
`question` where SC-5 requires it, and provenance (the revision or digest read).

## Brownfield path (AC-02)

Research the gaps and recommend; do not impose a mandatory question per turn or
an exhaustive zero-fog gate. Consequential choices are surfaced one at a time,
each with its evidence and a recommendation.
