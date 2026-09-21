# Checks and completion reports

Record meaningful, authorized checks. Reading tests or commands is not execution. No observer
or automatic runner is enabled. PACK is the package; PROJECT the workspace. Quote arguments.

## Run, inspect, clean

`/agent-verify run|show|note` uses:

```text
python3 -B PACK/verification.py run --project PROJECT --kind tests -- python3 -B -m unittest discover
python3 -B PACK/verification.py run --project PROJECT --kind check -- CHECK ARGUMENTS
python3 -B PACK/verification.py run --project PROJECT --kind check -- python3 -B -c 'assert 1 + 1 == 2'
python3 -B PACK/verification.py show --project PROJECT --receipt RECEIPT --cleanup --json
```

Default `run` returns evidence and removes its private temporary receipt/directory. Temporary
storage must be authorized; otherwise use native results. Explicit `--receipt RECEIPT` retains
up to 20 observations at a unique owned path outside the project. Plain `show` is read-only;
`show --cleanup` inspects then removes only the validated unchanged receipt, never its parent.
Use `note --receipt RECEIPT --status not_run|denied --reason TEXT` for reported limitations.
Refused cleanup fails and reports a leftover path. Never sweep shared scratch or unexpected
files. Forced termination can leave state; this cleanup excludes files a command itself creates.

Run only authorized commands; no shell or permission bypass. Never retry a denial via this
wrapper. `--timeout` bounds execution, `--label` names checks, `--json` exposes evidence.
Pass inline code as `python3 -B -c 'CODE'` (each `'` written `'\''`): hosts refuse heredocs
containing braces. `--stdin` reads a pipe (64 KiB maximum), takes no argument and goes before
`-- python3 -B -`; Python `-` without explicit stdin is refused. Stored command
details omit inline code/sensitive arguments; raw output is discarded.

Unittest/pytest counts are runner reports, not coverage proof. Unsupported summaries have
unknown counts; zero tests is not a pass. Generic success proves only a successful command exit.
Inspect retained receipts immediately before reporting. File changes during/after checks or
incomplete scans prevent current-pass claims. Ignored files, external dependencies/services are
unverified. Rerun affected checks after edits. Preserve failures until the same check passes;
inspect all receipts rather than erasing earlier evidence. Receipts are editable local records.

## Audit task edits

With authorized temporary storage, add `--audit` to first context preparation. It snapshots
before helper writes. Keep `change_audit.state`; never reset the baseline after edits. Finish:

```text
python3 -B PACK/change_audit.py finish --project PROJECT --state STATE --json
```

Repeat `--writable-path` for actual allowed relative files/subtrees (directories end in /).
The report names added/deleted/modified and out-of-scope files, including untracked/ignored
caches, then cleans owned state. `.git` is outside scope. Exclusions and bounds prevent blanket
preservation claims. Without a baseline, disclose the gap; a Git diff alone is insufficient.

## Saved preferences

`/agent-preferences show|set` maps to:

```text
python3 -B PACK/preferences.py show --project PROJECT --json
python3 -B PACK/preferences.py set --output eli5-succinct --effort low
```

Set is global unless `--project PROJECT` selects an override. Output: `eli5-succinct|detailed`;
effort: `low|medium|high|host`. Fields are independently optional; `--state-dir` selects external
storage. Defaults: ELI5 succinct, host effort. Storage: `$XDG_CONFIG_HOME/agent-dispatcher/preferences.json`
or `~/.config/agent-dispatcher/preferences.json`, including project overrides. Show/preparation
never modify preferences. Use authorized host controls to apply effort; otherwise retain
effective effort unknown. Never silently change host configuration/models or claim confirmation.
User instructions and required checks win. Activity `output compact|verbose` is separate.

## ELI5 succinct

Answer first in plain language, usually under 150 words: changes, observed checks, gaps.
Use brief prose or useful bullets; define necessary jargon. Skip praise, request restatements
and unsolicited offers. Create no explanation file unless requested. Detailed output expands
evidence without upgrading uncertainty. Required findings may exceed the target; one passing
check never establishes whole-task verification.

Style adapted from [isas1/skills ELI5 succinct](https://github.com/isas1/skills/blob/c47c4e637ffbbca8b81c35a8eb16d34bece04de1/skills/eli5-succinct/SKILL.md),
MIT licensed; see the package NOTICE.
