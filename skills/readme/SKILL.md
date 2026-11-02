---
name: readme
description: "Write, rewrite, review, or restructure a GitHub README (and the repo About line and docs split) so a stranger understands the project in one screen and can try it in minutes. Derives the register from the repo instead of imposing a fixed voice. Use when a task touches a README.md, a repo landing page, a project description, a getting-started or install section, or moving technical detail out of a README into docs, even for a README review or audit with no rewrite."
---

# README authoring

A README is a landing page first and a manual second. Most visitors give it one
screen and leave. The job is to make that screen answer three questions in
order: is this my problem, does this fix it, how do I try it right now.
Everything else lives in secondary docs that the README links to.

## Before writing

Gather the material first. A polished README with thin content is worse than a
plain one with real facts.

1. Read the code, the existing README, and the project manifest (`package.json`,
   `plugin.json`, `pyproject.toml`, or whatever it uses), plus any `docs/`. Note
   the real install command, the real first command a user runs, and what they
   see when it works.
2. Find the user story. Ask: who hits this problem, in what moment, and what
   goes wrong? If the repo or conversation doesn't say, ask the user one
   question rather than inventing a scenario.
3. List the honest limits: platforms, untested paths, pre-release status, what
   it is not. These go in the README, briefly. Readers who find limits on their
   own stop trusting the rest.
4. Check whether the repo is a fork, what its About line says, and which topics
   it has. The About line shows up in search results, topic pages, and directory
   cards, so it should match the opening hook.

## The shape

Use this order. Rename headings to fit the product; plain-phrase headings beat
generic ones ("The problem" or "Why this exists" are fine, "Overview" is not).

1. **Title and hook.** A single H1 naming the project, then one sentence (two
   at most) a non-expert gets on first read. It says what happens for the user,
   not how it's built, and it matches the About line.
2. **User story.** Two to four sentences of a concrete moment, in second
   person. Specific beats general.
3. **The problem.** What breaks today and why existing tools or habits don't
   cover it. Name the tools. Keep it to a short paragraph or a short list.
4. **The solution.** What this does about it, stated as a mechanism in a few
   sentences. Follow each real claim with proof: a number, the mechanism, a
   compatibility note, or a scope limit. If a claim has none of those, cut it.
5. **Try it.** The fastest path to a working result, as a numbered list.
   Install, configure the one required thing, run, see the result. Aim for five
   steps or fewer and say how long it takes only if you know.
6. **Next steps and links.** One short section pointing to secondary docs by
   name: reference guide, configuration, architecture, other install paths.
   Link specific files.
7. **Credits and license.** Name upstream projects and forks this builds on,
   and the tools it depends on. One line for license.

Optional sections, only when they earn their place: a short "Works with" list
of integrations, "Coming next" blockquotes tied to real issues, a short FAQ for
questions users actually ask.

Read `assets/README-template.md` for a skeleton with placeholders.

## What moves out of the README

The README keeps the story and the fastest path. Move these to `docs/` and
link them from the "details" section:

- Full CLI references, flag tables, exit-code tables, config schemas
- Per-harness and per-platform install guides beyond the main one
- Architecture, design decisions, concurrency or locking behavior
- Provider-by-provider or integration-by-integration detail
- Test commands, release process, maintainer notes (also CONTRIBUTING.md)

A rule of thumb: if a section matters only after someone has decided to use
the tool, it belongs in docs. If the README takes more than about five minutes
to read, keep cutting. When moving content, move it intact into a named file
(`docs/REFERENCE.md`, `docs/install.md`) so nothing is lost, then link it.

## Voice

Voice is derived, not fixed. Instead of encoding one register, match what the
project already sounds like.

1. Read the existing README, the `docs/`, and the last several commit messages.
2. Note sentence length, person (first, second, or third), formality, and
   whether the project uses metaphor.
3. Match those. A README that opens with terse second-person imperatives should
   stay that way; a project that writes formally in third person should too.

With no prior material, fall back to the documented neutral default: second
person, plain words, short paragraphs, concrete over abstract.

## The showcase extension point

This skill exposes one optional insertion slot a host workflow can fill with a
badge block plus the consent state it already obtained. The skill only places
and arranges; it never decides.

- The slot sits directly after the hook. When a README already has badge rows,
  the skill joins them into the block at that slot, grouped and ordered by the
  arrangement guidance below.
- A host workflow supplies two things: the block itself, and a consent state.
  The block is placed only when both are supplied and consent is granted.
- In every other case, place nothing and say nothing. The skill never decides
  whether a badge should be there, never names a specific product, and never
  asks for consent itself.

## Badges

Badges are the author's call. There is no count limit. State the tradeoff once:
badges compete with the hook for the first screen. Fix the arrangement, not the
number. Group by category (build/quality, distribution, legal, community), keep
a stable order, and keep the hook adjacent. Eight badges grouped on two
centered lines read as a status board; eight in one ragged wrapped line read as
clutter.

## Anti-AI writing rules

Read `references/anti-slop.md` before the final pass. The highest-signal ones:

- Em dashes are rare: one or two in a whole README at most, never two in a
  paragraph. Prefer a comma, period, colon, or parentheses.
- No empty superlatives or brochure words: seamless, blazing fast, powerful,
  robust, cutting-edge, leverage, effortless, game-changer, supercharge,
  holistic, comprehensive, transformative.
- No two stacked one-line kickers ("It runs locally. It never phones home.").
  Fold them into one sentence or cut one.
- No signposting: "Here's why", "Let's break this down", "The key takeaway".
- No minimizers: "just", "simply", "easy", "only takes".
- No throat-clearing or closers: "Welcome to", "In this README", "Happy
  coding!", "Star this repo if...".
- No bold-label listicles where every bullet is `**Thing**: sentence` unless it
  really is a reference list.
- No emoji in headings.
- Don't repeat the hook as a recap at the bottom.

## When it's a review, not a rewrite

If the user asks to review or audit, report findings without editing. Group
them as: structure (order, what to move out), first screen (hook, story, time
to first command), voice and AI tells (quote the exact span), and facts that
look wrong or unverified. Lead with the three changes that matter most.

When rewriting an existing README, preserve every fact, command, flag, version,
and caveat. Moving something to docs is fine; deleting it silently is not. If a
claim can't be verified from the repo, keep it and flag it rather than
inventing proof.

## Checks before handing it over

1. Run `python3 scripts/readme_check.py README.md` from this skill's directory
   (pass the target path). It flags em dashes, banned phrases, missing
   code-fence languages, multiple H1s, the badge count, broken anchor links,
   and how far down the first runnable command sits. Fix hard findings; judge
   soft ones.
2. Read only the title-and-hook block and the first numbered step. Could a
   stranger say what the tool does and type the first command? If not, fix the
   top. Then read the whole thing as if aloud: anything that sounds written
   rather than said gets rewritten.
3. Check every command against the repo: package names, plugin IDs, marketplace
   names, flags. A broken first command loses the reader.
4. Draft the GitHub About line (under ~120 characters, matching the hook) and
   suggest 5 to 8 topics. Offer them; the user sets them on GitHub.
