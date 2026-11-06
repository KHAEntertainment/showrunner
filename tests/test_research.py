"""Focused checks for #207 lane L4: the C1 read-only research lane and the C2
pinned `advise-project-approach` provider wiring.

Content assertions pin each key rule; a per-sentence mutation check proves each
assertion reads the file it checks. The locator run uses temporary fixture
roots only — never the developer's real skill directory or plugin cache.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "dev"

RESEARCH = SKILL / "research.md"
AB_RECORD = ROOT / "docs" / "v2.2" / "research-ab-record.md"
RESEARCHER = SKILL / "agents" / "researcher.md"
PHASE15 = SKILL / "phases" / "phase1.5.md"
TEMPLATE = SKILL / "templates" / "TECHNICAL_PLAN_TEMPLATE.md"
SCRIPT = SKILL / "scripts" / "locate_pinned_skill.py"

SKILL_NAME = "example-skill"
PINNED_COMMIT = "abc1234"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _contains(text: str, sentence: str) -> bool:
    return sentence in text


class ResearchContentTests(unittest.TestCase):
    def test_research_is_read_only(self) -> None:
        self.assertIn(
            "no writes, no installs, no network-mutating calls, no provider cost",
            _read(RESEARCH),
        )

    def test_c2_falls_back_visibly_with_cause(self) -> None:
        text = _read(RESEARCH)
        self.assertIn("A visible fallback to C1", text)
        self.assertIn("the `cause` is shown to the user and recorded", text)

    def test_c2_is_never_installed_automatically(self) -> None:
        self.assertIn(
            "Never install, update, or fetch the pinned provider automatically",
            _read(RESEARCH),
        )

    def test_fallback_is_never_a_completed_step(self) -> None:
        self.assertIn(
            "A fallback is never reported as a completed research step",
            _read(RESEARCH),
        )

    def test_needs_input_returns_to_the_lead(self) -> None:
        self.assertIn(
            "A provider `needs_input` returns to the lead",
            _read(RESEARCH),
        )

    def test_wayfinder_is_not_auto_run(self) -> None:
        text = _read(RESEARCH)
        self.assertIn("are not default and never auto-run", text)
        self.assertIn("never auto-run because installed", text)

    def test_c3_is_conditional_and_not_invoked(self) -> None:
        self.assertIn("is conditional and not invoked here", _read(RESEARCH))

    def test_sc5_result_types_are_named(self) -> None:
        text = _read(RESEARCH)
        for token in ("finding", "needs_input", "not_available", "drift", "error"):
            with self.subTest(token=token):
                self.assertIn(token, text)

    def test_writes_installs_and_cost_are_unconditionally_forbidden(self) -> None:
        self.assertIn(
            "Writes, installs, network mutation and provider cost are unconditionally forbidden.",
            _read(RESEARCH),
        )

    def test_scoped_approval_applies_only_to_sources(self) -> None:
        self.assertIn(
            "scoped approval applies only to sources, never to writes, installs, network mutation or provider cost.",
            _read(RESEARCH),
        )

    def test_pin_unconfirmed_is_a_visible_fallback(self) -> None:
        self.assertIn("cause `pin_unconfirmed`", _read(RESEARCH))

    def test_documented_roots_are_listed(self) -> None:
        self.assertIn(
            "`~/.agents/skills`, `~/.claude/skills`, `<repo>/.claude/skills`, `~/.claude/plugins/cache`",
            _read(RESEARCH),
        )

    def test_locator_skips_missing_roots_and_adds_no_others(self) -> None:
        text = _read(RESEARCH)
        self.assertIn("The locator skips missing roots", text)
        self.assertIn(
            "The lead never adds other paths, and nothing is searched automatically beyond that list.",
            text,
        )

    def test_command_shape_and_exit_codes_are_documented(self) -> None:
        text = _read(RESEARCH)
        self.assertIn(
            "rtk proxy python3 ${CLAUDE_SKILL_DIR}/scripts/locate_pinned_skill.py",
            text,
        )
        self.assertIn("exit 0 is `present`", text)

    def test_present_dispatches_the_researcher_in_c2_mode(self) -> None:
        self.assertIn("dispatch the researcher in C2 mode", _read(RESEARCH))

    def test_locator_availability_is_separate_from_provider_result(self) -> None:
        text = _read(RESEARCH)
        self.assertIn("Locator availability vs provider result", text)
        self.assertIn("Availability is its own field", text)
        self.assertIn("`finding` only for an evidenced answer", text)
        self.assertIn("A locator fallback is recorded as `not_available`", text)

    def test_usage_error_branch_is_documented(self) -> None:
        text = _read(RESEARCH)
        self.assertIn(
            "parse stdout as JSON only when it is present and valid",
            text,
        )
        self.assertIn("cause `usage_error`", text)

    def test_confirmed_pin_label(self) -> None:
        text = _read(RESEARCH)
        self.assertIn("The pin below is **confirmed by the owner**", text)
        self.assertIn("C2 may activate against this pin.", text)

    def test_confirmed_pin_cites_the_owner_ruling(self) -> None:
        self.assertIn("`ruling-207-pin-2026-11-05`", _read(RESEARCH))

    def test_repin_or_drift_still_falls_back_with_pin_unconfirmed(self) -> None:
        text = _read(RESEARCH)
        self.assertIn(
            "Precondition: C2 runs only once the pin is owner-confirmed.", text
        )
        self.assertIn("a new pin, or after drift until re-confirmed", text)
        self.assertIn("cause `pin_unconfirmed`", text)

    def test_confirmation_did_not_change_the_pin_values(self) -> None:
        text = _read(RESEARCH)
        self.assertIn("**skill**: `advise-project-approach`", text)
        self.assertIn("**commit**: none", text)
        self.assertIn(
            "sha256:2386030e843dd13158bf7fb7e129715718bf36c2e29c73e3f9249fc22404896c",
            text,
        )

    def test_evidence_order_repository_and_primary_docs_first(self) -> None:
        self.assertIn("Repository and primary documentation first", _read(RESEARCH))

    def test_question_counts_never_become_the_user_script(self) -> None:
        self.assertIn("templates never become the user script", _read(RESEARCH))

    def test_phase15_step2_points_at_research(self) -> None:
        text = _read(PHASE15)
        self.assertIn("${CLAUDE_SKILL_DIR}/research.md", text)
        self.assertIn("**C1** runs always", text)
        self.assertIn("**C2** is optional", text)
        self.assertIn("A provider `needs_input` returns to the lead", text)
        self.assertIn("never report the fallback as a completed research step", text)

    def test_refactoring_skips_the_research_step(self) -> None:
        self.assertIn(
            "The lite Phase 1.5 for Refactoring skips this step entirely.",
            _read(PHASE15),
        )

    def test_researcher_agent_is_read_only_and_cites(self) -> None:
        text = _read(RESEARCHER)
        self.assertIn(
            "No writes, no installs, no network-mutating calls, no provider cost.",
            text,
        )
        self.assertIn("exact location and revision", text)

    def test_researcher_has_c1_and_c2_modes(self) -> None:
        text = _read(RESEARCHER)
        self.assertIn("**C1 mode**", text)
        self.assertIn("**C2 mode**", text)
        self.assertIn("`<path>/SKILL.md` as provider guidance", text)
        self.assertIn("Provenance is the pin plus the returned path and digest", text)

    def test_c2_does_not_narrow_sources_to_the_provider(self) -> None:
        text = _read(RESEARCHER)
        self.assertIn("never to narrow the allowed source list to the provider directory", text)

    def test_researcher_output_never_user_facing_questions(self) -> None:
        self.assertIn("never user-facing questions", _read(RESEARCHER))

    def test_researcher_references_report_back(self) -> None:
        self.assertIn(
            "${CLAUDE_SKILL_DIR}/agents/report-back.md",
            _read(RESEARCHER),
        )

    def test_researcher_inputs_paragraph(self) -> None:
        self.assertIn("You are given: the mode (C1 or C2)", _read(RESEARCHER))

    def test_template_has_a_research_section(self) -> None:
        text = _read(TEMPLATE)
        self.assertIn("## Research findings and provider provenance", text)
        self.assertIn("**locator**", text)
        self.assertIn("A locator fallback is recorded with no finding", text)
        self.assertIn("provider name and pin", text)
        self.assertIn("unresolved questions", text)


class ResearchAbRecordTests(unittest.TestCase):
    """The three-effort A/B value evidence record (M2 charter §2 criterion 4)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(AB_RECORD)

    def test_cites_the_sdp_a_b_value_gate(self) -> None:
        self.assertIn("SDP l.81", self.text)
        self.assertIn(
            "Run the A/B value gate over three real planning efforts before superiority claims/promotion.",
            self.text,
        )

    def test_cites_charter_criterion_4(self) -> None:
        self.assertIn("§2, criterion 4", self.text)
        self.assertIn(
            "Three-real-effort A/B value evidence recorded before any superiority/promotion claim",
            self.text,
        )

    def test_cites_the_owner_rulings(self) -> None:
        self.assertIn("`ruling-207-pin-2026-11-05`", self.text)
        self.assertIn("`ruling-207-ab-u1-2026-11-05`", self.text)
        self.assertIn(
            "It supersedes `ruling-207-ab-efforts-2026-11-05`", self.text
        )

    def test_no_claim_until_all_three_efforts_are_recorded(self) -> None:
        self.assertIn(
            "No superiority or promotion claim is made until all three efforts are recorded",
            self.text,
        )

    def test_arms_are_defined(self) -> None:
        self.assertIn("C1 built-in research only", self.text)
        self.assertIn("C1 + C2 pinned provider", self.text)

    def test_each_arm_records_locator_and_sc5_result(self) -> None:
        self.assertIn("its locator result", self.text)
        self.assertIn("its SC-5 result", self.text)

    def test_metric_columns_are_named(self) -> None:
        for column in (
            "date",
            "plan_ref (origin / approved revision)",
            "consequential misses",
            "repeated or low-value questions",
            "rounds",
            "wall time",
            "user burden (owner review minutes)",
            "C2 locator + result",
            "evidence links",
            "recorder",
        ):
            with self.subTest(column=column):
                self.assertIn(column, self.text)

    def test_three_named_effort_sections(self) -> None:
        for heading in (
            "## 5. Effort 1 — U1 unified CLI",
            "## 6. Effort 2 — U1 workspace panel",
            "## 7. Effort 3 — U1 Scout tool",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, self.text)

    def test_each_effort_is_research_only_over_the_u1_outline(self) -> None:
        self.assertEqual(
            3,
            self.text.count(
                "research only over the existing U1 outline (the foreman epic artifact "
                "`u1-binary-components-phase`)"
            ),
        )
        self.assertIn(
            "nothing designed or built, the U1 page not edited, no U1 Issues filed",
            self.text,
        )

    def test_efforts_run_inside_m2_without_pulling_in_other_work(self) -> None:
        self.assertIn(
            "they run inside M2: no work slated for another milestone is fetched and pulled in here",
            self.text,
        )

    def test_owner_reviews_blind_before_the_key_is_revealed(self) -> None:
        self.assertIn(
            "The owner reviews both outputs per effort blind (labelled X/Y), and the A/B key is revealed after review.",
            self.text,
        )

    def test_effort_sections_do_not_name_the_plans(self) -> None:
        for token in ("M3", "M4", "completion-verifier"):
            with self.subTest(token=token):
                self.assertNotIn(token, self.text)

    def test_every_effort_starts_pending(self) -> None:
        self.assertEqual(3, self.text.count("**Status: pending**"))

    def test_recording_rule(self) -> None:
        self.assertIn("Measured values only.", self.text)
        self.assertIn('"not run" and "unknown" stay explicit', self.text)
        self.assertIn(
            "A C2 fallback is recorded as a fallback, never as a B-arm result.",
            self.text,
        )

    def test_comparison_stays_empty_until_three_of_three(self) -> None:
        self.assertIn("## 8. Comparison", self.text)
        self.assertIn("Empty until 3/3.", self.text)


