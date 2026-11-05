# SC-6 — records/config/tracker (`project-binding-v1`, `record-link-v1`)

**Source revision.** Showrunner v2.2 SDP `63124e80…` §8 l.545. Bound schemas: `.dev.json` closed schema (`skills/dev/scripts/dev_config.py`, `SUPPORTED_VERSION = 1`), Foreman project config `~/foreman/showrunner/.foreman/project.json` (SHA-256 `f68b259be5bc4ab5e4818865bb28a12770a7a1a6f00b36686fa6f0c531373ad3`). Issue #184's body cites the superseded snapshot `dae53a66…`; this spec binds the current snapshot.

**Contracts.** `project-binding-v1` (explicit project/repo/host intent) and `record-link-v1` (a link between records and tracker IDs).

**Semantic owner.** Each record owner owns its record; the tracker integration owner maps IDs.

**Version owner.** This SDP owns the version identifier.

**Producer.** Dev `.dev.json` closed schema, Foreman project config/bridge, board config; later #104/Scout.

**Consumers (package).** P1 (export intake); O-TRACK later (per-tracker operation/dedup/retry).

**Authoritative writer / one writer per ledger.** Each record owner is the authoritative writer of its own record; the integration owner maps IDs. `.dev.json` records intent and never holds a token/password/key (`dev_config.py`). `project-binding-v1` / `record-link-v1` carry policy/state/credential refs separately (l.545). Existing supported connections and the Foreman bridge are **not** removed by CUT-6 (l.545).

**Field table.** Meanings from the SDP only.

| Field | Type | Cardinality | Required/conditional | Meaning |
| --- | --- | --- | --- | --- |
| `project` / `repo` / `host` | qualified identifier | 1 | required | explicit project/repo/host |
| `tracker_ids` | list of tracker-qualified IDs/revisions | 1..* | required | tracker-qualified IDs and revisions |
| `provenance` | record | 1 | required | provenance of the record |
| `authoritative_writer` | identity record | 1 | required | the authoritative writer |
| `operation` | enum (read/write) | 1 | required | intended read/write operation |
| `delivery` / `dedup_identity` | record | 1 | required | delivery and dedup identity |
| `policy_ref` / `state_ref` / `credential_ref` | references | 0..* | conditional | kept separate (l.545) |

**Accepted example.** A supplied document with verified provenance; an existing authorized bridge link (l.545).

**Rejected example.** A guessed cwd project; duplicate sync writers; acknowledgment treated as an applied ruling; preference overriding a grant (l.545).

**Edge cases.**

- guessed cwd project → `reject`
- duplicate sync writers → `reject`
- acknowledgment treated as applied ruling → `reject`
- preference overriding grant → `reject`

**Fixtures.**

- `fixtures/sc-6/accepted-verified-provenance-document.json` (accept)
- `fixtures/sc-6/rejected-guessed-cwd-project.json` (reject)

**Counterpart acceptance.** `pending` per consumer (P1; O-TRACK later). No compatibility inferred from silence (l.550).
