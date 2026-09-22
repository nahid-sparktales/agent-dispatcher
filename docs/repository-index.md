# Deep repository index, onboarding Explorer and task experience

This page covers the persistent layer behind `repository_intelligence.py`: an explicitly built,
incrementally maintained index of a repository, an optional model-backed onboarding Explorer that
writes evidence-backed architectural notes, and a store of task experience that later tasks may
draw on. Everything here sits behind the retrieval described in
[repository-intelligence.md](repository-intelligence.md) and the budgets in
[context-engine.md](context-engine.md); it does not replace either. Deep indexing requires an
explicit build, and the model-backed Explorer is off by default. Experience recording and
retrieval are enabled by default, but nothing is captured until a host or user explicitly
submits a record. Without an index or recorded experience, these layers add nothing to a packet.

```text
explicit onboarding        repository_intelligence.py build
  -> complete admitted inventory (no 10,000-path prefix), deterministic batches, checkpoints
  -> per-file records, symbols, relationships, corpus statistics, bounded HEAD history
  -> atomic publication in private state outside the working tree
  -> optional: repository_intelligence.py explore   (model, off by default)

each later task            context.py ... (as today)
  -> the scan runs as before; records whose fingerprint matches come from the index
  -> files the scan could not read are ranked after a metadata check and read lazily on selection
  -> optional eligible experience and current inferences vote as labeled retrievers
  -> the normal budgeted packet; authorized tasks upsert changed records within a small budget
  -> optional: repository_intelligence.py experience record ...   (explicit; a host hands over the receipts)
```

## Five switches, kept apart

| Capability | Where it is decided | Default |
| --- | --- | --- |
| Deep deterministic indexing | `repository_intelligence.py build` / `refresh`; used when `index.use` is `auto` and a published index exists | off until built |
| Onboarding Explorer (model) | `exploration.enabled` in the settings file, plus `repository_intelligence.py explore` | off |
| Query-time model reranking | unchanged: `llm-retrieval.json` ([llm-assisted-retrieval.md](llm-assisted-retrieval.md)) | off |
| Experience recording | `repository_memory.py record`, or the older `repository_intelligence.py experience record` (both explicit; one shared store) | memory command: on (`experience.recording` in `repository-memory.json`); older command: explicit writes |
| Experience use at query time | `experience.retrieval` in `repository-memory.json` (the unified memory layer; `experience.use` here is superseded) | on |

Index and Explorer settings live in `~/.config/agent-dispatcher/repository-intelligence.json`
(or the path in `AGENT_DISPATCHER_INDEX_CONFIG`); a file inside the inspected project is refused,
so repository content cannot enable model calls or override these controls:

```json
{
  "index": {"use": "auto", "maintain": {"enabled": true, "max_seconds": 10, "max_files": 500},
            "build": {"max_files": 50000, "max_admitted_bytes": 268435456, "batch_size": 200, "verify": "fast",
                      "history": {"max_commits": 5000, "max_commit_files": 30, "min_support": 2}}},
  "exploration": {"enabled": false, "provider": "openai", "base_url": "http://localhost:11434/v1", "model": "qwen3.6:27b",
                  "max_calls": 12, "max_iterations": 8, "max_evidence_bytes": 200000, "max_seconds": 600, "max_spend_usd": null}
}
```

`index.use` is `auto` (use a published index when one exists), `off`, or `require` (add a
diagnostic when none is usable). `--repository-index` on `context.py` overrides it per call.
Experience retrieval is controlled separately in `repository-memory.json`; the defaults are
`"experience": {"recording": true, "retrieval": "on"}`. Set `retrieval` to `"shadow"` to inspect
what existing records would contribute without changing rankings, or `"off"` to omit them.
The `recording` switch controls `repository_memory.py record`; the older explicit
`repository_intelligence.py experience record` command writes the same store directly.
See [repository memory](repository-memory.md) for the shared settings and lifecycle controls.

## Storage and trust

Two SQLite files (standard library, no server, no extension) live in the same owner-only private
directory as the project map and graph: `~/.cache/agent-dispatcher/state-v1/<project id>/`
(`repository-index.sqlite`, `experience.sqlite`), under an absolute `XDG_CACHE_HOME` when set.
Nothing is written into the inspected repository, and an in-tree `.agent-dispatcher/…` file is
never an authority. `repository_intelligence.py export` writes a sanitized JSON *document*; it is
not read back as state.

