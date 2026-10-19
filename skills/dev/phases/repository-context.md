# Repository & Account Context — canonical procedure

One canonical procedure, referenced by every phase and agent prompt that
touches a Git push or a GitHub read/mutation. Do not redefine this logic
independently in another prompt file; reference this one.

`.dev.json` at the worktree root records confirmed, nonsecret project intent.
It never holds a token, password, private key, or credential-bearing URL.
`skills/dev/scripts/dev_config.py` owns its schema, validation, and creation.
`skills/dev/scripts/resolve_repository.py` owns comparing that intent against
what a checkout and its authentication would actually do — and **loads
`.dev.json` itself**: pre-write checks fail closed on a missing, invalid, or
tracked config. First-use candidate checks are explicitly separate and never
authorize a write.

```json
{
  "version": 1,
  "github": {
    "host": "github.com",
    "account": "your-account",
    "pushRepository": "your-account/project",
    "pullRequestRepository": "your-account/project",
    "pushRemote": "origin"
  }
}
```

## First invocation (run before any GitHub mutation, Phase 0)

1. Locate the worktree root (`git rev-parse --show-toplevel`, or the
   explicitly selected project root before Git exists). Do not search parent
   directories for another project's `.dev.json`.
2. Run `rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/dev_config.py" status`. Its `status` field decides the next step:
   - `tracked` — `/.dev.json` is committed in this repository. **Stop.**
     A repository-supplied file is never trusted as user-confirmed intent.
     Ask the user for a focused decision before doing anything else.
   - `invalid` — a file exists but fails schema validation. **Stop.** Report
     the `reason`. Never rewrite or discard the file to make it valid.
   - `not_ignored` — the file is valid and untracked, but not yet covered by
     the repository-local exclude file. Run `rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/dev_config.py" exclude`
     before treating it as ready, then re-check status. This preserves the file.
   - `incomplete` — Git provenance or local I/O could not be verified. Stop
     and report the reason; do not treat a Git error as a new project.
   - `valid` — reuse it. Do not ask the user to reconfirm values that already
     agree with observed reality.
   - `missing` — continue to step 3.
3. For `missing` on an existing checkout: collect candidate remotes, every
   effective push URL, GitHub repository metadata, and available account
   evidence with read-only calls only. Remote names, fork metadata, and the
   active CLI account are candidates, not confirmed intent.
   - If the repository is a fork (or the user states a work-type preference),
     present the two supported presets and their resulting destinations:

     | Preset | Git pushes | Plugin task issues | PRs |
     | --- | --- | --- | --- |
     | Independent fork | user's fork | user's fork | user's fork |
     | Upstream contributor | user's fork | user's fork | explicitly confirmed upstream |

     Never infer contributor mode merely because GitHub reports a parent.
     When contributor mode is selected, confirm the actual upstream target
     explicitly. A preset initializes the explicit fields; do not persist a
     separate `workType` field that could disagree with them.
4. Present one compact setup proposal — account, push/task-issue repository,
   push remote, and PR repository — and ask for confirmation or a correction
   together. Reuse an explicit choice the user already supplied instead of
   asking again.
5. Verify the selected values against available repository/authentication
   facts: use the account modes below with `--setup-account-check`, the proposed
   `--account`, and exact candidate push URLs. This option is permitted only
   while config is missing. A successful `candidate_verified` result supports
   setup only; it never licenses a GitHub write. After saving config, repeat
   the ordinary check without this flag and require `verified`. An
   unresolved identity/destination mismatch on an existing checkout stops
   setup; do not stamp a guessed configuration as established.
6. Run `rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/dev_config.py" create` with the confirmed values. It refuses to
   overwrite an existing file; if another setup process created one
   meanwhile, read and compare instead of replacing it.
7. Confirm the file is excluded (`dev_config.py` runs `ensure_excluded`
   automatically on create) before staging any project files. A file already
   tracked by the project requires the same focused user decision as step 2;
   never untrack or overwrite it automatically.

### A genuinely new project (no remote yet)

