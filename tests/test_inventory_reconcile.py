"""Tests for the report-only inventory reconcile (Issue #112).

Every listing is injected: no test reaches the live Traycer CLI, runs
`git`, or spawns a subprocess. The CLI-failure paths patch the imported
helpers in the script's namespace instead.

Fixtures live under `tests/fixtures/inventory_reconcile/` and the SC-7
contract fixtures under `docs/v2.2/contracts/fixtures/sc-7/` are read as
inputs, never edited.
"""

from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "dev" / "scripts"
SCRIPT = SCRIPTS / "inventory_reconcile.py"
FIXTURES = ROOT / "tests" / "fixtures" / "inventory_reconcile"
SC7 = ROOT / "docs" / "v2.2" / "contracts" / "fixtures" / "sc-7"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("inventory_reconcile", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

NOW = datetime(2026, 11, 6, 12, 0, 0, tzinfo=timezone.utc)
REPO_DIR = Path("/synthetic/repo/main")
LEAD = "lead-1"
AGENTS = json.loads((FIXTURES / "agent_list.json").read_text(encoding="utf-8"))
SHELLS = json.loads((FIXTURES / "shells.json").read_text(encoding="utf-8"))
WORKTREES = MODULE._parse_porcelain((FIXTURES / "worktrees.porcelain").read_text(encoding="utf-8"))

# Words an idle decision must never produce: idle is not done, and archival
# is not deletion (SC-7 rejected-idle-inferred-done).
NEVER_STATES = {"done", "complete", "completed", "deletable", "deleted", "cleaned", "removed"}


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _scalar(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(value)


def ledger(rows, *, lead=LEAD, goal_run=None, inventory=True, execution_id=None):
    """Write a schema-v2 ledger frontmatter holding `rows` as inventory."""
    out = ["---", "schema_version: 2", "execution:", f"  traycer_agent_id: {_scalar(execution_id)}",
           "lead:", f"  agent_id: {_scalar(lead)}"]
    if inventory:
        if not rows:
            out.append("inventory: []")
        else:
            out.append("inventory:")
            for row in rows:
                first = True
                for key, value in row.items():
                    prefix = "  - " if first else "    "
                    first = False
                    if isinstance(value, list) and value:
                        out.append(f"{prefix}{key}:")
                        for item in value:
                            item_first = True
                            for ikey, ivalue in item.items():
                                ip = "      - " if item_first else "        "
                                item_first = False
                                out.append(f"{ip}{ikey}: {_scalar(ivalue)}")
                    elif isinstance(value, list):
                        out.append(f"{prefix}{key}: []")
                    else:
                        out.append(f"{prefix}{key}: {_scalar(value)}")
    if goal_run is not None:
        out.extend(goal_run)
    out.extend(["updated_at: null", "---", "", "# /dev Recovery Log", ""])
    return "\n".join(out)


def agent_row(agent_id="worker-1", *, idle=None, state="active", open_requests=(), **extra):
    row = {
        "id": agent_id,
        "kind": "agent",
        "pr": 12,
        "role": "worker-new",
        "created_at": "2026-11-06T08:00:00Z",
        "state": state,
    }
    if idle is not None:
        row["last_exchange_at"] = _iso(NOW - idle)
    if open_requests is not None:
        row["open_requests"] = list(open_requests)
    row.update(extra)
    return row


def run(rows, *, backend="traycer", agents=AGENTS, worktrees=WORKTREES, shells=SHELLS, lead=LEAD,
        lead_in_ledger=LEAD, execution_id=None, **kw):
    """`lead` is the calling agent; `lead_in_ledger` is the ledger's recorded writer."""
    text = kw.pop("text", None) or ledger(rows, lead=lead_in_ledger, execution_id=execution_id, **kw)
    return MODULE.reconcile(
        text,
        backend=backend,
        now=NOW,
        lead_agent_id=lead,
        agents_data=agents,
        worktree_records=worktrees,
        shells_data=shells,
        repo_dir=REPO_DIR,
    )


def finding_for(report, row_id):
    matches = [f for f in report["findings"] if f["id"] == row_id]
    assert len(matches) == 1, (row_id, report)
    return matches[0]


def agents_with(mutate):
    data = copy.deepcopy(AGENTS)
    mutate(data["data"])
    return data


class ImportedHelpersTest(unittest.TestCase):
    """The script reuses private helpers by import; fail loudly if one goes."""

    def test_reused_names_still_exist(self):
        import dev_state
        import workspace_debt

        for name in (
            "ScriptError", "_agent_belongs_to_project", "_detect_backend",
            "_git_worktree_list", "_parse_porcelain",
        ):
            self.assertTrue(callable(getattr(workspace_debt, name, None)), f"workspace_debt.{name} disappeared")
        for name in ("WRAPPER", "COMMAND_TIMEOUT_SECONDS"):
            self.assertTrue(hasattr(workspace_debt, name), f"workspace_debt.{name} disappeared")
        for name in ("LEDGER_ABSENT", "GoalRunError", "read_ledger_block"):
            self.assertTrue(hasattr(dev_state, name), f"dev_state.{name} disappeared")


class IdleBoundaryTest(unittest.TestCase):
    """Exit criterion 1: idle STRICTLY greater than 60 minutes is due."""

    def test_just_under_sixty_is_not_due(self):
        report = run([agent_row(idle=timedelta(minutes=59, seconds=59))])
        self.assertEqual(report["status"], "ok")
        self.assertEqual(finding_for(report, "worker-1")["finding"], "not_due")

    def test_exactly_sixty_is_not_due(self):
        report = run([agent_row(idle=timedelta(minutes=60))])
        self.assertEqual(finding_for(report, "worker-1")["finding"], "not_due")

    def test_just_over_sixty_is_archive_due(self):
        report = run([agent_row(idle=timedelta(minutes=60, seconds=1))])
        item = finding_for(report, "worker-1")
        self.assertEqual(item["finding"], "archive_due")
        self.assertEqual(item["proposed_action"], "archive")
        self.assertTrue(item["reversible"])
        self.assertEqual(item["next_state"], "archived-idle-timeout")
        self.assertEqual(report["counts"]["archive_due"], 1)

    def test_report_back_complete_is_archivable(self):
        report = run([agent_row(idle=timedelta(hours=2), state="report-back-complete")])
        self.assertEqual(finding_for(report, "worker-1")["finding"], "archive_due")

    def test_open_request_blocks_and_is_named(self):
        request = {"id": "resp-9", "what": "PR 12 QA report", "opened_at": "2026-11-06T09:00:00Z"}
        report = run([agent_row(idle=timedelta(minutes=61), open_requests=[request])])
        item = finding_for(report, "worker-1")
        self.assertEqual(item["finding"], "blocked_by_open_request")
        self.assertEqual(item["open_requests"], [{"id": "resp-9", "what": "PR 12 QA report"}])
        self.assertNotIn("proposed_action", item)

    def test_open_request_under_timeout_is_not_due(self):
        request = {"id": "resp-9", "what": "PR 12 QA report"}
        report = run([agent_row(idle=timedelta(minutes=10), open_requests=[request])])
        self.assertEqual(finding_for(report, "worker-1")["finding"], "not_due")


class BlockedStatesTest(unittest.TestCase):
    """Exit criterion 4: pending reports, waits and custody are preserved."""

    def assertBlocked(self, report, reason, row_id="worker-1"):
        item = finding_for(report, row_id)
        self.assertEqual(item["finding"], "blocked")
        self.assertEqual(item["reason"], reason)
        self.assertNotIn("proposed_action", item)

    def test_report_back_pending_is_not_idle_archivable(self):
        self.assertBlocked(run([agent_row(idle=timedelta(hours=5), state="report-back-pending")]),
                           "state:report-back-pending")

    def test_report_back_incomplete_is_not_idle_archivable(self):
        self.assertBlocked(run([agent_row(idle=timedelta(hours=5), state="report-back-incomplete")]),
                           "state:report-back-incomplete")

    def test_planned_row_is_blocked(self):
        self.assertBlocked(run([agent_row("never-made", idle=timedelta(hours=5), state="planned")]),
                           "state:planned", row_id="never-made")

    def test_listing_active_overrides_the_clock(self):
        agents = agents_with(lambda d: d["agents"][1].update(active=True))
        self.assertBlocked(run([agent_row(idle=timedelta(hours=5))], agents=agents), "listing_active")

    def test_missing_open_requests_is_unknown_not_none(self):
        self.assertBlocked(run([agent_row(idle=timedelta(hours=5), open_requests=None)]), "open_requests_unknown")

    def test_missing_last_exchange_is_idle_unknown(self):
        self.assertBlocked(run([agent_row(idle=None)]), "idle_unknown")

    def test_naive_last_exchange_is_idle_unknown(self):
        self.assertBlocked(run([agent_row(last_exchange_at="2026-11-06T08:00:00")]), "idle_unknown")

    def test_future_last_exchange_is_idle_unknown(self):
        self.assertBlocked(run([agent_row(idle=timedelta(minutes=-5))]), "idle_unknown")

    def test_obligation_child_is_preserved(self):
        goal_run = ["goal_run:", "  obligations:", "    children:", "      - worker-1"]
        self.assertBlocked(run([agent_row(idle=timedelta(hours=5))], goal_run=goal_run), "obligation:children")

    def test_successor_custody_is_preserved(self):
        goal_run = ["goal_run:", "  custody:", "    prior_session_id: worker-1", "    current_session_id: lead-1"]
        self.assertBlocked(run([agent_row(idle=timedelta(hours=5))], goal_run=goal_run), "successor_custody")


class OwnershipTest(unittest.TestCase):
    """Exit criterion 2: nothing outside the inventory is ever a candidate."""

    def test_listed_agents_outside_inventory_are_not_mine(self):
        report = run([agent_row(idle=timedelta(hours=2))])
        item = finding_for(report, "foreign-1")
        self.assertEqual(item["finding"], "not_mine")
        self.assertEqual(item["source"], "listing")
        self.assertEqual(item["hint"], "idle")
        self.assertEqual(item["parent_id"], "someone-else")
        # qa-1 is ours by parentId but not in the inventory: still not mine.
        self.assertEqual(finding_for(report, "qa-1")["finding"], "not_mine")
        self.assertEqual(finding_for(report, "qa-1")["parent_id"], "previous-lead")

    def test_only_inventory_rows_carry_an_action(self):
        report = run([agent_row(idle=timedelta(hours=2))])
        actionable = {f["id"] for f in report["findings"] if "proposed_action" in f}
        self.assertEqual(actionable, {"worker-1"})

    def test_lead_other_projects_and_archived_listings_are_not_reported(self):
        report = run([])
        ids = {f["id"] for f in report["findings"]}
        self.assertNotIn(LEAD, ids)
        self.assertNotIn("other-project-1", ids)
        self.assertNotIn("foreign-archived", ids)

    def test_foreign_inventory_rows_are_not_mine(self):
        rows = [
            agent_row("foreign-1", idle=timedelta(hours=9), state="foreign-idle"),
            {"id": "/synthetic/repo/main", "kind": "worktree", "pr": None, "role": None,
             "created_at": "2026-11-06T08:00:00Z", "state": "foreign"},
        ]
        report = run(rows)
        for row_id in ("foreign-1", "/synthetic/repo/main"):
            item = finding_for(report, row_id)
            self.assertEqual(item["finding"], "not_mine")
            self.assertNotIn("proposed_action", item)


class LifecycleStatesTest(unittest.TestCase):
    """Exit criterion 4: stopped, idle, archived, done, deletable stay distinct."""

    def test_archived_rows_are_skipped_even_when_gone(self):
        rows = [agent_row(f"gone-{state}", idle=timedelta(hours=9), state=state)
                for state in ("archived-on-accept", "archived-on-closeout", "archived-idle-timeout")]
        report = run(rows)
        self.assertEqual({f["finding"] for f in report["findings"] if f["id"].startswith("gone-")}, {"skipped"})

    def test_archive_never_sets_done_or_deletable(self):
        report = run([agent_row(idle=timedelta(hours=3))])
        for item in report["findings"]:
            self.assertNotIn(item.get("next_state"), NEVER_STATES)
            self.assertIn(item.get("proposed_action"), (None, "archive"))
        self.assertTrue(report["report_only"])

    def test_listing_archived_but_row_live_is_reported(self):
        agents = agents_with(lambda d: d["agents"][1].update(archived=True))
        report = run([agent_row(idle=timedelta(hours=3))], agents=agents)
        self.assertEqual(finding_for(report, "worker-1")["finding"], "already_archived")

    def test_target_gone_for_each_kind(self):
        rows = [
            agent_row("vanished-agent", idle=timedelta(hours=3)),
            {"id": "/synthetic/repo/wt-gone", "kind": "worktree", "pr": 12, "role": "worker-new",
             "created_at": "2026-11-06T08:00:00Z", "state": "in-progress"},
            {"id": "review:/synthetic/repo/review-gone", "kind": "review_checkout", "pr": 12, "role": "qa",
             "created_at": "2026-11-06T08:00:00Z", "state": "in-use"},
            {"id": "shell:host-1:gone-shell", "kind": "shell", "pr": None, "role": None,
             "created_at": "2026-11-06T08:00:00Z", "state": "running", "shell_id": "gone-shell"},
        ]
        report = run(rows)
        for row in rows:
            self.assertEqual(finding_for(report, row["id"])["finding"], "target_gone", row["id"])
        self.assertEqual(report["counts"]["target_gone"], 4)

    def test_present_targets_are_tracked_and_terminal_rows_skipped(self):
        rows = [
            {"id": "/synthetic/repo/wt-worker", "kind": "worktree", "pr": 12, "role": "worker-new",
             "created_at": "2026-11-06T08:00:00Z", "state": "landed-eligible"},
            {"id": "review:/synthetic/repo/review-12", "kind": "review_checkout", "pr": 12, "role": "qa",
             "created_at": "2026-11-06T08:00:00Z", "state": "clean"},
            {"id": "shell:host-1:dev-server", "kind": "shell", "pr": None, "role": None,
             "created_at": "2026-11-06T08:00:00Z", "state": "running", "shell_id": "dev-server"},
            {"id": "shell:host-1:old", "kind": "shell", "pr": None, "role": None,
             "created_at": "2026-11-06T08:00:00Z", "state": "stopped"},
            {"id": "/synthetic/repo/wt-old", "kind": "worktree", "pr": 3, "role": "worker-new",
             "created_at": "2026-11-06T08:00:00Z", "state": "cleaned"},
        ]
        report = run(rows)
        self.assertEqual([finding_for(report, r["id"])["finding"] for r in rows],
                         ["tracked", "tracked", "tracked", "skipped", "skipped"])


class FailClosedTest(unittest.TestCase):
    """Exit criterion 3: any doubt is `unavailable`, counts null, no actions."""

    def assertUnavailable(self, report, reason_code):
        self.assertEqual(report["status"], "unavailable", report)
        self.assertEqual(report["reason_code"], reason_code)
        self.assertIsNone(report["counts"])
        self.assertEqual(report["findings"], [])

    def test_agent_listing_status_error(self):
        self.assertUnavailable(run([agent_row(idle=timedelta(hours=3))],
                                   agents={"type": "result", "status": "error", "data": {}}), "listing_error")

    def test_agent_listing_unparseable(self):
        self.assertUnavailable(run([], agents="not json"), "listing_unparseable")
        self.assertUnavailable(run([], agents={"data": {"caller": {}}}), "listing_unparseable")
        self.assertUnavailable(run([], agents=None), "listing_unparseable")

    def test_paged_listing_is_partial(self):
        for key, value in (("nextOffset", 200), ("hasMore", True), ("next_page_token", "abc"), ("truncated", True)):
            agents = agents_with(lambda d, k=key, v=value: d.__setitem__(k, v))
            self.assertUnavailable(run([agent_row(idle=timedelta(hours=3))], agents=agents), "listing_partial")

    def test_total_mismatch_is_partial(self):
        agents = agents_with(lambda d: d.__setitem__("total", 999))
        self.assertUnavailable(run([agent_row(idle=timedelta(hours=3))], agents=agents), "listing_partial")

    def test_row_missing_a_decision_field_is_partial(self):
        for field in ("archived", "active", "folderPaths", "id"):
            agents = agents_with(lambda d, f=field: d["agents"][1].pop(f))
            self.assertUnavailable(run([agent_row(idle=timedelta(hours=3))], agents=agents), "listing_partial")

    def test_non_boolean_flags_are_partial(self):
        agents = agents_with(lambda d: d["agents"][1].update(active="no"))
        self.assertUnavailable(run([agent_row(idle=timedelta(hours=3))], agents=agents), "listing_partial")

    def test_empty_worktree_listing_is_not_an_empty_result(self):
        self.assertUnavailable(run([agent_row(idle=timedelta(hours=3))], worktrees=[]), "listing_unparseable")

    def test_running_shell_without_shell_listing(self):
        row = {"id": "shell:host-1:dev-server", "kind": "shell", "pr": None, "role": None,
               "created_at": "2026-11-06T08:00:00Z", "state": "running"}
        self.assertUnavailable(run([row], shells=None), "shells_listing_missing")
        self.assertUnavailable(run([row], shells={"shells": [{"id": "dev-server"}]}), "listing_partial")
        self.assertUnavailable(run([row], shells={"shells": [], "hasMore": True}), "listing_partial")

    def test_ledger_defects(self):
        self.assertUnavailable(run([], text="no frontmatter here"), "ledger_unreadable")
        self.assertUnavailable(run([], inventory=False), "inventory_missing")
        self.assertUnavailable(run([agent_row(state="idle")]), "inventory_malformed")
        self.assertUnavailable(run([agent_row(kind="robot")]), "inventory_malformed")
        self.assertUnavailable(run([agent_row(idle=timedelta(hours=2)), agent_row(idle=timedelta(hours=2))]),
                               "inventory_malformed")

    def test_unknown_backend(self):
        self.assertUnavailable(run([], backend="incomplete"), "backend_incomplete")

    def test_cli_timeout_and_nonzero_exit(self):
        args = MODULE.argparse.Namespace(
            dev_state=str(FIXTURES / "missing-on-purpose.md"), repo_dir=str(REPO_DIR), backend="traycer",
            lead_agent_id=LEAD, now=_iso(NOW), agents_json=None,
            worktrees_porcelain=str(FIXTURES / "worktrees.porcelain"), shells_json=None,
        )
        # Ledger first: an unreadable ledger is itself unavailable.
        self.assertUnavailable(MODULE.build_report(args), "input_unreadable")

        with self._ledger_file([agent_row(idle=timedelta(hours=3))]) as path:
            args.dev_state = path
            # Live path: only subprocess.run is mocked.
            for side_effect, code in (
                (subprocess.TimeoutExpired(cmd="traycer", timeout=30), "listing_error"),
                (subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom"), "listing_error"),
                (subprocess.CompletedProcess(args=[], returncode=0, stdout="not json", stderr=""),
                 "listing_unparseable"),
            ):
                kwargs = {"side_effect": side_effect} if isinstance(side_effect, Exception) else {
                    "return_value": side_effect}
                with mock.patch("subprocess.run", **kwargs):
                    self.assertUnavailable(MODULE.build_report(args), code)
            args.worktrees_porcelain = None
            with mock.patch.object(MODULE, "_git_worktree_list", side_effect=MODULE.ScriptError("git exit 128")):
                self.assertUnavailable(MODULE.build_report(args), "listing_error")
            args.backend = None
            with mock.patch.object(MODULE, "_detect_backend",
                                   return_value={"detection_status": "incomplete", "reason": "no identity"}):
                self.assertUnavailable(MODULE.build_report(args), "backend_incomplete")

    @contextlib.contextmanager
    def _ledger_file(self, rows):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dev-state.md"
            path.write_text(ledger(rows), encoding="utf-8")
            yield str(path)


class SingleWriterTest(unittest.TestCase):
    """SC-7 rejected-two-active-writers, mapped to the run ledger's writer."""

    FIXTURE = json.loads((SC7 / "rejected-two-active-writers.json").read_text(encoding="utf-8"))

    def test_fixture_two_writers_is_refused(self):
        self.assertEqual(self.FIXTURE["expected_outcome"], "reject")
        first, second = self.FIXTURE["input"]["writers"]
        report = run([agent_row(idle=timedelta(hours=3))], lead=second, lead_in_ledger=first)
        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["reason_code"], "two_active_writers")
        self.assertIsNone(report["counts"])
        self.assertEqual(report["findings"], [])

    def test_one_writer_with_qa_reviewer_and_redispatched_worker_passes(self):
        writer = self.FIXTURE["input"]["writers"][0]
        rows = [
            agent_row("worker-1", idle=timedelta(hours=3), state="archived-on-accept"),
            agent_row("worker-2", idle=timedelta(hours=3), role="worker-new"),
            agent_row("qa-2", idle=timedelta(hours=3), role="qa"),
            agent_row("reviewer-1", idle=timedelta(hours=3), role="reviewer"),
        ]
        agents = agents_with(lambda d: d["agents"].extend([
            {"id": writer, "parentId": "foreman-1", "active": True, "archived": False,
             "folderPaths": ["/synthetic/repo/wt-lead"]},
            {"id": "worker-2", "parentId": writer, "active": False, "archived": False,
             "folderPaths": ["/synthetic/repo/wt-worker"]},
            {"id": "qa-2", "parentId": writer, "active": False, "archived": False,
             "folderPaths": ["/synthetic/repo/wt-worker"]},
            {"id": "reviewer-1", "parentId": writer, "active": False, "archived": False,
             "folderPaths": ["/synthetic/repo/wt-worker"]},
        ]))
        report = run(rows, lead=writer, agents=agents, lead_in_ledger=writer)
        self.assertEqual(report["status"], "ok", report)
        self.assertEqual(report["counts"]["archive_due"], 3)

    def test_unrecorded_writer_and_missing_caller_are_refused(self):
        self.assertEqual(run([], lead_in_ledger=None)["reason_code"], "lead_unrecorded")
        self.assertEqual(run([], lead=None)["reason_code"], "lead_agent_id_missing")

    def test_execution_id_is_a_recorded_writer_too(self):
        # A lead swap that updated lead.agent_id but not execution.traycer_agent_id.
        report = run([agent_row(idle=timedelta(hours=3))], execution_id="previous-lead")
        self.assertEqual(report["reason_code"], "two_active_writers")
        self.assertIsNone(report["counts"])
        # Both ids updated to the caller: the reconcile runs.
        self.assertEqual(run([agent_row(idle=timedelta(hours=3))], execution_id=LEAD)["status"], "ok")
        # Only the execution id recorded, and it is the caller.
        self.assertEqual(run([], lead_in_ledger=None, execution_id=LEAD)["status"], "ok")


class IdleNeverDoneTest(unittest.TestCase):
    """SC-7 rejected-idle-inferred-done: idle is archived (reversible), never done."""

    FIXTURE = json.loads((SC7 / "rejected-idle-inferred-done.json").read_text(encoding="utf-8"))

    def test_fixture_idle_run_is_archived_not_done(self):
        source = self.FIXTURE["input"]
        self.assertEqual(self.FIXTURE["expected_outcome"], "reject")
        self.assertEqual(source["lifecycle"], "idle")
        agent_id = source["session"]
        agents = agents_with(lambda d: d["agents"].append(
            {"id": agent_id, "parentId": LEAD, "active": False, "archived": False,
             "folderPaths": ["/synthetic/repo/wt-worker"]}))
        report = run([agent_row(agent_id, idle=timedelta(hours=4), role=source["seat"])], agents=agents)
        item = finding_for(report, agent_id)
        self.assertEqual(item["finding"], "archive_due")
        self.assertTrue(item["reversible"])
        self.assertEqual(item["next_state"], "archived-idle-timeout")
        self.assertNotIn(item["next_state"], NEVER_STATES)
        self.assertNotIn(source["next_action"], json.dumps(report))
        for value in json.dumps(report).replace('"', " ").split():
            self.assertNotIn(value.strip(",:{}[]"), {"inferred_complete", "delete", "deletable"})


class LegacyRowTest(unittest.TestCase):
    """A #73-era inventory row without the #112 fields still reads, and never
    comes out archive_due (additive schema; absence is unknown, not none)."""

    def legacy_row(self, **extra):
        row = {"id": "worker-1", "kind": "agent", "pr": 12, "role": "worker-new",
               "created_at": "2026-11-06T08:00:00Z", "state": "active"}
        row.update(extra)
        return row

    def test_row_without_either_field_is_blocked(self):
        report = run([self.legacy_row()])
        self.assertEqual(report["status"], "ok", report)
        item = finding_for(report, "worker-1")
        self.assertEqual((item["finding"], item["reason"]), ("blocked", "open_requests_unknown"))

    def test_row_without_last_exchange_is_idle_unknown(self):
        report = run([self.legacy_row(open_requests=[])])
        item = finding_for(report, "worker-1")
        self.assertEqual((item["finding"], item["reason"]), ("blocked", "idle_unknown"))

    def test_row_without_open_requests_but_long_idle_is_blocked(self):
        report = run([self.legacy_row(last_exchange_at=_iso(NOW - timedelta(days=3)))])
        item = finding_for(report, "worker-1")
        self.assertEqual((item["finding"], item["reason"]), ("blocked", "open_requests_unknown"))
        self.assertEqual(report["counts"]["archive_due"], 0)

    def test_template_inventory_reads(self):
        template = (ROOT / "skills" / "dev" / "templates" / "DEV_STATE_TEMPLATE.md").read_text(encoding="utf-8")
        self.assertEqual(MODULE.load_inventory(template), [])
        self.assertIn("archived-idle-timeout", template)
        for state in MODULE.STATES["agent"]:
            self.assertIn(f"`{state}`", template, state)


class ClaudeNativeTest(unittest.TestCase):
    def test_agent_count_is_not_applicable(self):
        report = run([agent_row(idle=timedelta(hours=3))], backend="claude-native", agents=None, lead=None,
                     lead_in_ledger=None)
        self.assertEqual(report["status"], "ok", report)
        self.assertEqual(report["counts"]["agents"], "not_applicable")
        self.assertEqual(finding_for(report, "worker-1")["finding"], "not_applicable")
        self.assertFalse([f for f in report["findings"] if f["finding"] == "not_mine"])
        self.assertFalse([f for f in report["findings"] if "proposed_action" in f])


class MainTest(unittest.TestCase):
    def test_exit_codes_and_json_output(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dev-state.md"
            path.write_text(ledger([agent_row(idle=timedelta(hours=3))]), encoding="utf-8")
            base = ["--dev-state", str(path), "--repo-dir", str(REPO_DIR), "--backend", "traycer",
                    "--lead-agent-id", LEAD, "--now", _iso(NOW),
                    "--agents-json", str(FIXTURES / "agent_list.json"),
                    "--worktrees-porcelain", str(FIXTURES / "worktrees.porcelain"),
                    "--shells-json", str(FIXTURES / "shells.json")]
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = MODULE.main(base)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.getvalue())["counts"]["archive_due"], 1)

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = MODULE.main(base[:-1] + [str(Path(tmp) / "absent.json")])
            self.assertEqual(code, 2)
            self.assertIsNone(json.loads(out.getvalue())["counts"])

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = MODULE.main(base[:9] + ["not-a-time"] + base[10:])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out.getvalue())["reason_code"], "clock_invalid")


