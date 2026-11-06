#!/usr/bin/env python3
"""Goal completion verifier (GV): the single completion evaluator for a goal run.

GV reads a Dev ledger (``.agent/dev-state.md``) read-only, reads fresh
repository facts through one injectable runner, and prints one
``completion-result-v1`` record (SDP D4.5). It writes nothing: no ledger,
tracker, branch or repository write, and no merge, close or reopen. The Dev lead
records the result as sole ledger writer.

Usage::

    verify_goal_completion.py --ledger .agent/dev-state.md [--purpose final]
        [--owner-account LOGIN] [--marker TEXT] [--approved-revision DIGEST]
        [--invoker-role ROLE] [--invoker-id ID] [--invoker-harness HARNESS]
        [--consumer-context CONTEXT] [--hook-cap-exhausted]
        [--supersedes RESULT_ID ...] [--result-id ID] [--ledger-ref REF]

Exit codes (D4.3 item 3). Only ``0`` means success:

    0  verified
    1  not_complete (final) or not_ready (readiness)
    2  usage or internal error, or a goal rejected at arming (no result)
    3  inconclusive (either purpose)
    4  evidence_ready (readiness; never success)

Outcome classes. Each reason code carries one class:

* ``not_complete``: a demonstrated unmet condition. Examples: an Issue not
  closed, a PR not merged, the wrong merge SHA, base or repository, a merge not
  reachable from the destination, a withdrawn integration, a failed post-merge
  gate, ``criteria_verdict: unmet``, an Issue with no PR record, proof of a kind
  D4.4 never accepts, or a human criterion awaiting owner acceptance.
* ``inconclusive``: missing, unreadable, stale or ambiguous evidence. Examples:
  a read failing after three tries, an API error or rate limit, a missing PR
  record in a multi-PR mapping, an absent or pending post-merge record, a stale
  criteria or source revision, a suspected unrecorded revert, a mismatched
  marker, or a missing owner account for a human criterion.
* ``advisory``: recorded, never blocking. Examples: a revert scan that could
  not run, hook-cap exhaustion, or an open Issue under ``purpose: readiness``.

A ``not_complete`` reason outranks an ``inconclusive`` one. Neither the lead's
marker nor its summary is ever read as proof, and no prior result is reused:
every call re-reads the repository.

Test proof binding (D4.4). The proving run of a ``test`` criterion is the
post-merge ``run`` when the action is ``full_required_gate_rerun``. When the
action is ``applies_verbatim``, it is the ``ci_runs`` entry whose
``tested_subject.head`` matches the PR head. Its definition and environment are
compared with the PR ``checks`` entry whose ``id`` equals the run's ``job``.

Ledger reading. The goal block is read by ``dev_state.parse_goal_run_block``
and armed through ``goal_run.arm``. The evidence blocks (``pull_requests``,
``parent_acceptance``, ``workers``) are lists of maps, which that reader does
not accept, so GV carries a second block reader here. It handles map items in
lists and ``@`` in keys, and delegates every scalar to
``dev_state._goal_scalar``. It is a candidate to fold into dev_state.py in
L195-2.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import dev_state  # noqa: E402  (sibling payload module)
import goal_run  # noqa: E402  (sibling payload module)

RESULT_PROFILE = "completion-result-v1"
EVIDENCE_PROFILE = "completion-evidence-v1"
ARMING_REJECTION_KIND = "gv-arming-rejection"
ERROR_KIND = "gv-error"
DEFAULT_LEDGER_REF = ".agent/dev-state.md"

PURPOSE_FINAL = "final"
PURPOSE_READINESS = "readiness"
VOCABULARY = {
    PURPOSE_FINAL: ("verified", "not_complete", "inconclusive"),
    PURPOSE_READINESS: ("evidence_ready", "not_ready", "inconclusive"),
}

EXIT_VERIFIED = 0
EXIT_NOT_COMPLETE = 1
EXIT_ERROR = 2
EXIT_INCONCLUSIVE = 3
EXIT_EVIDENCE_READY = 4
EXIT_CODES = {
    "verified": EXIT_VERIFIED,
    "not_complete": EXIT_NOT_COMPLETE,
    "not_ready": EXIT_NOT_COMPLETE,
    "inconclusive": EXIT_INCONCLUSIVE,
    "evidence_ready": EXIT_EVIDENCE_READY,
}

# D3 item 4: three tries with a short backoff between them.
READ_TRIES = 3
READ_BACKOFF_SECONDS = (1.0, 2.0)

# The only external command GV ever builds: a GitHub REST read.
GH_READ_PREFIX = ("gh", "api", "--method", "GET")
_GH_PAGINATE = "--paginate"

NOT_COMPLETE = "not_complete"
INCONCLUSIVE = "inconclusive"
ADVISORY = "advisory"

EVALUATOR_TYPES = ("test", "demonstration", "independent_reviewer", "human")
_ARMING_REJECTIONS = {
    "non_pr_goal": "non_pr_work",
    "empty_issue_set": "empty_goal_set",
    "cross_repo_issue": "cross_repo_goal",
}
_SOURCE_MISMATCHES = ("approval_revision_mismatch", "source_revision_mismatch")
_FAILED_GATE_RESULTS = ("rerun_fail", "fail", "failed", "failure")
_FAILED_CONCLUSIONS = ("failure", "cancelled", "skipped", "timed_out", "neutral",
                       "action_required", "stale", "startup_failure")
_CI_ENVIRONMENTS = ("ci",)

_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_ISSUE_RE = re.compile(r"^([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#([0-9]+)$")
_HEX_RE = re.compile(r"^[0-9a-f]{7,40}$")
_DIGEST_RE = re.compile(r"^sha256:([0-9a-f]{4,64})$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
_ENDPOINT_RE = re.compile(r"^repos/[A-Za-z0-9_.\-/?=&:.@\[\]%+]+$")
_ACCEPT_RE = re.compile(r"^/accept\s+(\S+)\s*$")
_REVERT_RE = re.compile(r"This reverts commit ([0-9a-fA-F]{7,40})")
_STRICT_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|\+00:00)$")
_BLOCK_KEY_RE = re.compile(r'^(?:"([^"]+)"|([A-Za-z0-9_][A-Za-z0-9_.\-/#@]*)):(?:\s+(.*))?$')

# The assignment-v1 keys, exactly the fields of goal_run.Assignment.
_ASSIGNMENT_KEYS = tuple(f.name for f in fields(goal_run.Assignment))

_PR_REQUIRED = ("repository", "issue", "criteria_ref", "criteria_ids", "policy_ref",
                "base_oid", "target_branch", "headRefOid", "checks", "criteria",
                "assurance", "integrated")
_PARENT_REQUIRED = ("parent", "mode", "criteria_ref", "contributions", "criteria",
                    "outcome", "observed_at")
_PR_COMPLETION_FIELDS = ("goal_completion", "goal_completion_ref", "completion_result",
                         "goal_complete", "verified")


# --- Runner -----------------------------------------------------------------


class ReadFailed(Exception):
    """A fresh read that did not complete within ``READ_TRIES`` tries."""

    def __init__(self, read_id: str, cause: str) -> None:
        super().__init__(f"{read_id}: {cause}")
        self.read_id = read_id
        self.cause = cause


def build_gh_read(endpoint: str, paginate: bool = False) -> list:
    """Return the argv for one GitHub REST read of ``endpoint``."""
    if not isinstance(endpoint, str) or not _ENDPOINT_RE.match(endpoint) or ".." in endpoint.replace("...", ""):
        raise ValueError(f"unsafe endpoint: {endpoint!r}")
    argv = list(GH_READ_PREFIX)
    if paginate:
        argv.append(_GH_PAGINATE)
    argv.append(endpoint)
    return argv


def is_read_argv(argv) -> bool:
    """True only for the pinned read shape: the GET prefix, an optional
    pagination flag, then one endpoint."""
    if not isinstance(argv, (list, tuple)) or tuple(argv[:4]) != GH_READ_PREFIX:
        return False
    rest = list(argv[4:])
    if rest and rest[0] == _GH_PAGINATE:
        rest = rest[1:]
    return len(rest) == 1 and isinstance(rest[0], str) and bool(_ENDPOINT_RE.match(rest[0]))


def subprocess_runner(argv):
    """The real runner. Refuses anything but the pinned read shape."""
    if not is_read_argv(argv):
        raise ValueError(f"refused non-read argv: {argv!r}")
    proc = subprocess.run(list(argv), capture_output=True, text=True, check=False, timeout=120)
    return proc.returncode, proc.stdout, proc.stderr


def _classify_failure(stderr: str) -> str:
    text = (stderr or "").lower()
    if "rate limit" in text or "429" in text:
        return "rate_limited"
    if "404" in text or "not found" in text:
        return "not_found"
    return "api_error"


def _parse_json_stream(text: str):
    """Parse ``gh api`` output; ``--paginate`` concatenates one array per page."""
    decoder = json.JSONDecoder()
    values = []
    index = 0
    text = text or ""
    while True:
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        value, index = decoder.raw_decode(text, index)
        values.append(value)
    if not values:
        raise ValueError("empty output")
    if len(values) == 1:
        return values[0]
    if all(isinstance(v, list) for v in values):
        return [item for page in values for item in page]
    raise ValueError("unexpected multi-document output")


@dataclass
class _Reader:
    runner: object
    sleep: object
    unread: list = field(default_factory=list)
    cache: dict = field(default_factory=dict)

    def read(self, read_id: str, endpoint: str, paginate: bool = False, blocking: bool = True):
        key = (endpoint, paginate)
        if key in self.cache:
            return self.cache[key]
        argv = build_gh_read(endpoint, paginate)
        cause = "api_error"
        for attempt in range(READ_TRIES):
            try:
                rc, out, err = self.runner(argv)
            except Exception as exc:  # timeout, missing gh, OS error
                rc, out, err = -1, "", f"{type(exc).__name__}: {exc}"
            if rc == 0:
                try:
                    value = _parse_json_stream(out)
                except ValueError:
                    cause = "unparseable_output"
                else:
                    self.cache[key] = value
                    return value
            else:
                cause = _classify_failure(err)
            if attempt + 1 < READ_TRIES:
                self.sleep(READ_BACKOFF_SECONDS[attempt])
        self.unread.append({"read": read_id, "endpoint": endpoint, "cause": cause,
                            "tries": READ_TRIES, "blocking": blocking})
        raise ReadFailed(read_id, cause)


# --- Ledger block reader --------------------------------------------------------


class LedgerError(Exception):
    """A ledger block outside the supported YAML subset."""

    def __init__(self, field_name: str, message: str) -> None:
        super().__init__(f"{field_name}: {message}")
        self.field = field_name
        self.message = message


_ABSENT = object()


def _frontmatter_lines(text):
    if not isinstance(text, str) or not text.startswith("---\n"):
        raise LedgerError("frontmatter", "missing opening delimiter")
    end = text.find("\n---\n")
    if end == -1:
        raise LedgerError("frontmatter", "missing closing delimiter")
    return text[4:end].split("\n")


def _scalar(raw: str, path: str, lineno: int):
    if raw in ("|", ">") or raw.startswith(("|-", "|+", ">-", ">+")):
        raise LedgerError(path, f"block scalars are not supported (line {lineno})")
    try:
        return dev_state._goal_scalar(raw, path, lineno)
    except dev_state.GoalRunError as exc:
        raise LedgerError(exc.field, exc.message) from exc


def _append_token(tokens: list, indent: int, content: str, lineno: int, path: str) -> None:
    if content == "-" or content.startswith("- "):
        rest = content[1:]
        inner = rest.strip()
        if inner.startswith("- ") or inner == "-":
            raise LedgerError(path, f"nested list items are not supported (line {lineno})")
        if inner and inner[0] not in "\"'" and _BLOCK_KEY_RE.match(inner):
            offset = 1 + (len(rest) - len(rest.lstrip(" ")))
            tokens.append((indent, "-", lineno))
            tokens.append((indent + offset, inner, lineno))
            return
    tokens.append((indent, content, lineno))


def _parse_node(tokens: list, index: int, indent: int, path: str):
    first = tokens[index][1]
    if first == "-" or first.startswith("- "):
        items = []
        while index < len(tokens) and tokens[index][0] == indent:
            _, content, lineno = tokens[index]
            if not (content == "-" or content.startswith("- ")):
                raise LedgerError(path, f"mixed list and map on line {lineno}")
            raw = content[1:].strip()
            index += 1
            if raw:
                items.append(_scalar(raw, path, lineno))
                continue
            if index >= len(tokens) or tokens[index][0] <= indent:
                raise LedgerError(path, f"empty list item on line {lineno}")
            child, index = _parse_node(tokens, index, tokens[index][0], f"{path}[{len(items)}]")
            items.append(child)
        return items, index

    mapping = {}
    while index < len(tokens) and tokens[index][0] == indent:
        _, content, lineno = tokens[index]
        if content == "-" or content.startswith("- "):
            raise LedgerError(path, f"mixed list and map on line {lineno}")
        match = _BLOCK_KEY_RE.match(content)
        if not match:
            raise LedgerError(path, f"malformed line {lineno}")
        key = match.group(1) if match.group(1) is not None else match.group(2)
        child_path = f"{path}.{key}"
        if key in mapping:
            raise LedgerError(child_path, f"duplicate key on line {lineno}")
        raw = (match.group(3) or "").strip()
        index += 1
        if raw:
            mapping[key] = _scalar(raw, child_path, lineno)
            continue
        if index >= len(tokens) or tokens[index][0] <= indent:
            raise LedgerError(child_path, f"missing value on line {lineno}")
        mapping[key], index = _parse_node(tokens, index, tokens[index][0], child_path)
    if index < len(tokens) and tokens[index][0] > indent:
        raise LedgerError(path, f"unexpected indentation on line {tokens[index][2]}")
    return mapping, index


def read_block(text: str, key: str):
    """Read one top-level frontmatter key. Returns ``_ABSENT`` when missing."""
    lines = _frontmatter_lines(text)
    starts = [i for i, line in enumerate(lines) if re.match(rf"^{re.escape(key)}:(\s|$)", line)]
    if not starts:
        return _ABSENT
    if len(starts) > 1:
        raise LedgerError(key, f"duplicate key on line {starts[1] + 2}")
    start = starts[0]
    rest = lines[start][len(key) + 1:].strip()
    if rest:
        return _scalar(rest, key, start + 2)
    tokens = []
    for i in range(start + 1, len(lines)):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise LedgerError(key, f"tab indentation on line {i + 2}")
        if not line.startswith(" "):
            break
        _append_token(tokens, len(line) - len(line.lstrip(" ")), stripped, i + 2, key)
    if not tokens:
        raise LedgerError(key, "block is empty")
    value, index = _parse_node(tokens, 0, tokens[0][0], key)
    if index != len(tokens):
        raise LedgerError(key, f"unexpected indentation on line {tokens[index][2]}")
    return value


def read_goal_block(text: str) -> dict:
    """The armed goal block, read by dev_state's own goal-run reader."""
    key = dev_state.GOAL_RUN_KEY
    lines = _frontmatter_lines(text)
    heads = [line for line in lines if re.match(rf"^{key}:(\s|$)", line)]
    if not heads or heads[0][len(key) + 1:].strip() in ("null", "~"):
        raise LedgerError(key, "no goal run is armed in this ledger")
    try:
        return dev_state.parse_goal_run_block(text)
    except dev_state.GoalRunError as exc:
        raise LedgerError(exc.field, exc.message) from exc


