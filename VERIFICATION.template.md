# Checks and completion reports

Record task-scoped checks; no observer, hook or automatic runner is enabled. Select meaningful
checks. Reading tests, declared commands or another agent's claims is not execution.

## Record and inspect

`{{VERIFY_CONTROL}} run|show|note` uses the helper below. PACK is the dispatcher package;
PROJECT is the workspace. Quote absolute paths and each argument separately. RECEIPT is a
unique host-owned task/state path **outside the project**, reused only for this task. If a
receipt write is outside authorized scope, use observed native results and disclose the gap.
Never use the project's parent or shared scratch names. Receipts cannot prove cleanup/confinement.

```text
{{VERIFICATION_COMMAND}} run --project PROJECT --receipt RECEIPT --kind tests -- python3 -B -m unittest discover
{{VERIFICATION_COMMAND}} run --project PROJECT --receipt RECEIPT --kind check -- CHECK ARGUMENTS
{{VERIFICATION_COMMAND}} show --project PROJECT --receipt RECEIPT --json
{{VERIFICATION_COMMAND}} note --project PROJECT --receipt RECEIPT --status not_run --reason "Browser check not available"
```

Run only already-authorized commands through `run`; it preserves native permissions and runs
without a shell. Do not retry a denied command through the wrapper. A `denied`/`not_run` note is
an agent-reported limitation, not observed execution. `--timeout` bounds execution;
`--label` names a check; `--json` exposes details. Add `--stdin` before `-- python3 -B -` to pass
quoted stdin to an inline Python check (64 KiB limit); without it Python `-` is refused. Inline
code and sensitive arguments are omitted from stored command details. Output is not retained.
Command exit and conservative unittest/pytest counts are observations, not proof a tool is
honest or the task is correct. Unsupported summaries have unknown counts; zero tests is not
a passing test suite. A successful generic check proves only that command exited successfully.

Inspect immediately before the final report. Workspace fingerprints connect checks to file
versions. Later changes, additions/deletions, changes during execution or incomplete scanning
prevent a current-pass claim. Ignored files, dependencies outside the workspace and external
services are not covered: report relevant gaps. Rerun only affected necessary checks after
changes. Preserve failures and limitations; do not replace them with a later success claim
unless the same failing check was rerun successfully. A receipt can hold 20 observations;
when full, use another task-owned receipt and inspect both, never erase earlier evidence.

## Saved preferences

`{{PREFERENCES_CONTROL}} show|set` maps to:

```text
{{PREFERENCES_COMMAND}} show --project PROJECT --json
{{PREFERENCES_COMMAND}} set --output eli5-succinct --effort low
```

Set is global unless `--project PROJECT` selects an override. Output accepts `eli5-succinct`
or `detailed`; effort accepts `low`, `medium`, `high`, or `host` (defer to host). Both fields
are independently optional. `--state-dir` selects an explicit external preferences directory.
Defaults are ELI5 succinct and host effort. Settings live under
`$XDG_CONFIG_HOME/agent-dispatcher/preferences.json` or `~/.config/agent-dispatcher/preferences.json`;
project overrides stay there too. Show and context preparation are read-only.

Effort is a request: use documented host controls only when available and authorized;
otherwise retain effective effort unknown. Never silently edit host config, substitute models
or claim a change without host confirmation. User instructions and required checks win.

## ELI5 succinct

Default final replies answer first in plain language, usually under 150 words. Explain what
changed, what was actually checked and anything still uncertain. Prefer a short paragraph;
use a few bullets when easier to scan. Define necessary jargon, use a concrete example only
when useful, and keep the tone adult. Skip restating the request, praise and unsolicited offers.
Do not create an explanation file unless requested; receipts store evidence, not chat prose.
Detailed output expands evidence without inventing it. Required findings and limitations can
exceed the length target. Never label the whole task verified from one passing check.
Activity `output compact|verbose` remains a separate conversation-only control.

Style adapted from [isas1/skills ELI5 succinct](https://github.com/isas1/skills/blob/c47c4e637ffbbca8b81c35a8eb16d34bece04de1/skills/eli5-succinct/SKILL.md),
MIT licensed; see the package NOTICE.
