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

## Project map task view

Measured on 2026-09-22 with `run.py --strategy full --map` on the development split (474 tasks).
The context packet carries an eight-fact view of the project map beside the excerpts. Before this
change the view re-ranked the map's facts by counting request words as substrings of each fact; now
the context selector hands it the retrieval ranking with excerpted files last, one fact per file.
`hit` is the share of target files among the view's files, `gain` the share that the excerpts of
`full` missed but the view names, `packet` the share in the excerpts or the view (the excerpts
alone reach .74, the context recall above). The view exists to add files, so `gain` and `packet`
are the numbers that matter; a high `hit` on already-excerpted files would only repeat them.

| Repo (dev) | targets with a fact | `hit` before -> after | `gain` before -> after | `packet` before -> after | facts per map |
| --- | --- | --- | --- | --- | --- |
| all (474) | .87 | .27 -> .09 | .02 -> .05 | .76 -> .79 | 1,503 -> 774 |
| networkx (120) | 1.00 | .39 -> .06 | .01 -> .01 | .90 -> .90 | 1,774 -> 877 |
| pip (113) | .98 | .26 -> .08 | .04 -> .06 | .66 -> .69 | 1,985 -> 1,001 |
| sqlglot (117) | .89 | .27 -> .16 | .02 -> .10 | .74 -> .82 | 973 -> 472 |
| zod (124) | .62 | .15 -> .06 | .02 -> .04 | .75 -> .76 | 1,301 -> 753 |

"Before" is the branch's first commit, the measurement alone (`d1d7921`); "after" is the tip with
the ordering, one import fact per definition-less module, one fact per distinct test command and the
widened definition regex. The term-ranked view is still computed at the tip (.27 hit, .02 gain, .77
packet): the extraction changes did not move it. `--check` passed on both runs: file ranking is
unchanged.

- The old view's .27 hit was mostly files the agent already had: it added a target the excerpts
  lacked for 2% of targets. The ordered view adds one for 5%, and for 10% on sqlglot, where the
  files ranked just below the ten excerpted ones hold a target most often.
- networkx gains nothing: its excerpts already reach .89 of targets and the next ranked files
  rarely hold the rest. zod's ceiling is coverage: .62 of its targets have a fact, because
  documentation and re-export files define nothing (a barrel keeps one stand-in import fact).
- Dropping every import line first cost coverage (.87 -> .79): `sqlglot/typing/postgres.py`, a
  data table touched by 17 of 117 sqlglot tasks, had only import facts. Keeping one import for a
  module without definitions restored it; facts per map still halved and derivation fell from 43
  to 31 ms per task.
- With the default compact budget on this repository the packet trims all eight map facts before
  any excerpt (`packet_omissions.map_facts`), so the view reaches the agent only when the budget
  allows. Changing that trim order is a separate decision.

### Held-out (test split, 126 tasks)

Run once after the branch was frozen; `--check` passed on both runs.

| Repo (held-out) | targets with a fact | `hit` before -> after | `gain` before -> after | `packet` before -> after |
| --- | --- | --- | --- | --- |
| all (126) | .91 | .24 -> .11 | .04 -> .09 | .83 -> .89 |
| networkx (30) | 1.00 | .36 -> .07 | .00 -> .02 | .92 -> .93 |
| pip (37) | .95 | .22 -> .15 | .06 -> .15 | .79 -> .88 |
| sqlglot (33) | .96 | .25 -> .10 | .05 -> .07 | .85 -> .87 |
| zod (26) | .66 | .10 -> .11 | .02 -> .11 | .79 -> .87 |

The ordered view adds a target the excerpts missed for 9% of held-out targets against 4% before,
lifting packet-level recall from .83 to .89 at the same eight facts (about 2,500 characters). One
held-out task is 0.8 points, so the per-repository rows are indicative only; the pooled gain is
consistent with development (.02 -> .05).

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

1. ~~**De-correlate the lexical votes**~~ — measured 2026-09-22 (section below): grouping the
   lexical voters or down-weighting references does not help; see the table.
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