No remote or repository may exist on the first invocation. Confirm the
intended name/owner/account, verify the available GitHub account, and save
those confirmed values at the selected project root with
`rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/dev_config.py" create`.
Use `--setup-account-check` only for that initial read-only account discovery.
Explicitly report that remote and Git-transport checks are pending —
file existence never makes a push ready. If the user has not chosen a name or
usable account yet, leave setup incomplete rather than inventing one; finish
it before the first GitHub write. Phase 2's bootstrap step is responsible for
the actual repository creation; before that write, check the CLI account
(`rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/resolve_repository.py" --repo-dir "<selected-project-root>" --mode check-gh-account --account <github.account>`)
and create using the full confirmed `github.pushRepository` (which may belong to an organization), never a bare
project name. After creation/clone, re-run this procedure to verify the
actual remote, repository, and Git identity before any push. If bootstrap
creates a different local root, move the confirmed file there explicitly and
exclude it before any staging.

## Worktrees

When preparing a worker/QA/reviewer worktree, the lead copies the confirmed
local file into the new worktree before launch, after verifying the
source/worker Git common-directory relationship. Do not overwrite a
differing worker config — if one already exists and disagrees, report it
rather than replacing it. This avoids a new setup interview per worker while
preserving the same target intent. A worker or resumed session that finds no
config in an unrelated clone triggers first-use setup, not a silent copy from
elsewhere.

## Pre-write verification (run immediately before every push and every GitHub mutation)

Never reuse a verdict from before a config, credential, branch, or remote
change — recheck immediately before the write, using the same remote/target
and refspec the write will use. `resolve_repository.py` always loads and
requires a valid `.dev.json` for both forms below; there is no way to bypass
that by omitting a flag.

### Before a Git push

```bash
rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/resolve_repository.py" --repo-dir <worktree> --operation push \
  --assigned-branch <ledger-assigned branch>
```

- Loads `.dev.json`, resolves the actual effective push remote and **every
  one of its push URLs** (fetch URLs are separate context and never block —
  a fork that fetches upstream while pushing to itself is a supported shape,
  not a mismatch), and requires them to match `github.pushRepository` and
  `github.pushRemote`.
- Verifies the actual Git transport account for every effective push URL against `github.account`; any failed or unsupported account check stops before the dry run.
- Confirms the current checkout is actually on `--assigned-branch`, then runs
  `git push --dry-run` for the exact validated remote and refspec. Like account and access verification, this can contact the remote: it never advances a ref, but it is
  evidence that the checked refspec is accepted. The only permitted destination is `refs/heads/<ledger-assigned branch>`; a differing `--dest-ref` stops the write.
- Exit 0 with `status: "ready"` means push. Use the printed
  `effective_push_remote` (or `--print-push-remote`) as the remote argument —
  never a value read from a rejected verdict, and never a bare `git push`
  that lets Git's own default choose:
  ```bash
  remote="$(rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/resolve_repository.py" --repo-dir <worktree> --operation push \
    --assigned-branch <branch> --print-push-remote)" || exit 1
  rtk proxy git push "$remote" "refs/heads/<branch>:refs/heads/<branch>"
  ```
- Exit 2 means stop — no fallback, no default selection. `gh_default` and
  `notes` in the JSON output are informational only: an unrelated `gh repo
  set-default` disagreeing with the target does **not** block.

### Before a force-with-lease push (rebased branch)

A rebased branch cannot be pushed fast-forward, so the plain check above ends
`dry_run_failed`. That is correct and stays the default: **a worker never rebases
and force-pushes on its own.** A lease is allowed only when the lead's
assignment or a later message explicitly instructs a rebase of that branch. Prefer
`git merge --no-ff origin/main` (a fast-forward push) whenever the instruction
allows it. The lease check is the only sanctioned way to push a rebase; skipping
the pre-write check, or any bare `--force`, `-f`, or `+<refspec>`, is never allowed.

Use the remote head oid the lead authorised replacing (`<oid>`, normally the PR's
current `headRefOid`):

