#!/usr/bin/env bash
# Install the English /dev personal Skill for Claude Code.

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SOURCE_DIR="$SCRIPT_DIR/skills/dev"
VALIDATOR="$SCRIPT_DIR/scripts/validate_skill.py"

# When SCRIPT_DIR is itself the root of a git checkout that tracks
# skills/dev, stage from committed content instead of the working tree so
# untracked/ignored files and uncommitted edits never ship. A release
# tarball has no .git, so it falls back to the working-tree copy
# unchanged. This is decided by a filesystem check, not by whether the git
# binary happens to be usable: whether
# SCRIPT_DIR *looks like* a git checkout (a .git entry — directory or, for
# a linked worktree, the "gitdir: ..." file — is present) and whether it
# can actually be *validated* as one are kept separate on purpose. A
# directory that looks like a checkout but can't be validated (git is
# missing, or validation fails for any other reason) must never silently
# fall back to the copy path — that would ship possibly-dirty working-tree
# content while looking, from the outside, exactly like the safe case.
# Resulting matrix:
#   own .git + validates + tar available  -> git-archive path
#   own .git + validates + tar missing    -> abort (checked further down,
#                                             once tar's availability is known)
#   own .git + does not validate          -> abort (git missing, or the
#                                             directory isn't actually a
#                                             valid checkout tracking
#                                             skills/dev at HEAD)
#   no own .git                           -> copy path, tarball provenance
#                                             (git/tar not required here)
# -L (not just -e) catches a dangling .git symlink too: -e alone follows
# the link and reports false when its target is missing, which would
# otherwise read as "no git metadata at all" and fall through to the copy
# path even though a .git entry — just a broken one — is genuinely present.
HAS_OWN_GIT=0
if [[ -e "$SCRIPT_DIR/.git" || -L "$SCRIPT_DIR/.git" ]]; then
  HAS_OWN_GIT=1
fi

# GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE, GIT_OBJECT_DIRECTORY, and
# GIT_COMMON_DIR, if inherited from the caller's environment, override
# `-C`'s repository discovery entirely — every git call below uses this
# array instead of a bare `git` so an inherited GIT_DIR pointed at some
# other repository can't make the installer validate, archive, and
# install that other repository's committed skills/dev tree while still
# reporting *its* commit, even though the own-.git check above passed on
# SCRIPT_DIR. GIT_COMMON_DIR (the linked-worktree analog of GIT_DIR) is
# included for the same reason, as defense in depth alongside the other
# four, even though it did not independently redirect a worktree-less
# checkout in testing.
GIT_ENV_CLEAN=(env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE -u GIT_OBJECT_DIRECTORY -u GIT_COMMON_DIR git)

IS_GIT_CHECKOUT=0
GIT_VALIDATION_ERROR=""
INSTALL_COMMIT=""
if ((HAS_OWN_GIT)); then
  if ! command -v git >/dev/null 2>&1; then
    GIT_VALIDATION_ERROR="this looks like a git checkout of the Skill (a .git entry is present at $SCRIPT_DIR), but git is required to stage it safely from git content. Install git, or install from a release tarball instead."
  # The `if VAR=$(cmd) && ...` form (rather than capturing output
  # unconditionally) is what lets an empty result be told apart from a
  # failed lookup: git exits non-zero with no output at all when SCRIPT_DIR
  # isn't a valid repository, so a bare `-z "$GIT_PREFIX"` check alone
  # would wrongly treat that failure the same as "cwd is the repo root."
  # `--show-prefix` answers "is cwd the repo root" directly (empty output
  # means yes), avoiding a path-string comparison that symlink resolution
  # could otherwise throw off. INSTALL_COMMIT is captured here, once, as
  # part of the same validation chain, and reused verbatim for every later
  # archive: resolving HEAD again at staging time would leave a window
  # where a concurrent commit on this checkout could make the archived
  # content disagree with the commit the install reports.
  elif GIT_PREFIX="$("${GIT_ENV_CLEAN[@]}" -C "$SCRIPT_DIR" rev-parse --show-prefix 2>/dev/null)" \
    && [[ -z "$GIT_PREFIX" ]] \
    && [[ -n "$("${GIT_ENV_CLEAN[@]}" -C "$SCRIPT_DIR" ls-tree -d HEAD -- skills/dev 2>/dev/null)" ]] \
    && INSTALL_COMMIT="$("${GIT_ENV_CLEAN[@]}" -C "$SCRIPT_DIR" rev-parse HEAD 2>/dev/null)" \
    && [[ -n "$INSTALL_COMMIT" ]]; then
    IS_GIT_CHECKOUT=1
  else
    INSTALL_COMMIT=""
    GIT_VALIDATION_ERROR="this looks like a git checkout of the Skill (a .git entry is present at $SCRIPT_DIR), but its git metadata could not be validated (it may not be the repository root, or skills/dev may not be tracked at HEAD). Refusing to guess; install from a clean checkout or a release tarball instead."
  fi
