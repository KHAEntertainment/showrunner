#!/usr/bin/env python3
"""
Ledger profile validator for .agent/dev-state.md.

Usage:
    python3 dev_state.py --validate <path>

Parses the YAML subset (maps, lists, scalars; no anchors, tags, or flow syntax)
and fails closed on any parse or profile error.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


VALID_RUN_STATUSES = frozenset({"active", "blocked", "recovering", "complete", "standby"})


def fail(message: str) -> None:
    """Print a failure message and exit with non-zero code."""
    print(f"FAIL: {message}", file=sys.stderr)
    sys.exit(1)


def parse_simple_yaml(text: str) -> dict:
    """
    Parse a YAML subset: maps, lists, and scalars only.
    Rejects anchors, tags, flow mappings, flow sequences.
    
    Returns the parsed dict (top-level must be a map).
    """
    if not text.strip():
        fail("empty file")
    
    # Only validate the YAML portion (before any markdown heading)
    markdown_start = text.find("\n## ")
    if markdown_start == -1:
        yaml_content = text
    else:
        yaml_content = text[:markdown_start]
    
    # Check for YAML anchors: &name at start of value (after : or whitespace)
    if re.search(r":\s+&\w+", yaml_content):
        fail("anchor syntax detected")
    # Check for YAML anchor references: *name at start of a value
    if re.search(r"[\s:]\*\w+", yaml_content):
        fail("anchor reference detected")
    
    # Check for tags (!) in YAML content
    if re.search(r"!\w+", yaml_content):
        fail("tag syntax detected")
    
    # Check for YAML flow mappings { } in YAML content only
    if re.search(r"\{[^}]+\}", yaml_content):
        fail("flow mapping syntax detected")
    
    # Check for YAML flow sequences [ ] in YAML content only
    if re.search(r"\[[^\]]+\]", yaml_content):
        fail("flow sequence syntax detected")
    
    # Parse frontmatter if present - only the YAML portion before closing ---
    if not text.startswith("---\n"):
        fail("missing opening frontmatter delimiter")
    end = text.find("\n---\n")
    if end == -1:
        fail("missing closing frontmatter delimiter")
    content = text[4:end]
    
    # Parse simple key: value pairs (top-level only for validation)
    result = {}
    lines = content.split("\n")
    current_key = None
    in_literal_block = False
    in_list_item = False
    
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        
        # Skip comments and empty lines
        if not stripped or stripped.startswith("#"):
            continue
        
        # Check if we're entering a literal block scalar
        if line.rstrip().endswith("|") or ("| " in line and line.strip().endswith("|")):
            in_literal_block = True
            continue
        
        # Skip lines in literal block (indented content)
        if in_literal_block and (line.startswith("  ") or line.startswith("\t") or not line.strip()):
            continue
        
        # End of literal block if we get an unindented line
        if in_literal_block and not line.startswith("  ") and not line.startswith("\t"):
            in_literal_block = False
        
        # Handle indentation for list items and continuation lines
        if line.startswith("  ") and not line.startswith("   "):
            # OK - 2-space indent (list items, continuations)
            continue
        if line.startswith("   ") and not line.startswith("    "):
            # 3-space indent is invalid
            fail(f"unexpected indentation on line {i}")
        if line.startswith("\t"):
            continue
        
        # Parse key: value
        match = re.match(r"^(\w[\w_]*):\s*(.*)$", line)
        if match:
            key = match.group(1)
            value = match.group(2).strip()
            
            # Handle list items (indented with dash)
            if value == "" or value.startswith("-"):
                current_key = key
                if key not in result:
                    result[key] = []
                elif not isinstance(result[key], list):
                    fail(f"key '{key}' used as both scalar and list")
                if value and value.startswith("-"):
                    result[key].append(value[1:].strip())
            else:
                # Convert scalar values
                if value == "null" or value == "~":
                    result[key] = None
                elif value == "true" or value == "True":
                    result[key] = True
                elif value == "false" or value == "False":
                    result[key] = False
                else:
                    # Try to convert to number
                    try:
                        result[key] = int(value.strip('"').strip("'"))
                    except ValueError:
                        try:
                            result[key] = float(value.strip('"').strip("'"))
                        except ValueError:
                            result[key] = value.strip('"').strip("'")
                current_key = None
        elif line and not line.startswith("  ") and not line.startswith("\t"):
            fail(f"parse error on line {i}: malformed line")
    
    return result


def validate_profile(data: dict) -> None:
    """Check that the parsed data conforms to the ledger profile."""
    # Check schema_version
    schema_version = data.get("schema_version")
    if schema_version != 2:
        fail(f"schema_version must be 2, got {schema_version}")
    
    # Check run_status
    run_status = data.get("run_status")
    if run_status is not None and run_status not in VALID_RUN_STATUSES:
        fail(f"run_status must be one of {sorted(VALID_RUN_STATUSES)}, got '{run_status}'")
    
    # Check run_id and run_status when present
    run_id = data.get("run_id")
    if run_id is not None and (run_id == "" or run_id is None):
        fail("run_id must be non-empty when present")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate ledger profile")
    parser.add_argument("--validate", metavar="PATH", required=True,
                       help="Path to ledger file to validate")
    args = parser.parse_args()
    
    path = Path(args.validate)
    if not path.is_file():
        fail(f"file not found: {path}")
    
    content = path.read_text(encoding="utf-8")
    
    try:
        data = parse_simple_yaml(content)
    except SystemExit:
        raise
    except Exception as e:
        fail(f"parse error: {e}")
    
    try:
        validate_profile(data)
    except SystemExit:
        raise
    except Exception as e:
        fail(f"profile validation error: {e}")
    
    print(f"OK: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
