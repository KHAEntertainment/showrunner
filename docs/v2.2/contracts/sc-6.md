# SC-6 — records/config/tracker (`project-binding-v1`, `record-link-v1`)

**Source revision.** Showrunner v2.2 SDP `fee134d9…` §8 l.545. Bound schemas: `.dev.json` closed schema (`skills/dev/scripts/dev_config.py`, `SUPPORTED_VERSION = 1`), Foreman project config `~/foreman/showrunner/.foreman/project.json` (SHA-256 `f68b259be5bc4ab5e4818865bb28a12770a7a1a6f00b36686fa6f0c531373ad3` (revision 2197d2a)), Foreman state `~/.claude/skills/foreman-showrunner/templates/FOREMAN_STATE_TEMPLATE.md` (SHA-256 `acfd05c47757a1eaffc019889645e6f910c5067fcad95ea8a05f6b6f09e11204`). Issue #184's body cites the superseded snapshot `dae53a66…`; this spec binds the current snapshot.

**Contracts.** `project-binding-v1` (explicit project/repo/host intent) and `record-link-v1` (a link between records and tracker IDs).

**Semantic owner.** Each record owner owns its record; the tracker integration owner maps IDs.

**Version owner.** This SDP owns the version identifier.

**Producer.** Dev `.dev.json` closed schema, Foreman project config/bridge, board config; later #104/Scout.

**Consumers (package).** P1 (export intake); O-TRACK later (per-tracker operation/dedup/retry).

**Authoritative writer / one writer per ledger.** Each record owner is the authoritative writer of its own record; the integration owner maps IDs. `.dev.json` records intent and never holds a token/password/key (`dev_config.py`). `project-binding-v1` / `record-link-v1` carry policy/state/credential refs separately (l.545). Existing supported connections and the Foreman bridge are **not** removed by CUT-6 (l.545).

**Source → projection mapping.**

| Source field (schema) | `project-binding-v1` / `record-link-v1` |
| --- | --- |
| `dev_config.py` `github.host` / `github.account` | `host` / `account` (project intent) |
| `dev_config.py` `github.pushRepository` | `push_repository` — the push destination |
| `dev_config.py` `github.pullRequestRepository` | `pull_request_repository` — the PR destination (kept distinct from push) |
| `dev_config.py` `github.pushRemote` | `push_remote` — the named push remote |
| `dev_config.py` `version` (`SUPPORTED_VERSION = 1`) | config schema version |
| `project.json` `repo.github` | `repository` |
| `project.json` `repo.default_branch` | destination branch |
| `project.json` `tracker.kind` + `tracker.repo` | tracker-qualified IDs (`OWNER/REPO#N`) |
| `FOREMAN_STATE_TEMPLATE.md` `github_bridge.last_scan` / `bridged` / `left` | bridge watermark and bridged records (Linear trackers only) |

**Board schema.** Not identified in this package's pinned sources. Recorded as `unavailable/deferred` with reason: board notes/presence are owned by the board, and the board schema is not among the sources pinned for SC-6 here. No D9 question is decided by this package.

**Field table.** Meanings from the SDP only; required/conditional are source-dependent (`.dev.json` vs a supplied document vs Foreman `project.json`).

| Field | Type | Cardinality | Required/conditional | Meaning |
| --- | --- | --- | --- | --- |
| `source` | enum (`dev-config` / `foreman-project` / `supplied-document`) | 1 | required | which source the record projects: `.dev.json`, Foreman `project.json`, or a supplied document |
| `project` / `repo` / `host` | qualified identifier | 1 | required | explicit project/repo/host. **Alias (declared):** Foreman `project.json` `repo.github` maps to the same `project`/`repo` meaning; a record uses one spelling, never both inconsistently |
| `push_repository` | qualified identifier | 0..1 | conditional (`dev-config` source) | push destination (distinct from PR destination), `dev_config.py` `github.pushRepository` |
| `pull_request_repository` | qualified identifier | 0..1 | conditional (`dev-config` source) | PR destination, `dev_config.py` `github.pullRequestRepository` |
| `push_remote` | string | 0..1 | conditional (`dev-config` source) | named push remote, `dev_config.py` `github.pushRemote` |
| `destination_branch` | string | 0..1 | conditional (`foreman-project` source) | default branch, `project.json` `repo.default_branch` |
| `tracker_ids` | list of tracker-qualified IDs/revisions | 1..* | required (`record-link-v1`); conditional otherwise | tracker-qualified IDs and revisions |
| `bridge` | record | 0..1 | conditional (Linear trackers only) | bridge watermark / bridged records, `FOREMAN_STATE_TEMPLATE.md` `github_bridge` |
| `provenance` | record (`origin`, `digest`) | 1 | required | provenance of the record; `origin` names the source |
| `authoritative_writer` | identity record | 1 | required | the authoritative writer |
| `operation` | enum (read/write) | 1 | required | intended read/write operation |
| `delivery` / `dedup_identity` | record | 1 | required | delivery and dedup identity |
| `policy_ref` / `state_ref` / `credential_ref` | references | 0..* | conditional (condition not stated in the SDP; present only when the source records it (no default inferred)) | kept separate (l.545) |

**Source-dependent required fields.** A `supplied-document` record carries `project`/`repo`/`host` + `provenance` and need not pretend to be Dev config — no `push_repository`/`pull_request_repository`/`push_remote`. A `dev-config` record carries those config fields (distinct push vs PR destinations). A `foreman-project` record carries `repository` (alias of `project`/`repo`), `destination_branch`, and `bridge` when the tracker is Linear.

**Accepted example.** A supplied document with verified provenance; an existing authorized bridge link (l.545).

**Rejected example.** A guessed cwd project; duplicate sync writers; acknowledgment treated as an applied ruling; preference overriding a grant (l.545).

**Edge cases.**

- guessed cwd project → `reject`
- duplicate sync writers → `reject`
- acknowledgment treated as applied ruling → `reject`
- preference overriding grant → `reject`

**Fixtures.**

- `fixtures/sc-6/accepted-verified-provenance-document.json` (accept)
- `fixtures/sc-6/accepted-mapped-config-bridge.json` (accept — uses mapped config/bridge fields)
- `fixtures/sc-6/rejected-guessed-cwd-project.json` (reject)

**Counterpart acceptance.** `pending` per consumer (P1; O-TRACK later). No compatibility inferred from silence (l.550).
