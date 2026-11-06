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


if __name__ == "__main__":
    unittest.main()
