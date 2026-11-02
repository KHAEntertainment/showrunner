#!/usr/bin/env python3
"""Load, validate, and create the local `.dev.json` project configuration.

`.dev.json` records confirmed, nonsecret project intent -- GitHub host, account,
push repository, PR repository, and named push remote -- so later `/dev`
operations can verify actual destinations against durable intent instead of
reconstructing it from conversation memory or a CLI default. It never holds a
token, password, private key, or credential-bearing URL.

This module owns config *shape* and *persistence*: parsing, schema validation,
Git index/ignore provenance, and atomic first-write. It does not decide which
remote a push will actually use or whether the current GitHub session matches
`account` -- that is `resolve_repository.py`'s job, using the values this
module hands it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

CONFIG_FILENAME = ".dev.json"
SUPPORTED_VERSION = 1
SUPPORTED_HOSTS = frozenset({"github.com"})

# Bounded so a hung `git` cannot block the lead indefinitely.
COMMAND_TIMEOUT = 10

OWNER_REPO_PATTERN = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?/[A-Za-z0-9._-]+$"
)
REMOTE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
ACCOUNT_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$")

REQUIRED_GITHUB_FIELDS = (
    "host",
    "account",
    "pushRepository",
    "pullRequestRepository",
    "pushRemote",
)
ALLOWED_TOP_LEVEL_FIELDS = frozenset({"version", "github", "showcase"})
ALLOWED_GITHUB_FIELDS = frozenset(REQUIRED_GITHUB_FIELDS)

# The opt-in "Built with Showrunner" badge decision. `showcase` is optional, so
# an existing config without it keeps validating and SUPPORTED_VERSION stays 1.
# `badge` means "the badge has landed on the default branch" (true) or "the user
# declined / removed it" (false); an absent key means "never decided yet".
# `registerApproved` records consent to register a private project and is
# written before the network call; `registered`/`privateId` are written only on
# success. `showBadge` remembers "also show the badge" across a failed call.
# `privateId` is a lowercase hex hash (not a secret) returned by registration.
ALLOWED_SHOWCASE_FIELDS = frozenset(
    {"badge", "registered", "registerApproved", "privateId", "showBadge", "decidedAt"}
)
PRIVATE_ID_PATTERN = re.compile(r"[0-9a-f]{8,128}\Z")

# Substrings that mark a field name as secret-shaped. `.dev.json` records
# intent, never a token/password/key -- reject the field outright rather than
# silently accepting and later leaking it into a ledger or log.
FORBIDDEN_FIELD_NAME_SUBSTRINGS = (
    "token",
    "password",
    "passwd",
    "secret",
    "credential",
    "key",
)


class ConfigError(RuntimeError):
    """A missing, malformed, or untrustworthy config that cannot be used as intent."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _looks_like_secret_field(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in FORBIDDEN_FIELD_NAME_SUBSTRINGS)


def _contains_userinfo_or_url(value: str) -> bool:
    """Reject a repository/account value that embeds a URL or userinfo.

    A credential can hide in `https://user:token@github.com/...` or a bare
    `user@host` fragment; neither is a plain `OWNER/REPO` or account name.
    """
    return "://" in value or "@" in value


def validate_host(value: object, *, label: str = "github.host") -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ConfigError("invalid_field", f"{label} must be a non-empty string")
    if value not in SUPPORTED_HOSTS:
        raise ConfigError(
            "unsupported_host", f"{label} is not a supported host: {sorted(SUPPORTED_HOSTS)}"
        )
    return value


def validate_account(value: object, *, label: str = "github.account") -> str:
    if not isinstance(value, str) or not value:
        raise ConfigError("invalid_field", f"{label} must be a non-empty string")
    if value.strip() != value:
        raise ConfigError("invalid_field", f"{label} must not have leading/trailing whitespace")
    if _contains_userinfo_or_url(value):
        raise ConfigError("credential_bearing_value", f"{label} must not contain a URL or userinfo")
    if not ACCOUNT_PATTERN.match(value):
        raise ConfigError("invalid_field", f"{label} must be a plain account/organization name")
    return value


