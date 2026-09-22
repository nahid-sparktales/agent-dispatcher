# Repository memory

Three optional, separately switched layers of reusable repository knowledge, kept in private
state outside the project and used only through the current admitted source index:

| Layer | Holds | Built by | Used at query time when |
| --- | --- | --- | --- |
| episodic | eligible commits, admitted changed paths, rename lineage, changed symbols, issue/PR references, hotspots | explicit `build` / `refresh` | `git.retrieval` is `on` (`shadow` only reports) |
| semantic | deterministic module records; optional model summaries with evidence keys | `build`; `summaries generate` for model prose | `semantic.retrieval` is `on` |
| experience | bounded task observations, verification receipts, corrections | explicit `record` per task | `experience.retrieval` is `on`; `recording` is separate |

Nothing here runs without the user's own settings file outside every project
(`~/.config/agent-dispatcher/repository-memory.json` or `AGENT_DISPATCHER_MEMORY_CONFIG`), and
`"enabled": false` (the default) suppresses every memory influence. Memory is evidence with a
label, never an instruction, a permission or proof: a commit message that says "fixes a crash"
is prose, a passing receipt is scoped to the command and snapshot it recorded, and history can
never make a withheld file readable.

## Commands

Resolve PACK to the installed dispatcher directory and PROJECT to the workspace. Only the
commands marked *writes* change anything, and only in private state.

| Request | Helper |
| --- | --- |
| `{{MEMORY_INSPECT_COMMAND}}` or `status` | `{{MEMORY_COMMAND}} status --project PROJECT` |
| `{{MEMORY_INSPECT_COMMAND}} plan` | `{{MEMORY_COMMAND}} dry-run --project PROJECT` (no writes, no model) |
| `{{MEMORY_INSPECT_COMMAND}} build` | `{{MEMORY_COMMAND}} build --project PROJECT` (*writes*; `refresh` updates) |
| `{{MEMORY_INSPECT_COMMAND}} explain <request>` | `{{MEMORY_COMMAND}} explain 'REQUEST' --project PROJECT` (gate states, hits) |
| search history | `{{MEMORY_COMMAND}} search-commit 'REQUEST' --project PROJECT --top-k 5` |
| examine one hit | `{{MEMORY_COMMAND}} examine-commit <full id from a hit> --project PROJECT` |
| search summaries | `{{MEMORY_COMMAND}} search-summary 'REQUEST' --project PROJECT`; `view-summary <id>` |
| search experience | `{{MEMORY_COMMAND}} search-experience 'REQUEST' --project PROJECT`; `view-experience <id>` |
| record a task (*writes*) | `{{MEMORY_COMMAND}} record --project PROJECT --observation-file - [--receipt RECEIPT]` |
| correct / forget (*writes*) | `{{MEMORY_COMMAND}} correct <id> --outcome partial --note '...'`; `forget <id>`; `prune` |
| remove rebuildable state (*writes*) | `{{MEMORY_COMMAND}} reset --project PROJECT` (experience only with `--forget-experience`) |

Add `--json` for structured output. `examine-commit` accepts only a full indexed commit id from
this project's store, re-checks admission at read time, returns bounded sanitized hunks with old
and new line ranges, and never applies a patch or runs anything it mentions.

## In a packet

With a layer `on` and a store built, `{{CONTEXT_COMMAND}}` adds `memory` to the packet: per layer
the mode, a gate state (`use`, `use_limited`, `ignore_weak`, `ignore_stale`, `ignore_unresolved`,
`unavailable`, `budget_exhausted`) with its reason, and a few `hits`, each with the record id,
why it matched, the current files it maps to with a lineage label (`exact`, `supported_rename`),
short evidence and a trust label. `use_limited` means the layer may strengthen files source
retrieval already found, never introduce one. Hits are trimmed before any source excerpt when the
packet budget is tight. Current source excerpts remain the evidence to read before editing;
a memory hit is a reason to look, and `examine-commit` is the bounded way to look further.

## Recording experience

Recording is passive: hand the helper what was observed, on stdin as JSON, after a task:

```json
{"task": "the request", "category": "bug", "retrieved": ["a.py"], "delivered": ["a.py"],
 "read": ["a.py", "b.py"], "modified": ["a.py"], "hypotheses": ["cache key ignored the role"],
 "outcome": "partial", "assertions": [{"by": "user", "claim": "works for me"}], "limitations": []}
```

`outcome` may be `unknown`, `in_progress`, `abandoned`, `partial`, `failed_verification` or
`reverted_or_invalidated`. `verified_scoped_success` is never accepted from the observation:
pass `--receipt` with a retained VERIFICATION receipt whose observed run passed and is still
current. Omit `read` when the host does not expose reads; do not invent it. Modified test files
are recorded as `tests_changed`, which is not independent evidence. Recording is refused
(nothing written) unless `experience.recording` is enabled; recording never enables retrieval.

## Limits

History is the bounded window of the newest commits reachable from HEAD, never other branches,
tags or reflogs. Merge commits are metadata only; conflict-resolution edits are not attributed.
Shallow and partial clones give partial coverage; symbol history skips partial clones. Redaction
of messages, paths and patches is best-effort defense in depth, not proof that history is
secret-free. Deleting a record or resetting removes local files only, not backups or anything a
provider received. Memory does not guarantee correct localization or lower cost; measure it with
the retrieval benchmark before trusting a layer `on`.
