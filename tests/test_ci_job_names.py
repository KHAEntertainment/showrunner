"""Tests that every CI job named in PROJECT_CONTEXT.md's check-ownership table exists.

Issue #259: the check-ownership table binds each gate command to one executor
by naming a CI job, and the completion verifier binds CI proof to those job
names. A renamed job - or a doc that cites a job no workflow defines - breaks
that evidence ownership silently, so the table and the workflow files are
checked against each other here.

The check is read-only and stdlib only: no YAML library, no edit to
PROJECT_CONTEXT.md or to any workflow, and no CI change.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTEXT = ROOT / "PROJECT_CONTEXT.md"
WORKFLOW_DIR = ROOT / ".github" / "workflows"

# A standalone "job" or "jobs" word introduces a cited job name.
_JOB_WORD = re.compile(r"\bjobs?\b")
# A backticked token.
_BACKTICKED = re.compile(r"`([^`]*)`")
# A job name's optional parameter part, e.g. "Bash installer (${{ matrix.os }})".
_PARAMETERISED = re.compile(r"^(?P<prefix>.*?)\s*\((?P<parameter>[^()]*)\)\s*$")
# A citation list continues across ", " and stops at any other separator.
_LIST_SEPARATOR = re.compile(r"[\s,]*")
# A job key inside the "jobs:" block.
_JOB_KEY = re.compile(r"^([^:#][^:]*):")
# A job's display name, directly under the job key.
_JOB_NAME = re.compile(r"^name:\s*(.*)$")

# The names used by the synthetic fixtures.
UNKNOWN_JOB = "Ghost Job"
MATRIX_JOB_NAME = "Bash installer (${{ matrix.os }})"
MATRIX_JOB_CITATION = "Bash installer (ubuntu-latest)"

# A synthetic check-ownership table. It cites one real job and one name no
# workflow defines, and it carries the two decoys the parser must ignore: a
# gate command and a tag name after the job list.
SYNTHETIC_CONTEXT = """\
## Verification Gate

**Check ownership** (synthetic fixture for Issue #259).

| Gate commands | Executor (owner) | Evidence consumers cite |
| --- | --- | --- |
| `python3 scripts/validate_skill.py` | PR CI: Verification Gate workflow, job `Skill validation` | run, job, attempt |
| `bash tests/test-install.sh` | Release Gate workflow, jobs `Skill validation`, `Ghost Job`; runs on a `vX.Y.Z` tag | run, job, attempt |
"""

# A synthetic workflow. Every "name:" that is not a job name is a decoy: the
# workflow's own name, a four-space "name:" under "on:" (which a plain
# `^\s{4}name:` match would wrongly collect) and a step input's name.
SYNTHETIC_WORKFLOW = """\
name: Verification Gate

on:
  pull_request:
    name: Not a job name

jobs:
  skill:
    name: Skill validation
    runs-on: ubuntu-latest
    steps:
      - run: python3 scripts/validate_skill.py
        with:
          name: Not a job name either
"""

# A synthetic workflow whose job is displayed as a fixed prefix plus a
# rendered matrix parameter.
SYNTHETIC_MATRIX_WORKFLOW = """\
name: Release Gate

on:
  push:
    tags:
      - 'v*'

jobs:
  installer:
    name: Bash installer (${{ matrix.os }})
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest]
    steps:
      - run: bash tests/test-install.sh
