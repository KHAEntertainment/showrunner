#!/usr/bin/env bash
# Opt-in migration test: dev-skill@khaentertainment-dev-skill -> dev-skill@kha-marketplace.
#
# Needs the claude CLI, git, python3 and network access, so it is NOT part of
# scripts/verify.sh and not named test_*.py (unittest discovery skips it). Run it
# for the release check in docs/RELEASING.md and whenever the migration steps in
# docs/install.md change.
#
# Safety: every claude call runs with CLAUDE_CONFIG_DIR pointing at a directory
# this script created under its own mktemp base. It refuses an unset config dir,
# a pre-existing non-empty one, anything inside ~/.claude, and anything outside
# its base, and it removes the base on exit. It also fails if the set of
# registered plugins or marketplaces in the real registry changes, or mentions the
# scratch directory, while it runs.
#
# Usage: tests/migration-scratch.sh
#   MIGRATION_OLD_TAG     tag holding the retired local catalog (default v2.1.1)
#   MIGRATION_EXPECT_TAG  tag the central catalog should install (default v2.1.1;
#                         set to the release tag after the central pin bump)

set -uo pipefail

OLD_TAG=${MIGRATION_OLD_TAG:-v2.1.1}
EXPECT_TAG=${MIGRATION_EXPECT_TAG:-v2.1.1}
OLD_MARKETPLACE=khaentertainment-dev-skill
NEW_MARKETPLACE=kha-marketplace
OLD_ID="dev-skill@$OLD_MARKETPLACE"
NEW_ID="dev-skill@$NEW_MARKETPLACE"
SOURCE_URL=https://github.com/KHAEntertainment/claude-dev-skill.git
CENTRAL=KHAEntertainment/marketplace

passed=0
failed=0

for tool in claude git python3; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        printf 'NOT RUN: %s is not on PATH\n' "$tool" >&2
        exit 2
    fi
done

real_home_claude=$(cd -P -- "$HOME/.claude" 2>/dev/null && pwd -P || printf '%s' "$HOME/.claude")
base=$(mktemp -d "${TMPDIR:-/tmp}/dev-skill-migration.XXXXXX") || exit 2
base=$(cd -P -- "$base" && pwd -P)
trap 'rm -rf -- "$base"' EXIT

# Other Claude sessions refresh lastUpdated timestamps in the real registry while
# this runs, so compare identity only: which plugin ids and marketplace names are
# registered, and whether any real registry file mentions this script's scratch base.
registry_fingerprint() {
    python3 - "$real_home_claude/plugins" "$base" <<'PY'
import json, sys
plugins, base = sys.argv[1:3]
def load(name):
    try:
        text = open(f"{plugins}/{name}").read()
    except OSError:
        return None, False
    return json.loads(text), base in text
installed, leak_a = load("installed_plugins.json")
known, leak_b = load("known_marketplaces.json")
print("installed", sorted((installed or {}).get("plugins", {})))
print("marketplaces", sorted(known or {}))
print("scratch-path-leaked", leak_a or leak_b)
PY
}
registry_before=$(registry_fingerprint)

pass() { printf '[%s] %s: PASS\n' "$1" "$2"; passed=$((passed + 1)); }
fail() { printf '[%s] %s: FAIL - %s\n' "$1" "$2" "$3"; failed=$((failed + 1)); }
check() { # check <id> <description> <command...>
    local id=$1 description=$2
    shift 2
    if "$@" >/dev/null 2>&1; then pass "$id" "$description"; else fail "$id" "$description" "$*"; fi
}

