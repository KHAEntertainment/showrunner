# Traycer Execution Adapter

Use this adapter only when detection returns `traycer`. Any missing CLI/Host/authentication/permission/A2A capability, malformed JSON or NDJSON, missing page, or unverified response makes the operation `incomplete`; never fall back to Claude-native.

## Wrapper route

Every Traycer CLI step — whoami, host status, agent list/create/send/inbox/transcript/stop/archive, worktree create, and selection-guide — runs as `rtk proxy python3 ${CLAUDE_SKILL_DIR}/scripts/traycer_cli.py <traycer args>`. Prose below that names one of those commands (`agent inbox`, `agent list`, and so on) means that route, and the code blocks spell it out. Never invoke `traycer` directly, and never through a bare `rtk proxy traycer`: the CLI takes its caller and epic from `TRAYCER_AGENT_ID` and `TRAYCER_EPIC_ID`, and the wrapper is what supplies them when the harness does not export them.

The wrapper applies the detector's own lookup and rules. With both identifiers in the environment it runs `traycer <args>` unchanged and passes stdout, stderr, and the exit code through. With neither in the environment and a valid `.agent/traycer.env`, it exports both identifiers from the file first. When it cannot run `traycer` it writes nothing to stdout and one line of JSON to stderr, `{"traycer_cli":"error","code":...,"reason":...}`, then exits 78 for `no_usable_identity` or 69 for `traycer_not_found` or `traycer_exec_failed`. Any such failure makes the operation `incomplete`: the exit codes are chosen not to collide with `traycer`'s own, and the `traycer_cli` key on stderr is the definitive discriminator.