Why SQLite next to the HMAC-signed parser cache: the index has independently reusable layers
(inventory and fingerprints, per-file records, corpus term frequencies, symbols, edges, history,
inferences, experience) that must be updated in small transactions, must survive an interruption
with a resumable checkpoint, and must outgrow the parser cache's single 64 MiB blob and 12,000
entries. The parser cache keeps its contract: only it ever hands *redacted source text* back to a
scan, and it still requires the hardened metadata check.

The index store's trust model is narrower on purpose:

- It holds derived facts only, never source text. Every record is bound to the fingerprint of the
  source it came from. A reader uses a stored record only when the current scan reports that
  fingerprint; files beyond the scan's caps join the ranking only after their metadata signature
  matches, and their text is read on selection through the ordinary admission and redaction rules
  and compared with the stored fingerprint. A forged store can at worst perturb ranking: it cannot
  inject text into a packet, resurrect an excluded or deleted file, or authorize a read
  (`tests/test_repository_index.py`).
- Readers never combine generations. A build writes rows under a new generation number and flips
  it live in one statement; a reader sees the last published generation. An interrupted build
  leaves a `building` generation that `--resume` continues; a build stopped by its budget leaves the
  previous generation published and reports what is pending.
- Sweeping obsolete rows happens only after a complete enumeration and only for rows an older
  generation left behind. Batch upserts never delete. This is the difference from
  `repo_index.load_records`, which prunes shards against the paths it was given and must never be
  fed partial batches.
- Status and dry-run open the file read-only in rollback-journal mode: no directory, journal or
  side file is created. Writers use `BEGIN IMMEDIATE` with a bounded busy timeout; a locked,
  corrupt, incompatible or unpublished store is reported and the context helper falls back to its
  ordinary retrieval.
- The store is keyed by the project's resolved path, device and inode, like the parser cache, so
  branches checked out in separate worktrees never share an index. A harness may pass an explicit
  identity (`--identity NAME` or `AGENT_DISPATCHER_INDEX_ID`) to map successive temporary
  workspaces of one benchmark sequence to one store.
- Records are keyed by a policy fingerprint covering the extractor version, the redaction policy
  and the history settings. A package upgrade that changes extraction makes the index
  `incompatible`; the helper says so and `refresh` recomputes every record.

## One evidence model, four kinds of knowledge

`repo_store.provenance()` is the common shape: record id, kind, producer, method, version,
repository identity, path or stable symbol id, span, source fingerprint, supporting record ids,
snapshot (generation or commit), timestamp, status and invalidation reason; model records add
provider, model and prompt version. The `kind` says what a reader may make of a record:

| Kind | Examples | Label in explanations |
| --- | --- | --- |
| observation | a definition exists at a span; an import statement names a module; a commit touched an admitted path | repository fact |
| derived | a resolved import target; a call name that resolves to a unique definition (`candidate`); a test paired by name; a co-change score; a rename match | structural or statistical evidence, with method and status |
| inference | a subsystem responsibility written by the Explorer | "model inference, not a repository fact" |
| experience | files changed in an earlier checked task resembling this request | "experience, not a repository fact" |

Edges carry `method` and `status`: Python imports resolved by module path are `resolved`; calls,
references, inheritance and test links are `candidate` (an AST call name that resolves to one
definition still says nothing about the runtime target); names with several definitions are
counted as `ambiguous` and names without one as `unresolved` in the coverage report rather than
guessed. A Git rename is recorded with its similarity score; a symbol keeps an alias to its old
identity only when the content fingerprint matches, otherwise the link is `uncertain`. Symbol ids
come from language, path, qualified name, kind and order of appearance, never line numbers, and
location and content fingerprints are stored separately. Ranking scores are ordinal and a model's
confidence is stored as `uncertainty`; neither is a probability of correctness.

## Onboarding

```bash
python3 -B repository_intelligence.py build --project /path/to/project --json          # complete build
python3 -B repository_intelligence.py build --project /path/to/project --dry-run       # counts only; creates nothing
python3 -B repository_intelligence.py build --project /path/to/project --resume        # continue an interrupted generation
python3 -B repository_intelligence.py build --project /path/to/project --max-seconds 120 --batch-size 100 --strict
python3 -B repository_intelligence.py status --project /path/to/project --json         # read-only
```

