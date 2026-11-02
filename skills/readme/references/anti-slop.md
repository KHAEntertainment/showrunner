# Anti-AI writing rules for READMEs

The goal is not to sound "less like AI" by swapping words. It is to say real
things plainly. A tell is usually a sign that a sentence has nothing in it.
Delete the empty sentence rather than rewording it.

## Phrases to cut

**Brochure words.** seamless, seamlessly, powerful, robust, blazing fast,
lightning-fast, cutting-edge, state-of-the-art, world-class, best-in-class,
next-generation, revolutionary, game-changer, supercharge, effortless,
elegant, beautiful (about code), production-ready (unless defined),
enterprise-grade. Replace with the number or mechanism, or delete.

**Corporate verbs.** leverage, utilize, empower, unlock, streamline,
facilitate, harness, elevate. Use "uses", "lets you", "makes faster" with a
measure, or say what actually happens.

**AI vocabulary.** delve, tapestry, intricate, multifaceted, underscore,
paramount, pivotal, myriad, plethora, realm, landscape, ecosystem (when it
means "tools"), journey, embark, navigate (not literal), resonate.

**Minimizers.** just, simply, easy, easily, only takes, all you need is,
quick and painless. They tell the reader they're slow if it doesn't work.
"Run this command" is enough.

**Throat-clearing.** "Welcome to X!", "In this README we will", "This
project aims to", "X is a tool that", "Whether you're a beginner or an
expert", "Have you ever wondered", "Let's dive in", "Here's the thing".
Start with the hook.

**Closers.** "Happy coding!", "Enjoy!", "Hope this helps", "Feel free to
open an issue", "Contributions are welcome!" as a standalone line, "If you
like this project, give it a star". One specific line that echoes the hook is
fine; a generic sign-off is not.

**Vague authority.** "Developers love", "widely used", "industry standard",
"trusted by" without names or numbers.

## Structure tells

- **Slogan fragments and stacked kickers.** "One command. Zero config.
  Infinite possibilities." One short punchy line can be voice; two one-line
  kickers in a row is the single most AI-shaped pattern there is. Fold them
  into one sentence or cut one.
- **Manufactured triplets.** "Faster, smarter, more scalable." Use however
  many items the thought actually has.
- **Signposting.** "Here's why", "Let's break this down", "The key takeaway",
  "At its core". Say the thing.
- **Hedging carpet.** may, might, could, generally, in some cases, stacked
  across a section. State what's true plainly; keep a hedge only where the
  uncertainty is real (and then keep it exactly).
- **Abstractions acting on abstractions.** "The framework enables
  orchestration of workflows" is dead. Put a person in the sentence doing
  something.
- **"Not X. It's Y." contrasts** and colon reveals ("The result: speed.").
- **Bold-label listicles.** Every bullet shaped `**Fast**: does a thing fast.`
  Use this only for true reference lists (flags, commands). For features,
  write sentences or a short plain list.
- **Feature walls.** Twelve emoji bullets under "Features". Keep the three
  that matter on the first screen; move the rest to docs or cut.
- **Preview and recap.** An intro that lists what the README covers, or a
  closing section that repeats the hook. Neither adds anything.
- **Scaffold openers.** Paragraphs starting "Additionally", "Furthermore",
  "Moreover", "In addition", "Ultimately", "In conclusion".
- **Uniform rhythm.** Every sentence the same length, or every paragraph one
  line. Vary it.
- **Tool anthropomorphism in headings.** "The CLI decides for you", "It knows
  your workflow". Say what it actually does. A deliberate, carried-through
  metaphor that explains the mechanism is different.
- **Emoji headings** (`## ✨ Features`, `## 🚀 Quick Start`). Plain headings.

## Punctuation

- **Em dashes are rare.** One or two in a whole README at most, never two in
  a paragraph. Use a comma, period, colon, or parentheses. If a sentence seems
  to need one, it usually wants to be two sentences.
- No exclamation points in body text.
- No decorative bold mid-sentence.
- Sentence case for headings ("Try it in two minutes", not "Try It In Two
  Minutes").

## Front-load the action

- The first runnable command should be on the first or second screen.
- Multi-step setup is a numbered list, one action per step, no "and then"
  twice in one step. Fewest steps that work.
- Say what success looks like after the last step.
- Time estimates are specific or absent. "About two minutes" when true;
  never "quick".
- Keep visible lists to about five items; group or link the rest.
- Tangents (other harnesses, advanced config, edge cases) get one line and a
  link, not a paragraph.
- The first-line/last-line test: if a reader sees only the hook and the first
  step, do they know what it is and what to type?

## Proof

Every major claim gets one of: a number, the mechanism, a compatibility note,
or a scope limit. "Checks risky commands in about a third of a second" passes.
"Lightning-fast safety checks" does not. If a claim has no proof, cut it.

## Things to protect while cleaning

Don't let an anti-slop pass damage the facts:

- Keep every command, flag, package name, version, path, and number exactly.
- Keep load-bearing words in safety and security text: "never", "must",
  "does not", "only", "unless".
- Keep honest hedges ("not live-tested", "macOS only"). Deleting a real hedge
  manufactures confidence.
- Keep credit and attribution intact.
- Don't add claims, numbers, or anecdotes the source doesn't support.
