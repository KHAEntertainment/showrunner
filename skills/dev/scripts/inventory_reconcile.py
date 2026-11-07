#!/usr/bin/env python3
"""Reconcile the lead's ledger inventory against what is actually running.

Issue #112, the follow-up to #73. This script is REPORT-ONLY: it never
archives, stops, deletes or messages anything. The lead reads its report at
a turn boundary and acts on it by the procedure in
``reply-contract.md`` § 7.3. Only an ``archive_due`` finding proposes an
action, and that action is an archive: reversible, never done, never
deletable.

It compares the ``inventory`` rows of ``.agent/dev-state.md`` with three
listings:

- the Traycer agent listing (``traycer_cli.py agent list --json``),
- ``git worktree list --porcelain`` for the repository,
- the lead's own shells (no CLI lists them; the lead passes its shell
  listing in with ``--shells-json``).

Every inventory row gets exactly one finding:

- ``archive_due``: an agent idle for MORE than 60 minutes (strictly
  greater; exactly 60:00 is not due) with no open request.
- ``blocked_by_open_request``: idle past the timeout, but the lead has an
  open request with it. Each request is named.
- ``blocked``: not archivable for another reason (``listing_active``,
  ``state:<state>``, ``obligation:children``, ``successor_custody``,
  ``open_requests_unknown``, ``idle_unknown``).
- ``not_due``: idle for 60 minutes or less.
- ``target_gone``: the row's agent, worktree, checkout or shell is missing
  from its listing.
- ``already_archived``: the listing shows the agent archived but the row
  does not say so yet.
- ``tracked``: a live worktree, checkout or shell that is present.
- ``skipped``: the row is in a terminal state (``archived-*``, ``cleaned``,
  ``removed``, ``stopped``, ``exited``).
- ``not_mine``: a ``foreign-*`` row. Listed agents in this project that
  are NOT in the inventory are reported as ``not_mine`` too. Neither is
  ever a candidate for action.
- ``not_applicable``: an agent row on the claude-native backend, which has
  no agent listing.

The idle signal is the ledger's ``last_exchange_at``: the Traycer agent
listing carries no last-activity timestamp (probed 2026-11-06), so the
lead records the time of every message it sends to an agent and every
reply it receives. A listing row with ``active: true`` overrides the clock.

It fails closed. A CLI error, timeout, non-zero exit or unparseable output,
a partial listing (a pagination marker, or a row missing a field the
decision needs), an unreadable or malformed ledger, or a second writer on
the run ledger gives ``status: unavailable`` with ``counts: null`` and no
findings. An empty result never stands in for "unknown".

Exit 0 when ``status`` is ``ok``, 2 when it is ``unavailable``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# Reuse, not copies. tests/test_inventory_reconcile.py fails loudly if any of
# these names disappears from its module.
from dev_state import LEDGER_ABSENT, GoalRunError, read_ledger_block  # noqa: E402
from workspace_debt import (  # noqa: E402
    ScriptError,
    _agent_belongs_to_project,
    _detect_backend,
    _git_worktree_list,
    _parse_porcelain,
    _run_traycer_cli,
)

IDLE_TIMEOUT = timedelta(minutes=60)
ARCHIVE_NEXT_STATE = "archived-idle-timeout"

AGENT_ARCHIVED_STATES = frozenset({"archived-on-accept", "archived-on-closeout", ARCHIVE_NEXT_STATE})
AGENT_FOREIGN_STATES = frozenset({"foreign-idle", "foreign-archived"})
AGENT_ARCHIVABLE_STATES = frozenset({"active", "report-back-complete"})
AGENT_BLOCKING_STATES = frozenset({"planned", "report-back-pending", "report-back-incomplete"})

STATES: dict[str, frozenset[str]] = {
    "agent": AGENT_ARCHIVED_STATES | AGENT_FOREIGN_STATES | AGENT_ARCHIVABLE_STATES | AGENT_BLOCKING_STATES,
    "worktree": frozenset({
        "in-progress", "review-only", "landed-eligible",
        "landed-eligible-and-approved", "cleaned", "foreign",
    }),
    "review_checkout": frozenset({"in-use", "clean", "removed"}),
    "shell": frozenset({"running", "stopped", "exited"}),
}
TERMINAL_STATES: dict[str, frozenset[str]] = {
    "agent": AGENT_ARCHIVED_STATES,
    "worktree": frozenset({"cleaned"}),
    "review_checkout": frozenset({"removed"}),
    "shell": frozenset({"stopped", "exited"}),
}

# Fields the decision needs on every agent listing row. A row without one of
# them makes the listing partial.
AGENT_LISTING_FIELDS = ("id", "active", "archived", "folderPaths")

# Keys a paged or truncated listing carries. Any of them set means the rows we
# hold are not the whole listing.
PAGINATION_KEYS = (
    "nextOffset", "next_offset", "hasMore", "has_more", "nextPageToken",
    "next_page_token", "nextCursor", "next_cursor", "truncated", "partial",
)

FINDINGS = (
    "archive_due", "blocked_by_open_request", "blocked", "not_due",
    "target_gone", "already_archived", "tracked", "skipped", "not_mine",
    "not_applicable",
)


class Unavailable(Exception):
    """A fault that makes the whole report ``unavailable``."""

    def __init__(self, reason_code: str, reason: str) -> None:
        super().__init__(reason)
        self.reason_code = reason_code
        self.reason = reason


def _unavailable(reason_code: str, reason: str, backend: str | None) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason_code": reason_code,
        "reason": reason,
        "backend": backend,
        "report_only": True,
        "counts": None,
        "findings": [],
    }


def _parse_time(value: Any) -> datetime | None:
    """A timezone-qualified ISO-8601 time, or None when it is not one."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _read_block(text: str, key: str) -> Any:
    try:
        return read_ledger_block(text, key)
    except GoalRunError as error:
        raise Unavailable("ledger_unreadable", f"{key}: {error}") from error


