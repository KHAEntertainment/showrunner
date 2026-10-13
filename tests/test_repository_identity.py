from __future__ import annotations

import contextlib
import io
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESOLVER = ROOT / "skills" / "dev" / "scripts" / "resolve_repository.py"
SPEC = importlib.util.spec_from_file_location("resolve_repository", RESOLVER)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

CANONICAL = "KHAEntertainment/claude-dev-skill"
PARENT = "hnaymyh123-henry/claude-dev-skill"
ORIGIN_HTTPS = "https://github.com/KHAEntertainment/claude-dev-skill.git"
UPSTREAM_HTTPS = "https://github.com/hnaymyh123-henry/claude-dev-skill.git"

VALID_DOC = {
    "version": 1,
    "github": {
        "host": "github.com",
        "account": "KHAEntertainment",
        "pushRepository": CANONICAL,
        "pullRequestRepository": CANONICAL,
        "pushRemote": "origin",
    },
}

CONTRIBUTOR_DOC = {
    "version": 1,
    "github": {
        "host": "github.com",
        "account": "KHAEntertainment",
        "pushRepository": CANONICAL,
        "pullRequestRepository": PARENT,
        "pushRemote": "origin",
    },
}


def _git(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(cwd), check=check, capture_output=True, text=True)


def _init_repo_with_config(root: Path, doc: dict[str, object]) -> None:
    _git("init", "-q", cwd=root)
    _git("config", "user.email", "test@example.com", cwd=root)
    _git("config", "user.name", "Test", cwd=root)
    (root / "README.md").write_text("hello\n", encoding="utf-8")
    _git("add", "README.md", cwd=root)
    _git("commit", "-q", "-m", "initial", cwd=root)
    (root / ".dev.json").write_text(json.dumps(doc), encoding="utf-8")


# HTTP-method tokens are the only ones that appear as argv tokens, not phrases.
MUTATING_TOKENS = ("POST", "PATCH", "PUT", "--method")

MUTATING_PHRASES = (
    r"\bgh\s+issue\s+create\b",
    r"\bgh\s+issue\s+comment\b",
    r"\bgh\s+pr\s+create\b",
    r"\bgh\s+pr\s+comment\b",
    r"\bgh\s+pr\s+review\b",
    r"\bgh\s+pr\s+merge\b",
)


def _is_bare_push(joined: str) -> bool:
    """A `git push` line is mutating unless it is explicitly `--dry-run`."""
    if not re.search(r"\bgit\s+push\b", joined):
        return False
    return "--dry-run" not in joined


# Read-only (or dry-run) command shapes the resolver may emit.
READ_ONLY_COMMANDS = (
    (("git", "branch", "--show-current"), 0, 0),
    (("git", "check-ref-format"), 1, 1),
    (("git", "config"), 1, 2),
    (("git", "remote"), 0, 0),
    (("git", "remote", "get-url", "--all"), 1, 1),
    (("git", "remote", "get-url", "--push", "--all"), 1, 1),
    (("git", "push", "--dry-run"), 2, 2),
    (("git", "rev-parse", "--show-toplevel"), 0, 0),
    (("git", "ls-files", "--error-unmatch"), 1, 1),
    (("git", "check-ignore", "-q"), 1, 1),
    (("gh", "repo", "set-default", "--view"), 0, 0),
    (("gh", "repo", "view"), 1, None),
    (("gh", "api", "--hostname", "github.com", "user", "--jq", ".login"), 0, 0),
)

# Generic git/gh stub. The test sets FIXTURE (JSON) in the environment.
STUB = """#!{python}
import json
import os
import sys

with open(os.environ["REPO_IDENTITY_LOG"], "a", encoding="utf-8") as handle:
    handle.write("\\t".join([os.path.basename(sys.argv[0])] + sys.argv[1:]) + "\\n")

fixture = json.loads(os.environ.get("FIXTURE", "{{}}"))
name = os.path.basename(sys.argv[0])
args = sys.argv[1:]

if name == "git" and args == ["branch", "--show-current"]:
    print(fixture.get("branch", "main"))
    raise SystemExit(0)

if name == "git" and args[0] == "config":
    key = args[1]
    value = fixture.get("config", {{}}).get(key, "")
    if value:
        print(value)
        raise SystemExit(0)
    raise SystemExit(1)

if name == "git" and args[0] == "check-ref-format":
    raise SystemExit(0)

if name == "git" and args == ["remote"]:
    for remote in fixture.get("remotes", {{}}):
        print(remote)
    raise SystemExit(0)

if name == "git" and args[:3] == ["remote", "get-url", "--all"]:
    remote = args[3]
    for url in fixture.get("remotes", {{}}).get(remote, {{}}).get("fetch", []):
        print(url)
    raise SystemExit(0)

if name == "git" and args[:4] == ["remote", "get-url", "--push", "--all"]:
    remote = args[4]
    for url in fixture.get("remotes", {{}}).get(remote, {{}}).get("push", []):
        print(url)
    raise SystemExit(0)

if name == "git" and args[:2] == ["push", "--dry-run"]:
    code = int(fixture.get("dry_run_exit", 0))
    if code != 0:
        sys.stderr.write("dry run rejected\\n")
    raise SystemExit(code)

if name == "gh" and args == ["repo", "set-default", "--view"]:
    default = fixture.get("gh_default", "")
    if default and not default.lower().startswith("no default"):
        print(default)
        raise SystemExit(0)
    sys.stderr.write((default or "no default repository has been set") + "\\n")
    raise SystemExit(0)

if name == "gh" and args[:2] == ["repo", "view"]:
    print(args[2].removeprefix("github.com/"))
    raise SystemExit(0)

if name == "gh" and args[:5] == ["api", "--hostname", "github.com", "user", "--jq"]:
    login = fixture.get("gh_login", "")
    if login:
        print(login)
        raise SystemExit(0)
    raise SystemExit(1)

# dev_config's provenance checks: these fixture-driven CLI tests are about
# identity/branch/dry-run logic, not provenance (covered separately with
# real git), so the stub always reports "this is the repo root, the config
# is untracked, and it is ignored" -- i.e. a config that reuses cleanly.
if name == "git" and args == ["rev-parse", "--show-toplevel"]:
    print(os.getcwd())
    raise SystemExit(0)

if name == "git" and args[:2] == ["ls-files", "--error-unmatch"]:
    raise SystemExit(1)

if name == "git" and args[:2] == ["check-ignore", "-q"]:
    raise SystemExit(0)

sys.stderr.write("unexpected command\\n")
raise SystemExit(1)
"""