def validate_owner_repo(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigError("invalid_field", f"{label} must be a non-empty string")
    if value.strip() != value:
        raise ConfigError("invalid_field", f"{label} must not have leading/trailing whitespace")
    if _contains_userinfo_or_url(value):
        raise ConfigError("credential_bearing_value", f"{label} must not contain a URL or userinfo")
    if not OWNER_REPO_PATTERN.match(value):
        raise ConfigError("invalid_field", f"{label} must be OWNER/REPO")
    return value


def validate_remote_name(value: object, *, label: str = "github.pushRemote") -> str:
    if not isinstance(value, str) or not value:
        raise ConfigError("invalid_field", f"{label} must be a non-empty string")
    if value.strip() != value or not REMOTE_NAME_PATTERN.match(value):
        raise ConfigError("invalid_field", f"{label} must be a plain git remote name")
    return value


def validate_showcase(value: object) -> dict[str, object]:
    """Validate an optional `showcase` block. Raises `ConfigError` on any defect.

    Field names are checked for the secret-shaped substrings *before* the
    unknown-field check, so a secret-shaped name reports `secret_field_rejected`
    rather than `unknown_field` (the acceptance criterion requires that code).
    """
    if not isinstance(value, dict):
        raise ConfigError("invalid_field", "showcase must be an object")

    for field in value:
        if _looks_like_secret_field(field):
            raise ConfigError(
                "secret_field_rejected",
                f"showcase.{field} looks like a secret field and is not allowed",
            )

    unknown = sorted(set(value) - ALLOWED_SHOWCASE_FIELDS)
    if unknown:
        raise ConfigError("unknown_field", f"unknown showcase field(s): {unknown}")

    result: dict[str, object] = {}
    for field in ("badge", "registered", "registerApproved", "showBadge"):
        if field in value:
            raw = value[field]
            if not isinstance(raw, bool):
                raise ConfigError("invalid_field", f"showcase.{field} must be a boolean")
            result[field] = raw

    if "privateId" in value:
        raw = value["privateId"]
        if not isinstance(raw, str) or not PRIVATE_ID_PATTERN.fullmatch(raw):
            raise ConfigError(
                "invalid_field", "showcase.privateId must be a lowercase hex id"
            )
        result["privateId"] = raw

    if "decidedAt" in value:
        raw = value["decidedAt"]
        if not isinstance(raw, str) or not raw.strip():
            raise ConfigError("invalid_field", "showcase.decidedAt must be a non-empty string")
        result["decidedAt"] = raw

    return result


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """`json.loads` silently keeps the last of a duplicate key by default.

    A duplicate key is a malformed document, not a hint about which value to
    prefer -- accepting one path silently would let a later, unreviewed key
    win over an earlier, reviewed one.
    """
    seen: dict[str, object] = {}
    for key, value in pairs:
        if key in seen:
            raise ConfigError("duplicate_key", f"duplicate key in config: {key}")
        seen[key] = value
    return seen


def parse_config(raw_text: str) -> dict[str, object]:
    """Parse and validate `.dev.json` text. Never accepts secrets or unknown fields.

    Raises `ConfigError` for anything that is not a fully-formed, in-bounds
    document: malformed JSON, duplicate keys, missing/extra/empty fields, an
    unsupported version, or a value shaped like a credential.
    """
    try:
        payload = json.loads(raw_text, object_pairs_hook=_reject_duplicate_keys)
    except ConfigError:
        raise
    except json.JSONDecodeError as exc:
        raise ConfigError("malformed_json", "config is not valid JSON") from exc

    if not isinstance(payload, dict):
        raise ConfigError("malformed_json", "config must be a JSON object")

    unknown_top = sorted(set(payload) - ALLOWED_TOP_LEVEL_FIELDS)
    if unknown_top:
        raise ConfigError("unknown_field", f"unknown top-level field(s): {unknown_top}")

    if "version" not in payload:
        raise ConfigError("missing_field", "version is required")
    version = payload["version"]
    if not isinstance(version, int) or isinstance(version, bool):
        raise ConfigError("invalid_field", "version must be an integer")
    if version != SUPPORTED_VERSION:
        raise ConfigError("unsupported_version", f"unsupported version: {version!r}")

    github = payload.get("github")
    if not isinstance(github, dict):
        raise ConfigError("missing_field", "github section is required")

    unknown_github = sorted(set(github) - ALLOWED_GITHUB_FIELDS)
    if unknown_github:
        raise ConfigError("unknown_field", f"unknown github field(s): {unknown_github}")

    for field in github:
        if _looks_like_secret_field(field):
            raise ConfigError(
                "secret_field_rejected",
                f"github.{field} looks like a secret field and is not allowed",
            )

    missing = [field for field in REQUIRED_GITHUB_FIELDS if field not in github]
    if missing:
        raise ConfigError("missing_field", f"missing github field(s): {missing}")

    for field, raw_value in github.items():
        if isinstance(raw_value, str) and _contains_userinfo_or_url(raw_value):
            raise ConfigError(
                "credential_bearing_value", f"github.{field} must not contain a URL or userinfo"
            )

    validated_github = {
        "host": validate_host(github["host"]),
        "account": validate_account(github["account"]),
        "pushRepository": validate_owner_repo(github["pushRepository"], label="github.pushRepository"),
        "pullRequestRepository": validate_owner_repo(
            github["pullRequestRepository"], label="github.pullRequestRepository"
        ),
        "pushRemote": validate_remote_name(github["pushRemote"]),
    }

    result: dict[str, object] = {"version": version, "github": validated_github}
    if "showcase" in payload:
        result["showcase"] = validate_showcase(payload["showcase"])
    return result


def build_config(
    *,
    host: str,
    account: str,
    push_repository: str,
    pull_request_repository: str,
    push_remote: str,
) -> dict[str, object]:
    """Assemble and validate a config document from confirmed setup values."""
    raw = {
        "version": SUPPORTED_VERSION,
        "github": {
            "host": host,
            "account": account,
            "pushRepository": push_repository,
            "pullRequestRepository": pull_request_repository,
            "pushRemote": push_remote,
        },
    }
    return parse_config(json.dumps(raw))


def _run(command: list[str], *, cwd: Path) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=COMMAND_TIMEOUT,
            env={**os.environ, "LC_ALL": "C"},
        )
    except OSError as exc:
        return (-1, str(exc))
    except subprocess.SubprocessError as exc:
        return (124, str(exc))
    return completed.returncode, completed.stdout.strip()