# --- ledger ---------------------------------------------------------------


def _validate_open_requests(row_id: str, value: Any) -> list[dict[str, Any]] | None:
    """None when the field is absent (unknown). A malformed value is a ledger defect."""
    if value is LEDGER_ABSENT or value is None:
        return None
    if not isinstance(value, list):
        raise Unavailable("inventory_malformed", f"inventory {row_id}: open_requests must be a list")
    requests = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip():
            raise Unavailable(
                "inventory_malformed",
                f"inventory {row_id}: each open_requests entry needs a non-empty id",
            )
        requests.append({"id": item["id"], "what": item.get("what")})
    return requests


def load_inventory(text: str) -> list[dict[str, Any]]:
    inventory = _read_block(text, "inventory")
    if inventory is LEDGER_ABSENT:
        raise Unavailable("inventory_missing", "the ledger has no inventory block")
    if not isinstance(inventory, list):
        raise Unavailable("inventory_malformed", "inventory must be a list")
    seen: set[str] = set()
    rows = []
    for index, row in enumerate(inventory):
        if not isinstance(row, dict):
            raise Unavailable("inventory_malformed", f"inventory[{index}] is not a map")
        row_id = row.get("id")
        if not isinstance(row_id, str) or not row_id.strip():
            raise Unavailable("inventory_malformed", f"inventory[{index}] has no id")
        if row_id in seen:
            raise Unavailable("inventory_malformed", f"inventory id {row_id} appears twice")
        seen.add(row_id)
        kind = row.get("kind")
        if kind not in STATES:
            raise Unavailable("inventory_malformed", f"inventory {row_id}: unknown kind {kind!r}")
        state = row.get("state")
        if state not in STATES[kind]:
            raise Unavailable("inventory_malformed", f"inventory {row_id}: state {state!r} is not a {kind} state")
        clean = dict(row)
        if kind == "agent":
            clean["open_requests"] = _validate_open_requests(row_id, row.get("open_requests", LEDGER_ABSENT))
        rows.append(clean)
    return rows


