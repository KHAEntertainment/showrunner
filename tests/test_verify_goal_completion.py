"""Offline checks for the goal completion verifier (#195 lane L195-1, GV core).

Each acceptance criterion and each required verification case of SDP section 6
(l.352) is a named test that asserts behavior. The fake runner stands in for
``gh``; no test reaches the network or starts a process. SC-3 fixtures under
docs/v2.2/contracts/fixtures/sc-3/ are read only.
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "dev" / "scripts"
MODULE_PATH = SCRIPTS / "verify_goal_completion.py"
FIXTURES = ROOT / "tests" / "fixtures" / "goal_completion"
SC3 = ROOT / "docs" / "v2.2" / "contracts" / "fixtures" / "sc-3"
TEMPLATE = ROOT / "skills" / "dev" / "templates" / "DEV_STATE_TEMPLATE.md"


def _load_module():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("verify_goal_completion", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gv = _load_module()
import dev_state  # noqa: E402  (loaded by the module above)
import goal_run  # noqa: E402

REPO = "OWNER/synthetic-repo"
ISSUE = "OWNER/synthetic-repo#1"
PR = "OWNER/synthetic-repo#10"
OWNER = "synthetic-owner"
HEAD = "4e683b4aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
MERGE = "d44f1e0ccccccccccccccccccccccccccccccccc"
NOW = datetime(2099, 1, 4, tzinfo=timezone.utc)
ISSUE_EP = f"repos/{REPO}/issues/1"
PR_EP = f"repos/{REPO}/pulls/10"
COMPARE_EP = f"repos/{REPO}/compare/main...{MERGE}"
REVERT_EP = f"repos/{REPO}/commits?sha=main&since=2099-01-02T00:10:00Z&per_page=100"
REVIEW_EP = f"repos/{REPO}/pulls/10/reviews/2201"
COMMENTS_EP = f"repos/{REPO}/issues/1/comments?per_page=100"

# Flags that turn ``gh api`` into a write, pinned here (lead binding note 3).
FORBIDDEN_GH_FLAGS = ("-f", "-F", "--field", "--raw-field", "--input", "-X")
FORBIDDEN_METHODS = ("POST", "PATCH", "PUT", "DELETE")
# Words that would make an argv a tracker or repository write.
FORBIDDEN_WORDS = FORBIDDEN_METHODS + ("merge", "close", "reopen", "edit", "comment", "create",
                                       "push", "git", "issue", "pr")

BASE_LEDGER = json.loads((FIXTURES / "base_ledger.json").read_text(encoding="utf-8"))
BASE_GH = json.loads((FIXTURES / "base_github.json").read_text(encoding="utf-8"))
BASE_LEDGER.pop("_comment")
BASE_GH.pop("_comment")

ALL_ARGV = []


# --- Ledger rendering (the YAML subset the lead writes) -----------------------


def _emit_scalar(value):
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value)
    plain = (text and text == text.strip() and text[0] not in "-\"'[{|>#&*!"
             and ": " not in text and " #" not in text and not text.endswith(":"))
    if plain:
        try:
            if dev_state._goal_scalar(text, "x", 0) == text:
                return text
        except dev_state.GoalRunError:
            pass
    assert '"' not in text, text
    return f'"{text}"'


def _emit(value, indent):
    pad = " " * indent
    lines = []
    if isinstance(value, dict):
        for key, item in value.items():
            name = key if re.match(r"^[A-Za-z0-9_][A-Za-z0-9_.\-/@]*$", key) else f'"{key}"'
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{pad}{name}:")
                lines += _emit(item, indent + 2)
            elif isinstance(item, dict):
                lines.append(f"{pad}{name}: {{}}")
            elif isinstance(item, list):
                lines.append(f"{pad}{name}: []")
            else:
                lines.append(f"{pad}{name}: {_emit_scalar(item)}")
        return lines
    for item in value:
        if isinstance(item, dict) and item:
            sub = _emit(item, indent + 2)
            sub[0] = f"{pad}- {sub[0].lstrip()}"
            lines += sub
        else:
            assert not isinstance(item, (dict, list)), item
            lines.append(f"{pad}- {_emit_scalar(item)}")
    return lines


def render(data):
    return "---\n" + "\n".join(_emit(data, 0)) + "\n---\n\n# /dev Recovery Log\n"


# --- Fake runner ------------------------------------------------------------------


class FakeRunner:
    """Answers pinned reads from a response map; never runs anything."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        self.unknown = []

    def __call__(self, argv):
        argv = list(argv)
        self.calls.append(argv)
        ALL_ARGV.append(argv)
        endpoint = argv[-1]
        if endpoint not in self.responses:
            self.unknown.append(endpoint)
            return 1, "", "HTTP 404: Not Found (fake runner has no response)"
        value = self.responses[endpoint]
        if isinstance(value, Failing):
            return value.next()
        return 0, json.dumps(value), ""

    def count(self, endpoint):
        return sum(1 for argv in self.calls if argv[-1] == endpoint)


class Failing:
    """A scripted sequence of (rc, stdout, stderr), then success with ``value``."""

    def __init__(self, failures, value=None, exc=None):
        self.failures = list(failures)
        self.value = value
        self.exc = exc

    def next(self):
        if self.failures:
            item = self.failures.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        return 0, json.dumps(self.value), ""


def scenario(mutate_ledger=None, mutate_gh=None, **kwargs):
    data = copy.deepcopy(BASE_LEDGER)
    responses = copy.deepcopy(BASE_GH)
    if mutate_ledger:
        mutate_ledger(data)
    if mutate_gh:
        mutate_gh(responses)
    runner = FakeRunner(responses)
    sleeps = []
    kwargs.setdefault("owner_account", OWNER)
    kwargs.setdefault("now", NOW)
    result = gv.evaluate(render(data), runner=runner, sleep=sleeps.append, **kwargs)
    return result, runner, sleeps


def codes(result, cls=None):
    return {r["code"] for r in result.record.get("reason_codes", [])
            if r["blocking"] and (cls is None or r["class"] == cls)}


def advisory(result):
    return {r["code"] for r in result.record.get("reason_codes", []) if not r["blocking"]}


def line(result, criterion):
    return next(item for item in result.record["criteria"] if item["id"] == criterion)


def pr(data):
    return data["pull_requests"][0]


def pm(data):
    return pr(data)["post_merge"][0]


def parent(data):
    return data["parent_acceptance"][0]


def make_verbatim(data):
    entry = pm(data)
    entry.update({"tested_vs_merged": "same", "action": "applies_verbatim",
                  "gate_result": "applies_verbatim"})
    entry.pop("run")
    # Fixture-only (fix batch 1): a verbatim merge has no rerun, so its proof is the head run 123.
    pr(data)["ci_runs"] = [r for r in pr(data)["ci_runs"] if r["run"] != 130]
    for item in entry["criteria"] + entry["checks"]:
        if item["id"] in ("AC-1@9f3c", "build"):
            item.update(evidence_ref="run 123 attempt 1", basis="reused",
                        justification="merged tree equals tested tree")


def _set(mapping, **values):
    mapping.update(values)


LANE_COMMENT_EP = f"repos/{REPO}/issues/comments/991"
LANE_COMMENT_URL = "https://github.com/OWNER/synthetic-repo/pull/10#issuecomment-991"


def internal_lane(data):
    pr(data)["criteria"][1]["evaluator"]["id"] = "reviewer-lane-1"
    pr(data)["review"]["evidence_ref"] = {"comment": LANE_COMMENT_URL,
                                          "snapshot": "evidence/10/review-4e683b4.txt"}


def add_lane_comment(responses):
    responses[LANE_COMMENT_EP] = {"id": 991, "issue_url": f"https://api.github.com/repos/{REPO}/issues/10",
                                  "body": "Review lane report for 4e683b4: no material findings."}


def only_criteria(data, *ids):
    """Keep only the named criteria, consistently, in the parent, PR and post-merge sets."""
    parent(data)["criteria"] = [c for c in parent(data)["criteria"] if c["id"] in ids]
    pr(data)["criteria"] = [c for c in pr(data)["criteria"] if c["id"] in ids]
    pr(data)["criteria_ids"] = [c for c in pr(data)["criteria_ids"] if c in ids]
    pm(data)["criteria"] = [c for c in pm(data)["criteria"] if c["id"] in ids]


def local_fallback(data, check_env="host:mac-1", approved=True):
    run = {"run": "local-7", "job": "build", "attempt": 1, "executor": "host:mac-1",
           "definition_ref": {"ref": ".github/workflows/ci.yml#build", "rev": "2ab2b59"},
           "tested_subject": {"sha": "d44f1e0", "kind": "head"}, "environment": "host:mac-1",
           "conclusion": "success", "observed_at": "2099-01-02T00:25:00Z"}
    if approved:
        run["fallback_approved_by"] = OWNER
    pr(data)["ci_runs"] = [r for r in pr(data)["ci_runs"] if r["run"] != 130] + [run]
    pm(data)["run"] = {k: run[k] for k in ("run", "job", "attempt", "tested_subject", "conclusion")}
    pm(data)["run"].update({k: run[k] for k in ("executor", "fallback_approved_by") if k in run})
    for item in pm(data)["criteria"] + pm(data)["checks"]:
        if item["id"] in ("AC-1@9f3c", "build"):
            item["evidence_ref"] = "run local-7 attempt 1"
    pr(data)["checks"][0].update(environment=check_env, executor="host:mac-1")


# --- AC1: packaging and mutation boundary -------------------------------------


class TestPackagingBoundary(unittest.TestCase):
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))

    def _constants(self):
        docstrings = {id(node.value) for node in ast.walk(self.tree)
                      if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)}
        return [node for node in ast.walk(self.tree) if isinstance(node, ast.Constant)
                and isinstance(node.value, str) and id(node) not in docstrings]

    def test_ac1_imports_are_stdlib_or_sibling_payload_modules(self):
        allowed_siblings = {path.stem for path in SCRIPTS.glob("*.py")}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            for name in names:
                self.assertTrue(name in sys.stdlib_module_names or name in allowed_siblings or name == "__future__",
                                f"non-stdlib, non-sibling import: {name}")

    def test_ac1_no_file_writes_and_no_process_spawn_outside_the_runner(self):
        forbidden_attrs = {"write_text", "write_bytes", "unlink", "rmdir", "mkdir", "rename",
                           "replace_file", "chmod", "remove", "makedirs", "rmtree", "system",
                           "popen", "Popen", "call", "check_call", "check_output", "symlink_to",
                           "touch"}
        runner_def = next(n for n in self.tree.body if isinstance(n, ast.FunctionDef)
                          and n.name == "subprocess_runner")
        runner_nodes = {id(n) for n in ast.walk(runner_def)}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, forbidden_attrs, f"forbidden call .{node.attr}")
                if isinstance(node.value, ast.Name) and node.value.id == "subprocess":
                    self.assertIn(id(node), runner_nodes, "subprocess used outside subprocess_runner")
                if isinstance(node.value, ast.Name) and node.value.id in ("os", "shutil", "socket"):
                    self.fail(f"{node.value.id}.{node.attr} is not allowed")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
                mode = node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else None
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                        mode = kw.value.value
                self.assertEqual(mode, "r", "open() must be read-only with an explicit 'r' mode")

    def test_ac1_only_command_literal_is_the_gh_get_read_prefix(self):
        self.assertEqual(gv.GH_READ_PREFIX, ("gh", "api", "--method", "GET"))
        gh_literals = [node for node in ast.walk(self.tree) if isinstance(node, (ast.Tuple, ast.List))
                       and any(isinstance(e, ast.Constant) and e.value == "gh" for e in node.elts)]
        self.assertEqual(len(gh_literals), 1)
        values = [c.value for c in self._constants()]
        for flag in FORBIDDEN_GH_FLAGS:
            self.assertNotIn(flag, values, f"forbidden gh flag literal {flag}")
        for word in FORBIDDEN_METHODS + ("git",):
            self.assertNotIn(word, values, f"forbidden command word {word}")
        self.assertEqual(values.count("--method"), 1)
        self.assertEqual(values.count("GET"), 1)

    def test_ac1_every_argv_the_module_builds_is_a_pinned_get_read(self):
        # Drive every scenario family once, then pin every argv that was built.
        scenario()
        scenario(mutate_ledger=make_verbatim)
        scenario(mutate_gh=lambda g: g.update({ISSUE_EP: Failing([(1, "", "HTTP 500")] * 3)}))
        self.assertTrue(ALL_ARGV)
        for argv in ALL_ARGV:
            self.assertEqual(tuple(argv[:4]), gv.GH_READ_PREFIX, argv)
            self.assertTrue(gv.is_read_argv(argv), argv)
            for token in argv:
                self.assertNotIn(token, FORBIDDEN_GH_FLAGS, argv)
                self.assertNotIn(token, FORBIDDEN_WORDS, argv)
            self.assertLessEqual(set(argv[4:-1]), {"--paginate"}, argv)

    def test_ac1_read_shape_refuses_write_flags_and_methods(self):
        for flag in FORBIDDEN_GH_FLAGS:
            self.assertFalse(gv.is_read_argv(["gh", "api", "--method", "GET", flag, "x=1", "repos/O/r/issues/1"]))
        for method in ("POST", "PATCH", "PUT", "DELETE"):
            self.assertFalse(gv.is_read_argv(["gh", "api", "--method", method, "repos/O/r/issues/1"]))
        self.assertFalse(gv.is_read_argv(["gh", "issue", "close", "1"]))
        self.assertFalse(gv.is_read_argv(["git", "push"]))
        for bad in ("-f", "repos/O/r/issues/1 -X POST", "../etc", "https://x", ""):
            with self.assertRaises(ValueError):
                gv.build_gh_read(bad)

    def test_ac1_real_runner_refuses_a_write_before_spawning(self):
        with mock.patch.object(gv.subprocess, "run") as spawned:
            with self.assertRaises(ValueError):
                gv.subprocess_runner(["gh", "api", "--method", "POST", "repos/O/r/issues/1"])
            with self.assertRaises(ValueError):
                gv.subprocess_runner(["gh", "api", "--method", "GET", "-f", "state=closed", "repos/O/r/issues/1"])
        spawned.assert_not_called()


