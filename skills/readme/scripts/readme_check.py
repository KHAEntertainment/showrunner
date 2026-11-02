#!/usr/bin/env python3
"""Lint a README for structure problems and common AI writing tells.

Usage:
    python3 readme_check.py README.md
    python3 readme_check.py README.md --json

Exit code 1 when any hard finding is present, 0 otherwise. Findings are
prompts to look, not orders to edit: judge each one in context.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass

HARD_PHRASES = [
    "seamless", "seamlessly", "blazing fast", "blazingly fast", "lightning-fast",
    "lightning fast", "cutting-edge", "cutting edge", "state-of-the-art",
    "world-class", "best-in-class", "next-generation", "game-changer",
    "game changer", "supercharge", "supercharges", "effortless", "effortlessly",
    "leverage", "leverages", "leveraging", "utilize", "utilizes", "utilizing",
    "empower", "empowers", "delve", "tapestry", "multifaceted", "paramount",
    "embark", "welcome to", "in this readme we", "this readme will",
    "this readme covers", "happy coding", "let's dive in",
    "here's the thing", "whether you're a beginner", "have you ever wondered",
    "it should be noted", "please note that", "in order to",
    "let's break this down", "the key takeaway",
    "that's a thoughtful", "you raise an important point", "holistic",
    "transformative",
]

SOFT_PHRASES = [
    "simply", "just run", "just install", "just add", "easy to use", "easily",
    "powerful", "robust", "revolutionary", "elegant", "streamline",
    "streamlines", "unlock", "unlocks", "elevate", "facilitate",
    "pivotal", "myriad", "plethora", "realm", "landscape", "journey",
    "production-ready", "enterprise-grade", "battle-tested", "out of the box",
    "hope this helps", "feel free to", "give it a star", "star this repo",
    "furthermore", "moreover", "additionally", "in conclusion", "ultimately",
    "aims to", "is a tool that", "here's why", "comprehensive", "nuanced",
    "ecosystem", "it is", "at its core",
]

SCAFFOLD_OPENERS = (
    "additionally", "furthermore", "moreover", "in addition", "ultimately",
    "in conclusion", "finally", "overall", "importantly",
)

COMMAND_STARTS = ("$ ", "npx ", "npm ", "pnpm ", "yarn ", "bun ", "brew ", "pip ", "pipx ",
                  "uv ", "go ", "cargo ", "git ", "curl ", "docker ", "claude ", "codex ",
                  "opencode ", "pi ", "/plugin ", "make ", "python", "node ")
SHELL_LANGS = {"bash", "sh", "shell", "console", "zsh", "fish", "powershell", "ps1", "cmd"}
EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF⭐✅❌]"
)
SMALL_WORDS = {"a", "an", "the", "and", "or", "but", "for", "nor", "on", "at",
               "to", "from", "by", "of", "in", "with", "vs", "via", "as", "is"}

# A badge image is recognised when its source is an `.svg`, when its URL
# carries a badge-host signal, or when the image is a link. Keeping the source
# host-independent is deliberate: a badge served from any host must count.
BADGE_HOST_RE = re.compile(
    r"(shields|badge|badgen|codecov|coveralls|travis|circleci|appveyor|codacy|codeclimate|scrutinizer)",
    re.I,
)


@dataclass
class Finding:
    severity: str  # "hard" or "soft"
    rule: str
    line: int
    detail: str


def strip_inline_code(text: str) -> str:
    return re.sub(r"`[^`]*`", "", text)


def split_lines(text: str):
    """Yield (lineno, line, in_code, fence_info) with HTML comments removed."""
    text = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    in_code = False
    fence_char = ""
    fence_len = 0
    for i, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        m = re.match(r"^(```+|~~~+)(.*)$", stripped)
        if m:
            run = m.group(1)
            char = run[0]
            length = len(run)
            rest = m.group(2).strip()
            if not in_code:
                in_code = True
                fence_char = char
                fence_len = length
                yield i, line, False, ("open", rest)
                continue
            # Close only on a run of the same character at least as long, with
            # nothing after it, so a shorter backtick example inside a longer
            # block does not close it early.
            if char == fence_char and length >= fence_len and rest == "":
                in_code = False
                yield i, line, False, ("close", "")
                continue
        yield i, line, in_code, None


def github_slug(heading: str) -> str:
    """Approximate GitHub's heading anchor: strip markup, lowercase, drop punctuation."""
    text = re.sub(r"<[^>]+>", "", heading)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)   # [text](url) -> text
    text = re.sub(r"[`*_~]", "", text).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE)
    return text.replace(" ", "-")


