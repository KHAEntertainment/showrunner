"""Focused checks for #206 lane L2: the `/dev plan` router, Phase 1.5 wiring,
and the Phase 2/Issue/worker no-reask rule."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "dev"

SKILL_MD = SKILL / "SKILL.md"
PHASE2 = SKILL / "phases" / "phase2.md"
WORKER_NEW = SKILL / "agents" / "worker-new.md"
WORKER_FIX = SKILL / "agents" / "worker-fix.md"
CONTRACT = SKILL / "backends" / "contract.md"
TEMPLATE = SKILL / "templates" / "PROJECT_CONTEXT_TEMPLATE.md"

NO_REASK_SENTENCE = "never re-asks a locked decision"
WORKER_NO_REASK = "do not re-ask or re-decide"
WORKER_REPORT_CONFLICT = "report the conflict to the Tech Lead"
CONTRACT_WORKER_GATE = "the worker's implementation-plan gate"


def _router_paths() -> dict[str, str]:
    text = SKILL_MD.read_text(encoding="utf-8")
    heading = "## Phase 0 — Entry Router"
    start = text.index(heading)
    body = text[start + len(heading):]
    end = body.find("\n## ")
    section = body if end == -1 else body[:end]
    paths: dict[str, str] = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == 3 and cells[0].startswith("**") and cells[0].endswith("**"):
            paths[cells[0].strip("*")] = cells[2]
    return paths


def _no_reask_present(text: str) -> bool:
    return NO_REASK_SENTENCE in text


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _contains(text: str, sentence: str) -> bool:
    return sentence in text


class RouterRowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.paths = _router_paths()

    def test_six_request_types(self) -> None:
        self.assertEqual(len(self.paths), 6)

    def test_planning_types_route_through_phase_1_5(self) -> None:
        for request_type in (
            "New Feature / Large Change",
            "Architectural Change",
            "Refactoring",
        ):
            with self.subTest(type=request_type):
                self.assertIn("Phase 1.5", self.paths[request_type])

    def test_non_planning_types_do_not_route_through_phase_1_5(self) -> None:
        for request_type in (
            "New Project",
            "Small Change / Bug Fix",
            "Emergency Hotfix",
        ):
            with self.subTest(type=request_type):
                self.assertNotIn("Phase 1.5", self.paths[request_type])


class WiringTests(unittest.TestCase):
    def test_dev_plan_argument_mode_present(self) -> None:
        self.assertIn(
            "`/dev plan <description>`", SKILL_MD.read_text(encoding="utf-8")
        )

    def test_phase2_no_reask(self) -> None:
        text = PHASE2.read_text(encoding="utf-8")
        self.assertIn("never re-asked", text)
        self.assertIn(NO_REASK_SENTENCE, text)

    def test_worker_prompts_carry_plan_ref(self) -> None:
        self.assertIn("`plan_ref` (SC-1)", WORKER_NEW.read_text(encoding="utf-8"))
        self.assertIn("`plan_ref` (SC-1)", WORKER_FIX.read_text(encoding="utf-8"))

    def test_worker_prompts_do_not_reask_or_redecide(self) -> None:
        self.assertIn(WORKER_NO_REASK, WORKER_NEW.read_text(encoding="utf-8"))
        self.assertIn(WORKER_NO_REASK, WORKER_FIX.read_text(encoding="utf-8"))

    def test_worker_prompts_report_conflict_to_the_lead(self) -> None:
        self.assertIn(WORKER_REPORT_CONFLICT, WORKER_NEW.read_text(encoding="utf-8"))
        self.assertIn(WORKER_REPORT_CONFLICT, WORKER_FIX.read_text(encoding="utf-8"))

    def test_contract_disambiguation(self) -> None:
        self.assertIn(
            "Technical Plan approval is not worker plan approval",
            CONTRACT.read_text(encoding="utf-8"),
        )

    def test_contract_plan_approval_requirement_is_the_worker_gate(self) -> None:
        contract = CONTRACT.read_text(encoding="utf-8")
        self.assertIn("plan-approval requirement", contract)
        self.assertIn(CONTRACT_WORKER_GATE, contract)

    def test_template_plans_row_and_gitignore(self) -> None:
        text = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("`docs/plans/`", text)
        self.assertIn("is never committed (D6.5.5)", text)


class MutationTests(unittest.TestCase):
    """Each key-sentence check must actually read the file: stripping the
    sentence from a copy flips its check to false."""

    CASES = (
        (PHASE2, NO_REASK_SENTENCE),
        (WORKER_NEW, WORKER_NO_REASK),
        (WORKER_FIX, WORKER_NO_REASK),
        (WORKER_NEW, WORKER_REPORT_CONFLICT),
        (WORKER_FIX, WORKER_REPORT_CONFLICT),
        (CONTRACT, CONTRACT_WORKER_GATE),
    )

    def test_removing_each_key_sentence_is_detected(self) -> None:
        for path, sentence in self.CASES:
            with self.subTest(file=path.name, sentence=sentence):
                text = _read(path)
                self.assertTrue(_contains(text, sentence))
                stripped = text.replace(sentence, "")
                self.assertFalse(_contains(stripped, sentence))


if __name__ == "__main__":
    unittest.main()
