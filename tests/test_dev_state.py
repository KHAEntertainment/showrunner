#!/usr/bin/env python3
"""Tests for dev_state.py ledger validator."""

import subprocess
import tempfile
import unittest
from pathlib import Path


DEV_STATE = Path(__file__).parent.parent / "skills" / "dev" / "scripts" / "dev_state.py"
TEMPLATE = Path(__file__).parent.parent / "skills" / "dev" / "templates" / "DEV_STATE_TEMPLATE.md"


def run_validator(content: str) -> tuple[int, str, str]:
    """Run validator on in-memory content. Returns (exit_code, stdout, stderr)."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(content)
        path = f.name
    try:
        result = subprocess.run(
            ["python3", str(DEV_STATE), "--validate", path],
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout, result.stderr
    finally:
        Path(path).unlink()


class TestDevStateValidator(unittest.TestCase):
    def test_template_passes(self):
        """The shipped template should pass."""
        content = TEMPLATE.read_text()
        code, _, _ = run_validator(content)
        self.assertEqual(code, 0)

    def test_anchor_fails(self):
        """Anchor should fail."""
        content = """---
schema_version: 2
run_id: test
run_status: active
execution:
  backend: &traycer traycer
---
"""
        code, _, stderr = run_validator(content)
        self.assertNotEqual(code, 0)
        self.assertIn("anchor", stderr.lower())

    def test_tag_fails(self):
        """Tag should fail."""
        content = """---
schema_version: 2
run_id: test
run_status: active
execution:
  backend: !!str traycer
---
"""
        code, _, stderr = run_validator(content)
        self.assertNotEqual(code, 0)
        self.assertIn("tag", stderr.lower())

    def test_flow_mapping_fails(self):
        """Flow mapping should fail."""
        content = """---
schema_version: 2
run_id: test
run_status: active
data: {name: traycer}
---
"""
        code, _, stderr = run_validator(content)
        self.assertNotEqual(code, 0)
        self.assertIn("flow", stderr.lower())

    def test_flow_sequence_fails(self):
        """Flow sequence with content should fail."""
        content = """---
schema_version: 2
run_id: test
run_status: active
data: [traycer]
---
"""
        code, _, stderr = run_validator(content)
        self.assertNotEqual(code, 0)
        self.assertIn("flow", stderr.lower())
    
    def test_bad_indent_fails(self):
        """Bad indentation (3 spaces) should fail."""
        content = """---
schema_version: 2
run_id: test
run_status: active
execution:
   backend: traycer
---
"""
        code, _, stderr = run_validator(content)
        self.assertNotEqual(code, 0)

    def test_truncated_fails(self):
        """Truncated file should fail."""
        content = """---
schema_version: 2
run_id: test
run_status:
"""
        code, _, stderr = run_validator(content)
        self.assertNotEqual(code, 0)

    def test_missing_closing_delimiter_fails(self):
        """Frontmatter without closing delimiter should fail."""
        content = """---
schema_version: 2
run_id: test
run_status: active
"""
        code, _, stderr = run_validator(content)
        self.assertNotEqual(code, 0)

    def test_invalid_run_status_fails(self):
        """Invalid run_status should fail."""
        content = """---
schema_version: 2
run_id: test
run_status: invalid
---
"""
        code, _, stderr = run_validator(content)
        self.assertNotEqual(code, 0)
        self.assertIn("run_status", stderr.lower())

    def test_missing_run_id_passes(self):
        """Missing run_id (optional) should pass."""
        content = """---
schema_version: 2
run_status: active
next_action: test
---
"""
        code, _, _ = run_validator(content)
        self.assertEqual(code, 0)

    def test_empty_run_id_fails(self):
        """Empty run_id should fail."""
        content = """---
schema_version: 2
run_id: ""
run_status: active
---
"""
        code, _, stderr = run_validator(content)
        self.assertNotEqual(code, 0)
        self.assertIn("run_id", stderr.lower())

    def test_missing_lead_checkpoint_passes(self):
        """Missing lead_checkpoint (optional) should pass."""
        content = """---
schema_version: 2
run_id: test
run_status: active
next_action: test
---
"""
        code, _, _ = run_validator(content)
        self.assertEqual(code, 0)

    def test_single_quoted_json_passes(self):
        """Single-quoted JSON string passes."""
        content = """---
