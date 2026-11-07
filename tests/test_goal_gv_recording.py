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


class Unwritable(ValueError):
    """A value the ledger reader cannot read back identically."""


def block_yaml(value, indent=0):
    """Lines of a block-YAML rendering of ``value``: maps, lists, scalars only.

    The ledger reader (``dev_state._goal_scalar``) strips the outer quotes of a
    string and decodes nothing. So a string is written literally between double
    quotes, with no escaping, and a value that cannot be written that way is
    refused (``Unwritable``), never altered: a line break or any control
    character cannot sit on one ledger line. Whether the rest reads back
    identically is proved by ``record_entry``, which reads the entry back.
    """
    pad = " " * indent
    lines = []
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise Unwritable(f"key {key!r}")
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
            elif isinstance(item, (dict, list)) and item:
                raise Unwritable("nested list")
            else:
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
    if value == []:
        return "[]"
    if value == {}:
        return "{}"
    if isinstance(value, str):
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise Unwritable(f"control character in {value!r}")
        return '"' + value + '"'
    raise Unwritable(f"unsupported value {value!r}")


def record_entry(ledger_text, records):
    """The ledger text with ``records`` as its ``completion_results`` block.

    Raises ``Unwritable`` when a value cannot be written, or when the block
    read back by ``dev_state.read_ledger_block`` differs from ``records``. The
    caller's ledger text is never changed; nothing is appended on a refusal.
    """
    block = "completion_results:\n" + "\n".join(block_yaml(records, 2)) + "\n"
    updated = ledger_text.replace("\n---\n\n", "\n" + block + "---\n\n", 1)
    try:
        stored = dev_state.read_ledger_block(updated, "completion_results")
    except Exception as exc:
        raise Unwritable(f"read-back failed: {exc}") from exc
    if stored != records:
        raise Unwritable("read-back differs from the printed record")
    return updated


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

    def record_and_check(self, printed_records, name):
        """Record through the writer, validate, and return the stored records."""
        path = self.dir / name
        path.write_text(record_entry(t.render(self.data), printed_records), encoding="utf-8")
        status, err = self.validate(path)
        self.assertEqual(status, 0, err)
        return dev_state.read_ledger_block(path.read_text(encoding="utf-8"), "completion_results")

    def test_block_yaml_conversion_validates_and_round_trips(self):
        code, raw = self.run_gv(self.data)
        printed = json.loads(raw)
        stored = self.record_and_check([printed], "block.md")
        self.assertEqual(len(stored), 1)
        for key in printed:
            self.assertEqual(stored[0][key], printed[key], key)
        self.assertEqual(stored[0], printed)

    def test_non_ascii_quotes_and_backslashes_round_trip_equal(self):
        # R2-B2: the reader strips the outer quotes and decodes nothing, so a
        # string is written literally. café, quotes and backslashes survive.
        for value in ("café", 'say "hi"', "back\\slash \\n", "it's \"mixed\" \\ é"):
            with self.subTest(value=value):
                code, raw = self.run_gv(self.data, extra=["--consumer-context", value])
                printed = json.loads(raw)
                self.assertEqual(printed["producer"]["consumer_context"], value)
                stored = self.record_and_check([printed], "ctx.md")
                self.assertEqual(stored, [printed])
                self.assertEqual(stored[0]["producer"]["consumer_context"], value)

    def test_a_newline_cannot_be_recorded_and_nothing_is_appended(self):
        # R2-B2: a line break cannot sit on one ledger line. The writer refuses
        # it; the ledger text is not changed.
        code, raw = self.run_gv(self.data, extra=["--consumer-context", "line one\nline two"])
        printed = json.loads(raw)
        self.assertEqual(printed["producer"]["consumer_context"], "line one\nline two")
        before = t.render(self.data)
        with self.assertRaises(Unwritable):
            record_entry(before, [printed])
        self.assertNotIn("completion_results", before)
        self.assertEqual(before, t.render(self.data))

    def test_a_value_that_does_not_read_back_identically_is_refused(self):
        # Fail closed: the read-back is the check, not the writer's confidence.
        _, raw = self.run_gv(self.data)
        printed = json.loads(raw)
        printed["producer"]["consumer_context"] = float("inf")
        with self.assertRaises(Unwritable):
            record_entry(t.render(self.data), [printed])

    def test_supersedes_chain_survives_the_conversion(self):
        _, raw = self.run_gv(self.data)
        first = json.loads(raw)
        self.data["completion_results"] = [first]
        _, raw2 = self.run_gv(self.data, extra=["--supersedes", first["result_id"]])
        second = json.loads(raw2)
        self.assertEqual(second["supersedes"], [first["result_id"]])
        self.data.pop("completion_results")
        stored = self.record_and_check([first, second], "chain.md")
        self.assertEqual(stored, [first, second])

    def test_optional_keys_validate_inside_goal_run_and_not_at_the_root(self):
        # R2-B1: the six optional keys are goal_run fields (dev_state.py
        # _GOAL_RUN_STATE_KEYS). completion_results is the top-level key.
        bad = {"measured": True, "count": -1}
        nested = copy.deepcopy(self.data)
        nested["goal_run"]["context_resets"] = bad
        path = self.dir / "nested.md"
        path.write_text(t.render(nested), encoding="utf-8")
        code, err = self.validate(path)
        self.assertEqual(code, 1, err)
        self.assertIn("goal_run.context_resets.count", err)

        root = copy.deepcopy(self.data)
        root["context_resets"] = bad
        text = t.render(root)
        self.assertNotIn("context_resets", dev_state.parse_goal_run_block(text))
        path = self.dir / "root.md"
        path.write_text(text, encoding="utf-8")
        code, err = self.validate(path)
        self.assertEqual(code, 0, err)

    def test_goal_md_tells_the_lead_to_convert_not_append_as_printed(self):
        goal = GOAL.read_text(encoding="utf-8")
        body = goal[goal.index("### Completion verification"):]
        self.assertIn("block YAML", body)
        self.assertRegex(body, r"flow syntax|JSON")
        self.assertNotIn("append it as printed", body)
        self.assertNotRegex(body, re.compile(r"append[^.]*as printed", re.I))

    def test_goal_md_tells_the_lead_to_record_only_what_reads_back_identically(self):
        # R2-B2, for the lead: the same principle as the test writer.
        goal = GOAL.read_text(encoding="utf-8")
        body = goal[goal.index("### Completion verification"):]
        self.assertIn("reads back identically", body)
        self.assertIn("line break", body)
        self.assertIn("do not record it; report it", body)
        self.assertIn("read the entry back", body)


if __name__ == "__main__":
    unittest.main()
