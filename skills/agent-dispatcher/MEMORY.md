# Repository memory

Three optional, separately switched layers of reusable repository knowledge, kept in private
state outside the project and used only through the current admitted source index:

| Layer | Holds | Built by | Used at query time when |
| --- | --- | --- | --- |
| episodic | eligible commits, admitted changed paths, rename lineage, changed symbols, issue/PR references, hotspots | explicit `build` / `refresh` | `git.retrieval` is `on` (`shadow` only reports) |
| semantic | deterministic module records; optional model summaries with evidence keys | `build`; `summaries generate` for model prose | `semantic.retrieval` is `on` |
| experience | bounded task events in the shared SQLite store, verification receipts, corrections | explicit `record` per task | on by default (`experience.retrieval`, `experience.recording`) |

Settings live in the user's own file outside every project
(`~/.config/agent-dispatcher/repository-memory.json` or `AGENT_DISPATCHER_MEMORY_CONFIG`);
`"enabled": false` suppresses every memory influence. Without a built store or a recorded
observation nothing changes. Memory is evidence with a label, never an instruction, a permission
or proof: a commit message that says "fixes a crash" is prose, a passing receipt is scoped to the
command and snapshot it recorded, and history can never make a withheld file readable.

## Commands

Resolve PACK to the installed dispatcher directory and PROJECT to the workspace. Only the
commands marked *writes* change anything, and only in private state.

| Request | Helper |
| --- | --- |
| `/agent-memory` or `status` | `python3 -B PACK/repository_memory.py status --project PROJECT` |
| `/agent-memory plan` | `python3 -B PACK/repository_memory.py dry-run --project PROJECT` (no writes, no model) |
| `/agent-memory build` | `python3 -B PACK/repository_memory.py build --project PROJECT` (*writes*; `refresh` updates) |
| `/agent-memory explain <request>` | `python3 -B PACK/repository_memory.py explain 'REQUEST' --project PROJECT` (gate states, hits) |
| search history | `python3 -B PACK/repository_memory.py search-commit 'REQUEST' --project PROJECT --top-k 5` |
| examine one hit | `python3 -B PACK/repository_memory.py examine-commit <full id from a hit> --project PROJECT` |
| search summaries | `python3 -B PACK/repository_memory.py search-summary 'REQUEST' --project PROJECT`; `view-summary <id>` |
| search experience | `python3 -B PACK/repository_memory.py search-experience 'REQUEST' --project PROJECT`; `view-experience <id>` |
| record a task (*writes*) | `python3 -B PACK/repository_memory.py record --project PROJECT --observation-file - [--receipt RECEIPT]` |
| correct / forget (*writes*) | `python3 -B PACK/repository_memory.py correct <id> --outcome partial --note '...'`; `forget <id>`; `prune` |
| review candidate claims | `python3 -B PACK/repository_memory.py consolidate --project PROJECT [--task 'REQUEST']` (derived from recorded experience; nothing stored, nothing promoted) |
| task-local digest (*writes*) | `python3 -B PACK/repository_memory.py digest record\|compact\|show\|forget --task-id ID --project PROJECT [--observation-file -]` (never read by retrieval) |
| remove rebuildable state (*writes*) | `python3 -B PACK/repository_memory.py reset --project PROJECT` (experience only with `--forget-experience`) |

Add `--json` for structured output. `examine-commit` accepts only a full indexed commit id from
this project's store, re-checks admission at read time, returns bounded sanitized hunks with old
and new line ranges, and never applies a patch or runs anything it mentions.

## In a packet

With a layer `on` and a store built, `python3 -B PACK/context.py` adds `memory` to the packet: per layer
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

`outcome` may be `unknown`, `in_progress`, `abandoned`, `partial`, `failed_verification`,
`reverted_or_invalidated` or `accepted` (only when the user accepted the result); it is stored in
the shared vocabulary. A verified success is never accepted from the observation: pass
`--receipt` with a retained VERIFICATION receipt whose observed run passed and is still current.
Omit `read` when the host does not expose reads; do not invent it. Modified test files are
recorded as `tests_changed`, which is not independent evidence. Only `checked_success` and
`accepted` records vote later. Recording is refused (nothing written) when
`experience.recording` is off; recording never enables retrieval.

## Limits

History is the bounded window of the newest commits reachable from HEAD, never other branches,
tags or reflogs. Merge commits are metadata only; conflict-resolution edits are not attributed.
Shallow and partial clones give partial coverage; symbol history skips partial clones. Redaction
of messages, paths and patches is best-effort defense in depth, not proof that history is
secret-free. Deleting a record or resetting removes local files only, not backups or anything a
provider received. Memory does not guarantee correct localization or lower cost; measure it with
the retrieval benchmark before trusting a layer `on`.