A Codex terminal lead's default sandbox blocked the CLI's network access: `traycer_cli.py` calls returned `E_AUTH_NETWORK` or `E_HOST_UNREACHABLE` until the user approved escalation (Issue #91 live probes); a Codex chat lead ran the same calls without it. A Codex lead that hits those errors asks the user for network access for the CLI, by approval or by sandbox setting. Until it is granted those errors make the operation `incomplete`, as any other CLI failure does.

## Supplied identity

The detector returns `traycer` in two ways, recorded in the ledger as `backend_source`: `detected` when both identifiers are in the environment, and `supplied` when neither is and `.agent/traycer.env` at the worktree root holds both. The worktree root is the first directory, walking up from the current directory, that has a `.git` entry. There is no override flag. Sources are never mixed: with exactly one identifier in the environment the file is not opened and the result is `incomplete`.

The file is exactly two lines, in either order, each `export KEY=value`:

```text
export TRAYCER_AGENT_ID=<agent-id>
export TRAYCER_EPIC_ID=<epic-id>
```

A value is one or more of `A-Z a-z 0-9 . _ : -`; quotes, spaces, and shell metacharacters are rejected. An extra line, a missing key, an empty value, a duplicate key, a wrong key name, an unreadable file, or any other departure from this format makes detection `incomplete` with a reason naming the defect; the file is never partially read. The file holds identifiers, never secrets, so it carries no permission requirement.

**Identity acquisition rule.** When the detector returns `incomplete` inside a Traycer session with neither identifier in the environment, the lead obtains its identity as follows and never guesses an id:

1. Take the agent id from the session's own self-identity source.
2. Take the epic id from the Traycer session context the harness was given: the task id in the `Agents in task '<epic>' (relative to you):` header the harness's agent-list tool prints (`traycer_list_agents` in the Traycer MCP tools), or the epic label in the harness's own system context. `agent list --json` carries no epic or task field (its `data` holds only `caller`, `scope`, and `agents`), so the CLI cannot supply it.
3. For either id not available that way, use the id given in the user's invocation message.
4. If one is still missing, ask the user once and stop until answered.

Never derive an id from a path guess, a directory name, or another agent's record. A working directory that happens to sit under `~/.traycer/epics/<epic>/` is a path guess, not a source. Then write `.agent/traycer.env` once, in the format above, and confirm it is git-ignored or excluded: `git check-ignore -q .agent/traycer.env`, and when that fails, add `.agent/` to the file named by `git rev-parse --git-path info/exclude`. Re-run `${CLAUDE_SKILL_DIR}/scripts/detect_execution_backend.py`; it must now return `traycer` with `backend_source: supplied`. Preflight step 3 then checks the pair, which reduces but cannot eliminate the chance of accepting a wrong one. That the harness's own agent can read these two sources was verified live for Codex and OpenCode leads on Traycer's chat surface on 2026-10-03 (Issue #91). Codex and OpenCode terminal agents receive both identifiers in the environment, so this path does not apply to them.

**Partial environment.** The file applies only when neither identifier is in the environment. With exactly one identifier present the detector ignores the file, so a partial environment cannot be recovered by the file. The lead records `incomplete`, reports the partial environment to the user as a host defect, and stops. It never sets or unsets `TRAYCER_AGENT_ID` or `TRAYCER_EPIC_ID` itself to make the file apply.

**The CLI's self marker is not evidence.** The `isSelf` marker on an `agent list` row and the `data.caller.agentId` block are derived by the CLI from the two supplied identifiers, so a wrong pair reports itself as the caller. They are not evidence of the caller's identity, for a supplied identity or any other, and no step in this adapter treats them as such. The checks in Preflight step 3 replace the marker. They reduce, and do not eliminate, the chance of accepting a wrong pair.

## Preflight

1. Confirm both session identifiers, and their `backend_source` (`detected` or `supplied`), were recorded by the detector.
2. Run `rtk proxy python3 ${CLAUDE_SKILL_DIR}/scripts/traycer_cli.py whoami --json` and `rtk proxy python3 ${CLAUDE_SKILL_DIR}/scripts/traycer_cli.py host status --json`; authentication and Host must be verified rather than inferred.
3. Query the current lead with `rtk proxy python3 ${CLAUDE_SKILL_DIR}/scripts/traycer_cli.py agent list --json`, then verify the identity. In a busy task the unfiltered output runs past 80 KB and overflows a harness's tool buffer, so filter it to the rows needed (`jq` or a short `python3` filter; for example `... agent list --json | jq --arg id <agent-id> '.data.agents[] | select(.id == $id)'`) and never print it whole. Every other `agent list --json` in this adapter is filtered the same way.
   - **Row facts (`detected` and `supplied` alike).** The row whose `id` equals the recorded `TRAYCER_AGENT_ID` must exist; verify its harness (`harnessId`), model, and reasoning effort, and that the session's epic matches the recorded `TRAYCER_EPIC_ID`; otherwise `incomplete`. The `isSelf` marker and `data.caller.agentId` are derived by the CLI from the two identifiers and are not evidence of the caller's identity, so a row marked `isSelf: true` proves nothing here. A `detected` identity is trusted because the host injected it into the environment, not because of that marker.
   - **A `supplied` identity is also checked two ways, and neither check is proof.** Check (a) establishes the agent id when a self-identity source exists; check (b) corroborates it and is the weaker of the two. Together or alone, they reduce, and do not eliminate, the chance of accepting a wrong pair.
     - **(a) Self-source comparison.** When the session has its own self-identity source, the recorded agent id must equal the id that source reports. This is mandatory whenever the source exists, including when the id came from the user's message.
     - **(b) Row corroboration.** In the `agent list` output, the row whose `id` equals the recorded agent id must exist, its `folderPaths` must include the lead's current worktree root (compared as real paths), and its `harnessId` must be the harness the lead itself knows it is running on. A wrong id belonging to another agent fails this unless that agent shares the same worktree and harness. Check (b) counts as not made only when the row carries no `folderPaths` at all; a missing row or a mismatch is a failure, not an inability.
   - **Verdict.** A failed (a) or a failed (b) is `incomplete`: the identity is wrong, and the lead deletes or corrects `.agent/traycer.env` before anything else. When (a) cannot be made because no self-identity source exists, (b) alone is the floor and the ledger records that. When (b) cannot be made and (a) passes, (a) alone verifies it. When neither can be made, the result is `incomplete`. Record which check verified the identity in `identity_verification` (allowed values in `${CLAUDE_SKILL_DIR}/templates/DEV_STATE_TEMPLATE.md`); a `detected` identity leaves it `null`.
   - **Residual limits.** (b) cannot distinguish two agents that share one worktree and one harness, so row corroboration accepts a wrong id that belongs to an agent sharing the lead's worktree and harness. Read-only QA and review lanes that share a checkout with the lead are the realistic way this happens. `worktree_match` stays the floor, because failing closed without a self-identity source would make a lead impossible on any harness that has none. A lead verified by `worktree_match` alone says so to the user in its first status reply. Neither check corroborates the epic id beyond the session context it came from.
   - The CLI derives epic and caller from the two identifiers and accepts no `--epic-id` or `--sender-agent-id` flags, which is why these checks exist.
4. Query available values with `agent list-harnesses`, `agent list-harness-models <harness> --json`, and `agent list-profiles <harness> --json` before launching a configured route. The last two take the harness as a positional argument, once per harness a route names; without it they fail with `E_INVALID_ARGUMENT`.
5. Read workspace `.traycer/agent-selection-guide.md` directly when present. The current CLI `agent selection-guide` (through the wrapper) exposes the global guide; query it only after the workspace guide.
6. Verify the selected Chat/GUI surface can receive A2A messages. V1 must create managed children with `--surface gui`; Terminal agents for Codex/OpenCode can send/read but are not valid receive-capable v1 children.

## Route resolution

Resolve each role in this order:

1. Explicit `PROJECT_CONTEXT.md` Execution Routing Policy.
2. Workspace `.traycer/agent-selection-guide.md`, read directly.
3. Global `rtk proxy python3 ${CLAUDE_SKILL_DIR}/scripts/traycer_cli.py agent selection-guide --json`.
4. Lead route from the lead row in `rtk proxy python3 ${CLAUDE_SKILL_DIR}/scripts/traycer_cli.py agent list --json`.

Validate harness, model, profile, reasoning effort, and permission mode against the preflight lists before launch. An invalid field, unavailable model/profile, or unsupported reasoning/permission value makes route resolution `incomplete`; do not substitute another route. On lead fallback, inherit harness/model/reasoning. Omit profile intentionally so Traycer uses `last_used`, and record profile as `value: omitted`, `source: traycer_last_used`. Do not add cost, rate-limit, or performance routing heuristics. The external-review rate-limit breakpoint in `${CLAUDE_SKILL_DIR}/phases/external-review.md` is a documented SOP exit, not a routing heuristic: its substitute reviewer comes from the review routes resolved above, and this route resolution is otherwise unchanged.

Traycer currently defaults creation to `full_access` unless an explicit selection guide chooses `supervised` or `auto_accept_edits`. Do not invent `read_only`. QA/review safety is enforced by their prompts and verified by a clean worktree check plus immutable local `HEAD` and PR `headRefOid` checks against the recorded target commit.

## Worktree preparation

The lead owns branch/base/path requirements; Traycer owns creation mechanics:

```text
rtk proxy python3 ${CLAUDE_SKILL_DIR}/scripts/traycer_cli.py worktree create --workspace <source-workspace> --source-branch <verified-base> --branch <assigned-branch> --json
```

The adapter must never use `--carry-uncommitted`. Parse the structured response, then independently verify absolute source/run paths, assigned branch, base OID, and clean status. Record the exact source-workspace/worktree relationship before launch.

## Launch and messaging

Create one Chat/GUI agent bound to the exact source/run relationship:

```text
rtk proxy python3 ${CLAUDE_SKILL_DIR}/scripts/traycer_cli.py agent create --surface gui --workspace-entry <source-workspace>=<worker-worktree> --harness <harness> --model <model> [--profile <profile>] [--reasoning-effort <level>] [--permission-mode <mode>] --json
```

Do not combine `--cwd` with the same workspace entry. Parse and record the new agent ID; require reviewer and QA IDs to differ from implementation IDs.

Send the full provider-neutral assignment and require a correlated reply:

```text
rtk proxy python3 ${CLAUDE_SKILL_DIR}/scripts/traycer_cli.py agent send --to <agent-id> --message <assignment> --expect-reply --json
```

The assignment must embed the report-back contract from `${CLAUDE_SKILL_DIR}/agents/report-back.md`, so the lane receives it as adapter payload and not only through its role prompt. Sending without `--expect-reply` is never a way to dispatch a lane that is not expected to report.

Record the returned response ID. Absence of an ID or an incomplete structured stream is `incomplete`.

## Observation, shutdown, and recovery

- Read `agent inbox --agent-id <lead-agent-id> --json`, passing each returned cursor/page token according to the installed CLI contract until the response declares completion; never treat the first page as complete.
- **Classify `absent` before anything else.** When the bounded inbox read ends, first ask whether it produced a reply correlated to the recorded response ID. If it did not, record `report_back: incomplete` and the read's `report_back_termination` — the read ran, so it ended somehow — then stop without checking sections. The cause is `absent` only when that condition was `completed`, meaning the inbox declared itself exhausted and the reply was not in it; a read cut short — `stalled`, `page_cap`, or `time_bound` — records `truncated`, because the reply may lie past the cut and nothing about the lane has been established. Both empty reads look identical in the inbox and mean opposite things: an exhausted inbox with no correlated reply says the lane did not reply, while one that ended `stalled` on a non-advancing cursor says only that reading stopped. Recording which condition ended it is the entire difference. After a lead change, an inbox read that ended `completed` with no correlated reply, and would therefore record `absent`, consults the swap-time evidence rule below, and only for the narrow case that rule defines; every other read is classified exactly as stated here.
- **Bound that read.** It ends on the first of: the response declares the reply complete (`completed`); a page returns no new content or a cursor equal to the one just sent (`stalled`); **20 pages** consumed (`page_cap`); **120 seconds** elapsed across the read (`time_bound`). Record which of the four ended it as `report_back_termination` and derive the verdict and cause from the ledger mapping using termination, reply correlation, and section presence; termination decides whether section inspection is permitted. The stall condition is the one that fires in practice: a transport that never declares completion returns a non-advancing cursor rather than an error, and without it the other two bounds only delay the same loop.
- Use `agent transcript --json` and `agent list --json` to verify replies and live state. Correlate replies to the recorded response ID.
- Having correlated a reply, verify it carries all seven required sections — Outputs; Commands + exit codes; Deviations; Quality-gate self-assessment; Acceptance criteria; Evidence; Scope / ownership — by case-insensitive heading presence, each with content under it. A missing section fails the lane closed per the report-back enforcement section of `${CLAUDE_SKILL_DIR}/backends/contract.md`: record `report_back: incomplete` with cause `malformed`. A lane whose recorded response ID never produced a reply was already recorded `absent` by the precedence rule above and never reaches this check; `agent list` showing the agent alive and idle is not a completion signal. Check shape only when the bounded read above ended on the completion signal. If it ended `stalled`, `page_cap`, or `time_bound`, record cause `truncated` regardless of which sections are present, and re-read rather than re-request.
- **Swap-time evidence (after a lead change only).** Traycer pushes a lane's reply into a GUI lead's session and acknowledges it, so after a lead change both leads' inboxes can read empty although the lane did report; the transcript of the lead that dispatched the lane is then the only surviving evidence. This rule decides only whether such a message counts as the correlated reply. It adds no row, termination value, or cause to the mapping in `${CLAUDE_SKILL_DIR}/templates/DEV_STATE_TEMPLATE.md`, which applies unchanged. It is consulted only when all three conditions hold, and a missing condition leaves the result exactly as the `absent` classification above set it:
  1. **A swap occurred.** The lead's verified agent id differs from the lane's recorded `dispatched_by`. A worker entry with no `dispatched_by` fails this condition, so the rule does not apply to it and its empty read stays `absent`. The previous lead's session id comes only from `dispatched_by`, never from a path guess, a directory name, or another agent's record.
  2. **Both inbox reads ended `completed` with no correlated reply.** That is the new lead's own bounded inbox read and the bounded `agent inbox --agent-id <dispatched_by> --json` read. A read that ended `stalled`, `page_cap`, or `time_bound` stays `truncated`, and this rule is never consulted: the swap rule never upgrades a truncated read.
  3. **A qualifying message exists in the previous lead's transcript.** `agent transcript --agent-id <dispatched_by> --json` holds a message that comes from the lane's recorded `agent_id` (the sender id in its `Agent message from <title> (agent <id>)` header, never the title and never an id mentioned in the body), was sent after the recorded `dispatched_at`, and contains the recorded `communication_response_id` verbatim and in full; a prefix, a different id, or a paraphrase does not match. When several qualify, the latest counts. A message from any other agent that quotes the id, such as the previous lead, a QA lane, or a reviewer, never qualifies.

  The transcript has no pages, so its read ends `completed` when the NDJSON stream ends cleanly, and `stalled` or `time_bound` (**120 seconds**) otherwise; a transcript read that errors, or yields malformed NDJSON, did not end `completed`. When this rule consults the transcript, record that read's condition as `report_back_termination`; the inbox `completed` is its precondition. A qualifying message with a `completed` stream is the correlated reply and is judged on its sections as above: all seven present is `complete`, any missing is `malformed`. No qualifying message with a `completed` stream stays `absent`. A transcript read that did not end `completed` records `truncated`, because a cut read cannot establish absence.
- When replying in the opened thread, pass its `--response-id`; a mismatched or absent correlation fails closed.
- Send a final status/report request before `agent stop`. Archive with `agent archive` only after the result is recorded. During preflight, verify the installed CLI exposes both commands and their current target-ID flags; if not, mark shutdown capability incomplete rather than guessing syntax.
- Delete worktrees only through the existing post-merge safety gate; stopping or archiving an agent does not authorize deletion.
- On recovery, load the YAML ledger, run `dev_state.py --validate` to check profile compliance, then re-run the detector (a `supplied` identity is re-read from `.agent/traycer.env`; a missing or invalid file is `incomplete`, never a reason to fall back), and verify the session's own agent id and epic id with `agent list` and the Preflight step 3 identity checks, consume pending inbox pages, reconcile transcript evidence, and update state before sending anything. Then compare the verified agent id with the recorded `execution.traycer_agent_id` (not `lead.agent_id`). Equal means the same lead is resuming. Different means a **lead swap**, not an identity failure: the recorded id is the previous lead's, so the lead appends a recovery entry naming both ids, sets `execution.traycer_agent_id` to the verified id, and leaves every lane's `dispatched_by` unchanged; the swap-time evidence rule above applies per lane from there. Only a failed Preflight step 3 check is an identity failure, a verified epic id that differs from the recorded `execution.traycer_epic_id` is never a swap and makes the operation `incomplete`, and a swap never relaxes any Preflight step 3 check. Never duplicate an agent whose live state cannot be determined.

## Harness compatibility boundary

Traycer adapts launch, model/profile selection, worktree binding, and A2A transport. It does not translate Claude slash-command syntax or install `/dev` in another harness. Codex, OpenCode, Cursor, and other supported harnesses can execute provider-neutral worker/QA/reviewer assignments without their own `/dev` copy. A native non-Claude lead entrypoint would be a separate thin distribution over this same contract.