fi

LANGUAGE="en"
CONFIG_DIR="${CLAUDE_CONFIG_DIR:-${HOME:?HOME is required}/.claude}"
TARGET=""
TARGET_EXPLICIT=0
MIGRATE_LEGACY="auto"
DRY_RUN=0
AGENTS_LINK=1

# shellcheck disable=SC2016 # help text names variables literally
usage() {
  printf '%s\n' \
    'Usage: ./install.sh [--lang en] [--config-dir DIR] [--target DIR] [--no-agents-link] [--dry-run]' \
    '' \
    'Installs skills/dev as a personal Claude Code Skill.' \
    '--lang en and --lang=en are accepted for compatibility; Chinese is not distributed.' \
    'A custom --target installs in isolation: it does not migrate legacy commands by default' \
    'and does not create the Codex discovery link.' \
    '' \
    'The installed copy has its ${CLAUDE_SKILL_DIR} references replaced by its absolute path,' \
    'so harnesses other than Claude Code can resolve them.' \
    'A default install also links $HOME/.agents/skills/dev to the installed Skill so Codex and' \
    'other harnesses discover the same copy. An existing real directory, file, or link to another' \
    'existing directory at that path is reported and left untouched; a link whose target no longer' \
    'exists is replaced. That guarantee assumes nothing else writes to that path during the install.' \
    'A newline or carriage return in the config dir, the install target, or the Codex discovery link' \
    'path is refused. The link path is checked whenever link creation is enabled: a default install,' \
    'dry runs included, but not with --no-agents-link or an explicit --target. A relative --target' \
    'also checks the working directory. HOME is not checked on its own.' \
    '--no-agents-link  do not create or touch that link.'
}

while (($#)); do
  case "$1" in
    --lang)
      (($# >= 2)) || { printf 'ERROR: --lang requires a value\n' >&2; exit 2; }
      LANGUAGE="$2"
      shift 2
      ;;
    --lang=*) LANGUAGE="${1#*=}"; shift ;;
    --config-dir)
      (($# >= 2)) || { printf 'ERROR: --config-dir requires a value\n' >&2; exit 2; }
      CONFIG_DIR="$2"
      shift 2
      ;;
    --config-dir=*) CONFIG_DIR="${1#*=}"; shift ;;
    --target)
      (($# >= 2)) || { printf 'ERROR: --target requires a value\n' >&2; exit 2; }
      TARGET="$2"
      TARGET_EXPLICIT=1
      shift 2
      ;;
    --target=*) TARGET="${1#*=}"; TARGET_EXPLICIT=1; shift ;;
    --migrate-legacy) MIGRATE_LEGACY=1; shift ;;
    --keep-legacy) MIGRATE_LEGACY=0; shift ;;
    --no-agents-link) AGENTS_LINK=0; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      printf 'ERROR: unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$LANGUAGE" != "en" ]]; then
  printf 'ERROR: this maintained distribution is English-only; use --lang en.\n' >&2
  exit 2
fi

if [[ -z "$TARGET" ]]; then TARGET="$CONFIG_DIR/skills/dev"; fi
if [[ "$MIGRATE_LEGACY" == "auto" ]]; then
  if ((TARGET_EXPLICIT)); then MIGRATE_LEGACY=0; else MIGRATE_LEGACY=1; fi
fi

AGENTS_LINK_PATH=""
AGENTS_LINK_SKIP=""
if ((!AGENTS_LINK)); then
  AGENTS_LINK_SKIP="--no-agents-link"
elif ((TARGET_EXPLICIT)); then
  AGENTS_LINK_SKIP="explicit --target installs in isolation"
else
  AGENTS_LINK_PATH="${HOME:?HOME is required}/.agents/skills/dev"
fi

