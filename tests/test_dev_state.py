#!/usr/bin/env python3
"""Tests for dev_state.py ledger validator."""

import subprocess
import tempfile
import unittest
from pathlib import Path


DEV_STATE = Path(__file__).parent.parent / "skills" / "dev" / "scripts" / "dev_state.py"
TEMPLATE = Path(__file__).parent.parent / "skills" / "dev" / "templates" / "DEV_STATE_TEMPLATE.md"


def run_validator(content: str) -> tuple[int, str, str]:
    """Run validator on in-memory content. Returns (exit_code, stdout, stderr)."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(content)
        path = f.name
    try:
        result = subprocess.run(
            ["python3", str(DEV_STATE), "--validate", path],
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout, result.stderr
    finally:
        Path(path).unlink()


class TestDevStateValidator(unittest.TestCase):
    def test_template_passes(self):
        """The shipped template should pass."""
        content = TEMPLATE.read_text()
        code, _, _ = run_validator(content)
        self.assertEqual(code, 0)

    def test_anchor_fails(self):
        """Anchor should fail."""
        content = """---
schema_version: 2
run_id: test
run_status: active
execution:
  backend: &traycer traycer
---
"""
        code, _, stderr = run_validator(content)
        self.assertNotEqual(code, 0)
        self.assertIn("anchor", stderr.lower())

    def test_tag_fails(self):
        """Tag should fail."""
        content = """---
schema_version: 2
run_id: test
run_status: active
execution:
  backend: !!str traycer
---
"""
        code, _, stderr = run_validator(content)
        self.assertNotEqual(code, 0)
        self.assertIn("tag", stderr.lower())

    def test_flow_mapping_fails(self):
        """Flow mapping should fail."""
        content = """---
schema_version: 2
run_id: test
run_status: active
data: {name: traycer}
---
"""
        code, _, stderr = run_validator(content)
        self.assertNotEqual(code, 0)
        self.assertIn("flow", stderr.lower())

    def test_flow_sequence_fails(self):
        """Flow sequence with content should fail."""
        content = """---
schema_version: 2
run_id: test
run_status: active
data: [traycer]
---
"""
        code, _, stderr = run_validator(content)
        self.assertNotEqual(code, 0)
        self.assertIn("flow", stderr.lower())
    
    def test_bad_indent_fails(self):
        """Bad indentation (3 spaces) should fail."""
        content = """---
schema_version: 2
run_id: test
run_status: active
execution:
   backend: traycer
---
"""
        code, _, stderr = run_validator(content)
        self.assertNotEqual(code, 0)

    def test_truncated_fails(self):
        """Truncated file should fail."""
        content = """---
schema_version: 2
run_id: test
run_status:
"""
        code, _, stderr = run_validator(content)
        self.assertNotEqual(code, 0)

    def test_missing_closing_delimiter_fails(self):
        """Frontmatter without closing delimiter should fail."""
        content = """---
schema_version: 2
run_id: test
run_status: active
"""
        code, _, stderr = run_validator(content)
        self.assertNotEqual(code, 0)

    def test_invalid_run_status_fails(self):
        """Invalid run_status should fail."""
        content = """---
schema_version: 2
run_id: test
run_status: invalid
---
"""
        code, _, stderr = run_validator(content)
        self.assertNotEqual(code, 0)
        self.assertIn("run_status", stderr.lower())

    def test_missing_run_id_passes(self):
        """Missing run_id (optional) should pass."""
        content = """---
schema_version: 2
run_status: active
next_action: test
---
"""
        code, _, _ = run_validator(content)
        self.assertEqual(code, 0)

    def test_empty_run_id_fails(self):
        """Empty run_id should fail."""
        content = """---
schema_version: 2
run_id: ""
run_status: active
---
"""
        code, _, stderr = run_validator(content)
        self.assertNotEqual(code, 0)
        self.assertIn("run_id", stderr.lower())

    def test_missing_lead_checkpoint_passes(self):
        """Missing lead_checkpoint (optional) should pass."""
        content = """---
schema_version: 2
run_id: test
run_status: active
next_action: test
---
"""
        code, _, _ = run_validator(content)
        self.assertEqual(code, 0)

    def test_single_quoted_json_passes(self):
        """Single-quoted JSON string passes."""
        content = """---
schema_version: 2
run_id: test
run_status: active
guard_at_merge: '{"at_head":0,"head":"abc"}'
---
"""
        code, _, _ = run_validator(content)
        self.assertEqual(code, 0)

    def test_double_quoted_flow_passes(self):
        """Double-quoted string containing { or [ passes."""
        content = """---
schema_version: 2
run_id: test
run_status: active
        data: "value with { and ["
---
"""
        code, _, _ = run_validator(content)
        self.assertEqual(code, 0)

    def test_unquoted_flow_mapping_fails(self):
        """Unquoted flow mapping fails."""
        content = """---
schema_version: 2
run_id: test
run_status: active
data: {a: 1}
---
"""
        code, _, stderr = run_validator(content)
        self.assertNotEqual(code, 0)
        self.assertIn("flow", stderr.lower())

    def test_unquoted_flow_sequence_fails(self):
        """Unquoted flow sequence fails."""
        content = """---
schema_version: 2
run_id: test
run_status: active
data: [1, 2]
---
"""
        code, _, stderr = run_validator(content)
        self.assertNotEqual(code, 0)
        self.assertIn("flow", stderr.lower())

    def test_unterminated_quote_fails(self):
        """Unterminated quote fails."""
        content = """---
schema_version: 2
run_id: test
run_status: active
data: "unclosed
---
"""
        code, _, stderr = run_validator(content)
        self.assertNotEqual(code, 0)
        self.assertIn("quote", stderr.lower())


if __name__ == "__main__":
    unittest.main()
