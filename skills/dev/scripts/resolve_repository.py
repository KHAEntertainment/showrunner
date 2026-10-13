#!/usr/bin/env python3
"""Resolve the canonical GitHub repository and account before a `/dev` write.

Read-only by construction (a bounded `git push --dry-run` is the one
exception, and it never advances a ref). This helper decides whether a real
push or GitHub mutation is safe to run, by loading `.dev.json` itself rather
than trusting whatever a caller happens to pass. When it cannot establish one
unambiguous, matching, verified identity it exits 2 so the caller pauses
before the write instead of letting `git`, `gh`, or an omitted argument pick
a target for it.

Three independent things are validated, and a caller must not conflate them:

- **Push-target identity** (`--operation push`): does the actual Git push
  destination — every one of its push URLs, and the named remote itself —
  match `.dev.json`'s `pushRepository`? Fetch URLs are context, never a
  destination. This also runs the branch/refspec check and a `--dry-run`
  push using the exact validated remote and refspec. With `--tag-target` the
  branch check is replaced by a release-tag check (target equals the live
  remote default-branch tip, tag absent locally and remotely, `gh` login
  verified) that works from a detached checkout.
- **Operation-target identity** (`--operation pr` / `--operation issue`): does
  the *explicit* `--repo`/`--target` argument the caller is about to pass to
  `gh` match the confirmed value for this operation — `pullRequestRepository`
  for an ordinary PR, `pushRepository` for a plugin-created Issue, or an
  explicitly assigned existing Issue's own qualified identity (pass
  `--allow-target-override` for that last case)? This has nothing to do with
  git push URLs.
- **Transport/CLI account** (`--mode check-https-account` / `check-ssh-account`
  / `check-gh-account`): does the credential Git or the `gh` CLI will
  actually use match `.dev.json`'s `account`? Neither commit authorship, a
  URL username, nor `gh auth status` establishes this.

`--fixture` is a separate, lower-level path that exercises the pure push-
target decision function (`_decide_push_target` via `resolve_repository()`)
against a hand-written remotes/defaults JSON document, without loading
`.dev.json` or touching the filesystem beyond that one file. It exists for
unit-testing the decision logic in isolation and is not the production
entrypoint: every real caller uses the default (non-fixture) `--operation`
path below, which loads and requires a valid `.dev.json`.

The GitHub CLI's own repository default (`gh repo set-default`) is recorded
for the ledger but never blocks a resolution: every supported operation is
explicitly scoped, so an unrelated CLI default may legitimately disagree with
a correctly configured fork's operation target.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

# Make the sibling `dev_config` module importable regardless of how this file
# is loaded (as `__main__`, or via `importlib.util.spec_from_file_location` in
# tests) rather than relying on `sys.path[0]` being set for us.
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
import dev_config  # noqa: E402

GITHUB_HOST = "github.com"
SUPPORTED_SCHEMES = frozenset({"https", "http", "ssh", "git"})
SCP_LIKE = re.compile(r"^(?:(?P<user>[^@/]+)@)?(?P<host>[^:/@]+):(?P<path>.+)$")
OWNER_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$")
REPO_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")

# Bounded so a hung `gh` / `git` / `ssh` cannot block the lead indefinitely.
COMMAND_TIMEOUT = 30

# Never let a probe fall back to an interactive prompt. A prompt-shaped setup
# is `incomplete`, not an invitation to collect credentials through the agent.
NONINTERACTIVE_ENV_OVERRIDES = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "",
    "SSH_ASKPASS": "",
}

GITHUB_SSH_GREETING = re.compile(
    r"Hi ([A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)!.*successfully authenticated",
    re.IGNORECASE | re.DOTALL,
)


class RepositoryError(RuntimeError):
    """A remote URL, fixture, or command result that cannot be trusted."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _parse_scheme_host_path(url: str) -> tuple[str | None, str, str]:
    """Split *url* into (scheme-or-None, host, path) without validating the host."""
    text = (url or "").strip()
    if not text:
        raise RepositoryError("ambiguous_origin", "remote URL is empty")

    if "://" in text:
        scheme, _, rest = text.partition("://")
        if scheme.lower() not in SUPPORTED_SCHEMES:
            raise RepositoryError("non_github_origin", f"unsupported remote scheme: {scheme}")
        authority, _, path = rest.partition("/")
        host = authority.rpartition("@")[2].partition(":")[0]
        return scheme.lower(), host, path

    match = SCP_LIKE.match(text)
    if not match:
        raise RepositoryError("ambiguous_origin", f"unrecognized remote URL: {text}")
    return None, match.group("host"), match.group("path")


def _owner_repo_from_path(path: str) -> str:
    trimmed = path.strip().strip("/")
    if trimmed[-4:].lower() == ".git":
        trimmed = trimmed[:-4].strip("/")
    segments = [segment for segment in trimmed.split("/") if segment]
    if len(segments) != 2:
        raise RepositoryError("ambiguous_origin", f"remote path is not OWNER/REPO: {path}")
    owner, repository = segments
    if not OWNER_PATTERN.match(owner) or not REPO_PATTERN.match(repository):
        raise RepositoryError("ambiguous_origin", f"remote path is not OWNER/REPO: {path}")
    return f"{owner}/{repository}"


def normalize_remote(url: str) -> str:
    """Return canonical `OWNER/REPO` for an ordinary HTTPS or SSH GitHub remote.

    Pure and offline: only recognizes the literal host `github.com`. An SSH
    host alias that resolves to GitHub via `ssh -G` is a *different*, wider
    check -- see `normalize_remote_with_ssh_resolution` -- because resolving
    an alias requires consulting the actual SSH configuration, which this
    function deliberately does not do.
    """
    _scheme, host, path = _parse_scheme_host_path(url)
    if host.lower() != GITHUB_HOST:
        raise RepositoryError("non_github_origin", f"remote host is not {GITHUB_HOST}: {host or url}")
    return _owner_repo_from_path(path)


def resolve_ssh_effective_host(
    repo_dir: Path, host_or_alias: str, *, ssh_command: tuple[str, ...] = ("ssh",),
    user: str | None = None, port: int | None = None,
) -> tuple[str, str, str] | None:
    """Return `(hostname, user, port)` via `ssh -G <host_or_alias>`, or None on failure.

    `ssh_command` defaults to the real `ssh` binary, consulting whatever
    config the environment's actual user resolves (OpenSSH looks up the home
    directory from the system user database, not the `HOME` environment
    variable, so tests inject an explicit `-F <config>` here rather than
    trying to override `HOME`).
    """
    options = (["-l", user] if user else []) + (["-p", str(port)] if port else [])
    status, output = read_command([*ssh_command, "-G", *options, host_or_alias], cwd=repo_dir)
    if status != 0:
        return None
    values: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[0] in ("hostname", "user", "port") and parts[0] not in values:
            values[parts[0]] = parts[1]
    if "hostname" not in values:
        return None
    return values["hostname"], values.get("user", "git"), values.get("port", "22")


def normalize_remote_with_ssh_resolution(
    url: str, repo_dir: Path | None, *, ssh_command: tuple[str, ...] = ("ssh",)
) -> str:
    """Like `normalize_remote`, but a non-literal SSH host gets a second chance
    via `ssh -G` alias resolution when *repo_dir* is available.

    The original alias is what a real push/probe must keep using -- this
    function only uses the resolved hostname to decide whether the alias
    points at GitHub, never to rewrite the URL itself.
    """
    try:
        return normalize_remote(url)
    except RepositoryError as exc:
        if repo_dir is None or exc.code != "non_github_origin":
            raise
        scheme, host, path = _parse_scheme_host_path(url)
        if scheme is not None and scheme != "ssh":
            raise
        if not host or host.startswith("-"):
            raise RepositoryError("non_github_origin", "invalid SSH host token")
        resolved = resolve_ssh_effective_host(repo_dir, host, ssh_command=ssh_command)
        if resolved is None or resolved[0].lower() != GITHUB_HOST:
            raise
        return _owner_repo_from_path(path)


