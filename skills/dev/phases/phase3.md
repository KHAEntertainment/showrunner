# Phase 3 — Delegated Development (Execution Rules)

---

## Select Backend and Topology

Read `${CLAUDE_SKILL_DIR}/backends/contract.md`, run the backend detector, and load exactly one adapter. Record the detection result before preflight.

Choose topology independently:

- **Parallel:** 2+ independent GitHub Issues with clear, non-overlapping ownership and no unresolved dependency.
- **Serial:** one Issue, same-file edits, tightly coupled refactors, sequential migrations, hotfixes, or blocking dependencies.

Do not silently change backend or topology. Partial Traycer environment, unavailable native teaming, failed auth/capability checks, or malformed backend output becomes `incomplete` and pauses dispatch.

## Prepare Coding Worktrees

Before launching a coding worker, execute the adapter's `prepare_worktree` operation:

1. Fetch `origin`, verify the integration branch, and require a clean lead worktree.
2. Create one named branch and isolated worktree per coding Issue from the verified base. Hotfixes use `origin/main` unless the user approved another base.
3. Verify absolute source/worktree paths, assigned branch, base OID, and clean status.
4. Record the mapping and `worktree_ready` state in `.agent/dev-state.md` before launch.
5. Pass the exact mapping to the worker. It must verify it and must not create or switch branches.

Traycer creation must use the official worktree command and must never use `--carry-uncommitted`. Read-only research, QA, and review may share a verified checkout only when they make no changes.

## Resolve Routes and Launch

For every role, execute adapter `resolve_route` and validate it before `launch`.

- Parallel Claude-native maps to Agent Teams; serial maps to one native worker.
- Both Traycer topologies use distinct receive-capable Chat/GUI child agents. Topology controls scheduling and ownership, not backend selection.
- Map each agent to exactly one Issue or explicit lane. Agents never self-claim unrelated work.
- Give coding agents explicit file ownership and one pre-created, verified worktree.
- Require plan approval before edits involving architecture, databases, auth, shared interfaces, migrations, or broad refactors.
- Send the full worker prompt and provider-neutral assignment envelope. Record the agent ID, resolved route/source, and communication response ID.

## Backend-Neutral Task Board

Output after launch and whenever a PR or blocker changes state:

```markdown
## Agent Task Board

| # | Topology | Backend | Agent | Route | Branch | Issue/PR | Ownership | Status |
|---|---|---|---|---|---|---|---|---|
| 1 | parallel | traycer | agt_123 | codex/gpt-5 | feat/auth | #3 | src/auth/** | active |
| 2 | serial | claude-native | worker-fix | claude-code/lead | fix/cache | #8 / PR #12 | src/cache.ts | pr_created |
```

Use only ledger statuses: `planned`, `worktree_ready`, `active`, `blocked`, `pr_created`, `qa`, `review`, `complete`, or `stopped`.

## Dispatch Prompts

- New feature: `${CLAUDE_SKILL_DIR}/agents/worker-new.md`
- Fix/improvement: `${CLAUDE_SKILL_DIR}/agents/worker-fix.md`

Fill the Issue number and include: role, topology, backend, agent ID after launch, route/source, branch, absolute source/worktree mapping, base OID, ownership, the lead's open questions (when genuine uncertainty exists), RTK-first requirement, plan-approval requirement, reporting path, and stop condition.

On PR creation or blocker, execute adapter `observe`, update the task board and ledger, and preserve the communication evidence. Never infer completion from silence.
