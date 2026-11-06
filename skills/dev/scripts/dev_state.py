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
import dataclasses
import math
import re
import sys
from pathlib import Path
from types import MappingProxyType


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
# Run-state keys the template documents beside the assignment keys. The top
# level of a goal_run block is closed: these plus _GOAL_ASSIGNMENT_KEYS.
_GOAL_RUN_STATE_KEYS = (
    "approval_time", "next_wake_at", "paused", "policy", "counters",
    # Issue #194 lane L4: optional grant and gate records (absent or null is valid).
    "grant", "merge_ledger", "gate_evidence", "delegated_records",
    # Issue #196 lane L6: optional recovery records (absent or null is valid).
    "obligations", "custody", "event_ledger", "recovery_receipts", "unknown_effects",
    # Issue #196 lane L7: optional lifecycle-clock counter (absent or null is valid).
    "context_resets",
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
# Finite decimals and exponent forms (repr() writes 1e-06, 2.5e+30); inf/nan are
# never numbers here.
_GOAL_FLOAT_RE = re.compile(r"^-?(?:[0-9]+\.[0-9]+|[0-9]+(?:\.[0-9]+)?[eE][-+]?[0-9]+)$")


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
        number = float(raw)
        if not math.isfinite(number):
            raise GoalRunError(path, f"number is not finite (line {lineno})")
        return number
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
        # Tabs are refused before the boundary test: a tab-led line must never
        # be mistaken for the next top-level key and silently end the block.
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise GoalRunError(GOAL_RUN_KEY, f"tab indentation on line {i + 2}")
        if not line.startswith(" "):
            break
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


# --- Goal-run grant and gate records (Issue #194, lane L4) -------------------
#
# Optional and additive: each key may be absent or null, so an L2 block (the 16
# keys above minus these four) validates unchanged. Shapes follow the merged
# goal_authority.py public API: `grant` is the D2 bounded grant validate_grant
# checks, `merge_ledger` is a MergeLedger (consumed pairs written as a map of PR
# number to merge SHA, because the reader allows only scalar lists), and
# `delegated_records` are D7.2 control records checked by
# validate_delegated_record. goal_authority.py is imported, never copied.

_GOAL_AUTHORITY_KEYS = ("grant", "merge_ledger", "gate_evidence", "delegated_records")
_GOAL_GRANT_KEYS = (
    "run_id", "host", "repository", "base", "eligible_issues", "max_merges",
    "expires_at", "authorized_by", "excluded_actions", "merge_method",
)
_GOAL_AUTHORIZED_BY_KEYS = ("who", "at", "instruction")
_GOAL_MERGE_LEDGER_KEYS = (
    "run_id", "consumed", "slots_used", "revoked_at", "grant_in_force",
    "halted", "halt_ref", "reopen_issues", "halt_history", "cleared_halts",
)
_GOAL_GATE_EVIDENCE_KEYS = ("checked_head", "outcome", "failures", "checked_at")
# The gate names goal_authority.check_gates reports in detail["failures"].
_GOAL_GATE_NAMES = (
    "record_shape", "current_head", "destination", "qa", "review_level", "ask",
    "external_review",
)
_GOAL_GATE_OUTCOMES = ("accept", "blocked")
_GOAL_DELEGATED_KEYS = ("gate", "decision", "reasoning", "evidence_pointer", "reversal_path")
_GOAL_PR_KEY_RE = re.compile(r"^[1-9][0-9]*$")
_GOAL_QUALIFIED_ISSUE_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[0-9]+$")


def _load_goal_authority_module():
    """Import the merged goal_authority.py from this script's own directory."""
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    try:
        import goal_authority  # noqa: PLC0415 - only grant-bearing ledgers need it
    except ImportError as exc:
        raise GoalRunError(GOAL_RUN_KEY, f"goal_authority.py is unavailable ({exc})") from exc
    return goal_authority


def _nonempty(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _closed_map(value, base: str, keys: tuple, label: str, optional=()) -> None:
    if not isinstance(value, dict):
        raise GoalRunError(base, "must be a map")
    for key in value:
        if key not in keys:
            raise GoalRunError(f"{base}.{key}", f"unknown {label} field")
    for key in keys:
        if key not in value and key not in optional:
            raise GoalRunError(f"{base}.{key}", "missing required field")


def _qualified_issue_list(value, path: str) -> list:
    """Type-check an Issue list at this boundary, before any hashing or
    set membership: a list of unique qualified ``OWNER/REPO#N`` strings."""
    if not isinstance(value, list):
        raise GoalRunError(path, "must be a list of qualified OWNER/REPO#N strings")
    for item in value:
        if not isinstance(item, str) or not _GOAL_QUALIFIED_ISSUE_RE.match(item):
            raise GoalRunError(path, "each item must be a qualified OWNER/REPO#N string")
    if len(set(value)) != len(value):
        raise GoalRunError(path, "must not repeat an Issue")
    return value


def _string_list(value, path: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise GoalRunError(path, "must be a list of strings")


def _validate_goal_grant(grant, block, authority) -> None:
    base = f"{GOAL_RUN_KEY}.grant"
    _closed_map(grant, base, _GOAL_GRANT_KEYS, "grant", optional=("merge_method",))
    if grant["eligible_issues"] is not None:
        if grant["eligible_issues"] == []:
            raise GoalRunError(f"{base}.eligible_issues", "invalid_field")
        _qualified_issue_list(grant["eligible_issues"], f"{base}.eligible_issues")
    if grant["excluded_actions"] is not None:
        _string_list(grant["excluded_actions"], f"{base}.excluded_actions")
    auth = grant["authorized_by"]
    if isinstance(auth, dict):
        for key in auth:
            if key not in _GOAL_AUTHORIZED_BY_KEYS:
                raise GoalRunError(f"{base}.authorized_by.{key}", "unknown authorized_by field")
    checked = authority.validate_grant(grant)
    if not checked.may_proceed:
        field = checked.detail.get("field") or "grant"
        raise GoalRunError(f"{base}.{field}" if field != "grant" else base, checked.reason)
    # Bindings (D2 item 1, frozen scope): the grant belongs to this run and repo,
    # and its eligible Issues never exceed the frozen set (D2 scope row:
    # milestones, queries, boards and future Issues cannot expand eligibility).
    if grant["run_id"] != block["run"]:
        raise GoalRunError(f"{base}.run_id", "does not match goal_run.run")
    if grant["repository"] != block["repo"]:
        raise GoalRunError(f"{base}.repository", "does not match goal_run.repo")
    scope = set(block["fixed_issues"])
    for issue in grant["eligible_issues"]:
        if issue not in scope:
            raise GoalRunError(f"{base}.eligible_issues", f"{issue} is not in fixed_issues")


def _validate_goal_merge_ledger(record, grant, block, authority) -> None:
    base = f"{GOAL_RUN_KEY}.merge_ledger"
    if grant is None:
        raise GoalRunError(base, "requires a grant")
    _closed_map(record, base, _GOAL_MERGE_LEDGER_KEYS, "merge_ledger")
    if record["run_id"] != grant["run_id"]:
        raise GoalRunError(f"{base}.run_id", "does not match goal_run.grant.run_id")

    consumed = record["consumed"]
    if not isinstance(consumed, dict):
        raise GoalRunError(f"{base}.consumed", "must be a map of PR number to merge SHA")
    for pr, sha in consumed.items():
        if not _GOAL_PR_KEY_RE.match(str(pr)):
            raise GoalRunError(f"{base}.consumed", f"{pr} is not a PR number")
        if not _nonempty(sha):
            raise GoalRunError(f"{base}.consumed", f"{pr} needs a merge SHA")
    used = record["slots_used"]
    if not _is_count(used):
        raise GoalRunError(f"{base}.slots_used", "must be an integer >= 0")
    if used != len(consumed):
        raise GoalRunError(f"{base}.slots_used", "does not match consumed")
    if used > grant["max_merges"]:
        raise GoalRunError(f"{base}.slots_used", "exceeds goal_run.grant.max_merges")

    in_force = record["grant_in_force"]
    if not isinstance(in_force, bool):
        raise GoalRunError(f"{base}.grant_in_force", "must be true or false")
    revoked = record["revoked_at"]
    if revoked is not None:
        probe = authority.revoke_grant(authority.MergeLedger(run_id=record["run_id"]), revoked)
        if not probe.may_proceed:
            raise GoalRunError(f"{base}.revoked_at", "must be a timezone-qualified ISO 8601 time")
        if in_force:
            raise GoalRunError(f"{base}.grant_in_force", "must be false after a revocation")

    halted = record["halted"]
    if not isinstance(halted, bool):
        raise GoalRunError(f"{base}.halted", "must be true or false")
    halt_ref = record["halt_ref"]
    if halted and not _nonempty(halt_ref):
        raise GoalRunError(f"{base}.halt_ref", "a halt needs its failure reference")
    if not halted and halt_ref is not None:
        raise GoalRunError(f"{base}.halt_ref", "must be null when not halted")

    scope = set(block["fixed_issues"])
    reopen = _qualified_issue_list(record["reopen_issues"], f"{base}.reopen_issues")
    for issue in reopen:
        if issue not in scope:
            raise GoalRunError(f"{base}.reopen_issues", f"{issue} is not in fixed_issues")

    # Post-merge failure evidence (D2 item 9). halt_history (ledger-only) keeps
    # every failure reference with its Issue; cleared_halts (ledger-only) keeps
    # the triage ref each clear_halt was given. A failure on record that is no
    # longer halted must have a nonempty triage entry. This is a single-snapshot
    # check: history is append-only and written only by the lead through
    # merge_ledger_record_failure, and a coherent erasure of it is a breach of
    # the single-writer rule that this validator cannot detect.
    history = record["halt_history"]
    if not isinstance(history, dict):
        raise GoalRunError(f"{base}.halt_history", "must be a map of halt ref to Issue")
    for ref, issue in history.items():
        if not isinstance(issue, str) or not _GOAL_QUALIFIED_ISSUE_RE.match(issue):
            raise GoalRunError(f"{base}.halt_history", f"{ref} must map to a qualified OWNER/REPO#N string")
        if issue not in reopen:
            raise GoalRunError(f"{base}.halt_history", f"{ref} names {issue}, which is not in reopen_issues")
    recorded_issues = set(history.values())
    for issue in reopen:
        if issue not in recorded_issues:
            raise GoalRunError(f"{base}.reopen_issues", f"{issue} has no failure in halt_history")

    cleared = record["cleared_halts"]
    if not isinstance(cleared, dict):
        raise GoalRunError(f"{base}.cleared_halts", "must be a map of halt ref to triage ref")
    for ref, triage in cleared.items():
        if not _nonempty(triage):
            raise GoalRunError(f"{base}.cleared_halts", f"{ref} needs a triage ref")
        if ref not in history:
            raise GoalRunError(f"{base}.cleared_halts", f"{ref} is not in halt_history")
    if halted:
        if halt_ref not in history:
            raise GoalRunError(f"{base}.halt_ref", f"{halt_ref} is not in halt_history")
        if halt_ref in cleared:
            raise GoalRunError(f"{base}.cleared_halts", f"{halt_ref} is still halted")
    else:
        for ref in history:
            if ref not in cleared:
                raise GoalRunError(
                    f"{base}.cleared_halts", f"{ref} was cleared without triage evidence"
                )


def _validate_goal_gate_evidence(evidence, goal_run, policy) -> None:
    base = f"{GOAL_RUN_KEY}.gate_evidence"
    if not isinstance(evidence, dict):
        raise GoalRunError(base, "must be a map of PR number to gate evidence")
    for pr, entry in evidence.items():
        path = f"{base}.{pr}"
        if not _GOAL_PR_KEY_RE.match(str(pr)):
            raise GoalRunError(base, f"{pr} is not a PR number")
        _closed_map(entry, path, _GOAL_GATE_EVIDENCE_KEYS, "gate evidence")
        if not _nonempty(entry["checked_head"]):
            raise GoalRunError(f"{path}.checked_head", "must name the checked head")
        outcome = entry["outcome"]
        if outcome not in _GOAL_GATE_OUTCOMES:
            raise GoalRunError(f"{path}.outcome", "must be accept or blocked")
        failures = entry["failures"]
        if not isinstance(failures, list) or any(f not in _GOAL_GATE_NAMES for f in failures):
            raise GoalRunError(f"{path}.failures", "must list check_gates gate names")
        if outcome == "accept" and failures:
            raise GoalRunError(f"{path}.failures", "must be empty when outcome is accept")
        if outcome == "blocked" and not failures:
            raise GoalRunError(f"{path}.failures", "must name a gate when outcome is blocked")
        if not isinstance(entry["checked_at"], str):
            raise GoalRunError(f"{path}.checked_at", "must be a strict UTC ISO 8601 time")
        _goal_utc(goal_run, policy, entry["checked_at"], f"gate_evidence.{pr}.checked_at")


def _validate_goal_delegated_records(records, authority) -> None:
    base = f"{GOAL_RUN_KEY}.delegated_records"
    if not isinstance(records, dict):
        raise GoalRunError(base, "must be a map of record id to control record")
    for record_id, record in records.items():
        path = f"{base}.{record_id}"
        _closed_map(record, path, _GOAL_DELEGATED_KEYS, "delegated record")
        checked = authority.validate_delegated_record(record)
        if not checked.may_proceed:
            field = checked.detail.get("field")
            raise GoalRunError(f"{path}.{field}" if field else path, checked.reason)


def _validate_goal_authority_records(block, goal_run, policy) -> None:
    if all(block.get(key) is None for key in _GOAL_AUTHORITY_KEYS):
        return
    authority = _load_goal_authority_module()
    grant = block.get("grant")
    if grant is not None:
        _validate_goal_grant(grant, block, authority)
    if block.get("merge_ledger") is not None:
        _validate_goal_merge_ledger(block["merge_ledger"], grant, block, authority)
    if block.get("gate_evidence") is not None:
        _validate_goal_gate_evidence(block["gate_evidence"], goal_run, policy)
    if block.get("delegated_records") is not None:
        _validate_goal_delegated_records(block["delegated_records"], authority)


@dataclasses.dataclass(frozen=True)
class MergeLedgerState:
    """A goal_authority ``MergeLedger`` plus the two ledger-only maps the
    ``merge_ledger`` record keeps beside it: ``halt_history`` (halt ref ->
    Issue) and ``cleared_halts`` (halt ref -> triage ref). The helpers below
    carry all three together, so a rebuild never drops triage evidence."""

    ledger: object
    halt_history: dict = dataclasses.field(default_factory=dict)
    cleared_halts: dict = dataclasses.field(default_factory=dict)


def merge_ledger_to_record(state: MergeLedgerState) -> dict:
    """Write a ``MergeLedgerState`` as the ledger's ``merge_ledger`` map."""
    if not isinstance(state, MergeLedgerState):
        raise TypeError("merge_ledger_to_record takes a MergeLedgerState")
    ledger = state.ledger
    return {
        "run_id": ledger.run_id,
        "consumed": {str(pr): sha for pr, sha in ledger.consumed},
        "slots_used": ledger.slots_used,
        "revoked_at": ledger.revoked_at,
        "grant_in_force": ledger.grant_in_force,
        "halted": ledger.halted,
        "halt_ref": ledger.halt_ref,
        "reopen_issues": list(ledger.reopen_issues),
        "halt_history": dict(state.halt_history),
        "cleared_halts": dict(state.cleared_halts),
    }


def merge_ledger_from_record(record) -> MergeLedgerState:
    """Rebuild a ``MergeLedgerState`` from a validated ``merge_ledger`` map,
    before each decide_merge / record_merge call. Both ledger-only maps are
    required and carried through, never defaulted."""
    authority = _load_goal_authority_module()
    ledger = authority.MergeLedger(
        run_id=record["run_id"],
        consumed=tuple((int(pr), sha) for pr, sha in record["consumed"].items()),
        revoked_at=record["revoked_at"],
        halted=record["halted"],
        halt_ref=record["halt_ref"],
        reopen_issues=tuple(record["reopen_issues"]),
        grant_in_force=record["grant_in_force"],
    )
    return MergeLedgerState(ledger, dict(record["halt_history"]), dict(record["cleared_halts"]))


def merge_ledger_with(state: MergeLedgerState, result):
    """Carry a goal_authority result's new ``MergeLedger`` (record_merge,
    revoke_grant, carry_grant) into the state. A refused result is returned
    unchanged; an accepted one carries the new state as its ``value``."""
    if not result.may_proceed:
        return result
    return dataclasses.replace(result, value=dataclasses.replace(state, ledger=result.value))


def merge_ledger_record_failure(state: MergeLedgerState, issue, ref):
    """``record_post_merge_failure`` that also records ``ref`` -> ``issue`` in
    ``halt_history``. A reused ref is refused (``duplicate_halt_ref``)."""
    authority = _load_goal_authority_module()
    result = authority.record_post_merge_failure(state.ledger, issue, ref)
    if not result.may_proceed:
        return result
    if ref in state.halt_history:
        return dataclasses.replace(result, outcome="invalid", reason="duplicate_halt_ref",
                                   value=None, detail={"halt_ref": ref})
    history = dict(state.halt_history)
    history[ref] = issue
    return dataclasses.replace(result, value=MergeLedgerState(result.value, history, dict(state.cleared_halts)))


def merge_ledger_clear_halt(state: MergeLedgerState, triage_ref):
    """``clear_halt`` that records ``triage_ref`` against every halt ref not
    yet cleared, so the evidence survives the next write."""
    authority = _load_goal_authority_module()
    result = authority.clear_halt(state.ledger, triage_ref)
    if not result.may_proceed:
        return result
    cleared = dict(state.cleared_halts)
    if state.ledger.halted:
        for ref in state.halt_history:
            cleared.setdefault(ref, triage_ref)
    return dataclasses.replace(result, value=MergeLedgerState(result.value, dict(state.halt_history), cleared))


# --- Goal-run recovery records (Issue #196, lane L6) -------------------------
#
# Optional and additive: each key may be absent or null, so a pre-L6 block (the
# L2 16-key or L4 20-key block) validates unchanged. Shapes follow the merged
# goal_recovery.py public records so they round-trip: `obligations` is an
# `Obligations` snapshot (owed replies restated first), `event_ledger` an
# `EventLedger` (counted event identities), `recovery_receipts` a map of
# recovery-receipt-v1 records (checkpoint reference embedded), `custody` the
# classify_lineage inputs and their Result outcome/reason, and `unknown_effects`
# the unknown-effect outcomes with their blocked dependents. goal_recovery.py is
# imported, never copied.

_GOAL_RECOVERY_KEYS = (
    "obligations", "custody", "event_ledger", "recovery_receipts", "unknown_effects",
)
_GOAL_OBLIGATIONS_KEYS = (
    "children", "owed_replies", "original_request", "responsible_party",
    "evidence", "consumed_allowances", "worker_count", "defect_episode",
    "defect_episode_ref", "fix_batch_count", "owner_escalation",
)
_GOAL_OBLIGATION_STR_LISTS = ("children", "owed_replies", "evidence", "consumed_allowances")
_GOAL_OBLIGATION_STRINGS = ("original_request", "responsible_party")
_GOAL_OBLIGATION_COUNTS = ("worker_count",)
_GOAL_CUSTODY_KEYS = (
    "prior_session_id", "current_session_id", "claim", "outcome", "reason",
    "previous_lead_liveness",
)
_GOAL_CUSTODY_CLAIMS = ("successor", "takeover")
_GOAL_CUSTODY_OUTCOMES = ("accept", "invalid")
_GOAL_CUSTODY_LIVENESS = ("live", "unknown", "ended")
_GOAL_EVENT_LEDGER_KEYS = ("seen", "duplicates")
_GOAL_UNKNOWN_EFFECT_KEYS = ("state", "blocked", "evidence")
_GOAL_UNKNOWN_EFFECT_STATES = ("unknown", "resolved")


def _load_goal_recovery_module():
    """Import the merged goal_recovery.py from this script's own directory."""
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    try:
        import goal_recovery  # noqa: PLC0415 - only recovery-bearing ledgers need it
    except ImportError as exc:
        raise GoalRunError(GOAL_RUN_KEY, f"goal_recovery.py is unavailable ({exc})") from exc
    return goal_recovery


def obligations_to_record(obligations, defect_episodes=None) -> dict:
    """Write an ``Obligations`` snapshot as the ledger's ``obligations`` map.

    ``defect_episode`` (the 1-based ordinal of the canonical episode, 0 = none)
    and ``fix_batch_count`` carry the dataclass ints unchanged (lossless).
    ``defect_episode_ref`` is the ledger-only id of the episode at that ordinal,
    filled from ``defect_episodes`` (``parse_defect_episodes``) when given and
    in range, else ``null``; it has no dataclass field."""
    recovery = _load_goal_recovery_module()
    if not isinstance(obligations, recovery.Obligations):
        raise TypeError("obligations_to_record takes a goal_recovery.Obligations")
    return {
        "children": list(obligations.children),
        "owed_replies": list(obligations.owed_replies),
        "original_request": obligations.original_request,
        "responsible_party": obligations.responsible_party,
        "evidence": list(obligations.evidence),
        "consumed_allowances": list(obligations.consumed_allowances),
        "worker_count": obligations.worker_count,
        "defect_episode": obligations.defect_episode,
        "defect_episode_ref": _episode_ref(obligations.defect_episode, defect_episodes),
        "fix_batch_count": obligations.fix_batch_count,
        "owner_escalation": obligations.owner_escalation,
    }


def _episode_ref(ordinal, defect_episodes):
    if _is_count(ordinal) and defect_episodes and 0 < ordinal <= len(defect_episodes):
        return defect_episodes[ordinal - 1][0]
    return None


def obligations_from_record(record, defect_episodes=None):
    """Rebuild an ``Obligations`` from a validated ``obligations`` map. The int
    ``defect_episode`` and ``fix_batch_count`` round-trip unchanged; the
    ledger-only ``defect_episode_ref`` is not a dataclass field."""
    _validate_goal_obligations(record, defect_episodes or [])
    recovery = _load_goal_recovery_module()
    return recovery.Obligations(
        children=tuple(record["children"]),
        owed_replies=tuple(record["owed_replies"]),
        original_request=record["original_request"],
        responsible_party=record["responsible_party"],
        evidence=tuple(record["evidence"]),
        consumed_allowances=tuple(record["consumed_allowances"]),
        worker_count=record["worker_count"],
        defect_episode=record["defect_episode"],
        fix_batch_count=record["fix_batch_count"],
        owner_escalation=record["owner_escalation"],
    )


def event_ledger_to_record(ledger) -> dict:
    """Write an ``EventLedger`` as the ledger's ``event_ledger`` map."""
    recovery = _load_goal_recovery_module()
    if not isinstance(ledger, recovery.EventLedger):
        raise TypeError("event_ledger_to_record takes a goal_recovery.EventLedger")
    return {"seen": list(ledger.seen), "duplicates": dict(ledger.duplicates)}


def event_ledger_from_record(record):
    """Rebuild an ``EventLedger`` from a validated ``event_ledger`` map."""
    _validate_goal_event_ledger(record)
    recovery = _load_goal_recovery_module()
    return recovery.EventLedger(
        seen=tuple(record["seen"]), duplicates=MappingProxyType(dict(record["duplicates"]))
    )


class DefectEpisode(tuple):
    """One canonical ``defect_episodes`` entry: ``(id, fix_batches, bound, body)``.
    ``body`` is the episode's raw field lines (diagnoses included), so the whole
    canonical record compares equal or not. Index 0/1 are the id and counter."""

    __slots__ = ()

    def __new__(cls, episode_id, fix_batches, bound, body):
        return super().__new__(cls, (episode_id, fix_batches, bound, tuple(body)))

    id = property(lambda self: self[0])
    fix_batches = property(lambda self: self[1])
    bound = property(lambda self: self[2])
    body = property(lambda self: self[3])


_DEFECT_EPISODES_KEY = "defect_episodes"
# Episode-level keys read as scalars; every other episode field is kept raw.
_DEFECT_EPISODE_COUNT_KEYS = ("fix_batches", "bound")


def parse_defect_episodes(text: str) -> list:
    """Return the ordered ``DefectEpisode`` list of the top-level
    ``defect_episodes`` block, the sole counter authority for fix batches. An
    episode's 1-based ordinal is its list position.

    The block is read structurally, never by searching for a key anywhere: each
    episode is a two-space ``- <field>: <value>`` map item (fields in any order,
    exactly one ``id``), and its fields are read only at the episode's field
    indentation, so a ``fix_batches:`` line inside a deeper value (a diagnosis
    ``what_failed: |`` narrative) is never the counter. Unsupported or ambiguous
    shapes fail closed as ``defect_episodes: <reason>``: a repeated header, a flow
    or scalar header value, tab or odd indentation, a bare ``-`` item, an episode
    without an id, a repeated episode field or id, and an
    ``id``/``fix_batches``/``bound`` that is not a plain scalar of the right type.
    Only a ledger whose goal_run carries an ``obligations`` snapshot is read here.
    A ledger with no block, ``defect_episodes: []`` or ``null`` yields ``[]``."""
    key = _DEFECT_EPISODES_KEY
    end = text.find("\n---\n")
    lines = text[4:end].split("\n") if end != -1 else []
    starts = [i for i, line in enumerate(lines) if re.match(rf"^{key}:", line)]
    if not starts:
        return []
    if len(starts) > 1:
        raise GoalRunError(key, f"duplicate key on line {starts[1] + 2}")
    header = lines[starts[0]][len(key) + 1:].strip()
    if header in ("[]", "null", "~"):
        return []
    if header:
        raise GoalRunError(key, f"must be a block list of episodes (line {starts[0] + 2})")

    episodes: list = []
    current = None  # [id, {field: value}, body lines]

    def label():
        return current[0] if current[0] is not None else f"#{len(episodes) + 1}"

    def close():
        if current is not None:
            if current[0] is None:
                raise GoalRunError(key, f"episode {label()} has no id")
            fields = current[1]
            episodes.append(DefectEpisode(
                current[0], fields.get("fix_batches"), fields.get("bound"), current[2]
            ))

    for i in range(starts[0] + 1, len(lines)):
        line = lines[i]
        lineno = i + 2
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        if not stripped:
            continue
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise GoalRunError(key, f"tab indentation on line {lineno}")
        if indent == 0:
            if stripped.startswith("#"):
                continue
            break
        if indent > 4:
            if current is None:
                raise GoalRunError(key, f"unexpected indentation on line {lineno}")
            current[2].append(line)
            continue
        if stripped.startswith("#"):
            continue
        if indent == 2:
            # A list item opens an episode map; its first key may be any field.
            if not stripped.startswith("- "):
                raise GoalRunError(
                    key, f"each episode must be a '- <field>: <value>' map item (line {lineno})"
                )
            close()
            current = [None, {}, []]
            stripped = stripped[2:].strip()
            line = "    " + stripped
        elif indent != 4 or current is None:
            raise GoalRunError(key, f"unexpected indentation on line {lineno}")
        match = _GOAL_KEY_RE.match(stripped)
        if not match:
            raise GoalRunError(key, f"malformed episode field on line {lineno}")
        field = match.group(1) if match.group(1) is not None else match.group(2)
        if field in current[1] or (field == "id" and current[0] is not None):
            raise GoalRunError(key, f"duplicate {field} for episode {label()} (line {lineno})")
        raw = (match.group(3) or "").strip()
        if field == "id":
            episode_id = _goal_scalar(raw, key, lineno) if raw else None
            if (
                not isinstance(episode_id, str) or not episode_id.strip()
                or episode_id[0] in "|>"
            ):
                raise GoalRunError(key, f"episode id must be a non-empty string (line {lineno})")
            current[0] = episode_id
            continue
        if field in _DEFECT_EPISODE_COUNT_KEYS:
            value = _goal_scalar(raw, key, lineno) if raw else None
            if not _is_count(value):
                raise GoalRunError(
                    key, f"{field} for episode {label()} must be an integer >= 0 (line {lineno})"
                )
        else:
            value = raw
        current[1][field] = value
        current[2].append(line)
    close()
    seen = set()
    for episode in episodes:
        if episode[0] in seen:
            raise GoalRunError(key, f"duplicate episode id {episode[0]}")
        seen.add(episode[0])
    return episodes


def _validate_goal_obligations(value, defect_episodes) -> None:
    base = f"{GOAL_RUN_KEY}.obligations"
    if not isinstance(value, dict):
        raise GoalRunError(base, "must be a map")
    _closed_map(value, base, _GOAL_OBLIGATIONS_KEYS, "obligations")
    for key in _GOAL_OBLIGATION_STR_LISTS:
        items = value[key]
        if not isinstance(items, list) or any(
            not isinstance(i, str) or not i.strip() for i in items
        ):
            raise GoalRunError(f"{base}.{key}", "must be a list of non-empty strings")
    for key in _GOAL_OBLIGATION_STRINGS:
        if not isinstance(value[key], str):
            raise GoalRunError(f"{base}.{key}", "must be a string")
    for key in _GOAL_OBLIGATION_COUNTS:
        if not _is_count(value[key]):
            raise GoalRunError(f"{base}.{key}", "must be an integer >= 0")
    if not isinstance(value["owner_escalation"], bool):
        raise GoalRunError(f"{base}.owner_escalation", "must be true or false")
    # The snapshot links to the canonical defect-episode record by ordinal and id,
    # never keeps a second counter. defect_episode is the 1-based position of the
    # episode in the append-only defect_episodes list (0 = none); defect_episode_ref
    # is that episode's id; fix_batch_count must equal its fix_batches.
    defect_episode = value["defect_episode"]
    ref = value["defect_episode_ref"]
    fix_batch_count = value["fix_batch_count"]
    if not _is_count(defect_episode):
        raise GoalRunError(f"{base}.defect_episode", "must be an integer >= 0 (0 = no episode)")
    if ref is not None and (not isinstance(ref, str) or not ref.strip()):
        raise GoalRunError(f"{base}.defect_episode_ref", "must be an episode id or null")
    if not _is_count(fix_batch_count):
        raise GoalRunError(f"{base}.fix_batch_count", "must be an integer >= 0")
    if defect_episode == 0:
        if ref is not None:
            raise GoalRunError(f"{base}.defect_episode_ref", "must be null when defect_episode is 0")
        if fix_batch_count != 0:
            raise GoalRunError(f"{base}.fix_batch_count", "must be 0 when no defect episode is named")
        return
    if ref is None:
        raise GoalRunError(f"{base}.defect_episode_ref", "must name the episode when defect_episode is non-zero")
    if defect_episode > len(defect_episodes):
        raise GoalRunError(f"{base}.defect_episode", f"{defect_episode} is not a recorded defect episode")
    episode = defect_episodes[defect_episode - 1]
    episode_id, canonical = episode[0], episode[1]
    if ref != episode_id:
        raise GoalRunError(
            f"{base}.defect_episode_ref",
            f"{ref} does not match the episode at ordinal {defect_episode} ({episode_id})",
        )
    if canonical is None:
        raise GoalRunError(
            f"{base}.fix_batch_count", f"episode {episode_id} records no fix_batches"
        )
    if fix_batch_count != canonical:
        raise GoalRunError(
            f"{base}.fix_batch_count", f"must equal the episode's fix_batches ({canonical})"
        )


def _validate_goal_custody(value, recovery) -> None:
    base = f"{GOAL_RUN_KEY}.custody"
    if not isinstance(value, dict):
        raise GoalRunError(base, "must be a map")
    _closed_map(value, base, _GOAL_CUSTODY_KEYS, "custody")
    for key in ("prior_session_id", "current_session_id", "reason"):
        if value[key] is not None and not isinstance(value[key], str):
            raise GoalRunError(f"{base}.{key}", "must be a string or null")
    claim = value["claim"]
    if claim is not None and (not isinstance(claim, str) or claim not in _GOAL_CUSTODY_CLAIMS):
        raise GoalRunError(f"{base}.claim", "must be 'successor', 'takeover' or null")
    outcome = value["outcome"]
    if outcome not in _GOAL_CUSTODY_OUTCOMES:
        raise GoalRunError(f"{base}.outcome", "must be 'accept' or 'invalid'")
    liveness = value["previous_lead_liveness"]
    if liveness is not None and liveness not in _GOAL_CUSTODY_LIVENESS:
        raise GoalRunError(f"{base}.previous_lead_liveness", "must be 'live', 'unknown', 'ended' or null")
    prior = value["prior_session_id"]
    current = value["current_session_id"]
    reason = value["reason"]
    # Custody is accepted only on (i) a same-session resume: both session ids
    # nonempty and equal, no claim; or (ii) a takeover: both nonempty and
    # distinct, an explicit valid claim and previous_lead_liveness ended.
    # custody_unknown and a bare new-session lineage are never accepted
    # transfers; classify_lineage's may_proceed alone is not relied on.
    if outcome == "accept":
        if not _nonempty(prior):
            raise GoalRunError(f"{base}.prior_session_id", "accept needs nonempty prior and current session ids")
        if not _nonempty(current):
            raise GoalRunError(f"{base}.current_session_id", "accept needs nonempty prior and current session ids")
        if prior == current:
            if claim is not None:
                raise GoalRunError(f"{base}.claim", "a same-session resume cannot carry a custody claim")
        else:
            if claim not in _GOAL_CUSTODY_CLAIMS:
                raise GoalRunError(f"{base}.claim", "a takeover needs an explicit custody claim")
            if liveness != "ended":
                raise GoalRunError(
                    f"{base}.previous_lead_liveness", "a takeover needs the previous lead verified ended"
                )
        if _nonempty(reason):
            raise GoalRunError(f"{base}.reason", "must be null or empty when outcome is accept")
        return
    # outcome invalid: a non-accepted state (custody_unknown, a bare new-session
    # lineage, an unverified takeover) is recordable; a lineage classify_lineage
    # itself refuses must carry its reason.
    result = recovery.classify_lineage(prior, current, claim)
    if not result.may_proceed and reason != result.reason:
        raise GoalRunError(f"{base}.reason", "does not match classify_lineage")


def _validate_goal_event_ledger(value) -> None:
    base = f"{GOAL_RUN_KEY}.event_ledger"
    if not isinstance(value, dict):
        raise GoalRunError(base, "must be a map")
    _closed_map(value, base, _GOAL_EVENT_LEDGER_KEYS, "event ledger")
    seen = value["seen"]
    if not isinstance(seen, list) or any(not isinstance(i, str) or not i for i in seen):
        raise GoalRunError(f"{base}.seen", "must be a list of non-empty event identities")
    if len(set(seen)) != len(seen):
        raise GoalRunError(f"{base}.seen", "an event identity must not be counted twice")
    duplicates = value["duplicates"]
    if not isinstance(duplicates, dict):
        raise GoalRunError(f"{base}.duplicates", "must be a map")
    for identity, count in duplicates.items():
        if not isinstance(identity, str) or not identity:
            raise GoalRunError(f"{base}.duplicates", "identity must be a non-empty string")
        if not _is_count(count) or count == 0:
            raise GoalRunError(
                f"{base}.duplicates", f"{identity} duplicate count must be a positive integer"
            )
        if identity not in seen:
            raise GoalRunError(f"{base}.duplicates", f"{identity} is not a counted event")


def _validate_goal_recovery_receipts(value, recovery) -> None:
    base = f"{GOAL_RUN_KEY}.recovery_receipts"
    if not isinstance(value, dict):
        raise GoalRunError(base, "must be a map")
    for receipt_id, record in value.items():
        if not isinstance(receipt_id, str) or not receipt_id:
            raise GoalRunError(base, "receipt id must be a non-empty string")
        check = recovery.validate_sc9_record("recovery-receipt-v1", record)
        if not check.ok:
            raise GoalRunError(f"{base}.{receipt_id}", check.reason)


def _validate_goal_unknown_effects(value) -> None:
    base = f"{GOAL_RUN_KEY}.unknown_effects"
    if not isinstance(value, dict):
        raise GoalRunError(base, "must be a map")
    for effect_id, entry in value.items():
        if not isinstance(effect_id, str) or not effect_id:
            raise GoalRunError(base, "effect id must be a non-empty string")
        if not isinstance(entry, dict):
            raise GoalRunError(f"{base}.{effect_id}", "must be a map")
        for key in entry:
            if key not in _GOAL_UNKNOWN_EFFECT_KEYS:
                raise GoalRunError(f"{base}.{effect_id}.{key}", "unknown effect field")
        for key in _GOAL_UNKNOWN_EFFECT_KEYS:
            if key not in entry:
                raise GoalRunError(f"{base}.{effect_id}.{key}", "missing required field")
        state = entry["state"]
        if state not in _GOAL_UNKNOWN_EFFECT_STATES:
            raise GoalRunError(f"{base}.{effect_id}.state", "must be 'unknown' or 'resolved'")
        blocked = entry["blocked"]
        if not isinstance(blocked, list) or any(not isinstance(b, str) or not b for b in blocked):
            raise GoalRunError(f"{base}.{effect_id}.blocked", "must be a list of non-empty strings")
        evidence = entry["evidence"]
        if evidence is not None and not isinstance(evidence, str):
            raise GoalRunError(f"{base}.{effect_id}.evidence", "must be a string or null")
        if state == "resolved":
            if not evidence or not evidence.strip():
                raise GoalRunError(f"{base}.{effect_id}", "a resolved unknown effect needs evidence")
            if blocked:
                raise GoalRunError(
                    f"{base}.{effect_id}.blocked", "a resolved effect cannot block dependents"
                )


def _validate_goal_recovery_records(block, goal_run, defect_episodes) -> None:
    """Validate the L6 recovery keys. Absent or all-null means a pre-L6 block and
    returns without importing goal_recovery.py."""
    if all(block.get(key) is None for key in _GOAL_RECOVERY_KEYS):
        return
    recovery = _load_goal_recovery_module()
    if block.get("obligations") is not None:
        _validate_goal_obligations(block["obligations"], defect_episodes)
    if block.get("custody") is not None:
        _validate_goal_custody(block["custody"], recovery)
    if block.get("event_ledger") is not None:
        _validate_goal_event_ledger(block["event_ledger"])
    if block.get("recovery_receipts") is not None:
        _validate_goal_recovery_receipts(block["recovery_receipts"], recovery)
    if block.get("unknown_effects") is not None:
        _validate_goal_unknown_effects(block["unknown_effects"])


# --- Goal-run lifecycle-clock counter (Issue #196, lane L7) ------------------
#
# D7.1 keeps two idle timers separate and gives the Dev its own reset count.
# This key holds the Dev's count and nothing else: Foreman owns its
# orchestrator clock values, so the ledger has no field for them. Optional and
# additive, so a pre-L7 block validates unchanged.

_CONTEXT_RESETS_KEYS = ("measured", "count")
_CONTEXT_RESETS_UNKNOWN = "unknown"


def _validate_goal_context_resets(block) -> None:
    """Validate the optional L7 context-reset count. Absent or null is valid, so
    a pre-L7 ledger validates unchanged. The shape is closed:
    ``{measured: bool, count: int >= 0 | "unknown"}``; ``measured`` false admits
    only ``unknown``, so an unmeasured count is never 0."""
    base = f"{GOAL_RUN_KEY}.context_resets"
    record = block.get("context_resets")
    if record is None:
        return
    if not isinstance(record, dict):
        raise GoalRunError(base, "must be a map")
    for key in record:
        if key not in _CONTEXT_RESETS_KEYS:
            raise GoalRunError(f"{base}.{key}", "unknown context_resets field")
    for key in _CONTEXT_RESETS_KEYS:
        if key not in record:
            raise GoalRunError(f"{base}.{key}", "missing required field")
    measured = record["measured"]
    if not isinstance(measured, bool):
        raise GoalRunError(f"{base}.measured", "must be true or false")
    count = record["count"]
    # Element types are checked before any comparison, so a malformed value
    # fails as a named error instead of raising out of the validator.
    if measured:
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise GoalRunError(
                f"{base}.count", "measured context resets must be an integer >= 0"
            )
        return
    if count == _CONTEXT_RESETS_UNKNOWN:
        return
    if isinstance(count, bool):
        raise GoalRunError(
            f"{base}.count", "unmeasured context resets must be unknown, never a number"
        )
    if isinstance(count, (int, float)):
        if count == 0:
            raise GoalRunError(
                f"{base}.count", "unmeasured context resets must be unknown, never 0"
            )
        raise GoalRunError(
            f"{base}.count", "unmeasured context resets must be unknown, never a number"
        )
    raise GoalRunError(f"{base}.count", "unmeasured context resets must be unknown")


def validate_goal_run(block, defect_episodes=None) -> None:
    """Validate a goal-run block (a plain dict). Raises ``GoalRunError``.

    The assignment fields are checked by goal_run.normalize_entry and must equal
    the normalized ``Assignment.to_dict()``; the policy by goal_run.apply_policy;
    the counters against goal_run.RunCounters' fields plus the two ledger-only
    counters ``usage_measured`` and ``gv_retries_used``; the optional grant and
    gate records against goal_authority.py (Issue #194, lane L4); and the optional
    recovery records against goal_recovery.py (Issue #196, lane L6), with the
    obligations snapshot cross-checked against the canonical ``defect_episodes``."""
    if not isinstance(block, dict):
        raise GoalRunError(GOAL_RUN_KEY, "must be a map")
    for key in block:
        if key not in _GOAL_ASSIGNMENT_KEYS and key not in _GOAL_RUN_STATE_KEYS:
            raise GoalRunError(f"{GOAL_RUN_KEY}.{key}", "unknown goal_run field")
    goal_run = _load_goal_run_module()

    entry = {key: block[key] for key in _GOAL_ASSIGNMENT_KEYS if key in block}
    normalized = goal_run.normalize_entry(entry)
    if normalized.outcome != "accept":
        field = normalized.detail.get("field") or _GOAL_REASON_FIELDS.get(normalized.reason)
        path = f"{GOAL_RUN_KEY}.{field}" if field else GOAL_RUN_KEY
        raise GoalRunError(path, normalized.reason)
    for key, expected in normalized.value.to_dict().items():
        if key not in block:
            raise GoalRunError(f"{GOAL_RUN_KEY}.{key}", "missing required field")
        if block[key] != expected:
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
    _validate_goal_context_resets(block)
    _validate_goal_authority_records(block, goal_run, applied.value)
    _validate_goal_recovery_records(block, goal_run, defect_episodes or [])


def validate_goal_run_text(text: str, data: dict) -> None:
    """Entry point from main(): a no-op unless the frontmatter has a top-level
    ``goal_run:`` header that is not explicitly null, so ledgers without goal
    fields are untouched. The decision reads the raw header lines, not the flat
    reader's ``data``: that reader drops ``goal_run: |`` (a literal block) and
    keeps only the last of repeated keys, so neither may decide "null"."""
    end = text.find("\n---\n")
    frontmatter = text[4:end] if end != -1 else ""
    headers = re.findall(rf"^{GOAL_RUN_KEY}:(.*)$", frontmatter, re.M)
    if not headers:
        return
    if len(headers) == 1 and headers[0].strip() in ("null", "~"):
        return
    try:
        block = parse_goal_run_block(text)
        # The strict canonical-episode read serves only the obligations
        # cross-check; without a snapshot the pre-L6 path is unchanged.
        episodes = (
            parse_defect_episodes(text)
            if isinstance(block, dict) and block.get("obligations") is not None
            else None
        )
        validate_goal_run(block, episodes)
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
