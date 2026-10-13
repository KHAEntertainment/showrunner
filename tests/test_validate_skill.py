"""The forbidden-path guard must see the whole shipped repository.

`validate_skill.py` widens its home-path scan beyond the Skill payload
(`skills/dev/`) to `en/`, `zh/`, and root-level markdown, anchored on the
validator's own `__file__` location -- the same anchor the existing
`PROJECT_CONTEXT.md` check uses, and for the same reason: every call site
stages `--skill-dir` elsewhere but always runs this validator from the
project or archive root.

Exercising that anchor means running a *copy* of the validator from a
fabricated project root. Copying only `skills/dev` the way
`test_skill_frontmatter.py` does for its narrower, `--skill-dir`-relative
checks would still resolve `Path(__file__).resolve().parents[1]` to this real
repository, silently scanning the real `en/`/`zh/` trees instead of the
fixture.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "dev"
PROJECT_CONTEXT = ROOT / "PROJECT_CONTEXT.md"
VALIDATOR = ROOT / "scripts" / "validate_skill.py"


class HomePathScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

        shutil.copytree(SKILL, self.root / "skills" / "dev")
        (self.root / "scripts").mkdir(parents=True)
        shutil.copy(VALIDATOR, self.root / "scripts" / "validate_skill.py")
        shutil.copy(PROJECT_CONTEXT, self.root / "PROJECT_CONTEXT.md")

        self.validator = self.root / "scripts" / "validate_skill.py"
        self.skill_dir = self.root / "skills" / "dev"

    def run_validator(self, skill_dir: Path | None = None) -> subprocess.CompletedProcess[str]:
        target = skill_dir if skill_dir is not None else self.skill_dir
        return subprocess.run(
            [sys.executable, str(self.validator), "--skill-dir", str(target)],
            check=False,
            capture_output=True,
            text=True,
        )

    def plant(self, relative: str, content: str) -> Path:
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def test_clean_fixture_passes(self) -> None:
        """Establish the fixture itself is valid before any test mutates it."""
        completed = self.run_validator()
        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_planted_home_path_in_en_fails_and_names_the_file(self) -> None:
        self.plant(
            "en/commands/dev.md",
            "Rollback snapshot: `/Users/alice/Documents/backups`.\n",
        )
        completed = self.run_validator()
        self.assertEqual(1, completed.returncode)
        self.assertIn("en/commands/dev.md", completed.stderr)
        self.assertIn("machine-specific absolute path", completed.stderr)

    def test_removing_the_planted_path_passes(self) -> None:
        planted = self.plant(
            "en/commands/dev.md",
            "Rollback snapshot: `/Users/alice/Documents/backups`.\n",
        )
        failing = self.run_validator()
        self.assertEqual(1, failing.returncode)

        planted.write_text("A rollback snapshot is kept locally.\n", encoding="utf-8")
        passing = self.run_validator()
        self.assertEqual(0, passing.returncode, passing.stderr)

    def test_archive_tree_without_en_or_zh_passes(self) -> None:
        """`en/` and `zh/` are `.gitattributes export-ignore`d; CI's packaging
        job extracts a `git archive` tree that never has them."""
        self.assertFalse((self.root / "en").exists())
        self.assertFalse((self.root / "zh").exists())
        completed = self.run_validator()
        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_planted_home_path_in_zh_fails_and_names_the_file(self) -> None:
        self.plant("zh/commands/dev.md", "备份路径：`/home/carol/backups/`\n")
        completed = self.run_validator()
        self.assertEqual(1, completed.returncode)
        self.assertIn("zh/commands/dev.md", completed.stderr)

    def test_planted_home_path_in_root_markdown_fails_and_names_the_file(self) -> None:
        self.plant("NOTES.md", "See `C:\\Users\\dave\\workspace` for details.\n")
        completed = self.run_validator()
        self.assertEqual(1, completed.returncode)
        self.assertIn("NOTES.md", completed.stderr)

    def test_template_placeholders_do_not_false_positive(self) -> None:
        self.plant(
            "en/commands/dev.md",
            "Use `/Users/<name>/project`, `C:\\path\\to\\skills\\dev`, or `$HOME/project`.\n",
        )
        completed = self.run_validator()
        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_home_path_inside_skill_payload_still_fails(self) -> None:
        """The pre-existing in-payload guard keeps working under the new regex."""
        target = self.skill_dir / "phases" / "phase1.md"
        target.write_text(
            target.read_text(encoding="utf-8") + "\nSee `/home/eve/notes` for background.\n",
            encoding="utf-8",
        )
        completed = self.run_validator()
        self.assertEqual(1, completed.returncode)
        self.assertIn("phase1.md", completed.stderr)

    def test_staged_tree_outside_repo_root_skips_the_extra_scan(self) -> None:
        """`install.sh`'s git-staging mode runs the SOURCE checkout's validator
        against a STAGED copy of the payload elsewhere -- a preflight checkout,
        a git-archive extraction, or the final stage directory -- none of
        which is `repo_root` or under it. Scanning the source's own `en/` in
        that case would fail an install over content that was never staged
        and never ships as part of it, so the extra scan must be skipped for
        any `--skill-dir` outside `repo_root`, while an in-tree validation
        (`--skill-dir` under `repo_root`, as every other test in this suite
        uses) keeps failing on the same leak.
        """
        self.plant(
            "en/commands/dev.md",
            "Rollback snapshot: `/Users/alice/Documents/backups`.\n",
        )

        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        staged_skill_dir = Path(outside.name) / "skills" / "dev"
        shutil.copytree(SKILL, staged_skill_dir)
        self.assertNotIn(
            self.root, staged_skill_dir.parents, "fixture bug: staged copy must be outside repo_root"
        )

        staged = self.run_validator(skill_dir=staged_skill_dir)
        self.assertEqual(0, staged.returncode, staged.stderr)

        in_tree = self.run_validator()
        self.assertEqual(1, in_tree.returncode)
        self.assertIn("en/commands/dev.md", in_tree.stderr)

    def test_home_path_in_url_passes(self) -> None:
        """Mid-URL /Users/ should NOT trigger."""
        self.plant(
            "en/commands/dev.md",
            "See https://api.example.com/Users/svc/status for status.\n",
        )
        completed = self.run_validator()
        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_home_path_with_spaces_and_apostrophe_in_the_name_fails(self) -> None:
        self.plant("en/commands/dev.md", "Backup: `/Users/Jane Doe/Documents/backups`.\n")
        completed = self.run_validator()
        self.assertEqual(1, completed.returncode)
        self.assertIn("en/commands/dev.md", completed.stderr)

    def test_home_path_at_start_of_line_fails(self) -> None:
        """Bare /Users/ at start should trigger."""
        self.plant(
            "en/commands/dev.md",
            "/Users/bbrenner/.ssh/id_rsa\n",
        )
        completed = self.run_validator()
        self.assertEqual(1, completed.returncode)
        self.assertIn("en/commands/dev.md", completed.stderr)

    def test_home_path_at_end_of_line_fails(self) -> None:
        """Bare /Users/ at end of line should trigger."""
        self.plant(
            "en/commands/dev.md",
            "See the file at `/Users/bbrenner/notes`.\n",
        )
        completed = self.run_validator()
        self.assertEqual(1, completed.returncode)
        self.assertIn("en/commands/dev.md", completed.stderr)

    def test_home_path_in_docs_fails(self) -> None:
        """docs/ should be scanned."""
        self.plant(
            "docs/architecture.md",
            "Config path: `/Users/bbrenner/config`.\n",
        )
        completed = self.run_validator()
        self.assertEqual(1, completed.returncode)
        self.assertIn("docs/architecture.md", completed.stderr)

    def test_home_path_with_apostrophe_in_the_name_fails(self) -> None:
        self.plant("en/commands/dev.md", "Backup: `/home/O'Connor/notes`.\n")
        completed = self.run_validator()
        self.assertEqual(1, completed.returncode)
        self.assertIn("en/commands/dev.md", completed.stderr)

    def test_windows_home_path_with_spaces_in_the_name_fails(self) -> None:
        self.plant("en/commands/dev.md", "Backup: `C:\\Users\\Mary Jane\\Desktop`.\n")
        completed = self.run_validator()
        self.assertEqual(1, completed.returncode)
        self.assertIn("en/commands/dev.md", completed.stderr)

    def test_template_placeholders_still_do_not_false_positive_under_the_wider_class(self) -> None:
        """The widened segment class (spaces, apostrophes) must not swallow
        the `<name>` placeholder boundary it was already excluding."""
        self.plant(
            "en/commands/dev.md",
            "Use `/Users/<name>/project`, `C:\\path\\to\\skills\\dev`, or `$HOME/project`.\n",
        )
        completed = self.run_validator()
        self.assertEqual(0, completed.returncode, completed.stderr)


class SuppliedIdentityPinTests(unittest.TestCase):
    """Issue #89: the manifest entry and policy pins fail the validator when removed."""

    PINS = (
        ("backends/traycer.md", ".agent/traycer.env"),
        ("backends/traycer.md", "export TRAYCER_AGENT_ID="),
        ("backends/traycer.md", "git-ignored or excluded"),
        ("backends/traycer.md", "never guesses an id"),
        ("backends/traycer.md", "ask the user once and stop until answered"),
        ("backends/traycer.md", "are not evidence of the caller's identity"),
        ("backends/traycer.md", "**(a) Self-source comparison.**"),
        ("backends/traycer.md", "This is mandatory whenever the source exists, including when the id came from the user's message."),
        ("backends/traycer.md", "**(b) Row corroboration.**"),
        ("backends/traycer.md", "`folderPaths`"),
        ("backends/traycer.md", "(b) alone is the floor and the ledger records that"),
        ("backends/traycer.md", "(b) cannot distinguish two agents that share one worktree and one harness"),
        ("backends/traycer.md", "corroborates it and is the weaker of the two"),
        ("backends/traycer.md", "reduce, and do not eliminate, the chance of accepting a wrong pair"),
        ("backends/traycer.md", "row corroboration accepts a wrong id that belongs to an agent sharing the lead's worktree and harness"),
        ("backends/traycer.md", "Read-only QA and review lanes that share a checkout with the lead are the realistic way this happens."),
        ("backends/traycer.md", "A lead verified by `worktree_match` alone says so to the user in its first status reply."),
        ("backends/traycer.md", "the Preflight step 3 identity checks"),
        ("backends/contract.md", "A partial environment (exactly one identifier) is a host defect"),
        ("backends/contract.md", "the file never recovers it"),
        ("backends/traycer.md", "identity_verification"),
        ("backends/traycer.md", "a partial environment cannot be recovered by the file"),
        ("backends/traycer.md", "reports the partial environment to the user as a host defect"),
        ("backends/traycer.md", "It never sets or unsets `TRAYCER_AGENT_ID` or `TRAYCER_EPIC_ID` itself to make the file apply."),
        ("backends/traycer.md", "verified live for Codex and OpenCode leads"),
        ("backends/traycer.md", "Never invoke `traycer` directly"),
        ("backends/contract.md", "`claude-native` is never available to it"),
        ("backends/contract.md", "`lead.harness` is recorded from the Traycer agent list, never inferred."),
        ("backends/contract.md", "A lead whose harness is not Claude Code selects `traycer` or records `incomplete` and stops."),
        ("backends/contract.md", "Sources are never mixed"),
        ("templates/DEV_STATE_TEMPLATE.md", "`supplied` (the detector chose `traycer` from identifiers in `.agent/traycer.env`)"),
        ("templates/DEV_STATE_TEMPLATE.md", "identity_verification"),
        ("templates/DEV_STATE_TEMPLATE.md", "`self_source_and_worktree_match`"),
        ("templates/DEV_STATE_TEMPLATE.md", "additive under `schema_version: 2`"),
        ("SKILL.md", "never available to a lead whose harness is not Claude Code"),
    )

    # Issue #97: swap-time report-back evidence. Listed literally rather than
    # imported from the validator, so a pin dropped from the validator fails here.
    SWAP_PINS = (
        ("backends/traycer.md", "**Swap-time evidence (after a lead change only).**"),
        ("backends/traycer.md", "It adds no row, termination value, or cause to the mapping"),
        ("backends/traycer.md", "A worker entry with no `dispatched_by` fails this condition"),
        ("backends/traycer.md", "the swap rule never upgrades a truncated read"),
        ("backends/traycer.md", "never the title and never an id mentioned in the body"),
        ("backends/traycer.md", "was sent after the recorded `dispatched_at`"),
        ("backends/traycer.md", "verbatim and in full; a prefix, a different id, or a paraphrase does not match"),
        ("backends/traycer.md", "because a cut read cannot establish absence"),
        ("backends/traycer.md", "Different means a **lead swap**, not an identity failure"),
        ("backends/traycer.md", "a swap never relaxes any Preflight step 3 check"),
        ("backends/contract.md", "**Swap-time evidence is adapter-defined, narrow, and fails closed.**"),
        ("backends/contract.md", "It never upgrades a read that ended `stalled`, `page_cap`, or `time_bound`"),
        ("backends/contract.md", "and anything less stays `absent`"),
        ("backends/contract.md", "It adds no row, termination value, or cause to the mapping"),
        ("agents/report-back.md", "on the **first line**"),
        ("agents/report-back.md", "(for example `Response ID: <id>`), above the seven sections."),
        ("agents/report-back.md", "A missing or mismatched correlation ID fails the lane closed."),
        ("agents/report-back.md", "and a missing or mismatched ID still fails the lane closed"),
        ("templates/DEV_STATE_TEMPLATE.md", "`communication_response_id`, `dispatched_by`, `dispatched_at`, `report_back`"),
        ("templates/DEV_STATE_TEMPLATE.md", "`dispatched_by` and `dispatched_at` are additive under `schema_version: 2`"),
        ("templates/DEV_STATE_TEMPLATE.md", "**The swap-time evidence rule adds no row.**"),
    )

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        shutil.copytree(SKILL, self.root / "skills" / "dev")
        (self.root / "scripts").mkdir(parents=True)
        shutil.copy(VALIDATOR, self.root / "scripts" / "validate_skill.py")
        shutil.copy(PROJECT_CONTEXT, self.root / "PROJECT_CONTEXT.md")
        self.skill_dir = self.root / "skills" / "dev"

    def run_validator(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.root / "scripts" / "validate_skill.py"), "--skill-dir", str(self.skill_dir)],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_clean_fixture_passes(self) -> None:
        completed = self.run_validator()
        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_missing_wrapper_fails_the_manifest(self) -> None:
        (self.skill_dir / "scripts" / "traycer_cli.py").unlink()
        completed = self.run_validator()
        self.assertEqual(1, completed.returncode)
        self.assertIn("missing required file: scripts/traycer_cli.py", completed.stderr)

    def test_removing_each_pinned_sentence_fails(self) -> None:
        for relative, token in self.PINS + self.SWAP_PINS:
            with self.subTest(file=relative, token=token):
                target = self.skill_dir / relative
                original = target.read_text(encoding="utf-8")
                self.assertIn(token, original)
                target.write_text(original.replace(token, "REMOVED"), encoding="utf-8")
                try:
                    completed = self.run_validator()
                finally:
                    target.write_text(original, encoding="utf-8")
                self.assertEqual(1, completed.returncode)
                self.assertIn("missing required policy", completed.stderr)

    def test_a_bare_traycer_route_alone_does_not_satisfy_the_wrapper_pin(self) -> None:
        route = "rtk proxy python3 ${CLAUDE_SKILL_DIR}/scripts/traycer_cli.py"
        for target in sorted(self.skill_dir.rglob("*.md")):
            text = target.read_text(encoding="utf-8")
            if route in text:
                target.write_text(text.replace(route, "rtk proxy traycer"), encoding="utf-8")
        completed = self.run_validator()
        self.assertEqual(1, completed.returncode)
        self.assertIn(route, completed.stderr)


if __name__ == "__main__":
    unittest.main()
