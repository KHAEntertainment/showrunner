"""Tests for scripts/check_contract_digests.py (Issue #233).

Temp-dir fixtures only: every test builds its own tree under a temporary
directory and never writes to the repository. No test launches the test suite
or any subprocess; the checker is imported and called in-process. The one test
that touches the real repository tree only reads it.
"""

import contextlib
import hashlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_contract_digests", ROOT / "scripts" / "check_contract_digests.py")
CCD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CCD)

CONTRACTS = Path("docs/v2.2/contracts")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def aggregate(paths_and_bytes):
    """Independent implementation of the index.md aggregate method."""
    lines = b""
    for repo_path in sorted(paths_and_bytes):
        lines += f"{digest(paths_and_bytes[repo_path])}  {repo_path}\n".encode("utf-8")
    return hashlib.sha256(lines).hexdigest()


class TreeBuilder:
    """A minimal contracts tree: fixtures, their table rows, one aggregate."""

    def __init__(self, root):
        self.root = root
        self.files = {}

    def add(self, name, data=b"fixture bytes"):
        repo_path = (CONTRACTS / "fixtures" / name).as_posix()
        self.files[repo_path] = data
        return repo_path

    def write_index(self, row_paths, row_digests, agg=None):
        rows = []
        for repo_path in row_paths:
            table_path = repo_path.replace(CONTRACTS.as_posix() + "/", "")
            recorded = row_digests[repo_path] if repo_path in row_digests \
                else digest(self.files[repo_path])
            rows.append(f"| `{table_path}` | `{recorded}` |")
        recorded_agg = agg if agg is not None else aggregate(self.files)
        text = ("# fixtures\n\n## Fixture digest index\n\n"
                "| Fixture | SHA-256 |\n| --- | --- |\n"
                + "\n".join(rows) + "\n\n"
                f"**Aggregate digest ({len(row_paths)} fixtures, 2099-01-01, #0):** "
                f"`{recorded_agg}`. Method: as stated.\n")
        index = self.root / CONTRACTS / "index.md"
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text(text, encoding="utf-8")

    def write_files(self):
        for repo_path, data in self.files.items():
            target = self.root / repo_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    def write_raw(self, text):
        index = self.root / CONTRACTS / "index.md"
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text(text, encoding="utf-8")


def build_tree(root, tamper_row=None, tamper_aggregate=False, drop_file=None, extra_file=None):
    """A tree whose table matches disk, optionally broken in one named way."""
    builder = TreeBuilder(root)
    builder.add("sc-1/one.json", b"one")
    builder.add("sc-2/two.json", b"two")
    builder.add("sc-3/three.json", b"three")
    row_digests = {}
    listed = sorted(builder.files)
    if drop_file is not None:
        row_digests[drop_file] = digest(builder.files[drop_file])
        del builder.files[drop_file]  # listed in the table, absent from disk
    if extra_file is not None:
        builder.add(extra_file, b"unlisted")  # on disk, absent from the table
    if tamper_row is not None:
        row_digests[tamper_row] = "0" * 64
    builder.write_files()
    builder.write_index(
        row_paths=listed,
        row_digests=row_digests,
        agg="0" * 64 if tamper_aggregate else None)
    return builder


def rows_block(paths_and_bytes, digests=None):
    lines = []
    for repo_path in sorted(paths_and_bytes):
        table_path = repo_path.replace(CONTRACTS.as_posix() + "/", "")
        recorded = (digests or {}).get(repo_path, digest(paths_and_bytes[repo_path]))
        lines.append(f"| `{table_path}` | `{recorded}` |")
    return "\n".join(lines)


def aggregate_line(value):
    return f"**Aggregate digest (3 fixtures, 2099-01-01, #0):** `{value}`. Method: as stated."


def run_main(root):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = CCD.main(["check_contract_digests", str(root)])
    return code, buf.getvalue()