## Query-analysis fix after the end-to-end evaluation (2026-09-22)

A prose parenthetical (`in this sqlglot checkout (\`sqlglot.executor.execute\`)`) was parsed as a
call, making `checkout` a weight-3 symbol that seeded graph expansion from CI workflows, and
process words in task prompts (`welcome`, `finish`, `summarize`, `verify`, `claim`, `offline`)
counted as concepts. Both are now ignored. Deterministic `full`, all 126 held-out tasks:
R@1 .363 -> .376, R@5 .698 -> .700, R@8 .783 -> .785, R@10 .791 -> .808, MRR .604 -> .614; development
split R@8 .720 -> .726, MRR .549 -> .553; no repository regressed beyond noise. `baseline.json`
records the new numbers. Every Phase 10 table above was measured before this change.

## Retrieval follow-ups measured and declined (2026-09-22)

Two ideas from the failure analysis above were implemented as switches (`fusion_groups`,
`graph.multi_edge`, both off) and swept on the development split, 474 tasks, `full` = .345 / .645 /
.726 / .553 (R@1 / R@5 / R@8 / MRR):

| Variant | R@1 | R@5 | R@8 | MRR | Reading |
| --- | --- | --- | --- | --- | --- |
| lexical group (BM25 + rare terms + references vote once) | .316 | .608 | .684 | .518 | clearly worse on every repository but networkx: the correlated votes carry agreement, not just redundancy |
| … group weight 2.0 | .328 | .655 | .708 | .540 | recovers part of it, still below `full` |
| BM25 + rare terms grouped, references separate | .329 | .612 | .682 | .530 | worse |
| BM25 .7, rare terms .7, references .5 | .331 | .645 | .704 | .537 | worse |
| references weight .5 / .3 / .7 | .348 / .352 / .346 | .658 / .652 / .649 | .718 / .723 / .721 | .556 / .559 / .553 | within noise, R@8 slightly down |
| graph: sum every edge kind between a pair | .338 | .637 | .715 | .546 | worse (sqlglot -.034 R@8); `soft` likewise |
| path weight 1.5 / 2.0 | .328 / .327 | .652 / .658 | .729 / .734 | .541 / .535 | recall up, top ranks down |
| definitions weight 1.5 | .338 | .641 | .698 | .544 | worse |
| path 1.5 + references .5 (+ definitions 1.5) | .341 / .341 | .656 / .645 | .727 / .719 | .550 / .547 | noise |

Nothing beats the current fusion on both recall and top-rank quality, so the defaults stand and
the held-out split was not consulted. The lesson is that "correlated voters" was the wrong
diagnosis: when BM25, rare terms and references agree, they are usually right, and taking away
their combined vote costs more than it saves on the cases where a lone path match should have won.
The switches remain for ablation. The OFFSET fixture from the end-to-end suite illustrates the
limit: `sqlglot/planner.py` has no lexical trace of "offset", and summing its three edges from
`executor/python.py` lifts it only from rank 57 to 32.

## LLM-assisted retrieval (Phase 10)

Measured 2026-09-21 with [llm-assisted-retrieval.md](llm-assisted-retrieval.md) enabled. No hosted
API key was available, so both the representation writer and the reranker were a **local**
Ollama model (`Qwen3.6-35B-A3B`, 4-bit, thinking off, temperature 0, `max_source_chars` 5000,
`max_chars` 1000; schema 1, representation prompt 1, rerank prompt 1). A stronger or hosted model
may move every number below; the stores are keyed by model, so such a run adds to, and never
overwrites, these results. Reranker answers were cached by prompt, so the integration variants
share one model call per task.

**Coverage.** Every eligible file must be represented at every task's base commit, so the
model-backed evaluation uses the newest tasks of the held-out split, chosen by date alone:
**67 tasks, 110 targets** (all 30 sqlglot test tasks, all 37 pip test tasks). The deterministic
`full` baseline scores lower on this subset (R@8 .722, MRR .535) than on the 126-task held-out set
(.783 / .604); every comparison below is paired on the same tasks. All settings (role vote weight
2.0, pre-graph placement, `replace` integration, 20 candidates) were chosen on 28 validation
tasks; the test split was run once per configuration.

