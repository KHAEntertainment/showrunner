# SC-5 — provider/tool invocation (`provider-request-v1`, `provider-result-v1`)

**Source revision.** Showrunner v2.2 SDP `63124e80…` §8 l.544. Issue #184's body cites the superseded snapshot `dae53a66…`; this spec binds the current snapshot.

**Contracts.** `provider-request-v1` (a request to a provider/model/tool) and `provider-result-v1` (the result/error it returns).

**Semantic owner.** Shared utility owner; the domain owns the verdict (l.544).

**Version owner.** This SDP owns the version identifier.

**Producer.** Existing locator/review helpers and the migration diagnostic; planned Scout and stop judge.

**Consumers (package).** P1 (minimal provider discovery, absent/drift fallback, `needs_input`); U2, O-STOP, O-DB later.

**Authoritative writer / one writer per ledger.** The domain owns the verdict; the shared utility owns the request/result envelope. `provider-request-v1` / `provider-result-v1` are envelopes — credentials are carried by reference only (l.544). No new service/SDK abstraction is required merely to meet P1 (l.544).

**Field table.** Meanings from the SDP only.

| Field | Type | Cardinality | Required/conditional | Meaning |
| --- | --- | --- | --- | --- |
| `domain` / `schema` | string | 1 | required | the domain and its schema |
| `source_digest` | digest | 1 | required | source digest |
| `sensitivity` | enum | 1 | required | sensitivity of the source |
| `allowed_capabilities` | list | 1 | required | the capabilities the request permits |
| `provider` / `model` / `route` | reference | 1 | required | the provider, model, and route |
| `usage` | string | 1 | required | bounded usage |
| `retry` | number | 1 | required | retry bound |
| `result` / `error_provenance` | record | 1 | required | result or error provenance |
| `credentials` | reference | 0..* | conditional | credentials by reference only — never inline (l.544) |

**Accepted example.** A scoped read-only finding, or a typed domain answer (l.544).

**Rejected example.** Secret-bearing requests; model-granted writes; an unavailable required judgment defaulting to LOW; one domain's calibration asserted for another (l.544).

**Edge cases.**

- secret-bearing request → `reject`
- model-granted write → `reject`
- unavailable required judgment defaulting LOW → `reject`
- one domain's calibration asserted for another → `reject`

**Fixtures.**

- `fixtures/sc-5/accepted-scoped-read-only-finding.json` (accept)
- `fixtures/sc-5/rejected-secret-bearing-request.json` (reject)

**Counterpart acceptance.** `pending` per consumer (P1; U2, O-STOP, O-DB later). No compatibility inferred from silence (l.550).
