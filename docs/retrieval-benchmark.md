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

## Co-change statistics measured and declined (2026-09-23)

`git.statistic` selects the association measure computed over one eligible event population (commits
within the 30-file cap, support of at least two shared commits, ten partners per file): the shipped
Jaccard, `conditional` (P(partner | seed), with `git.shrinkage` events added to the denominator) and
`lift` (gated by `git.min_lift` 1.0). Same seeds, same half-weight vote, same caps; only the score and
the ordering inside the git list change. Swept once on the development split with
`evals/retrieval/run.py --split dev --variant`, then the two conditional variants were run once on the
held-out split. Paired-bootstrap 95% intervals are over tasks.

| Split | Variant | R@1 | R@3 | R@5 | R@8 | R@10 | R@20 | All@5 | MRR |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dev (474) | `full` (jaccard) | .346 | .563 | .645 | .729 | .742 | .810 | .576 | .552 |
| dev | conditional | .345 | .575 | .665 | .730 | .750 | .820 | .599 | .557 |
| dev | conditional, shrinkage 2 | .345 | .580 | .664 | .728 | .752 | .819 | .597 | .557 |
| dev | lift | .339 | .568 | .640 | .727 | .737 | .812 | .570 | .548 |
| dev | lift, support 3 | .337 | .565 | .645 | .730 | .740 | .814 | .576 | .545 |
| dev | no git at all | .337 | .563 | .639 | .726 | .733 | .807 | .570 | .546 |
| train (357) | `full` -> conditional | | .570 -> .583 | .654 -> .675 | .734 -> .735 | | .816 -> .829 | .588 -> .611 | .558 -> .564 |
| validation (117) | `full` -> conditional | | .540 -> .549 | .617 -> .635 | .714 -> .716 | | .789 -> .791 | .538 -> .564 | .534 -> .534 |
| test (126) | `full` (jaccard) | .373 | .600 | .698 | .791 | .808 | .881 | .619 | .610 |
| test | conditional | .381 | .624 | .707 | .781 | .808 | .886 | .627 | .634 |
| test | conditional, shrinkage 2 | .381 | .624 | .707 | .783 | .808 | .886 | .627 | .634 |

Development, conditional against jaccard: R@5 +.020 [+.007, +.034], R@8 +.001 [-.009, +.011], MRR
+.005 [-.006, +.016]; train and validation agree in direction on R@3, R@5 and All@5. Held-out: R@3
+.024 [-.000, +.053], R@5 +.009 [-.013, +.034], R@8 -.011 [-.026, +.004], MRR +.024 [-.003, +.051].
Per repository on the held-out split, conditional helps zod (R@5 .628 -> .673, MRR .513 -> .588) and
pip's MRR, costs sqlglot and pip two points of R@8, and moves networkx only at R@1. Lift is worse or
within noise everywhere, which is the expected instability of a ratio that rewards rare pairs.

Reading: the conditional statistic reorders the git list toward a seed's most frequent partners and
lifts a target into the top three or five a little more often, at the price of the eighth slot; every
held-out interval straddles zero and R@8 leans down, so the result is **inconclusive** and Jaccard
stays the default. The switches remain for ablation, and the evidence lines now name their
denominators either way. The same runs measured the new expansion report: graph and git together
introduce 1.4 to 1.5 files into the top ten and displace as many per task on both splits; removing git
lowers that to 1.1 and costs 0.3 to 0.6 points of R@8, which is what the earlier `full-git` ablation
found. The evidence label of the top window is `anchored` on 468 of 474 development tasks and on
every held-out task (issue texts almost always name a symbol some file defines), so the benchmark
also reports the label of the leading file alone: `lexical` leaders (5 to 6 held-out tasks) score
R@8 .60 to .67 against .79 to .80 for anchored ones. That is a stratum for reading traces, not a
calibrated abstention threshold: no no-gold tasks exist in this benchmark.

## Expansion caps by retrieval profile, measured and declined (2026-09-23)

The retrieval plan labels every request with a profile; on the development split the labels are
`exact` 373 (a path, frame, dotted name or quoted literal in the request), `behavior` 87, `history` 9,
`tests` 4, `impact` 1, `vague` 0. Issue and PR texts almost always carry an anchor, so only the first
two strata can decide anything here. Five expansion caps were swept globally with `--variant` and
read per profile (paired bootstrap over tasks; `*` marks an interval clear of zero):

