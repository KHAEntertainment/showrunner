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
import math
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
    
    # Flow mapping/sequence checks will be done per-value during parsing
    
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
                    # Check for flow syntax in UNQUOTED values only
                    stripped = value.lstrip()
                    if stripped and not stripped.startswith('"') and not stripped.startswith("'"):
                        # Check for non-empty flow syntax (exclude empty [] or {})
                        if ("{" in value or "[" in value) and value.strip() not in ["{}", "[]"]:
                                fail(f"flow mapping syntax detected on line {i}")
                    
                    # Check for unterminated quotes
                    if (value.startswith('"') and not value.endswith('"')) or                        (value.startswith("'") and not value.endswith("'")):
                        fail(f"unterminated quote on line {i}")
                    
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


# --- Goal-run block (Issue #193, lane L2) -----------------------------------
#
# Optional and additive under schema_version 2. A ledger with no `goal_run`
# key, or `goal_run: null`, never reaches this code, so pre-L2 ledgers parse and
# validate exactly as before. When the block is present it is read by a small
# indentation-based reader (block maps, block lists of scalars, scalars, and the
# empty `[]` / `{}` forms only) and validated against the merged goal_run.py
# public API. Every failure is reported as `goal_run.<field>: <reason>`.

GOAL_RUN_KEY = "goal_run"
_GOAL_ASSIGNMENT_KEYS = (
    "repo", "run", "mode", "lead", "plan_ref", "source", "approval_revision",
    "fixed_issues", "coordinator", "charter_revision", "contract_refs",
)
_GOAL_POLICY_KEYS = ("run_time_hours", "dispatch_cap_per_issue", "gv_retries", "spend_cap")
_GOAL_COUNTER_KEYS = (
    "usage_measured", "spend", "gv_retries_used",
    "dispatch_counts", "dispatch_request_ids", "request_issues",
)
# goal_run.py refusal reasons that carry no detail field, mapped to the ledger field.
_GOAL_REASON_FIELDS = {
    "approval_revision_mismatch": "approval_revision",
    "source_revision_missing": "source",
    "source_revision_mismatch": "source",
    "source_locator_missing": "source",
    "empty_issue_set": "fixed_issues",
    "bare_ambiguous_issue_id": "fixed_issues",
    "duplicate_issue": "fixed_issues",
    "cross_repo_issue": "fixed_issues",
}
_GOAL_KEY_RE = re.compile(r'^(?:"([^"]+)"|([A-Za-z0-9_][A-Za-z0-9_.\-/#]*)):(?:\s+(.*))?$')
_GOAL_INT_RE = re.compile(r"^-?[0-9]+$")
_GOAL_FLOAT_RE = re.compile(r"^-?[0-9]+\.[0-9]+$")


