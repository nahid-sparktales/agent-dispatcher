# Repository memory (optional)

Agent Dispatcher can build reusable repository knowledge on purpose, retrieve a small amount of it
safely, and decline it when it does not help. Three layers, each with its own build, retrieval and
recording controls:

| Layer | Records | Built by | Retrieval mode |
| --- | --- | --- | --- |
| **Episodic** (`repo_history.py`) | eligible commits with admitted changed paths, old/new blob ids, rename evidence, changed symbols, issue/PR references, hotspots, co-change support | explicit `build` / `refresh` | `git.retrieval`: `off`, `shadow` (default), `on` |
| **Semantic** (`repository_memory.py`) | deterministic module and repository records with evidence manifests; optional model summaries keyed to their evidence | `build`; `summaries generate` for model prose | `semantic.retrieval`: `off`, `shadow` (default), `on` |
| **Experience** (`memory_experience.py`) | bounded task observations, verification receipts, corrections, forgetting | explicit `record` per task | `experience.recording` (off) and `experience.retrieval` (`off` default) |

Everything ships **off**. Nothing is read, written or influenced until the user's own settings
file exists outside every project, and `"enabled": false` (the default) suppresses every memory
influence while leaving baseline retrieval, including the pre-existing Git co-change signal,
untouched. With memory off, packets are byte-for-byte what they were before this feature.

The design takes RepoMem (*Improving Code Localization with Repository Memory*, Wang et al.,
ICLR 2026, [arXiv:2510.01003](https://arxiv.org/abs/2510.01003)) as motivation for commit memory
and hotspot summaries. Its reported gains are not a promise for this implementation; every layer
here is measured separately with [the retrieval benchmark](retrieval-benchmark.md), and the
experience layer starts in shadow mode until a measurement says otherwise.

```text
explicit build / refresh                                  query time (context.py, retrieval.py explain)
  current admitted index (context._scan_sources)            request -> query analysis
  eligible history: HEAD's ancestry, bounded window          source retrievers -> fusion (unchanged)
    events, admitted changes, references, reverts, merges     memory layers, each: search -> current-file
    symbol history (Python AST, bounded blob reads)             resolution -> gate state -> bounded candidates
    lineage (renames), hotspots, co-change support            `use`: one more voter   `use_limited`: boost only
  semantic module records (+ optional model prose)           `ignore_*`, `unavailable`: nothing enters
  private, validated, atomically published state             packet: `memory` section, trimmed before excerpts
```

## Turning it on

`~/.config/agent-dispatcher/repository-memory.json` (or the path in `AGENT_DISPATCHER_MEMORY_CONFIG`;
an absolute `XDG_CONFIG_HOME` moves the default). A file inside the inspected project is refused.

```json
{
  "enabled": true,
  "git": {"retrieval": "on", "max_commits": 2000, "fields": ["message", "paths", "identifiers", "symbols"],
          "symbols": {"enabled": true, "max_commits": 300}},
  "semantic": {"retrieval": "shadow", "generation": {"enabled": false}},
  "experience": {"recording": true, "retrieval": "off"},
  "retrieval": {"rrf_weights": {"memory_git": 0.5, "memory_semantic": 0.5, "memory_experience": 0.5},
                "max_events": 10, "max_files_per_event": 8, "file_affinity": 1.0,
                "gate": {"min_concept_matches": 2, "min_relative_score": 0.25,
                         "support_fields": ["message", "paths", "identifiers", "symbols"]}}
}
```

Every key has a default in `repository_memory.DEFAULTS`. `shadow` computes and reports what a
layer would have contributed without changing any ranking; it is how a layer earns `on`.

```bash
python3 -B repository_memory.py dry-run --project .         # scope, existing coverage, bounds, planned provider use; writes nothing
python3 -B repository_memory.py build --project .           # events, symbols, lineage, hotspots, module records -> private state
python3 -B repository_memory.py refresh --project .         # fast-forward additions; rewritten history or a policy change rebuilds
python3 -B repository_memory.py status --project . --json   # freshness and completeness per layer, storage, pending work
python3 -B repository_memory.py explain 'TASK' --project .  # gate state and hits per layer for one request
python3 -B repository_memory.py search-commit 'TASK' --project . --top-k 5
python3 -B repository_memory.py examine-commit <full id> --project . --max-hunks 6
python3 -B repository_memory.py search-summary 'TASK' --project . --level module
python3 -B repository_memory.py summaries generate --project .          # model prose for hotspot modules; explicit, resumable
python3 -B repository_memory.py record --project . --observation-file - [--receipt RECEIPT]
python3 -B repository_memory.py correct <record> --outcome partial --note '...' ; forget <record> ; prune --max-age-days 90
python3 -B repository_memory.py reset --project . [--forget-experience]
python3 -B retrieval.py explain 'TASK' --project . --verbose     # MEMORY section next to every other retriever
python3 -B context.py --project . --task 'TASK' --compact --json  # packet with a `memory` section when a layer is on
```

The `/agent-memory` command (Claude) and `$agent-dispatcher memory` (Codex) read `MEMORY.md`,
the shared guide installed beside the helpers.

## What a record is, and is not

Records carry an explicit evidence model. Direct observations (a commit touched these admitted
paths, these blob ids, this parsed declaration span) are kept apart from derived observations
(diff-to-symbol overlap, Jaccard co-change, hotspot features), from model interpretations (module
summaries, `confidence_label: interpretation`) and from experience assertions (who reported what,
with the verification source). A commit message saying "fixes a crash" is prose. An owner-only,
validated store file proves local origin, not the truth of anything in it.

Identity: the store is keyed by the project's resolved path, device and inode (the same private
state directory as the project map), so two clones never share memory; a repository URL, a
directory name or a commit hash alone never selects a namespace. Each store records its history
boundary (the exact commit), whether that boundary's own commit is included, the object format,
the window, a policy digest (redaction, skip rules, schema versions), the admitted-universe digest
and the stage status. Line numbers are locators; historical symbols are versioned by blob id;
current candidates are re-resolved against the present admitted index on every query.

## Episodic memory

**Eligibility.** One service (`repo_history.repository` + `enumerate_events`) resolves HEAD to an
immutable commit once per operation and enumerates only that commit's ancestry, newest first,
bounded by `git.max_commits`; never `--all`, reflogs, tags or an object id a caller knows.
Timestamps are recorded but decide nothing: a commit with a 2001 date at the tip is still the
newest event. `git.boundary: exclusive` drops the boundary's own event (the paper-style
"prior to base commit" window used by the benchmark). Detached HEAD works; an unborn or non-Git
directory yields a store with no events and a layer state of `unavailable`; shallow and partial
clones are recorded as such and symbol history is skipped for partial clones (no lazy fetch).