```bash
remote="$(rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/resolve_repository.py" --repo-dir <worktree> --operation push \
  --assigned-branch <branch> --force-with-lease <oid> --print-push-remote)" || exit 1
rtk proxy git -C <worktree> push --force-with-lease="refs/heads/<branch>:<oid>" "$remote" "refs/heads/<branch>:refs/heads/<branch>"
```

- Never fill `<oid>` by reading the remote yourself and pushing whatever you
  find: that defeats the lease. If the live head is not the oid you were given,
  the check says `lease_mismatch`; stop and report both oids.
- `--force-with-lease <oid>` takes a full 40- or 64-character lowercase object
  id. An abbreviation, ref name, empty, uppercase, or padded value is refused
  (`invalid_lease_oid`).
- It runs every check of the branch push above, then reads the live head of
  `refs/heads/<branch>` with `git ls-remote --symref` from **every** push URL (never a
  local `refs/remotes/*` ref) and requires it to equal the lease, then runs
  `git push --dry-run --force-with-lease=refs/heads/<branch>:<oid> <remote> refs/heads/<branch>:refs/heads/<branch>`.
- The real push must carry the identical lease: Git re-checks it atomically at
  push time, so a push that landed after the check is not overwritten.
- It applies only to `--operation push --assigned-branch`. Combined with
  `--operation pr`/`issue`, `--tag-target`, `--fixture`, a `check-*` mode, or no
  `--assigned-branch`, it is refused (`lease_not_applicable`).
- A lease never replaces the remote's default branch: the same `ls-remote` read
  includes the remote `HEAD` symref, and an assigned branch equal to it is
  refused (`lease_on_default_branch`). If the default branch cannot be read, the
  check fails closed (`default_branch_unresolved`).
- The lease-specific checks add these 6 reason codes: `invalid_lease_oid`,
  `lease_not_applicable`, `lease_mismatch` (names both oids),
  `lease_branch_missing`, `remote_head_unresolved`, `lease_on_default_branch`.
  They reuse the existing `remote_unreachable`, `push_url_unavailable`,
  `default_branch_unresolved` and `dry_run_failed`. Every one is exit 2
  with no push target; stop and report it.
- Without the flag nothing changes: a non-fast-forward is still `dry_run_failed`.
- After a lease push the PR head changes, so prior review and QA results for the
  old head no longer apply; report the new head to the lead.

### Before a release tag push

A release tag is cut from the remote default branch's tip, often from a clean
detached checkout or a linked worktree on another branch, so the branch guard
above does not apply. Use tag mode instead — `--tag-target` replaces
`--assigned-branch`, and the two together are rejected:

```bash
remote="$(rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/resolve_repository.py" --repo-dir <worktree> --operation push \
  --dest-ref refs/tags/<tag> --tag-target <commit> --print-push-remote)" || exit 1
```

Run it **before** `git tag` (a tag that already exists locally is refused),
tag the same `<commit>` explicitly, then push `refs/tags/<tag>` to `"$remote"`.

- Runs the same remote-identity and transport-account checks as a branch push,
  and additionally verifies the `gh` CLI login against `github.account`.
- Requires no checked-out branch. `--dest-ref` must be `refs/tags/<name>`;
  `--tag-target` must resolve to a commit in this checkout.
- Reads the default branch live from each push URL with
  `git ls-remote --symref <push-url> HEAD` — never from a local `origin/HEAD` or
  `refs/remotes/*` ref, so a stale clone cannot pass and no fetch is needed.
  The target must equal that tip at **every** push URL.
- Refuses a tag that already exists locally or on any push URL, then runs
  `git push --dry-run <remote> <commit>:refs/tags/<tag>`.
- The tag-specific checks add these 11 reason codes: `invalid_tag_target`,
  `invalid_tag_destination`, `conflicting_arguments`, `tag_exists_local`,
  `local_tag_check_failed`, `push_url_unavailable`, `remote_unreachable`,
  `default_branch_unresolved`, `target_mismatch`, `tag_exists_remote`,
  `dry_run_failed`. Identity, transport-account and `gh` login refusals keep
  their existing codes. Under `--print-push-remote`, stdout carries the remote
  only on `ready`. A refusal exits 2, and stdout may carry the JSON verdict or
  nothing depending on which check refused, so gate on the exit status, never
  on stdout.