| Variant | All: R@5 / R@8 / MRR vs `full` | `exact` (373) R@8 | `behavior` (87) R@8 | ms |
| --- | --- | --- | --- | --- |
| `git.max_candidates` 20 | -.001 / -.000 / +.001 | +.000 | -.004 | 63 |
| `rrf_weights.git` 1.0 | -.001 / -.011 / -.003 | -.015 [-.029, -.001]* | +.006 | 63 |
| `graph.max_hops` 2 | -.001 / -.006 / +.003 | -.008 | +.000 | 99 |
| `graph.max_neighbors_per_seed` 12 | -.012* / -.016* / -.011* | -.023 [-.039, -.009]* | +.011 [+.000, +.034] | 63 |
| `seed_count` 8 | +.001 / -.008* / +.002 | -.007 [-.016, -.001]* | -.011 | 69 |

Nothing improves a stratum with an interval clear of zero except twelve neighbors per seed on
`behavior` requests (+.011 R@8, lower bound at zero), which costs 2.3 points on the `exact` majority
and would need a profile-specific switch the `history`, `impact` and `tests` strata are far too small
to validate. A second hop costs half again the latency for nothing. The shipped caps stand, the plan
stays observational, and a future profile-specific policy needs a benchmark with more behavioral and
change-impact requests than issue texts provide.

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
- **End-to-end check (2026-09-22, private `dist/evals/big-v4` and `big-v6`)**: on the five-task
  sqlglot suite (Opus 5, 20 trials each), the deterministic dispatcher scored 9/10 against stock's
  9/10 and, with Haiku summaries plus a Sonnet rerank in every helper call, 8/10 against 9/10.
  Localization was visibly better (the OFFSET task's `planner.py` moved from rank 57 to 2 in the
  packet) at $0.04 and ~4 s per call, and the dispatcher ran faster on 6 of 10 pairs at about 8 %
  lower total cost; the one fixture that separates the conditions is a coin-flip HAVING-before-
  OFFSET check that both sides miss, and there sharper excerpts led the model to read less and
  patch the highlighted lines. Twenty trials cannot resolve less than one task; better retrieval
  did not change task success here.
- **Not done, deliberately**: default-on for any LLM feature; embeddings; query rewriting; an
  explorer loop.

Re-run everything with `dist/retrieval-llm/index_rounds.sh` (indexing, resumable) and
`dist/retrieval-llm/experiments.sh SPLIT LIMIT rep|rerank|prompt REPO...` after pointing
`dist/retrieval-llm/settings.json` at a provider; `evals/retrieval/llm_report.py` renders the
tables above from the saved JSON.

## Traceback frames and structural records for oversized files (2026-09-22)

Two deterministic additions from the failure analysis above, measured with `full-frames` and
`full-structure` (each removes exactly one from `full`; positive differences mean the feature helps).

| Split | Feature | R@1 | R@5 | R@8 | All@8 | MRR | Tasks whose target ranks changed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| train (357) | frames | +.002 | .000 | .000 | .000 | +.001 | 3 of 474 dev tasks |
| train (357) | structural records | -.002 | -.001 | +.004 | +.006 | -.001 | 32 of 474 dev tasks |
| validation (117) | frames | .000 | .000 | .000 | .000 | .000 | |
| validation (117) | structural records | -.002 | .000 | .000 | .000 | -.004 | |
| **held-out (126)** | frames | .000 | .000 | +.004 | .000 | .000 | 1 task |
| **held-out (126)** | structural records | -.003 | -.002 | +.003 | +.008 | -.004 | |

- **Frames** fire only when a request carries a traceback, which almost none of these issue and
  PR texts do (3 development tasks, 1 held-out task); where they fire they help and they never
  cost anything, so the feature stays on. Its value has to be measured on issue reports with
  tracebacks, which this benchmark does not contain in numbers.
- **Structural records** matter where the oversized files are: sqlglot's `parser.py` and
  `generator.py` (17 name-only targets on train). On train sqlglot R@8 .761 -> .776 and All@8
  .718 -> .741; two `parser.py` targets move from rank 36 to 12 and 35 to 7; held-out sqlglot
  R@8 .805 -> .815 and All@8 .697 -> .727. The other three repositories have no oversized files
  and are unchanged. The small negative R@1 and MRR movements are the price of definitions
  from a 400 KB file competing at the top rank; net positive at R@8 and All@8 on every split
  where it applies, so the feature stays on (`structural_records: false` restores name-only).

## Oversized lexical coverage, oversized term references and name calibration: development split (2026-09-23)

