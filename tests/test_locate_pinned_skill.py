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
        os.chmod(locked, 0o000)
        self.addCleanup(os.chmod, locked, 0o755)

        completed = self.locate(digest)
        self.assertEqual(1, completed.returncode, completed.stdout)
        self.assertEqual("", completed.stdout)
        payload = json.loads(completed.stderr)
        self.assertEqual("error", payload["status"])
        self.assertEqual("unreadable_candidate", payload["cause"])


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


if __name__ == "__main__":
    unittest.main()
