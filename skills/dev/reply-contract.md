# Lead-to-User Reply Contract

Delegated lanes report to the Tech Lead through `${CLAUDE_SKILL_DIR}/agents/report-back.md`. This file governs the other side of that boundary: what the Tech Lead then says to the human user at the end of a turn. The two contracts are not the same shape and must not collapse into each other — a lead that pastes the worker's seven-section report back to the user has not summarized anything, it has relayed it.

## 1. Scope

This contract governs only the Tech Lead's end-of-turn replies to the user in the main `/dev` conversation. Before sending, run `dev_state.py --validate` on `.agent/dev-state.md` to confirm ledger integrity. It never governs:

- Agent-to-lead reports (`${CLAUDE_SKILL_DIR}/agents/report-back.md` is unchanged and still required in full from every delegated lane).
- Issue or PR bodies, which are the durable record and keep whatever detail they need.
- `docs/*.md` or other tracked project documentation.

A brevity requirement on what the lead says to the user is not a brevity requirement on what a lane records anywhere else.

## 2. Cap

Routine replies aim under 100 words. Within that budget:

- Do not restate an approved plan the user has already seen.
- Do not paste a worker, QA, or reviewer report, or any of its seven sections, verbatim into the reply.
- Do not ask a next-action question unless a decision is genuinely needed from the user — and then ask exactly one.

The cap is a target for routine turns, not a hard technical limit enforced character-by-character; it exists to keep the lead summarizing instead of relaying.

## 3. Exceptions — never compressed away

Some content is surfaced first and in full, regardless of the cap:

- A material failure (a gate that failed, a lane that could not complete its assignment).
- A gate verdict (QA health score, review rating, external-review outcome) once one exists.
- A decision the user must make (an ambiguous acceptance criterion, a scope conflict, a merge-order choice).
- Confirmation before an irreversible action (a merge, a force-push, a deletion, a bypass).
- A security or data-loss finding, at any severity.

These are surfaced first, ahead of any other content in the same reply, and never trimmed to fit the routine-turn word target.

## 4. Carve-out — the cap counts prose, not required structured artifacts

The cap counts prose, not required structured artifacts. Where a Phase explicitly requires an artifact to reach the user in full, that artifact is emitted whole and the cap applies only to the sentences the lead adds around it. Named exemptions:

- Phase 1's progress breadcrumb and its one-question block.
- Phase 3's Backend-Neutral Task Board.
- Phase 4's review rating.
- Phase 5's retro and technical-debt-sweep templates.

Emitting one of these in full is compliant even when doing so exceeds 100 words; padding it with restated plan content or a pasted report is not.

## 5. Pull principle

Internal lane output is pulled, not pushed: the lead reads a worker/QA/reviewer report or a prototype readout, extracts the delta the user needs, and reports that delta. The full report stays in the backend transcript — the conversation in which the lane was dispatched and replied — and, for the QA and review lanes, in that lane's PR comment. `.agent/dev-state.md` records the **verdict** of that lane, not the report's text: the status, the cause, the ids, the next action, and nothing more, which is what `${CLAUDE_SKILL_DIR}/templates/DEV_STATE_TEMPLATE.md` defines the ledger to hold. A later lane or a recovering lead therefore pulls the full report from the transcript or the PR record, never from the ledger, and a reply that reported the delta has discarded nothing. This generalizes the don't-relay rule `${CLAUDE_SKILL_DIR}/phases/phase1-prototyping.md` already states for prototype readouts to every delegated lane's output.

## 6. Composition note

`/dev` never claims a task-requirements override to justify verbosity. A session brevity skill that requires explicit activation and permits overriding task requirements when it is active is not overridden by this Skill's own reporting habits — `/dev`'s reply behavior composes with whatever brevity skill governs the session, rather than treating its report-back detail as license to ignore one. This note is intentionally third-party-agnostic: it names no specific brevity skill. Skill-specific compatibility notes belong in project documentation, not in this payload.
