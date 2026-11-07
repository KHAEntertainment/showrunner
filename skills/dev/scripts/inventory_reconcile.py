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

- the Traycer agent listing (``traycer_cli.py agent list --json``, read
  with its full envelope so status and pagination markers are checked),
- ``git worktree list --porcelain`` for the repository,
- the lead's own shells (no CLI lists them; the lead passes its shell
  listing in with ``--shells-json``).

Every inventory row gets exactly one finding:

- ``archive_due``: an agent idle for MORE than 60 minutes (strictly
  greater; exactly 60:00 is not due) with no open request.
- ``blocked_by_open_request``: idle past the timeout, but the lead has an
  open request with it. Each request is named.
- ``blocked``: not archivable for another reason (``listing_active``,
  ``listing_owner_mismatch``, ``state:<state>``, ``obligation:children``,
  ``successor_custody``, ``open_requests_unknown``,
  ``open_requests_malformed``, ``idle_unknown``, ``shell_unmatched``).
- ``not_due``: idle for 60 minutes or less.
- ``target_gone``: the row's agent, worktree, checkout or shell is missing
  from its listing.
- ``already_archived``: the listing shows the agent archived but the row
  does not say so yet.
- ``tracked``: a live worktree, checkout or shell that is present.
- ``skipped``: the row is in a terminal state (``archived-*``, ``cleaned``,
  ``removed``, ``stopped``, ``exited``).
- ``not_mine``: listed agents in this project that are NOT in the
  inventory (``source: listing``), and ``foreign-*`` inventory rows
  (``source: inventory``). Neither is ever a candidate for action.
- ``not_applicable``: an agent row on the claude-native backend, which has
  no agent listing.

The idle signal is the ledger's ``last_exchange_at``: the Traycer agent
listing carries no last-activity timestamp (probed 2026-11-06), so the
lead records the time of every message it sends to an agent and every
reply it receives. A listing row with ``active: true`` overrides the clock.

It fails closed. Any fault, inconsistency or malformed input gives
``status: unavailable`` with ``counts: null``, no findings and exit 2: a
CLI error, timeout, non-zero exit or unparseable output; an error status or
a partial or pagination marker at any level of the listing; an empty
listing or one that omits the lead; a duplicate id; a field of the wrong
type; non-UTF-8 input; an unreadable or malformed ledger or recovery
record; a malformed writer id or a second writer on the run ledger. An
empty result never stands in for "unknown", and no input produces a
traceback.

Exit 0 when ``status`` is ``ok``, 2 when it is ``unavailable``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# Reuse, not copies. tests/test_inventory_reconcile.py fails loudly if any of
# these names disappears from its module. The agent listing is read here, not
# through workspace_debt._run_traycer_cli, because that helper returns only
# the envelope's `data` and drops the status and pagination markers.
from dev_state import LEDGER_ABSENT, GoalRunError, read_ledger_block  # noqa: E402
from workspace_debt import (  # noqa: E402
    COMMAND_TIMEOUT_SECONDS,
    WRAPPER,
    ScriptError,
    _agent_belongs_to_project,
    _detect_backend,
    _git_worktree_list,
    _parse_porcelain,
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

# Keys a paged, truncated or partial listing carries. Any of them set, at the
# envelope or the data level, means the rows we hold are not the whole listing.
PAGINATION_KEYS = (
    "nextOffset", "next_offset", "hasMore", "has_more", "hasNextPage", "has_next_page",
    "nextPageToken", "next_page_token", "nextCursor", "next_cursor", "next",
    "truncated", "partial", "incomplete",
)

FINDINGS = (
    "archive_due", "blocked_by_open_request", "blocked", "not_due",
    "target_gone", "already_archived", "tracked", "skipped", "not_mine",
    "not_applicable",
)

# Keys a listing level uses to declare how many rows it holds. Any one that is
# present, at any level, must equal the rows received.
TOTAL_KEYS = ("total", "count", "totalCount", "total_count", "totalRows", "total_rows")

BACKENDS = frozenset({"traycer", "claude-native"})


def _known_backend(backend: Any) -> bool:
    return isinstance(backend, str) and backend in BACKENDS


class Unavailable(Exception):
    """A fault that makes the whole report ``unavailable``."""

    def __init__(self, reason_code: str, reason: str) -> None:
        super().__init__(reason)
        self.reason_code = reason_code
        self.reason = reason


def _unavailable(reason_code: str, reason: str, backend: Any) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason_code": reason_code,
        "reason": reason,
        "backend": backend if _known_backend(backend) else None,
        "report_only": True,
        "counts": None,
        "findings": [],
    }


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _parse_time(value: Any) -> datetime | None:
    """A timezone-qualified ISO-8601 time, or None when it is not one."""
    if not _is_text(value):
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


