"""Tests for the pinned-provider locator (`skills/dev/scripts/locate_pinned_skill.py`).

Every fixture root is built inside a `tempfile` directory. The locator's real
inputs are the harness skill directories and plugin caches on the machine, and
a test must never read -- let alone touch -- a developer's own copy of a
pinned skill. The fixtures therefore imitate the shapes the locator has to
cope with (a flat harness skill directory, a plugin cache holding several
versions) without going near the real ones.

The locator is read-only by construction, and one test proves it rather than
asserting it: a fixture root is snapshotted before and after a run and the
two snapshots must be identical.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "dev" / "scripts" / "locate_pinned_skill.py"

SKILL_NAME = "example-skill"
PINNED_COMMIT = "abc1234"

# A fixed digest vector for the documented algorithm: the fixture below is
# built byte for byte, so this literal pins the canonical byte stream (sorted
# relative path + size + file bytes) against an accidental change to it.
PINNED_DIGEST = "ca8bd87665f5478067b3d174249ad8f19486913d3405ce9e3c6992b6cdd29686"


def load_locator() -> types.ModuleType:
    """Load the locator without importing it from a package.

    The script ships inside the Skill payload, not as an importable module,
    and loading it through `importlib` would drop a `__pycache__` directory
    next to the source file -- a write the read-only test would then catch.
    Executing the source in a private namespace keeps the tree untouched.
    """
    module = types.ModuleType("locate_pinned_skill")
    module.__file__ = str(SCRIPT)
    source = SCRIPT.read_text(encoding="utf-8")
    exec(compile(source, str(SCRIPT), "exec"), module.__dict__)  # noqa: S102
    return module


LOCATOR = load_locator()


def write_skill(
    directory: Path,
    body: str = "Example.\n",
    extra: str | None = None,
) -> Path:
    """Create a skill directory that the locator accepts as a candidate."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_bytes(
        f"---\nname: {directory.name}\n---\n\n{body}".encode("utf-8")
    )
    if extra is not None:
        (directory / "references").mkdir(parents=True, exist_ok=True)
        (directory / "references" / "notes.md").write_bytes(extra.encode("utf-8"))
    return directory


