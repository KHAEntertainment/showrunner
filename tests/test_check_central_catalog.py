"""Exercise scripts/check_central_catalog.py: every failure branch, no network."""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_central_catalog as cc  # noqa: E402

COMMIT = "a" * 40
VERSION = "2.1.2"
TAG = "v2.1.2"


def catalog(**overrides):
    entry = {"name": "dev-skill", "source": {"source": "url", "url": cc.PLUGIN_URL, "ref": TAG}}
    entry.update(overrides)
    return {"name": "kha-marketplace", "plugins": [{"name": "view-limits"}, entry]}


def resolver(commit=COMMIT):
    return lambda url, ref: commit


def reader(head=COMMIT, name="dev-skill", version=VERSION):
    return lambda url, ref: (head, {"name": name, "version": version})


class VerifyTests(unittest.TestCase):
    def verify(self, cat=cc, resolve=None, read=None, tag=TAG):
        return cc.verify(VERSION, tag, catalog() if cat is cc else cat,
                         resolve or resolver(), read or reader())

    def test_matching_entry_passes(self):
        self.assertEqual(self.verify(), [])

    def test_entry_version_when_present_must_match(self):
        self.assertEqual(self.verify(catalog(version=VERSION)), [])
        self.assertTrue(any("version" in f for f in self.verify(catalog(version="2.1.1"))))

    def test_stale_ref_fails(self):
        cat = catalog()
        cat["plugins"][1]["source"]["ref"] = "v2.1.1"
        self.assertTrue(any("source.ref" in f for f in self.verify(cat)))

    def test_wrong_url_or_source_kind_fails(self):
        cat = catalog()
        cat["plugins"][1]["source"].update(url="https://example.com/x.git", source="github")
        failures = self.verify(cat)
        self.assertTrue(any("source.url" in f for f in failures))
        self.assertTrue(any("source.source" in f for f in failures))

    def test_missing_duplicate_or_malformed_entry_fails(self):
        self.assertTrue(self.verify({"plugins": [{"name": "view-limits"}]}))
        dup = catalog()
        dup["plugins"].append(dict(dup["plugins"][1]))
        self.assertTrue(any("exactly one" in f for f in self.verify(dup)))
        for bad in (None, [], {}, {"plugins": "x"}, {"plugins": [{"name": "dev-skill"}]}):
            self.assertTrue(self.verify(bad), bad)

    def test_unpublished_tag_fails(self):
        self.assertTrue(any("not published" in f for f in self.verify(resolve=lambda u, r: None)))

    def test_checkout_that_is_not_the_peeled_commit_fails(self):
        failures = self.verify(read=reader(head="b" * 40))
        self.assertTrue(any("peels to" in f for f in failures))

    def test_tagged_manifest_name_and_version_must_match(self):
        self.assertTrue(any("named" in f for f in self.verify(read=reader(name="other"))))
        self.assertTrue(any("version" in f for f in self.verify(read=reader(version="2.1.1"))))

    def test_tagged_manifest_unparseable_fails(self):
        read = lambda u, r: (COMMIT, {"name": "dev-skill"})
        self.assertTrue(self.verify(read=read))
        read = lambda u, r: (COMMIT, ["not", "an", "object"])
        self.assertTrue(self.verify(read=read))

    def test_tag_must_equal_local_version(self):
        self.assertTrue(any("does not match" in f for f in self.verify(tag="v2.1.1")))