- Known refusal: a `branch.<current>.pushRemote` that names a different remote
  than `github.pushRemote` fails closed in a linked worktree, as it does for a
  branch push. Remedy: run from a detached checkout, where no branch setting
  applies.

### Before a PR or Issue operation

```bash
rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/resolve_repository.py" --repo-dir <worktree> --operation pr \
  --target <the literal OWNER/REPO you are about to pass to gh>
```

This has nothing to do with git push URLs — a PR/Issue is a literal `--repo`
argument, so the check is simply "does that argument match confirmed
intent". Use `--operation pr` (target must equal `pullRequestRepository`) for
PR create/read/review/merge, or `--operation issue` (target must equal
`pushRepository` by default) for a plugin-created Issue. For an operation on
an **explicitly assigned existing Issue** whose own qualified repository
identity is expected to differ (already confirmed via the ledger, not
re-derived here), add `--allow-target-override`. The same flag applies to an explicitly approved one-off upstream PR recorded in the task ledger; it never changes `.dev.json` or permits an upstream Git push. Every `ready` result here
also verifies the actual `gh` CLI login
against `github.account`
before you may treat the operation as safe — two accounts can both have
access to a repository, so a correct Git credential does not establish which
account `gh` will use.

A conflicting `GH_HOST` stops the account/operation check. Use `--hostname github.com` for `gh api`, `--repo github.com/OWNER/REPO` for commands accepting it, and `GH_HOST=github.com` with the full configured `OWNER/REPO` for repository creation. Do not switch a conflicting host silently.

Use the confirmed target explicitly in the command: `gh <cmd> --repo
github.com/<owner/repo>` where accepted, the explicit REST/GraphQL endpoint path or
repository identity for `gh api`, and the positional repository for `gh repo
create`. Never rely on a cwd-derived `{owner}`/`{repo}` placeholder or an
inherited `gh` default. Reference an Issue in another repository as `Closes
OWNER/REPO#N` (or its URL), never a bare `#N`.

**Run this check before the first command that touches the repository at
all** — including an early read like posting an understanding-confirmation
comment on an Issue, not only the final write. A check run only immediately
before the last command in a sequence leaves every earlier command in that
sequence unscoped.

### Authentication support boundary

| Transport | Supported verification |
| --- | --- |
| Ordinary HTTPS with an existing credential helper | `rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/resolve_repository.py" --repo-dir "<worktree>" --mode check-https-account --url <exact push URL> --account <github.account>` — `git credential fill` for the exact URL/context, checked in-process only |
| Standard OpenSSH, including host aliases | `rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/resolve_repository.py" --repo-dir "<worktree>" --mode check-ssh-account --url <exact push URL> --account <github.account>` — resolves the alias via `ssh -G` with the URL-explicit user and port applied, then probes the **original alias** (never the resolved hostname) so the alias's own port/identity/user apply exactly as a real push would; requires GitHub's documented greeting and exit status **1** |
| GitHub CLI / API mutation | `rtk proxy python3 "${CLAUDE_SKILL_DIR}/scripts/resolve_repository.py" --repo-dir "<worktree>" --mode check-gh-account --account <github.account>` — `gh api --hostname github.com user`, never `gh auth status` alone |

Ordinary account modes load the validated config and verify its account;
an optional `--account` must agree with it. `verified` is the only account
status that permits proceeding to a write; `candidate_verified` is setup
evidence only. `incomplete` with
`unsupported_transport_auth`, `identity_unavailable`, or `account_mismatch`
all stop the write. Commit authorship, a URL username, and `gh auth status`
alone never establish this — they are not accepted as substitutes.