schema_version: 2
run_id: test
run_status: active
guard_at_merge: '{"at_head":0,"head":"abc"}'
---
"""
        code, _, _ = run_validator(content)
        self.assertEqual(code, 0)

    def test_double_quoted_flow_passes(self):
        """Double-quoted string containing { or [ passes."""
        content = """---
schema_version: 2
run_id: test
run_status: active
        data: "value with { and ["
---
"""
        code, _, _ = run_validator(content)
        self.assertEqual(code, 0)

    def test_unquoted_flow_mapping_fails(self):
        """Unquoted flow mapping fails."""
        content = """---
schema_version: 2
run_id: test
run_status: active
data: {a: 1}
---
"""
        code, _, stderr = run_validator(content)
        self.assertNotEqual(code, 0)
        self.assertIn("flow", stderr.lower())

    def test_unquoted_flow_sequence_fails(self):
        """Unquoted flow sequence fails."""
        content = """---
schema_version: 2
run_id: test
run_status: active
data: [1, 2]
---
"""
        code, _, stderr = run_validator(content)
        self.assertNotEqual(code, 0)
        self.assertIn("flow", stderr.lower())

    def test_unterminated_quote_fails(self):
        """Unterminated quote fails."""
        content = """---
schema_version: 2
run_id: test
run_status: active
data: "unclosed
---
"""
        code, _, stderr = run_validator(content)
        self.assertNotEqual(code, 0)
        self.assertIn("quote", stderr.lower())


class TestEvidenceFieldsReader(unittest.TestCase):
    """Issue #155 AC-7: the evidence fields are additive under schema_version 2."""

    @staticmethod
    def evidence_example() -> str:
        """The worked example in the template: the approved records, block style."""
        import re

        blocks = re.findall(
            r"^## Evidence record schema \(Issue #155\).*?^```yaml\n(.*?)^```",
            TEMPLATE.read_text(),
            re.M | re.S,
        )
        assert len(blocks) == 1, "expected one worked evidence example"
        return blocks[0]

    def test_reader_fixture_parses_the_evidence_fields(self):
        """The reader fixture with every new field passes dev_state.py --validate."""
        content = (
            "---\nschema_version: 2\nrun_id: example\nrun_status: active\n"
            + self.evidence_example()
            + "---\n"
        )
        code, stdout, stderr = run_validator(content)
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)

    def test_old_ledger_without_evidence_fields_stays_valid(self):
        """A ledger written before Issue #155 has none of the fields and still passes."""
        content = """---
schema_version: 2
run_id: v2.1.2-old
run_status: complete
pull_requests:
  - number: 142
    issue: 141
    branch: feat/141-example
    headRefOid: 4e683b4
    qa_status: complete
defect_episodes: []
blockers: []
next_action: none
---
"""
        for field in ("profile_version", "criteria_ref", "assurance", "parent_acceptance"):
            self.assertNotIn(field, content)
        code, _, stderr = run_validator(content)
        self.assertEqual(code, 0, stderr)

    def test_top_level_flow_map_for_a_new_field_fails(self):
        """The new fields follow the subset: a flow map is still refused."""
        content = """---
schema_version: 2
run_id: test
run_status: active
parent_acceptance: {scope: parent_acceptance}
---
"""
        code, _, stderr = run_validator(content)
        self.assertNotEqual(code, 0)
        self.assertIn("flow", stderr.lower())


# --- Issue #193 lane L2: goal-run ledger fields ------------------------------

import copy  # noqa: E402
import dataclasses  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402

SCRIPTS = DEV_STATE.parent
sys.path.insert(0, str(SCRIPTS))
import dev_state  # noqa: E402
import goal_run  # noqa: E402

GOAL_SECTION_RE = re.compile(
    r"^## Goal run record schema \(Issue #193\).*?(?=^## )", re.M | re.S
)

REAL_SHAPE_PRE_L2_LEDGER = """---
schema_version: 2
execution:
  execution_backend: traycer
  detection_status: detected
  detection_reason: identifiers_present
  backend_source: detected
  identity_verification: null
  topology: serial
  skill_dir: /opt/skills/dev
  traycer_agent_id: lead-1
  traycer_epic_id: epic-1
lead:
  agent_id: lead-1
  harness: claude
  model: example-model
workers:
  - role: worker-new
    issue: 222
    agent_id: worker-1
    status: merged
    pr: 222
inventory: []
pull_requests:
  - number: 222
    issue: 193
    headRefOid: e370e22
    qa_status: complete
parent_acceptance: []
defect_episodes: []
blockers: []
run_id: m3-l1
run_status: complete
lead_checkpoint: null
next_action: none
updated_at: 2026-11-05T09:00:00Z
---

# /dev Recovery Log
"""


def goal_example() -> str:
    """The worked goal_run example in the template (block style)."""
    blocks = re.findall(
        r"^## Goal run record schema \(Issue #193\).*?^```yaml\n(.*?)^```",
        TEMPLATE.read_text(),
        re.M | re.S,
    )
    assert len(blocks) == 1, "expected one worked goal_run example"
    return blocks[0]


def ledger_with(block_yaml: str) -> str:
    return (
        "---\nschema_version: 2\nrun_id: goal-test\nrun_status: active\n"
        + block_yaml
        + "next_action: dispatch\n---\n"
    )


def render_scalar(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    assert '"' not in value
    return f'"{value}"'


def render_block(value, indent: int) -> list[str]:
    pad = " " * indent
    lines = []
    if isinstance(value, dict):
        for key, item in value.items():
            name = key if re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.\-]*", key) else f'"{key}"'
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{pad}{name}:")
                lines.extend(render_block(item, indent + 2))
            elif isinstance(item, dict):
                lines.append(f"{pad}{name}: {{}}")
            elif isinstance(item, list):
                lines.append(f"{pad}{name}: []")
            else:
                lines.append(f"{pad}{name}: {render_scalar(item)}")
    else:
        for item in value:
            lines.append(f"{pad}- {render_scalar(item)}")
    return lines


def render_goal_run(block: dict) -> str:
    return "goal_run:\n" + "\n".join(render_block(block, 2)) + "\n"


def approved_entry(mode="standalone") -> dict:
    entry = {
        "repo": "example-org/example-repo",
        "run": "goal-roundtrip",
        "mode": mode,
        "lead": {"agent_id": "lead-1", "harness": "claude", "model": "example-model"},
        "plan_ref": {
            "origin": "docs/plans/goal.md",
            "source_revision": "4f3c2a1",
            "approved_revision": "4f3c2a1",
            "approval": {
                "authority": {"agent_id": "owner"},
                "evidence": {"reference": "approval comment", "digest": "sha256-x"},
            },
            "producer": {"session": "planner-1", "harness": "claude"},
        },
        "source": "docs/plans/goal.md@4f3c2a1",
        "approval_revision": "4f3c2a1",
        "fixed_issues": ["example-org/example-repo#12", "example-org/example-repo#13"],
    }
    if mode == "managed":
        entry["coordinator"] = {"agent_id": "coord-1", "harness": "codex", "model": "m"}
        entry["charter_revision"] = "charter-r1"
        entry["contract_refs"] = ["SC-1@v1"]
    return entry


def serialize_counters(counters, usage_measured=False, gv_retries_used=0) -> dict:
    """RunCounters is a plain dataclass (dicts, sets, str/number): asdict is safe.
    Sets become sorted lists for the ledger."""
    plain = dataclasses.asdict(counters)
    plain["dispatch_request_ids"] = {
        issue: sorted(ids) for issue, ids in plain["dispatch_request_ids"].items()
    }
    plain["usage_measured"] = usage_measured
    plain["gv_retries_used"] = gv_retries_used
    return plain


def armed_block(mode="standalone", spend=None) -> dict:
    coordinator_policy = {"dispatch_cap_per_issue": 6} if mode == "managed" else None
    result = goal_run.arm(
        approved_entry(mode),
        project_policy={"run_time_hours": 24.0},
        goal={"spend_cap": 50.0} if spend is not None else None,
        coordinator=coordinator_policy,
    )
    assert result.may_proceed, result
    armed = result.value
    counters = goal_run.RunCounters()
    if spend is not None:
        counters.spend = spend
    for issue, request in (
        ("example-org/example-repo#12", "req-1"),
        ("example-org/example-repo#12", "req-2"),
        ("example-org/example-repo#12", "req-2"),  # duplicate counts once
        ("example-org/example-repo#13", "req-3"),
    ):
        assert goal_run.account_dispatch(counters, issue, request).may_proceed
    block = armed.assignment.to_dict()
    block.update(
        {
            "approval_time": "2026-11-06T10:00:00Z",
            "next_wake_at": None,
            "paused": False,
            "policy": dataclasses.asdict(armed.policy),
            "counters": serialize_counters(counters, usage_measured=spend is not None),
        }
    )
    return block


class TestGoalRunLedgerCompat(unittest.TestCase):
    """AC1 (foreman condition): a pre-L2 ledger validates unchanged."""

    def pre_l2_template(self) -> str:
        text = TEMPLATE.read_text()
        text = GOAL_SECTION_RE.sub("", text)
        return text.replace("goal_run: null\n", "", 1)

    def test_pre_l2_template_validates_unchanged(self):
        old = self.pre_l2_template()
        self.assertNotIn("goal_run", old)
        code, stdout, stderr = run_validator(old)
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)
        self.assertEqual(stderr, "")

    def test_pre_l2_parse_is_identical_apart_from_the_new_key(self):
        old = dev_state.parse_simple_yaml(self.pre_l2_template())
        new = dev_state.parse_simple_yaml(TEMPLATE.read_text())
        self.assertIsNone(new.pop("goal_run"))
        self.assertEqual(old, new)

    def test_real_shape_pre_l2_ledger_validates_unchanged(self):
        self.assertNotIn("goal_run", REAL_SHAPE_PRE_L2_LEDGER)
        code, stdout, stderr = run_validator(REAL_SHAPE_PRE_L2_LEDGER)
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)

    def test_goal_parser_never_reached_when_absent_or_null(self):
        def boom(*_args, **_kwargs):
            raise AssertionError("goal_run code reached")

        saved = (dev_state.parse_goal_run_block, dev_state._load_goal_run_module)
        dev_state.parse_goal_run_block = boom
        dev_state._load_goal_run_module = boom
        try:
            for text in (REAL_SHAPE_PRE_L2_LEDGER, TEMPLATE.read_text()):
                data = dev_state.parse_simple_yaml(text)
                self.assertIsNone(dev_state.validate_goal_run_text(text, data))
        finally:
            dev_state.parse_goal_run_block, dev_state._load_goal_run_module = saved


