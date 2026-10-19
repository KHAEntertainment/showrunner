# Phase 1 — Product Alignment

Module-progressive alignment + word-precision capture + prototype-driven when needed.
**Do not enter Phase 2 until all ambiguity is eliminated.**

---

## Top-level Anchoring Principles (apply throughout Phase 1)

1. **Ask one question at a time**, wait for the user's answer; never batch questions
2. **Every question comes with an AI recommended answer + a one-line rationale**, so the user can yes / no / tweak instead of thinking from scratch
3. **No cap on the number of questions** — only advance when the user actively presses the module-switch gate by saying "satisfied"
4. **Show a progress breadcrumb every turn** (format below), so the user doesn't have to remember "where are we"
5. **Do not assume; do not rewrite the user's existing documents** (unless explicitly requested)
6. **Check the codebase before asking** — in existing projects, call graphs, current conventions, and model structures should be read from code rather than asked

**Progress breadcrumb format** (every response starts with this):
```
[Module N/M: <module name>] · Current layer: <Big Picture | Behavior | Detail> · Locked: K · Pending: J
```

- `K` and `J` are **non-negative integers** (decision counts). Think of "Pending" as "the number of concrete questions in the current layer that haven't been locked yet."
- **The breadcrumb ends immediately after `J`**. Do not append descriptive fields like `Pending: B.3 stress-testing` or `Status: gate` to the tail — status information goes in the body below the breadcrumb.
- **Pre-lock stage** (Step A in progress, module list not yet locked) breadcrumb form: `[Module split in progress] · Current layer: Big Picture · Locked: 0 · Pending: N` (N is the number of top-level questions still left in Step A). Do not use the `Module -/-` form.
- **Splitting principle for multi-part recommended answers**: if a single Q's recommended answer would lock ≥3 **mutually independent** decisions at once, it should be split into multiple Qs (the "one at a time" rule targets decision granularity, not question count). If the multiple parts of a recommended answer are **mutually coupled** (e.g. CLI command name + default behavior + output format all belong to one UX decision bundle), they can be packaged into one Q, but the recommended answer must clearly note that it locks N sub-decisions together.

---

## Entry Routing

- **Situation A — User provided a requirements document** (all three must be satisfied):
  - Has a core feature description (more than a one-line product direction)
  - Has target users or usage scenarios
  - Has technical constraints or explicit non-functional requirements

  → Use the user's document as the PRD basis; **do not rewrite**. Go directly to Step A for module split; later Step B still drives module-progressive questioning to nail down everything the document didn't make clear. When Situation A holds, Step B reads the document first (B.0) and asks only what the document did not settle.

- **Situation B — User did not provide a requirements document**:
  → Run the full Step A → B → C → D, ultimately producing the PRD.

---

## Step A — Product overview + module split

### A.1 Top-level questions (one at a time)

Ask the following in order, each with an AI recommended answer:
1. What is this product? What does it do? (one-line positioning)
2. Who uses it? What is the typical scenario?
3. What is the deployment form? (Web / desktop / API / CLI / local script)
4. Where is the v1 (MVP) boundary? What explicitly **will not** be built?

In Situation A, if the document already covers an item, skip it and only follow up on ambiguities.

### A.2 Module split draft

Based on the information above, **judge on the spot** how this product should be split into modules. **Do not pre-set a template**:
- Non-AI ordinary project: might be `frontend / backend / DB / deployment` style
- AI Agent project: might be `frontend / Agent core / toolset / retrieval-memory / model layer / deployment` style
- Single-machine script: might be a simple `input handling / core logic / output` split

Output format:
```
Based on the above understanding, I suggest splitting this product into the following N modules to align on one by one:
1. <module name> — <one-line responsibility>
2. <module name> — <one-line responsibility>
...
Module dependencies: <brief description>
```

### A.3 Lock the module list (mandatory handshake)

Explicitly ask the user:
```
Is the module split above accurate? We'll align module by module in the order 1 → 2 → 3 → ...
If it needs adjustment, tell me; if it's OK, reply "lock".
```

**Do not enter Step B until the user replies "lock" or an equivalent confirmation.** This step looks tedious, but the module list later carries the anchoring duties for the progress breadcrumb, term ownership, and prototype slug naming — it cannot drift.

---

## Step B — Per-module loop

For each locked module, run B.1 → B.4 in order, looping until the user presses "satisfied" at the gate.

### B.0 Document-first mode (Situation A only)

Applies only when the Entry Routing test for Situation A held; Situation B runs B.1 unchanged. Read this before B.1, then run B.1 → B.4 as usual. The layers and the Top-level Anchoring Principles are the same loop — what changes is which items get asked.

