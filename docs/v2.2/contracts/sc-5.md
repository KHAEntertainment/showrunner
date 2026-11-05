# SC-5 — provider/tool invocation (`provider-request-v1`, `provider-result-v1`)

**Source revision.** Showrunner v2.2 SDP `7177580c…` §8 l.544 (snapshot SHA-256 `7177580c8429d6e5f8f07e6138de72506ac7a419e9697f5102f842d43a93315b`, 819 lines). Issue #184's body cites the superseded snapshot `dae53a66…`; the earlier snapshot `fee134d9…` is superseded by `7177580c…` (re-pinned 2026-11-05).

L0b revision (2026-11-05) cites SDP `7177580c…`; l.540/544/545 unchanged from `fee134d9`.

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
| `credentials` | reference | 0..* | conditional (condition not stated in the SDP; present only when the source records it (no default inferred)) | credentials by reference only — never inline (l.544) |

**`result` sub-table.** `provider-result-v1` `result.type` ∈ {`finding`, `needs_input`, `not_available`, `drift`, `error`} (SDP l.81; AC-02 l.750).

| `result.type` | `cause` / `question` | Meaning |
| --- | --- | --- |
| `finding` | none | a scoped read-only finding or typed domain answer — the domain owns the verdict (l.544) |
| `needs_input` | `question` (required, read-only) | a question returned to the lead, who answers from evidence or escalates genuinely user-owned choices (l.81) |
| `not_available` | `cause` (required) | the provider is absent; fall back visibly, never install automatically (l.81) |
| `drift` | `cause` (required) | the provider pin mismatches the located/installed provider; fall back visibly (l.81) |
| `error` | `cause` (required) | a failed invocation with error provenance |

`cause` is required for `not_available`, `drift` and `error`. `not_available` and `drift` are never reported as a completed research step — they are a visible fallback, not a step result (l.81; l.750).

**Accepted example.** A scoped read-only finding, or a typed domain answer (l.544); a `needs_input` question back to the lead; an absent/drifted provider falling back visibly with a `cause` (l.81, l.750).

**Rejected example.** Secret-bearing requests; model-granted writes; an unavailable required judgment defaulting to LOW; one domain's calibration asserted for another (l.544); a `not_available`/`drift`/`error` result without a `cause` (l.81, l.750).

**Edge cases.**

- secret-bearing request → `reject`
- model-granted write → `reject`
- unavailable required judgment defaulting LOW → `reject`
- one domain's calibration asserted for another → `reject`
- `not_available` / `drift` / `error` without `cause` → `reject`
- `needs_input` without `question` → `reject`

**Fixtures.**

- `fixtures/sc-5/accepted-scoped-read-only-finding.json` (accept)
- `fixtures/sc-5/rejected-secret-bearing-request.json` (reject)
- `fixtures/sc-5/accepted-needs-input.json` (accept)
- `fixtures/sc-5/accepted-drift-fallback.json` (accept)
- `fixtures/sc-5/rejected-not-available-without-cause.json` (reject)

**Counterpart acceptance.** `pending` per consumer (P1; U2, O-STOP, O-DB later). No compatibility inferred from silence (l.550).

**Revision note.** Additive v1 revision, 2026-11-05, M2 L0b (defects D-SC1-1, D-SC5-1). Consumers listed unchanged.