def snapshot(root: Path) -> list[tuple[str, int, str]]:
    """Return a content snapshot of every entry under ``root``."""
    entries: list[tuple[str, int, str]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries.append((relative, -1, "symlink"))
        elif path.is_dir():
            entries.append((relative, -1, "dir"))
        elif path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            entries.append((relative, path.stat().st_size, digest))
        else:
            entries.append((relative, -1, "other"))
    return entries


class LocatorCliTests(unittest.TestCase):
    """The locator's contract as a command: JSON on stdout, exit codes."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.root = self.base / "roots"
        self.root.mkdir()
        self._locked: list[Path] = []

    def tearDown(self) -> None:
        """Restore every directory this test locked.

        A directory left at mode 000 would keep the rest of the fixture tree
        unreadable and would survive the temporary directory's cleanup.
        """
        for directory in self._locked:
            try:
                os.chmod(directory, 0o755)
            except OSError:
                pass

    def lock(self, directory: Path) -> Path:
        """Make a directory unreadable, and remember to restore it.

        A root account defeats directory permissions, so the case that needs
        an unreadable tree cannot be meaningful there.
        """
        if getattr(os, "geteuid", lambda: 1)() == 0:
            self.skipTest("root bypasses directory permissions")
        os.chmod(directory, 0o000)
        self._locked.append(directory)
        return directory

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            check=False,
            capture_output=True,
            text=True,
        )

    def locate(self, digest: str, *roots: Path) -> subprocess.CompletedProcess[str]:
        arguments = ["--skill", SKILL_NAME, "--commit", PINNED_COMMIT, "--digest", digest]
        for root in roots or (self.root,):
            arguments += ["--root", str(root)]
        return self.run_cli(*arguments)

    def payload(self, completed: subprocess.CompletedProcess[str]) -> dict:
        return json.loads(completed.stdout)

    def test_present_reports_path_and_digest(self) -> None:
        skill_dir = write_skill(self.root / SKILL_NAME)
        digest = LOCATOR.directory_digest(skill_dir)

        completed = self.locate(digest)
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = self.payload(completed)
        self.assertEqual("present", payload["status"])
        self.assertEqual(str(skill_dir), payload["path"])
        self.assertEqual(f"sha256:{digest}", payload["digest"])
        self.assertEqual(PINNED_COMMIT, payload["pin_commit"])

    def test_absent_reports_not_available_with_a_cause(self) -> None:
        completed = self.locate(PINNED_DIGEST)
        self.assertEqual(2, completed.returncode, completed.stdout)
        payload = self.payload(completed)
        self.assertEqual("not_available", payload["status"])
        self.assertEqual("no_candidate_found", payload["cause"])
        self.assertNotIn("path", payload)

    def test_drifted_content_reports_drift_with_a_cause(self) -> None:
        skill_dir = write_skill(self.root / SKILL_NAME)
        digest = LOCATOR.directory_digest(skill_dir)
        (skill_dir / "SKILL.md").write_bytes(
            b"---\nname: example-skill\n---\n\nDrifted.\n"
        )

        completed = self.locate(digest)
        self.assertEqual(2, completed.returncode, completed.stdout)
        payload = self.payload(completed)
        self.assertEqual("drift", payload["status"])
        self.assertEqual("digest_mismatch", payload["cause"])
        self.assertEqual(1, len(payload["candidates"]))
        self.assertEqual(str(skill_dir), payload["candidates"][0]["path"])

    def test_plugin_cache_with_several_versions_picks_the_matching_one(self) -> None:
        cache = self.root / "kha-marketplace" / "example-plugin"
        old = write_skill(cache / "1.0.0" / "skills" / SKILL_NAME, body="Old.\n")
        new = write_skill(cache / "2.0.0" / "skills" / SKILL_NAME, body="New.\n")
        digest = LOCATOR.directory_digest(new)

        completed = self.locate(digest)
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = self.payload(completed)
        self.assertEqual("present", payload["status"])
        self.assertEqual(str(new), payload["path"])
        self.assertNotEqual(str(old), payload["path"])
        self.assertEqual(2, len(payload["candidates"]))

    def test_plugin_cache_with_several_versions_and_no_match_reports_drift(self) -> None:
        cache = self.root / "kha-marketplace" / "example-plugin"
        write_skill(cache / "1.0.0" / "skills" / SKILL_NAME, body="Old.\n")
        write_skill(cache / "2.0.0" / "skills" / SKILL_NAME, body="New.\n")
        # A pin for a copy that is not in any searched root: no candidate can
        # match it, and the two versions present make the cause specific.
        elsewhere = write_skill(self.base / "unrelated" / SKILL_NAME, body="Pinned.\n")

        completed = self.locate(LOCATOR.directory_digest(elsewhere))
        self.assertEqual(2, completed.returncode, completed.stdout)
        payload = self.payload(completed)
        self.assertEqual("drift", payload["status"])
        self.assertEqual("multiple_versions_none_match", payload["cause"])
        self.assertEqual(2, len(payload["candidates"]))

    def test_missing_root_reports_not_available(self) -> None:
        completed = self.locate(PINNED_DIGEST, self.base / "does-not-exist")
        self.assertEqual(2, completed.returncode, completed.stdout)
        payload = self.payload(completed)
        self.assertEqual("not_available", payload["status"])
        self.assertEqual("no_candidate_found", payload["cause"])

    def test_directory_without_skill_md_is_not_a_candidate(self) -> None:
        (self.root / SKILL_NAME).mkdir()
        completed = self.locate(PINNED_DIGEST)
        self.assertEqual(2, completed.returncode, completed.stdout)
        payload = self.payload(completed)
        self.assertEqual("not_available", payload["status"])
        self.assertEqual("no_candidate_found", payload["cause"])

    def test_argument_errors_exit_1(self) -> None:
        cases = (
            (),
            ("--skill", SKILL_NAME),
            ("--skill", SKILL_NAME, "--commit", PINNED_COMMIT, "--digest", PINNED_DIGEST),
            (
                "--skill",
                SKILL_NAME,
                "--commit",
                PINNED_COMMIT,
                "--digest",
                PINNED_DIGEST,
                "--root",
                str(self.root),
                "--unexpected",
                "x",
            ),
            (
                "--skill",
                SKILL_NAME,
                "--commit",
                PINNED_COMMIT,
                "--digest",
                "not-a-digest",
                "--root",
                str(self.root),
            ),
            (
                "--skill",
                SKILL_NAME,
                "--commit",
                PINNED_COMMIT,
                "--digest",
                "z" * 64,
                "--root",
                str(self.root),
            ),
            (
                "--skill",
                SKILL_NAME,
                "--commit",
                PINNED_COMMIT,
                "--digest",
                PINNED_DIGEST,
                "--root",
                "",
            ),
        )
        for args in cases:
            with self.subTest(args=args):
                completed = self.run_cli(*args)
                self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
                self.assertEqual("", completed.stdout)

    def test_locator_writes_nothing_to_the_roots(self) -> None:
        skill_dir = write_skill(self.root / SKILL_NAME)
        digest = LOCATOR.directory_digest(skill_dir)
        before = snapshot(self.base)

        completed = self.locate(digest)
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(before, snapshot(self.base))

    @unittest.skipIf(
        getattr(os, "geteuid", lambda: 1)() == 0,
        "root bypasses directory permissions",
    )
    def test_unreadable_candidate_tree_is_an_error_not_a_verdict(self) -> None:
        """An I/O failure must not be reported as drift or as a verdict."""
        skill_dir = write_skill(self.root / SKILL_NAME)
        digest = LOCATOR.directory_digest(skill_dir)
        locked = skill_dir / "references"
        locked.mkdir()
        (locked / "notes.md").write_bytes(b"notes\n")
        self.lock(locked)

        completed = self.locate(digest)
        self.assertEqual(1, completed.returncode, completed.stdout)
        payload = json.loads(completed.stdout)
        self.assertEqual("error", payload["status"])
        self.assertEqual("candidate_unreadable", payload["cause"])

    def test_an_unreadable_candidate_alone_is_an_error(self) -> None:
        """A candidate that cannot be read yields no verdict at all."""
        skill_dir = write_skill(self.root / SKILL_NAME)
        digest = LOCATOR.directory_digest(skill_dir)
        self.lock(skill_dir)

        completed = self.locate(digest)
        self.assertEqual(1, completed.returncode, completed.stdout)
        payload = json.loads(completed.stdout)
        self.assertEqual("error", payload["status"])
        self.assertEqual("candidate_unreadable", payload["cause"])

    def test_an_unreadable_candidate_does_not_hide_a_later_match(self) -> None:
        """One unreadable version must not stop the search before a match."""
        cache = self.root / "kha-marketplace" / "example-plugin"
        broken = write_skill(cache / "1.0.0" / "skills" / SKILL_NAME, body="Old.\n")
        good = write_skill(cache / "2.0.0" / "skills" / SKILL_NAME, body="New.\n")
        digest = LOCATOR.directory_digest(good)
        self.lock(broken)

        completed = self.locate(digest)
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = self.payload(completed)
        self.assertEqual("present", payload["status"])
        self.assertEqual(str(good), payload["path"])

    def test_an_unreadable_subtree_does_not_hide_a_later_match(self) -> None:
        """The candidate itself is readable; something inside it is not.

        This is the case where the failure happens while the tree is being
        hashed, so the search has to survive it and keep looking.
        """
        cache = self.root / "kha-marketplace" / "example-plugin"
        broken = write_skill(cache / "1.0.0" / "skills" / SKILL_NAME, body="Old.\n")
        good = write_skill(cache / "2.0.0" / "skills" / SKILL_NAME, body="New.\n")
        digest = LOCATOR.directory_digest(good)
        locked = broken / "references"
        locked.mkdir()
        (locked / "notes.md").write_bytes(b"notes\n")
        self.lock(locked)

        completed = self.locate(digest)
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = self.payload(completed)
        self.assertEqual("present", payload["status"])
        self.assertEqual(str(good), payload["path"])

    def test_a_symlinked_skill_md_is_never_present(self) -> None:
        """A symlinked SKILL.md cannot be verified, so it is never a match."""
        skill_dir = write_skill(self.root / SKILL_NAME)
        target = self.base / "linked" / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((skill_dir / "SKILL.md").read_bytes())
        (skill_dir / "SKILL.md").unlink()
        (skill_dir / "SKILL.md").symlink_to(target)
        # The pin is the digest of the tree as it stands: the old behaviour
        # matched it and reported the skill as present.
        digest = LOCATOR.directory_digest(skill_dir)

        completed = self.locate(digest)
        self.assertEqual(2, completed.returncode, completed.stdout)
        payload = self.payload(completed)
        self.assertEqual("drift", payload["status"])
        self.assertEqual("symlinked_content", payload["cause"])
        self.assertNotIn("path", payload)

    def test_a_symlinked_sibling_file_is_never_present(self) -> None:
        """A linked reference file is content too, and is never hashed."""
        skill_dir = write_skill(self.root / SKILL_NAME, extra="Reference notes.\n")
        target = self.base / "linked" / "notes.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"Reference notes.\n")
        (skill_dir / "references" / "notes.md").unlink()
        (skill_dir / "references" / "notes.md").symlink_to(target)
        digest = LOCATOR.directory_digest(skill_dir)

        completed = self.locate(digest)
        self.assertEqual(2, completed.returncode, completed.stdout)
        payload = self.payload(completed)
        self.assertEqual("drift", payload["status"])
        self.assertEqual("symlinked_content", payload["cause"])

    def test_a_symlinked_sibling_directory_is_never_present(self) -> None:
        """A linked directory is content too, and is never followed."""
        skill_dir = write_skill(self.root / SKILL_NAME)
        outside = self.base / "linked" / "references"
        outside.mkdir(parents=True)
        (outside / "notes.md").write_bytes(b"Reference notes.\n")
        (skill_dir / "references").symlink_to(outside)
        digest = LOCATOR.directory_digest(skill_dir)

        completed = self.locate(digest)
        self.assertEqual(2, completed.returncode, completed.stdout)
        payload = self.payload(completed)
        self.assertEqual("drift", payload["status"])
        self.assertEqual("symlinked_content", payload["cause"])

    def test_content_changed_behind_a_link_is_still_not_present(self) -> None:
        """The hole this closes: the digest skips links, so what is behind
        one could change without changing the digest."""
        skill_dir = write_skill(self.root / SKILL_NAME)
        target = self.base / "linked" / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"---\nname: example-skill\n---\n\nOriginal.\n")
        (skill_dir / "SKILL.md").unlink()
        (skill_dir / "SKILL.md").symlink_to(target)
        digest = LOCATOR.directory_digest(skill_dir)

        target.write_bytes(b"---\nname: example-skill\n---\n\nChanged.\n")
        self.assertEqual(digest, LOCATOR.directory_digest(skill_dir))

        completed = self.locate(digest)
        self.assertEqual(2, completed.returncode, completed.stdout)
        payload = self.payload(completed)
        self.assertNotEqual("present", payload["status"])
        self.assertEqual("symlinked_content", payload["cause"])

    def test_a_clean_candidate_wins_over_a_symlinked_one(self) -> None:
        """A refused candidate never hides a verifiable match beside it."""
        cache = self.root / "kha-marketplace" / "example-plugin"
        linked = write_skill(cache / "1.0.0" / "skills" / SKILL_NAME, body="Old.\n")
        clean = write_skill(cache / "2.0.0" / "skills" / SKILL_NAME, body="New.\n")
        target = self.base / "linked" / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((linked / "SKILL.md").read_bytes())
        (linked / "SKILL.md").unlink()
        (linked / "SKILL.md").symlink_to(target)

        completed = self.locate(LOCATOR.directory_digest(clean))
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = self.payload(completed)
        self.assertEqual("present", payload["status"])
        self.assertEqual(str(clean), payload["path"])

    def test_a_clean_mismatch_outranks_a_symlinked_candidate(self) -> None:
        """A symlinked candidate never hides a clean digest mismatch beside it.

        A clean candidate whose digest mismatches is a more specific drift than
        a symlinked one: the symlinked candidate is listed under ``symlinked``
        and never chosen, and the verdict names the digest mismatch.
        """
        cache = self.root / "kha-marketplace" / "example-plugin"
        linked = write_skill(cache / "1.0.0" / "skills" / SKILL_NAME, body="Old.\n")
        clean = write_skill(cache / "2.0.0" / "skills" / SKILL_NAME, body="New.\n")
        target = self.base / "linked" / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((linked / "SKILL.md").read_bytes())
        (linked / "SKILL.md").unlink()
        (linked / "SKILL.md").symlink_to(target)

        elsewhere = write_skill(self.base / "unrelated" / SKILL_NAME, body="Pinned.\n")
        completed = self.locate(LOCATOR.directory_digest(elsewhere))
        self.assertEqual(2, completed.returncode, completed.stdout)
        payload = self.payload(completed)
        self.assertEqual("drift", payload["status"])
        self.assertEqual("digest_mismatch", payload["cause"])
        self.assertEqual(str(linked), payload["symlinked"][0]["path"])
        self.assertNotIn("path", payload)

    def test_an_unreadable_root_is_an_error_not_an_absence(self) -> None:
        """The skill could be inside a root that cannot be read."""
        root = self.base / "locked-root"
        root.mkdir()
        self.lock(root)

        completed = self.locate(PINNED_DIGEST, root)
        self.assertEqual(1, completed.returncode, completed.stdout)
        payload = json.loads(completed.stdout)
        self.assertEqual("error", payload["status"])
        self.assertEqual("root_unreadable", payload["cause"])

    def test_a_root_behind_an_unreadable_parent_is_an_error_not_an_absence(self) -> None:
        """A root whose parent cannot be searched must not be skipped as absent.

        ``Path.exists()`` swallows a permission error and reports False, so a
        root sitting behind an unreadable parent looked absent and produced
        ``not_available``. It is an operational error: the skill could be
        inside it.
        """
        parent = self.base / "locked-parent"
        parent.mkdir()
        root = parent / "root"
        root.mkdir()
        self.lock(parent)

        completed = self.locate(PINNED_DIGEST, root)
        self.assertEqual(1, completed.returncode, completed.stdout)
        payload = json.loads(completed.stdout)
        self.assertEqual("error", payload["status"])
        self.assertEqual("root_unreadable", payload["cause"])

    def test_a_root_that_is_not_a_directory_is_a_usage_error(self) -> None:
        """``--root`` naming a regular file is a bad argument, not an absence."""
        root = self.base / "not-a-directory"
        root.write_bytes(b"not a directory\n")

        completed = self.locate(PINNED_DIGEST, root)
        self.assertEqual(1, completed.returncode, completed.stdout)
        self.assertEqual("", completed.stdout)
        self.assertIn("--root is not a directory", completed.stderr)

    def test_a_missing_root_does_not_hide_a_candidate_in_another_root(self) -> None:
        """A missing root is skipped; another root still decides the verdict."""
        skill_dir = write_skill(self.root / SKILL_NAME)
        digest = LOCATOR.directory_digest(skill_dir)

        completed = self.locate(digest, self.base / "does-not-exist", self.root)
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = self.payload(completed)
        self.assertEqual("present", payload["status"])
        self.assertEqual(str(skill_dir), payload["path"])


class DirectoryDigestTests(unittest.TestCase):
    """The digest algorithm itself: deterministic, whole-directory, sensitive."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)

    def test_digest_matches_the_fixed_vector(self) -> None:
        """The documented algorithm is pinned by a literal digest."""
        skill_dir = write_skill(
            self.base / SKILL_NAME,
            body="Example.\n",
            extra="Reference notes.\n",
        )
        self.assertEqual(PINNED_DIGEST, LOCATOR.directory_digest(skill_dir))

    def test_same_tree_gives_the_same_digest(self) -> None:
        skill_dir = write_skill(self.base / SKILL_NAME)
        self.assertEqual(
            LOCATOR.directory_digest(skill_dir),
            LOCATOR.directory_digest(skill_dir),
        )

    def test_one_changed_byte_gives_a_different_digest(self) -> None:
        skill_dir = write_skill(self.base / SKILL_NAME)
        before = LOCATOR.directory_digest(skill_dir)

        entry = skill_dir / "SKILL.md"
        data = entry.read_bytes()
        entry.write_bytes(data[:-1] + bytes([data[-1] ^ 0x01]))

        self.assertNotEqual(before, LOCATOR.directory_digest(skill_dir))

    def test_a_sibling_reference_file_is_covered(self) -> None:
        """The pin is the whole directory: a drifting sibling changes it."""
        skill_dir = write_skill(self.base / SKILL_NAME, extra="Reference notes.\n")
        before = LOCATOR.directory_digest(skill_dir)

        (skill_dir / "references" / "notes.md").write_bytes(b"Reference notes, revised.\n")

        self.assertNotEqual(before, LOCATOR.directory_digest(skill_dir))

    def test_vcs_directories_are_excluded(self) -> None:
        skill_dir = write_skill(self.base / SKILL_NAME)
        before = LOCATOR.directory_digest(skill_dir)

        (skill_dir / ".git").mkdir()
        (skill_dir / ".git" / "config").write_bytes(b"[core]\n")

        self.assertEqual(before, LOCATOR.directory_digest(skill_dir))


class LocatorSourceTests(unittest.TestCase):
    """The script's own guarantees, checked on its source.

    The guarantees are structural, so they are checked structurally: a
    substring scan would trip over the module docstring, which names the
    very things the script must not do.
    """

    ALLOWED_IMPORTS = frozenset(
        {"__future__", "argparse", "hashlib", "json", "pathlib", "sys"}
    )

    FORBIDDEN_CALLS = frozenset(
        {
            "write_text",
            "write_bytes",
            "unlink",
            "rmdir",
            "removedirs",
            "rename",
            "mkdir",
            "makedirs",
            "rmtree",
            "copytree",
            "copyfile",
            "system",
            "popen",
            "urlopen",
            "urlretrieve",
            "check_output",
        }
    )

    def setUp(self) -> None:
        self.source = SCRIPT.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def test_no_hardcoded_home_path(self) -> None:
        """The candidate roots come from the caller, never from a baked path."""
        self.assertNotIn("~/.claude", self.source)
        self.assertNotIn("/Users/", self.source)
        self.assertNotIn("/home/", self.source)

    def test_only_the_allowed_stdlib_modules_are_imported(self) -> None:
        """Stdlib only, and nothing that can fetch, run or write a process."""
        imported: set[str] = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertLessEqual(imported, self.ALLOWED_IMPORTS)
        for forbidden in ("urllib", "socket", "http", "requests", "subprocess", "shutil", "os"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, imported)

    def test_the_script_never_writes_fetches_or_runs_anything(self) -> None:
        """No write, install, fetch or process call hides in the source."""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    with self.subTest(call=node.func.id):
                        self.assertNotIn(node.func.id, self.FORBIDDEN_CALLS)
                        self.assertNotEqual("open", node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    with self.subTest(call=node.func.attr):
                        self.assertNotIn(node.func.attr, self.FORBIDDEN_CALLS)

    def test_main_has_no_dead_locator_error_handler(self) -> None:
        """``locate()`` internalizes ``LocatorError``, so ``main()`` has no handler.

        The operational-error JSON contract (exit 1, an ``{"status": "error",
        "cause": ...}`` object on stdout) is produced by ``locate()``'s return
        payload, not by an exception handler, so a handler for ``LocatorError``
        in ``main()`` is dead code.
        """
        main_node = next(
            (
                node
                for node in ast.walk(self.tree)
                if isinstance(node, ast.FunctionDef) and node.name == "main"
            ),
            None,
        )
        self.assertIsNotNone(main_node, "main() not found")
        handled: list[str] = []
        for node in ast.walk(main_node):
            if isinstance(node, ast.ExceptHandler) and isinstance(node.type, ast.Name):
                handled.append(node.type.id)
        self.assertNotIn("LocatorError", handled)


if __name__ == "__main__":
    unittest.main()