def find_git_root(start: Path) -> Path | None:
    """Return the worktree root for *start*, or None outside any Git worktree."""
    status, output = _run(["git", "rev-parse", "--show-toplevel"], cwd=start)
    if status == 0 and output:
        return Path(output)
    # Only Git's explicit outside-worktree result permits pre-Git setup.
    # A broken checkout marker or any other failure leaves provenance unknown.
    outside = "fatal: not a git repository (or any of the parent directories): .git"
    start = start.resolve()
    if status == 128 and output == outside and not any(
        (parent / ".git").exists() or (parent / ".git").is_symlink()
        for parent in (start, *start.parents)
    ):
        return None
    raise ConfigError("git_provenance_unavailable", "cannot establish the Git worktree root")


def is_tracked(repo_root: Path, relative_path: str) -> bool:
    """Return True if *relative_path* is tracked in the Git index."""
    status, _ = _run(["git", "ls-files", "--error-unmatch", relative_path], cwd=repo_root)
    if status not in (0, 1):
        raise ConfigError("git_provenance_unavailable", "cannot establish whether the config is tracked")
    return status == 0


def is_ignored(repo_root: Path, relative_path: str) -> bool:
    """Return True if Git's own exclude resolution would ignore *relative_path*."""
    status, _ = _run(["git", "check-ignore", "-q", relative_path], cwd=repo_root)
    if status not in (0, 1):
        raise ConfigError("git_provenance_unavailable", "cannot establish whether the config is ignored")
    return status == 0


def ensure_excluded(repo_root: Path, relative_path: str = CONFIG_FILENAME) -> bool:
    """Add *relative_path* to the repository-local exclude file if not already ignored.

    Uses `git rev-parse --git-path info/exclude` rather than a hand-built path,
    so a linked worktree resolves to the same shared exclude file Git itself
    would consult -- never the worktree's private git-dir. Never touches global
    ignore/auth configuration. Returns whether the path is ignored afterward.
    """
    if is_ignored(repo_root, relative_path):
        return True

    status, output = _run(["git", "rev-parse", "--git-path", "info/exclude"], cwd=repo_root)
    if status != 0 or not output:
        return False
    exclude_path = Path(output)
    if not exclude_path.is_absolute():
        exclude_path = (repo_root / exclude_path).resolve()

    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude_path.read_text(encoding="utf-8") if exclude_path.exists() else ""
    existing_lines = {line.strip() for line in existing.splitlines()}
    if relative_path not in existing_lines:
        with exclude_path.open("a", encoding="utf-8") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            handle.write(f"{relative_path}\n")

    return is_ignored(repo_root, relative_path)


