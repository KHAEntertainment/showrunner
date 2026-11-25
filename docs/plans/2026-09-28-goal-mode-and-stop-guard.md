# Assessment and plan: Span-01, /dev goal mode, and a stop guard

> **Status: planned for v2.2.0, not started.** Nothing in this plan is implemented. It is feature and scope-increasing work, so it targets v2.2.0 rather than a v2.1.x patch release (decided 2026-09-29).
>
> Research and planning only; nothing was implemented in this session.
> Observed 2026-09-28. Execute after v2.1.2 lands. The earlier plan in this PR (`docs/plans/2026-09-26-technical-planning-and-research-providers.md`) is unchanged; this plan builds on its WP-A2 where noted.
> **Step 0 (done):** this plan was saved here on branch `claude/optimistic-fermi-nrtegl` (PR #81) when the planning session closed.
>
> **Sources:**
> - Web search snippets. openrouter.ai, respan.ai and runtimewire.com were blocked by the egress proxy, so their pages were never fetched.
> - `OpenRouterTeam/skills@067f57c` (`skills/openrouter-decisions`).
> - `phaseoteam/Phaseo` PR #2629 (a Span-01 adapter).
> - `noplan-inc/limpet@7a841b0` and `valentynkit/jev-belay@ef719db`.
> - NousResearch/hermes-agent#126036.
> - Claude Code hooks and `/goal` docs.
> - A read-only map of every stop and ask rule in /dev.

---

## Context

**Your problem.**
- /dev goal-driven sessions keep moving on frontier leads.
- On MiniMax M3 or Kimi K3 the lead keeps stopping to ask for confirmation, even when told to be goal-oriented and to stop only in emergencies.
- You asked whether Respan's new Span-01, a workflow-monitoring classifier, could fix that, and whether it belongs in /dev.
- 90% of the time your lead is Claude Code pointed at a MiniMax or Kimi Anthropic-compatible URL, with lanes on your ADE or Traycer. Occasionally the lead is Codex or OpenCode.

**Finding.**
- Span-01 can help, but only as an optional second-stage judge in a small stop guard. It is neither the first fix nor the main one.
- Weaker models stop mainly because /dev's own text tells them to. It has about 25 user gates, contradictory rules, no autonomy mode, and no definition of "emergency".

**Outcome of this plan:**
1. A /dev **goal mode**: a closed list of hard stops. Everything else is decided, recorded, and the session continues.
2. A machine-checkable `HARD-STOP:` line.
3. An optional **deterministic** Stop hook that pushes back any stop lacking that line. It has a dormant Span-01/Jev stage that is switched on only if measurement shows it is needed. (You chose: deterministic first.)

---

## 1. What Span-01 is

- **Kind.** A behavior classifier, not an agent or chat model.
  - Input: a span (the prior messages plus one assistant turn) and plain-language behavior definitions.
  - Output per behavior: `p_present`, `p_absent` and `p_not_observable`.
  - It generates no text and makes no choices.
- **API.**
  - OpenRouter's **alpha** Decisions API: `POST https://openrouter.ai/api/alpha/decisions`, not chat completions.
  - Per the Phaseo adapter: only `noul` (yes/no) questions, and `state` must be `{input:[messages], output: assistantMessage}`.
  - Respan's native endpoint is `POST https://api.respan.ai/api/v1/scores`.
- **Price.**
  - `respan/span-01`: $0.02 per million input tokens, output free. About $0.00004 per 2k-token stop check.
  - `respan/span-01-lite:free`: free.
- **Age and evidence.**
  - Released 2026-09-25/26.
  - The claims are vendor-only: "2x cheaper, 18% better than Jev; 700x cheaper, 4% better than GPT-6 Luna", and "#1 on Behavior Benchmark".
  - Architecture: RLAIF-trained; every behavior is scored in one pass, with no cap on the count.
- **Alternative.** TypeSafe Jev (`typesafe/jev-1.13`) uses the same Decisions API and adds `choice` and `score`. It also has an ecosystem of coding-agent stop hooks.
  - Code written to the intersection (`noul` only, `{input, output}` state) can swap between the two models through a pinned slug.
- **Limits** (OpenRouter skill, `decision-model-limits.md`):
  - It cannot pick an answer; there is no `choice`.
  - No arithmetic or counting.
  - Text in the span can argue for its own classification.

## 2. What prior builders measured

- **limpet** (MIT, © 2026 no plan inc.)
  - A Jev-judged Stop hook with plain-language rules for Claude Code and Codex.
  - Shadow mode by default; the second stop in a chain always passes.
  - **Its own calibration over 1,500 real stops scored "Don't ask 'shall I start?'…" at AUROC 0.60**: 10% of bad stops caught at a 5% false-block rate. Judging wording alone separates poorly.
- **jev-belay** (MIT, © 2026 Valentyn Kit)
  - Establishes code-side facts first, then asks the classifier. **AUROC rose from 0.777 (wording only) to 0.976.**
  - Fails open. Caps: 1 block per prompt, none within 60 s, 3 per session.
  - Sends only the task, the final message and counts.
- **hermes-agent#126036** has the same root cause as your problem: harness text ("If you are blocked… say so clearly and stop") plus a judge that treats decision points as blocked. The proposed fix is a text-level `ask | best_judgement | never_ask` policy.
- **dsh-auto-mode** lets Jev answer the agent's open questions when `choice` ≥0.6 and a safety `noul` ≥0.5. /dev doesn't need that, because every /dev question already carries a recommended answer (`phase1.md:11`).

**Lesson.** A classifier becomes useful once the harness provides facts it can check. Code decides whatever facts settle; the model judges only the rest. This follows OpenRouter's own skill: "When code-side facts settle the action… code returns that action and skips the model."

## 3. Why weaker leads stop under /dev

- **Confirmation gates on the execution path:**
  - `SKILL.md:116`: "Classify the request, explain… get confirmation"
  - `phase2.md:30`: "Confirm all decisions with the user"
  - `phase2.md:74,89`: DAG confirmation
  - `phase2.md:99,108`: Issue confirmation, even for hotfixes
  - `phase4.md:167`: "decide after user confirmation"
  - `phase4.md:47`: ask before installing a tool
  - `SKILL.md:216`: "never assume"
- **Contradictions that a literal model settles by asking:**
  - `phase2.md:19` vs `:30`
  - `reply-contract.md:32` (confirm a merge) vs `phase4.md:159-160` (merge on APPROVE)
  - `reply-contract.md:21` ("ask exactly one") vs `phase4.md:109` ("Batch ASK items")
- **Missing pieces:**
  - no autonomy mode (the `.dev.json` schema is closed, `dev_config.py:47-48`)
  - no closed list of emergencies
  - nowhere for the lead to record a decision made without you

  Workers already have the rule the lead is missing: "record assumption and continue" (`worker-new.md:53`).
- **Claude Code's native `/goal`** re-prompts through a prompt-based Stop hook, judged by the "small fast model". When `ANTHROPIC_BASE_URL` points at MiniMax or Kimi, which model and endpoint judge that hook is **undocumented**. It is plausibly the provider's own small model, so a weak lead may also have a weak judge. Its verdicts are "Not yet met / Met / Impossible", and nothing tells it what counts as a legitimate stop.

## 4. Verdict

| Question | Answer |
|---|---|
| Add Span-01 to /dev? | **Not in the payload.** Use it as a **dormant, optional stage-2 judge** in a companion stop guard (§5.3), turned on only if the pilot shows: (a) the lead stamps `HARD-STOP` on non-hard-stops, or (b) the deterministic guard wastes too many turns on genuine hard stops that lack the tag. |
| Span-01 or Jev | Decide with a probe on your own stop fixtures (the OpenRouter skill's step 8, `decide.ts --compare`) across `respan/span-01`, `respan/span-01-lite:free` and `typesafe/jev-1.13`. Pin `canonical_slug`. |
| Let the classifier answer for the agent? | No. The answer is the agent's own recommended answer. The guard judges only whether a human is needed. |
| Biggest lever | **Goal-mode text (WP-G1).** Zero dependencies, portable to every harness and model, and it removes the instructions that cause the stops. |

---

## 5. Design

### 5.1 Goal mode (payload; text only)

**New file:** `skills/dev/phases/goal-mode.md`. SKILL.md links it from Invocation and Phase 0, and adds `goal` to `argument-hint`.

- **Entry.**
  - `/dev goal <approved plan path | frozen PRD | Issue list>`, or a ledger that already has `autonomy: goal`.
  - An approved plan is one /dev promoted after its own Phase 1.5 approval gate (it carries the `plan-progress` header /dev writes at promotion), the same rule as the Phase 2 shortcut in the Technical Planning plan. Every other plan, including an externally authored plan marked APPROVED, goes through Phase 1.5 ingest first; goal mode starts only after that approval.
  - Phases 1 and 1.5 stay interactive. *Planning is where you are asked; execution is where you are not.*
  - Without an approved source, goal mode refuses and routes to planning.
- **Ledger fields** (`templates/DEV_STATE_TEMPLATE.md`; not `.dev.json`, whose schema is closed and records repo identity):
  - `autonomy: interactive | goal`
  - `goal_source: <path>`
  - `assumed_decisions[]`, each with `{what, why, reversible_how, phase}`
  - `hard_stops[]`
  - `next_wake_at: <ISO-8601 UTC> | none`, written whenever a turn ends with `WAKE:`; paired with the existing `next_action`
  - `goal_issues[]`: each entry `{repository: OWNER/REPO, number}`, recorded when goal mode starts (from the approved plan's Phase 2 breakdown, or the supplied Issue list). The repository is the confirmed Issue repository from repository context, never inferred from the number; a bare number is invalid
- **Closed hard-stop list.** These are the only reasons to end a turn waiting for you:
  - **H1 Irreversible or outward-facing** actions the plan did not authorize: force-push, deleting a branch or data, a review-gate bypass, a release or publish, repo settings.
  - **H2 Credentials, identity, money:** pre-write verification not `ready`, a paid service, installing a tool.
  - **H3 Security or data-loss finding** (`reply-contract.md:33`).
  - **H4 Scope conflict:** the work contradicts the plan's Out of scope or Decisions, or would change an acceptance criterion.
  - **H5 Unrecoverable failure:** a gate still failing after the retry budget, with no autonomous path.
  - **H6 Goal complete** (the final report). The lead emits it only after checking every `goal_issues[]` entry is closed by a merged PR; the stop guard verifies it independently (§5.2).
  - **Merges are not a hard stop** (your answer): merge on APPROVE with green CI; post-merge verification still runs, and each merge is listed in the digest.
- **Everything else is decided, recorded, and the session continues:**
  - route classification
  - DAG or order confirmation
  - Issue confirmation
  - architecture items the plan did not lock
  - COMMENT ratings
  - ASK findings answerable from the plan or code

  For each: adopt the recommended answer, append to `assumed_decisions`, keep going.
- **Turn-end rule.** In goal mode a turn ends only in one of three ways, each marked by the message's last non-empty line (grammar and precedence in §5.2):
  - (a) a hard stop: `HARD-STOP: H<1-5> — <one line>`;
  - (b) a scheduled wake or yield (`external-review.md:92-98`): `WAKE: <ISO-8601 UTC time> — <next action>`, with the same time and action written first to the ledger's `next_wake_at` and `next_action`;
  - (c) H6, goal complete: the final report, ending with `GOAL-COMPLETE: <goal_source>`.
- **Assumption digest.** Every hard stop and the final report list "Decisions made without you", each with how to reverse it. This needs a reply-contract §4 carve-out.
- **Contradiction fixes, both modes:**
  - `phase2.md:19` vs `:30`
  - `reply-contract.md:21` vs `phase4.md:109`
  - Reword `reply-contract.md:32` to cover irreversible actions *the workflow has not already authorized* (e.g. a merge without an APPROVE verdict). Check the pinned tokens at `validate_skill.py:617-625` and `tests/test_backend_contract.py:1510-1560` before editing.
- **Lanes.** Unchanged. Lanes never address you (`worker-new.md:22,53`). In goal mode the lead handles their questions without asking.
- **Portability.** No Claude tool names (ADR-012). The same text reaches Codex and OpenCode leads and Traycer lanes.

### 5.2 Stop-guard contract: `docs/stop-guard-contract.md` (tracked doc, not payload)

- **What a guard may read:**
  - ledger `autonomy`, `goal_source`, `goal_issues[]`, `next_wake_at` and `next_action`
  - `assumed_decisions`
  - the last assistant message (Claude Code: the Stop payload's `last_assistant_message`)
- **Turn-end markers**, the only machine-readable signals of a legitimate stop:
  - `HARD-STOP: H<1-5> — <text>` (H1–H5)
  - `WAKE: <ISO-8601 UTC timestamp> — <next action>` (scheduled wake or yield)
  - `GOAL-COMPLETE: <goal_source>` (H6; the value must equal the ledger's `goal_source`)
- **Precedence:** only the message's last non-empty line is inspected, and it must match exactly one marker. A marker anywhere else in the message does not count. A malformed marker, or a `GOAL-COMPLETE:` naming a different source, counts as no marker. A `WAKE:` marker is valid only when its time equals the ledger's `next_wake_at` and its action equals `next_action` (whitespace trimmed). A `GOAL-COMPLETE:` marker is valid only when the completion verifier passes.
- **Completion verifier** (one implementation, shared by every runner's hook, Claude Code and Codex alike): before accepting `GOAL-COMPLETE:`, read `goal_issues[]` and query GitHub read-only for each Issue by its recorded `repository` and `number` (`--repo OWNER/REPO`). Pass only when every Issue is closed by a merged PR. Fail when `goal_issues[]` is empty, any entry lacks a repository, any Issue is open or closed without a merged PR, or any query errors or is rate limited; failed and inconclusive both **block** with the unverified `OWNER/REPO#N` identities in the reason. This is the one exception to Stage 0's fail-open, and it stays bounded by the block caps.
- **Cap exhaustion is incomplete, never complete.** When a cap stops the hook from blocking an unverified `GOAL-COMPLETE:`, the hook still lets the turn end, but reports the outcome as `goal_incomplete: verification_failed` (a warning to you where the harness supports one, and a line in the guard's own log; the guard still never writes the ledger).
- **`GOAL-COMPLETE:` is a claim, not proof.** No consumer treats it as verified on its own: the `/goal` judge (text only, not the authority), the pilot metrics, and a lead resuming the run all count the goal complete only when the completion verifier passes. A resuming lead re-runs the verifier before reporting the goal done.
- **What a guard must never do:**
  - write the ledger
  - answer for you
  - push past H1–H4
- **Recommended Claude Code `/goal` condition** (zero build): *"Complete `<goal_source>` under /dev goal mode. Met: the last message ends with `GOAL-COMPLETE: <goal_source>` and its report shows every planned Issue merged. Impossible: only if the last message ends with a `HARD-STOP:` line."* The `/goal` judge's job then shrinks to checking whether a literal line is present.
- **Pairing:** Claude Code auto mode removes per-tool prompts; goal mode plus a guard removes per-turn stops.
- **Vendor names** stay out of the payload, keeping `tests/test_backend_contract.py:866-871` clean.

### 5.3 `dev-stopguard` companion (separate repo; optional; you install it)

**Why a separate repo:**
- The /dev plugin root may not ship `hooks/` (ADR-002; `scripts/check_plugin_root.sh:21-23`).
- The core takes no dependencies (ADR-005).
- Hooks are harness-specific (ADR-012).

It ships as its own Claude Code plugin with `hooks/hooks.json`. It may optionally get a marketplace entry pinned to a tag (ADR-003). /dev never installs it; the README advises.

- **Stage 0: exit, allowing the stop, on any of these:**
  - `stop_hook_active`
  - a cap is reached (1 block per prompt, none within 60 s, 3 per session; the host also caps at 8 consecutive, `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`)
  - any error (fail-open), except a completion-verifier failure, which blocks `GOAL-COMPLETE:` (§5.2)
  - **the `.agent/dev-state.md` found under the hook's `cwd` is not `autonomy: goal`**, so interactive phases are never touched
- **Stage 1: deterministic, no model calls, the default.** Its only network use is the completion verifier's read-only GitHub query, made only for a `GOAL-COMPLETE:` line.
  - Read `last_assistant_message` from the Stop payload.
  - If its last non-empty line is not a valid turn-end marker (`HARD-STOP:`, `WAKE:` matching the ledger, or `GOAL-COMPLETE:` passing the completion verifier, per §5.2), **block** with exit 2 and a one-line reason on stderr: *"/dev goal mode: this is not a hard stop (H1–H6). Adopt your recommended answer, record it in `assumed_decisions`, continue. If it is a hard stop, restate it with a `HARD-STOP:` line and stop."*
  - A genuine hard stop that lacks the tag costs one extra turn.
- **Stage 2: the classifier. Built but off by default; runs in shadow or log mode until the pilot says otherwise.**
  - One Decisions call, pinned model, `noul` only.
  - State: `{input: goal + H-list + the last 3 messages, output: final message}`, redacted as below. No diffs, files or paths.
  - **Redaction boundary** (applies in shadow and log mode too):
    - Allowed fields only: the plan's one-line Destination (not the plan body), the fixed H1–H6 text, and the last 3 messages' prose.
    - Removed before sending: fenced and inline code, file paths, URLs, email addresses, IP addresses, and tool-call or tool-result content.
    - Masked as `[SECRET]`: known credential formats (e.g. `ghp_`, `github_pat_`, `sk-`, `AKIA`, JWTs, `-----BEGIN … KEY-----`), `KEY=value` assignments, and high-entropy strings of 24+ characters.
    - Each message capped at 2,000 characters after redaction.
    - Fail closed: if redaction errors, nothing is sent and Stage 1's result stands.
  - **Gate:** Stage 2 does not run in any mode until payload tests pass with representative secrets and personal data (each credential format, an email, a home path, a `.env` excerpt) and assert none reaches the request body.
  - Behaviors:
    - `asks_confirmation`
    - `states_recommendation`
    - `irreversible_action`
    - `credentials_or_money`
    - `security_or_data_loss`
    - `scope_conflict`
    - `claims_goal_complete`
    - `unrecoverable_failure`
    - Logged-only drift behaviors: `lead_writes_code`, `off_plan_work`, `repeating_failure`.
  - Uses:
    - (a) verify that a claimed H-class is supported, blocking tag abuse;
    - (b) let an untagged genuine hard stop through without spending a turn;
    - (c) log drift.
  - Thresholds are named constants set from the probe, never defaults.
  - Every decision is logged with the response's `model` string.
- **Harness coverage:**
  - **Claude Code**, your 90% case: the Stop payload carries `last_assistant_message`, `stop_hook_active`, `cwd` and `transcript_path`. Exit 2 with stderr blocks (the limpet and jev-belay pattern).
  - **Codex:** a Stop hook with a block decision injects the reason as the continuation prompt, and the hook must be trusted through `/hooks`.
  - **OpenCode:** `session.idle` fires only after the loop has ended, and a re-prompt appears as a user message (anomalyco/opencode#16626). Deferred.
  - **Traycer lanes:** out of scope. Lanes report to the lead.
- **Credits** in the companion README: limpet and jev-belay concepts (caps, shadow mode, fail-open, evidence-first). OpenRouter's Decisions skill for API shapes. No code is copied; the OpenRouter skills repo has no LICENSE file.

---

## 6. Conflict register

| # | Conflict | Sev. | Remediation |
|---|---|---|---|
| G-C1 | The guard pushes past a genuine hard stop | High | Stage 1 costs one turn at most, then the tagged restatement passes. Stage 2 never blocks when an H1–H4 behavior score is high. **Pilot bar: zero wrong continues past H1–H4.** |
| G-C2 | Transcript text is sent to OpenRouter or Respan (stage 2 only) | Med | Opt-in. Minimal redacted state (redaction boundary and test gate in §5.3). Respan's retention policy is unverified (its site is blocked here), so check it before enabling. Stage 1 sends no transcript text; its only network call is the completion verifier's read-only GitHub query. |
| G-C3 | Vendor newness; alpha API | Med | Pin `canonical_slug`, fail-open, swap by config, re-probe on every model change. |
| G-C4 | Text in the span argues for continuing | Med | The deterministic line check plus ledger facts veto first. Adversarial fixtures go in the probe. |
| G-C5 | ADR-002, ADR-005 and ADR-012, plus the vendor-name tests | High if placed inside /dev | The companion lives outside the payload. /dev ships only text and a contract doc. |
| G-C6 | Goal mode hides real ambiguity | Med | Goal mode requires a /dev-promoted plan, so every plan has passed the Phase 1.5 gap pass and approval gate; externally authored plans go through ingest first. The assumption digest includes reversal notes. H4 covers scope. |
| G-C7 | A weak lead ignores goal-mode text | Med | That is the guard's job: defense in depth. |
| G-C8 | Wording-only judgments separate poorly (limpet AUROC 0.60) | Med | Facts first (stage 1). Stage 2 is enabled only if it measures well on your stops. |
| G-C9 | `/goal`'s judge model on a compat URL is undocumented | Low-Med | The HARD-STOP condition reduces the judge's job to a literal check. The stage 1 hook doesn't depend on it at all. |

**Licensing.**
- Span-01 and Jev are hosted APIs under terms of service; no code is reused from either.
- limpet and jev-belay are MIT; only concepts are borrowed, with credit.
- **No license blocks any path.**

---

## 7. Work packages

| WP | Scope | Key files | Depends on |
|---|---|---|---|
| **WP-G1** Goal mode (payload) | §5.1 | new `skills/dev/phases/goal-mode.md`; `SKILL.md` (Invocation, Phase 0, argument-hint); `reply-contract.md`; `templates/DEV_STATE_TEMPLATE.md`; `phases/phase2.md`; `phases/phase4.md`; `scripts/validate_skill.py` (`REQUIRED` +1; per-file tokens "decide, record, continue", `HARD-STOP:`, H1–H6 headers); tests (goal-mode section exists; Phase 1 gates unchanged; carve-out test extended; frontmatter suite green) | v2.1.2. Earlier WP-A2 for `/dev goal <approved plan>`; frozen-PRD and Issue-list entry can land first |
| **WP-G2** Contract doc and README "Companions" | §5.2, including the recommended `/goal` condition | new `docs/stop-guard-contract.md`, `README.md` | G1 |
| **WP-G3** Pilot, no build | Claude Code with MiniMax M3 and Kimi K3 on one approved plan, three arms: (1) no goal mode; (2) G1; (3) G1 plus the `/goal` HARD-STOP condition. Log every stop by class | `docs/dogfooding.md` | G1, G2 |
| **WP-G4** `dev-stopguard` stage 0+1 | §5.3 stages 0 and 1; the shared completion verifier (§5.2) called by both hooks; stdlib Python; Claude Code and Codex hook configs; offline tests | separate repo | G3 shows leftover untagged stops |
| **WP-G4b** Stage 2, dormant | Decisions client, redaction module and its payload tests (§5.3 gate), probe fixtures, `compare` across span-01, span-01-lite and jev; logging only | separate repo | G4 |
| **WP-G5** Enable stage 2, or not | Turn stage 2 on only if G4's logs show tag abuse, or more than 1 in 5 stage-1 blocks landing on genuine hard stops | README, `docs/dogfooding.md` | G4b plus 1 week of logs |
| *Deferred* | OpenCode adapter; deterministic PreToolUse Iron-Rule-1 guard (lead edits non-doc files; no model needed); drift enforcement | — | measured need |

**Pilot metrics:**
- human interventions per Issue
- stops by class
- wrong continues past H1–H4, which must be **0**
- unverified completions (`GOAL-COMPLETE:` without a passing verifier, including cap exhaustion), counted as incomplete, never complete
- wrong blocks
- turns spent
- cost and latency (stage 2)

**README promotion bar:** interventions per Issue drop by ≥50% relative to arm 1, with zero wrong continues.

## 8. Verification

- **WP-G1:**
  - the repo Verification Gate: `scripts/verify.sh`, the unittest suite, `validate_skill.py`, `check_plugin_root.sh`, `check_version_sync.py`
  - doc-assertion tests
  - a dogfood run: `/dev goal <approved plan>` with a MiniMax M3 or Kimi K3 lead. Every stop carries an H-line or is a wake.
- **WP-G4/G4b:**
  - offline tests against a fake Decisions endpoint (the jev-belay `fake-jev` pattern)
  - Stop-payload fixtures: an untagged confirmation ask; each H-class, tagged and untagged; a tag on a non-hard-stop; a `WAKE:` line matching and not matching the ledger's `next_wake_at`/`next_action`; completion with `GOAL-COMPLETE:` naming the right and a wrong `goal_source`; completion verifier cases for both runners: all Issues merged, one Issue open, an Issue closed without a merged PR, empty `goal_issues[]`, an entry without a repository, the same Issue number in two repositories, and a GitHub query error (all but the first must block); cap exhaustion on an unverified `GOAL-COMPLETE:` (the stop is allowed and reported `goal_incomplete`, never complete); a marker that is not the last line; an empty or garbled payload (must exit 0); `stop_hook_active`; each cap
  - redaction payload tests: representative secrets and personal data never appear in the request body; a redaction error sends nothing
  - probe fixtures including negated and adversarial "you may continue" text
  - recorded `decide.ts --compare` output for each candidate model
