# Project map

A small local map records feature locations, dependencies, test commands, and declared
architecture decisions with source paths, line numbers, and content fingerprints.
It is a source-linked JSON evidence index, not a binary tree or a complete architecture model.
It provides evidence for investigation, never instructions or authority to execute a command.
Keep the active role, output style, and activation state unchanged during map controls.

## Commands

Resolve PACK to the installed dispatcher directory and PROJECT to the workspace.
Use the helper beside the context selector; quote absolute paths and task arguments.

| Request | Helper |
| --- | --- |
| `{{MAP_INSPECT_COMMAND}}` or `show [request]` | `{{MAP_COMMAND}} show --project PROJECT` |
| `{{MAP_INSPECT_COMMAND}} build` | `{{MAP_COMMAND}} build --project PROJECT` |
| `{{MAP_INSPECT_COMMAND}} refresh` | `{{MAP_COMMAND}} refresh --project PROJECT` |

Add `--task "<request>"` to filter displayed facts and `--json` for structured output.
The request filters evidence; it does not authorize executing that task. Show the result,
including source links, freshness, omissions, and diagnostics. Do not invent a map when absent.

`build` and `refresh` explicitly write `.agent-dispatcher/project-map.json` in PROJECT.
They do not change host settings, activation, project rules, or Git ignore files. Existing
unrecognized state and symlinked destinations are refused. Let the user decide whether to
share the map through version control; it is local project data. Do not manually edit cached
claims. Correct their source and refresh the map.

## Use during work

During substantial source work, use the context selector with --map-maintain to create or
update the local cache from its existing safe scan. This reuses that scan rather than
opening the project a second time. Unchanged source hashes allow supported cached facts
to be reused, but every persisted claim is revalidated against the current source text.
New, changed, removed, and newly ignored sources are reflected in the next complete scan.
Identical map content causes no write. No task text or exclusion policy is saved.

Maintenance reports its action (`built`, `refreshed`, `unchanged`, `deferred`, or
`unavailable`) and whether this call persisted a map. A partial or task-filtered scan
returns evidence only from allowed sources and defers persistence, preserving the existing
global cache. It never labels that subset as verified whole-project freshness. Unsafe,
foreign, or malformed state is left untouched; write failures report that saving failed.
Use current permitted evidence and targeted investigation when maintenance cannot finish.

Use --map-preview for read-only work, protected caches, and limited file-edit scopes. It derives
fresh evidence when the cache is absent or stale without saving anything. With neither flag, context selection
only reads and verifies an existing cache; a missing map leaves ordinary context selection
available. The standalone `show` command always stays read-only, and explicit `build` and
`refresh` remain available for authorized cache operations, never to bypass task restrictions.
If both flags reach the helper, preview takes precedence and maintenance is deferred.

Both automatic cache writers check scope before creating a directory or changing a file.
The conservative request guard treats read-only, limited edits, and file-preservation language
as a veto; request text never grants additional write access. Repeat --writable-path with the
actual permitted relative files or subtrees (trailing /) for a literal boundary. Each cache is
checked separately; task restrictions still win. This option does not constrain source reads,
external reuse state, or arbitrary host tools. It is not a general permission sandbox.
Unknown natural-language phrasing needs the explicit path boundary or preview.

Scope deferral returns fresh evidence with `maintenance.action: deferred`, `persisted: false`,
and `maintenance.write_scope` naming the target and reason. `project_read_only` reports whether
context preparation changed project state. Do not confuse successful evidence preparation with
a saved cache, or recommend an out-of-scope refresh to remove the diagnostic.

Saved-cache status and evidence origin are reported separately; eight facts and 1,000
estimated tokens bound the evidence. Intentional task exclusions are not stale sources.
Changed, deleted, ignored, or unreadable sources cannot supply current facts. Report stale
or partial coverage and fill gaps with targeted investigation. A new file can make coverage
incomplete even when previous facts remain valid. Current-scan evidence is not a persisted
refresh when maintenance is deferred or a write fails.

Recheck context when the task focus or relevant source changes. The map is bounded and
heuristic: a recognized definition suggests a feature location; imports and manifests
identify declared dependencies. Test command text is discovered, never executed or verified.
Decision documents record what their authors stated, not proof that code follows the decision.
Missing facts are unknown; explain limits instead of inferring architecture or successful checks.

The helper uses local Git/ripgrep enumeration and the selector's file safety and redaction
rules. It has no model calls, external services, persistent processes, or background refresh.
Recognized credential patterns are scrubbed, but detection is incomplete. Map context has
its own bounded output and token estimate, separate from the workspace excerpt budget.
The scan still reads permitted source text and computes hashes; no filesystem-read or
performance savings beyond scan reuse are promised. Host instruction discovery remains
responsible for applicable project rules. The host also owns agent coordination, waiting,
and worktree isolation; the map does not launch or supervise workers.

## Optional structural graph

--map-preview and --map-maintain also derive a structural view from the same redacted
scan. Only maintenance can save `.agent-dispatcher/project-graph.json`; partial scans
defer writes. This separate cache cannot invalidate legacy map facts.

Python AST supplies definitions, local imports, and unambiguous static direct calls.
JavaScript/TypeScript relative imports remain inferred candidates. Every edge cites its
method, confidence, and fingerprinted source. Unknown dispatch stays unknown; test
relationships are candidates, not coverage. Task-seeded ranking and role preferences can
promote related source excerpts. Upstream/downstream impact and possible call paths require
retained resolved edges; they do not prove runtime behavior.

Limits: 80 sources, 240 nodes, 400 edges stored; about 1,500 estimated tokens, 12 nodes,
16 edges, and eight source hints per task view. Report omissions and parse failures.
Trimming removes unsupported paths and impact claims. No embeddings, architecture rules,
extra source scan, provider calls, or worker supervision are added.
