---
name: technical-writing
description: Write or repair documentation that stays true to the system it describes — README, setup guide, how-to, API reference, architecture explanation, release notes, runbook — by fixing the reader and the task first, then grounding every factual claim in code you actually read. Use when documentation is being written, restructured or found to be stale, or when a reader cannot get from the docs to a working result. Not for interface strings inside a product, not for persuasive or marketing copy, and not itself proof that the documented commands work.
---

# Technical writing

Documentation drifts because it is written from what the author remembers rather than from what
the system does. The failure is not bad prose — it is a true-sounding sentence nobody checked.

Keep the verbs apart: **created** is the document written; **reviewed** is someone reading it;
**verified** is every command run and every link resolved. This skill gets you to created and
reviewed. It does not get you to verified — see `documentation-verification`.

## When this fires

Documentation is being authored, restructured, or updated after a change; a README no longer
matches the repository; a reader reports that the guide does not work. It does not fire for copy
inside the product's own interface, or for copy whose job is to persuade.

## Procedure

1. **Name the reader and the moment.** Who they are, what they already know, what they were doing
   one step before they opened this, and what state the system is in when they arrive. Write to
   that person. "Developers" is not a reader.
2. **Name the one task this document completes**, and what proves it completed — a running server,
   a passing request, a deployed change. A document with no finishable task becomes reference by
   accident and serves nobody.
3. **Choose the shape and keep it pure.** A tutorial gets a beginner to a first success; a how-to
   solves one problem for someone who already has the context; a reference is looked up, never
   read; an explanation covers why. Mixing two of these in one page is the most common structural
   defect — split instead, and link.
4. **Find the source of truth and pin the scope.** Read the code, the config, the schema, the
   route definitions, the CLI's own help output, the migrations. Record the version, platform and
   environment the document is true for. Where two sources disagree, resolve it before writing —
   an unresolved contradiction shipped as prose is a defect you authored.
5. **Draft the spine before the sentences:** prerequisites, the single main path in order, and
   what the reader should observe after each step. If a reader cannot tell whether step 4 worked,
   step 5 is where they will silently fail.
6. **Ground every factual claim in something you read.** Default flags, env var names, config
   keys, return shapes, error text, supported versions — each should be traceable to a file you
   can name. A claim you cannot trace is a hypothesis: check it, or mark it as unconfirmed. Never
   write plausible output you have not seen.
7. **Make examples literally runnable.** Copy-pasteable commands, complete code, and placeholders
   that are visibly placeholders (`<your-project-id>`), never a real-looking value a reader will
   paste. Never invent a flag, an endpoint or a sample response to make an example tidy.
8. **Document the failure the reader will actually hit** — the missing dependency, the wrong
   version, the permission error you met while checking. A troubleshooting section written from
   imagination is filler.
9. **Reconcile with what already exists.** Update the stale page rather than adding a second
   truth; fix cross-references, navigation and terminology so one name means one thing throughout.
   Delete what the code no longer supports instead of leaving it as history.
10. **Hand off honestly.** List the commands, examples and links you did not execute, and say the
    document is written but unverified. Publishing it — to a docs site, a wiki, a package
    registry, a public repository — is an outward-facing act: **stop and ask** rather than
    shipping it as part of the writing.

## Checklist

- [ ] Reader, prior knowledge and finishing condition are written down, not assumed
- [ ] One document shape, not two spliced together
- [ ] Version, platform and environment scope stated
- [ ] Every factual claim traceable to code, config or observed output
- [ ] Every command and example complete, runnable, with placeholders marked as such
- [ ] No invented flags, fields, options or sample output
- [ ] Each step tells the reader what they should now see
- [ ] Failure cases come from real ones encountered, not imagined
- [ ] Stale content updated or deleted; cross-references and terminology consistent
- [ ] Unexecuted commands, examples and links named; publication not performed unasked

## Failure handling

- **The code does not settle the question** — read the tests and the callers next. If it is still
  ambiguous, write what is true of every branch and raise the question; do not pick the version
  that reads better.
- **The existing document contradicts the implementation** — the implementation wins for what you
  describe, but say so in the report. A silent rewrite hides either a doc bug or a code bug, and
  you do not yet know which.
- **A behaviour only the maintainers know** — mark it unconfirmed and ask. An authoritative
  sentence sourced from inference is the exact failure this skill exists to prevent.
- **The feature is not built yet** — do not document it in the present tense. Documentation
  describing intent is indistinguishable from documentation describing the product.
- **A third-party library's current behaviour matters** — read its current documentation rather
  than recalling it, and cite what you read.

## Evidence to report

The reader and task the document targets; the files, commands and outputs each non-obvious claim
came from; the version and platform scope; the contradictions found between docs and code, and how
you resolved them; and the explicit list of what remains unverified. "Docs updated" with no source
named and no unverified list is not evidence — it is the claim this skill asks you to back.
