# Gate inventory disposal (v2.2, AC-04)

These are audit disposals of SDP l.191–208 at pin 7177580c, not new delegations.

The machine-readable source is `GATE_INVENTORY` in `skills/dev/scripts/goal_authority.py`. `tests/test_goal_authority.py` checks that this table and the module agree row for row, that all 12 historical groups are present, and that every Dev 2.1.4 reference names a file and heading that exist under `skills/dev/`.

## Dispositions

| Disposition | Meaning | Delegable |
| --- | --- | --- |
| `preserved_lead_owned` | Tier A. Existing lead-owned behavior stays as it is; fail-closed detection and verification are not weakened. | no |
| `delegated_d7_2` | Settled under D7.2. The lead decides within the stated condition and records gate, decision, reasoning, evidence pointer and reversal path. "Proceed unless stopped" applies only here. | yes |
| `superseded_interactive` | Not an autonomous delegation in v2.2. Phase 1 stays interactive. | no |
| `protected` | Tier C, or a user-owned decision. Explicit authority or fail-closed handling; autonomous mode is not authorization. | no |

A gate tied to an unresolved decision is refused with `unresolved_decision` and never delegated. Currently unresolved: `express-issue-confirmation` (D7.2 item 2 names only lightweight Issues; the inventory row also names express-mode confirmation).

## Groups

| Group | Tier | SDP line | Historical group |
| --- | --- | --- | --- |
| 1 | A | 197 | backend detection/adapter load; serial/parallel topology; worktree preparation and destination verification |
| 2 | A | 198 | worker/QA/reviewer dispatch and worker-plan approval; tier-based QA floors (v2.1.3); prototype dispatch |
| 3 | A | 199 | external-review observation/inspection/triage; static analysis, scope-drift checks, two-pass review, coverage audit, adversarial second opinion; final review rating |
| 4 | A | 200 | post-merge coordination/verification/Issue reopening; retro, debt sweep, cleanup Issues, agent shutdown |
| 5 | B | 201 | Phase 0 classification and verified setup proposal |
| 6 | B | 202 | module lock, per-module questions/satisfied, scenario stress-test, PRD freeze |
| 7 | B | 203 | architecture checkpoint, task list/dependency DAG, lightweight/express Issue confirmation |
| 8 | B | 204 | review ASK disposition, COMMENT decisions, external-review re-requests, mid-run backend/topology changes |
| 9 | C | 205 | tracked/invalid/conflicting .dev.json, conflicting first-time destinations, fork/upstream preset, new-repo owner/name/visibility |
| 10 | C | 206 | merges, force-push, deletions including worktrees, tag pushes, releases, marketplace/formula publication |
| 11 | C | 207 | external-review bypass, unknown trusted reviewer identities, cross-repo target overrides, nonstandard hotfix base, auth/credential anomalies |
| 12 | C | 208 | product-intent ambiguity, scope beyond the goal, scenario opt-out |

## Gates