def _read_text(path: str, what: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise Unavailable("input_unreadable", f"{what} {path} is not UTF-8: {error}") from error
    except OSError as error:
        raise Unavailable("input_unreadable", f"{what} {path}: {error}") from error


def _read_json(path: str, what: str) -> Any:
    text = _read_text(path, what)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, RecursionError) as error:
        raise Unavailable("listing_unparseable", f"{what} {path}: {error}") from error


# --- ledger ---------------------------------------------------------------


def _check_open_requests(value: Any) -> list[dict[str, str]] | str | None:
    """None when absent (unknown); ``"malformed"`` for a bad value; else the list."""
    if value is LEDGER_ABSENT or value is None:
        return None
    if not isinstance(value, list):
        return "malformed"
    requests = []
    for item in value:
        if not isinstance(item, dict) or not _is_text(item.get("id")) or not _is_text(item.get("what")):
            return "malformed"
        requests.append({"id": item["id"], "what": item["what"]})
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
        if not _is_text(row_id):
            raise Unavailable("inventory_malformed", f"inventory[{index}] has no string id")
        if row_id in seen:
            raise Unavailable("inventory_malformed", f"inventory id {row_id} appears twice")
        seen.add(row_id)
        kind = row.get("kind")
        if not isinstance(kind, str) or kind not in STATES:
            raise Unavailable("inventory_malformed", f"inventory {row_id}: unknown kind {kind!r}")
        state = row.get("state")
        if not isinstance(state, str) or state not in STATES[kind]:
            raise Unavailable("inventory_malformed", f"inventory {row_id}: state {state!r} is not a {kind} state")
        pr = row.get("pr")
        if pr is not None and (isinstance(pr, bool) or not isinstance(pr, int)):
            raise Unavailable("inventory_malformed", f"inventory {row_id}: pr must be an integer or null")
        role = row.get("role")
        if role is not None and not isinstance(role, str):
            raise Unavailable("inventory_malformed", f"inventory {row_id}: role must be a string or null")
        for optional in ("shell_id", "path"):
            if optional in row and row[optional] is not None and not _is_text(row[optional]):
                raise Unavailable("inventory_malformed", f"inventory {row_id}: {optional} must be a non-blank string")
        clean = dict(row)
        if kind == "agent":
            clean["open_requests"] = _check_open_requests(row.get("open_requests", LEDGER_ABSENT))
        rows.append(clean)
    return rows


def _writer_id(text: str, block: str, field: str) -> str | None:
    value = _read_block(text, block)
    if value is LEDGER_ABSENT or value is None:
        return None
    if not isinstance(value, dict):
        raise Unavailable("writer_malformed", f"{block} must be a map")
    writer = value.get(field)
    if writer is None:
        return None
    if not _is_text(writer):
        raise Unavailable("writer_malformed", f"{block}.{field} must be null or a non-blank string")
    return writer