def redact_remote(url: str | None) -> str | None:
    """Return a display-safe copy of *url* with any userinfo removed."""
    if url is None:
        return None
    text = (url or "").strip()
    if not text:
        return text

    if "://" in text:
        scheme, _, rest = text.partition("://")
        authority, _, path = rest.partition("/")
        safe_authority = authority.rsplit("@", 1)[-1]
        redacted = f"{scheme}://{safe_authority}"
        if path:
            redacted = f"{redacted}/{path}"
        return redacted

    if "@" in text:
        _, _, after = text.partition("@")
        return after
    return text


def parse_owner_repo(value: str, *, label: str) -> str:
    """Validate an already-canonical `OWNER/REPO` string such as the `gh` default."""
    segments = [segment for segment in (value or "").strip().split("/") if segment]
    if len(segments) != 2:
        raise RepositoryError("ambiguous_default", f"{label} is not OWNER/REPO: {value}")
    owner, repository = segments
    if not OWNER_PATTERN.match(owner) or not REPO_PATTERN.match(repository):
        raise RepositoryError("ambiguous_default", f"{label} is not OWNER/REPO: {value}")
    return f"{owner}/{repository}"


def same_repository(left: str, right: str) -> bool:
    """GitHub owner and repository names are case-insensitive."""
    return left.casefold() == right.casefold()


def _as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def _effective_push_urls(
    remotes: dict[str, list[str] | str],
    push_remotes: dict[str, list[str] | str] | None,
    remote_name: str,
) -> list[str]:
    """The URLs that actually receive a push for *remote_name*.

    An explicit `push_remotes` entry for this remote is authoritative -- it is
    exactly what `git remote get-url --push --all` reports. When absent, real
    Git itself falls back to the fetch URL as the push URL, so mirroring that
    fallback here (rather than blending both sets into one equality class) is
    what keeps a genuinely split fetch/push remote (fetch upstream, push
    fork) from being flagged as internally inconsistent.
    """
    push_lookup = push_remotes or {}
    explicit_push = _as_list(push_lookup.get(remote_name, []))
    if explicit_push:
        return explicit_push
    return _as_list(remotes.get(remote_name, []))


def _first_canonical(
    remotes: dict[str, list[str] | str],
    push_remotes: dict[str, list[str] | str] | None,
    remote_name: str,
    *,
    repo_dir: Path | None = None,
) -> str | None:
    """Return the first normalisable canonical repo for *remote_name*, preferring
    its actual push URLs (falling back to fetch only when no push URL exists),
    or None."""
    push_urls = _effective_push_urls(remotes, push_remotes, remote_name)
    fetch_urls = _as_list(remotes.get(remote_name, []))
    for url in push_urls + [u for u in fetch_urls if u not in push_urls]:
        try:
            return normalize_remote_with_ssh_resolution(url, repo_dir)
        except RepositoryError:
            continue
    return None


def _decide_push_target(
    *,
    remotes: dict[str, list[str] | str],
    push_remotes: dict[str, list[str] | str] | None = None,
    gh_default: str | None,
    verified_name: str | None = None,
    access_verified: bool = False,
    expected: str | None = None,
    remote_name: str = "origin",
    configured_remote: str | None = None,
    repo_dir: Path | None = None,
) -> dict[str, object]:
    """Decide the canonical **push** repository, or fail closed with a named mismatch.

    Only the remote's actual push URLs (falling back to its fetch URL when no
    push URL is configured, matching Git's own behavior) are validated against
    `expected` -- a fetch-only URL that disagrees (e.g. a fork's `upstream`
    fetch remote, or a contributor-mode remote that fetches upstream but
    pushes the fork) is recorded in `conflicting_remotes` and never blocks.

    `expected` is the operation's configured target from `.dev.json`'s
    `pushRepository`. It is not optional in the supported workflow.

    `configured_remote` is `.dev.json`'s named `pushRemote`. When git's own
    effective push remote (`remote_name`) disagrees, that is a stop: a
    conflicting Git push-remote default (e.g. a hijacked `remote.pushDefault`)
    gets no fallback.

    The GitHub CLI default (`gh_default`) is recorded for the ledger only. It
    never fails the decision: every supported operation is explicitly scoped,
    so an unrelated CLI default may legitimately disagree with a correctly
    configured fork's operation target.
    """
    result: dict[str, object] = {
        "status": "incomplete",
        "repository": None,
        "effective_push_remote": remote_name,
        "remote": remote_name,
        "remote_url": None,
        "push_url": None,
        "gh_default": gh_default,
        "conflicting_remotes": [],
        "notes": [],
        "reason_code": "",
        "reason": "",
    }

    if configured_remote is not None and configured_remote != remote_name:
        result["reason_code"] = "configured_remote_mismatch"
        result["reason"] = (
            f".dev.json names `{configured_remote}` as the push remote, but the "
            f"effective push remote for this checkout is `{remote_name}`; refusing "
            "to substitute one for the other"
        )
        return result

    push_urls = _effective_push_urls(remotes, push_remotes, remote_name)

    if not push_urls:
        result["reason_code"] = "missing_origin"
        result["reason"] = (
            f"effective push remote `{remote_name}` has no configured push (or fetch) "
            "URLs; repository identity cannot be established"
        )
        return result

    candidate: str | None = None
    first_valid_url: str | None = None
    for url in push_urls:
        try:
            canon = normalize_remote_with_ssh_resolution(url, repo_dir)
        except RepositoryError as exc:
            result["reason_code"] = exc.code
            result["reason"] = f"`{remote_name}` push URL `{redact_remote(url)}` is unusable: {exc}"
            return result

        if first_valid_url is None:
            first_valid_url = url
            candidate = canon
            continue

        if not same_repository(canon, candidate):
            result["remote_url"] = redact_remote(first_valid_url)
            result["push_url"] = redact_remote(url)
            result["reason_code"] = "remote_url_mismatch"
            result["reason"] = (
                f"`{remote_name}` has multiple push URLs that resolve differently: "
                f"{redact_remote(first_valid_url)} -> {candidate} but "
                f"{redact_remote(url)} -> {canon}"
            )
            return result

    assert candidate is not None  # noqa: S101
    assert first_valid_url is not None  # noqa: S101

    result["repository"] = candidate
    result["remote_url"] = redact_remote(first_valid_url)

    # Other remotes' URLs -- and this remote's own *fetch* URL when it differs
    # from its push URL -- are recorded, never blocking. A fork's `upstream`
    # fetch source, or a contributor-mode remote whose fetch source is
    # upstream while its push target is the fork, are supported shapes, not
    # errors.
    all_remote_names = set(remotes) | set(push_remotes or {})
    conflicts: set[str] = set()
    own_fetch_urls = [u for u in _as_list(remotes.get(remote_name, [])) if u not in push_urls]
    for url in own_fetch_urls:
        try:
            other = normalize_remote_with_ssh_resolution(url, repo_dir)
        except RepositoryError:
            continue
        if not same_repository(other, candidate):
            conflicts.add(f"{remote_name} (fetch)={other}")
    for name in sorted(all_remote_names):
        if name == remote_name:
            continue
        other_urls = _effective_push_urls(remotes, push_remotes, name) or _as_list(remotes.get(name, []))
        for other_url in other_urls:
            try:
                other = normalize_remote_with_ssh_resolution(other_url, repo_dir)
            except RepositoryError:
                continue
            if not same_repository(other, candidate):
                conflicts.add(f"{name}={other}")

    if conflicts:
        result["conflicting_remotes"] = sorted(conflicts)

    # Informational only. Every supported operation is explicitly scoped
    # (`--repo`, an explicit endpoint, or a positional argument), so the CLI's
    # unrelated repository default has no bearing on whether this push is
    # safe, and must not block a correctly configured fork.
    if gh_default is not None:
        try:
            default = parse_owner_repo(gh_default, label="gh default repository")
        except RepositoryError:
            default = None
        if default is not None and not same_repository(default, candidate):
            result["notes"].append(
                f"the gh CLI default repository is {default}, which differs from "
                f"the operation's actual target {candidate}; not blocking, because "
                "this operation is explicitly scoped"
            )

    if access_verified:
        if verified_name is None:
            result["repository"] = None
            result["reason_code"] = "inaccessible_repository"
            result["reason"] = f"{candidate} could not be read with the current gh credentials"
            return result
        if not same_repository(verified_name, candidate):
            result["repository"] = None
            result["reason_code"] = "origin_redirects"
            result["reason"] = (
                f"the effective push remote `{remote_name}` is {candidate} but "
                f"GitHub resolves it to {verified_name}; update the remote before continuing"
            )
            return result

    if expected is not None and not same_repository(expected, candidate):
        result["repository"] = None
        result["reason_code"] = "expected_mismatch"
        result["reason"] = (
            f".dev.json names {expected} as pushRepository, but this checkout's "
            f"effective push remote `{remote_name}` resolves to {candidate}"
        )
        return result

    result["status"] = "ready"
    conflict_note = ""
    if conflicts:
        conflict_note = (
            "; non-target sources disagree ("
            f"{', '.join(sorted(conflicts))}) but the effective push target is {candidate}"
        )
    result["reason_code"] = "target_confirmed"
    result["reason"] = f"effective push remote `{remote_name}` resolves to {candidate}{conflict_note}"
    return result