class TestCheckContractDigests(unittest.TestCase):
    def test_passes_on_a_consistent_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            build_tree(Path(tmp))
            self.assertEqual(CCD.check(Path(tmp)), [])

    def test_row_mismatch_fails_naming_file_and_both_digests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo_path = (CONTRACTS / "fixtures/sc-2/two.json").as_posix()
            wrong = "0" * 64
            build_tree(root, tamper_row=repo_path)
            problems = CCD.check(root)
            lines = [p for p in problems if "digest mismatch" in p and repo_path in p]
            self.assertEqual(len(lines), 1, problems)
            self.assertIn(wrong, lines[0])
            self.assertIn(digest(b"two"), lines[0])

    def test_aggregate_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wrong = "0" * 64
            build_tree(root, tamper_aggregate=True)
            problems = CCD.check(root)
            self.assertTrue(
                any("aggregate digest mismatch" in p and wrong in p for p in problems),
                problems)

    def test_missing_listed_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = (CONTRACTS / "fixtures/sc-3/three.json").as_posix()
            build_tree(root, drop_file=missing)
            problems = CCD.check(root)
            self.assertTrue(any(missing in p and "missing" in p for p in problems), problems)

    def test_unlisted_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unlisted = (CONTRACTS / "fixtures/sc-9/nine.json").as_posix()
            build_tree(root, extra_file=unlisted)
            problems = CCD.check(root)
            self.assertTrue(any(unlisted in p and "not listed" in p for p in problems),
                            problems)

    def test_later_heading_aggregate_does_not_mask_a_stale_canonical_aggregate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            builder = build_tree(root)
            stale = "0" * 64
            correct = aggregate(builder.files)
            builder.write_raw(
                "# fixtures\n\n## Fixture digest index\n\n"
                "| Fixture | SHA-256 |\n| --- | --- |\n"
                + rows_block(builder.files) + "\n\n"
                + aggregate_line(stale) + "\n\n"
                "## Historical example\n\n" + aggregate_line(correct) + "\n")
            code, out = run_main(root)
            self.assertEqual(code, 1)
            self.assertIn("aggregate digest mismatch", out)
            self.assertIn(stale, out)
            self.assertIn(correct, out)
            self.assertNotIn("OK:", out)

    def test_duplicate_aggregate_in_section_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            builder = build_tree(root)
            correct = aggregate(builder.files)
            builder.write_raw(
                "# fixtures\n\n## Fixture digest index\n\n"
                "| Fixture | SHA-256 |\n| --- | --- |\n"
                + rows_block(builder.files) + "\n\n"
                + aggregate_line(correct) + "\n" + aggregate_line(correct) + "\n")
            code, out = run_main(root)
            self.assertEqual(code, 1)
            self.assertIn(str(CONTRACTS / "index.md"), out)
            self.assertIn("aggregate digest declared more than once", out)
            self.assertNotIn("aggregate digest mismatch", out)
            self.assertNotIn("OK:", out)

    def test_row_under_later_heading_is_not_treated_as_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            builder = build_tree(root)
            three = (CONTRACTS / "fixtures/sc-3/three.json").as_posix()
            listed = {p: d for p, d in builder.files.items() if p != three}
            builder.write_raw(
                "# fixtures\n\n## Fixture digest index\n\n"
                "| Fixture | SHA-256 |\n| --- | --- |\n"
                + rows_block(listed) + "\n\n"
                + aggregate_line(aggregate(builder.files)) + "\n\n"
                "## Historical example\n\n"
                "| Fixture | SHA-256 |\n| --- | --- |\n"
                f"| `fixtures/sc-3/three.json` | `{'0' * 64}` |\n")
            code, out = run_main(root)
            self.assertEqual(code, 1)
            self.assertIn(three, out)
            self.assertIn("not listed", out)
            self.assertNotIn("digest mismatch", out)

    def test_real_repository_tree_passes(self):
        self.assertEqual(CCD.check(ROOT), [])


if __name__ == "__main__":
    unittest.main()
