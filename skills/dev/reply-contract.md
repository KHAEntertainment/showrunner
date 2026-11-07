# Lead-to-User Reply Contract

Delegated lanes report to the Tech Lead through `${CLAUDE_SKILL_DIR}/agents/report-back.md`. This file governs the other side of that boundary: what the Tech Lead then says to the human user at the end of a turn. The two contracts are not the same shape and must not collapse into each other — a lead that pastes the worker's seven-section report back to the user has not summarized anything, it has relayed it.

## 1. Scope

This contract governs only the Tech Lead's end-of-turn replies to the user in the main `/dev` conversation. Before sending, run `${CLAUDE_SKILL_DIR}/scripts/dev_state.py --validate` on `.agent/dev-state.md` to confirm ledger integrity; if validation fails, report the named error to the user and repair the ledger. It never governs:

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
- A gate verdict (QA outcome conclusion, review rating, external-review outcome) once one exists.
- A decision the user must make (an ambiguous acceptance criterion, a scope conflict, a merge-order choice).
- Confirmation before an irreversible action (a merge, a force-push, a deletion, a bypass).
- A security or data-loss finding, at any severity.

These are surfaced first, ahead of any other content in the same reply, and never trimmed to fit the routine-turn word target.

**Goal-run merges under a D2 grant (SDP D2 item 6).** In a goal run, a valid bounded grant in force counts as the confirmation this section requires for a merge: when `decide_merge` in `${CLAUDE_SKILL_DIR}/scripts/goal_authority.py` returns `accept` for a PR at its reviewed head, the lead merges without asking again. The lead sends the user a notice for each merge and each failure, surfaced first like the items above, and waits for no acknowledgement. Without a grant in force (no grant, a `confirm_each` result, or outside a goal run), the confirmation above stands. The grant covers merges only, never a force-push, deletion or bypass.

## 4. Carve-out — the cap counts prose, not required structured artifacts

The cap counts prose, not required structured artifacts. Where a Phase explicitly requires an artifact to reach the user in full, that artifact is emitted whole and the cap applies only to the sentences the lead adds around it. Named exemptions:

- Phase 1's progress breadcrumb and its one-question block.
- Phase 1.5's proposed-locked list with its stated counts.
- Phase 1.5's gap question with its recommendation.
- Phase 3's Backend-Neutral Task Board.
- Phase 4's review rating.
- Phase 5's retro and technical-debt-sweep templates.

Emitting one of these in full is compliant even when doing so exceeds 100 words; padding it with restated plan content or a pasted report is not.

## 5. Pull principle

Internal lane output is pulled, not pushed: the lead reads a worker/QA/reviewer report or a prototype readout, extracts the delta the user needs, and reports that delta. The full report stays in the backend transcript — the conversation in which the lane was dispatched and replied — and, for the QA and review lanes, in that lane's PR comment. `.agent/dev-state.md` records the **verdict** of that lane, not the report's text: the status, the cause, the ids, the next action, and nothing more, which is what `${CLAUDE_SKILL_DIR}/templates/DEV_STATE_TEMPLATE.md` defines the ledger to hold. A later lane or a recovering lead therefore pulls the full report from the transcript or the PR record, never from the ledger, and a reply that reported the delta has discarded nothing. This generalizes the don't-relay rule `${CLAUDE_SKILL_DIR}/phases/phase1-prototyping.md` already states for prototype readouts to every delegated lane's output.

## 6. Composition note

`/dev` never claims a task-requirements override to justify verbosity. A session brevity skill that requires explicit activation and permits overriding task requirements when it is active is not overridden by this Skill's own reporting habits — `/dev`'s reply behavior composes with whatever brevity skill governs the session, rather than treating its report-back detail as license to ignore one. This note is intentionally third-party-agnostic: it names no specific brevity skill. Skill-specific compatibility notes belong in project documentation, not in this payload.

## 7. Cleanup line and consolidation offer (Issue #73)

The end-of-turn reply carries exactly **one** `Cleanup:` line whenever this turn retired something or inventory rows from `${CLAUDE_SKILL_DIR}/templates/DEV_STATE_TEMPLATE.md` remain open. The line is a structured summary, not prose; it surfaces so the user can scan it without scrolling past the verdict. The shape is fixed so a single parser can teach the lead what each field means:

```
Cleanup: retired <N> (<comma-separated kind:count>). Still open: <role-or-id> (<status reason>). Not mine: <id> idle (<backend hint>).
```

Fields, in order:

- `retired <N>` — the count of artifacts this turn archived, stopped, or removed (with their kind), grouped by what the lead actually did (lanes archived, shells stopped, review checkouts removed, agents archived on accept). Zero is itself a value and must be quoted as `retired 0`.
- `Still open:` — every inventory row whose `state` is anything other than `archived`, `landed-eligible-and-approved`, or `cleaned`. The reason field is the row's `state`, never a paraphrase (e.g. `worker (PR not merged)`, `qa-blocked`, `review-checkout-uncommitted`). Rows the lead did not spawn appear here, not under `Not mine`.
- `Not mine:` — agents in this task whose `parentId` is not this lead, listed by id and a single backend hint (`idle`, `archived`, `sandbox-blocked`). The lead never stops or archives these. On the claude-native backend this field is always empty. On traycer, this field's source is the reconcile of § 7.3: its `not_mine` findings, which are listed agents in this project that are absent from the inventory, plus `foreign-*` inventory rows.