# --- AC2: one evaluator, reusing the sibling parsers ---------------------------


class TestReuse(unittest.TestCase):
    def test_ac2_reuses_dev_state_and_goal_run_parsers(self):
        with mock.patch.object(gv.dev_state, "parse_goal_run_block", wraps=dev_state.parse_goal_run_block) as block, \
                mock.patch.object(gv.goal_run, "arm", wraps=goal_run.arm) as arm, \
                mock.patch.object(gv.dev_state, "_goal_scalar", wraps=dev_state._goal_scalar) as scalar:
            result, _, _ = scenario()
        self.assertEqual(result.outcome, "verified")
        block.assert_called()
        arm.assert_called()
        scalar.assert_called()

    def test_coupling_private_sibling_symbols_gv_depends_on(self):
        # M3/ledger coupling: a rename upstream fails here, in GV's own suite.
        self.assertIsNone(dev_state._goal_scalar("null", "x", 1))
        self.assertEqual(dev_state._goal_scalar("AC-1@9f3c", "x", 1), "AC-1@9f3c")
        with self.assertRaises(dev_state.GoalRunError):
            dev_state._goal_scalar("[1, 2]", "x", 1)
        self.assertEqual(dev_state.GOAL_RUN_KEY, "goal_run")
        block = dev_state.parse_goal_run_block(render(BASE_LEDGER))
        self.assertEqual(block["repo"], REPO)
        self.assertTrue(goal_run._validate_plan_ref(BASE_LEDGER["goal_run"]["plan_ref"]).ok)
        self.assertEqual(goal_run.arm(dict(BASE_LEDGER["goal_run"], fixed_issues=[])).reason, "empty_issue_set")
        self.assertEqual(goal_run.parse_turn_end_marker("GOAL-COMPLETE: x", expected_source="y").reason,
                         "wrong_source")
        self.assertIn("fixed_issues", gv._ASSIGNMENT_KEYS)


# --- Second YAML block reader (pinned to the template's real shape) ------------


