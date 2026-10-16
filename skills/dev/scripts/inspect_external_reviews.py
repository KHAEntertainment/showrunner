#!/usr/bin/env python3
"""Inspect trusted external review evidence for one GitHub pull request.

The helper deliberately does not make semantic judgments about review comments.
It normalizes current-head evidence and accepts Tech Lead dispositions so the
workflow can distinguish blocking findings from advisory or false-positive
findings without relying on vendor-specific wording heuristics.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


# Issue #82: built-in reviewers. Each reviewer key maps to logins confirmed
# on 2026-09-28 by querying `commenter:app/<name>` (PR counts) or the users
# API. A login that no longer resolves is not added. `github-actions[bot]`
# is shared by every workflow and is not a stable identity, so it is
# deliberately absent: a workflow that wants to be trusted must install a
# dedicated GitHub App or bot account and surface it under
# `Additional reviewer identities` in `PROJECT_CONTEXT.md`.
#
# Vendor identity notes (kept here, not in the SOP, so the data row is the
# only thing that changes when a login does). Reviewer behavior below
# without a `check: ...` line is comment-only and has no entry in
# `DEFAULT_CHECK_MARKERS`; pushing re-review defaults are documented where
# verified (CodeRabbit, Kilo, Greptile, Sourcery) and left unverified
# otherwise (Gemini, Qodo):
#   - gemini-code-assist: comment-only. Re-review-on-push default is
#     UNVERIFIED here; Google's docs describe the initial review and a
#     manual `/gemini review` trigger, not an automatic new-push
#     re-review. Treat the documented "comment-only" as the only
#     confirmed shape.
#   - greptile: review (`greptile-apps[bot]`) AND check ("Greptile
#     Review", app slug `greptile-apps`). Re-reviews new pushes by
#     default. Verified by a real run on b-editor/beutl#3095.
#   - sourcery: review (`sourcery-ai[bot]`) AND check ("Sourcery
#     review", app slug `sourcery-ai`). Re-reviews on new pushes.
#     Verified by a real run on linuxdeepin/dde-daemon#1280.
#   - qodo: review only (`qodo-code-review[bot]`,
#     `qodo-free-for-open-source-projects[bot]`). Both Qodo apps grant
#     `checks: read` only (no `checks: write`, no `statuses: write`),
#     so no published CheckRun or StatusContext is produced.
#     `qodo-ai[bot]` exists but its review role is unverified and is
#     not added. Comment-only by default; a check run is not added
#     because no producing app was found.
#   - pr-agent (self-hosted): excluded — runs under `github-actions[bot]`,
#     which is shared with every workflow and therefore not a stable
#     identity. Trust per repo only when it posts under a dedicated bot
#     account, via `Additional reviewer identities`.
DEFAULT_IDENTITIES: dict[str, set[str]] = {
    "coderabbit": {
        "coderabbit",
        "coderabbitai",
        "coderabbitai[bot]",
    },
    "kilo": {
        "kilo-code",
        "kilo-code-bot",
        "kilo-code-bot[bot]",
        "kilo-code[bot]",
        "kilocode",
        "kilocode-bot",
        "kilocode-bot[bot]",
    },
    "github-copilot": {
        "copilot-pull-request-reviewer",
        "copilot-pull-request-reviewer[bot]",
    },
    "gemini-code-assist": {
        "gemini-code-assist",
        "gemini-code-assist[bot]",
    },
    "greptile": {
        "greptile-apps",
        "greptile-apps[bot]",
    },
    "sourcery": {
        "sourcery-ai",
        "sourcery-ai[bot]",
    },
    "qodo": {
        "qodo-code-review",
        "qodo-code-review[bot]",
        "qodo-free-for-open-source-projects",
        "qodo-free-for-open-source-projects[bot]",
    },
}

# Check-run markers: a check matches a reviewer if any marker appears in the
# check's combined identity (name, context, app slug, app name, workflow
# name). Only added where a real check producer was verified; comment-only
# reviewers leave this empty and complete through review evidence alone.
# The Kilo marker covers the historical "kilocode" and the current
# "kilo-code-bot" app slugs (renamed 2025-10-28).
DEFAULT_CHECK_MARKERS: dict[str, set[str]] = {
    "coderabbit": {"coderabbit", "coderabbitai"},
    "kilo": {"kilo code", "kilocode", "kilo-code", "kilo-code-bot"},
    "github-copilot": {"copilot code review", "github copilot review"},
    "greptile": {"greptile", "greptile review", "greptile-apps"},
    "sourcery": {"sourcery", "sourcery review", "sourcery-ai"},
}

# Issue #117: Kilo posts a PR issue comment with this marker as its
# summary, when its check run succeeds. A reviewer that completes only
# through summary comments is documented as comment-only in
# `phases/external-review.md` (the same way Copilot is).
KILO_REVIEW_MARKER = "<!-- kilo-review -->"
# "No Issues Found" is the only status line that counts as a clear verdict
# at head. Any other status ("Issues Found", "Recommendation: Request
# Changes", "Recommendation: Investigate", etc.) leaves Kilo pending with
# the summary as an untriaged finding, so the lead triages it through the
# normal disposition path.
KILO_CLEAR_STATUS = "No Issues Found"
# Both fields must read this way for the summary to count as a clear
# verdict at head. Issue #117's scope comment is explicit: any
# recommendation other than Merge is "blocking or untriaged until
# dispositioned", so a `Status: No Issues Found | Recommendation:
# Request Changes` summary must NOT clear. The two constants are
# paired in `kilo_summary_evidence_for_head` below.
KILO_CLEAR_RECOMMENDATION = "Merge"
# A failed Kilo check whose output names this phrase is the rate-limit
# failure the rate-limit breakpoint (#48) needs to count. Matched
# case-insensitively against the check's `description` (or `output.text`,
# when a future API surfaces it), so a vendor that changes its prefix
# string still trips the same gate.
KILO_RATE_LIMIT_PHRASE = "assistant request was rate limited"
# A failed check whose output names this general phrase is a
# vendor-agnostic rate-limit failure. Used by the #48 breakpoint to
# count a rate-limit event against any reviewer (the Issue #82
# acceptance criterion exercises the breakpoint against one of the
# newly added reviewers). `RATE_LIMIT_PHRASE` is intentionally broad
# (case-insensitive substring) so a vendor that prefixes the rate-limit
# with a different word — "Greptile review failed: Assistant request
# was rate limited" vs Kilo's wording — still trips the same gate.
RATE_LIMIT_PHRASE = "rate limit"

REQUEST_ALIASES: dict[str, set[str]] = {
    "github-copilot": {
        "copilot",
        "@copilot",
        "copilot-pull-request-reviewer",
        "copilot-pull-request-reviewer[bot]",
    },
}

VALID_DISPOSITIONS = {"blocking", "advisory", "false_positive"}

# Ordered so a reason reads the same way every time.
STALE_VERDICT_PHRASES = (
    ("changes_requested", "requested changes"),
    ("approved", "approved"),
    ("commented", "commented"),
)


class InspectionError(RuntimeError):
    """Raised when GitHub evidence cannot be retrieved or decoded."""


@dataclass(frozen=True)
class ReviewerPolicy:
    identities: dict[str, set[str]]
    check_markers: dict[str, set[str]]
    required: set[str]
    ignored: set[str]


def normalize(value: Any) -> str:
    return str(value or "").strip().lower()


def clip_text(value: Any, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def list_value(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        nodes = value.get("nodes")
        if isinstance(nodes, list):
            return nodes
    return []


def login_from(item: Any) -> str:
    if isinstance(item, str):
        return normalize(item)
    if not isinstance(item, dict):
        return ""
    for path in (
        ("login",),
        ("author", "login"),
        ("requestedReviewer", "login"),
        ("requestedReviewer", "slug"),
    ):
        candidate = nested(item, *path)
        if candidate:
            return normalize(candidate)
    return ""


def commit_oid(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    for path in (("commit", "oid"), ("commit", "id"), ("originalCommit", "oid")):
        candidate = nested(item, *path)
        if candidate:
            return normalize(candidate)
    return normalize(item.get("commitOid") or item.get("headSha"))


def check_identity(check: dict[str, Any]) -> str:
    parts = [
        check.get("name"),
        check.get("context"),
        nested(check, "app", "slug"),
        nested(check, "app", "name"),
        nested(check, "workflow", "name"),
    ]
    return " ".join(normalize(part) for part in parts if part)


def looks_like_bot_login(login: str) -> bool:
    candidate = normalize(login)
    return candidate.endswith("[bot]") or candidate.endswith("-bot") or candidate.endswith("_bot")


def unknown_review_app_identity(check: dict[str, Any]) -> str:
    app_parts = [nested(check, "app", "slug"), nested(check, "app", "name")]
    app_identity = " ".join(normalize(part) for part in app_parts if part)
    if not app_identity:
        return ""
    if not any(marker in app_identity for marker in ("review", "reviewer", "bot", " ai", "ai-", "-ai")):
        return ""
    return check_identity(check)


def reviewer_for_login(login: str, policy: ReviewerPolicy, *, requested: bool = False) -> str | None:
    candidate = normalize(login)
    if not candidate:
        return None
    for reviewer, identities in policy.identities.items():
        allowed = set(identities)
        if requested:
            allowed.update(REQUEST_ALIASES.get(reviewer, set()))
        if candidate in {normalize(identity) for identity in allowed}:
            return reviewer
    return None


def reviewer_for_check(check: dict[str, Any], policy: ReviewerPolicy) -> str | None:
    identity = check_identity(check)
    for reviewer, markers in policy.check_markers.items():
        if any(normalize(marker) in identity for marker in markers):
            return reviewer
    return None


def check_timestamps(check: dict[str, Any]) -> tuple[str, str]:
    """Return (startedAt, completedAt) for a check, in ISO-8601 form.

    A missing field is the empty string. The dates are kept verbatim
    for the ordering comparison; the parser below rejects values that
    do not round-trip as ISO 8601, so a malformed date cannot
    silently satisfy the rule.
    """
    if not isinstance(check, dict):
        return ("", "")
    return (str(check.get("startedAt") or ""), str(check.get("completedAt") or ""))


def parse_iso8601(value: str) -> str | None:
    """Return `value` iff it parses as an ISO 8601 timestamp, else None.

    GitHub returns timestamps in the form
    `2026-10-14T00:22:51Z` (or with milliseconds and a `+00:00`
    offset). The inspector compares these lexicographically: a value
    that fails to parse must NOT be allowed to silently satisfy the
    comparison, so the lexical compare stays on strings. This helper
    is the gate.
    """
    text = str(value or "").strip()
    if not text:
        return None
    pattern = (
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
        r"(\.\d{1,6})?(Z|[+\-]\d{2}:\d{2})$"
    )
    if not re.match(pattern, text):
        return None
    return text


def check_description(check: dict[str, Any]) -> str:
    """Read a check's text payload for vendor-specific markers.

    The rate-limit phrase lives in `output.summary` (and `output.title`,
    for vendors that name their failure mode there) of the head SHA's
    check run. GitHub's `gh pr view --json statusCheckRollup` does not
    expose this field; the live `fetch_pr` path augments each check
    with `output` by querying the head's check-runs REST endpoint
    (see `fetch_pr_with_check_output`). The `description` field is
    kept for backward compatibility with fixtures that pre-date the
    REST augmentation.
    """
    if not isinstance(check, dict):
        return ""
    parts = [
        str(check.get("description") or ""),
        str(nested(check, "output", "text") or ""),
        str(nested(check, "output", "summary") or ""),
        str(nested(check, "output", "title") or ""),
    ]
    return "\n".join(part for part in parts if part)


def is_rate_limited_check(check: dict[str, Any]) -> bool:
    """True when a failed check's description names a rate-limit.

    A vendor-agnostic substring match against the check's text payload
    (description, output.text, output.summary). Kilo's exact phrase
    (`KILO_RATE_LIMIT_PHRASE`) is also matched, so a Kilo check that
    ships only its specific phrase still trips the gate. The broad
    phrase (`RATE_LIMIT_PHRASE`) is the floor: a vendor that prefixes
    its rate-limit message differently — "Greptile review failed:
    Assistant request was rate limited" vs Kilo's wording — still trips
    the same gate, which is what the #48 breakpoint needs to count
    rate-limit events across all built-in reviewers (Issue #82
    acceptance criterion).
    """
    if not isinstance(check, dict):
        return False
    description = normalize(check_description(check))
    return (
        KILO_RATE_LIMIT_PHRASE in description
        or RATE_LIMIT_PHRASE in description
    )


def kilo_summary_status(body: str) -> str:
    """Backwards-compat shim for the legacy single-field Status reader.

    Issue #117's scope comment requires both `Status` AND
    `Recommendation` to be parsed: `Status: No Issues Found |
    Recommendation: Request Changes` is NOT a clear verdict. The new
    verdict function is `kilo_summary_fields`, which returns both.
    This shim keeps any external caller working; the inspector uses
    `kilo_summary_fields` directly.
    """
    status, _ = kilo_summary_fields(body)
    return status


def kilo_summary_fields(body: str) -> tuple[str, str]:
    """Extract the Status and Recommendation lines from a Kilo summary.

    The Kilo summary uses the form
    `**Status:** No Issues Found | **Recommendation:** Merge`. We
    read the substring between `Status:**` and the next `|` (or end
    of line) for status, and the substring after `Recommendation:**`
    to the next newline for recommendation. Both are returned
    lowercased. Issue #117's scope comment is explicit: a
    recommendation other than `Merge` is "blocking or untriaged
    until dispositioned", so the two fields are returned as a pair.
    """
    text = str(body or "")
    lowered = text.lower()
    status_marker = "status:**"
    recommendation_marker = "recommendation:**"
    status_value = ""
    status_index = lowered.find(status_marker)
    if status_index >= 0:
        after = text[status_index + len(status_marker):]
        head = after.splitlines()[0] if after else ""
        status_value = normalize(head.split("|", 1)[0])
    recommendation_value = ""
    recommendation_index = lowered.find(recommendation_marker)
    if recommendation_index >= 0:
        after = text[recommendation_index + len(recommendation_marker):]
        head = after.splitlines()[0] if after else ""
        recommendation_value = normalize(head.split("|", 1)[0])
    return status_value, recommendation_value


def kilo_summary_evidence_for_head(
    current: dict[str, Any],
    policy: ReviewerPolicy,
    dispositions: dict[str, str] | None = None,
) -> tuple[set[str], list[dict[str, Any]], set[str], list[dict[str, Any]], set[Any]]:
    """Return evidence state for a Kilo summary comment at head.

    The Kilo bot posts its verdict as a regular PR issue comment
    with the marker `<!-- kilo-review -->`, when its check run
    succeeds. The comment is bound to the head SHA's check run, not
    to a merely-completed check, because a year-old completed run
    would otherwise clear against a fresh head (the B1 finding). The
    invariant:

      1. The Kilo check for the head SHA COMPLETED with `conclusion`
         equal to `success` (or its upper-case form). A failed or
         still-running run is not a head review.
      2. The summary comment's `updatedAt` (or `createdAt` when the
         comment was never edited) parses as ISO 8601 and is at or
         after the run's `startedAt`. Kilo edits its summary in
         place, so a comment whose `updatedAt` is at or after the
         run started belongs to this run. A comment whose date
         predates the run, or whose date is malformed, does not
         belong to this run and must not clear the gate.

    A summary with `Status: No Issues Found` AND `Recommendation:
    Merge` puts Kilo in `completed_on_head` and routes the gate as
    `clear`. Any other status line, or a non-`Merge`
    recommendation, leaves Kilo out of `completed_on_head` and
    surfaces the summary as a finding the lead triages through the
    existing `blocking` / `advisory` / `false_positive` disposition
    path — a Kilo review with findings still gates instead of
    clearing.

    Returns:
        completed_reviewers: reviewers completed on head by the summary
        findings:            active current-head findings (issues, not clear)
        pending_reviewers:   reviewers to mark pending (e.g. stale)
        rate_limit_reasons:  per-reviewer rate-limit reason entries
                             to feed `pending_reasons` so the
                             breakpoint (#48) can count it.
        consumed_check_ids:  the set of Kilo check identifiers the
                             helper has handled. The main `inspect()`
                             uses this to exclude those checks from
                             the generic `check_failed` path, which
                             would otherwise add a duplicate
                             "trusted review check failed without
                             readable current-head findings" error.

    """
    completed: set[str] = set()
    findings: list[dict[str, Any]] = []
    pending: set[str] = set()
    rate_limit_reasons: list[dict[str, Any]] = []
    consumed_check_ids: set[Any] = set()
    if "kilo" in policy.ignored:
        return completed, findings, pending, rate_limit_reasons, consumed_check_ids

    # The Kilo check for the head SHA is the one in the rollup. We
    # use its `startedAt`, `completedAt`, and `conclusion` for the
    # ordering rule, and its `output` (or `description`) to spot
    # the rate-limit failure. A check that is not a successful head
    # run cannot license a clear summary, regardless of how old or
    # new the comment is.
    kilo_check: dict[str, Any] | None = None
    rate_limited_check: dict[str, Any] | None = None
    for check in list_value(current.get("statusCheckRollup")):
        if not isinstance(check, dict):
            continue
        if reviewer_for_check(check, policy) != "kilo":
            continue
        if is_rate_limited_check(check):
            rate_limited_check = check
            continue
        if kilo_check is None:
            kilo_check = check

    # A failed Kilo check whose description names the rate-limit
    # phrase is the rate-limit signal the rate-limit breakpoint
    # needs. We surface it as a distinct pending reason (not the
    # generic "trusted review check failed without readable
    # current-head findings" the inspector would otherwise add) so
    # the lead's retry path is unambiguous.
    if rate_limited_check is not None:
        pending.add("kilo")
        rate_limit_reasons.append(
            {
                "reviewer": "kilo",
                "reason": "Kilo review check failed with a rate-limit response; retry or take the rate-limit breakpoint",
            }
        )
        consumed_check_ids.add(rate_limited_check.get("id") or rate_limited_check.get("name"))
        return completed, findings, pending, rate_limit_reasons, consumed_check_ids

    started_at_raw, completed_at_raw = check_timestamps(kilo_check or {})
    started_at = parse_iso8601(started_at_raw)
    completed_at = parse_iso8601(completed_at_raw)
    conclusion = normalize(kilo_check.get("conclusion") or "") if isinstance(kilo_check, dict) else ""
    # B1: the Kilo check must COMPLETE with `success` (case-folded).
    # Any other conclusion (failure, neutral, skipped, timed_out,
    # empty) is not a positive head review. The previous
    # implementation admitted any non-empty `completedAt`, which a
    # year-old failed run could satisfy; binding to `success` here
    # closes that hole. A malformed `completedAt` also fails closed,
    # which closes the B1 timestamp-parsing sub-finding.
    head_run_succeeded = (
        conclusion == "success" and bool(completed_at) and bool(started_at)
    )
    if not head_run_succeeded:
        # No successful head run to license the summary. The
        # comment may be from a previous head or the check may
        # still be running; either way, Kilo is pending and the
        # comment is not promoted to a clear verdict.
        has_kilo_marker = any(
            isinstance(c, dict)
            and reviewer_for_login(login_from(c), policy) == "kilo"
            and KILO_REVIEW_MARKER in str(c.get("body") or "")
            for c in list_value(current.get("comments"))
        )
        if has_kilo_marker:
            pending.add("kilo")
        if kilo_check is not None:
            consumed_check_ids.add(kilo_check.get("id") or kilo_check.get("name"))
        return completed, findings, pending, rate_limit_reasons, consumed_check_ids

    dispositions = dispositions or {}
    for comment in list_value(current.get("comments")):
        if not isinstance(comment, dict):
            continue
        if reviewer_for_login(login_from(comment), policy) != "kilo":
            continue
        body = str(comment.get("body") or "")
        if KILO_REVIEW_MARKER not in body:
            continue
        # The comment's `updatedAt` is the moment Kilo last edited
        # the summary in place (PR #118: 00:26:26Z, two seconds
        # after the head's run completed at 00:26:24Z). When the
        # comment was never edited, `updatedAt` is null/empty and
        # `createdAt` is the moment the comment was first posted.
        # A malformed date fails closed: it cannot prove the edit
        # belongs to this run, so the comment does not satisfy the
        # ordering rule.
        updated_at = parse_iso8601(str(comment.get("updatedAt") or ""))
        created_at = parse_iso8601(str(comment.get("createdAt") or ""))
        last_update = updated_at or created_at
        if not last_update or not started_at:
            # A comment without a usable date is not bound to this
            # run. Kilo stays pending until the lead re-runs with
            # a comment that has a parseable timestamp, and the
            # malformed-timestamp case (B1) cannot clear the gate.
            pending.add("kilo")
            continue
        # B1: bind the comment to this run by requiring
        # `last_update >= started_at`. Lexical compare is correct
        # for ISO 8601 in the same zone; both `updated_at` and
        # `created_at` are stored as `...Z` UTC by `gh pr view`,
        # so no zone normalization is needed.
        bound = last_update >= started_at
        if not bound:
            pending.add("kilo")
            continue
        # The summary is from the head's successful run. Apply
        # the verdict rule (Status: No Issues Found AND
        # Recommendation: Merge) and the disposition path for
        # findings.
        status, recommendation = kilo_summary_fields(body)
        if (
            status == normalize(KILO_CLEAR_STATUS)
            and recommendation == normalize(KILO_CLEAR_RECOMMENDATION)
        ):
            completed.add("kilo")
            continue
        # A summary with findings is surfaced as a current-head
        # finding the lead can disposition through the existing
        # `blocking`/`advisory`/`false_positive` path.
        finding_id = str(comment.get("id") or comment.get("url") or "kilo-summary")
        disposition = dispositions.get(finding_id)
        if disposition and disposition not in VALID_DISPOSITIONS:
            disposition = None
        findings.append(
            {
                "id": finding_id,
                "reviewer": "kilo",
                "body": clip_text(body, 2000),
                "url": str(comment.get("url") or ""),
                "path": "",
                "line": None,
                "resolved": False,
                "outdated": False,
                "minimized": False,
                "current_head": True,
                "active": True,
                "disposition": disposition,
            }
        )
    if kilo_check is not None:
        consumed_check_ids.add(kilo_check.get("id") or kilo_check.get("name"))
    return completed, findings, pending, rate_limit_reasons, consumed_check_ids


def stale_review_reason(verdicts: set[str]) -> str:
    """Name what the earlier-head review actually said.

    A stale rejection and a stale approval used to render identically, so a
    lead recording a bypass could not say which one they were waiving. This
    only reports state already read; it changes no merge behaviour, and both
    still leave the reviewer pending.
    """
    phrases = [phrase for verdict, phrase in STALE_VERDICT_PHRASES if verdict in verdicts]
    if not phrases:
        return "submitted review exists only at an earlier head"
    return "submitted review at an earlier head " + ", ".join(phrases)


def parse_identity(
    spec: str,
    identities: dict[str, set[str]],
    check_markers: dict[str, set[str]],
) -> None:
    if "=" not in spec:
        raise argparse.ArgumentTypeError("--identity must use reviewer=login[,login]")
    reviewer, values = spec.split("=", 1)
    reviewer = normalize(reviewer)
    aliases = {normalize(value) for value in values.split(",") if normalize(value)}
    if not reviewer or not aliases:
        raise argparse.ArgumentTypeError("--identity requires a reviewer and at least one login")
    identities.setdefault(reviewer, set()).update(aliases)
    check_markers.setdefault(reviewer, set()).update(aliases)


def run_json(command: list[str], *, snapshot: Path | None = None) -> Any:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
        raise InspectionError(f"command failed ({' '.join(command)}): {detail}")
    if snapshot is not None:
        temporary = None
        try:
            # Publish only a complete, closed file. A hard link creates the
            # destination atomically without replacing an existing snapshot.
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="", dir=snapshot.parent,
                prefix=f".{snapshot.name}.", delete=False,
            ) as output:
                temporary = Path(output.name)
                output.write(completed.stdout)
            os.link(temporary, snapshot)
        except OSError as exc:
            raise InspectionError(f"cannot persist payload snapshot {snapshot}: {exc}") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise InspectionError(f"command returned malformed JSON ({' '.join(command)}): {exc}") from exc


def fetch_threads(repo: str, pr_number: int) -> list[dict[str, Any]]:
    owner, separator, name = repo.partition("/")
    if not separator or not owner or not name:
        raise InspectionError("--repo must use OWNER/REPO")
    query = """
query($owner:String!,$repo:String!,$number:Int!,$cursor:String){
  repository(owner:$owner,name:$repo){
    pullRequest(number:$number){
      reviewThreads(first:100,after:$cursor){
        nodes{
          id isResolved isOutdated path line
          comments(first:100){nodes{
            id body url state createdAt isMinimized minimizedReason
            author{login}
            commit{oid}
            originalCommit{oid}
          } pageInfo{hasNextPage}
        }
        }
        pageInfo{hasNextPage endCursor}
      }
    }
  }
}
""".strip()
    cursor = ""
    threads: list[dict[str, Any]] = []
    while True:
        command = [
            "rtk",
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-F",
            f"owner={owner}",
            "-F",
            f"repo={name}",
            "-F",
            f"number={pr_number}",
        ]
        if cursor:
            command.extend(["-f", f"cursor={cursor}"])
        response = run_json(command)
        connection = nested(response, "data", "repository", "pullRequest", "reviewThreads")
        if not isinstance(connection, dict):
            raise InspectionError("GitHub GraphQL response omitted pullRequest.reviewThreads")
        for node in list_value(connection):
            comments = node.get("comments") if isinstance(node, dict) else None
            if isinstance(comments, dict) and (comments.get("pageInfo") or {}).get("hasNextPage"):
                raise InspectionError("review thread comments exceed the fetched page; evidence is incomplete")
        threads.extend(node for node in list_value(connection) if isinstance(node, dict))
        page_info = connection.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        cursor = str(page_info.get("endCursor") or "")
        if not cursor:
            raise InspectionError("GitHub reported another review-thread page without an end cursor")
    return threads


def fetch_pr(repo: str, pr_number: int, snapshot: Path | None = None) -> dict[str, Any]:
    value = run_json(
        [
            "rtk",
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repo,
            "--json",
            "number,headRefOid,reviewRequests,reviews,latestReviews,statusCheckRollup,comments",
        ],
        snapshot=snapshot,
    )
    if not isinstance(value, dict):
        raise InspectionError("gh pr view did not return an object")
    return value


def fetch_check_output(repo: str, head_sha: str, name: str) -> dict[str, Any] | None:
    """Return the live `output` (and timing) of the head SHA's named check.

    `gh pr view --json statusCheckRollup` returns a CheckRun shape that
    omits both `output` and the run id; the rate-limit phrase lives in
    `output.summary`. To detect a rate-limited Kilo check on live data
    (#117), we call the check-runs REST endpoint for the head SHA and
    return the most recent matching run's output. Failures (network,
    permissions, malformed response) are reported as `None`: the
    inspector's `check_description` will then fall back to the
    `description` field the rollup does carry, and a missing output
    fails closed only as a check the inspector cannot read.

    `name` is matched against the check's `name` field; the returned
    object is the same shape the rollup would carry if `output` were
    on it, so callers can splat it back into a rollup entry.
    """
    if not repo or not head_sha or not name:
        return None
    owner, separator, name_repo = repo.partition("/")
    if not separator or not owner or not name_repo:
        return None
    response = run_json(
        [
            "rtk",
            "gh",
            "api",
            f"repos/{owner}/{name_repo}/commits/{head_sha}/check-runs",
            "-f",
            f"check_name={name}",
            "--jq",
            ".check_runs | sort_by(.started_at) | last // null",
        ]
    )
    if not isinstance(response, dict):
        return None
    output = response.get("output") or {}
    if not isinstance(output, dict):
        return None
    return {
        "id": response.get("id"),
        "name": response.get("name"),
        "status": response.get("status"),
        "conclusion": response.get("conclusion"),
        "startedAt": response.get("started_at"),
        "completedAt": response.get("completed_at"),
        "detailsUrl": response.get("details_url"),
        "app": response.get("app"),
        "output": output,
    }


def augment_checks_with_output(
    current: dict[str, Any], repo: str
) -> dict[str, Any]:
    """Augment each check in the rollup with its live `output` field.

    Live data requires an extra REST call per check; fixture data
    already carries `output`. To keep fixtures authoritative (so a
    fixture can deliberately model an absent output), this function
    only augments a check that lacks `output`; the existing
    `output`/`description` payload is never overwritten.

    Failures are silent: the inspector will report the check as
    unreadable via the generic "trusted review check failed without
    readable current-head findings" error path, which is the safe
    side. The rate-limit path therefore needs a fixture or a
    successful REST call; the SOP names a `description` field as a
    documented fallback for vendors that expose the rate-limit text
    on the rollup itself.
    """
    if not isinstance(current, dict):
        return current
    head_sha = str(current.get("headRefOid") or "")
    if not head_sha:
        return current
    rollup = current.get("statusCheckRollup")
    if not isinstance(rollup, list):
        return current
    for index, check in enumerate(rollup):
        if not isinstance(check, dict):
            continue
        # Skip checks that already carry the augmenting fields
        # (fixtures) or that have a `description` (the documented
        # fallback path). The REST call only adds value when both
        # are absent.
        if isinstance(check.get("output"), dict) and check.get("output"):
            continue
        if check.get("description"):
            continue
        name = str(check.get("name") or "")
        if not name:
            continue
        try:
            augmented = fetch_check_output(repo, head_sha, name)
        except InspectionError:
            continue
        if not augmented:
            continue
        merged = dict(check)
        # Fill only the timing fields when the rollup did not
        # carry them; the REST values are the canonical ones for
        # the head SHA and so outrank the rollup's.
        for field in ("id", "startedAt", "completedAt", "detailsUrl", "app", "output"):
            if augmented.get(field) and not merged.get(field):
                merged[field] = augmented[field]
        rollup[index] = merged
    return current


def fetch_recent(repo: str, current_pr: int, limit: int) -> list[dict[str, Any]]:
    if limit == 0:
        return []
    summaries = run_json(
        [
            "rtk",
            "gh",
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "all",
            "--limit",
            str(limit + 1),
            "--json",
            "number",
        ]
    )
    recent: list[dict[str, Any]] = []
    for summary in list_value(summaries):
        number = summary.get("number") if isinstance(summary, dict) else None
        if not isinstance(number, int) or number == current_pr:
            continue
        recent.append(fetch_pr(repo, number))
        if len(recent) >= limit:
            break
    return recent


def load_fixture(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InspectionError(f"cannot read fixture {path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("current"), dict):
        raise InspectionError("fixture must contain a current PR object")
    threads: list[dict[str, Any]] = []
    raw_threads = payload.get("threads", [])
    if isinstance(raw_threads, list):
        for page in raw_threads:
            if isinstance(page, dict) and "nodes" in page:
                threads.extend(node for node in list_value(page) if isinstance(node, dict))
            elif isinstance(page, dict):
                threads.append(page)
    recent = [item for item in payload.get("recent", []) if isinstance(item, dict)]
    return payload["current"], threads, recent


def iter_reviews(pr: dict[str, Any]) -> Iterable[dict[str, Any]]:
    seen: set[str] = set()
    for key in ("latestReviews", "reviews"):
        for review in list_value(pr.get(key)):
            if not isinstance(review, dict):
                continue
            fallback = f"{login_from(review)}:{review.get('submittedAt')}:{review.get('body')}"
            identifier = str(review.get("id") or fallback)
            if identifier in seen:
                continue
            seen.add(identifier)
            yield review


def observed_in_pr(pr: dict[str, Any], policy: ReviewerPolicy) -> set[str]:
    observed: set[str] = set()
    for review in iter_reviews(pr):
        reviewer = reviewer_for_login(login_from(review), policy)
        if reviewer:
            observed.add(reviewer)
    for comment in list_value(pr.get("comments")):
        reviewer = reviewer_for_login(login_from(comment), policy)
        if reviewer:
            observed.add(reviewer)
    for request in list_value(pr.get("reviewRequests")):
        reviewer = reviewer_for_login(login_from(request), policy, requested=True)
        if reviewer:
            observed.add(reviewer)
    for check in list_value(pr.get("statusCheckRollup")):
        if isinstance(check, dict):
            reviewer = reviewer_for_check(check, policy)
            if reviewer:
                observed.add(reviewer)
    return observed


def inspect(
    current: dict[str, Any],
    threads: list[dict[str, Any]],
    recent: list[dict[str, Any]],
    policy: ReviewerPolicy,
    dispositions: dict[str, str],
    max_body_chars: int = 2000,
) -> dict[str, Any]:
    head_oid = normalize(current.get("headRefOid"))
    errors: list[str] = []
    if not head_oid:
        errors.append("current PR is missing headRefOid")

    current_observed = observed_in_pr(current, policy)
    recent_observed: set[str] = set()
    for pr in recent:
        recent_observed.update(observed_in_pr(pr, policy))

    requested: set[str] = set()
    for request in list_value(current.get("reviewRequests")):
        reviewer = reviewer_for_login(login_from(request), policy, requested=True)
        if reviewer:
            requested.add(reviewer)

    thread_findings: list[dict[str, Any]] = []
    thread_reviewers: set[str] = set()
    completed_on_head: set[str] = set()
    # Issue #117: a Kilo `<!-- kilo-review -->` summary comment is review
    # evidence at head, with its own ordering rule and verdict mapping.
    # Computed before the thread scan so a clear summary satisfies the
    # gate even when no review thread exists, and a rate-limited Kilo
    # check leaves Kilo pending with a distinct reason instead of the
    # generic "trusted review check failed without readable current-head
    # findings" the inspector would otherwise add.
    (
        kilo_completed,
        kilo_findings,
        kilo_pending,
        kilo_rate_limit_reasons,
        kilo_consumed_check_ids,
    ) = kilo_summary_evidence_for_head(current, policy, dispositions)
    completed_on_head.update(kilo_completed)
    thread_findings.extend(kilo_findings)
    for thread in threads:
        comments = [item for item in list_value(thread.get("comments")) if isinstance(item, dict)]
        raw_comments = thread.get("comments")
        if isinstance(raw_comments, dict):
            page_info = raw_comments.get("pageInfo") or {}
            if page_info.get("hasNextPage") or len(list_value(raw_comments)) >= 100:
                errors.append("review thread comments reached the page limit; evidence is incomplete")
        trusted_comments: list[tuple[str, dict[str, Any]]] = []
        for comment in comments:
            reviewer = reviewer_for_login(login_from(comment), policy)
            if reviewer:
                trusted_comments.append((reviewer, comment))
                thread_reviewers.add(reviewer)
        if not trusted_comments:
            continue
        reviewer = trusted_comments[-1][0]
        resolved = bool(thread.get("isResolved"))
        outdated = bool(thread.get("isOutdated"))
        active_comments = [
            (candidate_reviewer, candidate)
            for candidate_reviewer, candidate in trusted_comments
            if head_oid and commit_oid(candidate) == head_oid
            and normalize(candidate.get("state")) == "submitted"
            and not resolved and not outdated and not bool(candidate.get("isMinimized"))
        ]
        active = bool(active_comments)
        latest = active_comments[-1][1] if active_comments else trusted_comments[-1][1]
        finding_id = str(thread.get("id") or latest.get("id") or latest.get("url") or "unknown")
        minimized = bool(latest.get("isMinimized"))
        current_head = bool(head_oid and commit_oid(latest) == head_oid)
        if active:
            completed_on_head.update(candidate_reviewer for candidate_reviewer, _ in active_comments)
        disposition = dispositions.get(finding_id)
        if disposition and disposition not in VALID_DISPOSITIONS:
            errors.append(f"invalid disposition for {finding_id}: {disposition}")
        thread_findings.append(
            {
                "id": finding_id,
                "reviewer": reviewer,
                "body": clip_text(latest.get("body"), max_body_chars) if active else "",
                "url": str(latest.get("url") or ""),
                "path": str(thread.get("path") or ""),
                "line": thread.get("line"),
                "resolved": resolved,
                "outdated": outdated,
                "minimized": minimized,
                "current_head": current_head,
                "active": active,
                "disposition": disposition,
            }
        )

    current_observed.update(thread_reviewers)
    expected = (set(policy.required) | current_observed | recent_observed) - policy.ignored
    current_observed -= policy.ignored
    requested -= policy.ignored

    check_pending: set[str] = set()
    check_failed: set[str] = set()
    check_complete: set[str] = set()
    # Issue #117 and #82: a rate-limited check is a known signal with
    # its own pending reason. It must not be folded into the generic
    # `check_failed` set, which would otherwise add a `trusted review
    # check failed without readable current-head findings` error and
    # route the gate to `incomplete` instead of `pending`. Scanned
    # across ALL built-in reviewers so the #48 breakpoint (vendor-
    # agnostic) can count rate-limit events against any reviewer
    # (Issue #82 acceptance criterion).
    rate_limited_reviewers: set[str] = {
        entry["reviewer"] for entry in kilo_rate_limit_reasons
    }
    for check in list_value(current.get("statusCheckRollup")):
        if not isinstance(check, dict):
            continue
        reviewer = reviewer_for_check(check, policy)
        if not reviewer or reviewer in policy.ignored:
            continue
        if is_rate_limited_check(check):
            rate_limited_reviewers.add(reviewer)
            continue
        # The Kilo summary helper handles every Kilo check it sees
        # (success → clear, rate-limited → distinct reason, non-
        # success → pending). A Kilo check that survives the helper
        # was either not a Kilo check at all (covered by the helper's
        # own scan) or was deliberately ignored (e.g. Kilo is in
        # `policy.ignored`). In either case the generic
        # `check_failed` path would add the same "trusted review
        # check failed without readable current-head findings" error
        # the helper exists to replace, so the check is consumed.
        if reviewer == "kilo" and (
            check.get("id") in kilo_consumed_check_ids
            or check.get("name") in kilo_consumed_check_ids
        ):
            continue
        status = normalize(check.get("status") or check.get("state"))
        conclusion = normalize(check.get("conclusion"))
        if status in {"queued", "pending", "in_progress", "requested", "waiting"}:
            check_pending.add(reviewer)
        elif conclusion in {"failure", "cancelled", "timed_out", "action_required", "startup_failure"} or status in {
            "failure",
            "error",
        }:
            check_failed.add(reviewer)
        elif conclusion in {"success", "neutral", "skipped"} or status in {"success", "completed"}:
            check_complete.add(reviewer)

    stale_reviewers: set[str] = set()
    blocking_reviewers: set[str] = set()
    head_review_verdicts: dict[str, str] = {}
    head_review_times: dict[str, str] = {}
    unorderable_verdicts: dict[str, set[str]] = {}
    stale_verdicts: dict[str, set[str]] = {}
    for review in iter_reviews(current):
        reviewer = reviewer_for_login(login_from(review), policy)
        if not reviewer or reviewer in policy.ignored:
            continue
        oid = commit_oid(review)
        # Only explicit submitted states establish completion or staleness. Missing,
        # unknown, draft, and dismissed states are not positive evidence.
        # They intentionally enter neither set, even at head; observation still
        # makes the reviewer expected and pending without claiming review work.
        submitted = normalize(review.get("state")) in {"approved", "changes_requested", "commented"}
        verdict = normalize(review.get("state"))
        if oid and head_oid and oid == head_oid and submitted:
            submitted_at = str(review.get("submittedAt") or "").strip()
            if not submitted_at:
                # A submitted review we cannot order is not positive evidence:
                # it can never be shown to be the reviewer's latest word. Fail
                # closed rather than reading a missing timestamp as a valid one.
                # It is not dropped either -- an unorderable rejection still
                # blocks below, and the reviewer stays pending with a reason.
                unorderable_verdicts.setdefault(reviewer, set()).add(verdict)
                continue
            previous_time = head_review_times.get(reviewer)
            if previous_time is None or submitted_at > previous_time or (submitted_at == previous_time and verdict == "changes_requested"):
                head_review_times[reviewer] = submitted_at
                head_review_verdicts[reviewer] = verdict
        elif oid and head_oid and oid != head_oid and submitted:
            stale_reviewers.add(reviewer)
            stale_verdicts.setdefault(reviewer, set()).add(verdict)
    for reviewer, verdict in head_review_verdicts.items():
        completed_on_head.add(reviewer)
        if verdict == "changes_requested":
            blocking_reviewers.add(reviewer)
    # An unorderable rejection is still a rejection we read, so it blocks. An
    # unorderable approval or comment establishes nothing and leaves the
    # reviewer pending.
    unorderable_reviewers = set(unorderable_verdicts)
    for reviewer, verdicts in unorderable_verdicts.items():
        if "changes_requested" in verdicts:
            blocking_reviewers.add(reviewer)
    stale_reviewers -= completed_on_head

    active_findings = [finding for finding in thread_findings if finding["active"]]
    blocking = [finding for finding in active_findings if finding["disposition"] == "blocking"]
    untriaged = [finding for finding in active_findings if not finding["disposition"]]
    readable_by_reviewer = {finding["reviewer"] for finding in active_findings}
    unreadable_failed_checks = sorted(check_failed - readable_by_reviewer)
    if unreadable_failed_checks:
        errors.append(
            "trusted review check failed without readable current-head findings: "
            + ", ".join(unreadable_failed_checks)
        )

    untriaged_reviewers = {finding["reviewer"] for finding in untriaged}
    pending_reviewers = (
        check_pending | requested | stale_reviewers | untriaged_reviewers
        | kilo_pending
        | (expected - completed_on_head)
    )
    check_only_reviewers = check_complete - completed_on_head
    pending_reasons: dict[str, list[str]] = {}
    # Issue #117 and #82: a rate-limited check is recorded with a
    # distinct reason so the rate-limit breakpoint (#48) and the
    # lead's retry loop can identify it without parsing the generic
    # "trusted review check failed" message. Scanned across all
    # reviewers (not just Kilo) so any built-in reviewer that hits a
    # rate-limit gets the same treatment.
    rate_limit_by_reviewer: dict[str, str] = {
        entry["reviewer"]: entry["reason"]
        for entry in kilo_rate_limit_reasons
    }
    for reviewer in rate_limited_reviewers:
        if reviewer in rate_limit_by_reviewer:
            continue
        rate_limit_by_reviewer[reviewer] = (
            f"{reviewer} review check failed with a rate-limit response; "
            "retry or take the rate-limit breakpoint"
        )
    for reviewer in sorted(pending_reviewers):
        reasons = []
        if reviewer in rate_limit_by_reviewer:
            reasons.append(rate_limit_by_reviewer[reviewer])
        if reviewer in check_only_reviewers:
            reasons.append(
                "status check succeeded or completed but no submitted review or review thread exists at head"
            )
        if reviewer in unorderable_reviewers:
            reasons.append(
                "submitted review at head has a missing or unreadable submittedAt "
                "timestamp, so it cannot be ordered and does not establish completion"
            )
        if reviewer in stale_reviewers:
            reasons.append(stale_review_reason(stale_verdicts.get(reviewer, set())))
        if reviewer in check_pending:
            reasons.append("reviewer status check is pending")
        if reviewer in requested:
            reasons.append("review request is outstanding")
        if reviewer in untriaged_reviewers:
            reasons.append("current-head findings need a disposition")
        pending_reasons[reviewer] = reasons or ["no review evidence at head"]

    # This is a structural signal only; PR comments do not prove review work
    # at head, and their wording does not establish why a reviewer is parked.
    parked_comments = []
    for comment in list_value(current.get("comments")):
        if not isinstance(comment, dict):
            continue
        reviewer = reviewer_for_login(login_from(comment), policy)
        if reviewer in check_only_reviewers:
            parked_comments.append({"reviewer": reviewer, "url": str(comment.get("url") or "")})

    known_logins = {
        normalize(identity)
        for identities in (*DEFAULT_IDENTITIES.values(), *policy.identities.values())
        for identity in identities
    }
    default_policy = ReviewerPolicy(
        identities=DEFAULT_IDENTITIES,
        check_markers=DEFAULT_CHECK_MARKERS,
        required=set(),
        ignored=set(),
    )
    unknown_bots: set[str] = set()
    for collection in (current.get("reviews"), current.get("latestReviews"), current.get("comments")):
        for item in list_value(collection):
            login = login_from(item)
            if login and login not in known_logins and looks_like_bot_login(login):
                unknown_bots.add(login)
    for check in list_value(current.get("statusCheckRollup")):
        if (
            not isinstance(check, dict)
            or reviewer_for_check(check, policy)
            or reviewer_for_check(check, default_policy)
        ):
            continue
        identity = unknown_review_app_identity(check)
        if identity:
            unknown_bots.add(identity)

    # A known rejection outranks errors: an unreadable check must not soften a
    # verdict we already read. Errors still surface in "errors" either way.
    if blocking_reviewers:
        state = "blocking"
    elif errors:
        state = "incomplete"
    elif blocking:
        state = "blocking"
    elif not expected:
        state = "not_applicable"
    elif pending_reviewers or untriaged:
        state = "pending"
    else:
        state = "clear"

    return {
        "state": state,
        "pr_number": current.get("number"),
        "head_oid": head_oid,
        "expected_reviewers": sorted(expected),
        "observed_reviewers": sorted(current_observed),
        "recently_observed_reviewers": sorted(recent_observed),
        "requested_reviewers": sorted(requested),
        "completed_on_head": sorted(completed_on_head),
        "pending_reviewers": sorted(pending_reviewers),
        "check_only_reviewers": sorted(check_only_reviewers),
        "pending_reasons": pending_reasons,
        "parked_comments": parked_comments,
        "stale_reviewers": sorted(stale_reviewers),
        "findings": thread_findings,
        "blocking_findings": blocking,
        "blocking_reviewers": sorted(blocking_reviewers),
        "blocking_review_reasons": {reviewer: "latest submitted review at head requested changes" for reviewer in sorted(blocking_reviewers)},
        "untriaged_findings": untriaged,
        "unknown_bot_identities": sorted(unknown_bots),
        "errors": errors,
    }


def load_dispositions(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InspectionError(f"cannot read dispositions {path}: {exc}") from exc
    valid_mapping = isinstance(value, dict) and all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    )
    if not valid_mapping:
        raise InspectionError("dispositions must be a JSON object mapping finding IDs to strings")
    return {key: normalize(item) for key, item in value.items()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", type=Path, help="read deterministic GitHub-shaped fixture data")
    source.add_argument("--repo", help="GitHub repository in OWNER/REPO form")
    parser.add_argument("--pr", type=int, help="pull request number (required with --repo)")
    parser.add_argument("--recent-pr-limit", type=int, default=5)
    parser.add_argument("--max-body-chars", type=int, default=2000)
    parser.add_argument(
        "--trusted-reviewer",
        action="append",
        default=[],
        help="restrict trust to the repeated canonical reviewer names; defaults to all built-ins",
    )
    parser.add_argument("--required-reviewer", action="append", default=[])
    parser.add_argument("--ignored-reviewer", action="append", default=[])
    parser.add_argument("--identity", action="append", default=[], metavar="REVIEWER=LOGIN[,LOGIN]")
    parser.add_argument("--dispositions", type=Path)
    parser.add_argument("--payload-snapshot", type=Path, help="save verbatim current-PR JSON to a new file (live mode)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.repo and not args.pr:
        print("ERROR: --pr is required with --repo", file=sys.stderr)
        return 2
    if args.fixture and args.payload_snapshot:
        print("ERROR: --payload-snapshot requires live --repo mode", file=sys.stderr)
        return 2
    if args.recent_pr_limit < 0 or args.recent_pr_limit > 20:
        print("ERROR: --recent-pr-limit must be between 0 and 20", file=sys.stderr)
        return 2
    if args.max_body_chars < 200 or args.max_body_chars > 20000:
        print("ERROR: --max-body-chars must be between 200 and 20000", file=sys.stderr)
        return 2

    identities = {reviewer: set(values) for reviewer, values in DEFAULT_IDENTITIES.items()}
    check_markers = {reviewer: set(values) for reviewer, values in DEFAULT_CHECK_MARKERS.items()}
    try:
        for spec in args.identity:
            parse_identity(spec, identities, check_markers)
        trusted = {normalize(value) for value in args.trusted_reviewer}
        if trusted:
            unknown = trusted - identities.keys()
            if unknown:
                raise InspectionError("trusted reviewer has no identity mapping: " + ", ".join(sorted(unknown)))
            identities = {reviewer: values for reviewer, values in identities.items() if reviewer in trusted}
            check_markers = {
                reviewer: values for reviewer, values in check_markers.items() if reviewer in trusted
            }
        required = {normalize(value) for value in args.required_reviewer}
        untrusted_required = required - identities.keys()
        if untrusted_required:
            raise InspectionError(
                "required reviewer is not trusted or has no identity mapping: "
                + ", ".join(sorted(untrusted_required))
            )
        policy = ReviewerPolicy(
            identities=identities,
            check_markers=check_markers,
            required=required,
            ignored={normalize(value) for value in args.ignored_reviewer},
        )
        dispositions = load_dispositions(args.dispositions)
        if args.fixture:
            current, threads, recent = load_fixture(args.fixture)
        else:
            current = fetch_pr(args.repo, args.pr, args.payload_snapshot)
            # `gh pr view --json statusCheckRollup` does not expose
            # `output` or the run id, so the rate-limit phrase on a
            # failed Kilo check would otherwise be unreachable on
            # live data. Augment checks with the head SHA's
            # REST-fetched output when the rollup is silent.
            augment_checks_with_output(current, args.repo)
            threads = fetch_threads(args.repo, args.pr)
            recent = fetch_recent(args.repo, args.pr, args.recent_pr_limit)
        result = inspect(
            current,
            threads,
            recent,
            policy,
            dispositions,
            max_body_chars=args.max_body_chars,
        )
    except (InspectionError, argparse.ArgumentTypeError) as exc:
        result = {
            "state": "incomplete",
            "errors": [str(exc)],
        }
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 2 if result["state"] == "incomplete" else 0


if __name__ == "__main__":
    raise SystemExit(main())