### Held-out results (67 tasks)

| Strategy | R@1 | R@3 | R@5 | R@8 | R@10 | MRR | MAP | CtxR | Query cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `full` (Phase 1-9) | .297 | .534 | .623 | .722 | .737 | .535 | .480 | .75 | 0 calls, 84 ms |
| `+ role_summary` (`full+role`) | .306 | .642 | .728 | .757 | .782 | .592 | .523 | .80 | 0 calls, 75 ms |
| `+ reranker` only (`full+rerank`) | .421 | .599 | .723 | .747 | .754 | .662 | .589 | .77 | 1 call, 4.2k in / 0.5k out |
| `+ role_summary + reranker` (`full+role+rerank`, default) | .444 | .614 | .736 | .759 | .809 | .688 | .609 | .82 | 1 call, 4.8k in / 0.45k out |
| … reranker as one RRF voter (w=2) | .380 | .625 | .738 | .762 | .812 | .650 | .567 | .83 | same |
| … reranker + deterministic order blended (w=2) | .437 | .638 | .736 | .797 | .817 | .696 | .612 | .83 | same |
| … reranker picks graph seeds only | .341 | .600 | .728 | .757 | .787 | .611 | .539 | .80 | same |
| … reranker after graph/git, blended | .452 | .673 | .736 | .817 | .822 | .711 | .643 | .84 | 1 call, 5.3k in |

Paired-bootstrap 95% intervals against `full`: `full+role` R@5 +.105 [+.040, +.177], MRR +.057
[-.002, +.117]; `full+role+rerank` R@5 +.112 [+.031, +.197], R@8 +.038 [-.035, +.114], MRR +.153
[+.063, +.250]; post-graph blended R@8 +.096 [+.025, +.175], MRR +.176 [+.089, +.267]. Recall@5
and MRR gains are real; the Recall@8 gain of the default configuration is not distinguishable from
zero on 67 tasks, and only the post-graph variants clear that bar.

By repository: sqlglot (30) `full` .697 / .763 / .618 (R@5 / R@8 / MRR) -> `full+role+rerank`
.830 / .863 / .789; pip (37) .564 / .688 / .469 -> .659 / .675 / .606, where `full+role` alone
reaches .718 / .743 / .567. The reranker helped sqlglot on every metric and pip mainly on MRR.

### Where the gain comes from

- **Candidate recall (RQ2, RQ3).** Targets inside the fused top 20 before any model call: 73.6%
  with `full`, 78.2% with `full+role`; top 5: 49.1% -> 61.8%. The role retriever put 64 of 110
  targets in its own top 10, 3 of which no deterministic retriever had; its main effect is
  agreement, lifting files the lexical retrievers ranked low. `role-only` (.527 / .640 / .483) is
  below `full` but above raw-source BM25 (`+query-analysis`, .549 / .668 / .469) on MRR, and
  `bm25+role` fusion (.709 / .753 / .606) beats both alone (RQ1).
- **Reranking (RQ4, RQ5).** Inside the 20-candidate set the mean target rank moved 3.65 -> 2.67
  (median 2 -> 1): 32 targets improved, 34 unchanged, 20 worsened, 24 never offered. Against the
  final `full` order, 44 targets improved, 34 unchanged, 26 worsened. The 24 candidate-generation
  misses (plus 6 unreadable targets) are the ceiling no reranker can move.
- **Seed selection** alone (`seeds`) keeps only about a third of the MRR gain: the value is in the
  ordering, not in better graph seeds. Graph and git contribute nothing measurable on top of the
  reranker (`rr-no-graph`, `rr-no-git` are within a point).
