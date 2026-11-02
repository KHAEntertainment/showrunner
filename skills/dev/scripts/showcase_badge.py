#!/usr/bin/env python3
"""Opt-in "Built with Showrunner" badge: decide, build, and register.

Phase 5 calls this script, never hand-rolls the badge URL or the decision. The
README on the default branch is the source of truth for "is the badge there";
`.dev.json` (in the primary checkout, never a lane worktree copy) only remembers
a *no*, a public "yes" while the docs PR is open, or a private-registration
outcome, so the user is asked at most once.

Decision logic is a pure function (`decide`) so it is unit-testable without any
network or `gh`. Registration uses `urllib` in-process against the fixed host
`svg.khaentertainment.com` over HTTPS, sends the token as an `Authorization:
Bearer` header (never in the URL), never follows a redirect, and never lets the
token reach stdout, stderr, an exception, the ledger, or `.dev.json`.

For a private repo, the repository name is sent once over HTTPS to the badge
host, which stores only a keyed hash of it (never the name itself) and returns
an id; the name is never written into the README (`?project=` is never emitted
for a private or undetermined repo).

The token is read only from the `SHOWRUNNER_REGISTER_TOKEN` environment
variable. If it is absent, the private path stays off.

The primary `.dev.json` must be a local, untracked file before any showcase
state is read from it or written to it, and the configured remote's fetch URL
must resolve to `github.pushRepository` before anything is fetched.
"""

from __future__ import annotations

import argparse
import datetime
import http.client
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dev_config  # noqa: E402  (same-directory schema/persistence module)
import resolve_repository  # noqa: E402  (read-only remote-identity helpers)


HOST = "svg.khaentertainment.com"
BADGE_IMAGE_PATH = "/badge.svg"
GO_PATH = "/go"
REGISTER_PATH = "/register"
BADGE_QUERY = "theme=midnight&anim=orbit"
HOST_MARKER = "svg.khaentertainment.com"
TOKEN_ENV = "SHOWRUNNER_REGISTER_TOKEN"
GIT_TIMEOUT = 15
GIT_FETCH_TIMEOUT = 60
READ_LIMIT = 4096
PRIVATE_ID_PATTERN = re.compile(r"[0-9a-f]{8,128}\Z")

# Exact, supported README filenames, in selection priority. A root entry that
# is not one of these (e.g. `README-assets/`, `README.en.md`) is never chosen,
# and only a blob (not a symlink or a submodule) qualifies.
README_NAMES = ("README.md", "README.rst", "README.txt", "README")

PROMPT_PUBLIC = (
    'Add a "Built with Showrunner" badge to this README? It is a single animated '
    "badge that links back to Showrunner. If you add it and later change your "
    "mind, removing it is just deleting the one line. (Answer yes to add it, or "
    "no to leave it out.)"
)

PROMPT_PRIVATE = (
    "This repository is private. Showrunner can register the project in its adoption "
    "count. The repository name is sent once over HTTPS to the badge host, which "
    "stores only a keyed hash of it, does not store or log the name, and returns an "
    "id; nothing else sends it, and `?project=` is never written into the README. "
    "Register it? (If you also want the badge shown in the README, a `?p=` badge "
    "keeps the name hidden there too.) Answer: register / register+show / no."
)

DETAILS = {
    "readme_skill_missing": "the Showrunner README skill is not installed, so there is no badge slot",
    "declined": "the badge was declined or removed; it will not be offered again",
    "idempotent": "the README already contains a Showrunner badge",
    "token_missing": "SHOWRUNNER_REGISTER_TOKEN is not set, so private registration is off",
    "already_registered": "this private project is already registered",
    "fail_closed": "the repository state is uncertain, so no badge, prompt, or network call",
    "provenance_unavailable": "the primary .dev.json is tracked, invalid, or its provenance is unknown",
    "fetch_identity_mismatch": "the configured fetch remote does not resolve to pushRepository",
    "no_readme": "no README on the default branch (or the fetch failed)",
    "landed": "the badge is present on the default branch; recorded badge: true",
    "default_on": "the badge is included and removing it is deleting the one line",
    "unsupported_visibility": "public repositories are not registered; nothing was written",
}


