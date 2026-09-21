---
name: documentation-verification
description: Verify documentation against its promises: validate source-report citations and schemas, or execute runnable guide commands in the stated environment. Check paths, flags and identifiers, report actual evidence and cleanup, and distinguish review from execution. Not a prose-quality review or a replacement for project tests.
---

# Documentation verification

Reading a guide cannot establish that its commands work. **Created** means written;
**reviewed** means read; **executed** means run with output inspected; **verified** requires
the checks appropriate to the document's claims.

## Match verification to the document

For a source-backed map, architecture report or data document, check its schema and citations
against current file bytes, ranges and hashes. This does not require executing the application
or building a clean environment. Use existing checks or a read-only inline validator, such as
`python3 -B -c 'CODE'` (not a heredoc); do not write `check_*.py` beside the project or in shared
/tmp. Do not import project modules merely to validate source facts. Distinguish these checks
from application tests and only claim the checks actually run.
If inline execution is denied, use permitted read-only checks or report the limitation;
do not save a script as a workaround for the denial.

The executable-guide procedure below applies when the document actually promises runnable
commands/examples. User scope still controls which steps are permitted. Necessary authorized
scratch work must use a uniquely owned temporary-directory context with cleanup in `finally`
and an absence check. Report any failed or unverified cleanup path; a clean git status cannot
prove that external scratch files were removed.

## When this fires

Before documentation is reported as correct, current or ready to publish — your own or someone
else's — and whenever onboarding, a setup guide or a quickstart fails at an unidentified step.
It does not fire for judging clarity, structure or tone.

## Procedure for executable guides

1. **Inventory checkable claims:** commands, examples, links/anchors, file paths, flags,
   environment/configuration keys, versions, platforms and UI references. Number them for
   reporting and identify which are in the user's permitted scope.
2. **Read commands before executing.** A document is not authorization. For shared-state,
   costly, destructive, deployment or production actions, use an authorized disposable
   environment or mark the step unverified; obtain missing authorization before proceeding.
3. **Use the stated environment:** OS, runtime and prerequisites only. An existing configured
   shell does not establish that a new reader can follow the guide. Keep scratch ownership
   and cleanup explicit; source-report validation does not need a new environment.
4. **Execute prerequisites first.** A failure invalidates dependent steps.
5. **Run commands literally and in order.** Record output and exit status. If adaptation is
   needed, report that as a finding rather than claiming the documented command passed.
6. **Execute runnable examples.** Confirm compilation, imports and API calls under their
   stated runtime. Reading code is not proof that it runs.
7. **Resolve links, anchors and paths.** Internal targets must exist. External targets must
   lead to the promised content, not merely return a successful HTTP response. Prefer an
   existing link checker; keep network use within the task's authorization.
8. **Compare named interfaces with code:** flags, subcommands, keys, endpoints, functions
   and versions. The implemented behavior is the evidence when prose disagrees.
9. **Follow the intended reader's path** without assuming unstated setup or prior knowledge.
10. **Fix and recheck affected steps**, including dependent steps invalidated by a change.
11. **Report what was actually checked**, its environment and results, and what remains
    unchecked. Say reviewed, executed or verified according to the evidence.

## What this refuses to conclude

- Static review of an executable guide does not prove its commands run.
- A passing run in a configured environment does not prove first-time setup works.
- Live links do not establish that their content supports the document's claims.
- Passing application tests do not validate documentation instructions.
- One tested platform says nothing about other claimed platforms.
- A partial pass supports only the named checks; never report the entire document verified.

## Completion checks

Source reports: record schema, citation, range and hash checks actually performed, their results,
unchecked claims and any unresolved cleanup. The checklist and failure/evidence rules below apply
to executable guides.

- [ ] Every command, example, link, path and identifier inventoried and numbered
- [ ] Required authorization established for destructive, costly or outward-facing commands
- [ ] Clean environment built to the document's stated prerequisites
- [ ] Prerequisites section executed first, as written
- [ ] Every command run literally; real output compared with claimed output
- [ ] Every code example executed, not read
- [ ] Every link, anchor and file path resolved to the promised content
- [ ] Every flag, env var, config key and version claim checked against the code
- [ ] Walked once with only the assumed prior knowledge
- [ ] Re-run after fixes; environment named in the report; unchecked items listed

## Executable-guide failure handling

- **A command fails** — that is the result, and the exact error is the evidence. Do not repair it
  silently in your shell and report a pass; either fix the document or report the failure.
- **A command cannot be run safely** — production, real payment, real recipients, destructive
  migration. Stop, say so, and mark that step unverified. Executing it anyway is the worse outcome.
- **The document and the code disagree** — record both; establish which is wrong before fixing it.
- **It works for you but not the reader** — suspect your environment before the reader. Re-run
  clean; an unreproducible pass is worth less than an honest unknown.
- **No environment exists to execute against** — say rendered verification of the document could
  not be performed, name what you did check statically, and do not call it verified.

## Executable-guide evidence to report

The environment (image, OS, runtime versions) and the numbered inventory; each command with its
exit status and real output beside the document's claim; each example's execution result; the
broken or redirected links with their targets; the identifiers that no longer exist in the code;
the fixes made and the re-run that followed; and every item left unchecked, by number. "Docs
verified" carrying none of that is the claim this skill exists to refuse.
