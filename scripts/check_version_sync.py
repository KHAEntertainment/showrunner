#!/usr/bin/env python3
"""Verify that the plugin's release-version sites agree.

Offline by design: it compares the Skill frontmatter, `.claude-plugin/plugin.json`,
and an optional `--tag`. The central marketplace catalog lives in another
repository and is checked at release time by `check_central_catalog.py`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SEMVER = re.compile(
    r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
SKILL_SEMVER = re.compile(rf"{SEMVER.pattern}(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?")
FRONTMATTER = re.compile(r"\A---\r?\n(?P<body>.*?)\r?\n---(?:\r?\n|\Z)", re.DOTALL)
VERSION_FIELD = re.compile(r"^version:[ \t]*(?P<value>[^\s#]+)[ \t]*$", re.MULTILINE)


class CheckError(Exception):
    """An expected validation error that should not produce a traceback."""


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise CheckError(f"{path}: cannot read file ({error})") from error


def load_json(path: Path) -> Any:
    try:
        return json.loads(read_text(path))
    except json.JSONDecodeError as error:
        raise CheckError(f"{path}: invalid JSON ({error.msg})") from error


def parse_version(value: object, label: str, allow_build_metadata: bool = False) -> str:
    if not isinstance(value, str):
        raise CheckError(f"{label}: version must be a string")
    pattern = SKILL_SEMVER if allow_build_metadata else SEMVER
    if pattern.fullmatch(value) is None:
        raise CheckError(f"{label}: unparseable version {value!r}")
    return value


def skill_version(path: Path) -> str:
    match = FRONTMATTER.match(read_text(path))
    if match is None:
        raise CheckError(f"{path}: missing YAML frontmatter")
    version_match = VERSION_FIELD.search(match.group("body"))
    if version_match is None:
        raise CheckError(f"{path}: missing frontmatter version")
    return parse_version(version_match.group("value"), f"{path} frontmatter", True)


def object_value(data: Any, key: str, path: Path) -> Any:
    if not isinstance(data, dict):
        raise CheckError(f"{path}: expected a JSON object")
    if key not in data:
        raise CheckError(f"{path}: missing {key!r}")
    return data[key]


def print_version_table(values: list[tuple[str, str]]) -> None:
    width = max(len(site) for site, _ in values)
    print("ERROR: version sites disagree", file=sys.stderr)
    print(f"ERROR: {'site'.ljust(width)}  value", file=sys.stderr)
    for site, value in values:
        print(f"ERROR: {site.ljust(width)}  {value}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="optional release tag in vX.Y.Z form")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    skill_path = root / "skills" / "dev" / "SKILL.md"
    plugin_path = root / ".claude-plugin" / "plugin.json"

    try:
        skill_raw = skill_version(skill_path)
        plugin_raw = parse_version(
            object_value(load_json(plugin_path), "version", plugin_path),
            f"{plugin_path} version",
        )
        tag_raw = None
        if args.tag is not None:
            if not args.tag.startswith("v"):
                raise CheckError("--tag must be v-prefixed semver")
            parse_version(args.tag[1:], "--tag")
            tag_raw = args.tag
    except CheckError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    values = [
        ("skills/dev/SKILL.md frontmatter", skill_raw),
        (".claude-plugin/plugin.json version", plugin_raw),
    ]
    if tag_raw is not None:
        values.append(("--tag", tag_raw))

    cores = [skill_raw.split("+", 1)[0], plugin_raw]
    if tag_raw is not None:
        cores.append(tag_raw[1:])
    if len(set(cores)) != 1:
        print_version_table(values)
        return 1

    print(f"OK: version {cores[0]} agrees across release sites")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
