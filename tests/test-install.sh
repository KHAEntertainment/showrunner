#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
INSTALLER="$REPO_DIR/install.sh"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/claude-dev-install.XXXXXX")"

cleanup() {
  chmod -R u+w "$TEST_ROOT" 2>/dev/null || true
  rm -rf -- "$TEST_ROOT"
}
trap cleanup EXIT

# The installer links "$HOME/.agents/skills/dev" by default. Point HOME at a
# scratch directory for the whole suite so no case can touch the real
# ~/.agents (or ~/.claude); cases that assert on the link use their own HOME.
export HOME="$TEST_ROOT/home"
mkdir -p "$HOME"
# Nothing the caller exported may steer a case: the installer's config-dir
# default and failure-injection hook are cleared, and the detector case below
# scrubs or sets the Traycer session identifiers itself.
unset CLAUDE_CONFIG_DIR DEV_INSTALL_FAIL_AT

# The installer requires rtk on PATH but never calls it. Give the suite its own
# stub so it needs no host rtk (and so the release-gate workflow no longer has
# to provide one), and so any real invocation fails loudly instead of passing
# silently (Issue #138, F4).
stub_bin="$TEST_ROOT/stubbin"
mkdir -p "$stub_bin"
printf '%s\n' '#!/bin/sh' 'printf "unexpected rtk invocation: %s\n" "$*" >&2' 'exit 99' >"$stub_bin/rtk"
chmod +x "$stub_bin/rtk"
export PATH="$stub_bin:$PATH"

pass_count=0
# Each case starts with no discovery link under the suite HOME, so cases that
# do not assert on the link never see (or print) a leftover from the previous one.
skip() { printf 'SKIP: %s (%s)\n' "$1" "$2"; }
pass() { printf 'PASS: %s\n' "$1"; pass_count=$((pass_count + 1)); rm -rf -- "$HOME/.agents"; }
fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }
expect_file() { [[ -f "$1" ]] || fail "missing file $1"; }
expect_absent() { [[ ! -e "$1" ]] || fail "unexpected path $1"; }