**Extract before asking.** For each locked module, read the supplied document first and draft that module's decisions across the Big Picture, Behavior, and Detail layers as a *proposed* locked list, not as answers the user already gave. Each item cites the document section it came from:

```
Module <N> — <module name>
From the document — <N> proposed decisions:
- <decision> — source: <document heading or section>
- ...
Not settled by the document — <M> gaps:
- <the missing item, at decision granularity>
```

Present the proposed list and the gap list together, and **state both counts**. Then ask only the gaps, one question at a time, each with an AI recommended answer and a one-line rationale, per the Top-level Anchoring Principles. An item the document settles is not asked again; the user can reopen any of them at the Step C gate, where the full proposed list is shown for confirmation.

**The rest of Step B is unchanged.** The B.3 stress-test runs for every module, including one whose decisions were all extracted from the document, and the Step C gate still requires the user to press "satisfied" before the next module. A list the user never watched being built is still a list the user confirms.

**The document is never rewritten.** Principle 5 holds exactly as it does in Situation B: the extracted decisions are written into `PRD-draft.md` **with their citations**, and the user's document is left exactly as supplied. Extraction reads the document; it does not edit it.

### B.1 Three-layer progressive questioning

Go from shallow to deep in the following order; finish the current layer before drilling down:

**Big Picture layer**
- What is this module's goal? Where is its boundary?
- What are its interfaces with other modules? What goes in, what comes out?

**Behavior layer**
- What actions do users / the system take inside this module?
- What is the main data flow?
- What are the key states?

**Detail layer**
- Specific fields, UI form, tech selection
- Edge cases and exception handling

**Drill-down condition between layers**: only drill down when the user explicitly says "clear enough." Do not let the AI decide on its own to switch layers.

### B.2 Word precision inline

**Monitoring timing**: word-precision watching **starts from the very first answer to the Step A top-level questions**, not after entering Step B. If term drift is detected during Step A, **mark it first** (one line below the breadcrumb: "I noticed you just used X; flagging it for now and we'll nail it down when we reach the corresponding module"), and **defer the glossary write to Step B of the relevant module** — this way the glossary entry hangs off the correct module context.

While asking questions, monitor the user's wording continuously. Interrupt the flow immediately for term clarification when any of the following hits:
- Used a vague word ("account / customer / user / resource / task / project / message" and other easily overloaded words)
- Used multiple different words for the same concept
- Conflicts with an existing glossary definition

After clarification, **immediately write to** `docs/glossary.md` (do not batch-write at the end of the module):
```markdown
**<canonical term>**: <one-line definition>
_Avoid_: <list of replaced near-synonyms>
```

Create the file if it doesn't exist. Terms must be **used strictly in the canonical form** in the main conversation and in later Phases, including in the AI's own questions.

### B.3 Scenario stress-test (mandatory before module close-out)

Before entering the Step C gate, the AI must **construct 2-3 concrete edge scenarios** and walk the user through them:

```
Before entering the gate for Module X, I made up a few scenarios to stress-test your understanding of this module:

Scenario 1: <concrete situation, e.g. "user loses connection mid-login and then recovers">
Per the design you just described, what should happen?

Scenario 2: <concrete situation>
...
```

Pass means the user can walk through it smoothly. If they stall → go back to the corresponding B.1 layer and keep questioning.

**Handling a user-initiated opt-out**: if the user explicitly says "this module is simple, no need to stress-test / I have no doubts about this / skip it," **do not silently skip**. Handle it like this:
1. The AI restates the opt-out: "OK, you believe the design of Module X is already clear enough and doesn't need a scenario stress-test."
2. Write this opt-out as a **locked decision** in the current module's lock list (e.g. "user actively opted out of scenario stress-test — accepts the risk"), so it explicitly appears in the frozen PRD at Step D
3. Then enter the Step C gate

The AI itself never proactively suggests skipping B.3. This rule guards against "user-driven skip," not against the user's decision.

### B.4 Prototype trigger

At any point if a **low-fidelity signal** is detected, pause the current questioning and follow `${CLAUDE_SKILL_DIR}/phases/phase1-prototyping.md`.

After dispatch:
- The main conversation **stays in the same module at the same layer** waiting for the user's answer based on the prototype
- Do not jump to the next layer or next module just because a prototype was dispatched
- Once the prototype comes back, re-ask the original decision point based on the readout

---

## Step C — Module switch gate

After B.1-B.4 of the current module are done, **immediately write the locked decisions of the current module into `PRD-draft.md`** (append or update the corresponding module section), then explicitly ask the user:

```
[Module N/M: <module name>] We have currently locked the following decisions:
- <decision 1>
- <decision 2>
...

I have written these into PRD-draft.md; once all modules are done it will be frozen as PRD.md.

Any remaining ambiguity in this module? If not, I'll switch to the next module <next module name>.
(Reply "switch to next" or point out what still needs follow-up)
```

