from __future__ import annotations

import ast
import importlib.util
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "dev"

# The `required_policy` tuple as it stood at base 66ecfa3, frozen as data.
#
# The tokens are the mechanism that protects every policy sentence in the
# payload, but nothing protected the tokens themselves: deleting an entry from
# `required_policy` and then deleting the prose it pinned passed green gates at
# both steps. The scheme guarded the prose and not itself.
#
# Frozen here rather than read from git so this works in a tree without `.git`.
# Extracted with `ast` from `git show 66ecfa3:scripts/validate_skill.py`, not
# transcribed.
BASE_REQUIRED_POLICY = (
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
)


# The seven required report-back sections, held once. Every document that has
# to name them is asserted against this tuple, so adding an eighth section is a
# one-line change here that then fails until each document carries it — rather
# than four independent lists that drift apart silently.
REPORT_BACK_SECTIONS = (
    "Outputs",
    "Commands + exit codes",
    "Deviations",
    "Quality-gate self-assessment",
    "Acceptance criteria",
    "Evidence",
    "Scope / ownership",
)


# The cause taxonomy, held once for the same reason as the section names: the
# contract defines these and the ledger has to store exactly them. Two lists
# would let the adapters record a cause the ledger cannot hold.
REPORT_BACK_CAUSES = ("absent", "malformed", "truncated")

# The four bounded-read terminating conditions, under the names the contract,
# both adapters, and the ledger all use. Held once for the same reason: the
# adapters record one of these and the ledger has to store exactly these, and
# the cause uses termination, reply correlation, and section presence.
REPORT_BACK_TERMINATIONS = ("completed", "stalled", "page_cap", "time_bound")

_COMPLETED, *_TRUNCATING = REPORT_BACK_TERMINATIONS
_ABSENT, _MALFORMED, _TRUNCATED = REPORT_BACK_CAUSES

# The derivation itself, as data: which terminating condition (with the section
# check, when the read completed) yields which verdict and cause.
#
# This is the guarantee the whole field rests on. `report_back_cause` is safe
# to keep beside `report_back_termination` only because it is read off a total
# mapping rather than authored independently - so the mapping's CONTENT is
# load-bearing, not just its presence. Asserting that the table contains the
# right words in some order leaves a wrong row silently authoritative, and a
# wrong row sends a lead to re-request the shape of a reply that was truncated:
# the wrong remedy, chosen confidently, off a ledger that looks right.
#
# Built from the tuples above rather than retyped, so a renamed condition or
# cause cannot leave this mapping describing the old vocabulary.
# Correlation is an explicit input, not an implicit one. The earlier version
# recorded `report_back_termination: null` for an absent lane on the reasoning
# that no bounded read had run - which is false. Absence is established BY
# reading: the read runs, terminates, and only then is correlation checked. The
# ledger discarded that condition and then asserted the read never happened,
# contradicting `contract.md`'s own "nothing can be known to be absent without
# looking" at the same head.
#
# `absent` additionally requires a `completed` read. A cut read that found no
# correlated reply has established nothing - the reply may lie past the cut -
# so it is `truncated` and re-read. Calling it `absent` would read a partial
# absence of signal as a positive finding, in the ledger built to prevent that.
REPORT_BACK_DERIVATION = (
    ("not yet read", ("null",), "not examined", "pending", "null"),
    ("not observed", tuple(_TRUNCATING), "not examined", "incomplete", _TRUNCATED),
    ("not observed", (_COMPLETED,), "not examined", "incomplete", _ABSENT),
    ("observed", tuple(_TRUNCATING), "not judged", "incomplete", _TRUNCATED),
    ("observed", (_COMPLETED,), "any missing", "incomplete", _MALFORMED),
    ("observed", (_COMPLETED,), "all seven", "complete", "null"),
)


def _mapping_rows(text: str) -> list[tuple[str, tuple[str, ...], str, str, str]]:
    """Parse the ledger's derivation table into comparable tuples.

    Returns (correlation, terminations, sections, verdict, cause) per row, with
    backticked tokens extracted so a reflow or added emphasis is not a policy
    change while a changed value is.
    """
    rows: list[tuple[str, tuple[str, ...], str, str, str]] = []
    for line in text.splitlines():
        if not line.strip().startswith("|") or line.strip().startswith("|---"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 5:
            continue
        terminations = tuple(re.findall(r"`([^`]+)`", cells[1]))
        verdict = re.findall(r"`([^`]+)`", cells[3])
        cause = re.findall(r"`([^`]+)`", cells[4])
        if not terminations or not verdict or not cause:
            continue
        # Skip the header row, which names the fields rather than values.
        if terminations[0] == "report_back_termination":
            continue
        rows.append((cells[0], terminations, cells[2], verdict[0], cause[0]))
    return rows


def _assigns(cause: str) -> str:
    """Regex matching a sentence that ASSIGNS `cause`, not one mentioning it.

    The distinction is the whole difference between a guard and a nuisance. A
    sentence that assigns a cause makes a claim about when it applies and must
    name what licenses it; one that refers to the cause — a remedy, a
    cross-reference, a pointer at the contract — makes no such claim, and
    failing on it is a guard crying wolf, which is how guards get disabled.

    Deliberately narrower than "mentions the cause": phrasings that assign
    without one of these constructions will escape. A narrow guard that is
    trusted beats a broad one that is switched off.
    """
    return rf"(?:is|as|in|cause|record(?:s|ed)?|classified|file[ds]?)\s+`{cause}`"


def _sentence_containing(text: str, needle: str) -> str | None:
    """Return the sentence containing `needle`, for cross-document checks."""
    for sentence in re.split(r"(?<=\.)\s+(?=[A-Z`*])", text):
        if needle in sentence:
            return sentence
    return None


def _markdown_section(text: str, heading: str) -> str | None:
    """Return the body under `heading` up to the next same-level heading."""
    match = re.search(
        rf"^{re.escape(heading)}$(.*?)(?=^## |\Z)", text, re.M | re.S
    )
    return match.group(1) if match else None


def _markdown_subsection(text: str, heading: str) -> str | None:
    """Return the body under `heading` up to the next heading of any level.

    `_markdown_section` stops only at a `##` boundary, so a `###` body runs
    into everything below it and an assertion scoped to the subsection is
    scoped to half the file. Same reason as `_bullet`: the assertion has to be
    about the region that states the rule.
    """
    match = re.search(
        rf"^{re.escape(heading)}$(.*?)(?=^#+ |\Z)", text, re.M | re.S
    )
    return match.group(1) if match else None


def _bullet(text: str, starts_with: str) -> str | None:
    """Return the single list bullet beginning with `starts_with`.

    Assertions about one rule have to be scoped to the bullet stating it. A
    file-wide `assertIn` passes on any other occurrence of the same words, so a
    deleted condition can still be "found" in the bullet that consumes it —
    which is a test reporting a guard it is not actually holding.
    """
    match = re.search(
        rf"^- {re.escape(starts_with)}.*?(?=^- |\Z)", text, re.M | re.S
    )
    return match.group(0) if match else None


def _line_starting(text: str, prefix: str) -> str | None:
    """Return the single line beginning with `prefix`.

    Same reason as `_bullet`: an enumeration has to be asserted against the
    line that enumerates it, or a renamed value is still "found" in some other
    field's vocabulary elsewhere in the file.
    """
    return next((line for line in text.splitlines() if line.startswith(prefix)), None)


def _table_row(text: str, operation: str) -> str | None:
    """Return the operations-table row for `operation`, or None."""
    for line in text.splitlines():
        if line.startswith(f"| `{operation}` |"):
            return line
    return None


def _parse_required_policy(source: str) -> list[str]:
    """Return the `required_policy` tuple's literals, parsed with `ast`.

    Parsed rather than grepped on purpose. A regex over this tuple silently
    matches nothing when the formatting shifts and then reports a clean run,
    which is the same defect class the tokens exist to guard against: an
    instrument that fails looks identical to a check that passed.
    """
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "required_policy"
            for target in node.targets
        ):
            return [ast.literal_eval(element) for element in node.value.elts]
    raise AssertionError("required_policy assignment not found in validate_skill.py")