Four switches, measured on the development split only (see
[repository-intelligence.md](repository-intelligence.md)). Every number in this section is
in-sample development evidence; the held-out split was not run for any of them. Oversized files
are indexed lexically by default but add no term-reference edges; the two `names` switches are
off and change nothing until a variant selects them.

- `oversized.lexical` (default `true`, strategy `full-oversized-structural` for `false`): files over
  the read limit are indexed by their terms, not only their definitions. `run.py` builds one index
  per value of this switch. A target counts as unreachable only when the default index has no
  lexical coverage for it, and as `name_only` when that index still knows it by name
  (`index.coverage` `structural_only` or `unreadable`); a lexically indexed oversized target
  (`complete` or `partial_lexical`) is ranked like any file.
- `oversized.references` (default `false`, strategy `full-oversized-references` for `true`): a
  lexically indexed file over 256 KiB adds no term-reference graph edges. Its terms still count
  for BM25, rare terms and symbol references, and its import, call, definition and inheritance
  edges are unchanged. `run.py` builds one index per value of this switch too.
- `names.case_only` (`shape` default, `resolved`): capitalization-only names weighed by what they
  denote in the index.
- `names.slash_words` (`path` default, `resolved`): `A/B` prose is a path only when it resolves.

The two `names` switches came out of the five end-to-end fixtures, where dialect names typed in
CamelCase (and slash lists of them) pulled whole dialect families above the edited core files. That
evidence is in-sample (15 correlated task strings) and decides nothing. Protocol, fixed before the
first run: one development run of the arms below; every delta against `full` is a paired bootstrap
over tasks (10,000 resamples, 95% interval); profile strata use `full`'s label for each task. Plain
`run.py`'s "By plan profile" section labels each arm by its own plan instead, so for `names-slash`
and `names-both` it prints exact n=362 and behavior n=95 where the columns below, relabelled by
`full`'s plan in the analysis script, use 373 and 87. A `names` arm would become the default only
if its R@8 delta had an interval above zero and no profile stratum lost more than .02 R@8. Coverage
would be re-checked on the held-out split only if `full` lost R@8 to `full-oversized-structural`
with an interval clear of zero. Neither condition held, so the held-out split was not run.
`full-oversized-references` joined the final run as the ablation of the `oversized.references`
default; neither rule was changed for it.

```text
python3 -B evals/retrieval/run.py --split dev \
  --dataset dist/retrieval-datasets/networkx.jsonl --dataset dist/retrieval-datasets/pip.jsonl \
  --dataset dist/retrieval-datasets/sqlglot.jsonl --dataset dist/retrieval-datasets/zod.jsonl \
  --strategy full,full-oversized-references,full-oversized-structural \
  --variant 'names-case=full:names.case_only="resolved"' \
  --variant 'names-slash=full:names.slash_words="resolved"' \
  --variant 'names-both=full:names.case_only="resolved";names.slash_words="resolved"'
```

The run went through a thin wrapper around `run.py`'s `main`, on a snapshot of the final code. The
wrapper also recorded each arm's query calibration, its path tokens and each target's coverage
state; on a six-task check the scored output was identical to plain `run.py`. One process ran all
six arms: 474 s for 474 tasks. Per task, that covers the checkout, a 130 ms scan, the default index
(133 ms, shared by `full` and the `names` arms), the references-on index (101 ms), the coverage-off
index (100 ms) and 59-66 ms of ranking per arm. Arms run in a fixed order inside one process, and
the default index is built first, so the latency differences between them are not a controlled
comparison.

