#!/usr/bin/env python3
"""Issue #193 lane L2: the Phase 0 goal-run row and phases/goal.md.

AC5: the SKILL.md router gains exactly one goal-run row, pointing to
phases/goal.md, and the rest of the table is unchanged.
AC6: every goal_run name, outcome and reason code goal.md uses exists in the
merged goal_run.py, and goal.md calls nothing from goal_authority/goal_recovery.
"""

from __future__ import annotations

import dataclasses
import inspect
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "dev"
SKILL_MD = SKILL_DIR / "SKILL.md"
GOAL_MD = SKILL_DIR / "phases" / "goal.md"
GOAL_RUN = SKILL_DIR / "scripts" / "goal_run.py"
TEMPLATE = SKILL_DIR / "templates" / "DEV_STATE_TEMPLATE.md"

sys.path.insert(0, str(SKILL_DIR / "scripts"))
import goal_run  # noqa: E402

ROUTER_HEADER = "| Type | Criteria | Path |"
PRE_L2_ROUTER_TYPES = [
    "New Project",
    "New Feature / Large Change",
    "Small Change / Bug Fix",
    "Emergency Hotfix",
    "Architectural Change",
    "Refactoring",
]


def router_rows() -> list[str]:
    lines = SKILL_MD.read_text(encoding="utf-8").splitlines()
    start = lines.index(ROUTER_HEADER)
    rows = []
    for line in lines[start + 2:]:
        if not line.startswith("|"):
            break
        rows.append(line)
    return rows


def cells(row: str) -> list[str]:
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


class RouterRowTests(unittest.TestCase):
    """AC5."""

    def test_exactly_one_goal_row_added_and_existing_rows_kept(self):
        rows = router_rows()
        types = [cells(row)[0].strip("*") for row in rows]
        self.assertEqual(types, PRE_L2_ROUTER_TYPES + ["Goal Run"])

    def test_goal_row_path_starts_with_goal_phase_and_keeps_risk_tier(self):
        goal_rows = [row for row in router_rows() if "goal.md" in row]
        self.assertEqual(len(goal_rows), 1)
        _, criteria, path = cells(goal_rows[0])
        self.assertTrue(path.startswith("`phases/goal.md`"), path)
        self.assertIn("3.5 (per risk tier) → 4 → 5", path)
        self.assertIn("approved", criteria.lower())
        self.assertIn("OWNER/REPO#N", criteria)

    def test_goal_phase_is_referenced_only_by_that_row(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertEqual(text.count("goal.md"), 1)
        self.assertTrue(GOAL_MD.is_file())


def goal_run_vocabulary() -> set[str]:
    """Names goal_run.py itself defines: public API, Result members, public
    dataclass fields, public function parameters, and every string literal or
    double-backticked token in its source (outcomes, reason codes, detail keys,
    classifications)."""
    names = set(goal_run.__all__)
    names |= {"outcome", "reason", "value", "detail", "ok", "may_proceed", "to_dict"}
    for public in goal_run.__all__:
        obj = getattr(goal_run, public)
        if dataclasses.is_dataclass(obj):
            names |= {f.name for f in dataclasses.fields(obj)}
        elif inspect.isfunction(obj):
            names |= set(inspect.signature(obj).parameters)
    source = GOAL_RUN.read_text(encoding="utf-8")
    names |= set(re.findall(r"""["']([a-z_][a-z0-9_]*)["']""", source))
    names |= set(re.findall(r"``([a-z_][a-z0-9_]*)``", source))
    return names


def ledger_goal_fields() -> set[str]:
    """Keys of the documented goal_run worked example in the template."""
    block = re.search(
        r"^## Goal run record schema \(Issue #193\).*?^```yaml\n(.*?)^```",
        TEMPLATE.read_text(encoding="utf-8"),
        re.M | re.S,
    ).group(1)
    return set(re.findall(r"^\s*([a-z_][a-z0-9_]*):", block, re.M))


# Ledger and Dev names goal.md may use that goal_run.py does not define.
DEV_NAMES = {"goal_run", "next_action", "skill_dir", "true", "false", "null"}


class GoalPhaseApiTests(unittest.TestCase):
    """AC6."""

    def setUp(self):
        self.text = GOAL_MD.read_text(encoding="utf-8")
        self.tokens = re.findall(r"`([^`\n]+)`", self.text)

    def test_every_called_function_is_public_goal_run_api(self):
        calls = set()
        for token in self.tokens:
            calls |= set(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\(", token))
        self.assertTrue(calls, "goal.md names no calls")
        methods = {"to_dict", "dispatch_count"}
        unknown = sorted(c for c in calls if c not in goal_run.__all__ and c not in methods)
        self.assertEqual(unknown, [])
        for name in calls - methods:
            self.assertTrue(callable(getattr(goal_run, name)), name)

    def test_every_named_identifier_exists_in_goal_run_or_the_ledger(self):
        allowed = goal_run_vocabulary() | ledger_goal_fields() | DEV_NAMES
        identifiers = {t for t in self.tokens if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", t)}
        # All-caps tokens are marker words and UTC suffixes (`WAKE`, `Z`): they
        # must occur literally in goal_run.py's source.
        source = GOAL_RUN.read_text(encoding="utf-8")
        literal_caps = {t for t in identifiers if t.isupper() and t in source}
        unknown = sorted(identifiers - allowed - literal_caps)
        self.assertEqual(unknown, [], "goal.md names identifiers goal_run.py does not define")

    def test_outcomes_named_are_the_documented_vocabulary(self):
        doc = goal_run.__doc__
        vocabulary = re.search(r"Result outcome vocabulary:(.*?)``Result.ok``", doc, re.S).group(1)
        documented = set(re.findall(r"``([a-z_]+)``", vocabulary))
        for outcome in ("accept", "invalid", "complete", "incomplete",
                        "claim_requires_gv", "protected_stop"):
            self.assertIn(outcome, documented)
            self.assertIn(f"`{outcome}`", self.text)
        self.assertNotIn("`unavailable`", self.text)

    def test_no_authority_or_recovery_module_call(self):
        self.assertNotIn("goal_authority", self.text)
        self.assertNotIn("goal_recovery", self.text)
        self.assertNotIn("TBD", self.text)

    def test_states_runtime_dependency_and_sole_writer(self):
        self.assertIn("scripts/goal_run.py", self.text)
        self.assertIn("sole writer", self.text)
        self.assertIn("existing Dev gates govern", self.text)


if __name__ == "__main__":
    unittest.main()