The cleanup line is a fixed-shape record; it does not bury debt or migration status, which live in the inventory and the post-merge verification record respectively. The cap of § 2 still applies to the prose around it.

### 7.1 Threshold-based debt line

When the project's workspace-debt gauge (Issue #73, `python3 ${CLAUDE_SKILL_DIR}/scripts/workspace_debt.py`) returns counts for this run's project that exceed the issue's threshold, the lead appends one **threshold debt line** to the cleanup line on the same line, separated by a single space, so a single regex can split them. The threshold is configured per project in `.agent/dev-state.md`; the default for the v2.1.2 dogfood is `worktrees.total > 5` OR `agents.active_not_mine > 0` OR `status == unavailable`. The line shape:

```
Threshold: debt <project> worktrees=<n>/<threshold> agents=<n> backend=<traycer|claude-native|unavailable> gauge=<ok|unavailable>
```

A threshold trip is **report-only**. The lead surfaces it so the user can decide whether to act, never acts unilaterally; the action is the consolidation offer below.

### 7.2 Consolidation offer

When the threshold debt line reports `gauge=ok` and `worktrees.total > threshold` (the worktree half of the threshold, not the union), the lead closes the reply with one **consolidation offer** that names the run's project, the count of landed-eligible worktrees, and the user action required (the wrapper's `worktree delete --path`, with review-tier rows approved one at a time). The offer is one line, ends in a single approval question, never commits to a deletion in the same turn:

```
Consolidation: <project> has <landed-eligible> landed-eligible worktrees (review-tier approved one at a time). Approve the deletion batch?
```

The lead never invents a count: the offer's number is the gauge's `counts.worktrees.landed_eligible` for this run's project, and the offer is omitted entirely when that field is `null` (an unavailable gauge) or `0`. Removing a worktree still goes through user approval per the consolidation batch in fix item 5 of Issue #73; the offer is a question, not a commit, and the lead does not pre-empt it by listing the paths in the reply body (they belong in the proposal the user reviews out-of-band).

### 7.3 Idle timeout at turn boundaries (Issue #112)

At the start and at the end of every lead turn on the traycer backend, the lead runs the inventory reconcile:

```
rtk proxy python3 ${CLAUDE_SKILL_DIR}/scripts/inventory_reconcile.py --dev-state .agent/dev-state.md --repo-dir <repo> --lead-agent-id <verified agent id> --shells-json <file>
```

`--shells-json` holds the lead's own shell listing (no CLI lists shells); it is required when the inventory has a `running` shell row. The script is **report-only**: it never archives, stops, deletes or messages anything. The lead acts on its report, and only on inventory rows:

- `status: unavailable`, for any `reason_code` (a CLI error or timeout, a partial or paged listing, an unreadable ledger, `two_active_writers`): act on nothing this turn and report it as `Still open: reconcile (unavailable: <reason_code>)`. `counts` is `null`; an unavailable report is never read as zero findings.
- `archive_due`: the agent has been idle for **more than** 60 minutes (exactly 60 is not due) with no open request. Archive it with `agent archive`, write its row `state: archived-idle-timeout`, and count it under `retired`. Archiving is reversible: the next message unarchives the agent and wakes it with its context. It never marks the agent's work done and never deletes its worktree.
- `blocked_by_open_request`: do not archive. List it as `Still open: <role-or-id> (idle >60m, open request: <id> <what>)`, naming every open request.
- `blocked`, `not_due`, `tracked`: no action. The row stays under `Still open` with its `state` as the reason.
- `target_gone`, `already_archived`: no action on the target. Correct the row in the ledger and report the correction.
- `not_mine`: list it under `Not mine:`. Never archive or stop it.

**The idle signal.** The Traycer agent listing has no last-activity timestamp, so the clock is the ledger's `last_exchange_at` (inventory schema in `${CLAUDE_SKILL_DIR}/templates/DEV_STATE_TEMPLATE.md`). The lead writes it on every send to that agent and on every reply received from it. When it sends a request that expects an answer, starts a wait, or holds a shared-surface grant with that agent, it adds an `open_requests` entry, and it removes the entry only when that request is answered. A row missing either field is never archived. A listing that shows the agent active overrides the clock.

**Lead swap.** The reconcile acts for exactly one writer of the run ledger: `lead.agent_id` and `execution.traycer_agent_id` must both equal `--lead-agent-id`. After a lead swap, the new lead updates both (the lead-swap recovery entry in `${CLAUDE_SKILL_DIR}/backends/traycer.md`) before it runs the reconcile. Until then the reconcile returns `two_active_writers`, and the lead acts on nothing and reports it.

**Two timers.** In a Foreman-managed run, Foreman's 4-hour close-out of a finished lane stays separate from this 60-minute idle archive (SDP D7.1 item 4). Neither replaces the other, and neither acts on agents its owner did not spawn.

On the claude-native backend there is no agent listing: the reconcile reports `counts.agents: not_applicable`, agent rows come out `not_applicable`, and there is no idle archive.