| Gate ID | Gate | Group | Tier | Disposition | Delegable | Condition | SDP line | Dev 2.1.4 reference |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `backend_detection` | backend detection and adapter load | 1 | A | `preserved_lead_owned` | no | Preserve existing lead-owned behavior and fail-closed detection; do not weaken verification. | 197 | `SKILL.md § Execution Backend and Topology Policy`; `backends/contract.md § Common invariants` |
| `topology` | serial/parallel topology | 1 | A | `preserved_lead_owned` | no | Preserve existing lead-owned behavior and fail-closed detection; do not weaken verification. | 197 | `phases/phase3.md § Select Backend and Topology` |
| `worktree_destination` | worktree preparation and destination verification | 1 | A | `preserved_lead_owned` | no | Preserve existing lead-owned behavior and fail-closed detection; do not weaken verification. | 197 | `phases/phase3.md § Prepare Coding Worktrees`; `phases/repository-context.md § Pre-write verification (run immediately before every push and every GitHub mutation)` |
| `lane_dispatch` | worker/QA/reviewer dispatch | 2 | A | `preserved_lead_owned` | no | Preserve the existing lead role and the worker-plan gates. | 198 | `phases/phase3.md § Dispatch Prompts`; `phases/phase3.5.md § Prepare the QA Lane` |
| `worker_plan_approval` | worker-plan approval (architecture/database/auth/interface/migration/refactor) | 2 | A | `preserved_lead_owned` | no | Preserve the existing lead role and the worker-plan gates. | 198 | `phases/phase3.md § Dispatch Prompts`; `agents/worker-new.md § [Step 2: Design First]` |
| `qa_tier_floor` | tier-based QA floors (v2.1.3) | 2 | A | `preserved_lead_owned` | no | Preserve the existing lead role and the worker-plan gates. | 198 | `phases/phase3.5.md § Risk Tiers` |
| `prototype_dispatch` | prototype dispatch | 2 | A | `preserved_lead_owned` | no | Interactive planning does not itself revoke existing prototype-dispatch behavior. | 198 | `phases/phase1-prototyping.md § Step 4 — Dispatch` |
| `external_review_observation` | external-review observation | 3 | A | `preserved_lead_owned` | no | Preserve quality gates and lead accountability; reviewer lanes remain advisory. | 199 | `phases/external-review.md § Start Observation in Phase 3.5` |
| `external_review_inspection` | external-review inspection | 3 | A | `preserved_lead_owned` | no | Preserve quality gates and lead accountability; reviewer lanes remain advisory. | 199 | `phases/external-review.md § Inspect One PR` |
| `external_review_triage` | external-review triage | 3 | A | `preserved_lead_owned` | no | Preserve quality gates and lead accountability; reviewer lanes remain advisory. | 199 | `phases/external-review.md § Triage Current-Head Findings` |
| `static_analysis` | static analysis | 3 | A | `preserved_lead_owned` | no | Preserve quality gates and lead accountability; reviewer lanes remain advisory. | 199 | `phases/phase4.md § Static Analysis Gate (run before human review)` |
| `scope_drift` | scope-drift checks | 3 | A | `preserved_lead_owned` | no | Preserve quality gates and lead accountability; reviewer lanes remain advisory. | 199 | `phases/phase4.md § Step 0 — Scope-Drift Gate` |
| `two_pass_review` | two-pass review | 3 | A | `preserved_lead_owned` | no | Preserve quality gates and lead accountability; reviewer lanes remain advisory. | 199 | `phases/phase4.md § Two-Pass Review` |
| `coverage_audit` | coverage audit | 3 | A | `preserved_lead_owned` | no | Preserve quality gates and lead accountability; reviewer lanes remain advisory. | 199 | `phases/phase4.md § Coverage-Path Audit` |
| `adversarial_second_opinion` | adversarial second opinion | 3 | A | `preserved_lead_owned` | no | Preserve quality gates and lead accountability; reviewer lanes remain advisory. | 199 | `phases/phase4.md § Adversarial Second Opinion` |
| `final_review_rating` | final review rating | 3 | A | `preserved_lead_owned` | no | Preserve quality gates and lead accountability; reviewer lanes remain advisory. | 199 | `phases/phase4.md § Review Rating` |
| `post_merge_coordination` | post-merge coordination | 4 | A | `preserved_lead_owned` | no | Preserve existing responsibilities; merge authority remains separate under D2. | 200 | `phases/phase4.md § Post-Merge: Affected PR Coordination (mandatory after every merge)` |
| `post_merge_verification` | post-merge verification | 4 | A | `preserved_lead_owned` | no | Preserve existing responsibilities; merge authority remains separate under D2. | 200 | `phases/phase4.md § Post-Merge Verification (unconditional)` |
| `issue_reopening` | Issue reopening | 4 | A | `preserved_lead_owned` | no | Preserve existing responsibilities; merge authority remains separate under D2. | 200 | `phases/phase4.md § Post-Merge Verification (unconditional)` |
| `retro` | retro | 4 | A | `preserved_lead_owned` | no | Preserve existing responsibilities; merge authority remains separate under D2. | 200 | `phases/phase5.md § Step 1 — Retro` |
| `debt_sweep` | debt sweep | 4 | A | `preserved_lead_owned` | no | Preserve existing responsibilities; merge authority remains separate under D2. | 200 | `phases/phase5.md § Step 3 — Focused Debt Sweep` |
| `cleanup_issues` | cleanup Issues | 4 | A | `preserved_lead_owned` | no | Preserve existing responsibilities; merge authority remains separate under D2. | 200 | `phases/phase5.md § Deprecated implementation` |
| `agent_shutdown` | agent shutdown | 4 | A | `preserved_lead_owned` | no | Preserve existing responsibilities; merge authority remains separate under D2. | 200 | `phases/phase5.md § Step 5 — Cleanup and Standby`; `backends/traycer.md § Observation, shutdown, and recovery` |
| `phase0_classification` | Phase 0 classification | 5 | B | `delegated_d7_2` | yes | Lead proceeds when the setup is verified and has exactly one candidate; conflicting candidates and Tier C setup boundaries come to the user (D7.2.1). | 201 | `SKILL.md § Phase 0 — Entry Router` |
| `verified_setup_proposal` | verified setup proposal | 5 | B | `delegated_d7_2` | yes | Lead proceeds when the setup is verified and has exactly one candidate; conflicting candidates and Tier C setup boundaries come to the user (D7.2.1). | 201 | `SKILL.md § Repository & Account Setup (run before any GitHub mutation)`; `phases/repository-context.md § First invocation (run before any GitHub mutation, Phase 0)` |
| `module_lock` | module lock | 6 | B | `superseded_interactive` | no | Superseded as an autonomous delegation for v2.2: Phase 1 stays interactive; approved-input reuse; the user owns scenario opt-out. | 202 | `phases/phase1.md § A.3 Lock the module list (mandatory handshake)` |
| `per_module_questions` | per-module questions / satisfied | 6 | B | `superseded_interactive` | no | Superseded as an autonomous delegation for v2.2: Phase 1 stays interactive; approved-input reuse; the user owns scenario opt-out. | 202 | `phases/phase1.md § B.1 Three-layer progressive questioning`; `phases/phase1.md § Step C — Module switch gate` |
| `scenario_stress_test` | scenario stress-test | 6 | B | `superseded_interactive` | no | Superseded as an autonomous delegation for v2.2: Phase 1 stays interactive; approved-input reuse; the user owns scenario opt-out. | 202 | `phases/phase1.md § B.3 Scenario stress-test (mandatory before module close-out)` |
| `prd_freeze` | PRD freeze | 6 | B | `superseded_interactive` | no | Superseded as an autonomous delegation for v2.2: Phase 1 stays interactive; approved-input reuse; the user owns scenario opt-out. | 202 | `phases/phase1.md § Step D — All modules complete → freeze the PRD` |
| `architecture_checkpoint` | architecture checkpoint | 7 | B | `delegated_d7_2` | yes | Engineering judgment is the lead's; a conflict with the approved plan or PROJECT_CONTEXT.md stops dependent work and surfaces (D7.2.2). | 203 | `phases/phase2.md § Architecture Decision Checkpoint (run for all modes, before task decomposition)` |
| `task_dag` | task list and dependency DAG | 7 | B | `delegated_d7_2` | yes | Lead decides task order and the dependency graph; the transition to the frozen goal set records the Issues and their order (D7.2.2). | 203 | `phases/phase2.md § Execution Steps` |
| `lightweight_issue_confirmation` | lightweight Issue confirmation | 7 | B | `delegated_d7_2` | yes | Only within the approved goal; product priority, scope and acceptance stay with the user (D7.2.2). | 203 | `phases/phase2.md § Lightweight Mode (Small Change / Bug Fix)` |
| `express_issue_confirmation` | express Issue confirmation | 7 | B | `protected` | no | Not delegated: D7.2.2 names only lightweight Issues. Existing user confirmation stays until the owner settles express mode. | 203 | `phases/phase2.md § Express Mode (Emergency Hotfix)` |
| `technical_ask_disposition` | technical review ASK disposition | 8 | B | `delegated_d7_2` | yes | Lead resolves with a second opinion and a recorded disposition (D7.2.3). | 204 | `phases/phase4.md § Two-Pass Review`; `phases/phase4.md § Adversarial Second Opinion` |
| `product_ask_disposition` | product review ASK disposition | 8 | B | `protected` | no | A product question stays with the user (D7.2.3). | 204 | `phases/phase4.md § Two-Pass Review` |
| `comment_decisions` | COMMENT decisions | 8 | B | `delegated_d7_2` | yes | Technical comments: second opinion plus recorded disposition; product comments stay with the user (D7.2.3). | 204 | `phases/phase4.md § Review Rating` |
| `external_review_rerequest` | external-review re-requests | 8 | B | `delegated_d7_2` | yes | Follow the project's review policy (v2.1.3 T1: CI plus one qualified review) (D7.2.3). | 204 | `phases/external-review.md § Waiting and Explicit Decisions`; `phases/external-review.md § Rate-limited review retries` |
| `midrun_backend_change` | mid-run backend/topology change | 8 | B | `delegated_d7_2` | yes | Recorded with a change notice; a detection failure still stops execution (D7.2.3). | 204 | `SKILL.md § Execution Backend and Topology Policy` |
| `dev_json_tracked` | tracked .dev.json | 9 | C | `protected` | no | Protected setup/public-destination boundary; autonomous mode is not authorization. | 205 | `phases/repository-context.md § First invocation (run before any GitHub mutation, Phase 0)` |
| `dev_json_invalid` | invalid .dev.json | 9 | C | `protected` | no | Protected setup/public-destination boundary; autonomous mode is not authorization. | 205 | `phases/repository-context.md § First invocation (run before any GitHub mutation, Phase 0)` |
| `dev_json_conflicting` | conflicting .dev.json | 9 | C | `protected` | no | Protected setup/public-destination boundary; autonomous mode is not authorization. | 205 | `phases/repository-context.md § First invocation (run before any GitHub mutation, Phase 0)` |
| `first_time_destination_conflict` | conflicting first-time destinations | 9 | C | `protected` | no | Protected setup/public-destination boundary; autonomous mode is not authorization. | 205 | `phases/repository-context.md § First invocation (run before any GitHub mutation, Phase 0)` |
| `fork_upstream_preset` | fork/upstream preset | 9 | C | `protected` | no | Protected setup/public-destination boundary; autonomous mode is not authorization. | 205 | `phases/repository-context.md § First invocation (run before any GitHub mutation, Phase 0)` |
| `new_repo_identity` | new-repo owner/name/visibility | 9 | C | `protected` | no | Protected setup/public-destination boundary; autonomous mode is not authorization. | 205 | `phases/repository-context.md § A genuinely new project (no remote yet)` |
| `merge` | merges | 10 | C | `protected` | no | Protected; the only exception is a D2 bounded per-run grant checked by decide_merge. | 206 | `phases/phase4.md § Merge Order` |
| `force_push` | force-push | 10 | C | `protected` | no | Explicit authority boundary; D2 alone addresses the bounded merge exception. | 206 | `phases/repository-context.md § Before a force-with-lease push (rebased branch)` |
| `deletions` | deletions including worktrees | 10 | C | `protected` | no | Explicit authority boundary; D2 alone addresses the bounded merge exception. | 206 | `phases/phase5.md § Step 5 — Cleanup and Standby`; `backends/traycer.md § Observation, shutdown, and recovery` |
| `tag_push` | tag pushes | 10 | C | `protected` | no | Explicit authority boundary; D2 alone addresses the bounded merge exception. | 206 | `phases/repository-context.md § Before a release tag push` |
| `release` | releases | 10 | C | `protected` | no | Explicit authority boundary; D2 alone addresses the bounded merge exception. | 206 | `phases/repository-context.md § Before a release tag push` |
| `marketplace_publication` | marketplace/formula publication | 10 | C | `protected` | no | Explicit authority boundary; D2 alone addresses the bounded merge exception. | 206 | none (v2.2 new) |
| `external_review_bypass` | external-review bypass | 11 | C | `protected` | no | Explicit approval or fail-closed handling; no implicit bypass from goal mode. | 207 | `phases/external-review.md § Waiting and Explicit Decisions` |
| `unknown_reviewer_identity` | unknown trusted reviewer identities | 11 | C | `protected` | no | Explicit approval or fail-closed handling; no implicit bypass from goal mode. | 207 | `phases/external-review.md § Ask once about unknown review bots, record the answer` |
| `cross_repo_override` | cross-repo target overrides | 11 | C | `protected` | no | Explicit approval or fail-closed handling; no implicit bypass from goal mode. | 207 | `phases/repository-context.md § Before a PR or Issue operation` |
| `nonstandard_hotfix_base` | nonstandard hotfix base | 11 | C | `protected` | no | Explicit approval or fail-closed handling; no implicit bypass from goal mode. | 207 | `SKILL.md § Repository & Account Setup (run before any GitHub mutation)` |
| `auth_anomaly` | auth/credential anomalies | 11 | C | `protected` | no | Explicit approval or fail-closed handling; no implicit bypass from goal mode. | 207 | `phases/repository-context.md § Authentication support boundary` |
| `product_intent_ambiguity` | product-intent ambiguity | 12 | C | `protected` | no | User ownership; neither a plan nor a merge policy broadens the authorized goal. | 208 | `phases/phase1.md § A.1 Top-level questions (one at a time)` |
| `scope_beyond_goal` | scope beyond the goal | 12 | C | `protected` | no | User ownership; neither a plan nor a merge policy broadens the authorized goal. | 208 | `phases/phase4.md § Step 0 — Scope-Drift Gate` |
| `scenario_opt_out` | scenario opt-out | 12 | C | `protected` | no | User ownership; neither a plan nor a merge policy broadens the authorized goal. | 208 | `phases/phase1.md § B.3 Scenario stress-test (mandatory before module close-out)` |

The control-and-ledger paragraph (SDP l.210) is not a gate group. Its rules are carried by the D7.2 control-record functions in the same module: `validate_delegated_record`, `step_boundary`, `check_dependencies`, `next_question`, `escalate` and `proceed_unless_stopped`.
