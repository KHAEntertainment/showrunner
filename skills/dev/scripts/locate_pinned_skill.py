#!/usr/bin/env python3
"""Locate a pinned third-party skill and report whether it still matches its pin.

This locator answers exactly one question: *is the pinned skill available on
this machine, and does the copy on disk still match the pin?* It is read-only
by construction. It never installs, fetches, clones, updates, or writes to
anything: it reads candidate directories, computes digests, and prints one
JSON object on stdout. The candidate roots are supplied by the caller, so the
real harness directories and plugin caches are searched only when the caller
names them -- no path is baked in here.

Usage:
    locate_pinned_skill.py --skill NAME --commit COMMIT --digest SHA256 \
        --root DIR [--root DIR ...]

``--root`` may be repeated; every root is searched for directories named
after the skill. A plugin cache that holds several versions of the same
plugin yields several candidates, and the one whose digest matches the pin
wins.

Output (one JSON object on stdout):

* ``status`` is ``present``, ``not_available`` or ``drift``.
* On ``present``: ``path`` (the matching directory) and ``digest`` (the
  directory digest that was computed).
* On ``not_available`` / ``drift``: a ``cause``, and never a "success" that a
  caller could mistake for a completed step.
* ``candidates`` lists every directory that was examined, with its digest.
* ``pin_commit`` echoes the ``--commit`` value that was passed in. The commit
  is recorded, not verified: only the digest is checked, because the digest
  of the whole directory is what the pin is actually compared against. A
  caller that needs the commit itself proven must check it against the
  directory it was handed.

Causes:

* ``no_candidate_found`` -- no directory named after the skill was found in
  any root.
* ``digest_mismatch`` -- one candidate was found and its digest differs from
  the pin.
* ``multiple_versions_none_match`` -- several candidates were found (a plugin
  cache with more than one version) and none of them matched the pin.

The ``not_available`` / ``drift`` vocabulary and the mandatory ``cause`` are
the provider-result vocabulary of contract SC-5 as revised by PR #209: an
absent or drifted provider is never reported as a completed research step.

Exit codes:
    0  present -- a candidate matched the pinned digest.
    2  not_available or drift -- the pin could not be satisfied.
    1  usage error (bad arguments), or a candidate tree could not be read.

Directory digest
----------------
The digest of a skill directory is the SHA-256 (hex) of a canonical byte
stream built from every regular file in the tree:

* VCS directories (``.git``, ``.hg``, ``.svn``) are excluded.
* Symlinks -- files and directories alike -- are excluded, so the digest
  never depends on anything outside the directory it was given and never
  follows a cycle.
* Non-regular files (sockets, FIFOs, devices) are excluded.
* Empty directories carry no information and are excluded.
* Every surviving file contributes exactly one record::

      b"F\\0" + relative_path_utf8 + b"\\0" + size_ascii + b"\\0" + bytes + b"\\0"

  where ``relative_path_utf8`` is the file's POSIX-style path relative to
  the directory root (no leading ``./``), encoded as UTF-8, and ``size_ascii``
  is the file's byte length in ASCII.
* Records are concatenated in ascending order of the UTF-8 encoded relative
  path, compared byte by byte (never locale-dependent).
* The directory digest is the SHA-256 hex of that concatenated stream.

The path and the size are framed inside every record, so two different trees
cannot produce the same stream, and a single changed byte in a single file
changes the digest. A pinned digest therefore covers the whole skill
directory -- sibling reference files drift with it, which is the point.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

VCS_DIR_NAMES = frozenset({".git", ".hg", ".svn"})

# How deep below a root a candidate may sit. A plugin cache nests as
# <marketplace>/<plugin>/<version>/skills/<skill>, so the depth has to
# cover the versioned layout without turning the search into a full disk
# walk.
MAX_SEARCH_DEPTH = 8

EXIT_PRESENT = 0
EXIT_USAGE = 1
EXIT_ABSENT = 2

DIGEST_PREFIX = "sha256:"
_DIGEST_HEX_LENGTH = 64


class LocatorError(Exception):
    """A candidate tree could not be read, so no verdict can be produced."""


def normalize_digest(value: str) -> str:
    """Return the bare lowercase hex of a SHA-256 digest.

    Accepts ``<hex>`` and ``sha256:<hex>``; rejects anything else so a
    malformed pin is a usage error rather than a silent mismatch.
    """
    if not isinstance(value, str):
        raise ValueError(f"digest must be a string, got {type(value).__name__}")
    text = value.strip()
    if text.lower().startswith(DIGEST_PREFIX):
        text = text[len(DIGEST_PREFIX) :]
    text = text.lower()
    if len(text) != _DIGEST_HEX_LENGTH:
        raise ValueError(
            f"digest must be {_DIGEST_HEX_LENGTH} hex characters, got {len(text)}"
        )
    if any(character not in "0123456789abcdef" for character in text):
        raise ValueError("digest must be hexadecimal")
    return text


def format_digest(hex_digest: str) -> str:
    """Return the canonical ``sha256:<hex>`` spelling of a digest."""
    return f"{DIGEST_PREFIX}{hex_digest}"


def _collect_files(root: Path) -> list[tuple[str, Path]]:
    """Return every hashable file under ``root`` as (relative path, path).

    The relative path is POSIX-style and relative to ``root``. Exclusions:
    VCS directories, symlinks, and non-regular files.
    """
    collected: list[tuple[str, Path]] = []
    stack: list[tuple[Path, str]] = [(root, "")]
    while stack:
        directory, prefix = stack.pop()
        try:
            entries = sorted(directory.iterdir(), key=lambda entry: entry.name)
        except OSError as error:
            # A tree that cannot be fully walked has no digest. Saying so is
            # better than hashing a partial tree: a partial digest can only
            # ever fail to match the pin, but it would report the pin as
            # drifted when the truth is that the tree was unreadable.
            raise LocatorError(f"cannot read directory {directory}: {error}") from error
        for entry in entries:
            if entry.name in VCS_DIR_NAMES:
                continue
            if entry.is_symlink():
                continue
            relative = f"{prefix}{entry.name}"
            if entry.is_dir():
                stack.append((entry, f"{relative}/"))
            elif entry.is_file():
                collected.append((relative, entry))
    collected.sort(key=lambda item: item[0].encode("utf-8"))
    return collected


def directory_digest(root: Path) -> str:
    """Return the SHA-256 hex digest of the directory tree at ``root``.

    See the module docstring for the exact algorithm. The tree is read and
    never written.
    """
    digest = hashlib.sha256()
    for relative, path in _collect_files(root):
        try:
            data = path.read_bytes()
        except OSError as error:
            raise LocatorError(f"cannot read {path}: {error}") from error
        record = b"F\0" + relative.encode("utf-8") + b"\0"
        record += str(len(data)).encode("ascii") + b"\0" + data + b"\0"
        digest.update(record)
    return digest.hexdigest()


def _iter_directories(root: Path, max_depth: int) -> list[tuple[Path, int]]:
    """Return the directories at or below ``root`` as (path, depth)."""
    found: list[tuple[Path, int]] = []
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        directory, depth = stack.pop()
        found.append((directory, depth))
        if depth >= max_depth:
            continue
        try:
            entries = sorted(directory.iterdir(), key=lambda entry: entry.name)
        except OSError:
            continue
        for entry in entries:
            if entry.name in VCS_DIR_NAMES:
                continue
            if entry.is_symlink():
                continue
            if entry.is_dir():
                stack.append((entry, depth + 1))
    return found


def find_candidates(roots: list[Path], skill: str, max_depth: int = MAX_SEARCH_DEPTH) -> list[Path]:
    """Return every directory under ``roots`` that could hold the skill.

    A candidate is a directory whose name is exactly ``skill`` and that
    contains a ``SKILL.md``. The name test is what makes a plugin cache with
    several versions resolve to several candidates instead of one.
    """
    candidates: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        try:
            if not root.is_dir():
                continue
        except (OSError, ValueError):
            continue
        for directory, depth in _iter_directories(root, max_depth):
            if depth > max_depth or directory.name != skill:
                continue
            if not (directory / "SKILL.md").is_file():
                continue
            resolved = directory.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            candidates.append(directory)
    candidates.sort(key=lambda path: str(path))
    return candidates


def locate(
    skill: str,
    commit: str,
    digest: str,
    roots: list[Path],
    max_depth: int = MAX_SEARCH_DEPTH,
) -> dict[str, object]:
    """Locate the pinned skill and return the result payload.

    ``digest`` is the bare lowercase hex of the pinned directory digest.
    """
    pinned = normalize_digest(digest)
    candidates = find_candidates(roots, skill, max_depth=max_depth)
    examined: list[dict[str, str]] = []
    for candidate in candidates:
        actual = directory_digest(candidate)
        examined.append({"path": str(candidate), "digest": format_digest(actual)})
        if actual == pinned:
            return {
                "status": "present",
                "skill": skill,
                "pin_commit": commit,
                "path": str(candidate),
                "digest": format_digest(actual),
                "candidates": examined,
            }
    if not candidates:
        return {
            "status": "not_available",
            "skill": skill,
            "pin_commit": commit,
            "cause": "no_candidate_found",
            "candidates": [],
        }
    cause = (
        "multiple_versions_none_match" if len(candidates) > 1 else "digest_mismatch"
    )
    return {
        "status": "drift",
        "skill": skill,
        "pin_commit": commit,
        "cause": cause,
        "candidates": examined,
    }


class _ArgumentParser(argparse.ArgumentParser):
    """An ``ArgumentParser`` whose usage errors exit 1, not argparse's 2.

    Exit 2 is reserved for "the pin could not be satisfied", so a malformed
    command line must not share it.
    """

    def error(self, message: str) -> None:  # noqa: D102 - argparse contract
        self.print_usage(sys.stderr)
        print(f"error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def _digest_argument(value: str) -> str:
    try:
        return normalize_digest(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="locate_pinned_skill.py",
        description=(
            "Locate a pinned skill directory and report present / not_available / "
            "drift as JSON on stdout. Read-only: it never installs, fetches, or writes."
        ),
    )
    parser.add_argument(
        "--skill",
        required=True,
        help="the pinned skill's name (its directory name)",
    )
    parser.add_argument(
        "--commit",
        required=True,
        help="the pinned commit, recorded in the result",
    )
    parser.add_argument(
        "--digest",
        required=True,
        type=_digest_argument,
        help="the pinned whole-directory SHA-256 digest, as hex or sha256:<hex>",
    )
    parser.add_argument(
        "--root",
        required=True,
        action="append",
        default=[],
        help=(
            "a candidate root directory to search; repeat for several roots "
            "(harness skill dirs, plugin caches, ...)"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    roots: list[Path] = []
    for raw in args.root:
        if not raw.strip():
            print("error: --root must not be empty", file=sys.stderr)
            return EXIT_USAGE
        try:
            roots.append(Path(raw).expanduser())
        except (OSError, RuntimeError, ValueError) as error:
            print(f"error: invalid --root {raw!r}: {error}", file=sys.stderr)
            return EXIT_USAGE
    try:
        payload = locate(args.skill, args.commit, args.digest, roots)
    except LocatorError as error:
        print(
            json.dumps({"status": "error", "cause": "unreadable_candidate", "detail": str(error)}),
            file=sys.stderr,
        )
        return EXIT_USAGE
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE
    print(json.dumps(payload, indent=2, sort_keys=True))
    return EXIT_PRESENT if payload["status"] == "present" else EXIT_ABSENT


if __name__ == "__main__":
    raise SystemExit(main())