def check_single_writer(text: str, lead_agent_id: str | None) -> None:
    """SC-7 ``rejected-two-active-writers``: one run ledger has one writer.

    The lead is the sole writer of its ledger. Its id is recorded twice:
    ``lead.agent_id`` and ``execution.traycer_agent_id`` (the id the lead-swap
    rule in ``backends/traycer.md`` compares). Every recorded id must equal
    the caller; a caller that differs from either is a second active writer
    on the same run ledger, and the report refuses. After a lead swap the new
    lead updates both before it runs the reconcile. Inventory rows (workers,
    QA, reviewers, a re-dispatched worker) are never writers and never trip
    this.
    """
    if not isinstance(lead_agent_id, str) or not lead_agent_id.strip():
        raise Unavailable("lead_agent_id_missing", "the caller's lead agent id is required on traycer")
    recorded: dict[str, str] = {}
    for block, field in (("lead", "agent_id"), ("execution", "traycer_agent_id")):
        value = _read_block(text, block)
        writer = value.get(field) if isinstance(value, dict) else None
        if isinstance(writer, str) and writer.strip():
            recorded[f"{block}.{field}"] = writer
    if not recorded:
        raise Unavailable(
            "lead_unrecorded",
            "the ledger records neither lead.agent_id nor execution.traycer_agent_id, so its writer is unknown",
        )
    for where, writer in recorded.items():
        if writer != lead_agent_id:
            raise Unavailable(
                "two_active_writers",
                f"the ledger's {where} is {writer}, not the caller {lead_agent_id}; "
                "two active writers on one run ledger are refused",
            )


def load_custody_blockers(text: str) -> dict[str, str]:
    """Agent ids that the goal-run recovery records name: they are never idle-archivable."""
    goal_run = _read_block(text, "goal_run")
    if not isinstance(goal_run, dict):
        return {}
    blockers: dict[str, str] = {}
    obligations = goal_run.get("obligations")
    if isinstance(obligations, dict) and isinstance(obligations.get("children"), list):
        for child in obligations["children"]:
            if isinstance(child, str) and child:
                blockers[child] = "obligation:children"
    custody = goal_run.get("custody")
    if isinstance(custody, dict):
        for key in ("prior_session_id", "current_session_id"):
            value = custody.get(key)
            if isinstance(value, str) and value:
                blockers.setdefault(value, "successor_custody")
    return blockers


# --- listings -------------------------------------------------------------


def _check_not_paged(payload: dict[str, Any], what: str, rows: list[Any]) -> None:
    for key in PAGINATION_KEYS:
        if payload.get(key) not in (None, False, "", 0):
            raise Unavailable("listing_partial", f"{what} is paged or truncated ({key} is set)")
    total = payload.get("total")
    if isinstance(total, int) and not isinstance(total, bool) and total != len(rows):
        raise Unavailable("listing_partial", f"{what} reports total {total} but holds {len(rows)} rows")


