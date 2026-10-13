#!/usr/bin/env python3
"""Release check: the central catalog entry must match the tagged plugin.

`dev-skill` is listed in KHAEntertainment/marketplace, not in this repository.
Run this after the central pin bump merges. It fails closed: an unreachable or
unparseable catalog is never a pass.

Exit status: 0 = verified, 1 = a check failed, 2 = could not verify (network,
git, or parse error). Both nonzero outcomes name a reason; rerun on 2.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_version_sync import CheckError, SEMVER, load_json, object_value, parse_version  # noqa: E402

CATALOG_REPO = "https://github.com/KHAEntertainment/marketplace.git"
CATALOG_BRANCH = "main"
CATALOG_PATH = ".claude-plugin/marketplace.json"
PLUGIN_NAME = "dev-skill"
PLUGIN_URL = "https://github.com/KHAEntertainment/claude-dev-skill.git"
PLUGIN_MANIFEST = ".claude-plugin/plugin.json"
GIT_TIMEOUT = 120


class Unverifiable(Exception):
    """The check could not be performed; never a pass."""


def git(args: list[str], cwd: Path | None = None) -> str:
    """Run git anonymously with a timeout; any failure is Unverifiable."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    command = ["git", "-c", "credential.helper=", "-c", "core.askPass=", "-c", "http.extraheader=", *args]
    try:
        done = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True,
                              timeout=GIT_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Unverifiable(f"git {args[0]} did not complete ({error})") from error
    if done.returncode != 0:
        raise Unverifiable(f"git {args[0]} failed with exit {done.returncode}: {done.stderr.strip()[:300]}")
    return done.stdout


def load_catalog_from_git(repo: str = CATALOG_REPO, branch: str = CATALOG_BRANCH) -> Any:
    with tempfile.TemporaryDirectory(prefix="central-catalog-") as directory:
        git(["clone", "--quiet", "--depth", "1", "--branch", branch, repo, directory])
        return load_catalog_file(Path(directory) / CATALOG_PATH)


def load_catalog_file(path: Path) -> Any:
    try:
        return load_json(path)
    except CheckError as error:
        raise Unverifiable(str(error)) from error


def resolve_tag(url: str, ref: str) -> str | None:
    """Return the commit the remote tag peels to, or None if the tag is absent."""
    output = git(["ls-remote", url, f"refs/tags/{ref}", f"refs/tags/{ref}^{{}}"])
    plain = peeled = None
    for line in output.splitlines():
        sha, _, name = line.partition("\t")
        if name == f"refs/tags/{ref}^{{}}":
            peeled = sha
        elif name == f"refs/tags/{ref}":
            plain = sha
    # An annotated tag lists the tag object, then the commit; a lightweight tag lists the commit.
    return peeled or plain


def read_manifest_at_tag(url: str, ref: str) -> tuple[str, Any]:
    """Clone the tag and return (HEAD commit, parsed plugin.json) from the same checkout."""
    with tempfile.TemporaryDirectory(prefix="central-plugin-") as directory:
        git(["clone", "--quiet", "--depth", "1", "--branch", ref, url, directory])
        head = git(["rev-parse", "HEAD"], cwd=Path(directory)).strip()
        try:
            manifest = load_json(Path(directory) / PLUGIN_MANIFEST)
        except CheckError as error:
            raise Unverifiable(str(error)) from error
        return head, manifest


def verify(
    local_version: str,
    tag: str,
    catalog: Any,
    resolve: Callable[[str, str], str | None] = resolve_tag,
    read_manifest: Callable[[str, str], tuple[str, Any]] = read_manifest_at_tag,
) -> list[str]:
    """Return failure reasons; an empty list means every check passed."""
    expected = f"v{local_version}"
    if tag != expected:
        return [f"--tag {tag} does not match the local plugin version (expected {expected})"]
    if not isinstance(catalog, dict) or not isinstance(catalog.get("plugins"), list):
        return ["central catalog is not an object with a plugins array"]

    entries = [p for p in catalog["plugins"] if isinstance(p, dict) and p.get("name") == PLUGIN_NAME]
    if len(entries) != 1:
        return [f"central catalog must list exactly one {PLUGIN_NAME!r} entry, found {len(entries)}"]
    entry = entries[0]

    failures: list[str] = []
    source = entry.get("source")
    if not isinstance(source, dict):
        return ["central entry has no source object"]
    if source.get("source") != "url":
        failures.append(f"central source.source is {source.get('source')!r}, expected 'url'")
    url = source.get("url")
    if url != PLUGIN_URL:
        failures.append(f"central source.url is {url!r}, expected {PLUGIN_URL!r}")
    ref = source.get("ref")
    if ref != tag:
        failures.append(f"central source.ref is {ref!r}, expected {tag!r}")
    if "version" in entry and entry["version"] != local_version:
        failures.append(f"central entry version is {entry['version']!r}, expected {local_version!r}")
    if failures:
        return failures

    commit = resolve(PLUGIN_URL, tag)
    if commit is None:
        return [f"tag {tag} is not published at {PLUGIN_URL}"]
    head, manifest = read_manifest(PLUGIN_URL, tag)
    if head != commit:
        failures.append(f"checkout of {tag} is at {head}, but the tag peels to {commit}")
    try:
        name = object_value(manifest, "name", Path(PLUGIN_MANIFEST))
        version = parse_version(object_value(manifest, "version", Path(PLUGIN_MANIFEST)), f"{tag} plugin.json version")
    except CheckError as error:
        return failures + [str(error)]
    if name != PLUGIN_NAME:
        failures.append(f"plugin.json at {tag} is named {name!r}, expected {PLUGIN_NAME!r}")
    if version != local_version:
        failures.append(f"plugin.json at {tag} has version {version!r}, expected {local_version!r}")
    return failures


def local_plugin_version(root: Path) -> str:
    path = root / PLUGIN_MANIFEST
    return parse_version(object_value(load_json(path), "version", path), f"{path} version")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tag", help="release tag vX.Y.Z (default: v<plugin.json version>)")
    parser.add_argument("--catalog-file", type=Path,
                        help="read the catalog from this file instead of cloning KHAEntertainment/marketplace (tests)")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    try:
        version = local_plugin_version(root)
        tag = args.tag if args.tag is not None else f"v{version}"
        if not tag.startswith("v") or SEMVER.fullmatch(tag[1:]) is None:
            raise CheckError("--tag must be v-prefixed semver")
        catalog = load_catalog_file(args.catalog_file) if args.catalog_file else load_catalog_from_git()
        failures = verify(version, tag, catalog)
    except CheckError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except Unverifiable as error:
        print(f"UNVERIFIED: {error}", file=sys.stderr)
        return 2

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    print(f"OK: central catalog pins {PLUGIN_NAME} {tag}, and the tag's plugin.json reports {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