class TestGoalRunFieldsValidate(unittest.TestCase):
    """AC2: valid goal fields pass; each malformed field fails with a named error."""

    def assert_named_failure(self, block: dict, expected: str):
        with self.assertRaises(dev_state.GoalRunError) as raised:
            dev_state.validate_goal_run(block)
        self.assertEqual(str(raised.exception), expected)
        code, _, stderr = run_validator(ledger_with(render_goal_run(block)))
        self.assertEqual(code, 1)
        self.assertIn(f"FAIL: {expected}", stderr)
        self.assertNotIn("Traceback", stderr)

    def test_template_worked_example_validates(self):
        code, stdout, stderr = run_validator(ledger_with(goal_example()))
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)

    def test_template_example_parses_to_a_valid_block(self):
        block = dev_state.parse_goal_run_block(ledger_with(goal_example()))
        self.assertEqual(block["fixed_issues"][0], "example-org/example-repo#12")
        self.assertEqual(block["counters"]["spend"], "unknown")
        dev_state.validate_goal_run(block)

    def test_malformed_fields_fail_with_named_errors(self):
        cases = [
            (("mode",), "auto", "goal_run.mode: malformed_input"),
            (("fixed_issues",), [], "goal_run.fixed_issues: empty_issue_set"),
            (("fixed_issues",), ["#12"], "goal_run.fixed_issues: bare_ambiguous_issue_id"),
            (("counters", "spend"), 0,
             "goal_run.counters.spend: unmeasured usage must be unknown, never 0"),
            (("counters", "spend"), 3.5, "goal_run.counters.spend: unmeasured usage must be unknown"),
            (("counters", "usage_measured"), "no", "goal_run.counters.usage_measured: must be true or false"),
            (("counters", "gv_retries_used"), -1,
             "goal_run.counters.gv_retries_used: must be an integer >= 0 or unknown"),
            (("policy", "dispatch_cap_per_issue"), "eight",
             "goal_run.policy.dispatch_cap_per_issue: invalid_policy_value"),
            (("policy", "run_time_hours"), 0, "goal_run.policy.run_time_hours: invalid_policy_value"),
            (("paused",), "yes", "goal_run.paused: must be true or false"),
            (("approval_time",), "2026-11-06T10:00:00",
             "goal_run.approval_time: must be a strict UTC ISO 8601 time"),
            (("next_wake_at",), "2026-11-06T12:00:00+02:00",
             "goal_run.next_wake_at: must be a strict UTC ISO 8601 time"),
            (("coordinator",), {"agent_id": "c", "harness": "h", "model": "m"},
             "goal_run.coordinator: does not match the normalized assignment"),
        ]
        for path, value, expected in cases:
            with self.subTest(expected=expected):
                block = armed_block()
                target = block
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                self.assert_named_failure(block, expected)

    def test_measured_spend_must_be_a_number(self):
        block = armed_block(spend=1.5)
        dev_state.validate_goal_run(block)
        block["counters"]["spend"] = "unknown"
        self.assert_named_failure(
            block, "goal_run.counters.spend: measured usage must be a finite number >= 0"
        )

    def test_counter_consistency_and_scope_fail_closed(self):
        block = armed_block()
        block["counters"]["dispatch_counts"]["example-org/example-repo#12"] = 5
        self.assert_named_failure(
            block,
            "goal_run.counters.dispatch_counts: "
            "example-org/example-repo#12 count does not match its request ids",
        )
        block = armed_block()
        block["counters"]["dispatch_counts"]["example-org/example-repo#99"] = 0
        self.assert_named_failure(
            block,
            "goal_run.counters.dispatch_counts: example-org/example-repo#99 is not in fixed_issues",
        )

    def test_missing_and_unknown_fields_fail(self):
        block = armed_block()
        del block["counters"]["gv_retries_used"]
        self.assert_named_failure(block, "goal_run.counters.gv_retries_used: missing required field")
        block = armed_block()
        block["policy"]["fix_batches"] = 2
        self.assert_named_failure(block, "goal_run.policy.fix_batches: unknown limit field")
        block = armed_block()
        del block["run"]
        self.assert_named_failure(block, "goal_run.run: missing_required_field")


class TestGoalRunRoundTrip(unittest.TestCase):
    """AC3: goal_run.py objects serialized through their own paths validate.
    Assignment uses to_dict(); BoundsPolicy and RunCounters are plain dataclasses
    (no MappingProxyType members), so dataclasses.asdict is used for them."""

    def test_standalone_round_trip(self):
        block = armed_block()
        dev_state.validate_goal_run(copy.deepcopy(block))
        text = ledger_with(render_goal_run(block))
        self.assertEqual(dev_state.parse_goal_run_block(text), block)
        code, stdout, stderr = run_validator(text)
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)

    def test_managed_round_trip_with_measured_spend(self):
        block = armed_block(mode="managed", spend=12.25)
        self.assertEqual(block["policy"]["dispatch_cap_per_issue"], 6)
        text = ledger_with(render_goal_run(block))
        self.assertEqual(dev_state.parse_goal_run_block(text), block)
        code, _, stderr = run_validator(text)
        self.assertEqual(code, 0, stderr)

    def test_ledger_counters_rebuild_run_counters(self):
        block = armed_block()
        stored = block["counters"]
        counters = goal_run.RunCounters(
            dispatch_counts=dict(stored["dispatch_counts"]),
            dispatch_request_ids={k: set(v) for k, v in stored["dispatch_request_ids"].items()},
            request_issues=dict(stored["request_issues"]),
            spend=stored["spend"],
        )
        self.assertEqual(counters.dispatch_count("example-org/example-repo#12"), 2)
        policy = goal_run.BoundsPolicy(**block["policy"])
        result = goal_run.evaluate_limits(
            policy, counters, block["approval_time"], "2026-11-06T11:00:00Z"
        )
        self.assertEqual(result.outcome, "complete")


class TestGoalRunParserFailsClosed(unittest.TestCase):
    """A malformed block fails with goal_run.<field> and never a traceback."""

    def test_malformed_blocks(self):
        good = goal_example()
        cases = [
            ("goal_run:\n  run: x\n      mode: standalone\n", "goal_run"),
            ("goal_run:\n  run: [a]\n", "goal_run.run: flow syntax"),
            ('goal_run:\n  run: "x\n', "goal_run.run: unterminated quote"),
            ("goal_run:\n  run: x\n  run: y\n", "goal_run.run: duplicate key"),
            ("goal_run:\n  run:\n  mode: standalone\n", "goal_run.run: missing value"),
            ("goal_run:\n  fixed_issues:\n    - a: b\n", "goal_run.fixed_issues: only scalar"),
            ("goal_run:\n  run: x # note\n", "goal_run.run: inline comment"),
            ("goal_run:\n", "goal_run: block is empty"),
            ("goal_run: yes\n", "goal_run: must be a block map or null"),
            (good.replace("  paused: false\n", "  paused: false\n    extra: 1\n"), "goal_run"),
        ]
        for block_yaml, expected in cases:
            with self.subTest(expected=expected):
                code, _, stderr = run_validator(ledger_with(block_yaml))
                self.assertEqual(code, 1, stderr)
                self.assertIn(f"FAIL: {expected}", stderr)
                self.assertNotIn("Traceback", stderr)

    def test_duplicate_goal_run_key_fails(self):
        """A trailing `goal_run: null` must not hide an earlier block."""
        content = ledger_with(goal_example() + "goal_run: null\n")
        code, _, stderr = run_validator(content)
        self.assertEqual(code, 1, stderr)
        self.assertIn("FAIL: goal_run: duplicate key", stderr)

    def test_missing_goal_run_module_fails_closed(self):
        """A goal-run ledger checked by a dev_state.py with no goal_run.py beside
        it fails with a named error; a pre-L2 ledger there still passes."""
        import shutil

        with tempfile.TemporaryDirectory() as tmp:
            lone = Path(tmp) / "dev_state.py"
            shutil.copy(DEV_STATE, lone)
            ledger = Path(tmp) / "ledger.md"
            for content, expected_code in (
                (ledger_with(goal_example()), 1),
                (REAL_SHAPE_PRE_L2_LEDGER, 0),
            ):
                ledger.write_text(content)
                done = subprocess.run(
                    [sys.executable, "-I", str(lone), "--validate", str(ledger)],
                    capture_output=True, text=True,
                )
                self.assertEqual(done.returncode, expected_code, done.stderr)
                self.assertNotIn("Traceback", done.stderr)
                if expected_code:
                    self.assertIn("FAIL: goal_run: goal_run.py is unavailable", done.stderr)



