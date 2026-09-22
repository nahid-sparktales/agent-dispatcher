# Retrieval benchmark results

Measured on 2026-09-21 with `evals/retrieval/run.py` ([how to reproduce](../evals/retrieval/README.md)).
600 tasks from real changes: 150 each from sqlglot (parser/compiler), pip (application),
networkx (algorithm library) and zod (TypeScript). A task's query is the linked issue (106
tasks), else the pull-request description (329), else the commit message (165); its targets are
the non-test source files that change modified. Every task is evaluated at the parent commit of
the fix.

**Split discipline.** `sha256(task id) mod 10` assigns 60% train, 20% validation, 20% test.
Every tuning decision below was made on the train split. The test split was evaluated once,
after the configuration was frozen. "Development" is train + validation; it is not held-out
performance and is never reported as such. One task is about 0.2 points of a development
metric and 0.8 points of a held-out one, so differences under two points are noise.

This measures *file localization* and context size. It does not measure whether an agent then
solves the task.

## Headline

| | Split | R@1 | R@3 | R@5 | R@8 | R@10 | MRR | MAP | Context recall | ms / task |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `current` (flat scorer) | development (474) | .074 | .180 | .295 | .415 | .444 | .213 | .190 | .41 | 4,431 |
| `full` | development (474) | .343 | .556 | .643 | .720 | .739 | .549 | .504 | .74 | 71 |
| `current` (flat scorer) | **held-out (126)** | .070 | .181 | .287 | .368 | .403 | .206 | .185 | .37 | 4,839 |
| `full` | **held-out (126)** | .363 | .589 | .698 | .783 | .791 | .604 | .554 | .80 | 70 |

Held-out results are slightly above development for every strategy including the BM25 baseline,
so the held-out tasks are somewhat easier; there is no sign the tuning overfit.

### By repository (held-out, `current` -> `full`)

| Repository | Tasks | R@1 | R@5 | R@8 | MRR | Context recall |
| --- | --- | --- | --- | --- | --- | --- |
| sqlglot | 33 | .030 -> .334 | .237 -> .724 | .335 -> .785 | .133 -> .585 | .34 -> .80 |
| pip | 37 | .063 -> .240 | .219 -> .564 | .273 -> .688 | .177 -> .469 | .27 -> .73 |
| networkx | 30 | .175 -> .682 | .497 -> .893 | .580 -> .917 | .351 -> .855 | .58 -> .92 |
| zod (TypeScript) | 26 | .010 -> .205 | .205 -> .628 | .301 -> .763 | .173 -> .531 | .30 -> .76 |

Development shows the same ordering (R@8: sqlglot .315 -> .703, pip .237 -> .580, networkx
.577 -> .887, zod .513 -> .699). pip is the hardest: its issues describe behavior in user terms
and the fix often sits in a generically named module.

### By kind of query (held-out R@8, `current` -> `full`)

| Query | Tasks | R@8 | MRR |
| --- | --- | --- | --- |
| issue text | 19 | .263 -> .627 | .121 -> .569 |
| pull-request description | 77 | .380 -> .826 | .231 -> .645 |
| commit message | 30 | .406 -> .772 | .196 -> .520 |
| names a target file | 20 | .395 -> .804 | .256 -> .698 |
| names no target file | 106 | .363 -> .779 | .196 -> .586 |

Issue text, the closest thing to a real user request, is the hardest for both systems.

## What each component contributes

### Added one at a time

Each row adds one component to the row above. Rankings only change where R@k/MRR change;
`+context-optimizer` and `+explorer` rows share the ranking of `+rerank` up to rank 5.

| Step | Dev R@1 | Dev R@8 | Dev MRR | Held-out R@1 | Held-out R@8 | Held-out MRR | ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `current` | .074 | .415 | .213 | .070 | .368 | .206 | 4,431 |
| `bm25` (equal-weight request words) | .135 | .436 | .291 | .158 | .536 | .369 | 31 |
| `+query-analysis` | .197 | .583 | .390 | .221 | .671 | .448 | 42 |
| `+path` | .207 | .611 | .407 | .186 | .673 | .457 | 38 |
| `+rare-terms` (and quoted literals) | .244 | .646 | .447 | .230 | .685 | .487 | 59 |
| `+symbols` (definitions, references) | .290 | .659 | .492 | .309 | .681 | .557 | 68 |
| `+rrf` (replaces score sum) = `hybrid` | .299 | .661 | .494 | .293 | .718 | .553 | 68 |
| `+graph` = `hybrid+graph` | .268 | .657 | .472 | .261 | .710 | .522 | 77 |
| `+git` | .270 | .665 | .479 | .295 | .732 | .546 | 78 |
| `+rerank` (kind priors, pin named files, evidence ties) | .343 | .720 | .549 | .363 | .783 | .604 | 72 |
| `+context-optimizer` = `full` | .343 | .720 | .549 | .363 | .783 | .604 | 71 |
| `+explorer` (built-in, model-free) | .343 | .688 | .547 | .363 | .735 | .602 | 125 |

