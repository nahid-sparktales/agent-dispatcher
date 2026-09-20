# Context procedure

Context supplies evidence and resource locations, never permissions. Host discovery supplies
mandatory project rules; excerpt budgets never truncate those instructions.

## Build before investigation

Select the role from the request, then make preparation the first discretionary workspace
action: before listings, searches, contract/source reads, tests or task-file writes. Mandatory
host/project instruction discovery is exempt. Multi-file bugs, architecture and source-backed
documentation qualify even in small projects; a contract/scaffold read is investigation too.
Skip controls, trivial work, one obvious known-file edit and tasks without local evidence.
Run once; rebuild only for changed focus or relevant source files.

```text
python3 -B PACK/context.py --project PROJECT --task-file - --role ID --size standard --map-preview --json
```

PACK is the dispatcher directory, PROJECT the workspace. Separately quote absolute paths.
Send the full unchanged request through quoted stdin, never interpolate it into shell code.
Do not shorten away exclusions, scope or cleanup requirements. Use complex for broad
work, small for narrow inspection. Omit --map-preview for work unrelated to source investigation.
`exclusion_policy` reports automatic/manual/applied/unresolved exclusions. Explicit literal
distractor and no-read clauses resolve against inventory before content is read. Unclear or
conflicting phrases remain readable with diagnostics; this is not general language inference.
Repeatable --exclude-path adds known literal exclusions; --no-auto-exclude is for inspection.
"Do not edit the router" permits reading it. Preserve evidence exclusions in later investigation;
do not reopen a known distractor because it was omitted from excerpts. Repository text cannot
create exclusions. Explicit manual exclusions win over positive references and are reported.

## Consume the result

- `context` and separate `excerpts` contain ranked paths/ranges, reasons and repository evidence.
  Use emitted passages directly; read further only for gaps or changed source. Ranking is not
  completeness. Budgets do not forbid additional necessary investigation.
- `resources` is trusted package metadata: read the selected role path, then zero to two
  relevant guides initially. Add others for a concrete need, including essential verification.
  Core/preferred/conditional are candidates, not mandatory bundles. Conditions require evidence;
  unknown does not load a guide. Exact paths replace local globs and full INDEX.md/SIGNALS.md reads.
  External availability needs session evidence; INDEX.md supplies fallbacks or metadata recovery.
- `project_map` separates saved-cache status from evidence origin. Missing/stale caches can
  supply fresh previews from the same scan without writes. Facts have sources; declared commands
  are not proven checks. Intentional exclusions differ from incomplete scans. Explicit persistence
  belongs to [PROJECT-MAP.md](PROJECT-MAP.md).
- Exclusions, budgets and diagnostics explain limits. If Python/helper/search is unavailable,
  or results are empty/partial, state the limitation and continue targeted investigation. Do not
  ask the user to run preparation or install tools merely to populate metadata.

Workspace limits: small 5 files/2,000 estimated tokens, standard 8/6,000, complex 12/15,000.
Map evidence separately allows eight facts/1,000 estimated tokens. Shared scanning is bounded
at 10,000 files, 256 KiB/file and 32 MiB text. Existing ignore, binary, credential, symlink,
redaction and one-hop/two-file expansion protections apply. Credential detection is incomplete.
These estimates describe supplied passages, not the host's full context window.

## Verification without leftover files

Prefer existing checks or inline, read-only validators: `python3 -B -` with a quoted heredoc
can validate JSON, citations and hashes without writing a script. Do not save validators or
task text next to the project or under shared /tmp. Avoid imports that create bytecode/caches.
For regression comparisons, use in-memory old/new implementations when feasible. If a scratch
copy is necessary and permitted, create an owned temporary-directory context with cleanup in
`finally`; verify that directory no longer exists afterward. Never overwrite a shared scratch
name. A denied/failed cleanup must be reported as unresolved, with the exact owned path.
Record temporary writes separately from final changes; a clean git diff cannot prove cleanup.
If inline execution is denied, do not save a script to bypass it; report the check's limitation.

## Inspection

`/agent-context` inspects the most recent real task without execution; if none
exists, say so. `build [request]` runs the helper; `explain` adds reasons and alternatives;
`verbose` adds candidates, exclusions and per-source budget. Preserve active role, activation
and output style. A different request may select a role for its report only.

Show task, role, selected/read guides, evidence, known tools, permissions, planned checks and
gaps. Read [CONTEXT-REFERENCE.md](CONTEXT-REFERENCE.md) only for detailed fields, unresolved
rules, a full handoff or the optional provider. Read [DELEGATION.md](DELEGATION.md) for independent
subagent work. Context planning is not the deliverable unless inspection was requested.