def is_title_case(heading: str) -> bool:
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'-]*", heading)]
    if len(words) < 3:
        return False
    content = [w for w in words[1:] if w.lower() not in SMALL_WORDS]
    if len(content) < 2:
        return False
    capped = [w for w in content if w[0].isupper() and not w.isupper()]
    return len(capped) == len(content)


def _is_setext_candidate(text: str) -> bool:
    """True when a line of text can be the heading above a `===` underline."""
    t = text.strip()
    if not t:
        return False
    if re.match(r"^(#{1,6})\s", t):        # already an ATX heading
        return False
    if re.fullmatch(r"[-=*_]{3,}", t):     # horizontal rule or another underline
        return False
    if re.match(r"^<h[1-6][\s>]", t, re.I):  # HTML heading
        return False
    return True


def _url_is_badge(url: str) -> bool:
    u = url.strip().lower()
    if re.search(r"\.svg(?:\?|#|$)", u):
        return True
    return bool(BADGE_HOST_RE.search(u))


def _markdown_image_is_linked(line: str, start: int, end: int) -> bool:
    """True when the `![alt](url)` match at [start, end) is wrapped in a link."""
    return (
        start > 0
        and line[start - 1] == "["
        and end + 1 < len(line)
        and line[end] == "]"
        and line[end + 1] == "("
    )


def _html_image_is_linked(line: str, start: int) -> bool:
    """True when the `<img` tag at `start` sits inside an `<a>` tag on the line."""
    return bool(re.search(r"<a\b[^>]*>$", line[:start]))


def count_badges(line: str) -> int:
    """Count badge images in Markdown and HTML forms, host-independently.

    An image is a badge when its source is an `.svg`, when its URL carries a
    badge-host signal, or when it is a linked image. A plain screenshot
    (`![shot](docs/shot.png)`, unlinked, no badge signal) does not count.
    """
    count = 0
    for m in re.finditer(r"!\[[^\]]*\]\(([^)]*)\)", line):
        if _url_is_badge(m.group(1)) or _markdown_image_is_linked(line, m.start(), m.end()):
            count += 1
    for m in re.finditer(r"<img\b[^>]*?src\s*=\s*[\"']([^\"']+)[\"']", line, re.I):
        if _url_is_badge(m.group(1)) or _html_image_is_linked(line, m.start()):
            count += 1
    return count