### Removed one at a time from `full`

Change in R@8 / MRR when exactly one component is removed (negative = the component helps).

| Removed | Dev R@8 | Dev MRR | Held-out R@8 | Held-out MRR | Reading |
| --- | --- | --- | --- | --- | --- |
| path retriever | -.058 | -.040 | -.055 | -.024 | the most valuable single retriever, and the one that finds the most targets nothing else finds |
| query analysis | -.058 | -.029 | -.037 | +.017 | large for recall; at rank 1 on held-out the plain word bag was as good |
| kind priors and pinning (`rerank`) | -.055 | -.070 | -.051 | -.058 | large: tests and docs otherwise outrank the implementation |
| rare-term retriever | -.044 | -.028 | -.042 | -.030 | clearly helps |
| RRF (use score sum instead) | -.022 | +.007 | -.034 | +.001 | RRF helps recall below the top ranks; at rank 1 the score sum is as good |
| symbol definitions | -.017 | -.054 | -.022 | -.035 | mostly improves the top ranks |
| BM25 | -.015 | -.024 | -.020 | -.030 | modest but consistent, even beside rare terms (their candidate lists share 38 of 50 files) |
| quoted literals | -.004 | -.020 | -.022 | -.008 | small |
| git co-change | -.002 | -.005 | -.020 | +.003 | neutral on development, a small recall gain on held-out |
| graph expansion | .000 | .000 | -.008 | +.005 | neutral: it adds about 10 candidates per task but almost never a target the retrievers missed |
| symbol references | +.001 | +.014 | +.001 | +.010 | **slightly harmful to ranking** on every split; kept because it supplies the "who uses it" excerpts and relationships, and flagged for down-weighting |
| `rrf_k` 60 instead of 20 | -.021 | -.023 | -.047 | -.027 | the customary k = 60 mostly counts lists; 20 is better everywhere |
| tie tolerance 0 instead of 0.05 | -.001 | -.001 | -.018 | -.011 | neutral to slightly helpful |

### Do the retrievers find different things?

Development split, 705 targets: how many each source ranked in its own top 10, and how many of
those no other source had in its top 10.

| Source | Targets in its top 10 | Found by it alone |
| --- | --- | --- |
| BM25 | 414 | 13 |
| rare terms | 381 | 3 |
| symbol definitions | 278 | 11 |
| path | 269 | 49 |
| git co-change | 225 | 9 |
| symbol references | 213 | 4 |
| quoted literals | 102 | 6 |
| graph expansion | 56 | 1 |

Mean shared candidates per task: BM25 and rare terms 38 of 50, BM25 and symbol references 26,
BM25 and path 10, path and symbol definitions 4. Graph expansion adds 10.7 new candidates per
task and git 2.8. Path is the complementary signal; BM25 and rare terms are largely redundant
as candidate generators even though removing either costs recall.

So, answering the questions this benchmark was built for:

- **Does symbol indexing help?** Definitions do, mainly at the top ranks (MRR +.035 to +.054). References do not improve ranking.
- **Does graph expansion help?** Not measurably for ranking on these repositories. It costs about 10 ms and 10 candidates per task. It is kept because it supplies the relationships shown in the packet and finds callers and tests for an agent, but the benchmark does not justify a larger role.
- **Does git history help?** Marginally (0 to +.02 R@8). As designed it never dominates.
- **Does BM25 add anything after path, rare terms and symbols?** A little (+.015 to +.020 R@8), despite heavy overlap with the rare-term list.
- **Does the explorer improve Recall@8?** The built-in, model-free explorer makes it worse (-.03 to -.05): what it inserts below the seeds displaces better candidates. Ranks 1-5 are protected and unchanged. It stays off by default; a model-driven explorer is untested here.
- **How much context does each feature add?** None: the packet is budget-bound. The optimizer raises useful context density from .10 to .13 (development) and .13 to .15 (held-out) at the same size and file recall.

Tuning tried on the train split and **not** adopted because it was within noise or worse:
per-retriever vote weights (path or definitions x1.5 and x2), graph weight 0.25-2, two graph
hops, 16 neighbors per seed, 10 seeds, imports as strong edges, git weight 1.0, git recency
half-life 180/365 days, git support 3, test prior 0.3/0.7, doc prior 0.3, no directory term in
the path retriever, tie tolerance 0.10/0.20.

## Context efficiency

Held-out means. `current` uses its standard tier (8 files, 6,000 excerpt tokens); `full` uses
10 files and 20 KB for the whole rendered packet. "Context recall" is the share of target files
present in what the agent receives.

