# Goal Run — bounded execution over a frozen Issue set

---

Enter this file only from the Phase 0 **Goal Run** row: the user explicitly approved a goal, and its plan, PRD, Issue or milestone resolves to a nonempty fixed set of qualified Issues (`OWNER/REPO#N`). One loop owns the run. Each frozen Issue still goes through its own normal path, and Phase 3.5 runs per risk tier, exactly as the Phase 0 router says.

## Runtime requirement

This procedure calls `${CLAUDE_SKILL_DIR}/scripts/goal_run.py`. If the installed runtime has no `goal_run.py`, stop: tell the user this Dev install cannot run goal runs, and offer the ordinary Phase 0 rows instead. Never imitate the module by hand.

`goal_run.py` is pure. It reads no clock, writes no file, and grants no authority. The lead supplies every time (`now`, `approval_time`, `next_wake_at`) as strict UTC ISO 8601 (`Z` or `+00:00`), persists every result, and enforces who may decide what. Call it from the resolved `execution.skill_dir`:

```bash
rtk proxy python3 - <<'PY'
import sys
sys.path.insert(0, "<execution.skill_dir>/scripts")  # substitute the resolved path
import goal_run
# build inputs from the ledger, call the function, print the Result fields
PY
```

Every call returns a `Result` with `outcome`, `reason`, `value` and `detail`. `ok` only means "not `invalid`" and is never permission.

- **Calls whose success outcome is `accept`** (`arm`, `normalize_entry`, `apply_policy`, `guard_frozen_scope`, `account_dispatch`, `extend_limit`, `classify_input`, `classify_question`, `make_handback`): proceed only when `may_proceed` is true.
- **`evaluate_limits` gates continuation by its own outcomes:** `complete` means continue; `incomplete` means stop the affected scope and report the limit named by `reason`; `invalid` (for example a malformed `approval_time`) stops the run. Its `may_proceed` is always false, so read `outcome`.
- **`parse_turn_end_marker`** returns `accept` only for a matching `WAKE`; `claim_requires_gv` and `protected_stop` are handled as step 4 says.

## Ledger fields this phase writes

The lead is the sole writer of `.agent/dev-state.md`. This phase writes only the `goal_run` block documented in `${CLAUDE_SKILL_DIR}/templates/DEV_STATE_TEMPLATE.md` (Goal run record schema) and the existing top-level `next_action`:

- the frozen scope: every key of `Assignment.to_dict()` (`run`, `mode`, `repo`, `fixed_issues`, `source`, `approval_revision`, `lead`, `plan_ref`, `coordinator`, `charter_revision`, `contract_refs`);
- `approval_time`, `next_wake_at`, `paused`;
- `policy`: the `BoundsPolicy` fields (`run_time_hours`, `dispatch_cap_per_issue`, `gv_retries`, `spend_cap`);
- `counters`: the `RunCounters` fields (`dispatch_counts`, `dispatch_request_ids`, `request_issues`, `spend`) plus the ledger-only `usage_measured` and `gv_retries_used`.

After every write, run `rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/dev_state.py" --validate .agent/dev-state.md`. A failure names the field (`goal_run.<field>: <reason>`); repair the ledger before any further step.

## 1. Arm

1. Build the entry from the approved goal: `repo`, `run`, `mode` (`standalone` or `managed`), `lead`, `plan_ref`, `source` (`path@revision`), `approval_revision`, and `fixed_issues`. Managed mode adds `coordinator`, `charter_revision` and `contract_refs`. For a milestone entry, pass the Issue list resolved once at approval as `resolved_issues`; a milestone query is never a moving target.
2. Call `arm(entry, resolved_issues, deliverable_type, project_policy, goal, coordinator)`. `project_policy` is the run-bounds defaults from `PROJECT_CONTEXT.md` (omit for the D3 defaults), `goal` is the owner's narrowing at approval, and `coordinator` is a managed coordinator's tightening. `arm` runs `normalize_entry` and `apply_policy` itself.
3. On outcome `invalid`, do not start. Report the `reason` code to the user and stop. Refusal codes include `empty_issue_set`, `cross_repo_issue`, `bare_ambiguous_issue_id`, `duplicate_issue`, `non_pr_goal`, `managed_missing_bindings`, `approval_revision_mismatch`, `source_revision_missing`, `source_revision_mismatch`, `machine_specific_path`, `missing_resolved_issues`, `goal_widening`, `coordinator_loosening`, `coordinator_in_standalone` and `invalid_policy_value`.
4. On `accept`, `value` is an `ArmedRun`. In one ledger write, record `assignment.to_dict()`, `policy`, `approval_time`, `next_wake_at: null`, `paused: false`, and the initial counters: empty `dispatch_counts`, `dispatch_request_ids` and `request_issues`; `usage_measured: true` only when the harness reports usage, with `spend` as a number, otherwise `usage_measured: false` and `spend: unknown`; `gv_retries_used: 0`.
5. If `spend_cap` is set and usage is not measured, the approval message tells the user the cap cannot be enforced (D3).

## 2. Frozen scope and mode guard

The Issue set and the mode are frozen at arming. Before acting on anything that would change either, call `guard_frozen_scope(scope, mode, fixed_issues)` with the frozen `Assignment` or `ArmedRun` as `scope`. On `invalid` (`managed_to_standalone`, `standalone_to_managed`, `mode_change`, `scope_growth`), refuse the change and keep the frozen scope. A request outside the frozen set becomes a handback (step 6); it never grows `fixed_issues` and never silently downgrades the mode.