def check(text: str) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    h1_lines: list[int] = []
    words_total = 0
    words_before_command = None
    first_command_line = None
    badge_count = 0
    bold_label_run = 0
    bold_label_start = 0
    scaffold_run = 0
    prev_blank = True
    pending_fence_lang = None
    em_dash_lines: list[tuple[int, int]] = []
    anchors: list[tuple[int, str]] = []
    slugs: dict[str, int] = {}
    prev_text = ""
    prev_lineno = 0

    for lineno, line, in_code, fence in split_lines(text):
        if fence:
            kind, info = fence
            prev_text = ""
            prev_lineno = 0
            if kind == "open":
                lang = info.split()[0].lower() if info else ""
                if not lang:
                    findings.append(Finding("hard", "code_fence_no_language", lineno,
                                            "Code block has no language; add one (bash, json, ts...)."))
                pending_fence_lang = lang
            continue

        if in_code:
            if first_command_line is None and pending_fence_lang is not None:
                lang = pending_fence_lang
                if lang in SHELL_LANGS or (lang in {"", "text"} and line.strip().startswith(COMMAND_STARTS)):
                    first_command_line = lineno
                    words_before_command = words_total
            continue

        raw_line = line.strip()
        prose = strip_inline_code(line)
        stripped = prose.strip()

        # Setext H1: an `===` underline beneath a non-blank text line.
        if re.fullmatch(r"=+", raw_line) and _is_setext_candidate(prev_text):
            base = github_slug(prev_text)
            if base in slugs:
                slugs[base] += 1
                slugs[f"{base}-{slugs[base]}"] = 0
            else:
                slugs[base] = 0
            h1_lines.append(prev_lineno)

        # Word count for prose only (skip image/badge-only lines).
        line_words = len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*",
                                    re.sub(r"\(https?://[^)]*\)", "", prose)))
        words_total += line_words

        # Badges, counted host-independently across Markdown and HTML forms.
        badge_count += count_badges(line)

        # Anchor links and explicit anchors.
        line_anchors = re.findall(r"\]\(#([^)\s]+)\)", line)
        anchors.extend((lineno, a) for a in line_anchors)
        for explicit in re.findall(r'(?:name|id)=["\']([^"\']+)["\']', line):
            slugs.setdefault(explicit.lower(), 0)

        # HTML <h1> titles.
        if re.match(r"^<h1[\s>]", raw_line, re.I):
            h1_lines.append(lineno)

        # Headings. Structure and slugs use the original heading text (inline
        # code still contributes its characters to the anchor); prose checks
        # below use the inline-code-stripped text.
        hm = re.match(r"^(#{1,6})\s+(.*)$", raw_line)
        if hm:
            level, heading = len(hm.group(1)), hm.group(2).strip()
            base = github_slug(heading)
            if base in slugs:
                slugs[base] += 1
                slugs[f"{base}-{slugs[base]}"] = 0
            else:
                slugs[base] = 0
            if level == 1:
                h1_lines.append(lineno)
            if EMOJI_RE.search(heading):
                findings.append(Finding("soft", "emoji_heading", lineno,
                                        f"Heading uses emoji: {heading!r}. Use a plain heading."))
            if level >= 2 and is_title_case(heading):
                findings.append(Finding("soft", "title_case_heading", lineno,
                                        f"Title Case heading: {heading!r}. Prefer sentence case."))

        # Em and en dashes used as dashes. Severity is decided after the loop.
        if "—" in prose:
            em_dash_lines.append((lineno, prose.count("—")))
        elif re.search(r"\s–\s", prose):
            findings.append(Finding("soft", "en_dash_as_dash", lineno,
                                    "En dash used as a dash; rewrite with a comma or period."))

        # Exclamation points in prose (not images, not HTML).
        if re.search(r"[A-Za-z\)]!(\s|$)", re.sub(r"!\[", "", prose)):
            findings.append(Finding("soft", "exclamation", lineno,
                                    "Exclamation point in body text."))

        lowered = stripped.lower()
        for phrase in HARD_PHRASES:
            if re.search(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])", lowered):
                findings.append(Finding("hard", "banned_phrase", lineno, f"'{phrase}'"))
        for phrase in SOFT_PHRASES:
            if re.search(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])", lowered):
                findings.append(Finding("soft", "watch_phrase", lineno, f"'{phrase}'"))

        # Bold-label listicle runs: "- **Thing**: text" or "- **Thing** - text".
        if re.match(r"^[-*+]\s+(\S+\s+)?\*\*[^*]+\*\*\s*[:\-–—]", stripped):
            if bold_label_run == 0:
                bold_label_start = lineno
            bold_label_run += 1
        elif stripped:
            if bold_label_run >= 5:
                findings.append(Finding("soft", "bold_label_listicle", bold_label_start,
                                        f"{bold_label_run} bullets in a row shaped '**Label**: text'. "
                                        "Fine for reference lists; for features, write plainly or cut."))
            bold_label_run = 0

        # Scaffold paragraph openers.
        if prev_blank and stripped and not hm:
            if lowered.startswith(SCAFFOLD_OPENERS):
                scaffold_run += 1
                findings.append(Finding("soft", "scaffold_opener", lineno,
                                        f"Paragraph opens with a connective: {stripped.split()[0]!r}."))
        prev_blank = not stripped
        if raw_line:
            prev_text = raw_line
            prev_lineno = lineno
        else:
            prev_text = ""
            prev_lineno = 0

    # Em dashes: rare is fine, a habit is a tell.
    em_total = sum(n for _, n in em_dash_lines)
    for lineno, n in em_dash_lines:
        hard = em_total > 2 or n > 1
        why = (f"{em_total} em dashes in the README; keep it to one or two." if em_total > 2 else
               "Two em dashes on one line." if n > 1 else
               "Em dash; fine if rare, but a comma, period, or parentheses usually reads better.")
        findings.append(Finding("hard" if hard else "soft", "em_dash", lineno, why))

    if bold_label_run >= 5:
        findings.append(Finding("soft", "bold_label_listicle", bold_label_start,
                                f"{bold_label_run} bullets in a row shaped '**Label**: text'."))

    for lineno, anchor in anchors:
        if "{" in anchor:
            continue  # template placeholder
        if anchor.lower() not in slugs:
            findings.append(Finding("hard", "broken_anchor", lineno,
                                    f"Link to #{anchor} matches no heading."))

    if len(h1_lines) == 0:
        findings.append(Finding("soft", "no_h1", 1, "No H1 title. Start with '# project-name'."))
    elif len(h1_lines) > 1:
        findings.append(Finding("hard", "multiple_h1", h1_lines[1],
                                f"{len(h1_lines)} H1 headings; keep one for the project name."))

    if badge_count > 0:
        findings.append(Finding("soft", "badge_count", 1,
                                f"{badge_count} badge image(s) in the README. Group them by "
                                "category (build/quality, distribution, legal, community), keep a "
                                "stable order, and keep the hook adjacent."))

    if first_command_line is None:
        findings.append(Finding("hard", "no_runnable_command", 1,
                                "No shell code block found. The reader needs a command to try it."))
    elif words_before_command is not None and words_before_command > 400:
        findings.append(Finding("soft", "command_too_far_down", first_command_line,
                                f"First runnable command comes after {words_before_command} words "
                                "(aim for under ~400, the first or second screen)."))

    if words_total > 1500:
        findings.append(Finding("soft", "too_long", 1,
                                f"About {words_total} words of prose (over ~5 minutes to read). "
                                "Move reference material to docs/."))

    stats = {
        "prose_words": words_total,
        "words_before_first_command": words_before_command,
        "first_command_line": first_command_line,
        "badges": badge_count,
        "h1_count": len(h1_lines),
        "em_dashes": em_total,
    }
    return findings, stats


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", help="README file to check")
    parser.add_argument("--json", action="store_true", help="Print findings as JSON")
    args = parser.parse_args(argv)

    with open(args.path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()

    findings, stats = check(text)
    hard = [f for f in findings if f.severity == "hard"]

    if args.json:
        print(json.dumps({"stats": stats, "findings": [asdict(f) for f in findings]}, indent=2))
    else:
        print(f"{args.path}: {stats['prose_words']} prose words, "
              f"first command at line {stats['first_command_line']} "
              f"(after {stats['words_before_first_command']} words), "
              f"{stats['badges']} badges")
        if not findings:
            print("No findings.")
        for sev in ("hard", "soft"):
            group = [f for f in findings if f.severity == sev]
            if group:
                print(f"\n{sev.upper()} ({len(group)})")
                for f in sorted(group, key=lambda x: x.line):
                    print(f"  line {f.line:>4}  {f.rule:<24} {f.detail}")
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