class TestBlockReader(unittest.TestCase):
    def test_block_reader_parses_template_example_and_at_sign_keys(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        example = re.search(r"Worked example \(the approved §2 records.*?```yaml\n(.*?)```", text, re.S).group(1)
        ledger = "---\n" + example + "---\n"
        prs = gv.read_block(ledger, "pull_requests")
        parents = gv.read_block(ledger, "parent_acceptance")
        self.assertEqual(prs[0]["number"], 23)
        self.assertEqual(prs[0]["ci_runs"][0]["tested_subject"]["kind"], "merge_ref")
        self.assertEqual(prs[0]["post_merge"][0]["criteria"][1]["evaluator"]["id"], "worker:9b2")
        self.assertEqual(prs[0]["integrated"]["history"][0]["withdrawn_at"], "2026-10-23T09:12:00Z")
        self.assertEqual(parents[0]["criteria_map"]["AC-1@9f3c"], "AC-1@b17e")
        self.assertEqual(parents[0]["amendment"]["changed"], ["AC-3"])
        self.assertEqual(gv.check_evidence_record(prs[0]), ("accept", []))
        self.assertEqual(gv.check_evidence_record(parents[0]), ("accept", []))

    def test_block_reader_round_trips_the_base_fixture(self):
        text = render(BASE_LEDGER)
        self.assertEqual(gv.read_block(text, "pull_requests"), BASE_LEDGER["pull_requests"])
        self.assertEqual(gv.read_block(text, "parent_acceptance"), BASE_LEDGER["parent_acceptance"])

    def test_block_reader_fails_closed_and_the_result_is_inconclusive(self):
        good = render(BASE_LEDGER)
        broken = good.replace("pull_requests:\n", "pull_requests:\n  - [flow, syntax]\n", 1)
        with self.assertRaises(gv.LedgerError):
            gv.read_block(broken, "pull_requests")
        for bad in ("pull_requests:\n\t- x\n", "pull_requests:\n  - a: |\n    text\n",
                    "pull_requests:\n  - a: 1\n    a: 2\n"):
            with self.assertRaises(gv.LedgerError):
                gv.read_block(f"---\n{bad}---\n", "pull_requests")
        runner = FakeRunner(copy.deepcopy(BASE_GH))
        result = gv.evaluate(broken, runner=runner, sleep=lambda s: None, owner_account=OWNER, now=NOW)
        self.assertEqual(result.outcome, "inconclusive")
        self.assertIn("ledger_block_unreadable", codes(result))
        self.assertIn("ledger:pull_requests", [u["read"] for u in result.record["unread_inputs"]])


# --- AC3: the result record ---------------------------------------------------------


class TestResultRecord(unittest.TestCase):
    def test_ac3_verified_record_carries_completion_result_v1(self):
        result, runner, _ = scenario(supersedes=["gv-prior"], consumer_context="lead-final",
                                     invoker={"role": "lead", "id": "lead-agent", "harness": "claude"})
        record = result.record
        self.assertEqual(result.kind, "result")
        self.assertEqual(record["outcome"], "verified")
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(runner.unknown, [])
        self.assertEqual(record["profile_version"], "completion-result-v1")
        self.assertEqual(record["run_id"], "synthetic-run-195")
        self.assertEqual(record["plan_ref"], BASE_LEDGER["goal_run"]["plan_ref"])
        self.assertEqual(record["goal"], {"repository": REPO, "fixed_issues": [ISSUE],
                                          "frozen_at": "2099-01-01T00:00:00Z"})
        self.assertEqual(record["evidence_profile"], "completion-evidence-v1")
        self.assertEqual(record["purpose"], "final")
        self.assertEqual(record["repository_facts"]["observed_at"], "2099-01-04T00:00:00Z")
        self.assertEqual(record["repository_facts"]["pull_requests"][0]["merge_sha"], MERGE)
        self.assertTrue(record["repository_facts"]["pull_requests"][0]["reachable_from_destination"])
        self.assertEqual(record["repository_facts"]["closed_issues"], [{"issue": ISSUE, "state": "closed"}])
        self.assertEqual(record["repository_facts"]["integrated_acceptance"]["record"], "parent_acceptance")
        self.assertEqual([c["state"] for c in record["criteria"]], ["met"] * 4)
        self.assertEqual(record["reason_codes"], [])
        self.assertEqual(record["producer"]["recorded_by"], "lead")
        self.assertEqual(record["producer"]["consumer_context"], "lead-final")
        self.assertTrue(record["producer"]["helper_revision"].startswith("sha256:"))
        self.assertEqual(record["supersedes"], ["gv-prior"])
        self.assertTrue(record["result_id"].startswith("gv-"))
        for item in record["consumed_inputs"]:
            self.assertTrue(item["reference"] and item["digest"].startswith("sha256:"))
            self.assertTrue(item["revision"] or item["recorded_at"])
        self.assertEqual(gv.read_result(record), ("accept", []))

    def test_ac3_readiness_returns_evidence_ready_never_verified(self):
        result, _, _ = scenario(purpose="readiness")
        self.assertEqual(result.outcome, "evidence_ready")
        self.assertEqual(result.exit_code, 4)
        opened, _, _ = scenario(purpose="readiness",
                                mutate_gh=lambda g: g[ISSUE_EP].update(state="open"))
        self.assertEqual(opened.outcome, "evidence_ready")
        self.assertIn("issue_open", advisory(opened))
        self.assertNotEqual(opened.exit_code, 0)
        failing, _, _ = scenario(purpose="readiness", mutate_ledger=lambda d: _set(pm(d), criteria_verdict="unmet"))
        self.assertEqual(failing.outcome, "not_ready")
        for outcome in (result, opened, failing):
            self.assertIn(outcome.outcome, gv.VOCABULARY["readiness"])
            self.assertNotEqual(outcome.outcome, "verified")
            self.assertEqual(gv.read_result(outcome.record)[0], "accept")

    def test_ac3_reader_rules_make_unusable_records_unusable(self):
        good, _, _ = scenario()
        record = good.record
        cases = {
            "unmet criterion under verified": lambda r: r["criteria"][0].update(state="unmet"),
            "blocking reason under verified": lambda r: r["reason_codes"].append(
                {"code": "x", "class": "inconclusive", "blocking": True}),
            "outcome outside vocabulary": lambda r: r.update(outcome="evidence_ready"),
            "readiness returning verified": lambda r: r.update(purpose="readiness"),
            "not recorded by the lead": lambda r: r["producer"].update(recorded_by="worker"),
            "consumed input without revision or time": lambda r: r["consumed_inputs"][0].update(
                revision=None, recorded_at=None),
            "facts without observed_at": lambda r: r["repository_facts"].pop("observed_at"),
            "met criterion without proof": lambda r: r["criteria"][0].update(accepted_proof=None),
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                broken = copy.deepcopy(record)
                mutate(broken)
                self.assertEqual(gv.read_result(broken)[0], "unusable", name)
        missing = copy.deepcopy(record)
        missing.pop("profile_version")
        self.assertEqual(gv.read_result(missing)[0], "unknown")
        missing["profile_version"] = "completion-result-v9"
        self.assertEqual(gv.read_result(missing)[0], "unknown")
        silent = copy.deepcopy(record)
        silent.update(outcome="inconclusive")
        self.assertEqual(gv.read_result(silent)[0], "unusable")

    def test_ac3_inconclusive_result_names_the_inputs_it_could_not_read(self):
        result, _, _ = scenario(mutate_gh=lambda g: g.pop(COMPARE_EP))
        self.assertEqual(result.outcome, "inconclusive")
        self.assertEqual([u["read"] for u in result.record["unread_inputs"]], [f"reachability:{PR}"])
        self.assertEqual(gv.read_result(result.record)[0], "accept")

    def test_ac3_reason_codes_name_affected_issues_prs_and_criteria(self):
        result, _, _ = scenario(mutate_ledger=lambda d: _set(pm(d)["criteria"][0], outcome="fail"))
        reason = next(r for r in result.record["reason_codes"] if r["code"] == "criterion_failed")
        self.assertEqual(reason["criteria"], ["AC-1@9f3c"])
        self.assertEqual(reason["prs"], [PR])
        opened, _, _ = scenario(mutate_gh=lambda g: g[ISSUE_EP].update(state="open"))
        reason = next(r for r in opened.record["reason_codes"] if r["code"] == "issue_not_closed")
        self.assertEqual(reason["issues"], [ISSUE])


# --- AC4: SDP section 6 required verification cases (l.352) ----------------------


class TestRequiredCases(unittest.TestCase):
    def assertOutcome(self, result, outcome, code=None):
        self.assertEqual(result.kind, "result", result.record)
        self.assertEqual(result.outcome, outcome, result.record.get("reason_codes"))
        if code is not None:
            self.assertIn(code, codes(result), result.record.get("reason_codes"))
        self.assertEqual(gv.read_result(result.record)[0], "accept", gv.read_result(result.record))

    def test_l352_passing_tree_equivalence(self):
        result, runner, _ = scenario(mutate_ledger=make_verbatim)
        self.assertOutcome(result, "verified")
        self.assertTrue(result.record["repository_facts"]["pull_requests"][0]["tree_equivalent"])
        self.assertEqual(runner.count(f"repos/{REPO}/commits/7a0b5d1"), 1)

    def test_l352_passing_merged_tree_rerun(self):
        result, _, _ = scenario()
        self.assertOutcome(result, "verified")
        self.assertEqual(line(result, "AC-1@9f3c")["accepted_proof"]["run"]["run"], 130)

    def test_l352_closed_issue_with_no_pr(self):
        def mutate(d):
            d["goal_run"]["fixed_issues"].append("OWNER/synthetic-repo#2")
        result, _, _ = scenario(mutate, lambda g: g.update(
            {f"repos/{REPO}/issues/2": {"number": 2, "state": "closed"}}))
        self.assertOutcome(result, "not_complete", "issue_without_pr")

    def test_l352_closed_issue_with_unrelated_pr(self):
        def mutate(d):
            pr(d)["issue"] = "OWNER/synthetic-repo#7"
            pr(d)["parent_ref"] = "OWNER/synthetic-repo#7"
            parent(d)["contributions"] = []
        result, runner, _ = scenario(mutate)
        self.assertOutcome(result, "not_complete", "issue_without_pr")
        self.assertEqual(runner.count(PR_EP), 0)

    def test_l352_wrong_merge_sha(self):
        result, _, _ = scenario(mutate_gh=lambda g: g[PR_EP].update(merge_commit_sha="9" * 40))
        self.assertOutcome(result, "not_complete", "merge_sha_mismatch")

    def test_l352_wrong_base(self):
        result, _, _ = scenario(mutate_gh=lambda g: g[PR_EP]["base"].update(ref="develop"))
        self.assertOutcome(result, "not_complete", "wrong_base")

    def test_l352_wrong_repository(self):
        result, _, _ = scenario(mutate_gh=lambda g: g[PR_EP]["base"]["repo"].update(full_name="OTHER/fork"))
        self.assertOutcome(result, "not_complete", "wrong_repository")

    def test_l352_absent_post_merge_result(self):
        result, _, _ = scenario(lambda d: _set(pr(d), post_merge=[]))
        self.assertOutcome(result, "inconclusive", "post_merge_missing")

    def test_l352_failed_post_merge_result(self):
        result, _, _ = scenario(lambda d: pm(d)["run"].update(conclusion="failure"))
        self.assertOutcome(result, "not_complete", "post_merge_failed")
        failed, _, _ = scenario(lambda d: _set(pm(d), gate_result="rerun_fail"))
        self.assertOutcome(failed, "not_complete", "post_merge_failed")

    def test_l352_criteria_verdict_unmet(self):
        result, _, _ = scenario(lambda d: _set(pm(d), criteria_verdict="unmet"))
        self.assertOutcome(result, "not_complete", "criteria_unmet")

    def test_l352_stale_criteria_revision(self):
        def mutate(d):
            parent(d)["criteria_ref"] = "sha256:b17e" + "0" * 60
            for item in parent(d)["criteria"]:
                item["id"] = item["id"].replace("@9f3c", "@b17e")

        def without_human(d):
            mutate(d)
            parent(d)["criteria"].pop(3)
        result, _, _ = scenario(without_human)
        # Fix batch 1 (B3): the PR record's criteria_ref now contradicts the parent's: not_complete.
        self.assertOutcome(result, "not_complete", "criteria_ref_mismatch")
        self.assertIn("criteria_revision_stale", codes(result))
        self.assertEqual(line(result, "AC-1@b17e")["state"], "inconclusive")
        # The human criterion's only /accept names the superseded revision.
        human, _, _ = scenario(mutate)
        self.assertOutcome(human, "not_complete", "awaiting_owner_acceptance")
        self.assertIn("criteria_revision_stale", codes(human))

    def test_l352_stale_source_revision(self):
        result, _, _ = scenario(approved_revision="sha256:" + "3" * 64)
        self.assertOutcome(result, "inconclusive", "source_revision_stale")
        mismatch, _, _ = scenario(lambda d: _set(d["goal_run"], approval_revision="sha256:" + "4" * 64))
        self.assertOutcome(mismatch, "inconclusive", "source_revision_mismatch")

    def test_l352_reopened_issue(self):
        result, _, _ = scenario(mutate_gh=lambda g: g[ISSUE_EP].update(state="open"))
        self.assertOutcome(result, "not_complete", "issue_not_closed")

    def test_l352_one_issue_multiple_prs_with_a_missing_record(self):
        def mutate(d):
            parent(d)["contributions"].append({"pr": 11, "issue": ISSUE, "criteria": ["AC-4"],
                                               "assurance": {"outcome": "pass", "revision": "1f9e77c", "current": True},
                                               "integrated": None})
        result, _, _ = scenario(mutate)
        self.assertOutcome(result, "inconclusive", "missing_pr_record")
        reason = next(r for r in result.record["reason_codes"] if r["code"] == "missing_pr_record")
        self.assertEqual(reason["prs"], ["OWNER/synthetic-repo#11"])

    def test_l352_duplicate_bare_issue_numbers_across_repositories(self):
        def other_only(d):
            other = copy.deepcopy(pr(d))
            other.update(repository="OTHER/other-repo", issue="OTHER/other-repo#1", parent_ref=None)
            d["pull_requests"] = [other]
            d["parent_acceptance"] = []
        result, runner, _ = scenario(other_only)
        self.assertOutcome(result, "not_complete", "issue_without_pr")
        self.assertFalse(any("OTHER/" in argv[-1] for argv in runner.calls))

        def both(d):
            other = copy.deepcopy(pr(d))
            other.update(repository="OTHER/other-repo", issue="OTHER/other-repo#1", parent_ref=None)
            d["pull_requests"].append(other)
        ok, runner, _ = scenario(both)
        self.assertOutcome(ok, "verified")
        self.assertFalse(any("OTHER/" in argv[-1] for argv in runner.calls))

    def test_l352_inaccessible_attestation_or_evidence(self):
        result, _, _ = scenario(mutate_gh=lambda g: g.pop(REVIEW_EP))
        self.assertOutcome(result, "inconclusive", "read_failed")
        self.assertEqual(line(result, "AC-2@9f3c")["state"], "inconclusive")
        self.assertIn(f"review:{PR}/2201", [u["read"] for u in result.record["unread_inputs"]])

    def test_l352_api_error_or_rate_limit(self):
        limited = Failing([(1, "", "HTTP 403: API rate limit exceeded")] * 3)
        result, _, sleeps = scenario(mutate_gh=lambda g: g.update({ISSUE_EP: limited}))
        self.assertOutcome(result, "inconclusive", "read_failed")
        reason = next(r for r in result.record["reason_codes"] if r["code"] == "read_failed")
        self.assertEqual(reason["detail"], {"read": f"issue:{ISSUE}", "cause": "rate_limited"})
        error = Failing([(1, "", "HTTP 502: Bad Gateway")] * 3)
        broken, _, _ = scenario(mutate_gh=lambda g: g.update({PR_EP: error}))
        self.assertOutcome(broken, "inconclusive", "read_failed")

    def test_l352_empty_goal_set(self):
        result, runner, _ = scenario(lambda d: _set(d["goal_run"], fixed_issues=[]))
        self.assertEqual(result.kind, "arming_rejection")
        self.assertEqual(result.record["rejected"], "empty_goal_set")
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(runner.calls, [])

    def test_l352_mismatched_marker(self):
        result, _, _ = scenario(marker="GOAL-COMPLETE: docs/other.md@sha256:" + "9" * 64)
        self.assertOutcome(result, "inconclusive", "marker_mismatch")
        source = BASE_LEDGER["goal_run"]["source"]
        claimed, _, _ = scenario(lambda d: _set(pm(d), criteria_verdict="unmet"), marker=f"GOAL-COMPLETE: {source}")
        self.assertOutcome(claimed, "not_complete", "criteria_unmet")

    def test_l352_resume_after_invalidation(self):
        first, runner_one, _ = scenario()
        self.assertOutcome(first, "verified")

        def withdraw(d):
            pr(d)["integrated"] = {"current": None, "history": [
                {"branch": "main", "merge_sha": "d44f1e0", "integrated_at": "2099-01-02T00:10:00Z",
                 "withdrawn_at": "2099-01-05T00:00:00Z", "reason": "reverted by e5a0c3b"}]}
            pr(d)["assurance"].update(current=False, stale_reason="integration withdrawn")
        second, runner_two, _ = scenario(withdraw, supersedes=[first.record["result_id"]])
        self.assertOutcome(second, "not_complete", "integration_withdrawn")
        self.assertEqual(second.record["supersedes"], [first.record["result_id"]])
        self.assertGreaterEqual(runner_two.count(ISSUE_EP), 1)

    def test_l352_hook_cap_exhaustion(self):
        result, _, _ = scenario(lambda d: _set(pm(d), criteria_verdict="unmet"), hook_cap_exhausted=True,
                                consumer_context="o-stop-hook")
        self.assertOutcome(result, "not_complete", "criteria_unmet")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("hook_cap_exhausted", advisory(result))
        self.assertTrue(result.record["producer"]["hook_cap_exhausted"])

    def test_l352_each_evidence_mode(self):
        result, _, _ = scenario()
        self.assertOutcome(result, "verified")
        self.assertEqual(line(result, "AC-1@9f3c")["accepted_proof"]["conclusion"], "success")
        self.assertEqual(line(result, "AC-2@9f3c")["accepted_proof"]["kind"], "external")
        self.assertEqual(line(result, "AC-3@9f3c")["accepted_proof"]["revision"], "4e683b4")
        self.assertEqual(line(result, "AC-4@9f3c")["accepted_proof"]["command"], "/accept AC-4@9f3c")
        self.assertEqual([line(result, f"AC-{n}@9f3c")["evaluator"] for n in range(1, 5)],
                         ["test", "independent_reviewer", "demonstration", "human"])

    def test_l352_missing_required_reviewer_or_human_decision(self):
        result, _, _ = scenario(lambda d: pm(d)["criteria"].pop(1))
        self.assertOutcome(result, "inconclusive", "post_merge_criterion_missing")
        human, _, _ = scenario(mutate_gh=lambda g: g.update({COMMENTS_EP: []}))
        self.assertOutcome(human, "not_complete", "awaiting_owner_acceptance")

    def test_l352_evaluator_mismatch(self):
        result, _, _ = scenario(lambda d: pr(d)["criteria"][0]["evaluator"].update(type="demonstration"))
        self.assertOutcome(result, "not_complete", "evaluator_mismatch")

    def test_l352_non_pr_work_rejected_at_arming(self):
        result, runner, _ = scenario(lambda d: _set(d["goal_run"], deliverable_type="document"))
        self.assertEqual(result.kind, "arming_rejection")
        self.assertEqual(result.record["rejected"], "non_pr_work")
        self.assertEqual(runner.calls, [])

    def test_l352_goal_spanning_repositories_rejected_at_arming(self):
        result, runner, _ = scenario(lambda d: d["goal_run"]["fixed_issues"].append("OTHER/other-repo#2"))
        self.assertEqual(result.kind, "arming_rejection")
        self.assertEqual(result.record["rejected"], "cross_repo_goal")
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(runner.calls, [])
        for key in ("result_id", "outcome", "purpose", "profile_version", "criteria"):
            self.assertNotIn(key, result.record)
        self.assertEqual(gv.read_result(result.record)[0], "unknown")

    def test_l352_revert_recorded_only_as_ledger_withdrawal(self):
        def withdraw(d):
            pr(d)["integrated"] = {"current": None, "history": [
                {"branch": "main", "merge_sha": "d44f1e0", "integrated_at": "2099-01-02T00:10:00Z",
                 "withdrawn_at": "2099-01-03T09:00:00Z", "reason": "reverted by e5a0c3b"}]}
        result, _, _ = scenario(withdraw)
        self.assertOutcome(result, "not_complete", "integration_withdrawn")
        self.assertEqual(result.record["repository_facts"]["closed_issues"][0]["state"], "closed")

    def test_l352_inconclusive_and_error_exit_codes_never_success(self):
        self.assertEqual(gv.EXIT_CODES["verified"], 0)
        for outcome, code in gv.EXIT_CODES.items():
            if outcome != "verified":
                self.assertNotEqual(code, 0, outcome)
        self.assertNotEqual(gv.EXIT_ERROR, 0)
        self.assertEqual(len({gv.EXIT_VERIFIED, gv.EXIT_NOT_COMPLETE, gv.EXIT_INCONCLUSIVE, gv.EXIT_ERROR,
                              gv.EXIT_EVIDENCE_READY}), 5)
        result, _, _ = scenario(mutate_gh=lambda g: g.pop(COMPARE_EP))
        self.assertEqual((result.outcome, result.exit_code), ("inconclusive", 3))
        error = gv.evaluate("not a ledger", runner=FakeRunner({}), sleep=lambda s: None)
        self.assertEqual((error.kind, error.exit_code), ("error", 2))

    def test_l352_human_criterion_without_acceptance_command(self):
        result, _, _ = scenario(mutate_gh=lambda g: g.update({COMMENTS_EP: [
            {"id": 6, "user": {"login": OWNER}, "body": "looks good", "created_at": "2099-01-03T00:00:00Z"}]}))
        self.assertOutcome(result, "not_complete", "awaiting_owner_acceptance")
        self.assertEqual(line(result, "AC-4@9f3c")["state"], "unmet")

    def test_l352_acceptance_from_non_owner_account(self):
        result, _, _ = scenario(mutate_gh=lambda g: g[COMMENTS_EP][0]["user"].update(login="lead-bot"))
        self.assertOutcome(result, "not_complete", "awaiting_owner_acceptance")
        reason = next(r for r in result.record["reason_codes"] if r["code"] == "awaiting_owner_acceptance")
        self.assertEqual(reason["detail"]["ignored"][0]["why"], "non_owner")

    def test_l352_acceptance_naming_superseded_criterion_revision(self):
        result, _, _ = scenario(mutate_gh=lambda g: g[COMMENTS_EP][0].update(body="/accept AC-4@1111"))
        self.assertOutcome(result, "not_complete", "awaiting_owner_acceptance")
        reason = next(r for r in result.record["reason_codes"] if r["code"] == "awaiting_owner_acceptance")
        self.assertEqual(reason["detail"]["ignored"][0]["why"], "superseded_revision")

    def test_l352_implementing_worker_offered_as_independent_reviewer(self):
        def mutate(d):
            pr(d)["criteria"][1]["evaluator"]["id"] = "worker-agent-1"
            pr(d)["reviewer_agent_id"] = "worker-agent-1"
            pr(d)["review"]["evidence_ref"] = "lane report retained at evidence/10/review.txt"
        result, _, _ = scenario(mutate)
        self.assertOutcome(result, "not_complete", "reviewer_not_independent")

    def test_l352_only_complete_consistent_evidence_returns_verified(self):
        result, _, _ = scenario()
        self.assertOutcome(result, "verified")
        for mutate in (lambda d: _set(pr(d)["assurance"], current=False, stale_reason="new head"),
                       lambda d: _set(parent(d), outcome="pending"),
                       lambda d: pr(d)["criteria_ids"].remove("AC-3@9f3c")):
            other, _, _ = scenario(mutate)
            self.assertNotEqual(other.outcome, "verified")


# --- AC5: D4.3 floor --------------------------------------------------------------


class TestFloor(unittest.TestCase):
    def test_d43_floor_reads_are_fresh_at_every_check(self):
        data = render(BASE_LEDGER)
        runner = FakeRunner(copy.deepcopy(BASE_GH))
        for _ in range(2):
            self.assertEqual(gv.evaluate(data, runner=runner, sleep=lambda s: None, owner_account=OWNER,
                                         now=NOW).outcome, "verified")
        for endpoint in (ISSUE_EP, PR_EP, COMPARE_EP):
            self.assertEqual(runner.count(endpoint), 2, endpoint)

    def test_d43_merge_not_reachable_from_destination(self):
        result, _, _ = scenario(mutate_gh=lambda g: g[COMPARE_EP].update(status="diverged"))
        self.assertEqual(result.outcome, "not_complete")
        self.assertIn("merge_not_reachable", codes(result))
        self.assertFalse(result.record["repository_facts"]["pull_requests"][0]["reachable_from_destination"])

    def test_d43_unreadable_floor_check_is_inconclusive(self):
        for endpoint in (ISSUE_EP, PR_EP, COMPARE_EP):
            with self.subTest(endpoint):
                result, _, _ = scenario(mutate_gh=lambda g, e=endpoint: g.pop(e))
                self.assertEqual(result.outcome, "inconclusive")

    def test_d43_unrecorded_revert_is_inconclusive(self):
        revert = {"sha": "e5a0c3b" + "0" * 33, "commit": {"message": f"Revert \"x\"\n\nThis reverts commit {MERGE}."}}
        result, _, _ = scenario(mutate_gh=lambda g: g[REVERT_EP].append(revert))
        self.assertEqual(result.outcome, "inconclusive")
        self.assertIn("unrecorded_revert_suspected", codes(result))

    def test_d43_revert_scan_failure_is_advisory_and_never_upgrades(self):
        result, _, _ = scenario(mutate_gh=lambda g: g.pop(REVERT_EP))
        self.assertEqual(result.outcome, "verified")
        self.assertIn("revert_scan_unavailable", advisory(result))
        self.assertEqual(result.record["unread_inputs"], [])
        failing, _, _ = scenario(lambda d: _set(pm(d), criteria_verdict="unmet"),
                                 lambda g: g[REVERT_EP].clear())
        self.assertEqual(failing.outcome, "not_complete")


# --- AC6: D4.4 proof table, every "never accepted" entry ----------------------------


class TestProofTable(unittest.TestCase):
    def assertRejected(self, result, code, criterion):
        self.assertNotEqual(result.outcome, "verified")
        self.assertIn(code, codes(result), result.record["reason_codes"])
        self.assertNotEqual(line(result, criterion)["state"], "met")

    def test_d44_test_green_run_for_a_different_subject(self):
        result, _, _ = scenario(lambda d: pm(d)["run"]["tested_subject"].update(sha="1234abc"))
        self.assertEqual(result.outcome, "not_complete")
        self.assertIn("rerun_subject_mismatch", codes(result))
        verbatim, _, _ = scenario(make_verbatim, lambda g: g[f"repos/{REPO}/commits/7a0b5d1"]["commit"]["tree"]
                                  .update(sha="0" * 40))
        self.assertIn("tree_not_equivalent", codes(verbatim))

    def test_d44_test_green_run_for_a_different_definition(self):
        result, _, _ = scenario(lambda d: pr(d)["checks"][0]["definition_ref"].update(rev="9999999"))
        self.assertRejected(result, "definition_mismatch", "AC-1@9f3c")

    def test_d44_test_green_run_for_a_different_environment(self):
        result, _, _ = scenario(lambda d: pm(d)["run"].update(environment="macos-14"))
        self.assertRejected(result, "environment_mismatch", "AC-1@9f3c")

    def test_d44_test_skipped_or_cancelled_run(self):
        for conclusion in ("skipped", "cancelled"):
            with self.subTest(conclusion):
                def mutate(d, c=conclusion):
                    make_verbatim(d)
                    pr(d)["ci_runs"][0]["conclusion"] = c
                result, _, _ = scenario(mutate)
                self.assertRejected(result, "run_not_success", "AC-1@9f3c")

    def test_d44_test_local_run_only_under_an_approved_fallback(self):
        result, _, _ = scenario(lambda d: pm(d)["run"].pop("run"))
        self.assertRejected(result, "local_run_without_fallback", "AC-1@9f3c")

    def test_d44_demonstration_standing_in_for_another_evaluator(self):
        result, _, _ = scenario(lambda d: pr(d)["criteria"][1]["evaluator"].update(type="demonstration"))
        self.assertRejected(result, "evaluator_mismatch", "AC-2@9f3c")

    def test_d44_unexplained_works_claim_or_expired_demonstration(self):
        result, _, _ = scenario(lambda d: _set(pr(d), demonstrated="unverified"))
        self.assertRejected(result, "demonstration_unexplained", "AC-3@9f3c")
        expired, _, _ = scenario(lambda d: _set(pr(d), demonstrated="expired"))
        self.assertRejected(expired, "demonstration_expired", "AC-3@9f3c")
        stale, _, _ = scenario(lambda d: pr(d)["demonstrated"].update(revision="0abc123"))
        self.assertRejected(stale, "demonstration_stale_revision", "AC-3@9f3c")

    def test_d44_review_by_the_lead(self):
        def mutate(d):
            pr(d)["criteria"][1]["evaluator"]["id"] = "lead-agent"
        result, _, _ = scenario(mutate)
        self.assertRejected(result, "reviewer_not_independent", "AC-2@9f3c")

    def test_d44_review_of_an_earlier_head(self):
        result, _, _ = scenario(lambda d: pr(d)["review"].update(head="0abc123"))
        self.assertRejected(result, "review_of_earlier_head", "AC-2@9f3c")
        fresh, _, _ = scenario(mutate_gh=lambda g: g[REVIEW_EP].update(commit_id="0abc123" + "0" * 33))
        self.assertRejected(fresh, "review_of_earlier_head", "AC-2@9f3c")

    def test_d44_external_review_must_be_by_the_reviewer_of_record(self):
        result, _, _ = scenario(mutate_gh=lambda g: g[REVIEW_EP]["user"].update(login="someone"))
        self.assertRejected(result, "reviewer_not_of_record", "AC-2@9f3c")
        open_finding, _, _ = scenario(lambda d: pr(d)["review"].update(unresolved_material=1))
        self.assertRejected(open_finding, "unresolved_material_finding", "AC-2@9f3c")

    def test_d44_internal_review_lane_with_retained_evidence(self):
        # Fixture-only (fix batch 1, B4): the retained review is now a resolvable PR comment.
        result, _, _ = scenario(internal_lane, add_lane_comment)
        self.assertEqual(result.outcome, "verified")
        self.assertEqual(line(result, "AC-2@9f3c")["accepted_proof"]["kind"], "internal_lane")

    def test_d44_human_summary_informal_comment_or_panel_ack_not_accepted(self):
        comments = [
            {"id": 7, "user": {"login": OWNER}, "body": "LGTM, AC-4 accepted", "created_at": "2099-01-03T00:00:00Z"},
            {"id": 8, "user": {"login": OWNER}, "body": "panel acknowledged AC-4@9f3c", "created_at": "2099-01-03T00:00:00Z"},
            {"id": 9, "user": {"login": "lead-agent"}, "body": "Summary: owner accepted AC-4", "created_at": "2099-01-03T00:00:00Z"},
        ]
        result, _, _ = scenario(mutate_gh=lambda g: g.update({COMMENTS_EP: comments}))
        self.assertRejected(result, "awaiting_owner_acceptance", "AC-4@9f3c")

    def test_d44_acceptance_posted_before_the_current_revision_approval(self):
        result, _, _ = scenario(mutate_gh=lambda g: g[COMMENTS_EP][0].update(created_at="2098-12-31T00:00:00Z"))
        self.assertRejected(result, "awaiting_owner_acceptance", "AC-4@9f3c")

    def test_d44_owner_account_missing_is_inconclusive_only_for_human_criteria(self):
        result, _, _ = scenario(owner_account=None)
        self.assertEqual(result.outcome, "inconclusive")
        self.assertIn("owner_account_unavailable", codes(result))
        no_human, runner, _ = scenario(lambda d: parent(d)["criteria"].pop(3), owner_account=None)
        self.assertEqual(no_human.outcome, "verified")
        self.assertEqual(runner.count(COMMENTS_EP), 0)

    def test_d44_amended_criterion_needs_acceptance_after_the_amendment(self):
        def amend(d):
            parent(d)["amendment"] = {"from": "sha256:9f3c", "to": parent(d)["criteria_ref"], "changed": ["AC-4"],
                                      "approved_by": "owner", "recorded_by": "lead", "at": "2099-01-03T12:00:00Z"}
        result, _, _ = scenario(amend)
        self.assertRejected(result, "awaiting_owner_acceptance", "AC-4@9f3c")
        later, _, _ = scenario(amend, lambda g: g[COMMENTS_EP][0].update(created_at="2099-01-03T13:00:00Z"))
        self.assertEqual(later.outcome, "verified")


# --- Fix batch 1 regressions (PR #237 review B1-B6, QA M1-M3, Low) ------------------
# Each test reproduces a false `verified` seen at 6df0a07 and asserts the fixed outcome.


class TestFixBatch1(unittest.TestCase):
    def assertNotVerified(self, result, outcome, code):
        self.assertEqual(result.outcome, outcome, result.record.get("reason_codes"))
        self.assertIn(code, codes(result), result.record.get("reason_codes"))
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(gv.read_result(result.record)[0], "accept", gv.read_result(result.record))

    # B1 + M1: the test proof is the criterion's own named run -------------------------

    def test_b1_failed_criterion_run_beside_a_passing_other_job_never_verifies(self):
        def mutate(d):
            pr(d)["ci_runs"].append({
                "run": 999, "job": "lint", "attempt": 2,
                "definition_ref": {"ref": ".github/workflows/ci.yml#lint", "rev": "5e5e5e5"},
                "tested_subject": {"sha": "d44f1e0", "kind": "head"}, "environment": "ubuntu-latest",
                "conclusion": "failure", "observed_at": "2099-01-02T00:30:00Z"})
            pr(d)["checks"].append({"id": "lint", "definition_ref": {"ref": ".github/workflows/ci.yml#lint",
                                                                     "rev": "5e5e5e5"},
                                    "executor": "ci", "tested_subject": "d44f1e0", "environment": "ci",
                                    "outcome": "fail", "evidence_ref": "run 999 attempt 2",
                                    "observed_at": "2099-01-02T00:30:00Z"})
            pr(d)["criteria"][0]["evidence_ref"] = "run 999 attempt 2"
            pm(d)["criteria"][0]["evidence_ref"] = "run 999 attempt 2"
        result, _, _ = scenario(mutate)
        self.assertNotVerified(result, "not_complete", "run_not_success")
        self.assertEqual(line(result, "AC-1@9f3c")["state"], "unmet")
        unrecorded, _, _ = scenario(lambda d: pm(d)["criteria"][0].update(evidence_ref="run 999 attempt 2"))
        self.assertNotVerified(unrecorded, "inconclusive", "ci_run_unrecorded")

    def test_b1_criterion_naming_a_check_must_be_proved_by_that_check(self):
        def mutate(d):
            pr(d)["checks"].append({"id": "lint", "definition_ref": {"ref": ".github/workflows/ci.yml#lint",
                                                                     "rev": "5e5e5e5"},
                                    "executor": "ci", "tested_subject": "d44f1e0", "environment": "ci",
                                    "outcome": "pass", "evidence_ref": "run 998 attempt 1",
                                    "observed_at": "2099-01-02T00:30:00Z"})
            pr(d)["criteria"][0]["evaluator"]["id"] = "lint"
        result, _, _ = scenario(mutate)
        self.assertNotVerified(result, "not_complete", "test_run_for_other_check")

    def test_m1_missing_attempt_is_inconclusive(self):
        result, _, _ = scenario(lambda d: pm(d)["criteria"][0].update(evidence_ref="run 130"))
        self.assertNotVerified(result, "inconclusive", "ci_identity_incomplete")

        def unrecorded_attempt(d):
            pr(d)["ci_runs"][1].pop("attempt")
            pm(d)["run"].pop("attempt")
        both, _, _ = scenario(unrecorded_attempt)
        self.assertNotVerified(both, "inconclusive", "ci_identity_incomplete")

    def test_m1_missing_criterion_evidence_ref_is_inconclusive(self):
        result, _, _ = scenario(lambda d: pm(d)["criteria"][0].pop("evidence_ref"))
        self.assertNotVerified(result, "inconclusive", "criterion_evidence_missing")
        pre, _, _ = scenario(lambda d: pr(d)["criteria"][0].pop("evidence_ref"))
        self.assertNotVerified(pre, "inconclusive", "criterion_evidence_missing")

    def test_m1_missing_check_environment_is_inconclusive(self):
        result, _, _ = scenario(lambda d: pr(d)["checks"][0].pop("environment"))
        self.assertNotVerified(result, "inconclusive", "check_environment_missing")

    # M2: the environment rule ----------------------------------------------------------

    def test_m2_ci_runner_spelling_verifies(self):
        result, _, _ = scenario(lambda d: pr(d)["checks"][0].update(environment="ci:ubuntu-latest"))
        self.assertEqual(result.outcome, "verified", result.record["reason_codes"])
        self.assertEqual(line(result, "AC-1@9f3c")["accepted_proof"]["check_environment"], "ci:ubuntu-latest")

    def test_m2_runner_first_token_matches_template_descriptors(self):
        for descriptor in ("ubuntu-latest, python 3.x",
                           "ubuntu-latest / node 22 / prisma generate, tsc --noEmit, eslint, vitest run"):
            with self.subTest(descriptor):
                def mutate(d, env=descriptor):
                    pr(d)["checks"][0]["environment"] = "ci:ubuntu-latest"
                    pr(d)["ci_runs"][1]["environment"] = env
                result, _, _ = scenario(mutate)
                self.assertEqual(result.outcome, "verified", result.record["reason_codes"])
        self.assertIsNone(gv._environment_verdict("ci:ubuntu-latest", {"run": 130, "environment": "ubuntu-latest, python 3.x"}))
        self.assertIsNone(gv._environment_verdict("ci:ubuntu-latest", {"run": 130, "environment": "ubuntu-latest / node 22 / x"}))

    def test_m2_runner_prefix_is_not_a_match(self):
        def mutate(d):
            pr(d)["checks"][0]["environment"] = "ci:ubuntu-latest"
            pr(d)["ci_runs"][1]["environment"] = "ubuntu-latest-arm"
        result, _, _ = scenario(mutate)
        self.assertNotVerified(result, "not_complete", "environment_mismatch")

    def test_m2_other_runner_never_verifies(self):
        result, _, _ = scenario(lambda d: pr(d)["checks"][0].update(environment="ci:macos-latest"))
        self.assertNotVerified(result, "not_complete", "environment_mismatch")

    def test_m2_runner_check_without_run_descriptor_is_inconclusive(self):
        def mutate(d):
            pr(d)["checks"][0]["environment"] = "ci:ubuntu-latest"
            pr(d)["ci_runs"][1].pop("environment")
        result, _, _ = scenario(mutate)
        self.assertNotVerified(result, "inconclusive", "run_environment_missing")

    def test_m2_approved_local_fallback_verifies(self):
        result, _, _ = scenario(local_fallback)
        self.assertEqual(result.outcome, "verified", result.record["reason_codes"])
        proof = line(result, "AC-1@9f3c")["accepted_proof"]
        self.assertEqual(proof["fallback"], {"executor": "host:mac-1", "approved_by": OWNER})
        self.assertEqual(proof["run"]["run"], "local-7")

    def test_m2_local_fallback_on_a_mismatched_environment_never_verifies(self):
        result, _, _ = scenario(lambda d: local_fallback(d, check_env="host:other-box"))
        self.assertNotVerified(result, "not_complete", "environment_mismatch")

    def test_m2_host_check_without_fallback_approval_never_verifies(self):
        result, _, _ = scenario(lambda d: local_fallback(d, approved=False))
        self.assertNotVerified(result, "not_complete", "local_run_without_fallback")

    def test_m2_named_environment_is_never_test_proof(self):
        result, _, _ = scenario(lambda d: pr(d)["checks"][0].update(environment="preview-vps"))
        self.assertNotVerified(result, "not_complete", "environment_not_test_proof")

    def test_m2_local_fallback_never_satisfies_a_ci_check(self):
        result, _, _ = scenario(lambda d: local_fallback(d, check_env="ci"))
        self.assertNotVerified(result, "not_complete", "local_run_not_ci")

    # B2: the prior gate must have passed, whatever the evaluators ----------------------

    def test_b2_failed_prior_gate_blocks_a_demonstration_only_goal(self):
        for conclusion in ("cancelled", "failure", "skipped"):
            with self.subTest(conclusion):
                def mutate(d, c=conclusion):
                    make_verbatim(d)
                    only_criteria(d, "AC-3@9f3c")
                    pr(d)["ci_runs"][0]["conclusion"] = c
                result, _, _ = scenario(mutate)
                self.assertNotVerified(result, "not_complete", "prior_gate_not_success")

    def test_b2_demonstration_only_goal_with_a_passing_gate_verifies(self):
        def mutate(d):
            make_verbatim(d)
            only_criteria(d, "AC-3@9f3c")
        result, _, _ = scenario(mutate)
        self.assertEqual(result.outcome, "verified", result.record["reason_codes"])

    def test_b2_failed_post_merge_check_blocks(self):
        result, _, _ = scenario(lambda d: pm(d)["checks"][0].update(outcome="fail"))
        self.assertNotVerified(result, "not_complete", "post_merge_check_failed")

    # B3: the combined records describe the same revisions -----------------------------

    def test_b3_pr_criteria_ref_contradicting_the_parent_never_verifies(self):
        result, _, _ = scenario(lambda d: pr(d).update(criteria_ref="sha256:b17e" + "0" * 60))
        self.assertNotVerified(result, "not_complete", "criteria_ref_mismatch")
        reason = next(r for r in result.record["reason_codes"] if r["code"] == "criteria_ref_mismatch")
        self.assertEqual(reason["detail"]["records"], [f"{PR}.criteria_ref", f"parent_acceptance/{ISSUE}.criteria_ref"])

    def test_b3_unrelated_assurance_or_integration_revision_never_verifies(self):
        result, _, _ = scenario(lambda d: pr(d)["assurance"].update(revision="0abc123"))
        self.assertNotVerified(result, "not_complete", "assurance_revision_mismatch")
        integrated, _, _ = scenario(lambda d: pr(d)["integrated"]["current"].update(revision="0abc123"))
        self.assertNotVerified(integrated, "not_complete", "integration_revision_mismatch")

    def test_b3_noncurrent_or_unintegrated_contribution_never_verifies(self):
        stale, _, _ = scenario(lambda d: parent(d)["contributions"][0]["assurance"].update(current=False))
        self.assertNotVerified(stale, "not_complete", "contribution_assurance_not_current")
        loose, _, _ = scenario(lambda d: parent(d)["contributions"][0].update(integrated=None))
        self.assertNotVerified(loose, "not_complete", "contribution_not_integrated")
        other, _, _ = scenario(lambda d: parent(d)["contributions"][0].update(integrated="0abc123"))
        self.assertNotVerified(other, "not_complete", "contribution_integration_mismatch")

    # B4: internal review evidence must resolve ------------------------------------------

    def test_b4_nonexistent_internal_review_evidence_is_inconclusive(self):
        def missing(d):
            internal_lane(d)
            pr(d)["review"]["evidence_ref"] = "evidence/does-not-exist.txt"
        result, _, _ = scenario(missing)
        self.assertNotVerified(result, "inconclusive", "review_evidence_unresolvable")
        unread, _, _ = scenario(internal_lane)  # the comment read returns 404
        self.assertNotVerified(unread, "inconclusive", "read_failed")
        self.assertIn(f"review-evidence:{PR}/comment-991", [u["read"] for u in unread.record["unread_inputs"]])

    def test_b4_internal_review_evidence_on_another_pr_never_verifies(self):
        result, _, _ = scenario(internal_lane, lambda g: g.update({LANE_COMMENT_EP: {
            "id": 991, "issue_url": f"https://api.github.com/repos/{REPO}/issues/77"}}))
        self.assertNotVerified(result, "not_complete", "review_evidence_for_other_pr")

    # B5: an unreadable floor fact blocks success --------------------------------------

    def test_b5_unexpected_compare_response_is_inconclusive(self):
        for body in ([], {}, {"status": "unexpected"}, "behind"):
            with self.subTest(body=body):
                result, _, _ = scenario(lambda d: only_criteria(d, "AC-4@9f3c"),
                                        lambda g, b=body: g.update({COMPARE_EP: b}))
                self.assertNotVerified(result, "inconclusive", "unreadable_floor_fact")
                self.assertIsNone(result.record["repository_facts"]["pull_requests"][0]["reachable_from_destination"])

    def test_b5_human_only_goal_still_verifies_with_confirmed_floor(self):
        result, _, _ = scenario(lambda d: only_criteria(d, "AC-4@9f3c"))
        self.assertEqual(result.outcome, "verified", result.record["reason_codes"])
        self.assertTrue(result.record["repository_facts"]["pull_requests"][0]["reachable_from_destination"])

    # B6: the reader checks every container's shape --------------------------------------

    def test_b6_reader_rejects_malformed_required_containers(self):
        good, _, _ = scenario()
        self.assertEqual(gv.read_result(good.record), ("accept", []))
        for field_name in ("criteria", "plan_ref", "repository_facts", "consumed_inputs", "producer",
                           "run_id", "result_id", "evidence_profile", "reason_codes", "supersedes"):
            for value in ("not-a-container", 5):
                if value == "not-a-container" and field_name in ("run_id", "result_id"):
                    continue  # a string is the right shape for an identifier
                with self.subTest(field=field_name, value=value):
                    broken = copy.deepcopy(good.record)
                    broken[field_name] = value
                    self.assertEqual(gv.read_result(broken)[0], "unusable", gv.read_result(broken))
        for path in (("pull_requests",), ("closed_issues",)):
            broken = copy.deepcopy(good.record)
            broken["repository_facts"][path[0]] = "x"
            self.assertEqual(gv.read_result(broken)[0], "unusable")
        unreachable = copy.deepcopy(good.record)
        unreachable["repository_facts"]["pull_requests"][0]["reachable_from_destination"] = None
        self.assertEqual(gv.read_result(unreachable)[0], "unusable")
        opened = copy.deepcopy(good.record)
        opened["repository_facts"]["closed_issues"][0]["state"] = "open"
        self.assertEqual(gv.read_result(opened)[0], "unusable")

    # M3: external review state -------------------------------------------------------

    def test_m3_dismissed_or_changes_requested_review_never_verifies(self):
        for state in ("DISMISSED", "CHANGES_REQUESTED", "PENDING"):
            with self.subTest(state):
                result, _, _ = scenario(mutate_gh=lambda g, s=state: g[REVIEW_EP].update(state=s))
                self.assertNotVerified(result, "not_complete", "review_state_not_accepting")
        approved, _, _ = scenario(mutate_gh=lambda g: g[REVIEW_EP].update(state="APPROVED"))
        self.assertEqual(approved.outcome, "verified")

    # Low: duplicate criterion IDs ---------------------------------------------------------

    def test_low_duplicate_criterion_ids_never_verify(self):
        result, _, _ = scenario(lambda d: parent(d)["criteria"].append(copy.deepcopy(parent(d)["criteria"][0])))
        self.assertNotVerified(result, "not_complete", "duplicate_criterion_id")
        good, _, _ = scenario()
        doubled = copy.deepcopy(good.record)
        doubled["criteria"].append(copy.deepcopy(doubled["criteria"][0]))
        self.assertEqual(gv.read_result(doubled)[0], "unusable")

    # Item 10: GitHub UI revert form ---------------------------------------------------------

    def test_item10_ui_squash_revert_is_detected_and_never_upgrades(self):
        revert = {"sha": "e5a0c3b" + "0" * 33,
                  "commit": {"message": 'Revert "synthetic change" (#12)\n\nReverts OWNER/synthetic-repo#10'}}
        result, _, _ = scenario(mutate_gh=lambda g: g[REVERT_EP].append(revert))
        self.assertNotVerified(result, "inconclusive", "unrecorded_revert_suspected")
        other = copy.deepcopy(revert)
        other["commit"]["message"] = "Reverts OWNER/synthetic-repo#11"
        unrelated, _, _ = scenario(mutate_gh=lambda g: g[REVERT_EP].append(other))
        self.assertEqual(unrelated.outcome, "verified")
        failing, _, _ = scenario(lambda d: _set(pm(d), criteria_verdict="unmet"),
                                 lambda g: g[REVERT_EP].append(revert))
        self.assertEqual(failing.outcome, "not_complete")

    # Item 11: goal-level reason codes name their targets ---------------------------------------

    def test_item11_goal_level_reason_codes_name_the_frozen_issue_set(self):
        result, _, _ = scenario(approved_revision="sha256:" + "3" * 64, hook_cap_exhausted=True,
                                marker="GOAL-COMPLETE: docs/other.md@sha256:" + "9" * 64)
        for reason in result.record["reason_codes"]:
            with self.subTest(reason["code"]):
                self.assertTrue(reason["issues"] or reason["prs"] or reason["criteria"], reason)
        stale = next(r for r in result.record["reason_codes"] if r["code"] == "source_revision_stale")
        self.assertEqual(stale["issues"], [ISSUE])


# --- Fix batch 2 regressions (PR #237 round 2 R2-F1..F4, R2-A1, QA Medium-4, Low-1) --------
# Each test reproduces a wrong outcome seen at e95d393 and asserts the fixed one.


def demo_only_verbatim(data):
    make_verbatim(data)
    only_criteria(data, "AC-3@9f3c")


def older_run_100(conclusion, observed_at="2099-01-01T01:00:00Z"):
    run = {"run": 100, "job": "build", "attempt": 5,
           "definition_ref": {"ref": ".github/workflows/ci.yml#build", "rev": "2ab2b59"},
           "tested_subject": {"sha": "7a0b5d1", "kind": "merge_ref", "head": "4e683b4", "base_oid": "b720c68"},
           "environment": "ubuntu-latest", "conclusion": conclusion,
           "applicability": {"to": "4e683b4", "established": True}}
    if observed_at is not None:
        run["observed_at"] = observed_at
    return run


def rename_job(data, job):
    for run in pr(data)["ci_runs"]:
        run["job"] = job
    pr(data)["checks"][0]["id"] = job
    pm(data)["checks"][0]["id"] = job
    pm(data)["run"]["job"] = job
    pm(data)["criteria"][0]["evidence_ref"] = f"run 130 job {job} attempt 1"


class TestFixBatch2(unittest.TestCase):
    def assertNotVerified(self, result, outcome, code):
        self.assertEqual(result.kind, "result", result.record)
        self.assertEqual(result.outcome, outcome, result.record.get("reason_codes"))
        self.assertIn(code, codes(result), result.record.get("reason_codes"))
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(gv.read_result(result.record)[0], "accept", gv.read_result(result.record))

    # R2-F1 + QA Medium-4: executor class is independent of approval -------------------------

    def test_r2f1_unapproved_host_executor_never_satisfies_a_ci_check(self):
        result, _, _ = scenario(lambda d: local_fallback(d, check_env="ci", approved=False))
        self.assertNotVerified(result, "not_complete", "local_run_not_ci")
        runner, _, _ = scenario(lambda d: local_fallback(d, check_env="ci:ubuntu-latest", approved=False))
        self.assertNotVerified(runner, "not_complete", "local_run_not_ci")

    def test_r2f1_host_environment_without_executor_is_local(self):
        result, _, _ = scenario(lambda d: pr(d)["ci_runs"][1].update(environment="host:mac-1"))
        self.assertNotVerified(result, "not_complete", "local_run_not_ci")

    def test_r2f1_non_github_run_id_without_executor_is_local(self):
        def mutate(d):
            pr(d)["ci_runs"][1]["run"] = "manual-130"
            pm(d)["run"]["run"] = "manual-130"
            pm(d)["criteria"][0]["evidence_ref"] = "run manual-130 attempt 1"
        result, _, _ = scenario(mutate)
        self.assertNotVerified(result, "not_complete", "local_run_not_ci")

    def test_r2f1_approved_local_entry_never_satisfies_a_ci_check(self):
        result, _, _ = scenario(lambda d: local_fallback(d, check_env="ci"))
        self.assertNotVerified(result, "not_complete", "local_run_not_ci")

    def test_r2f1_ci_entry_never_satisfies_a_host_check(self):
        result, _, _ = scenario(lambda d: pr(d)["checks"][0].update(environment="host:mac-1"))
        self.assertNotVerified(result, "not_complete", "environment_mismatch")

    def test_r2f1_local_classification_shapes(self):
        self.assertFalse(gv._is_local({"run": 130}))
        self.assertFalse(gv._is_local({"run": "130", "executor": "ci"}))
        for entry in ({"run": 130, "executor": "host:mac-1"}, {"run": 130, "environment": "host:mac-1"},
                      {"run": "local-7"}, {"run": None}, {"run": True}):
            with self.subTest(entry):
                self.assertTrue(gv._is_local(entry))

    # R2-F2: unreadable trees ------------------------------------------------------------------

    def test_r2f2_both_trees_unreadable_is_inconclusive(self):
        def blank(g):
            g[f"repos/{REPO}/commits/7a0b5d1"] = {}
            g[f"repos/{REPO}/commits/{MERGE}"] = {}
        result, _, _ = scenario(demo_only_verbatim, blank)
        self.assertNotVerified(result, "inconclusive", "tree_unreadable")
        reason = next(r for r in result.record["reason_codes"] if r["code"] == "tree_unreadable")
        self.assertEqual(reason["detail"]["reads"], ["tree:7a0b5d1", f"tree:{MERGE}"])
        self.assertIsNone(result.record["repository_facts"]["pull_requests"][0]["tree_equivalent"])

    def test_r2f2_one_tree_unreadable_is_inconclusive(self):
        result, _, _ = scenario(demo_only_verbatim, lambda g: g.update({f"repos/{REPO}/commits/{MERGE}": {}}))
        self.assertNotVerified(result, "inconclusive", "tree_unreadable")

    def test_r2f2_reader_rejects_verified_verbatim_without_tree_equivalence(self):
        good, _, _ = scenario(demo_only_verbatim)
        self.assertEqual(good.outcome, "verified")
        self.assertEqual(good.record["repository_facts"]["pull_requests"][0]["gate_result"], "applies_verbatim")
        for value in (False, None):
            with self.subTest(value=value):
                broken = copy.deepcopy(good.record)
                broken["repository_facts"]["pull_requests"][0]["tree_equivalent"] = value
                self.assertEqual(gv.read_result(broken)[0], "unusable")
        dropped = copy.deepcopy(good.record)
        dropped["repository_facts"]["pull_requests"][0].pop("tree_equivalent")
        self.assertEqual(gv.read_result(dropped)[0], "unusable")

    # R2-F3: prior gate selection ----------------------------------------------------------------

    def test_r2f3_newer_failure_is_not_masked_by_an_older_high_attempt_success(self):
        def mutate(d):
            demo_only_verbatim(d)
            pr(d)["ci_runs"][0].update(conclusion="failure", observed_at="2099-01-01T12:00:00Z")
            pr(d)["ci_runs"].append(older_run_100("success"))
        result, _, _ = scenario(mutate)
        self.assertNotVerified(result, "not_complete", "prior_gate_not_success")

    def test_r2f3_newer_success_after_an_older_failure_verifies(self):
        def mutate(d):
            demo_only_verbatim(d)
            pr(d)["ci_runs"][0].update(observed_at="2099-01-01T12:00:00Z")
            pr(d)["ci_runs"].append(older_run_100("failure"))
        result, _, _ = scenario(mutate)
        self.assertEqual(result.outcome, "verified", result.record["reason_codes"])

    def test_r2f3_unorderable_runs_are_inconclusive(self):
        def missing_time(d):
            demo_only_verbatim(d)
            pr(d)["ci_runs"].append(older_run_100("failure", observed_at=None))
        result, _, _ = scenario(missing_time)
        self.assertNotVerified(result, "inconclusive", "prior_gate_ambiguous")

        def tie(d):
            demo_only_verbatim(d)
            pr(d)["ci_runs"].append(older_run_100("failure", observed_at=pr(d)["ci_runs"][0]["observed_at"]))
        tied, _, _ = scenario(tie)
        self.assertNotVerified(tied, "inconclusive", "prior_gate_ambiguous")

    def test_r2f3_attempts_order_within_one_run(self):
        def mutate(d):
            demo_only_verbatim(d)
            retry = copy.deepcopy(pr(d)["ci_runs"][0])
            retry.update(attempt=2, conclusion="failure")
            retry.pop("observed_at")
            pr(d)["ci_runs"].append(retry)
        result, _, _ = scenario(mutate)
        self.assertNotVerified(result, "not_complete", "prior_gate_not_success")

    def test_r2f3_gate_runs_are_selected_by_the_recorded_tested_subject(self):
        def other_subject(d):
            demo_only_verbatim(d)
            stray = older_run_100("failure", observed_at="2099-01-01T23:00:00Z")
            stray["tested_subject"]["sha"] = "8b1c2d3"
            pr(d)["ci_runs"].append(stray)
        unnamed, _, _ = scenario(other_subject)
        self.assertNotVerified(unnamed, "not_complete", "prior_gate_not_success")

        def named(d):
            other_subject(d)
            pm(d)["tested_subject"] = {"sha": "7a0b5d1", "kind": "merge_ref", "head": "4e683b4", "base_oid": "b720c68"}
        selected, _, _ = scenario(named)
        self.assertEqual(selected.outcome, "verified", selected.record["reason_codes"])

    # R2-F4: text evidence-ref parser ---------------------------------------------------------

    def test_r2f4_text_refs_keep_hyphenated_and_spaced_job_names(self):
        pairs = {
            "run 130 job build-and-test attempt 1": "130/build-and-test/attempt-1",
            "run 130 job Skill validation attempt 1": "130/Skill validation/attempt-1",
            "run 42 job lint - strict attempt 3": "42/lint - strict/attempt-3",
        }
        for text, path in pairs.items():
            with self.subTest(text):
                self.assertEqual(gv._run_identity(text), gv._run_identity(path))
        self.assertEqual(gv._run_identity("run 130 job build-and-test attempt 1"), ("130", "build-and-test", 1))
        self.assertEqual(gv._run_identity("run 130 attempt 1 (vitest re-executed on the merged tree)"),
                         ("130", None, 1))
        self.assertEqual(gv._run_identity("run 130"), ("130", None, None))
        self.assertIsNone(gv._run_identity("review 2201"))

    def test_r2f4_hyphenated_and_spaced_job_names_verify_end_to_end(self):
        for job in ("build-and-test", "Skill validation"):
            with self.subTest(job):
                result, _, _ = scenario(lambda d, j=job: rename_job(d, j))
                self.assertEqual(result.outcome, "verified", result.record["reason_codes"])
                self.assertEqual(line(result, "AC-1@9f3c")["accepted_proof"]["run"]["job"], job)

    # R2-A1: malformed nested identities never raise --------------------------------------------

    def test_r2a1_non_scalar_identities_are_reported_not_raised(self):
        mutations = (
            lambda d: parent(d)["criteria"][0].update(id=["AC-1@9f3c"]),
            lambda d: parent(d)["criteria"][0].update(id={"id": "AC-1@9f3c"}),
            lambda d: parent(d)["contributions"][0].update(issue={"issue": ISSUE}),
            lambda d: pr(d).update(parent_ref=[ISSUE]),
            lambda d: d["workers"][0].update(agent_id=["worker-agent-1"]),
        )
        for mutate in mutations:
            result, _, _ = scenario(mutate)
            self.assertNotEqual(result.outcome, "verified")
        good, _, _ = scenario()
        for path, value in ((("criteria", 0, "id"), ["AC-1@9f3c"]),
                            (("criteria", 0, "id"), {"x": 1}),
                            (("repository_facts", "closed_issues", 0, "issue"), [ISSUE]),
                            (("repository_facts", "closed_issues", 0, "issue"), {"x": 1})):
            broken = copy.deepcopy(good.record)
            target = broken
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            self.assertEqual(gv.read_result(broken)[0], "unusable")

    def test_r2a1_every_scalar_leaf_replaced_by_a_container_never_raises(self):
        def leaves(value, path=()):
            if isinstance(value, dict):
                for key, item in value.items():
                    yield from leaves(item, path + (key,))
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    yield from leaves(item, path + (index,))
            else:
                yield path
        roots = (("pull_requests", 0), ("parent_acceptance", 0), ("workers", 0))
        count = 0
        for root in roots:
            base = BASE_LEDGER
            for key in root:
                base = base[key]
            for leaf in leaves(base):
                for replacement in ([1], {"x": 1}):
                    if isinstance(leaf[-1], int) and isinstance(replacement, list):
                        continue  # the ledger grammar has no list-of-lists; render() cannot emit one
                    def mutate(d, p=root + leaf, r=replacement):
                        target = d
                        for key in p[:-1]:
                            target = target[key]
                        target[p[-1]] = copy.deepcopy(r)
                    result, _, _ = scenario(mutate)
                    count += 1
                    if result.kind == "result" and result.outcome == "verified":
                        self.assertEqual(gv.read_result(result.record)[0], "accept", root + leaf)
        self.assertGreater(count, 100)

    # QA Low-1: stale criterion revision while the records agree ----------------------------------

    def test_low1_stale_criterion_revision_with_agreeing_criteria_refs_is_inconclusive(self):
        result, _, _ = scenario(lambda d: parent(d)["criteria"][0].update(id="AC-1@aaaa"))
        self.assertNotVerified(result, "inconclusive", "criteria_revision_stale")
        self.assertNotIn("criteria_ref_mismatch", codes(result))
        self.assertEqual(line(result, "AC-1@aaaa")["state"], "inconclusive")

# --- Fix batch 3 (PR #237 round 3 R3-F1..F4): one function per invariant, tested by enumeration --
# Each test reproduces a wrong outcome seen at d65ec5b and asserts the fixed one.


def localize(entry, shape):
    """Make one ci_runs entry LOCAL in one of the R2-F1 shapes, never approved."""
    entry.pop("fallback_approved_by", None)
    if shape == "unapproved_host_executor":  # the R3-F1 reproduction
        entry.update(run=f"local-{entry['run']}", executor="host:mac-1", environment="host:mac-1")
    elif shape == "host_environment_only":
        entry.update(environment="host:mac-1")
    elif shape == "executor_only":
        entry.update(executor="host:mac-1")
    elif shape == "negative_int_run_id":  # R3-F2
        entry.update(run=-entry["run"])
    else:
        raise AssertionError(shape)
    return entry["run"]


LOCAL_SHAPES = ("unapproved_host_executor", "host_environment_only", "executor_only", "negative_int_run_id")


def localize_run(data, run_id, shape):
    """LOCAL-ize ci_runs entry ``run_id`` and point every ref (and the post-merge run) at it."""
    entry = next(r for r in pr(data)["ci_runs"] if r["run"] == run_id)
    new_id = localize(entry, shape)
    if isinstance(pm(data).get("run"), dict) and pm(data)["run"].get("run") == run_id:
        pm(data)["run"]["run"] = new_id
    for item in pr(data)["checks"] + pr(data)["criteria"] + pm(data)["criteria"] + pm(data)["checks"]:
        if item.get("evidence_ref") == f"run {run_id} attempt 1":
            item["evidence_ref"] = f"run {new_id} attempt 1"


def head_kind_subject(data, sha="4e683b4"):
    """Record the prior gate run 123 as a direct-head build: {sha, kind: head}, no ``head`` member."""
    entry = next(r for r in pr(data)["ci_runs"] if r["run"] == 123)
    entry["tested_subject"] = {"sha": sha, "kind": "head"}


def head_tree(responses):
    responses[f"repos/{REPO}/commits/4e683b4"] = copy.deepcopy(responses[f"repos/{REPO}/commits/7a0b5d1"])


class TestFixBatch3(unittest.TestCase):
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))

    def assertNotVerified(self, result, outcome, code):
        self.assertEqual(result.kind, "result", result.record)
        self.assertEqual(result.outcome, outcome, result.record.get("reason_codes"))
        self.assertIn(code, codes(result), result.record.get("reason_codes"))
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(gv.read_result(result.record)[0], "accept", gv.read_result(result.record))

    def _functions(self):
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield node

    def _calls(self, name):
        """(enclosing function, Call) for every call of ``name`` or ``self.name``."""
        found = []
        for fn in self._functions():
            for node in ast.walk(fn):
                if isinstance(node, ast.Call):
                    f = node.func
                    called = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
                    if called == name:
                        found.append((fn.name, node))
        return found

    # R3-F1: one executor-class and authorization rule for every consumed run entry ----------

    def test_r3f1_every_run_consumer_calls_the_one_authorization_function(self):
        # Only two functions read ci_runs; only check_gate and proof_test call them.
        readers = set()
        for fn in self._functions():
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" \
                        and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "ci_runs":
                    readers.add(fn.name)
                if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                        and node.slice.value == "ci_runs":
                    readers.add(fn.name)
        self.assertEqual(readers, {"prior_gate_runs", "resolve_ci_run"})
        callers = {fn for name in ("prior_gate_runs", "resolve_ci_run") for fn, _ in self._calls(name)}
        self.assertEqual(callers, {"check_gate", "proof_test"})
        # Each consumer names itself once; the names are exactly RUN_CONSUMERS.
        sites = {}
        for fn, call in self._calls("_authorize_run"):
            consumer = call.args[2].value
            self.assertNotIn(consumer, sites)
            sites[consumer] = fn
        self.assertEqual(sites, {"test_proof": "proof_test", "prior_gate": "check_gate",
                                 "post_merge_rerun": "check_gate"})
        self.assertEqual(set(sites), set(gv.RUN_CONSUMERS))
        # The environment rule is reached only through the one function.
        self.assertEqual({fn for fn, _ in self._calls("_environment_verdict")}, {"_authorize_run"})

    def test_r3f1_unapproved_local_entry_never_verifies_on_any_consumer_path(self):
        paths = {
            # path: (ledger setup, run consumed, consumers that must name the LOCAL entry)
            "demonstration_only_applies_verbatim": (demo_only_verbatim, 123, {"prior_gate"}),
            "test_proof_applies_verbatim": (make_verbatim, 123, {"prior_gate", "test_proof"}),
            "test_proof_after_rerun": (lambda d: None, 130, {"post_merge_rerun"}),
            "rerun_without_test_criterion": (lambda d: only_criteria(d, "AC-2@9f3c", "AC-3@9f3c"), 130,
                                             {"post_merge_rerun"}),
        }
        seen = set()
        for path, (setup, run_id, consumers) in paths.items():
            for shape in LOCAL_SHAPES:
                with self.subTest(path=path, shape=shape):
                    def mutate(d, s=setup, r=run_id, sh=shape):
                        s(d)
                        localize_run(d, r, sh)
                    result, _, _ = scenario(mutate)
                    self.assertNotVerified(result, "not_complete", "local_run_not_ci")
                    named = {r["detail"].get("consumer") for r in result.record["reason_codes"]
                             if r["code"] == "local_run_not_ci"}
                    for item in result.record["criteria"]:
                        for reason in item.get("reasons") or []:
                            if isinstance(reason, dict) and reason.get("code") == "local_run_not_ci":
                                named.add((reason.get("detail") or {}).get("consumer"))
                    self.assertTrue(consumers <= named, (consumers, named))
                    seen |= named
        self.assertEqual(seen - {None}, set(gv.RUN_CONSUMERS))

    def test_r3f1_approved_fallback_still_verifies_through_the_rerun_consumer(self):
        result, _, _ = scenario(local_fallback)
        self.assertEqual(result.outcome, "verified", result.record["reason_codes"])

    def test_r3f1_prior_gate_run_without_a_required_check_is_inconclusive(self):
        def mutate(d):
            demo_only_verbatim(d)
            next(r for r in pr(d)["ci_runs"] if r["run"] == 123)["job"] = "unbound-job"
        result, _, _ = scenario(mutate)
        self.assertNotVerified(result, "inconclusive", "required_check_unbound")

    def test_r3f1_authorize_run_table(self):
        ci = {"run": 130, "job": "build", "environment": "ubuntu-latest"}
        local = {"run": "local-7", "job": "build", "executor": "host:mac-1", "environment": "host:mac-1"}
        approved = dict(local, fallback_approved_by=OWNER)
        table = [
            (ci, {"environment": "ci"}, None),
            (ci, {"environment": "ci:ubuntu-latest"}, None),
            (approved, {"environment": "host:mac-1"}, None),
            (local, {"environment": "ci"}, "local_run_not_ci"),
            (approved, {"environment": "ci"}, "local_run_not_ci"),
            (approved, {"environment": "ci:ubuntu-latest"}, "local_run_not_ci"),
            (local, {"environment": "host:mac-1"}, "local_run_without_fallback"),
            (approved, {"environment": "host:other-box"}, "environment_mismatch"),
            (ci, {"environment": "host:mac-1"}, "environment_mismatch"),
            (ci, {"environment": "preview-vps"}, "environment_not_test_proof"),
            (ci, {}, "check_environment_missing"),
            (ci, None, "required_check_unbound"),
            (None, {"environment": "ci"}, "ci_run_unrecorded"),
        ]
        for consumer in gv.RUN_CONSUMERS:
            for entry, check, code in table:
                with self.subTest(consumer=consumer, entry=entry, check=check):
                    verdict = gv._authorize_run(entry, check, consumer)
                    if code is None:
                        self.assertIsNone(verdict)
                    else:
                        self.assertEqual(verdict[1], code)
                        self.assertEqual(verdict[2]["consumer"], consumer)

    # R3-F2: one GitHub run-id validator --------------------------------------------------------

    def test_r3f2_github_run_id_table(self):
        table = [(130, True), ("130", True), (-130, False), ("-130", False), (0, False), ("0", False),
                 ("0130", False), ("130 ", False), ("", False), (None, False), (1.5, False), (True, False),
                 ([130], False), ("local-7", False), ("+130", False), (" 130", False),
                 ("١٣٠", False), ("130\n", False), (False, False)]
        for value, is_ci in table:
            with self.subTest(value=value):
                self.assertIs(gv._is_github_run_id(value), is_ci)
                self.assertIs(gv._is_local({"run": value, "environment": "ubuntu-latest"}), not is_ci)

    def test_r3f2_no_other_ad_hoc_run_id_check(self):
        self.assertEqual({fn for fn, _ in self._calls("isdigit")}, {"_pr_identity"})  # PR numbers, not runs
        self.assertEqual({fn for fn, _ in self._calls("_is_github_run_id")}, {"_is_local"})

    def test_r3f2_invalid_run_ids_never_satisfy_a_ci_check(self):
        for bad in (-130, "-130", 0, "0130"):
            with self.subTest(run=bad):
                def mutate(d, b=bad):
                    next(r for r in pr(d)["ci_runs"] if r["run"] == 130)["run"] = b
                    pm(d)["run"]["run"] = b
                    for item in pm(d)["criteria"] + pm(d)["checks"]:
                        if item["id"] in ("AC-1@9f3c", "build"):
                            item["evidence_ref"] = f"run {b} attempt 1"
                result, _, _ = scenario(mutate)
                self.assertNotVerified(result, "not_complete", "local_run_not_ci")

    # R3-F3: a head-kind subject at the PR head is a run at the head ------------------------------

    def test_r3f3_direct_head_subject_verifies_a_demonstration_only_verbatim_goal(self):
        result, _, _ = scenario(lambda d: (demo_only_verbatim(d), head_kind_subject(d)), head_tree)
        self.assertEqual(result.outcome, "verified", result.record["reason_codes"])

    def test_r3f3_direct_head_subject_verifies_a_verbatim_test_proof(self):
        result, _, _ = scenario(lambda d: (make_verbatim(d), head_kind_subject(d)), head_tree)
        self.assertEqual(result.outcome, "verified", result.record["reason_codes"])

    def test_r3f3_head_kind_subject_not_at_the_head_selects_nothing(self):
        result, _, _ = scenario(lambda d: (demo_only_verbatim(d), head_kind_subject(d, sha="8b1c2d3")))
        self.assertNotVerified(result, "inconclusive", "tree_unreadable")

    def test_r3f3_subject_at_head_table(self):
        head = "4e683b4"
        table = [({"sha": "7a0b5d1", "kind": "merge_ref", "head": head}, True),
                 ({"sha": head, "kind": "head"}, True),
                 ({"sha": "8b1c2d3", "kind": "head"}, False),
                 ({"sha": head, "kind": "merge_ref"}, False),
                 ({"sha": head}, False),
                 ({"kind": "head"}, False),
                 (head, False), (None, False)]
        for subject, expected in table:
            with self.subTest(subject=subject):
                self.assertIs(gv._subject_at_head(subject, head), expected)
        self.assertEqual({fn for fn, _ in self._calls("_subject_at_head")}, {"prior_gate_runs", "proof_test"})

    # R3-F4: the job name extends to the last attempt clause ------------------------------------

    def test_r3f4_text_ref_equals_path_form_table(self):
        for job in ("build", "build-and-test", "Build and test", "build attempt 1 results", "attempt"):
            for suffix in ("", " (merged-tree rerun)"):
                with self.subTest(job=job, suffix=suffix):
                    text = gv._run_identity(f"run 130 job {job} attempt 1{suffix}")
                    path = gv._run_identity(f"130/{job}/attempt-1")
                    self.assertEqual(text, path)
                    self.assertEqual(text, ("130", job, 1))

    def test_r3f4_job_name_containing_an_attempt_clause_verifies_end_to_end(self):
        result, _, _ = scenario(lambda d: rename_job(d, "build attempt 1 results"))
        self.assertEqual(result.outcome, "verified", result.record["reason_codes"])
        self.assertEqual(line(result, "AC-1@9f3c")["accepted_proof"]["run"]["job"], "build attempt 1 results")