The build enumerates every path Git (or ripgrep) lists, applies the same policy exclusions the
scan applies (credential names, vendor and generated directories, lock files, `.agent-dispatcher`),
and processes admitted files in deterministic batches: read through the helper's reader (symlink,
size and binary rules), redact, extract with `repo_index.file_record`, fingerprint, store. Limits
are explicit (`max_files`, `max_admitted_bytes`, `max_seconds`, `batch_size`) and separate from the
packet's display limits. The coverage report distinguishes `discovered`, `policy_excluded` (by
reason), `indexed`, `oversized` (inventory metadata only in this store), `binary`, `failed` (unreadable or unsafe),
`deleted_in_worktree`, `pending` (budget stopped the pass), `omitted` (over the file limit),
`unsupported_parser` (regex fallback only), per-language counts and per-top-level-directory
counts, and `complete_within_policy`. Complete within policy means every admitted file was
processed, not that every file in the repository was indexed. Files that changed while the build
ran are re-checked once and counted. Independently, the context scan can extract definitions,
imports and calls from admitted oversized files up to 4 MiB; their source text is not retained
or excerpted.

History is `git log` from `HEAD` only, never other refs, the reflog or dangling objects, bounded by
commit count, bytes and time, run through the hardened subprocess helper (no hooks, fsmonitor,
pager, external diff or textconv). Subjects are redacted and capped, authors are not read, paths
are reduced to the admitted universe before anything is stored, and rename evidence keeps the old
name only when the policy would have admitted it. The horizon (head, commit count, truncation,
shallow clone) is stored and reported. Co-change stays the normalized Jaccard score with support
counts, the bulk-commit guard and a partner cap. Symbol-level history and blame are not ingested;
history is file-level, and the report says so.

## Maintenance

```bash
python3 -B repository_intelligence.py refresh --project /path/to/project --json
python3 -B repository_intelligence.py refresh --project /path/to/project --strict     # re-hash every file's content
```

Refresh reconciles the working tree, not just `HEAD`: the inventory is enumerated again
(committed, staged, unstaged, untracked and newly ignored paths), each admitted path's metadata
signature (device, inode, size, mtime, ctime, mode, owner, links) is compared with the stored one,
and only files whose signature differs are re-hashed; identical content keeps its record and
symbols, changed content is re-extracted. `--strict` re-hashes everything and counts the bytes it
read; fast mode reports zero reads for a no-op refresh, and that is a metadata shortcut, not a
content verification. The snapshot semantics are explicit: working-tree content over `HEAD`; staged
but unsaved content is not indexed. A branch switch, rebase or non-ancestor `HEAD` rebuilds the
history; an ancestor `HEAD` appends the new commits; detached, unborn and shallow states are
recorded; without Git the index is source-only. Deleted tracked paths, renamed files and newly
excluded paths are swept after the complete enumeration. Relationships are then re-resolved over
every current record so a changed definition or module name retargets edges in files that did not
change; the cost is measured (`relationships_ms`, `edges_written`) rather than hidden. Stale
inferences (their evidence changed) are marked `stale` and omitted until the Explorer is run again;
a normal task never regenerates them.

`tests/test_repository_index.py` proves that an incremental sequence (edit, add, delete, rename,
strict pass) ends in the same records, symbols, edges, corpus statistics, partners and commits as
a clean build of the same final tree.

During an ordinary task, `context.py --map-maintain` performs bounded authorized maintenance under
the same write scope as the parser cache (a preview, a read-only role, a restriction in the
request or a `--writable-path` list that omits the logical target
`.agent-dispatcher/repository-index.sqlite` defers it): records the scan just computed for changed
files are upserted within `index.maintain.max_files` and `max_seconds`, their symbols replaced,
affected inferences invalidated. It never sweeps, never re-resolves edges and never publishes a new
generation; `refresh` does that. The packet reports what happened
(`repository_intelligence.index.maintenance`).

## Query-time integration

The context helper opens a published index when settings allow, in the normal `select_context`
flow, and reports it under `repository_intelligence.index`:

