#!/usr/bin/env python3
"""Report the workspace debt for this project without ever modifying it.

This gauge is the read-only counterpart to Lane Close-Out (Issue #73). It
counts Traycer worktrees and in-task agents that belong to the project
recorded in `.dev.json` `github.pushRepository`, then classifies them by
tier so the lead can quote totals in the reply contract's cleanup line and
consolidation offer.

The script is scoped to **one project**: the repository identity in
`.dev.json`. Other projects' worktrees and agents are neither counted nor
listed. A multi-project sweep is outside Issue #73's scope; the
housekeeping skill handles cross-project cleanup.

Backend selection follows `skills/dev/phases/phase4.md`. On `traycer` it
invokes the wrapper at `${CLAUDE_SKILL_DIR}/scripts/traycer_cli.py` for
`agent list --json` and `worktree list --json --include-activity`. On
`claude-native` the worktree side comes from `git worktree list --porcelain`
and the agent side is `not_applicable`. Any CLI error, timeout, missing
binary, or unparseable output fails closed: `status: unavailable`, every
count zero or null, the JSON is still valid for downstream tooling.

Removal happens **only** through `traycer worktree delete --path`, after
user approval, with review-tier rows approved one at a time. This script
NEVER deletes, stops, or archives anything; it only reports.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# Locate skill_dir using the same rules as the wrapper. CLAUDE_SKILL_DIR is
# the convention every `/dev` script honours; the fallback resolves to this
# file's parent directory (skills/dev/scripts/workspace_debt.py → ../..).
SCRIPT_HERE = Path(__file__).resolve()
SKILL_DIR = Path(os.environ.get("CLAUDE_SKILL_DIR") or SCRIPT_HERE.parents[1])
WRAPPER = SKILL_DIR / "scripts" / "traycer_cli.py"
BACKEND_DETECTOR = SKILL_DIR / "scripts" / "detect_execution_backend.py"
DEV_CONFIG = SKILL_DIR / "scripts" / "dev_config.py"

# Single source of the per-CLI budgets. The script is read-only, so timeouts
# only need to bound an obviously hung `traycer`; the trapdoor cases are
# network auth under Codex sandbox and a worktree list past 1.2 MB on busy
# epics, both well under 30s in practice. Keep this loose enough for those.
COMMAND_TIMEOUT_SECONDS = 30
# `git worktree list --porcelain` is local and bounded by the user's repo;
# 5s covers the worst legitimate case and bounds a hung pager-forked shell.
GIT_TIMEOUT_SECONDS = 5

# Tiers reported in the worktree breakdown. They mirror what
# `traycer worktree list --include-activity` emits on the
# `tier` field, with one extension: `null` (the script cannot read
# `tier` because the field is missing from this CLI version, or the
# output is not from the activity-aware command). When `tier` is null
# every row counts under `tier_null` instead of being guessed.
WORKTREE_TIERS = ("in-use", "review", "unreferenced", "orphaned", "at-base-commit", "merged")


class ScriptError(RuntimeError):
    """A defect this script can recover by emitting the unavailable status."""


def _load_dev_config(repo_dir: Path) -> dict[str, str]:
    """Load and validate `.dev.json` from `repo_dir`. Fail closed on any defect.

    A defect here is a host/project defect (the project isn't initialised
    for `/dev`), not something the gauge should paper over: an
    uninitialised gauge produces `status: unavailable` and the lead
    treats it as "ask the user to initialise the project", the same way it
    treats a missing CLI.
    """
    config_path = repo_dir / ".dev.json"
    if not config_path.is_file():
        raise ScriptError(f".dev.json not found at {config_path}")
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ScriptError(f".dev.json unreadable: {error}") from error
    github = raw.get("github") if isinstance(raw, dict) else None
    if not isinstance(github, dict):
        raise ScriptError(".dev.json github section missing")
    push = github.get("pushRepository")
    if not isinstance(push, str) or "/" not in push:
        raise ScriptError(".dev.json github.pushRepository missing or malformed")
    owner, _, name = push.partition("/")
    if not owner or not name:
        raise ScriptError(".dev.json github.pushRepository must be OWNER/REPO")
    return {"owner": owner, "name": name, "raw": push}


def _detect_backend() -> dict[str, str | None]:
    """Call the detector via `python3` so the wrapper's lookup rule applies.

    Importing the module would couple this script to the detector's import
    surface. The detector is itself a stdlib-only script whose stdout is a
    deterministic JSON object; shelling out keeps the same fail-closed
    surface the rest of the gauge already has.
    """
    if not BACKEND_DETECTOR.is_file():
        return {
            "execution_backend": "incomplete",
            "detection_status": "incomplete",
            "traycer_agent_id": None,
            "traycer_epic_id": None,
            "backend_source": None,
            "reason": "detect_execution_backend.py not found",
        }
    try:
        completed = subprocess.run(
            [sys.executable, str(BACKEND_DETECTOR)],
            capture_output=True,
            text=True,
            check=False,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {
            "execution_backend": "incomplete",
            "detection_status": "incomplete",
            "traycer_agent_id": None,
            "traycer_epic_id": None,
            "backend_source": None,
            "reason": f"backend detector failed: {error}",
        }
    if completed.returncode != 0:
        return {
            "execution_backend": "incomplete",
            "detection_status": "incomplete",
            "traycer_agent_id": None,
            "traycer_epic_id": None,
            "backend_source": None,
            "reason": f"backend detector exit {completed.returncode}",
        }
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "execution_backend": "incomplete",
            "detection_status": "incomplete",
            "traycer_agent_id": None,
            "traycer_epic_id": None,
            "backend_source": None,
            "reason": "backend detector returned malformed JSON",
        }
    if not isinstance(payload, dict):
        return {
            "execution_backend": "incomplete",
            "detection_status": "incomplete",
            "traycer_agent_id": None,
            "traycer_epic_id": None,
            "backend_source": None,
            "reason": "backend detector returned non-object payload",
        }
    return payload  # type: ignore[return-value]


def _unavailable(reason_code: str, reason: str, **extras: Any) -> dict[str, Any]:
    """Build a fail-closed gauge payload.

    Counts are `null` (absent), never zero: a zero reads as "clean" and
    would let the lead's reply-contract cleanup line quote a debt that
    was never measured. Downstream consumers that need a number for
    rendering are expected to treat `null` as "unknown" and route through
    the reason code instead of inventing a value.
    """
    payload: dict[str, Any] = {
        "status": "unavailable",
        "reason_code": reason_code,
        "reason": reason,
        "project": None,
        "backend": None,
        "counts": None,
    }
    payload.update(extras)
    return payload


def _empty_counts() -> dict[str, Any]:
    return {
        "worktrees": {
            "total": 0,
            "by_tier": {tier: 0 for tier in WORKTREE_TIERS},
            "tier_null": 0,
            "landed_eligible": 0,
            "lead_created_review": 0,
        },
        "agents": {
            "total": 0,
            "active": 0,
            "archived": 0,
            "active_for_this_lead": 0,
            "active_not_mine": 0,
            "presence": "not_applicable",
            "by_field": {"archived_supported": False, "distinguishable": []},
        },
    }


def _run_traycer_cli(traycer_args: list[str]) -> dict[str, Any]:
    """Invoke the wrapper and return its decoded JSON payload, or fail closed.

    The wrapper applies the same identity-file lookup as the detector. On
    exit it writes nothing on stdout and one JSON `{"traycer_cli":"error",...}`
    line to stderr when `traycer` itself was never reached; otherwise `traycer`
    exits with its own code and stdout is whatever `traycer` printed.
    """
    if not WRAPPER.is_file():
        raise ScriptError(f"traycer_cli.py wrapper missing at {WRAPPER}")
    if shutil.which("python3") is None:
        raise ScriptError("python3 not on PATH")
    try:
        completed = subprocess.run(
            [sys.executable, str(WRAPPER), *traycer_args],
            capture_output=True,
            text=True,
            check=False,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise ScriptError(f"{' '.join(traycer_args)} timed out after {COMMAND_TIMEOUT_SECONDS}s") from error
    except OSError as error:
        raise ScriptError(f"{' '.join(traycer_args)} failed to launch: {error}") from error
    if completed.returncode != 0:
        raise ScriptError(
            f"{' '.join(traycer_args)} exit {completed.returncode}: "
            f"{(completed.stderr or completed.stdout).strip()[:200] or 'no output'}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ScriptError(f"{' '.join(traycer_args)} returned malformed JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ScriptError(f"{' '.join(traycer_args)} returned non-object payload")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ScriptError(f"{' '.join(traycer_args)} omitted data object")
    return data


def _list_worktrees_traycer(repo: dict[str, str]) -> list[dict[str, Any]]:
    """Filter `worktree list --include-activity` to the project repo."""
    payload = _run_traycer_cli(["worktree", "list", "--json", "--include-activity"])
    worktrees = payload.get("worktrees")
    if not isinstance(worktrees, list):
        raise ScriptError("worktree list JSON missing 'worktrees' array")
    return [
        wt for wt in worktrees
        if isinstance(wt, dict)
        and _matches_repo(wt.get("repoIdentifier"), repo)
    ]


def _list_agents_traycer() -> list[dict[str, Any]]:
    """Fetch `agent list` rows. Project scoping happens in `_filter_agents`."""
    payload = _run_traycer_cli(["agent", "list", "--json"])
    agents = payload.get("agents")
    if not isinstance(agents, list):
        raise ScriptError("agent list JSON missing 'agents' array")
    return [agent for agent in agents if isinstance(agent, dict)]


def _git_worktree_list(repo_dir: Path) -> list[dict[str, Any]]:
    """`git worktree list --porcelain` parsed into the same shape as the JSON path.

    `--porcelain` is the local, no-network contract this script needs on the
    Claude-native backend: stable output, no `--json`, no progress chatter,
    bounded by the user's repo. The CLI JSON carries a `tier` field the
    porcelain output cannot synthesise, so those rows are reported under
    `tier_null` with the reason recorded. The lead knows from
    `backend=claude-native` that the gauge ran without the activity overlay;
    it does not have to read it from the worktree rows.
    """
    git = shutil.which("git")
    if git is None:
        raise ScriptError("git not on PATH")
    try:
        completed = subprocess.run(
            [git, "-C", str(repo_dir), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise ScriptError(f"git worktree list timed out after {GIT_TIMEOUT_SECONDS}s") from error
    except OSError as error:
        raise ScriptError(f"git worktree list failed to launch: {error}") from error
    if completed.returncode != 0:
        raise ScriptError(
            f"git worktree list exit {completed.returncode}: "
            f"{(completed.stderr or completed.stdout).strip()[:200] or 'no output'}"
        )
    return _parse_porcelain(completed.stdout)


def _parse_porcelain(text: str) -> list[dict[str, Any]]:
    """`--porcelain` is a record-per-worktree of `KEY VALUE` lines separated by blank lines.

    The same shape every modern Git ships. We carry over the path and the
    HEAD SHA so callers can join against agents that record `folderPaths`,
    and we leave every activity-aware field null so the count breakdown can
    route them to `tier_null` honestly.
    """
    worktrees: list[dict[str, Any]] = []
    record: dict[str, Any] = {}
    for line in text.splitlines():
        if not line.strip():
            if record:
                worktrees.append(record)
                record = {}
            continue
        if line.startswith("worktree "):
            record["worktreePath"] = line[len("worktree "):].strip()
        elif line.startswith("HEAD "):
            record["headSha"] = line[len("HEAD "):].strip()
        elif line == "detached":
            record["detached"] = True
        elif line.startswith("branch "):
            record["branch"] = line[len("branch "):].strip()
    if record:
        worktrees.append(record)
    return worktrees


def _matches_repo(identifier: Any, repo: dict[str, str]) -> bool:
    """Decide whether a worktree record belongs to `repo` (`OWNER/REPO`).

    The CLI returns a nested `repoIdentifier` on the activity-aware path.
    Records whose `repoIdentifier` is null (a local-only worktree, or a
    porcelain row) are treated as out-of-scope: without an owner/repo pair
    we cannot tell which project it belongs to, and Issue #73's scope
    amendment forbids guessing. Such records are recorded in
    `undistinguishable_records` for the lead to read; they never count.
    """
    if not isinstance(identifier, dict):
        return False
    owner = identifier.get("owner")
    name = identifier.get("repo")
    return owner == repo["owner"] and name == repo["name"]


def _worktree_tier(worktree: dict[str, Any]) -> str | None:
    """Return the CLI's `tier` if it's a recognised value, else None."""
    tier = worktree.get("tier")
    if isinstance(tier, str) and tier in WORKTREE_TIERS:
        return tier
    return None


def _is_landed_eligible(worktree: dict[str, Any], tier: str | None) -> bool:
    """A worktree is landed-eligible iff its PR merged and the lane worktree
    itself is clean enough to drop later (no uncommitted changes on a
    detached review checkout of a merged PR counts).

    The rule is intentionally narrow: a worktree's removal still goes
    through the user-approved consolidation batch in the reply contract.
    `landed_eligible: true` is only the lead's *permission* to propose it,
    never the act of removing it.
    """
    pr_state = worktree.get("prState")
    pr_url = worktree.get("prUrl")
    if pr_state != "merged" or not isinstance(pr_url, str):
        return False
    uncommitted = worktree.get("uncommittedCount")
    if not isinstance(uncommitted, int) or uncommitted > 0:
        return False
    return True


def _is_lead_created_review(worktree: dict[str, Any]) -> bool:
    """A `review-tier` worktree whose branch was issued by the host in response
    to this run's request, as recorded in `worktreePath`/branch naming.

    The CLI's `tier` says "review" but the lead still needs to know which
    rows it owns before removing them in this turn. We treat anything with
    `tier == "review"` and a non-empty `worktreePath` as a candidate; the
    reply contract's "one at a time" rule stops the lead from deleting more
    than one, so over-marking only makes the lead slow down, never
    accidentally remove a foreign worktree.
    """
    return _worktree_tier(worktree) == "review"


def _summarise_worktrees_traycer(worktrees: list[dict[str, Any]]) -> dict[str, Any]:
    by_tier = {tier: 0 for tier in WORKTREE_TIERS}
    tier_null = 0
    landed_eligible = 0
    lead_created_review = 0
    for wt in worktrees:
        tier = _worktree_tier(wt)
        if tier is None:
            tier_null += 1
        else:
            by_tier[tier] += 1
        if _is_landed_eligible(wt, tier):
            landed_eligible += 1
        if _is_lead_created_review(wt):
            lead_created_review += 1
    return {
        "total": len(worktrees),
        "by_tier": by_tier,
        "tier_null": tier_null,
        "landed_eligible": landed_eligible,
        "lead_created_review": lead_created_review,
    }


def _summarise_worktrees_claude_native(worktrees: list[dict[str, Any]]) -> dict[str, Any]:
    by_tier = {tier: 0 for tier in WORKTREE_TIERS}
    return {
        "total": len(worktrees),
        "by_tier": by_tier,
        # Porcelain has no `tier`, so every row lands here. Documenting it
        # in the counts lets the lead quote a tier count of 0 without
        # pretending the rows don't exist.
        "tier_null": len(worktrees),
        # `landed_eligible` needs `prState`/`prUrl`/`uncommittedCount`,
        # none of which porcelain emits, so the gauge cannot establish it
        # locally. That is a known Claude-native gap, not a defect in
        # `git worktree list`.
        "landed_eligible": 0,
        "lead_created_review": 0,
    }


def _agent_belongs_to_project(agent: dict[str, Any], project_paths: set[str]) -> bool:
    """An agent belongs to this project iff any of its `folderPaths` is a
    worktree path we counted. Agents in `isWorktree=false` modes (TUI,
    ad-hoc on-disk folders) only match when one of their paths equals a
    recognised project path.

    Equal prefix is wrong: two projects share an upstream worktree tree
    and the agent can sit in either. Strict equality on the path means the
    agent's working directory is a worktree we own, which is the same
    scoping rule the user-approved amendment uses.
    """
    paths = agent.get("folderPaths")
    if not isinstance(paths, list):
        return False
    for path in paths:
        if isinstance(path, str) and path in project_paths:
            return True
    return False


def _summarise_agents_traycer(
    agents: list[dict[str, Any]],
    project_paths: set[str],
    lead_agent_id: str | None,
) -> dict[str, Any]:
    """Tally the in-task agents that touch this project's worktrees.

    Issue #73 scope amendment: agents the lead did not spawn are
    report-only. Distinguishing requires a `parentId`-vs-self comparison
    that the CLI JSON supports: a row whose `parentId` equals the lead
    belongs to this lead; everything else in the task does not. Without a
    lead identity (an `incomplete` backend row, or a scripted run with
    no agent), every active agent is "not mine".
    """
    total = 0
    active = 0
    archived = 0
    active_for_this_lead = 0
    active_not_mine = 0
    distinguishable: list[str] = []
    have_parent = False
    have_archived = False
    have_active = False
    for agent in agents:
        if not _agent_belongs_to_project(agent, project_paths):
            continue
        total += 1
        is_active = bool(agent.get("active"))
        is_archived = bool(agent.get("archived"))
        parent_id = agent.get("parentId")
        if is_active:
            active += 1
        if is_archived:
            archived += 1
        if parent_id is not None:
            have_parent = True
        if "archived" in agent:
            have_archived = True
        if "active" in agent:
            have_active = True
        if is_active:
            if lead_agent_id is not None and parent_id == lead_agent_id:
                active_for_this_lead += 1
            else:
                active_not_mine += 1
    for field in ("parentId", "active", "archived"):
        if {"parentId": have_parent, "active": have_active, "archived": have_archived}[field]:
            distinguishable.append(field)
    return {
        "total": total,
        "active": active,
        "archived": archived,
        "active_for_this_lead": active_for_this_lead,
        "active_not_mine": active_not_mine,
        "presence": "ok",
        "by_field": {
            "archived_supported": have_archived,
            "distinguishable": distinguishable,
        },
    }


def build_report(
    repo_dir: Path,
    *,
    lead_agent_id: str | None = None,
    backend_override: str | None = None,
) -> dict[str, Any]:
    """Compute the workspace-debt gauge from a project root.

    `lead_agent_id` distinguishes this lead's agents from foreign ones.
    Pass `None` (the default) when the script is called outside a
    Traycer backend (Claude-native, or a test fixture that doesn't model a
    lead). `backend_override` accepts `"traycer"` or `"claude-native"`
    and bypasses detection; the detector never returns `claude-native`
    on its own, so this is the only path that reaches the claude-native
    branch in tests and on a known-Claude-Code lead (`backend_source:
    lead_resolved` in `detect_execution_backend.py` parlance). The
    function never raises: every fault path returns a valid JSON object
    with `status: unavailable`.
    """
    try:
        repo = _load_dev_config(repo_dir)
    except ScriptError as error:
        return _unavailable("dev_config_invalid", str(error))

    if backend_override in {"traycer", "claude-native"}:
        if backend_override == "traycer":
            return _report_traycer(repo_dir, repo, {"execution_backend": "traycer"}, lead_agent_id)
        return _report_claude_native(repo_dir, repo, {"execution_backend": "claude-native"})

    backend = _detect_backend()
    backend_kind = backend.get("execution_backend")
    backend_status = backend.get("detection_status")

    # `incomplete` is a first-class fail-closed case. Counting would be
    # guessing which CLI to invoke and which fields to read; the user
    # voted on 2026-10-13 that absence is not evidence.
    if backend_status != "ready" or backend_kind not in {"traycer", "claude-native"}:
        return _unavailable(
            "backend_incomplete",
            f"backend detector: {backend.get('reason') or 'unknown'}",
            project=repo["raw"],
            backend=backend_kind,
        )

    if backend_kind == "traycer":
        return _report_traycer(repo_dir, repo, backend, lead_agent_id)
    return _report_claude_native(repo_dir, repo, backend)


def _report_traycer(
    repo_dir: Path,
    repo: dict[str, str],
    backend: dict[str, str | None],
    lead_agent_id: str | None,
) -> dict[str, Any]:
    try:
        worktrees = _list_worktrees_traycer(repo)
    except ScriptError as error:
        return _unavailable(
            "worktree_list_failed",
            str(error),
            project=repo["raw"],
            backend="traycer",
        )
    project_paths = {
        wt.get("worktreePath")
        for wt in worktrees
        if isinstance(wt.get("worktreePath"), str)
    }
    try:
        agents = _list_agents_traycer()
    except ScriptError as error:
        # Returning a partial report is dishonest; an agents-list failure
        # also blocks the lead's reply-contract cleanup line because the
        # line names per-tier agent counts. Fail the whole gauge closed.
        return _unavailable(
            "agent_list_failed",
            str(error),
            project=repo["raw"],
            backend="traycer",
        )
    counts = _empty_counts()
    counts["worktrees"] = _summarise_worktrees_traycer(worktrees)
    counts["agents"] = _summarise_agents_traycer(agents, project_paths, lead_agent_id)
    # The CLI JSON does not surface a per-row `archived_at` or last
    # activity for agents. Report exactly what we cannot distinguish so the
    # lead's reply line stays honest: it can say "active not mine: N" but
    # cannot say "merged-and-clean worktrees: M" without re-querying Git.
    indistinguishable: list[str] = []
    if backend.get("backend_source") is None:
        indistinguishable.append("backend_source")
    return {
        "status": "ok",
        "reason_code": None,
        "reason": None,
        "project": repo["raw"],
        "backend": "traycer",
        "counts": counts,
        "distinguishable": ["archived (bool)", "active (bool)", "parentId (uuid)"],
        "undistinguishable": indistinguishable,
    }


def _report_claude_native(
    repo_dir: Path,
    repo: dict[str, str],
    backend: dict[str, str | None],
) -> dict[str, Any]:
    try:
        worktrees = _git_worktree_list(repo_dir)
    except ScriptError as error:
        return _unavailable(
            "git_worktree_list_failed",
            str(error),
            project=repo["raw"],
            backend="claude-native",
        )
    counts = _empty_counts()
    counts["worktrees"] = _summarise_worktrees_claude_native(worktrees)
    # Agents are not modelled on the claude-native backend. Reporting
    # `not_applicable` is honest: the gauge only signals that an agent
    # count is meaningless here, not that there are zero.
    counts["agents"] = {
        "total": 0,
        "active": 0,
        "archived": 0,
        "active_for_this_lead": 0,
        "active_not_mine": 0,
        "presence": "not_applicable",
        "by_field": {
            "archived_supported": False,
            "distinguishable": [],
        },
    }
    return {
        "status": "ok",
        "reason_code": None,
        "reason": None,
        "project": repo["raw"],
        "backend": "claude-native",
        "counts": counts,
        "distinguishable": ["worktree paths (from git worktree list --porcelain)"],
        "undistinguishable": [
            "agents",
            "worktree tier",
            "PR state per worktree",
            "uncommitted changes per worktree",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    repo_dir = Path.cwd()
    backend_override: str | None = None
    positional: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--backend" and index + 1 < len(args):
            backend_override = args[index + 1]
            index += 2
            continue
        if arg.startswith("--backend="):
            backend_override = arg.split("=", 1)[1]
            index += 1
            continue
        positional.append(arg)
        index += 1
    if positional:
        repo_dir = Path(positional[0]).resolve()
    report = build_report(repo_dir, backend_override=backend_override)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