- **Task category (RQ6)**, R@8 / MRR, `full` -> `full+role` -> `full+role+rerank`:
  weak lexical overlap (19 tasks) .34/.25 -> .53/.40 -> .59/.57; cross-file (20) .52/.57 ->
  .54/.68 -> .59/.79; explicit symbol (17) .81/.79 -> .83/.80 -> .89/.83; explicit path (10)
  .61/.40 -> .61/.43 -> .71/.56; strong lexical (48) .87/.65 -> .85/.67 -> .83/.74. The role
  retriever earns its keep where grep fails; the reranker adds ordering everywhere and costs about
  three points of R@8 on strongly lexical tasks while raising their MRR.

### Representation experiments (no model at query time)

Field ablation of `role-only` on the 67 tasks (R@5 / R@8 / MRR): role .351/.471/.320; +
responsibilities .448/.492/.405; + symbols .495/.547/.483; + concepts + interactions
.524/.618/.462; + likely tasks .524/.618/.470. Every field helps in isolation, and the file path
token adds the rest (full representation .527/.640/.483). Removing `likely_tasks` from the fused
`full+role` changes nothing (.728/.757/.602 vs .728/.757/.592); removing the path token costs
MRR (.580). Role vote weight: 0.5 .688/.749/.568, 1.0 .688/.742/.573, 2.0 .728/.757/.592.

### Reranker prompt experiments (sqlglot, 30 tasks)

| Variant | R@5 | R@8 | MRR | Input tokens | p50 latency |
| --- | --- | --- | --- | --- | --- |
| 10 candidates | .774 | .786 | .757 | 2957 | 16.5 s |
| 20 candidates (default) | .830 | .863 | .789 | 5068 | 50 s* |
| 30 candidates | .841 | .886 | .774 | 7097 | 39 s |
| candidates in fused order | .819 | .863 | .773 | 5068 | 29 s |
| candidates in reverse order | .819 | .863 | .758 | 5068 | 29 s |
| raw source instead of role summaries (same budget) | .830 | .852 | .762 | 6828 | 35 s |
| paths only | .797 | .819 | .752 | 2474 | 22 s |
| no deterministic evidence lines | .830 | .852 | .753 | 4210 | 27 s |

\* measured while a second model job shared the GPU; the other rows ran alone.

Ten candidates lose recall (17 targets never offered against 10); thirty gain R@8 at 40% more
tokens. The hashed order used by default is within noise of fused and reversed order, so position
bias is not driving the result. Role summaries match truncated raw source at 26% fewer tokens
and beat paths alone; the deterministic evidence lines and the summaries each add a few MRR
points. Per candidate a summary costs about 240 tokens, so a 20-candidate prompt is ~5k tokens
regardless of repository size.

### Conditional reranking (RQ8, replayed from recorded confidence signals)

`full+role+rerank`, asking only when no file is named and fewer than A retrievers agree on a
leader ahead by G: never .623/.722/.535 (0% of tasks); A=2 G=0.05 .706/.730/.660 (49%); A=3
G=0.05 .736/.740/.694 (63%); always .736/.759/.688 (100%). Asking on 63% of tasks keeps the whole
R@5 and MRR gain and gives up 2 points of R@8; asking on half keeps most of it. Left off by
default (`"when": "always"`) pending a second model.

### Cost (RQ7)

Index time, once per file content: sqlglot 357 representations, 518k input + 99k output tokens,
20.9x smaller than source (median file 10.8x), 232 tokens per representation; pip 498
representations, 682k + 125k tokens, 14.0x (median 9.7x), 233 tokens; zod (TypeScript, small
files) 70 representations, 4.0x. On the local model about 11 s per file; at $1 / $5 per million
tokens the two Python repositories would cost about $2.30 to index in full. Validation removed
unsupported symbol names from 30% of files (mostly imported base classes such as `Parser`,
`Generator`, `Dialect` claimed as defined) and dropped 238 interaction targets that did not
resolve inside the universe; 582 of 587 kept interactions matched a static edge.

