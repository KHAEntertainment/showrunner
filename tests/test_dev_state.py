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
execution:
  backend: {name: traycer}
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
execution:
  backend: [traycer]
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

    def test_truncated_fails(self):
        """Truncated file should fail."""
        content = """---
schema_version: 2
run_id: test
run_status:
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


if __name__ == "__main__":
    unittest.main()