| Field | Meaning |
| --- | --- |
| `status` | `used`, `off`, `absent`, `unpublished`, `incompatible`, `unavailable` (locked or corrupt), `settings_invalid` |
| `coverage` | discovered, indexed, pending, failed, complete_within_policy, from the published generation |
| `head_match` | the stored history horizon is for the current `HEAD`, so co-change was reused without `git log` |
| `extended` | files beyond this scan's caps: candidates, verified by metadata, stale, pending (verification budget) |
| `inferences` | current inferences attached, omitted (cite a withheld path), stale, candidates ranked |
| `experience` | points to the unified report at `memory.layers.experience` |
| `maintenance` | allowed, records upserted, pending, edges_stale |
| `counters` | lazy reads, stale evidence rejected, history reused |

Within the scan's universe nothing changes: records come from the index instead of the parser
cache shards when their fingerprints match, and everything the retrievers, fusion, graph and
budget do is as documented. Beyond the universe, `extended` files are ranked from their stored
records and read only when selected; a file whose content no longer matches is withheld with the
reason `stale index evidence` and counted. Task exclusions filter stored evidence before ranking:
possessing a record never grants permission to expose it. Quoted-literal search covers only texts
the scan read, so the explain output is honest about which files it looked at.

Two retrievers can join the fusion when evidence is available, with default vote weights of 0.5
(like git co-change), candidate caps and no way to introduce a file the policy withheld:

- `experience`: the unified memory layer gates votes from earlier eligible tasks whose request
  resembles this one (cosine over analyzed terms, floor 0.2). They vote for the files they
  changed, weighted by outcome, recency (180-day
  half-life) and whether the file changed since (factor 0.5); a minimum support applies and the
  reason names the association and the count.
- `inference`: current Explorer claims whose text matches the request vote for the files they
  cite, split among them.

With nothing attached, `full+deep` ranks exactly like `full`. Setting `experience.retrieval` to
`off` in `repository-memory.json` removes experience votes without touching the event store.
The old `experience.use` setting no longer controls query-time use. The strategies `full+experience`,
`full+inference`, `full+deep`, `full+deep-experience` and `full+deep-inference` exist for ablation;
the shipped default strategy and its weights are unchanged, and the existing model-free explorer
and graph weights were not altered by this feature.

```bash
python3 -B context.py --project . --task 'TASK' --compact --map-maintain --json      # the normal call; the index is used if built
python3 -B context.py --project . --task 'TASK' --repository-index off               # skip the deep index; memory has separate controls
python3 -B repository_intelligence.py explain 'TASK' --project . --no-llm            # ranking with index provenance
```

## Onboarding Explorer

`repository_intelligence.py explore` asks a model bounded questions about the repository
(subsystems, entry points, persistence and authentication boundaries, processing stages, test
organization, dependency hubs, recent refactors) and stores what survives validation as
inferences. It is distinct from the model-free retrieval explorer (`--retrieval full+explorer`)
and from the per-file role summaries of `llm_retrieval.py`; the brief it starts from reuses the
deterministic index (subsystem counts, manifests, entry points by name, dependency hubs from
incoming edges, recent renames) and costs no model call.