class RemoteNormalizationTests(unittest.TestCase):
    def test_https_and_ssh_forms_normalize_identically(self) -> None:
        equivalent = (
            "https://github.com/KHAEntertainment/claude-dev-skill.git",
            "https://github.com/KHAEntertainment/claude-dev-skill",
            "https://github.com/KHAEntertainment/claude-dev-skill/",
            "http://github.com/KHAEntertainment/claude-dev-skill.git",
            "https://KHAEntertainment@github.com/KHAEntertainment/claude-dev-skill.git",
            "git@github.com:KHAEntertainment/claude-dev-skill.git",
            "git@github.com:KHAEntertainment/claude-dev-skill",
            "ssh://git@github.com/KHAEntertainment/claude-dev-skill.git",
            "ssh://git@github.com:22/KHAEntertainment/claude-dev-skill.git",
            "git://github.com/KHAEntertainment/claude-dev-skill.git",
            "  https://github.com/KHAEntertainment/claude-dev-skill.git  ",
        )
        for url in equivalent:
            with self.subTest(url=url):
                self.assertEqual(CANONICAL, MODULE.normalize_remote(url))

    def test_non_github_and_ambiguous_origins_are_rejected(self) -> None:
        cases = (
            ("https://gitlab.com/KHAEntertainment/claude-dev-skill.git", "non_github_origin"),
            ("git@gitlab.com:KHAEntertainment/claude-dev-skill.git", "non_github_origin"),
            ("https://github.example.com/KHAEntertainment/claude-dev-skill.git", "non_github_origin"),
            ("file:///srv/git/claude-dev-skill.git", "non_github_origin"),
            ("https://github.com/KHAEntertainment", "ambiguous_origin"),
            ("https://github.com/KHAEntertainment/claude-dev-skill/extra", "ambiguous_origin"),
            ("/srv/git/claude-dev-skill.git", "ambiguous_origin"),
            ("", "ambiguous_origin"),
        )
        for url, code in cases:
            with self.subTest(url=url):
                with self.assertRaises(MODULE.RepositoryError) as caught:
                    MODULE.normalize_remote(url)
                self.assertEqual(code, caught.exception.code)

    def test_whitespace_in_local_path_is_rejected(self) -> None:
        cases = ("/tmp/exfil dir/stash.git", "/tmp/exfil dir/stash")
        for url in cases:
            with self.subTest(url=url):
                with self.assertRaises(MODULE.RepositoryError) as caught:
                    MODULE.normalize_remote(url)
                self.assertEqual("ambiguous_origin", caught.exception.code)

    def test_repository_comparison_is_case_insensitive(self) -> None:
        self.assertTrue(MODULE.same_repository(CANONICAL, CANONICAL.lower()))
        self.assertFalse(MODULE.same_repository(CANONICAL, PARENT))

    def test_credentials_are_redacted(self) -> None:
        redacted = MODULE.redact_remote("https://token@github.com/KHAEntertainment/claude-dev-skill.git")
        self.assertEqual("https://github.com/KHAEntertainment/claude-dev-skill.git", redacted)


class SshAliasResolutionTests(unittest.TestCase):
    """`ssh -G` is a pure local config lookup -- no network call is made."""

    def _with_temp_home(self, config_body: str):
        directory = tempfile.TemporaryDirectory()
        home = Path(directory.name)
        config_path = home / "ssh_config"
        config_path.write_text(config_body, encoding="utf-8")
        return directory, home, ("ssh", "-F", str(config_path))

    def test_resolve_ssh_effective_host_reads_alias(self) -> None:
        # OpenSSH resolves the home directory from the system user database,
        # not the `HOME` environment variable, so tests inject an explicit
        # `-F <config>` rather than trying to override `HOME`.
        directory, home, ssh_command = self._with_temp_home(
            "Host corp-github\n    HostName github.com\n    User git\n    Port 443\n"
        )
        with directory:
            resolved = MODULE.resolve_ssh_effective_host(home, "corp-github", ssh_command=ssh_command)
        self.assertIsNotNone(resolved)
        hostname, user, port = resolved
        self.assertEqual("github.com", hostname)
        self.assertEqual("git", user)
        self.assertEqual("443", port)

    def test_normalize_remote_with_ssh_resolution_accepts_alias_pointing_at_github(self) -> None:
        directory, home, ssh_command = self._with_temp_home("Host corp-github\n    HostName github.com\n    User git\n")
        with directory:
            result = MODULE.normalize_remote_with_ssh_resolution(
                "git@corp-github:KHAEntertainment/claude-dev-skill.git", home, ssh_command=ssh_command
            )
        self.assertEqual(CANONICAL, result)

    def test_normalize_remote_with_ssh_resolution_rejects_alias_pointing_elsewhere(self) -> None:
        directory, home, ssh_command = self._with_temp_home("Host corp-gitlab\n    HostName gitlab.example.com\n    User git\n")
        with directory:
            with self.assertRaises(MODULE.RepositoryError) as caught:
                MODULE.normalize_remote_with_ssh_resolution(
                    "git@corp-gitlab:Acme/widget.git", home, ssh_command=ssh_command
                )
        self.assertEqual("non_github_origin", caught.exception.code)

    def test_without_repo_dir_alias_is_rejected_not_silently_resolved(self) -> None:
        """The pure offline function never guesses at an alias -- callers
        without a real checkout (e.g. `--fixture`) get the honest `no
        resolution attempted` outcome, never a false accept or a crash."""
        with self.assertRaises(MODULE.RepositoryError) as caught:
            MODULE.normalize_remote_with_ssh_resolution("git@corp-github:Acme/widget.git", None)
        self.assertEqual("non_github_origin", caught.exception.code)