def _decide_operation_target(
    *,
    target: str | None,
    expected: str | None,
    allow_override: bool = False,
) -> dict[str, object]:
    """Decide whether an explicit PR/Issue operation target is confirmed.

    This has no relationship to Git push URLs: a PR or Issue API call takes
    its repository as a literal argument, so the only question is whether
    that literal argument matches confirmed intent. `allow_override` is for
    an explicitly assigned existing Issue, whose own qualified repository
    identity is expected to differ from the project's default and has
    already been confirmed elsewhere (the ledger), not re-derived here.
    """
    result: dict[str, object] = {
        "status": "incomplete",
        "repository": target,
        "reason_code": "",
        "reason": "",
    }
    if not target:
        result["reason_code"] = "missing_argument"
        result["reason"] = "no explicit --target repository was supplied for this operation"
        return result
    try:
        canonical_target = parse_owner_repo(target, label="--target")
    except RepositoryError as exc:
        result["reason_code"] = exc.code
        result["reason"] = str(exc)
        return result
    if allow_override:
        result["status"] = "ready"
        result["repository"] = canonical_target
        result["reason_code"] = "explicit_override_accepted"
        result["reason"] = f"{canonical_target} accepted as an explicitly assigned qualified identity"
        return result
    if not expected:
        result["reason_code"] = "missing_expected"
        result["reason"] = ".dev.json has no confirmed target for this operation"
        return result
    try:
        canonical_expected = parse_owner_repo(expected, label="confirmed target")
    except RepositoryError as exc:
        result["reason_code"] = exc.code
        result["reason"] = str(exc)
        return result
    if not same_repository(canonical_target, canonical_expected):
        result["reason_code"] = "operation_target_mismatch"
        result["reason"] = f"the operation targets {canonical_target}, but .dev.json confirms {canonical_expected}"
        return result
    result["status"] = "ready"
    result["repository"] = canonical_target
    result["reason_code"] = "target_confirmed"
    result["reason"] = f"operation target {canonical_target} matches .dev.json"
    return result


def resolve_repository(**kwargs: object) -> dict[str, object]:
    """Decide the canonical push repository and enforce the do-not-act invariant.

    `_decide_push_target` has multiple failure returns. Rather than remember
    to clear the actionable field at each one, the invariant is enforced
    once, here, on the way out: a verdict whose status is not `ready` carries
    no push target. A consumer that ignores the status still cannot harvest a
    usable remote.
    """
    result = _decide_push_target(**kwargs)  # type: ignore[arg-type]
    if result.get("status") != "ready":
        for actionable in ("effective_push_remote", "remote"):
            result[actionable] = None
    return result


def read_command(
    command: list[str], *, cwd: Path, merge_stderr: bool = True, env: dict[str, str] | None = None
) -> tuple[int, str]:
    """Run one command and return its exit status and stdout."""
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
            text=True,
            check=False,
            timeout=COMMAND_TIMEOUT,
            env=env,
        )
    except OSError as exc:
        return (-1, str(exc))
    except subprocess.SubprocessError as exc:
        return (124, str(exc))
    return completed.returncode, completed.stdout.strip()


def collect_remotes(repo_dir: Path) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    status, output = read_command(["git", "remote"], cwd=repo_dir)
    if status == -1:
        raise RepositoryError("git_cli_missing", "git CLI is not installed or not in PATH")
    if status != 0:
        raise RepositoryError("missing_origin", "`git remote` failed in this checkout")

    names = [line.strip() for line in output.splitlines() if line.strip()]
    fetch: dict[str, list[str]] = {}
    push: dict[str, list[str]] = {}
    for name in names:
        fetch_status, fetch_output = read_command(["git", "remote", "get-url", "--all", name], cwd=repo_dir)
        fetch[name] = [line.strip() for line in fetch_output.splitlines() if line.strip()] if fetch_status == 0 else []

        push_status, push_output = read_command(["git", "remote", "get-url", "--push", "--all", name], cwd=repo_dir)
        push[name] = [line.strip() for line in push_output.splitlines() if line.strip()] if push_status == 0 else []
    return fetch, push


def get_effective_push_remote(repo_dir: Path, *, fallback: str = "origin") -> str:
    """Resolve the git remote that will receive a push for the current branch."""
    status, output = read_command(["git", "branch", "--show-current"], cwd=repo_dir)
    if status == -1:
        raise RepositoryError("git_cli_missing", "git CLI is not installed or not in PATH")
    current_branch = output.splitlines()[0].strip() if status == 0 and output else ""

    for key in (
        f"branch.{current_branch}.pushRemote",
        "remote.pushDefault",
        f"branch.{current_branch}.remote",
    ):
        if not current_branch and key.startswith("branch."):
            continue
        status, output = read_command(["git", "config", key], cwd=repo_dir)
        if status == 0 and output:
            return output.splitlines()[0].strip()
    return fallback


def get_current_branch(repo_dir: Path) -> str | None:
    status, output = read_command(["git", "branch", "--show-current"], cwd=repo_dir)
    if status != 0 or not output:
        return None
    return output.splitlines()[0].strip()


def collect_gh_default(repo_dir: Path) -> str | None:
    status, output = read_command(
        ["gh", "repo", "set-default", "--view"],
        cwd=repo_dir,
        merge_stderr=False,
    )
    if status == -1:
        raise RepositoryError("gh_cli_missing", "gh CLI is not installed or not in PATH")
    if status == 0 and output:
        first = output.splitlines()[0].strip()
        try:
            parse_owner_repo(first, label="gh default repository")
        except RepositoryError:
            return None
        return first
    return None