The model may only request registered read-only operations, each validated by the coordinator
against the index: `search_symbols`, `search_files`, `snippet` (an exact indexed path and a span
capped at 60 lines, read through the scan's rules and fingerprint-checked), `relationships`,
`history`, and `investigate` (one bounded follow-up question). An invented path, symbol, commit or
operation name is rejected and never read; repeated requests are counted and end a question;
budgets cover iterations, operations, calls, retries, input tokens, output tokens, evidence bytes,
elapsed time and, when prices are known, spend (unknown prices stay unknown). Answers must be one
JSON object with claims, cited evidence ids, `confidence` (stored as `uncertainty`),
alternatives and unanswered questions; a claim without a valid citation is discarded. Source and
model output are untrusted data: evidence is delimited so it cannot close its own block, and the
system prompt says so. Evidence validation proves provenance only; the stored claim is still a
model inference and is labeled that way wherever it appears.

```bash
python3 -B repository_intelligence.py explore --project . --dry-run --json     # brief, questions, budget; no model
python3 -B repository_intelligence.py explore --project . --json              # only stale or unanswered questions
python3 -B repository_intelligence.py explore --project . --all               # every question again
python3 -B repository_intelligence.py inferences list --project . --status all
python3 -B repository_intelligence.py inferences forget --project . --stale
```

Disabled means zero model calls; a missing provider, failed validation, timeout, missing key or
exhausted budget ends the run with a diagnostic and never touches deterministic indexing or
retrieval. Tests use a Python callable as the provider; no transport is invented.

## Task experience

There is no observer. A host or harness records an event explicitly, handing over the lifecycle
artifacts that already exist: the context packet (retrieved files), the paths it inspected, the
edited files (a change-audit result, `git diff` against the baseline, or explicit paths) and the
verification receipt. The event keeps a sanitized task representation (analyzed terms, named
symbols and paths, a 240-character scrubbed summary), the role and configuration id, baseline and
final fingerprints, the file lists, a compact receipt summary (outcomes, freshness, counts), the
outcome category, the source (`explicit` or `harness`) and optional measured resource numbers.
Raw conversations, command output, credentials and author identities are never stored.

```bash
python3 -B repository_intelligence.py experience record --project . --task-id T-42 --task 'TASK' \
    --role implementer --packet packet.json --edited-from-git BASE --receipt receipt.json
python3 -B repository_intelligence.py experience record --project . --task-id T-43 --task 'TASK' --edited app/x.py --outcome accepted
python3 -B repository_intelligence.py experience list --project . --json
python3 -B repository_intelligence.py experience show EVENT --project .
python3 -B repository_intelligence.py experience correct EVENT --project . --path app/x.py --verdict irrelevant --note 'drive-by edit'
python3 -B repository_intelligence.py experience forget --project . --task T-42
```

| Outcome | Definition | Eligible by default |
| --- | --- | --- |
| `checked_success` | the receipt's last observed run is `tests_passed` and still `current` | yes |
| `accepted` | the user explicitly accepted the result | yes |
| `grader_passed` | an external harness grader passed the final state; a harness decides eligibility and says so | no |
| `exit_code_only`, `zero_tests`, `stale_checks` | a command exited 0 without a recognized summary, no tests ran, or files changed after the check | no |
| `failed_checks`, `unresolved`, `infrastructure_error`, `cancelled`, `insufficient_evidence`, `reverted_or_invalidated` | as named | no |

Associations are observed (`changed_in_checked_task`, `changed_in_accepted_task`,
`changed_in_task`, `user_correction`), never causal. An event id is the digest of task id, final
state and outcome, so repeated recordings of one outcome cannot inflate support. Corrections and
forgetting are recorded and every aggregate is recomputed from the surviving events at use time.
A file that no longer exists or is excluded from the current task never scores; a file whose
content changed since the event is down-weighted; retrieving or editing a file never raises its
weight on its own, because only eligible outcomes count. An optional exposure log records which
experience candidates were offered and kept (paths and a request hash only) for analysis.

## Evaluation

The four conditions are defined in [evals/retrieval/README.md](../evals/retrieval/README.md)
(offline, chronological, retrieval-only) and [evals/end_to_end/README.md](../evals/end_to_end/README.md)
(native clients). In short:

| Condition | Definition |
| --- | --- |
| stock | native client without Dispatcher |
| dispatcher basic | current shipped behavior, including its retrieval and index machinery, no deep index, no experience |
| dispatcher indexed | a deep index built at the sequence's first snapshot and refreshed at each later snapshot; experience recorded but not used |
| dispatcher warm-experience | exactly indexed, plus eligible experience from strictly earlier tasks of the same sequence |

The offline benchmark can only obtain experience from gold target files, which makes its
warm-experience arm an explicitly labeled oracle diagnostic. Live native-client sequences are
runnable but were not run for this change; nothing here reports a measured task-success gain.

## Limitations

- Coverage is bounded by the configured limits and the policy. The deep store keeps oversized
  files as inventory entries; the context scan can add bounded structural records but no excerpts.
  `unsupported_parser` counts files known only through the regex fallback.
- Static relationships are candidates: an AST call name is not a runtime target, a test import is
  not coverage, a rename is a similarity match.
- History is file-level from `HEAD`; blame and symbol-level history are not ingested.
- Relationships are re-resolved globally on refresh; that is measured, not incremental.
- Experience capture is explicit; hosts that do not expose inspected-file lists record fewer
  fields. Its retriever's weights are uncalibrated and its scores are not probabilities.
- Inferences are model output validated for provenance only.