**Write rules**:
- File path: `PRD-draft.md` at the project root
- Create the file if it doesn't exist; append/update the corresponding module section if it does
- The top contains progress metadata: `<!-- phase1-progress: module N/M locked at YYYY-MM-DD HH:MM, current=<next>, layer=<layer> -->`
- The locked list matches what is shown to the user at this gate

**The user must actively press "satisfied" before advancing; the AI does not switch modules on its own**. This is where "uncapped questioning" actually lands.

When switching to the next module, update the breadcrumb's `N/M` count. **Do not advance without writing PRD-draft.md** — when a session breaks off this is the only anchor for state recovery.

---

## Step D — All modules complete → freeze the PRD

After all modules are done, output the frozen PRD.

PRD output format (human-readable, no enforced schema — Phase 2 does not consume the PRD via field mapping, it reads it as context):

```markdown
<!-- phase1-progress: ALL MODULES LOCKED at YYYY-MM-DD HH:MM -->
<!-- modules: 1.<name> 2.<name> 3.<name> ... -->

# <Product Name> — PRD

## One-line positioning

## Target users and scenarios

## Deployment form

## Module list and dependencies
(matches the module list locked in Step A)

## Per-module alignment results
### Module 1: <name>
**Goal and boundary**:
**Key behaviors**:
**Key decisions**:
- <decision 1>
- <decision 2>
**Known open items** (do not block Phase 2, but Phase 2 task split should be aware):
**Linked prototypes** (if any): prototypes/...

### Module 2: <name>
...

## MVP scope
## V2 candidates (explicitly deferred)
## Explicitly will not build

## Technical constraints

## Success criteria
```

After output, explicitly ask the user:
```
That's the frozen PRD. Phase 2 will split tasks based on it.
Please confirm (reply "freeze" or point out what needs adjusting).
```

**Enter Phase 2 only after the user confirms "freeze"**.

---

## State Recovery Protocol (cross-session)

If the previous session ended mid-Phase-1, when entering `/dev` again this time:

1. Read the progress metadata at the top of the PRD draft (if it exists) at the project root:
   ```
   <!-- phase1-progress: module 2/5 locked, current=3 (Agent core), layer=Behavior -->
   ```
2. Read `docs/glossary.md` to restore locked terms
3. Read the `prototypes/` directory to restore the list of generated prototypes
4. Report the recovery result to the user via a progress breadcrumb:
   ```
   Restored Phase 1 context: currently in Module 3/5 (Agent core), Behavior layer.
   Locked decisions: X, generated prototypes: Y.
   Continue from here, or go back and revisit a prior module?
   ```

File naming: before Step D, use `PRD-draft.md` at the project root; after Step D freeze, rename to `PRD.md`. See the Step C section for draft update timing and write conventions.

---

## Term Re-review Rule

A discussion in Module N may uncover an issue with a term that was locked in Module M. In that case:

- **Explicitly surface it**: say in the main conversation, "Earlier in Module M we defined X as Y, but in Module N's scenario that definition conflicts; I suggest changing it to Z"
- **Modify the glossary after the user confirms**, and go back to Module M to check whether its locked decisions need adjustment
- **Do not silently change**: term drift pollutes later Phases — it must be explicit

If the re-review forces a major change in Module M, go back to Module M and re-run the relevant Step B sub-loops. **Do not advance carrying the conflict.**

---

## Phase 2 Loopback Handling

If something like an architecture-level change routes the flow back to Phase 1:

- **Do not re-run the full flow**
- Read the frozen PRD, identify the affected modules
- Re-run Step B only for the affected modules (including B.2/B.3/B.4 if necessary); other modules remain unchanged
- After completion, update the corresponding module section in the PRD with the change time and reason
- Step D no longer produces a brand-new PRD, only updates the version number (add `<!-- phase1-progress: REVISED at YYYY-MM-DD ... -->` at the top)

---

## Prohibited Behaviors

- Do not enter Phase 2 before the user confirms "freeze" in Step D
- Do not enter Step B before the user confirms "lock" in Step A.3
- Do not batch questions (one at a time)
- Do not omit the AI recommended answer for any question
- Do not assume requirements the user did not explicitly state
- Do not rewrite the user's existing document (unless explicitly requested)
- Do not, in Situation A, ask a module-level question the supplied document already settles (B.0 extracts it and cites the section; the user reopens it at the gate instead)
- Do not skip the scenario stress-test (B.3) in pursuit of "finishing quickly"
- Do not let a prototype agent lock decisions on behalf of the main conversation (prototype agents only produce artifacts + readouts)
- Do not silently modify locked terms or decisions (re-reviews must be surfaced)
