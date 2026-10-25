# Report-Back Contract

Every delegated lane ends by reporting back to the Tech Lead through the active
backend's messaging surface. A report-back is a fixed list, never freeform
prose, so the lead can verify completion mechanically and never infer it from
silence.

## Delivery

- Send the report-back through the same backend surface the assignment arrived on.
- Include the backend correlation/response ID recorded by the adapter when one
  was provided. A missing or mismatched correlation ID fails the lane closed.
- Put that correlation/response ID, verbatim and in full, on the **first line**
  of the report (for example `Response ID: <id>`), above the seven sections. A
  line above the first heading is not a section, so it never counts toward or
  against the seven. The first-line ID does not replace the correlation rule
  above, and a missing or mismatched ID still fails the lane closed. It exists
  so the report names its own thread: after a lead change the pushed reply may
  survive only in the previous lead's transcript, where the lead can recover
  the correlation from the message body alone (swap-time evidence in
  `${CLAUDE_SKILL_DIR}/backends/traycer.md`).
- Read-only lanes (QA, reviewer) must also confirm they left zero tracked changes.
- This contract is enforced by the adapter, not only by this prompt. The
  assignment envelope carries it, and `observe` marks the operation `incomplete`
  when a reply is missing sections or never arrives. See the report-back
  enforcement section of `${CLAUDE_SKILL_DIR}/backends/contract.md`.

## Required sections (all lanes)

1. **Outputs** — files changed/created, PR URL, artifact + readout paths, or a
   finding list.
2. **Commands + exit codes** — every verification/gate command run, with its
   exit code.
3. **Deviations** — anything outside the assignment or assigned ownership,
   including departures from the specification as written; where you believe
   the specification itself is wrong, say so here *before* departing from it —
   a defect flagged in advance is a finding, not an excuse. Write `none` when
   clean.
4. **Quality-gate self-assessment** — syntax / types / lint / tests, each
   `pass` / `fail` / `n/a`.
5. **Acceptance criteria** — each criterion restated as
   `[trigger] → [behavior]`, marked ✓/✗ with a one-line result.
6. **Evidence** — the commit `headRefOid` (or local `HEAD`) the lane ran
   against, plus clean-worktree evidence for read-only lanes.
7. **Scope / ownership** — confirm no file outside assigned ownership was
   modified; list any exception and its reason.

A report-back with a missing section is flagged, not back-filled; never invent
evidence.

## Evidence discipline

- Every completion claim maps to an executed command's actual output. If you
  cannot name the command and what it printed, do not make the claim — record
  what was not run instead. An unrun check is reported as unrun, never omitted.
- One executor per check. The Verification Gate in `PROJECT_CONTEXT.md` names
  who runs each check; a check CI owns is cited, not re-run by your role. For a
  CI-owned check, cite the run, job and attempt, the tested subject and the
  conclusion, read by id, in place of a command and exit code. Pending, missing,
  skipped, cancelled or stale CI evidence is reported as incomplete coverage,
  never as a pass; see **Check Ownership and CI Evidence** in
  `${CLAUDE_SKILL_DIR}/phases/phase4.md`.
- After any fix, obtain the full Verification Gate result again at the new head
  rather than only the check that failed: CI evidence for the checks CI owns,
  your own run for the focused checks you own. A targeted re-run shows the one
  symptom went away; it does not show the fix left everything else intact.
- Every exit code you report comes from your final run of that check, at the
  head commit you report. Never carry an exit code forward from a run that
  preceded the change, and report a partial re-run as partial.
- What counts as "verified" is defined once, in the Tool Capability Boundary of
  `${CLAUDE_SKILL_DIR}/agents/qa-agent.md`. Every lane uses that definition;
  this contract does not restate it.

## Role-specific close-out

Role-specific close-outs are additive. They
never substitute for the seven required sections: a lane that posts its
role-specific artifact — a QA PR comment, a reviewer finding list — and replies
nothing has not reported.

- **Worker** (`worker-new` / `worker-fix`): report the created PR URL and the
  exact head commit, then stop and wait for review or shutdown.
- **Graft Evidence** (when any gate in the lane requested graph evidence per
   `${CLAUDE_SKILL_DIR}/graft.md`): this contract applies uniformly to every lane
   that requests graph evidence (worker-new, worker-fix, qa-agent, phase2,
   phase4 — the five prompt sites). Include in the report-back the three ledger
   fields for each gate: `graft_version` (string or `null`), `graph_evidence`
   (`present` | `unavailable`), and `graph_evidence_cause` (`null` |
   `not_installed` | `version_mismatch` | `build_failed` | `unparseable_output` |
   `query_failure`). When `graph_evidence: present`, include the query output
   (trimmed) and the `graft check` freshness result. When `graph_evidence:
   unavailable`, include the recorded cause and a description of the manual
   fallback actually performed for the failed query type:
     - `graft callers` failure → call-tree trace (manual or via `rg`/`git grep`)
     - `graft grep` failure → `rg` or `git grep` against the symbol/regex
     - `graft map` failure → call-tree trace (manual or via existing call-graph analysis path)
     - invalid JSON from any query → classified as `query_failure` with `graph_evidence: unavailable` and the manual fallback recorded
   Silence never passes — a lane that records `unavailable` without documenting the manual fallback is incomplete.
- **QA** (`qa-agent`): use the QA report template as the role-specific form of
  the contract and finish with the outcome close-out
  `QA ✓ Pass — outcomes: [n] pass, 0 fail, 0 inconclusive, [n] not_applicable`;
  the per-criterion and per-check outcomes (`pass | fail | inconclusive |
  not_applicable`, each with evaluator type, executor, evidence reference and
  reason) live inside the existing sections 4 and 5, not in an added section. A
  health score line is optional and never decides; a lane that is not a clean
  pass reports `Needs Fix` with its evidence and stops.
- **Reviewer** (`reviewer`): repeat the correlation ID, the reviewed commit,
  and clean-worktree evidence; classify findings `blocking` / `advisory` /
  `question` / `clear`.
- **Prototype** (`worker-prototype-*`): report the artifact + readout paths and
  the decision point answered; do not restate the full readout.

A change to `headRefOid` marks the new head pending and requires fresh review
results. Approval from the previous head does not apply to the new head; retain
the prior report-back only as historical evidence. A correction review issues a fresh report under **Review after
fixes** in `${CLAUDE_SKILL_DIR}/phases/phase4.md`, naming the reviewed base, target
head, scope, executed checks and remaining findings.
