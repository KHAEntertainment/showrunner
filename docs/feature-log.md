# Feature Log

## Completed

- v2.1.0 content: adapter report-back enforcement (PR #32), bounded review recovery
  (PR #35), and `.dev.json` repository/account verification (PR #36), merged 2026-09-11.
- Committed verification gate and current-head external-review enforcement (PR #23/#28),
  plus role-prompt discipline (PR #30), included in v2.1.0.
- v2.1.1 WS4: ADR-012 records that child harnesses (Codex CLI, OpenCode,
  Cursor-class, and any receive-capable Claude-class-or-similar) execute
  Traycer-managed lanes via the provider-neutral assignment envelope — no
  `/dev` variants, no forked SOPs — with a four-item capability checklist
  in `skills/dev/backends/contract.md` (#58). Coupled: ADR-009's lint
  reclassification is now recorded in `backends/contract.md` so the
  delegated lanes read it (#38).

- CI Verification Gate: 6 jobs across ubuntu/macos/windows, archive validation,
  and packaging guards (PR #11, merged 2026-08-31)
- Plugin-root and version-sync guard scripts (PR #10, merged 2026-08-31)
- v2.0.1 release: HTTPS marketplace source, no SSH key required (PR #8/#9, merged 2026-08-31)
- Claude Code plugin distribution and v2.0.0 version scheme (PR #7, merged 2026-08-30)
- Traycer execution backend v1 (PR #1, merged 2026-08-30)
- External review oversight gate (commit `6ad111b`)
- Validated atomic Skill distribution installer (commit `ad6101a`)

## Retro — claude-dev-skill / v2.0.x Distribution

### Completed

- Claude Code plugin distribution. `skills/dev/` ships as a plugin from the
  repository root; installable in two commands and verified working end to end
  on a machine with no GitHub SSH key.
- `v2.0.0` release line adopted, resolving a collision with upstream's `v1.x`
  tags that live in this fork's history. `v2.0.1` was the published version at that retrospective; v2.1.0 is the current release-preparation target.
- Two stdlib-only packaging guards, both with proven failure modes.
- The repository's first CI: 6 jobs across ubuntu/macos/windows, validating the
  extracted release archive as well as the working tree.
- A documented release procedure, which did not previously exist.
- A latent dispatch defect fixed: dispatched agents do not inherit
  `${CLAUDE_SKILL_DIR}`, which plugin packaging would have made unguessable.

### Known Issues

- `README.zh.md` carries an outdated banner but its body is still wrong.
- The plugin-root component list is defined by Claude Code, not by this repo, and
  can grow without notice.
- `install.ps1` remains under-tested relative to `install.sh` (5 assertions vs 9).

### Deferred

- Homebrew tap (ADR-007). Now unblocked: it needs a tagged tarball, and `v2.0.1`
  exists.
- PyPI packaging. Note the exec-bit hazard — wheels do not preserve file modes,
  and `detect_execution_backend.py` must stay 755.

### Recommended Next Priorities

1. Homebrew tap — smallest remaining distribution gap, and now unblocked.
2. Issue #3 was completed in PR #32; the next controlled run is ScadForge #48 after the tag and separate authorization.
3. `README.zh.md` — retranslate or delete; a banner is a stopgap.

## Retro — claude-dev-skill / v2.1.0

### Completed

- The content stack is merged; release metadata and ADR corrections are prepared.
- Repository/account intent is persisted locally and checked against the selected
  worktree. The rejected credential-boundary architecture is superseded by ADR-010.
- Review corrections were batched and review waits bounded; exact-head evidence
  and user-authorized dispositions were recorded separately.

### Known Issues

- Live SSH verification remains untested (#37); supported checks fail closed.
- Pre-write checks are not containment of arbitrary agent commands.
- Live rate-limit recovery required user-adjusted timing; fresh-session policy
  adherence and skill selection are not established by local/static tests.
- Reviewer status checks and formal review events can disagree. PR #36 used an
  explicit user disposition of clean current-head substantive evidence plus prior
  formal approval. Superseded-head finding tracking remains procedural debt (#33).
- v2.1.0 tag publication and isolated post-tag installation are still pending.

### Deferred

- #17 and #38: authorship-lint follow-ups; #39: Homebrew; #40: dogfooding distillation.
- Existing v2.1.1 engineering debt remains separate from release preparation.

### Recommended Next Priorities

1. Complete approved release steps, with separate authorization for release merge/tag.
2. Run the planned controlled ScadForge #48 test in a fresh session after the tag,
   when authorized; prioritize its findings before expanding the debt scope.

## Retro — claude-dev-skill / v2.1.1

### Completed

- ADR-012 + child-harness capability checklist (#58) and ADR-009 guard
  reclassification recorded in `skills/dev/backends/contract.md` (#38).
- Lead-to-user end-of-turn reply contract (#54) in
  `skills/dev/reply-contract.md`.
- Unconditional post-merge verification step (#26), owned by the lead.
- `install.sh` and `install.ps1` no longer ship the working tree under
  `skills/dev` (#44): git-staged archive from a captured commit, with a
  matching preflight validator.
- External-review bypass requires a re-request after a head-moving push (#33).
- Closed test-coverage gaps from PR #30 (#31, #25).
- `en/commands/dev.md` no longer leaks the maintainer's home directory (#42).
- Graft pinned optional code-graph evidence adapter (#57, PR #60) in
  `skills/dev/graft.md`, recorded as ADR-011.
- Dogfooding distillation (#40, PR #63) in `docs/dogfooding.md`, plus the
  i-have-adhd compatibility note added with this release.
- README documents the v2.1.1 integrations, borrowed concepts, and
  thank-yous (#50, PR #64).
- Homebrew tap documentation (#39, PR #65): the `docs/RELEASING.md` Homebrew
  formula section and the README alternative-install subsection. The tap
  formula is published at v2.1.0.
- External-review rate-limit breakpoint (#48, PR #68): after 3 consecutive
  rate-limited responses from a trusted reviewer on one PR, the lead
  dispatches a family-distinct substitute reviewer instead of waiting or
  bypassing.
- Version metadata bumped from `v2.1.0` to `v2.1.1` in the four repo fields
  (`.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` `ref` +
  `version`, `skills/dev/SKILL.md` frontmatter) with the `+upstream.3e87db0`
  build metadata preserved.

### Post-release record

The retro above was written in the release commit (PR #66, `4a0e699`),
before the tag existed. The tagged tree keeps that wording; these are the
facts after release (recorded 2026-09-29, #72):

- **Tag**: `v2.1.1` published as annotated tag `00ef967` on `4a0e699`.
- **Marketplace install**: verified against the live tag in a scratch
  `CLAUDE_CONFIG_DIR`. The installed `skills/dev` is identical to
  `git archive v2.1.1` and reports `2.1.1+upstream.3e87db0`.
- **Homebrew formula**: `url` + `sha256` bumped to v2.1.1 at
  `homebrew-tap@7acd583`. `brew install` works; `brew test` fails (#70).

### Known Issues

- Homebrew `brew test` fails for the v2.1.1 formula (#70): the test asserts
  the wrong `detect_execution_backend.py` path, and `brew test` times out for
  a cause not yet diagnosed. The fix ships in v2.1.2; the v2.1.1 tag is not
  moved (ADR-007).
- Pre-write verification scope is unchanged from v2.1.0.
- Remaining engineering debt is tracked in the v2.1.2 milestone (see
  `PROJECT_CONTEXT.md`, "Next iteration").

### Deferred

- The `brew test` fix (#70), to v2.1.2.

### Recommended Next Priorities

1. ~~Run the controlled ScadForge issue #48 test against v2.1.1.~~
   **Done 2026-09-29**: about a week of real-project use across several
   projects in place of the single ScadForge run. Findings were triaged as
   #73, #74, #75, and #82, and are recorded in `docs/dogfooding.md`.
2. ~~Publish the v2.1.1 tag and run the marketplace install test.~~
   **Done**; see the post-release record above.
3. ~~Bump the Homebrew formula and verify it.~~ **Bumped**; `brew test`
   fails, tracked as #70.
4. Work the v2.1.2 milestone in the phase order in `PROJECT_CONTEXT.md`.

## Known Tech Debt

- Phase-level role prompts are not covered by the reviewer/QA distinctness
  regression test. `test_qa_and_reviewer_are_distinct_clean_current_head_lanes`
  asserts the wording in the agent docs and loads the phase docs, but does not
  assert against them — so future propagation drift would go undetected.
  (source: PR #1 re-review, recorded 2026-08-30)
- `README.zh.md` is stale and contradicts the current installer: it still
  documents the upstream bilingual *command* install and advertises
  `install.sh --lang zh`, which `install.sh` now rejects. Its prerequisites
  table also omits RTK and Python. **Mitigated** as of PR #7 with a bilingual
  outdated/unsupported banner directing readers to the English README; the body
  itself is still wrong and either needs retranslation or deletion.
  (recorded 2026-08-30, mitigated 2026-08-31)
- `install.sh` has no uninstall path. Recovery from a bad install is a manual
  restore out of `~/.claude/backups/dev/<timestamp>/`. (recorded 2026-08-30)
- `install.ps1` is under-tested relative to `install.sh`: 5 assertions versus 9.
  It lacks the symlink-refusal, broken-distribution, and idempotent-rerun cases.
  (recorded 2026-08-30)
- `--migrate-legacy` and `--keep-legacy` are accepted by `install.sh` but absent
  from its `usage()` output. (recorded 2026-08-30)
- ~~The advertised plugin install path has not been verified end to end.~~
  **Resolved 2026-08-31**: verified against the live `v2.0.0` tag in an isolated
  `CLAUDE_CONFIG_DIR`. Installs cleanly with no SSH key present; payload is 23
  files, version `2.0.0+upstream.3e87db0`, exec bits preserved (755 detector /
  644 inspector, matching git modes), and the detector executes from the
  installed copy.
- `README.zh.md` carries an outdated banner but its body is still wrong.
  Retranslate or delete. (recorded 2026-08-31)
- The plugin-root guard checks the 11 documented auto-discovered components as of
  2026-08-31. That list is defined by Claude Code, not by this repo, so it can
  grow without notice. Re-check it against
  https://code.claude.com/docs/en/plugins-reference on each upstream sync.
  (recorded 2026-08-31)
- CI installs a pinned `@anthropic-ai/claude-code@2.1.251` to run strict manifest
  validation. The pin needs periodic review: too old and it stops matching the
  format the runtime actually enforces. (recorded 2026-08-31)
