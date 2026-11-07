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
import sys
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


def ledger(rows, *, lead=LEAD, goal_run=None, inventory=True):
    """Write a schema-v2 ledger frontmatter holding `rows` as inventory."""
    out = ["---", "schema_version: 2", "lead:", f"  agent_id: {_scalar(lead)}"]
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
        lead_in_ledger=LEAD, **kw):
    """`lead` is the calling agent; `lead_in_ledger` is the ledger's recorded writer."""
    text = kw.pop("text", None) or ledger(rows, lead=lead_in_ledger, **kw)
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
            "_git_worktree_list", "_parse_porcelain", "_run_traycer_cli",
        ):
            self.assertTrue(callable(getattr(workspace_debt, name, None)), f"workspace_debt.{name} disappeared")
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
             "created_at": "2026-11-06T08:00:00Z", "state": "running"},
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
             "created_at": "2026-11-06T08:00:00Z", "state": "running"},
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
        self.assertUnavailable(run([agent_row(open_requests=[{"what": "no id"}])]), "inventory_malformed")

    def test_unknown_backend(self):
        self.assertUnavailable(run([], backend="incomplete"), "backend_incomplete")

    def test_cli_timeout_and_nonzero_exit(self):
        args = MODULE.argparse.Namespace(
            dev_state=str(FIXTURES / "missing-on-purpose.md"), repo_dir=str(REPO_DIR), backend="traycer",
            lead_agent_id=LEAD, now=_iso(NOW), agents_json=None,
            worktrees_porcelain=str(FIXTURES / "worktrees.porcelain"), shells_json=None,
        )
        # Ledger first: an unreadable ledger is itself unavailable.
        self.assertUnavailable(MODULE.build_report(args), "ledger_unreadable")

        with self._ledger_file([agent_row(idle=timedelta(hours=3))]) as path:
            args.dev_state = path
            for message in ("agent list --json timed out after 30s", "agent list --json exit 1: boom"):
                with mock.patch.object(MODULE, "_run_traycer_cli", side_effect=MODULE.ScriptError(message)):
                    self.assertUnavailable(MODULE.build_report(args), "listing_error")
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
            agent_row("qa-1", idle=timedelta(hours=3), role="qa"),
            agent_row("reviewer-1", idle=timedelta(hours=3), role="reviewer"),
        ]
        agents = agents_with(lambda d: d["agents"].extend([
            {"id": "worker-2", "parentId": writer, "active": False, "archived": False,
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


if __name__ == "__main__":
    unittest.main()