class PushTargetResolutionTests(unittest.TestCase):
    """Finding 2: push validation uses only the remote's actual push URLs;
    fetch URLs are non-blocking context."""

    def resolve(self, **overrides: object) -> dict[str, object]:
        arguments: dict[str, object] = {
            "remotes": {"origin": ORIGIN_HTTPS},
            "push_remotes": None,
            "gh_default": CANONICAL,
            "remote_name": "origin",
            "expected": CANONICAL,
        }
        arguments.update(overrides)
        return MODULE.resolve_repository(**arguments)

    def test_single_remote_with_matching_default_is_ready(self) -> None:
        result = self.resolve()
        self.assertEqual("ready", result["status"])
        self.assertEqual(CANONICAL, result["repository"])

    def test_split_fetch_upstream_push_fork_is_ready_reproduction(self) -> None:
        """Finding 2, reproduction 1: a valid contributor-mode remote that
        fetches upstream but pushes the fork must be `ready`, not
        `remote_url_mismatch`."""
        result = self.resolve(
            remotes={"origin": UPSTREAM_HTTPS},
            push_remotes={"origin": [ORIGIN_HTTPS]},
            expected=CANONICAL,
        )
        self.assertEqual("ready", result["status"])
        self.assertEqual(CANONICAL, result["repository"])
        self.assertTrue(any("fetch" in c for c in result["conflicting_remotes"]))

    def test_multiple_push_urls_all_matching_is_ready(self) -> None:
        result = self.resolve(
            remotes={"origin": ORIGIN_HTTPS},
            push_remotes={"origin": [ORIGIN_HTTPS, "https://github.com/KHAEntertainment/claude-dev-skill"]},
            gh_default=None,
        )
        self.assertEqual("ready", result["status"])
        self.assertEqual(CANONICAL, result["repository"])

    def test_multiple_push_urls_with_hostile_is_incomplete(self) -> None:
        """Two different *push* URLs on the same remote genuinely disagree --
        this remains a real inconsistency, unlike a differing fetch URL."""
        result = self.resolve(
            remotes={"origin": ORIGIN_HTTPS},
            push_remotes={"origin": [ORIGIN_HTTPS, UPSTREAM_HTTPS]},
            gh_default=None,
        )
        self.assertEqual("incomplete", result["status"])
        self.assertEqual("remote_url_mismatch", result["reason_code"])
        self.assertIsNone(result["repository"])

    def test_conflicting_unrelated_remote_does_not_block(self) -> None:
        result = self.resolve(
            remotes={"origin": ORIGIN_HTTPS, "upstream": UPSTREAM_HTTPS},
            push_remotes={"origin": [ORIGIN_HTTPS], "upstream": [UPSTREAM_HTTPS]},
            gh_default=CANONICAL,
            remote_name="origin",
        )
        self.assertEqual("ready", result["status"])
        self.assertEqual(CANONICAL, result["repository"])
        self.assertIn("upstream=hnaymyh123-henry/claude-dev-skill", result["conflicting_remotes"])

    def test_hostile_origin_canonical_effective_push_is_ready(self) -> None:
        result = self.resolve(
            remotes={"origin": UPSTREAM_HTTPS, "fork": ORIGIN_HTTPS},
            push_remotes={"origin": [UPSTREAM_HTTPS], "fork": [ORIGIN_HTTPS]},
            gh_default=CANONICAL,
            remote_name="fork",
        )
        self.assertEqual("ready", result["status"])
        self.assertEqual(CANONICAL, result["repository"])
        self.assertEqual("fork", result["effective_push_remote"])
        self.assertIn("origin=hnaymyh123-henry/claude-dev-skill", result["conflicting_remotes"])

    def test_gh_default_mismatch_does_not_block(self) -> None:
        result = self.resolve(gh_default=PARENT)
        self.assertEqual("ready", result["status"])
        self.assertTrue(any("gh CLI default" in note for note in result["notes"]))

    def test_missing_gh_default_with_conflicts_is_ready(self) -> None:
        result = self.resolve(
            remotes={"origin": ORIGIN_HTTPS, "upstream": UPSTREAM_HTTPS},
            push_remotes={"origin": [ORIGIN_HTTPS], "upstream": [UPSTREAM_HTTPS]},
            gh_default=None,
        )
        self.assertEqual("ready", result["status"])
        self.assertIn("upstream=hnaymyh123-henry/claude-dev-skill", result["conflicting_remotes"])

    def test_assignment_expectation_mismatch_fails_closed(self) -> None:
        result = self.resolve(expected=PARENT)
        self.assertEqual("incomplete", result["status"])
        self.assertEqual("expected_mismatch", result["reason_code"])

    def test_inaccessible_repository_fails_closed(self) -> None:
        result = self.resolve(access_verified=True, verified_name=None)
        self.assertEqual("incomplete", result["status"])
        self.assertEqual("inaccessible_repository", result["reason_code"])

    def test_redirected_origin_fails_closed(self) -> None:
        result = self.resolve(access_verified=True, verified_name="Other/Repo")
        self.assertEqual("incomplete", result["status"])
        self.assertEqual("origin_redirects", result["reason_code"])

    def test_missing_origin_fails_closed(self) -> None:
        result = self.resolve(remotes={"upstream": UPSTREAM_HTTPS}, remote_name="origin")
        self.assertEqual("incomplete", result["status"])
        self.assertEqual("missing_origin", result["reason_code"])

    def test_configured_remote_matching_effective_push_remote_is_ready(self) -> None:
        result = self.resolve(configured_remote="origin")
        self.assertEqual("ready", result["status"])

    def test_configured_remote_mismatch_fails_closed_with_no_fallback(self) -> None:
        result = self.resolve(
            remotes={"origin": ORIGIN_HTTPS, "upstream": UPSTREAM_HTTPS},
            push_remotes={"origin": [ORIGIN_HTTPS], "upstream": [UPSTREAM_HTTPS]},
            remote_name="upstream",
            configured_remote="origin",
            expected=CANONICAL,
        )
        self.assertEqual("incomplete", result["status"])
        self.assertEqual("configured_remote_mismatch", result["reason_code"])
        self.assertIsNone(result["effective_push_remote"])
        self.assertIsNone(result["remote"])
        self.assertIsNone(result["repository"])


class OperationTargetResolutionTests(unittest.TestCase):
    """Finding 2, reproduction 2: a PR/Issue operation's target is validated
    against the *explicit* argument, independent of any git push URL."""

    def test_pr_target_matching_pull_request_repository_is_ready(self) -> None:
        result = MODULE._decide_operation_target(target=PARENT, expected=PARENT)
        self.assertEqual("ready", result["status"])
        self.assertEqual(PARENT, result["repository"])

    def test_contributor_mode_pr_at_upstream_is_ready_reproduction(self) -> None:
        """The exact scenario the review reproduced as `expected_mismatch`:
        pushes go to the fork, but this PR explicitly targets upstream."""
        result = MODULE._decide_operation_target(target=PARENT, expected=PARENT)
        self.assertEqual("ready", result["status"])

    def test_pr_target_mismatch_fails_closed(self) -> None:
        result = MODULE._decide_operation_target(target=CANONICAL, expected=PARENT)
        self.assertEqual("incomplete", result["status"])
        self.assertEqual("operation_target_mismatch", result["reason_code"])

    def test_missing_target_fails_closed(self) -> None:
        result = MODULE._decide_operation_target(target=None, expected=CANONICAL)
        self.assertEqual("incomplete", result["status"])
        self.assertEqual("missing_argument", result["reason_code"])

    def test_assigned_issue_override_accepts_a_differing_qualified_identity(self) -> None:
        result = MODULE._decide_operation_target(target=PARENT, expected=CANONICAL, allow_override=True)
        self.assertEqual("ready", result["status"])
        self.assertEqual(PARENT, result["repository"])

    def test_malformed_target_fails_closed_even_with_override(self) -> None:
        result = MODULE._decide_operation_target(target="not-owner-repo", expected=CANONICAL, allow_override=True)
        self.assertEqual("incomplete", result["status"])