# Guard every claude call: the config dir must be inside $base and never ~/.claude.
cfg=""
cc() {
    local resolved
    if [[ -z $cfg ]]; then printf 'refusing: CLAUDE_CONFIG_DIR is unset\n' >&2; return 97; fi
    resolved=$(cd -P -- "$cfg" 2>/dev/null && pwd -P) || { printf 'refusing: %s does not exist\n' "$cfg" >&2; return 97; }
    case $resolved in
        "$real_home_claude"|"$real_home_claude"/*) printf 'refusing: %s is inside ~/.claude\n' "$resolved" >&2; return 97 ;;
        "$base"/*) ;;
        *) printf 'refusing: %s is outside the scratch base\n' "$resolved" >&2; return 97 ;;
    esac
    CLAUDE_CONFIG_DIR=$resolved claude "$@"
}

fresh_cfg() { # fresh_cfg <name>: new, empty, script-created config dir
    cfg="$base/cfg-$1"
    if [[ -e $cfg ]] && [[ -n $(ls -A "$cfg") ]]; then printf 'refusing: %s exists and is not empty\n' "$cfg" >&2; exit 2; fi
    mkdir -p "$cfg"
}

# dev_skill_state: one "id enabled version installPath" line per dev-skill@* entry.
# The scratch list can also show session-scoped plugins from the caller's
# environment, so only the dev-skill@ prefix is considered.
dev_skill_state() {
    cc plugin list --json | python3 -c '
import json, sys
for p in json.load(sys.stdin):
    if p["id"].startswith("dev-skill@"):
        print(p["id"], str(p["enabled"]).lower(), p["version"], p["installPath"])
'
}

settings_has() { # settings_has <needle>: needle appears in enabledPlugins or extraKnownMarketplaces keys
    python3 - "$cfg/settings.json" "$1" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1]))
except (OSError, ValueError):
    sys.exit(1)
keys = list(data.get("enabledPlugins", {})) + list(data.get("extraKnownMarketplaces", {}))
sys.exit(0 if any(sys.argv[2] in key for key in keys) else 1)
PY
}

settings_lacks() { ! settings_has "$1"; }

old_enabled_state() { dev_skill_state | awk -v id="$OLD_ID" '$1 == id {print $2}'; }
enabled_copies() { dev_skill_state | awk '$2 == "true"' | wc -l | tr -d ' '; }

marketplace_names() {
    cc plugin marketplace list --json | python3 -c 'import json,sys; print(" ".join(sorted(m["name"] for m in json.load(sys.stdin))))'
}

# assert_single_active <scenario> <expected enabled: true|false>
assert_single_active() {
    local s=$1 want=$2 state count id enabled version path core expected_core
    state=$(dev_skill_state)
    count=$(printf '%s\n' "$state" | grep -c . || true)
    read -r id enabled version path <<<"$state"
    expected_core=${EXPECT_TAG#v}
    core=${version%%+*}
    check "$s" "exactly one dev-skill@ copy is installed (found $count)" test "$count" = 1
    check "$s" "the copy is $NEW_ID (got ${id:-none})" test "$id" = "$NEW_ID"
    check "$s" "enabled state is $want (got ${enabled:-none})" test "$enabled" = "$want"
    check "$s" "installed version is $expected_core (got ${version:-none})" test "$core" = "$expected_core"
    check "$s" "entry point skills/dev/SKILL.md exists in the install" test -f "$path/skills/dev/SKILL.md"
    check "$s" "plugin.json names the plugin dev-skill (namespace /dev-skill:dev)" \
        python3 -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1] + "/.claude-plugin/plugin.json"))["name"] == "dev-skill" else 1)' "$path"
    check "$s" "installed skills/dev equals git archive $EXPECT_TAG" diff -r "$base/ref/skills/dev" "$path/skills/dev"
    check "$s" "only $NEW_MARKETPLACE is configured (got $(marketplace_names))" test "$(marketplace_names)" = "$NEW_MARKETPLACE"
    check "$s" "settings.json holds no $OLD_MARKETPLACE key" settings_lacks "$OLD_MARKETPLACE"
}

# The documented migration (docs/install.md), in two halves so scenario B can
# observe the duplicate state between them: install central, then carry a
# disabled state over and retire the old copy and catalog.
migrate_install() { cc plugin marketplace add "$CENTRAL" >/dev/null && cc plugin install "$NEW_ID" >/dev/null; }
migrate_retire() { # migrate_retire <old enabled state recorded before switching>
    if [[ $1 == false ]]; then cc plugin disable "$NEW_ID" >/dev/null || return 1; fi
    cc plugin uninstall "$OLD_ID" >/dev/null || return 1
    cc plugin marketplace remove "$OLD_MARKETPLACE" >/dev/null || return 1
}

seed_old_install() {
    cc plugin marketplace add "$base/old-catalog" >/dev/null && cc plugin install "$OLD_ID" >/dev/null
}

printf '== Fixtures (old tag %s, expected central tag %s) ==\n' "$OLD_TAG" "$EXPECT_TAG"
git clone --quiet --branch "$OLD_TAG" "$SOURCE_URL" "$base/old-catalog" 2>/dev/null \
    || { printf 'NOT RUN: cannot clone %s at %s\n' "$SOURCE_URL" "$OLD_TAG" >&2; exit 2; }
if ! python3 - "$base/old-catalog/.claude-plugin/marketplace.json" "$OLD_MARKETPLACE" <<'PY'
import json, sys
sys.exit(0 if json.load(open(sys.argv[1]))["name"] == sys.argv[2] else 1)
PY
then printf 'NOT RUN: %s does not carry the %s catalog\n' "$OLD_TAG" "$OLD_MARKETPLACE" >&2; exit 2; fi
git clone --quiet --branch "$EXPECT_TAG" "$SOURCE_URL" "$base/ref-src" 2>/dev/null \
    || { printf 'NOT RUN: cannot clone %s at %s\n' "$SOURCE_URL" "$EXPECT_TAG" >&2; exit 2; }
mkdir -p "$base/ref"
git -C "$base/ref-src" archive --format=tar "$EXPECT_TAG" | tar -x -C "$base/ref" \
    || { printf 'NOT RUN: no reference payload for %s\n' "$EXPECT_TAG" >&2; exit 2; }

printf '\n== Scenario A: clean install from the central catalog ==\n'
fresh_cfg a
check A "marketplace add $CENTRAL" cc plugin marketplace add "$CENTRAL"
check A "install $NEW_ID" cc plugin install "$NEW_ID"
assert_single_active A true

printf '\n== Scenario B: existing old-marketplace install (enabled), then migrate ==\n'
fresh_cfg b
check B "seeded the old install ($OLD_ID) from a local clone of $OLD_TAG" seed_old_install
recorded=$(old_enabled_state)
check B "old copy is enabled before migration" test "$recorded" = true
check B "migration step: install $NEW_ID from the central catalog" migrate_install
check B "before retiring the old copy, two enabled copies load (the duplicate case)" test "$(enabled_copies)" = 2
check B "migration step: retire the old copy and catalog" migrate_retire "$recorded"
assert_single_active B true

printf '\n== Scenario C: old copy disabled; the migration keeps it disabled ==\n'
fresh_cfg c
check C "seeded the old install ($OLD_ID) from a local clone of $OLD_TAG" seed_old_install
check C "disabled the old copy" cc plugin disable "$OLD_ID"
recorded=$(old_enabled_state)
check C "old copy is disabled before migration" test "$recorded" = false
check C "migration step: install $NEW_ID from the central catalog" migrate_install
check C "migration step: retire the old copy and catalog" migrate_retire "$recorded"
assert_single_active C false

printf '\n== Real configuration untouched ==\n'
if [[ $(registry_fingerprint) == "$registry_before" ]]; then
    pass R "real plugin and marketplace registrations unchanged"
else
    fail R "real plugin and marketplace registrations unchanged" "fingerprint changed"
fi

printf '\nSUMMARY: %s passed, %s failed\n' "$passed" "$failed"
if (( failed > 0 )); then printf 'MIGRATION TEST FAILED\n'; exit 1; fi
printf 'MIGRATION TEST PASSED\n'
