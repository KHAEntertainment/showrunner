"""Tests for skills/readme/scripts/readme_check.py.

Covers the Issue #163 acceptance criteria for the checker: badge count is a
SOFT observation that never changes the exit code by itself, while a missing
code-fence language and multiple H1s are HARD findings that force a non-zero
exit.
"""

from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "skills" / "readme" / "scripts" / "readme_check.py"
SPEC = importlib.util.spec_from_file_location("readme_check", CHECKER)
CHECK = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["readme_check"] = CHECK
SPEC.loader.exec_module(CHECK)


CLEAN = """\
# example

**A hook sentence.**

## Quick start

1. Install it:

   ```bash
   pip install example
   ```

2. Run it and see the result.
"""

EIGHT_BADGES = """\
# example

**A hook sentence.**

## Quick start

1. Install it:

   ```bash
   pip install example
   ```

## Status

![Build](https://img.shields.io/github/actions/workflow/status/o/r/ci.yml)
![License](https://img.shields.io/github/license/o/r)
![Version](https://img.shields.io/pypi/v/example)
![Coverage](https://codecov.io/gh/o/r/branch/main/graph/badge.svg)
![Downloads](https://img.shields.io/pypi/dm/example)
![Stars](https://img.shields.io/github/stars/o/r)
![CodeRabbit](https://img.shields.io/coderabbit/prs/github/o/r)
![Docs](https://readthedocs.org/projects/example/badge)
"""

TWO_H1S = """\
# example

**A hook sentence.**

# second

## Quick start

1. Install it:

   ```bash
   pip install example
   ```
"""

NO_FENCE_LANGUAGE = """\
# example

**A hook sentence.**

## Quick start

```
pip install example
```
"""


def run_check(content: str) -> tuple[int, list[CHECK.Finding], dict]:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "README.md"
        path.write_text(content, encoding="utf-8")
        findings, stats = CHECK.check(content)
        with redirect_stdout(io.StringIO()):
            code = CHECK.main([str(path)])
    return code, findings, stats


class HardFindingsTests(unittest.TestCase):
    def test_missing_code_fence_language_is_hard(self) -> None:
        code, findings, _ = run_check(NO_FENCE_LANGUAGE)
        self.assertEqual(1, code)
        self.assertTrue(
            any(f.rule == "code_fence_no_language" and f.severity == "hard" for f in findings)
        )

    def test_multiple_h1_is_hard(self) -> None:
        code, findings, _ = run_check(TWO_H1S)
        self.assertEqual(1, code)
        self.assertTrue(
            any(f.rule == "multiple_h1" and f.severity == "hard" for f in findings)
        )


class SoftFindingsTests(unittest.TestCase):
    def test_badge_count_is_soft_and_exit_untouched(self) -> None:
        code, findings, stats = run_check(EIGHT_BADGES)
        self.assertEqual(0, code)
        self.assertEqual(8, stats["badges"])
        badge_findings = [f for f in findings if f.rule == "badge_count"]
        self.assertEqual(1, len(badge_findings))
        self.assertEqual("soft", badge_findings[0].severity)
        self.assertIn("8", badge_findings[0].detail)

    def test_clean_readme_has_no_hard_findings(self) -> None:
        code, findings, _ = run_check(CLEAN)
        self.assertEqual(0, code)
        self.assertFalse(any(f.severity == "hard" for f in findings))


class BadgeCountingTests(unittest.TestCase):
    def test_markdown_shields_badge_counts(self) -> None:
        self.assertEqual(
            1, CHECK.count_badges("![License](https://img.shields.io/github/license/o/r)")
        )

    def test_html_img_badge_counts(self) -> None:
        self.assertEqual(
            1, CHECK.count_badges('<img src="https://img.shields.io/github/license/o/r" />')
        )

    def test_linked_image_counts_as_badge(self) -> None:
        self.assertEqual(
            1, CHECK.count_badges('[![logo](assets/logo.png)](https://example.com)')
        )
        self.assertEqual(
            1, CHECK.count_badges('<a href="LICENSE"><img src="assets/logo.png"></a>')
        )

    def test_plain_screenshot_does_not_count(self) -> None:
        self.assertEqual(0, CHECK.count_badges("![screenshot](docs/screenshot.png)"))
        self.assertEqual(0, CHECK.count_badges('<img src="docs/screenshot.png" />'))


class StructureRegressionTests(unittest.TestCase):
    def test_inline_code_heading_anchor_is_not_broken(self) -> None:
        content = (
            "# p\n\n"
            "[Install](#install)\n\n"
            "## `install`\n\n"
            "```bash\npip install p\n```\n"
        )
        code, findings, _ = run_check(content)
        self.assertEqual(0, code)
        self.assertFalse(any(f.rule == "broken_anchor" for f in findings))

    def test_nested_shorter_fence_does_not_close_early(self) -> None:
        content = (
            "# p\n\n"
            "````bash\n"
            "echo hi\n"
            "```\n"
            "inner example\n"
            "```\n"
            "````\n"
        )
        code, findings, _ = run_check(content)
        self.assertEqual(0, code)
        self.assertFalse(any(f.rule == "code_fence_no_language" for f in findings))

    def test_two_setext_h1s_are_hard(self) -> None:
        content = (
            "Title One\n"
            "=========\n\n"
            "Body.\n\n"
            "Title Two\n"
            "=========\n\n"
            "```bash\npip install p\n```\n"
        )
        code, findings, stats = run_check(content)
        self.assertEqual(1, code)
        self.assertEqual(2, stats["h1_count"])
        self.assertTrue(
            any(f.rule == "multiple_h1" and f.severity == "hard" for f in findings)
        )

    def test_front_matter_and_table_separator_are_not_h1(self) -> None:
        content = (
            "---\n"
            "title: x\n"
            "---\n\n"
            "# real\n\n"
            "| a | b |\n"
            "| --- | --- |\n\n"
            "```bash\npip install p\n```\n"
        )
        code, findings, stats = run_check(content)
        self.assertEqual(0, code)
        self.assertEqual(1, stats["h1_count"])
        self.assertFalse(any(f.rule == "multiple_h1" for f in findings))


if __name__ == "__main__":
    unittest.main()
