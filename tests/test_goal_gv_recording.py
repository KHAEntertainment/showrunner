"""Issue #195 lane L195-2b, fix batch 1 (B1): recording a GV result in the ledger.

GV prints JSON. The ledger block reader refuses flow syntax, so the lead cannot
append the printed text. goal.md tells the lead to record the printed record as
a block-YAML ``completion_results`` entry, converting the representation only.

These tests are executed and offline: GV's ``main()`` runs against a fake runner
on a scratch ledger, with no subprocess, network or repository read. The block
writer below is the conversion goal.md describes, kept here as the test's own.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import re
import shlex
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import tests.test_verify_goal_completion as t

ROOT = Path(__file__).resolve().parents[1]
GOAL = ROOT / "skills" / "dev" / "phases" / "goal.md"
dev_state = t.dev_state
gv = t.gv


def block_yaml(value, indent=0):
    """Lines of a block-YAML rendering of ``value``: maps, lists, scalars only.

    Every key and value is kept exactly. Strings are double-quoted JSON strings,
    which the ledger scalar rule reads back unchanged. An empty list or map is
    written inline, as the ledger allows.
    """
    pad = " " * indent
    lines = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{pad}{key}:")
                lines += block_yaml(item, indent + 2)
            else:
                lines.append(f"{pad}{key}: {scalar(item)}")
    else:
        for item in value:
            if isinstance(item, dict) and item:
                sub = block_yaml(item, indent + 2)
                lines.append(f"{pad}- {sub[0].lstrip()}")
                lines += sub[1:]
            else:
                assert not (isinstance(item, (dict, list)) and item), item
                lines.append(f"{pad}- {scalar(item)}")
    return lines


def scalar(value):
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if value == [] or value == {}:
        return "[]" if value == [] else "{}"
    return json.dumps(value)


class GvRecordingTests(unittest.TestCase):
    def setUp(self):
        self._socket = mock.patch.object(
            socket, "socket", side_effect=AssertionError("network forbidden")
        )
        self._socket.start()
        self.addCleanup(self._socket.stop)
        self.tmp = tempfile.TemporaryDirectory(prefix="gv-recording-")
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.ledger = self.dir / "dev-state.md"

        self.data = copy.deepcopy(t.BASE_LEDGER)
        self.data["goal_run"].update(
            policy={"run_time_hours": 24.0, "dispatch_cap_per_issue": 8,
                    "gv_retries": 3, "spend_cap": None},
            next_wake_at=None,
            paused=False,
            counters={"usage_measured": False, "spend": "unknown", "gv_retries_used": 0,
                      "dispatch_counts": {}, "dispatch_request_ids": {}, "request_issues": {}},
        )
        goal_run = self.data["goal_run"]
        self.replacements = {
            "<last line of the turn>": "GOAL-COMPLETE: " + goal_run["source"],
            "<approval_revision>": goal_run["approval_revision"],
            "<lead id>": goal_run["lead"]["agent_id"],
            "<harness>": "codex",
            ".agent/dev-state.md": str(self.ledger),
        }

    def documented_args(self):
        """The argv of the final command exactly as goal.md documents it."""
        goal = GOAL.read_text(encoding="utf-8")
        command = next(
            line for line in goal.splitlines()
            if line.startswith('rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/verify_goal_completion.py"')
        )
        return [self.replacements.get(a, a) for a in shlex.split(command)[4:]]

    def run_gv(self, data, extra=()):
        self.ledger.write_text(t.render(data), encoding="utf-8")
        fake = t.FakeRunner(copy.deepcopy(t.answered(data)))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = gv.main(self.documented_args() + list(extra), runner=fake,
                           sleep=lambda _: None, now=t.NOW)
        return code, out.getvalue()

    def validate(self, path):
        """``dev_state.py --validate`` in process: (exit code, stderr)."""
        err = io.StringIO()
        code = 0
        with mock.patch.object(sys, "argv", ["dev_state.py", "--validate", str(path)]), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            try:
                code = dev_state.main()
            except SystemExit as exc:
                code = exc.code
        return code, err.getvalue()

    def with_results(self, results_lines):
        """The scratch ledger with a ``completion_results`` block spliced in."""
        text = t.render(self.data)
        block = "completion_results:\n" + "\n".join(results_lines) + "\n"
        return text.replace("\n---\n\n", "\n" + block + "---\n\n", 1)

    def test_gv_main_prints_one_json_record_with_exit_zero(self):
        code, raw = self.run_gv(self.data)
        record = json.loads(raw)
        self.assertEqual((code, record["outcome"]), (0, "verified"))
        self.assertEqual(record["producer"]["recorded_by"], "lead")

    def test_raw_json_append_fails_validation(self):
        _, raw = self.run_gv(self.data)
        indented = "  - " + raw.rstrip().replace("\n", "\n    ")
        path = self.dir / "raw.md"
        path.write_text(self.with_results([indented]), encoding="utf-8")
        code, err = self.validate(path)
        self.assertEqual(code, 1, err)
        self.assertIn("completion_results", err)

    def test_block_yaml_conversion_validates_and_round_trips(self):
        code, raw = self.run_gv(self.data)
        printed = json.loads(raw)
        lines = block_yaml([printed], 2)
        path = self.dir / "block.md"
        path.write_text(self.with_results(lines), encoding="utf-8")
        status, err = self.validate(path)
        self.assertEqual(status, 0, err)
        stored = dev_state.read_ledger_block(path.read_text(encoding="utf-8"), "completion_results")
        self.assertEqual(len(stored), 1)
        for key in printed:
            self.assertEqual(stored[0][key], printed[key], key)
        self.assertEqual(stored[0], printed)

    def test_supersedes_chain_survives_the_conversion(self):
        _, raw = self.run_gv(self.data)
        first = json.loads(raw)
        self.data["completion_results"] = [first]
        _, raw2 = self.run_gv(self.data, extra=["--supersedes", first["result_id"]])
        second = json.loads(raw2)
        self.assertEqual(second["supersedes"], [first["result_id"]])
        self.data.pop("completion_results")
        path = self.dir / "chain.md"
        path.write_text(self.with_results(block_yaml([first, second], 2)), encoding="utf-8")
        status, err = self.validate(path)
        self.assertEqual(status, 0, err)

    def test_goal_md_tells_the_lead_to_convert_not_append_as_printed(self):
        goal = GOAL.read_text(encoding="utf-8")
        body = goal[goal.index("### Completion verification"):]
        self.assertIn("block YAML", body)
        self.assertRegex(body, r"flow syntax|JSON")
        self.assertNotIn("append it as printed", body)
        self.assertNotRegex(body, re.compile(r"append[^.]*as printed", re.I))


if __name__ == "__main__":
    unittest.main()
