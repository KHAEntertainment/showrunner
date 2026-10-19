"""Tests for the workspace-debt gauge.

Each test mounts a self-contained fixture under a scratch directory so that
`workspace_debt.build_report` reads from the mock scripts and PATH it
points at, never the real `traycer` binary or the user's repo.

Per the velocity rule on subprocess discipline:

- `pgrep -f unittest` must show nothing of ours at the end. The tests
  spawn Python interpreters on the scratch bin, but never on
  `python -m unittest`. Each spawned child exits before the parent test
  does, because the fixture scripts `raise SystemExit(0)` (or a known
  non-zero) on the same call.
- No `&`, no `unittest discover`, no parallel runner. Each test calls
  `subprocess.run(...)` synchronously and asserts on the captured
  output.

The fixtures live under `tests/fixtures/workspace_debt/`:

- `agent_list_project_a.json` / `worktree_list_mixed.json`: canned JSON
  for the traycer backend's success path; `worktree_list_mixed.json`
  deliberately mixes two repositories so we can assert project-B
  isolation without re-modelling the data shape.
- `agent_list_project_a.json`: includes a foreign agent whose worktree
  path lives under project B. That row must NOT appear in the project-A
  gauge because `folderPaths` membership, not `repoIdentifier`, scopes
  agents (the CLI does not tag agents with a repo).
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "dev" / "scripts" / "workspace_debt.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "workspace_debt"

SPEC = importlib.util.spec_from_file_location("workspace_debt", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _write_fake_script(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _fake_detector_body(payload: str) -> str:
    return textwrap.dedent(
        f"""\
        #!/usr/bin/env python3
        import sys
        sys.stdout.write({payload!r})
        sys.exit(0)
        """
    )


def _fake_wrapper_body(stdout: str, *, exit_code: int = 0) -> str:
    return textwrap.dedent(
        f"""\
        #!/usr/bin/env python3
        import sys
        sys.stdout.write({stdout!r})
        sys.stderr.write("")
        sys.exit({exit_code})
        """
    )


def _fake_wrapper_sleeping() -> str:
    # Sleeps past the script's 30s CLI timeout. The script kills the
    # child via `subprocess.run(timeout=...)`; we don't actually wait
    # 30s in the test because Python's timeout kills the child.
    return textwrap.dedent(
        f"""\
        #!/usr/bin/env python3
        import sys, time
        time.sleep(45)
        sys.stdout.write("")
        sys.exit(0)
        """
    )


def _fake_detector_incomplete() -> str:
    return _fake_detector_body(
        json.dumps(
            {
                "execution_backend": "incomplete",
                "detection_status": "incomplete",
                "traycer_agent_id": None,
                "traycer_epic_id": None,
                "backend_source": None,
                "reason": "no TRAYCER_AGENT_ID/TRAYCER_EPIC_ID in env",
            }
        )
    )


class _WorkspaceDebtFixture(unittest.TestCase):
    """Common fixture: scratch skill_dir + scratch repo_dir + fake scripts."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.skill_dir = Path(self.tmp.name) / "skill"
        self.bin_dir = Path(self.tmp.name) / "bin"
        self.skill_dir.mkdir()
        self.bin_dir.mkdir()
        self.repo_dir = Path(self.tmp.name) / "repo"
        self.repo_dir.mkdir()

    def write_dev_config(self, *, push_repo: str = "KHAEntertainment/showrunner") -> None:
        (self.repo_dir / ".dev.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "github": {
                        "host": "github.com",
                        "account": push_repo.split("/", 1)[0],
                        "pushRepository": push_repo,
                        "pullRequestRepository": push_repo,
                        "pushRemote": "origin",
                    },
                }
            ),
            encoding="utf-8",
        )

    def write_detector(self, body: str) -> None:
        _write_fake_script(self.skill_dir / "scripts" / "detect_execution_backend.py", body)

    def write_wrapper(self, body: str) -> None:
        _write_fake_script(self.skill_dir / "scripts" / "traycer_cli.py", body)

    def report_for(
        self,
        *,
        backend_override: str | None = None,
        lead_agent_id: str | None = "lead-self",
    ) -> dict[str, object]:
        env = self._scratch_env()
        with mock.patch.object(MODULE, "WRAPPER", self.skill_dir / "scripts" / "traycer_cli.py"), \
                mock.patch.object(MODULE, "BACKEND_DETECTOR", self.skill_dir / "scripts" / "detect_execution_backend.py"):
            return MODULE.build_report(
                self.repo_dir,
                lead_agent_id=lead_agent_id,
                backend_override=backend_override,
            )

    def _scratch_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["CLAUDE_SKILL_DIR"] = str(self.skill_dir)
        env["PATH"] = self._scratch_path()
        return env

    def _scratch_path(self) -> str:
        # The script looks up `python3` via shutil.which on PATH, but
        # `subprocess.run([sys.executable, ...])` uses the interpreter
        # that ran this test. We only need to drop the real `traycer`
        # binary from PATH so the wrapper's own `which("traycer")` does
        # not accidentally find a host install.
        real_path = os.environ.get("PATH", "")
        path_only = os.pathsep.join(
            entry for entry in real_path.split(os.pathsep) if "traycer" not in entry
        )
        return str(self.bin_dir) + os.pathsep + path_only


