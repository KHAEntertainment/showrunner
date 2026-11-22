"""Tests for repository-relative Markdown links (Issue #258).

Walks ``README.md`` and every ``docs/**/*.md`` and fails — naming the file
and the target — for any repository-relative link target that does not
exist.  External links (``scheme:``), pure anchors (``#...``) and
out-of-repository paths (starting ``~`` or ``/``) are skipped and listed
in the test output, never failed.  Links inside fenced code blocks or
inline code spans are examples, not links, and are skipped too.

No document is modified: the broken-link proof uses a synthetic fixture
in a temp directory.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# [text](target) — captures the target of a Markdown link or image.
LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
# A URL scheme: "https:", "mailto:", "ftp:", ...
SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
# Inline code span: `...`
INLINE_CODE_RE = re.compile(r"`[^`]*`")
FENCE_PREFIXES = ("```", "~~~")


def markdown_files(root: Path) -> list[Path]:
    """README.md plus every docs/**/*.md under *root*, in stable order."""
    files: list[Path] = []
    readme = root / "README.md"
    if readme.is_file():
        files.append(readme)
    docs = root / "docs"
    if docs.is_dir():
        files.extend(sorted(docs.rglob("*.md")))
    return files


def link_lines(text: str) -> list[tuple[int, str]]:
    """Line numbers and content of *text* outside fenced code blocks.

    Lines inside a ```/~~~ fence are examples, not links, and are dropped.
    Inline code spans are blanked out for the same reason.
    """
    out: list[tuple[int, str]] = []
    fence: str | None = None
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith(FENCE_PREFIXES):
            marker = stripped[:3]
            if fence is None:
                fence = marker
            elif stripped.startswith(marker):
                fence = None
            continue
        if fence is not None:
            continue
        out.append((lineno, INLINE_CODE_RE.sub("", line)))
    return out


def classify(target: str) -> str:
    """Return ``relative`` or the skip kind for a link *target*."""
    if target.startswith("#"):
        return "anchor"
    if target.startswith("~") or target.startswith("/"):
        return "out-of-repo"
    if SCHEME_RE.match(target):
        return "scheme"
    return "relative"


def check_links(root: Path) -> tuple[list[str], list[str]]:
    """Scan *root*'s Markdown for links.

    Returns ``(broken, skipped)``: every repository-relative target that
    does not exist (one ``file -> target`` line each, naming both), and
    every skipped target (``file -> target (kind)``), which is listed in
    test output and never failed.  A target like ``other.md#section``
    checks the file part and ignores the anchor.  The skip list is exactly
    ``scheme:``, ``#...``, ``~...`` and ``/...``: a relative target whose
    path resolves outside *root* (e.g. ``../../x.md``) is broken, named by
    file and target, even when the file exists on disk outside *root* —
    on GitHub it can never resolve.
    """
    root = root.resolve()
    broken: list[str] = []
    skipped: list[str] = []
    for md in markdown_files(root):
        rel_md = str(md.relative_to(root))
        text = md.read_text(encoding="utf-8", errors="replace")
        for lineno, line in link_lines(text):
            for match in LINK_RE.finditer(line):
                target = match.group(2)
                kind = classify(target)
                if kind != "relative":
                    skipped.append(f"{rel_md}:{lineno} -> {target} ({kind})")
                    continue
                path_part = target.split("#", 1)[0].split("?", 1)[0]
                if not path_part:
                    skipped.append(f"{rel_md}:{lineno} -> {target} (anchor)")
                    continue
                resolved = (md.parent / path_part).resolve()
                if not _within(resolved, root) or not resolved.exists():
                    broken.append(f"{rel_md}:{lineno} -> {target}")
    return broken, skipped


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def write(root: Path, name: str, text: str) -> None:
    """Write a synthetic Markdown fixture under *root*."""
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


class DocsLinksTests(unittest.TestCase):
    def test_docs_relative_links_resolve(self) -> None:
        """AC1: every repository-relative link in README.md and docs/ exists."""
        broken, skipped = check_links(ROOT)
        for line in skipped:
            print(f"skipped: {line}")
        self.assertEqual(
            broken,
            [],
            "repository-relative link target does not exist:\n"
            + "\n".join(broken),
        )

    def test_docs_links_reports_broken_target(self) -> None:
        """AC2: a broken relative link fails naming the file and the target."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            write(root, "README.md", "# fixture\n\nSee [missing](nowhere/missing.md).\n")
            broken, _skipped = check_links(root)
        self.assertEqual(len(broken), 1, broken)
        self.assertIn("README.md", broken[0], broken)
        self.assertIn("nowhere/missing.md", broken[0], broken)

    def test_docs_links_reports_escape_outside_repo(self) -> None:
        """A relative target resolving outside the repo root is broken.

        The Issue's skip list is only ``scheme:``, ``#...``, ``~...`` and
        ``/...``; ``../../x.md`` is repository-relative, and on GitHub it
        can never resolve — reported broken by file and target even when
        the file really exists on disk outside the repository.
        """
        with tempfile.TemporaryDirectory() as tmp:
            holder = Path(tmp)
            root = holder / "repo"
            write(root, "docs/page.md", "# fixture\n\n[escape](../outside.md)\n")
            write(holder, "outside.md", "# exists outside the repo root\n")
            broken, skipped = check_links(root)
        self.assertEqual(skipped, [], skipped)
        self.assertEqual(len(broken), 1, broken)
        self.assertIn("docs/page.md", broken[0], broken)
        self.assertIn("../outside.md", broken[0], broken)
        self.assertNotIn("outside.md (", broken[0])

    def test_docs_links_skips_out_of_repo(self) -> None:
        """AC3: ~/..., /..., https://... and #anchor are skipped, never failed."""
        fixture = "\n".join(
            [
                "# fixture",
                "",
                "[home](~/.traycer/epics/example/index.md)",
                "[abs](/etc/hosts)",
                "[ext](https://example.com/page)",
                "[anch](#section)",
                "",
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "docs/fixture.md", fixture)
            broken, skipped = check_links(root)
        self.assertEqual(broken, [], broken)
        joined = "\n".join(skipped)
        for expected in (
            "~/.traycer/epics/example/index.md",
            "/etc/hosts",
            "https://example.com/page",
            "#section",
        ):
            self.assertIn(expected, joined)

    def test_docs_links_skips_code_examples(self) -> None:
        """Links in fenced blocks and inline code are examples, not links."""
        fixture = "\n".join(
            [
                "# fixture",
                "",
                "```markdown",
                "[example](not-a-real-file.md)",
                "```",
                "",
                "Inline example: `[other](also-missing.md)` is not a link.",
                "",
                "[real](exists.md)",
                "",
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "docs/fixture.md", fixture)
            write(root, "docs/exists.md", "# exists\n")
            broken, skipped = check_links(root)
        self.assertEqual(broken, [], broken)
        self.assertEqual(skipped, [], skipped)


if __name__ == "__main__":
    unittest.main()