def collect_verified_name(repo_dir: Path, repository: str) -> str | None:
    status, output = read_command(
        ["gh", "repo", "view", f"{GITHUB_HOST}/{repository}", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
        cwd=repo_dir,
    )
    if status == -1:
        raise RepositoryError("gh_cli_missing", "gh CLI is not installed or not in PATH")
    if status != 0 or not output:
        return None
    return output.splitlines()[0].strip()


def load_fixture(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RepositoryError("ambiguous_origin", f"cannot read fixture {path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("remotes"), dict):
        raise RepositoryError("ambiguous_origin", "fixture must contain a remotes object")
    return payload


# --- Branch/refspec verification and dry-run push --------------------------


def verify_branch_and_dry_run(
    repo_dir: Path,
    *,
    remote: str,
    assigned_branch: str,
    dest_ref: str | None = None,
    dry_run_runner: Callable[[list[str], Path], tuple[int, str]] | None = None,
    lease_oid: str | None = None,
) -> dict[str, object]:
    """Confirm the current checkout is on the ledger-assigned branch, then run
    a `git push --dry-run` for the exact remote/refspec a real push would use.

    A dry run is read-only in effect (it never advances a ref) but is a real
    network round-trip against the actual remote, so it is the only
    non-offline check in this module; it is also the strongest evidence that
    the push will actually succeed against the intended destination.

    `lease_oid` opts in to a rebased-branch push: the live remote head of the
    branch must equal it at every push URL (`verify_branch_lease`), and the
    dry run then carries `--force-with-lease=<ref>:<oid>`. Without it nothing
    here can force: a non-fast-forward stays `dry_run_failed`.
    """
    current = get_current_branch(repo_dir)
    if current is None:
        return {
            "status": "incomplete",
            "reason_code": "branch_unavailable",
            "reason": "could not determine the current branch",
        }
    if current != assigned_branch:
        return {
            "status": "incomplete",
            "reason_code": "branch_mismatch",
            "reason": f"the ledger assigns `{assigned_branch}` but the checkout is on `{current}`",
        }

    ref = f"refs/heads/{assigned_branch}"
    if dest_ref is not None and dest_ref != ref:
        return {"status": "incomplete", "reason_code": "destination_mismatch",
                "reason": "destination must be the assigned task branch"}
    valid_ref, _ = read_command(["git", "check-ref-format", ref], cwd=repo_dir)
    if valid_ref != 0 or assigned_branch.startswith("-"):
        return {"status": "incomplete", "reason_code": "invalid_branch",
                "reason": "assigned branch is not a valid branch name"}
    refspec = f"{assigned_branch}:{ref}"
    runner = dry_run_runner or (lambda cmd, cwd: read_command(cmd, cwd=cwd))
    command = ["git", "push", "--dry-run"]
    if lease_oid is not None:
        lease = verify_branch_lease(repo_dir, remote=remote, ref=ref, lease_oid=lease_oid, runner=dry_run_runner)
        if lease["status"] != "ready":
            return lease
        command.append(f"--force-with-lease={ref}:{lease_oid}")
    command += [remote, refspec]
    status, output = runner(command, repo_dir)
    if status != 0:
        return {
            "status": "incomplete",
            "reason_code": "dry_run_failed",
            "reason": f"`{' '.join(command)}` did not succeed (exit {status})",
        }
    verdict: dict[str, object] = {
        "status": "ready",
        "reason_code": "dry_run_confirmed",
        "reason": f"dry run of `git push {remote} {refspec}` succeeded",
        "remote": remote,
        "refspec": refspec,
    }
    if lease_oid is not None:
        verdict["lease"] = f"--force-with-lease={ref}:{lease_oid}"
        verdict["reason"] = f"dry run of `git push {verdict['lease']} {remote} {refspec}` succeeded"
    return verdict


# --- Force-with-lease (rebased branch) verification --------------------------
#
# A rebased branch can only reach its remote by a non-fast-forward push. The
# sanctioned form is an explicit lease on the exact remote head the lead
# approved replacing -- never a bare `--force`. The lease is opt-in
# (`--force-with-lease <oid>`), applies to the assigned branch push only, and
# is checked twice: here against the *live* remote head (`git ls-remote`, so a
# stale local remote-tracking ref cannot make a wrong oid look right), and again
# by Git itself when the dry run and the real push carry the same lease.


def validate_lease_oid(value: str) -> dict[str, object]:
    """Offline validation of `--force-with-lease`; fails closed.

    Only a full-length lowercase object id is accepted. An abbreviation,
    a ref name, an empty or whitespace-padded value, or an uppercase id is
    refused rather than normalized or resolved: the lease must name one exact
    remote head.
    """
    if not FULL_SHA.fullmatch(value):
        return _incomplete(
            "invalid_lease_oid",
            "--force-with-lease requires a full 40 or 64 character lowercase hex object id",
        )
    return {"status": "ready", "oid": value}


def verify_branch_lease(
    repo_dir: Path,
    *,
    remote: str,
    ref: str,
    lease_oid: str,
    runner: Callable[[list[str], Path], tuple[int, str]] | None = None,
) -> dict[str, object]:
    """Require the live remote head of `ref` to equal `lease_oid` at every push URL.

    Reads each push URL with `git ls-remote -- <url> <ref>` and compares the
    exact `ref` line. Every unreadable, unparseable, missing, or differing
    answer is `incomplete`; the mismatch reason names both oids.
    """
    run = runner or (lambda cmd, cwd: read_command(cmd, cwd=cwd, merge_stderr=False))
    url_status, url_output = read_command(["git", "remote", "get-url", "--push", "--all", remote], cwd=repo_dir)
    urls = [line.strip() for line in url_output.splitlines() if line.strip()] if url_status == 0 else []
    if not urls:
        return _incomplete("push_url_unavailable", f"could not read the push URL of remote `{remote}`")

    for index, url in enumerate(urls, 1):
        where = f"push URL {index} of {len(urls)} of remote `{remote}`"
        status, output = run(["git", "ls-remote", "--", url, ref], repo_dir)
        if status != 0:
            return _incomplete("remote_unreachable", f"could not read `{ref}` from {where} (exit {status})")
        heads: list[str] = []
        for line in output.splitlines():
            value, _, name = line.partition("\t")
            if name == ref:
                if not FULL_SHA.fullmatch(value):
                    return _incomplete("remote_head_unresolved", f"{where} reported an unparseable head for `{ref}`")
                heads.append(value)
        if not heads:
            return _incomplete("lease_branch_missing", f"`{ref}` does not exist on {where}; a lease needs an existing remote head")
        if len(heads) != 1:
            return _incomplete("remote_head_unresolved", f"{where} reported more than one head for `{ref}`")
        if heads[0] != lease_oid:
            return _incomplete(
                "lease_mismatch",
                f"lease oid {lease_oid} does not match the live head {heads[0]} of `{ref}` at {where}",
            )
    return {"status": "ready", "reason_code": "lease_verified", "reason": f"`{ref}` is at {lease_oid} at every push URL"}


# --- Release tag push verification -------------------------------------------
#
# A release tag is cut from the remote default branch's tip, usually from a
# detached or linked-worktree checkout, so the branch-state guard above cannot
# apply. This mode replaces it with checks that do not depend on which branch
# (if any) is checked out: the tag target must be the *live* tip of the remote
# default branch, and the tag must not already exist locally or on the remote.
# The default branch is read with `git ls-remote --symref <push-url> HEAD`
# rather than from a local `refs/remotes/*` ref, so a stale or un-fetched local
# ref cannot make a wrong target look right and no fetch is needed.

TAG_REF_PREFIX = "refs/tags/"
FULL_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def _incomplete(reason_code: str, reason: str) -> dict[str, object]:
    return {"status": "incomplete", "reason_code": reason_code, "reason": reason}


def validate_tag_arguments(
    repo_dir: Path,
    *,
    tag_target: str,
    dest_ref: str | None,
    assigned_branch: str | None,
) -> dict[str, object]:
    """Offline validation of the tag-mode arguments; fails closed.

    Returns `ready` with the tag name and the full commit sha `tag_target`
    resolves to in this checkout, or an `incomplete` verdict.
    """
    if assigned_branch is not None:
        return _incomplete(
            "conflicting_arguments",
            "--tag-target and --assigned-branch cannot be combined: a tag push has no branch guard",
        )
    if not dest_ref or not dest_ref.startswith(TAG_REF_PREFIX):
        return _incomplete("invalid_tag_destination", "--tag-target requires --dest-ref refs/tags/<name>")
    name = dest_ref[len(TAG_REF_PREFIX):]
    if not name or name.startswith("-"):
        return _incomplete("invalid_tag_destination", "tag name is empty or starts with `-`")
    valid_ref, _ = read_command(["git", "check-ref-format", dest_ref], cwd=repo_dir)
    if valid_ref != 0:
        return _incomplete("invalid_tag_destination", "destination is not a valid tag ref name")

    if not tag_target or tag_target.startswith("-"):
        return _incomplete("invalid_tag_target", "--tag-target is empty or starts with `-`")
    status, output = read_command(
        ["git", "rev-parse", "--verify", "--quiet", f"{tag_target}^{{commit}}"], cwd=repo_dir)
    if status == -1:
        raise RepositoryError("git_cli_missing", "git CLI is not installed or not in PATH")
    sha = output.strip().lower()
    if status != 0 or not FULL_SHA.match(sha):
        return _incomplete("invalid_tag_target", "--tag-target does not resolve to a commit in this checkout")
    return {"status": "ready", "name": name, "target": sha}


def _parse_remote_head(output: str) -> tuple[str | None, str | None]:
    """Return (default branch name, tip sha) from `git ls-remote --symref <url> HEAD`."""
    branch = sha = None
    for line in output.splitlines():
        if line.startswith("ref: "):
            ref, _, name = line[len("ref: "):].partition("\t")
            if name == "HEAD" and ref.startswith("refs/heads/") and len(ref) > len("refs/heads/"):
                branch = ref[len("refs/heads/"):]
        else:
            value, _, name = line.partition("\t")
            if name == "HEAD" and FULL_SHA.match(value):
                sha = value
    return branch, sha


def verify_tag_push(
    repo_dir: Path,
    *,
    remote: str,
    tag_name: str,
    target: str,
    runner: Callable[[list[str], Path], tuple[int, str]] | None = None,
) -> dict[str, object]:
    """Verify that pushing `refs/tags/<tag_name>` at `target` to `remote` is safe.

    Every check is against live state and none requires a checked-out branch.
    Any unreadable, unparseable, or unreachable answer is `incomplete`.
    """
    ref = f"{TAG_REF_PREFIX}{tag_name}"
    run = runner or (lambda cmd, cwd: read_command(cmd, cwd=cwd, merge_stderr=False))

    local_status, _ = read_command(["git", "show-ref", "--verify", "--quiet", ref], cwd=repo_dir)
    if local_status == 0:
        return _incomplete("tag_exists_local", f"tag `{tag_name}` already exists locally")
    if local_status != 1:
        return _incomplete("local_tag_check_failed", f"could not determine whether tag `{tag_name}` exists locally")

    url_status, url_output = read_command(["git", "remote", "get-url", "--push", "--all", remote], cwd=repo_dir)
    urls = [line.strip() for line in url_output.splitlines() if line.strip()] if url_status == 0 else []
    if not urls:
        return _incomplete("push_url_unavailable", f"could not read the push URL of remote `{remote}`")

    default_branch: str | None = None
    for index, url in enumerate(urls, 1):
        where = f"push URL {index} of {len(urls)} of remote `{remote}`"
        status, output = run(["git", "ls-remote", "--symref", "--", url, "HEAD"], repo_dir)
        if status != 0:
            return _incomplete("remote_unreachable", f"could not read the default branch from {where} (exit {status})")
        branch, tip = _parse_remote_head(output)
        if branch is None or tip is None:
            return _incomplete("default_branch_unresolved", f"{where} did not report a default branch and tip")
        if tip != target:
            return _incomplete(
                "target_mismatch",
                f"tag target {target} is not the tip of the remote default branch `{branch}` ({tip}) at {where}",
            )
        default_branch = branch

        status, output = run(["git", "ls-remote", "--tags", "--", url, ref], repo_dir)
        if status != 0:
            return _incomplete("remote_unreachable", f"could not list tags on {where} (exit {status})")
        for line in output.splitlines():
            _, _, listed = line.partition("\t")
            if listed in (ref, f"{ref}^{{}}"):
                return _incomplete("tag_exists_remote", f"tag `{tag_name}` already exists on {where}")

    refspec = f"{target}:{ref}"
    status, _ = run(["git", "push", "--dry-run", remote, refspec], repo_dir)
    if status != 0:
        return _incomplete("dry_run_failed", f"`git push --dry-run {remote} {refspec}` did not succeed (exit {status})")
    return {
        "status": "ready",
        "reason_code": "tag_push_verified",
        "reason": f"tag `{tag_name}` at {target} is the tip of `{default_branch}` and does not exist yet",
        "remote": remote,
        "refspec": refspec,
        "tag": {"name": tag_name, "target": target, "default_branch": default_branch},
    }


# --- Transport account verification -----------------------------------------
#
# Bounded to the two supported transports named in the plan: an ordinary HTTPS
# credential helper, and standard OpenSSH including host aliases. Anything
# else -- a custom SSH command/variant, an HTTP auth header override (matched
# the way Git itself matches it), or an askpass fallback (env or
# `core.askPass`) -- returns `unsupported_transport_auth` rather than probing
# a different, lower-precedence source and reporting on the wrong identity.
#
# No network call in this module is exercised during development or in the
# test suite: `lookup_login` / `prober` / `runner` are always injected by the
# caller (production wiring calls the real implementations; tests inject a
# stub).


def detect_ssh_overrides(repo_dir: Path) -> str | None:
    """Return the name of a higher-precedence SSH command/variant override, if any."""
    for env_var in ("GIT_SSH_COMMAND", "GIT_SSH"):
        if os.environ.get(env_var):
            return env_var
    status, output = read_command(["git", "config", "core.sshCommand"], cwd=repo_dir)
    if status == 0 and output:
        return "core.sshCommand"
    if os.environ.get("GIT_SSH_VARIANT"):
        return "GIT_SSH_VARIANT"
    status, output = read_command(["git", "config", "ssh.variant"], cwd=repo_dir)
    if status == 0 and output:
        return "ssh.variant"
    return None


def detect_https_auth_overrides(repo_dir: Path, url: str) -> str | None:
    """Return the name of a higher-precedence HTTP auth override, if any.

    Uses Git's own effective URL-matching resolution
    (`git config --get-urlmatch`) rather than literal key lookups: Git
    commonly stores a URL-scoped override under a prefix like
    `http.https://github.com/.extraHeader`, which a literal
    `http.<url>.extraHeader` key lookup never finds. A separate authorization
    header means the credential helper does not speak for the account Git
    will actually use; probing it anyway would attest to the wrong identity.
    """
    status, output = read_command(
        ["git", "config", "--get-urlmatch", "http.extraHeader", url], cwd=repo_dir
    )
    if status == 0 and output:
        return "http.extraHeader"
    return None


def detect_askpass_overrides(repo_dir: Path) -> str | None:
    for env_var in ("GIT_ASKPASS", "SSH_ASKPASS"):
        if os.environ.get(env_var):
            return env_var
    status, output = read_command(["git", "config", "core.askPass"], cwd=repo_dir)
    if status == 0 and output:
        return "core.askPass"
    return None


def fill_https_credential(repo_dir: Path, url: str) -> dict[str, str] | None:
    """Resolve the credential Git would use for *url* via `git credential fill`.

    Captured only in this process; the caller must never print, log, or
    persist the returned password. Returns None on any failure or missing
    field rather than raising, so an unavailable helper reads as
    `identity_unavailable`, not a traceback.
    """
    env = {**os.environ, **NONINTERACTIVE_ENV_OVERRIDES}
    try:
        completed = subprocess.run(
            ["git", "credential", "fill"],
            cwd=str(repo_dir),
            input=f"url={url}\n\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=COMMAND_TIMEOUT,
            env=env,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    fields: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        fields[key] = value
    if "username" not in fields or "password" not in fields:
        return None
    return fields


def lookup_authenticated_login_https(credential: dict[str, str]) -> str | None:
    """Call GitHub's authenticated-user endpoint with the resolved credential.

    Production wiring only. Not called during this change's development or
    test suite -- every test injects `lookup_login`. Live evidence is a
    separate, explicitly-run step in the user's own environment.
    """
    import urllib.error
    import urllib.request

    token = f"{credential['username']}:{credential['password']}"
    basic = base64.b64encode(token.encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        "https://api.github.com/user",
        headers={
            "Authorization": f"Basic {basic}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "dev-skill-resolve-repository",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=COMMAND_TIMEOUT) as response:
            if response.status != 200:
                return None
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError, OSError):
        return None
    login = payload.get("login")
    return str(login) if isinstance(login, str) else None


def verify_https_account(
    repo_dir: Path,
    url: str,
    expected_account: str,
    *,
    lookup_login: Callable[[dict[str, str]], str | None] = lookup_authenticated_login_https,
) -> dict[str, object]:
    """Verify the account an HTTPS credential helper would present for *url*."""
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname != GITHUB_HOST
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or parsed.query or parsed.fragment
                or any(c.isspace() for c in url)):
            raise ValueError
    except ValueError:
        return {"status": "incomplete", "reason_code": "unsupported_transport_auth",
                "reason": "expected a noncredential HTTPS GitHub push URL"}
    override = detect_https_auth_overrides(repo_dir, url)
    if override:
        return {
            "status": "incomplete",
            "reason_code": "unsupported_transport_auth",
            "reason": f"`{override}` overrides HTTPS authentication for this URL",
        }
    askpass_override = detect_askpass_overrides(repo_dir)
    if askpass_override:
        return {
            "status": "incomplete",
            "reason_code": "unsupported_transport_auth",
            "reason": f"`{askpass_override}` is set; a helper-only probe cannot be guaranteed noninteractive",
        }
    credential = fill_https_credential(repo_dir, url)
    if credential is None:
        return {
            "status": "incomplete",
            "reason_code": "identity_unavailable",
            "reason": "no credential helper resolved a credential for this URL",
        }
    login = lookup_login(credential)
    if login is None:
        return {
            "status": "incomplete",
            "reason_code": "identity_unavailable",
            "reason": "the resolved credential did not authenticate against GitHub",
        }
    if login.casefold() != expected_account.casefold():
        return {
            "status": "incomplete",
            "reason_code": "account_mismatch",
            "reason": f"authenticated as {login}, but .dev.json names {expected_account}",
        }
    return {"status": "verified", "reason_code": "account_matches", "reason": f"authenticated as {login}"}


def probe_ssh_account(repo_dir: Path, target: str, user: str, *, port: int | None = None) -> tuple[int, str]:
    """Probe `<user>@<target>`, where *target* is the original alias/host --
    never the resolved hostname -- so SSH's own config resolution (identity,
    port, proxy) applies exactly as it would for a real push."""
    env = {**os.environ, **NONINTERACTIVE_ENV_OVERRIDES}
    command = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
               "-o", "StrictHostKeyChecking=yes", "-o", "UpdateHostKeys=no"]
    if port is not None:
        command += ["-p", str(port)]
    command += [f"{user}@{target}"]
    try:
        completed = subprocess.run(
            command,
            cwd=str(repo_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=COMMAND_TIMEOUT,
            env=env,
            check=False,
        )
    except OSError as exc:
        return (-1, str(exc))
    except subprocess.SubprocessError as exc:
        return (124, str(exc))
    return completed.returncode, completed.stdout.strip()


def verify_ssh_account(
    repo_dir: Path,
    host_or_alias: str,
    expected_account: str,
    *,
    prober: Callable[[Path, str, str], tuple[int, str]] = probe_ssh_account,
    resolver: Callable[[Path, str], tuple[str, str, str] | None] = resolve_ssh_effective_host,
) -> dict[str, object]:
    """Verify the account an OpenSSH probe authenticates as for *host_or_alias*.

    *host_or_alias* is resolved via `ssh -G` first, both to confirm it
    actually points at GitHub and to obtain the effective user -- the alias
    itself (never the resolved hostname) is what gets probed, preserving
    whatever `Host` block, port, or identity file the alias configures.
    GitHub's documented successful SSH test exits **1** with an
    account-bearing greeting; a generic zero-exit rule would misclassify
    both directions.
    """
    override = detect_ssh_overrides(repo_dir)
    if override:
        return {
            "status": "incomplete",
            "reason_code": "unsupported_transport_auth",
            "reason": f"`{override}` overrides the SSH transport",
        }
    resolved = resolver(repo_dir, host_or_alias)
    if resolved is None:
        return {
            "status": "incomplete",
            "reason_code": "identity_unavailable",
            "reason": f"`ssh -G {host_or_alias}` did not resolve an effective host",
        }
    hostname, user, _port = resolved
    if hostname.lower() != GITHUB_HOST:
        return {
            "status": "incomplete",
            "reason_code": "non_github_origin",
            "reason": f"`{host_or_alias}` resolves to {hostname}, not {GITHUB_HOST}",
        }
    status, output = prober(repo_dir, host_or_alias, user)
    if status == -1:
        return {
            "status": "incomplete",
            "reason_code": "identity_unavailable",
            "reason": "ssh is not installed or not in PATH",
        }
    match = GITHUB_SSH_GREETING.search(output)
    if status != 1 or not match:
        return {
            "status": "incomplete",
            "reason_code": "identity_unavailable",
            "reason": "did not receive the documented GitHub SSH greeting/exit status",
        }
    login = match.group(1)
    if login.casefold() != expected_account.casefold():
        return {
            "status": "incomplete",
            "reason_code": "account_mismatch",
            "reason": f"authenticated as {login}, but .dev.json names {expected_account}",
        }
    return {"status": "verified", "reason_code": "account_matches", "reason": f"authenticated as {login}"}


def verify_ssh_url_account(repo_dir: Path, url: str, expected_account: str) -> dict[str, object]:
    """Use the exact push URL's user/port overrides while preserving its alias."""
    try:
        if any(c.isspace() for c in url):
            raise ValueError
        if "://" in url:
            parsed = urlsplit(url)
            if parsed.scheme != "ssh" or parsed.password is not None or parsed.query or parsed.fragment:
                raise ValueError
            host, user, port = parsed.hostname, parsed.username, parsed.port
        else:
            match = SCP_LIKE.fullmatch(url)
            if not match:
                raise ValueError
            host, user, port = match.group("host"), match.group("user"), None
        if not host or host.startswith("-") or (user and not re.fullmatch(r"[A-Za-z0-9._-]+", user)):
            raise ValueError
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        return {"status": "incomplete", "reason_code": "unsupported_transport_auth",
                "reason": "expected a standard SSH push URL"}
    return verify_ssh_account(
        repo_dir, host, expected_account,
        resolver=lambda cwd, alias: resolve_ssh_effective_host(cwd, alias, user=user, port=port),
        prober=lambda cwd, alias, effective_user: probe_ssh_account(cwd, alias, effective_user, port=port),
    )


def verify_gh_cli_login(
    repo_dir: Path,
    expected_account: str,
    *,
    runner: Callable[[], tuple[int, str]] | None = None,
) -> dict[str, object]:
    """Verify the account the `gh` CLI is actually authenticated as.

    Distinct from the Git transport account: two accounts can both have
    access to a repository, so a correct Git credential does not establish
    which account `gh` will use for an API mutation. `gh auth status` alone
    is not accepted -- it names the configured account, not necessarily the
    one a given command will authenticate as -- so this calls the
    authenticated-user endpoint through `gh api` directly.
    """
    if os.environ.get("GH_HOST", GITHUB_HOST).lower() != GITHUB_HOST:
        return {"status": "incomplete", "reason_code": "host_mismatch",
                "reason": "GH_HOST conflicts with the configured github.com host"}
    run = runner or (lambda: read_command(
        ["gh", "api", "--hostname", GITHUB_HOST, "user", "--jq", ".login"], cwd=repo_dir,
        merge_stderr=False))
    status, output = run()
    if status == -1:
        return {"status": "incomplete", "reason_code": "gh_cli_missing", "reason": "gh CLI is not installed or not in PATH"}
    if status != 0 or not output:
        return {
            "status": "incomplete",
            "reason_code": "identity_unavailable",
            "reason": "`gh api user` did not return an authenticated login",
        }
    login = output.splitlines()[0].strip()
    if login.casefold() != expected_account.casefold():
        return {
            "status": "incomplete",
            "reason_code": "account_mismatch",
            "reason": f"gh CLI is authenticated as {login}, but .dev.json names {expected_account}",
        }
    return {"status": "verified", "reason_code": "account_matches", "reason": f"gh CLI authenticated as {login}"}


# --- CLI ---------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    # No prefix matching: `--force` must never resolve to `--force-with-lease`.
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument(
        "--mode",
        choices=("resolve", "check-https-account", "check-ssh-account", "check-gh-account"),
        default="resolve",
        help="'resolve' (default) decides the operation target; the check-* modes verify an account",
    )
    parser.add_argument(
        "--operation",
        choices=("push", "pr", "issue"),
        default="push",
        help="'push' validates the Git push destination; 'pr'/'issue' validate an explicit API target",
    )
    parser.add_argument("--repo-dir", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path, help="explicit path to the selected worktree root's .dev.json; other locations are rejected")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--target", help="explicit OWNER/REPO this pr/issue operation is about to use")
    parser.add_argument(
        "--allow-target-override",
        action="store_true",
        help="accept --target as an already-confirmed, explicitly assigned Issue's own qualified identity",
    )
    parser.add_argument("--assigned-branch", help="the ledger-assigned branch for a push operation")
    parser.add_argument("--dest-ref", help="destination ref for the dry run; defaults to refs/heads/<assigned-branch>")
    parser.add_argument(
        "--tag-target",
        help=(
            "release-tag push mode: the commit the tag will point at. Requires --dest-ref refs/tags/<name> and "
            "replaces --assigned-branch; verifies the commit is the live remote default-branch tip and the tag "
            "does not exist yet, without requiring any branch to be checked out"
        ),
    )
    parser.add_argument(
        "--force-with-lease",
        metavar="OID",
        help=(
            "rebased-branch push mode: the full object id the remote branch must currently be at. Applies only "
            "to `--operation push --assigned-branch`. Verifies the live remote head equals OID, then dry-runs "
            "`git push --force-with-lease=refs/heads/<branch>:OID`; the caller must push with the same lease. "
            "Opt-in and never a bare --force; without it a non-fast-forward stays `dry_run_failed`"
        ),
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        help="pure decision-logic testing only: read deterministic remote/default state instead of loading .dev.json",
    )
    parser.add_argument("--expect", help="(--fixture only) canonical OWNER/REPO override")
    parser.add_argument("--configured-remote", help="(--fixture only) pushRemote override")
    parser.add_argument(
        "--print-push-remote",
        action="store_true",
        help=(
            "print only the validated push remote name, and only when the verdict "
            "is `ready`; otherwise print nothing on stdout and exit 2"
        ),
    )
    parser.add_argument(
        "--no-verify-access",
        action="store_true",
        help="skip the read-only gh accessibility check (bootstrap before a remote is reachable)",
    )
    parser.add_argument("--url", help="exact push URL for check-https-account or check-ssh-account")
    parser.add_argument("--account", help="expected account for a check-*-account mode")
    parser.add_argument("--setup-account-check", action="store_true", help="read-only candidate check before .dev.json exists; never authorizes a write")
    return parser.parse_args()


def _emit(decision: dict[str, object]) -> int:
    ready = decision.get("status") in ("ready", "verified")
    print(json.dumps(decision, sort_keys=True, separators=(",", ":")))
    return 0 if ready else 2


def _run_resolve_fixture(args: argparse.Namespace) -> int:
    """Pure decision-logic path: exercises `_decide_push_target` against a
    hand-written fixture. Never loads `.dev.json` -- see the module
    docstring for why this is not the production entrypoint."""
    try:
        fixture = load_fixture(args.fixture)
        remotes = {str(k): _as_list(v) for k, v in fixture["remotes"].items()}
        push_raw = fixture.get("push_remotes")
        push_remotes = {str(k): _as_list(v) for k, v in push_raw.items()} if isinstance(push_raw, dict) else None
        raw_default = fixture.get("gh_default")
        gh_default = None if raw_default is None else str(raw_default)
        access_verified = bool(fixture.get("access_verified", False))
        raw_verified = fixture.get("verified_name")
        verified_name = None if raw_verified is None else str(raw_verified)
        remote_name = str(fixture.get("effective_push_remote", args.remote))
        configured_remote = fixture.get("configured_remote", args.configured_remote)
        configured_remote = None if configured_remote is None else str(configured_remote)
        expect = fixture.get("expect", args.expect)
        decision = resolve_repository(
            remotes=remotes,
            push_remotes=push_remotes,
            gh_default=gh_default,
            verified_name=verified_name,
            access_verified=access_verified,
            expected=expect,
            remote_name=remote_name,
            configured_remote=configured_remote,
        )
    except RepositoryError as exc:
        decision = {
            "status": "incomplete",
            "repository": None,
            "effective_push_remote": None,
            "remote": args.remote,
            "reason_code": exc.code,
            "reason": str(exc),
        }
    if args.print_push_remote:
        if decision.get("status") == "ready":
            print(decision["effective_push_remote"])
            return 0
        print(decision["reason"], file=sys.stderr)
        return 2
    return _emit(decision)


def _load_required_config(args: argparse.Namespace) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    """Load and require a valid `.dev.json`. Returns (config, error-decision);
    exactly one is None."""
    repo_dir = args.repo_dir.resolve()
    try:
        git_root = dev_config.find_git_root(repo_dir)
    except dev_config.ConfigError as exc:
        return None, {"status": "incomplete", "reason_code": exc.code, "reason": str(exc)}
    config_path = (git_root or repo_dir).resolve() / dev_config.CONFIG_FILENAME
    # Compare against the root's literal filename, not its symlink destination.
    if config_path.resolve() != config_path or (args.config is not None and args.config.resolve() != config_path):
        return None, {
            "status": "incomplete",
            "reason_code": "config_path_mismatch",
            "reason": "config must be the selected worktree root's .dev.json, without a symlink to another location",
        }
    status = dev_config.resolve_status(config_path)
    if status["status"] != "valid":
        return None, {
            "status": "incomplete",
            "reason_code": status["reason_code"] or f"config_{status['status']}",
            "reason": status["reason"] or f".dev.json status is {status['status']}",
        }
    return status["config"], None


def _run_resolve_push(args: argparse.Namespace, config: dict[str, object]) -> int:
    github = config["github"]
    if args.no_verify_access:
        return _emit({"status": "incomplete", "reason_code": "verification_required",
                      "reason": "push readiness cannot skip repository verification"})
    tag_mode = args.tag_target is not None
    tag_args: dict[str, object] = {}
    lease_oid: str | None = args.force_with_lease
    if lease_oid is not None:
        # Defense in depth: main() already refuses the lease on every other path.
        lease_args = _lease_applicability(args)
        if lease_args["status"] != "ready":
            return _emit(lease_args)
    if tag_mode:
        try:
            tag_args = validate_tag_arguments(
                args.repo_dir.resolve(), tag_target=args.tag_target,
                dest_ref=args.dest_ref, assigned_branch=args.assigned_branch)
        except RepositoryError as exc:
            tag_args = _incomplete(exc.code, str(exc))
        if tag_args["status"] != "ready":
            return _emit(tag_args)
    elif not args.assigned_branch:
        return _emit({
            "status": "incomplete",
            "reason_code": "missing_argument",
            "reason": "--assigned-branch is required for --operation push",
        })

    repo_dir = args.repo_dir.resolve()
    try:
        remotes, push_remotes = collect_remotes(repo_dir)
        remote_name = get_effective_push_remote(repo_dir)
        gh_default = collect_gh_default(repo_dir)
        access_verified = not args.no_verify_access
        verified_name = None
        if access_verified:
            try:
                canonical = _first_canonical(remotes, push_remotes, remote_name, repo_dir=repo_dir)
            except RepositoryError:
                access_verified = False
            else:
                if canonical is not None:
                    verified_name = collect_verified_name(repo_dir, canonical)
    except RepositoryError as exc:
        return _emit({
            "status": "incomplete",
            "repository": None,
            "effective_push_remote": None,
            "reason_code": exc.code,
            "reason": str(exc),
        })

    decision = resolve_repository(
        remotes=remotes,
        push_remotes=push_remotes,
        gh_default=gh_default,
        verified_name=verified_name,
        access_verified=access_verified,
        expected=github["pushRepository"],
        remote_name=remote_name,
        configured_remote=github["pushRemote"],
        repo_dir=repo_dir,
    )

    if decision["status"] == "ready":
        for url in _effective_push_urls(remotes, push_remotes, remote_name):
            if url.startswith("https://"):
                account = verify_https_account(repo_dir, url, github["account"])
            else:
                account = verify_ssh_url_account(repo_dir, url, github["account"])
            if account["status"] != "verified":
                return _emit({"status": "incomplete", "repository": None,
                              "remote": None, "effective_push_remote": None,
                              "reason_code": account["reason_code"], "reason": account["reason"]})
        if tag_mode:
            login = verify_gh_cli_login(repo_dir, github["account"])
            if login["status"] != "verified":
                return _emit({"status": "incomplete", "repository": None,
                              "remote": None, "effective_push_remote": None,
                              "reason_code": login["reason_code"], "reason": login["reason"]})
            dry_run = verify_tag_push(
                repo_dir,
                remote=str(decision["effective_push_remote"]),
                tag_name=str(tag_args["name"]),
                target=str(tag_args["target"]),
            )
        else:
            dry_run = verify_branch_and_dry_run(
                repo_dir,
                remote=str(decision["effective_push_remote"]),
                assigned_branch=args.assigned_branch,
                dest_ref=args.dest_ref,
                lease_oid=lease_oid,
            )
        if dry_run["status"] != "ready":
            decision["status"] = "incomplete"
            decision["reason_code"] = dry_run["reason_code"]
            decision["reason"] = dry_run["reason"]
            decision["effective_push_remote"] = None
            decision["remote"] = None
            decision["repository"] = None
        else:
            decision["dry_run"] = {"remote": dry_run["remote"], "refspec": dry_run["refspec"]}
            if "lease" in dry_run:
                decision["dry_run"]["lease"] = dry_run["lease"]
            if tag_mode:
                decision["tag"] = dry_run["tag"]

    if args.print_push_remote:
        if decision.get("status") == "ready":
            print(decision["effective_push_remote"])
            return 0
        print(decision["reason"], file=sys.stderr)
        return 2
    return _emit(decision)


def _run_resolve_operation(args: argparse.Namespace, config: dict[str, object]) -> int:
    github = config["github"]
    expected = github["pullRequestRepository"] if args.operation == "pr" else github["pushRepository"]
    decision = _decide_operation_target(target=args.target, expected=expected, allow_override=args.allow_target_override)
    if decision["status"] == "ready":
        repo_dir = args.repo_dir.resolve()
        login_check = verify_gh_cli_login(repo_dir, github["account"])
        if login_check["status"] != "verified":
            decision["status"] = "incomplete"
            decision["reason_code"] = login_check["reason_code"]
            decision["reason"] = login_check["reason"]
    return _emit(decision)


def _run_resolve(args: argparse.Namespace) -> int:
    if args.fixture is not None:
        return _run_resolve_fixture(args)

    config, error = _load_required_config(args)
    if error is not None:
        return _emit(error)
    assert config is not None

    if args.operation == "push":
        return _run_resolve_push(args, config)
    return _run_resolve_operation(args, config)


def _run_check_account(args: argparse.Namespace) -> int:
    config, error = _load_required_config(args)
    if args.setup_account_check:
        if error is None or error["reason_code"] != "missing_config":
            return _emit(error or {"status": "incomplete", "reason_code": "config_exists", "reason": "setup candidate checks require a missing config"})
        if not args.account:
            return _emit({"status": "incomplete", "reason_code": "missing_argument", "reason": "--account is required for setup"})
        account = args.account
    else:
        if error is not None:
            return _emit(error)
        account = config["github"]["account"]
        if args.account and args.account.lower() != account.lower():
            return _emit({"status": "incomplete", "reason_code": "account_mismatch", "reason": "--account disagrees with the configured account"})
    repo_dir = args.repo_dir.resolve()
    if args.mode == "check-https-account":
        if not args.url:
            return _emit({"status": "incomplete", "reason_code": "missing_argument", "reason": "--url is required"})
        result = verify_https_account(repo_dir, args.url, account)
    elif args.mode == "check-ssh-account":
        if not args.url:
            return _emit({"status": "incomplete", "reason_code": "missing_argument", "reason": "--url is required"})
        result = verify_ssh_url_account(repo_dir, args.url, account)
    else:
        result = verify_gh_cli_login(repo_dir, account)
    if args.setup_account_check and result["status"] == "verified":
        print(json.dumps({**result, "status": "candidate_verified", "reason": "candidate account verified for setup only; save confirmed config and recheck before writing"}))
        return 0
    return _emit(result)


def _lease_applicability(args: argparse.Namespace) -> dict[str, object]:
    """Fail closed unless `--force-with-lease` is a well-formed lease on a branch push.

    The lease exists only for `--operation push --assigned-branch` against
    live state. Any other combination -- an Issue/PR operation, a tag push, a
    fixture run, an account check, a missing branch, a branch-less checkout --
    is refused rather than silently ignoring the flag.
    """
    if args.mode != "resolve" or args.operation != "push" or args.fixture is not None or args.tag_target is not None:
        return _incomplete(
            "lease_not_applicable",
            "--force-with-lease applies only to `--operation push --assigned-branch` (not pr/issue, --tag-target, "
            "--fixture, or the check-* modes)",
        )
    if not args.assigned_branch:
        return _incomplete("lease_not_applicable", "--force-with-lease requires --assigned-branch")
    return validate_lease_oid(args.force_with_lease)


def main() -> int:
    args = parse_args()
    if args.force_with_lease is not None:
        lease_args = _lease_applicability(args)
        if lease_args["status"] != "ready":
            return _emit(lease_args)
    if args.mode == "resolve":
        if args.setup_account_check:
            return _emit({"status": "incomplete", "reason_code": "invalid_mode", "reason": "setup candidate checks cannot resolve a write target"})
        return _run_resolve(args)
    return _run_check_account(args)


if __name__ == "__main__":
    raise SystemExit(main())