class MutationTests(unittest.TestCase):
    """Each key-sentence check must actually read the file: stripping the
    sentence from a copy flips its check to false."""

    CASES = (
        (RESEARCH, "no writes, no installs, no network-mutating calls, no provider cost"),
        (RESEARCH, "A visible fallback to C1"),
        (RESEARCH, "the `cause` is shown to the user and recorded"),
        (RESEARCH, "Never install, update, or fetch the pinned provider automatically"),
        (RESEARCH, "A fallback is never reported as a completed research step"),
        (RESEARCH, "A provider `needs_input` returns to the lead"),
        (RESEARCH, "never auto-run because installed"),
        (RESEARCH, "is conditional and not invoked here"),
        (RESEARCH, "Writes, installs, network mutation and provider cost are unconditionally forbidden."),
        (RESEARCH, "scoped approval applies only to sources, never to writes, installs, network mutation or provider cost."),
        (RESEARCH, "cause `pin_unconfirmed`"),
        (RESEARCH, "The locator skips missing roots"),
        (RESEARCH, "The lead never adds other paths, and nothing is searched automatically beyond that list."),
        (RESEARCH, "exit 0 is `present`"),
        (RESEARCH, "dispatch the researcher in C2 mode"),
        (RESEARCH, "Availability is its own field"),
        (RESEARCH, "`finding` only for an evidenced answer"),
        (RESEARCH, "A locator fallback is recorded as `not_available`"),
        (RESEARCH, "parse stdout as JSON only when it is present and valid"),
        (RESEARCH, "cause `usage_error`"),
        (RESEARCH, "The pin below is **confirmed by the owner**"),
        (RESEARCH, "C2 may activate against this pin."),
        (RESEARCH, "`ruling-207-pin-2026-11-05`"),
        (RESEARCH, "a new pin, or after drift until re-confirmed"),
        (RESEARCH, "Repository and primary documentation first"),
        (RESEARCH, "templates never become the user script"),
        (RESEARCH, "are not default and never auto-run"),
        (PHASE15, "The lite Phase 1.5 for Refactoring skips this step entirely."),
        (PHASE15, "**C1** runs always"),
        (PHASE15, "**C2** is optional"),
        (PHASE15, "A provider `needs_input` returns to the lead"),
        (PHASE15, "never report the fallback as a completed research step"),
        (RESEARCHER, "No writes, no installs, no network-mutating calls, no provider cost."),
        (RESEARCHER, "**C2 mode**"),
        (RESEARCHER, "`<path>/SKILL.md` as provider guidance"),
        (RESEARCHER, "never to narrow the allowed source list to the provider directory"),
        (RESEARCHER, "never user-facing questions"),
        (RESEARCHER, "${CLAUDE_SKILL_DIR}/agents/report-back.md"),
        (RESEARCHER, "You are given: the mode (C1 or C2)"),
        (TEMPLATE, "provider name and pin"),
        (TEMPLATE, "unresolved questions"),
        (RESEARCH, "The pin below is **confirmed by the owner**"),
        (RESEARCH, "C2 may activate against this pin."),
        (RESEARCH, "`ruling-207-pin-2026-11-05`"),
        (RESEARCH, "a new pin, or after drift until re-confirmed"),
        (AB_RECORD, "No superiority or promotion claim is made until all three efforts are recorded"),
        (AB_RECORD, "C1 built-in research only"),
        (AB_RECORD, "C1 + C2 pinned provider"),
        (AB_RECORD, "its locator result"),
        (AB_RECORD, "its SC-5 result"),
        (AB_RECORD, "plan_ref (origin / approved revision)"),
        (AB_RECORD, "consequential misses"),
        (AB_RECORD, "repeated or low-value questions"),
        (AB_RECORD, "user burden (owner review minutes)"),
        (AB_RECORD, "C2 locator + result"),
        (AB_RECORD, "evidence links"),
        (AB_RECORD, "recorder"),
        (AB_RECORD, "## 5. Effort 1 — U1 unified CLI"),
        (AB_RECORD, "## 6. Effort 2 — U1 workspace panel"),
        (AB_RECORD, "## 7. Effort 3 — U1 Scout tool"),
        (AB_RECORD, "research only over the existing U1 outline (the foreman epic artifact `u1-binary-components-phase`)"),
        (AB_RECORD, "they run inside M2: no work slated for another milestone is fetched and pulled in here"),
        (AB_RECORD, "The owner reviews both outputs per effort blind (labelled X/Y), and the A/B key is revealed after review."),
        (AB_RECORD, "**Status: pending**"),
        (AB_RECORD, "Measured values only."),
        (AB_RECORD, '"not run" and "unknown" stay explicit'),
        (AB_RECORD, "A C2 fallback is recorded as a fallback, never as a B-arm result."),
        (AB_RECORD, "Empty until 3/3."),
    )

    def test_removing_each_key_sentence_is_detected(self) -> None:
        for path, sentence in self.CASES:
            with self.subTest(file=path.name, sentence=sentence):
                text = _read(path)
                self.assertTrue(_contains(text, sentence))
                stripped = text.replace(sentence, "")
                self.assertFalse(_contains(stripped, sentence))