class MainExitCodeTests(unittest.TestCase):
    def run_main(self, *argv, catalog_text=None, git_side_effect=None):
        with tempfile.TemporaryDirectory() as directory:
            args = list(argv)
            if catalog_text is not None:
                path = Path(directory) / "marketplace.json"
                path.write_text(catalog_text, encoding="utf-8")
                args += ["--catalog-file", str(path)]
            out, err = io.StringIO(), io.StringIO()
            patches = [mock.patch.object(cc, "local_plugin_version", return_value=VERSION)]
            if git_side_effect is not None:
                patches.append(mock.patch.object(cc.subprocess, "run", side_effect=git_side_effect))
            with redirect_stdout(out), redirect_stderr(err):
                for p in patches:
                    p.start()
                try:
                    code = cc.main(args)
                finally:
                    mock.patch.stopall()
            return code, out.getvalue(), err.getvalue()

    def test_unparseable_catalog_is_exit_2(self):
        code, _, err = self.run_main(catalog_text="{nope")
        self.assertEqual(code, 2)
        self.assertIn("UNVERIFIED", err)

    def test_missing_catalog_file_is_exit_2(self):
        code, _, _ = self.run_main("--catalog-file", "/nonexistent/marketplace.json")
        self.assertEqual(code, 2)

    def test_unreachable_catalog_clone_is_exit_2_not_a_pass(self):
        fail = subprocess.CompletedProcess([], 128, "", "fatal: unable to access")
        code, out, err = self.run_main(git_side_effect=lambda *a, **k: fail)
        self.assertEqual(code, 2)
        self.assertNotIn("OK", out)
        self.assertIn("unable to access", err)

    def test_git_timeout_is_exit_2(self):
        def boom(*a, **k):
            raise subprocess.TimeoutExpired("git", 1)
        code, _, err = self.run_main(git_side_effect=boom)
        self.assertEqual(code, 2)
        self.assertIn("did not complete", err)

    def test_missing_git_is_exit_2(self):
        def boom(*a, **k):
            raise FileNotFoundError("git")
        self.assertEqual(self.run_main(git_side_effect=boom)[0], 2)

    def test_stale_catalog_is_exit_1(self):
        cat = catalog()
        cat["plugins"][1]["source"]["ref"] = "v2.1.1"
        code, _, err = self.run_main(catalog_text=json.dumps(cat))
        self.assertEqual(code, 1)
        self.assertIn("source.ref", err)

    def test_bad_tag_argument_is_exit_1(self):
        self.assertEqual(self.run_main("--tag", "2.1.2", catalog_text="{}")[0], 1)

    def test_subprocess_calls_are_arg_lists_with_timeouts(self):
        calls = []

        def spy(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, "", "")

        with mock.patch.object(cc.subprocess, "run", side_effect=spy):
            cc.git(["ls-remote", "x"])
        command, kwargs = calls[0]
        self.assertIsInstance(command, list)
        self.assertFalse(kwargs.get("shell"))
        self.assertEqual(kwargs["timeout"], cc.GIT_TIMEOUT)
        self.assertEqual(kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")


class RealGitTests(unittest.TestCase):
    """The git helpers against a local repository: annotated vs lightweight tags."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repo = Path(self.directory.name) / "src"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        (self.repo / ".claude-plugin").mkdir()
        (self.repo / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": "dev-skill", "version": "2.1.2"}), encoding="utf-8")
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x")
        self.commit = self.git("rev-parse", "HEAD").strip()
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "tag", "-a", "v2.1.2", "-m", "rel")
        self.git("tag", "v2.1.3")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, text=True, capture_output=True, check=True).stdout

    def test_annotated_tag_is_peeled_to_the_commit(self):
        tag_object = self.git("rev-parse", "v2.1.2").strip()
        self.assertNotEqual(tag_object, self.commit)
        self.assertEqual(cc.resolve_tag(str(self.repo), "v2.1.2"), self.commit)

    def test_lightweight_tag_resolves_to_its_commit(self):
        self.assertEqual(cc.resolve_tag(str(self.repo), "v2.1.3"), self.commit)

    def test_absent_tag_is_none_and_prefix_does_not_match(self):
        self.assertIsNone(cc.resolve_tag(str(self.repo), "v2.1"))
        self.assertIsNone(cc.resolve_tag(str(self.repo), "v9.9.9"))

    def test_manifest_is_read_from_the_peeled_commit(self):
        head, manifest = cc.read_manifest_at_tag(str(self.repo), "v2.1.2")
        self.assertEqual(head, self.commit)
        self.assertEqual(manifest["version"], "2.1.2")

    def test_unreachable_repository_is_unverifiable(self):
        with self.assertRaises(cc.Unverifiable):
            cc.resolve_tag(str(Path(self.directory.name) / "missing"), "v2.1.2")

    def test_clone_temp_dirs_are_removed(self):
        created = []
        real = tempfile.TemporaryDirectory

        def tracking(*a, **k):
            d = real(*a, **k)
            created.append(Path(d.name))
            return d

        with mock.patch.object(cc.tempfile, "TemporaryDirectory", side_effect=tracking):
            cc.read_manifest_at_tag(str(self.repo), "v2.1.2")
            with self.assertRaises(cc.Unverifiable):
                cc.read_manifest_at_tag(str(self.repo), "v9.9.9")
        self.assertEqual(len(created), 2)
        self.assertTrue(all(not p.exists() for p in created))


if __name__ == "__main__":
    unittest.main()
