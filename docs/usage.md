# Usage and configuration

Start with the [quick start](../README.md#quick-start). This guide covers commands, context,
project knowledge, output preferences, activation, and removal. For the complete role and
integration lists, see the [catalog](catalog.md).

[Routing](#let-the-dispatcher-choose) · [Output](#see-what-the-dispatcher-loads) ·
[Context](#build-local-context) · [Project maps](#keep-a-project-map-current) ·
[Memory](#repository-memory) · [Activation](#activate-automatically-in-future-sessions) ·
[Uninstall](#uninstall)

Run shell commands that name repository scripts from the root of your clone.

## Command syntax

The examples and the [catalog](catalog.md) use **Claude Code manual-install command names**. For a Claude plugin install,
add `agent-dispatcher:` after the slash: `/agent-context` becomes
`/agent-dispatcher:agent-context`.

In Codex, use `$agent-dispatcher <request>`. Choose a role with `$agent-dispatcher reviewer`,
inspect context with `$agent-dispatcher context`, and use `$agent-dispatcher decision` for
decision settings. The catalog's `/agent-uidesigner` maps to `$agent-dispatcher uidesigner`,
and the other role aliases work the same way. Activation arguments such as `on here` and
`off everywhere` are shared between hosts; their settings are stored separately.

### Let the dispatcher choose

```text
/agent-dispatcher Redesign the settings page, implement it, and check it on mobile.
/agent-dispatcher Review this change for correctness and missing tests.
/agent-dispatcher Compare the approaches already used in this repository and recommend one.
```

Routing follows the requested deliverable, using three execution profiles without an extra
router or model call:

- **Direct:** trivial work or one safe, obvious edit in a known file. Skip role/guide loading,
  context preparation, preference lookups and reporting references; use known preferences or
  defaults and check the result with native tools. Required checks still apply.
- **Guided:** work needing specialist judgment or investigation. Select a role, prepare context
  before substantial investigation, and load only the guidance the task needs.
- **Coordinated:** guided work with useful independent subtasks. Give workers separate scopes
  and combine their evidence using the host's subagent tools.

Security-sensitive work, configuration or behavior ambiguity, and multi-file tasks stay guided.
If a direct task reveals wider scope or uncertainty, prepare before investigating further.
Explicitly selected roles, invoked workflows, user instructions and host permissions always
win. Profiles do not switch the host's model, effort or permissions.

### Prepare less repeated context

Substantial work uses a compact context packet containing source excerpts, the selected role's
instructions, and resource locations. Supplied guidance is consumed directly instead of read
again from its file. Repeatable `--guide ID` supplies eligible guide bodies. Compact packets keep
up to three other guide candidates, prioritizing verification, and omit duplicate role metadata.
Explicit guides resolve against the full eligible catalog even when absent from the shortlist.

`--packet-tokens N` bounds the estimated size of the whole compact packet, including guidance,
metadata, diagnostics, map facts, graph views and excerpts. This is not a measurement of the host's full
context window or model usage. Normal preparation uses `--compact`; omit it with `--json` for
full inspection. Missing required evidence still needs investigation; a small packet is not
proof of completeness.

`--packet-mode lean|evidence` (or `AGENT_DISPATCHER_PACKET=lean|evidence`) slims a compact packet.
Lean keeps the role body, ranked navigation rows with line spans, coverage, a `next_action` when
coverage is partial or nothing ranked, and `timing`. Evidence adds up to two excerpts per file. The
default `legacy` mode is unchanged, and the variable is ignored without `--compact`. In these modes
`--packet-tokens` (or `AGENT_DISPATCHER_PACKET_TOKENS`, default 4000) is a soft target in estimated
tokens for SKILL.md plus the packet, estimated as UTF-8 bytes / 2 rather than characters / 4. When
required content alone exceeds it, the packet drops every optional item, excerpts included (counted
in `packet_omissions`), and reports `target_met: false` with `protected_content_exceeds_target`; the
rows' spans are then what to open. At the default 4000 that is the usual outcome, so evidence mode
needs a larger target to carry excerpts. The printed payload always stays within 28,000 UTF-16
units including its newline; if it cannot, the helper fails instead of truncating. See
[context selection](context-engine.md#packet-modes-budgets-and-timing) for units, trimming order
and timing fields.

During substantial source work, `--map-maintain` uses the same scan to maintain the source-linked
project map and structural graph when safe writes are permitted. Excluded or incomplete scans defer persistence;
unsafe destinations leave a read-only result with diagnostics. Both writers veto recognized task
restrictions and roles whose tool posture is read-only. Use `--map-preview` for edit limits the
helper may miss, such as unusual wording or plan mode; preview always wins. Repeat `--writable-path` to enforce literal permitted files or
subtrees (trailing `/`), independently of source-reading exclusions. Deferred maintenance still
returns fresh evidence and explains its write decision. Map facts never authorize execution.

Repeated preparation may opt into `--reuse-state ABS --reuse-scope ID`, using an authorized
absolute state path outside the project. Reuse references only within the same context that
still retains the earlier content. Changed evidence is supplied again. A fresh chat, new worker
or lost/compacted evidence needs a fresh scope or full output. This does not enable automatic
cross-chat memory, an observer or background processing. See the
[context procedure](../skills/agent-dispatcher/CONTEXT.md) for limits and inspection controls.
The [project-intelligence design](project-intelligence.md) explains how mapping, caching,
retrieval, and the final packet fit together. Packet limits cover the helper's output, not the
host's entire conversation or model usage.

### Choose a role or inspect a decision

| Command | Purpose |
| --- | --- |
| `/agent-uidesigner` | Work as the UI/UX Designer. |
| `/agent-debugger` | Work as the Debugger. |
| `/agent-reviewer` | Work as the Reviewer. |
| `/agent-inventory` | List skills, tools, and MCPs with usability and setup status. |
| `/agent-doctor` | Check installation health, list every capability, and recommend relevant setup. |
| `/agent-context` | Show the current context plan. |
| `/agent-context build <request>` | Retrieve relevant workspace passages with locations, reasons, and a size budget. |
| `/agent-map [show\|build\|refresh]` | Record project facts with source links and detect when those sources change. |
| `/agent-context explain` | Explain the role, skills, and tools selected. |
| `/agent-context verbose` | Include candidates, dropped files, and the context budget. |
| `/agent-decision` | Show optional decision-engine configuration and status. |
| `/agent-verify run\|show\|note` | Record actual checks, inspect freshness, or disclose a check that wasn't run. |
| `/agent-preferences show\|set` | Inspect or save output style and requested effort. |

A directly selected role stays active until you choose another or stop the dispatcher.

### See what the dispatcher loads

Compact output is the default. It combines the role and resources into one progress line:

```text
→ reviewer · Skills loaded: secure-code-review · Tools selected: files, terminal · MCPs: none selected
```

For more detail, switch to verbose output. In Codex:

```text
$agent-dispatcher output verbose
$agent-dispatcher output compact
$agent-dispatcher output
```

In Claude Code, use `/agent-dispatcher output verbose` or `output compact` (with the
`agent-dispatcher:` prefix for plugin installations). `output` reports the current style.
You can also say "use verbose output" or "show what you load".

Verbose output explains the selections and names context read, recipes loaded, unavailable
resources and fallbacks, and planned verification. For example:

```text
Role: reviewer — evaluate the change for correctness and regressions
Skills loaded: secure-code-review — inspect the changed security boundary
Tools selected: files, terminal — available; inspect the diff and run checks
MCPs: none selected
Recipe loaded: review-pull-request — structure the review
Verification planned: focused regression checks; not run yet
```

These are examples, not a fixed loadout. Only skills actually read are labeled loaded;
selected MCP servers are marked used only after a call. Later additions get a short update,
and the final report names tools used and checks performed. Trivial tasks skip the summary.

The setting lasts for the conversation; new conversations default to compact. It changes
activity reporting, not routing, permissions, or the length of the requested deliverable.
`context verbose` remains a one-time inspection of the context plan.

### Short answers backed by checks

Final replies default to **ELI5 succinct**: plain language, answer first, usually under 150
words. They say what changed, what actually passed and what remains unchecked. This style is
adapted from [isas1/skills](https://github.com/isas1/skills/tree/main/skills/eli5-succinct)
under MIT; see [NOTICE](../NOTICE). Detailed evidence stays available separately.

Save preferences in Codex:

```text
$agent-dispatcher preferences set --output eli5-succinct --effort low
$agent-dispatcher preferences show
```

Claude uses `/agent-preferences` with the same arguments. Add `--project PROJECT` when setting
a project override. Settings live outside the project in Dispatcher-owned configuration.
Low effort is a **saved request**, not proof the host changed its active setting; the helper
never edits Claude or Codex model configuration. Default effort is `host` until changed.
Activity `output compact|verbose` remains separate.

The verification helper wraps authorized commands and fingerprints workspace files. Default
receipts are temporary: evidence is returned and owned files are removed with a cleanup result.
Explicit retained receipts can be inspected after edits and removed with `show --cleanup`.
Failed checks, zero tests, unknown counts and checks not run remain distinct. Optional preparation
with `--audit` captures a task baseline before helper writes; start it before any task edits.
Finishing the audit reports actual file changes, including untracked/ignored caches, then cleans
its state. Partial scans cannot prove preservation. No observer, behavioral-coverage claim or
permission bypass is enabled. See the
[verification guide](../skills/agent-dispatcher/VERIFICATION.md) for commands and coverage limits.

### List what is usable and what needs setup

In Codex:

```text
$agent-dispatcher inventory
$agent-dispatcher inventory skills
$agent-dispatcher inventory tools
$agent-dispatcher inventory mcps
$agent-dispatcher inventory setup
$agent-dispatcher inventory setup verbose
```

In Claude Code, use `/agent-inventory` with the same filters, or
`/agent-dispatcher:agent-inventory` for a plugin install. `/agent-dispatcher inventory` also works.

The report covers bundled guides, referenced external skills, other host-exposed skills,
visible tools, and catalog or host-exposed MCP servers. Each entry has a status and a next step:

| Status | Meaning |
| --- | --- |
| Usable | Guidance is readable or the tool is exposed, with no known blocker. Tool connectivity may still be untested. |
| Needs setup | A missing installation, dependency, connection, or authentication step is confirmed. |
| Blocked | A user preference or host permission prevents use. |
| Unknown | Available evidence is insufficient; the report names what to check. |
| Not recommended | The registry records an unmaintained or retired integration and its fallback. |

`setup` filters to entries needing attention. `verbose` adds evidence, prerequisites, source
links, and fallbacks; compact still lists every entry in the requested scope. The command
inspects availability without loading every skill, probing accounts, or installing anything.
It reports discovery limits rather than treating an unseen integration as missing. Usability
is separate from permission to perform a particular action.

### Build local context

The dispatcher uses a local selector after choosing a role for substantial or unfamiliar
workspace tasks. It skips trivial edits and configuration controls. To inspect context directly:

```text
$agent-dispatcher context build Investigate why validate_login rejects valid sessions
/agent-context build Investigate why validate_login rejects valid sessions
```

The first form is for Codex, the second for Claude Code. Inspection returns relevant passages,
file locations, line numbers, selection reasons, exclusions and an estimated size budget; it does
not perform the requested change. Existing `context`, `context explain`, and `context verbose`
commands still inspect the context plan.

The selector uses repository intelligence by default (`--retrieval auto`). It recognizes paths,
dotted modules, code identifiers, quoted errors, and stack-trace frames; combines independent search rankings using
reciprocal rank fusion; then expands the strongest matches through bounded code relationships
and Git co-change history. Explicitly named files stay first. `--retrieval legacy` selects the
older flat scorer, which is also the fallback if the new engine cannot load.

Ignore rules, task exclusions, and credential checks run before retrieval. Excluded sources
cannot reappear through symbols, history, explorer requests, or explain output. Files above
the 256 KiB excerpt limit can still contribute paths, relationships, and structural records
extracted from bounded reads; their source text is not retained in the index or excerpted. Scan limits and unavailable evidence are reported. A limited packet
is a starting point; the agent can read additional evidence when needed.

Default retrieval needs no model call. If you have enabled model assistance, preparation can
also use current stored summaries and the configured reranker. Querying never generates missing
summaries. Optional bounded exploration (`--retrieval full+explorer` or `retrieval.py expand`)
can request symbols, paths, callers, references, and neighbors from the existing index;
it is off by default.

The dispatcher entrypoint and concise context guide are each capped at 6 KiB per host. Role
catalogs, configuration controls, delegation and advanced examples live in references read only
when needed. These are limits on dispatcher instructions and retrieved passages, not the host's
whole context window or a claim of improved model performance.

From the source checkout, pass the request as one quoted argument. This also avoids heredoc
handling differences between hosts:

```bash
python3 -B context.py --project /path/to/project --role debugger \
  --task='Investigate why validate_login rejects valid sessions. Do not change any files.' \
  --compact --map-preview --json
```

`--map-preview` prevents map and parser-cache writes; it does not disable a user-enabled
reranker. To inspect deterministic retrieval without model assistance:

```bash
python3 -B retrieval.py explain-query 'Investigate why validate_login rejects valid sessions'
python3 -B retrieval.py explain 'Investigate why validate_login rejects valid sessions' \
  --project /path/to/project --verbose --no-llm
```

`explain-query` shows which words became paths, symbols, concepts, or ignored terms. `explain`
shows each search method's contribution, relationships, and budgeting decisions. Omit
`--no-llm` to include your enabled model layer; `context.py --explain` embeds the trace in a packet.

Use `--size small|standard|complex` for retrieval scope, `--max-files N` and `--max-bytes N`
to tighten file and excerpt limits, `--max-tokens N` for excerpt tokens, or `--packet-tokens N`
for the whole compact packet. Each file gets an initial excerpt before second excerpts are
added; duplicate content and tests are constrained to leave room for distinct source files.
See [context selection](context-engine.md) for controls and limits.

### Keep a project map current

Dispatcher maintains two project indexes and a separate private cache. Optional model-written
representations have their own store. These serve different purposes; none stores a conversation
or replaces the host's instructions.

| Stored data | Location | Purpose |
| --- | --- | --- |
| Fact map | `~/.cache/agent-dispatcher/state-v1/<project id>/project-map.json` | Feature locations, declared dependencies, test commands, and documented architecture decisions, with source locations and fingerprints. |
| Structural graph | `~/.cache/agent-dispatcher/state-v1/<project id>/project-graph.json` | Files, Python symbols, imports, supported direct calls, and candidate test relationships, with evidence and confidence labels. |
| Incremental parser cache | `~/.cache/agent-dispatcher/parser-v1/` | Authenticated records of redacted source text, extracted facts, per-file retrieval records, filtered Git history, and resolved graphs. |
| Optional file summaries | `~/.cache/agent-dispatcher/llm-retrieval-v1/` | Model-written retrieval aids keyed by source content, model, provider, and prompt/schema versions. |
| Optional deep index | `~/.cache/agent-dispatcher/state-v1/<project id>/repository-index.sqlite` | Complete admitted inventory, per-file records, symbols, relationships, corpus statistics, bounded history and Explorer inferences; built only by `repository_intelligence.py build`. |
| Task experience | `~/.cache/agent-dispatcher/state-v1/<project id>/experience.sqlite` | Explicitly recorded task events with outcomes, corrections and forgetting; recording and retrieval are enabled by default. |

The map, graph, and parser cache honor an absolute `XDG_CACHE_HOME`. Their locations must be
outside the inspected project. Older `.agent-dispatcher/project-map.json` and
`project-graph.json` files are validated and read when no private copy exists; maintenance
does not rewrite or delete them. Current index maintenance creates no `.agent-dispatcher/`
directory or working-tree changes. The optional summary store uses the separate path above.

During substantial guided work, `context.py --compact --map-maintain` requests automatic
maintenance. A complete, unrestricted scan can create or refresh both project indexes and
populate the private cache. No discovered test command or project module is executed to build
them. Maintenance happens during context preparation; there is no background watcher.

On later preparations:

1. **Check the current inventory.** Apply ignore rules, task exclusions, and file safety checks
   before using a source. New, deleted, renamed, and newly ignored paths affect the current view.
2. **Reuse unchanged evidence.** Valid cached entries can avoid repeated source reads, parsing,
   and fact extraction. Changed sources are read again; missing or invalid entries fall back
   to fresh extraction. File identity, timestamps, permissions, and parser/redaction policy
   are part of the reuse checks.
3. **Update relationships.** Reuse a graph when its scoped inputs match. When those inputs
   change, resolve relationships again using current cached and newly parsed evidence.
4. **Select a task view.** Rank a bounded set of facts, symbols, candidate tests, and source
   excerpts for the request and role. The complete indexes are not dumped into model context.

Python definitions, imports, and a conservative subset of direct calls use the standard AST
parser. JavaScript/TypeScript support covers inferred relative-import candidates; the retrieval
index also recognizes declaration patterns in other languages. Possible
call paths are static hints; test links do not prove coverage, and documented decisions do
not prove that the code follows them. The graph is bounded to 1,000 source files, 30,000 nodes,
36,000 edges and 16 MiB. The fact map is bounded to 1,000 source files, 6,200 facts, and 4 MiB;
both stop at their storage limits and report omitted evidence or parse failures.

#### Control mapping and cache writes

| Control | Effect |
| --- | --- |
| `--map-maintain` | Request index maintenance when the task, role, write scope, scan, and destination permit it. |
| `--map-preview` | Derive or reuse current evidence without saving indexes or the private parser cache. Takes precedence over maintenance. |
| `--writable-path PATH` | Restrict optional index/cache writes to literal files or subtrees; repeat as needed and end directory paths with `/`. Index writes still require their logical cache targets to be allowed. |
| `--exclude-path PATH` | Omit a file or directory from source retrieval before reading or using its evidence. |
| `--no-parser-cache` | Bypass private cache reads and writes and perform fresh source extraction. Does not itself make project-map maintenance read-only. |

Read-only tasks and recognized edit restrictions veto automatic cache writes. Explicit limited
write scopes also prevent private host-cache writes. Partial or task-excluded scans return
permitted evidence and defer persistence, preserving the existing global indexes. Unsafe or
unrecognized cache destinations are left untouched. Write checks retain the logical targets
`.agent-dispatcher/project-map.json` and `.agent-dispatcher/project-graph.json` even though
storage is now private. Moving storage outside the project does not bypass task restrictions.
These controls govern the helpers; host permissions still govern the agent's other tools.

File metadata checks are a reuse shortcut, not a newly computed content hash on every call.
Use `--no-parser-cache` when fresh reads are required. Redaction is best-effort. Project-local
map and graph files remain untrusted: matching fingerprints alone do not authenticate their
claims. The `parser_cache` result reports actual source bytes read, logical scan bytes,
parses, reuse, graph hits, and write outcomes. Read-only and warm calls retain the same scan
limits as fresh extraction.

To manage just the fact map explicitly:

```text
$agent-dispatcher map build
$agent-dispatcher map show authentication
$agent-dispatcher map refresh
```

In Claude Code use `/agent-map build`, `/agent-map show authentication`, and
`/agent-map refresh`. Build and refresh write the fact-map file; show stays read-only. These
standalone commands scan sources independently. The incremental parser cache and structural
graph are used through the context selector's map modes.

The standalone helper supports `build`, `show`, and `refresh`, `--project`, optional
`--task`, `--pack`, and `--json`:

```sh
python3 -B project_map.py build --project /path/to/project
python3 -B project_map.py show --project /path/to/project --task authentication
```

See the [project-map reference](../skills/agent-dispatcher/PROJECT-MAP.md) for freshness checks,
coverage limits, and write-scope diagnostics.

### Optional model-assisted retrieval

This layer is **off by default**. Enable it in your own settings file outside the project:
`~/.config/agent-dispatcher/llm-retrieval.json`, or a path selected with
`AGENT_DISPATCHER_LLM_CONFIG`. An absolute `XDG_CONFIG_HOME` changes the default configuration
root. A project cannot enable it or choose the destination for its source.

| Feature | What it does | When a model is called |
| --- | --- | --- |
| File role summaries | Describes a file's responsibilities, symbols, concepts, and interactions; searches those descriptions locally alongside source-based retrieval. | During an explicit indexing run, for missing or changed content. |
| Candidate reranker | Orders a bounded set of already retrieved files using summaries and retrieval evidence. | During retrieval, if separately enabled and its policy and budget permit it. |

File summaries describe what code does; they are separate from the dispatcher's specialist
roles. Summaries are checked against the index, stale summaries are skipped, and unsupported
symbol names or interaction targets are discarded. They remain advisory; the packet supplies
real source excerpts for the agent to inspect.

Representation generation and reranking can use different models. Supported transports are
OpenAI-compatible endpoints, Anthropic's Messages API, and a local command. API credentials
come from named environment variables. See the [LLM-assisted retrieval guide](llm-assisted-retrieval.md)
for a complete settings example, provider options, and payload details.

After configuring a provider, run from the source checkout:

```bash
python3 -B llm_retrieval.py index --project /path/to/project --dry-run
python3 -B llm_retrieval.py index --project /path/to/project
python3 -B llm_retrieval.py status --project /path/to/project
```

The dry run counts eligible files and estimates input tokens without calling a model. Indexing
is incremental and resumable: stored results are reused for unchanged content under the same
model and versions. It sends eligible files' paths, static evidence, and bounded redacted source
to the configured provider. Retrieval itself never fills missing summaries.

The reranker defaults to at most 20 candidates, runs before graph expansion, and uses `replace`
integration: its order leads the candidate list while explicitly named files remain pinned.
It cannot introduce a new file. Optional settings allow post-graph placement, blended rankings,
seed-only use, reranking only when the deterministic result is ambiguous, or shadow mode that
records a proposed order without applying it. Invalid or unavailable model responses fall back
to deterministic ordering with diagnostics.

Summary search makes no per-query model call. Reranking sends the request, candidate paths,
summaries or symbol metadata, and selection evidence to the configured provider. Indexing and
querying have separate call budgets. Exclusions apply before either operation; redaction is
best-effort. Provider access and usage costs are separate from normal dispatcher use.
Usage records include model and prompt versions, tokens, and latency. Cost reporting uses
provider-reported amounts when available, otherwise an estimate from your configured prices.

### Deep onboarding, incremental maintenance, and task experience

For a repository you will work in repeatedly, an explicit deep index covers every admitted file
(not the scan's 10,000-path prefix), keeps stable symbol identities and labeled relationships,
bounded `HEAD` history and corpus statistics, and is refreshed incrementally from the working
tree. Ordinary context preparation uses it automatically once it exists and reports it under
`repository_intelligence.index`; without one, nothing changes.

```bash
python3 -B repository_intelligence.py build --project /path/to/project --json      # explicit onboarding
python3 -B repository_intelligence.py refresh --project /path/to/project --json    # fast metadata reconcile; --strict re-hashes
python3 -B repository_intelligence.py status --project /path/to/project --json     # read-only; creates nothing
python3 -B repository_intelligence.py explain 'Fix validate_login' --project /path/to/project
```

An optional onboarding Explorer lets a model ask bounded, validated questions of the index and
stores architectural notes labeled as inferences. Enable it in your own
`~/.config/agent-dispatcher/repository-intelligence.json`; `explore` is off by default and makes
zero model calls when off. Task experience uses a separate setting in `repository-memory.json`:
recording and retrieval are on by default, but observations must be handed in explicitly
(`experience record|list|correct|forget`). Eligible records can then contribute one labeled,
half-weight vote for later similar requests. A zero-test run, an exit
code alone or a stale receipt never counts as success. See
[the deep-index guide](repository-index.md).

### Repository memory

Three separately switched layers of reusable repository knowledge kept in private state outside
the project and used only through the current admitted source index, configured in
`~/.config/agent-dispatcher/repository-memory.json` (or `AGENT_DISPATCHER_MEMORY_CONFIG`).
Experience is on by default; episodic and semantic retrieval ship in `shadow` mode. Nothing has any
effect until a store is built or an observation is recorded.

| Layer | Holds | Built by |
| --- | --- | --- |
| Episodic | eligible commits reachable from HEAD, admitted changed paths, rename lineage, changed symbols, issue/PR references, hotspots | `repository_memory.py build` / `refresh` |
| Semantic | deterministic module records with evidence manifests; optional model summaries keyed to their evidence | `build`; `summaries generate` |
| Experience | bounded task events in the shared SQLite store (also written by `repository_intelligence.py experience`), verification receipts, corrections, forgetting | `record` after a task |

Each layer's retrieval is `off`, `shadow` (reports what it would add, changes nothing) or `on`. At
query time a deterministic gate labels every layer `use`, `use_limited` (may strengthen files source
retrieval found, never introduce one), `ignore_weak`, `ignore_stale`, `ignore_unresolved`,
`unavailable` or `budget_exhausted`, with a reason; the packet's `memory` section lists a few hits
with the current files they map to and a trust label. History can never make a withheld file
readable, `examine-commit` re-checks admission at read time, and a commit message or an experience
record is evidence, never an instruction or proof.

```bash
python3 -B repository_memory.py dry-run --project /path/to/project     # scope, bounds, writes nothing
python3 -B repository_memory.py build --project /path/to/project
python3 -B repository_memory.py explain 'TASK' --project /path/to/project
python3 -B repository_memory.py consolidate --project /path/to/project --task 'TASK'   # candidate claims from recorded experience; stores nothing
python3 -B repository_memory.py digest record --task-id T-1 --project /path/to/project --observation-file -   # explicit task-local digest
```

See the [repository memory guide](repository-memory.md) for settings, the evidence model,
storage, the experience contract, consolidation, working-memory digests, measurement and limits.

### Procedural learning

Off by default. When enabled in `~/.config/agent-dispatcher/procedural-learning.json` (or
`AGENT_DISPATCHER_LEARNING_CONFIG`; never a file inside the project), Dispatcher can attach explicit
observations to recorded task experience, review them for recurring patterns, and carry candidate
overlays (a repository procedure on a skill, an optional recipe step, a role method note, a bounded
retrieval profile, a verification scheduling hint) through validation, a paired evaluation against
the frozen incumbent and a human approval before they compose into packets. `shadow` mode reports
what would apply and changes nothing; `active` composes admitted overlays within a separate
added-guidance budget. No key, account or service is needed for the deterministic lifecycle.

```bash
python3 -B learning.py configure --enable --mode shadow --record-observations on
python3 -B learning.py status --project /path/to/project --json
python3 -B learning.py explain --task 'TASK' --role debugger --project /path/to/project
python3 -B learning.py review --project /path/to/project --packet
```

`/agent-learning` (Claude) and `$agent-dispatcher learning` (Codex) read the shared `LEARNING.md`
guide. See [procedural learning](procedural-learning.md) for the lifecycle, approval flow, budgets,
privacy controls and limits.

### Check health and get setup recommendations

In Codex:

```text
$agent-dispatcher doctor
$agent-dispatcher doctor all reviewer
$agent-dispatcher doctor mcps
$agent-dispatcher doctor setup
```

In Claude Code, use `/agent-doctor` with the same arguments, or
`/agent-dispatcher:agent-doctor` for a plugin install. `/agent-dispatcher doctor` also works.

The default checks the installation and goes through **all bundled guides, referenced external
skills, catalog MCPs, and additional skills/tools exposed in the current session**. Each entry
states what is usable, what connection has been verified, what needs setup, or what remains
unknown. It also checks activation and hook registration; a registered hook does not prove trust.
The full inventory is followed by a ranked shortlist of useful missing capabilities, with a
reason, source link, next step, and existing fallback. A role argument focuses recommendations
without hiding other inventory entries or changing your active role.

Doctor checks availability without loading every guide or calling every integration. It never
connects accounts, enables services, uses stored credentials, or changes permissions. A configured
server is not automatically connected; incomplete host discovery is reported as unknown.
Disabled and retired integrations are not recommended for activation.

For an offline local check from the source checkout:

```bash
python3 -B doctor.py --project /path/to/project --role reviewer
python3 -B doctor.py mcps --project /path/to/project --json
```

The standalone command cannot see a running agent's connections by itself. In-session commands
supply a sanitized observation snapshot using `--evidence`; see the
[doctor procedure and evidence format](../sources/shared/DOCTOR.template.md). JSON output is available for tooling.

### Activate automatically in future sessions

Automatic activation is opt-in. These commands manage the settings for you:

| Command | Effect |
| --- | --- |
| `/agent-dispatcher on here` | Activate in future sessions in this project. |
| `/agent-dispatcher on` | Activate in future sessions across projects. |
| `/agent-dispatcher off` | Stop routing for this session. |
| `/agent-dispatcher off here` | Silence this project, including when global activation is on. |
| `/agent-dispatcher off everywhere` | Disable global activation; individually armed projects remain armed. |
| `/agent-dispatcher status` | Show activation flags and whether the hook is installed. |

Claude project activation requires both a local flag and an allow-list entry in your Claude
config directory. Codex keeps its allow-list in your Codex config directory and ignores local
activation flags. Cloning a repository with an activation flag is not enough to enable the dispatcher.
Project and session silences take precedence over activation.

### Uninstall

For Codex, run from your clone:

```bash
python3 install_codex.py --uninstall
```

For a Claude plugin install:

```bash
claude plugin uninstall agent-dispatcher@agent-dispatcher
```

For a Claude manual install, run from your clone:

```bash
./install.sh --uninstall
```

The manual uninstaller removes the installed pack, its recorded commands, and its hook
registration. It leaves activation flags in place.

## Roles, skills, and permissions

A **role** owns the outcome. A **skill** supplies a reusable method. An **MCP server or tool**
provides a capability. A **recipe** suggests a workflow across roles. The context plan assembles
what the specialist needs before it plans the work.

Project signals such as `package.json`, `Dockerfile`, or `components.json` help select relevant
guidance. Missing skills or tools lead to documented fallbacks and explicit verification limits.
The build caps always-on skills at five and 30 KB per role.

These are instructions and validation rules, not a sandbox. **Authorization remains with the
user and the host's permission controls.** Detecting a stack, selecting a tool, or switching
roles does not grant permission to use it.

Verification is specific to the work: a bug fix needs the original reproduction and regression
evidence; a UI change needs rendered interaction checks when a browser is available. A review
of work produced in the same session is a self-check, even when another role performs it.
See [verification expectations](verification.md) and the
[context engine](context-engine.md).

## Optional decision engine

Your coding agent handles routing by default. The pack also includes an opt-in Jev integration for selecting
roles, skills, and tools from the catalog. **All Jev scopes ship disabled.** Normal use requires
no Jev account, key, or configuration.

Enabling Jev sends task text, candidate metadata, and relevant routing context to TypeSafe's API
using your own credential and billed usage. Task redaction is best-effort. See the
[Jev guide](jev.md) for setup, payload details, modes, and fallback behavior.

## Manual Claude Code installation

Run in your terminal:

```bash
git clone https://github.com/nahid-sparktales/agent-dispatcher.git
cd agent-dispatcher
./install.sh
```

The installer builds and validates the pack, copies its skills into
`~/.claude/skills/agent-dispatcher/`, adds role commands under `~/.claude/commands/`, and
registers a `SessionStart` hook. It backs up an existing `settings.json` before adding the hook
and skips command files it does not own. `CLAUDE_CONFIG_DIR` overrides the default config directory.

Updates are staged before live files are replaced. If a replacement fails, the installer
restores the previous pack, commands, hook, settings, and manifest. A failed staging check
leaves the installed version untouched. See [manual installer recovery](../adapters/claude-code/README.md#installing)
for the recovery limits.

Start a new Claude Code session and use the shorter command names:

```text
/agent-dispatcher Find why the tests are failing, fix the cause, and verify the fix.
/agent-dispatcher status
```

Use one installation method per host at a time to avoid duplicate commands and hooks.