def _load_locator() -> types.ModuleType:
    module = types.ModuleType("locate_pinned_skill")
    module.__file__ = str(SCRIPT)
    source = SCRIPT.read_text(encoding="utf-8")
    exec(compile(source, str(SCRIPT), "exec"), module.__dict__)  # noqa: S102
    return module


class LocatorFixtureRunTests(unittest.TestCase):
    """The C2 locator's three verdicts, run against temporary fixture roots."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.locator = _load_locator()

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.root = self.base / "roots"
        self.root.mkdir()

    def write_skill(self, directory: Path, body: str = "Example.\n") -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "SKILL.md").write_bytes(
            f"---\nname: {directory.name}\n---\n\n{body}".encode("utf-8")
        )
        return directory

    def locate(self, digest: str, *roots: Path) -> subprocess.CompletedProcess[str]:
        arguments = ["--skill", SKILL_NAME, "--commit", PINNED_COMMIT, "--digest", digest]
        for root in roots or (self.root,):
            arguments += ["--root", str(root)]
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_present_when_the_pinned_copy_is_found(self) -> None:
        skill_dir = self.write_skill(self.root / SKILL_NAME)
        digest = self.locator.directory_digest(skill_dir)

        completed = self.locate(digest)
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn('"status": "present"', completed.stdout)

    def test_not_available_when_no_candidate_exists(self) -> None:
        completed = self.locate("0" * 64)
        self.assertEqual(2, completed.returncode, completed.stdout)
        self.assertIn('"status": "not_available"', completed.stdout)

    def test_drift_when_the_copy_no_longer_matches(self) -> None:
        skill_dir = self.write_skill(self.root / SKILL_NAME)
        digest = self.locator.directory_digest(skill_dir)
        (skill_dir / "SKILL.md").write_bytes(
            b"---\nname: example-skill\n---\n\nDrifted.\n"
        )

        completed = self.locate(digest)
        self.assertEqual(2, completed.returncode, completed.stdout)
        self.assertIn('"status": "drift"', completed.stdout)

    def test_present_with_the_documented_multi_root_shape(self) -> None:
        """The documented command shape — repeatable --root, missing roots
        skipped — locates the pinned copy."""
        agents = self.base / "agents-skills"
        claude = self.base / "claude-skills"
        repo = self.base / "repo" / ".claude" / "skills"
        cache = self.base / "plugins-cache"
        for directory in (agents, claude, repo, cache):
            directory.mkdir(parents=True, exist_ok=True)
        skill_dir = self.write_skill(cache / SKILL_NAME)
        digest = self.locator.directory_digest(skill_dir)
        missing = self.base / "does-not-exist"

        completed = self.locate(digest, agents, claude, repo, cache, missing)
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn('"status": "present"', completed.stdout)

    def test_usage_error_leaves_stdout_empty(self) -> None:
        """A --root that is not a directory is a usage error: exit 1, empty
        stdout, plain stderr (no JSON)."""
        not_a_dir = self.base / "not-a-directory"
        not_a_dir.write_bytes(b"not a directory\n")

        completed = self.locate("0" * 64, not_a_dir)
        self.assertEqual(1, completed.returncode, completed.stdout)
        self.assertEqual("", completed.stdout)
        self.assertIn("--root is not a directory", completed.stderr)


if __name__ == "__main__":
    unittest.main()
