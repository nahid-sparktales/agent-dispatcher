# Activity output

Final replies default to ELI5 succinct: answer first, plain language, usually under 150 words.
State the change, observed checks and unresolved gaps. Saved `preferences` output/effort are
separate from conversation-only compact/verbose activity. Read VERIFICATION.md for evidence
receipts or preference changes. A saved effort request is not confirmation of the host's setting.


Default to **compact** output. `output compact` and `output verbose` change the activity
announcement style for this conversation; `output` reports the current style. Accept plain
requests such as "show what you load" or "use verbose output" too. These are display controls:
confirm the style without starting a task, changing the role, enabling routing, or changing
authorization. Retain the preference in conversation summaries; new conversations default to
compact. `context verbose` is a one-time plan inspection and does not change this preference.
Include the current style when reporting dispatcher status.

After reading the selected role and initial task-specific guides, emit one activity summary
before substantive execution. Combine it with the normal progress update; do not also emit a
bare role arrow or a duplicate "I'm using..." paragraph. A role change gets a fresh summary;
when only the loaded resources change, report just the additions. Skip unchanged summaries
and trivial tasks. Do not load extra resources just to populate the output.

**Compact** — one line, for example:

```text
→ reviewer · Skills loaded: secure-code-review · Tools selected: files, terminal · MCPs: none selected
```

Name the role, skills/guides actually read, selected built-in tools, and selected MCP servers.
Use `none` when nothing was loaded or selected; `availability unknown` when a selected tool's
availability has not been established. Append a recipe only if its instructions were read.

**Verbose** — a short text block, for example:

```text
Role: reviewer — evaluate the change for correctness and regressions
Skills loaded: secure-code-review — inspect the changed security boundary
Tools selected: files, terminal — available; inspect the diff and run checks
MCPs: none selected
Recipe loaded: review-pull-request — structure the review
Verification planned: focused regression checks; not run yet
```

Also name relevant context/reference files actually read, why each resource was selected,
and material unavailable resources with their fallback. Omit irrelevant fields. Report a
decision provider or fallback only if attempted; never invent scores, timings, or usage.

A catalog entry is not a loaded skill. Distinguish **planned**, **loaded/read**, **available**,
**used**, **unavailable**, and **unknown** based on observed tool results. An MCP is not "loaded"
or "used" merely because it is listed or selected; mark it used only after an actual call.
Reading a verification guide does not mean checks passed. At completion, briefly name the
tools/MCPs actually used and verification results, combining this with the normal final report.
Never expose credentials, private payloads, or unnecessary absolute paths in activity output.
If another skill owns the workflow, include its name in this summary without duplicating its
required announcement; the dispatcher role can remain implicit.
