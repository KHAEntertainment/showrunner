# Execution backends

`/dev` selects its execution substrate from the environment. Without Traycer identifiers, it resolves `claude-native` only when the lead positively identifies itself as a Claude Code session; missing or partial Traycer identity otherwise resolves to `incomplete` and pauses (see [Detection and fail-closed behavior](#detection-and-fail-closed-behavior)). It runs in two execution modes: **Claude-native** (default, no Traycer required) or **Traycer** (optional multi-harness execution). The lead is normally a Claude Code session; under the Traycer backend it can also be a Codex or OpenCode session (see [Running the lead from Codex or OpenCode](#running-the-lead-from-codex-or-opencode)).

## Claude-native — works without Traycer

When no Traycer session is present, the lead resolves the `claude-native` backend and records `backend_source: lead_resolved`. This mode runs entirely inside Claude Code and uses Agent Teams for parallel lanes — no Traycer, no tmux/iTerm. Anyone using `/dev` as a plain Claude Code skill stays on this path.

## Traycer — optional multi-harness

When both `TRAYCER_AGENT_ID` and `TRAYCER_EPIC_ID` are present, detection returns `traycer`/`ready` (`backend_source: detected`) and the lead loads the Traycer adapter at [`skills/dev/backends/traycer.md`](../skills/dev/backends/traycer.md). Traycer owns CLI worktree/session mechanics and launches receive-capable Chat/GUI child lanes on any supported harness (Claude Code, Codex, OpenCode, Cursor, …). Every Traycer CLI call goes through the `skills/dev/scripts/traycer_cli.py` wrapper (run as `rtk proxy python3 …/traycer_cli.py`), enabling cross-harness A2A coordination and managed transcript capture.

Each role's harness, model, provider profile, and reasoning effort are resolved in order from the `PROJECT_CONTEXT.md` Execution Routing Policy, the workspace `.traycer/agent-selection-guide.md`, the global Traycer agent selection guide, and finally the lead's own route. An invalid or unavailable route makes resolution `incomplete`; the adapter never substitutes another route. See [`skills/dev/backends/traycer.md`](../skills/dev/backends/traycer.md#route-resolution).

Capability-verified: any gap in a child harness surfaces as `incomplete`, not as a silent fallback. At first dispatch of a Traycer-managed lane, the child harness is checked against the capability checklist in [`skills/dev/backends/contract.md`](../skills/dev/backends/contract.md) (ADR-012).

## Detection and fail-closed behavior

`skills/dev/scripts/detect_execution_backend.py` decides the backend from the environment, or from a supplied identity file, and never probes binaries. Both identifiers in the environment → `traycer` (`backend_source: detected`). Neither in the environment but a valid `.agent/traycer.env` at the worktree root → `traycer` (`backend_source: supplied`; see [Running the lead from Codex or OpenCode](#running-the-lead-from-codex-or-opencode)). Anything else, including exactly one identifier in the environment, fails closed to `incomplete` (exit 2) and pauses rather than guessing. Because the absence of Traycer identifiers cannot distinguish a native Claude session from a Traycer child whose environment was not injected, `claude-native` is a **lead-resolved** choice backed by positive evidence, never an automatic fallback. The chosen backend is recorded in `.agent/dev-state.md` as `backend_source: detected | supplied | lead_resolved`.

## Running the lead from Codex or OpenCode

The `/dev` lead can run on Codex or OpenCode as well as Claude Code, so you can swap the lead to whichever harness is not rate-limited. This works **under the Traycer backend only**. Without Traycer, a Codex or OpenCode lead records `incomplete` and stops; `claude-native` stays Claude-only. The decision is recorded as [ADR-013](architecture.md#adr-013--non-claude-leads-run-the-same-payload-under-the-traycer-backend).

**1. Install with the installer, not the plugin.** The marketplace plugin relies on Claude Code to expand `${CLAUDE_SKILL_DIR}` in the Skill's prompts, and no other harness does. `install.sh` and `install.ps1` write the absolute installed path into the installed copy instead, so the same files work for every harness. Use [Manual installation](install.md#manual-installation) (`./install.sh`, or `.\install.ps1` on Windows).

**2. Let each harness find the Skill.** One installed copy at `~/.claude/skills/dev` serves all three harnesses:

| Harness | How it finds the Skill | How you invoke it |
| --- | --- | --- |
| Claude Code | `~/.claude/skills/dev` | `/dev` |
| Codex | the link `~/.agents/skills/dev`, which a default install creates or refreshes (`--no-agents-link` / `-NoAgentsLink` skips it; an install with `--target` / `-Target` never creates it) | `$dev` |
| OpenCode | reads `~/.claude/skills` directly | through its skill tool |

**3. The lead supplies its Traycer identity.** Traycer gives `TRAYCER_AGENT_ID` and `TRAYCER_EPIC_ID` to Claude Code agents and to Codex and OpenCode terminal agents; Codex and OpenCode leads on Traycer's chat surface do not receive them (observed 2026-09-21, confirmed 2026-10-03). When detection returns `incomplete` with **neither** identifier present, the lead takes its agent id from the session's own self-identity source and its epic id from the Traycer session context, falls back to ids in your invocation message, and asks you once if one is still missing. It writes them to `.agent/traycer.env` (two `export` lines, identifiers only, never secrets), confirms the file is git-ignored or excluded, and re-runs detection, which now records `backend_source: supplied`. Exactly one identifier in the environment is a host defect: the lead reports it and stops.

**4. Preflight checks the supplied identity.** The Traycer CLI derives its caller and "self" marker from the supplied identifiers, so neither is evidence. Instead the lead compares the agent id with its session's self-identity source when one exists, and checks that the agent-list row for that id names the lead's own worktree and harness. The second check is weaker: it cannot tell apart two agents sharing one worktree and one harness (for example a QA lane sharing the lead's checkout). The ledger records which check verified the identity (`identity_verification`), and a lead verified by the weaker check alone says so in its first status reply.

**5. Swapping leads mid-run is a recovery.** The new lead reads `.agent/dev-state.md` and runs the Traycer adapter's recovery procedure before sending anything: it reconciles the lanes the previous lead dispatched and must observe them rather than create duplicates. Verified 2026-10-03 (#91): Codex and OpenCode leads each recovered a Claude lead's run, reconciled the outstanding lane, and created no duplicate agent. A report-back the lane already delivered to the previous lead is accepted by the new lead only under the Traycer adapter's swap-time evidence rule (#97): both inbox reads ended `completed` with no reply, and the previous lead's transcript holds a message from the recorded lane agent, after the recorded dispatch, naming the recorded response ID in full; anything less stays `absent`.

### Surface status

| Surface | Detection result | Status |
| --- | --- | --- |
| Claude Code, Traycer chat | `traycer`, `backend_source: detected` | Supported (the original path) |
| Codex, Traycer chat | Identifiers absent from the environment; the lead supplies its identity (agent id from its session's self-identity source, epic id from the Traycer session context). Detection `traycer`, `backend_source: supplied`; both identity checks passed (2026-10-03) | Supported (#91); post-swap report-back acceptance follows the adapter's swap-time evidence rule (#97) |
| OpenCode, Traycer chat | Identifiers absent from the environment; the lead supplies its identity (agent id from its session's self-identity source, epic id from the Traycer session context). Detection `traycer`, `backend_source: supplied`; both identity checks passed (2026-10-03) | Supported (#91); the same swap-time evidence rule (#97) |
| Codex, Traycer terminal | `traycer`, `backend_source: detected`; Traycer injects both identifiers into terminal agents (2026-10-03). The Traycer CLI needed network approval in Codex's sandbox | Detection verified. These agents must be opened by you: Traycer cannot create them from another agent or deliver agent messages to them. Dispatching lanes from a terminal Codex lead is not yet verified |
| OpenCode, Traycer terminal | `traycer`, `backend_source: detected`; Traycer injects both identifiers into terminal agents (2026-10-03) | Detection verified. These agents must be opened by you: Traycer cannot create them from another agent or deliver agent messages to them. Dispatching lanes from a terminal OpenCode lead is not yet verified |

A surface that fails closed is documented here, not worked around.