def check_single_writer(text: str, lead_agent_id: Any) -> None:
    """SC-7 ``rejected-two-active-writers``: one run ledger has one writer.

    The lead is the sole writer of its ledger. Its id is recorded twice:
    ``lead.agent_id`` and ``execution.traycer_agent_id`` (the id the lead-swap
    rule in ``backends/traycer.md`` compares). Each must be null or a
    non-blank string, and every recorded id must equal the caller; a caller
    that differs from either is a second active writer on the same run
    ledger, and the report refuses. After a lead swap the new lead updates
    both before it runs the reconcile. Inventory rows (workers, QA,
    reviewers, a re-dispatched worker) are never writers and never trip this.
    """
    if not _is_text(lead_agent_id):
        raise Unavailable("lead_agent_id_missing", "the caller's lead agent id is required on traycer")
    recorded = {
        where: writer
        for where, writer in (
            ("lead.agent_id", _writer_id(text, "lead", "agent_id")),
            ("execution.traycer_agent_id", _writer_id(text, "execution", "traycer_agent_id")),
        )
        if writer is not None
    }
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


def _recovery_ids(record: Any, where: str, fields: tuple[str, ...]) -> list[str]:
    if not isinstance(record, dict):
        raise Unavailable("recovery_malformed", f"{where} must be a map")
    ids = []
    for field in fields:
        if field not in record:
            raise Unavailable("recovery_malformed", f"{where}.{field} is missing")
        value = record[field]
        if value is None:
            continue
        if not _is_text(value):
            raise Unavailable("recovery_malformed", f"{where}.{field} must be null or a non-blank string")
        ids.append(value)
    return ids


def load_custody_blockers(text: str) -> dict[str, str]:
    """Agent ids the goal-run recovery records name: they are never idle-archivable.

    Only a legitimately absent ``goal_run``, ``obligations`` or ``custody``
    counts as none; any present record of the wrong shape is unavailable.
    """
    goal_run = _read_block(text, "goal_run")
    if goal_run is LEDGER_ABSENT or goal_run is None:
        return {}
    if not isinstance(goal_run, dict):
        raise Unavailable("recovery_malformed", "goal_run must be a map or null")
    blockers: dict[str, str] = {}
    obligations = goal_run.get("obligations")
    if obligations is not None:
        if not isinstance(obligations, dict):
            raise Unavailable("recovery_malformed", "goal_run.obligations must be a map")
        children = obligations.get("children")
        if not isinstance(children, list):
            raise Unavailable("recovery_malformed", "goal_run.obligations.children must be a list")
        for child in children:
            if not _is_text(child):
                raise Unavailable("recovery_malformed", "goal_run.obligations.children entries must be agent ids")
            blockers[child] = "obligation:children"
    custody = goal_run.get("custody")
    if custody is not None:
        for session in _recovery_ids(custody, "goal_run.custody", ("prior_session_id", "current_session_id")):
            blockers.setdefault(session, "successor_custody")
    return blockers


# --- listings -------------------------------------------------------------


def _check_envelope_level(payload: dict[str, Any], what: str) -> None:
    status = payload.get("status")
    if "status" in payload and status != "ok":
        raise Unavailable("listing_error", f"{what} status {status!r}")
    if "ok" in payload and payload["ok"] is not True:
        raise Unavailable("listing_error", f"{what} ok is {payload['ok']!r}")
    if payload.get("error") not in (None, False, "", {}, []):
        raise Unavailable("listing_error", f"{what} carries an error")
    for key in PAGINATION_KEYS:
        if payload.get(key) not in (None, False, "", 0):
            raise Unavailable("listing_partial", f"{what} is paged or partial ({key} is set)")


def _check_total(payload: dict[str, Any], what: str, rows: list[Any]) -> None:
    """Every declared total at this level must equal the rows received."""
    for key in TOTAL_KEYS:
        if key not in payload or payload[key] is None:
            continue
        total = payload[key]
        if isinstance(total, bool) or not isinstance(total, int) or total != len(rows):
            raise Unavailable("listing_partial", f"{what} declares {key} {total!r} but holds {len(rows)} rows")