Query time: one call, 4.8k input + 0.45k output tokens per task ($0.007 at the prices above),
p50 48 s and p95 62 s on the local model with the GPU shared, versus 84 ms for the deterministic
pipeline. The `role_summary` retriever itself costs nothing at query time.

### Failure patterns

Of 110 held-out targets under the default configuration, 77 are in the top 8; 18 never entered the
20-candidate set, 6 were unreadable (over the size limit or outside the scan), and 9 were offered
and ranked below 8. The 9 reranker regressions of three or more places are all pip pull-request
descriptions: the model preferred the file that implements the described mechanism over the
command or option file the change actually touched (`commands/list.py`, `cli/cmdoptions.py`,
`models/link.py`), or a vendored/test file that raises the quoted error over the caller that was
fixed. These are "owns the behavior" judgments that are defensible from the summary alone; they
suggest handing the reranker the change kind (command wiring versus mechanism) rather than a
prompt patch per case.

### Model comparison: local Qwen versus Claude (same 67 held-out tasks)

Re-run with the `command` provider driving the `claude` CLI (`env MAX_THINKING_TOKENS=0 claude -p
--tools "" ...`, extended thinking off so that a representation is 150-280 output tokens instead of
2-6k thinking tokens): Claude Haiku 4.5 writes the representations, Claude Sonnet 5 reranks. The
stores are keyed by model, so both sets of representations coexist; everything else (tasks,
deterministic pipeline, prompts, validation, candidate limit 20, `replace` integration) is identical.

| Strategy | R@5 | R@8 | MRR | local Qwen (R@5 / R@8 / MRR) |
| --- | --- | --- | --- | --- |
| `full` | .623 | .722 | .535 | same |
| `full+role` | .725 | .752 | .644 | .728 / .757 / .592 |
| `full+rerank` | .743 | .774 | .736 | .723 / .747 / .662 |
| `full+role+rerank` (default) | **.771** | **.802** | **.753** | .736 / .759 / .688 |
| … reranker + deterministic order blended (w=2) | .771 | .804 | .736 | .736 / .797 / .696 |
| … reranker as one RRF voter (w=2) | .750 | .772 | .683 | .738 / .762 / .650 |
| … reranker picks graph seeds only | .730 | .767 | .669 | .728 / .757 / .611 |

Paired-bootstrap 95% intervals against `full`, Claude rows: `full+role` R@5 +.102 [+.037, +.174],
MRR +.109 [+.039, +.182]; `full+role+rerank` R@5 +.147 [+.070, +.227], **R@8 +.080 [+.011, +.157]**,
MRR +.218 [+.122, +.311]. With the hosted models every headline gain of the default configuration,
including Recall@8, is clear of zero; with the local model only R@5 and MRR were.

- **Representations.** Haiku's summaries retrieve better than the local model's: `role-only` R@5
  .580 / MRR .514 versus .527 / .483, and `full+role` MRR .644 versus .592 with the same recall.
  Candidate recall in the fused top 5 rises to 63.6% (local 61.8%, deterministic 49.1%).
- **Reranking.** Inside the 20-candidate set Sonnet improved 34 targets, left 38 and worsened 13
  (local: 32 / 34 / 20); only 4 offered targets end below rank 8 (local: 9). The remaining misses
  are 19 targets never in the top 20 and 6 unreadable ones, the same ceiling as before.
- **By category**, R@8 / MRR, `full` -> `full+role` -> `full+role+rerank`: weak lexical (19)
  .34/.25 -> .53/.45 -> .62/.62; cross-file (20) .52/.57 -> .52/.76 -> .64/.80; explicit path (10)
  .61/.40 -> .61/.57 -> .81/.72; explicit symbol (17) .81/.79 -> .81/.86 -> .89/.85; strong
  lexical (48) .87/.65 -> .84/.72 -> .87/.81. Unlike the local model, Sonnet no longer costs
  Recall@8 on strongly lexical tasks.