**The Git wrapper.** Argument arrays; `GIT_*` environment dropped; `GIT_OPTIONAL_LOCKS=0`,
`GIT_TERMINAL_PROMPT=0`, `GIT_NO_LAZY_FETCH=1` (Git 2.46+; older versions ignore it, which is why
partial clones skip blob reads); `--no-replace-objects`; `core.pager=cat`, `diff.external=`,
`--no-ext-diff --no-textconv`, `protocol.allow=never`; per-call byte and time limits with the
child killed at the limit; NUL-framed `git log --raw -z` output parsed field by field, with any
record that breaks the frame dropped and counted rather than guessed. `tests/test_repository_memory.py`
sets `diff.external`, `core.pager`, a `textconv` filter and `GIT_EXTERNAL_DIFF` to a script that
would leave a marker and checks that build, search and examine never run it.

**Admission.** Historical paths pass the same rules as current source: credential names,
generated and dependency directories, plus the task's exclusions. Both sides of a change must be
admitted before a blob id is kept, so a credential file renamed to a harmless name stays
withheld (count only, never the name). Messages lose e-mail addresses and identity trailers, go
through the shared credential redaction, and are bounded (200-character subject, 1,500-character
body). Blob text goes through the same redaction as current source before it is parsed or shown.
A query with narrower exclusions gets a projected view: excluded changes, symbols and lineage
entries are removed, and an event whose message names an excluded path is omitted, before any
scoring happens.

**Events.** Commit id, parents, times, sanitized subject/body, admitted changes (`kind`, historical
path, old/new blob ids, rename source and similarity), withheld and omitted counts, merge/bulk/
release flags, `revert_of`, references (`pr #12 (squashed)`, `issue #7 (declares_fix)`,
`mentions`), completeness (`full`, `metadata_only`, `truncated`). Merge commits are metadata-only
by policy: their first-parent diff would repeat the non-merge commits that are indexed
individually, so a logical change is attributed once; conflict-resolution edits inside a merge
are therefore not attributed (documented limitation). A revert and its target form one
provenance group and vote once.

**Symbol history.** For the newest `git.symbols.max_commits` non-merge, non-bulk events with
Python changes, both blob versions are read (size-checked first, content-addressed within a
build), parsed independently, and the changed line ranges are intersected with definition spans
including decorators. A definition owns its span minus nested definitions, so a hunk inside one
method marks that method, not its class or sibling methods; a line shift above a function is not
a change to it. Qualified names keep `A.run` and `B.run` apart. Other languages fall back to
declaration lines with `confidence: heuristic`; a file the redaction made unparsable reports
`parse_error`; a partial clone reports `unavailable`. Budgets: files per commit, bytes per blob,
total parsed bytes; exhausted budgets leave file-level history in place.