class TestGoalRunFixBatch1(unittest.TestCase):
    """PR #226 fix batch 1: R1 header-based null, R2 tabs, R3 exponent numbers."""

    def assert_fails_closed(self, content: str, expected: str = "FAIL: goal_run"):
        code, _, stderr = run_validator(content)
        self.assertEqual(code, 1, stderr)
        self.assertIn(expected, stderr)
        self.assertNotIn("Traceback", stderr)

    def test_r1_literal_block_goal_run_fails(self):
        """The flat reader drops `goal_run: |`; it must not read as null."""
        self.assert_fails_closed(
            ledger_with("goal_run: |\n  mode: broken\n  fixed_issues: []\n"),
            "FAIL: goal_run: must be a block map or null",
        )

    def test_r1_non_null_scalars_and_shapes_fail(self):
        for header in ("goal_run: >", "goal_run: >-", "goal_run: 0", "goal_run: false",
                       "goal_run: []", "goal_run: {}", 'goal_run: "null"', "goal_run: none"):
            with self.subTest(header=header):
                self.assert_fails_closed(
                    ledger_with(header + "\n"), "FAIL: goal_run: must be a block map or null"
                )

    def test_r1_explicit_null_forms_skip(self):
        for header in ("goal_run: null", "goal_run: ~", "goal_run: null   "):
            with self.subTest(header=header):
                code, _, stderr = run_validator(ledger_with(header + "\n"))
                self.assertEqual(code, 0, stderr)

    def test_r2_tab_after_a_complete_block_fails(self):
        self.assert_fails_closed(
            ledger_with(goal_example() + "\tpaused: true\n"),
            "FAIL: goal_run: tab indentation",
        )

    def test_r2_other_malformed_tails_after_a_complete_block_fail(self):
        tails = {
            "  \tpaused: true\n": "FAIL: goal_run: tab indentation",
            "        deep: 1\n": "FAIL: goal_run",
            "  paused: true\n": "FAIL: goal_run.paused: duplicate key",
            "  - stray\n": "FAIL: goal_run",
            "  run: [x]\n": "FAIL: goal_run.run",
            " x: 1\n": "FAIL:",
        }
        for tail, expected in tails.items():
            with self.subTest(tail=tail):
                self.assert_fails_closed(ledger_with(goal_example() + tail), expected)

    def test_r3_exponent_numbers_parse_and_non_finite_fail(self):
        for raw, value in (("1e-06", 1e-06), ("2.5E+3", 2500.0), ("-3e2", -300.0), ("0.5", 0.5)):
            with self.subTest(raw=raw):
                self.assertEqual(dev_state._goal_scalar(raw, "goal_run.x", 1), value)
        with self.assertRaises(dev_state.GoalRunError) as raised:
            dev_state._goal_scalar("1e999", "goal_run.counters.spend", 7)
        self.assertEqual(raised.exception.field, "goal_run.counters.spend")
        for raw in ("inf", "nan", "-inf"):
            with self.subTest(raw=raw):
                self.assertEqual(dev_state._goal_scalar(raw, "goal_run.x", 1), raw)

    def test_r3_tiny_measured_spend_round_trips(self):
        block = armed_block(spend=0.000001)
        text = ledger_with(render_goal_run(block))
        self.assertIn("spend: 1e-06", text)
        self.assertEqual(dev_state.parse_goal_run_block(text), block)
        code, stdout, stderr = run_validator(text)
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)

    def test_r3_non_finite_measured_spend_fails(self):
        for raw in ("inf", "nan", "1e999"):
            with self.subTest(raw=raw):
                text = ledger_with(render_goal_run(armed_block(spend=1.5)))
                self.assertIn("spend: 1.5", text)
                self.assert_fails_closed(
                    text.replace("spend: 1.5", f"spend: {raw}", 1),
                    "FAIL: goal_run.counters.spend",
                )



class TestGoalRunFixBatch2(unittest.TestCase):
    """PR #226 fix batch 2: M1 closed top level, L1 missing-field message."""

    def assert_named_failure(self, block: dict, expected: str):
        with self.assertRaises(dev_state.GoalRunError) as raised:
            dev_state.validate_goal_run(block)
        self.assertEqual(str(raised.exception), expected)
        code, _, stderr = run_validator(ledger_with(render_goal_run(block)))
        self.assertEqual(code, 1)
        self.assertIn(f"FAIL: {expected}", stderr)
        self.assertNotIn("Traceback", stderr)

    def test_m1_unknown_top_level_key_fails(self):
        block = armed_block()
        block["zz_typo_field"] = "x"
        self.assert_named_failure(block, "goal_run.zz_typo_field: unknown goal_run field")

    def test_m1_allowed_keys_match_the_template_example(self):
        example = goal_example()
        documented = set(re.findall(r"^  ([a-z_]+):", example, re.M))
        allowed = set(dev_state._GOAL_ASSIGNMENT_KEYS) | set(dev_state._GOAL_RUN_STATE_KEYS)
        self.assertEqual(documented, allowed)

    def test_l1_omitted_contract_refs_is_missing_required_field(self):
        block = armed_block()
        del block["contract_refs"]
        self.assert_named_failure(block, "goal_run.contract_refs: missing required field")

    def test_l1_present_but_different_keeps_mismatch_message(self):
        block = armed_block()
        block["contract_refs"] = ["SC-1@v1"]
        self.assert_named_failure(
            block, "goal_run.contract_refs: does not match the normalized assignment"
        )

    def test_valid_ledgers_still_pass(self):
        for content in (
            TEMPLATE.read_text(),
            REAL_SHAPE_PRE_L2_LEDGER,
            ledger_with(goal_example()),
            ledger_with(render_goal_run(armed_block())),
        ):
            code, stdout, stderr = run_validator(content)
            self.assertEqual(code, 0, stderr)
            self.assertIn("OK:", stdout)



# --- Issue #194 lane L4: goal-run grant and gate records ---------------------

L2_STATE_KEYS = ("approval_time", "next_wake_at", "paused", "policy", "counters")
L4_AUTHORITY_KEYS = ("grant", "merge_ledger", "gate_evidence", "delegated_records")
L6_RECOVERY_KEYS = ("obligations", "custody", "event_ledger", "recovery_receipts", "unknown_effects")
L7_LIFECYCLE_KEYS = ("context_resets",)


def grant_record(**changes) -> dict:
    grant = {
        "run_id": "goal-roundtrip",
        "host": "github.com",
        "repository": "example-org/example-repo",
        "base": "main",
        "eligible_issues": ["example-org/example-repo#12", "example-org/example-repo#13"],
        "max_merges": 2,
        "expires_at": "2026-11-07T10:00:00Z",
        "authorized_by": {
            "who": "owner",
            "at": "2026-11-06T10:00:00Z",
            "instruction": "Approved. At most 2 merges for 24 hours.",
        },
        "excluded_actions": ["external_review_bypass", "force_push"],
        "merge_method": "squash",
    }
    grant.update(changes)
    return grant


def authority_block() -> dict:
    """An L2 block plus valid L4 records, produced through goal_authority."""
    ga = dev_state._load_goal_authority_module()
    ledger = ga.record_merge(
        ga.MergeLedger(run_id="goal-roundtrip"),
        {"pr": 41, "outcome": "merged", "merge_sha": "9b1c2d3e"},
    ).value
    block = armed_block()
    block["grant"] = grant_record()
    block["merge_ledger"] = dev_state.merge_ledger_to_record(dev_state.MergeLedgerState(ledger))
    block["gate_evidence"] = {
        "41": {
            "checked_head": "3c4d5e6f",
            "outcome": "accept",
            "failures": [],
            "checked_at": "2026-11-06T14:00:00Z",
        }
    }
    block["delegated_records"] = {
        "pr41-ask-1": {
            "gate": "technical_ask_disposition",
            "decision": "Keep the retry bound at 3.",
            "reasoning": "Second opinion agreed.",
            "evidence_pointer": "PR 41 review comment",
            "reversal_path": "Raise the bound in a follow-up PR.",
        }
    }
    return block


def assert_goal_failure(test: unittest.TestCase, block: dict, expected: str) -> None:
    with test.assertRaises(dev_state.GoalRunError) as raised:
        dev_state.validate_goal_run(block)
    test.assertEqual(str(raised.exception), expected)
    code, _, stderr = run_validator(ledger_with(render_goal_run(block)))
    test.assertEqual(code, 1)
    test.assertIn(f"FAIL: {expected}", stderr)
    test.assertNotIn("Traceback", stderr)


class TestGoalRunAuthorityLedgerCompat(unittest.TestCase):
    """AC1 (foreman condition, ledger-compat test): goal_run: null and the exact
    L2 16-key block validate unchanged, without reaching the L4 code."""

    def test_goal_run_null_validates_unchanged(self):
        code, stdout, stderr = run_validator(ledger_with("goal_run: null\n"))
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)
        self.assertEqual(stderr, "")

    def test_l2_sixteen_key_block_validates_unchanged(self):
        block = armed_block()
        self.assertEqual(len(block), 16)
        self.assertEqual(
            set(block), set(dev_state._GOAL_ASSIGNMENT_KEYS) | set(L2_STATE_KEYS)
        )
        self.assertFalse(set(block) & set(L4_AUTHORITY_KEYS))

        def boom(*_args, **_kwargs):
            raise AssertionError("L4 authority code reached")

        saved = dev_state._load_goal_authority_module
        dev_state._load_goal_authority_module = boom
        try:
            dev_state.validate_goal_run(copy.deepcopy(block))
            nulls = dict(block, **{key: None for key in L4_AUTHORITY_KEYS})
            dev_state.validate_goal_run(nulls)
        finally:
            dev_state._load_goal_authority_module = saved
        code, stdout, stderr = run_validator(ledger_with(render_goal_run(block)))
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)
        self.assertEqual(stderr, "")

    def test_state_keys_are_l2_plus_four_authority_five_recovery_and_l7(self):
        self.assertEqual(
            dev_state._GOAL_RUN_STATE_KEYS,
            L2_STATE_KEYS + L4_AUTHORITY_KEYS + L6_RECOVERY_KEYS + L7_LIFECYCLE_KEYS,
        )


