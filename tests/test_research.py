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
        self.assertIn("never auto-run because installed", _read(RESEARCH))

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

    def test_phase15_step2_points_at_research(self) -> None:
        text = _read(PHASE15)
        self.assertIn("${CLAUDE_SKILL_DIR}/research.md", text)
        self.assertIn("**C1** runs always", text)
        self.assertIn("**C2** is optional", text)

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

    def test_template_has_a_research_section(self) -> None:
        text = _read(TEMPLATE)
        self.assertIn("## Research findings and provider provenance", text)
        self.assertIn("**locator**", text)
        self.assertIn("A locator fallback is recorded with no finding", text)


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
        (PHASE15, "The lite Phase 1.5 for Refactoring skips this step entirely."),
        (PHASE15, "**C1** runs always"),
        (PHASE15, "**C2** is optional"),
        (RESEARCHER, "No writes, no installs, no network-mutating calls, no provider cost."),
        (RESEARCHER, "**C2 mode**"),
        (RESEARCHER, "`<path>/SKILL.md` as provider guidance"),
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


if __name__ == "__main__":
    unittest.main()