**Lineage.** `exact` (the path exists now), `supported_rename` (one chain of renames with
similarity at least 50 reaches a current path), `ambiguous` (copies, diverging chains, weak
similarity) or `unresolved` (deleted, or renamed outside the window). Ambiguous and unresolved
entries never contribute a candidate. Historical-only paths are never current edit targets.

**Hotspots.** Explainable normalized features over eligible events resolved to current files:
log-scaled edits, boundary-relative recency (by position in the window, not the clock), explicit
fix participation (heuristic, labeled), distinct incident references, changed-symbol diversity
(left out of a file's average when unknown), co-change support, and a penalty for release-only or
bulk participation. Diversified selection applies a per-directory cap and reserves slots for
high in-degree entry points and uncovered top-level modules; `hotspots.selector: frequency`
keeps the raw edit count as an ablation. Hotspots order summarization effort; they never restrict
what is searchable.

**Search and gate.** `SearchCommit` is BM25 over independently switchable fields (`message`,
`paths`, `identifiers`, `symbols`; a commit-message-only baseline is `["message"]`), events
first, then files: each strong event maps its admitted changes to current files through the
lineage with bounded fan-out (`max_files_per_event`), ordered and weighted by each file's own
affinity to the request (request terms and named symbols present in the current file, scaled by
`file_affinity`), so a ten-file commit does not hand every file the same vote; a bulk event
contributes at 30%, a distant runner-up (below `min_relative_score` of the leader) neither votes
nor appears. `gate.support_fields` says which fields may count as identifier-level support (a
request word that is only a directory name is weaker evidence than a symbol in the message). The gate returns one of
`use`, `use_limited`, `ignore_weak`, `ignore_stale`, `ignore_unresolved`, `unavailable`,
`budget_exhausted` with a reason: identifier-level support that resolves to current admitted
files is `use` (one more RRF voter at `retrieval.rrf_weights.memory_git`); concept-only or
rename-only support is `use_limited` (it may strengthen files source retrieval found, never
introduce one); a store whose boundary is not an ancestor of HEAD, or built under another policy,
is `ignore_stale`; a store behind HEAD is still used, and `status` reports by how many commits.
Raw scores are never compared across layers, and none of them is a probability.

**Examine.** `ExamineCommit` takes only a full commit id that is an indexed eligible event of this
store and reachable from the current boundary; revision expressions, options, foreign or future
ids are rejected. It re-runs admission at read time, reads only admitted blobs (size-checked),
diffs them with `difflib` (no external diff), returns bounded sanitized hunks with old and new
line ranges, the current path and mapping label per file, changed symbols (computed on demand
within the read budget), references without bodies, and truncation/unavailable markers. No
persistent patch cache exists; every view is recomputed under the current policy.

## Semantic memory

`build` derives one deterministic record per directory (files, defined symbols, tests, in-degree,
hotspot score, a manifest of file fingerprints) plus a repository record listing modules. These
are navigation aids with `confidence_label: derived`. `summaries generate` (explicit, resumable,
bounded by `generation.max_calls` and `max_modules`, hotspot order first) asks the provider from
your [LLM retrieval settings](llm-assisted-retrieval.md) for module prose; the answer is
schema-validated, `entities` must be symbols the module defines and `interactions` must be module
paths in the index, and the prose is stored with an evidence key over the child fingerprints,
prompt version and provider/model. On `refresh`, prose whose key no longer matches is marked
`stale` and leaves the retriever; unchanged evidence is never regenerated. Query time never
generates a summary. Retrieval is BM25 over record text with member files entering once each
(best-matching members first); a file found through its module and through its own role summary
is one vote, not two.

## Experience memory

An observation is what a host or user hands to `record` after a task: request text, category,
retrieved/delivered/read/modified paths (`read` may be `null` when the host cannot observe reads;
it is never invented), hypotheses, assertions with their author, limitations, an asserted
outcome, and optionally a `--receipt`. Paths are admitted through the same policy and withheld
ones are counted, not named. Outcomes are `unknown`, `in_progress`, `abandoned`, `partial`,
`failed_verification`, `verified_scoped_success`, `reverted_or_invalidated`;
`verified_scoped_success` is reachable only from a [verification receipt](verification.md) whose
observed run reported passing tests and is still current for the snapshot; a stale receipt is
`partial`, a failed run is `failed_verification`, and "42 tests passed" in an assertion stays an
assertion. Modified test files set `tests_changed`, which is recorded as not independent
evidence. Fingerprints of modified files bind a record to its snapshot; at retrieval a record whose
files changed is `changed` and can only strengthen, never introduce.

Corrections are new records that supersede the old one (which keeps its original outcome and a
`superseded_by` pointer); a reverted or failed record is listed as caution and never votes for a
file. Duplicate tasks are one provenance group with one vote. `forget` removes a record and the
corrections that superseded it; `prune` applies age and count limits; `reset` never touches
experience unless asked. All of this is logical deletion in a local file, not secure erasure.
Experience is per project; nothing distills it into skills, instructions or other repositories.

## Packet contract

```json
"memory": {"status": "used",
  "history": {"boundary": "3de9d02f7951", "events": 82, "freshness": "current", "behind_by": 0},
  "layers": {"git": {"mode": "on", "state": "use", "reason": "identifier-level support resolves to current admitted files", "applied": true, "candidates": 12, "matches": 4},
             "semantic": {"mode": "shadow", "state": "use_limited", "reason": "...", "applied": false},
             "experience": {"mode": "off", "state": "unavailable", "reason": "layer is off", "applied": false}},
  "hits": [{"kind": "commit", "id": "<full id>", "why": "matched packet, fit_packet", "files": ["context_packet.py (exact)"],
            "evidence": "context: keep the compact packet under ...", "label": "observation", "applied": true, "refs": []}]}
```

Hits are bounded (`retrieval.max_packet_hits`, `max_hit_chars`) and accounted inside the packet
budget under `repository_memory`; `fit_packet` trims them before any source excerpt. `retrieval.py
explain` shows the same layers under `MEMORY`, and every memory candidate appears as ordinary
evidence (`memory_git rank #3: changed in eligible commit ...`) next to the deterministic sources.

## Storage, integrity and migration

Stores live in the project's private state directory (`~/.cache/agent-dispatcher/state-v1/<id>/`,
under an absolute `XDG_CACHE_HOME`) as `repository-memory.json`, `memory-semantic.json` and
`memory-experience.json`, written through the project map's helper: owner-only directory, 0600
files, schema validation on every read, atomic publication, a concurrent-change check on save,
size limits (24, 8 and 8 MiB). Nothing is created in the working tree, and nothing inside the
project is read as memory state. Malformed, oversized, symlinked or foreign state is ignored with
a diagnostic and rebuilt on the next `build`; the experience file is never rewritten by a cache
rebuild. There is no HMAC on these files: they hold derived facts and the user's own records,
never source text, and every candidate they yield must resolve to a file the current admitted
index contains, so a forged store can at most reorder. A schema bump makes old files invalid,
which `status` reports and `build` replaces. Read-only commands (`status`, `dry-run`, searches,
`explain`, packets) create no files.

