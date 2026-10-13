"""Exercise scripts/check_version_sync.py against throwaway plugin trees."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_version_sync.py"


def skill_text(version: str) -> str:
    return f"---\nname: dev\nversion: {version}\n---\nbody\n"


class VersionSyncTests(unittest.TestCase):
    def run_check(self, *, skill="2.1.2+upstream.abc1234", plugin="2.1.2", tag=None,
                  plugin_json=None, skill_md=None, extra_catalog=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            shutil.copy2(SCRIPT, root / "scripts" / "check_version_sync.py")
            (root / "skills" / "dev").mkdir(parents=True)
            (root / ".claude-plugin").mkdir()
            if skill_md is not False:
                (root / "skills" / "dev" / "SKILL.md").write_text(
                    skill_md if skill_md is not None else skill_text(skill), encoding="utf-8")
            if plugin_json is not False:
                (root / ".claude-plugin" / "plugin.json").write_text(
                    plugin_json if plugin_json is not None else json.dumps({"name": "dev-skill", "version": plugin}),
                    encoding="utf-8")
            if extra_catalog is not None:
                (root / ".claude-plugin" / "marketplace.json").write_text(extra_catalog, encoding="utf-8")
            argv = [sys.executable, str(root / "scripts" / "check_version_sync.py")]
            if tag is not None:
                argv += ["--tag", tag]
            return subprocess.run(argv, text=True, capture_output=True, check=False)

    def test_agreement_without_a_local_catalog_passes(self):
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK: version 2.1.2 agrees", result.stdout)

    def test_matching_tag_passes(self):
        self.assertEqual(self.run_check(tag="v2.1.2").returncode, 0)

    def test_build_metadata_is_stripped_before_comparing(self):
        self.assertEqual(self.run_check(skill="2.1.2+other.build").returncode, 0)

    def test_skill_mismatch_is_rejected_with_a_table(self):
        result = self.run_check(skill="2.1.1+upstream.abc1234")
        self.assertEqual(result.returncode, 1)
        self.assertIn("version sites disagree", result.stderr)
        self.assertIn("skills/dev/SKILL.md frontmatter", result.stderr)

    def test_plugin_mismatch_is_rejected(self):
        self.assertEqual(self.run_check(plugin="2.1.1").returncode, 1)

    def test_tag_mismatch_is_rejected(self):
        result = self.run_check(tag="v2.1.1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("--tag", result.stderr)

    def test_unprefixed_or_unparseable_tag_is_rejected(self):
        self.assertEqual(self.run_check(tag="2.1.2").returncode, 1)
        self.assertEqual(self.run_check(tag="vtwo").returncode, 1)

    def test_missing_plugin_json_fails_closed(self):
        result = self.run_check(plugin_json=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("cannot read file", result.stderr)

    def test_malformed_plugin_json_fails_closed(self):
        result = self.run_check(plugin_json="{not json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("invalid JSON", result.stderr)

    def test_missing_or_unversioned_skill_fails_closed(self):
        self.assertEqual(self.run_check(skill_md=False).returncode, 1)
        self.assertEqual(self.run_check(skill_md="no frontmatter\n").returncode, 1)
        self.assertEqual(self.run_check(skill_md="---\nname: dev\n---\n").returncode, 1)

    def test_non_string_plugin_version_fails_closed(self):
        self.assertEqual(self.run_check(plugin_json='{"version": 2}').returncode, 1)

    def test_a_stray_catalog_is_ignored_even_when_it_disagrees(self):
        stale = json.dumps({"plugins": [{"name": "dev-skill", "version": "0.0.1",
                                         "source": {"ref": "v0.0.1"}}]})
        self.assertEqual(self.run_check(extra_catalog=stale).returncode, 0)

    def test_shipped_tree_agrees_with_the_script(self):
        result = subprocess.run([sys.executable, str(SCRIPT)], text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