# The stamp is written into text files and read back from command substitution,
# both of which mangle a line break in a path (a trailing newline is stripped
# outright), so refuse such a path up front rather than stamp a wrong one. The
# working directory only matters when a relative path is resolved against it.
reject_line_break() {
  case "$2" in
    *$'\n'*|*$'\r'*)
      printf 'ERROR: %s must not contain a newline or carriage return: %q\n' "$1" "$2" >&2
      exit 2
      ;;
  esac
}
reject_line_break 'config dir' "$CONFIG_DIR"
reject_line_break 'install target' "$TARGET"
reject_line_break 'Codex discovery link path' "$AGENTS_LINK_PATH"
case "$TARGET" in /*) ;; *) reject_line_break 'working directory' "$PWD" ;; esac

case "$TARGET" in
  ''|'/'|"$HOME"|"$CONFIG_DIR")
    printf 'ERROR: unsafe install target: %s\n' "$TARGET" >&2
    exit 2
    ;;
esac
if [[ "$(basename -- "$TARGET")" != "dev" ]]; then
  printf 'ERROR: --target must be the exact dev Skill directory and end in /dev: %s\n' "$TARGET" >&2
  exit 2
fi
if [[ -L "$TARGET" ]]; then
  printf 'ERROR: refusing to replace symlink target: %s\n' "$TARGET" >&2
  exit 2
fi

command -v python3 >/dev/null || { printf 'ERROR: python3 is required for preflight validation.\n' >&2; exit 1; }
command -v rtk >/dev/null || { printf 'ERROR: RTK is required by this customized /dev workflow.\n' >&2; exit 1; }
if [[ -n "$GIT_VALIDATION_ERROR" ]]; then
  printf 'ERROR: %s\n' "$GIT_VALIDATION_ERROR" >&2
  exit 1
fi
if ((IS_GIT_CHECKOUT)) && ! command -v tar >/dev/null 2>&1; then
  printf 'ERROR: this is a git checkout of the Skill, but tar is required to stage it safely from git content. Install tar, or install from a release tarball instead.\n' >&2
  exit 1
fi
# Preflight validates the tree that will actually be installed. In git
# mode that is the committed content at INSTALL_COMMIT, not SOURCE_DIR: an
# uncommitted local edit or deletion under SOURCE_DIR must not block
# installing a perfectly valid committed tree, and conversely, a genuinely
# broken committed tree must still be caught here, before any mutation.
# This costs a second archive/extract beyond the one staging does later
# (cheap for a skill-sized tree) rather than skipping preflight validation
# for git mode entirely.
if ((IS_GIT_CHECKOUT)); then
  PREFLIGHT_DIR="$(mktemp -d)"
  # shellcheck disable=SC2064 # intentionally expand PREFLIGHT_DIR now
  trap "rm -rf -- '$PREFLIGHT_DIR'" EXIT
  # cd instead of `tar -C`: GNU tar processes backslash escapes in a -C
  # argument, and PREFLIGHT_DIR lives under the caller's TMPDIR.
  "${GIT_ENV_CLEAN[@]}" -C "$SCRIPT_DIR" archive "$INSTALL_COMMIT" -- skills/dev | (cd -- "$PREFLIGHT_DIR" && tar -x --strip-components=2)
  python3 "$VALIDATOR" --skill-dir "$PREFLIGHT_DIR"
  rm -rf -- "$PREFLIGHT_DIR"
  trap - EXIT
else
  python3 "$VALIDATOR" --skill-dir "$SOURCE_DIR"
fi

LEGACY_FILE="$CONFIG_DIR/commands/dev.md"
LEGACY_DIR="$CONFIG_DIR/commands/dev"
if [[ "$MIGRATE_LEGACY" == 1 && ( -L "$LEGACY_FILE" || -L "$LEGACY_DIR" ) ]]; then
  printf 'ERROR: refusing to migrate symlinked legacy command paths.\n' >&2
  exit 2
fi

printf 'Source: %s\nTarget: %s\n' "$SOURCE_DIR" "$TARGET"
if [[ "$MIGRATE_LEGACY" == 1 ]]; then
  printf 'Legacy migration: %s and %s\n' "$LEGACY_FILE" "$LEGACY_DIR"
else
  printf 'Legacy migration: disabled\n'
fi
if [[ -n "$AGENTS_LINK_PATH" ]]; then
  printf 'Codex discovery link: %s\n' "$AGENTS_LINK_PATH"
else
  printf 'Codex discovery link: skipped (%s)\n' "$AGENTS_LINK_SKIP"
fi
if ((DRY_RUN)); then
  printf 'DRY RUN: validation passed; no files changed.\n'
  exit 0
fi

TARGET_PARENT="$(dirname -- "$TARGET")"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)-$$"
BACKUP_DIR="$CONFIG_DIR/backups/dev/$STAMP"
STAGE_DIR="$TARGET_PARENT/.dev-stage-$STAMP"
HAD_TARGET=0
HAD_LEGACY_FILE=0
HAD_LEGACY_DIR=0
INSTALLED_NEW=0
SUCCESS=0

rollback() {
  local status=$?
  if ((SUCCESS)); then return; fi
  printf 'Install failed; rolling back.\n' >&2
  if [[ -d "$STAGE_DIR" ]]; then rm -rf -- "$STAGE_DIR"; fi
  if ((INSTALLED_NEW)) && [[ -d "$TARGET" && ! -L "$TARGET" ]]; then rm -rf -- "$TARGET"; fi
  if ((HAD_TARGET)) && [[ -d "$BACKUP_DIR/skill" ]]; then mv -- "$BACKUP_DIR/skill" "$TARGET"; fi
  if ((HAD_LEGACY_FILE)) && [[ -f "$BACKUP_DIR/legacy/dev.md" ]]; then
    mkdir -p -- "$(dirname -- "$LEGACY_FILE")"
    mv -- "$BACKUP_DIR/legacy/dev.md" "$LEGACY_FILE"
  fi
  if ((HAD_LEGACY_DIR)) && [[ -d "$BACKUP_DIR/legacy/dev" ]]; then
    mkdir -p -- "$(dirname -- "$LEGACY_DIR")"
    mv -- "$BACKUP_DIR/legacy/dev" "$LEGACY_DIR"
  fi
  exit "$status"
}
trap rollback EXIT

mkdir -p -- "$TARGET_PARENT"
[[ -w "$TARGET_PARENT" ]] || { printf 'ERROR: target parent is not writable: %s\n' "$TARGET_PARENT" >&2; exit 1; }
mkdir -- "$STAGE_DIR"
if ((IS_GIT_CHECKOUT)); then
  # Archive the exact commit already captured and validated above, not
  # HEAD again: re-resolving HEAD here would reopen the race the earlier
  # capture exists to close (see INSTALL_COMMIT's capture site).
  # cd into the stage dir instead of `tar -C`: GNU tar processes backslash
  # escapes in a -C argument, which turns a stage path containing a backslash
  # into a different (nonexistent) directory. The stage path holds the target's
  # parent, which the user chooses.
  "${GIT_ENV_CLEAN[@]}" -C "$SCRIPT_DIR" archive "$INSTALL_COMMIT" -- skills/dev | (cd -- "$STAGE_DIR" && tar -x --strip-components=2)
else
  cp -R -- "$SOURCE_DIR/." "$STAGE_DIR/"
fi
python3 "$VALIDATOR" --skill-dir "$STAGE_DIR"

# Stamp only after the staged (git-archived, still variable-form) payload has
# passed validation, and only on the staged copy that is about to become the
# installed one: the repository, the preflight tree, and the validator's
# variable-form pins are never modified. The stamped value is the final
# absolute install path, not the stage path. TARGET_PARENT exists by now.
TARGET_ABS="$(cd -- "$TARGET_PARENT" && pwd)"
TARGET_ABS="${TARGET_ABS%/}/$(basename -- "$TARGET")"
reject_line_break 'resolved install target' "$TARGET_ABS"
# Byte-exact literal replacement in python3 (already required): the path is
# handed over through the environment and never interpolated into code, argv,
# or a sed/regex replacement, so space, &, |, \, $ and quotes cannot corrupt it.
STAMP_ROOT="$STAGE_DIR" STAMP_VALUE="$TARGET_ABS" python3 - <<'PY'
import os
import sys

needle = b"${CLAUDE_SKILL_DIR}"
value = os.environb[b"STAMP_VALUE"]
root = os.environb[b"STAMP_ROOT"]
stamped = 0
for dirpath, _dirnames, filenames in os.walk(root):
    for name in filenames:
        path = os.path.join(dirpath, name)
        if os.path.islink(path):
            continue
        with open(path, "rb") as handle:
            data = handle.read()
        if needle not in data:
            continue
        data = data.replace(needle, value)
        if needle in data:
            sys.exit("ERROR: stamping left a literal ${CLAUDE_SKILL_DIR} in " + os.fsdecode(path)
                     + "; the install path must not itself contain that text.")
        with open(path, "wb") as handle:
            handle.write(data)
        stamped += 1
print("Stamped %d files with %s" % (stamped, os.fsdecode(value)))
PY

if [[ "${DEV_INSTALL_FAIL_AT:-}" == "after-stamp" ]]; then
  printf 'ERROR: injected failure after stamp\n' >&2
  exit 97
fi

if [[ "${DEV_INSTALL_FAIL_AT:-}" == "after-stage" ]]; then
  printf 'ERROR: injected failure after stage\n' >&2
  exit 97
fi

if [[ -e "$TARGET" ]]; then
  [[ -d "$TARGET" ]] || { printf 'ERROR: target exists and is not a directory: %s\n' "$TARGET" >&2; exit 2; }
  mkdir -p -- "$BACKUP_DIR"
  mv -- "$TARGET" "$BACKUP_DIR/skill"
  HAD_TARGET=1
fi

if [[ "$MIGRATE_LEGACY" == 1 && ( -e "$LEGACY_FILE" || -e "$LEGACY_DIR" ) ]]; then
  mkdir -p -- "$BACKUP_DIR/legacy"
  if [[ -e "$LEGACY_FILE" ]]; then mv -- "$LEGACY_FILE" "$BACKUP_DIR/legacy/dev.md"; HAD_LEGACY_FILE=1; fi
  if [[ -e "$LEGACY_DIR" ]]; then mv -- "$LEGACY_DIR" "$BACKUP_DIR/legacy/dev"; HAD_LEGACY_DIR=1; fi
fi

if [[ "${DEV_INSTALL_FAIL_AT:-}" == "after-backup" ]]; then
  printf 'ERROR: injected failure after backup\n' >&2
  exit 97
fi

mv -- "$STAGE_DIR" "$TARGET"
INSTALLED_NEW=1

if [[ "${DEV_INSTALL_FAIL_AT:-}" == "after-install" ]]; then
  printf 'ERROR: injected failure after install\n' >&2
  exit 97
fi

SUCCESS=1
trap - EXIT
printf 'Installed /dev Skill at %s\n' "$TARGET"
if ((IS_GIT_CHECKOUT)); then
  printf 'Installed from commit %s\n' "$INSTALL_COMMIT"
else
  printf 'Installed from: no git metadata (tarball install)\n'
fi
if [[ -d "$BACKUP_DIR" ]]; then printf 'Previous files backed up at %s\n' "$BACKUP_DIR"; fi

# Codex discovery link. Runs after the install is committed and outside the
# rollback window: a link problem is reported, never fatal, and never undoes
# or blocks the install. Nothing that holds data is overwritten.
link_agents_skill() {
  local link="$AGENTS_LINK_PATH" old_target want have
  if [[ -z "$link" ]]; then
    printf 'Codex discovery link: skipped (%s)\n' "$AGENTS_LINK_SKIP"
    return 0
  fi
  if [[ -L "$link" ]]; then
    old_target="$(readlink -- "$link")" || old_target="?"
    if [[ -e "$link" ]]; then
      want="$(cd -P -- "$TARGET_ABS" && pwd -P)"
      have=""
      if [[ -d "$link" ]]; then have="$(cd -P -- "$link" && pwd -P)"; fi
      if [[ "$have" == "$want" ]]; then
        printf 'Codex discovery link: up to date: %s -> %s\n' "$link" "$old_target"
      else
        printf 'WARNING: Codex discovery link not changed: %s already points to %s; leaving it. Remove it to let the installer link %s.\n' "$link" "$old_target" "$TARGET_ABS" >&2
      fi
      return 0
    fi
    # Dangling: holds no data and would otherwise block the link forever. The
    # check-then-remove below is not atomic: it assumes no concurrent writer
    # swaps this entry in between (accepted for a single-user installer).
    if rm -- "$link" && ln -s -- "$TARGET_ABS" "$link"; then
      printf 'Codex discovery link: replaced dangling link (was -> %s): %s -> %s\n' "$old_target" "$link" "$TARGET_ABS"
    else
      printf 'WARNING: Codex discovery link skipped: could not replace dangling link %s\n' "$link" >&2
    fi
    return 0
  fi
  if [[ -e "$link" ]]; then
    printf 'WARNING: Codex discovery link not created: %s already exists and is not a link; leaving it.\n' "$link" >&2
    return 0
  fi
  if mkdir -p -- "$(dirname -- "$link")" && ln -s -- "$TARGET_ABS" "$link"; then
    printf 'Codex discovery link: created %s -> %s\n' "$link" "$TARGET_ABS"
  else
    printf 'WARNING: Codex discovery link skipped: could not create %s\n' "$link" >&2
  fi
  return 0
}
link_agents_skill
printf 'Restart Claude Code, then invoke /dev.\n'
