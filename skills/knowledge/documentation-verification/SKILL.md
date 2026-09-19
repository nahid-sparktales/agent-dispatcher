---
name: documentation-verification
description: Prove a document works by executing it — every command run in a clean environment, every code example executed, every link and file path resolved, every flag and env var checked against the code. Use before calling docs correct or up to date, when a README or setup guide is suspected stale, when onboarding fails at an unknown step, or when checking someone else's documentation change. Not for judging whether the writing is clear or well structured, and not a substitute for the project's own test suite.
---

# Documentation verification

Reading a document is not verification. A guide that is well written, internally consistent and
recently edited can still name a flag that was renamed, link to a page that moved, or open with a
prerequisite command that has not worked for two releases.

Keep the verbs apart: **created** is the document written; **reviewed** is someone reading it;
**executed** is a command actually run and its output actually read; **verified** is the
conclusion, and it is available only after execution.

## When this fires

Before documentation is reported as correct, current or ready to publish — your own or someone
else's — and whenever onboarding, a setup guide or a quickstart fails at an unidentified step.
It does not fire for judging clarity, structure or tone.

## Procedure

1. **Inventory what is checkable** and number it, so the report can name what was covered: every
   command, every code block, every link and anchor, every file path, every flag, env var and
   config key, every version and platform claim, every reference to a screen or control.
2. **Read each command before running any of them.** Anything that mutates shared state, spends
   money, deploys, sends mail, or touches production is an outward-facing action: **stop and ask**
   before executing it, and verify it against a disposable environment or not at all. A document
   is never authorization to run what it contains.
3. **Build the environment the document claims to need** — the stated OS, runtime version and
   prerequisites, and nothing else. Start from a clean checkout or container. Tools already
   installed in your shell are the single largest source of false passes: a guide that works only
   for someone who already has the product working is not verified.
4. **Execute the prerequisites section first, as written.** This is where most documents fail, and
   a failure here invalidates every step after it.
5. **Run every command literally and in order** — copy-pasted, not adapted. When you have to
   change a command to make it work, that change is the finding. Record the command, its exit
   status and its real output next to what the document claims the output is.
6. **Execute code examples as programs**, not by reading them. An example that does not compile,
   imports a module that no longer exists, or calls a renamed function is a defect even when the
   surrounding prose is right.
7. **Resolve every link, anchor and file path.** Internal paths must exist at that path in this
   repository; anchors must exist in the target document; external links must resolve to the page
   the text promises, not to a redirect or a moved index. Use whatever link checker the project
   already depends on; otherwise resolve them one by one.
8. **Check every named identifier against the code** — flags, subcommands, env var names, config
   keys, endpoints, function and field names, default values, supported versions. The document
   claims these exist; the code is the arbiter.
9. **Walk it as the stated reader**, with only the prior knowledge the document assumes. The first
   point where you need knowledge it never supplied is a defect, and it is invisible to anyone who
   already knows the system.
10. **Fix or report, then start again from step 3.** A fixed document is not verified by the
    reasoning that fixed it, and an edit to step 2 often breaks step 9.
11. **Report with the right verb**, naming the environment. "Verified on a clean container with
    Node 20" and "verified" are different claims; print the one you earned.

## What this refuses to conclude

- **Without executing the commands** — nothing. Reading a document against the code is a review;
  say "reviewed", not "verified".
- **From a run in your existing environment** — only that it works for someone already set up. It
  says nothing about the new reader the document is written for.
- **From resolving links alone** — that the URLs are live. Not that they point at the content the
  sentence promises.
- **From a passing project test suite** — that the code works. Tests exercise the API, not the
  prose describing it, and both drift independently.
- **From one platform** — nothing about the others the document claims to support. Name the
  platform, or check them.
- **From a partial pass** — never "the docs are correct". Only the numbered items executed, with
  the rest listed as unchecked.

## Checklist

- [ ] Every command, example, link, path and identifier inventoried and numbered
- [ ] Destructive, costly or outward-facing commands identified and asked about before running
- [ ] Clean environment built to the document's stated prerequisites
- [ ] Prerequisites section executed first, as written
- [ ] Every command run literally; real output compared with claimed output
- [ ] Every code example executed, not read
- [ ] Every link, anchor and file path resolved to the promised content
- [ ] Every flag, env var, config key and version claim checked against the code
- [ ] Walked once with only the assumed prior knowledge
- [ ] Re-run after fixes; environment named in the report; unchecked items listed

## Failure handling

- **A command fails** — that is the result, and the exact error is the evidence. Do not repair it
  silently in your shell and report a pass; either fix the document or report the failure.
- **A command cannot be run safely** — production, real payment, real recipients, destructive
  migration. Stop, say so, and mark that step unverified. Executing it anyway is the worse outcome.
- **The document and the code disagree** — trust the executed behaviour, record both, and raise it.
  You have found either a doc bug or a code bug and do not yet know which; do not decide by
  rewriting the prose.
- **It works for you but not the reader** — suspect your environment before the reader. Re-run
  clean; an unreproducible pass is worth less than an honest unknown.
- **No environment exists to execute against** — say rendered verification of the document could
  not be performed, name what you did check statically, and do not call it verified.

## Evidence to report

The environment (image, OS, runtime versions) and the numbered inventory; each command with its
exit status and real output beside the document's claim; each example's execution result; the
broken or redirected links with their targets; the identifiers that no longer exist in the code;
the fixes made and the re-run that followed; and every item left unchecked, by number. "Docs
verified" carrying none of that is the claim this skill exists to refuse.
