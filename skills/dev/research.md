# Research (C1 / C2)

Phase 1.5 Step 2 fills the research gaps a Technical Plan still has open after
intake (D6.3). Research is **read-only** and its synthesis is **lead-owned**:
the lead decides what a finding means for the plan; a research step never
writes, installs, mutates anything over the network, or spends provider budget.
Writes, installs, network mutation and provider cost are unconditionally forbidden.

Two lanes supply evidence:

- **C1 — the built-in read-only research lane.** The lead dispatches a read-only
  research agent (see `${CLAUDE_SKILL_DIR}/agents/researcher.md`) against the
  repository and primary documentation. The lead owns the synthesis.
- **C2 — an optional pinned `advise-project-approach`.** The lead runs the L3
  locator (`${CLAUDE_SKILL_DIR}/scripts/locate_pinned_skill.py`) with the pin
  below. Only a `present` result may be used as a provider.

## Evidence order

Repository and primary documentation first; broader or community sources only
when relevant and under the applicable approval — scoped approval applies only to sources, never to writes, installs, network mutation or provider cost.
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

### Calling the locator

Precondition: C2 runs only once the pin is owner-confirmed. While the pin is
still proposed, the lead skips C2 and records a fallback with result type
`not_available`, cause `pin_unconfirmed`.

The lead passes an explicit list of harness skill directories as repeatable
`--root`: `~/.agents/skills`, `~/.claude/skills`, `<repo>/.claude/skills`, `~/.claude/plugins/cache`. The locator skips missing roots. The lead never adds other paths, and nothing is searched automatically beyond that list.

```text
rtk proxy python3 ${CLAUDE_SKILL_DIR}/scripts/locate_pinned_skill.py \
  --skill advise-project-approach --commit none \
  --digest sha256:2386030e843dd13158bf7fb7e129715718bf36c2e29c73e3f9249fc22404896c \
  --root ~/.agents/skills --root ~/.claude/skills \
  --root <repo>/.claude/skills --root ~/.claude/plugins/cache
```

Read the result by exit code and the JSON on stdout: exit 0 is `present` (JSON
has `path` and `digest`); exit 2 is `not_available` or `drift` (JSON has a
`cause`); exit 1 is a usage or operational error (JSON `status` `error` plus a
`cause`) and is no verdict.

On `present`: dispatch the researcher in C2 mode with the returned `path`.

### Locator availability vs provider result

The locator's verdict is availability, not an SC-5 result.
Availability is its own field: `locator: present | not_available | drift | error` plus `cause`.
The SC-5 `result.type` is the provider's actual outcome: `finding` only for an evidenced answer; `needs_input` with `question`; `error` / `not_available` / `drift` with `cause`.
A locator fallback is recorded as `not_available` / `drift` / `error` with `cause`, and no finding.

A visible fallback to C1: the `cause` is shown to the user and recorded.
Never install, update, or fetch the pinned provider automatically.
A fallback is never reported as a completed research step.

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

Record the locator's availability and the provider's SC-5 result separately:
the locator field (`present` / `not_available` / `drift` / `error` with
`cause`), and the provider `result.type` (`finding`, `needs_input`,
`not_available`, `drift`, `error`) with its `cause` or `question`. Record
provider/model/route, source digest, and provenance (the revision or digest
read). A locator fallback is recorded with no finding.

## Brownfield path (AC-02)

Research the gaps and recommend; do not impose a mandatory question per turn or
an exhaustive zero-fog gate. Consequential choices are surfaced one at a time,
each with its evidence and a recommendation.
