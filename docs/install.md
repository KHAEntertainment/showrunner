# Installation

Every way to install, update, and invoke `/dev`. For the short version, see the
[Quick start](../README.md#quick-start) in the README.

## Requirements

- Claude Code. Agent Teams are required only for Claude-native *parallel* topology.
- Git and an authenticated GitHub CLI (`gh`)
- [RTK](https://github.com/rtk-ai/rtk) — `brew install rtk`, or see the RTK README for other platforms
- Python 3 (used by the Skill at runtime, and by the manual installer's preflight validation)
- **Optional** Traycer CLI/Host for managed multi-harness execution; Traycer children use the Chat/GUI surface in v1. Without it, the skill runs Claude-native with no loss of core workflow.
- **Optional** [Graft](https://github.com/trailhq/Graft) (`@nanonets/graft@0.18.0`) for pinned code-graph evidence at gates; accessed via `rtk proxy graft` per [`skills/dev/graft.md`](../skills/dev/graft.md). Not installed by the Skill; each developer runs `graft init` locally if desired. Without it, gates record `graph_evidence: unavailable` and fall back to manual tracing — no loss of core workflow.
- Agent Teams run in-process and do not require tmux or iTerm

## Plugin install (recommended)

```bash
claude plugin marketplace add KHAEntertainment/marketplace
claude plugin install dev-skill@kha-marketplace
```

Restart Claude Code, then invoke:

```text
/dev [optional project or feature description]
```

Plain `/dev` needs Claude Code 2.1.265 or later. The plugin also answers to its
full name, `/dev-skill:dev`: use that on older Claude Code versions, or when
another `/dev` command is installed, for example a manual install (see
[Running both at once](#running-both-at-once)).

That is the whole plugin install. To update the plugin later:

```bash
claude plugin marketplace update kha-marketplace   # refresh the catalog
claude plugin update dev-skill@kha-marketplace     # update the installed plugin
```

Both steps are needed — refreshing the catalog does not update an installed
plugin. Restart Claude Code afterwards to apply the update.

All of these commands are also available inside a session as `/plugin …`.

> `dev-skill` is listed in the central KHA Entertainment catalog,
> [`KHAEntertainment/marketplace`](https://github.com/KHAEntertainment/marketplace)
> (catalog name `kha-marketplace`), next to the other KHA plugins. The entry
> pins a release tag, so the plugin resolves only from a tagged release and
> moves forward when the entry is bumped after a release. See
> [Releasing](RELEASING.md) for how a release is cut and published.

No SSH key is required — the marketplace entry fetches over HTTPS.

### Migrating from `dev-skill@khaentertainment-dev-skill`

Up to v2.1.1 this repository hosted its own catalog, installed as
`dev-skill@khaentertainment-dev-skill`. That catalog is retired. Once it is
gone from `main`, `claude plugin marketplace update khaentertainment-dev-skill`
can no longer find it, so an old install **stops tracking releases** and stays
on the version it has. Switch to the central catalog. Adding the central
marketplace without removing the old one loads two copies of the same plugin,
both answering `/dev` and `/dev-skill:dev`, so retire the old one in the same sitting.
A GitHub redirect does not carry your install across; the plugin ID is
different.

1. **Record whether the old copy is enabled.** The new copy always installs
   enabled, so you must carry a disabled state over yourself:

   ```bash
   claude plugin list --json    # find dev-skill@khaentertainment-dev-skill and read "enabled"
   ```

2. **Install from the central catalog:**

   ```bash
   claude plugin marketplace add KHAEntertainment/marketplace
   claude plugin install dev-skill@kha-marketplace
   ```

3. **If step 1 showed `"enabled": false`, disable the new copy too:**

   ```bash
   claude plugin disable dev-skill@kha-marketplace
   ```

4. **Retire the old copy and its catalog:**

   ```bash
   claude plugin uninstall dev-skill@khaentertainment-dev-skill
   claude plugin marketplace remove khaentertainment-dev-skill
   ```

5. **Check, then restart Claude Code.** `claude plugin list` should show
   exactly one `dev-skill` entry, `dev-skill@kha-marketplace`.

These commands act on user scope. If you installed the old copy with
`--scope project` or `--scope local`, repeat steps 2 to 4 with the same
`--scope` (and read the enabled state for that scope in step 1). The
migration is exercised end to end, in a throwaway `CLAUDE_CONFIG_DIR` and never
your real configuration, by `tests/migration-scratch.sh`.

Need an air-gapped machine, an isolated evaluation target, or a lead on Codex
or OpenCode? See [Manual installation](#manual-installation).

## Invocation

Type it yourself at any time:

```text
/dev [optional project or feature description]
```

On Claude Code older than 2.1.265, a plugin install needs the full name,
`/dev-skill:dev`.

The Skill is also model-invocable, so an explicit request survives the
plan-to-implementation transition. If you say during planning that you want the
dev skill — or the full Issue-to-PR workflow — once implementation starts, the
agent can invoke it for you after you accept the plan and before the first
implementation edit. You do not have to interrupt implementation to type the
command.

Explicit workflow intent is the trigger, not the subject matter. An ordinary
coding, debugging, refactoring, or review request with no stated `/dev` or
Issue-to-PR intent does not activate the Skill.

> Frontmatter is read when the Skill is loaded. A Claude Code session that was
> already running when you installed or updated the plugin keeps the previous
> invocation behavior until you reload the plugin or restart the session — the
> same reload the update steps above require. After a manual install, restart
> Claude Code before checking invocation behavior.

## Homebrew

If you prefer Homebrew, install via the [KHAEntertainment tap](https://github.com/KHAEntertainment/homebrew-tap):

```bash
brew tap KHAEntertainment/tap
brew install khaentertainment/tap/dev-skill   # places the payload; installs nothing yet
dev-skill-install --dry-run                   # preview: changes nothing
dev-skill-install                             # installs into ~/.claude/skills/dev
```

`brew install` only places the files; `dev-skill-install` runs the bundled
`install.sh`, which does the actual install (see [Live installation](#live-installation))
into `~/.claude/skills/dev`.

The Homebrew formula and the plugin marketplace install the same payload but
follow independent release cadences. The formula may lag by one release while
`url`/`sha256` are bumped — see [`RELEASING.md`](RELEASING.md#homebrew-formula).
Check `brew info dev-skill` for the version it carries. `brew test dev-skill`
currently fails on the v2.1.1 formula (#70).

## Manual installation

The plugin above is the recommended path. Install manually when evaluating a change
against an isolated target, on a machine that cannot reach the marketplace, or
when the lead will run from Codex or OpenCode (see
[Running the lead from Codex or OpenCode](backends.md#running-the-lead-from-codex-or-opencode)).

Run every command in this section from the root of a clone of this repository.

### Running both at once

The plugin and a manual install can coexist. Bare `/dev` then runs the manual
install, because a local skill takes the short name, and the plugin stays
reachable as `/dev-skill:dev`. They are two independent copies and will drift apart as
one is updated and the other is not. Pick one as your working path; if you
switch to the plugin, move the old Skill aside into the same backup location the
installer uses:

```bash
mkdir -p ~/.claude/backups/dev
mv ~/.claude/skills/dev ~/.claude/backups/dev/manual-$(date -u +%Y%m%dT%H%M%SZ)
```

This is the same `~/.claude/backups/dev/` directory the installer writes to, so
the restore instructions below apply unchanged.

### Validate before installing

```bash
python3 scripts/validate_skill.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py' -v
bash -n install.sh
shellcheck install.sh tests/test-install.sh
bash tests/test-install.sh
./install.sh --dry-run
```

### Isolated installation

Use an explicit target while another Claude Code session is active or while evaluating the Skill:

```bash
./install.sh --target "/tmp/claude-dev-test/skills/dev"
```

An explicit target does not migrate `~/.claude/commands/dev.md` or `~/.claude/commands/dev/` unless `--migrate-legacy` is also supplied.

### Live installation

When ready to swap the global `/dev` implementation:

```bash
./install.sh --dry-run
./install.sh
```

The default installation:

1. Validates every required Skill file and reference before mutation.
2. Stages the new Skill beside the destination and writes the absolute installed path over every `${CLAUDE_SKILL_DIR}` in the staged copy (the repository keeps the variable form).
3. Moves an existing `~/.claude/skills/dev` and legacy command paths into `~/.claude/backups/dev/<timestamp>/`.
4. Atomically renames the staged Skill into `~/.claude/skills/dev`.
5. Restores the previous Skill and command paths if installation fails.
6. Creates or refreshes the Codex link `~/.agents/skills/dev` (skip it with `--no-agents-link`). An existing directory, a file, or a link to another existing directory at that path is reported and left alone; a link whose target no longer exists is replaced.

Restart Claude Code after the swap, then invoke:

```text
/dev [optional project or feature description]
```

The restart is not optional if you are checking invocation behavior: a session
that was already running keeps the previously loaded frontmatter, including
whether the Skill is model-invocable.

Compatibility forms `--lang en` and `--lang=en` are accepted. Chinese installation is intentionally rejected before any filesystem mutation.

There is no uninstall command. To reverse an install, restore the most recent
directory under `~/.claude/backups/dev/`.

### Windows PowerShell

```powershell
.\install.ps1 -DryRun
.\install.ps1
```

Use `-Target C:\path\to\skills\dev` for an isolated target.