"""


def _check_ownership_rows(text: str) -> list[list[str]]:
    """The rows of the check-ownership table, as lists of their cells.

    The table is the first markdown table after the first "check ownership"
    marker. The header row and the header separator are not rows. Raises
    AssertionError when there is no such table, so a broken extractor fails
    loudly instead of finding nothing and passing.
    """
    lines = text.splitlines()
    marker = next(
        (index for index, line in enumerate(lines) if "check ownership" in line.lower()),
        None,
    )
    if marker is None:
        raise AssertionError("PROJECT_CONTEXT.md has no 'check ownership' table")
    header: list[str] | None = None
    rows: list[list[str]] = []
    for line in lines[marker + 1:]:
        if not line.startswith("|"):
            if header is not None:
                break
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if header is None:
            header = cells
            continue
        if all(set(cell) <= set("-: ") for cell in cells):
            continue  # the header separator row
        rows.append(cells)
    if header is None:
        raise AssertionError("PROJECT_CONTEXT.md has no 'check ownership' table")
    return rows


def _cited_names_in_cell(cell: str) -> list[str]:
    """The job names one table cell cites.

    A backticked token is a job citation when the text between it and the
    previous backticked token names a "job" or "jobs". A citation list
    continues across ", " separators and stops at the first other separator,
    so "jobs `A`, `B`; runs on a `vX.Y.Z` tag" cites A and B, not `vX.Y.Z`.
    """
    names: list[str] = []
    leading = False
    previous_end = 0
    for token in _BACKTICKED.finditer(cell):
        gap = cell[previous_end:token.start()]
        if _JOB_WORD.search(gap):
            leading = True
        elif not (leading and _LIST_SEPARATOR.fullmatch(gap)):
            leading = False
        if leading:
            names.append(token.group(1))
        previous_end = token.end()
    return names


def extract_cited_job_names(text: str) -> list[str]:
    """Every job name the check-ownership table cites, in table order.

    Only backticked tokens led by a "job" or "jobs" word count, so the gate
    commands and the tag and label names in the same table are not mistaken
    for job names.
    """
    names: list[str] = []
    for row in _check_ownership_rows(text):
        for cell in row:
            names.extend(_cited_names_in_cell(cell))
    return names


def _job_names_in_workflow(text: str) -> list[str]:
    """The display names of the jobs one workflow file defines.

    Only a "name:" that sits directly under a job key inside the "jobs:"
    block is a job name: the workflow's own "name:" (column 0) and a deeper
    "name:" (a step input, a matrix key) are not. A job that declares no
    "name:" is displayed under its job id, so the id is used for it.
    """
    names: list[str] = []
    in_jobs = False
    job_indent: int | None = None
    job_id: str | None = None
    job_name: str | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if not in_jobs:
            if indent == 0 and stripped == "jobs:":
                in_jobs = True
            continue
        if indent == 0:
            break  # the jobs block ended
        if job_indent is None:
            job_indent = indent
        if indent == job_indent:
            if job_id is not None:
                names.append(job_name if job_name is not None else job_id)
            match = _JOB_KEY.match(stripped)
            job_id = match.group(1).strip() if match else None
            job_name = None
            continue
        if indent == job_indent + 2:
            match = _JOB_NAME.match(stripped)
            if match:
                job_name = match.group(1).strip().strip("'\"") or None
    if job_id is not None:
        names.append(job_name if job_name is not None else job_id)
    return names


def workflow_job_names(workflow_dir: Path) -> list[str]:
    """The display names of every job defined under a workflow directory."""
    names: list[str] = []
    paths = sorted(workflow_dir.glob("*.yml")) + sorted(workflow_dir.glob("*.yaml"))
    for path in paths:
        names.extend(_job_names_in_workflow(path.read_text(encoding="utf-8")))
    return names


def job_name_matches(citation: str, job_name: str) -> bool:
    """Whether a cited name is satisfied by a job's display name.

    A matrix job is displayed as its fixed prefix plus a rendered parameter:
    "Bash installer (${{ matrix.os }})" is shown as "Bash installer
    (ubuntu-latest)". So a citation matches a parameterised job when both
    sides share the prefix before " (" and at least one side's parameter part
    is a "${{ ... }}" expression. Two concrete names that merely share a
    prefix are different jobs and do not match each other.
    """
    if citation == job_name:
        return True
    cited = _PARAMETERISED.match(citation)
    job = _PARAMETERISED.match(job_name)
    if cited is None or job is None:
        return False
    prefix = cited.group("prefix")
    if not prefix or prefix != job.group("prefix"):
        return False
    return "${{" in cited.group("parameter") or "${{" in job.group("parameter")


def find_missing_job_names(cited: list[str], available: list[str]) -> list[str]:
    """The cited names that no workflow job satisfies."""
    return [
        name
        for name in cited
        if not any(job_name_matches(name, job) for job in available)
    ]


def missing_job_names_message(missing: list[str]) -> str:
    """A message naming every cited job that no workflow defines."""
    return (
        "PROJECT_CONTEXT.md's check-ownership table cites CI job names that no "
        "workflow defines: " + ", ".join(missing)
    )


class OwnershipTableJobNamesTest(unittest.TestCase):
    """Issue #259: the check-ownership table and the workflow files agree."""

    def test_ownership_table_jobs_exist(self) -> None:
        """Every job the table cites is a job name in the workflows."""
        cited = extract_cited_job_names(CONTEXT.read_text(encoding="utf-8"))
        self.assertTrue(
            cited,
            "PROJECT_CONTEXT.md's check-ownership table cites no job name; "
            "the extractor is broken, not the table",
        )
        available = workflow_job_names(WORKFLOW_DIR)
        self.assertTrue(available, "no workflow job name found")
        missing = find_missing_job_names(cited, available)
        self.assertEqual([], missing, missing_job_names_message(missing))

    def test_unknown_job_name_fails(self) -> None:
        """A cited name that no job defines fails, and the failure names it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflows = root / ".github" / "workflows"
            workflows.mkdir(parents=True)
            (root / "PROJECT_CONTEXT.md").write_text(SYNTHETIC_CONTEXT, encoding="utf-8")
            (workflows / "ci.yml").write_text(SYNTHETIC_WORKFLOW, encoding="utf-8")

            cited = extract_cited_job_names(
                (root / "PROJECT_CONTEXT.md").read_text(encoding="utf-8")
            )
            # The gate command and the tag name are not job citations.
            self.assertNotIn("vX.Y.Z", cited)
            self.assertNotIn("python3 scripts/validate_skill.py", cited)
            available = workflow_job_names(workflows)
            # Only the job's own display name is a job name: not the
            # workflow's name, not a "name:" under "on:", not a step input's.
            self.assertIn("Skill validation", available)
            self.assertNotIn("Verification Gate", available)
            self.assertNotIn("Not a job name", available)
            self.assertNotIn("Not a job name either", available)

            missing = find_missing_job_names(cited, available)
            self.assertIn(UNKNOWN_JOB, missing)
            self.assertNotIn("Skill validation", missing)
            self.assertIn(UNKNOWN_JOB, missing_job_names_message(missing))

    def test_matrix_job_prefix_matches(self) -> None:
        """A matrix job satisfies a citation of one of its rendered names."""
        with tempfile.TemporaryDirectory() as tmp:
            workflows = Path(tmp) / ".github" / "workflows"
            workflows.mkdir(parents=True)
            (workflows / "release-gate.yml").write_text(
                SYNTHETIC_MATRIX_WORKFLOW, encoding="utf-8"
            )

            available = workflow_job_names(workflows)
            self.assertIn(MATRIX_JOB_NAME, available)
            # Both rendered names of the matrix job are satisfied by it.
            missing = find_missing_job_names(
                [MATRIX_JOB_CITATION, "Bash installer (macos-latest)"], available
            )
            self.assertEqual([], missing, missing_job_names_message(missing))
            # A name that shares no prefix with the job is still unknown.
            self.assertEqual(
                [UNKNOWN_JOB], find_missing_job_names([UNKNOWN_JOB], available)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