class RegistrationError(RuntimeError):
    """A registration failure with a fixed, non-leaking message."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RegistrationError("registration failed (redirect refused)")


def _today() -> str:
    return datetime.date.today().isoformat()


def build_block(slug: str, private_id: str | None = None) -> str:
    """Return the Markdown badge row for *slug*, or the `?p=` form when *private_id*.

    A private badge embeds `?p=<id>` on both the image and the link so the repo
    name is not recoverable from a click's referrer; a public badge embeds
    `?project=<slug>` on the image only and links `/go`.
    """
    if private_id is not None:
        image = f"https://{HOST}{BADGE_IMAGE_PATH}?{BADGE_QUERY}&p={private_id}"
        link = f"https://{HOST}{GO_PATH}?p={private_id}"
    else:
        encoded = urllib.parse.quote(slug, safe="/")
        image = f"https://{HOST}{BADGE_IMAGE_PATH}?{BADGE_QUERY}&project={encoded}"
        link = f"https://{HOST}{GO_PATH}"
    return f"[![Built with Showrunner]({image})]({link})"


def validate_id(value: str) -> bool:
    """A registration `id` is a lowercase hex hash of sane length."""
    return bool(PRIVATE_ID_PATTERN.fullmatch(value))


def _build_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_NoRedirect())


def register(token: str, slug: str, *, opener=None, timeout: float = 10.0) -> str:
    """Register a private project and return the validated id, or raise.

    The token travels only as an `Authorization: Bearer` header; it never appears
    in the request URL. Any transport failure raises `RegistrationError` with a
    fixed message that carries neither the token nor the URL (`HTTPError` and
    `URLError` text both embed the URL, so they are discarded).
    """
    if opener is None:
        opener = _build_opener()
    encoded_slug = urllib.parse.quote(slug, safe="/")
    url = f"https://{HOST}{REGISTER_PATH}?private=1&project={encoded_slug}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "showrunner-dev-skill",
            "Authorization": f"Bearer {token}",
        },
    )

    response = None
    try:
        response = opener.open(request, timeout=timeout)
        body = response.read(READ_LIMIT)
    except RegistrationError:
        raise
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        OSError,
        http.client.HTTPException,
        ValueError,
    ):
        raise RegistrationError("registration failed (network error)") from None
    finally:
        if response is not None:
            try:
                response.close()
            except OSError:
                pass

    text = body.decode("utf-8", "replace").strip()
    candidate: object = None
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            candidate = payload.get("id")
    except ValueError:
        candidate = None
    if candidate is None:
        candidate = text if validate_id(text) else None
    if not isinstance(candidate, str) or not validate_id(candidate):
        raise RegistrationError("registration response was not a valid id")
    return candidate


def _git(
    args: list[str], cwd: Path, timeout: int = GIT_TIMEOUT
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", "-C", str(cwd), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError):
        return None


def primary_checkout_root(start: Path) -> Path | None:
    """The main checkout root for the worktree *start*, or None (fail closed)."""
    bare = _git(["rev-parse", "--is-bare-repository"], start)
    if bare is None or bare.returncode != 0 or bare.stdout.strip() == "true":
        return None
    common = _git(["rev-parse", "--git-common-dir"], start)
    if common is None or common.returncode != 0:
        return None
    common_path = common.stdout.strip()
    if not common_path:
        return None
    resolved = Path(common_path)
    if not resolved.is_absolute():
        resolved = (start / resolved).resolve()
    else:
        resolved = resolved.resolve()
    root = resolved.parent
    if not (root / ".git").exists():
        return None
    return root


def _readme_blob_name_from_ls_tree(output: str) -> str | None:
    """The supported README name from `ls-tree` output, in priority order, or None.

    Matched case-insensitively against the canonical names, returning the actual
    tracked path (e.g. `readme.md`). Only a blob at the tree root qualifies; a
    directory like `README-assets/`, a symlink, or a non-supported name like
    `README.en.md` is skipped.
    """
    by_name: dict[str, tuple[str, str]] = {}
    for line in output.splitlines():
        meta, _, name = line.partition("\t")
        parts = meta.split()
        if len(parts) >= 2 and name:
            by_name[name] = (parts[0], parts[1])
    lowered = {name.lower(): name for name in by_name}
    for candidate in README_NAMES:
        actual = lowered.get(candidate.lower())
        if actual is None:
            continue
        mode, typ = by_name[actual]
        if typ == "blob" and mode.startswith("100"):
            return actual
    return None


def readme_path_at_ref(root: Path, ref: str) -> str | None:
    """The root README blob path at *ref* by exact supported name, or None."""
    listing = _git(["ls-tree", ref], root)
    if listing is None or listing.returncode != 0:
        return None
    return _readme_blob_name_from_ls_tree(listing.stdout)


def readme_present_at_commit(root: Path, oid: str) -> bool | None:
    """Whether a supported root README blob exists at *oid*. None on error."""
    if not oid:
        return None
    listing = _git(["ls-tree", oid], root)
    if listing is None or listing.returncode != 0:
        return None
    return _readme_blob_name_from_ls_tree(listing.stdout) is not None


def readme_content_at_ref(root: Path, ref: str) -> str | None:
    """The root README blob content at *ref*, or None if absent/unreadable."""
    readme_path = readme_path_at_ref(root, ref)
    if readme_path is None:
        return None
    shown = _git(["show", f"{ref}:{readme_path}"], root)
    if shown is None or shown.returncode != 0:
        return None
    return shown.stdout


def live_default_branch(root: Path, remote: str) -> str | None:
    """The remote's default branch name via `ls-remote --symref`, or None.

    Reads the *live* remote HEAD rather than a possibly-stale cached
    `refs/remotes/<remote>/HEAD`.
    """
    probe = _git(
        ["ls-remote", "--symref", remote, "HEAD"], root, timeout=GIT_FETCH_TIMEOUT
    )
    if probe is None or probe.returncode != 0:
        return None
    for line in probe.stdout.splitlines():
        if line.startswith("ref: "):
            target, _, name = line[len("ref: "):].partition("\t")
            if name == "HEAD" and target.startswith("refs/heads/"):
                branch = target[len("refs/heads/"):]
                if branch:
                    return branch
    return None


def readme_now(root: Path, remote: str) -> str | None:
    """The README on the fetched default branch, or None on any failure.

    The default branch is resolved live with `ls-remote --symref`, fetched
    explicitly, and read from the just-fetched remote-tracking ref -- never from
    a stale cached ref. A failed fetch (nonzero exit) returns None, so the
    caller reports NO_OP with no write.
    """
    branch = live_default_branch(root, remote)
    if branch is None:
        return None
    ref = f"refs/remotes/{remote}/{branch}"
    fetched = _git(
        ["fetch", remote, f"refs/heads/{branch}:{ref}"],
        root,
        timeout=GIT_FETCH_TIMEOUT,
    )
    if fetched is None or fetched.returncode != 0:
        return None
    return readme_content_at_ref(root, ref)


def normalize_visibility(value: str | None) -> str:
    if value in ("public", "private"):
        return value
    return "undetermined"


def readme_skill_present(readme_skill_dir: Path | None) -> bool:
    if readme_skill_dir is None:
        readme_skill_dir = Path(__file__).resolve().parent.parent.parent / "readme"
    return (Path(readme_skill_dir) / "SKILL.md").is_file()


def decide(
    *,
    readme_skill_present: bool,
    showcase: dict | None,
    host_present: bool,
    visibility: str,
    token_present: bool,
    greenfield: bool,
    slug: str,
) -> dict:
    """The full decision table. Order matters; see the phase text and tests.

    Precedence: readme-skill missing, recorded decline, hand removal, idempotent
    host match, public `badgeApproved` resume, private registered-but-not-yet-
    displayed, pending-registration retry, already-registered, then the
    visibility branches. The private `privateId` row (registered but no badge
    wanted) never collides with hand removal, which only fires on `badge is True`.
    """
    result: dict = {
        "visibility": visibility,
        "host_present": host_present,
        "greenfield": greenfield,
    }

    if not readme_skill_present:
        result.update(
            action="noop", reason="readme_skill_missing", detail=DETAILS["readme_skill_missing"]
        )
        return result

    state = showcase or {}
    badge = state.get("badge")
    register_approved = state.get("registerApproved", False)
    registered = state.get("registered", False)
    private_id = state.get("privateId")
    show_badge = state.get("showBadge", False)
    badge_approved = state.get("badgeApproved", False)

    if badge is False and not register_approved:
        result.update(action="noop", reason="declined", detail=DETAILS["declined"])
        return result

    if badge is True and not host_present:
        result.update(action="hand_removal", record={"badge": False, "decidedAt": _today()})
        return result

    if host_present:
        result.update(action="noop", reason="idempotent", detail=DETAILS["idempotent"])
        return result

    if badge_approved and visibility == "public":
        result.update(action="resume", block=build_block(slug), unplaced=True)
        return result

    if private_id is not None and badge is not True:
        if show_badge:
            if not token_present:
                result.update(action="noop", reason="token_missing", detail=DETAILS["token_missing"])
                return result
            result.update(
                action="registered_not_displayed",
                block=build_block(slug, private_id),
                unplaced=True,
            )
            return result
        result.update(action="noop", reason="already_registered", detail=DETAILS["already_registered"])
        return result

    if register_approved and not registered and private_id is None:
        if visibility != "public" and token_present:
            result.update(action="retry_register")
            return result
        if not token_present:
            result.update(action="noop", reason="token_missing", detail=DETAILS["token_missing"])
            return result
        result.update(action="noop", reason="fail_closed", detail=DETAILS["fail_closed"])
        return result

    if visibility != "public":
        if not token_present:
            result.update(action="noop", reason="token_missing", detail=DETAILS["token_missing"])
            return result
        result.update(action="prompt_private", prompt=PROMPT_PRIVATE)
        return result

    if greenfield:
        result.update(
            action="default_on",
            consent="granted",
            block=build_block(slug),
            detail=DETAILS["default_on"],
        )
        return result

    result.update(
        action="prompt_public", prompt=PROMPT_PUBLIC, block=build_block(slug), unplaced=True
    )
    return result


def load_lane_config(repo_dir: Path) -> dict | None:
    path = repo_dir / dev_config.CONFIG_FILENAME
    if not path.exists():
        return None
    try:
        return dev_config.parse_config(path.read_text(encoding="utf-8"))
    except (dev_config.ConfigError, OSError):
        return None


def _read_config(path: Path) -> dict | None:
    """Parsed config, or None when absent. Raises on an invalid file."""
    if not path.exists():
        return None
    return dev_config.parse_config(path.read_text(encoding="utf-8"))


def primary_showcase(primary_root: Path) -> tuple[bool, dict]:
    """`(ok, showcase)` for the primary checkout's `.dev.json`.

    `ok` is False when the primary config is tracked, invalid, or its Git
    provenance is unknown -- the caller must then NO_OP with no write and no
    network. A valid-but-not-yet-ignored config is accepted only after
    `ensure_excluded` succeeds. `showcase` is the parsed `showcase` block (empty
    when missing).
    """
    path = primary_root / dev_config.CONFIG_FILENAME
    try:
        status = dev_config.resolve_status(path)
    except dev_config.ConfigError:
        return False, {}
    st = status["status"]
    if st == "missing":
        return True, {}
    if st == "not_ignored":
        if not dev_config.ensure_excluded(primary_root):
            return False, {}
        status = dev_config.resolve_status(path)
        st = status["status"]
    if st == "valid":
        config = status.get("config") or {}
        return True, config.get("showcase") or {}
    return False, {}


def fetch_identity_matches(root: Path, remote: str, push_repository: str) -> bool:
    """Whether the configured remote's fetch URL resolves to *push_repository*.

    `origin` can fetch upstream while pushing to a fork even when the config's
    `pushRepository` and `pullRequestRepository` agree, so the fetch URL -- the
    source the badge README is read from -- must match the configured project.
    A missing, unparseable, or mismatched fetch URL is a mismatch.
    """
    completed = _git(["remote", "get-url", "--all", remote], root)
    if completed is None or completed.returncode != 0:
        return False
    urls = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not urls:
        return False
    try:
        identity = resolve_repository.normalize_remote(urls[0])
    except resolve_repository.RepositoryError:
        return False
    return resolve_repository.same_repository(identity, push_repository)


def _print(payload: dict) -> None:
    print(json.dumps(payload, sort_keys=True))


def _fork_shape(lane: dict) -> bool:
    return lane["github"]["pushRepository"] != lane["github"]["pullRequestRepository"]


def write_showcase(primary_root: Path, lane_config: dict, showcase_block: dict) -> None:
    """Merge *showcase_block* into the primary checkout's `.dev.json`.

    Creates the primary file from the lane's validated config when it does not
    yet exist, publishing the first version through a complete temp file with
    no-overwrite semantics (preserving its `github` content and the exclude
    behavior), then re-validates and atomically replaces it on later writes.
    Raises on any validation failure.
    """
    config_path = primary_root / dev_config.CONFIG_FILENAME
    existing = _read_config(config_path)
    if existing is None:
        if not dev_config.ensure_excluded(primary_root):
            raise dev_config.ConfigError(
                "git_provenance_unavailable",
                "could not exclude .dev.json before creating it",
            )
        merged = dict(lane_config)
        merged["showcase"] = showcase_block
        validated = dev_config.parse_config(json.dumps(merged))
        try:
            dev_config.create_config_atomic(config_path, validated)
            return
        except dev_config.ConfigError as exc:
            if exc.code != "already_exists":
                raise
            existing = _read_config(config_path)
            if existing is None:
                raise

    merged = dict(existing)
    merged["showcase"] = showcase_block
    dev_config.write_config_atomically(
        config_path, dev_config.parse_config(json.dumps(merged))
    )


def decide_cmd(args: argparse.Namespace) -> int:
    repo_dir = Path(args.repo_dir).resolve()
    lane = load_lane_config(repo_dir)
    if lane is None:
        _print({"action": "noop", "reason": "fail_closed", "detail": "no valid .dev.json"})
        return 0

    if _fork_shape(lane):
        _print({"action": "noop", "reason": "fork_shape", "detail": "fork-shaped repositories are not supported in v2.1.4"})
        return 0

    slug = lane["github"]["pushRepository"]
    visibility = normalize_visibility(args.visibility)
    skill_present = readme_skill_present(args.readme_skill_dir)

    primary = primary_checkout_root(repo_dir)
    if primary is None:
        _print({"action": "noop", "reason": "fail_closed", "detail": "cannot resolve primary checkout"})
        return 0

    ok, showcase = primary_showcase(primary)
    if not ok:
        _print({"action": "noop", "reason": "fail_closed", "detail": DETAILS["provenance_unavailable"]})
        return 0

    remote = lane["github"]["pushRemote"]
    if not fetch_identity_matches(primary, remote, slug):
        _print({"action": "noop", "reason": "fail_closed", "detail": DETAILS["fetch_identity_mismatch"]})
        return 0

    token_present = bool(os.environ.get(TOKEN_ENV))

    readme_text = readme_now(primary, remote)
    if readme_text is None:
        _print({"action": "noop", "reason": "no_readme", "detail": DETAILS["no_readme"]})
        return 0

    host_present = HOST_MARKER in readme_text

    present_at_base = readme_present_at_commit(primary, args.base) if args.base else None
    greenfield = present_at_base is False

    if host_present and showcase.get("badge") is not True:
        landed_block = {
            **showcase,
            "badge": True,
            "badgeApproved": False,
            "showBadge": False,
            "decidedAt": _today(),
        }
        write_showcase(primary, lane, landed_block)
        _print({"action": "noop", "reason": "landed", "detail": DETAILS["landed"]})
        return 0

    decision = decide(
        readme_skill_present=skill_present,
        showcase=showcase,
        host_present=host_present,
        visibility=visibility,
        token_present=token_present,
        greenfield=greenfield,
        slug=slug,
    )
    _print(decision)
    return 0


def apply_cmd(args: argparse.Namespace) -> int:
    repo_dir = Path(args.repo_dir).resolve()
    lane = load_lane_config(repo_dir)
    if lane is None:
        _print({"status": "noop", "reason": "fail_closed", "detail": "no valid .dev.json"})
        return 0

    if _fork_shape(lane):
        _print({"status": "noop", "reason": "fork_shape", "detail": "fork-shaped repositories are not supported in v2.1.4"})
        return 0

    if args.consent == "register" and normalize_visibility(args.visibility) == "public":
        _print({"status": "noop", "reason": "unsupported_visibility", "detail": DETAILS["unsupported_visibility"]})
        return 0

    primary = primary_checkout_root(repo_dir)
    if primary is None:
        _print({"status": "noop", "reason": "fail_closed", "detail": "cannot resolve primary checkout"})
        return 0

    ok, existing_showcase = primary_showcase(primary)
    if not ok:
        _print({"status": "noop", "reason": "fail_closed", "detail": DETAILS["provenance_unavailable"]})
        return 0

    slug = lane["github"]["pushRepository"]
    remote = lane["github"]["pushRemote"]
    if not fetch_identity_matches(primary, remote, slug):
        _print({"status": "noop", "reason": "fail_closed", "detail": DETAILS["fetch_identity_mismatch"]})
        return 0

    if args.consent == "decline":
        block = {
            **existing_showcase,
            "badge": False,
            "registerApproved": False,
            "showBadge": False,
            "badgeApproved": False,
            "decidedAt": _today(),
        }
        write_showcase(primary, lane, block)
        _print({"status": "declined"})
        return 0

    if args.consent == "landed":
        block = {
            **existing_showcase,
            "badge": True,
            "showBadge": False,
            "badgeApproved": False,
            "decidedAt": _today(),
        }
        write_showcase(primary, lane, block)
        _print({"status": "landed"})
        return 0

    if args.consent == "approve":
        block = {**existing_showcase, "badgeApproved": True, "decidedAt": _today()}
        write_showcase(primary, lane, block)
        _print({"status": "approved"})
        return 0

    # register
    token = os.environ.get(TOKEN_ENV)
    if not token:
        _print({"status": "noop", "reason": "token_missing", "detail": DETAILS["token_missing"]})
        return 0

    show_badge = bool(args.visible) or bool(existing_showcase.get("showBadge"))

    if existing_showcase.get("privateId"):
        out = {"status": "registered", "registered": True, "already": True}
        if show_badge:
            out["block"] = build_block(slug, existing_showcase["privateId"])
        _print(out)
        return 0

    consent_block = {
        **existing_showcase,
        "registerApproved": True,
        "showBadge": show_badge,
        "decidedAt": _today(),
    }
    write_showcase(primary, lane, consent_block)

    try:
        private_id = register(token, slug)
    except RegistrationError:
        _print({"status": "registered_pending", "registered": False})
        return 0

    primary_config = _read_config(primary / dev_config.CONFIG_FILENAME) or {}
    landed_showcase = {
        **(primary_config.get("showcase") or {}),
        "registered": True,
        "privateId": private_id,
    }
    write_showcase(primary, lane, landed_showcase)

    out: dict = {"status": "registered", "registered": True}
    if show_badge:
        out["block"] = build_block(slug, private_id)
    _print(out)
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    decide_p = sub.add_parser("decide", help="compute the showcase action")
    decide_p.add_argument("--repo-dir", required=True, type=Path)
    decide_p.add_argument("--base", default=None, help="earliest lane base_oid for the iteration")
    decide_p.add_argument("--visibility", default=None, help="public or private; anything else is undetermined")
    decide_p.add_argument("--readme-skill-dir", default=None, type=Path)

    apply_p = sub.add_parser("apply", help="record a decision / register a private project")
    apply_p.add_argument("--repo-dir", required=True, type=Path)
    apply_p.add_argument("--consent", choices=["decline", "register", "landed", "approve"], required=True)
    apply_p.add_argument("--visible", action="store_true", help="also show the badge in a private repo")
    apply_p.add_argument("--visibility", default=None, help="public or private; public blocks registration")

    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        if args.command == "decide":
            return decide_cmd(args)
        return apply_cmd(args)
    except dev_config.ConfigError as exc:
        _print({"status": "noop", "reason": exc.code, "detail": str(exc)})
        return 2
    except OSError:
        _print({"status": "noop", "reason": "io_error", "detail": "could not read or write local config"})
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