def parse_agent_listing(envelope: Any, lead_agent_id: Any) -> dict[str, dict[str, Any]]:
    """Validate the full `agent list --json` envelope, or a flat object."""
    if not isinstance(envelope, dict):
        raise Unavailable("listing_unparseable", "agent listing is not an object")
    _check_envelope_level(envelope, "agent listing")
    if "data" in envelope:
        data = envelope["data"]
        if not isinstance(data, dict):
            raise Unavailable("listing_unparseable", "agent listing data is not an object")
        _check_envelope_level(data, "agent listing data")
    else:
        data = envelope
    agents = data.get("agents")
    if not isinstance(agents, list):
        raise Unavailable("listing_unparseable", "agent listing has no agents array")
    # Totals at every level, so an outer total that disagrees with the rows,
    # or with an inner total, is caught before any decision.
    if data is not envelope:
        _check_total(envelope, "agent listing", agents)
    _check_total(data, "agent listing data" if data is not envelope else "agent listing", agents)
    if not agents:
        raise Unavailable("listing_partial", "agent listing is empty; it always lists at least the lead")
    by_id: dict[str, dict[str, Any]] = {}
    for index, agent in enumerate(agents):
        if not isinstance(agent, dict):
            raise Unavailable("listing_partial", f"agent listing row {index} is not an object")
        missing = [field for field in AGENT_LISTING_FIELDS if field not in agent]
        if missing:
            raise Unavailable("listing_partial", f"agent listing row {index} lacks {', '.join(missing)}")
        agent_id = agent["id"]
        if not _is_text(agent_id):
            raise Unavailable("listing_partial", f"agent listing row {index} has no string id")
        if not isinstance(agent["active"], bool) or not isinstance(agent["archived"], bool):
            raise Unavailable("listing_partial", f"agent {agent_id}: active/archived must be booleans")
        paths = agent["folderPaths"]
        if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
            raise Unavailable("listing_partial", f"agent {agent_id}: folderPaths must be a list of strings")
        parent = agent.get("parentId")
        if parent is not None and not isinstance(parent, str):
            raise Unavailable("listing_partial", f"agent {agent_id}: parentId must be a string or null")
        if agent_id in by_id:
            raise Unavailable("listing_duplicate_id", f"agent listing has id {agent_id} twice")
        by_id[agent_id] = agent
    if lead_agent_id not in by_id:
        raise Unavailable("listing_partial", f"agent listing omits the lead {lead_agent_id}")
    return by_id


def parse_worktrees(records: Any) -> set[str]:
    if not isinstance(records, list) or not records:
        # A repository always lists at least its main worktree.
        raise Unavailable("listing_unparseable", "git worktree list returned no worktrees")
    paths: set[str] = set()
    for record in records:
        path = record.get("worktreePath") if isinstance(record, dict) else None
        if not _is_text(path):
            raise Unavailable("listing_partial", "a git worktree record has no path")
        if path in paths:
            raise Unavailable("listing_duplicate_id", f"git worktree list has {path} twice")
        paths.add(path)
    return paths


def parse_shell_listing(data: Any) -> dict[str, dict[str, Any]]:
    if isinstance(data, dict):
        _check_envelope_level(data, "shell listing")
        shells = data.get("shells")
        if not isinstance(shells, list):
            raise Unavailable("listing_unparseable", "shell listing has no shells array")
        _check_total(data, "shell listing", shells)
    elif isinstance(data, list):
        shells = data
    else:
        raise Unavailable("listing_unparseable", "shell listing is not a list or object")
    by_id: dict[str, dict[str, Any]] = {}
    for index, shell in enumerate(shells):
        if not isinstance(shell, dict) or not _is_text(shell.get("id")):
            raise Unavailable("listing_partial", f"shell listing row {index} has no string id")
        if not isinstance(shell.get("status"), str):
            raise Unavailable("listing_partial", f"shell {shell['id']} has no status")
        if shell["id"] in by_id:
            raise Unavailable("listing_duplicate_id", f"shell listing has id {shell['id']} twice")
        by_id[shell["id"]] = shell
    return by_id


