# SC-8 — distribution/adoption (`component-receipt-v1`)

**Source revision.** Showrunner v2.2 SDP `63124e80…` §8 l.547. Issue #184's body cites the superseded snapshot `dae53a66…`; this spec binds the current snapshot.

**Contract.** `component-receipt-v1` — the receipt for an installed or adopted component.

**Semantic owner.** Package/component maintainers.

**Version owner.** This SDP owns the version identifier.

**Producer.** Existing Showrunner installers/catalog and Foreman install/discovery scripts; handoff release/native registration.

**Consumers (package).** P5 (archive/install/path/catalog/backup tests); I1 later (package policy changes explicit); U1 later (host independent of full Scout).

**Authoritative writer / one writer per ledger.** Each package/component maintainer owns its own receipt. `component-receipt-v1` is a receipt over existing installers/catalog — it introduces no new writable store. Holds remain (l.547).

**Field table.** Meanings from the SDP only.

| Field | Type | Cardinality | Required/conditional | Meaning |
| --- | --- | --- | --- | --- |
| `source_digest` / `release` | digest + reference | 1 | required | source digest and release |
| `installed_version` vs `adopted_version` | version pair | 1 | required | installed vs adopted version |
| `supported_interface` / `runtime` | record | 1 | required | supported interface and runtime |
| `registration` | record | 1 | required | registration |
| `load_proof` | per-session load proof | 1 | required | per-session load proof (not a global marker) |
| `update_window` / `backup` / `rollback` | references | 0..* | conditional | update window, backup, and rollback refs |

**Accepted example.** A compatible existing installation; a safe next-session adoption (l.547).

**Rejected example.** Hot replacement of running instructions; a global load marker counted as per-run coverage; incompatible schema/runtime; an optional component forced at core install (l.547).

**Edge cases.**

- hot replacement of running instructions → `reject`
- global load marker as per-run coverage → `reject`
- incompatible schema/runtime → `reject`
- optional component forced at core install → `reject`

**Fixtures.**

- `fixtures/sc-8/accepted-compatible-existing-installation.json` (accept)
- `fixtures/sc-8/rejected-hot-replacement.json` (reject)

**Counterpart acceptance.** `pending` per consumer (P5; I1, U1 later). No compatibility inferred from silence (l.550).
