"""Focused checks for #206 lane L1: Phase 1.5 core and the Technical Plan template.

Assertions cover only what the lane creates: the phase file and template exist,
the disambiguation and intake sentences are present, the template sections and
provisional `plan_ref` fields are present, and the Step 2 research step points
at the C1/C2 lane instead of a placeholder.
"""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "dev"

PHASE = SKILL / "phases" / "phase1.5.md"
TEMPLATE = SKILL / "templates" / "TECHNICAL_PLAN_TEMPLATE.md"

TEMPLATE_SECTIONS = (
    "Intent and destination",
    "Source documents and provenance",
    "Locked decisions",
    "Gaps",
    "Approach",
    "Affected areas",
    "Verification",
    "Amendments",
)

PLAN_REF_FIELDS = (
    "origin",
    "source_revision",
    "approved_revision",
    "authority",
    "evidence",
    "session",
    "harness",
)


class Phase15FilesTests(unittest.TestCase):
    def test_phase_and_template_exist(self) -> None:
        self.assertTrue(PHASE.is_file(), f"missing {PHASE}")
        self.assertTrue(TEMPLATE.is_file(), f"missing {TEMPLATE}")


class Phase15ContentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.phase = PHASE.read_text(encoding="utf-8")

    def test_disambiguation_sentence_present(self) -> None:
        self.assertIn(
            "Technical Plan approval is not worker plan approval.",
            self.phase,
        )

    def test_foreign_directives_listed_once_as_not_followed(self) -> None:
        self.assertIn("listed once in the ledger as not followed", self.phase)

    def test_no_harness_dependency_rule_present(self) -> None:
        self.assertIn(
            "does not depend on any harness's plan mode or tool names",
            self.phase,
        )

    def test_research_step_is_defined_not_placeholder(self) -> None:
        # L4 (#207) filled the Step 2 placeholder; it is no longer a placeholder.
        self.assertNotIn("Research (C1/C2), defined by #207", self.phase)
        self.assertIn("${CLAUDE_SKILL_DIR}/research.md", self.phase)

    def test_plan_ref_cites_sc1_and_d4_invariant(self) -> None:
        self.assertIn("SC-1", self.phase)
        self.assertIn("`approval_revision` equals `plan_ref.approved_revision`", self.phase)


class TemplateContentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.template = TEMPLATE.read_text(encoding="utf-8")

    def test_all_sections_present(self) -> None:
        for section in TEMPLATE_SECTIONS:
            with self.subTest(section=section):
                self.assertIn(section, self.template)

    def test_plan_ref_fields_present(self) -> None:
        for field in PLAN_REF_FIELDS:
            with self.subTest(field=field):
                self.assertIn(field, self.template)

    def test_plan_ref_cites_sc1_and_d4_invariant(self) -> None:
        self.assertIn("SC-1", self.template)
        self.assertIn("`approval_revision` equals `plan_ref.approved_revision`", self.template)

    def test_source_documents_and_provenance_fields(self) -> None:
        for field in ("**origin**", "**revision or digest**", "**directives not followed**"):
            with self.subTest(field=field):
                self.assertIn(field, self.template)
        self.assertIn("the supplied source's locator lives in this section", self.template)


if __name__ == "__main__":
    unittest.main()