def _checkout_path(row: dict[str, Any]) -> str:
    if _is_text(row.get("path")):
        return row["path"]
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
    lead_agent_id: str,
    project_paths: set[str],
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
    parent = listed.get("parentId")
    if (parent is not None and parent != lead_agent_id) or not _agent_belongs_to_project(listed, project_paths):
        return _base(row, "blocked", reason="listing_owner_mismatch")
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
    if open_requests == "malformed":
        return _base(row, "blocked", reason="open_requests_malformed")
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
        return _base(row, "tracked" if row["id"] in worktree_paths else "target_gone")
    if kind == "review_checkout":
        return _base(row, "tracked" if _checkout_path(row) in worktree_paths else "target_gone")
    # shell: a running row, so reconcile() has required the shell listing.
    if shells is None:
        raise Unavailable("shells_listing_missing", "a running shell row has no shell listing")
    if _is_text(row.get("shell_id")):
        return _base(row, "tracked" if row["shell_id"] in shells else "target_gone")
    # Without shell_id, only the full row id can match; a partial match is
    # never evidence, so an unmatched row is blocked, not gone.
    if row["id"] in shells:
        return _base(row, "tracked")
    return _base(row, "blocked", reason="shell_unmatched")


def _reconcile(
    ledger_text: str,
    *,
    backend: Any,
    now: Any,
    lead_agent_id: Any,
    agents_data: Any,
    worktree_records: Any,
    shells_data: Any,
    repo_dir: Path,
) -> dict[str, Any]:
    if not _known_backend(backend):
        raise Unavailable("backend_incomplete", f"backend {backend!r} is not traycer or claude-native")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise Unavailable("clock_invalid", "now must be a timezone-qualified time")
    if not isinstance(ledger_text, str):
        raise Unavailable("ledger_unreadable", "the ledger is not text")
    if backend == "traycer":
        check_single_writer(ledger_text, lead_agent_id)
    rows = load_inventory(ledger_text)
    custody_blockers = load_custody_blockers(ledger_text)
    worktree_paths = parse_worktrees(worktree_records)
    project_paths = set(worktree_paths) | {str(repo_dir)}

    shells: dict[str, dict[str, Any]] | None = None
    if any(r["kind"] == "shell" and r["state"] == "running" for r in rows):
        if shells_data is None:
            raise Unavailable(
                "shells_listing_missing",
                "the inventory has running shells but no --shells-json listing was given",
            )
        shells = parse_shell_listing(shells_data)

    agents = parse_agent_listing(agents_data, lead_agent_id) if backend == "traycer" else None

    findings: list[dict[str, Any]] = []
    inventory_ids = {r["id"] for r in rows}
    for row in rows:
        if row["kind"] == "agent":
            if agents is None:
                findings.append(_base(row, "not_applicable"))
            else:
                findings.append(decide_agent(
                    row, agents.get(row["id"]), now, custody_blockers, lead_agent_id, project_paths,
                ))
        else:
            findings.append(decide_other(row, worktree_paths, shells))

    listed_in_project = 0
    if agents is not None:
        for agent_id, agent in sorted(agents.items()):
            if not _agent_belongs_to_project(agent, project_paths):
                continue
            listed_in_project += 1
            if agent_id in inventory_ids or agent_id == lead_agent_id or agent["archived"]:
                continue
            title = agent.get("title")
            findings.append({
                "finding": "not_mine",
                "id": agent_id,
                "kind": "agent",
                "source": "listing",
                "parent_id": agent.get("parentId"),
                "title": title if isinstance(title, str) else None,
                "hint": "active" if agent["active"] else "idle",
            })

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


def reconcile(ledger_text: str, *, backend: Any, **inputs: Any) -> dict[str, Any]:
    """Pure decision over injected inputs. Never raises; never acts."""
    try:
        return _reconcile(ledger_text, backend=backend, **inputs)
    except Unavailable as fault:
        return _unavailable(fault.reason_code, fault.reason, backend)
    except Exception as error:  # noqa: BLE001 - fail closed on anything unforeseen
        return _unavailable("internal_error", f"{type(error).__name__}: {error}", backend)


# --- I/O ------------------------------------------------------------------