# --- AC7: D3 retries --------------------------------------------------------------


class TestRetries(unittest.TestCase):
    def test_d3_three_tries_with_backoff_then_inconclusive_naming_the_read(self):
        result, runner, sleeps = scenario(mutate_gh=lambda g: g.update(
            {ISSUE_EP: Failing([(1, "", "HTTP 500")] * 3)}))
        self.assertEqual(result.outcome, "inconclusive")
        self.assertEqual(runner.count(ISSUE_EP), 3)
        self.assertEqual(sleeps[:2], [1.0, 2.0])
        self.assertEqual(result.record["unread_inputs"][0]["read"], f"issue:{ISSUE}")
        self.assertEqual(result.record["unread_inputs"][0]["tries"], 3)

    def test_d3_success_on_the_third_try(self):
        recovered = Failing([(1, "", "HTTP 502"), (1, "", "HTTP 502")], value=BASE_GH[ISSUE_EP])
        result, runner, sleeps = scenario(mutate_gh=lambda g: g.update({ISSUE_EP: recovered}))
        self.assertEqual(result.outcome, "verified")
        self.assertEqual(runner.count(ISSUE_EP), 3)
        self.assertEqual(sleeps, [1.0, 2.0])

    def test_d3_runner_exception_and_unparseable_output_are_retried(self):
        timeout = subprocess.TimeoutExpired(["gh"], 120)
        result, runner, _ = scenario(mutate_gh=lambda g: g.update(
            {PR_EP: Failing([timeout, (0, "not json", ""), (0, "", "")])}))
        self.assertEqual(result.outcome, "inconclusive")
        self.assertEqual(runner.count(PR_EP), 3)
        self.assertEqual(result.record["unread_inputs"][0]["cause"], "unparseable_output")

    def test_d3_paginated_pages_are_joined(self):
        pages = json.dumps([]) + "\n" + json.dumps(BASE_GH[COMMENTS_EP])
        result, _, _ = scenario(mutate_gh=lambda g: g.update({COMMENTS_EP: Failing([(0, pages, "")])}))
        self.assertEqual(result.outcome, "verified")