- **Cost and latency (provider-reported).** Indexing: 832 representations for both repositories,
  $3.08, about 6 s per file at concurrency 4 (14 minutes wall for pip's 491). Reranking: $0.039 per
  task (8.9k input + 0.3k output tokens under Claude's tokenizer), p50 4.6 s, p95 8.3 s, versus
  ~50 s on the local model.

### Recommendation

- **Deterministic mode stays the default**: it is unchanged, free and 84 ms.
- **`role_summary` is worth enabling** wherever a user accepts one-time indexing cost or runs a
  local model: +10 points R@5, +6 MRR, largest on weak-lexical and cross-file tasks, no per-query
  model call, and the only step whose gain has a confidence interval clear of zero on both R@5
  and R@8 in at least one configuration.
- **The reranker earns its cost with a hosted model**: with Sonnet, `full+role+rerank` improves
  R@5 by +.15, R@8 by +.08 and MRR by +.22 over deterministic retrieval, every interval clear of
  zero, at $0.04 and about 5 s per request. Recommended as the opt-in configuration for users with
  a hosted provider, in the default `replace` mode with 20 candidates. With the local model the R@8
  gain was not established and each request cost ~50 s, so local-only users should stop at
  `full+role`; the post-graph blended placement remains worth trying for R@8 and was not measured
  with Claude.
- **Not done, deliberately**: default-on for any LLM feature; embeddings; query rewriting; an
  explorer loop.

Re-run everything with `dist/retrieval-llm/index_rounds.sh` (indexing, resumable) and
`dist/retrieval-llm/experiments.sh SPLIT LIMIT rep|rerank|prompt REPO...` after pointing
`dist/retrieval-llm/settings.json` at a provider; `evals/retrieval/llm_report.py` renders the
tables above from the saved JSON.

## Repository memory

Measured on 2026-09-22 with `evals/retrieval/run.py --memory` (see
[repository-memory.md](repository-memory.md)). At each task the episodic store is built in memory
from the base commit's ancestry with the base commit's own event excluded (2,000-commit window,
no symbol history, no experience), the leakage check confirms the fix commit never entered the
store, and `full+memory` adds the gated `memory_git` voter (weight 0.5) to the unchanged `full`
pipeline. Same datasets, splits and discipline as above: tuning on the train split, choice on
validation, one held-out run.

### Held-out (test split, 126 tasks, 204 targets, run once)

| Strategy | R@1 | R@3 | R@5 | R@8 | R@10 | All@5 | All@8 | MRR | MAP | ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `full` | .376 | .600 | .700 | .785 | .808 | .619 | .722 | .614 | .567 | 80 |
| `full+memory` | .399 | .637 | .740 | .798 | .832 | .659 | .738 | .642 | .598 | 76 (+ ~150 memory) |
| `full+memory-messages` | .387 | .617 | .735 | .799 | .835 | .651 | .738 | .629 | .585 | 75 (+ ~150 memory) |

`All@k` is the share of tasks whose every target is in the top k (RepoMem's Accuracy@k); it is
impossible above k targets, so by target count: one target (84 tasks) R@8/All@8 .845 -> .857, two
targets (19) .711/.632 -> .763/.684, three or more (23) .624/.348 -> .609/.348. Per repository
(R@8, `full` -> `full+memory`): networkx .900 -> .950, pip .688 -> .728, sqlglot .805 -> .765, zod
.763 -> .763. One held-out task is 0.8 points, so the R@8 change is within noise; the R@3, R@5,
All@5 and MRR gains (3 to 4 points, consistent with the development splits) are the signal.

### Development (train 357 tasks; validation 117 tasks)

| Split | Strategy | R@3 | R@5 | R@8 | All@5 | All@8 | MRR |
| --- | --- | --- | --- | --- | --- | --- | --- |
| train | `full` | .571 | .655 | .730 | .591 | .672 | .557 |
| train | `full+memory` | .588 | .666 | .732 | .602 | .683 | .577 |
| train | `full+memory-messages` (commit message only) | .598 | .676 | .743 | .616 | .686 | .576 |
| train | `full+memory-forced` (gate open) | .589 | .671 | .735 | .608 | .683 | .570 |
| train | `full+memory-limited` (may only strengthen) | .589 | .671 | .734 | .608 | .683 | .573 |
| validation | `full` | .540 | .617 | .714 | .538 | .650 | .538 |
| validation | `full+memory` | .586 | .660 | .719 | .590 | .650 | .540 |
| validation | `full+memory-messages` | .569 | .660 | .717 | .590 | .641 | .542 |

Tried on train and left at the defaults because the difference was within noise: gate support
restricted to message/identifier/symbol fields (no path tokens; identical), no file affinity
(identical), three files per event with a 0.25 weight (worse: R@8 .724). The gate opens on 83%
of tasks and marks 14% `use_limited`; `forced` and `limited` therefore equal the gated result to
the third decimal, because these issue and PR texts almost always carry an identifier that some
commit message also carries, and memory rarely names a file no source retriever found (7 to 10 of
516 train targets, 5 of 204 held-out). Message-only versus all fields is a wash (train favors
messages by one point of R@8, validation favors all fields at R@3); the default keeps all fields
for the richer explanations. pip is the repository memory helps least on development and most
on held-out, which is the size of the per-repository noise. Where memory hurts sqlglot at R@8
held-out, the losses are three-target tasks where a big historical commit outvotes the second
and third target.

### Chronological replay (sqlglot development split, 117 tasks in commit order, 4 blocks)

`evals/retrieval/chronology.py`: memory pinned before each task, 24 held-out probes (every fifth
task) never recorded, experience arms fed **oracle** records (gold target files as a `partial`
observation asserted by the harness, never verified success) from earlier non-probe tasks.

| Arm | R@8 | All@8 | MRR | paired 95% interval of the R@8 / MRR difference from `full` |
| --- | --- | --- | --- | --- |
| `full` | .724 | .660 | .519 | |
| `full+memory` | .737 | .676 | .540 | +.017 [-.026, +.062] / +.021 [-.002, +.045] |
| `+ experience, frozen after block 0` | .734 | .676 | .573 | +.014 [-.028, +.060] / +.054 [+.019, +.094] |
| `+ experience, accumulated` | .752 | .694 | .590 | +.031 [-.016, +.083] / +.071 [+.037, +.112] |

On the 24 probes every arm scores R@8 .736 / All@8 .667: accumulated oracle experience raised
MRR on the recorded tasks' neighbours but did not move the held-out probes, so this is an upper
bound on what recorded experience could add to retrieval, not evidence that an agent acquires
it. Blocks show no monotonic curve (R@8 by block, `full` .636/.694/.764/.793 versus
`full+memory` .712/.761/.719/.756): later tasks are easier for the baseline, which is exactly
why a rising line alone would prove nothing. Leakage checks: none violated.

### Cost

Per task in the benchmark: 390 to 580 ms to enumerate and parse a 2,000-commit window (one
`git log --raw -z` call), 115 to 175 ms to score the events and resolve files at query time,
against 75 ms for the rest of retrieval. In ordinary use the store is built once by
`repository_memory.py build` (4 s on this repository with symbol history for 40 commits, 0.6 MB)
and refreshed incrementally; the query-time cost is the BM25 pass plus one `merge-base` call.
Symbol history (`--memory-symbols`) and the semantic and experience layers were not part of these
runs; their retrieval paths are exercised by the offline tests only.

### Recommendation

`git.retrieval` stays `shadow` by default: the held-out gain is real at R@3 to R@5 and MRR, small
at R@8, and comes with about 150 ms per query on a 2,000-commit store. Turn it `on` per project
after looking at a few `shadow` packets or `retrieval.py explain` traces. The experience layer
stays `off` until an experiment with agent-acquired (not oracle) records exists; the semantic
layer stays `shadow` until its module records are measured against the file role summaries
above. Raw results: `dist/retrieval-results/memory-{train-*,validation-default-*,test}-<repo>.json`
and `dist/retrieval-results/chronology-sqlglot-dev.json` in the checkout that ran them.
