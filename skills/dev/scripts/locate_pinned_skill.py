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
wins. A root that does not exist is skipped. A root that exists but cannot
be read is an operational error (``root_unreadable``), never an absence:
the skill could be inside it.

Output (one JSON object on stdout):

* ``status`` is ``present``, ``not_available``, ``drift`` or ``error``.
* On ``present``: ``path`` (the matching directory) and ``digest`` (the
  directory digest that was computed).
* On ``not_available`` / ``drift``: a ``cause``, and never a "success" that a
  caller could mistake for a completed step.
* On ``error``: a ``cause`` and a ``detail``. An operational error is not a
  verdict -- the locator could not find out whether the pin is satisfied.
* ``candidates`` lists every candidate that was digested, with its digest;
  ``symlinked`` lists the candidates refused because they hold a symlink;
  ``unreadable`` lists the roots and candidates that could not be read.
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
* ``symlinked_content`` -- a candidate holds a symlink, a file or a
  directory, ``SKILL.md`` included. Symlinked content is never followed and
  never hashed, so such a candidate can never be reported as ``present``.
* ``root_unreadable`` -- a root exists but could not be read.
* ``candidate_unreadable`` -- a candidate exists but could not be read.

The ``not_available`` / ``drift`` vocabulary and the mandatory ``cause`` are
the provider-result vocabulary of contract SC-5 as revised by PR #209: an
absent or drifted provider is never reported as a completed research step,
and an operational error is not a verdict at all.

Verdict precedence, when nothing matched:

    1. a candidate that matched        -> present
    2. an unreadable root              -> error / root_unreadable
    3. an unreadable candidate         -> error / candidate_unreadable
    4. clean candidates, none matching -> drift / digest_mismatch (one) or
                                          multiple_versions_none_match
                                          (several)
    5. a candidate holding a symlink   -> drift / symlinked_content
    6. no candidate at all             -> not_available / no_candidate_found

An unreadable tree outranks a drift cause, because an unreadable candidate
could have been the match. A clean candidate whose digest mismatches is a
more specific drift than a symlinked one: a symlinked candidate can never
match, so it is listed under ``symlinked`` and never chosen, but it does not
hide a digest mismatch beside it.

Exit codes:

    0  present -- a candidate matched the pinned digest.
    2  not_available or drift -- a definitive verdict: the pin was not
       satisfied by anything that was found.
    1  usage error, or an operational error.
       - Usage error: stdout is empty and stderr carries the usage message.
       - Operational error: stdout carries one JSON error object
         ({"status": "error", "cause": ...}) and stderr is empty.
       A caller must treat exit 1 as "no verdict": it is neither
       ``present`` nor a definitive absence, and it must never be reported
       as a completed research step.

Directory digest
----------------
The digest of a skill directory is the SHA-256 (hex) of a canonical byte
stream built from every regular file in the tree:

* VCS directories (``.git``, ``.hg``, ``.svn``) are excluded.
* Symlinks -- files and directories alike -- are excluded from the digest and
  are never followed, so the digest never depends on anything outside the
  directory it was given and never follows a cycle. A candidate that holds a
  symlink is not a valid match at all: the content behind the link could
  change without changing the digest, so such a candidate is reported as
  drift with the cause ``symlinked_content``.
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
EXIT_NO_VERDICT = 1  # usage error or operational error: no verdict at all
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


def scan_directory(root: Path) -> tuple[list[tuple[str, Path]], list[str]]:
    """Return the regular files and the symlinks under ``root``.

    The first list holds ``(relative path, path)`` for every regular file,
    sorted by the UTF-8 bytes of the relative path. The second holds the
    relative path of every symlink found, sorted the same way. Symlinks are
    never followed and never hashed.

    Raises ``LocatorError`` when a directory in the tree cannot be read: a
    partial tree has no digest, and saying so beats hashing what happened to
    be readable.
    """
    files: list[tuple[str, Path]] = []
    links: list[str] = []
    stack: list[tuple[Path, str]] = [(root, "")]
    while stack:
        directory, prefix = stack.pop()
        try:
            entries = sorted(directory.iterdir(), key=lambda entry: entry.name)
        except OSError as error:
            raise LocatorError(f"cannot read directory {directory}: {error}") from error
        for entry in entries:
            if entry.name in VCS_DIR_NAMES:
                continue
            relative = f"{prefix}{entry.name}"
            if entry.is_symlink():
                # Never followed, never hashed: the content behind a link
                # could change without changing the digest, so a candidate
                # that holds one can never be a valid match.
                links.append(relative)
                continue
            if entry.is_dir():
                stack.append((entry, f"{relative}/"))
            elif entry.is_file():
                files.append((relative, entry))
    files.sort(key=lambda item: item[0].encode("utf-8"))
    links.sort(key=lambda relative: relative.encode("utf-8"))
    return files, links


def _digest_files(files: list[tuple[str, Path]]) -> str:
    """Return the SHA-256 hex digest of the given ``(relative path, path)`` files."""
    digest = hashlib.sha256()
    for relative, path in files:
        try:
            data = path.read_bytes()
        except OSError as error:
            raise LocatorError(f"cannot read {path}: {error}") from error
        record = b"F\0" + relative.encode("utf-8") + b"\0"
        record += str(len(data)).encode("ascii") + b"\0" + data + b"\0"
        digest.update(record)
    return digest.hexdigest()