## Cost and budgets

`dry-run` reports the eligible commit count, the window, symbol-history bounds and, for semantic
generation, the planned call count with an unknown price (no provider price is assumed). Build
cost on this repository (82 commits, 672 files): about 4 s including symbol history for 40
commits; the store is 0.6 MB. Query-time cost is a BM25 pass over the events plus one
`merge-base` call for freshness, a few milliseconds, reported as `memory_ms` in `--explain`
telemetry. Symbol enrichment is bounded per build and resumable; `git.symbols.enabled: false`
keeps file-level history only.

## Measuring it

`evals/retrieval/run.py --memory` builds the episodic store in memory at each task's base commit
(boundary excluded, so the fix never leaks) and evaluates `full+memory` (gated), `full+memory-forced`
(gate open) and `full+memory-messages` (commit-message field only) beside `full`, reporting
Recall@k, Hit@k, AllTargets@k (RepoMem's Accuracy@k), MRR, strata by target count, and memory
hit/use rates. `evals/retrieval/chronology.py` replays one repository's tasks in commit order with
memory pinned before each task and an oracle-labeled experience arm, reporting per block with
paired-bootstrap intervals and leakage checks. Results and their limits are in
[retrieval-benchmark.md](retrieval-benchmark.md#repository-memory). End-to-end runs with a host
model are separate, paid experiments (`evals/end_to_end`, `memory_settings`).

## Limits

- History is a bounded window of HEAD's ancestry; other branches, tags and reflogs are outside it.
- Merge commits are metadata only; conflict-resolution edits are not attributed.
- Redaction is best-effort defense in depth. Do not treat a store as proof that history is secret-free.
- Symbol history covers Python precisely; other languages use declaration heuristics.
- Issue and PR bodies are never fetched; only references found in commit messages are stored.
- Subsystems are directories; there is no inferred architecture beyond module aggregates.
- Experience records are only as good as the observations handed in; hosts that cannot observe reads leave `read` null.
- Deletion and reset are local logical deletions.
- Memory does not guarantee better localization, lower cost or improvement on any future task; the benchmark makes that measurable per layer.