# Builds a scratch PATH containing everything reachable on the real PATH
# except the named tool, so a test can prove "X is unavailable" without
# actually uninstalling anything on the host.
build_path_without() {
  local exclude="$1" scratch dir target base
  scratch="$(mktemp -d "$TEST_ROOT/fakebin-no-$exclude.XXXXXX")"
  local saved_ifs="$IFS"
  IFS=':'
  for dir in $PATH; do
    IFS="$saved_ifs"
    [[ -d "$dir" ]] || continue
    for target in "$dir"/*; do
      [[ -x "$target" ]] || continue
      base="$(basename -- "$target")"
      [[ "$base" == "$exclude" ]] && continue
      [[ -e "$scratch/$base" ]] && continue
      ln -s -- "$target" "$scratch/$base" 2>/dev/null || true
    done
    IFS=':'
  done
  IFS="$saved_ifs"
  printf '%s\n' "$scratch"
}

# Replaces the stamped absolute path $2 with the variable form in every file
# under $1 (byte-exact, path via the environment), undoing the install stamp.
unstamp_tree() {
  UNSTAMP_ROOT="$1" UNSTAMP_VALUE="$2" python3 - <<'PY'
import os
value = os.environb[b"UNSTAMP_VALUE"]
for dirpath, _dirs, files in os.walk(os.environb[b"UNSTAMP_ROOT"]):
    for name in files:
        path = os.path.join(dirpath, name)
        with open(path, "rb") as handle:
            data = handle.read()
        if value in data:
            with open(path, "wb") as handle:
                handle.write(data.replace(value, b"${CLAUDE_SKILL_DIR}"))
PY
}

# Asserts the installed Skill at $1 has no literal ${CLAUDE_SKILL_DIR} left and
# that every path stamped as "$1/<relpath>" names an existing file or
# directory. Prints how many stamped paths it resolved.
check_stamped_tree() {
  local root="$1"
  # shellcheck disable=SC2016 # literal text to grep for, not expansion
  if grep -rqF '${CLAUDE_SKILL_DIR}' -- "$root"; then
    fail "literal \${CLAUDE_SKILL_DIR} remains under $root"
  fi
  CHECK_ROOT="$root" python3 - <<'PY' || fail "a stamped path under $root does not exist"
import os
import re
import sys
root = os.environ["CHECK_ROOT"]
pattern = re.compile(re.escape(root) + r"((?:/[A-Za-z0-9_.-]+)*)")
checked = 0
missing = []
for dirpath, _dirs, files in os.walk(root):
    for name in files:
        with open(os.path.join(dirpath, name), encoding="utf-8") as handle:
            text = handle.read()
        for match in pattern.finditer(text):
            rel = match.group(1).rstrip(".")
            checked += 1
            if not os.path.exists(root + rel):
                missing.append(root + rel)
if missing or checked == 0:
    sys.exit("stamped paths: checked=%d missing=%s" % (checked, sorted(set(missing))))
PY
}

# Fresh installation, compatibility argument, and path containing spaces.
fresh="$TEST_ROOT/fresh config"
bash "$INSTALLER" --config-dir "$fresh" --lang=en >/dev/null
expect_file "$fresh/skills/dev/SKILL.md"
expect_file "$fresh/skills/dev/phases/phase3.5.md"
expect_file "$fresh/skills/dev/phases/external-review.md"
expect_file "$fresh/skills/dev/phases/phase5.md"
expect_file "$fresh/skills/dev/scripts/inspect_external_reviews.py"
expect_file "$fresh/skills/dev/scripts/detect_execution_backend.py"
expect_file "$fresh/skills/dev/scripts/traycer_cli.py"
expect_file "$fresh/skills/dev/backends/contract.md"
expect_file "$fresh/skills/dev/backends/claude-native.md"
expect_file "$fresh/skills/dev/backends/traycer.md"
expect_file "$fresh/skills/dev/agents/report-back.md"
expect_file "$fresh/skills/dev/agents/reviewer.md"
expect_file "$fresh/skills/dev/templates/DEV_STATE_TEMPLATE.md"
pass "fresh install with path spaces"

# Dry run must not create the target.
dry="$TEST_ROOT/dry run config"
bash "$INSTALLER" --config-dir "$dry" --lang en --dry-run >/dev/null
expect_absent "$dry"
pass "dry run is non-mutating"

# English-only rejection must happen before mutation.
invalid="$TEST_ROOT/invalid language"
if bash "$INSTALLER" --config-dir "$invalid" --lang zh >/dev/null 2>&1; then fail "Chinese install unexpectedly succeeded"; fi
expect_absent "$invalid"
pass "unsupported language rejected before mutation"

# Explicit target is isolated and keeps a legacy command by default.
isolated_config="$TEST_ROOT/isolated config"
isolated_target="$TEST_ROOT/custom target/dev"
mkdir -p "$isolated_config/commands"
printf 'legacy\n' >"$isolated_config/commands/dev.md"
bash "$INSTALLER" --config-dir "$isolated_config" --target "$isolated_target" >/dev/null
expect_file "$isolated_target/SKILL.md"
expect_file "$isolated_config/commands/dev.md"
pass "explicit target does not migrate legacy command"

# Default target migrates legacy command files into a timestamped backup.
legacy="$TEST_ROOT/legacy config"
mkdir -p "$legacy/commands/dev"
printf 'legacy entry\n' >"$legacy/commands/dev.md"
printf 'legacy phase\n' >"$legacy/commands/dev/phase.md"
bash "$INSTALLER" --config-dir "$legacy" >/dev/null
expect_file "$legacy/skills/dev/SKILL.md"
expect_absent "$legacy/commands/dev.md"
expect_absent "$legacy/commands/dev"
legacy_backup="$(find "$legacy/backups/dev" -type f -name dev.md -print -quit)"
[[ -n "$legacy_backup" ]] || fail "legacy command backup missing"
pass "legacy command migration and backup"

# --keep-legacy must leave legacy command files alone on a default install
# (which otherwise migrates them) and must not create a backup directory
# (Issue #138, F1: inverting --keep-legacy to MIGRATE_LEGACY=1 escaped the
# suite before this case existed).
keep_legacy="$TEST_ROOT/keep legacy config"
mkdir -p "$keep_legacy/commands/dev"
printf 'legacy entry\n' >"$keep_legacy/commands/dev.md"
printf 'legacy phase\n' >"$keep_legacy/commands/dev/phase.md"
keep_legacy_output="$(bash "$INSTALLER" --config-dir "$keep_legacy" --keep-legacy)"
expect_file "$keep_legacy/skills/dev/SKILL.md"
expect_file "$keep_legacy/commands/dev.md"
expect_file "$keep_legacy/commands/dev/phase.md"
expect_absent "$keep_legacy/backups"
grep -qF 'Legacy migration: disabled' <<<"$keep_legacy_output" || fail "--keep-legacy install did not report migration as disabled"
pass "--keep-legacy leaves legacy commands and creates no backup"

# A rerun replaces the Skill and backs up the previous version.
printf 'old marker\n' >"$legacy/skills/dev/old-marker.txt"
bash "$INSTALLER" --config-dir "$legacy" >/dev/null
expect_absent "$legacy/skills/dev/old-marker.txt"
old_marker="$(find "$legacy/backups/dev" -type f -name old-marker.txt -print -quit)"
[[ -n "$old_marker" ]] || fail "previous Skill backup missing on rerun"
pass "idempotent rerun with previous-version backup"

# Failure after backup must restore both existing Skill and legacy command.
rollback="$TEST_ROOT/rollback config"
mkdir -p "$rollback/skills/dev" "$rollback/commands/dev"
printf 'old skill\n' >"$rollback/skills/dev/old.txt"
printf 'legacy entry\n' >"$rollback/commands/dev.md"
printf 'legacy phase\n' >"$rollback/commands/dev/old-phase.md"
if DEV_INSTALL_FAIL_AT=after-backup bash "$INSTALLER" --config-dir "$rollback" >/dev/null 2>&1; then fail "injected failure unexpectedly succeeded"; fi
expect_file "$rollback/skills/dev/old.txt"
expect_file "$rollback/commands/dev.md"
expect_file "$rollback/commands/dev/old-phase.md"
pass "rollback after backup"

# Symlink targets are refused without changing the link destination.
symlink_case="$TEST_ROOT/symlink case"
mkdir -p "$symlink_case/config/skills" "$symlink_case/real-dev"
printf 'sentinel\n' >"$symlink_case/real-dev/sentinel.txt"
ln -s "$symlink_case/real-dev" "$symlink_case/config/skills/dev"
if bash "$INSTALLER" --config-dir "$symlink_case/config" >/dev/null 2>&1; then fail "symlink target unexpectedly accepted"; fi
expect_file "$symlink_case/real-dev/sentinel.txt"
pass "symlink target refusal"

# --- Issue #138, F3: the installer's refusal paths -------------------------
# Every row below must exit non-zero with the installer's own documented
# message and must not create or delete anything. HOME always points at the
# suite's scratch home (never the real one), and a sentinel tree snapshotted
# before and after each run proves nothing was written or removed.
refusal_root="$TEST_ROOT/refusal root"
refusal_home="$TEST_ROOT/refusal home"
mkdir -p "$refusal_root/commands/dev" "$refusal_home"
printf 'sentinel\n' >"$refusal_root/commands/dev/sentinel.txt"
# Snapshot the config tree and the HOME the installer runs with: a refusal that
# leaked a file into either would otherwise go unseen.
refusal_snapshot() { find "$refusal_root" "$refusal_home" -print | LC_ALL=C sort; }
expect_refusal() {
  local label="$1" expected="$2" rc=0 out before after
  shift 2
  before="$(refusal_snapshot)"
  out="$(HOME="$refusal_home" bash "$INSTALLER" "$@" 2>&1)" || rc=$?
  after="$(refusal_snapshot)"
  ((rc != 0)) || fail "$label unexpectedly succeeded"
  [[ "$rc" == 2 ]] || fail "$label exited $rc (expected 2)"
  grep -qF -- "$expected" <<<"$out" || fail "$label did not report '$expected': $out"
  [[ "$before" == "$after" ]] || fail "$label changed the filesystem"
}

expect_refusal "unsafe target /" "ERROR: unsafe install target: /" \
  --config-dir "$refusal_root" --target /
expect_refusal "unsafe target \$HOME" "ERROR: unsafe install target: $refusal_home" \
  --config-dir "$refusal_root" --target "$refusal_home"
expect_refusal "unsafe target equal to the config dir" "ERROR: unsafe install target: $refusal_root" \
  --config-dir "$refusal_root" --target "$refusal_root"
expect_refusal "target not ending in /dev" \
  "ERROR: --target must be the exact dev Skill directory and end in /dev: $refusal_root/not-a-dev" \
  --config-dir "$refusal_root" --target "$refusal_root/not-a-dev"
mkdir -p "$refusal_root/file-target"
printf 'not a directory\n' >"$refusal_root/file-target/dev"
expect_refusal "target exists as a file" \
  "ERROR: target exists and is not a directory: $refusal_root/file-target/dev" \
  --config-dir "$refusal_root" --target "$refusal_root/file-target/dev"
expect_refusal "missing --target value" "ERROR: --target requires a value" \
  --config-dir "$refusal_root" --target
expect_refusal "missing --config-dir value" "ERROR: --config-dir requires a value" \
  --config-dir
expect_refusal "missing --lang value" "ERROR: --lang requires a value" \
  --config-dir "$refusal_root" --lang
expect_refusal "unknown argument" "ERROR: unknown argument: --bogus-argument" \
  --config-dir "$refusal_root" --bogus-argument
expect_absent "$refusal_home/.agents"
expect_absent "$HOME/.agents"
pass "installer refusals exit 2 with their documented message and change nothing"

# Missing distribution files fail preflight without creating a target.
# No .git here: this simulates a broken release-tarball-style copy, where
# whatever is on disk is what would ship, so a genuinely missing file must
# be caught (contrast with the git-mode "committed tree is still rejected"
# case further down, which covers the analogous git-mode failure).
broken="$TEST_ROOT/broken distribution"
mkdir -p "$broken"
cp -R "$REPO_DIR/." "$broken/repo"
rm -rf -- "$broken/repo/.git"
rm -- "$broken/repo/skills/dev/phases/phase5.md"
if bash "$broken/repo/install.sh" --config-dir "$broken/config" >/dev/null 2>&1; then fail "broken distribution unexpectedly installed"; fi
expect_absent "$broken/config"
pass "missing source file rejected before mutation"

# Dirty checkout: uncommitted edits to tracked files and ignored/untracked
# files under skills/dev must not ship (Issue #44).
dirty_source="$TEST_ROOT/dirty-source"
mkdir -p "$dirty_source"
cp -R -- "$REPO_DIR/." "$dirty_source/repo"
printf '\n<!-- local edit: must not ship -->\n' >>"$dirty_source/repo/skills/dev/SKILL.md"
mkdir -p "$dirty_source/repo/skills/dev/scripts/__pycache__"
printf 'compiled\n' >"$dirty_source/repo/skills/dev/scripts/__pycache__/x.pyc"
dirty_target="$TEST_ROOT/dirty target"
bash "$dirty_source/repo/install.sh" --config-dir "$dirty_target" --lang en >/dev/null
expect_file "$dirty_target/skills/dev/SKILL.md"
if grep -q 'local edit: must not ship' "$dirty_target/skills/dev/SKILL.md"; then
  fail "uncommitted edit to a tracked file shipped in the install"
fi
expect_absent "$dirty_target/skills/dev/scripts/__pycache__"
pass "dirty checkout excludes uncommitted edits and ignored files"

# The converse of the exclusion case above: an uncommitted *deletion* of a
# required tracked file must not block installing the perfectly valid
# committed tree. Preflight has to validate what will actually be
# installed (the committed content at HEAD), not the mutable working tree
# (Issue #44 follow-up).
dirty_deletion_source="$TEST_ROOT/dirty-deletion-source"
mkdir -p "$dirty_deletion_source"
cp -R -- "$REPO_DIR/." "$dirty_deletion_source/repo"
rm -- "$dirty_deletion_source/repo/skills/dev/phases/phase5.md"
dirty_deletion_target="$TEST_ROOT/dirty-deletion target"
bash "$dirty_deletion_source/repo/install.sh" --config-dir "$dirty_deletion_target" --lang en >/dev/null
expect_file "$dirty_deletion_target/skills/dev/phases/phase5.md"
pass "uncommitted deletion of a tracked file does not block installing the committed tree"

# The other side of that fix: a file *actually* missing from the committed
# tree (removed and committed, not just deleted on disk) must still be
# caught by preflight in git mode, before any mutation — the fix above
# must not have quietly turned preflight validation off for git checkouts.
committed_broken_source="$TEST_ROOT/committed-broken-source"
git clone --quiet -- "$REPO_DIR" "$committed_broken_source"
git -c user.name=test -c user.email=test@example.com \
  -C "$committed_broken_source" rm --quiet -- skills/dev/phases/phase5.md
git -c user.name=test -c user.email=test@example.com \
  -C "$committed_broken_source" commit --quiet -m "remove a required file"
committed_broken_target="$TEST_ROOT/committed-broken target"
if bash "$committed_broken_source/install.sh" --config-dir "$committed_broken_target" --lang en >/dev/null 2>&1; then
  fail "install with a required file missing from the committed tree unexpectedly succeeded"
fi
expect_absent "$committed_broken_target"
pass "a required file missing from the committed tree is still rejected before mutation"

# A dangling .git symlink is still a .git entry: -e alone follows the link
# and reports false when its target doesn't exist, which would otherwise
# read as "no git metadata" and take the copy path, shipping whatever is
# on disk (Issue #44 follow-up).
dangling_source="$TEST_ROOT/dangling-git-source"
mkdir -p "$dangling_source"
cp -R -- "$REPO_DIR/." "$dangling_source/repo"
rm -rf -- "$dangling_source/repo/.git"
ln -s -- "/nonexistent/path/to/a/gitdir" "$dangling_source/repo/.git"
mkdir -p "$dangling_source/repo/skills/dev/scripts/__pycache__"
printf 'compiled\n' >"$dangling_source/repo/skills/dev/scripts/__pycache__/x.pyc"
dangling_target="$TEST_ROOT/dangling-git target"
if bash "$dangling_source/repo/install.sh" --config-dir "$dangling_target" --lang en >/dev/null 2>&1; then
  fail "install with a dangling .git symlink unexpectedly succeeded"
fi
expect_absent "$dangling_target"
pass "dangling .git symlink aborts instead of falling back to the copy path"

# No .git source: falls back to the working-tree copy and reports tarball
# provenance instead of a commit (Issue #44, ADR-007 tarball/libexec case).
nogit_source="$TEST_ROOT/nogit-source"
mkdir -p "$nogit_source"
cp -R -- "$REPO_DIR/." "$nogit_source/repo"
rm -rf -- "$nogit_source/repo/.git"
nogit_target="$TEST_ROOT/nogit target"
nogit_output="$(bash "$nogit_source/repo/install.sh" --config-dir "$nogit_target" --lang en)"
expect_file "$nogit_target/skills/dev/SKILL.md"
if ! grep -q 'Installed from: no git metadata (tarball install)' <<<"$nogit_output"; then
  fail "no-.git install did not report tarball provenance"
fi
pass "no-.git source installs via the copy path with tarball provenance"

# A source with no .git of its own, sitting underneath an unrelated git
# checkout, must not be misclassified as that ancestor's repo: it has to
# install via the copy path too, not attempt (and fail) a git archive of
# the ancestor's unrelated tree (Issue #44 follow-up).
nested_parent="$TEST_ROOT/nested-parent"
mkdir -p "$nested_parent"
git init --quiet -- "$nested_parent"
# -c user.name/user.email keep this fixture hermetic: a CI runner with no
# git identity configured (no ~/.gitconfig, no GECOS full name) otherwise
# fails this commit with "Please tell me who you are."
git -c user.name=test -c user.email=test@example.com \
  -C "$nested_parent" commit --quiet --allow-empty -m "unrelated ancestor root commit"
mkdir -p "$nested_parent/nested"
cp -R -- "$REPO_DIR/." "$nested_parent/nested/repo"
rm -rf -- "$nested_parent/nested/repo/.git"
nested_target="$TEST_ROOT/nested target"
nested_output="$(bash "$nested_parent/nested/repo/install.sh" --config-dir "$nested_target" --lang en)"
expect_file "$nested_target/skills/dev/SKILL.md"
if ! grep -q 'Installed from: no git metadata (tarball install)' <<<"$nested_output"; then
  fail "nested no-own-.git install did not report tarball provenance"
fi
pass "nested source with no own .git installs via the copy path"

# A source with its own .git but no git binary on PATH must abort with an
# actionable error and install nothing — never silently fall back to the
# copy path, which would ship possibly-dirty working-tree content while
# looking, from the outside, exactly like the safe case (Issue #44
# follow-up).
no_git_bin_path="$(build_path_without git)"
no_git_bin_target="$TEST_ROOT/no-git-bin target"
if PATH="$no_git_bin_path" bash "$INSTALLER" --config-dir "$no_git_bin_target" --lang en >/dev/null 2>&1; then
  fail "install unexpectedly succeeded with git unavailable in a git checkout"
fi
expect_absent "$no_git_bin_target"
pass "git checkout with git binary unavailable aborts and installs nothing"

# A genuine git checkout with tar unavailable must abort the same way,
# rather than silently shipping the working tree with false git provenance
# (Issue #44 follow-up; PowerShell has the mirrored case already).
no_tar_bin_path="$(build_path_without tar)"
no_tar_bin_target="$TEST_ROOT/no-tar-bin target"
if PATH="$no_tar_bin_path" bash "$INSTALLER" --config-dir "$no_tar_bin_target" --lang en >/dev/null 2>&1; then
  fail "install unexpectedly succeeded with tar unavailable in a git checkout"
fi
expect_absent "$no_tar_bin_target"
pass "git checkout with tar unavailable aborts and installs nothing"

# The rtk presence gate is a PATH check only: the installer never runs rtk.
# With rtk absent it must abort with its documented message and install
# nothing (Issue #138, F4).
no_rtk_bin_path="$(build_path_without rtk)"
no_rtk_target="$TEST_ROOT/no-rtk target"
no_rtk_rc=0
no_rtk_output="$(PATH="$no_rtk_bin_path" bash "$INSTALLER" --config-dir "$no_rtk_target" --lang en 2>&1)" || no_rtk_rc=$?
[[ "$no_rtk_rc" == 1 ]] || fail "install without rtk exited $no_rtk_rc (expected 1)"
grep -qF 'ERROR: RTK is required by this customized /dev workflow.' <<<"$no_rtk_output" \
  || fail "install without rtk did not report the documented message: $no_rtk_output"
expect_absent "$no_rtk_target"
pass "rtk absent from PATH aborts with the documented message and installs nothing"

# Clean checkout: the installed tree matches a plain git archive of HEAD,
# and the install reports the staged commit (Issue #44).
clean_target="$TEST_ROOT/clean target"
clean_output="$(bash "$INSTALLER" --config-dir "$clean_target" --lang en)"
expected_commit="$(git -C "$REPO_DIR" rev-parse HEAD)"
if ! grep -q "Installed from commit $expected_commit" <<<"$clean_output"; then
  fail "clean checkout install did not report the staged commit"
fi
archive_check="$TEST_ROOT/archive-check"
mkdir -p "$archive_check"
git -C "$REPO_DIR" archive HEAD -- skills/dev | tar -x -C "$archive_check" --strip-components=2
# The installed copy is stamped, so it differs from the archive only by the
# absolute path standing in for the variable. Undo the stamp on a copy and the
# trees must be identical: nothing but the stamp differs, and no working-tree
# content shipped.
unstamped="$TEST_ROOT/unstamped"
cp -R -- "$clean_target/skills/dev" "$unstamped"
unstamp_tree "$unstamped" "$(cd -- "$clean_target/skills" && pwd)/dev"
diff -r "$archive_check" "$unstamped" >/dev/null || fail "installed tree differs from git archive of HEAD beyond the stamp"
pass "clean checkout install matches git archive (modulo stamp) and reports commit provenance"

# Static guard against the provenance race regressing: both archive calls
# must pin the commit already captured and validated (INSTALL_COMMIT), not
# re-resolve HEAD at staging time, which would reopen a window where a
# concurrent commit could make the archived content disagree with the
# commit the install reports (Issue #44 follow-up).
# shellcheck disable=SC2016 # literal source text to grep for, not expansion
if grep -Eq 'git -C "\$SCRIPT_DIR" archive HEAD\b' "$INSTALLER"; then
  fail "install.sh archives HEAD directly instead of the captured INSTALL_COMMIT"
fi
# shellcheck disable=SC2016 # literal source text to grep for, not expansion
if ! grep -Fq 'archive "$INSTALL_COMMIT"' "$INSTALLER"; then
  fail "install.sh does not archive the captured INSTALL_COMMIT"
fi
pass "install.sh archives the captured commit, not HEAD, at staging time"

# GIT_DIR/GIT_WORK_TREE/GIT_COMMON_DIR inherited from the caller's
# environment override `-C`'s repository discovery entirely, so without
# neutralizing them a perfectly valid own-.git checkout could silently
# validate, archive, and install a completely different repository's
# committed tree while reporting *its* commit (Issue #44 follow-up).
# GIT_COMMON_DIR is the linked-worktree analog of GIT_DIR; poisoning it
# alongside the other two is defense in depth even though it did not
# independently redirect this worktree-less checkout. Point all three at
# a disposable repo carrying a planted marker file and confirm the real
# source's own tree and commit are what actually gets installed.
env_hijack_alt="$TEST_ROOT/env-hijack-alt"
mkdir -p "$env_hijack_alt"
cp -R -- "$REPO_DIR/skills" "$env_hijack_alt/skills"
rm -rf -- "$env_hijack_alt/.git"
git init --quiet -- "$env_hijack_alt"
printf 'planted by an unrelated repo; must never ship\n' >"$env_hijack_alt/skills/dev/ENV_HIJACK_MARKER.txt"
git -C "$env_hijack_alt" add -A
git -c user.name=test -c user.email=test@example.com \
  -C "$env_hijack_alt" commit --quiet -m "alt repo commit carrying a planted marker"
env_hijack_target="$TEST_ROOT/env-hijack target"
expected_real_commit="$(git -C "$REPO_DIR" rev-parse HEAD)"
env_hijack_output="$(GIT_DIR="$env_hijack_alt/.git" GIT_WORK_TREE="$env_hijack_alt" GIT_COMMON_DIR="$env_hijack_alt/.git" \
  bash "$INSTALLER" --config-dir "$env_hijack_target" --lang en)"
expect_file "$env_hijack_target/skills/dev/SKILL.md"
expect_absent "$env_hijack_target/skills/dev/ENV_HIJACK_MARKER.txt"
if ! grep -q "Installed from commit $expected_real_commit" <<<"$env_hijack_output"; then
  fail "install reported the wrong commit under an inherited GIT_DIR/GIT_WORK_TREE/GIT_COMMON_DIR"
fi
pass "inherited GIT_DIR/GIT_WORK_TREE/GIT_COMMON_DIR cannot redirect install to another repository"

# --- Issue #88: install-time stamping and the Codex discovery link ---------

# Substitution: no literal left, every stamped path resolves, and the
# detector executes from the installed copy.
stamp_config="$TEST_ROOT/stamp config"
stamp_home="$TEST_ROOT/stamp home"
mkdir -p "$stamp_home"
HOME="$stamp_home" bash "$INSTALLER" --config-dir "$stamp_config" >/dev/null
stamp_root="$(cd -- "$stamp_config/skills" && pwd)/dev"
check_stamped_tree "$stamp_root"
# The detector's answer depends on TRAYCER_AGENT_ID / TRAYCER_EPIC_ID, so both
# outcomes are pinned explicitly: identifiers scrubbed -> exit 2, incomplete;
# synthetic identifiers -> exit 0, traycer. The caller's own values never count.
# The detector also falls back to <worktree root>/.agent/traycer.env, where the
# root is the nearest directory above the working directory holding a .git
# entry. Run it from a scratch directory that is its own root (an empty .git
# marker) so no identity file from the caller's checkout can be found.
detector="$stamp_root/scripts/detect_execution_backend.py"
detector_cwd="$TEST_ROOT/detector cwd"
mkdir -p "$detector_cwd/.git"
detector_rc=0
detector_output="$(cd -- "$detector_cwd" && env -u TRAYCER_AGENT_ID -u TRAYCER_EPIC_ID python3 "$detector")" || detector_rc=$?
[[ "$detector_rc" == 2 ]] || fail "installed detector exited $detector_rc without session identifiers (expected 2)"
DETECTOR_JSON="$detector_output" python3 -c '
import json, os
d = json.loads(os.environ["DETECTOR_JSON"])
assert d["detection_status"] == "incomplete" and d["execution_backend"] == "incomplete", d
' || fail "installed detector did not report incomplete without session identifiers: $detector_output"
detector_rc=0
detector_output="$(cd -- "$detector_cwd" && env TRAYCER_AGENT_ID=agent-under-test TRAYCER_EPIC_ID=epic-under-test python3 "$detector")" || detector_rc=$?
[[ "$detector_rc" == 0 ]] || fail "installed detector exited $detector_rc with session identifiers (expected 0)"
DETECTOR_JSON="$detector_output" python3 -c '
import json, os
d = json.loads(os.environ["DETECTOR_JSON"])
assert d["detection_status"] == "ready" and d["execution_backend"] == "traycer", d
assert d["traycer_agent_id"] == "agent-under-test" and d["traycer_epic_id"] == "epic-under-test", d
' || fail "installed detector did not report traycer with session identifiers: $detector_output"
pass "installed copy has no literal variable, every stamped path resolves, detector answers both ways"

# The repository keeps the variable form: stamping touches only the installed copy.
# shellcheck disable=SC2016 # literal text to grep for, not expansion
grep -rqF '${CLAUDE_SKILL_DIR}' -- "$REPO_DIR/skills/dev" || fail "repository payload lost its variable form"
python3 "$REPO_DIR/scripts/validate_skill.py" --skill-dir "$REPO_DIR/skills/dev" >/dev/null || fail "repository payload no longer validates"
pass "repository payload keeps the variable form and still validates"

# Byte-exact stamp for a path with a space, &, |, a backslash, $, quotes and a
# sed-style back-reference.
# shellcheck disable=SC2016 # deliberately literal special characters
weird_config="$TEST_ROOT"'/we ird & pipe | back\slash $x '"'"'q'"'"' "dq" \1 &amp'
weird_home="$TEST_ROOT/weird home"
mkdir -p "$weird_home"
HOME="$weird_home" bash "$INSTALLER" --config-dir "$weird_config" >/dev/null
weird_root="$(cd -- "$weird_config/skills" && pwd)/dev"
check_stamped_tree "$weird_root"
grep -qF -- "$weird_root/scripts/detect_execution_backend.py" "$weird_root/SKILL.md" || fail "special-character path was not stamped byte-exact"
[[ "$(readlink -- "$weird_home/.agents/skills/dev")" == "$weird_root" ]] || fail "link target is not the byte-exact special-character path"
pass "path with space, &, |, backslash, \$, quotes is stamped and linked byte-exact"

# A relative --target is stamped as an absolute path.
rel_base="$TEST_ROOT/relative target base"
mkdir -p "$rel_base"
(cd -- "$rel_base" && bash "$INSTALLER" --config-dir "$TEST_ROOT/rel config" --target rel/dev >/dev/null)
check_stamped_tree "$(cd -- "$rel_base/rel" && pwd)/dev"
pass "relative --target is stamped as an absolute path"

# A target path that itself contains the variable text cannot be stamped
# faithfully: abort before mutation rather than leave a literal behind.
# shellcheck disable=SC2016 # deliberately literal variable text
token_config="$TEST_ROOT"'/tok ${CLAUDE_SKILL_DIR} cfg'
if HOME="$stamp_home" bash "$INSTALLER" --config-dir "$token_config" >/dev/null 2>&1; then fail "install into a path containing the variable text unexpectedly succeeded"; fi
expect_absent "$token_config/skills/dev"
[[ -z "$(find "$token_config" -name '.dev-stage-*' -print -quit 2>/dev/null)" ]] || fail "stage directory left behind after stamp abort"
pass "target path containing the variable text is rejected without residue"

# Idempotence: a rerun over an existing install yields the identical tree,
# keeps backing up the previous version, and leaves the link alone.
idem_config="$TEST_ROOT/idem config"
idem_home="$TEST_ROOT/idem home"
mkdir -p "$idem_home"
HOME="$idem_home" bash "$INSTALLER" --config-dir "$idem_config" >/dev/null
cp -R -- "$idem_config/skills/dev" "$TEST_ROOT/idem-first"
idem_output="$(HOME="$idem_home" bash "$INSTALLER" --config-dir "$idem_config")"
diff -r "$TEST_ROOT/idem-first" "$idem_config/skills/dev" >/dev/null || fail "rerun produced a different tree than the first install"
[[ -n "$(find "$idem_config/backups/dev" -type f -name SKILL.md -print -quit)" ]] || fail "rerun did not back up the previous install"
grep -q 'Codex discovery link: up to date' <<<"$idem_output" || fail "rerun did not report the link as up to date"
pass "rerun is idempotent, still backs up, and keeps the link"

# Link: created on a default install, pointing at the installed Skill.
link_home="$TEST_ROOT/link home"
link_config="$TEST_ROOT/link config"
mkdir -p "$link_home"
link_output="$(HOME="$link_home" bash "$INSTALLER" --config-dir "$link_config")"
link_root="$(cd -- "$link_config/skills" && pwd)/dev"
[[ -L "$link_home/.agents/skills/dev" ]] || fail "default install did not create the discovery link"
[[ "$(readlink -- "$link_home/.agents/skills/dev")" == "$link_root" ]] || fail "discovery link does not point at the installed Skill"
[[ -f "$link_home/.agents/skills/dev/SKILL.md" ]] || fail "discovery link does not resolve to the Skill"
grep -q 'Codex discovery link: created' <<<"$link_output" || fail "link creation was not reported"
pass "default install creates the discovery link to the installed Skill"

# Link: a real directory at the path is reported and left untouched.
dir_home="$TEST_ROOT/dir home"
mkdir -p "$dir_home/.agents/skills/dev"
printf 'keep\n' >"$dir_home/.agents/skills/dev/sentinel.txt"
dir_output="$(HOME="$dir_home" bash "$INSTALLER" --config-dir "$TEST_ROOT/dir config" 2>&1)" || fail "install failed because a real directory sat at the link path"
[[ ! -L "$dir_home/.agents/skills/dev" ]] || fail "a real directory was replaced by a link"
expect_file "$dir_home/.agents/skills/dev/sentinel.txt"
grep -q 'already exists and is not a link' <<<"$dir_output" || fail "real directory at the link path was not reported"
expect_file "$TEST_ROOT/dir config/skills/dev/SKILL.md"
pass "a real directory at the link path is reported and left untouched"

# Link: a regular file at the path is also left untouched.
file_home="$TEST_ROOT/file home"
mkdir -p "$file_home/.agents/skills"
printf 'keep\n' >"$file_home/.agents/skills/dev"
HOME="$file_home" bash "$INSTALLER" --config-dir "$TEST_ROOT/file config" >/dev/null 2>&1 || fail "install failed because a file sat at the link path"
[[ -f "$file_home/.agents/skills/dev" && ! -L "$file_home/.agents/skills/dev" ]] || fail "a file at the link path was replaced"
pass "a file at the link path is left untouched"

# Link: a symlink to a different, existing directory is reported and left.
foreign_home="$TEST_ROOT/foreign home"
foreign_dir="$TEST_ROOT/foreign skill"
mkdir -p "$foreign_home/.agents/skills" "$foreign_dir"
ln -s -- "$foreign_dir" "$foreign_home/.agents/skills/dev"
foreign_output="$(HOME="$foreign_home" bash "$INSTALLER" --config-dir "$TEST_ROOT/foreign config" 2>&1)" || fail "install failed because a foreign link sat at the link path"
[[ "$(readlink -- "$foreign_home/.agents/skills/dev")" == "$foreign_dir" ]] || fail "a link to another existing directory was overwritten"
grep -q 'Codex discovery link not changed' <<<"$foreign_output" || fail "foreign link was not reported"
pass "a link to another existing directory is reported and left untouched"

# Link: a dangling symlink holds no data and is replaced, with a report.
dangling_home="$TEST_ROOT/dangling home"
mkdir -p "$dangling_home/.agents/skills"
ln -s -- "$TEST_ROOT/deleted scratch install/dev" "$dangling_home/.agents/skills/dev"
dangling_link_config="$TEST_ROOT/dangling link config"
dangling_link_output="$(HOME="$dangling_home" bash "$INSTALLER" --config-dir "$dangling_link_config")"
[[ "$(readlink -- "$dangling_home/.agents/skills/dev")" == "$(cd -- "$dangling_link_config/skills" && pwd)/dev" ]] || fail "dangling link was not replaced"
grep -q 'replaced dangling link (was -> ' <<<"$dangling_link_output" || fail "dangling link replacement was not reported"
pass "a dangling link is replaced and reported"

# Link: opt-out creates nothing and leaves an existing link alone.
optout_home="$TEST_ROOT/optout home"
mkdir -p "$optout_home"
HOME="$optout_home" bash "$INSTALLER" --config-dir "$TEST_ROOT/optout config" --no-agents-link >/dev/null
expect_absent "$optout_home/.agents"
optout_kept_home="$TEST_ROOT/optout kept home"
mkdir -p "$optout_kept_home/.agents/skills" "$TEST_ROOT/optout other"
ln -s -- "$TEST_ROOT/optout other" "$optout_kept_home/.agents/skills/dev"
HOME="$optout_kept_home" bash "$INSTALLER" --config-dir "$TEST_ROOT/optout kept config" --no-agents-link >/dev/null
[[ "$(readlink -- "$optout_kept_home/.agents/skills/dev")" == "$TEST_ROOT/optout other" ]] || fail "--no-agents-link touched an existing link"
pass "--no-agents-link creates and touches nothing"

# Link: an explicit --target is an isolated install; dry run never links.
iso_home="$TEST_ROOT/iso home"
mkdir -p "$iso_home"
HOME="$iso_home" bash "$INSTALLER" --config-dir "$TEST_ROOT/iso config" --target "$TEST_ROOT/iso target/dev" >/dev/null
expect_absent "$iso_home/.agents"
check_stamped_tree "$(cd -- "$TEST_ROOT/iso target" && pwd)/dev"
HOME="$iso_home" bash "$INSTALLER" --config-dir "$TEST_ROOT/iso dry config" --dry-run >/dev/null
expect_absent "$iso_home/.agents"
pass "explicit --target and --dry-run do not create the link"

# Failure after stamping leaves the previous install untouched and no residue.
stampfail_config="$TEST_ROOT/stampfail config"
mkdir -p "$stampfail_config/skills/dev"
printf 'old skill\n' >"$stampfail_config/skills/dev/old.txt"
stampfail_home="$TEST_ROOT/stampfail home"
mkdir -p "$stampfail_home"
if DEV_INSTALL_FAIL_AT=after-stamp HOME="$stampfail_home" bash "$INSTALLER" --config-dir "$stampfail_config" >/dev/null 2>&1; then fail "injected after-stamp failure unexpectedly succeeded"; fi
expect_file "$stampfail_config/skills/dev/old.txt"
[[ -z "$(find "$stampfail_config" -name '.dev-stage-*' -print -quit)" ]] || fail "stage directory left behind after after-stamp failure"
expect_absent "$stampfail_home/.agents"
expect_absent "$stampfail_config/backups"
pass "failure after stamping keeps the previous install and leaves no residue"

# A path with a newline or carriage return cannot be stamped faithfully (and a
# trailing newline is stripped by command substitution): refuse it before any
# mutation instead of exiting 0 with references to a path that does not exist.
nl_home="$TEST_ROOT/nl home"
mkdir -p "$nl_home"
nl_cases=("$TEST_ROOT/nl"$'\n'"config" "$TEST_ROOT/nl trailing"$'\n' "$TEST_ROOT/nl cr"$'\r'"config")
for nl_config in "${nl_cases[@]}"; do
  if HOME="$nl_home" bash "$INSTALLER" --config-dir "$nl_config" >/dev/null 2>&1; then fail "install into a path with a line break unexpectedly succeeded"; fi
  expect_absent "$nl_config"
done
nl_target_rc=0
HOME="$nl_home" bash "$INSTALLER" --config-dir "$TEST_ROOT/nl target config" --target "$TEST_ROOT/nl target"$'\n'"x/dev" >/dev/null 2>&1 || nl_target_rc=$?
[[ "$nl_target_rc" == 2 ]] || fail "--target with a line break was not refused (exit $nl_target_rc)"
expect_absent "$TEST_ROOT/nl target config"
nl_relative_base="$TEST_ROOT/nl relative"$'\n'"base"
mkdir -p "$nl_relative_base"
nl_relative_rc=0
(cd -- "$nl_relative_base" && HOME="$nl_home" bash "$INSTALLER" --config-dir "$TEST_ROOT/nl relative config" --target rel/dev >/dev/null 2>&1) || nl_relative_rc=$?
[[ "$nl_relative_rc" == 2 ]] || fail "relative --target under a working directory with a line break was not refused (exit $nl_relative_rc)"
expect_absent "$nl_relative_base/rel"
nl_link_home="$TEST_ROOT/nl link"$'\n'"home"
mkdir -p "$nl_link_home"
if HOME="$nl_link_home" bash "$INSTALLER" --config-dir "$TEST_ROOT/nl link config" >/dev/null 2>&1; then fail "install with a line break in the link path unexpectedly succeeded"; fi
expect_absent "$TEST_ROOT/nl link config"
HOME="$nl_link_home" bash "$INSTALLER" --config-dir "$TEST_ROOT/nl link opt-out config" --no-agents-link >/dev/null 2>&1 || fail "a line break in HOME must not block an install that skips the link"
pass "a path containing a newline or carriage return is refused before any change"

# GNU tar processes backslash escapes in a -C argument, so extraction into a
# directory under a TMPDIR containing a backslash used to fail preflight on
# Linux. Only GNU tar shows the difference, so the case runs where GNU tar is
# the tar in use and says so when it is skipped (bsdtar would pass either way).
if tar --version 2>/dev/null | grep -q 'GNU tar'; then
  # shellcheck disable=SC2016 # deliberately literal backslashes
  bs_tmp="$TEST_ROOT"'/tmp back\slash \1'
  mkdir -p "$bs_tmp"
  bs_config="$TEST_ROOT/backslash tmp config"
  TMPDIR="$bs_tmp" bash "$INSTALLER" --config-dir "$bs_config" --no-agents-link >/dev/null || fail "install failed with a backslash in TMPDIR (preflight extraction)"
  expect_file "$bs_config/skills/dev/SKILL.md"
  pass "a backslash in TMPDIR does not break preflight extraction"
else
  skip "a backslash in TMPDIR does not break preflight extraction" "tar is not GNU tar; the case is only meaningful with GNU tar"
fi

# Help documents the flag.
usage_text="$(bash "$INSTALLER" --help)"
grep -q -- '--no-agents-link' <<<"$usage_text" || fail "--help does not document --no-agents-link"
pass "--help documents --no-agents-link"

# The help must name exactly the paths the line-break guard checks (config dir,
# install target, the Codex link path whenever link creation is enabled -- a
# default install, dry runs included, not with --no-agents-link or an explicit
# --target -- and the working directory for a relative target) and must not
# claim HOME is checked on its own.
usage_flat="$(tr '\n' ' ' <<<"$usage_text" | tr -s ' ')"
for guarded in 'config dir' 'install target' 'Codex discovery link path' 'checked whenever link creation is enabled' 'dry runs included' 'not with --no-agents-link or an explicit --target' 'relative --target also checks the working directory' 'HOME is not checked on its own'; do
  grep -qF -- "$guarded" <<<"$usage_flat" || fail "--help line-break wording does not mention: $guarded"
done
if grep -qF -- '(config dir, target, home)' <<<"$usage_flat"; then fail "--help still claims home is refused"; fi
if grep -qF -- 'only when a link is made' <<<"$usage_flat"; then fail "--help still limits the link-path check to when a link is made"; fi
pass "--help names exactly the paths the line-break guard checks"

printf 'All %d installer tests passed.\n' "$pass_count"