Anything else — `GIT_SSH_COMMAND`/`GIT_SSH`/`core.sshCommand`/`ssh.variant`
overrides, an HTTP auth override matched the way Git itself matches it
(`git config --get-urlmatch http.extraHeader <url>`, not a literal key), an
askpass fallback (`GIT_ASKPASS`/`SSH_ASKPASS` or `core.askPass`), or an
unreadable/unexpected probe response — returns `unsupported_transport_auth`
or `identity_unavailable` rather than probing a different, lower-precedence
source. Never run credential `approve`/`reject`, persist a new credential,
switch accounts, or accept a new SSH host key automatically. A
credential-helper secret is captured only inside the helper process; it is
never printed, logged, or written to a temp file or the ledger.

This narrows stale-state exposure within the supported workflow; it is not an
atomic guarantee against a concurrent hostile change.

## Multiple GitHub accounts on one host

Two or more GitHub accounts may share a single host (a personal account plus
a work account, an operator plus a bot). The skill is a verification layer:
`.dev.json` records the intended account, and the pre-write checks compare it
against the real `gh` login, HTTPS credential, or SSH identity, refusing to
write on a mismatch. **The skill never chooses the account and never
persists host or credential state.** That is by design — picking the account
is host setup, and the skill has no opinion on it. Routing comes from
user-approved host changes that are made explicitly, reported back in the
same turn they are made, and verifiable from the ledger afterwards; no
account is switched automatically, no token is duplicated silently, and no
credential is persisted on the user's behalf.

When the lead finds the project `.dev.json` account disagrees with the active
`gh` user, the SOP names this section, asks the user to approve the host
changes that follow, and never persists anything until that approval is
recorded.

### Recommended routing layer

These are host changes the **user** makes; the skill only verifies them.

- **Git pushes.** Configure `credential.https://github.com.useHttpPath=true`
  in `~/.gitconfig`, plus one
  `credential.https://github.com/<ORG>.username=<login>` entry per org that
  this host writes to. The `gh` (or git-credential-manager) credential
  helper then selects the right token by remote path from the multi-user
  hosts file, so the skill's HTTPS check passes for the right reason without
  re-prompting. No token duplication is needed.
- **`gh` CLI.** Set `GH_CONFIG_DIR` to a project-scoped config directory in
  `.claude/settings.local.json` `env`, holding only that account's login. The
  skill's `check-gh-account` output records the effective `GH_CONFIG_DIR`
  (or `"default"`) so the ledger shows which login was verified. **Seeding
  that directory by piping a token from an existing login is credential
  persistence and requires the user's explicit approval in the same turn**;
  an unpiped interactive `gh auth login` per project is the lower-risk path.
  Cross-reference #37, the SSH half of the same host situation; this section
  is the HTTPS and `gh` CLI half, and the two land or cross-reference
  together.
- **Commit author identity.** `includeIf "gitdir:/path/to/work"` in
  `~/.gitconfig` is acceptable **only** when the user confirms every repo
  under that directory belongs to that identity; otherwise set `user.email`
  per repo. A cross-pollinated repo under that folder pushing to a remote
  belonging to the other account would otherwise carry the wrong author.

### Evidence rule

Any claim about cross-shell behaviour ("fails closed", "prompts", "uses
account B") must be exercised with `git push --dry-run` (and, for `gh`, a
`check-gh-account` from the other shell) **before** it is asserted. Absence
of a test is not a pass: the failing-closed verdict is the only verdict
that is verifiable from this machine.

### Lane propagation

The `GH_CONFIG_DIR` (or absence thereof) from the lead's session is carried
into the worker, QA, and reviewer assignment envelopes
(`backends/contract.md`, `## Provider-neutral assignment envelope`). A lane
that runs with a different `GH_CONFIG_DIR` than the lead's pre-write check
verified sees a different login than the one the lead authorised; the
envelope pinning prevents that drift.

### New-project order

`dev_config.py create --no-exclude` writes `.dev.json` but skips
`info/exclude`, so before `git init` the file is valid and untracked but not
yet ignored by anything. After Phase 2's bootstrap `git init`, re-run
`dev_config.py exclude` so the file is covered by the repository-local
exclude file before any project files are staged; `dev_config.py status`
then reports `valid`, not `not_ignored`.
