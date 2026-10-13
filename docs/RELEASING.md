# Releasing

The plugin is listed in the central KHA Entertainment catalog,
[`KHAEntertainment/marketplace`](https://github.com/KHAEntertainment/marketplace)
(catalog name `kha-marketplace`; ADR-014), and that entry pins a release tag
(ADR-003). So **the plugin does not resolve until the tag exists and is
pushed**, and **users do not receive a release until the central pin is bumped
to it**. Cutting a release is therefore a required step, not an optional one,
and it spans two repositories.

## Version sites

One version, four places — two repository fields, the git tag, and the central
catalog pin. The two repository fields are updated together in the release
commit; the tag is created afterwards, from that commit; the central pin is
bumped last, in the other repository (step 5).

| Site | Form | Example |
|---|---|---|
| `skills/dev/SKILL.md` frontmatter `version:` | semver + build metadata | `2.0.0+upstream.3e87db0` |
| `.claude-plugin/plugin.json` `version` | plain semver | `2.0.0` |
| git tag | `v` + semver | `v2.0.0` |
| `KHAEntertainment/marketplace` `.claude-plugin/marketplace.json`, `dev-skill` entry `source.ref` | `v` + semver | `v2.0.0` |

The Skill value carries `+upstream.<sha>` build metadata that `plugin.json`
does not. They are **not** byte-identical — they share the same core version,
the part before `+`. Comparison must strip build metadata. The central entry
has no `version` field, only the `ref`.

`scripts/check_version_sync.py` compares the first two sites and an optional
`--tag`, offline. The central pin lives in another repository, so it is checked
separately, over the network, by `scripts/check_central_catalog.py` (step 6).

## Tag scheme

Plain `vX.Y.Z`, starting at `v2.0.0` (ADR-004). Note that `claude plugin tag`
generates a *different* form — `dev-skill--v2.0.0` — which this project does not
use, because a plain `vX.Y.Z` tag also serves the Homebrew formula's source
tarball URL (`refs/tags/vX.Y.Z.tar.gz`, ADR-007). One tag serves both channels.

`claude plugin tag --dry-run .` is still useful as a *validation* step: it
checks `plugin.json` (name and version) and refuses a dirty tree. Ignore the
tag name it proposes; do not let it create the tag.

## Procedure

1. **Land the content.** Every PR for the release is merged to `main`.

2. **Verify agreement.** From a clean checkout of `main`:

   ```bash
   python3 scripts/validate_skill.py
   PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py'
   bash tests/test-install.sh
   claude plugin validate . --strict
   claude plugin tag --dry-run .        # validation only; ignore the proposed tag name
   ```

   `claude plugin tag` refuses to run on a dirty worktree, and `--force`
   defeats the check rather than satisfying it. Commit or clean first.

3. **Tag and push.**

   ```bash
   git checkout main && git pull --ff-only    # or a clean detached checkout of the merge commit
   sha="$(git rev-parse HEAD)"
   remote="$(python3 skills/dev/scripts/resolve_repository.py --repo-dir . --operation push \
     --dest-ref refs/tags/vX.Y.Z --tag-target "$sha" --print-push-remote)" || exit 1
   git tag -a vX.Y.Z -m "dev-skill X.Y.Z" "$sha"
   test "$(git rev-parse 'vX.Y.Z^{commit}')" = "$sha" || exit 1
   git push "$remote" refs/tags/vX.Y.Z
   ```

   The check is the canonical pre-write verification for a tag push. It
   verifies the remote identity and both accounts, that `$sha` is the live tip
   of the remote's default branch, and that the tag exists neither locally nor
   on the remote; it needs no particular branch checked out. It prints the
   remote to push to (`origin` here) when ready and exits 2 on anything it cannot
   verify, so `|| exit 1` stops the release. Gate on the exit status, never on
   stdout. It runs **before** `git tag` because it refuses a tag that
   already exists locally. Tagging the verified `$sha` explicitly, not `HEAD`,
   and re-reading the tag's peeled commit keep the pushed tag on exactly the
   commit the check approved. The checkout needs its `.dev.json`; see
   `skills/dev/phases/repository-context.md`.

   Cut the tag from `main` only. `master` mirrors upstream and carries
   upstream's `v1.x` tags; releasing from it would be wrong.

4. **Verify the tag resolves.**

   ```bash
   git ls-remote --exit-code "$remote" refs/tags/vX.Y.Z 'refs/tags/vX.Y.Z^{}'
   test "$(git ls-remote "$remote" 'refs/tags/vX.Y.Z^{}' | cut -f1)" = "$sha" || exit 1
   ```

   This queries the exact ref on the remote step 3 pushed to (`--exit-code`
   exits 2 when it is absent), so `vX.Y.Z` cannot match `vX.Y.Z0`, and the
   peeled commit must equal `$sha`. Run it in the same shell as step 3, or
   first re-resolve `remote` with the same `resolve_repository.py ...
   --print-push-remote` command.

5. **Publish to the central catalog.** This needs the tag from steps 3 and 4,
   because the central CI clones the pinned ref. In a clone of
   `KHAEntertainment/marketplace`, open a PR that changes only the `dev-skill`
   entry's `source.ref` in `.claude-plugin/marketplace.json` from the previous
   release tag to `vX.Y.Z`. Leave `source.source` (`url`) and `source.url`
   (`https://github.com/KHAEntertainment/claude-dev-skill.git`) alone; the
   HTTPS transport is ADR-003's. That repository's `verify-catalog.yml` clones
   every entry anonymously and checks the plugin name and any declared
   version; it must pass before the PR merges. It does not compare the plugin
   version with the tag, which is what step 6 is for. Merge the PR.

6. **Verify the central entry against the tag.** From the release commit:

   ```bash
   python3 scripts/check_central_catalog.py --tag vX.Y.Z
   ```

   It clones `KHAEntertainment/marketplace` `main` anonymously and passes only
   if the catalog has exactly one `dev-skill` entry, its source is the HTTPS
   URL above with `ref` equal to `vX.Y.Z`, the tag is published (annotated tags
   are peeled), the checkout it read is that tag's commit, and that commit's
   `plugin.json` is named `dev-skill` at the release version. It does not run
   in `scripts/verify.sh`: it needs the network and a published tag. It fails
   closed: exit 1 is a mismatch, exit 2 means it could not verify (no network,
   clone failure, unparseable catalog). **Exit 2 is not a pass; rerun it.** If
   it keeps failing, treat the release as incomplete (below).

7. **Verify the advertised install actually works**, in a scratch config so the
   real one is untouched.

   The catalog entry uses an `https://` `url` source specifically so this
   works without a GitHub SSH key (ADR-003). Verify on a machine where
   `ssh -T git@github.com` fails, if you have one — that is the configuration
   the `url` source exists to support.

   ```bash
   CLAUDE_CONFIG_DIR=/tmp/dev-skill-release-check \
     claude plugin marketplace add KHAEntertainment/marketplace
   CLAUDE_CONFIG_DIR=/tmp/dev-skill-release-check \
     claude plugin install dev-skill@kha-marketplace
   ```

   Then run the migration test, which does the same for a clean install and for
   an old-marketplace install, in directories it creates and removes itself:

   ```bash
   MIGRATION_EXPECT_TAG=vX.Y.Z bash tests/migration-scratch.sh
   ```

   This is the step that catches an unresolvable pin, and the only step that
   exercises the transport real users hit. Do not skip it — manifest validation
   passing proves neither that the pinned ref exists nor that it can be fetched.

   It can only be run **after** the tag is pushed and the central pin from step
   5 has merged. Before that, the catalog still serves the previous release (or
   the `owner/repo` shorthand fails on a missing manifest), which tells you
   nothing about the new one.

## Incomplete publication and recovery

Publication spans two repositories in a fixed order: tag (steps 3 and 4), then
central pin (step 5), then verification (steps 6 and 7). From the tag push until
step 7 passes, marketplace distribution of the release is **incomplete**: do not
announce the release, and do not bump the Homebrew formula. An incomplete
release is safe for users, because the central entry pins an immutable tag and
keeps serving the previous release until the pin moves.

| State | What users get | Recovery |
|---|---|---|
| Tag pushed, central PR not yet merged | The previous release | Open or finish the step 5 PR. |
| Step 6 exits 1 (mismatch) | The previous release, or a wrong pin if the PR already merged | Fix the central entry (or the tag mismatch it names) and rerun step 6. |
| Step 6 exits 2 (unverifiable) | Unknown | Rerun. If it persists, check the network and `KHAEntertainment/marketplace`, then repeat; never record it as a pass. |
| Pin merged, step 7 install fails | A broken install | Roll back by reverting the central pin PR so `ref` returns to the previous tag, confirm the central CI and step 7 against it, then diagnose. |
| The tagged content is wrong | Whatever the pin selects | Never move, delete, or recreate a published tag. Fix forward: release a new patch version through steps 1 to 7 and point the pin at it. |

Old release tags stay immutable. Rolling back always means repointing the central
`ref` at an earlier tag, never retagging.

## Homebrew formula

The formula lives in [`KHAEntertainment/homebrew-tap`](https://github.com/KHAEntertainment/homebrew-tap)
at `Formula/dev-skill.rb`. The marketplace plugin and the Homebrew formula are
independent distribution channels — they ship the same payload but follow
different update cadences. The formula's `url` and `sha256` must be bumped per
release; until bumped, the formula serves the previous release.

### Bumping the formula

After `docs/RELEASING.md` step 7 (marketplace install verification) succeeds:

```bash
# 1. Compute the new tarball sha256
curl -sL https://github.com/KHAEntertainment/claude-dev-skill/archive/refs/tags/vX.Y.Z.tar.gz \
  | shasum -a 256 | awk '{print $1}'

# 2. Update the formula in KHAEntertainment/homebrew-tap
git clone https://github.com/KHAEntertainment/homebrew-tap.git /tmp/homebrew-tap-bump
cd /tmp/homebrew-tap-bump
# Edit Formula/dev-skill.rb:
#   - url: bump vX.Y.Z in the refs/tags/vX.Y.Z.tar.gz URL
#   - sha256: paste the value from step 1
git commit -am "dev-skill X.Y.Z"
git push origin main

# 3. Verify the install
brew update
brew install --build-from-source khaentertainment/tap/dev-skill
brew test dev-skill
```

### Tag immutability

The formula pins a tag, not a commit SHA, so a moved tag silently changes what
existing users receive. Treat a pushed release tag as immutable. Formula
defects are fixed in the tap; payload defects wait for the next version. See
ADR-007 for the original tap design.

## What CI enforces for you

`.github/workflows/ci.yml` runs the full Verification Gate on every pull request
and every push to `main`, so most of step 2 is checked automatically. In
particular the packaging job extracts `git archive HEAD` and runs
`scripts/validate_skill.py` against the **extracted archive**, not just the
working tree — so a broken `export-ignore` rule that would ship a defective
source tarball fails CI rather than surfacing later as a broken `brew install`.

What CI cannot do is steps 5 to 7. The tag does not exist when CI runs and the
central catalog lives in another repository, so verifying the central entry and
that the published plugin actually installs remain manual post-tag steps.

## Never move a released tag

The central catalog entry pins `ref` only, not a commit `sha`, so a moved tag silently
changes what existing users receive. Treat a pushed release tag as immutable. If
a release is wrong, cut a new patch version.

Pinning `sha` alongside `ref` would make this mechanically impossible rather
than merely forbidden. It was deliberately deferred: it requires editing the
commit SHA into the manifest *after* the commit exists, which is a
chicken-and-egg step better handled by release automation. Revisit when CI
computes it (Issue #6).

## Next release

Update the two repository fields in a single commit, land it, then create the
tag from that commit — the tag is a separate site and by definition cannot be
inside the commit it points at — and bump the central pin (step 5). Then repeat
from step 1.

`CHANGELOG.custom.md` also records the version as a release-lifecycle heading.
It is not a plugin-resolution source, so it is not in the table above, but it
should be updated in the same release commit. `skills/dev/SKILL.md`
keeps its `+upstream.<sha>` suffix, updated only when an upstream merge changes
the base commit — see [UPSTREAM.md](../UPSTREAM.md).