# --- AC8: exit codes and the command line -------------------------------------------


class TestCommandLine(unittest.TestCase):
    def _main(self, args, data=None, responses=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dev-state.md"
            path.write_text(render(data or BASE_LEDGER), encoding="utf-8")
            argv = [a.replace("{ledger}", str(path)) for a in args]
            out = io.StringIO()
            with redirect_stdout(out):
                code = gv.main(argv, runner=FakeRunner(copy.deepcopy(responses or BASE_GH)),
                               sleep=lambda s: None, now=NOW)
        return code, out.getvalue()

    def test_ac8_cli_exit_codes_match_the_recorded_outcome(self):
        code, out = self._main(["--ledger", "{ledger}", "--owner-account", OWNER])
        self.assertEqual((code, json.loads(out)["outcome"]), (0, "verified"))
        code, out = self._main(["--ledger", "{ledger}", "--owner-account", OWNER, "--purpose", "readiness"])
        self.assertEqual((code, json.loads(out)["outcome"]), (4, "evidence_ready"))
        code, out = self._main(["--ledger", "{ledger}"])
        self.assertEqual((code, json.loads(out)["outcome"]), (3, "inconclusive"))
        data = copy.deepcopy(BASE_LEDGER)
        pm(data)["criteria_verdict"] = "unmet"
        code, out = self._main(["--ledger", "{ledger}", "--owner-account", OWNER], data=data)
        self.assertEqual((code, json.loads(out)["outcome"]), (1, "not_complete"))

    def test_ac8_usage_and_internal_errors_never_return_success(self):
        with redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                gv.main(["--purpose", "final"], runner=FakeRunner({}))
        self.assertEqual(raised.exception.code, 2)
        code, out = self._main(["--ledger", "/nonexistent/dev-state.md"])
        self.assertEqual((code, json.loads(out)["error"]), (2, "ledger_unreadable"))
        with mock.patch.object(gv, "evaluate", side_effect=RuntimeError("boom")):
            code, out = self._main(["--ledger", "{ledger}"])
        self.assertEqual((code, json.loads(out)["error"]), (2, "internal_error"))

    def test_ac8_arming_rejection_is_not_a_result_record(self):
        data = copy.deepcopy(BASE_LEDGER)
        data["goal_run"]["fixed_issues"].append("OTHER/other-repo#2")
        code, out = self._main(["--ledger", "{ledger}"], data=data)
        record = json.loads(out)
        self.assertEqual(code, 2)
        self.assertEqual(record["kind"], "gv-arming-rejection")
        for key in ("result_id", "outcome", "purpose", "profile_version", "reason_codes"):
            self.assertNotIn(key, record)
        self.assertNotIn(record.get("rejected"), set(gv.EXIT_CODES))
        self.assertNotEqual(gv.read_result(record)[0], "accept")


# --- AC9: offline ------------------------------------------------------------------


class TestOffline(unittest.TestCase):
    def test_ac9_no_network_or_process_during_evaluation_and_cli(self):
        import socket
        with mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network")) as connect, \
                mock.patch.object(socket, "create_connection", side_effect=AssertionError("network")) as create, \
                mock.patch.object(subprocess, "run", side_effect=AssertionError("process")) as run, \
                mock.patch.object(subprocess, "Popen", side_effect=AssertionError("process")) as popen:
            result, _, _ = scenario()
            TestCommandLine()._main(["--ledger", "{ledger}", "--owner-account", OWNER])
        self.assertEqual(result.outcome, "verified")
        for patched in (connect, create, run, popen):
            patched.assert_not_called()

    def test_ac9_real_runner_is_never_invoked_when_a_runner_is_injected(self):
        with mock.patch.object(gv, "subprocess_runner", side_effect=AssertionError("real runner")) as real:
            result, _, _ = scenario()
        real.assert_not_called()
        self.assertEqual(result.outcome, "verified")


# --- AC10: SC-3 fixtures, read only ------------------------------------------------


class TestSC3Fixtures(unittest.TestCase):
    def _fixture(self, name):
        return json.loads((SC3 / name).read_text(encoding="utf-8"))

    def test_ac10_result_fixtures_agree_with_the_reader(self):
        expected = {
            "accepted-final-verified-completion.json": "accept",
            "unusable-readiness-never-verified.json": "unusable",
            "unusable-outcome-outside-vocabulary.json": "unusable",
            "unknown-missing-profile-version.json": "unknown",
            "rejected-cross-repo-goal-at-arming.json": "reject",
        }
        for name, verdict in expected.items():
            with self.subTest(name):
                fixture = self._fixture(name)
                self.assertEqual(fixture["expected_outcome"], verdict)
                self.assertEqual(gv.read_result(fixture["input"])[0], verdict, gv.read_result(fixture["input"]))

    def test_ac10_evidence_fixtures_agree_with_the_record_checker(self):
        expected = {
            "evidence-accepted-pr-assurance.json": ("accept", None),
            "evidence-accepted-parent-acceptance.json": ("accept", None),
            "evidence-rejected-pr-assurance-noncurrent-no-stale-reason.json":
                ("reject", "noncurrent_assurance_without_stale_reason"),
            "evidence-rejected-parent-acceptance-carries-result.json": ("reject", "carries_result"),
        }
        for name, (verdict, reason) in expected.items():
            with self.subTest(name):
                fixture = self._fixture(name)
                self.assertEqual(fixture["expected_outcome"], verdict)
                got, reasons = gv.check_evidence_record(fixture["input"])
                self.assertEqual(got, verdict, reasons)
                if reason:
                    self.assertIn(reason, reasons)

    def test_ac10_producer_output_covers_the_accepted_fixture_shape(self):
        fixture = self._fixture("accepted-final-verified-completion.json")["input"]
        result, _, _ = scenario()
        record = result.record
        self.assertLessEqual(set(fixture), set(record))
        self.assertLessEqual(set(fixture["producer"]), set(record["producer"]))
        self.assertLessEqual(set(fixture["repository_facts"]), set(record["repository_facts"]))
        self.assertLessEqual(set(fixture["repository_facts"]["pull_requests"][0]),
                             set(record["repository_facts"]["pull_requests"][0]))
        self.assertLessEqual(set(fixture["criteria"][0]), set(record["criteria"][0]))
        self.assertLessEqual(set(fixture["consumed_inputs"][0]), set(record["consumed_inputs"][0]))


if __name__ == "__main__":
    unittest.main()