def create_config(path: Path, data: dict[str, object]) -> None:
    """Atomically create *path* with *data*. Never overwrites an existing file.

    Uses O_CREAT|O_EXCL directly on the destination rather than a
    write-then-rename, so there is no window in which a concurrent setup
    process's file could be silently replaced.
    """
    text = json.dumps(data, indent=2, sort_keys=False) + "\n"
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError as exc:
        raise ConfigError(
            "already_exists", f"{path} already exists; refusing to overwrite"
        ) from exc
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)


def write_config_atomically(path: Path, data: dict[str, object]) -> None:
    """Atomically replace *path* with the already-validated *data* document.

    Unlike `create_config` (which refuses to overwrite), this writes to a
    temporary file in the same directory and `os.replace`s it into place, so a
    crash or a concurrent reader never observes a truncated file. The caller
    must already have validated *data* with `parse_config`.
    """
    text = json.dumps(data, indent=2, sort_keys=False) + "\n"
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=".dev.json.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def nonsecret_summary(config: dict[str, object]) -> dict[str, object]:
    """Everything in a valid config is already nonsecret; this exists so callers
    have one explicit place to project fields for a ledger/report, rather than
    each caller deciding independently which fields are safe to echo."""
    return json.loads(json.dumps(config))


def resolve_status(config_path: Path) -> dict[str, object]:
    """Return config status, failing closed when Git provenance is unavailable."""
    try:
        return _resolve_status(config_path)
    except ConfigError as exc:
        return {"status": "incomplete", "path": str(config_path), "config": None,
                "reason_code": exc.code, "reason": str(exc)}


def _resolve_status(config_path: Path) -> dict[str, object]:
    """Resolve the config's current status without assuming Git exists yet.

    Returns one of:
      - `missing`: no file at *config_path*
      - `tracked`: the repository tracks `.dev.json` in its index; a
        repository-supplied file must never be trusted as user-confirmed
        intent without an explicit decision
      - `invalid`: a file exists but fails schema validation; it is reported,
        never rewritten or discarded
      - `not_ignored`: the file is valid and untracked, but Git would not
        currently ignore it (caller should run `ensure_excluded` before
        trusting/staging)
      - `valid`: untracked, ignored (or no Git yet), and schema-valid
    """
    result: dict[str, object] = {
        "status": "missing",
        "path": str(config_path),
        "reason_code": "",
        "reason": "",
        "config": None,
    }

    git_root = find_git_root(config_path.parent)
    relative_path = config_path.name if git_root is None else str(
        config_path.resolve().relative_to(git_root.resolve())
    )

    if git_root is not None and is_tracked(git_root, relative_path):
        result["status"] = "tracked"
        result["reason_code"] = "tracked_config"
        result["reason"] = (
            f"{relative_path} is tracked in the Git index; a repository-supplied "
            "file cannot be trusted as user-confirmed intent without an explicit decision"
        )
        return result

    if not config_path.exists():
        result["reason_code"] = "missing_config"
        result["reason"] = f"no config file at {config_path}"
        return result

    try:
        raw_text = config_path.read_text(encoding="utf-8")
        parsed = parse_config(raw_text)
    except ConfigError as exc:
        result["status"] = "invalid"
        result["reason_code"] = exc.code
        result["reason"] = str(exc)
        return result
    except OSError as exc:
        result["status"] = "invalid"
        result["reason_code"] = "unreadable_config"
        result["reason"] = str(exc)
        return result

    if git_root is not None and not is_ignored(git_root, relative_path):
        result["status"] = "not_ignored"
        result["reason_code"] = "not_ignored"
        result["reason"] = (
            f"{relative_path} is valid and untracked, but not yet covered by the "
            "repository-local exclude file"
        )
        result["config"] = nonsecret_summary(parsed)
        return result

    result["status"] = "valid"
    result["reason_code"] = "config_ready"
    result["reason"] = f"{relative_path} is a valid, untracked, ignored config"
    result["config"] = nonsecret_summary(parsed)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    status_cmd = sub.add_parser("status", help="report the current config's status")
    status_cmd.add_argument("--path", type=Path, default=None, help=f"defaults to <repo-root or cwd>/{CONFIG_FILENAME}")

    validate_cmd = sub.add_parser("validate", help="validate a config file without Git provenance checks")
    validate_cmd.add_argument("path", type=Path)

    exclude_cmd = sub.add_parser("exclude", help="exclude an existing valid, untracked config without rewriting it")
    exclude_cmd.add_argument("--path", type=Path, default=None)

    create_cmd = sub.add_parser("create", help="atomically create a new config from confirmed setup values")
    create_cmd.add_argument("--path", type=Path, default=None, help=f"defaults to <repo-root or cwd>/{CONFIG_FILENAME}")
    create_cmd.add_argument("--host", default="github.com")
    create_cmd.add_argument("--account", required=True)
    create_cmd.add_argument("--push-repository", required=True)
    create_cmd.add_argument("--pull-request-repository", required=True)
    create_cmd.add_argument("--push-remote", default="origin")
    create_cmd.add_argument(
        "--no-exclude",
        action="store_true",
        help="skip adding the config to the repository-local exclude file",
    )

    return parser.parse_args()