class ProductionEntrypointRequiresConfigTests(unittest.TestCase):
    """Finding 1: the non-fixture CLI path must load `.dev.json` itself and
    never reach `ready` on missing/invalid/tracked config, regardless of
    which optional flags a caller does or does not pass."""

    def _run(self, root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(RESOLVER), "--repo-dir", str(root), *extra],
            check=False, capture_output=True, text=True,
        )

    def test_missing_config_never_yields_ready_reproduction(self) -> None:
        """The review's exact reproduction: an ordinary GitHub remote, no
        `.dev.json`, no --expect, no --configured-remote."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _git("init", "-q", cwd=root)
            completed = self._run(root, "--assigned-branch", "main")
            self.assertEqual(2, completed.returncode)
            payload = json.loads(completed.stdout)
            self.assertNotEqual("ready", payload["status"])
            self.assertIn("config", payload["reason_code"])

    def test_no_verify_access_alone_still_requires_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _git("init", "-q", cwd=root)
            completed = self._run(root, "--no-verify-access", "--assigned-branch", "main")
            self.assertEqual(2, completed.returncode)
            payload = json.loads(completed.stdout)
            self.assertNotEqual("ready", payload["status"])

    def test_tracked_config_never_yields_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _init_repo_with_config(root, VALID_DOC)
            _git("add", ".dev.json", cwd=root)
            _git("commit", "-q", "-m", "add config", cwd=root)
            completed = self._run(root, "--assigned-branch", "main")
            self.assertEqual(2, completed.returncode)
            payload = json.loads(completed.stdout)
            self.assertEqual("tracked_config", payload["reason_code"])

    def test_invalid_config_never_yields_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _git("init", "-q", cwd=root)
            (root / ".dev.json").write_text('{"version": 1}', encoding="utf-8")
            completed = self._run(root, "--assigned-branch", "main")
            self.assertEqual(2, completed.returncode)
            payload = json.loads(completed.stdout)
            self.assertNotEqual("ready", payload["status"])


class ResolverCommandLineTests(unittest.TestCase):
    def _no_write_evidence(self, log_text: str) -> None:
        for raw in log_text.splitlines():
            joined = " ".join(raw.split("\t"))
            for token in MUTATING_TOKENS:
                self.assertNotIn(token, joined)
            for pattern in MUTATING_PHRASES:
                self.assertIsNone(re.search(pattern, joined), f"mutating phrase in: {joined}")
            self.assertFalse(_is_bare_push(joined), f"bare (non-dry-run) push in: {joined}")
            tokens = raw.split("\t")
            leading = tuple(tokens)
            total = len(tokens)
            allowed = any(
                leading[: len(prefix)] == prefix
                and total - len(prefix) >= min_extra
                and (max_extra is None or total - len(prefix) <= max_extra)
                for prefix, min_extra, max_extra in READ_ONLY_COMMANDS
            )
            self.assertTrue(allowed, f"resolver ran unexpected command: {joined}")

    def _run_with_fixture(
        self, fixture: dict[str, object], config: dict[str, object] | None, *extra_args: str
    ) -> tuple[subprocess.CompletedProcess[str], str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stub_dir = root / "stubs"
            stub_dir.mkdir()
            log = root / "commands.log"
            env = {
                "PATH": f"{stub_dir}:{os.environ['PATH']}",
                "REPO_IDENTITY_LOG": str(log),
                "FIXTURE": json.dumps(fixture),
            }
            (stub_dir / "git").write_text(STUB.format(python=sys.executable), encoding="utf-8")
            (stub_dir / "git").chmod(0o755)
            (stub_dir / "gh").write_text(STUB.format(python=sys.executable), encoding="utf-8")
            (stub_dir / "gh").chmod(0o755)
            if config is not None:
                (root / ".dev.json").write_text(json.dumps(config), encoding="utf-8")
            # Exercise argument parsing + main; stub transport auth so this
            # metadata matrix never looks up a real credential or uses network.
            argv = [str(RESOLVER), "--repo-dir", str(root), *extra_args]
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.dict(os.environ, env, clear=True), patch.object(sys, "argv", argv), \
                    patch.object(MODULE, "verify_https_account", return_value={"status": "verified"}), \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = MODULE.main()
            completed = subprocess.CompletedProcess(argv, code, stdout.getvalue(), stderr.getvalue())
            log_text = log.read_text(encoding="utf-8") if log.exists() else ""
            return completed, log_text

    def test_matching_default_exits_zero(self) -> None:
        fixture = {
            "branch": "main",
            "config": {"branch.main.pushRemote": "", "remote.pushDefault": "", "branch.main.remote": "origin"},
            "remotes": {"origin": {"fetch": [ORIGIN_HTTPS], "push": [ORIGIN_HTTPS]}},
            "gh_default": CANONICAL,
        }
        completed, log_text = self._run_with_fixture(fixture, VALID_DOC, "--assigned-branch", "main")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(CANONICAL, payload["repository"])
        self.assertIn("dry_run", payload)
        self._no_write_evidence(log_text)

    def test_fork_with_matching_default_exits_zero(self) -> None:
        fixture = {
            "branch": "main",
            "config": {"branch.main.pushRemote": "", "remote.pushDefault": "", "branch.main.remote": "origin"},
            "remotes": {
                "origin": {"fetch": [ORIGIN_HTTPS], "push": [ORIGIN_HTTPS]},
                "upstream": {"fetch": [UPSTREAM_HTTPS], "push": [UPSTREAM_HTTPS]},
            },
            "gh_default": CANONICAL,
        }
        completed, log_text = self._run_with_fixture(fixture, VALID_DOC, "--assigned-branch", "main")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual("ready", payload["status"])
        self.assertIn("upstream=hnaymyh123-henry/claude-dev-skill", payload["conflicting_remotes"])
        self._no_write_evidence(log_text)

    def test_upstream_contributor_split_remote_push_is_ready_reproduction(self) -> None:
        """Production CLI path, finding 2 reproduction 1: fetch is upstream,
        push is the fork, `.dev.json.pushRepository` is the fork."""
        fixture = {
            "branch": "main",
            "config": {"branch.main.pushRemote": "", "remote.pushDefault": "", "branch.main.remote": "origin"},
            "remotes": {"origin": {"fetch": [UPSTREAM_HTTPS], "push": [ORIGIN_HTTPS]}},
            "gh_default": None,
        }
        completed, _ = self._run_with_fixture(fixture, VALID_DOC, "--assigned-branch", "main")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual("ready", payload["status"])
        self.assertEqual(CANONICAL, payload["repository"])

    def test_contributor_mode_pr_operation_targets_upstream_reproduction(self) -> None:
        """Production CLI path, finding 2 reproduction 2: pushes go to the
        fork, but the PR operation explicitly and correctly targets
        upstream -- this must be `ready`, not `expected_mismatch`."""
        fixture = {"gh_login": "KHAEntertainment"}
        completed, _ = self._run_with_fixture(
            fixture, CONTRIBUTOR_DOC, "--operation", "pr", "--target", PARENT
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual("ready", payload["status"])
        self.assertEqual(PARENT, payload["repository"])

    def test_pr_operation_with_wrong_target_is_rejected(self) -> None:
        fixture = {"gh_login": "KHAEntertainment"}
        completed, _ = self._run_with_fixture(
            fixture, CONTRIBUTOR_DOC, "--operation", "pr", "--target", CANONICAL
        )
        self.assertEqual(2, completed.returncode)
        payload = json.loads(completed.stdout)
        self.assertEqual("operation_target_mismatch", payload["reason_code"])

    def test_pr_operation_requires_matching_gh_cli_login(self) -> None:
        """Finding 4: an API mutation also needs the actual authenticated CLI
        login checked, not only the repository target."""
        fixture = {"gh_login": "Clarit-AI"}
        completed, _ = self._run_with_fixture(
            fixture, CONTRIBUTOR_DOC, "--operation", "pr", "--target", PARENT
        )
        self.assertEqual(2, completed.returncode)
        payload = json.loads(completed.stdout)
        self.assertEqual("account_mismatch", payload["reason_code"])

    def test_push_default_routing_to_wrong_remote_is_caught_by_configured_remote(self) -> None:
        fixture = {
            "branch": "main",
            "config": {"branch.main.pushRemote": "", "remote.pushDefault": "upstream", "branch.main.remote": "origin"},
            "remotes": {
                "origin": {"fetch": [ORIGIN_HTTPS], "push": [ORIGIN_HTTPS]},
                "upstream": {"fetch": [UPSTREAM_HTTPS], "push": [UPSTREAM_HTTPS]},
            },
            "gh_default": CANONICAL,
        }
        completed, log_text = self._run_with_fixture(fixture, VALID_DOC, "--assigned-branch", "main")
        self.assertEqual(2, completed.returncode)
        payload = json.loads(completed.stdout)
        self.assertEqual("configured_remote_mismatch", payload["reason_code"])
        self.assertIsNone(payload["effective_push_remote"])
        self.assertIsNone(payload["remote"])
        self.assertIsNone(payload["repository"])
        self._no_write_evidence(log_text)

    def test_wrong_current_branch_is_caught_before_dry_run_reproduction(self) -> None:
        """Finding 3 reproduction: the current branch differs from the
        ledger-assigned branch. The old implementation had no branch check at
        all and would have reached `ready`."""
        fixture = {
            "branch": "wrong-branch",
            "config": {"branch.main.pushRemote": "", "remote.pushDefault": "", "branch.wrong-branch.remote": "origin"},
            "remotes": {"origin": {"fetch": [ORIGIN_HTTPS], "push": [ORIGIN_HTTPS]}},
            "gh_default": None,
        }
        completed, log_text = self._run_with_fixture(fixture, VALID_DOC, "--assigned-branch", "feature/expected")
        self.assertEqual(2, completed.returncode)
        payload = json.loads(completed.stdout)
        self.assertEqual("branch_mismatch", payload["reason_code"])
        self._no_write_evidence(log_text)

    def test_dry_run_failure_is_caught_reproduction(self) -> None:
        fixture = {
            "branch": "main",
            "config": {"branch.main.pushRemote": "", "remote.pushDefault": "", "branch.main.remote": "origin"},
            "remotes": {"origin": {"fetch": [ORIGIN_HTTPS], "push": [ORIGIN_HTTPS]}},
            "gh_default": None,
            "dry_run_exit": 1,
        }
        completed, log_text = self._run_with_fixture(fixture, VALID_DOC, "--assigned-branch", "main")
        self.assertEqual(2, completed.returncode)
        payload = json.loads(completed.stdout)
        self.assertEqual("dry_run_failed", payload["reason_code"])
        self.assertIsNone(payload["effective_push_remote"])
        self._no_write_evidence(log_text)

    def test_missing_assigned_branch_is_rejected(self) -> None:
        fixture = {
            "branch": "main",
            "config": {"branch.main.pushRemote": "", "remote.pushDefault": "", "branch.main.remote": "origin"},
            "remotes": {"origin": {"fetch": [ORIGIN_HTTPS], "push": [ORIGIN_HTTPS]}},
            "gh_default": None,
        }
        completed, _ = self._run_with_fixture(fixture, VALID_DOC)
        self.assertEqual(2, completed.returncode)
        payload = json.loads(completed.stdout)
        self.assertEqual("missing_argument", payload["reason_code"])

    def test_whitespace_url_in_push_position_fails_closed(self) -> None:
        fixture = {
            "branch": "main",
            "config": {"branch.main.pushRemote": "", "remote.pushDefault": "", "branch.main.remote": "origin"},
            "remotes": {"origin": {"fetch": [ORIGIN_HTTPS], "push": ["/tmp/exfil dir/stash.git"]}},
            "gh_default": CANONICAL,
        }
        completed, log_text = self._run_with_fixture(fixture, VALID_DOC, "--assigned-branch", "main")
        self.assertEqual(2, completed.returncode)
        payload = json.loads(completed.stdout)
        self.assertEqual("incomplete", payload["status"])
        self._no_write_evidence(log_text)

    def test_missing_gh_cli_returns_incomplete_not_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            python_dir = root / "python_stubs"
            python_dir.mkdir()
            log = root / "commands.log"
            (root / ".dev.json").write_text(json.dumps(VALID_DOC), encoding="utf-8")
            git_stub = (f'#!{sys.executable}\n'
                        'import os, sys\n'
                        'with open(os.environ["REPO_IDENTITY_LOG"], "a") as f:\n'
                        '    f.write("\\t".join(sys.argv) + "\\n")\n'
                        'if sys.argv[1:] == ["rev-parse", "--show-toplevel"]:\n'
                        '    print(os.getcwd()); raise SystemExit(0)\n'
                        'if sys.argv[1:2] == ["check-ignore"]:\n'
                        '    raise SystemExit(0)\n'
                        'if sys.argv[1:] == ["branch", "--show-current"]:\n'
                        '    print("main"); raise SystemExit(0)\n'
                        'if sys.argv[1:3] == ["config"]:\n'
                        '    raise SystemExit(1)\n'
                        'if sys.argv[1:] == ["remote"]:\n'
                        '    print("origin"); raise SystemExit(0)\n'
                        'if sys.argv[1:4] == ["remote", "get-url", "--all"]:\n'
                        '    print("https://github.com/KHAEntertainment/claude-dev-skill.git"); raise SystemExit(0)\n'
                        'if sys.argv[1:5] == ["remote", "get-url", "--push", "--all"]:\n'
                        '    print("https://github.com/KHAEntertainment/claude-dev-skill.git"); raise SystemExit(0)\n'
                        'raise SystemExit(1)\n')
            (python_dir / "git").write_text(git_stub, encoding="utf-8")
            (python_dir / "git").chmod(0o755)
            env = {"PATH": str(python_dir), "REPO_IDENTITY_LOG": str(log)}
            completed = subprocess.run(
                [sys.executable, str(RESOLVER), "--repo-dir", str(root), "--assigned-branch", "main"],
                check=False, capture_output=True, text=True, env=env,
            )
            self.assertEqual(2, completed.returncode)
            payload = json.loads(completed.stdout)
            self.assertEqual("incomplete", payload["status"])
            self.assertEqual("gh_cli_missing", payload["reason_code"])


class FixtureDecisionLogicTests(unittest.TestCase):
    """`--fixture` is the pure low-level decision-logic path (see module
    docstring): it does not load `.dev.json` and is not the production
    entrypoint. These tests confirm it still round-trips its documented
    optional overrides for isolated unit testing of `_decide_push_target`."""

    def _run(self, payload: dict[str, object], *extra: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory, "state.json")
            fixture.write_text(json.dumps(payload), encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(RESOLVER), "--fixture", str(fixture), *extra],
                check=False, capture_output=True, text=True,
            )

    def test_ready_with_explicit_expect(self) -> None:
        completed = self._run({"remotes": {"origin": ORIGIN_HTTPS}, "effective_push_remote": "origin"}, "--expect", CANONICAL)
        self.assertEqual(0, completed.returncode)

    def test_split_fetch_push_fixture_is_ready(self) -> None:
        status = self._run(
            {
                "remotes": {"origin": ORIGIN_HTTPS},
                "push_remotes": {"origin": [UPSTREAM_HTTPS]},
                "effective_push_remote": "origin",
                "gh_default": None,
            },
            "--expect", PARENT,
        )
        self.assertEqual(0, status.returncode)
        payload = json.loads(status.stdout)
        self.assertEqual(PARENT, payload["repository"])

    def test_hostile_multiple_push_url_first(self) -> None:
        status = self._run(
            {
                "remotes": {"origin": [ORIGIN_HTTPS]},
                "push_remotes": {"origin": [UPSTREAM_HTTPS, ORIGIN_HTTPS]},
                "effective_push_remote": "origin",
                "gh_default": None,
            }
        )
        self.assertEqual(2, status.returncode)
        payload = json.loads(status.stdout)
        self.assertEqual("remote_url_mismatch", payload["reason_code"])

    def test_hostile_multiple_push_url_last(self) -> None:
        status = self._run(
            {
                "remotes": {"origin": [ORIGIN_HTTPS]},
                "push_remotes": {"origin": [ORIGIN_HTTPS, UPSTREAM_HTTPS]},
                "effective_push_remote": "origin",
                "gh_default": None,
            }
        )
        self.assertEqual(2, status.returncode)
        payload = json.loads(status.stdout)
        self.assertEqual("remote_url_mismatch", payload["reason_code"])


class DoNotActInvariantTests(unittest.TestCase):
    """A verdict that says "do not act" must carry no actionable push target."""

    def _run(self, payload: dict[str, object], *extra: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory, "state.json")
            fixture.write_text(json.dumps(payload), encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(RESOLVER), "--fixture", str(fixture), *extra],
                check=False, capture_output=True, text=True,
            )

    NON_READY: tuple[tuple[str, dict[str, object]], ...] = (
        (
            "expected_disagrees",
            {"remotes": {"origin": ORIGIN_HTTPS}, "effective_push_remote": "origin", "gh_default": None, "expect": PARENT},
        ),
        (
            "unparseable_origin",
            {"remotes": {"origin": "not a url at all"}, "effective_push_remote": "origin", "gh_default": None},
        ),
        (
            "configured_remote_disagrees",
            {
                "remotes": {"origin": ORIGIN_HTTPS, "upstream": UPSTREAM_HTTPS},
                "effective_push_remote": "upstream",
                "configured_remote": "origin",
                "gh_default": None,
            },
        ),
    )

    def test_non_ready_verdicts_carry_no_push_remote(self) -> None:
        for label, payload in self.NON_READY:
            with self.subTest(label):
                completed = self._run(payload)
                verdict = json.loads(completed.stdout)
                self.assertNotEqual("ready", verdict["status"])
                self.assertEqual(2, completed.returncode)
                for actionable in ("effective_push_remote", "remote"):
                    self.assertIsNone(verdict[actionable])

    def test_print_push_remote_is_empty_and_fails_when_not_ready(self) -> None:
        for label, payload in self.NON_READY:
            with self.subTest(label):
                completed = self._run(payload, "--print-push-remote")
                self.assertEqual(2, completed.returncode)
                self.assertEqual("", completed.stdout.strip())
                self.assertNotEqual("", completed.stderr.strip())

    def test_print_push_remote_emits_only_the_name_when_ready(self) -> None:
        completed = self._run(
            {
                "remotes": {"origin": ORIGIN_HTTPS},
                "effective_push_remote": "origin",
                "gh_default": "KHAEntertainment/claude-dev-skill",
                "access_verified": True,
                "verified_name": "KHAEntertainment/claude-dev-skill",
                "expect": CANONICAL,
            },
            "--print-push-remote",
        )
        self.assertEqual(0, completed.returncode)
        self.assertEqual("origin", completed.stdout.strip())


class TransportAuthOverrideDetectionTests(unittest.TestCase):
    """Bounded transport support: a higher-precedence override yields a named
    `unsupported_transport_auth` result rather than a probe of the wrong
    identity source."""

    def _init_repo(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)

    def test_ssh_command_env_override_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_repo(root)
            old = os.environ.get("GIT_SSH_COMMAND")
            os.environ["GIT_SSH_COMMAND"] = "ssh -F /custom/config"
            try:
                self.assertEqual("GIT_SSH_COMMAND", MODULE.detect_ssh_overrides(root))
            finally:
                if old is None:
                    os.environ.pop("GIT_SSH_COMMAND", None)
                else:
                    os.environ["GIT_SSH_COMMAND"] = old

    def test_core_ssh_command_config_override_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_repo(root)
            subprocess.run(["git", "config", "core.sshCommand", "ssh -F /custom/config"], cwd=str(root), check=True)
            self.assertEqual("core.sshCommand", MODULE.detect_ssh_overrides(root))

    def test_no_ssh_override_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_repo(root)
            self.assertIsNone(MODULE.detect_ssh_overrides(root))

    def test_urlmatch_scoped_https_header_override_is_detected_reproduction(self) -> None:
        """Finding 5 reproduction: Git commonly stores a URL-scoped header
        under a prefix like `http.https://github.com/.extraHeader`, which a
        literal `http.<url>.extraHeader` key lookup never finds."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_repo(root)
            subprocess.run(
                ["git", "config", "http.https://github.com/.extraHeader", "Authorization: Bearer test-only"],
                cwd=str(root), check=True,
            )
            self.assertEqual(
                "http.extraHeader",
                MODULE.detect_https_auth_overrides(root, "https://github.com/Acme/Widget.git"),
            )

    def test_global_https_extra_header_override_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_repo(root)
            subprocess.run(["git", "config", "http.extraHeader", "Authorization: Bearer x"], cwd=str(root), check=True)
            self.assertEqual("http.extraHeader", MODULE.detect_https_auth_overrides(root, ORIGIN_HTTPS))

    def test_no_https_override_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_repo(root)
            self.assertIsNone(MODULE.detect_https_auth_overrides(root, ORIGIN_HTTPS))

    def test_askpass_env_override_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_repo(root)
            old = os.environ.get("SSH_ASKPASS")
            os.environ["SSH_ASKPASS"] = "/usr/bin/ssh-askpass"
            try:
                self.assertEqual("SSH_ASKPASS", MODULE.detect_askpass_overrides(root))
            finally:
                if old is None:
                    os.environ.pop("SSH_ASKPASS", None)
                else:
                    os.environ["SSH_ASKPASS"] = old

    def test_core_askpass_config_override_is_detected_reproduction(self) -> None:
        """Finding 5 reproduction: the approved support boundary names
        `core.askPass`, which the previous implementation never checked."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_repo(root)
            subprocess.run(["git", "config", "core.askPass", "/usr/bin/ssh-askpass"], cwd=str(root), check=True)
            self.assertEqual("core.askPass", MODULE.detect_askpass_overrides(root))

    def test_no_askpass_override_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_repo(root)
            self.assertIsNone(MODULE.detect_askpass_overrides(root))


class TransportAccountVerificationTests(unittest.TestCase):
    """Mocked identity checks only -- no live credential retrieval or network
    call runs here."""

    def _init_repo(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)

    def test_https_matching_account_is_verified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_repo(root)
            with _patched(MODULE, "fill_https_credential", lambda repo_dir, url: {"username": "KHAEntertainment", "password": "x"}):
                result = MODULE.verify_https_account(root, ORIGIN_HTTPS, "KHAEntertainment", lookup_login=lambda c: "KHAEntertainment")
            self.assertEqual("verified", result["status"])

    def test_https_mismatched_account_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_repo(root)
            with _patched(MODULE, "fill_https_credential", lambda repo_dir, url: {"username": "Clarit-AI", "password": "x"}):
                result = MODULE.verify_https_account(root, ORIGIN_HTTPS, "KHAEntertainment", lookup_login=lambda c: "Clarit-AI")
            self.assertEqual("incomplete", result["status"])
            self.assertEqual("account_mismatch", result["reason_code"])

    def test_https_unavailable_credential_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_repo(root)
            with _patched(MODULE, "fill_https_credential", lambda repo_dir, url: None):
                result = MODULE.verify_https_account(root, ORIGIN_HTTPS, "KHAEntertainment", lookup_login=lambda c: "irrelevant")
            self.assertEqual("incomplete", result["status"])
            self.assertEqual("identity_unavailable", result["reason_code"])

    def test_https_urlmatch_header_short_circuits_before_helper_lookup_reproduction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_repo(root)
            subprocess.run(
                ["git", "config", "http.https://github.com/.extraHeader", "Authorization: Bearer test-only"],
                cwd=str(root), check=True,
            )
            called = {"fill": False}

            def fake_fill(repo_dir: Path, url: str) -> dict[str, str] | None:
                called["fill"] = True
                return {"username": "KHAEntertainment", "password": "x"}

            with _patched(MODULE, "fill_https_credential", fake_fill):
                result = MODULE.verify_https_account(root, ORIGIN_HTTPS, "KHAEntertainment", lookup_login=lambda c: "KHAEntertainment")
            self.assertEqual("unsupported_transport_auth", result["reason_code"])
            self.assertFalse(called["fill"], "helper lookup must not run once a higher-precedence override is found")

    def test_ssh_matching_account_documented_exit_one_is_verified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_repo(root)
            prober = lambda repo_dir, target, user: (1, "Hi KHAEntertainment! You've successfully authenticated, but GitHub does not provide shell access.")
            resolver = lambda repo_dir, target: ("github.com", "git", "22")
            result = MODULE.verify_ssh_account(root, "github.com", "KHAEntertainment", prober=prober, resolver=resolver)
            self.assertEqual("verified", result["status"])

    def test_ssh_alias_resolved_before_probing_uses_original_alias_reproduction(self) -> None:
        """Finding 6: the probe must use the original alias, not the resolved
        hostname, so SSH's own per-alias config (identity, port) applies."""
        probed_target = {}

        def prober(repo_dir: Path, target: str, user: str) -> tuple[int, str]:
            probed_target["value"] = target
            return (1, "Hi KHAEntertainment! You've successfully authenticated")

        resolver = lambda repo_dir, target: ("github.com", "git", "443")
        with _patched(MODULE, "detect_ssh_overrides", lambda repo_dir: None):
            result = MODULE.verify_ssh_account(Path("."), "corp-github", "KHAEntertainment", prober=prober, resolver=resolver)
        self.assertEqual("verified", result["status"])
        self.assertEqual("corp-github", probed_target["value"])

    def test_ssh_alias_resolving_elsewhere_is_rejected_reproduction(self) -> None:
        resolver = lambda repo_dir, target: ("gitlab.example.com", "git", "22")
        called = {"probed": False}

        def prober(repo_dir: Path, target: str, user: str) -> tuple[int, str]:
            called["probed"] = True
            return (1, "should never be reached")

        with _patched(MODULE, "detect_ssh_overrides", lambda repo_dir: None):
            result = MODULE.verify_ssh_account(Path("."), "corp-gitlab", "KHAEntertainment", prober=prober, resolver=resolver)
        self.assertEqual("incomplete", result["status"])
        self.assertEqual("non_github_origin", result["reason_code"])
        self.assertFalse(called["probed"])

    def test_ssh_mismatched_account_is_reported(self) -> None:
        resolver = lambda repo_dir, target: ("github.com", "git", "22")
        prober = lambda repo_dir, target, user: (1, "Hi Clarit-AI! You've successfully authenticated")
        with _patched(MODULE, "detect_ssh_overrides", lambda repo_dir: None):
            result = MODULE.verify_ssh_account(Path("."), "github.com", "KHAEntertainment", prober=prober, resolver=resolver)
        self.assertEqual("incomplete", result["status"])
        self.assertEqual("account_mismatch", result["reason_code"])

    def test_ssh_generic_zero_exit_is_not_mistaken_for_success(self) -> None:
        resolver = lambda repo_dir, target: ("github.com", "git", "22")
        prober = lambda repo_dir, target, user: (0, "some other banner")
        with _patched(MODULE, "detect_ssh_overrides", lambda repo_dir: None):
            result = MODULE.verify_ssh_account(Path("."), "github.com", "KHAEntertainment", prober=prober, resolver=resolver)
        self.assertEqual("incomplete", result["status"])
        self.assertEqual("identity_unavailable", result["reason_code"])

    def test_ssh_command_override_short_circuits_before_resolving_or_probing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_repo(root)
            subprocess.run(["git", "config", "core.sshCommand", "ssh -F /custom/config"], cwd=str(root), check=True)
            called = {"probe": False, "resolve": False}

            def prober(repo_dir: Path, target: str, user: str) -> tuple[int, str]:
                called["probe"] = True
                return (1, "Hi KHAEntertainment! You've successfully authenticated")

            def resolver(repo_dir: Path, target: str) -> tuple[str, str, str] | None:
                called["resolve"] = True
                return ("github.com", "git", "22")

            result = MODULE.verify_ssh_account(root, "github.com", "KHAEntertainment", prober=prober, resolver=resolver)
            self.assertEqual("unsupported_transport_auth", result["reason_code"])
            self.assertFalse(called["probe"])
            self.assertFalse(called["resolve"])