# --- Small helpers -------------------------------------------------------------


def canonical_digest(value) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return "sha256:" + hashlib.sha256(data.encode("utf-8")).hexdigest()


def _parse_utc(value):
    if not isinstance(value, str) or not _STRICT_UTC_RE.match(value.strip()):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(value):
    """A recorded git object id, lower-cased, or None when it is not one."""
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    return text if _HEX_RE.match(text) else None


def _sha_eq(left, right) -> bool:
    a, b = _sha(left), _sha(right)
    if a is None or b is None:
        return False
    return a.startswith(b) or b.startswith(a)


def _digest_hex(value):
    match = _DIGEST_RE.match(value) if isinstance(value, str) else None
    return match.group(1) if match else None


def _split_issue(value):
    match = _ISSUE_RE.match(value) if isinstance(value, str) else None
    return (match.group(1), int(match.group(2))) if match else None


def _pr_identity(value, default_repo):
    """``23`` or ``"OWNER/REPO#23"`` -> (repo, number); otherwise None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return default_repo, value
    if isinstance(value, str) and value.isdigit():
        return default_repo, int(value)
    return _split_issue(value)


def _criterion_parts(criterion_id):
    if not isinstance(criterion_id, str) or criterion_id.count("@") != 1:
        return None
    base, rev = criterion_id.split("@")
    if not base or not re.match(r"^[0-9a-f]{4,64}$", rev):
        return None
    return base, rev


def _evaluator(item):
    evaluator = item.get("evaluator") if isinstance(item, dict) else None
    if isinstance(evaluator, dict):
        return evaluator.get("type"), evaluator.get("id")
    if isinstance(evaluator, str):
        return evaluator, None
    return None, None


def _find(items, key, value):
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and item.get(key) == value:
            return item
    return None


def _login(value):
    if isinstance(value, dict):
        value = value.get("login")
    return value.lower() if isinstance(value, str) and value else None


# --- Evidence record checker (completion-evidence-v1) ----------------------------


def check_evidence_record(record):
    """Check one evidence record. Returns (``accept``|``reject``|``unknown``, reasons)."""
    if not isinstance(record, dict):
        return "reject", ["malformed_record"]
    if record.get("profile_version") != EVIDENCE_PROFILE:
        return "unknown", ["unknown_profile_version"]
    reasons = []
    scope = record.get("scope")
    if scope == "pr_assurance":
        reasons += [f"missing_field:{name}" for name in _PR_REQUIRED if record.get(name) in (None, "")
                    and not (name == "integrated" and isinstance(record.get(name), dict))]
        repository = record.get("repository")
        if repository is not None and (not isinstance(repository, str) or not _REPO_RE.match(repository)):
            reasons.append("malformed_repository")
        issue = _split_issue(record.get("issue"))
        if record.get("issue") is not None and (issue is None or issue[0] != repository):
            reasons.append("issue_not_qualified_in_repository")
        if record.get("criteria_ref") is not None and _digest_hex(record.get("criteria_ref")) is None:
            reasons.append("malformed_criteria_ref")
        assurance = record.get("assurance")
        if assurance is not None:
            if not isinstance(assurance, dict) or "current" not in assurance:
                reasons.append("malformed_assurance")
            elif assurance.get("current") is False and not assurance.get("stale_reason"):
                reasons.append("noncurrent_assurance_without_stale_reason")
        integrated = record.get("integrated")
        if integrated is not None and (not isinstance(integrated, dict) or "current" not in integrated
                                       or not isinstance(integrated.get("history", []), list)):
            reasons.append("malformed_integrated")
        if any(name in record for name in _PR_COMPLETION_FIELDS):
            reasons.append("carries_goal_completion")
    elif scope == "parent_acceptance":
        reasons += [f"missing_field:{name}" for name in _PARENT_REQUIRED
                    if record.get(name) in (None, "") and name != "outcome"]
        if "outcome" not in record:
            reasons.append("missing_field:outcome")
        if record.get("mode") not in (None, "standalone"):
            reasons.append("unsupported_mode")
        ref = record.get("goal_completion_ref")
        if ref is not None and not isinstance(ref, str):
            reasons.append("carries_result")
        if record.get("contributions") is not None and not isinstance(record.get("contributions"), list):
            reasons.append("malformed_contributions")
    else:
        reasons.append("unknown_scope")
    return ("reject", reasons) if reasons else ("accept", [])


# --- Result reader (D4.5 reader rules, l.441-l.448) ------------------------------


def read_result(record):
    """Read a completion-result-v1 record.

    Returns (``accept``|``reject``|``unusable``|``unknown``, reasons). An exit
    code never substitutes for this reading (rule 5)."""
    if not isinstance(record, dict):
        return "unusable", ["malformed_record"]
    if record.get("profile_version") != RESULT_PROFILE:
        return "unknown", ["unknown_profile_version"]
    purpose = record.get("purpose")
    if purpose not in VOCABULARY:
        return "unusable", ["unknown_purpose"]
    outcome = record.get("outcome")
    if outcome not in VOCABULARY[purpose]:
        return "unusable", ["outcome_outside_vocabulary"]

    goal = record.get("goal")
    if not isinstance(goal, dict):
        return "unusable", ["missing_field:goal"]
    repository = goal.get("repository")
    issues = goal.get("fixed_issues")
    if not isinstance(issues, list) or not issues:
        return "reject", ["empty_goal_set"]
    for issue in issues:
        parts = _split_issue(issue)
        if parts is None:
            return "reject", ["bare_ambiguous_issue_id"]
        if parts[0] != repository:
            return "reject", ["cross_repo_goal"]

    reasons = []
    reason_names = {r.get("code") for r in record.get("reason_codes") or [] if isinstance(r, dict)}
    for name in ("result_id", "run_id", "plan_ref", "evidence_profile", "consumed_inputs",
                 "repository_facts", "criteria", "producer"):
        if name == "criteria" and record.get(name) == [] and outcome not in ("verified", "evidence_ready") \
                and "criteria_unavailable" in reason_names:
            continue  # a negative result that could not locate the criteria says so
        if record.get(name) in (None, "", [], {}):
            reasons.append(f"missing_field:{name}")
    if not goal.get("frozen_at"):
        reasons.append("missing_field:goal.frozen_at")
    plan_ref = record.get("plan_ref")
    if isinstance(plan_ref, dict):
        checked = goal_run._validate_plan_ref(plan_ref)
        if not checked.ok:
            reasons.append(f"invalid_plan_ref:{checked.reason}:{checked.detail.get('field', '')}")
    if record.get("evidence_profile") not in (None, EVIDENCE_PROFILE):
        reasons.append("unknown_evidence_profile")
    for item in record.get("consumed_inputs") or []:
        if not isinstance(item, dict) or not item.get("reference") or not item.get("digest") \
                or not (item.get("revision") or item.get("recorded_at")):
            reasons.append("unidentifiable_consumed_input")
            break
    facts = record.get("repository_facts")
    if isinstance(facts, dict) and not _parse_utc(facts.get("observed_at")):
        reasons.append("repository_facts_without_observed_at")
    producer = record.get("producer")
    if isinstance(producer, dict):
        if producer.get("recorded_by") != "lead":
            reasons.append("not_recorded_by_lead")
        if not producer.get("helper_revision"):
            reasons.append("missing_field:producer.helper_revision")
    criteria = record.get("criteria") if isinstance(record.get("criteria"), list) else []
    for item in criteria:
        if not isinstance(item, dict) or not item.get("id") or not item.get("evaluator") \
                or item.get("state") not in ("met", "unmet", "inconclusive"):
            reasons.append("malformed_criterion_line")
            break
        if item.get("state") == "met" and not item.get("accepted_proof"):
            reasons.append(f"met_without_proof:{item.get('id')}")
    blocking = [r for r in record.get("reason_codes") or []
                if not (isinstance(r, dict) and r.get("blocking") is False)]
    if outcome in ("verified", "evidence_ready"):
        if any(isinstance(i, dict) and i.get("state") != "met" for i in criteria):
            reasons.append("success_with_unmet_criterion")
        if blocking:
            reasons.append("success_with_blocking_reason")
    elif not blocking and not record.get("unread_inputs"):
        reasons.append("negative_outcome_without_reason")
    return ("unusable", reasons) if reasons else ("accept", [])


# --- Evaluation -----------------------------------------------------------------


@dataclass
class Verification:
    """What GV returns: ``kind`` is ``result``, ``arming_rejection`` or ``error``."""

    kind: str
    record: dict
    exit_code: int

    @property
    def outcome(self):
        return self.record.get("outcome") if self.kind == "result" else None


@dataclass
class _Reason:
    code: str
    cls: str
    issues: tuple = ()
    prs: tuple = ()
    criteria: tuple = ()
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"code": self.code, "class": self.cls, "blocking": self.cls != ADVISORY,
                "issues": list(self.issues), "prs": list(self.prs),
                "criteria": list(self.criteria), "detail": self.detail}


def _error(code: str, message: str, **detail) -> Verification:
    return Verification("error", {"kind": ERROR_KIND, "error": code, "message": message,
                                  "detail": detail}, EXIT_ERROR)


def _helper_revision() -> str:
    try:
        return "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError:
        return "unknown"


def _skill_revision():
    try:
        text = (_SCRIPTS_DIR.parent / "SKILL.md").read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"^version:\s*(\S+)\s*$", text, re.MULTILINE)
    return match.group(1) if match else None


class _Evaluation:
    def __init__(self, reader, purpose, owner_account, assignment, goal, blocks):
        self.reader = reader
        self.purpose = purpose
        self.owner = owner_account.lower() if isinstance(owner_account, str) and owner_account else None
        self.assignment = assignment
        self.goal = goal
        self.blocks = blocks
        self.repo = assignment.repo
        self.issues = list(assignment.fixed_issues)
        self.reasons = []
        self.inputs = []
        self.facts = {"pull_requests": [], "closed_issues": [], "integrated_acceptance": None}
        self.lines = []
        self.prs = {}
        self.parent = None
        self.parent_record = None
        self.records = {}
        self.ref = DEFAULT_LEDGER_REF
        self.cref = None

    def add(self, code, cls, *, issues=(), prs=(), criteria=(), **detail):
        self.reasons.append(_Reason(code, cls, tuple(issues), tuple(prs), tuple(criteria), detail))

    def read(self, read_id, endpoint, *, issues=(), prs=(), criteria=(), paginate=False):
        try:
            return self.reader.read(read_id, endpoint, paginate=paginate)
        except ReadFailed as exc:
            self.add("read_failed", INCONCLUSIVE, issues=issues, prs=prs, criteria=criteria,
                     read=exc.read_id, cause=exc.cause)
            return None

    # Evidence mapping --------------------------------------------------------

    def map_evidence(self):
        pull_requests = self.blocks.get("pull_requests")
        parents = self.blocks.get("parent_acceptance")
        records = {}
        by_issue = {issue: [] for issue in self.issues}
        for item in pull_requests or []:
            if not isinstance(item, dict) or "profile_version" not in item:
                continue
            if item.get("issue") not in by_issue:
                continue
            identity = _pr_identity(item.get("number"), item.get("repository"))
            if item.get("profile_version") != EVIDENCE_PROFILE or item.get("scope") != "pr_assurance":
                self.add("unknown_evidence_profile", INCONCLUSIVE, issues=[item.get("issue")],
                         profile_version=item.get("profile_version"), scope=item.get("scope"))
                continue
            if identity is None or identity[0] is None:
                self.add("pr_identity_missing", INCONCLUSIVE, issues=[item.get("issue")])
                continue
            prq = f"{identity[0]}#{identity[1]}"
            verdict, why = check_evidence_record(item)
            if verdict != "accept":
                self.add("evidence_record_invalid", INCONCLUSIVE, issues=[item.get("issue")],
                         prs=[prq], reasons=why)
                continue
            if prq in records:
                self.add("duplicate_pr_record", INCONCLUSIVE, prs=[prq])
                continue
            records[prq] = item
            by_issue[item["issue"]].append(prq)
            self.inputs.append({
                "reference": f"{self.ref}#pull_requests/{prq}",
                "revision": item.get("headRefOid"),
                "recorded_at": (item.get("assurance") or {}).get("observed_at"),
                "digest": canonical_digest(item),
                "supplies": "pr_assurance: post-merge gate result, criteria verdict, "
                            "per-criterion evidence and integration",
            })
        self.records = records

        parent_refs = {r.get("parent_ref") for r in records.values() if r.get("parent_ref") is not None}
        if len(parent_refs) > 1:
            self.add("ambiguous_parent", INCONCLUSIVE, prs=sorted(records), parents=sorted(parent_refs))
        if len(parent_refs) == 1:
            self.parent = next(iter(parent_refs))
        needs_parent = len(self.issues) > 1 or self.parent is not None \
            or any(len(v) > 1 for v in by_issue.values())
        candidate = self.parent or (self.issues[0] if len(self.issues) == 1 else None)
        matches = [p for p in parents or [] if isinstance(p, dict)
                   and p.get("scope") == "parent_acceptance" and p.get("parent") == candidate]
        if len(matches) > 1:
            self.add("ambiguous_parent_acceptance", INCONCLUSIVE, issues=[candidate])
        elif matches:
            verdict, why = check_evidence_record(matches[0])
            if verdict != "accept":
                self.add("evidence_record_invalid", INCONCLUSIVE, issues=[candidate],
                         record="parent_acceptance", reasons=why)
            else:
                self.parent_record = matches[0]
                self.parent = candidate
                self.inputs.append({
                    "reference": f"{self.ref}#parent_acceptance/{candidate}",
                    "revision": matches[0].get("criteria_ref"),
                    "recorded_at": matches[0].get("observed_at"),
                    "digest": canonical_digest(matches[0]),
                    "supplies": "integrated (parent) acceptance record",
                })
        elif needs_parent:
            self.add("missing_parent_acceptance", INCONCLUSIVE, issues=[candidate] if candidate else self.issues)

        contributed = set()
        if self.parent_record is not None:
            self.check_parent_outcome()
            for item in self.parent_record.get("contributions") or []:
                if not isinstance(item, dict):
                    self.add("malformed_contribution", INCONCLUSIVE, issues=[self.parent])
                    continue
                identity = _pr_identity(item.get("pr"), self.repo)
                if identity is None:
                    self.add("malformed_contribution", INCONCLUSIVE, issues=[self.parent])
                    continue
                prq = f"{identity[0]}#{identity[1]}"
                contributed.add(prq)
                issue = item.get("issue")
                if identity[0] != self.repo:
                    self.add("wrong_repository", NOT_COMPLETE, prs=[prq], issues=[issue],
                             expected=self.repo, found=identity[0])
                elif issue not in by_issue:
                    self.add("contribution_outside_goal", INCONCLUSIVE, prs=[prq], issues=[issue])
                elif prq not in records:
                    self.add("missing_pr_record", INCONCLUSIVE, prs=[prq], issues=[issue])
                elif records[prq].get("issue") != issue:
                    self.add("mapping_mismatch", INCONCLUSIVE, prs=[prq], issues=[issue])
            for prq in sorted(set(records) - contributed):
                self.add("unmapped_pr", INCONCLUSIVE, prs=[prq], issues=[records[prq].get("issue")])
        for issue, prs in by_issue.items():
            if not prs and not any(
                    isinstance(c, dict) and c.get("issue") == issue
                    for c in (self.parent_record or {}).get("contributions") or []):
                self.add("issue_without_pr", NOT_COMPLETE, issues=[issue])
        if self.parent_record is not None:
            self.facts["integrated_acceptance"] = {
                "parent": self.parent, "record": "parent_acceptance",
                "revision": self.parent_record.get("criteria_ref"),
                "outcome": self.parent_record.get("outcome"),
            }

    def check_parent_outcome(self):
        outcome = self.parent_record.get("outcome")
        if outcome in ("pass", "complete"):
            return
        cls = NOT_COMPLETE if outcome in ("fail", "not_complete") else INCONCLUSIVE
        self.add("parent_acceptance_not_final", cls, issues=[self.parent], outcome=outcome)

    # Fresh facts ------------------------------------------------------------

    def check_issues(self):
        for issue in self.issues:
            repo, number = _split_issue(issue)
            data = self.read(f"issue:{issue}", f"repos/{repo}/issues/{number}", issues=[issue])
            if data is None:
                self.facts["closed_issues"].append({"issue": issue, "state": None})
                continue
            state = data.get("state") if isinstance(data, dict) else None
            self.facts["closed_issues"].append({"issue": issue, "state": state})
            if isinstance(data, dict) and data.get("pull_request"):
                self.add("not_an_issue", INCONCLUSIVE, issues=[issue])
            elif state != "closed":
                if self.purpose == PURPOSE_READINESS:
                    self.add("issue_open", ADVISORY, issues=[issue], state=state)
                else:
                    self.add("issue_not_closed", NOT_COMPLETE, issues=[issue], state=state)

    def check_prs(self):
        for prq, record in sorted(self.records.items()):
            self.prs[prq] = self.check_pr(prq, record)

    def check_pr(self, prq, rec):
        issue = rec.get("issue")
        tag = {"issues": [issue], "prs": [prq]}
        repo, number = _split_issue(prq)
        ctx = {"record": rec, "prq": prq, "number": number, "usable": False, "merge": None,
               "head": None, "pm": None, "tree_equivalent": None, "verbatim_run": None}
        fact = {"pr": prq, "state": None, "merge_sha": None, "destination_branch": None,
                "reachable_from_destination": None}
        self.facts["pull_requests"].append(fact)
        if rec.get("repository") != self.repo or repo != self.repo:
            self.add("wrong_repository", NOT_COMPLETE, expected=self.repo, found=rec.get("repository"), **tag)
            return ctx
        branch = rec.get("target_branch")
        if not isinstance(branch, str) or not _BRANCH_RE.match(branch) or ".." in branch:
            self.add("malformed_evidence", INCONCLUSIVE, field="target_branch", **tag)
            return ctx

        integrated = rec.get("integrated") or {}
        current = integrated.get("current")
        if current is None:
            withdrawn = any(isinstance(h, dict) and h.get("withdrawn_at")
                            for h in integrated.get("history") or [])
            self.add("integration_withdrawn" if withdrawn else "not_integrated", NOT_COMPLETE, **tag)
            return ctx
        if not isinstance(current, dict) or _sha(current.get("merge_sha")) is None:
            self.add("malformed_evidence", INCONCLUSIVE, field="integrated.current", **tag)
            return ctx
        if current.get("branch") != branch:
            self.add("wrong_base", NOT_COMPLETE, recorded=branch, integrated=current.get("branch"), **tag)

        entries = [e for e in rec.get("post_merge") or []
                   if isinstance(e, dict) and _sha_eq(e.get("merge_sha"), current.get("merge_sha"))]
        if not entries:
            self.add("post_merge_missing", INCONCLUSIVE, **tag)
        elif len(entries) > 1:
            self.add("post_merge_ambiguous", INCONCLUSIVE, **tag)
        else:
            ctx["pm"] = entries[0]
            self.check_gate(ctx, rec, entries[0], current, tag)

        assurance = rec.get("assurance") or {}
        if assurance.get("outcome") == "fail":
            self.add("assurance_failed", NOT_COMPLETE, **tag)
        elif not (assurance.get("outcome") == "pass" and assurance.get("current") is True):
            self.add("assurance_not_current", INCONCLUSIVE, outcome=assurance.get("outcome"),
                     stale_reason=assurance.get("stale_reason"), **tag)

        data = self.read(f"pr:{prq}", f"repos/{repo}/pulls/{number}", **tag)
        if not isinstance(data, dict):
            if data is not None:
                self.add("unparseable_read", INCONCLUSIVE, read=f"pr:{prq}", **tag)
            return ctx
        base = data.get("base") or {}
        base_repo = (base.get("repo") or {}).get("full_name")
        merge = _sha(data.get("merge_commit_sha"))
        head = _sha((data.get("head") or {}).get("sha"))
        merged = data.get("merged") is True
        fact.update({"state": "merged" if merged else data.get("state"), "merge_sha": merge,
                     "destination_branch": base.get("ref"), "head_sha": head})
        ctx.update({"merge": merge, "head": head})
        demonstrated_unmet = False
        if not merged:
            self.add("pr_not_merged", NOT_COMPLETE, **tag)
            demonstrated_unmet = True
        if not isinstance(base_repo, str) or base_repo.lower() != self.repo.lower():
            self.add("wrong_repository", NOT_COMPLETE, expected=self.repo, found=base_repo, **tag)
            demonstrated_unmet = True
        if base.get("ref") != branch:
            self.add("wrong_base", NOT_COMPLETE, recorded=branch, found=base.get("ref"), **tag)
            demonstrated_unmet = True
        recorded_merges = [current.get("merge_sha")] + ([ctx["pm"].get("merge_sha")] if ctx["pm"] else [])
        if merged and (merge is None or not all(_sha_eq(merge, m) for m in recorded_merges)):
            self.add("merge_sha_mismatch", NOT_COMPLETE, recorded=recorded_merges, found=merge, **tag)
            demonstrated_unmet = True
        if not _sha_eq(head, rec.get("headRefOid")):
            self.add("head_mismatch", NOT_COMPLETE, recorded=rec.get("headRefOid"), found=head, **tag)
            demonstrated_unmet = True
        if demonstrated_unmet or merge is None:
            return ctx

        compare = self.read(f"reachability:{prq}", f"repos/{repo}/compare/{branch}...{merge}", **tag)
        if isinstance(compare, dict):
            reachable = compare.get("status") in ("behind", "identical")
            fact["reachable_from_destination"] = reachable
            if not reachable:
                self.add("merge_not_reachable", NOT_COMPLETE, branch=branch,
                         status=compare.get("status"), **tag)
                return ctx
        else:
            return ctx

        if ctx["pm"] is not None and ctx["pm"].get("gate_result") == "applies_verbatim":
            self.check_tree_equivalence(ctx, rec, tag)
        self.scan_reverts(ctx, branch, tag)
        ctx["usable"] = True
        return ctx

    def check_gate(self, ctx, rec, pm, current, tag):
        gate = pm.get("gate_result")
        if gate == "applies_verbatim":
            if pm.get("tested_vs_merged") == "differs":
                self.add("merged_tree_differs_without_rerun", NOT_COMPLETE, **tag)
            elif pm.get("action") != "applies_verbatim" or pm.get("tested_vs_merged") != "same":
                self.add("gate_record_inconsistent", INCONCLUSIVE, gate_result=gate,
                         action=pm.get("action"), tested_vs_merged=pm.get("tested_vs_merged"), **tag)
            else:
                ctx["verbatim_run"] = self.verbatim_run(rec)
                if ctx["verbatim_run"] is None:
                    self.add("tree_equivalence_unverifiable", INCONCLUSIVE, why="no passing run at head", **tag)
        elif gate == "rerun_pass":
            run = pm.get("run")
            subject = (run or {}).get("tested_subject") or {}
            if pm.get("action") != "full_required_gate_rerun" or not isinstance(run, dict):
                self.add("gate_record_inconsistent", INCONCLUSIVE, gate_result=gate,
                         action=pm.get("action"), **tag)
            elif run.get("conclusion") != "success":
                self.add("post_merge_failed", NOT_COMPLETE, conclusion=run.get("conclusion"), **tag)
            elif not _sha_eq(subject.get("sha"), current.get("merge_sha")):
                self.add("rerun_subject_mismatch", NOT_COMPLETE, tested=subject.get("sha"),
                         merge=current.get("merge_sha"), **tag)
        elif gate in (None, "pending"):
            self.add("post_merge_pending", INCONCLUSIVE, **tag)
        elif gate in _FAILED_GATE_RESULTS:
            self.add("post_merge_failed", NOT_COMPLETE, gate_result=gate, **tag)
        else:
            self.add("gate_result_unknown", INCONCLUSIVE, gate_result=gate, **tag)

        verdict = pm.get("criteria_verdict")
        if verdict == "unmet":
            self.add("criteria_unmet", NOT_COMPLETE, **tag)
        elif verdict != "confirmed":
            self.add("criteria_verdict_not_confirmed", INCONCLUSIVE, criteria_verdict=verdict, **tag)

        self.inputs.append({
            "reference": f"{self.ref}#pull_requests/{ctx['prq']}/post_merge",
            "revision": pm.get("merge_sha"),
            "recorded_at": pm.get("merged_at"),
            "digest": canonical_digest(pm),
            "supplies": "merged-tree gate result (gate_result, criteria_verdict) at the merge sha",
        })

    @staticmethod
    def verbatim_run(rec):
        runs = [r for r in rec.get("ci_runs") or [] if isinstance(r, dict)
                and _sha_eq(((r.get("tested_subject") or {}).get("head")), rec.get("headRefOid"))]
        return runs[-1] if runs else None

    def check_tree_equivalence(self, ctx, rec, tag):
        run = ctx["verbatim_run"]
        if run is None:
            return
        tested = _sha((run.get("tested_subject") or {}).get("sha"))
        repo = self.repo
        if tested is None:
            self.add("tree_equivalence_unverifiable", INCONCLUSIVE, why="tested subject unrecorded", **tag)
            return
        left = self.read(f"tree:{tested}", f"repos/{repo}/commits/{tested}", **tag)
        right = self.read(f"tree:{ctx['merge']}", f"repos/{repo}/commits/{ctx['merge']}", **tag)
        trees = []
        for data in (left, right):
            tree = (((data or {}).get("commit") or {}).get("tree") or {}).get("sha") if isinstance(data, dict) else None
            trees.append(tree)
        if left is None or right is None:
            return
        if not trees[0] or not trees[1]:
            self.add("tree_equivalence_unverifiable", INCONCLUSIVE, why="tree unreadable", **tag)
            return
        ctx["tree_equivalent"] = trees[0] == trees[1]
        self.facts["pull_requests"][-1]["tree_equivalent"] = ctx["tree_equivalent"]
        if not ctx["tree_equivalent"]:
            self.add("tree_not_equivalent", NOT_COMPLETE, tested=tested, merge=ctx["merge"], **tag)

    def scan_reverts(self, ctx, branch, tag):
        """Best effort (D4.3 item 2). It can only add a reason; it never upgrades."""
        pm = ctx["pm"] or {}
        merged_at = _parse_utc(pm.get("merged_at"))
        if merged_at is None:
            self.add("revert_scan_unavailable", ADVISORY, why="merged_at unrecorded", **tag)
            return
        endpoint = f"repos/{self.repo}/commits?sha={branch}&since={_iso(merged_at)}&per_page=100"
        try:
            commits = self.reader.read(f"revert-scan:{ctx['prq']}", endpoint, paginate=True, blocking=False)
        except ReadFailed as exc:
            self.add("revert_scan_unavailable", ADVISORY, cause=exc.cause, **tag)
            return
        for commit in commits if isinstance(commits, list) else []:
            message = ((commit or {}).get("commit") or {}).get("message") or ""
            for match in _REVERT_RE.finditer(message):
                if _sha_eq(match.group(1), ctx["merge"]):
                    self.add("unrecorded_revert_suspected", INCONCLUSIVE,
                             revert_commit=(commit or {}).get("sha"), **tag)
                    return

    # Criteria ---------------------------------------------------------------

    def criteria_set(self):
        if self.parent_record is not None:
            return self.parent_record.get("criteria_ref"), self.parent_record.get("criteria")
        if len(self.records) == 1:
            rec = next(iter(self.records.values()))
            return rec.get("criteria_ref"), rec.get("criteria")
        return None, None

    def check_criteria(self, lead_id, workers, workers_readable):
        cref, items = self.criteria_set()
        digest = _digest_hex(cref)
        if not isinstance(items, list) or not items or digest is None:
            self.add("criteria_unavailable", INCONCLUSIVE, issues=self.issues, criteria_ref=cref)
            return
        self.cref = cref
        self.lead_id = lead_id
        self.workers = workers
        self.workers_readable = workers_readable
        for item in items:
            cid = item.get("id") if isinstance(item, dict) else None
            etype, eid = _evaluator(item)
            line = {"criteria_ref": cref, "id": cid, "evaluator": etype, "evaluator_id": eid,
                    "state": "inconclusive", "reason_code": None, "accepted_proof": None, "prs": []}
            self.lines.append(line)
            parts = _criterion_parts(cid)
            if parts is None:
                self.criterion(line, INCONCLUSIVE, "malformed_criterion_id")
                continue
            if not digest.startswith(parts[1]):
                self.criterion(line, INCONCLUSIVE, "criteria_revision_stale", current=cref)
                continue
            if etype not in EVALUATOR_TYPES:
                self.criterion(line, INCONCLUSIVE, "evaluator_unassigned")
                continue
            if etype == "human":
                self.check_human(line, parts)
                continue
            proving = [ctx for prq, ctx in sorted(self.prs.items())
                       if cid in (ctx["record"].get("criteria_ids") or [])]
            line["prs"] = [ctx["prq"] for ctx in proving]
            if not proving:
                stale = any(
                    isinstance(other, str) and (_criterion_parts(other) or ("",))[0] == parts[0]
                    for ctx in self.prs.values() for other in ctx["record"].get("criteria_ids") or [])
                self.criterion(line, INCONCLUSIVE, "criteria_revision_stale" if stale else "criterion_unmapped")
                continue
            results = []
            for ctx in proving:
                if not ctx["usable"]:
                    results.append((INCONCLUSIVE, "pr_evidence_unusable", None, {"pr": ctx["prq"]}))
                    continue
                checker = {"test": self.proof_test, "demonstration": self.proof_demonstration,
                           "independent_reviewer": self.proof_reviewer}[etype]
                results.append(checker(cid, etype, ctx))
            self.settle(line, results)

    def settle(self, line, results):
        for cls in (NOT_COMPLETE, INCONCLUSIVE):
            for result_cls, code, _, detail in results:
                if result_cls == cls:
                    self.criterion(line, cls, code, **(detail or {}))
                    return
        line["state"] = "met"
        line["reason_code"] = "ok"
        proofs = [proof for _, _, proof, _ in results]
        line["accepted_proof"] = proofs[0] if len(proofs) == 1 else {"per_pr": proofs}

    def criterion(self, line, cls, code, **detail):
        line["state"] = "unmet" if cls == NOT_COMPLETE else "inconclusive"
        line["reason_code"] = code
        self.add(code, cls, criteria=[line["id"]], prs=line.get("prs") or (), **detail)

    def post_merge_item(self, cid, etype, ctx):
        """Common post-merge criterion checks. Returns (cls, code, detail) or None."""
        rec, pm = ctx["record"], ctx["pm"] or {}
        assigned = _find(rec.get("criteria"), "id", cid)
        if assigned is None:
            return INCONCLUSIVE, "criterion_record_missing", {}
        if _evaluator(assigned)[0] != etype:
            return NOT_COMPLETE, "evaluator_mismatch", {"assigned": etype, "recorded": _evaluator(assigned)[0]}
        item = _find(pm.get("criteria"), "id", cid)
        if item is None:
            return INCONCLUSIVE, "post_merge_criterion_missing", {}
        recorded_type = _evaluator(item)[0]
        if recorded_type is not None and recorded_type != etype:
            return NOT_COMPLETE, "evaluator_mismatch", {"assigned": etype, "recorded": recorded_type}
        if item.get("outcome") == "fail":
            return NOT_COMPLETE, "criterion_failed", {}
        if item.get("outcome") != "pass":
            return INCONCLUSIVE, "criterion_not_passed", {"outcome": item.get("outcome")}
        if not _sha_eq(item.get("at"), ctx["merge"]):
            return NOT_COMPLETE, "proof_at_wrong_revision", {"at": item.get("at")}
        basis = item.get("basis")
        if basis == "reused" and not item.get("justification"):
            return INCONCLUSIVE, "reuse_without_basis", {}
        if basis not in ("fresh", "reused"):
            return INCONCLUSIVE, "reuse_without_basis", {"basis": basis}
        return None

    def proof_test(self, cid, etype, ctx):
        failed = self.post_merge_item(cid, etype, ctx)
        if failed:
            return failed[0], failed[1], None, failed[2]
        rec, pm = ctx["record"], ctx["pm"]
        if pm.get("action") == "full_required_gate_rerun":
            run = pm.get("run")
            origin = _find(rec.get("ci_runs"), "job", (run or {}).get("job")) or {}
            subject_ok = _sha_eq(((run or {}).get("tested_subject") or {}).get("sha"), ctx["merge"])
        else:
            run = ctx["verbatim_run"]
            origin = run or {}
            subject_ok = ctx["tree_equivalent"] is True
        if not isinstance(run, dict):
            return INCONCLUSIVE, "test_run_missing", None, {}
        if run.get("conclusion") != "success":
            return NOT_COMPLETE, "run_not_success", None, {"conclusion": run.get("conclusion")}
        if run.get("run") is None and not (run.get("executor") and run.get("fallback_approved_by")):
            return NOT_COMPLETE, "local_run_without_fallback", None, {}
        if not subject_ok:
            return NOT_COMPLETE, "test_subject_mismatch", None, {}
        if pm.get("action") != "full_required_gate_rerun":
            applicability = origin.get("applicability")
            if not (isinstance(applicability, dict) and applicability.get("established") is True):
                return INCONCLUSIVE, "applicability_not_established", None, {}
        job = run.get("job") or origin.get("job")
        check = _find(rec.get("checks"), "id", job)
        definition = run.get("definition_ref") or origin.get("definition_ref")
        if check is None or not isinstance(definition, dict) or not isinstance(check.get("definition_ref"), dict):
            return INCONCLUSIVE, "definition_unbound", None, {"job": job}
        if (definition.get("ref"), definition.get("rev")) != (
                check["definition_ref"].get("ref"), check["definition_ref"].get("rev")):
            return NOT_COMPLETE, "definition_mismatch", None, {"run": definition,
                                                              "check": check["definition_ref"]}
        run_env = run.get("environment")
        origin_env = origin.get("environment")
        if run_env and origin_env and run is not origin and run_env != origin_env:
            return NOT_COMPLETE, "environment_mismatch", None, {"run": run_env, "tested": origin_env}
        check_env = check.get("environment")
        if check_env in _CI_ENVIRONMENTS:
            if run.get("run") is None:
                return NOT_COMPLETE, "environment_mismatch", None, {"check": check_env, "run": "local"}
        elif check_env and (run_env or origin_env) != check_env:
            return NOT_COMPLETE, "environment_mismatch", None, {"check": check_env, "run": run_env or origin_env}
        item = _find(pm.get("criteria"), "id", cid)
        proof = {"conclusion": "success", "definition": definition,
                 "tested_subject": run.get("tested_subject"),
                 "run": {"run": run.get("run"), "job": job, "attempt": run.get("attempt")},
                 "evidence_ref": item.get("evidence_ref"), "pr": ctx["prq"]}
        return None, "ok", proof, {}

    def proof_demonstration(self, cid, etype, ctx):
        failed = self.post_merge_item(cid, etype, ctx)
        if failed:
            return failed[0], failed[1], None, failed[2]
        demo = ctx["record"].get("demonstrated")
        if demo == "expired" or (isinstance(demo, dict) and (demo.get("expired") or demo.get("status") == "expired")):
            return NOT_COMPLETE, "demonstration_expired", None, {}
        if not isinstance(demo, dict) or not all(demo.get(k) for k in ("what", "where", "revision", "how")):
            return NOT_COMPLETE, "demonstration_unexplained", None, {}
        if not (_sha_eq(demo.get("revision"), ctx["record"].get("headRefOid"))
                or _sha_eq(demo.get("revision"), ctx["merge"])):
            return NOT_COMPLETE, "demonstration_stale_revision", None, {"revision": demo.get("revision")}
        proof = {k: demo.get(k) for k in ("what", "where", "revision", "how")}
        proof["pr"] = ctx["prq"]
        return None, "ok", proof, {}

    def proof_reviewer(self, cid, etype, ctx):
        failed = self.post_merge_item(cid, etype, ctx)
        if failed:
            return failed[0], failed[1], None, failed[2]
        rec = ctx["record"]
        reviewer = _evaluator(_find(rec.get("criteria"), "id", cid))[1]
        review = rec.get("review")
        if not isinstance(reviewer, str) or not reviewer:
            return INCONCLUSIVE, "reviewer_unidentified", None, {}
        if not self.workers_readable:
            return INCONCLUSIVE, "implementer_identity_unreadable", None, {}
        implementers = {w.get("agent_id") for w in self.workers or []
                        if isinstance(w, dict) and str(w.get("role", "")).startswith("worker")
                        and (w.get("issue") == rec.get("issue") or w.get("pr") in (ctx["number"], ctx["prq"]))}
        if reviewer == self.lead_id or reviewer in implementers:
            return NOT_COMPLETE, "reviewer_not_independent", None, {"reviewer": reviewer}
        if not isinstance(review, dict):
            return INCONCLUSIVE, "review_evidence_missing", None, {}
        if not _sha_eq(review.get("head"), rec.get("headRefOid")):
            return NOT_COMPLETE, "review_of_earlier_head", None, {"reviewed": review.get("head")}
        unresolved = review.get("unresolved_material")
        if not isinstance(unresolved, int) or isinstance(unresolved, bool):
            return INCONCLUSIVE, "review_evidence_missing", None, {"field": "unresolved_material"}
        if unresolved > 0:
            return NOT_COMPLETE, "unresolved_material_finding", None, {"count": unresolved}
        evidence = review.get("evidence_ref")
        review_id = evidence.get("review_id") if isinstance(evidence, dict) else None
        proof = {"reviewer": reviewer, "head": review.get("head"), "unresolved_material": 0,
                 "pr": ctx["prq"]}
        if isinstance(review_id, int) and not isinstance(review_id, bool):
            data = self.reader_read_review(ctx, review_id)
            if data is None:
                return INCONCLUSIVE, "read_failed", None, {"read": f"review:{ctx['prq']}/{review_id}"}
            if _login(data.get("user")) != reviewer.lower():
                return NOT_COMPLETE, "reviewer_not_of_record", None, {"author": _login(data.get("user"))}
            if not _sha_eq(data.get("commit_id"), rec.get("headRefOid")):
                return NOT_COMPLETE, "review_of_earlier_head", None, {"reviewed": data.get("commit_id")}
            proof.update({"kind": "external", "review_id": review_id, "author": _login(data.get("user"))})
            return None, "ok", proof, {}
        if reviewer != rec.get("reviewer_agent_id"):
            return NOT_COMPLETE, "reviewer_not_of_record", None, {"recorded": rec.get("reviewer_agent_id")}
        if not evidence:
            return INCONCLUSIVE, "review_evidence_missing", None, {}
        proof.update({"kind": "internal_lane", "evidence_ref": evidence})
        return None, "ok", proof, {}

    def reader_read_review(self, ctx, review_id):
        try:
            data = self.reader.read(f"review:{ctx['prq']}/{review_id}",
                                    f"repos/{self.repo}/pulls/{ctx['number']}/reviews/{review_id}")
        except ReadFailed:
            return None
        return data if isinstance(data, dict) else None

    def check_human(self, line, parts):
        cid = line["id"]
        if self.owner is None:
            self.criterion(line, INCONCLUSIVE, "owner_account_unavailable")
            return
        target = self.parent if self.parent is not None else (self.issues[0] if len(self.issues) == 1 else None)
        target_parts = _split_issue(target)
        if target_parts is None or target_parts[0] != self.repo:
            self.criterion(line, INCONCLUSIVE, "acceptance_target_unreadable", target=target)
            return
        approved_at = self.criterion_approved_at()
        if approved_at is None:
            self.criterion(line, INCONCLUSIVE, "approval_time_unknown")
            return
        comments = self.read(f"acceptance:{target}",
                             f"repos/{self.repo}/issues/{target_parts[1]}/comments?per_page=100",
                             criteria=[cid], paginate=True)
        if comments is None:
            line["state"] = "inconclusive"
            line["reason_code"] = "read_failed"
            return
        ignored = []
        for comment in comments if isinstance(comments, list) else []:
            if not isinstance(comment, dict):
                continue
            body = comment.get("body") or ""
            for text in body.splitlines():
                match = _ACCEPT_RE.match(text.strip())
                if not match:
                    continue
                named = match.group(1)
                named_parts = _criterion_parts(named)
                author = _login(comment.get("user"))
                posted = _parse_utc(comment.get("created_at"))
                if named != cid:
                    if named_parts and named_parts[0] == parts[0]:
                        ignored.append({"why": "superseded_revision", "named": named, "author": author})
                    continue
                if author != self.owner:
                    ignored.append({"why": "non_owner", "author": author})
                elif posted is None or posted <= approved_at:
                    ignored.append({"why": "before_current_revision_approval", "author": author})
                else:
                    line.update({"state": "met", "reason_code": "ok", "accepted_proof": {
                        "command": f"/accept {cid}", "author": author, "issue": target,
                        "created_at": comment.get("created_at"),
                        "comment": comment.get("html_url") or comment.get("id")}})
                    return
        self.criterion(line, NOT_COMPLETE, "awaiting_owner_acceptance", ignored=ignored)

    def criterion_approved_at(self):
        amendment = (self.parent_record or {}).get("amendment")
        if isinstance(amendment, dict) and amendment.get("to") == self.cref:
            return _parse_utc(amendment.get("at"))
        return _parse_utc(self.goal.get("approval_time"))


def evaluate(ledger_text, *, purpose=PURPOSE_FINAL, owner_account=None, runner=None, sleep=None,
             now=None, ledger_ref=DEFAULT_LEDGER_REF, invoker=None, consumer_context=None,
             supersedes=(), marker=None, approved_revision=None, hook_cap_exhausted=False,
             result_id=None) -> Verification:
    """Evaluate one goal run. Never raises for bad input; never writes."""
    if purpose not in VOCABULARY:
        return _error("usage", f"unknown purpose: {purpose!r}")
    moment = now if isinstance(now, datetime) else datetime.now(timezone.utc)
    observed_at = _iso(moment)
    try:
        goal = read_goal_block(ledger_text)
    except LedgerError as exc:
        return _error("ledger_unreadable", str(exc), field=exc.field)

    entry = {key: goal.get(key) for key in _ASSIGNMENT_KEYS if key in goal}
    reasons_pre = []
    armed = goal_run.arm(entry, deliverable_type=goal.get("deliverable_type"))
    if not armed.ok and armed.reason in _SOURCE_MISMATCHES:
        reasons_pre.append(_Reason("source_revision_mismatch", INCONCLUSIVE,
                                   detail={"reason": armed.reason}))
        plan = entry.get("plan_ref") if isinstance(entry.get("plan_ref"), dict) else {}
        approved = plan.get("approved_revision")
        locator = str(entry.get("source") or "").rsplit("@", 1)[0]
        armed = goal_run.arm(dict(entry, approval_revision=approved, source=f"{locator}@{approved}"),
                             deliverable_type=goal.get("deliverable_type"))
    if not armed.ok:
        if armed.reason in _ARMING_REJECTIONS:
            return Verification("arming_rejection", {
                "kind": ARMING_REJECTION_KIND,
                "rejected": _ARMING_REJECTIONS[armed.reason],
                "reason": armed.reason,
                "detail": dict(armed.detail),
                "run": goal.get("run"),
                "repository": goal.get("repo"),
                "fixed_issues": goal.get("fixed_issues"),
                "message": "rejected at goal arming: use the ordinary workflow; "
                           "no completion result was produced",
            }, EXIT_ERROR)
        return _error("invalid_goal_identity", armed.reason, detail=dict(armed.detail))
    assignment = armed.value.assignment

    reader = _Reader(runner=runner or subprocess_runner, sleep=sleep or time.sleep)
    blocks = {}
    block_failures = []
    for key in ("pull_requests", "parent_acceptance", "workers"):
        try:
            value = read_block(ledger_text, key)
        except LedgerError as exc:
            block_failures.append((key, str(exc)))
            value = None
        else:
            if value is _ABSENT or value is None:
                value = []
            elif not isinstance(value, list):
                block_failures.append((key, "must be a list"))
                value = None
        blocks[key] = value

    run = _Evaluation(reader, purpose, owner_account, assignment, goal, blocks)
    run.ref = ledger_ref
    run.reasons.extend(reasons_pre)
    for key, message in block_failures:
        if key != "workers":
            run.add("ledger_block_unreadable", INCONCLUSIVE, block=key, message=message)
        reader.unread.append({"read": f"ledger:{key}", "cause": message, "blocking": key != "workers"})

    plan_ref = assignment.to_dict()["plan_ref"]
    if approved_revision is not None and approved_revision != plan_ref.get("approved_revision"):
        run.add("source_revision_stale", INCONCLUSIVE, recorded=plan_ref.get("approved_revision"),
                current=approved_revision)
    frozen_at = goal.get("approval_time")
    if _parse_utc(frozen_at) is None:
        run.add("frozen_at_unknown", INCONCLUSIVE, approval_time=frozen_at)
    if marker is not None:
        parsed = goal_run.parse_turn_end_marker(marker, expected_source=assignment.source)
        if parsed.outcome == "invalid":
            run.add("marker_mismatch" if parsed.reason == "wrong_source" else "marker_invalid",
                    INCONCLUSIVE, reason=parsed.reason, detail=dict(parsed.detail))
    if hook_cap_exhausted:
        run.add("hook_cap_exhausted", ADVISORY)

    ledger_digest = "sha256:" + hashlib.sha256(ledger_text.encode("utf-8")).hexdigest()
    try:
        updated_at = read_block(ledger_text, "updated_at")
    except LedgerError:
        updated_at = None
    run.inputs.append({"reference": ledger_ref, "revision": None,
                       "recorded_at": updated_at if isinstance(updated_at, str) else None,
                       "digest": ledger_digest, "supplies": "the ledger snapshot read"})
    run.inputs.append({"reference": f"{ledger_ref}#goal_run",
                       "revision": plan_ref.get("approved_revision"), "recorded_at": frozen_at,
                       "digest": canonical_digest(goal),
                       "supplies": "goal identity, plan_ref and frozen qualified Issue set"})
    if run.inputs[0]["recorded_at"] is None:
        run.inputs[0]["revision"] = ledger_digest

    if blocks["pull_requests"] is not None and blocks["parent_acceptance"] is not None:
        run.map_evidence()
        run.check_issues()
        run.check_prs()
        lead_id = (goal.get("lead") or {}).get("agent_id") if isinstance(goal.get("lead"), dict) else None
        run.check_criteria(lead_id, blocks["workers"], blocks["workers"] is not None)
    else:
        run.check_issues()

    blocking = [r for r in run.reasons if r.cls != ADVISORY]
    if any(r.cls == NOT_COMPLETE for r in blocking):
        final = "not_complete"
    elif blocking or any(line["state"] != "met" for line in run.lines):
        final = "inconclusive"
    else:
        final = "verified"
    if not run.lines and final == "verified":
        final = "inconclusive"
        run.add("criteria_unavailable", INCONCLUSIVE, issues=run.issues)
    outcome = final if purpose == PURPOSE_FINAL else {
        "verified": "evidence_ready", "not_complete": "not_ready"}.get(final, final)

    goal_record = {"repository": assignment.repo, "fixed_issues": list(assignment.fixed_issues),
                   "frozen_at": frozen_at}
    if run.parent is not None and run.parent not in assignment.fixed_issues:
        goal_record["parent"] = run.parent
    invoker = invoker or {}
    record = {
        "profile_version": RESULT_PROFILE,
        "result_id": None,
        "run_id": assignment.run,
        "plan_ref": plan_ref,
        "goal": goal_record,
        "evidence_profile": EVIDENCE_PROFILE,
        "consumed_inputs": run.inputs,
        "purpose": purpose,
        "repository_facts": dict(run.facts, observed_at=observed_at),
        "criteria": run.lines,
        "outcome": outcome,
        "reason_codes": [r.to_dict() for r in run.reasons],
        "unread_inputs": [u for u in reader.unread if u.get("blocking")],
        "producer": {
            "helper": "skills/dev/scripts/verify_goal_completion.py",
            "helper_revision": _helper_revision(),
            "skill_revision": _skill_revision(),
            "invoker_role": invoker.get("role"),
            "invoker_id": invoker.get("id"),
            "invoker_harness": invoker.get("harness"),
            "consumer_context": consumer_context,
            "hook_cap_exhausted": bool(hook_cap_exhausted),
            "recorded_by": "lead",
        },
        "supersedes": [s for s in supersedes or () if isinstance(s, str) and s],
    }
    record["result_id"] = result_id or "gv-" + canonical_digest(
        [assignment.run, purpose, observed_at, ledger_digest])[7:23]
    return Verification("result", record, EXIT_CODES[outcome])


# --- Command line ------------------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # usage errors exit EXIT_ERROR, never 0
        self.print_usage(sys.stderr)
        print(json.dumps({"kind": ERROR_KIND, "error": "usage", "message": message}), file=sys.stdout)
        raise SystemExit(EXIT_ERROR)


def _build_parser():
    parser = _Parser(description="Goal completion verifier (completion-result-v1). Read-only.")
    parser.add_argument("--ledger", required=True, help="path to the Dev ledger (read only)")
    parser.add_argument("--purpose", default=PURPOSE_FINAL, choices=sorted(VOCABULARY))
    parser.add_argument("--owner-account", help="owner GitHub login for /accept commands")
    parser.add_argument("--marker", help="the lead's turn-end marker text (never proof)")
    parser.add_argument("--approved-revision", help="current approved plan revision")
    parser.add_argument("--invoker-role")
    parser.add_argument("--invoker-id")
    parser.add_argument("--invoker-harness")
    parser.add_argument("--consumer-context")
    parser.add_argument("--hook-cap-exhausted", action="store_true")
    parser.add_argument("--supersedes", action="append", default=[])
    parser.add_argument("--result-id")
    parser.add_argument("--ledger-ref", default=DEFAULT_LEDGER_REF)
    return parser


def main(argv=None, runner=None, sleep=None, now=None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        with open(args.ledger, "r", encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        result = _error("ledger_unreadable", f"{type(exc).__name__}: {exc}")
    else:
        try:
            result = evaluate(
                text, purpose=args.purpose, owner_account=args.owner_account, runner=runner,
                sleep=sleep, now=now, ledger_ref=args.ledger_ref,
                invoker={"role": args.invoker_role, "id": args.invoker_id, "harness": args.invoker_harness},
                consumer_context=args.consumer_context, supersedes=args.supersedes,
                marker=args.marker, approved_revision=args.approved_revision,
                hook_cap_exhausted=args.hook_cap_exhausted, result_id=args.result_id)
        except Exception as exc:  # internal error: never a success code
            result = _error("internal_error", f"{type(exc).__name__}: {exc}")
    print(json.dumps(result.record, indent=2, sort_keys=True))
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