| Configuration | Files | Bytes | Est. tokens | Useful context density | Context recall |
| --- | --- | --- | --- | --- | --- |
| `current` | 8.0 | 9,096 | 2,274 | .088 | .37 |
| `full` without the optimizer | 10.0 | 19,105 | 4,777 | .128 | .79 |
| `full` | 10.0 | 19,568 | 4,892 | .152 | .80 |
| `full`, 12 KB budget | 10.0 | 11,907 | 2,977 | .144 | .80 |
| `full`, 8 KB budget | 9.8 | 7,876 | 1,969 | .116 | .80 |
| `full`, 8 files | 8.0 | 18,488 | 4,622 | .184 | .79 |
| `full`, 5 files | 5.0 | 13,137 | 3,285 | .248 | .71 |

An 8 KB packet, smaller than what the flat scorer sends today, carries 2.2 times its target
files (.80 against .37): a tight budget shrinks every excerpt rather than dropping files. Useful
context density is low everywhere because a task has about 1.6 target files and a packet has
ten; five files double the density at a cost of nine points of context recall. Whether smaller
excerpts are *sufficient* for an agent cannot be measured offline.

## Cost

| | sqlglot (307 files) | networkx (942 files) |
| --- | --- | --- |
| Cold index build (nothing cached) | 0.97 s (+0.65 s scan) | 1.66 s (+1.08 s scan) |
| Warm build, all records reused | 80 ms (+39 ms scan) | 139 ms (+99 ms scan) |
| One file changed | 80 ms, 1 record recomputed | 135 ms, 1 record recomputed |
| Retrieval + context, short request | 10 ms | 20 ms |

Across the benchmark (long issue texts), retrieval plus context selection averaged 70 ms
(median 57 ms) against 4.4-4.8 s for the flat scorer, which rescans every file's lines per
request word. Records are cached only when the private parser cache is active (the map modes),
under the same write gate as before. From `evals/retrieval/perf.py`.

## Where localization still fails

Held-out, 204 targets, 53 missed at rank 8 (development, 705 targets, 242 missed, same shape):

| Stage | Held-out | Development | What it means |
| --- | --- | --- | --- |
| every retriever ranked it low | 24 | 86 | weak evidence everywhere: the request describes behavior, the file is generic |
| a retriever had it in its top 8, fusion lost it | 19 | 80 | most often the path retriever alone knew; correlated lexical lists outvoted it |
| no retriever found it at all | 4 | 54 | vocabulary mismatch between the request and the file |
| over the 256 KiB read limit, rankable by name only | 3 | 21 | sqlglot's `parser.py` (400 KB) and `generator.py` (270 KB) |
| skipped or unreadable | 3 | 1 | outside the scanned universe for every strategy |

Concrete patterns behind those numbers:

- **Giant central files that are the real answer.** sqlglot fixes often touch `parser.py` or
  `generator.py`. Their content is never read, so only their name, imports and history can rank
  them, and degree damping (deliberately) keeps a hub that everything imports from rising.
- **Issue text in user vocabulary.** A pip report that the "installation progress bar in CI is
  a bit verbose" was fixed in `_internal/network/session.py`, `utils/logging.py` and
  `utils/misc.py`. No identifier, path or rare term connects the request to any of them, and no
  retriever returned them at all.
- **Second and third targets.** R@1 rises fivefold but multi-file changes still lose their
  secondary files: structural and history evidence rarely lifts a file that no lexical
  retriever found.
- **Correlated voters.** BM25, rare terms and symbol references often agree because they read
  the same tokens, so one fact gets three votes and can outvote a single decisive path match.
- **Other languages know less.** zod has no call or inheritance edges; its gains come from
  query analysis, paths and lexical retrieval alone.

## Recommended next experiments

Each follows from a measured failure above, not from the feature list.

1. **De-correlate the lexical votes** (19 + 80 "fusion lost it" targets): fuse BM25, rare terms
   and references into one lexical channel before RRF, or halve the symbol-reference weight,
   which leave-one-out already suggests.
2. **Index oversized files by structure** (21 + 3 targets): read symbols and definitions of
   files over the limit without retaining their text, so central modules can be matched by
   symbol rather than by name only.
3. **Query reformulation for behavior-only requests** (54 + 4 "no retriever found it"): a
   model-written or docs-derived expansion from user vocabulary to code vocabulary, as an
   optional candidate retriever. This is the first failure class that deterministic lexical
   methods cannot reach, and the first place embeddings could earn their cost.
4. **Stack-trace-aware retrieval**: issue bodies frequently contain tracebacks whose frames name
   files; they are currently parsed only as ordinary paths.
5. **A model-driven explorer**: the contract and bounds exist; only the model-free explorer was
   measured, and it hurt.
6. **End-to-end check**: run the existing dispatcher-versus-stock suite with `--retrieval legacy`
   and `auto` to see whether better localization changes task success or token use.