class GhCliAccountVerificationTests(unittest.TestCase):
    """Finding 4: an API mutation needs the actual `gh` CLI login checked --
    distinct from the Git transport account."""

    def test_matching_login_is_verified(self) -> None:
        result = MODULE.verify_gh_cli_login(Path("."), "KHAEntertainment", runner=lambda: (0, "KHAEntertainment"))
        self.assertEqual("verified", result["status"])

    def test_mismatched_login_is_reported(self) -> None:
        result = MODULE.verify_gh_cli_login(Path("."), "KHAEntertainment", runner=lambda: (0, "Clarit-AI"))
        self.assertEqual("incomplete", result["status"])
        self.assertEqual("account_mismatch", result["reason_code"])

    def test_missing_gh_cli_is_incomplete(self) -> None:
        result = MODULE.verify_gh_cli_login(Path("."), "KHAEntertainment", runner=lambda: (-1, ""))
        self.assertEqual("incomplete", result["status"])
        self.assertEqual("gh_cli_missing", result["reason_code"])


class BranchAndDryRunTests(unittest.TestCase):
    """Finding 3: unit-level coverage of the branch/refspec check and the
    dry-run push, with an injected runner (the physical-fixture tests in
    tests/test_physical_push_safety.py exercise the real `git push --dry-run`
    against real local bare repositories)."""

    def _init_repo(self, root: Path, branch: str) -> None:
        subprocess.run(["git", "init", "-q", "-b", branch], cwd=str(root), check=True)

    def test_wrong_current_branch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_repo(root, "wrong-branch")
            result = MODULE.verify_branch_and_dry_run(root, remote="origin", assigned_branch="feature/expected")
            self.assertEqual("incomplete", result["status"])
            self.assertEqual("branch_mismatch", result["reason_code"])

    def test_matching_branch_runs_dry_run_and_reports_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_repo(root, "feature/expected")
            runner = lambda cmd, cwd: (0, "")
            result = MODULE.verify_branch_and_dry_run(
                root, remote="origin", assigned_branch="feature/expected", dry_run_runner=runner
            )
            self.assertEqual("ready", result["status"])
            self.assertEqual("origin", result["remote"])
            self.assertEqual("refs/heads/feature/expected:refs/heads/feature/expected", result["refspec"])

    def test_dry_run_failure_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._init_repo(root, "feature/expected")
            runner = lambda cmd, cwd: (1, "rejected")
            result = MODULE.verify_branch_and_dry_run(
                root, remote="origin", assigned_branch="feature/expected", dry_run_runner=runner
            )
            self.assertEqual("incomplete", result["status"])
            self.assertEqual("dry_run_failed", result["reason_code"])


class _patched:
    """Minimal monkeypatch context manager, kept local to avoid a pytest/mock dependency."""

    def __init__(self, module: object, name: str, value: object) -> None:
        self._module = module
        self._name = name
        self._value = value
        self._original = getattr(module, name)

    def __enter__(self) -> None:
        setattr(self._module, self._name, self._value)

    def __exit__(self, *exc: object) -> None:
        setattr(self._module, self._name, self._original)


if __name__ == "__main__":
    unittest.main()