class TestGoalRunAuthorityRecordsValidate(unittest.TestCase):
    """AC2: valid grant and gate records validate; each malformed field fails
    with a named goal_run.<field> error."""

    def test_valid_records_validate(self):
        block = authority_block()
        dev_state.validate_goal_run(copy.deepcopy(block))
        code, stdout, stderr = run_validator(ledger_with(render_goal_run(block)))
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)

    def test_template_documents_the_authority_keys(self):
        documented = set(re.findall(r"^  ([a-z_]+):", goal_example(), re.M))
        self.assertTrue(set(L4_AUTHORITY_KEYS) <= documented)
        text = TEMPLATE.read_text()
        for key in L4_AUTHORITY_KEYS:
            self.assertIn(f"| `{key}` |", text)

    def test_malformed_records_fail_with_named_errors(self):
        cases = [
            (("grant", "expires_at"), "2026-11-07T10:00:00", "goal_run.grant.expires_at: invalid_field"),
            (("grant", "eligible_issues"), [], "goal_run.grant.eligible_issues: invalid_field"),
            (("grant", "eligible_issues"), ["#12"],
             "goal_run.grant.eligible_issues: each item must be a qualified OWNER/REPO#N string"),
            (("grant", "max_merges"), 0, "goal_run.grant.max_merges: invalid_field"),
            (("grant", "max_merges"), -1, "goal_run.grant.max_merges: invalid_field"),
            (("grant", "authorized_by", "at"), "2026-11-06T10:00:00",
             "goal_run.grant.authorized_by: invalid_field"),
            (("grant", "authorized_by", "role"), "owner",
             "goal_run.grant.authorized_by.role: unknown authorized_by field"),
            (("grant", "eligible_issues"), ["example-org/example-repo#99"],
             "goal_run.grant.eligible_issues: example-org/example-repo#99 is not in fixed_issues"),
            (("grant", "run_id"), "other-run", "goal_run.grant.run_id: does not match goal_run.run"),
            (("grant", "scope"), "all", "goal_run.grant.scope: unknown grant field"),
            (("merge_ledger", "consumed"), {"41": None},
             "goal_run.merge_ledger.consumed: 41 needs a merge SHA"),
            (("merge_ledger", "consumed"), {"41": ""},
             "goal_run.merge_ledger.consumed: 41 needs a merge SHA"),
            (("merge_ledger", "consumed"), {"pr41": "a1"},
             "goal_run.merge_ledger.consumed: pr41 is not a PR number"),
            (("merge_ledger", "slots_used"), 2, "goal_run.merge_ledger.slots_used: does not match consumed"),
            (("merge_ledger", "run_id"), "other-run",
             "goal_run.merge_ledger.run_id: does not match goal_run.grant.run_id"),
            (("merge_ledger", "halted"), True,
             "goal_run.merge_ledger.halt_ref: a halt needs its failure reference"),
            (("merge_ledger", "halt_ref"), "fail-1",
             "goal_run.merge_ledger.halt_ref: must be null when not halted"),
            (("merge_ledger", "cleared_halts"), {"fail-1": None},
             "goal_run.merge_ledger.cleared_halts: fail-1 needs a triage ref"),
            (("merge_ledger", "revoked_at"), "2026-11-06T12:00:00Z",
             "goal_run.merge_ledger.grant_in_force: must be false after a revocation"),
            (("merge_ledger", "reopen_issues"), ["example-org/example-repo#99"],
             "goal_run.merge_ledger.reopen_issues: example-org/example-repo#99 is not in fixed_issues"),
            (("gate_evidence", "41", "outcome"), "maybe",
             "goal_run.gate_evidence.41.outcome: must be accept or blocked"),
            (("gate_evidence", "41", "failures"), ["qa"],
             "goal_run.gate_evidence.41.failures: must be empty when outcome is accept"),
            (("gate_evidence", "41", "failures"), ["vibes"],
             "goal_run.gate_evidence.41.failures: must list check_gates gate names"),
            (("gate_evidence", "41", "checked_at"), "2026-11-06T14:00:00+02:00",
             "goal_run.gate_evidence.41.checked_at: must be a strict UTC ISO 8601 time"),
            (("gate_evidence", "41", "checked_head"), "",
             "goal_run.gate_evidence.41.checked_head: must name the checked head"),
            (("delegated_records", "pr41-ask-1", "gate"), "merge",
             "goal_run.delegated_records.pr41-ask-1: gate_not_delegable"),
            (("delegated_records", "pr41-ask-1", "gate"), "product_ask_disposition",
             "goal_run.delegated_records.pr41-ask-1: gate_not_delegable"),
            (("delegated_records", "pr41-ask-1", "gate"), "express_issue_confirmation",
             "goal_run.delegated_records.pr41-ask-1: unresolved_decision"),
            (("delegated_records", "pr41-ask-1", "reasoning"), "",
             "goal_run.delegated_records.pr41-ask-1.reasoning: missing_record_field"),
        ]
        for path, value, expected in cases:
            with self.subTest(expected=expected):
                block = authority_block()
                target = block
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                assert_goal_failure(self, block, expected)

    def test_count_above_max_merges_fails(self):
        block = authority_block()
        block["merge_ledger"]["consumed"] = {"41": "a1", "42": "b2", "43": "c3"}
        block["merge_ledger"]["slots_used"] = 3
        assert_goal_failure(
            self, block, "goal_run.merge_ledger.slots_used: exceeds goal_run.grant.max_merges"
        )

    def test_repository_binding_and_missing_fields(self):
        block = authority_block()
        block["grant"]["repository"] = "other-org/other-repo"
        block["grant"]["eligible_issues"] = ["other-org/other-repo#12"]
        assert_goal_failure(self, block, "goal_run.grant.repository: does not match goal_run.repo")
        block = authority_block()
        del block["grant"]["expires_at"]
        assert_goal_failure(self, block, "goal_run.grant.expires_at: missing required field")
        block = authority_block()
        del block["merge_ledger"]["cleared_halts"]
        assert_goal_failure(self, block, "goal_run.merge_ledger.cleared_halts: missing required field")
        block = authority_block()
        block["gate_evidence"]["41"]["outcome"] = "blocked"
        assert_goal_failure(
            self, block, "goal_run.gate_evidence.41.failures: must name a gate when outcome is blocked"
        )

    def test_merge_ledger_requires_a_grant(self):
        block = authority_block()
        block["grant"] = None
        assert_goal_failure(self, block, "goal_run.merge_ledger: requires a grant")
        del block["merge_ledger"]
        dev_state.validate_goal_run(block)  # no grant, no ledger: per-push confirmation

    def test_naive_revocation_time_fails(self):
        block = authority_block()
        block["merge_ledger"]["revoked_at"] = "2026-11-06T12:00:00"
        block["merge_ledger"]["grant_in_force"] = False
        assert_goal_failure(
            self, block, "goal_run.merge_ledger.revoked_at: must be a timezone-qualified ISO 8601 time"
        )


class TestGoalRunAuthorityRoundTrip(unittest.TestCase):
    """AC3: a grant and MergeLedger produced by goal_authority.py validate
    through dev_state.py and rebuild to the same state, ledger-only evidence
    (halt_history, cleared_halts) included."""

    def ga(self):
        return dev_state._load_goal_authority_module()

    def round_trip(self, state, grant):
        block = armed_block()
        block["grant"] = grant
        block["merge_ledger"] = dev_state.merge_ledger_to_record(state)
        text = ledger_with(render_goal_run(block))
        parsed = dev_state.parse_goal_run_block(text)
        self.assertEqual(parsed, block)
        dev_state.validate_goal_run(parsed)
        code, stdout, stderr = run_validator(text)
        self.assertEqual(code, 0, stderr)
        self.assertIn("OK:", stdout)
        rebuilt = dev_state.merge_ledger_from_record(parsed["merge_ledger"])
        self.assertEqual(rebuilt, state)
        self.assertEqual(dev_state.merge_ledger_to_record(rebuilt), block["merge_ledger"])
        return rebuilt

    def test_grant_from_goal_authority_and_merge_sequence(self):
        ga = self.ga()
        amended = ga.amend_grant(grant_record(), {"max_merges": 2})
        self.assertEqual(amended.outcome, "accept")
        grant = amended.value
        state = dev_state.MergeLedgerState(ga.MergeLedger(run_id=grant["run_id"]))
        self.round_trip(state, grant)
        event = {"pr": 41, "outcome": "merged", "merge_sha": "9b1c2d3e"}
        state = dev_state.merge_ledger_with(state, ga.record_merge(state.ledger, event)).value
        replay = ga.record_merge(state.ledger, event)
        self.assertTrue(replay.detail["replay"])
        self.assertEqual(dev_state.merge_ledger_with(state, replay).value, state)
        self.round_trip(state, grant)

    def merged_state(self, grant):
        ga = self.ga()
        state = dev_state.MergeLedgerState(ga.MergeLedger(run_id=grant["run_id"]))
        event = {"pr": 41, "outcome": "merged", "merge_sha": "9b1c2d3e"}
        return dev_state.merge_ledger_with(state, ga.record_merge(state.ledger, event)).value

    def test_halt_clear_revocation_and_takeover_states(self):
        ga = self.ga()
        grant = grant_record()
        merged = self.merged_state(grant)
        halted = dev_state.merge_ledger_record_failure(merged, "example-org/example-repo#12", "fail-1").value
        self.assertEqual(halted.halt_history, {"fail-1": "example-org/example-repo#12"})
        self.round_trip(halted, grant)
        cleared = dev_state.merge_ledger_clear_halt(halted, "triage-1").value
        self.round_trip(cleared, grant)
        revoked = dev_state.merge_ledger_with(merged, ga.revoke_grant(merged.ledger, "2026-11-06T12:00:00Z")).value
        self.round_trip(revoked, grant)
        lost = dev_state.merge_ledger_with(
            merged, ga.carry_grant(grant, merged.ledger, "takeover", custody_passed=False)
        ).value
        self.round_trip(lost, grant)


