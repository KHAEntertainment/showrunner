#!/usr/bin/env python3
"""Validate the distributable /dev Claude Code Skill."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REQUIRED = {
    "SKILL.md",
    "backends/contract.md",
    "backends/claude-native.md",
    "backends/traycer.md",
    "phases/phase1.md",
    "phases/phase1-prototyping.md",
    "phases/phase2.md",
    "phases/phase3.md",
    "phases/phase3.5.md",
    "phases/external-review.md",
    "phases/phase4.md",
    "phases/phase5.md",
    "phases/repository-context.md",
    "reply-contract.md",
    "agents/report-back.md",
    "agents/worker-new.md",
    "agents/worker-fix.md",
    "agents/qa-agent.md",
    "agents/reviewer.md",
    "agents/worker-prototype-frontend.md",
    "agents/worker-prototype-backend.md",
    "templates/PROJECT_CONTEXT_TEMPLATE.md",
    "templates/DEV_STATE_TEMPLATE.md",
    "scripts/detect_execution_backend.py",
    "scripts/traycer_cli.py",
    "scripts/inspect_external_reviews.py",
    "scripts/dev_config.py",
    "scripts/resolve_repository.py",
    "graft.md",
}


# Issue #97: swap-time report-back evidence. Pinned per file, as the rest of the
# report-back enforcement is: `contract.md` states the backend-neutral
# constraints, `traycer.md` the rule itself, `report-back.md` the first-line
# response ID the rule depends on, and the ledger template the fields that let
# a new lead detect a swap. Each token is one the rule loses its fail-closed
# shape without: dropping "never upgrades a truncated read" would let a cut
# read become a verdict, and dropping the sender or dispatch-time condition
# would let any message that quotes the id satisfy correlation.
SWAP_EVIDENCE_PINS = {
    "backends/traycer.md": (
        "**Swap-time evidence (after a lead change only).**",
        "It adds no row, termination value, or cause to the mapping",
        "A worker entry with no `dispatched_by` fails this condition",
        "the swap rule never upgrades a truncated read",
        "never the title and never an id mentioned in the body",
        "was sent after the recorded `dispatched_at`",
        "verbatim and in full; a prefix, a different id, or a paraphrase does not match",
        "because a cut read cannot establish absence",
        "Different means a **lead swap**, not an identity failure",
        "a swap never relaxes any Preflight step 3 check",
    ),
    "backends/contract.md": (
        "**Swap-time evidence is adapter-defined, narrow, and fails closed.**",
        "It never upgrades a read that ended `stalled`, `page_cap`, or `time_bound`",
        "and anything less stays `absent`",
        "It adds no row, termination value, or cause to the mapping",
    ),
    "agents/report-back.md": (
        "on the **first line**",
        "(for example `Response ID: <id>`), above the seven sections.",
        "A missing or mismatched correlation ID fails the lane closed.",
        "and a missing or mismatched ID still fails the lane closed",
    ),
    "templates/DEV_STATE_TEMPLATE.md": (
        "`communication_response_id`, `dispatched_by`, `dispatched_at`, `report_back`",
        "`dispatched_by` and `dispatched_at` are additive under `schema_version: 2`",
        "**The swap-time evidence rule adds no row.**",
    ),
}


# The Execution Routing Policy section defers to the agent selection guide and
# exists to stay empty of routes. It is pinned structurally: the section must
# contain its approved content and nothing else, so any added line fails
# whatever words it uses.
#
# It is deliberately NOT a denylist of harness or model names. A denylist can
# only reject the names someone thought of — `traycer`, `cursor`, or a route
# phrased with no harness name at all ("all lanes use the lead route") walk
# straight through one. Enumeration over prose is unbounded, and this section
# is small and fixed, so the whole body is the guard.
#
# Whitespace is normalised before comparing, so reflowing or rewrapping the
# section is not a failure. Editing its wording IS a failure until this constant
# is updated in the same commit — that is the point: the section cannot change
# without the change being deliberate and reviewed.
ROUTING_HEADING = "## Execution Routing Policy"
ROUTING_SECTION_BODY = (
    "The agent selection guide governs role routing. This file records only "
    "project-specific exceptions, and there are none. Do not restate the "
    "guide's model or harness choices here, even to agree with them: a route "
    "recorded in this section outranks the guide in the adapter's resolution "
    "order, so anything written here silently overrides newer policy, and a "
    "copy made today becomes a stale override the moment the guide changes. "
    "That is why this section stays empty. One constraint does belong here, "
    "because it is a property of this project rather than a routing "
    "preference: **the lead runs on the harness that invokes `/dev`: Claude "
    "Code on either backend, or Codex or OpenCode under the Traycer backend "
    "only (ADR-013).** Worker, QA, and reviewer assignments are "
    "provider-neutral and may run on whichever harness and model the "
    "selection guide selects for them."
)


# Machine-specific absolute home-directory paths, matched by pattern rather
# than a literal username. A literal (the maintainer's own name) is itself a
# machine-specific leak once stored in this file, so the guard must not carry
# one. The name class includes spaces and apostrophes because real account
# names do ("Jane Doe", "O'Connor"), on top of the usual word characters,
# dots, and hyphens.
#
# Boundaries. Left: the mac and linux patterns need a literal leading `/` that
# is not preceded by a word character or dot, so `file:///Users/x` and
# `//Users/x` are caught while a mid-URL `https://host/Users/svc/status`
# (`/Users` follows `t`) and unrooted prose like `Users/alice/` or `home/ docs/`
# are not. The Windows pattern has no left boundary: a `C:\Users\` literal is
# never a URL segment, so `xC:\Users\bob\` is still caught as it always was.
# Right: the name must start with a word character (so `the /Users/ folder`
# is not a path) and be followed by a separator, whitespace, a quote, backtick,
# closing bracket, punctuation, or end of text, so a bare `/Users/name` at end
# of line, in backticks, or before a full stop is caught too. Template
# placeholders stay excluded: `<name>` cannot match the name class,
# `C:\path\to\...` never reaches the `C:\Users\` pattern, and `$HOME` is not
# a literal path.
_NAME = r"\w[\w.' -]*"
_RIGHT = r"""(?=[/\\\s"'`)\]}>.,;:!?]|\Z)"""
HOME_PATH_PATTERNS = (
    (re.compile(rf"(?<![\w.])/Users/{_NAME}{_RIGHT}"), "macOS home directory"),
    (re.compile(rf"(?<![\w.])/home/{_NAME}{_RIGHT}"), "Linux home directory"),
    (re.compile(rf"C:\\Users\\{_NAME}{_RIGHT}"), "Windows home directory"),
)

# Directories outside the Skill payload that still ship in the repository and
# so still leak a machine-specific path if one is left in them: `en/` and
# `zh/` are legacy/translated command mirrors and `docs/` holds the reference
# docs, none of them part of the distributable Skill under `skills/dev/`. All
# are `.gitattributes export-ignore`d, so the release-archive CI run extracts
# a tree without them -- tolerate that rather than failing closed on a
# directory that legitimately does not ship there.
EXTRA_MARKDOWN_DIRS = ("en", "zh", "docs")


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def normalize(text: str) -> str:
    """Collapse whitespace, so reflowing prose is not a policy change."""
    return " ".join(text.split())


def routing_section(text: str) -> str | None:
    """Return the Execution Routing Policy section body, or None if absent."""
    match = re.search(
        rf"^{re.escape(ROUTING_HEADING)}$(.*?)(?=^## |\Z)", text, re.M | re.S
    )
    return match.group(1) if match else None


# Issue #69: wording that must live inside external-review.md's Result Routing
# section itself (checked section-scoped in main), not merely anywhere in the file.
RESULT_ROUTING_PINS = (
    "whose only open seats are filled by a completed, current-head substitution routes as `clear`, provided no finding, the substitute's included, is blocking or awaiting disposition",
    "a substitute at an older head does not count",
    "A completed, current-head substitute review with a blocking finding routes as `blocking`, not as any other `pending`.",
)


def markdown_section(text: str, heading: str) -> str | None:
    """Return a top-level (`## …`) section body by exact heading, or None if absent.

    Used by per-section policy checks where a token must appear in a named
    structural location (Session State Anchor, Global Rules), not merely
    somewhere in the file. `routing_section` is the original use; this helper
    generalises the same regex for any heading.
    """
    match = re.search(
        rf"^{re.escape(heading)}$(.*?)(?=^## |\Z)", text, re.M | re.S
    )
    return match.group(1) if match else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skill-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "skills" / "dev",
    )
    args = parser.parse_args()
    skill_dir = args.skill_dir.resolve()
    errors: list[str] = []

    # Anchored on this script's own location, not `--skill-dir`: every call
    # site stages the Skill elsewhere but always runs this validator from the
    # project or archive root, where `en/`, `zh/`, `docs/`, and the root-level
    # markdown ship (when they ship at all -- see EXTRA_MARKDOWN_DIRS above).
    repo_root = Path(__file__).resolve().parents[1]

    for relative in sorted(REQUIRED):
        if not (skill_dir / relative).is_file():
            fail(errors, f"missing required file: {relative}")

    entry = skill_dir / "SKILL.md"
    if entry.is_file():
        text = entry.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            fail(errors, "SKILL.md must begin with YAML frontmatter")
        for field in (
            "name: dev",
            "version:",
            "description:",
            "argument-hint:",
            "when_to_use:",
        ):
            if field not in text:
                fail(errors, f"SKILL.md frontmatter missing: {field}")

        # The Skill must stay model-invocable so an explicit user request made
        # during planning survives into implementation. Require the explicit
        # `false` rather than an omitted field, so a regression is visible in
        # the diff instead of hiding in a default.
        frontmatter = text.split("\n---\n", 1)[0] if text.startswith("---\n") else ""
        if "disable-model-invocation: false" not in frontmatter:
            fail(
                errors,
                "SKILL.md must set `disable-model-invocation: false` explicitly; "
                "model invocation is required for the plan-to-implementation handoff",
            )
        when_to_use = ""
        for line in frontmatter.splitlines():
            if line.startswith("when_to_use:"):
                when_to_use = line.partition(":")[2].strip().strip('"').strip("'")
                break
        for phrase in ("explicitly", "after plan approval", "Do not invoke"):
            if phrase not in when_to_use:
                fail(
                    errors,
                    f"SKILL.md `when_to_use` must keep the explicit-intent trigger: {phrase}",
                )

    def scan_home_paths(path: Path, label: str) -> None:
        content = path.read_text(encoding="utf-8")
        for pattern, description in HOME_PATH_PATTERNS:
            match = pattern.search(content)
            if match:
                fail(
                    errors,
                    f"{label} contains a machine-specific absolute path "
                    f"({description}): {match.group(0)}",
                )

    combined_parts: list[str] = []
    for markdown in sorted(skill_dir.rglob("*.md")):
        content = markdown.read_text(encoding="utf-8")
        combined_parts.append(content)
        if re.search(r"[\u3400-\u9fff]", content):
            fail(errors, f"{markdown.relative_to(skill_dir)} contains Chinese text")
        for ref in re.findall(r"\$\{CLAUDE_SKILL_DIR\}/([^`\s)'\"]+)", content):
            if not (skill_dir / ref).is_file():
                fail(errors, f"{markdown.relative_to(skill_dir)} references missing file: {ref}")
        scan_home_paths(markdown, str(markdown.relative_to(skill_dir)))

    combined = "\n".join(combined_parts)
    forbidden = {
        "~/.claude/commands/dev": "legacy command path",
        "TeamCreate": "obsolete Agent Teams setup tool",
        "TeamDelete": "obsolete Agent Teams cleanup tool",
    }
    for token, description in forbidden.items():
        if token in combined:
            fail(errors, f"found {description}: {token}")

    # The home-path guard also covers markdown that ships in the repository
    # outside the Skill payload -- `en/` and `zh/` are legacy/translated
    # command mirrors, `docs/` holds the reference docs, and root-level
    # markdown ships too. A leak there is exactly
    # as public as one inside `skills/dev/`, and the other forbidden tokens
    # above legitimately appear in these mirrors (e.g. documenting the legacy
    # `~/.claude/commands/dev` path itself), so only the home-path check
    # widens; the rest of `forbidden` stays scoped to the payload.
    #
    # Only when `--skill-dir` resolves inside `repo_root`, though: that is
    # what tells apart validating this source tree from validating a staged,
    # archived, or otherwise external tree. `install.sh`'s git-staging mode
    # runs the SOURCE checkout's validator (so `repo_root` is the source
    # repository) against a STAGED copy of the payload elsewhere (a preflight
    # checkout, a git-archive extraction, or the final stage directory) --
    # none of which is `repo_root` or under it. Scanning the source's own
    # `en/`, `zh/`, or root markdown in that case would fail an install over
    # content that was never staged and never ships as part of it. The
    # release-archive CI run stays covered: it runs the ARCHIVE's own
    # validator against the ARCHIVE's own `skills/dev`, so `--skill-dir` is
    # under that same `repo_root`.
    try:
        skill_dir.relative_to(repo_root)
        validating_source_tree = True
    except ValueError:
        validating_source_tree = False

    if validating_source_tree:
        for extra_name in EXTRA_MARKDOWN_DIRS:
            extra_dir = repo_root / extra_name
            if not extra_dir.is_dir():
                continue
            for markdown in sorted(extra_dir.rglob("*.md")):
                scan_home_paths(markdown, str(markdown.relative_to(repo_root)))
        for markdown in sorted(repo_root.glob("*.md")):
            scan_home_paths(markdown, str(markdown.relative_to(repo_root)))

    required_policy = (
        "Never write or modify implementation or test code directly",
        ".agent/dev-state.md",
        "pre-created, verified branch/worktree",
        "RTK",
        "coderabbit",
        "kilo",
        "github-copilot",
        "copilot-pull-request-reviewer[bot]",
        "headRefOid",
        "Default wait minutes",
        "Allow automatic review requests",
        "--trusted-reviewer",
        "false_positive",
        "review evidence alone never establishes satisfaction",
        "incomplete",
        "TRAYCER_AGENT_ID",
        "TRAYCER_EPIC_ID",
        "claude-native",
        "rtk proxy traycer",
        # Issue #89: every Traycer CLI step goes through the wrapper, which is
        # what supplies a session identity the harness did not export. A bare
        # `traycer` call loses that identity, so the route and its prohibition
        # are pinned together. `rtk proxy traycer` stays pinned because
        # `test_no_baseline_policy_token_is_ever_removed` forbids dropping a
        # baseline token; the payload now carries it as the forbidden form.
        "rtk proxy python3 ${CLAUDE_SKILL_DIR}/scripts/traycer_cli.py",
        "Never invoke `traycer` directly",
        "backend_source: supplied",
        ".agent/traycer.env",
        "never inferred",
        "identity_verification",
        "are not evidence of the caller's identity",
        "--surface gui",
        "--expect-reply",
        "--workspace-entry",
        "--carry-uncommitted",
        "traycer_last_used",
        "schema_version",
        "communication_response_id",
        "head changed",
        "distinct agent ID",
        "lead is the sole ledger writer",
        "A trusted reviewer's status check alone never satisfies this gate.",
        # Reuse-first ladder and its safety carve-out. The carve-out is pinned
        # as a full sentence: a ladder that survives without it reads as
        # licence to delete guards in the name of minimality.
        "Reuse-first ladder",
        "lowest rung",
        "Minimizing scope must never mean removing a guard.",
        "speculative abstraction",
        # Completion-evidence discipline. `qa-agent.md` holds the canonical
        # definition of "verified"; `report-back.md` cross-references it.
        "Tool Capability Boundary",
        "executed command's actual output",
        "re-run the full Verification Gate",
        # QA scoring: absence of signal must not read as a positive result.
        # Each token pins one path by which a lane that measured nothing could
        # otherwise return a passing number.
        "qa_error: no acceptance criteria",
        "qa_error: no verification executed",
        "No test framework detected",
        "not verified by test execution",
        "Limitations are load-bearing",
        # The coverage term swings 10 points per criterion, so the predicate
        # deciding it must stay decidable. Without these two the term degrades
        # into a self-assessed judgment and two lanes scoring the same PR can
        # legitimately reach different numbers.
        "Test-executable is a decidable predicate",
        "without new infrastructure",
        # A failed criterion already lowers the ratio; deducting coverage on
        # top of it counts the same fact twice and fails legitimate work for
        # arithmetic reasons. Found by the formula's first real use.
        "The coverage term applies only to criteria that passed.",
        # The prototype lanes' opposing principle. Pinned positively: a guard
        # that only asserts a ladder is absent cannot be told apart from a
        # vacuous one, and no token list can enumerate every paraphrase. With
        # this pinned, adding reuse-first guidance to a prototype prompt means
        # first deleting a sentence that says the opposite.
        "Exploration favors breadth over minimality.",
        # QA must execute the whole gate, not read it. Without this the lane
        # could run the test suite, never run lint or type checks, and pass
        # with nothing recording that they had not run.
        "Execute the full Verification Gate.",
        "Reading the gate is not running it.",
        # A convenience entry point that omits a recorded command reports
        # success over something that never ran - the same defect one layer up.
        "may be used only when it is known to run every recorded command",
        # Report-back enforcement at the adapter layer. The same defect class
        # one transport down: a lane that never replied is not a lane that had
        # nothing to say. Each token pins one way the enforcement could be
        # softened back into prompt-level etiquette.
        "Absence of a report is not a report.",
        "the same verdict, not a lesser case",
        "report_back: incomplete",
        # Without this, seven empty headings satisfy a presence check.
        "A heading with no content under it is a missing section",
        # The role-specific close-outs are the obvious escape hatch: a QA lane
        # posting its PR comment and replying nothing must not read as reported.
        "never substitute for the seven required sections",
        # The empty-heading rule closed one hole and opened a smaller one: what
        # counts as content was itself a judgment, so two leads could reach
        # different verdicts on the same reply. This is the mechanical floor.
        "at least one line containing a non-whitespace character",
        # "Read until the transport declares completion" is unbounded, so the
        # `truncated` cause was unreachable in the exact state it exists for.
        "Paging must be bounded",
        # Termination decides whether section inspection is permitted;
        # completed reads still need correlation and section evidence.
        "Termination decides whether section inspection is permitted",
        # The cause taxonomy was right and ran too late: an empty read reached
        # the shape branch as `malformed`, or stalled as `truncated`, when what
        # happened was that nothing arrived. Precedence is part of the
        # taxonomy - two adapters deriving it independently is how they drift.
        "An empty read is never evidence of a reply's shape.",
        # The other half of that sentence used to say "or of its transport",
        # which the termination field falsified: the condition that ended an
        # empty read is exactly transport evidence, and is why it is recorded.
        "What an empty read *is* evidence of is its own transport",
        # Three adapters instructed recording a verdict and cause into a ledger
        # with no field for either, so every lead would have invented a shape.
        # The cause is the half that selects the remedy; a verdict without one
        # records that something failed and discards what to do about it.
        "A `report_back: incomplete` with a null cause is an invalid record.",
        # And the clean lane records too, or "reported and verified" and "never
        # checked" are the same absence - this contract's own failure mode.
        "A lane is never `complete` by never having been looked at.",
        # The cause is lossy on purpose - three conditions collapse to
        # `truncated` - so the condition itself is kept for diagnosis. The
        # verdict and cause use the full mapping of observed inputs.
        "report_back_termination",
        "derive the verdict and cause from the full mapping",
        # The ledger recorded `report_back_termination: null` for an absent
        # lane on the reasoning that no read had run - while `contract.md` said
        # nothing can be known to be absent without looking. Two documents, one
        # head, contradicting each other on the one row the drift guard did not
        # cover. Absence is a result of reading, and a cut read establishes none.
        "Absence is established by reading, not instead of reading",
        "has not established absence",
        # Issue #54: the lead-to-user reply contract. Pinned verbatim so the
        # cap, its scope over prose only, and the third-party-agnostic
        # composition note cannot be paraphrased away from the approved plan.
        "aim under 100 words",
        "The cap counts prose, not required structured artifacts.",
        "never claims a task-requirements override",
        # Issue #57: Graft adapter pinned optional evidence. Pinned verbatim so the
        # evidence-or-recorded-unavailability gate, the graft init ban, the approved
        # queries list, the degraded-path requirement, and the ledger fields cannot
        # be paraphrased away from the approved plan.
        "Never an execution backend.",
        "never `graft init` in managed projects",
        "graph_evidence: unavailable",
    )
    for token in required_policy:
        if token not in combined:
            fail(errors, f"missing required custom policy: {token}")

    # `required_policy` is matched against every Skill markdown file
    # concatenated, so a token surviving in one file satisfies it for all.
    # That is too weak wherever the invariant is "each of these files carries
    # this in its own right": deleting the sentence from one lane still passes
    # while a sibling lane holds it up. The doc-assertion tests check per file,
    # but `.gitattributes` export-ignores `tests`, so CI's archive validation
    # runs this script without them and the validator is the only guard there.
    per_file_policy = {
        "agents/worker-new.md": (
            "Reuse-first ladder",
            "Minimizing scope must never mean removing a guard.",
            "${CLAUDE_SKILL_DIR}/graft.md",
            "rtk proxy graft callers",
            "rtk proxy graft grep",
            "graph_evidence: unavailable",
            "trace callers manually",
            "search manually with `rg`",
            # Issue #34: challenging the assignment extends the ladder's
            # posture to the envelope itself. Same token in every lane prompt
            # so one file dropping it cannot hide behind a sibling holding it.
            "Challenging the specification is in scope",
            "specification defect found before implementation beats a faithful implementation of a flawed spec",
        ),
        "agents/worker-fix.md": (
            "Reuse-first ladder",
            "Minimizing scope must never mean removing a guard.",
            "${CLAUDE_SKILL_DIR}/graft.md",
            "rtk proxy graft grep",
            "graph_evidence: unavailable",
            "search manually with `rg`",
            "Challenging the specification is in scope",
            "specification defect found before implementation beats a faithful implementation of a flawed spec",
        ),
        "agents/worker-prototype-frontend.md": (
            "Exploration favors breadth over minimality.",
        ),
        "agents/worker-prototype-backend.md": (
            "Exploration favors breadth over minimality.",
        ),
        # Report-back enforcement is per-file by nature: `contract.md` is
        # backend-neutral, so both adapters must carry it in their own right.
        # A combined match would let one adapter hold it up for the other.
        "backends/contract.md": (
            "Absence of a report is not a report.",
            "report_back: incomplete",
            "never substitute for the seven required sections",
            "at least one line containing a non-whitespace character",
            "Paging must be bounded",
            "Termination decides whether section inspection is permitted",
            "An empty read is never evidence of a reply's shape.",
            "no correlated reply after `completed` is `absent`",
            "A verified report is recorded too, not only a failed one.",
            "Record the terminating condition, and derive the verdict and cause from the full mapping.",
            "still ran a bounded read",
            # Issue #58: Child-harness capability checklist. Pinned per file so
            # deleting any of these from `contract.md` fails the validator
            # rather than the doc-assertion tests alone (`tests/` is
            # export-ignored; archive extractions have no test layer).
            "## Child-harness capability checklist",
            "receive-capable GUI surface",
            "Tooling on PATH",
            "Shared-filesystem read of resolved Skill files",
            "Replies in seven-section shape on arrival surface",
            "remedy is a different route, never a trimmed prompt",
            # Issue #38: ADR-009 lint reclassification recorded here so the
            # delegated lanes read it at the point of use. Must not name the
            # rejected credential layer from ADR-008 as a control.
            "an authorship lint, not a security control",
            "behavioural tests and the supported pre-write verification are the real controls",
            # Issue #89: a lead that is not Claude Code has no native path, and
            # its harness is read from Traycer rather than assumed.
            "A lead whose harness is not Claude Code selects `traycer` or records `incomplete` and stops.",
            "`claude-native` is never available to it",
            "`lead.harness` is recorded from the Traycer agent list, never inferred.",
            "backend_source: supplied",
            "Sources are never mixed",
            "Never invoke `traycer` directly, and never through a bare `rtk proxy traycer`.",
            "with neither environment identifier present",
            "A partial environment (exactly one identifier) is a host defect",
            "the file never recovers it",
            # Issue #34: the open-questions element in the envelope list, plus
            # the two clauses that keep it honest — never mandatory (a
            # manufactured question trains the lane to skim), and the
            # expectation it puts on the receiving lane. Scoped to this file so
            # the list itself cannot lose the element while the clause below
            # survives elsewhere.
            "acceptance criteria, the lead's open questions, plan-approval requirement",
            "not a required field",
            "must not manufacture uncertainty",
            "specification defect found before implementation beats a faithful implementation of a flawed spec",
        ),
        # The ledger is the other half of Issue #3's "recorded in
        # .agent/dev-state.md": a contract pointing at a field that does not
        # exist is not a recorded verdict.
        "templates/DEV_STATE_TEMPLATE.md": (
            "report_back_cause",
            "A `report_back: incomplete` with a null cause is an invalid record.",
            "A lane is never `complete` by never having been looked at.",
            "report_back_termination",
            "termination, reply correlation, and section presence",
            "Every bounded read records how it ended",
            # Issue #89: the ledger must be able to say which source the
            # identity came from.
            "`supplied` (the detector chose `traycer` from identifiers in `.agent/traycer.env`)",
            "identity_verification",
            "`self_source_and_worktree_match`",
            "additive under `schema_version: 2`",
            # Issue #33: a bypass recorded against a PR number alone lets the
            # same debt be re-hidden behind a later, partially-reviewed head.
            "the exact unreviewed commit range",
            "<reviewed-head>..<merged-head>",
            # Reviewer-converged fix (CodeRabbit + internal review): when no
            # review ever completed on the PR there is no reviewed head, so
            # the range degenerates to empty unless the base-head form is
            # pinned as the other required case.
            "<base-head>..<merged-head>",
            # Issue #26: the ledger field that actually records whether a
            # closed Issue's acceptance criteria were checked against merged
            # code, and the sentence that forecloses auto-closure as a
            # substitute for checking.
            "Post-merge verification record schema",
            "merge_sha",
            "gate_result",
            "criteria_verdict",
            "Auto-closure by a merge keyword is never evidence of completion",
            # Issue #48: the ledger half of the rate-limit breakpoint — the
            # count, the no-family home, the substitution record, the families
            # that keep distinctness re-checkable, and that it is not bypass
            # debt. Fields are pinned one by one, never by list adjacency.
            "`consecutive_rate_limits`",
            "`external_reviewer_unavailable`",
            "`external_review_substitutions`",
            "external_reviewer_unavailable: rate_limited",
            "only a completed review or an explicit non-rate-limit decline from that reviewer resets it to 0",
            "it is the ledger record of the still-`pending` gate",
            "the model families of the substitute, the implementation worker, the QA lane, and the internal reviewer",
            "A substitution is a completed review, not an `approved_bypasses` or `review_debt` entry.",
        ),
        # Issue #33: the gate's own bypass path had become the routine path
        # because a review invalidated by the author's own fix-commit push
        # read as "unavailable". These tokens pin the scope narrowing and the
        # commit-range requirement in the file that states the policy itself.
        "phases/external-review.md": (
            # Issue #82: the ask-once contract. The contract is the
            # single piece of SOP prose that keeps the unknown-bot
            # surface from becoming a re-ask every PR, and it has
            # three discrete outcomes whose wording names the
            # recording site. Each token below is a single
            # per-outcome load-bearing sentence: deleting the
            # trust → ... line, or the ignore → ... line, or the
            # decide later → ... line, fails the validator closed
            # rather than degrading silently. The pair
            # (`Pending reviewer decisions`, "not re-asked") is the
            # no-re-ask rule the contract needs to function; the
            # `once per repository` sentence is the rule's scope.
            "Ask once about unknown review bots, record the answer",
            "asks the user **once per repository**",
            "trust → `Additional reviewer identities`",
            "ignore → `Ignored reviewers`",
            "decide later → a `Pending reviewer decisions` line",
            "A login already listed under `Pending reviewer decisions` is **not re-asked**",
            "The lead never adds an identity without the user's answer",
            "never for a review that arrived and was invalidated by the author's own response",
            "obligates a re-request at the new head, not a bypass",
            "the exact unreviewed commit range",
            "<base-head>..<merged-head>",
            # Issue #48: the rate-limited retry loop's only automatic exit was
            # the deadline choices. These pin the threshold, the per-reviewer
            # count and what resets it, the backend-neutral fallback chain,
            # the family-distinct substitute (never the internal reviewer's
            # seat), the seat and required-check limits, and the new-head
            # path. The Result Routing clause that lets a completed
            # substitution reach `clear` (without it the substitute cannot
            # reach APPROVE) is pinned in its own section below.
            "After 3 consecutive rate-limited responses to review requests on the same PR",
            "send that reviewer no further retries",
            "external_reviewer_unavailable: rate_limited",
            "The count is kept per PR per reviewer, across heads and wait episodes",
            "Only a completed review or an explicit non-rate-limit decline from that reviewer resets the count",
            "an acknowledgement or a processing or in-progress reply neither resets nor increments it",
            # An in-place edit reporting a new event is a new response;
            # counting it once would freeze a single-comment reviewer at 1.
            "An in-place edit that reports a new rate-limit event counts as a new rate-limited response",
            "a reviewer that reports each rate limit by editing a single summary comment still reaches the threshold",
            "a new event is a new head, a new limit window or reset time, or a response to a new review request (a retry, or the re-request the Head-Commit Invariant obligates)",
            "Only a re-render of the same event (same head, same window, no new request) does not count again.",
            # Issue #69: whether an unrequested rate-limit at a new head counts.
            "An automatic rate-limit report at a new head, with no explicit request from the lead, counts once toward the threshold",
            "so a rate-limited response to it counts as well",
            "The breakpoint is an exit from the retry loop, not a bypass",
            "The review fallback chain is the ordered set of available reviewer routes the lead can dispatch on the selected backend",
            "on Traycer, the agent selection guide's review routes",
            "on Claude-native, any distinct-family reviewer the lead can actually dispatch",
            # Issue #69: the fresh-identity requirement was unpinned; a
            # substitute that reuses an existing seat adds no diversity.
            "The substitute is a fresh identity whose model family differs from the implementation worker, the QA lane, and the internal reviewer",
            "never reuses the internal reviewer's seat",
            "never falls back to the bypass or to a same-family reviewer",
            "the lead never bypasses unilaterally",
            "deadline choice 2 (an explicit re-request) and choice 3 (a user-approved bypass) remain available",
            "apply the Head-Commit Invariant to it as to any review",
            "satisfies the external gate as a review, not a bypass",
            "creates no review debt",
            "It fills only the rate-limited reviewer's seat",
            "every other expected reviewer still gates",
            "still dispatch the substitute as review evidence; it does not fill that seat",
            "the breakpoint does not unblock merge",
            "this SOP never overrides GitHub branch protection",
            "the substitution record, not the inspector, fills its seat",
            "so distinctness stays re-checkable",
            "reconcile its findings normally",
            "the substitution record stands",
            "The count carries across heads for the same PR and reviewer.",
            "that re-request is not a retry",
            "After a breakpoint has fired on that PR for that reviewer, the count is already at or above the threshold",
            "dispatches a fresh substitute for the new head without a second retry cycle",
            # The Result Routing clause itself is pinned by a section-scoped
            # check (RESULT_ROUTING_PINS below): the "no finding, the
            # substitute's included, is blocking or awaiting disposition"
            # wording also appears in the Rate-limit breakpoint section, so
            # whole-file matching could not tell if the routing line were
            # deleted.
            #
            # Issue #82 / round-3 coverage pins (QA M6): the four new
            # Known-identities bullets in the Default Policy. Each
            # bullet is one load-bearing per-reviewer contract line
            # naming the login, the check (if any), and the
            # push-re-review behavior. Deleting any one bullet
            # (or the `github-actions[bot]` non-addition) fails
            # the validator closed. QA mutation M6 previously
            # deleted all four and passed every suite.
            "**Gemini Code Assist** — review (`gemini-code-assist[bot]`). Comment-only (no published check-run app)",
            "**Greptile** — review (`greptile-apps[bot]`) and check (app slug `greptile-apps`)",
            "**Sourcery** — review (`sourcery-ai[bot]`) and check (app slug `sourcery-ai`)",
            "**Qodo** — review (`qodo-code-review[bot]`, `qodo-free-for-open-source-projects[bot]`)",
            "`github-actions[bot]` is shared by every workflow and is not a stable identity",
            # Issue #82: the ask-once contract is pinned above;
            # the four Known-identities bullets above are the
            # M6 coverage fix.
        ),
        # Issue #33: without a named retro line, repeated bypass across
        # rounds was only ever visible per-PR, never as a pattern.
        "phases/phase5.md": (
            "External-Review Bypasses",
            "reported explicitly, including `0`",
            # Issue #69: substitutions are reported next to bypasses, kept
            # separate because a substitution is a completed review.
            "also report the count of rate-limit breakpoint substitutions this round",
            "Keep it separate from the bypass count: a substitution is a completed review, not a bypass",
            # Issue #26: the retro reads post-merge verification records
            # rather than re-running the check phase4.md already performed.
            "### Post-Merge Verification",
            "post-merge verification records",
        ),
        # Issue #26: nothing re-examined merged code against the closed
        # Issue's acceptance criteria, and a merge keyword's auto-closure was
        # read as completion evidence. These tokens pin the unconditional
        # step, its non-gate status, and the sentence that names the hazard.
        "phases/phase4.md": (
            "Post-Merge Verification (unconditional)",
            "This is not a merge gate",
            "the merge commit's tree hash",
            "the verified PR head's tree hash",
            "run the full recorded Verification Gate",
            "Auto-closure by a merge keyword is never evidence of completion",
            "merge_sha",
            "gate_result",
            "criteria_verdict",
            "${CLAUDE_SKILL_DIR}/graft.md",
            "rtk proxy graft callers",
            "graph_evidence: unavailable",
            "trace dependents manually",
            "Graph output = static evidence, never execution confirmation",
            # Issue #48: the rating is decided here, so a completed current-head
            # substitution must route as `clear` here too, not only in the gate.
            "whose only open seats are filled by a completed, current-head substitution routes as `clear`",
            # Issue #69: triage must name a completed substitute's findings.
            "and every finding of a completed current-head substitute review",
            "per **Rate-limit breakpoint** in the external-review gate",
            "no finding, the substitute's included, is blocking or awaiting disposition",
            "a substitute at an older head does not count",
            "a completed, current-head substitute review with a blocking finding → REQUEST CHANGES",
            "Any other `pending`, or `incomplete`, external review → do not merge",
            "a `pending` routed as `clear` by a completed, current-head substitution counts",
        ),
        "phases/phase1.md": (
            "### B.0 Document-first mode (Situation A only)",
            "**Extract before asking.**",
            "Each item cites the document section it came from",
            "Present the proposed list and the gap list together, and **state both counts**",
            "Then ask only the gaps, one question at a time",
            "The B.3 stress-test runs for every module",
            'the Step C gate still requires the user to press "satisfied" before the next module',
            "the user can reopen any of them at the Step C gate",
            "**The document is never rewritten.**",
            "**with their citations**",
        ),
        "phases/phase2.md": (
            "${CLAUDE_SKILL_DIR}/graft.md",
            "rtk proxy graft callers",
            "graph_evidence: unavailable",
            "trace dependents manually",
        ),
        "SKILL.md": (
            "the lead reconciles the merged tree and re-confirms the closed Issue's acceptance criteria",
            # Issue #89: the Execution Backend section names the supplied source.
            "backend_source: supplied",
            "never available to a lead whose harness is not Claude Code",
            "${CLAUDE_SKILL_DIR}/reply-contract.md",
        ),
        # Issue #54: the reply contract's own pinned sentences, held in the one
        # file that defines them rather than only in the combined-text check
        # above, so deleting this file's content and leaving the tokens
        # elsewhere cannot pass silently.
        "reply-contract.md": (
            "aim under 100 words",
            "The cap counts prose, not required structured artifacts.",
            "never claims a task-requirements override",
            "Phase 1's progress breadcrumb",
            "Phase 3's Backend-Neutral Task Board",
            "Phase 4's review rating",
            "Phase 5's retro and technical-debt-sweep templates",
        ),
        # Each adapter must state its own bound; `contract.md` requires one to
        # exist but cannot supply a page size or a timeout for a transport it
        # does not know. An adapter naming no bound has not implemented observe.
        "backends/traycer.md": (
            # Issue #89: the wrapper route, the identity file format and its
            # acquisition rule, and the preflight self-check that catches a
            # wrong supplied pair mechanically.
            "rtk proxy python3 ${CLAUDE_SKILL_DIR}/scripts/traycer_cli.py",
            "Never invoke `traycer` directly",
            ".agent/traycer.env",
            "export TRAYCER_AGENT_ID=",
            "export TRAYCER_EPIC_ID=",
            "git-ignored or excluded",
            "never guesses an id",
            "Never derive an id from a path guess, a directory name, or another agent's record.",
            "ask the user once and stop until answered",
            # The CLI derives its self marker and caller block from the supplied
            # identifiers, so neither can catch a wrong pair. Pinned as a
            # statement, with the two independent checks that replace them.
            "are not evidence of the caller's identity",
            "**(a) Self-source comparison.**",
            "This is mandatory whenever the source exists, including when the id came from the user's message.",
            "**(b) Row corroboration.**",
            "`folderPaths`",
            "`harnessId`",
            "its `harnessId` must be the harness the lead itself knows it is running on",
            "the identity is wrong, and the lead deletes or corrects `.agent/traycer.env` before anything else",
            "(b) alone is the floor and the ledger records that",
            "When neither can be made, the result is `incomplete`.",
            "(b) cannot distinguish two agents that share one worktree and one harness",
            # The two checks reduce the chance of accepting a wrong pair; they
            # do not eliminate it, and the prose must not promise more.
            "establishes the agent id when a self-identity source exists",
            "corroborates it and is the weaker of the two",
            "reduce, and do not eliminate, the chance of accepting a wrong pair",
            "row corroboration accepts a wrong id that belongs to an agent sharing the lead's worktree and harness",
            "Read-only QA and review lanes that share a checkout with the lead are the realistic way this happens.",
            "A lead verified by `worktree_match` alone says so to the user in its first status reply.",
            "the Preflight step 3 identity checks",
            "identity_verification",
            # A partial environment is a host defect, not something the lead
            # repairs by editing its own environment.
            "a partial environment cannot be recovered by the file",
            "reports the partial environment to the user as a host defect",
            "It never sets or unsets `TRAYCER_AGENT_ID` or `TRAYCER_EPIC_ID` itself to make the file apply.",
            "verified live for Codex and OpenCode leads",
            "report_back: incomplete",
            "Quality-gate self-assessment",
            "Bound that read.",
            "Classify `absent` before anything else.",
            # Issue #48: the no-heuristics rule stays; the breakpoint is carved
            # out as an SOP exit so the two do not read as a contradiction.
            "Do not add cost, rate-limit, or performance routing heuristics.",
            "is a documented SOP exit, not a routing heuristic",
        ),
        "backends/claude-native.md": (
            "seven required sections",
            "Bound the read",
            "Classify `absent` before anything else",
        ),
        # Issue #34: these two keys are declared a second time above the
        # report-back enforcement block; a dict literal keeps the last
        # declaration, so this entry is the one that runs. The open-questions
        # tokens live here for that reason — a pin in the shadowed entry would
        # pass a validator that never reads it.
        "agents/report-back.md": (
            "never substitute for the seven required sections",
            # The upstream half of Deviations: flagged before the departure,
            # not only after it.
            "including departures from the specification as written",
            "*before* departing from it",
        ),
        "agents/qa-agent.md": (
            "seven required sections",
            "${CLAUDE_SKILL_DIR}/graft.md",
            "rtk proxy graft callers",
            "graph_evidence: unavailable",
            "trace manually with `rg`",
            "Graph output = static evidence, never execution confirmation",
            # Issue #34: the QA lane reads the specification first, so it is
            # the lane most likely to find it wrong. Its sentence grades
            # against the criteria as written and still reports the
            # disagreement — the objection waives nothing.
            "Challenging the specification is in scope",
            "specification defect found before the next round beats a faithful pass over a flawed spec",
            "the objection waives nothing",
        ),
        "graft.md": (
            "Never an execution backend.",
            "never `graft init` in managed projects",
            "graph_evidence: unavailable",
        ),
        # Issue #82: the template's External Review Policy
        # section is the recording site for a freshly created
        # `PROJECT_CONTEXT.md`. The `Pending reviewer decisions`
        # line and the ask-once outcomes must be present so
        # initializing repos carry the contract forward. The QA
        # round 1 M4 mutation showed deleting the template line
        # (or any one outcome) passed both the validator and
        # the unit suite, so each token is pinned here.
        "templates/PROJECT_CONTEXT_TEMPLATE.md": (
            "External Review Policy (optional)",
            "**Pending reviewer decisions**: none",
            "`Ignored reviewers` takes precedence over every other setting",
        ),
        # Issue #75: multi-account routing is a verification-only layer, so
        # each token pins one way the layer could otherwise drift back into
        # silent credential persistence or auto-routing. The skill describes
        # the recommended routing layer; it never performs it.
        # Issue #75 (round 2): the `gh` credential helper does NOT select a
        # token per remote path; the account comes from the `gh` config in
        # effect. Tokens below pin that boundary so the false claim cannot
        # be re-introduced.
        "phases/repository-context.md": (
            "## Multiple GitHub accounts on one host",
            "The skill never chooses the account and never\npersists host or credential state.",
            "reported back in the\nsame turn they are made",
            "no\naccount is switched automatically, no token is duplicated silently",
            "asks the user to approve the host\nchanges that follow",
            "credential.https://github.com.useHttpPath=true",
            "credential.https://github.com/<ORG>.username=<login>",
            # The account comes from the `gh` config in effect (or the
            # project GH_CONFIG_DIR), NOT from `credential` username keys.
            "the one held by\n  the `gh` config in effect for that shell",
            "no separate per-path token lookup",
            "does **not**\n  select the account under the `gh` helper",
            "fails closed instead of silently\n  pushing as the wrong account",
            "git-credential-manager",
            "GH_CONFIG_DIR` to a project-scoped config directory",
            "(or `\"default\"`)",
            "Seeding\n  that directory by piping a token from an existing login is credential\n  persistence",
            "includeIf \"gitdir:/path/to/work\"",
            "Absence\nof a test is not a pass",
            "carried\ninto the worker, QA, and reviewer assignment envelopes",
            "`dev_config.py create --no-exclude`",
            # Round 2: Phase 2's new-project bootstrap does `gh repo create --clone`,
            # not `git init`; wording pinned on the `once Phase 2's bootstrap has\nproduced a repository`
            # form rather than a literal `git init` step.
            "Once Phase 2's bootstrap has\nproduced a repository",
            "Cross-reference #37, the SSH half",
            "this section\n  is the HTTPS and `gh` CLI half, and the two land or cross-reference\n  together.",
        ),
    }
    for relative, tokens in SWAP_EVIDENCE_PINS.items():
        per_file_policy[relative] = per_file_policy.get(relative, ()) + tokens
    for relative, tokens in sorted(per_file_policy.items()):
        target = skill_dir / relative
        if target.is_file():
            target_text = target.read_text(encoding="utf-8")
            for token in tokens:
                if token not in target_text:
                    fail(errors, f"{relative} missing required policy: {token}")

    # Issue #69: the Result Routing clear-condition shares its wording with the
    # Rate-limit breakpoint section, so per_file_policy's whole-file matching
    # would still pass after the routing line itself was deleted. Pin it inside
    # the `## Result Routing` section, so the validator fails on its own (the
    # export-ignored `tests/` are absent from archive validation).
    external_review = skill_dir / "phases" / "external-review.md"
    if external_review.is_file():
        routing_body = markdown_section(
            external_review.read_text(encoding="utf-8"), "## Result Routing"
        )
        if routing_body is None:
            fail(errors, "phases/external-review.md missing required section: Result Routing")
        else:
            routing_text = " ".join(routing_body.split())
            for token in RESULT_ROUTING_PINS:
                if token not in routing_text:
                    fail(
                        errors,
                        f"phases/external-review.md Result Routing missing required policy: {token}",
                    )

    # Issue #54: SKILL.md must hook the reply contract in BOTH required
    # sections (Session State Anchor + Global Rules), not merely anywhere in
    # the file. per_file_policy above is unscoped substring matching, so a
    # reference living in only one location still passes it. This check is
    # scoped per section so the validator itself fails when either hook is
    # missing, including when tests/ is absent (the export-ignored half of
    # the test-driven guarantee).
    skill_md = skill_dir / "SKILL.md"
    if skill_md.is_file():
        skill_text = skill_md.read_text(encoding="utf-8")
        anchor = markdown_section(
            skill_text, "## ⚓ Session State Anchor (execute on every user message)"
        )
        global_rules = markdown_section(skill_text, "## Global Rules")
        reply_token = "${CLAUDE_SKILL_DIR}/reply-contract.md"
        if anchor is None:
            fail(errors,
                "SKILL.md missing required section: Session State Anchor")
        elif reply_token not in anchor:
            fail(errors,
                 f"SKILL.md Session State Anchor missing required hook: {reply_token}")
        if global_rules is None:
            fail(errors,
                "SKILL.md missing required section: Global Rules")
        elif reply_token not in global_rules:
            fail(errors,
                 f"SKILL.md Global Rules missing required hook: {reply_token}")

    # Issue #54: the reply contract governs only the Tech Lead's own replies
    # to the user — never a delegated lane's prompt. The test suite enforces
    # this on a flat `agents/` glob, but `tests/` is export-ignored (see
    # `.gitattributes`) so archive extractions carry no test, and the gate
    # was only structurally guaranteed in-repo. Mirror the invariant at the
    # validator level so the archive's check is the same as the in-repo one.
    # Recursive so a future nested layout cannot smuggle a reference past
    # either layer. Each offending file is named in its own error so the
    # author does not have to grep to find the offender.
    # Matches the bare `reply-contract.md` token (same as the test) — both
    # the variable form `${CLAUDE_SKILL_DIR}/reply-contract.md` and a bare
    # filename reference are equivalent expressions of the same forbidden
    # cross-reference.
    agents_dir = skill_dir / "agents"
    if agents_dir.is_dir():
        for path in sorted(agents_dir.rglob("*")):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if "reply-contract.md" in text:
                fail(
                    errors,
                    f"agents/{path.relative_to(agents_dir)} references "
                    f"reply-contract.md; the contract governs only the lead's "
                    "replies, never a delegated lane's prompt",
                )

    detector = skill_dir / "scripts" / "detect_execution_backend.py"
    if detector.is_file():
        detector_text = detector.read_text(encoding="utf-8")
        if "shutil.which" in detector_text or "command -v" in detector_text:
            fail(errors, "backend detector must not probe binary presence")

    # `required_policy` above is matched against the Skill's own markdown, so it
    # structurally cannot pin a sentence in the repo-root `PROJECT_CONTEXT.md`.
    # Routing policy lives there and outranks the agent selection guide in the
    # adapter's resolution order, so a silent revert re-overrides newer policy
    # with a stale route. Anchored on `repo_root` (this script's own location,
    # not `--skill-dir`) for the same reason as the home-path scan above:
    # every call site stages the Skill elsewhere but always runs this
    # validator from the project or archive root, where the file ships.
    # Absence fails closed — an unreadable policy is not a satisfied one.
    project_context = repo_root / "PROJECT_CONTEXT.md"
    if not project_context.is_file():
        fail(errors, "missing required file: PROJECT_CONTEXT.md")
    else:
        project_text = project_context.read_text(encoding="utf-8")
        # Issue #82 / #117: the project's own
        # `PROJECT_CONTEXT.md` External Review Policy must
        # carry the `Pending reviewer decisions` line so the
        # ask-once contract has a recording site. Without
        # this pin, removing the line from the live policy
        # would drop the decide-later outcome and the
        # no-re-ask rule would have no place to land; the
        # QA round 1 M5 mutation showed the absence.
        if "**Pending reviewer decisions**" not in project_text:
            fail(
                errors,
                "PROJECT_CONTEXT.md External Review Policy must "
                "carry the `Pending reviewer decisions` line "
                "(Issue #82 ask-once contract)",
            )
        if "**Pending reviewer decisions**: none" not in project_text:
            fail(
                errors,
                "PROJECT_CONTEXT.md External Review Policy must "
                "carry the `Pending reviewer decisions: none` line "
                "(Issue #82 ask-once contract; a value other than "
                "`none` is a runtime decision recorded per-login "
                "below the line, never a replacement for it)",
            )
        # Round-3 coverage pin (QA M8): the External Review
        # Policy values are load-bearing (Issue #117):
        # `Required reviewers: kilo` (Kilo is the reviewer of
        # record) and `Ignored reviewers: coderabbit` (CodeRabbit
        # is summary/walkthrough-only, not review evidence).
        # QA mutation M8 previously reverted the section to
        # `Required: none` / `Ignored: none` and passed every
        # suite. Pin each value so a silent revert fails closed.
        if "**Required reviewers**: kilo" not in project_text:
            fail(
                errors,
                "PROJECT_CONTEXT.md External Review Policy must "
                "set `Required reviewers: kilo` (Issue #117: Kilo "
                "is the reviewer of record)",
            )
        if "**Ignored reviewers**: coderabbit" not in project_text:
            fail(
                errors,
                "PROJECT_CONTEXT.md External Review Policy must "
                "set `Ignored reviewers: coderabbit` (Issue #117: "
                "CodeRabbit is summary/walkthrough-only)",
            )
        # Round-3 coverage pin (QA M7): the CHANGELOG.custom.md
        # `Unreleased (v2.1.2)` entry must record the Issue
        # #82/#117 switch (added reviewers, ask-once contract,
        # Kilo summary evidence path). QA mutation M7 previously
        # deleted the whole v2.1.2 Kilo/CodeRabbit entry and
        # passed every suite. The entry is one of the few
        # user-facing places the behavior change is recorded, so
        # losing it silently is a real regression.
        #
        # Tolerant of absence: the file is a release-notes
        # document, so a fixture/archival tree that does not
        # carry it is not a defect (same tolerance pattern as
        # `EXTRA_MARKDOWN_DIRS` for `en/`, `zh/`). The check
        # applies only when the file is present, which is the
        # shape a real source tree has.
        changelog = repo_root / "CHANGELOG.custom.md"
        if changelog.is_file():
            changelog_text = changelog.read_text(encoding="utf-8")
            # D1 (release-aware): the section is the release
            # record for v2.1.2. While unreleased it is headed
            # `## Unreleased (v2.1.2)`; at release time the
            # heading becomes `## v2.1.2 (YYYY-MM-DD)`. Both
            # forms must be accepted so the pin does not break
            # the moment the release is cut. The 8 #82/#117
            # tokens are still required inside whichever
            # heading is present.
            unreleased_match = re.search(
                r"^## (?:Unreleased \(v2\.1\.2\)|v2\.1\.2(?: \(\d{4}-\d{2}-\d{2}\))?)"
                r"$(.*?)(?=^## |\Z)",
                changelog_text,
                re.M | re.S,
            )
            if unreleased_match is None:
                fail(
                    errors,
                    "CHANGELOG.custom.md must have an "
                    "`## Unreleased (v2.1.2)` section (or a "
                    "released `## v2.1.2 (YYYY-MM-DD)` heading)",
                )
            else:
                unreleased_body = unreleased_match.group(1)
                for token in (
                    "gemini-code-assist",
                    "greptile",
                    "sourcery",
                    "qodo",
                    "Ask-once contract",
                    "Kilo summary evidence",
                    "kilo` is required",
                    "coderabbit` is ignored",
                ):
                    if token not in unreleased_body:
                        fail(
                            errors,
                            f"CHANGELOG.custom.md Unreleased (v2.1.2) "
                            f"section missing required token: {token}",
                        )
        section = routing_section(project_text)
        if section is None:
            fail(errors, f"PROJECT_CONTEXT.md missing section: {ROUTING_HEADING}")
        elif normalize(section) != ROUTING_SECTION_BODY:
            fail(
                errors,
                f"PROJECT_CONTEXT.md `{ROUTING_HEADING}` must contain its approved "
                "content and nothing else; this section exists to specify no "
                "routes, so any added or altered line fails regardless of wording. "
                "If the edit is intentional, update ROUTING_SECTION_BODY in "
                "scripts/validate_skill.py in the same commit.",
            )

    state_template = skill_dir / "templates" / "DEV_STATE_TEMPLATE.md"
    if state_template.is_file():
        state_text = state_template.read_text(encoding="utf-8")
        if not state_text.startswith("---\n") or "\n---\n" not in state_text[4:]:
            fail(errors, "DEV_STATE_TEMPLATE.md must contain YAML frontmatter")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"OK: validated {skill_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