class GoalRunError(Exception):
    """A malformed goal-run block. ``field`` is the dotted path under goal_run."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field
        self.message = message


def _goal_scalar(raw: str, path: str, lineno: int):
    if raw in ("null", "~"):
        return None
    if raw in ("true", "True"):
        return True
    if raw in ("false", "False"):
        return False
    if raw == "[]":
        return []
    if raw == "{}":
        return {}
    if raw[0] in "\"'":
        if len(raw) < 2 or raw[-1] != raw[0]:
            raise GoalRunError(path, f"unterminated quote on line {lineno}")
        return raw[1:-1]
    if raw[0] in "[{":
        raise GoalRunError(path, f"flow syntax is not allowed (line {lineno})")
    if " #" in raw:
        raise GoalRunError(path, f"inline comment is not allowed (line {lineno})")
    if _GOAL_INT_RE.match(raw):
        return int(raw)
    if _GOAL_FLOAT_RE.match(raw):
        return float(raw)
    return raw


def _goal_parse_node(tokens: list, index: int, indent: int, path: str):
    """Parse the map or list starting at ``tokens[index]`` (all at ``indent``)."""
    if tokens[index][1].startswith("-"):
        items = []
        while index < len(tokens) and tokens[index][0] == indent:
            _, content, lineno = tokens[index]
            if not (content == "-" or content.startswith("- ")):
                raise GoalRunError(path, f"mixed list and map on line {lineno}")
            raw = content[1:].strip()
            if not raw or _GOAL_KEY_RE.match(raw) and not raw[0] in "\"'":
                raise GoalRunError(path, f"only scalar list items are supported (line {lineno})")
            items.append(_goal_scalar(raw, path, lineno))
            index += 1
        return items, index

    mapping = {}
    while index < len(tokens) and tokens[index][0] == indent:
        _, content, lineno = tokens[index]
        match = _GOAL_KEY_RE.match(content)
        if not match:
            raise GoalRunError(path, f"malformed line {lineno}")
        key = match.group(1) if match.group(1) is not None else match.group(2)
        child_path = f"{path}.{key}"
        if key in mapping:
            raise GoalRunError(child_path, f"duplicate key on line {lineno}")
        raw = (match.group(3) or "").strip()
        index += 1
        if raw:
            mapping[key] = _goal_scalar(raw, child_path, lineno)
            continue
        if index >= len(tokens) or tokens[index][0] <= indent:
            raise GoalRunError(child_path, f"missing value on line {lineno}")
        mapping[key], index = _goal_parse_node(tokens, index, tokens[index][0], child_path)
    if index < len(tokens) and tokens[index][0] > indent:
        raise GoalRunError(path, f"unexpected indentation on line {tokens[index][2]}")
    return mapping, index


def parse_goal_run_block(text: str) -> dict:
    """Read the ``goal_run:`` block of a ledger's frontmatter into a dict.

    Raises ``GoalRunError`` on anything outside the supported subset."""
    end = text.find("\n---\n")
    lines = text[4:end].split("\n") if end != -1 else []
    starts = [i for i, line in enumerate(lines) if re.match(rf"^{GOAL_RUN_KEY}:", line)]
    if len(starts) > 1:
        raise GoalRunError(GOAL_RUN_KEY, f"duplicate key on line {starts[1] + 2}")
    start = None
    if starts and re.match(rf"^{GOAL_RUN_KEY}:\s*$", lines[starts[0]]):
        start = starts[0]
    if start is None:
        raise GoalRunError(GOAL_RUN_KEY, "must be a block map or null")

    tokens = []
    for i in range(start + 1, len(lines)):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" "):
            break
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise GoalRunError(GOAL_RUN_KEY, f"tab indentation on line {i + 2}")
        tokens.append((len(line) - len(line.lstrip(" ")), stripped, i + 2))
    if not tokens:
        raise GoalRunError(GOAL_RUN_KEY, "block is empty")
    block, index = _goal_parse_node(tokens, 0, tokens[0][0], GOAL_RUN_KEY)
    if index != len(tokens):
        raise GoalRunError(GOAL_RUN_KEY, f"unexpected indentation on line {tokens[index][2]}")
    if not isinstance(block, dict):
        raise GoalRunError(GOAL_RUN_KEY, "must be a map")
    return block


def _load_goal_run_module():
    """Import the merged goal_run.py from this script's own directory."""
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    try:
        import goal_run  # noqa: PLC0415 - only goal-run ledgers need it
    except ImportError as exc:
        raise GoalRunError(GOAL_RUN_KEY, f"goal_run.py is unavailable ({exc})") from exc
    return goal_run