class TestGoalRunClearedHaltEvidence(unittest.TestCase):
    """Fix batch 1 B1: cleared-halt triage evidence is enforced and preserved."""

    def halted_block(self):
        block = authority_block()
        ga = dev_state._load_goal_authority_module()
        state = dev_state.merge_ledger_from_record(block["merge_ledger"])
        halted = dev_state.merge_ledger_record_failure(state, "example-org/example-repo#12", "fail-1")
        self.assertEqual(halted.outcome, "accept")
        self.assertTrue(ga.check_action(halted.value.ledger, "merge").outcome == "blocked")
        block["merge_ledger"] = dev_state.merge_ledger_to_record(halted.value)
        return block

    def test_genuine_clear_persists_and_survives_read_rebuild_write(self):
        block = self.halted_block()
        dev_state.validate_goal_run(copy.deepcopy(block))
        state = dev_state.merge_ledger_from_record(block["merge_ledger"])
        cleared = dev_state.merge_ledger_clear_halt(state, "triage-1").value
        block["merge_ledger"] = dev_state.merge_ledger_to_record(cleared)
        self.assertEqual(block["merge_ledger"]["cleared_halts"], {"fail-1": "triage-1"})
        text = ledger_with(render_goal_run(block))
        code, stdout, stderr = run_validator(text)
        self.assertEqual(code, 0, stderr)
        parsed = dev_state.parse_goal_run_block(text)
        rebuilt = dev_state.merge_ledger_from_record(parsed["merge_ledger"])
        self.assertEqual(rebuilt.cleared_halts, {"fail-1": "triage-1"})
        self.assertEqual(dev_state.merge_ledger_to_record(rebuilt), block["merge_ledger"])

    def test_premature_clear_by_hand_fails(self):
        block = self.halted_block()
        block["merge_ledger"]["halted"] = False
        block["merge_ledger"]["halt_ref"] = None
        assert_goal_failure(
            self, block, "goal_run.merge_ledger.cleared_halts: fail-1 was cleared without triage evidence"
        )

    def test_dropping_the_history_still_fails(self):
        block = self.halted_block()
        block["merge_ledger"].update({"halted": False, "halt_ref": None, "halt_history": {}})
        assert_goal_failure(
            self, block,
            "goal_run.merge_ledger.reopen_issues: example-org/example-repo#12 has no failure in halt_history",
        )

    def test_cleared_halts_entries_must_be_real_and_nonempty(self):
        cases = [
            ({"fail-1": ""}, False, "goal_run.merge_ledger.cleared_halts: fail-1 needs a triage ref"),
            ({"fail-9": "triage-1"}, True, "goal_run.merge_ledger.cleared_halts: fail-9 is not in halt_history"),
            ({"fail-1": "triage-1"}, True, "goal_run.merge_ledger.cleared_halts: fail-1 is still halted"),
        ]
        for cleared, halted, expected in cases:
            with self.subTest(expected=expected):
                block = self.halted_block()
                block["merge_ledger"]["cleared_halts"] = cleared
                if not halted:
                    block["merge_ledger"].update({"halted": False, "halt_ref": None})
                assert_goal_failure(self, block, expected)

    def test_helpers_carry_both_maps_and_refuse_a_bare_ledger(self):
        ga = dev_state._load_goal_authority_module()
        with self.assertRaises(TypeError):
            dev_state.merge_ledger_to_record(ga.MergeLedger(run_id="goal-roundtrip"))
        block = self.halted_block()
        record = dict(block["merge_ledger"])
        del record["cleared_halts"]
        with self.assertRaises(KeyError):
            dev_state.merge_ledger_from_record(record)
        state = dev_state.merge_ledger_from_record(block["merge_ledger"])
        again = dev_state.merge_ledger_record_failure(state, "example-org/example-repo#13", "fail-1")
        self.assertEqual((again.outcome, again.reason), ("invalid", "duplicate_halt_ref"))


class TestGoalRunAuthorityElementTypes(unittest.TestCase):
    """Fix batch 1 B2: element types are checked before validate_grant or any
    set membership, so a list or map element is a named error, never TypeError."""

    def cli_failure(self, block, sentinel_value, expected):
        text = ledger_with(render_goal_run(block)).replace('"__ELEMENT__"', sentinel_value)
        self.assertIn(f"- {sentinel_value}", text)
        code, _, stderr = run_validator(text)
        self.assertEqual(code, 1, stderr)
        self.assertIn(f"FAIL: {expected}", stderr)
        self.assertNotIn("Traceback", stderr)
        self.assertNotIn("malformed block", stderr)

    def test_list_and_map_elements_in_eligible_issues(self):
        expected = "goal_run.grant.eligible_issues: each item must be a qualified OWNER/REPO#N string"
        for element, text in (([], "[]"), ({}, "{}")):
            with self.subTest(element=text):
                block = authority_block()
                block["grant"]["eligible_issues"] = ["example-org/example-repo#12", element]
                with self.assertRaises(dev_state.GoalRunError) as raised:
                    dev_state.validate_goal_run(block)
                self.assertEqual(str(raised.exception), expected)
                block["grant"]["eligible_issues"] = ["example-org/example-repo#12", "__ELEMENT__"]
                self.cli_failure(block, text, expected)

    def test_list_and_map_elements_in_reopen_issues(self):
        expected = "goal_run.merge_ledger.reopen_issues: each item must be a qualified OWNER/REPO#N string"
        for element, text in (([], "[]"), ({}, "{}")):
            with self.subTest(element=text):
                block = authority_block()
                block["merge_ledger"]["reopen_issues"] = [element]
                with self.assertRaises(dev_state.GoalRunError) as raised:
                    dev_state.validate_goal_run(block)
                self.assertEqual(str(raised.exception), expected)
                block["merge_ledger"]["reopen_issues"] = ["__ELEMENT__"]
                self.cli_failure(block, text, expected)

    def test_other_scalar_boundaries_are_named(self):
        cases = [
            (("grant", "excluded_actions"), ["force_push", {}],
             "goal_run.grant.excluded_actions: must be a list of strings"),
            (("merge_ledger", "halt_history"), {"fail-1": []},
             "goal_run.merge_ledger.halt_history: fail-1 must map to a qualified OWNER/REPO#N string"),
            (("merge_ledger", "halt_ref"), {}, "goal_run.merge_ledger.halt_ref: must be null when not halted"),
            (("gate_evidence", "41", "checked_at"), [],
             "goal_run.gate_evidence.41.checked_at: must be a strict UTC ISO 8601 time"),
        ]
        for path, value, expected in cases:
            with self.subTest(expected=expected):
                block = authority_block()
                target = block
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                with self.assertRaises(dev_state.GoalRunError) as raised:
                    dev_state.validate_goal_run(block)
                self.assertEqual(str(raised.exception), expected)

# --- Issue #195 lane L195-2b: completion results and evidence additions -------

from unittest import mock  # noqa: E402


