# Upstream Maintenance

This fork maintains a customized English personal Skill while retaining upstream history.

## Remotes

- `origin`: `https://github.com/KHAEntertainment/showrunner.git`
- `upstream`: `https://github.com/hnaymyh123-henry/claude-dev-skill.git`
- `main`: maintained customized distribution
- `master`: upstream mirror retained for comparison

## Provenance

- Installed-era base: `3abcd9a75d3032e12a499afb464b56695a424cb9`
- First audited merge: `3e87db0c71ff51ad19c932a6849777e66398f556`
- Canonical maintained artifact: `skills/dev/`
- Historical upstream references: `en/` and `zh/`

## Sync Procedure

1. Check out `main`, fetch `upstream`, and inspect new tags/commits.
2. Compare both upstream language trees; do not assume English parity.
3. Update `docs/AUDIT.md` with newly discovered behavior and conflicts.
4. Merge the upstream commit with `--no-ff` to preserve ancestry.
5. Selectively translate relevant behavior into `skills/dev/`; never release directly from `en/` or `zh/`.
6. Preserve RTK, `.agent/dev-state.md`, the implementation/test no-lead-code rule, pre-created worktrees, Agent Teams ownership, specialist QA/review lanes, and lead-owned cleanup.
7. Run `scripts/validate_skill.py`, Bash syntax checks, ShellCheck, installer tests, isolated discovery, and `/dev` loading smoke tests.
8. Record the upstream commit in `CHANGELOG.custom.md` and the release tag.

Do not run the default installer while an active Claude Code session depends on the legacy global command. Use an explicit temporary `--target` for validation, then wait for an intentional swap window.
