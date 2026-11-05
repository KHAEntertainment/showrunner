# Technical Plan — <slug>

Draft out of git (Traycer artifact, or `.agent/plans/<slug>.md` in native mode). Promote only the approved copy to `docs/plans/<YYYY-MM-DD>-<slug>.md` through a docs-only PR.

---

## Intent and destination

What this change accomplishes and the target system or repository it lands in. Most existing-repository work states its intent here and needs no separate PRD (D6.2.2).

## Source documents and provenance

For each supplied source, record three per-source fields (D6.3.6):

- **origin** — the source's location or identity (a tracker-qualified identifier, a harness plan-mode file, a Traycer Tech Plan, or `pasted` when no identifier exists).
- **revision or digest** — the source's revision or digest as read.
- **directives not followed** — the source's foreign workflow directives, listed once and not followed.

`plan_ref.source_revision` carries only the drafted-from input's digest; the source locator lives in this section, not in `plan_ref`.

## Locked decisions

Decisions settled at intake or during drafting, each with its source citation. Frozen-PRD decisions are cited, not re-asked (D6.2.3).

## Gaps

Open items that still need a decision, each at decision granularity. Document conflicts become gaps here (D6.3.5).

## Approach

How the change is made: the mechanism, the sequence, and the reversible engineering details.

## Affected areas

Files, modules, and flows the change touches, with caller impact.

## Verification

How the change is checked — tests, gates, and evidence, one executor per check.

## Amendments

A material amendment creates a new revision and reopens affected approval (D6.2.3, D6.2.4). Record each amendment here.

---

## `plan_ref` (SC-1)

The shape is the `plan_ref` sub-table of SC-1 (`docs/v2.2/contracts/sc-1.md` @ `f839f15`), and it must not require machine-specific paths:

```text
origin:
source_revision:
approved_revision:
approval:
  authority:
  evidence:
producer:
  session:
  harness:
```

**D4 invariant.** The assignment's top-level `approval_revision` equals `plan_ref.approved_revision`; the assignment `source` names the promoted plan at this revision; and `plan_ref.source_revision` is the drafted-from input.