def evidence_section_example(fence: int) -> str:
    """The n-th yaml block of the template's L195-2b section."""
    section = TEMPLATE.read_text().split(
        "## Completion results and evidence additions (v2.2, Issue #195)", 1)[1].split("\n## ", 1)[0]
    return re.findall(r"^```yaml\n(.*?)^```", section, re.M | re.S)[fence]


def worked_evidence_ledger() -> str:
    return ("---\nschema_version: 2\nrun_id: example\nrun_status: active\n"
            + TestEvidenceFieldsReader.evidence_example() + "---\n")


def worked_pull_requests() -> list:
    return dev_state.read_ledger_block(worked_evidence_ledger(), "pull_requests")


def result_record(result_id="gv-1", run_id="goal-1", purpose="final", outcome="verified", supersedes=()):
    return {"profile_version": "completion-result-v1", "result_id": result_id, "run_id": run_id,
            "plan_ref": {"origin": "traycer-artifact:e/p/index.md", "approved_revision": "sha256:2222"},
            "purpose": purpose, "outcome": outcome,
            "producer": {"helper": "skills/dev/scripts/verify_goal_completion.py", "recorded_by": "lead"},
            "supersedes": list(supersedes)}


class TestLedgerBlockReader(unittest.TestCase):
    """Item 6: the folded reader is public, documented, and fails closed."""

    def test_reads_lists_of_maps_and_at_sign_keys(self):
        text = worked_evidence_ledger()
        prs = dev_state.read_ledger_block(text, "pull_requests")
        parents = dev_state.read_ledger_block(text, "parent_acceptance")
        self.assertEqual(prs[0]["number"], 23)
        self.assertEqual(parents[0]["criteria_map"]["AC-1@9f3c"], "AC-1@b17e")
        self.assertIs(dev_state.read_ledger_block(text, "completion_results"), dev_state.LEDGER_ABSENT)
        self.assertEqual(dev_state.read_ledger_block(text, "run_id"), "example")

    def test_fails_closed_with_a_named_error(self):
        cases = {
            "pull_requests:\n\t- x\n": "tab indentation",
            "pull_requests:\n  - a: |\n    text\n": "block scalars",
            "pull_requests:\n  - a: 1\n    a: 2\n": "duplicate key",
            "pull_requests:\n  - [flow]\n": "flow syntax",
            "pull_requests:\n  - - nested\n": "nested list",
            "pull_requests:\n": "block is empty",
            "pull_requests:\n  - a: 1\npull_requests: []\n": "duplicate key",
        }
        for body, phrase in cases.items():
            with self.subTest(body=body):
                with self.assertRaises(dev_state.LedgerBlockError) as raised:
                    dev_state.read_ledger_block(f"---\n{body}---\n", "pull_requests")
                self.assertIn(phrase, str(raised.exception))
        with self.assertRaises(dev_state.LedgerBlockError):
            dev_state.read_ledger_block("no frontmatter", "pull_requests")

    def test_is_documented(self):
        self.assertFalse(dev_state.read_ledger_block.__name__.startswith("_"))
        self.assertGreater(len(dev_state.read_ledger_block.__doc__ or ""), 200)


class TestEvidenceAdditionsLedgerCompat(unittest.TestCase):
    """Foreman condition: every legacy form validates unchanged, and the new
    evidence validator is never reached for it."""

    def legacy_ledgers(self) -> dict:
        import tests.test_goal_lifecycle_clocks as clocks  # noqa: PLC0415 (it imports this module)

        return {
            "template (goal_run null)": TEMPLATE.read_text(),
            "goal_run null": ledger_with("goal_run: null\n"),
            "real-shape pre-L2": REAL_SHAPE_PRE_L2_LEDGER,
            "L2 16-key": ledger_with(render_goal_run(armed_block())),
            "L4 20-key": ledger_with(render_goal_run(authority_block())),
            "L6 25-key": ledger_with(render_goal_run(clocks.l6_block())),
            "L7 context_resets": ledger_with(render_goal_run(clocks._context_resets_block(True, 0))),
            "completion_results null": ledger_with("completion_results: null\n"),
            "completion_results []": ledger_with("completion_results: []\n"),
        }

    def test_legacy_ledgers_never_reach_the_evidence_validator(self):
        def boom(*_args, **_kwargs):
            raise AssertionError("evidence validator reached")

        with mock.patch.object(dev_state, "read_ledger_block", boom):
            for name, text in self.legacy_ledgers().items():
                with self.subTest(name=name):
                    self.assertIsNone(dev_state.validate_evidence_text(text))

    def test_legacy_ledgers_validate_unchanged(self):
        for name, text in self.legacy_ledgers().items():
            with self.subTest(name=name):
                code, stdout, stderr = run_validator(text)
                self.assertEqual(code, 0, stderr)
                self.assertIn("OK:", stdout)
                self.assertEqual(stderr, "")

    def test_non_evidence_pull_requests_are_left_alone(self):
        """A pre-#155 PR entry with a text CI reference and no attempt still passes."""
        content = ("---\nschema_version: 2\nrun_id: old\nrun_status: active\npull_requests:\n"
                   "  - number: 142\n    ci_runs:\n      - run: 123\n        job: build\n"
                   "    checks:\n      - id: build\n        evidence_ref: \"run 123\"\n---\n")
        code, _, stderr = run_validator(content)
        self.assertEqual(code, 0, stderr)