def _validator_module():
    """Load scripts/validate_skill.py so its pinned policy has one home.

    The routing section is pinned in the validator rather than duplicated here
    because `.gitattributes` export-ignores `tests`, so CI's archive validation
    runs the validator without this file. Importing it keeps a single source of
    truth and still fails here when the live document drifts from it.
    """
    path = ROOT / "scripts" / "validate_skill.py"
    spec = importlib.util.spec_from_file_location("validate_skill", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BackendContractTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (SKILL / relative).read_text(encoding="utf-8")

    def mapping_rows(self) -> list[tuple[str, tuple[str, ...], str, str, str]]:
        """Parse the mapping table from the section that governs it.

        Scoped rather than file-wide, for the reason four earlier assertions
        in this module were not: a table parsed from the whole document would
        happily bind to some other table added later, and the check would go on
        passing while the section it exists to guard drifted.
        """
        section = _markdown_section(
            self.read("templates/DEV_STATE_TEMPLATE.md"),
            "## Report-back record schema",
        )
        self.assertIsNotNone(section, "template has no report-back record schema")
        rows = _mapping_rows(section)
        self.assertTrue(rows, "the report-back schema carries no mapping table")
        return rows

    def test_contract_has_all_fail_closed_operations(self) -> None:
        contract = self.read("backends/contract.md")
        for operation in (
            "preflight",
            "prepare_worktree",
            "resolve_route",
            "launch",
            "message",
            "observe",
            "shutdown",
            "recover",
        ):
            self.assertIn(f"`{operation}`", contract)
        for topology in ("serial", "parallel"):
            self.assertIn(topology, contract)
        for backend in ("claude-native", "traycer", "incomplete"):
            self.assertIn(backend, contract)

    def test_claude_adapter_preserves_serial_and_agent_teams(self) -> None:
        adapter = self.read("backends/claude-native.md")
        self.assertIn("`serial`", adapter)
        self.assertIn("`parallel`", adapter)
        self.assertIn("Agent Teams", adapter)
        self.assertIn("tmux/iTerm", adapter)
        self.assertIn("Never silently", adapter)

    def test_traycer_command_contract_and_receive_capability(self) -> None:
        adapter = self.read("backends/traycer.md")
        required = (
            "rtk proxy traycer",
            "rtk proxy python3 ${CLAUDE_SKILL_DIR}/scripts/traycer_cli.py",
            "worktree create",
            "--workspace",
            "--source-branch",
            "--branch",
            "--workspace-entry",
            "--surface gui",
            "agent create",
            "agent send",
            "--expect-reply",
            "agent inbox",
            "agent transcript",
            "agent stop",
            "agent archive",
            "response ID",
            "cursor/page",
            "--carry-uncommitted",
        )
        for token in required:
            self.assertIn(token, adapter)
        self.assertIn("must never use `--carry-uncommitted`", adapter)
        self.assertIn("Codex/OpenCode", adapter)

    def test_route_precedence_validation_and_last_used(self) -> None:
        adapter = self.read("backends/traycer.md")
        project = adapter.index("Explicit `PROJECT_CONTEXT.md`")
        workspace = adapter.index("Workspace `.traycer/agent-selection-guide.md`")
        global_guide = adapter.index("Global `rtk proxy python3 ${CLAUDE_SKILL_DIR}/scripts/traycer_cli.py agent selection-guide")
        lead = adapter.index("Lead route from the lead row")
        self.assertLess(project, workspace)
        self.assertLess(workspace, global_guide)
        self.assertLess(global_guide, lead)
        for token in ("list-harnesses", "list-harness-models", "list-profiles"):
            self.assertIn(token, adapter)
        self.assertIn("traycer_last_used", adapter)
        self.assertIn("Do not invent `read_only`", adapter)
        self.assertIn("invalid field", adapter)
        self.assertIn("unavailable model/profile", adapter)
        self.assertIn("do not substitute another route", adapter)

    def test_traycer_supports_both_topologies_without_backend_switching(self) -> None:
        adapter = self.read("phases/phase3.md")
        self.assertIn("Both Traycer topologies", adapter)
        self.assertIn("Topology controls scheduling and ownership", adapter)
        self.assertIn("Do not silently change backend or topology", adapter)

    def test_failures_never_trigger_claude_fallback(self) -> None:
        adapter = self.read("backends/traycer.md")
        for failure in (
            "missing CLI",
            "Host",
            "authentication",
            "permission",
            "A2A capability",
            "malformed JSON or NDJSON",
            "missing page",
        ):
            self.assertIn(failure, adapter)
        self.assertIn("never fall back to Claude-native", adapter)

    def test_state_schema_preserves_review_and_recovery_fields(self) -> None:
        state = self.read("templates/DEV_STATE_TEMPLATE.md")
        for token in (
            "schema_version",
            "execution_backend",
            "topology",
            "lead:",
            "reviewer:",
            "agent_id",
            "traycer_agent_id",
            "traycer_epic_id",
            "backend_source",
            "communication_response_id",
            "headRefOid",
            "external_review_state",
            "unresolved_actionable_findings",
            "review_deadline",
            "wait_extensions",
            "approved_review_requests",
            "approved_bypasses",
            "review_debt",
            "The Tech Lead is the sole writer",
        ):
            self.assertIn(token, state)
        for status in (
            "planned",
            "worktree_ready",
            "active",
            "blocked",
            "pr_created",
            "qa",
            "review",
            "complete",
            "stopped",
        ):
            self.assertIn(f"`{status}`", state)

    def test_ledger_can_hold_the_verdict_the_adapters_record(self) -> None:
        # All three adapters instructed recording `report_back` into
        # `.agent/dev-state.md`, which had no such field - so every lead would
        # have invented a shape and the record would be unusable as an audit
        # trail. Issue #3's criterion is "recorded in .agent/dev-state.md";
        # the ledger is the other half of it.
        state = self.read("templates/DEV_STATE_TEMPLATE.md")
        contract = self.read("backends/contract.md")
        self.assertIn("`report_back`", state)
        self.assertIn("`report_back_cause`", state)
        # The field is on the per-lane record, not floating in prose.
        workers = _markdown_section(state, "## Worker record schema")
        self.assertIsNotNone(workers, "template has no worker record schema")
        self.assertIn("`report_back`", workers)
        self.assertIn("`report_back_cause`", workers)
        self.assertIn("`report_back_termination`", workers)
        # The ledger stores exactly the causes the contract defines. Asserted
        # from one list so the two cannot drift into a cause the ledger cannot
        # hold, or a field the adapters never produce.
        # Scoped to the line that enumerates them. File-wide, `incomplete` and
        # `complete` already appear as a `backend_source` result and a worker
        # status, so a renamed cause here could still be "found" against an
        # unrelated field's vocabulary.
        allowed = _line_starting(state, "Allowed `report_back_cause` values:")
        self.assertIsNotNone(allowed, "template does not enumerate the causes")
        for cause in REPORT_BACK_CAUSES:
            with self.subTest(cause=cause):
                self.assertIn(f"`{cause}`", allowed)
                self.assertIn(f"`{cause}`", contract)

    def test_every_document_names_the_same_four_terminating_conditions(self) -> None:
        # External review, Medium: the ledger stored the cause but not the
        # condition it came from, and `truncated` collapses three conditions
        # into one value. The omission was deliberate and argued on remedy -
        # all three share one - and overturned on diagnosis, which the cause
        # cannot serve. One list, so contract, adapters and ledger cannot drift
        # into names that no longer match.
        # Scoped to the construct in each document that has to define the
        # names. File-wide, every name also appears in the prose explaining why
        # the cause is lossy, so a renamed condition in the definition would
        # still be "found" in the explanation of it.
        contract = self.read("backends/contract.md")
        traycer = self.read("backends/traycer.md")
        native = self.read("backends/claude-native.md")
        state = self.read("templates/DEV_STATE_TEMPLATE.md")
        scopes = {
            "contract.md paging bullet": _bullet(contract, "**Paging must be bounded"),
            "traycer.md bound bullet": _bullet(traycer, "**Bound that read."),
            "claude-native.md bound step": _line_starting(
                native, "   2. **Bound the read**"
            ),
            "template allowed values": _line_starting(
                state, "Allowed `report_back_termination` values:"
            ),
        }
        for name, scope in scopes.items():
            self.assertIsNotNone(scope, f"{name}: not found")
            for condition in REPORT_BACK_TERMINATIONS:
                with self.subTest(scope=name, condition=condition):
                    self.assertIn(f"`{condition}`", scope)
        # Each adapter must name the ledger field it writes, or the condition
        # is observed and then has nowhere to go - the defect one level up.
        for relative, adapter in (
            ("backends/traycer.md", traycer),
            ("backends/claude-native.md", native),
        ):
            with self.subTest(adapter=relative):
                self.assertIn("`report_back_termination`", adapter)

    def test_the_cause_is_derived_from_the_full_mapping(self) -> None:
        # Completed reads have multiple outcomes; termination alone cannot
        # select the row. Preserve the explicit inputs and total mapping.
        state = self.read("templates/DEV_STATE_TEMPLATE.md")
        contract = self.read("backends/contract.md")
        for document in (state, contract, self.read("backends/traycer.md"),
                         self.read("backends/claude-native.md")):
            self.assertIn("termination, reply correlation, and section presence", document)
        self.assertIn(
            "Record the terminating condition, and derive the verdict and cause from the full mapping.",
            contract,
        )
        self.assertIn("The mapping is total", state)
        self.assertIn("any pairing not in this table is an invalid record", state)

    def test_the_mapping_table_states_the_exact_pairings(self) -> None:
        # Content, not shape. The previous version of this check collected the
        # table's lines and asserted every value appeared somewhere in the
        # joined block - which stays true when a row's cause is changed, so a
        # table saying a stalled read is `malformed` passed the whole suite
        # while contradicting `contract.md`. The pairing is the guarantee; a
        # table asserted only for its vocabulary is not asserted at all.
        self.assertEqual(
            self.mapping_rows(),
            list(REPORT_BACK_DERIVATION),
            "the ledger's termination-to-cause mapping does not match the "
            "derivation it is supposed to encode",
        )

    def test_the_ledger_mapping_and_the_contract_prose_cannot_drift(self) -> None:
        # Two documents stating one rule is how they diverge, which is the
        # defect fixed at the contract level in b2632ba reappearing in the
        # artifact that resolves it. The contract's sentences are checked
        # against the cause parsed out of the ledger table, not against a
        # literal - so a wrong row fails here too, from the other side.
        rows = self.mapping_rows()
        truncating = next(
            (r for r in rows if r[0] == "observed" and r[1] == tuple(_TRUNCATING)), None
        )
        completed_missing = next(
            (r for r in rows if r[0] == "observed" and r[2] == "any missing"), None
        )
        uncorrelated = next(
            (r for r in rows if r[0] == "not observed" and r[1] == (_COMPLETED,)), None
        )
        self.assertIsNotNone(truncating, "no row for the truncating conditions")
        self.assertIsNotNone(completed_missing, "no row for a completed read")
        self.assertIsNotNone(uncorrelated, "no row for a completed read with no reply")

        bullet = _bullet(
            self.read("backends/contract.md"),
            "**Termination decides whether section inspection is permitted",
        )
        self.assertIsNotNone(bullet, "contract.md has no cause-decision bullet")
        stall_sentence = _sentence_containing(bullet, "ended by a stall")
        completed_sentence = _sentence_containing(bullet, "ended by the completion")
        self.assertIsNotNone(stall_sentence, "contract states no stall outcome")
        self.assertIsNotNone(completed_sentence, "contract states no completed outcome")

        # The cause the ledger assigns each case must be the cause the contract
        # names for it, and must not be the one it names for the other case.
        self.assertIn(f"`{truncating[4]}`", stall_sentence)
        self.assertNotIn(f"`{truncating[4]}`", completed_sentence)
        self.assertIn(f"`{completed_missing[4]}`", completed_sentence)
        self.assertNotIn(f"`{completed_missing[4]}`", stall_sentence)

        # The absent row, which the previous version of this check did not
        # cover - and which is exactly where the two documents drifted. The
        # contract must agree that absence needs a completed read and that a
        # cut read establishes nothing.
        absent_bullet = _bullet(
            self.read("backends/contract.md"), "**Record the terminating condition"
        )
        self.assertIsNotNone(absent_bullet, "contract.md has no derivation bullet")
        self.assertIn(f"`{uncorrelated[4]}`", absent_bullet)
        self.assertIn(f"is `{_COMPLETED}`", absent_bullet)
        self.assertIn("has not established absence", absent_bullet)
        # And the ledger must not claim the read never happened.
        state = self.read("templates/DEV_STATE_TEMPLATE.md")
        self.assertNotIn("no bounded read ran", state)
        self.assertIn("Absence is established by reading, not instead of reading", state)

    def test_no_prose_claims_absence_without_a_completed_read(self) -> None:
        """The drift guard's hole, found twice in one file.

        The cross-document check binds the rows where the two documents agree,
        and both times the drift went to prose no row covers — a bullet three
        sections above the mapping still saying an empty read "was already
        classified `absent` above and never reaches" the four conditions, which
        contradicts the table on two counts at once.

        So this binds the prose to the table instead of to a literal: any
        sentence in the enforcement section that names `absent` as a
        classification must also name the termination the mapping pairs it
        with. A reintroduced sentence claiming absence without a completed read
        has no way to satisfy that, whatever words it uses.
        """
        rows = self.mapping_rows()
        absent_row = next(
            (r for r in rows if r[0] == "not observed" and r[1] == (_COMPLETED,)), None
        )
        cut_row = next(
            (r for r in rows if r[0] == "not observed" and r[1] == tuple(_TRUNCATING)),
            None,
        )
        self.assertIsNotNone(absent_row, "no completed-read absent row")
        self.assertIsNotNone(cut_row, "no cut-read row for an uncorrelated reply")
        absent_cause, cut_cause = absent_row[4], cut_row[4]

        section = _markdown_section(
            self.read("backends/contract.md"), "## Report-back enforcement"
        )
        self.assertIsNotNone(section, "contract.md has no enforcement section")

        # The paging bullet is where the stale sentence lived and where the
        # split has to be stated, in the mapping's own terms.
        paging = _bullet(section, "**Paging must be bounded")
        self.assertIsNotNone(paging, "no bounded-paging bullet")
        self.assertIn(
            f"no correlated reply after `{_COMPLETED}` is `{absent_cause}`", paging
        )
        self.assertIn(f"is `{cut_cause}`", paging)
        for condition in _TRUNCATING:
            with self.subTest(condition=condition):
                self.assertIn(f"`{condition}`", paging)

        # And across the WHOLE enforcement section, no sentence that ASSIGNS
        # the cause may do so without naming the condition that licenses it.
        # Matched on the assignment construction — "cause `absent`", "is
        # `absent`", "classified `absent`" — rather than on any mention, so
        # prose that merely refers to the cause stays exempt: "`absent`
        # questions whether the lane is alive" is a remedy, and "`absent`
        # having already been ruled out" is a cross-reference. Neither assigns.
        #
        # Section-wide rather than bullet-scoped because the first pass of this
        # guard covered only the paging bullet and two other bullets carrying
        # the same stale assumption went through untouched.
        # Split per bullet before splitting sentences: a "sentence" spanning a
        # bullet boundary is a parsing artifact, and treating one as a claim
        # fails the guard on prose that is correct.
        classifying = [
            sentence
            for chunk in re.split(r"\n- ", section)
            for sentence in re.split(r"(?<=\.)\s+(?=[A-Z`*\"])", chunk)
            if re.search(_assigns(absent_cause), sentence)
        ]
        self.assertTrue(classifying, "no sentence assigns the absent cause")
        for sentence in classifying:
            with self.subTest(sentence=sentence[:70]):
                self.assertIn(
                    f"`{_COMPLETED}`",
                    sentence,
                    f"classifies a read as `{absent_cause}` without naming "
                    f"`{_COMPLETED}`, which is the only condition that licenses it",
                )

        # The two bullets the section sweep corrected, pinned directly: the
        # cause gloss must carry the qualification, and the cause-decision
        # bullet must say which replies it governs.
        self.assertIn(f"a `{_COMPLETED}` read carried no reply correlated", section)
        self.assertIn("For a reply that was observed", section)

    def test_adapters_license_every_cause_they_assign(self) -> None:
        """The same rule as the contract's, extended to both adapters.

        Third pass at one class. The contract's section was swept and guarded;
        the identical stale rationale was then found living in both adapters,
        where nothing bound it. Each sweep fixed the sites someone listed and
        the drift was wherever nobody looked — so this binds the adapters by
        the same rule rather than by another list of sites.

        Both directions:

        - a sentence assigning `absent` must name `completed`;
        - inside the classification bullet, a sentence naming `truncated` must
          name a cut condition.

        The second is scoped to that bullet on purpose. Elsewhere `truncated`
        appears in definitional prose that licenses it by negating completion
        rather than by naming a condition, and a blanket rule would fail on
        correct writing.
        """
        rows = self.mapping_rows()
        absent_cause = next(
            r[4] for r in rows if r[0] == "not observed" and r[1] == (_COMPLETED,)
        )
        cut_cause = next(
            r[4] for r in rows if r[0] == "not observed" and r[1] == tuple(_TRUNCATING)
        )
        assigns = _assigns(absent_cause)

        for relative, opener in (
            ("backends/traycer.md", "**Classify `absent` before anything else."),
            ("backends/claude-native.md", "**Classify `absent` before anything else."),
        ):
            adapter = self.read(relative)
            bullet = _bullet(adapter, opener) or _line_starting(
                adapter, f"   1. {opener}"
            )
            self.assertIsNotNone(bullet, f"{relative}: no absent-classification step")

            sentences = re.split(r"(?<=\.)\s+(?=[A-Z`*\"])", bullet)
            assigning = [s for s in sentences if re.search(assigns, s)]
            self.assertTrue(assigning, f"{relative}: nothing assigns `{absent_cause}`")
            for sentence in assigning:
                with self.subTest(adapter=relative, sentence=sentence[:70]):
                    self.assertIn(
                        f"`{_COMPLETED}`",
                        sentence,
                        f"{relative} assigns `{absent_cause}` without naming "
                        f"`{_COMPLETED}`",
                    )

            # Inverse direction. Every one of the three sites in this round
            # named `truncated` while describing an empty read and named no
            # condition that licenses it — which is what made each of them
            # read as a misclassification to avoid rather than the rule.
            for sentence in sentences:
                if not re.search(_assigns(cut_cause), sentence):
                    continue
                with self.subTest(adapter=relative, sentence=sentence[:70]):
                    self.assertTrue(
                        any(f"`{c}`" in sentence for c in _TRUNCATING),
                        f"{relative} names `{cut_cause}` in the classification "
                        "step without naming a condition that licenses it: "
                        f"{sentence[:120]}",
                    )

    def test_absent_is_not_a_terminating_condition(self) -> None:
        # `absent` is a cause, not a fifth terminating condition — but the read
        # that established it still ran and its condition is recorded. `null`
        # is reserved for a lane never read at all, which is `pending`.
        #
        # This comment previously said the opposite: that a lane with no
        # correlated reply never ran a bounded read. It survived the revision
        # that made it false, sitting directly above assertions checking for
        # "still ran a bounded read" — the test body was right the whole time
        # and the comment above it contradicted every line of it.
        contract = self.read("backends/contract.md")
        state = self.read("templates/DEV_STATE_TEMPLATE.md")
        self.assertIn("`absent` is not a fourth terminating condition", contract)
        # ...but the read that established it still ran, and its condition is
        # recorded. `null` is reserved for a lane never read at all.
        self.assertIn("still ran a bounded read", contract)
        self.assertIn("Every bounded read records how it ended", state)
        self.assertIn("no bounded read has been performed yet", state)
        for adapter in ("backends/traycer.md", "backends/claude-native.md"):
            with self.subTest(adapter=adapter):
                self.assertIn("the read ran, so it ended somehow", self.read(adapter))

    def test_an_incomplete_verdict_cannot_discard_its_cause(self) -> None:
        # The verdict says the lane is unverified; the cause is the only field
        # that selects the remedy. A verdict with a null cause is the same
        # defect one level down from the one this PR closes - recording that
        # something failed while throwing away what to do about it.
        state = self.read("templates/DEV_STATE_TEMPLATE.md")
        self.assertIn(
            "A `report_back: incomplete` with a null cause is an invalid record.",
            state,
        )

    def test_a_clean_lane_is_recorded_not_left_blank(self) -> None:
        # Without a positive record, "reported and verified" and "never looked
        # at" are the same absence in the ledger - which is precisely the
        # failure the report-back contract exists to detect, reappearing in the
        # audit trail of the mechanism that detects it.
        state = self.read("templates/DEV_STATE_TEMPLATE.md")
        allowed = _line_starting(state, "Allowed `report_back` values:")
        self.assertIsNotNone(allowed, "template does not enumerate report_back values")
        for value in ("`pending`", "`complete`", "`incomplete`"):
            with self.subTest(value=value):
                self.assertIn(value, allowed)
        self.assertIn("A lane is never `complete` by never having been looked at.", state)
        self.assertIn(
            "A verified report is recorded too, not only a failed one.",
            self.read("backends/contract.md"),
        )

    def test_qa_and_reviewer_are_distinct_clean_current_head_lanes(self) -> None:
        qa = self.read("agents/qa-agent.md")
        reviewer = self.read("agents/reviewer.md")
        phase3_5 = self.read("phases/phase3.5.md")
        traycer = self.read("backends/traycer.md")
        phase4 = self.read("phases/phase4.md")
        contract = self.read("backends/contract.md")
        self.assertIn("stale_head", qa)
        self.assertIn("rtk git status --short", qa)
        self.assertIn("distinct agent ID", reviewer)
        self.assertIn("from the QA agent", reviewer)
        self.assertIn("distinct from the reviewer agent", qa)
        self.assertIn("rtk git status --short", reviewer)
        self.assertIn("headRefOid", reviewer)
        self.assertIn("correlation/response ID", reviewer)
        self.assertIn("rev-parse", phase3_5)
        self.assertIn("unchanged checkout", phase3_5)
        self.assertIn("unchanged PR head", phase3_5)
        self.assertIn("the reviewer agent ID", phase3_5)
        self.assertIn("immutable local `HEAD`", traycer)
        self.assertIn("invalidate QA, internal review, and external-review", phase4)
        self.assertIn("and the QA agent", phase4)
        self.assertIn("distinct from each other", contract)
        self.assertIn("backend_source", contract)

    def test_rate_limited_review_has_bounded_authorized_retries(self) -> None:
        external = self.read("phases/external-review.md")
        retry = external.split("### Rate-limited review retries\n", 1)[1].split(
            "### Deadline choices\n", 1
        )[0]
        schedule = {}
        for line in retry.splitlines():
            if line.startswith("| ") and "minutes |" in line:
                elapsed, action = [cell.strip() for cell in line.strip("|").split("|")]
                schedule[elapsed] = action
        self.assertEqual(schedule, {
            "15 minutes": "First retry",
            "30 minutes": "Second and final retry",
            "45 minutes": "End the response window and surface the explicit deadline choices once",
        })
        normalized = " ".join(retry.split())
        for requirement in (
            "only after an explicit rate-limit response",
            "authorizes re-requesting that specific reviewer",
            "One lead owns retries",
            "submitted reviews, review threads, and substantive PR comments",
            "a PR comment does not itself satisfy the inspector",
            "There is no third automatic retry",
            "Observe an actively progressing review without sending a duplicate request",
            "do not send catch-up requests",
            "If the vendor specifies a later retry time",
            "Polling or an acknowledgement never resets the budget",
            "carry the remaining budget and deadline forward",
            "Only an explicit extension renews an exhausted episode",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, normalized)

    def test_rate_limit_breakpoint_substitutes_a_family_distinct_reviewer(self) -> None:
        """Issue #48: the retry loop needs an exit that is not the bypass.

        After 3 consecutive rate-limits on one PR the SOP itself authorizes a
        recorded substitution. The substitute must add family diversity, so it
        never takes the internal reviewer's seat, and its completed review
        satisfies the gate as a review rather than creating bypass debt.
        """
        external = self.read("phases/external-review.md")
        retry = external.split("### Rate-limited review retries\n", 1)[1].split(
            "### Deadline choices\n", 1
        )[0]
        section = " ".join(retry.split("#### Rate-limit breakpoint\n", 1)[1].split())
        for requirement in (
            # Trigger, loop stop, and what the count is and is not.
            "After 3 consecutive rate-limited responses to review requests on the same PR",
            "send that reviewer no further retries",
            "`external_reviewer_unavailable: rate_limited`",
            "The count is kept per PR per reviewer, across heads and wait episodes, not per session",
            "Only a completed review or an explicit non-rate-limit decline from that reviewer resets the count",
            "an acknowledgement or a processing or in-progress reply neither resets nor increments it",
            # A reviewer that reports each rate limit by editing one summary
            # comment must still reach the threshold.
            "An in-place edit that reports a new rate-limit event counts as a new rate-limited response",
            "a reviewer that reports each rate limit by editing a single summary comment still reaches the threshold",
            "a new event is a new head, a new limit window or reset time, or a response to a new review request (a retry, or the re-request the Head-Commit Invariant obligates)",
            "Only a re-render of the same event (same head, same window, no new request) does not count again.",
            # Issue #69: an unrequested rate-limit at a new head counts once.
            "An automatic rate-limit report at a new head, with no explicit request from the lead, counts once toward the threshold",
            "so a rate-limited response to it counts as well",
            "The breakpoint is an exit from the retry loop, not a bypass",
            # Where the substitute comes from, on either backend.
            "The review fallback chain is the ordered set of available reviewer routes the lead can dispatch on the selected backend",
            "on Traycer, the agent selection guide's review routes",
            "on Claude-native, any distinct-family reviewer the lead can actually dispatch",
            # Family distinctness and the no-qualifying-family case.
            "The substitute is a fresh identity whose model family differs from the implementation worker, the QA lane, and the internal reviewer",
            "never reuses the internal reviewer's seat",
            "the gate stays `pending` and the lead reports it, with `external_reviewer_unavailable` on the PR record",
            "never falls back to the bypass or to a same-family reviewer",
            "the lead never bypasses unilaterally",
            "deadline choice 2 (an explicit re-request) and choice 3 (a user-approved bypass) remain available",
            # What a completed substitute review is, and the seats it fills.
            "a clear status field or an acknowledgement is not a review",
            "apply the Head-Commit Invariant to it as to any review",
            "satisfies the external gate as a review, not a bypass",
            "creates no review debt",
            "It routes a `pending` gate as `clear` only while no finding, the substitute's included, is blocking or awaiting disposition; see **Result Routing**",
            "It fills only the rate-limited reviewer's seat",
            "never satisfies a `Required reviewers` entry or a required branch-protection check",
            "every other expected reviewer still gates",
            "still dispatch the substitute as review evidence; it does not fill that seat",
            "Where that reviewer is a required GitHub check, the breakpoint does not unblock merge",
            "this SOP never overrides GitHub branch protection",
            "the substitution record, not the inspector, fills its seat",
            "naming the model families of the implementation worker, the QA lane, and the internal reviewer",
            "one PR comment naming the rate-limit count, the substitute identity, and its model family",
            "reconcile its findings normally",
            "the substitution record stands",
            # A new head after a substitution.
            "The count carries across heads for the same PR and reviewer.",
            "the one re-request the Head-Commit Invariant obligates to the trusted reviewer",
            "that re-request is not a retry",
            "After a breakpoint has fired on that PR for that reviewer, the count is already at or above the threshold",
            "dispatches a fresh substitute for the new head without a second retry cycle",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, section)
        # The reversed round-1 rule must not come back.
        self.assertNotIn("edited in place counts once", section)
        # The shipped payload stays provider-neutral: roles and families only.
        # Backend names (Traycer, Claude-native) are adapter identifiers used
        # throughout `skills/dev/`, so they are not vendor names here.
        for vendor in (
            "Codex", "Kimi", "GLM", "Minimax", "CodeRabbit",
            "Kilo", "Copilot", "GPT", "Gemini",
            "Opus", "Sonnet", "Haiku", "Anthropic", "OpenAI",
        ):
            with self.subTest(vendor=vendor):
                self.assertNotIn(vendor, section)
        # B1: without a routing clause the inspector's `pending` never reaches
        # APPROVE, so the bypass would stay the only way to merge.
        # Scope exactly as the validator's markdown_section does: an exact
        # `## Result Routing` heading line, ending at the next `## ` or EOF, so
        # a demoted or missing heading fails here too.
        routing_match = re.search(
            r"^## Result Routing$(.*?)(?=^## |\Z)", external, re.M | re.S
        )
        self.assertIsNotNone(routing_match, "external-review.md lacks a `## Result Routing` heading")
        routing = " ".join(routing_match.group(1).split())
        for token in (
            "whose only open seats are filled by a completed, current-head substitution routes as `clear`",
            "no finding, the substitute's included, is blocking or awaiting disposition",
            "a substitute at an older head does not count",
            "A completed, current-head substitute review with a blocking finding routes as `blocking`, not as any other `pending`.",
            "take the rate-limit breakpoint when reached",
        ):
            with self.subTest(routing=token):
                self.assertIn(token, routing)
        rating = " ".join(
            self.read("phases/phase4.md")
            .split("## Review Rating\n", 1)[1]
            .split("## Review after fixes\n", 1)[0]
            .split()
        )
        for token in (
            "whose only open seats are filled by a completed, current-head substitution routes as `clear`",
            "triage every active current-head trusted-reviewer finding and every finding of a completed current-head substitute review",
            "per **Rate-limit breakpoint** in the external-review gate",
            "no finding, the substitute's included, is blocking or awaiting disposition",
            "a substitute at an older head does not count",
            "a completed, current-head substitute review with a blocking finding → REQUEST CHANGES",
            "Any other `pending`, or `incomplete`, external review → do not merge",
            "a `pending` routed as `clear` by a completed, current-head substitution counts",
        ):
            with self.subTest(rating=token):
                self.assertIn(token, rating)
        traycer = " ".join(self.read("backends/traycer.md").split())
        for token in (
            "Do not add cost, rate-limit, or performance routing heuristics.",
            "is a documented SOP exit, not a routing heuristic",
        ):
            with self.subTest(traycer=token):
                self.assertIn(token, traycer)
        raw_state = self.read("templates/DEV_STATE_TEMPLATE.md")
        state = " ".join(raw_state.split())
        # Slice the schema list itself (its one line), not the prose below it,
        # and not at the first "." so a dotted field name cannot truncate it.
        schema = raw_state.split("Each `pull_requests` entry records:", 1)[1].split("\n", 1)[0]
        self.assertIn("`next_action`", schema)
        # Each field is pinned on its own so reordering the schema list is safe.
        for field in (
            "`consecutive_rate_limits`",
            "`external_reviewer_unavailable`",
            "`external_review_substitutions`",
        ):
            with self.subTest(field=field):
                self.assertIn(field, schema)
        for token in (
            "only a completed review or an explicit non-rate-limit decline from that reviewer resets it to 0",
            "`external_reviewer_unavailable: rate_limited`",
            "it is the ledger record of the still-`pending` gate",
            "the model families of the substitute, the implementation worker, the QA lane, and the internal reviewer",
            "A substitution is a completed review, not an `approved_bypasses` or `review_debt` entry.",
        ):
            with self.subTest(token=token):
                self.assertIn(token, state)

    def test_correction_review_keeps_current_evidence_and_full_review_triggers(self) -> None:
        phase4 = self.read("phases/phase4.md")
        correction = phase4.split("## Review after fixes\n", 1)[1].split(
            "## Merge Order\n", 1
        )[0]
        normalized = " ".join(correction.split())
        for requirement in (
            "Both QA and internal review must issue fresh results",
            "Read the full diff",
            "reconcile every known finding",
            "A push alone does not resolve or supersede a finding",
            "If there is no usable prior review/base, perform the full review",
            "focus internal QA and review on changed behavior",
            "Reopen the full review if scope, interfaces, architecture, a safety boundary, or material dependencies changed",
            "or if the affected scope is uncertain",
            "Obtain the full required Verification Gate result at the final head",
            "distinct from implementation and each other",
            "reviewed base, target head, review scope, executed checks and remaining findings",
            "Internal delta review does not satisfy external review",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, normalized)

    def test_correction_review_entry_points_share_the_phase4_procedure(self) -> None:
        for relative in (
            "SKILL.md",
            "phases/phase3.5.md",
            "phases/external-review.md",
            "agents/qa-agent.md",
            "agents/reviewer.md",
            "agents/report-back.md",
            "backends/contract.md",
            "templates/DEV_STATE_TEMPLATE.md",
        ):
            with self.subTest(relative=relative):
                text = " ".join(self.read(relative).split())
                self.assertIn("Review after fixes", text)
                self.assertIn("${CLAUDE_SKILL_DIR}/phases/phase4.md", text)

    def test_fix_batches_do_not_promote_advisory_findings_to_blockers(self) -> None:
        phase4 = " ".join(self.read("phases/phase4.md").split())
        for requirement in (
            "First classify whether a finding blocks delivery",
            "An easy fix is not necessarily blocking",
            "Record advisory findings with a rationale and follow-up location",
            "consolidate findings already available from QA, internal review, and external review",
            "Dispatch confirmed blockers together",
            "Do not wait indefinitely",
            "or delay urgent security/data-loss containment",
            "avoid extra commits solely for advisory cleanup",
            "all blocking DELEGATE-FIX findings assigned to this PR are resolved",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, phase4)
        external = " ".join(self.read("phases/external-review.md").split())
        self.assertIn("a blocked merge does not block unrelated work", external)
        self.assertIn("record the next wake/action and yield", external)
        self.assertIn("A current-head `CHANGES_REQUESTED` remains blocking", external)
        self.assertIn("A timeout bypass cannot clear a known actionable finding", external)

    def test_ask_once_contract_pins_section_and_each_outcome(self) -> None:
        """Issue #82: the ask-once contract has a single load-bearing
        SOP paragraph and three discrete outcomes (trust, ignore,
        decide later) whose wording names the recording site.

        Issue #82 acceptance criterion: deleting the section, or
        any one outcome, fails both the validator and the unit
        suite. The test pins each load-bearing sentence (validator
        pins added in `scripts/validate_skill.py` per-file policy
        for `phases/external-review.md`; this test exercises the
        same tokens against the live file). Mutations are
        performed outside the worktree and are not part of this
        test body.
        """
        external = " ".join(self.read("phases/external-review.md").split())
        for requirement in (
            # Section heading and the rule's scope.
            "Ask once about unknown review bots, record the answer",
            "asks the user **once per repository**",
            # Each of the three outcomes names the recording
            # site, so a reworded outcome still has to name it
            # to keep the validator and the suite green.
            "trust → `Additional reviewer identities`",
            "ignore → `Ignored reviewers`",
            "decide later → a `Pending reviewer decisions` line",
            # The no-re-ask rule: a recorded `Pending reviewer
            # decisions` login does not re-trigger the question.
            "A login already listed under `Pending reviewer decisions` is **not re-asked**",
            # The trust-or-ignore rule: the lead never adds
            # without the user's answer.
            "The lead never adds an identity without the user's answer",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, external)

    def test_ask_once_mutation_each_outcome_fails_validation(self) -> None:
        """A2 rewrite: B6 acceptance criterion, with per-case
        pristine copies and no suite recursion.

        Deleting the ask-once section or any one of its three
        recorded outcomes must fail the validator. Each case
        starts from a PRISTINE copy of the Skill (no cumulative
        state across mutations) and performs a REAL line deletion
        (not a substring replacement that leaves the key intact).

        Hard rules observed:
          - the test NEVER runs the test suite (no `unittest
            discover`, `verify.sh`, `pytest`); it only invokes
            `scripts/validate_skill.py` on a temp copy of the
            Skill, which is the one mutation-proof mechanism
            the rules permit inside the suite;
          - mutations run ONE at a time, sequentially, from a
            fresh `tempfile.TemporaryDirectory()` per case, so a
            failure in one case cannot contaminate the next;
          - the negative control (an unrelated additive change)
            must NOT fail the validator, proving the assertions
            are scoped to the ask-once contract rather than to
            the file in general.

        The seven deletions:
          1. the entire `### Ask once` section from
             `phases/external-review.md`;
          2. the `trust -> Additional reviewer identities` line;
          3. the `ignore -> Ignored reviewers` line;
          4. the `decide later -> Pending reviewer decisions` line;
          5. the `not re-asked` paragraph;
          6. the `Pending reviewer decisions: none` line in
             `templates/PROJECT_CONTEXT_TEMPLATE.md`;
          7. the `Pending reviewer decisions: none` line in
             the root `PROJECT_CONTEXT.md`.
        """
        import re as _re
        import shutil
        import subprocess
        import sys as _sys
        import tempfile
        from pathlib import Path as _Path

        # The validator pins tokens in three files: the Skill's
        # `phases/external-review.md`, the Skill's
        # `templates/PROJECT_CONTEXT_TEMPLATE.md`, and the root
        # `PROJECT_CONTEXT.md`. The first two are reachable via
        # `--skill-dir`; the third is resolved against the
        # validator's own parent directory. To exercise all
        # three without touching the worktree, each case copies
        # the minimum tree into a fresh tempdir and runs the
        # validator against the copy.

        COPIED = (
            "scripts/validate_skill.py",
            "skills",
            "PROJECT_CONTEXT.md",
            "CHANGELOG.custom.md",
        )

        def fresh_copy(scratch_path: _Path) -> None:
            for relative in COPIED:
                source = ROOT / relative
                if source.is_dir():
                    shutil.copytree(source, scratch_path / relative)
                else:
                    target_file = scratch_path / relative
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target_file)

        def run_validator(scratch_path: _Path):
            return subprocess.run(
                [
                    _sys.executable,
                    "scripts/validate_skill.py",
                    "--skill-dir",
                    str(scratch_path / "skills" / "dev"),
                ],
                capture_output=True,
                text=True,
                check=False,
                cwd=scratch_path,
            )

        # Each case runs in its own fresh tempdir so there is
        # zero cumulative state between mutations (A2). The
        # order of cases is deterministic; each is a
        # sub-test so a failure names the exact mutation.
        cases = (
            (
                "section",
                "skills/dev/phases/external-review.md",
                lambda text: _re.sub(
                    r"^### Ask once about unknown review bots, record the answer"
                    r".*?(?=^## |\Z)",
                    "",
                    text,
                    count=1,
                    flags=_re.M | _re.S,
                ),
                "deleting the ask-once section must fail the validator",
            ),
            (
                "trust-outcome",
                "skills/dev/phases/external-review.md",
                lambda text: text.replace(
                    "trust \u2192 `Additional reviewer identities`",
                    "MUTATION: trust outcome deleted",
                ),
                "deleting the trust outcome must fail the validator",
            ),
            (
                "ignore-outcome",
                "skills/dev/phases/external-review.md",
                lambda text: text.replace(
                    "ignore \u2192 `Ignored reviewers`",
                    "MUTATION: ignore outcome deleted",
                ),
                "deleting the ignore outcome must fail the validator",
            ),
            (
                "decide-later-outcome",
                "skills/dev/phases/external-review.md",
                lambda text: text.replace(
                    "decide later \u2192 a `Pending reviewer decisions` line",
                    "MUTATION: decide-later outcome deleted",
                ),
                "deleting the decide-later outcome must fail the validator",
            ),
            (
                "not-re-asked-paragraph",
                "skills/dev/phases/external-review.md",
                lambda text: _re.sub(
                    r"A login already listed under `Pending reviewer decisions` "
                    r"is \*\*not re-asked\*\*.*?(?=^A login already listed|^\n|"
                    r"^## |\Z)",
                    "",
                    text,
                    count=1,
                    flags=_re.M | _re.S,
                ),
                "deleting the not-re-asked paragraph must fail the validator",
            ),
            (
                "template-line",
                "skills/dev/templates/PROJECT_CONTEXT_TEMPLATE.md",
                lambda text: text.replace(
                    "**Pending reviewer decisions**: none",
                    "**Pending reviewer decisions**: MUTATION",
                ),
                "deleting the template's `Pending reviewer decisions` "
                "line must fail the validator",
            ),
            (
                "project-context-line",
                "PROJECT_CONTEXT.md",
                lambda text: text.replace(
                    "**Pending reviewer decisions**: none",
                    "**Pending reviewer decisions**: MUTATION",
                ),
                "deleting PROJECT_CONTEXT.md's `Pending reviewer "
                "decisions` line must fail the validator",
            ),
        )

        for name, relative, mutate, message in cases:
            with self.subTest(mutation=name):
                with tempfile.TemporaryDirectory() as scratch:
                    scratch_path = _Path(scratch)
                    fresh_copy(scratch_path)
                    target = scratch_path / relative
                    original = target.read_text(encoding="utf-8")
                    # Negative control: an unrelated additive
                    # change must NOT fail the validator. Run
                    # once per case to prove the scratch is
                    # clean and the assertions are scoped. The
                    # control is applied to a file the
                    # validator's routing-section check does
                    # not touch (PROJECT_CONTEXT.md is
                    # routing-section-sensitive and would
                    # reject any trailing content in its last
                    # section), so the control targets
                    # CHANGELOG.custom.md instead.
                    control_target = scratch_path / "CHANGELOG.custom.md"
                    control_original = control_target.read_text(encoding="utf-8")
                    control_target.write_text(
                        control_original + "\n<!-- unrelated additive change -->\n",
                        encoding="utf-8",
                    )
                    control = run_validator(scratch_path)
                    self.assertEqual(
                        control.returncode, 0,
                        f"additive control must not fail validator: "
                        f"stderr={control.stderr}",
                    )
                    control_target.write_text(control_original, encoding="utf-8")
                    # Now the real deletion.
                    target.write_text(mutate(original), encoding="utf-8")
                    result = run_validator(scratch_path)
                    self.assertNotEqual(
                        result.returncode, 0,
                        message,
                    )

    def test_bypass_is_scoped_to_unavailable_review_and_records_commit_range(self) -> None:
        """Issue #33: bypass must never excuse a self-invalidated review.

        A review the author's own fix commits moved past is not
        "unavailable" — that case obligates a re-request at the new head,
        not a bypass. Where a bypass is still used, the recorded debt must
        name the exact unreviewed commit range, not just the PR.
        """
        external = " ".join(self.read("phases/external-review.md").split())
        for requirement in (
            "A bypass is only for a review that never arrived or is unavailable",
            "never for a review that arrived and was invalidated by the author's own response",
            "obligates a re-request at the new head, not a bypass",
            "never one invalidated by the author's own response",
            "the exact unreviewed commit range",
            # Two forms are required: a review that completed before the fix
            # commits anchors the range at the reviewed head, but a review
            # that never completed at all has no reviewed head to anchor
            # it — that case must fall back to the PR's base head, or the
            # range degenerates to empty while every commit is unreviewed.
            "<reviewed-head>..<merged-head>",
            "<base-head>..<merged-head>",
            "no review ever completed on the PR",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, external)

        state = self.read("templates/DEV_STATE_TEMPLATE.md")
        self.assertIn("the exact unreviewed commit range", state)
        self.assertIn("<reviewed-head>..<merged-head>", state)
        self.assertIn("<base-head>..<merged-head>", state)
        self.assertIn("no review ever completed on the PR", state)
        self.assertIn("the PR number alone is not sufficient", state)

        phase5 = self.read("phases/phase5.md")
        self.assertIn("### External-Review Bypasses", phase5)
        self.assertIn(
            "reported explicitly, including `0`",
            phase5,
        )
        self.assertIn(
            "visible as a pattern across rounds, not only per PR",
            phase5,
        )
        # Issue #69: substitutions are counted next to bypasses, separately.
        phase5_text = " ".join(phase5.split())
        for token in (
            "also report the count of rate-limit breakpoint substitutions this round",
            "`external_review_substitutions` entries in `.agent/dev-state.md`",
            "Keep it separate from the bypass count: a substitution is a completed review, not a bypass",
        ):
            with self.subTest(phase5_substitutions=token):
                self.assertIn(token, phase5_text)

    def test_post_merge_verification_is_unconditional_and_pins_the_ac_language(
        self,
    ) -> None:
        """Issue #26: nothing re-examined merged code against the closed
        Issue's acceptance criteria, and auto-closure by a merge keyword was
        read as completion evidence. The unconditional step must exist, must
        not be a merge gate, and must state the hazard explicitly rather than
        leaving it implied.
        """
        phase4 = " ".join(self.read("phases/phase4.md").split())
        for requirement in (
            "Post-Merge Verification (unconditional)",
            "This is not a merge gate",
            "the merge commit's tree hash",
            "the tree hash of the **actual tested subject**",
            "obtain the full recorded Verification Gate result",
            "A scoped recheck never replaces the full gate here.",
            "Auto-closure by a merge keyword is never evidence of completion",
            "merge_sha",
            "gate_result",
            "criteria_verdict",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, phase4)

        # Cross-references the bypass debt rule rather than restating its
        # commit-range syntax — duplicating it here is exactly the drift the
        # single-source-of-truth tokens above exist to prevent.
        self.assertIn("external-review.md", phase4)
        self.assertNotIn("<reviewed-head>..<merged-head>", phase4)
        self.assertNotIn("<base-head>..<merged-head>", phase4)

        phase5 = self.read("phases/phase5.md")
        self.assertIn("### Post-Merge Verification", phase5)
        self.assertIn("post-merge verification records", phase5)
        # The retro reads the records phase4.md's step produces; it must not
        # restate the check itself.
        self.assertIn(
            "do not repeat the check itself",
            phase5,
        )

        skill_section = _markdown_section(self.read("SKILL.md"), "## Global Rules")
        self.assertIsNotNone(skill_section, "SKILL.md has no Global Rules section")
        self.assertIn(
            "the lead reconciles the merged tree and re-confirms the closed "
            "Issue's acceptance criteria",
            skill_section,
        )
        self.assertIn("${CLAUDE_SKILL_DIR}/phases/phase4.md", skill_section)

        state = self.read("templates/DEV_STATE_TEMPLATE.md")
        for requirement in (
            "Post-merge verification record schema",
            "merge_sha",
            "gate_result",
            "criteria_verdict",
            "applies_verbatim",
            "Auto-closure by a merge keyword is never evidence of completion",
            "unmet_criteria",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, state)

    def test_implementation_lanes_carry_the_reuse_first_ladder(self) -> None:
        for relative in ("agents/worker-new.md", "agents/worker-fix.md"):
            prompt = self.read(relative)
            with self.subTest(prompt=relative):
                self.assertIn("Reuse-first ladder", prompt)
                self.assertIn("already in the codebase", prompt)
                self.assertIn("standard library", prompt)
                self.assertIn("already-installed dependency", prompt)
                self.assertIn("lowest rung", prompt)

    def test_safety_carveout_accompanies_the_ladder_in_both_lanes(self) -> None:
        # The ladder without the carve-out reads as licence to delete guards in
        # the name of minimality, so the two must never drift apart.
        for relative in ("agents/worker-new.md", "agents/worker-fix.md"):
            prompt = self.read(relative)
            with self.subTest(prompt=relative):
                self.assertIn("Safety carve-out", prompt)
                self.assertIn(
                    "Minimizing scope must never mean removing a guard.", prompt
                )
                for guard in (
                    "Validation",
                    "error handling",
                    "security",
                    "accessibility",
                ):
                    self.assertIn(guard, prompt)

    def test_prototype_lanes_state_the_opposing_principle(self) -> None:
        # Inverted guard. A negative assertion over prose is unbounded: it
        # cannot enumerate every paraphrase of a ladder, and a test asserting
        # only that the wrong thing is absent cannot tell a working guard from
        # a vacuous one. Asserting the opposing principle means a future edit
        # adding reuse-first guidance must first delete a sentence saying the
        # opposite - a visible, guarded act rather than an addition that slips
        # past untouched.
        for relative in (
            "agents/worker-prototype-frontend.md",
            "agents/worker-prototype-backend.md",
        ):
            prompt = self.read(relative)
            with self.subTest(prompt=relative):
                self.assertIn("Exploration Stance", prompt)
                self.assertIn("Exploration favors breadth over minimality.", prompt)
                self.assertIn("does not apply in this lane", prompt)
                self.assertIn("This exclusion is deliberate", prompt)
                # Cheap backstop for a literal copy of the ladder. The positive
                # assertions above are the actual guard; these two are not.
                self.assertNotIn("Reuse-first ladder", prompt)
                self.assertNotIn("lowest rung", prompt)

    def test_reviewer_checks_for_over_engineering_as_advisory(self) -> None:
        reviewer = self.read("agents/reviewer.md")
        self.assertIn("over-engineering", reviewer)
        self.assertIn("speculative abstraction", reviewer)
        self.assertIn("reimplemented by hand", reviewer)
        self.assertIn("`advisory` unless", reviewer)

    def test_completion_claims_require_executed_output(self) -> None:
        report_back = self.read("agents/report-back.md")
        qa = self.read("agents/qa-agent.md")
        for prompt in (report_back, qa):
            self.assertIn("executed command's actual output", prompt)
            # Issue #134: replaces the retired `re-run the full Verification
            # Gate` pin; a fix is followed by a fresh gate result from each
            # check's one executor, not a by-role rerun.
            self.assertIn("obtain the full Verification Gate result again", prompt)
        # qa-agent.md owns the canonical wording; report-back cross-references
        # it rather than restating it.
        self.assertIn("Tool Capability Boundary", report_back)
        self.assertIn("agents/qa-agent.md", report_back)
        self.assertIn("canonical definition", qa)

    def test_qa_outcomes_cannot_read_absence_of_signal_as_a_pass(self) -> None:
        qa = self.read("agents/qa-agent.md")
        # No denominator, nothing executed, and an undetected framework are all
        # explicit outcomes rather than paths to an implicit pass.
        self.assertIn("qa_error: no acceptance criteria", qa)
        self.assertIn("qa_error: no verification executed", qa)
        self.assertIn("No test framework detected", qa)
        self.assertIn("never a silent skip", qa)
        # Limitations feed the result: each resolves to `inconclusive`,
        # a contestable `not_applicable`, or a blocking skipped step.
        self.assertIn("Limitations are load-bearing", qa)
        self.assertIn("blocks the pass", qa)

    def test_qa_criterion_that_cannot_be_evaluated_is_inconclusive(self) -> None:
        # Issue #135 AC-1: the coverage term's job (making "not executed"
        # visible) moved to the `inconclusive` reason, and the lane does not
        # pass on it.
        qa = self.read("agents/qa-agent.md")
        for outcome in ("pass", "fail", "inconclusive", "not_applicable"):
            self.assertIn(f"`{outcome}`", qa)
        self.assertIn("pass / fail / inconclusive / not_applicable", qa)
        self.assertIn("A criterion that cannot be evaluated is `inconclusive`.", qa)
        self.assertIn("Name the missing infrastructure or the missing evaluator", qa)
        self.assertIn("The lane does not pass on an `inconclusive` entry.", qa)
        self.assertIn("is an `inconclusive` reason, not a deduction and not a pass", qa)
        # Pending/missing/skipped/cancelled/stale CI evidence is never `pass`.
        self.assertIn("pending, missing, skipped, cancelled or stale", qa)

    def test_qa_required_check_or_criterion_cannot_be_not_applicable(self) -> None:
        # Issue #135 AC-2.
        qa = self.read("agents/qa-agent.md")
        self.assertIn("A required check or criterion cannot be `not_applicable`.", qa)
        self.assertIn("`not_applicable` is available only to an optional check", qa)
        self.assertIn("with a stated reason the lead can contest", qa)

    def test_qa_records_evaluator_type_and_demonstration_rule(self) -> None:
        # Issue #135 AC-3: each criterion records its assigned evaluator type,
        # and a worker demonstration satisfies only a demonstration criterion.
        qa = self.read("agents/qa-agent.md")
        for evaluator in ("ci", "test", "demonstration", "independent reviewer", "human"):
            self.assertIn(evaluator, qa)
        self.assertIn(
            "ci / test / demonstration / independent reviewer / human", qa
        )
        self.assertIn("| Criterion | Outcome | Evaluator type | Executor | Evidence ref | Reason |", qa)
        self.assertIn(
            "A worker demonstration satisfies only a criterion whose assigned "
            "evaluator is the demonstration",
            qa,
        )
        self.assertIn("A criterion passes only by its assigned evaluator.", qa)

    def test_qa_lane_conclusion_is_outcomes_and_material_findings(self) -> None:
        qa = self.read("agents/qa-agent.md")
        self.assertIn("**Lane conclusion.**", qa)
        self.assertIn("no material finding is unresolved", qa)
        self.assertIn("The conclusion is determined by the outcomes and findings alone.", qa)
        # Materiality, not the severity label, decides whether a finding blocks;
        # a Medium finding is not newly blocking.
        self.assertIn("Materiality decides whether a finding blocks, not its label.", qa)
        self.assertIn("Recorded finding, no deduction", qa)

    def test_qa_health_score_is_an_optional_diagnostic(self) -> None:
        # Issue #135 AC-4: the score line is optional, absence is valid, it
        # never decides, and the validator does not require it. The numeric
        # gate and its coverage term must not come back as a pass condition.
        qa = self.read("agents/qa-agent.md")
        phase = self.read("phases/phase3.5.md")
        report_back = self.read("agents/report-back.md")
        self.assertIn("The health score is optional.", qa)
        self.assertIn("Its absence is valid", qa)
        self.assertIn("never decides the conclusion", qa)
        for retired in (
            "Require a score of at least 80",
            "Calculate the health score",
            "The coverage term",
            "coverage deduction",
            "10 per PASSED test-executable acceptance criterion",
        ):
            with self.subTest(retired=retired):
                self.assertNotIn(retired, qa)
        for text in (phase, report_back):
            self.assertNotIn("passing score", text)
            self.assertNotIn("`QA ✓ Health: [N]/100`", text)
        self.assertIn("never decides", phase)
        self.assertIn("QA ✓ Pass — outcomes:", phase)
        self.assertIn("QA ✓ Pass — outcomes:", report_back)
        # The validator must not require the score line.
        validator = (ROOT / "scripts" / "validate_skill.py").read_text(encoding="utf-8")
        current = _parse_required_policy(validator)
        self.assertFalse([t for t in current if "Health:" in t or "/100" in t])

    def test_qa_outcome_detail_stays_inside_the_seven_section_contract(self) -> None:
        # Issue #135 AC-5: the transport contract is unchanged; outcome detail
        # lives inside the existing sections.
        report_back = self.read("agents/report-back.md")
        flat = " ".join(report_back.split())
        self.assertIn("live inside the existing sections 4 and 5, not in an added section", flat)
        self.assertEqual(len(re.findall(r"^\d\. \*\*", report_back.split("## Evidence discipline")[0], re.M)), 7)

    def test_qa_executes_the_whole_gate_not_only_the_test_suite(self) -> None:
        # Requiring only the test suite let a lane pass with the gate's lint
        # and type checks never executed and nothing recording that they had
        # not run - absence of execution reading as satisfaction, inside the
        # file written to prevent exactly that.
        qa = self.read("agents/qa-agent.md")
        self.assertIn("Account for the full Verification Gate.", qa)
        self.assertIn("Reading the gate is not running it.", qa)
        self.assertIn("the command with the exit code it returned", qa)
        self.assertIn("Any gate command that fails fails QA.", qa)
        # A project with no recorded gate is a finding, not a silent skip.
        self.assertIn("records no Verification Gate", qa)
        # The report has somewhere to put the evidence.
        self.assertIn("### Verification Gate", qa)

    def test_check_ownership_is_declared_by_job_and_consumed_by_every_role(self) -> None:
        """Issue #134: one executor per check; roles cite CI evidence."""
        project = " ".join((ROOT / "PROJECT_CONTEXT.md").read_text(encoding="utf-8").split())
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        release = (ROOT / ".github" / "workflows" / "release-gate.yml").read_text(
            encoding="utf-8"
        )
        # The ownership table names real job names, so a renamed job breaks
        # this test instead of silently orphaning the declaration.
        for job in ("Skill validation", "Shell validation", "Packaging validation"):
            with self.subTest(job=job):
                self.assertIn(f"name: {job}", ci)
                self.assertIn(f"job `{job}`", project)
        for job in ("PowerShell installer", "Strict plugin validation"):
            with self.subTest(job=job):
                self.assertIn(f"name: {job}", release)
                self.assertIn(f"`{job}`", project)
        self.assertIn("name: Bash installer (${{ matrix.os }})", release)
        self.assertIn("`Bash installer (ubuntu-latest)`", project)
        self.assertIn("`Bash installer (macos-latest)`", project)
        self.assertIn("**Check ownership**", project)
        self.assertIn("No mandatory worker pre-push gate exists in this policy today.", project)

        phase4 = " ".join(self.read("phases/phase4.md").split())
        for requirement in (
            "## Check Ownership and CI Evidence",
            "**One executor per check.**",
            "A lane may cite a CI run it read by id, never one it assumes.",
            "the **tested subject** is established",
            "Pending CI never triggers local execution",
            "Missing, skipped, cancelled, failed, incomplete or stale evidence",
            "is **incomplete** and is never read as a pass",
            "A recorded reason alone is not authority.",
            "one designated executor",
            "records the reason, scope (the checks run), tested subject, environment and result",
            "A local pass never replaces required CI or erases a known failure.",
            "A mandatory pre-push requirement already in project policy",
            "until explicitly amended",
        ):
            with self.subTest(phase4=requirement):
                self.assertIn(requirement, phase4)

        for relative in ("agents/qa-agent.md", "agents/report-back.md"):
            prompt = " ".join(self.read(relative).split())
            with self.subTest(prompt=relative):
                self.assertIn("One executor per check.", prompt)
                self.assertIn("Check Ownership and CI Evidence", prompt)
                self.assertIn("run, job and attempt", prompt)
        qa = " ".join(self.read("agents/qa-agent.md").split())
        self.assertIn("leaves its verdict pending under the existing wait bounds", qa)
        self.assertIn("with no automatic local fallback", qa)
        self.assertIn("leaves required coverage incomplete and is never read as a pass", qa)

        # Workers run focused checks and project-required pre-push
        # prerequisites; the generic full local suite is gone.
        for relative in ("agents/worker-new.md", "agents/worker-fix.md"):
            prompt = " ".join(self.read(relative).split())
            with self.subTest(prompt=relative):
                self.assertIn("one executor per check", prompt)
                self.assertIn("Check Ownership and CI Evidence", prompt)
                self.assertIn("any prerequisite `PROJECT_CONTEXT.md` requires before a push", prompt)
                self.assertNotIn("run the full test suite", prompt)
                self.assertNotIn("rerun the full", prompt)

    def test_report_back_keeps_seven_sections_after_ci_evidence_change(self) -> None:
        report_back = self.read("agents/report-back.md")
        headings = re.findall(r"^\d\. \*\*([^*]+)\*\*", report_back, re.M)
        self.assertEqual(
            headings[:7],
            [
                "Outputs",
                "Commands + exit codes",
                "Deviations",
                "Quality-gate self-assessment",
                "Acceptance criteria",
                "Evidence",
                "Scope / ownership",
            ],
        )

    def test_validator_fails_when_ownership_sentences_are_removed(self) -> None:
        """Issue #134 AC-6: the validator, not only this suite, fails without them.

        Runs `scripts/validate_skill.py` on a fresh temp copy per mutation,
        never the test suite, one case at a time.
        """
        import shutil
        import subprocess
        import sys as _sys
        import tempfile

        def run_case(relative: str, old: str) -> subprocess.CompletedProcess:
            with tempfile.TemporaryDirectory() as scratch:
                scratch_path = Path(scratch)
                (scratch_path / "scripts").mkdir()
                shutil.copy2(ROOT / "scripts" / "validate_skill.py", scratch_path / "scripts")
                shutil.copytree(ROOT / "skills", scratch_path / "skills")
                shutil.copy2(ROOT / "PROJECT_CONTEXT.md", scratch_path / "PROJECT_CONTEXT.md")
                shutil.copy2(ROOT / "CHANGELOG.custom.md", scratch_path / "CHANGELOG.custom.md")
                target = scratch_path / "skills" / "dev" / relative
                text = target.read_text(encoding="utf-8")
                self.assertIn(old, text)
                target.write_text(text.replace(old, "MUTATION: sentence removed"), encoding="utf-8")
                return subprocess.run(
                    [
                        _sys.executable,
                        "scripts/validate_skill.py",
                        "--skill-dir",
                        str(scratch_path / "skills" / "dev"),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    cwd=scratch_path,
                )

        cases = (
            ("agents/qa-agent.md", "One executor per check.", "One executor per check."),
            ("agents/report-back.md", "One executor per check.", "One executor per check."),
            ("phases/phase4.md", "**One executor per check.**", "One executor per check."),
            (
                "agents/qa-agent.md",
                "**Reading the gate is not running it.**",
                "Reading the gate is not running it.",
            ),
        )
        for relative, old, expected in cases:
            with self.subTest(file=relative, sentence=expected):
                result = run_case(relative, old)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn(expected, result.stderr + result.stdout)

    def test_ci_evidence_example_parses_and_separates_head_from_tested_subject(
        self,
    ) -> None:
        """Issue #134 AC-7: the worked ledger example is valid and honest."""
        import subprocess
        import sys as _sys
        import tempfile

        template = self.read("templates/DEV_STATE_TEMPLATE.md")
        blocks = re.findall(
            r"^## CI evidence record schema.*?^```yaml\n(.*?)^```", template, re.M | re.S
        )
        self.assertEqual(len(blocks), 1, "expected one worked ci_runs example")
        example = blocks[0]
        ledger = (
            "---\nschema_version: 2\nrun_id: example\nrun_status: active\n"
            + example
            + "---\n"
        )
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "dev-state.md"
            path.write_text(ledger, encoding="utf-8")
            result = subprocess.run(
                [
                    _sys.executable,
                    str(SKILL / "scripts" / "dev_state.py"),
                    "--validate",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

        head = re.search(r"^    headRefOid: (\w+)$", example, re.M)
        tested = re.search(
            r"^        tested_subject:\n          sha: (\w+)\n          kind: (\w+)\n"
            r"          head: (\w+)\n          base_oid: (\w+)$",
            example,
            re.M,
        )
        self.assertIsNotNone(head)
        self.assertIsNotNone(tested)
        tested_sha, kind, tested_head, tested_base = tested.groups()
        self.assertEqual(kind, "merge_ref")
        self.assertNotEqual(head.group(1), tested_sha)
        self.assertEqual(head.group(1), tested_head)
        self.assertIn(f"base_oid: {tested_base}", example)
        for field in ("run:", "job:", "attempt:", "definition_rev:", "environment:",
                      "conclusion:", "observed_at:", "applicability:"):
            with self.subTest(field=field):
                self.assertIn(field, example)
        # Additive under schema_version 2, and the post-merge record compares
        # the actual tested subject rather than the PR head.
        self.assertIn("`ci_runs` is additive under `schema_version: 2`", template)
        self.assertIn("the tree hash of the recorded `tested_subject`", " ".join(template.split()))
        self.assertIn("A match against the PR head's tree is not a match", " ".join(template.split()))

    def test_project_context_defers_role_routing_to_the_selection_guide(self) -> None:
        # PROJECT_CONTEXT.md outranks the agent selection guide in the adapter's
        # resolution order, so any route restated here silently overrides newer
        # policy. The section must defer, and record only the one constraint
        # that is a property of this project rather than a routing preference.
        # Collapse wrapping first: these are prose sentences that wrap, so a
        # raw substring check would fail on a harmless reflow rather than on a
        # policy change.
        policy = " ".join(
            (ROOT / "PROJECT_CONTEXT.md").read_text(encoding="utf-8").split()
        )
        self.assertIn("The agent selection guide governs role routing.", policy)
        self.assertIn("outranks the guide in the adapter's resolution order", policy)
        self.assertIn(
            "the lead runs on the harness that invokes `/dev`: Claude Code on "
            "either backend, or Codex or OpenCode under the Traycer backend "
            "only (ADR-013).",
            policy,
        )
        # The retired Claude-only wording must not come back (Issue #90).
        self.assertNotIn(
            "the lead runs on the `claude` harness, because the lead is what invokes",
            policy,
        )
        self.assertIn("provider-neutral", policy)
        # The exact stale line this replaced, which routed every role to the
        # backend lead and so overrode the guide's per-role choices.
        self.assertNotIn(
            "use the selected backend's lead route for every role", policy
        )

    def test_routing_section_contains_only_approved_content(self) -> None:
        # Structural, not lexical. A denylist of harness names can only reject
        # the names someone thought of - `traycer`, `cursor`, or a route with
        # no harness name at all walk straight through one. The section is
        # small and fixed, so its whole body is the guard: anything added
        # fails, whatever words it uses.
        validator = _validator_module()
        policy = (ROOT / "PROJECT_CONTEXT.md").read_text(encoding="utf-8")
        section = validator.routing_section(policy)
        self.assertIsNotNone(section, "Execution Routing Policy section is missing")
        self.assertEqual(
            validator.normalize(section),
            validator.ROUTING_SECTION_BODY,
            "Execution Routing Policy must contain its approved content and "
            "nothing else",
        )
        # Reflowing the section must not be a policy change.
        self.assertEqual(
            validator.normalize("  a\n\n b \n c  "),
            "a b c",
            "normalize must collapse whitespace so a rewrap is not a failure",
        )
        # A leftover denylist beside the structural check invites a future
        # reader to maintain the list, which restarts the failure mode.
        self.assertFalse(
            hasattr(validator, "ROUTING_IDENTIFIERS"),
            "ROUTING_IDENTIFIERS is subsumed by the structural check and must "
            "not be reintroduced",
        )

    def test_report_back_defines_the_seven_sections(self) -> None:
        report_back = self.read("agents/report-back.md")
        for section in REPORT_BACK_SECTIONS:
            with self.subTest(section=section):
                self.assertIn(section, report_back)

    def test_message_and_observe_rows_carry_the_report_back(self) -> None:
        # The operations table is what an adapter author reads first. If the
        # enforcement lives only in prose further down, an adapter can satisfy
        # the table and never implement it.
        contract = self.read("backends/contract.md")
        message = _table_row(contract, "message")
        observe = _table_row(contract, "observe")
        self.assertIsNotNone(message, "contract.md has no `message` operations row")
        self.assertIsNotNone(observe, "contract.md has no `observe` operations row")
        self.assertIn("report-back contract", message)
        self.assertIn("report-back shape verdict", observe)

    def test_contract_enforcement_section_names_every_section(self) -> None:
        contract = self.read("backends/contract.md")
        section = _markdown_section(contract, "## Report-back enforcement")
        self.assertIsNotNone(section, "contract.md missing Report-back enforcement")
        for name in REPORT_BACK_SECTIONS:
            with self.subTest(section=name):
                self.assertIn(name, section)
        # Both operations are specified in the one place that defines them.
        self.assertIn("`message`", section)
        self.assertIn("`observe`", section)
        self.assertIn(".agent/dev-state.md", section)
        self.assertIn("never infer completion", section)

    def test_envelope_names_the_leads_open_questions(self) -> None:
        # Issue #34: the element must be named in the list itself, not only
        # described in prose below it — a lane skimming the list has to see it
        # — and the "not mandatory" clause is what stops a lead manufacturing
        # an uncertainty to fill a required field.
        contract = self.read("backends/contract.md")
        envelope = _markdown_section(contract, "## Provider-neutral assignment envelope")
        self.assertIsNotNone(envelope, "contract.md missing the envelope section")
        self.assertIn(
            "acceptance criteria, the lead's open questions, plan-approval requirement",
            envelope,
        )
        self.assertIn("not a required field", envelope)
        self.assertIn("must not manufacture uncertainty", envelope)
        self.assertIn(
            "specification defect found before implementation beats a "
            "faithful implementation of a flawed spec",
            envelope,
        )
        # Phase 3 restates the same list for dispatch; the two must not drift.
        self.assertIn(
            "the lead's open questions (when genuine uncertainty exists)",
            self.read("phases/phase3.md"),
        )

    def test_lane_prompts_invite_challenge_of_the_specification(self) -> None:
        # Issue #34: the posture only changes behaviour if every lane that
        # reads the specification is told challenging it is in scope, so each
        # prompt carries the sentence in its own right rather than inheriting
        # it from one sibling.
        for relative in (
            "agents/worker-new.md",
            "agents/worker-fix.md",
            "agents/qa-agent.md",
        ):
            text = self.read(relative)
            with self.subTest(prompt=relative):
                self.assertIn("Challenging the specification is in scope", text)
        for relative in ("agents/worker-new.md", "agents/worker-fix.md"):
            with self.subTest(prompt=relative):
                self.assertIn(
                    "specification defect found before implementation beats a "
                    "faithful implementation of a flawed spec",
                    self.read(relative),
                )
        # QA runs after implementation, so its equivalent names the next round
        # instead — and grades against the criteria as written regardless.
        qa = self.read("agents/qa-agent.md")
        self.assertIn(
            "specification defect found before the next round beats a "
            "faithful pass over a flawed spec",
            qa,
        )
        self.assertIn("the objection waives nothing", qa)
        # The upstream half of Deviations: flagged before the departure.
        report_back = self.read("agents/report-back.md")
        self.assertIn(
            "including departures from the specification as written", report_back
        )
        self.assertIn("*before* departing from it", report_back)

    def test_silence_and_malformed_reply_share_one_verdict(self) -> None:
        # The round's central defect class in the agent transport: no reply read
        # as no problem. A lane that never replied must not be a lesser case
        # than one that replied badly - both leave the lane unverified. The
        # cause is recorded separately because the remedy differs, but a
        # separate cause must never become a separate verdict.
        contract = self.read("backends/contract.md")
        self.assertIn("Absence of a report is not a report.", contract)
        self.assertIn("the same verdict, not a lesser case", contract)
        self.assertIn("report_back: incomplete", contract)
        for cause in REPORT_BACK_CAUSES:
            with self.subTest(cause=cause):
                self.assertIn(f"`{cause}`", contract)

    def test_heading_presence_has_a_non_empty_floor(self) -> None:
        # Presence-only recognition is deliberate - the lead judges content -
        # but without this floor seven empty headings pass the adapter check,
        # which is the silent-lane failure wearing the shape of a report.
        contract = self.read("backends/contract.md")
        self.assertIn("A heading with no content under it is a missing section", contract)
        self.assertIn("case-insensitive", contract.lower())

    def test_the_presence_floor_is_itself_mechanical(self) -> None:
        # "Has content under it" is a judgment unless what counts as content is
        # stated, so the rule closing the empty-headings hole reopened it one
        # level up: a heading followed by a blank line, by the next heading, or
        # by an empty code fence were all arguable. The floor must be decidable
        # by two leads independently, which means naming its edge case rather
        # than leaving it to be reasoned out per reply.
        contract = self.read("backends/contract.md")
        self.assertIn(
            "at least one line containing a non-whitespace character", contract
        )
        self.assertIn("before the next heading of any level", contract)
        self.assertIn("empty code fence", contract)

    def test_paging_is_bounded_so_truncated_is_reachable(self) -> None:
        # `truncated` is defined for the state where the transport never
        # declares completion - which is exactly the state an unbounded "read
        # until it declares completion" loops in forever, never recording the
        # cause that exists for it. The guard has to terminate to be a guard.
        contract = self.read("backends/contract.md")
        self.assertIn("Paging must be bounded", contract)
        self.assertIn("An adapter that names no bound has not implemented", contract)
        # The four terminating conditions, asserted inside the bullet that has
        # to state them. File-wide they would also match the cause bullet
        # downstream, so deleting one here would still "pass" against the other
        # bullet's mention of it.
        bullet = _bullet(contract, "**Paging must be bounded")
        self.assertIsNotNone(bullet, "contract.md has no bounded-paging bullet")
        for condition in (
            "declares the reply complete",
            "does not advance",
            "page cap is reached",
            "time bound elapses",
        ):
            with self.subTest(condition=condition):
                self.assertIn(condition, bullet)

    def test_each_adapter_states_a_concrete_bound(self) -> None:
        # `contract.md` requires a bound but cannot supply one: a page size and
        # a timeout are properties of a transport it does not know. Asserted
        # structurally so tuning the numbers stays a free change while deleting
        # the bound does not.
        for relative in ("backends/traycer.md", "backends/claude-native.md"):
            adapter = self.read(relative)
            with self.subTest(adapter=relative):
                self.assertRegex(adapter, r"\*\*\d+\s+(?:pages|re-reads)\*\*")
                self.assertRegex(adapter, r"\*\*\d+\s+seconds\*\*")

    def test_absent_is_classified_before_shape_and_paging(self) -> None:
        # The cause taxonomy was correct and ran too late. With shape or paging
        # classified first, a lane that never replied records `malformed`
        # (seven sections missing from nothing) or `truncated` (a cut in a
        # reply that never existed) - each sending the lead to a remedy for a
        # different failure than the one that happened. Found by external
        # review at a real head, in `claude-native.md`, and present in
        # `traycer.md` too: an empty inbox stalls like any non-advancing
        # cursor.
        contract = self.read("backends/contract.md")
        # Half of this sentence used to read "or of its transport", which the
        # termination field falsified: the condition ending an empty read is
        # precisely transport evidence, and is the reason it is now recorded.
        self.assertIn("An empty read is never evidence of a reply's shape.", contract)
        self.assertIn(
            "What an empty read *is* evidence of is its own transport", contract
        )
        self.assertIn("`absent` is classified first", contract)
        # Precedence is stated centrally rather than left to each adapter,
        # because two adapters deriving the same ordering from prose is how
        # they drift - which is exactly how this defect reached review.
        self.assertIn("part of the taxonomy rather than each adapter's discretion", contract)

    def test_the_absent_branch_precedes_the_others_in_every_document(self) -> None:
        # Ordering is the whole finding, and no substring assertion can catch a
        # reordering: every token survives being moved. Positional assertions
        # are the only ones that bind here.
        for relative, absent, shape, paging in (
            (
                "backends/contract.md",
                "`absent` is classified first",
                "Judge shape only after",
                "Paging must be bounded",
            ),
            (
                "backends/traycer.md",
                "Classify `absent` before anything else.",
                "verify it carries all seven required sections",
                "Bound that read.",
            ),
            (
                "backends/claude-native.md",
                "Classify `absent` before anything else",
                "Then verify the reply",
                "Bound the read",
            ),
        ):
            document = self.read(relative)
            with self.subTest(document=relative):
                for token in (absent, shape, paging):
                    self.assertIn(token, document)
                self.assertLess(
                    document.index(absent),
                    document.index(shape),
                    f"{relative}: `absent` must be classified before the shape branch",
                )
                self.assertLess(
                    document.index(absent),
                    document.index(paging),
                    f"{relative}: `absent` must be classified before the paging branch",
                )

    def test_termination_controls_whether_shape_can_be_judged(self) -> None:
        # A cut read cannot pass from its visible headings. Completed reads
        # still require the correlation and section checks in the full mapping.
        contract = self.read("backends/contract.md")
        self.assertIn("Termination decides whether section inspection is permitted", contract)
        self.assertIn("whatever sections it happens to contain", contract)
        # Both adapters have to record the condition, or the lead has nothing
        # to read it from.
        self.assertIn("Record which of the four ended it", self.read("backends/traycer.md"))
        self.assertIn(
            "Record which condition ended it", self.read("backends/claude-native.md")
        )

    def test_traycer_observe_checks_the_seven_sections(self) -> None:
        adapter = self.read("backends/traycer.md")
        for section in REPORT_BACK_SECTIONS:
            with self.subTest(section=section):
                self.assertIn(section, adapter)
        self.assertIn("report_back: incomplete", adapter)
        # Shape is judged only after the paged read completes; otherwise
        # pagination manufactures a lane defect.
        self.assertIn("truncated", adapter)
        self.assertIn("is not a completion signal", adapter)

    def test_traycer_message_embeds_the_contract(self) -> None:
        adapter = self.read("backends/traycer.md")
        self.assertIn("must embed the report-back contract", adapter)
        self.assertIn("agents/report-back.md", adapter)

    def test_claude_native_implements_the_same_enforcement(self) -> None:
        # contract.md is backend-neutral, so parity is the requirement, not a
        # courtesy: an adapter that omits this is the one every silent lane
        # would be dispatched through.
        adapter = self.read("backends/claude-native.md")
        self.assertIn("seven required sections", adapter)
        self.assertIn("agents/report-back.md", adapter)
        self.assertIn("`incomplete`", adapter)
        self.assertIn(".agent/dev-state.md", adapter)

    def test_role_specific_close_outs_never_substitute(self) -> None:
        # The escape hatch with a real precedent: a QA lane posting its PR
        # comment and replying nothing looks like a lane that reported.
        #
        # Whitespace is collapsed first because `report-back.md` hard-wraps its
        # prose, so a rewrap must not read as a policy change here. Note the
        # validator pins this same sentence lexically, which is why it sits on
        # one line there: a reflow that splits it reddens the gate in
        # `validate_skill.py` rather than in this test.
        for relative in ("agents/report-back.md", "backends/contract.md"):
            with self.subTest(document=relative):
                self.assertIn(
                    "never substitute for the seven required sections",
                    " ".join(self.read(relative).split()),
                )
        self.assertIn("seven required sections", self.read("agents/qa-agent.md"))

    def test_reply_contract_has_the_six_required_sections(self) -> None:
        """Issue #54: the lead-to-user reply contract's own required shape."""
        contract = self.read("reply-contract.md")
        for heading in (
            "## 1. Scope",
            "## 2. Cap",
            "## 3. Exceptions — never compressed away",
            "## 4. Carve-out — the cap counts prose, not required structured artifacts",
            "## 5. Pull principle",
            "## 6. Composition note",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, contract)

    def test_reply_contract_pins_the_three_approved_sentences(self) -> None:
        # Verbatim per the approved plan (Issue #54) so a paraphrase cannot
        # drift the cap, its scope, or the composition note unnoticed.
        contract = self.read("reply-contract.md")
        for sentence in (
            "aim under 100 words",
            "The cap counts prose, not required structured artifacts.",
            "never claims a task-requirements override",
        ):
            with self.subTest(sentence=sentence):
                self.assertIn(sentence, contract)

    def test_reply_contract_names_every_artifact_exemption(self) -> None:
        # Scoped to the Carve-out section, not file-wide: an exemption named
        # anywhere else in the file is not the same guarantee as it being
        # part of the list the cap actually defers to.
        contract = self.read("reply-contract.md")
        carveout = _markdown_section(
            contract,
            "## 4. Carve-out — the cap counts prose, not required structured artifacts",
        )
        self.assertIsNotNone(carveout, "reply-contract.md has no Carve-out section")
        for exemption in (
            "Phase 1's progress breadcrumb and its one-question block",
            "Phase 3's Backend-Neutral Task Board",
            "Phase 4's review rating",
            "Phase 5's retro and technical-debt-sweep templates",
        ):
            with self.subTest(exemption=exemption):
                self.assertIn(exemption, carveout)

    def test_reply_contract_scope_excludes_report_back_and_docs(self) -> None:
        contract = self.read("reply-contract.md")
        scope = _markdown_section(contract, "## 1. Scope")
        self.assertIsNotNone(scope, "reply-contract.md has no Scope section")
        self.assertIn("agents/report-back.md", scope)
        self.assertIn("Issue or PR bodies", scope)
        # Explicit documentation-exclusion assertion: the cap governs only
        # end-of-turn lead replies, never tracked project docs. Scoped here
        # (not file-wide) so a docs/ reference landing outside the Scope
        # section cannot satisfy this guard by accident.
        self.assertIn("docs/*.md", scope)

    def test_skill_hooks_reference_the_reply_contract_in_both_locations(self) -> None:
        # Issue #54 requires one hook bullet in each of two named sections;
        # scoped per section so a reference living in only one still fails.
        skill = self.read("SKILL.md")
        anchor = _markdown_section(
            skill, "## ⚓ Session State Anchor (execute on every user message)"
        )
        global_rules = _markdown_section(skill, "## Global Rules")
        self.assertIsNotNone(anchor, "SKILL.md has no Session State Anchor section")
        self.assertIsNotNone(global_rules, "SKILL.md has no Global Rules section")
        self.assertIn("${CLAUDE_SKILL_DIR}/reply-contract.md", anchor)
        self.assertIn("${CLAUDE_SKILL_DIR}/reply-contract.md", global_rules)

    def test_phase1_prototyping_cross_references_the_pull_principle(self) -> None:
        prototyping = self.read("phases/phase1-prototyping.md")
        bullet = _bullet(
            prototyping, "Do not relay the prototype agent's full readout"
        )
        self.assertIsNotNone(bullet, "phase1-prototyping.md has no don't-relay bullet")
        self.assertIn("pull principle", bullet)
        self.assertIn("${CLAUDE_SKILL_DIR}/reply-contract.md", bullet)

    def test_phase1_situation_a_extracts_the_document_before_asking(self) -> None:
        """Issue #74: Situation A reads the document first and asks only its gaps.

        The failure this guards is the one dogfooding run F-75 recorded: a
        supplied requirements document fed the questions instead of answering
        them. Both directions are asserted because either alone is
        insufficient - extracting and then asking everything anyway is the
        same defect, and dropping B.3 because nothing was asked trades one
        defect for another. Scoped to the subsection so no rule can be "found"
        elsewhere in the file.
        """
        section = _markdown_subsection(
            self.read("phases/phase1.md"),
            "### B.0 Document-first mode (Situation A only)",
        )
        self.assertIsNotNone(section, "phase1.md has no B.0 document-first mode")
        for token in (
            "Situation B runs B.1 unchanged",
            "**Extract before asking.**",
            "Each item cites the document section it came from",
            "Present the proposed list and the gap list together, and **state both counts**",
            "Then ask only the gaps, one question at a time",
            "each with an AI recommended answer and a one-line rationale",
        ):
            with self.subTest(token=token):
                self.assertIn(token, section)
        for token in (
            "The B.3 stress-test runs for every module",
            'the Step C gate still requires the user to press "satisfied" before the next module',
            "the user can reopen any of them at the Step C gate",
            "**The document is never rewritten.**",
            "**with their citations**",
        ):
            with self.subTest(token=token):
                self.assertIn(token, section)

    def test_agents_directory_never_references_the_reply_contract(self) -> None:
        """Issue #54: worker/QA/reviewer surfaces are untouched — pinned invariant.

        Negative and unbounded by nature: no token list can enumerate every
        way a reference could sneak in, so this walks every file actually
        shipped under `agents/` (recursive, so any future subdirectory is
        covered) rather than a named subset.
        """
        agents_dir = SKILL / "agents"
        offenders = [
            str(path.relative_to(SKILL))
            for path in sorted(agents_dir.rglob("*.md"))
            if "reply-contract.md" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(
            offenders,
            [],
            "reply-contract.md must govern only the lead's own replies to the "
            f"user, never a delegated lane's prompt; found references in: {offenders}",
        )

    def test_no_baseline_policy_token_is_ever_removed(self) -> None:
        """Every token pinned at base 66ecfa3 must still be pinned.

        `required_policy` protects the payload's policy prose, but nothing
        protected `required_policy` itself: removing a token and then removing
        the prose it pinned passed the validator and these tests at both steps.
        Additions are allowed and expected; removals are not.

        Repository-CI guard only. `.gitattributes` export-ignores `tests`, so
        this does NOT ship in the extracted archive and gives no protection
        there - unlike the per-file policy map, which is enforced in the
        validator precisely because the archive carries it. Do not read this
        test as archive coverage.
        """
        current = _parse_required_policy(
            (ROOT / "scripts" / "validate_skill.py").read_text(encoding="utf-8")
        )
        missing = [token for token in BASE_REQUIRED_POLICY if token not in current]
        self.assertEqual(
            missing,
            [],
            "required_policy dropped baseline token(s), unpinning the policy "
            f"prose they protect: {missing}",
        )

    def test_graft_md_exists_and_has_required_sections(self) -> None:
        """Issue #57: graft.md must exist with all required sections."""
        graft = self.read("graft.md")
        for heading in (
            "## Scope & Non-Goals",
            "## Pinned Version",
            "## Availability & Capability Check",
            "## Approved Queries",
            "## Evidence & Degraded Path",
            "## Ledger Fields (Additive to DEV_STATE_TEMPLATE)",
            "## Gate Integration",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, graft)

    def test_graft_md_pins_version_and_update_procedure(self) -> None:
        """Issue #57: graft.md must pin a real version and update procedure."""
        graft = self.read("graft.md")
        self.assertIn("Pinned Graft version: 0.18.0", graft)
        self.assertIn("Update procedure:", graft)
        self.assertIn("four compatibility checks", graft)

    def test_graft_md_lists_approved_queries_only(self) -> None:
        """Issue #57: graft.md must list only the three approved queries."""
        graft = self.read("graft.md")
        # The three approved queries
        self.assertIn("Callers-of / Dependents (impact)", graft)
        self.assertIn("rtk proxy graft callers <symbol> -d N --json", graft)
        self.assertIn("Symbol search", graft)
        self.assertIn("rtk proxy graft grep \"<regex>\" --json", graft)
        self.assertIn("Repo orientation", graft)
        self.assertIn("rtk proxy graft map --json", graft)
        # The approved queries table should only have 3 rows (3 data rows + header)
        approved_section = graft.split("## Approved Queries")[1].split("## Evidence")[0]
        table_rows = [line for line in approved_section.splitlines() if line.strip().startswith("|") and not line.strip().startswith("|---")]
        # Header row + 3 data rows = 4 rows with pipes
        self.assertEqual(len(table_rows), 4, "Approved queries table should have exactly 3 data rows")
        # Unapproved queries appear only in the exclusion note, not in the table
        self.assertIn("No other queries (e.g., `graft ask`, `graft skeleton`, `graft blast`, `graft viz`) are approved for gate evidence.", graft)

    def test_graft_md_requires_evidence_or_recorded_unavailability(self) -> None:
        """Issue #57: graft.md must require graph_evidence with cause and manual fallback."""
        graft = self.read("graft.md")
        self.assertIn("graph_evidence: present | unavailable", graft)
        self.assertIn("not_installed | version_mismatch | build_failed | unparseable_output | query_failure", graft)
        self.assertIn("manual fallback", graft)
        self.assertIn("Silence never passes", graft)
        # query_failure degraded path: approved query failures / invalid JSON
        self.assertIn("query_failure", graft)
        self.assertIn("Query Failure Classification", graft)
        self.assertIn("rtk proxy graft callers", graft)
        self.assertIn("rtk proxy graft grep", graft)
        self.assertIn("rtk proxy graft map", graft)
        self.assertIn("invalid JSON", graft)

    def test_graft_md_adds_ledger_fields(self) -> None:
        """Issue #57: graft.md must add ledger fields to DEV_STATE_TEMPLATE."""
        graft = self.read("graft.md")
        self.assertIn("graft_version", graft)
        self.assertIn("graph_evidence", graft)
        self.assertIn("graph_evidence_cause", graft)

    def test_graft_md_bans_graft_init(self) -> None:
        """Issue #57: graft.md must ban graft init in managed projects."""
        graft = self.read("graft.md")
        self.assertIn("never `graft init` in managed projects", graft)
        self.assertIn("Never an execution backend.", graft)

    def test_five_prompt_sites_reference_graft_md(self) -> None:
        """Issue #57: the five prompt sites must reference graft.md with the required pattern."""
        # 1. worker-new.md Step-1 layer-4 callers + reuse ladder rung 2
        worker_new = self.read("agents/worker-new.md")
        self.assertIn("${CLAUDE_SKILL_DIR}/graft.md", worker_new)
        self.assertIn("rtk proxy graft callers <symbol> -d 2 --json", worker_new)
        self.assertIn("rtk proxy graft grep \"<pattern>\" --json", worker_new)
        self.assertIn("graph_evidence: unavailable", worker_new)
        self.assertIn("trace callers manually", worker_new)
        self.assertIn("search manually with `rg`", worker_new)

        # 2. worker-fix.md rung 2
        worker_fix = self.read("agents/worker-fix.md")
        self.assertIn("${CLAUDE_SKILL_DIR}/graft.md", worker_fix)
        self.assertIn("rtk proxy graft grep \"<pattern>\" --json", worker_fix)
        self.assertIn("graph_evidence: unavailable", worker_fix)
        self.assertIn("search manually with `rg`", worker_fix)

        # 3. qa-agent.md Tool Capability Boundary
        qa = self.read("agents/qa-agent.md")
        self.assertIn("${CLAUDE_SKILL_DIR}/graft.md", qa)
        self.assertIn("rtk proxy graft callers <symbol> -d N --json", qa)
        self.assertIn("graph_evidence: unavailable", qa)
        self.assertIn("trace manually with `rg`", qa)
        self.assertIn("Graph output = static evidence, never execution confirmation", qa)

        # 4. phase4.md Coverage-Path Audit
        phase4 = self.read("phases/phase4.md")
        self.assertIn("${CLAUDE_SKILL_DIR}/graft.md", phase4)
        self.assertIn("rtk proxy graft callers <symbol> -d N --json", phase4)
        self.assertIn("graph_evidence: unavailable", phase4)
        self.assertIn("trace dependents manually", phase4)
        self.assertIn("Graph output = static evidence, never execution confirmation", phase4)

        # 5. phase2.md change-impact assessment
        phase2 = self.read("phases/phase2.md")
        self.assertIn("${CLAUDE_SKILL_DIR}/graft.md", phase2)
        self.assertIn("rtk proxy graft callers <symbol> -d all --json", phase2)
        self.assertIn("graph_evidence: unavailable", phase2)
        self.assertIn("trace dependents manually", phase2)


WRAPPER_ROUTE = "rtk proxy python3 ${CLAUDE_SKILL_DIR}/scripts/traycer_cli.py"


class ExternalReviewCoveragePinsTests(unittest.TestCase):
    """Round-3 coverage pins (QA mutations M6, M7, M8).

    QA round 2 showed three content criteria were test-executable
    but unpinned: deleting the four Known-identities bullets in
    `phases/external-review.md`, reverting the `PROJECT_CONTEXT.md`
    External Review Policy values (Required/Ignored), or deleting
    the `CHANGELOG.custom.md` `Unreleased (v2.1.2)` entry all
    passed every suite. Each is now pinned both in the validator
    (per-file policy / explicit check) and here, as plain text
    assertions with no subprocess at all.

    These tests read shipped files and assert tokens. The
    mutation proof (deleting each token and watching the validator
    fail) is performed OUTSIDE the suite in a scratch clone, per
    the lead's hard rules. No test in this class invokes
    `unittest discover`, `verify.sh`, `pytest`, or any subprocess
    at all — the suite never runs the suite.
    """

    def read(self, relative: str) -> str:
        return (SKILL / relative).read_text(encoding="utf-8")

    def test_m6_known_identities_bullets_are_pinned(self):
        """M6: the four new Known-identities bullets in
        `phases/external-review.md` carry the per-reviewer
        contract (login, check, push-re-review behavior).
        """
        external = " ".join(self.read("phases/external-review.md").split())
        for token in (
            "**Gemini Code Assist** — review (`gemini-code-assist[bot]`). Comment-only (no published check-run app)",
            "**Greptile** — review (`greptile-apps[bot]`) and check (app slug `greptile-apps`)",
            "**Sourcery** — review (`sourcery-ai[bot]`) and check (app slug `sourcery-ai`)",
            "**Qodo** — review (`qodo-code-review[bot]`, `qodo-free-for-open-source-projects[bot]`)",
            "`github-actions[bot]` is shared by every workflow and is not a stable identity",
        ):
            with self.subTest(token=token):
                self.assertIn(token, external)

    def test_m8_project_context_external_review_policy_values(self):
        """M8: the `PROJECT_CONTEXT.md` External Review Policy
        values are load-bearing (Issue #117): `Required
        reviewers: kilo` and `Ignored reviewers: coderabbit`.
        """
        project = (ROOT / "PROJECT_CONTEXT.md").read_text(encoding="utf-8")
        self.assertIn("**Required reviewers**: kilo", project)
        self.assertIn("**Ignored reviewers**: coderabbit", project)

    def test_m7_changelog_unreleased_entry_covers_82_117(self):
        """M7: the `CHANGELOG.custom.md` `Unreleased (v2.1.2)`
        entry must record the Issue #82/#117 switch: the four
        new reviewers, the ask-once contract, the Kilo summary
        evidence path, and the Kilo-led policy.

        D1 (release-aware): the heading is `## Unreleased
        (v2.1.2)` while unreleased, and `## v2.1.2 — YYYY-MM-DD`
        once cut, matching the house style. The parenthesized
        date form is still accepted so the pin does not break on
        an alternate release note shape.
        """
        changelog = (ROOT / "CHANGELOG.custom.md").read_text(encoding="utf-8")
        match = re.search(
            r"^## (?:Unreleased \(v2\.1\.2\)|v2\.1\.2(?: — \d{4}-\d{2}-\d{2}| \(\d{4}-\d{2}-\d{2}\))?)"
            r"$(.*?)(?=^## |\Z)",
            changelog,
            re.M | re.S,
        )
        self.assertIsNotNone(
            match,
            "CHANGELOG has no `## Unreleased (v2.1.2)` section "
            "(or released `## v2.1.2 — YYYY-MM-DD` heading)",
        )
        body = match.group(1)
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
            with self.subTest(token=token):
                self.assertIn(token, body)


class SuppliedIdentityContractTests(unittest.TestCase):
    """Issue #89: supplied identity, the wrapper route, and the non-Claude lead rule."""

    def read(self, relative: str) -> str:
        return (SKILL / relative).read_text(encoding="utf-8")

    def test_every_traycer_cli_step_is_routed_through_the_wrapper(self) -> None:
        adapter = self.read("backends/traycer.md")
        for step in (
            "whoami",
            "host status",
            "agent list",
            "agent create",
            "agent send",
            "agent selection-guide",
            "worktree create",
        ):
            with self.subTest(step=step):
                self.assertIn(f"{WRAPPER_ROUTE} {step}", adapter)
        for step in ("agent inbox", "agent transcript", "agent stop", "agent archive"):
            with self.subTest(step=step):
                self.assertIn(step, adapter)
        self.assertIn("means that route", adapter)
        self.assertIn("Never invoke `traycer` directly", adapter)
        self.assertIn(WRAPPER_ROUTE, self.read("backends/contract.md"))
        self.assertIn(WRAPPER_ROUTE, self.read("SKILL.md"))

    def test_no_line_runs_traycer_directly(self) -> None:
        pattern = re.compile(r"`(?:rtk proxy )?traycer (?:whoami|host|agent|worktree)")
        for path in sorted(SKILL.rglob("*.md")):
            with self.subTest(path=str(path.relative_to(SKILL))):
                self.assertIsNone(pattern.search(path.read_text(encoding="utf-8")))

    def test_the_wrapper_is_a_required_payload_file(self) -> None:
        self.assertTrue((SKILL / "scripts" / "traycer_cli.py").is_file())
        validator = (ROOT / "scripts" / "validate_skill.py").read_text(encoding="utf-8")
        self.assertIn('"scripts/traycer_cli.py"', validator)

    def test_adapter_documents_the_identity_file_format_and_source_rules(self) -> None:
        adapter = self.read("backends/traycer.md")
        for token in (
            ".agent/traycer.env",
            "export TRAYCER_AGENT_ID=<agent-id>",
            "export TRAYCER_EPIC_ID=<epic-id>",
            "exactly two lines, in either order",
            "`backend_source`: `detected`",
            "`supplied`",
            "Sources are never mixed",
            "There is no override flag.",
            "identifiers, never secrets",
            "no_usable_identity",
            "traycer_not_found",
            "traycer_exec_failed",
            "exits 78",
            "69",
            "nothing to stdout",
        ):
            with self.subTest(token=token):
                self.assertIn(token, adapter)

    def test_identity_acquisition_rule_never_guesses(self) -> None:
        section = _markdown_section(self.read("backends/traycer.md"), "## Supplied identity")
        self.assertIsNotNone(section)
        for token in (
            "Identity acquisition rule",
            "session's own self-identity source",
            "Traycer session context the harness was given",
            "user's invocation message",
            "ask the user once and stop until answered",
            "never guesses an id",
            "Never derive an id from a path guess, a directory name, or another agent's record.",
            "git-ignored or excluded",
            "git check-ignore -q .agent/traycer.env",
            "git rev-parse --git-path info/exclude",
            "Re-run",
            "backend_source: supplied",
            "verified live for Codex and OpenCode leads",
        ):
            with self.subTest(token=token):
                self.assertIn(token, section)
        # Harness-neutral: no Claude-specific tool name in the payload.
        for forbidden in ("traycer_get_self", "mcp__", "AskUserQuestion"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, section)

    def test_preflight_checks_a_supplied_identity_two_ways_without_promising_certainty(self) -> None:
        preflight = _markdown_section(self.read("backends/traycer.md"), "## Preflight")
        self.assertIsNotNone(preflight)
        for token in (
            "**(a) Self-source comparison.**",
            "the recorded agent id must equal the id that source reports",
            "This is mandatory whenever the source exists, including when the id came from the user's message.",
            "**(b) Row corroboration.**",
            "`folderPaths` must include the lead's current worktree root",
            "its `harnessId` must be the harness the lead itself knows it is running on",
            "A wrong id belonging to another agent fails this unless that agent shares the same worktree and harness.",
            "A failed (a) or a failed (b) is `incomplete`",
            "deletes or corrects `.agent/traycer.env` before anything else",
            "(b) alone is the floor and the ledger records that",
            "When neither can be made, the result is `incomplete`.",
            "(b) cannot distinguish two agents that share one worktree and one harness",
            "`identity_verification`",
            "a `detected` identity leaves it `null`",
            "neither check is proof",
            "establishes the agent id when a self-identity source exists",
            "corroborates it and is the weaker of the two",
            "reduce, and do not eliminate, the chance of accepting a wrong pair",
            "row corroboration accepts a wrong id that belongs to an agent sharing the lead's worktree and harness",
            "Read-only QA and review lanes that share a checkout with the lead are the realistic way this happens.",
            "`worktree_match` stays the floor",
            "A lead verified by `worktree_match` alone says so to the user in its first status reply.",
        ):
            with self.subTest(token=token):
                self.assertIn(token, preflight)

    def test_the_cli_self_marker_is_never_treated_as_evidence(self) -> None:
        """The CLI derives `isSelf` and `data.caller.agentId` from the supplied
        identifiers, so a wrong pair reports itself as the caller. The adapter
        must say so, and no sentence may claim the marker catches a wrong pair."""
        adapter = self.read("backends/traycer.md")
        preflight = _markdown_section(adapter, "## Preflight")
        supplied = _markdown_section(adapter, "## Supplied identity")
        self.assertIsNotNone(preflight)
        self.assertIsNotNone(supplied)
        for section in (preflight, supplied):
            self.assertIn("are not evidence of the caller's identity", section)
            self.assertIn("derived", section)
        self.assertIn("proves nothing here", preflight)
        self.assertIn("replace the marker", supplied)
        self.assertIn("do not eliminate", supplied)
        for retired in (
            "the output must contain a row marked `isSelf: true`",
            "`data.caller.agentId` must equal it too",
            "run the self-check",
            "This check applies to `detected` and `supplied` alike.",
            "a wrong supplied pair must be caught mechanically, not trusted: preflight step 3 fails closed on it",
            # Absolutes retired in round 2: the checks reduce the chance of a
            # wrong pair, they do not remove it, and either alone can be the basis.
            "two independent checks",
            "verifies the pair with",
            "a wrong pair is caught by",
            "never by the marker",
            "also needs",
            "the preflight self-check",
        ):
            with self.subTest(retired=retired):
                self.assertNotIn(retired.lower(), adapter.lower())

    def test_adapter_names_the_epic_id_source_and_cli_usage_gaps_found_by_the_91_probes(self) -> None:
        """Issue #98: the epic-id source, positional harness, Codex network, and
        agent-list size clarifications. Each token is a statement the live probes
        showed a lead needed spelled out."""
        adapter = self.read("backends/traycer.md")
        supplied = _markdown_section(adapter, "## Supplied identity")
        preflight = _markdown_section(adapter, "## Preflight")
        self.assertIsNotNone(supplied)
        self.assertIsNotNone(preflight)
        for token in (
            "`Agents in task '<epic>' (relative to you):` header",
            "`agent list --json` carries no epic or task field",
            "so the CLI cannot supply it",
            "A working directory that happens to sit under `~/.traycer/epics/<epic>/` is a path guess, not a source.",
        ):
            with self.subTest(section="supplied", token=token):
                self.assertIn(token, supplied)
        for token in (
            "`agent list-harness-models <harness> --json`",
            "`agent list-profiles <harness> --json`",
            "take the harness as a positional argument",
            "`E_INVALID_ARGUMENT`",
            "filter it to the rows needed",
            "never print it whole",
        ):
            with self.subTest(section="preflight", token=token):
                self.assertIn(token, preflight)
        wrapper = _markdown_section(adapter, "## Wrapper route")
        self.assertIsNotNone(wrapper)
        for token in (
            "A Codex terminal lead's default sandbox blocked the CLI's network access",
            "a Codex chat lead ran the same calls without it",
            "`E_AUTH_NETWORK`",
            "`E_HOST_UNREACHABLE`",
            "A Codex lead that hits those errors asks the user for network access for the CLI",
        ):
            with self.subTest(section="wrapper", token=token):
                self.assertIn(token, wrapper)

    def test_a_partial_environment_is_a_host_defect_the_file_cannot_repair(self) -> None:
        supplied = _markdown_section(self.read("backends/traycer.md"), "## Supplied identity")
        self.assertIsNotNone(supplied)
        for token in (
            "with neither identifier in the environment",
            "a partial environment cannot be recovered by the file",
            "The lead records `incomplete`, reports the partial environment to the user as a host defect, and stops.",
            "It never sets or unsets `TRAYCER_AGENT_ID` or `TRAYCER_EPIC_ID` itself to make the file apply.",
        ):
            with self.subTest(token=token):
                self.assertIn(token, supplied)

    def test_ledger_records_which_check_verified_a_supplied_identity(self) -> None:
        template = self.read("templates/DEV_STATE_TEMPLATE.md")
        frontmatter = template.split("\n---\n", 1)[0]
        self.assertIn("  identity_verification: null", frontmatter)
        self.assertIn("schema_version: 2", frontmatter)
        schema = _markdown_section(template, "## Execution record schema")
        self.assertIsNotNone(schema)
        self.assertIn("`identity_verification`", schema)
        line = next(
            row for row in schema.splitlines() if row.startswith("Allowed `identity_verification` values")
        )
        for value in (
            "`null`",
            "`self_source`",
            "`worktree_match`",
            "`self_source_and_worktree_match`",
        ):
            with self.subTest(value=value):
                self.assertIn(value, line)
        self.assertIn("additive under `schema_version: 2`", line)

    def test_recovery_accepts_a_supplied_identity(self) -> None:
        adapter = self.read("backends/traycer.md")
        recovery = adapter.split("On recovery,", 1)[1].split("\n", 1)[0]
        self.assertIn("re-run the detector", recovery)
        self.assertIn(".agent/traycer.env", recovery)
        self.assertIn("never a reason to fall back", recovery)
        self.assertIn("Preflight step 3 identity checks", recovery)
        self.assertNotIn("self-check", recovery)

    def test_contract_states_the_non_claude_lead_rule(self) -> None:
        contract = self.read("backends/contract.md")
        for token in (
            "**Non-Claude leads.**",
            "A lead whose harness is not Claude Code selects `traycer` or records `incomplete` and stops.",
            "`claude-native` is never available to it",
            "`lead.harness` is recorded from the Traycer agent list, never inferred.",
            "`backend_source: supplied`",
            "Sources are never mixed",
            "the file is not used to fill the gap",
            "with neither environment identifier present",
            "A partial environment (exactly one identifier) is a host defect: the lead records `incomplete`, reports it to the user, and stops, and the file never recovers it.",
        ):
            with self.subTest(token=token):
                self.assertIn(token, contract)
        non_claude = contract.split("**Non-Claude leads.**", 1)[1].split("\n", 1)[0]
        self.assertNotIn(
            "When the detector returns `incomplete` inside a Traycer session, the lead follows",
            non_claude,
        )

    def test_ledger_allows_supplied_alongside_the_other_sources(self) -> None:
        template = self.read("templates/DEV_STATE_TEMPLATE.md")
        line = next(
            row for row in template.splitlines() if row.startswith("Allowed `backend_source` values")
        )
        for value in ("`null`", "`detected`", "`supplied`", "`lead_resolved`"):
            with self.subTest(value=value):
                self.assertIn(value, line)

    def test_skill_md_names_the_supplied_source_without_contradicting_the_detector(self) -> None:
        section = _markdown_section(
            self.read("SKILL.md"), "## Execution Backend and Topology Policy"
        )
        self.assertIsNotNone(section)
        for token in (
            "`backend_source: supplied`",
            "`.agent/traycer.env`",
            "sources are never mixed",
            "never available to a lead whose harness is not Claude Code",
            "Binary presence never selects Traycer.",
            "A failed Traycer preflight never triggers Claude fallback.",
        ):
            with self.subTest(token=token):
                self.assertIn(token, section)

    def test_payload_paths_keep_the_variable_form(self) -> None:
        for relative in ("backends/traycer.md", "backends/contract.md", "SKILL.md"):
            text = self.read(relative)
            with self.subTest(path=relative):
                self.assertIn("${CLAUDE_SKILL_DIR}/scripts/traycer_cli.py", text)
                self.assertNotIn("/scripts/traycer_cli.py", text.replace("${CLAUDE_SKILL_DIR}/scripts/traycer_cli.py", ""))


class MultiHarnessContractTests(unittest.TestCase):
    """Issue #58 + #38: ADR-012 / capability checklist / ADR-009 lint pins.

    Doc-assertion layer for the lane-policy pins the validator's
    `per_file_policy` enforces at archive validation time. Together the two
    layers cover both the extracted archive (validator) and the in-repo
    checkout (this file); deleting either pin must fail both layers.
    """

    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_adr_012_pinned_sentence_in_architecture(self) -> None:
        """Issue #58: ADR-012 must record the verbatim decision sentence."""
        architecture = self.read("docs/architecture.md")
        self.assertIn("## ADR-012 — Child harnesses receive handoff context, never /dev variants", architecture)
        self.assertIn(
            "Child harnesses receive handoff context, never /dev variants",
            architecture,
        )

    def test_adr_013_pinned_heading_and_decision_in_architecture(self) -> None:
        """Issue #90: ADR-013 must keep its heading and its scope sentence."""
        architecture = self.read("docs/architecture.md")
        self.assertIn(
            "## ADR-013 — Non-Claude leads run the same payload under the Traycer backend",
            architecture,
        )
        self.assertIn(
            "Codex and OpenCode run the **same payload** as the lead "
            "**under the Traycer backend only**",
            architecture,
        )

    def test_capability_checklist_subsection_in_contract(self) -> None:
        """Issue #58: all four checklist items and the pinned remedy sentence
        must appear verbatim in `backends/contract.md`."""
        contract = self.read("skills/dev/backends/contract.md")
        self.assertIn("## Child-harness capability checklist", contract)
        for token in (
            "receive-capable GUI surface",
            "Tooling on PATH",
            "Shared-filesystem read of resolved Skill files",
            "Replies in seven-section shape on arrival surface",
        ):
            with self.subTest(token=token):
                self.assertIn(token, contract)
        # The pinned remedy sentence — the gate that closes the loophole the
        # capability checklist is designed to plug.
        self.assertIn(
            "remedy is a different route, never a trimmed prompt",
            contract,
        )

    def test_adr_009_lint_reclassification_in_contract(self) -> None:
        """Issue #38: the lint-vs-control reclassification must be in the
        file the delegated lanes read, and must not name the rejected ADR-008
        credential layer as a control."""
        contract = self.read("skills/dev/backends/contract.md")
        self.assertIn(
            "an authorship lint, not a security control",
            contract,
        )
        self.assertIn(
            "behavioural tests and the supported pre-write verification are the real controls",
            contract,
        )

    def test_contract_does_not_name_rejected_credential_layer(self) -> None:
        """Issue #38 explicit negative invariant: the rejected ADR-008
        credential layer is not a control here, and naming it as one would
        re-couple contract.md to a rejected design."""
        contract = " ".join(
            self.read("skills/dev/backends/contract.md").split()
        )
        # The scope here is bounded to phrases that would name the rejected
        # layer as a control. Scoped per-issue (rather than file-wide) so an
        # unrelated future mention does not fail this guard.
        self.assertNotIn("credential layer", contract)
        self.assertNotIn("scoped credential", contract)


class RecoverySpecificationExamples(unittest.TestCase):
    """Specification examples of the documented swap-time recovery procedure.

    NOT runtime coverage. The backend is prose that a lead executes; nothing
    here runs it. `recover()` below is a reference model written in this test
    file as a worked example of the rule in `skills/dev/backends/traycer.md`
    (the "Swap-time evidence" bullet, conditions 1-3, around lines 105-110)
    and `skills/dev/backends/contract.md` ("Swap-time evidence is
    adapter-defined, narrow, and fails closed."). The tests check that the
    examples agree with the derivation table the ledger carries; they cannot
    catch a lead that executes the prose wrongly. The prose itself is pinned by
    `SwapTimeEvidenceTests`, so the model and the prose cannot drift apart
    silently. If a shipped reducer is ever added, point these at it.

    The model follows the prose strictly: exactly two bounded inbox reads
    (the new lead's own and the one for `dispatched_by`) and a response ID that
    matches in full, never as a substring or prefix.
    """

    LANE = "lane-agent-1"
    OLD_LEAD = "old-lead-1"
    NEW_LEAD = "new-lead-2"
    RESPONSE_ID = "637a6bab-ca78-4b93-85cd-cac46f64a67d"
    DISPATCHED_AT = 100
    INBOX_READS = 2  # traycer.md condition 2: "Both inbox reads"

    def read(self, relative: str) -> str:
        return (SKILL / relative).read_text(encoding="utf-8")

    def ledger_rows(self) -> list[tuple[str, tuple[str, ...], str, str, str]]:
        section = _markdown_section(
            self.read("templates/DEV_STATE_TEMPLATE.md"), "## Report-back record schema"
        )
        self.assertIsNotNone(section)
        return _mapping_rows(section)

    # -- the reference model ------------------------------------------------

    @staticmethod
    def derive(observed: bool, termination: str, all_sections: bool, rows) -> tuple[str, str]:
        correlation = "observed" if observed else "not observed"
        for corr, terminations, sections, verdict, cause in rows:
            if corr != correlation or termination not in terminations:
                continue
            if sections in ("not examined", "not judged"):
                return verdict, cause
            if (sections == "all seven") == all_sections:
                return verdict, cause
        raise AssertionError(f"no mapping row for {correlation}/{termination}/{all_sections}")

    def recover(
        self,
        *,
        inbox,
        transcript=(),
        transcript_termination="completed",
        dispatched_by="old-lead-1",
        current_lead="new-lead-2",
        all_sections=True,
    ):
        """Classify a lane on recovery, as `traycer.md` states the rule.

        `inbox` is a list of (termination, correlated) reads; `transcript` is a
        list of (sender, sent_at, body) messages from the previous lead's
        session.
        """
        rows = self.ledger_rows()
        for termination, correlated in inbox:
            if correlated:
                return self.derive(True, termination, all_sections, rows)
        cut = [t for t, _ in inbox if t != "completed"]
        if cut:
            return self.derive(False, cut[0], all_sections, rows)
        absent = self.derive(False, "completed", all_sections, rows)
        if not dispatched_by or dispatched_by == current_lead:
            return absent
        if len(inbox) != self.INBOX_READS:
            # condition 2 needs BOTH bounded inbox reads to have ended
            # `completed`; with fewer the swap rule is never consulted.
            return absent
        qualifying = [
            m
            for m in transcript
            if m[0] == self.LANE and m[1] > self.DISPATCHED_AT and self.names_response_id(m[2])
        ]
        if transcript_termination != "completed":
            return self.derive(bool(qualifying), transcript_termination, all_sections, rows)
        if not qualifying:
            return absent
        return self.derive(True, "completed", all_sections, rows)

    def names_response_id(self, body: str) -> bool:
        """traycer.md condition 3: the id appears "verbatim and in full".

        A prefix, a different id, or the id inside a longer token does not
        match.
        """
        return self.RESPONSE_ID in re.split(r"[^0-9A-Za-z-]+", body)

    def report(self, body_extra: str = "") -> tuple[str, int, str]:
        return (self.LANE, self.DISPATCHED_AT + 5, f"Response ID: {self.RESPONSE_ID}\n{body_extra}")

    ABSENT = ("incomplete", "absent")
    TRUNCATED = ("incomplete", "truncated")
    COMPLETE = ("complete", "null")
    MALFORMED = ("incomplete", "malformed")

    # -- behaviour of the rule ----------------------------------------------

    def test_the_rule_accepts_only_the_narrow_swap_evidence(self) -> None:
        both_empty = [("completed", False), ("completed", False)]
        self.assertEqual(self.COMPLETE, self.recover(inbox=both_empty, transcript=[self.report()]))
        # all sections absent from the transcript message: the unchanged shape rule applies
        self.assertEqual(
            self.MALFORMED,
            self.recover(inbox=both_empty, transcript=[self.report()], all_sections=False),
        )

    def test_every_missing_condition_stays_absent(self) -> None:
        both_empty = [("completed", False), ("completed", False)]
        good = self.report()
        cases = {
            "no transcript message": dict(transcript=[]),
            "wrong sender (previous lead quotes the id)": dict(
                transcript=[(self.OLD_LEAD, 105, good[2])]
            ),
            "sent before the recorded dispatch": dict(
                transcript=[(self.LANE, self.DISPATCHED_AT, good[2])]
            ),
            "response id prefix only": dict(
                transcript=[(self.LANE, 105, f"Response ID: {self.RESPONSE_ID[:8]}")]
            ),
            "different response id": dict(
                transcript=[(self.LANE, 105, "Response ID: 00000000-0000-0000-0000-000000000000")]
            ),
            "no swap: same lead resuming": dict(
                transcript=[good], current_lead=self.OLD_LEAD
            ),
            "ledger has no dispatched_by": dict(transcript=[good], dispatched_by=None),
        }
        for name, kwargs in cases.items():
            with self.subTest(name):
                self.assertEqual(self.ABSENT, self.recover(inbox=both_empty, **kwargs))

    def test_one_inbox_read_does_not_satisfy_the_swap_rule(self) -> None:
        # traycer.md condition 2 names two reads: the new lead's own and the
        # one for `dispatched_by`. A single read cannot show that both ended
        # `completed` with no correlated reply, so a qualifying transcript
        # message must not be accepted.
        good = self.report()
        one_read = [("completed", False)]
        self.assertEqual(self.ABSENT, self.recover(inbox=one_read, transcript=[good]))
        both_reads = one_read * self.INBOX_READS
        self.assertEqual(self.COMPLETE, self.recover(inbox=both_reads, transcript=[good]))

    def test_the_response_id_must_match_in_full_not_as_a_substring(self) -> None:
        both_empty = [("completed", False), ("completed", False)]
        near_misses = {
            "id with a suffix": f"Response ID: {self.RESPONSE_ID}0",
            "id with a prefix": f"Response ID: 0{self.RESPONSE_ID}",
            "id embedded in a longer token": f"Response ID: x{self.RESPONSE_ID}x",
            "leading eight characters only": f"Response ID: {self.RESPONSE_ID[:8]}",
            "trailing characters cut off": f"Response ID: {self.RESPONSE_ID[:-1]}",
        }
        for name, body in near_misses.items():
            with self.subTest(name):
                self.assertEqual(
                    self.ABSENT,
                    self.recover(inbox=both_empty, transcript=[(self.LANE, 105, body)]),
                )
        # the exact id, anywhere in the message, still counts
        self.assertEqual(
            self.COMPLETE,
            self.recover(
                inbox=both_empty,
                transcript=[(self.LANE, 105, f"thread {self.RESPONSE_ID}, done")],
            ),
        )

    def test_a_cut_read_stays_truncated_and_is_never_upgraded(self) -> None:
        good = self.report()
        for termination in ("stalled", "page_cap", "time_bound"):
            for inbox in (
                [(termination, False), ("completed", False)],
                [("completed", False), (termination, False)],
            ):
                with self.subTest(termination=termination, inbox=inbox):
                    self.assertEqual(
                        self.TRUNCATED, self.recover(inbox=inbox, transcript=[good])
                    )
        # a transcript read that did not end `completed` cannot establish absence
        for termination in ("stalled", "time_bound"):
            for transcript in ([], [good]):
                with self.subTest(transcript_termination=termination, found=bool(transcript)):
                    self.assertEqual(
                        self.TRUNCATED,
                        self.recover(
                            inbox=[("completed", False), ("completed", False)],
                            transcript=transcript,
                            transcript_termination=termination,
                        ),
                    )

    def test_the_non_swap_path_is_the_unchanged_mapping(self) -> None:
        # With no lead change the rule is never consulted, whatever the
        # previous lead's transcript holds. Every inbox outcome maps exactly as
        # the ledger's table says; a drifted table fails here and in the
        # exact-pairings test.
        rows = self.ledger_rows()
        self.assertEqual(list(REPORT_BACK_DERIVATION), rows)
        planted = [self.report()]
        for termination in REPORT_BACK_TERMINATIONS:
            for correlated in (False, True):
                for all_sections in (False, True):
                    with self.subTest(termination=termination, correlated=correlated, all=all_sections):
                        got = self.recover(
                            inbox=[(termination, correlated)],
                            transcript=planted,
                            current_lead=self.OLD_LEAD,
                            all_sections=all_sections,
                        )
                        self.assertEqual(self.derive(correlated, termination, all_sections, rows), got)
        self.assertEqual(self.ABSENT, self.recover(inbox=[("completed", False)], transcript=planted, current_lead=self.OLD_LEAD))

class SwapTimeEvidenceTests(unittest.TestCase):
    """Issue #97: the prose that states which evidence satisfies report-back
    correlation after a lead swap.

    These tests read the shipped prose (`backends/traycer.md`,
    `backends/contract.md`, the ledger template) and pin the sentences the
    worked examples in `RecoverySpecificationExamples` are written against.
    """

    def read(self, relative: str) -> str:
        return (SKILL / relative).read_text(encoding="utf-8")

    def traycer_bullet(self, lead_in: str) -> str:
        for line in self.read("backends/traycer.md").splitlines():
            if line.startswith(lead_in):
                return line
        self.fail(f"traycer.md has no bullet starting {lead_in!r}")

    # -- the prose the examples are written against -------------------------

    def test_the_swap_bullet_states_every_condition_and_changes_no_vocabulary(self) -> None:
        swap = " ".join(self.read("backends/traycer.md").split())
        for token in (
            "**Swap-time evidence (after a lead change only).**",
            "A worker entry with no `dispatched_by` fails this condition",
            "Both inbox reads ended `completed` with no correlated reply",
            "A read that ended `stalled`, `page_cap`, or `time_bound` stays `truncated`",
            "the swap rule never upgrades a truncated read",
            "comes from the lane's recorded `agent_id`",
            "was sent after the recorded `dispatched_at`",
            "That is the new lead's own bounded inbox read and the bounded `agent inbox --agent-id <dispatched_by> --json` read.",
            "contains the recorded `communication_response_id` verbatim and in full",
            "a prefix, a different id, or a paraphrase does not match",
            "A message from any other agent that quotes the id",
            "never qualifies",
            "No qualifying message with a `completed` stream stays `absent`",
            "because a cut read cannot establish absence",
            "It adds no row, termination value, or cause to the mapping",
        ):
            with self.subTest(token=token):
                self.assertIn(token, swap)
        # No fifth termination and no fourth cause was introduced anywhere.
        template = self.read("templates/DEV_STATE_TEMPLATE.md")
        self.assertIn(
            "otherwise exactly one of `absent`, `malformed`, or `truncated`", template
        )
        self.assertIn(
            "`null` (no bounded read has been performed yet), `completed` (the transport declared the reply complete), `stalled` (a page returned no new content, or a cursor that did not advance), `page_cap` (the adapter's page or re-read cap was reached), and `time_bound` (the adapter's time bound elapsed)",
            template,
        )

    def test_the_swap_bullet_comes_after_the_absent_classification(self) -> None:
        # The swap rule refines an `absent` result; it must not precede, and so
        # appear to pre-empt, the absent-first classification.
        document = self.read("backends/traycer.md")
        absent = document.index("Classify `absent` before anything else.")
        swap = document.index("**Swap-time evidence (after a lead change only).**")
        self.assertLess(absent, swap)
        self.assertIn(
            "an inbox read that ended `completed` with no correlated reply, and would therefore record `absent`, consults the swap-time evidence rule below",
            document,
        )
        self.assertIn(
            "every other read is classified exactly as stated here", document
        )

    def test_the_previous_leads_session_comes_only_from_the_ledger(self) -> None:
        template = self.read("templates/DEV_STATE_TEMPLATE.md")
        self.assertIn("`dispatched_by` and `dispatched_at`", template)
        self.assertIn("the lead never fills them from a path guess", template)
        traycer = self.read("backends/traycer.md")
        self.assertIn(
            "The previous lead's session id comes only from `dispatched_by`, never from a path guess, a directory name, or another agent's record.",
            traycer,
        )
        self.assertIn("communication_response_id`, `dispatched_by`, `dispatched_at`", template)

    def test_recovery_distinguishes_a_swap_without_weakening_identity_checks(self) -> None:
        traycer = self.read("backends/traycer.md")
        for token in (
            "Different means a **lead swap**, not an identity failure",
            "Only a failed Preflight step 3 check is an identity failure",
            "is never a swap and makes the operation `incomplete`",
            "a swap never relaxes any Preflight step 3 check",
        ):
            with self.subTest(token=token):
                self.assertIn(token, traycer)

    def test_the_contract_binds_any_swap_rule(self) -> None:
        contract = " ".join(self.read("backends/contract.md").split())
        for token in (
            "**Swap-time evidence is adapter-defined, narrow, and fails closed.**",
            "only after a lead change recorded in the ledger",
            "ended `completed` with no correlated reply",
            "recorded lane agent, after the recorded dispatch",
            "names the recorded response ID in full",
            "anything less stays `absent`",
            "It never upgrades a read that ended `stalled`, `page_cap`, or `time_bound`",
            "a cut transcript read cannot establish absence",
            "adds no row, termination value, or cause to the mapping",
        ):
            with self.subTest(token=token):
                self.assertIn(token, contract)

    def test_the_report_names_its_thread_on_the_first_line_and_keeps_the_fail_closed_rule(self) -> None:
        report_back = " ".join(self.read("agents/report-back.md").split())
        self.assertIn("on the **first line** of the report", report_back)
        self.assertIn("(for example `Response ID: <id>`), above the seven sections", report_back)
        self.assertIn("A line above the first heading is not a section", report_back)
        # The existing rule is unchanged and the new line cross-references it.
        self.assertIn(
            "A missing or mismatched correlation ID fails the lane closed.", report_back
        )
        self.assertIn(
            "a missing or mismatched ID still fails the lane closed", report_back
        )
        self.assertIn("does not replace the correlation rule", report_back)


if __name__ == "__main__":
    unittest.main()