def read_agent_listing_live() -> dict[str, Any]:
    """`traycer_cli.py agent list --json`, keeping the whole envelope.

    Same wrapper route, timeout and exit-code handling as
    workspace_debt._run_traycer_cli, which returns only `data`.
    """
    if not WRAPPER.is_file():
        raise Unavailable("listing_error", f"traycer_cli.py wrapper missing at {WRAPPER}")
    try:
        completed = subprocess.run(
            [sys.executable, str(WRAPPER), "agent", "list", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise Unavailable("listing_error", f"agent list --json timed out after {COMMAND_TIMEOUT_SECONDS}s") from error
    except UnicodeDecodeError as error:
        raise Unavailable("input_unreadable", f"agent list --json output is not UTF-8: {error}") from error
    except OSError as error:
        raise Unavailable("listing_error", f"agent list --json failed to launch: {error}") from error
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[:200] or "no output"
        raise Unavailable("listing_error", f"agent list --json exit {completed.returncode}: {detail}")
    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError, RecursionError) as error:
        raise Unavailable("listing_unparseable", f"agent list --json returned malformed JSON: {error}") from error
    if not isinstance(payload, dict):
        raise Unavailable("listing_unparseable", "agent list --json returned a non-object payload")
    return payload


def _build_report(args: argparse.Namespace) -> tuple[dict[str, Any], Any]:
    repo_dir = Path(args.repo_dir).resolve()
    backend = args.backend
    lead_agent_id = args.lead_agent_id
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
    ledger_text = _read_text(args.dev_state, "ledger")

    if args.worktrees_porcelain:
        worktree_records = _parse_porcelain(_read_text(args.worktrees_porcelain, "worktree listing"))
    else:
        try:
            worktree_records = _git_worktree_list(repo_dir)
        except ScriptError as error:
            raise Unavailable("listing_error", str(error)) from error
        except UnicodeDecodeError as error:
            raise Unavailable("input_unreadable", f"git worktree list output is not UTF-8: {error}") from error

    agents_data = None
    if backend == "traycer":
        agents_data = (
            _read_json(args.agents_json, "agent listing") if args.agents_json else read_agent_listing_live()
        )
    shells_data = _read_json(args.shells_json, "shell listing") if args.shells_json else None

    report = reconcile(
        ledger_text,
        backend=backend,
        now=now,
        lead_agent_id=lead_agent_id,
        agents_data=agents_data,
        worktree_records=worktree_records,
        shells_data=shells_data,
        repo_dir=repo_dir,
    )
    return report, backend


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    """Read the inputs and reconcile. Never raises."""
    backend = getattr(args, "backend", None)
    try:
        report, _ = _build_report(args)
        return report
    except Unavailable as fault:
        return _unavailable(fault.reason_code, fault.reason, backend)
    except Exception as error:  # noqa: BLE001 - fail closed on anything unforeseen
        return _unavailable("internal_error", f"{type(error).__name__}: {error}", backend)


class _Parser(argparse.ArgumentParser):
    """Usage errors become an unavailable report, not argparse's exit."""

    def error(self, message: str) -> None:  # type: ignore[override]
        raise Unavailable("usage_error", message)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(description="Report-only inventory reconcile (Issue #112).")
    parser.add_argument("--dev-state", default=".agent/dev-state.md", help="ledger path")
    parser.add_argument("--repo-dir", default=".", help="repository root for git worktree list")
    parser.add_argument("--backend", choices=("traycer", "claude-native"), help="skip backend detection")
    parser.add_argument("--lead-agent-id", help="the calling lead's agent id (traycer)")
    parser.add_argument("--now", help="timezone-qualified ISO time to evaluate at (default: now, UTC)")
    parser.add_argument("--agents-json", help="saved `traycer_cli.py agent list --json` output (full envelope)")
    parser.add_argument("--worktrees-porcelain", help="saved `git worktree list --porcelain` output")
    parser.add_argument("--shells-json", help="the lead's shell listing: a list or {shells: [...]} of {id, status}")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        report = build_report(_parser().parse_args(argv))
    except Unavailable as fault:
        report = _unavailable(fault.reason_code, fault.reason, None)
    except Exception as error:  # noqa: BLE001 - never a traceback
        report = _unavailable("internal_error", f"{type(error).__name__}: {error}", None)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