**Earlier runs are superseded.** The tables below come from the final code. Two earlier
development runs of the same protocol are superseded: the first run (five arms) and a rerun after
three fixes to the `names` switches (a capitalization-only name without a definition keeps its
exact spelling at concept weight, the slash gate tests `./x`, `../x` and `.github/x` with the dot,
and a path's file name given in the request is not calibrated as a name). After the rerun, two
review fixes landed (the sniff read is no longer charged to the scan budget; span priority in
evidence mode) and `oversized.references` became `false` by default. Against the rerun, this run's
`full-oversized-references` (the rerun's default) and `full-oversized-structural` reproduce every
target rank, plan profile, query path and coverage stratum. `full` differs from the rerun's `full`
only through `oversized.references`. Raw outputs, the pre-declared analysis plan and the scripts are
in `dist/evals/optimization-2026-09-23/benchmark/` (first run), its `rerun-after-fixes/` folder
(rerun) and `dist/evals/optimization-2026-09-23/final/benchmark/` (this run) of the worktree that
ran them.

| Split | Arm | R@1 | R@5 | R@8 | R@20 | All@8 | MRR | `exact` R@8 (373) | `behavior` R@8 (87) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dev (474) | `full` | .352 | .667 | .727 | .820 | .667 | .561 | .741 | .647 |
| dev | `full-oversized-references` | .352 | .667 | .725 | .818 | .665 | .561 | .738 | .647 |
| dev | `full-oversized-structural` | .346 | .643 | .725 | .810 | .667 | .552 | .744 | .624 |
| dev | `names-case` | .361 | .668 | .722 | .820 | .662 | .565 | .737 | .639 |
| dev | `names-slash` | .350 | .670 | .727 | .822 | .665 | .560 | .741 | .647 |
| dev | `names-both` | .354 | .670 | .718 | .820 | .656 | .562 | .731 | .639 |

Paired deltas against `full` (arm minus `full`; `*` marks an interval clear of zero):

| Arm | R@1 | R@5 | R@8 | R@20 | MRR | Tasks with a target rank changed |
| --- | --- | --- | --- | --- | --- | --- |
| `full-oversized-references` | +.000 [+.000, +.000] | +.000 [+.000, +.000] | -.002 [-.006, +.000] | -.002 [-.006, +.000] | +.000 [-.000, +.001] | 17 |
| `full-oversized-structural` | -.007 [-.019, +.005] | -.024 [-.040, -.010]* | -.002 [-.019, +.014] | -.010 [-.021, +.001] | -.009 [-.020, +.001] | 106 |
| `names-case` | +.008 [+.000, +.018]* | +.002 [-.009, +.012] | -.005 [-.014, +.004] | +.001 [-.006, +.007] | +.004 [-.003, +.012] | 79 |
| `names-slash` | -.002 [-.006, +.000] | +.004 [-.004, +.012] | -.000 [-.004, +.003] | +.002 [+.000, +.006] | -.001 [-.004, +.001] | 40 |
| `names-both` | +.002 [-.009, +.013] | +.004 [-.007, +.015] | -.009 [-.019, -.001]* | +.000 [-.008, +.009] | +.001 [-.007, +.009] | 103 |

R@8 by stratum (`full`'s mean, then each arm's paired delta against `full`):

| Stratum (tasks) | `full` | `full-oversized-references` | `full-oversized-structural` | `names-case` | `names-slash` | `names-both` |
| --- | --- | --- | --- | --- | --- | --- |
| oversized target (20) | .782 | +.000 [+.000, +.000] | -.445 [-.620, -.278]* | -.017 [-.050, +.000] | -.033 [-.100, +.000] | -.050 [-.133, +.000] |
| no oversized target (454) | .725 | -.002 [-.007, +.000] | +.017 [+.005, +.031]* | -.004 [-.013, +.004] | +.001 [+.000, +.003] | -.008 [-.018, +.000] |
| case-only name (202) | .749 | +.000 [+.000, +.000] | +.001 [-.021, +.025] | -.012 [-.033, +.007] | +.002 [+.000, +.007] | -.019 [-.041, +.000] |
| unresolved slash token (135) | .701 | +.000 [+.000, +.000] | -.004 [-.035, +.027] | -.012 [-.040, +.012] | -.001 [-.015, +.011] | -.028 [-.059, -.004]* |

**Oversized term references are off by default.** The switch was adopted under a rule written
before any variant ran (`rule.json` in `dist/evals/optimization-2026-09-23/dominance/`): design on
train only, one validation run per train survivor, adoption only if on validation, against the
previous default and by point estimate, overall R@8 did not drop, the no-oversized-target stratum
did not drop, the oversized-target stratum dropped by at most .05, and sqlglot's `parser.py` stayed
at rank 10 or better on each of the three `group_by_order` queries of the five-fixture snapshot
check. Deltas below are references off minus references on.

| Evidence | Tasks | R@8 on -> off | R@8 delta | Tasks whose R@8 changed | Oversized-target stratum | Other tasks |
| --- | --- | --- | --- | --- | --- | --- |
| train (design) | 357 | .728 -> .731 | +.003 [+.000, +.008] | 1 (up) | +.000 (14 tasks) | +.003 [+.000, +.009] |
| validation (one run) | 117 | .716 -> .716 | +.000 [+.000, +.000] | 0 | +.000 (6 tasks) | +.000 [+.000, +.000] |
| dev, final code (this run) | 474 | .725 -> .727 | +.002 [+.000, +.006] | 1 (up, train) | +.000 (20 tasks) | +.002 [+.000, +.007] |

- On train, oversized files that are not targets appear 43 times in the graph retriever's own
  top 10 with references on and 4 times with them off. In the fused top 8 they fall only from 65
  to 63 instances. On validation R@20 moves by +.009 [+.000, +.026] and MRR by -.001
  [-.002, +.000]; the fixture ranks of `parser.py` are 7, 8 and 8 with and without the switch.
- In this run, 17 tasks have a target rank changed (14 sqlglot, 3 zod), each by one place.
  Going from references on to off, R@8 changes on one train task (rank 9 -> 8), R@3 on two tasks
  (both 3 -> 4) and R@20 on one validation task (21 -> 20). Oversized files sit in the top 8 of
  61 of the 454 tasks without an oversized target with references off, and of 60 with them on.
- Rejected on train, never run on validation: span documents of 16, 32 and 64 KiB (overall R@8
  -.002, -.002 and -.000; other tasks -.003 each; oversized non-targets in the top 8 rise from 65
  to 98, 109 and 104 instances) and capped span scoring at 16 KiB (overall R@8 -.003;
  oversized-target stratum -.094 over 14 tasks). The per-task outputs, the train and validation
  decisions and the scripts are in `dist/evals/optimization-2026-09-23/dominance/`.

**Oversized coverage stays on.** 20 development tasks have an oversized target: 23 targets, all
sqlglot's `parser.py` or `generator.py`, each indexed `complete`. The unreachable and `name_only`
strata are empty on this split. Coverage ranks every one of these 23 targets higher. With coverage,
19 of them are in the top 8; without it, 3 are in the top 8 and 4 are not ranked at all. On those 20
tasks, R@8 is .782 with coverage and .337 without (-.445 [-.620, -.278] for coverage off), and MRR
is .701 against .377.

The other 454 tasks pay for it: turning coverage off raises their R@8 from .725 to .742 (+.017
[+.005, +.031]). With coverage, `parser.py` sits in the top 8 of 53 and `generator.py` of 51 of the
117 sqlglot development tasks. On 61 of the 454 tasks without an oversized target, an oversized
file is in the top 8; without coverage, 5 are. On 4 of the 10 tasks where coverage lowers R@8, no
oversized file is in `full`'s top 8, so the effect also runs through something other than a top-8
slot; this run does not isolate what.

Across all tasks, R@8 is .727 with coverage and .725 without (-.002 [-.019, +.014] for coverage
off), and coverage leads at R@5 and MRR. That is no regression under the rule above, so the
held-out split was not consulted.

**No `names` arm clears the rule; the defaults stay.** No R@8 interval lies above zero, every point
estimate is at or below zero, and `names-both`'s interval lies below zero. No profile stratum loses
more than .02 R@8 (the largest drop is `names-both` on `exact`, -.010), so the R@8 interval alone
decides. `names-case` gains at R@1 (+.008, lower bound +.0004), which the rule does not consider.
Capitalization-only names are not rare in these requests: 202 of 474 carry at least one. 186 of
those have a name that calibration weighs below identifier weight or turns into a concept. Of the
416 calibrated name occurrences, 256 have no definition in the repository. The most frequent names
are product names (NetworkX, DuckDB, PostgreSQL, TypeScript, GitHub) and exception names. On the
202, `names-case` moves MRR by +.010 [-.007, +.028] and R@1 from .290 to .309; `names-both` moves
MRR by +.005 [-.013, +.024] and R@1 to .299.

135 requests carry a slash token that does not resolve to an indexed path, for example `zod/mini`,
`before/after`, `and/or` and `n/a`. Resolving these tokens moves 11 requests out of the `exact`
profile. On the validation part alone (117 tasks), `names-case` moves R@8 by -.026 [-.060, +.000].

## Hub-file damping: development split and one held-out check (2026-09-25)

`hubs` (default `{"damping": 0.0, "min_share": 0.15}`, strategy `full+hubs`) damps the bm25,
rare-term and symbol-reference votes of a file whose distinct terms are at least `min_share` of the
repository's vocabulary; definition, path, graph and git votes are untouched. It was written after
`sqlglot/generator.py` appeared in every packet of an end-to-end pilot. Four settings were declared
before the run, with the rule: adopt only if the development R@8 delta has a 95% interval above
zero and no repository or profile drops by more than .02, then confirm once on the held-out split.

| Setting | Dev R@8 | Δ R@8 vs `full` [95%] |
| --- | --- | --- |
| `full` | .727 | — |
| share .15, damping .5 | .728 | +.001 [−.006, +.007] |
| share .15, damping .8 | .734 | +.007 [+.001, +.015] |
| share .10, damping .5 | .725 | −.002 [−.011, +.007] |
| share .10, damping .8 | .731 | +.004 [−.006, +.014] |

Only share .15 / damping .8 passed on development (all of its change in sqlglot, where it mostly
demoted a 2 MB `CHANGELOG.md`). The single held-out run (126 tasks) gave Δ R@8 −.008 [−.024, .000],
failing every confirmation check, so damping stays `0.0`. At share .10 the switch demotes
`sqlglot/parser.py`, which is a target in 17 development tasks (Δ R@8 −.13 to −.16 there).

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

### Chronological replay (four repositories, development and held-out splits)

`evals/retrieval/chronology.py` over sqlglot, pip, networkx and zod: memory pinned before each task
(boundary excluded), experience arms fed **oracle** records through the shipped `experience` module
and memory layer (gold target files recorded as a harness-graded task, `grader_passed`, never
verified success) from earlier non-probe tasks of the same repository; every fifth task is a
held-out probe that is never recorded. Pooled intervals are paired bootstraps over tasks; the
second interval resamples repositories (the dependence unit), so one repository, and a fortiori
one task, cannot decide the verdict.

| Split | Arm | R@5 | R@8 | All@8 | MRR | R@8 vs `full` [tasks] (repositories) | MRR vs `full` [tasks] |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dev (474) | `full` | .645 | .726 | .667 | .553 | | |
| dev | `full+memory` | .664 | .729 | .675 | .568 | +.003 [-.013, +.019] (-.017, +.016) | +.016 [+.005, +.027] |
| dev | `+ experience, frozen after block 0` | .673 | .732 | .677 | .577 | +.005 [-.011, +.022] (-.018, +.024) | +.025 [+.011, +.039] |
| dev | `+ experience, accumulated` | .676 | .739 | .684 | .584 | +.013 [-.005, +.031] (-.013, +.037) | +.031 [+.016, +.047] |
| test (126) | `full` | .700 | .785 | .722 | .614 | | |
| test | `full+memory` | .740 | .798 | .738 | .642 | +.013 [-.022, +.052] (-.023, +.045) | +.028 [-.003, +.062] |
| test | `+ experience, frozen after block 0` | .744 | .802 | .738 | .647 | +.017 [-.019, +.056] (-.019, +.045) | +.033 [+.000, +.067] |
| test | `+ experience, accumulated` | .748 | .802 | .738 | .653 | +.017 [-.019, +.056] (-.019, +.045) | +.040 [+.006, +.076] |

Per repository (development, all blocks, R@8 / MRR difference from `full`): sqlglot memory
+.017 / +.021 and accumulated experience +.031 / +.070; zod +.016 / +.025 and +.042 / +.035;
networkx +.004 / +.010 (both); pip -.029 / +.007 (both). pip is the one repository where
memory costs R@8, and it does so in every arm, so the pooled R@8 interval straddles zero while
MRR is clear of zero on both splits. Held-out probes (dev: 96 tasks never recorded) move with
memory (R@8 .727 -> .732, MRR .544 -> .580) and a little more with accumulated experience (.740,
.596); on the 27 test probes nothing moves. Blocks show no monotonic curve on any repository.
Leakage checks: none violated on 600 tasks. The memory gate opened on 96% of tasks; oracle
experience matched 27% (frozen) to 53% (accumulated) of tasks.

Reading: recorded experience of the right kind improves the rank of the first target (MRR) and
does not hurt R@8 anywhere except pip; how much of that an agent can earn with its own records is
not measured here. Raw results: `dist/retrieval-results/chronology-{dev,test}-<repo>.json`.

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
after looking at a few `shadow` packets or `retrieval.py explain` traces. The experience layer is
`on` by default (a product decision: nothing is recorded until a host hands in an observation, and
the pooled replay shows an MRR gain clear of zero with no R@8 cost outside pip); an experiment with
agent-acquired rather than oracle records is still the missing measurement. The semantic layer
stays `shadow` until its module records are measured against the file role summaries above. Raw results: `dist/retrieval-results/memory-{train-*,validation-default-*,test}-<repo>.json`
and `dist/retrieval-results/chronology-{dev,test}-<repo>.json` in the checkout that ran them.