def _is_count(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _goal_utc(goal_run, policy, value, field: str) -> None:
    """Strict UTC check through goal_run's public evaluate_limits, which refuses
    any approval time that is naive, non-UTC or malformed."""
    result = goal_run.evaluate_limits(policy, goal_run.RunCounters(), value, value)
    if result.outcome == "invalid":
        raise GoalRunError(f"{GOAL_RUN_KEY}.{field}", "must be a strict UTC ISO 8601 time")


def _validate_goal_counters(counters, fixed_issues: list, goal_run) -> None:
    base = f"{GOAL_RUN_KEY}.counters"
    if not isinstance(counters, dict):
        raise GoalRunError(base, "must be a map")
    for key in counters:
        if key not in _GOAL_COUNTER_KEYS:
            raise GoalRunError(f"{base}.{key}", "unknown counter field")
    for key in _GOAL_COUNTER_KEYS:
        if key not in counters:
            raise GoalRunError(f"{base}.{key}", "missing required field")

    measured = counters["usage_measured"]
    if not isinstance(measured, bool):
        raise GoalRunError(f"{base}.usage_measured", "must be true or false")
    spend = counters["spend"]
    if measured:
        if spend == goal_run.USAGE_UNKNOWN or not (
            isinstance(spend, (int, float)) and not isinstance(spend, bool)
            and math.isfinite(float(spend)) and spend >= 0
        ):
            raise GoalRunError(f"{base}.spend", "measured usage must be a finite number >= 0")
    elif spend != goal_run.USAGE_UNKNOWN:
        if spend == 0 and not isinstance(spend, bool):
            raise GoalRunError(f"{base}.spend", "unmeasured usage must be unknown, never 0")
        raise GoalRunError(f"{base}.spend", "unmeasured usage must be unknown")

    gv_used = counters["gv_retries_used"]
    if gv_used != goal_run.USAGE_UNKNOWN and not _is_count(gv_used):
        raise GoalRunError(f"{base}.gv_retries_used", "must be an integer >= 0 or unknown")

    scope = set(fixed_issues)
    for key in ("dispatch_counts", "dispatch_request_ids", "request_issues"):
        if not isinstance(counters[key], dict):
            raise GoalRunError(f"{base}.{key}", "must be a map")
    counts = counters["dispatch_counts"]
    ids = counters["dispatch_request_ids"]
    owners = counters["request_issues"]
    for issue, count in counts.items():
        if issue not in scope:
            raise GoalRunError(f"{base}.dispatch_counts", f"{issue} is not in fixed_issues")
        if not _is_count(count):
            raise GoalRunError(f"{base}.dispatch_counts", f"{issue} count must be an integer >= 0")
    for issue, requests in ids.items():
        if issue not in scope:
            raise GoalRunError(f"{base}.dispatch_request_ids", f"{issue} is not in fixed_issues")
        if not isinstance(requests, list) or any(
            not isinstance(r, str) or not r for r in requests
        ) or len(set(requests)) != len(requests):
            raise GoalRunError(
                f"{base}.dispatch_request_ids", f"{issue} must list unique request ids"
            )
        if counts.get(issue, 0) != len(requests):
            raise GoalRunError(
                f"{base}.dispatch_counts", f"{issue} count does not match its request ids"
            )
        for request in requests:
            if owners.get(request) != issue:
                raise GoalRunError(
                    f"{base}.request_issues", f"{request} does not map to {issue}"
                )
    for issue, count in counts.items():
        if count and issue not in ids:
            raise GoalRunError(
                f"{base}.dispatch_counts", f"{issue} count does not match its request ids"
            )
    recorded = {r for requests in ids.values() if isinstance(requests, list) for r in requests}
    for request in owners:
        if request not in recorded:
            raise GoalRunError(f"{base}.request_issues", f"{request} has no recorded dispatch")


def validate_goal_run(block) -> None:
    """Validate a goal-run block (a plain dict). Raises ``GoalRunError``.

    The assignment fields are checked by goal_run.normalize_entry and must equal
    the normalized ``Assignment.to_dict()``; the policy by goal_run.apply_policy;
    the counters against goal_run.RunCounters' fields plus the two ledger-only
    counters ``usage_measured`` and ``gv_retries_used``."""
    if not isinstance(block, dict):
        raise GoalRunError(GOAL_RUN_KEY, "must be a map")
    goal_run = _load_goal_run_module()

    entry = {key: block[key] for key in _GOAL_ASSIGNMENT_KEYS if key in block}
    normalized = goal_run.normalize_entry(entry)
    if normalized.outcome != "accept":
        field = normalized.detail.get("field") or _GOAL_REASON_FIELDS.get(normalized.reason)
        path = f"{GOAL_RUN_KEY}.{field}" if field else GOAL_RUN_KEY
        raise GoalRunError(path, normalized.reason)
    for key, expected in normalized.value.to_dict().items():
        if block.get(key) != expected:
            raise GoalRunError(
                f"{GOAL_RUN_KEY}.{key}", "does not match the normalized assignment"
            )

    policy = block.get("policy")
    if not isinstance(policy, dict):
        raise GoalRunError(f"{GOAL_RUN_KEY}.policy", "must be a map")
    for key in policy:
        if key not in _GOAL_POLICY_KEYS:
            raise GoalRunError(f"{GOAL_RUN_KEY}.policy.{key}", "unknown limit field")
    for key in _GOAL_POLICY_KEYS:
        if key not in policy:
            raise GoalRunError(f"{GOAL_RUN_KEY}.policy.{key}", "missing required field")
    applied = goal_run.apply_policy(project_policy=policy, mode=block["mode"])
    if applied.outcome != "accept":
        field = applied.detail.get("field")
        path = f"{GOAL_RUN_KEY}.policy.{field}" if field else f"{GOAL_RUN_KEY}.policy"
        raise GoalRunError(path, applied.reason)

    _goal_utc(goal_run, applied.value, block.get("approval_time"), "approval_time")
    if block.get("next_wake_at", None) is not None:
        _goal_utc(goal_run, applied.value, block["next_wake_at"], "next_wake_at")
    elif "next_wake_at" not in block:
        raise GoalRunError(f"{GOAL_RUN_KEY}.next_wake_at", "missing required field")
    if not isinstance(block.get("paused"), bool):
        raise GoalRunError(f"{GOAL_RUN_KEY}.paused", "must be true or false")

    _validate_goal_counters(block.get("counters"), block["fixed_issues"], goal_run)


def validate_goal_run_text(text: str, data: dict) -> None:
    """Entry point from main(): a no-op unless ``goal_run`` is present and not
    null, so ledgers without goal fields are untouched. The frontmatter is also
    scanned for repeated top-level ``goal_run:`` lines, because the flat reader
    keeps only the last one (a trailing ``goal_run: null`` must not hide a block)."""
    end = text.find("\n---\n")
    frontmatter = text[4:end] if end != -1 else ""
    occurrences = len(re.findall(rf"^{GOAL_RUN_KEY}:", frontmatter, re.M))
    if occurrences == 0:
        return
    if occurrences == 1 and data.get(GOAL_RUN_KEY) is None:
        return
    try:
        validate_goal_run(parse_goal_run_block(text))
    except GoalRunError as exc:
        fail(str(exc))
    except Exception as exc:  # fail closed, never a traceback
        fail(f"{GOAL_RUN_KEY}: malformed block ({type(exc).__name__}: {exc})")


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
    
    validate_goal_run_text(content, data)
    
    print(f"OK: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