def _default_path() -> Path:
    cwd = Path.cwd()
    git_root = find_git_root(cwd)
    return (git_root or cwd) / CONFIG_FILENAME


def main() -> int:
    try:
        return _main()
    except ConfigError as exc:
        print(json.dumps({"status": "incomplete", "reason_code": exc.code, "reason": str(exc)}))
        return 2
    except OSError:
        print(json.dumps({"status": "incomplete", "reason_code": "config_io_error", "reason": "could not read or write local config/exclusion"}))
        return 2


def _main() -> int:
    args = parse_args()

    if args.command == "validate":
        try:
            parsed = parse_config(args.path.read_text(encoding="utf-8"))
        except ConfigError as exc:
            print(json.dumps({"status": "invalid", "reason_code": exc.code, "reason": str(exc)}))
            return 2
        except OSError as exc:
            print(json.dumps({"status": "invalid", "reason_code": "unreadable_config", "reason": str(exc)}))
            return 2
        print(json.dumps({"status": "valid", "config": nonsecret_summary(parsed)}, sort_keys=True))
        return 0

    if args.command == "status":
        path = args.path or _default_path()
        result = resolve_status(path)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "valid" else 2

    if args.command == "exclude":
        path = args.path or _default_path()
        result = resolve_status(path)
        if result["status"] == "not_ignored":
            git_root = find_git_root(path.parent)
            if git_root is None or not ensure_excluded(git_root, str(path.resolve().relative_to(git_root.resolve()))):
                result.update(status="incomplete", reason_code="not_ignored", reason="config exclusion was not established")
            else:
                result = resolve_status(path)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "valid" else 2

    if args.command == "create":
        path = args.path or _default_path()
        try:
            config = build_config(
                host=args.host,
                account=args.account,
                push_repository=args.push_repository,
                pull_request_repository=args.pull_request_repository,
                push_remote=args.push_remote,
            )
        except ConfigError as exc:
            print(json.dumps({"status": "invalid", "reason_code": exc.code, "reason": str(exc)}))
            return 2

        git_root = find_git_root(path.parent)
        if git_root is not None:
            relative_path = str(path.resolve().relative_to(git_root.resolve()))
            if is_tracked(git_root, relative_path):
                print(json.dumps({
                    "status": "incomplete",
                    "reason_code": "tracked_config",
                    "reason": f"{relative_path} is already tracked in the Git index",
                }))
                return 2

        try:
            create_config(path, config)
        except ConfigError as exc:
            print(json.dumps({"status": "incomplete", "reason_code": exc.code, "reason": str(exc)}))
            return 2

        ignored = True
        if git_root is not None:
            relative_path = str(path.resolve().relative_to(git_root.resolve()))
            ignored = is_ignored(git_root, relative_path) if args.no_exclude else ensure_excluded(git_root, relative_path)

        print(json.dumps({
            "status": "created" if ignored else "incomplete",
            "reason_code": "config_created" if ignored else "not_ignored",
            "path": str(path),
            "ignored": ignored,
            "config": nonsecret_summary(config),
        }, sort_keys=True))
        return 0 if ignored else 2

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
