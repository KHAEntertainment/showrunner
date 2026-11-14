#!/usr/bin/env python3
"""Read the contracts fixture digest index and verify it against the tree.

Issue #233: the Verification Gate recomputes the SHA-256 of every fixture file
listed in the ``docs/v2.2/contracts/index.md`` "Fixture digest index" table and
compares it with the recorded value; a mismatch fails the job and names the
file and both digests. The aggregate row is covered the same way, computed by
the method index.md states: SHA-256 of the ``sha256sum``-style lines
``<hex>  <repository path>`` (two spaces, one line per
``docs/v2.2/contracts/fixtures/**/*.json`` file, each ending in a newline),
sorted by repository path in byte order.

The check is read-only: it reads the table and the fixture files, writes
nothing, installs nothing, uses only the standard library and makes no network
calls. It also fails on a listed file that is missing from the tree and on a
fixture file the table does not list.

Exit 0 with a one-line OK when everything matches; exit 1 with one line per
problem otherwise.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = Path("docs") / "v2.2" / "contracts"
FIXTURES_DIR = CONTRACTS_DIR / "fixtures"
INDEX_PATH = CONTRACTS_DIR / "index.md"
TABLE_HEADING = "## Fixture digest index"

ROW_RE = re.compile(r"^\| `(?P<path>fixtures/[^`]+)` \| `(?P<digest>[0-9a-f]{64})` \|")
AGGREGATE_RE = re.compile(r"\*\*Aggregate digest \([^)]*\):\*\* `(?P<digest>[0-9a-f]{64})`")


def parse_table(text: str):
    """Return ([(table path, recorded digest)], aggregate digest or None).

    Rows are read under the "## Fixture digest index" heading; the aggregate
    is its closing ``**Aggregate digest (...):**`` line."""
    rows = []
    aggregate = None
    in_section = False
    for line in text.splitlines():
        if line.startswith(TABLE_HEADING):
            in_section = True
            continue
        if not in_section:
            continue
        row = ROW_RE.match(line)
        if row:
            rows.append((row.group("path"), row.group("digest")))
        agg = AGGREGATE_RE.search(line)
        if agg:
            aggregate = agg.group("digest")
    return rows, aggregate


def fixture_files(root: Path):
    """Every ``docs/v2.2/contracts/fixtures/**/*.json`` file, as repository paths."""
    base = root / FIXTURES_DIR
    return sorted(
        (p.relative_to(root).as_posix() for p in base.rglob("*.json")),
    )


def file_digest(root: Path, repo_path: str) -> str:
    return hashlib.sha256((root / repo_path).read_bytes()).hexdigest()


def aggregate_digest(root: Path, repo_paths) -> str:
    """The index.md l.94 aggregate method over the given repository paths."""
    lines = b""
    for repo_path in sorted(repo_paths):
        lines += f"{file_digest(root, repo_path)}  {repo_path}\n".encode("utf-8")
    return hashlib.sha256(lines).hexdigest()


def check(root: Path):
    """Return a list of problem lines; empty means the table matches the tree."""
    index = root / INDEX_PATH
    if not index.is_file():
        return [f"{INDEX_PATH.as_posix()}: digest table file missing"]
    rows, aggregate = parse_table(index.read_text(encoding="utf-8"))
    if not rows:
        return [f"{INDEX_PATH.as_posix()}: no rows under '{TABLE_HEADING}'"]
    if aggregate is None:
        return [f"{INDEX_PATH.as_posix()}: no aggregate digest row under '{TABLE_HEADING}'"]

    problems = []
    listed = set()
    for table_path, recorded in rows:
        repo_path = (CONTRACTS_DIR / table_path).as_posix()
        listed.add(repo_path)
        target = root / repo_path
        if not target.is_file():
            problems.append(f"{repo_path}: listed in the digest table but missing from the tree")
            continue
        computed = file_digest(root, repo_path)
        if computed != recorded:
            problems.append(
                f"{repo_path}: digest mismatch: recorded {recorded}, computed {computed}")

    for repo_path in fixture_files(root):
        if repo_path not in listed:
            problems.append(f"{repo_path}: fixture on disk but not listed in the digest table")

    computed_aggregate = aggregate_digest(root, fixture_files(root))
    if computed_aggregate != aggregate:
        problems.append(
            f"{INDEX_PATH.as_posix()}: aggregate digest mismatch: "
            f"recorded {aggregate}, computed {computed_aggregate}")
    return problems


def main(argv) -> int:
    root = Path(argv[1]).resolve() if len(argv) > 1 else REPO_ROOT
    problems = check(root)
    if problems:
        for line in problems:
            print(line)
        return 1
    rows, aggregate = parse_table((root / INDEX_PATH).read_text(encoding="utf-8"))
    print(f"OK: {len(rows)} fixtures match {INDEX_PATH.as_posix()} (aggregate {aggregate})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