class TestEvidencePullRequestsValidate(unittest.TestCase):
    """Items 2, 3, 4 and 7 on completion-evidence-v1 PR records."""

    def assert_error(self, mutate, path, phrase):
        prs = worked_pull_requests()
        mutate(prs[0])
        with self.assertRaises(dev_state.GoalRunError) as raised:
            dev_state.validate_evidence_pull_requests(prs)
        self.assertEqual(raised.exception.field, path)
        self.assertIn(phrase, raised.exception.message)

    def test_worked_example_validates_and_uses_the_structured_form(self):
        code, stdout, stderr = run_validator(worked_evidence_ledger())
        self.assertEqual(code, 0, stderr)
        rec = worked_pull_requests()[0]
        self.assertEqual(rec["post_merge"][0]["criteria"][0]["evidence_ref"],
                         {"run": 130, "job": "build", "attempt": 1})
        rerun = [r for r in rec["ci_runs"] if r["run"] == 130]
        self.assertEqual(len(rerun), 1)
        self.assertEqual(rerun[0]["tested_subject"], {"sha": "d44f1e0", "kind": "head"})
        self.assertEqual((rerun[0]["job"], rerun[0]["attempt"]),
                         (rec["post_merge"][0]["run"]["job"], rec["post_merge"][0]["run"]["attempt"]))

    def test_structured_evidence_ref_rules(self):
        def ref(**fields):
            def mutate(rec):
                rec["criteria"][0]["evidence_ref"] = fields
            return mutate
        base = "pull_requests[0].criteria[0].evidence_ref"
        self.assert_error(ref(run=123, job="build"), f"{base}.attempt", "positive integer")
        self.assert_error(ref(run=123, job="build", attempt=0), f"{base}.attempt", "positive integer")
        self.assert_error(ref(run=123, job="build", attempt="1"), f"{base}.attempt", "positive integer")
        self.assert_error(ref(run=123, attempt=1), f"{base}.job", "must name the job")
        self.assert_error(ref(run="", job="build", attempt=1), f"{base}.run", "run id")
        self.assert_error(ref(run=123, job="build", attempt=1, url="x"), f"{base}.url", "unknown")
        self.assert_error(
            lambda rec: rec["post_merge"][0]["checks"][0].update(evidence_ref={"run": 130, "job": "build"}),
            "pull_requests[0].post_merge[0].checks[0].evidence_ref.attempt", "positive integer")

    def test_text_and_non_ci_references_stay_readable(self):
        prs = worked_pull_requests()
        prs[0]["criteria"][0]["evidence_ref"] = "run 123 attempt 1"
        prs[0]["post_merge"][0]["criteria"][0]["evidence_ref"] = "123/build/attempt-1"
        self.assertIsNone(dev_state.validate_evidence_pull_requests(prs))
        self.assertIsInstance(prs[0]["checks"][1]["evidence_ref"], dict)  # comment + snapshot

    def test_ci_runs_entries_record_attempt(self):
        for bad in (None, 0, "1", True):
            with self.subTest(attempt=bad):
                self.assert_error(lambda rec, bad=bad: rec["ci_runs"][0].update(attempt=bad),
                                  "pull_requests[0].ci_runs[0].attempt", "positive integer")
        self.assert_error(lambda rec: rec["ci_runs"][0].pop("attempt"),
                          "pull_requests[0].ci_runs[0].attempt", "positive integer")

    def test_merge_ref_subject_records_head_base_oid_and_the_record_target_branch(self):
        for name in ("head", "base_oid"):
            with self.subTest(field=name):
                self.assert_error(lambda rec, name=name: rec["ci_runs"][0]["tested_subject"].pop(name),
                                  f"pull_requests[0].ci_runs[0].tested_subject.{name}", "merge_ref")
        self.assert_error(lambda rec: rec.pop("target_branch"), "pull_requests[0].target_branch", "merge ref")
        prs = worked_pull_requests()
        prs[0].pop("target_branch")
        prs[0]["ci_runs"] = [r for r in prs[0]["ci_runs"] if r["tested_subject"]["kind"] == "head"]
        self.assertIsNone(dev_state.validate_evidence_pull_requests(prs))

    def test_fallback_approved_by(self):
        approval = {"who": "owner", "at": "2026-10-20T16:20:00Z", "instruction": "owner message 16:18Z"}

        def local(**changes):
            def mutate(rec):
                entry = dict(rec["ci_runs"][1], run="local-7", executor="host:mac-1",
                             environment="host:mac-1", fallback_approved_by=dict(approval))
                entry.update(changes)
                rec["ci_runs"].append(entry)
            return mutate

        prs = worked_pull_requests()
        local()(prs[0])
        self.assertIsNone(dev_state.validate_evidence_pull_requests(prs))
        prs = worked_pull_requests()
        local(fallback_approved_by=dict(approval, who="lead", instruction="owner message 16:18Z, quoted"))(prs[0])
        self.assertIsNone(dev_state.validate_evidence_pull_requests(prs))
        base = "pull_requests[0].ci_runs[2]"
        self.assert_error(local(fallback_approved_by=dict(approval, who="worker")),
                          f"{base}.fallback_approved_by.who", "owner")
        self.assert_error(local(fallback_approved_by=dict(approval, at="2026-10-20 16:20")),
                          f"{base}.fallback_approved_by.at", "UTC")
        self.assert_error(local(fallback_approved_by=dict(approval, at="2026-10-20T16:20:00+02:00")),
                          f"{base}.fallback_approved_by.at", "UTC")
        self.assert_error(local(fallback_approved_by=dict(approval, instruction=" ")),
                          f"{base}.fallback_approved_by.instruction", "owner instruction")
        self.assert_error(local(fallback_approved_by={"who": "owner", "at": "2026-10-20T16:20:00Z"}),
                          f"{base}.fallback_approved_by.instruction", "missing")
        self.assert_error(local(fallback_approved_by=dict(approval, account="x")),
                          f"{base}.fallback_approved_by.account", "unknown")
        self.assert_error(local(fallback_approved_by="synthetic-owner"),
                          f"{base}.fallback_approved_by", "map")
        self.assert_error(local(executor=None), f"{base}.executor", "fallback_approved_by")

    def test_cli_reports_the_named_error(self):
        text = worked_evidence_ledger().replace("        attempt: 1\n        definition_ref:\n", "        definition_ref:\n", 1)
        code, _, stderr = run_validator(text)
        self.assertNotEqual(code, 0)
        self.assertIn("FAIL: pull_requests[0].ci_runs[0].attempt: must be a positive integer", stderr)


class TestCompletionResultsValidate(unittest.TestCase):
    """Item 1: the GV result record (completion-result-v1) in the ledger."""

    def assert_error(self, records, path, phrase):
        with self.assertRaises(dev_state.GoalRunError) as raised:
            dev_state.validate_completion_results(records)
        self.assertEqual(raised.exception.field, path)
        self.assertIn(phrase, raised.exception.message)

    def test_template_example_validates(self):
        example = evidence_section_example(2)
        self.assertTrue(example.startswith("completion_results:\n"))
        code, stdout, stderr = run_validator(
            "---\nschema_version: 2\nrun_id: example\nrun_status: active\n" + example + "---\n")
        self.assertEqual(code, 0, stderr)
        records = dev_state.read_ledger_block("---\n" + example + "---\n", "completion_results")
        self.assertEqual(records[1]["supersedes"], [records[0]["result_id"]])

    def test_template_section_examples_parse(self):
        ref = dev_state.read_ledger_block("---\n" + evidence_section_example(0) + "---\n", "evidence_ref")
        self.assertEqual(ref, {"run": 130, "job": "build", "attempt": 1})
        approval = dev_state.read_ledger_block("---\n" + evidence_section_example(1) + "---\n",
                                               "fallback_approved_by")
        self.assertIsNone(dev_state._validate_fallback_approved_by(approval, "fallback_approved_by"))

    def test_readiness_never_records_verified(self):
        self.assert_error([result_record(purpose="readiness", outcome="verified")],
                          "completion_results[0].outcome", "outside the readiness vocabulary")
        code, _, stderr = run_validator(ledger_with(
            "completion_results:\n  - profile_version: completion-result-v1\n    result_id: gv-1\n"
            "    run_id: goal-1\n    plan_ref:\n      origin: x\n    purpose: readiness\n"
            "    outcome: verified\n    producer:\n      recorded_by: lead\n"))
        self.assertNotEqual(code, 0)
        self.assertIn("completion_results[0].outcome: 'verified' is outside the readiness vocabulary", stderr)

    def test_vocabulary_per_purpose(self):
        for purpose, outcomes in dev_state.COMPLETION_RESULT_VOCABULARY.items():
            for outcome in outcomes:
                self.assertIsNone(dev_state.validate_completion_results(
                    [result_record(purpose=purpose, outcome=outcome)]))
        self.assert_error([result_record(outcome="evidence_ready")], "completion_results[0].outcome", "final")
        self.assert_error([result_record(purpose="accept")], "completion_results[0].purpose", "final or readiness")

    def test_required_identity_and_writer(self):
        cases = (
            ("profile_version", "completion-result-v2", "completion-result-v1"),
            ("result_id", "", "non-empty"),
            ("run_id", None, "non-empty"),
            ("plan_ref", "sha256:2222", "map"),
            ("producer", None, "map"),
        )
        for name, value, phrase in cases:
            with self.subTest(field=name):
                self.assert_error([dict(result_record(), **{name: value})], f"completion_results[0].{name}", phrase)
        record = result_record()
        record["producer"]["recorded_by"] = "worker"
        self.assert_error([record], "completion_results[0].producer.recorded_by", "lead")
        record["producer"].pop("recorded_by")
        self.assert_error([record], "completion_results[0].producer.recorded_by", "lead")
        self.assert_error({"result_id": "x"}, "completion_results", "list")
        self.assert_error(["gv-1"], "completion_results[0]", "map")

    def test_supersedes_chains_within_one_run_and_purpose(self):
        first = result_record("gv-1", outcome="inconclusive")
        self.assertIsNone(dev_state.validate_completion_results([first, result_record("gv-2", supersedes=["gv-1"])]))
        self.assert_error([first, result_record("gv-1")], "completion_results[1].result_id", "repeats")
        self.assert_error([first, result_record("gv-2", supersedes=["gv-0"])],
                          "completion_results[1].supersedes[0]", "names no earlier result")
        self.assert_error([result_record("gv-2", supersedes=["gv-1"]), first],
                          "completion_results[0].supersedes[0]", "names no earlier result")
        self.assert_error([first, result_record("gv-2", supersedes=["gv-2"])],
                          "completion_results[1].supersedes[0]", "never supersedes itself")
        self.assert_error([first, result_record("gv-2", purpose="readiness", outcome="not_ready",
                                                supersedes=["gv-1"])],
                          "completion_results[1].supersedes[0]", "one (run_id, purpose)")
        self.assert_error([first, result_record("gv-2", run_id="goal-2", supersedes=["gv-1"])],
                          "completion_results[1].supersedes[0]", "one (run_id, purpose)")
        self.assert_error([dict(result_record(), supersedes="gv-0")], "completion_results[0].supersedes", "list")

    def test_no_human_acceptance_fields_are_defined(self):
        section = TEMPLATE.read_text().split(
            "## Completion results and evidence additions (v2.2, Issue #195)", 1)[1].split("\n## ", 1)[0]
        for word in ("/accept", "owner_account", "owner-account setting"):
            self.assertNotIn(f"`{word}`", section)
        self.assertNotIn("owner_account", " ".join(dir(dev_state)))


if __name__ == "__main__":
    unittest.main()