Each frozen Issue then follows its full normal Phase 0 row, in the order recorded at arming, including Phase 1.5 where that row has it, under the existing approved-plan and no-reask rules (the lead never re-asks a locked decision). A goal run skips no phase that an Issue's row requires: Phase 3.5 runs per risk tier, then Phase 4 and Phase 5.

## 3. Bounds (D3)

Rebuild a `RunCounters` from `counters` (each `dispatch_request_ids` list back to a set) before each call, and write the counters back after it.

1. **Every dispatch.** Before starting any agent for an Issue (worker, QA, reviewer, fix worker or substitute), call `account_dispatch(counters, issue, request_id)` with the backend's request or response id. A repeated `request_id` counts once. `request_id_conflict` is `invalid`: stop and report.
2. **Every dispatch and step boundary.** Call `evaluate_limits(policy, counters, approval_time, now, dependencies)`. `dependencies` maps an Issue to the Issues it depends on. This outcome, not `ok` or `may_proceed`, decides whether the next dispatch or step may start:
   - `complete`: continue.
   - `invalid`: stop the run and repair the input it names; start nothing.
   - `incomplete`: a limit is reached, named by `reason` (`run_time_exceeded`, `spend_cap_exceeded`, `dispatch_cap_exceeded`). Follow D3. Finish or roll back the step in hand to a safe point. Start no new work and make no merges for the affected scope: the whole run, or for `dispatch_cap_exceeded` only the `incomplete_issues` (the `continue_issues` go on). Save the counters, and report the run or Issue as incomplete, naming the limit.
   - Unknown `spend` never stops a run. Run time and dispatches bound it instead, and the report says so (`spend_cap_enforceable` is false).
3. **Extensions.** Only the owner extends a limit. Apply the owner's new value with `extend_limit(policy, field, new_value)`, write the returned policy, and leave `counters` untouched. A compaction, wake, restart or lead change never renews a limit or resets a counter.

Existing limits stay in force alongside D3: fix batches per defect episode, external review waits and rate-limit retries, and the local heavy-run rule.

## 4. Turn end

The last nonempty line of a turn may carry one marker: `HARD-STOP: H<1-5> — <reason>`, `WAKE: <UTC time> — <action>` or `GOAL-COMPLETE: <source>` (an em dash before the argument). Parse it with `parse_turn_end_marker(text, expected_source, next_wake_at, next_action, paused, now)`, passing the persisted `next_wake_at`, top-level `next_action` and `paused`, and the frozen `source` as `expected_source`.

- `claim_requires_gv`: a completion **claim**, never proof. Nothing is complete because of it. This runtime has no GV step. Completion is decided by the existing Dev gates (Phase 4 and Phase 5 for every frozen Issue), and GV with its retry bound (`gv_retries`, `gv_retries_used`) is governed by the existing gates until a GV lane lands.
- `protected_stop`: escalate to the user immediately with the `detail` level and reason. H1–H4 are protected stops: "proceed unless stopped" never applies to them. H5 is an unrecoverable failure after the finite permitted retries: report the run incomplete and do not retry.
- `accept`: a `WAKE` that matches the persisted `next_wake_at` and `next_action`. Continue with that action. A wake renews nothing and creates no scheduling capability the harness lacks.
- `invalid` (`no_marker`, `marker_not_last`, `multiple_markers`, `malformed_marker`, `wrong_source`, `wake_mismatch`, `wake_during_pause`, `wake_time_not_utc`): the marker verifies nothing and schedules nothing. Record the reason, mark nothing complete, and continue only under the existing gates.

Sleep only after persisting both `next_wake_at` and `next_action`. A pause is recorded as `paused: true`; a wake never overrides it.

## 5. Inputs and questions

At every step boundary, check for user messages. A user message can stop or revise pending work; acknowledge it before continuing.

Classify each correlated input with `classify_input(payload)`, which needs an explicit `kind` (`context`, `work` or `question`):

- `context_only`: context for the run. A context-only input cannot add an Issue or change acceptance; `context_only_scope_change` is `invalid`, so ask the user.
- `authorized_work`: still passes `guard_frozen_scope` before it is acted on.
- `lead_resolvable` (an `engineering` question): the lead decides and records the gate, decision, reasoning, evidence pointer and reversal path (D7.2 control record).
- `user_owned` (`product`, `scope`, `acceptance`, or any missing or unknown kind; `classify_question` fails closed to the user): ask the user one question at a time, with a recommendation. Work that depends on it waits; independent work continues.

## 6. Handback

Return an out-of-scope request to the lead with `make_handback(request_ref, reason)`. The record carries `reference`, `reason` and `disposition` (`pending` until the lead disposes of it). A handback never grows `fixed_issues` and never escalates to the owner on its own.

## Where the existing Dev gates govern

A goal run grants no merge, release, credential or other Tier C authority, and delegation never renews an exhausted budget. For the following, existing Dev gates govern:

- **Merges and gate disposition:** the existing Phase 4 and Phase 5 merge rules and the user's merge authority.
- **Recovery and resume** after a restart, compaction or lead change: the existing recovery procedure from `.agent/dev-state.md` in `SKILL.md`. Counters persist and are never renewed.
- **GV:** completion stays a claim until the existing gates verify every frozen Issue.