# --- Fix batch 1 (de-251-1) regression tests -------------------------------
# Each fails at 6597e52: the reconcile either reported `ok` from unknown data
# or raised a traceback.


def envelope(**outer):
    """The fixture envelope with outer keys replaced or added."""
    data = copy.deepcopy(AGENTS)
    data.update(outer)
    return data


def assert_unavailable(case, report, reason_code):
    case.assertEqual(report["status"], "unavailable", report)
    case.assertEqual(report["reason_code"], reason_code, report)
    case.assertIsNone(report["counts"])
    case.assertEqual(report["findings"], [])


def main_report(argv):
    """Run main() and return (exit code, parsed JSON). A traceback fails the caller's test."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = MODULE.main(argv)
    return code, json.loads(out.getvalue())


def base_argv(ledger_path, *extra):
    return ["--dev-state", str(ledger_path), "--repo-dir", str(REPO_DIR), "--backend", "traycer",
            "--lead-agent-id", LEAD, "--now", _iso(NOW), *extra]


class EnvelopeStatusTest(unittest.TestCase):
    """B1: envelope metadata is checked at the outer and the data level."""

    ROWS = [agent_row(idle=timedelta(hours=3))]

    def test_outer_error_status(self):
        assert_unavailable(self, run(self.ROWS, agents=envelope(status="error")), "listing_error")

    def test_outer_ok_false_and_error_field(self):
        assert_unavailable(self, run(self.ROWS, agents=envelope(ok=False)), "listing_error")
        assert_unavailable(self, run(self.ROWS, agents=envelope(error="rate limited")), "listing_error")

    def test_outer_partial_and_pagination(self):
        for key, value in (("partial", True), ("hasMore", True), ("nextOffset", 200),
                           ("next_page_token", "abc"), ("nextCursor", "c1")):
            with self.subTest(key=key):
                assert_unavailable(self, run(self.ROWS, agents=envelope(**{key: value})), "listing_partial")

    def test_data_level_status_and_markers(self):
        assert_unavailable(self, run(self.ROWS, agents=agents_with(lambda d: d.update(status="error"))),
                           "listing_error")
        assert_unavailable(self, run(self.ROWS, agents=agents_with(lambda d: d.update(partial=True))),
                           "listing_partial")
        assert_unavailable(self, run(self.ROWS, agents=agents_with(lambda d: d.update(nextCursor="c2"))),
                           "listing_partial")

    def test_flat_error_object(self):
        flat = {"status": "error", "agents": copy.deepcopy(AGENTS["data"]["agents"])}
        assert_unavailable(self, run(self.ROWS, agents=flat), "listing_error")

    def test_flat_ok_object_is_accepted(self):
        flat = {"agents": copy.deepcopy(AGENTS["data"]["agents"])}
        self.assertEqual(run(self.ROWS, agents=flat)["status"], "ok")

    def test_agents_json_path_checks_the_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "dev-state.md"
            ledger_path.write_text(ledger(self.ROWS), encoding="utf-8")
            agents_path = Path(tmp) / "agents.json"
            agents_path.write_text(json.dumps(envelope(hasMore=True)), encoding="utf-8")
            code, report = main_report(base_argv(
                ledger_path, "--agents-json", str(agents_path),
                "--worktrees-porcelain", str(FIXTURES / "worktrees.porcelain")))
            self.assertEqual(code, 2)
            assert_unavailable(self, report, "listing_partial")

    def test_live_path_checks_the_envelope(self):
        """Only subprocess.run is mocked; the script reads the full envelope itself."""
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "dev-state.md"
            ledger_path.write_text(ledger(self.ROWS), encoding="utf-8")
            argv = base_argv(ledger_path, "--worktrees-porcelain", str(FIXTURES / "worktrees.porcelain"))
            cases = (
                (envelope(hasMore=True), "listing_partial"),
                (agents_with(lambda d: d.update(next_page_token="t")), "listing_partial"),
                (envelope(status="error"), "listing_error"),
            )
            for payload, reason in cases:
                done = subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(payload), stderr="")
                with mock.patch("subprocess.run", return_value=done) as patched:
                    code, report = main_report(argv)
                self.assertEqual(code, 2)
                assert_unavailable(self, report, reason)
                self.assertEqual(patched.call_args.args[0][-3:], ["agent", "list", "--json"])
            done = subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(AGENTS), stderr="")
            with mock.patch("subprocess.run", return_value=done):
                code, report = main_report(argv)
            self.assertEqual(report["status"], "ok", report)
            self.assertEqual(finding_for(report, "worker-1")["finding"], "archive_due")


class EmptyOrLeadlessListingTest(unittest.TestCase):
    """QA M2: an empty or lead-less listing never turns live rows into target_gone."""

    def test_empty_agents(self):
        report = run([agent_row(idle=timedelta(hours=3))], agents=agents_with(lambda d: d.update(agents=[])))
        assert_unavailable(self, report, "listing_partial")

    def test_lead_missing_from_listing(self):
        agents = agents_with(lambda d: d.update(agents=[a for a in d["agents"] if a["id"] != LEAD]))
        assert_unavailable(self, run([agent_row(idle=timedelta(hours=3))], agents=agents), "listing_partial")


class DuplicateIdTest(unittest.TestCase):
    """B2: a duplicate id in any listing is unavailable."""

    def test_duplicate_agent_id(self):
        agents = agents_with(lambda d: d["agents"].append(copy.deepcopy(d["agents"][1])))
        assert_unavailable(self, run([agent_row(idle=timedelta(hours=3))], agents=agents), "listing_duplicate_id")

    def test_duplicate_shell_id(self):
        row = {"id": "shell:host-1:dev-server", "kind": "shell", "pr": None, "role": None,
               "created_at": "2026-11-06T08:00:00Z", "state": "running", "shell_id": "dev-server"}
        shells = {"shells": [{"id": "dev-server", "status": "running"}, {"id": "dev-server", "status": "exited"}]}
        assert_unavailable(self, run([row], shells=shells), "listing_duplicate_id")

    def test_duplicate_worktree_path(self):
        assert_unavailable(self, run([], worktrees=WORKTREES + [dict(WORKTREES[1])]), "listing_duplicate_id")


class RecoveryMalformedTest(unittest.TestCase):
    """B3: malformed goal_run recovery records are unavailable, never "none"."""

    ROWS = [agent_row(idle=timedelta(hours=3))]

    def check(self, goal_run):
        assert_unavailable(self, run(self.ROWS, goal_run=goal_run), "recovery_malformed")

    def test_scalar_children(self):
        self.check(["goal_run:", "  obligations:", "    children: worker-1"])

    def test_non_map_obligations_and_missing_children(self):
        self.check(["goal_run:", "  obligations: pending"])
        self.check(["goal_run:", "  obligations:", "    worker_count: 1"])

    def test_non_string_child_entry(self):
        self.check(["goal_run:", "  obligations:", "    children:", "      - id: worker-1"])

    def test_custody_without_identity_fields(self):
        self.check(["goal_run:", "  custody:", "    claim: successor"])
        self.check(["goal_run:", "  custody:", "    prior_session_id: worker-1"])

    def test_custody_wrong_type(self):
        self.check(["goal_run:", "  custody:", "    prior_session_id: 7", "    current_session_id: lead-1"])

    def test_scalar_goal_run(self):
        self.check(["goal_run: armed"])

    def test_absent_records_count_as_none(self):
        self.assertEqual(run(self.ROWS, goal_run=["goal_run: null"])["status"], "ok")
        self.assertEqual(run(self.ROWS, goal_run=["goal_run:", "  run_id: r-1"])["status"], "ok")


class WriterMalformedTest(unittest.TestCase):
    """B4: writer ids are null or non-blank strings; anything else is unavailable."""

    def test_wrong_types(self):
        for value in (123, ""):
            with self.subTest(value=value):
                assert_unavailable(self, run([], lead_in_ledger=value), "writer_malformed")
                assert_unavailable(self, run([], execution_id=value), "writer_malformed")

    def test_list_and_map_values(self):
        base = ledger([])
        as_list = base.replace("  agent_id: \"lead-1\"", "  agent_id:\n    - lead-1")
        as_map = base.replace("  traycer_agent_id: null", "  traycer_agent_id:\n    id: lead-1")
        for text in (as_list, as_map):
            assert_unavailable(self, run([], text=text), "writer_malformed")

    def test_differing_string_is_still_two_writers(self):
        self.assertEqual(run([], execution_id="other-lead")["reason_code"], "two_active_writers")


class TypeAndEncodingTest(unittest.TestCase):
    """B5 + QA M1: wrong types and non-UTF-8 never reach a membership test or a traceback."""

    def test_unhashable_kind_and_state(self):
        base = ledger([agent_row(idle=timedelta(hours=3))])
        for old, new in (('    kind: "agent"', "    kind:\n      - agent"),
                         ('    state: "active"', "    state:\n      - active")):
            text = base.replace(old, new)
            self.assertNotEqual(text, base)
            assert_unavailable(self, run([], text=text), "inventory_malformed")

    def test_wrong_scalar_types(self):
        for extra in ({"pr": "twelve"}, {"role": 5}, {"id": 42}):
            with self.subTest(extra=extra):
                assert_unavailable(self, run([agent_row(idle=timedelta(hours=3), **extra)]), "inventory_malformed")

    def test_listing_field_types(self):
        for mutate in (lambda a: a.update(parentId=7), lambda a: a.update(folderPaths=[1]), lambda a: a.update(id=9)):
            agents = agents_with(lambda d, m=mutate: m(d["agents"][1]))
            assert_unavailable(self, run([agent_row(idle=timedelta(hours=3))], agents=agents), "listing_partial")

    def test_non_utf8_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "dev-state.md"
            good.write_text(ledger([agent_row(idle=timedelta(hours=3))]), encoding="utf-8")
            bad = Path(tmp) / "bad.bin"
            bad.write_bytes(b"\xff\xfe\x00garbage\x80")
            base = {"--dev-state": str(good), "--agents-json": str(FIXTURES / "agent_list.json"),
                    "--worktrees-porcelain": str(FIXTURES / "worktrees.porcelain"),
                    "--shells-json": str(FIXTURES / "shells.json")}
            for flag in base:
                with self.subTest(flag=flag):
                    values = dict(base, **{flag: str(bad)})
                    argv = ["--repo-dir", str(REPO_DIR), "--backend", "traycer", "--lead-agent-id", LEAD,
                            "--now", _iso(NOW)]
                    for key, value in values.items():
                        argv += [key, value]
                    code, report = main_report(argv)
                    self.assertEqual(code, 2)
                    assert_unavailable(self, report, "input_unreadable")


class MainNeverTracebacksTest(unittest.TestCase):
    """B5: main() prints parseable unavailable JSON with exit 2 on garbage."""

    def call(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = MODULE.main(argv)
        return code, json.loads(out.getvalue())

    def test_garbage_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dev-state.md"
            path.write_text("---\nlead: [unclosed\ninventory: {\n---\n", encoding="utf-8")
            code, report = self.call(["--dev-state", str(path), "--backend", "traycer", "--lead-agent-id", LEAD,
                                      "--worktrees-porcelain", str(FIXTURES / "worktrees.porcelain"),
                                      "--agents-json", str(FIXTURES / "agent_list.json")])
        self.assertEqual(code, 2)
        self.assertEqual(report["status"], "unavailable")
        self.assertIsNone(report["counts"])

    def test_bad_arguments(self):
        code, report = self.call(["--backend", "bogus"])
        self.assertEqual((code, report["reason_code"]), (2, "usage_error"))
        code, report = self.call(["--no-such-flag"])
        self.assertEqual((code, report["reason_code"]), (2, "usage_error"))

    def test_unforeseen_exception(self):
        with mock.patch.object(MODULE, "build_report", side_effect=RuntimeError("boom")):
            code, report = self.call(["--backend", "traycer"])
        self.assertEqual((code, report["reason_code"]), (2, "internal_error"))
        with mock.patch.object(MODULE, "load_inventory", side_effect=KeyError("x")):
            report = run([])
        self.assertEqual(report["reason_code"], "internal_error")


class OwnerMismatchTest(unittest.TestCase):
    """QA L1: a listed parent that is not the lead, or folders outside the project, block."""

    def test_foreign_parent_blocks(self):
        agents = agents_with(lambda d: d["agents"][1].update(parentId="someone-else"))
        item = finding_for(run([agent_row(idle=timedelta(hours=3))], agents=agents), "worker-1")
        self.assertEqual((item["finding"], item["reason"]), ("blocked", "listing_owner_mismatch"))

    def test_folders_outside_project_block(self):
        agents = agents_with(lambda d: d["agents"][1].update(folderPaths=["/synthetic/other-repo"]))
        item = finding_for(run([agent_row(idle=timedelta(hours=3))], agents=agents), "worker-1")
        self.assertEqual((item["finding"], item["reason"]), ("blocked", "listing_owner_mismatch"))

    def test_null_parent_in_project_is_still_archivable(self):
        agents = agents_with(lambda d: d["agents"][1].update(parentId=None))
        self.assertEqual(finding_for(run([agent_row(idle=timedelta(hours=3))], agents=agents),
                                     "worker-1")["finding"], "archive_due")


class ShellMatchTest(unittest.TestCase):
    """QA L2: without shell_id only the full row id matches; a miss is blocked, not gone."""

    def row(self, **extra):
        row = {"id": "shell:host-1:dev-server", "kind": "shell", "pr": None, "role": None,
               "created_at": "2026-11-06T08:00:00Z", "state": "running"}
        row.update(extra)
        return row

    def test_trailing_segment_never_matches(self):
        item = finding_for(run([self.row()]), "shell:host-1:dev-server")
        self.assertEqual((item["finding"], item["reason"]), ("blocked", "shell_unmatched"))

    def test_full_id_matches(self):
        shells = {"shells": [{"id": "shell:host-1:dev-server", "status": "running"}]}
        self.assertEqual(finding_for(run([self.row()], shells=shells), "shell:host-1:dev-server")["finding"],
                         "tracked")


class OpenRequestsMalformedTest(unittest.TestCase):
    """QA L6: an entry without a non-blank id and what blocks the row; "None" never prints."""

    def test_malformed_entries_block(self):
        for entry in ({"what": "no id"}, {"id": "r-1"}, {"id": "r-1", "what": ""}, {"id": "", "what": "x"}):
            with self.subTest(entry=entry):
                report = run([agent_row(idle=timedelta(hours=3), open_requests=[entry])])
                item = finding_for(report, "worker-1")
                self.assertEqual((item["finding"], item["reason"]), ("blocked", "open_requests_malformed"))
                self.assertNotIn("None", json.dumps(item))

    def test_non_list_value_blocks(self):
        text = ledger([agent_row(idle=timedelta(hours=3), open_requests=None)]).replace(
            '    state: "active"', '    state: "active"\n    open_requests: "resp-9"')
        item = finding_for(run([], text=text), "worker-1")
        self.assertEqual((item["finding"], item["reason"]), ("blocked", "open_requests_malformed"))


# --- Fix batch 2 (de-251-1) regression tests -------------------------------
# Each fails at 883b7ca.


class OuterTotalTest(unittest.TestCase):
    """Residual B1: a total declared at the envelope level must match the rows."""

    ROWS = [agent_row(idle=timedelta(hours=3))]
    RECEIVED = len(AGENTS["data"]["agents"])

    def ledger_file(self, tmp):
        path = Path(tmp) / "dev-state.md"
        path.write_text(ledger(self.ROWS), encoding="utf-8")
        return path

    def test_outer_total_mismatch_saved_path(self):
        for key in ("total", "count", "totalCount"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                agents_path = Path(tmp) / "agents.json"
                agents_path.write_text(json.dumps(envelope(**{key: self.RECEIVED + 1})), encoding="utf-8")
                code, report = main_report(base_argv(
                    self.ledger_file(tmp), "--agents-json", str(agents_path),
                    "--worktrees-porcelain", str(FIXTURES / "worktrees.porcelain")))
                self.assertEqual(code, 2)
                assert_unavailable(self, report, "listing_partial")

    def test_outer_total_mismatch_live_path(self):
        """Only subprocess.run is mocked."""
        with tempfile.TemporaryDirectory() as tmp:
            argv = base_argv(self.ledger_file(tmp), "--worktrees-porcelain", str(FIXTURES / "worktrees.porcelain"))
            done = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(envelope(total=self.RECEIVED + 1)), stderr="")
            with mock.patch("subprocess.run", return_value=done):
                code, report = main_report(argv)
        self.assertEqual(code, 2)
        assert_unavailable(self, report, "listing_partial")

    def test_outer_inner_total_conflict(self):
        both = envelope(total=self.RECEIVED + 1)
        both["data"]["total"] = self.RECEIVED
        assert_unavailable(self, run(self.ROWS, agents=both), "listing_partial")
        reverse = envelope(total=self.RECEIVED)
        reverse["data"]["total"] = self.RECEIVED + 1
        assert_unavailable(self, run(self.ROWS, agents=reverse), "listing_partial")

    def test_matching_totals_are_accepted(self):
        both = envelope(total=self.RECEIVED)
        both["data"]["count"] = self.RECEIVED
        self.assertEqual(run(self.ROWS, agents=both)["status"], "ok")


class BackendTypeTest(unittest.TestCase):
    """Advisory: a non-string backend is unavailable, never a TypeError."""

    def test_unhashable_backend(self):
        for backend in ([], {}, 3):
            with self.subTest(backend=backend):
                report = run([], backend=backend)
                assert_unavailable(self, report, "backend_incomplete")
                self.assertIsNone(report["backend"])


if __name__ == "__main__":
    unittest.main()