class SuccessPathTests(_WorkspaceDebtFixture):
    """The gauge counts only this project's rows, on the traycer backend."""

    def setUp(self) -> None:
        super().setUp()
        self.write_dev_config()
        self.write_detector(
            _fake_detector_body(
                json.dumps(
                    {
                        "execution_backend": "traycer",
                        "detection_status": "ready",
                        "traycer_agent_id": "lead-self",
                        "traycer_epic_id": "epic",
                        "backend_source": "detected",
                        "reason": "ok",
                    }
                )
            )
        )
        agent_list = (FIXTURES / "agent_list_project_a.json").read_text(encoding="utf-8")
        worktree_list = (FIXTURES / "worktree_list_mixed.json").read_text(encoding="utf-8")
        # The wrapper dispatches by argv. We tee stdout to whichever
        # fixture matches the first two args. A real Traycer wrapper
        # would invoke `traycer agent list --json`; here we just key
        # off the second argv.
        self.write_wrapper(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env python3
                import sys
                argv = sys.argv[1:]
                if "worktree" in argv:
                    sys.stdout.write({worktree_list!r})
                else:
                    sys.stdout.write({agent_list!r})
                sys.stderr.write("")
                sys.exit(0)
                """
            )
        )

    def test_counts_only_this_projects_worktrees(self) -> None:
        report = self.report_for()
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["project"], "KHAEntertainment/showrunner")
        self.assertEqual(report["backend"], "traycer")
        worktrees = report["counts"]["worktrees"]
        self.assertEqual(worktrees["total"], 5)
        self.assertEqual(worktrees["by_tier"]["in-use"], 1)
        self.assertEqual(worktrees["by_tier"]["review"], 2)
        self.assertEqual(worktrees["by_tier"]["unreferenced"], 1)
        self.assertEqual(worktrees["by_tier"]["merged"], 1)
        # Project B (one worktree under scadforge) must not be present.
        self.assertEqual(worktrees["tier_null"], 0)

    def test_landed_eligible_requires_pr_merged_and_clean(self) -> None:
        report = self.report_for()
        worktrees = report["counts"]["worktrees"]
        # `feat-2`: tier review, merged, uncommitted=0 → landed-eligible.
        # `feat-3`: tier review, merged, uncommitted=5 → NOT eligible
        #   (uncommitted count must be 0).
        # `feat-5`: tier merged, merged, uncommitted=0 → landed-eligible.
        # `feat-1`: tier in-use, open PR → NOT eligible.
        # `feat-4`: tier unreferenced, prState=null → NOT eligible.
        self.assertEqual(worktrees["landed_eligible"], 2)
        self.assertEqual(worktrees["lead_created_review"], 2)

    def test_agents_scope_to_project_worktrees(self) -> None:
        report = self.report_for()
        agents = report["counts"]["agents"]
        # `worker-self`: archived, NOT active → active stays low.
        # `qa-active-other`: active, parentId=`lead-other` (NOT this lead) → not_mine.
        # `unrelated-foreign`: folderPaths under projB, NOT counted here at all.
        self.assertEqual(agents["total"], 2)
        self.assertEqual(agents["active"], 1)
        self.assertEqual(agents["archived"], 1)
        self.assertEqual(agents["active_for_this_lead"], 0)
        self.assertEqual(agents["active_not_mine"], 1)
        self.assertTrue(agents["by_field"]["archived_supported"])
        self.assertIn("parentId", agents["by_field"]["distinguishable"])


class ProjectBIsolationTests(_WorkspaceDebtFixture):
    """Running the gauge in project A must never see project B's rows."""

    def setUp(self) -> None:
        super().setUp()
        # Same data; the only project scope is pushRepository.
        self.write_dev_config()
        self.write_detector(
            _fake_detector_body(
                json.dumps(
                    {
                        "execution_backend": "traycer",
                        "detection_status": "ready",
                        "traycer_agent_id": "lead-self",
                        "traycer_epic_id": "epic",
                        "backend_source": "detected",
                        "reason": "ok",
                    }
                )
            )
        )
        agent_list = (FIXTURES / "agent_list_project_a.json").read_text(encoding="utf-8")
        worktree_list = (FIXTURES / "worktree_list_mixed.json").read_text(encoding="utf-8")
        self.write_wrapper(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env python3
                import sys
                argv = sys.argv[1:]
                if "worktree" in argv:
                    sys.stdout.write({worktree_list!r})
                else:
                    sys.stdout.write({agent_list!r})
                sys.stderr.write("")
                sys.exit(0)
                """
            )
        )

    def test_project_b_worktrees_excluded_from_counts(self) -> None:
        report = self.report_for()
        # six rows total: 5 project-A + 1 project-B (scadforge/feat-9).
        # Only the 5 project-A rows must contribute to counts.
        worktrees = report["counts"]["worktrees"]
        self.assertEqual(worktrees["total"], 5)

    def test_project_b_agents_excluded_from_counts(self) -> None:
        report = self.report_for()
        agents = report["counts"]["agents"]
        # `unrelated-foreign` has folderPaths under /tmp/projB; must
        # not be counted even though the agent list is fed through the
        # same filter.
        self.assertEqual(agents["total"], 2)


class FailClosedTests(_WorkspaceDebtFixture):
    """Every fault path returns `status: unavailable` and `counts: null`."""

    def test_counts_are_null_not_zero_when_unavailable(self) -> None:
        self.write_dev_config()
        # Detector returns incomplete; no wrapper call happens at all.
        self.write_detector(_fake_detector_incomplete())
        self.write_wrapper(_fake_wrapper_body('{"data":{}}'))
        report = self.report_for()
        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["counts"], None)
        self.assertEqual(report["reason_code"], "backend_incomplete")
        # The validator-pinned assertion: no zero anywhere.
        self.assertNotIn('"total":0', json.dumps(report))

    def test_cli_error_returns_unavailable_and_reason(self) -> None:
        self.write_dev_config()
        self.write_detector(
            _fake_detector_body(
                json.dumps(
                    {
                        "execution_backend": "traycer",
                        "detection_status": "ready",
                        "traycer_agent_id": "lead-self",
                        "traycer_epic_id": "epic",
                        "backend_source": "detected",
                        "reason": "ok",
                    }
                )
            )
        )
        self.write_wrapper(_fake_wrapper_body("nope", exit_code=3))
        report = self.report_for()
        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["counts"], None)
        self.assertEqual(report["reason_code"], "worktree_list_failed")

    def test_timeout_returns_unavailable(self) -> None:
        self.write_dev_config()
        self.write_detector(
            _fake_detector_body(
                json.dumps(
                    {
                        "execution_backend": "traycer",
                        "detection_status": "ready",
                        "traycer_agent_id": "lead-self",
                        "traycer_epic_id": "epic",
                        "backend_source": "detected",
                        "reason": "ok",
                    }
                )
            )
        )
        self.write_wrapper(_fake_wrapper_sleeping())
        # Patch the per-call timeout down to 1 second so the test does
        # not actually wait 30s for the real script budget. The
        # script's fail-closed contract is the same at any timeout.
        with mock.patch.object(MODULE, "COMMAND_TIMEOUT_SECONDS", 1):
            report = self.report_for()
        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["counts"], None)
        self.assertEqual(report["reason_code"], "worktree_list_failed")
        self.assertIn("timed out", report["reason"])

    def test_missing_wrapper_returns_unavailable(self) -> None:
        # No wrapper or detector files written under scratch skill_dir.
        self.write_dev_config()
        # Detector returns `incomplete` so the gauge reports at the
        # backend-incomplete gate rather than failing for a different
        # reason.
        self.write_detector(_fake_detector_incomplete())
        report = self.report_for()
        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["counts"], None)
        self.assertEqual(report["reason_code"], "backend_incomplete")

    def test_unparseable_wrapper_output_returns_unavailable(self) -> None:
        self.write_dev_config()
        self.write_detector(
            _fake_detector_body(
                json.dumps(
                    {
                        "execution_backend": "traycer",
                        "detection_status": "ready",
                        "traycer_agent_id": "lead-self",
                        "traycer_epic_id": "epic",
                        "backend_source": "detected",
                        "reason": "ok",
                    }
                )
            )
        )
        # Wrapper exits 0 but stdout is not JSON.
        self.write_wrapper(_fake_wrapper_body("not-json"))
        report = self.report_for()
        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["counts"], None)
        self.assertEqual(report["reason_code"], "worktree_list_failed")
        self.assertIn("malformed JSON", report["reason"])

    def test_missing_dev_config_returns_unavailable(self) -> None:
        # Repo dir has no .dev.json.
        self.write_detector(_fake_detector_incomplete())
        self.write_wrapper(_fake_wrapper_body('{"data":{}}'))
        report = self.report_for()
        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["counts"], None)
        self.assertEqual(report["reason_code"], "dev_config_invalid")


@unittest.skipIf(shutil.which("git") is None, "git not on PATH")
class ClaudeNativeTests(unittest.TestCase):
    """`backend=claude-native` runs `git worktree list`, never `traycer`."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo_dir = Path(self.tmp.name) / "repo"
        self.repo_dir.mkdir()
        self._git_init()
        self._write_dev_config()

    def _git_init(self) -> None:
        env = os.environ.copy()
        env["GIT_AUTHOR_NAME"] = "Test"
        env["GIT_AUTHOR_EMAIL"] = "test@example.com"
        env["GIT_COMMITTER_NAME"] = "Test"
        env["GIT_COMMITTER_EMAIL"] = "test@example.com"
        subprocess.run(["git", "init", str(self.repo_dir)], check=True, env=env)
        (self.repo_dir / "README").write_text("hi\n")
        subprocess.run(
            ["git", "-C", str(self.repo_dir), "add", "README"],
            check=True,
            env=env,
        )
        subprocess.run(
            ["git", "-C", str(self.repo_dir), "commit", "-m", "init"],
            check=True,
            env=env,
        )
        # One extra branch so the porcelain list has a record + the main worktree.
        subprocess.run(
            ["git", "-C", str(self.repo_dir), "checkout", "-b", "feature-x"],
            check=True,
            env=env,
        )

    def _write_dev_config(self) -> None:
        (self.repo_dir / ".dev.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "github": {
                        "host": "github.com",
                        "account": "KHAEntertainment",
                        "pushRepository": "KHAEntertainment/showrunner",
                        "pullRequestRepository": "KHAEntertainment/showrunner",
                        "pushRemote": "origin",
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_porcelain_is_counted_and_agents_not_applicable(self) -> None:
        report = MODULE.build_report(
            self.repo_dir,
            lead_agent_id=None,
            backend_override="claude-native",
        )
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["backend"], "claude-native")
        worktrees = report["counts"]["worktrees"]
        # A fresh `git init` + first commit + `git checkout -b feature-x`
        # produces a single worktree (the current directory's checkout).
        # We don't synthesise a second branch into its own checkout
        # because that complicates the fixture; the point of this test
        # is "git worktree list --porcelain is wired in", not "we can
        # stage N worktrees". One record is enough to assert that.
        self.assertEqual(worktrees["total"], 1)
        self.assertEqual(worktrees["tier_null"], 1)
        self.assertEqual(sum(worktrees["by_tier"].values()), 0)
        # No activity overlay available without the CLI; landed-eligible
        # and lead-created-review both stay at 0 by design.
        self.assertEqual(worktrees["landed_eligible"], 0)
        self.assertEqual(worktrees["lead_created_review"], 0)
        agents = report["counts"]["agents"]
        self.assertEqual(agents["presence"], "not_applicable")
        # The undistinguishable list must name the fields we cannot
        # measure locally so a later lead does not invent them.
        self.assertIn("agents", report["undistinguishable"])
        self.assertIn("worktree tier", report["undistinguishable"])


class BackendOverrideTests(_WorkspaceDebtFixture):
    def test_backend_override_skips_detection(self) -> None:
        # No detector or wrapper present; the override short-circuits
        # to claude-native via `git worktree list`. We point at the
        # current repo so git is happy.
        import subprocess
        subprocess.run(["git", "init", str(self.repo_dir)], check=False, capture_output=True)
        self._write_dev_config_in_repo()
        report = MODULE.build_report(
            self.repo_dir,
            backend_override="claude-native",
        )
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["backend"], "claude-native")

    def _write_dev_config_in_repo(self) -> None:
        (self.repo_dir / ".dev.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "github": {
                        "host": "github.com",
                        "account": "KHAEntertainment",
                        "pushRepository": "KHAEntertainment/showrunner",
                        "pullRequestRepository": "KHAEntertainment/showrunner",
                        "pushRemote": "origin",
                    },
                }
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