def parse_agent_listing(data: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(data, dict):
        raise Unavailable("listing_unparseable", "agent listing is not an object")
    if isinstance(data.get("data"), dict) and "agents" not in data:
        if data.get("status") not in (None, "ok"):
            raise Unavailable("listing_error", f"agent listing status {data.get('status')!r}")
        data = data["data"]
    agents = data.get("agents")
    if not isinstance(agents, list):
        raise Unavailable("listing_unparseable", "agent listing has no agents array")
    _check_not_paged(data, "agent listing", agents)
    by_id: dict[str, dict[str, Any]] = {}
    for index, agent in enumerate(agents):
        if not isinstance(agent, dict):
            raise Unavailable("listing_partial", f"agent listing row {index} is not an object")
        missing = [field for field in AGENT_LISTING_FIELDS if field not in agent]
        if missing:
            raise Unavailable("listing_partial", f"agent listing row {index} lacks {', '.join(missing)}")
        if not isinstance(agent["id"], str) or not agent["id"]:
            raise Unavailable("listing_partial", f"agent listing row {index} has no id")
        if not isinstance(agent["active"], bool) or not isinstance(agent["archived"], bool):
            raise Unavailable("listing_partial", f"agent {agent['id']}: active/archived must be booleans")
        if not isinstance(agent["folderPaths"], list):
            raise Unavailable("listing_partial", f"agent {agent['id']}: folderPaths must be a list")
        by_id[agent["id"]] = agent
    return by_id


def parse_worktrees(records: Any) -> set[str]:
    if not isinstance(records, list) or not records:
        # A repository always lists at least its main worktree.
        raise Unavailable("listing_unparseable", "git worktree list returned no worktrees")
    paths = set()
    for record in records:
        path = record.get("worktreePath") if isinstance(record, dict) else None
        if not isinstance(path, str) or not path:
            raise Unavailable("listing_partial", "a git worktree record has no path")
        paths.add(path)
    return paths


def parse_shell_listing(data: Any) -> dict[str, dict[str, Any]]:
    if isinstance(data, dict):
        shells = data.get("shells")
        if not isinstance(shells, list):
            raise Unavailable("listing_unparseable", "shell listing has no shells array")
        _check_not_paged(data, "shell listing", shells)
    elif isinstance(data, list):
        shells = data
    else:
        raise Unavailable("listing_unparseable", "shell listing is not a list or object")
    by_id: dict[str, dict[str, Any]] = {}
    for index, shell in enumerate(shells):
        if not isinstance(shell, dict) or not isinstance(shell.get("id"), str) or not shell["id"]:
            raise Unavailable("listing_partial", f"shell listing row {index} has no id")
        if not isinstance(shell.get("status"), str):
            raise Unavailable("listing_partial", f"shell {shell['id']} has no status")
        by_id[shell["id"]] = shell
    return by_id


def _shell_target(row: dict[str, Any]) -> str:
    """The shell id a row points at: ``shell_id`` when recorded, else the
    last segment of the locally minted ``shell:<hostid>:<name>`` id."""
    explicit = row.get("shell_id")
    if isinstance(explicit, str) and explicit:
        return explicit
    return row["id"].rsplit(":", 1)[-1]


def _checkout_path(row: dict[str, Any]) -> str:
    explicit = row.get("path")
    if isinstance(explicit, str) and explicit:
        return explicit
    return row["id"][len("review:"):] if row["id"].startswith("review:") else row["id"]


# --- decision -------------------------------------------------------------


def _base(row: dict[str, Any], finding: str, **extra: Any) -> dict[str, Any]:
    item = {
        "finding": finding,
        "id": row["id"],
        "kind": row["kind"],
        "role": row.get("role"),
        "pr": row.get("pr"),
        "state": row["state"],
    }
    item.update(extra)
    return item


def decide_agent(
    row: dict[str, Any],
    listed: dict[str, Any] | None,
    now: datetime,
    custody_blockers: dict[str, str],
) -> dict[str, Any]:
    state = row["state"]
    if state in AGENT_FOREIGN_STATES:
        return _base(row, "not_mine", source="inventory")
    if state in AGENT_ARCHIVED_STATES:
        return _base(row, "skipped")
    if state == "planned":
        return _base(row, "blocked", reason="state:planned")
    if listed is None:
        return _base(row, "target_gone")
    if listed["archived"]:
        return _base(row, "already_archived")
    if listed["active"]:
        return _base(row, "blocked", reason="listing_active")
    if state in AGENT_BLOCKING_STATES:
        return _base(row, "blocked", reason=f"state:{state}")
    if row["id"] in custody_blockers:
        return _base(row, "blocked", reason=custody_blockers[row["id"]])
    open_requests = row["open_requests"]
    if open_requests is None:
        return _base(row, "blocked", reason="open_requests_unknown")
    last = _parse_time(row.get("last_exchange_at"))
    if last is None or last > now:
        return _base(row, "blocked", reason="idle_unknown")
    idle = now - last
    idle_minutes = round(idle.total_seconds() / 60, 2)
    if idle <= IDLE_TIMEOUT:
        return _base(row, "not_due", idle_minutes=idle_minutes)
    if open_requests:
        return _base(row, "blocked_by_open_request", idle_minutes=idle_minutes, open_requests=open_requests)
    return _base(
        row,
        "archive_due",
        idle_minutes=idle_minutes,
        proposed_action="archive",
        reversible=True,
        next_state=ARCHIVE_NEXT_STATE,
    )


def decide_other(
    row: dict[str, Any],
    worktree_paths: set[str],
    shells: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    kind, state = row["kind"], row["state"]
    if state in TERMINAL_STATES[kind]:
        return _base(row, "skipped")
    if kind == "worktree":
        if state == "foreign":
            return _base(row, "not_mine", source="inventory")
        present = row["id"] in worktree_paths
    elif kind == "review_checkout":
        present = _checkout_path(row) in worktree_paths
    else:  # shell
        assert shells is not None  # guaranteed by reconcile()
        present = _shell_target(row) in shells
    return _base(row, "tracked" if present else "target_gone")


def reconcile(
    ledger_text: str,
    *,
    backend: str,
    now: datetime,
    lead_agent_id: str | None,
    agents_data: Any,
    worktree_records: Any,
    shells_data: Any,
    repo_dir: Path,
) -> dict[str, Any]:
    """Pure decision over injected inputs. Never raises; never acts."""
    try:
        if backend not in {"traycer", "claude-native"}:
            raise Unavailable("backend_incomplete", f"backend {backend!r} is not traycer or claude-native")
        if now.tzinfo is None:
            raise Unavailable("clock_invalid", "now must be timezone-qualified")
        if backend == "traycer":
            check_single_writer(ledger_text, lead_agent_id)
        rows = load_inventory(ledger_text)
        custody_blockers = load_custody_blockers(ledger_text)
        worktree_paths = parse_worktrees(worktree_records)

        live_shell_rows = [r for r in rows if r["kind"] == "shell" and r["state"] == "running"]
        shells: dict[str, dict[str, Any]] | None = None
        if live_shell_rows:
            if shells_data is None:
                raise Unavailable(
                    "shells_listing_missing",
                    "the inventory has running shells but no --shells-json listing was given",
                )
            shells = parse_shell_listing(shells_data)

        agents: dict[str, dict[str, Any]] | None = None
        if backend == "traycer":
            agents = parse_agent_listing(agents_data)

        findings: list[dict[str, Any]] = []
        inventory_ids = {r["id"] for r in rows}
        for row in rows:
            if row["kind"] == "agent":
                if agents is None:
                    findings.append(_base(row, "not_applicable"))
                else:
                    findings.append(decide_agent(row, agents.get(row["id"]), now, custody_blockers))
            else:
                findings.append(decide_other(row, worktree_paths, shells))

        listed_in_project = 0
        if agents is not None:
            project_paths = set(worktree_paths) | {str(repo_dir)}
            for agent_id, agent in sorted(agents.items()):
                if not _agent_belongs_to_project(agent, project_paths):
                    continue
                listed_in_project += 1
                if agent_id in inventory_ids or agent_id == lead_agent_id or agent["archived"]:
                    continue
                findings.append({
                    "finding": "not_mine",
                    "id": agent_id,
                    "kind": "agent",
                    "source": "listing",
                    "parent_id": agent.get("parentId"),
                    "title": agent.get("title"),
                    "hint": "active" if agent["active"] else "idle",
                })
    except Unavailable as fault:
        return _unavailable(fault.reason_code, fault.reason, backend if backend in {"traycer", "claude-native"} else None)

    counts: dict[str, Any] = {name: 0 for name in FINDINGS}
    for item in findings:
        counts[item["finding"]] += 1
    counts["inventory"] = len(rows)
    counts["agents"] = "not_applicable" if agents is None else {"listed_in_project": listed_in_project}
    return {
        "status": "ok",
        "reason_code": "reconciled",
        "reason": "inventory compared with the agent listing, git worktree list and the lead's shells",
        "backend": backend,
        "observed_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "idle_timeout_minutes": int(IDLE_TIMEOUT.total_seconds() // 60),
        "report_only": True,
        "counts": counts,
        "findings": findings,
    }


# --- I/O ------------------------------------------------------------------


def _read_json_file(path: str, what: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Unavailable("listing_unparseable", f"{what} {path}: {error}") from error


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    repo_dir = Path(args.repo_dir).resolve()
    backend = args.backend
    lead_agent_id = args.lead_agent_id
    try:
        if backend is None:
            detected = _detect_backend()
            if detected.get("detection_status") != "ready":
                raise Unavailable("backend_incomplete", f"backend detector: {detected.get('reason') or 'unknown'}")
            backend = detected.get("execution_backend")
            lead_agent_id = lead_agent_id or detected.get("traycer_agent_id")
        if args.now:
            now = _parse_time(args.now)
            if now is None:
                raise Unavailable("clock_invalid", f"--now {args.now!r} is not a timezone-qualified time")
        else:
            now = datetime.now(timezone.utc)
        try:
            ledger_text = Path(args.dev_state).read_text(encoding="utf-8")
        except OSError as error:
            raise Unavailable("ledger_unreadable", f"{args.dev_state}: {error}") from error

        if args.worktrees_porcelain:
            try:
                worktree_records = _parse_porcelain(Path(args.worktrees_porcelain).read_text(encoding="utf-8"))
            except OSError as error:
                raise Unavailable("listing_unparseable", f"{args.worktrees_porcelain}: {error}") from error
        else:
            try:
                worktree_records = _git_worktree_list(repo_dir)
            except ScriptError as error:
                raise Unavailable("listing_error", str(error)) from error

        agents_data = None
        if backend == "traycer":
            if args.agents_json:
                agents_data = _read_json_file(args.agents_json, "agent listing")
            else:
                try:
                    agents_data = _run_traycer_cli(["agent", "list", "--json"])
                except ScriptError as error:
                    raise Unavailable("listing_error", str(error)) from error

        shells_data = _read_json_file(args.shells_json, "shell listing") if args.shells_json else None
    except Unavailable as fault:
        return _unavailable(fault.reason_code, fault.reason, backend if backend in {"traycer", "claude-native"} else None)

    return reconcile(
        ledger_text,
        backend=backend,
        now=now,
        lead_agent_id=lead_agent_id,
        agents_data=agents_data,
        worktree_records=worktree_records,
        shells_data=shells_data,
        repo_dir=repo_dir,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report-only inventory reconcile (Issue #112).")
    parser.add_argument("--dev-state", default=".agent/dev-state.md", help="ledger path")
    parser.add_argument("--repo-dir", default=".", help="repository root for git worktree list")
    parser.add_argument("--backend", choices=("traycer", "claude-native"), help="skip backend detection")
    parser.add_argument("--lead-agent-id", help="the calling lead's agent id (traycer)")
    parser.add_argument("--now", help="timezone-qualified ISO time to evaluate at (default: now, UTC)")
    parser.add_argument("--agents-json", help="saved `traycer_cli.py agent list --json` output")
    parser.add_argument("--worktrees-porcelain", help="saved `git worktree list --porcelain` output")
    parser.add_argument("--shells-json", help="the lead's shell listing: a list or {shells: [...]} of {id, status}")
    report = build_report(parser.parse_args(argv))
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