def directory_digest(root: Path) -> str:
    """Return the SHA-256 hex digest of the directory tree at ``root``.

    See the module docstring for the exact algorithm. The tree is read and
    never written. Symlinks are excluded from the digest; a tree that holds
    one is not a valid match for the locator (see ``symlinked_content``).
    """
    files, _links = scan_directory(root)
    return _digest_files(files)


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


def _classify_skill_entry(directory: Path) -> str:
    """Return ``file``, ``symlink`` or ``absent`` for a candidate's ``SKILL.md``.

    Raises OSError when the directory cannot be inspected at all, which is
    how an unreadable candidate is told apart from one that simply has no
    ``SKILL.md``.
    """
    entry = directory / "SKILL.md"
    if entry.is_symlink():
        return "symlink"
    try:
        entry.stat()
    except FileNotFoundError:
        return "absent"
    if not entry.is_file():
        return "absent"
    return "file"


def find_candidates(
    roots: list[Path],
    skill: str,
    max_depth: int = MAX_SEARCH_DEPTH,
) -> tuple[list[Path], list[tuple[Path, str]], list[tuple[Path, str]]]:
    """Return the candidates, the unreadable roots and the unreadable candidates.

    A candidate is a directory whose name is exactly ``skill`` and that
    holds a ``SKILL.md``. The name test is what makes a plugin cache with
    several versions resolve to several candidates instead of one.

    A root that does not exist is skipped: it is not a candidate source and
    its absence says nothing about the skill. A root that exists but cannot
    be read is reported, because the skill could be inside it.
    """
    candidates: list[Path] = []
    unreadable_roots: list[tuple[Path, str]] = []
    unreadable_candidates: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for root in roots:
        try:
            root.stat()
        except FileNotFoundError:
            continue
        except OSError as error:
            unreadable_roots.append((root, f"cannot read root {root}: {error}"))
            continue
        try:
            if not root.is_dir():
                raise ValueError(f"--root is not a directory: {root}")
            list(root.iterdir())
        except OSError as error:
            unreadable_roots.append((root, f"cannot read root {root}: {error}"))
            continue
        for directory, depth in _iter_directories(root, max_depth):
            if depth > max_depth or directory.name != skill:
                continue
            try:
                kind = _classify_skill_entry(directory)
            except OSError as error:
                unreadable_candidates.append(
                    (directory, f"cannot inspect {directory}: {error}")
                )
                continue
            if kind == "absent":
                continue
            resolved = directory.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            candidates.append(directory)
    candidates.sort(key=lambda path: str(path))
    return candidates, unreadable_roots, unreadable_candidates


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
    candidates, unreadable_roots, unreadable_candidates = find_candidates(
        roots, skill, max_depth=max_depth
    )
    examined: list[dict[str, str]] = []
    symlinked: list[dict[str, object]] = []
    matched: Path | None = None
    matched_digest = ""
    for candidate in candidates:
        try:
            files, links = scan_directory(candidate)
            if links:
                symlinked.append({"path": str(candidate), "symlinks": links})
                continue
            actual = _digest_files(files)
        except LocatorError as error:
            unreadable_candidates.append((candidate, str(error)))
            continue
        examined.append({"path": str(candidate), "digest": format_digest(actual)})
        if actual == pinned and matched is None:
            matched = candidate
            matched_digest = actual
    unreadable = [
        {"path": str(path), "detail": detail}
        for path, detail in unreadable_roots + unreadable_candidates
    ]
    base: dict[str, object] = {
        "skill": skill,
        "pin_commit": commit,
        "candidates": examined,
        "symlinked": symlinked,
        "unreadable": unreadable,
    }
    if matched is not None:
        return {
            **base,
            "status": "present",
            "path": str(matched),
            "digest": format_digest(matched_digest),
        }
    if unreadable_roots:
        return {
            **base,
            "status": "error",
            "cause": "root_unreadable",
            "detail": unreadable[0]["detail"],
        }
    if unreadable_candidates:
        return {
            **base,
            "status": "error",
            "cause": "candidate_unreadable",
            "detail": unreadable[0]["detail"],
        }
    if examined:
        cause = (
            "multiple_versions_none_match" if len(examined) > 1 else "digest_mismatch"
        )
        return {**base, "status": "drift", "cause": cause}
    if symlinked:
        return {**base, "status": "drift", "cause": "symlinked_content"}
    return {**base, "status": "not_available", "cause": "no_candidate_found"}


class _ArgumentParser(argparse.ArgumentParser):
    """An ``ArgumentParser`` whose usage errors exit 1, not argparse's 2.

    Exit 2 is reserved for "the pin could not be satisfied", so a malformed
    command line must not share it.
    """

    def error(self, message: str) -> None:  # noqa: D102 - argparse contract
        self.print_usage(sys.stderr)
        print(f"error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_NO_VERDICT)


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
            return EXIT_NO_VERDICT
        try:
            roots.append(Path(raw).expanduser())
        except (OSError, RuntimeError, ValueError) as error:
            print(f"error: invalid --root {raw!r}: {error}", file=sys.stderr)
            return EXIT_NO_VERDICT
    try:
        payload = locate(args.skill, args.commit, args.digest, roots)
    except ValueError as error:
        # A bad argument: a malformed pin, or a root that is not a directory.
        print(f"error: {error}", file=sys.stderr)
        return EXIT_NO_VERDICT
    print(json.dumps(payload, indent=2, sort_keys=True))
    status = payload["status"]
    if status == "present":
        return EXIT_PRESENT
    if status == "error":
        return EXIT_NO_VERDICT
    return EXIT_ABSENT


if __name__ == "__main__":
    raise SystemExit(main())
