# Evidence-backed repository intelligence: audit and decisions (2026-09-23)

Checkout audited: branch `claude/agent-dispatcher-repo-intelligence-691cab` at
`af24ee4d887a5a6f738a2abb0dde1c747788a8fd` (the public reference snapshot; clean tree), Python 3.14.6 on
macOS, CI matrix Python 3.10-3.14 on Linux and 3.14 on macOS. Build and test commands: `python3 build.py`,
`python3 -B -m tests` (828 tests, all passing before any change, 3 min 50 s). The Lean-packet and
completion-contract work (`test_lean.py`, `test_completion.py`, `context: Lean packet`) exists only on the
unmerged branch `claude/e2e-explored-condition`; nothing on this branch touches it, and no lean mode
exists on `main`, so "preserve the current packet mode and any newer lean-context variant" meant not
reintroducing one here.

The runtime modules under `skills/agent-dispatcher/` are byte copies made by `build.py`; the root
modules are canonical. Every change below was made in a root module and regenerated.

## Implementation map

Status after this iteration. "Caller" is the production path that runs the code, not a test.

| Capability (prompt section) | Status | Owner | Caller | Tests | Missing / decision |
| --- | --- | --- | --- | --- | --- |
| Deterministic query analysis: paths, dotted names, frames, quoted literals, identifiers, wants (8.1) | implemented and tested | `retrieval.analyze_query` | `retrieve` | `tests/test_retrieval.py` QueryAnalysisTests | No negation grammar in the analyzer (task exclusions handle "do not touch"). Model reformulation is absent by design: no provider stage exists for it and none was added (§8.1 asks for it only "optionally"). |
| Retriever registry, rank fusion, named-file pinning, tie-breaks (8.3) | implemented and tested | `retrieval.RETRIEVERS`, `fuse`, `_rerank` | `retrieve` | RetrieverTests, FusionTests | Unchanged: `rrf_k` 20, tuned weights, grouped voting and multi-edge switches measured and left off on 2026-09-22. |
| Explainable retrieval plan (8.2) | **implemented and tested (new)** | `retrieval.plan_retrieval` | `retrieve` → `result["plan"]`, `explain` | PlanAndStatusTests | Policy is `observe`: profiles and reason codes are reported and stratify evaluations; no family is switched off, because every deterministic family costs milliseconds and the optional stages (reranker `when`, memory gates, explorer) already carry gates. Profile-specific caps are a future ablation, not a default. |
| Result status vocabulary (6.2) | **implemented and tested (new)** | `retrieval._status`, `run` | `retrieve`, `run`, `explain`; `context.py` reports it in `repository_intelligence.retrieval_status` | PlanAndStatusTests | `stale_only` is not emitted at this level: staleness lives in the memory layer (`ignore_stale`, `behind`) and the index report (`stale index evidence`), which are reported beside it. Abstention is a label, never a suppression of candidates; the evidence label at window 10 is `anchored` on every held-out benchmark task, so a leader-only label is reported too. |
| Displacement report for expansion and reranking (8.3) | **implemented and tested (new)** | `retrieval._displacement` | `retrieve` → `trace.displacement`; `explain --verbose`; benchmark rows | PlanAndStatusTests | Explorer insertions are not diffed separately (they insert behind the protected seed block). |
| Co-change with explainable denominators (9.2) | **implemented and tested (new)** | `repo_index.cochange(stats=)`, `retrieval.git_candidates`, `repo_store.history_stats` | query-time history and deep-index reuse | GitHistoryTests | Denominators are `n(A,B)`, `n(A)`, `N` over the eligible population after the 30-file cap; shown by `explain` (`detail`), never in the packet line. |
| Alternative co-change statistics (9.2) | **experimental, measured, off** | `git.statistic`, `git.shrinkage`, `git.min_lift` | ablation only (`--variant`) | GitHistoryTests | Conditional and lift over the same population, support floor and cap; development-split results below. Jaccard stays the default. |
| Release/revert/bulk suppression in query-time co-change (9.1) | implemented but incomplete | `context._git_history` (`--no-merges`, 30-file cap) | query time | test_retrieval security tests | The query-time log carries no subjects, so release and revert commits are not excluded there; the episodic layer flags `release` and `revert_of` and groups a revert with its target. Deferred: adding subjects to the cached log would enlarge a security-sensitive cache. |
| Scale bounds for pair generation (9.3) | implemented | 30 files per event, 10 partners per file, 10 git candidates | query time and builder | GitHistoryTests | Truncation is disclosed as the bulk cap; per-event pair work is at most 435 pairs. |
| Episodic history, rename lineage, hotspots, hardened Git wrapper (9.1) | implemented and tested | `repo_history.py` | `repository_memory.build` | `tests/test_repository_memory.py` | Unchanged. Cherry-pick and patch-id deduplication does not exist and is labeled as such in the memory doc. |
| Typed memory layers, gate states, shadow/on modes (10) | implemented and tested | `repository_memory.layer` | `context._memory_layer` | RetrievalAndBudgets | Defaults unchanged: experience recording/retrieval on, history and semantic shadow, learning off. |
| Experience semantics: receipts, outcome vocabulary, corrections, forgetting (10.1) | implemented and tested; two fixes | `experience.py`, `repository_memory.record_experience` | `record`, `correct`, `forget` | ExperienceCorrectness, `tests/test_experience.py` | Fixed: the older `experience record --outcome` accepted an asserted `checked_success`; `read: null` was stored as `[]`. Forgetting is a hard delete without tombstone (documented as logical deletion). |
| Path-scoped recall with backoff (10.2) | **implemented for consolidation candidates (new)**; absent for votes | `repository_memory.consolidate(task=)` | `consolidate --task` | ExperienceCorrectness | Candidate claims are matched `exact` → `module` → `repository`; experience votes keep their term-similarity scoring, which the chronological replay measured. A scoped vote boost is an unmeasured follow-up. |
| Consolidation into reusable knowledge (10.3) | **implemented and tested (new)** | `repository_memory.consolidate` | CLI, demo | ExperienceCorrectness, `tests/test_memory_lifecycle.py` | Candidates are derived at read time (no store, so nothing can go stale silently), count independent families once, list contradictions, check freshness, and point to `learning propose` as the only promotion path. No probability is invented. |
| Selective invalidation (11.2) | implemented but incomplete; one fix | fingerprints per record/summary/experience file; `invalidate_inferences` | refresh, maintenance | test_exploration, test_repository_index | Fixed: task-time maintenance marked every inference stale because unseen paths counted as changed. Still scan-all in the memory layer (bounded stores, milliseconds); dependency manifests are not tracked. |
| Transactional private state, two-worktree isolation (11.3) | implemented and tested | `repo_store.py`, project-map writer | all stores | test_repository_index | Generation isolation is weaker than the doc's wording (shared mutable tables, fingerprint checks are the real gate); noted, not changed. |
| Budget-aware selection and accounting (12) | implemented | `context_budget.py`, `context_packet.py` | `context.py` | test_context_packet | Three budgets already exist (candidates per retriever, excerpt bytes, packet tokens with the 28,000-character host cap); `budget_exhausted` now surfaces byte-budget drops in the status. Tokens remain `ceil(chars/4)` estimates and are labeled so. |
| Bounded exploration (13.1) | implemented, off by default; one fix | `exploration.py`, `retrieval.deterministic_explorer` | `explore`, `full+explorer` | test_exploration | Fixed: failed and rejected calls were not counted. The model-free explorer measured worse Recall@8 and stays off. |
| Working-memory digests (13.2) | **implemented and tested (new)** | `repository_memory.working_memory` | `digest` CLI, demo | ExperienceCorrectness | Explicit record/compact/show/forget; no host hook exists, so nothing is automatic; never read by retrieval. |
| Optional role representations and bounded reranking (8.4, 8.5) | implemented, opt-in; three fixes | `llm_retrieval.py` | `_llm_layer` | test_llm_retrieval | Fixed: prompt overflow with long evidence, a masked retry error, an oversized store overwritten with an empty one. Embeddings are absent by design: no provider or index exists, and a placeholder would be marketing. Query-time model work is one reranker call at most (`max_query_calls` 1); the Explorer and summaries are build-time, each with its own budget. |
| Retrieval evaluation (14.1, 14.2) | implemented; extended | `evals/retrieval/run.py` | offline | BenchmarkMathTests | Added R@20, a stratum by evidence label and the mean expansion effect; `status` and `displacement` per row. Agent Retrieval Bench and SWE-Explore adapters were not written: no release is present locally and an adapter tested on synthetic schema fixtures is not a completed benchmark run. |
| Chronological replay and end-to-end harness (14.4, 14.5) | implemented; one fix | `chronology.py`, `sequence.py`, `evals/end_to_end` | offline / live-gated | e2e tests | Fixed: `learned_*` arms failed startup validation as non-treatments. No live run was performed. |
| Security invariants (15) | implemented and tested | admission, redaction, hardened Git | everywhere | `tests/test_retrieval_security.py`, memory admission tests | New surfaces (consolidation, digests, denominators) read only admitted paths and scrubbed text; digests are owner-only files with a bounded read. |

## Decisions

- **Extend, do not add a framework.** Every new behavior is a function in an existing module with an
  existing caller: the plan, status and displacement live in `retrieval.retrieve`; denominators in
  `repo_index.cochange`; consolidation and digests in `repository_memory.py` beside the commands that
  write the records they read. No new store, tokenizer, model client or router.
- **Rankings unchanged by default.** The held-out benchmark is identical before and after
  (126 tasks: R@1 .373, R@5 .698, R@8 .791, MRR .610), because every addition is observational or
  gated off. The packet's `why` lines are byte-identical; denominators are an explain-only `detail`.
- **Observed plan over enforced plan.** The prompt asks for a policy that does not call every retriever
  on every task. The deterministic families cost a few milliseconds each and give the baseline coverage
  path the prompt also asks to keep, so the plan reports and stratifies; enforcement would need the
  ablation the prompt says must precede any default change.
- **Consolidation derives, learning promotes.** A candidate claim is recomputed from surviving records
  on every call, so a correction or forgetting withdraws it without a second invalidation mechanism, and
  the only path to guidance is the governed learning lifecycle. Support is counted in task families, the
  same fingerprint the learning review uses, so the two never disagree about what is independent.
- **Digests are explicit.** There is no host observation hook, so the digest is a command a host or user
  runs; it is task-local, verbatim, bounded, and never read by retrieval.
- **What was not built, and why:** model reformulation (no provider stage, no local data to evaluate
  it), embeddings (no provider; a mock would misrepresent the capability), official benchmark adapters
  (no local releases), profile-specific retrieval caps (unmeasured), and automatic cross-session
  retention (no adapter supports it).

## Measurements

Offline, deterministic, on the four-repository benchmark clones present in this environment
(`evals/retrieval`, datasets hydrated earlier; no model, no network).

**Held-out regression check** (test split, 126 tasks, one run after all changes): `full` R@1 .373,
R@3 .600, R@5 .698, R@8 .791, R@10 .808, R@20 .881, MRR .610, MAP .566, 64 ms; identical to the run
before the changes and within tolerance of the frozen `baseline.json`. Expansion effect: on average
graph and git introduced 1.5 files into the top ten and displaced 1.5 baseline files per task; the
benchmark now reports whether those trades helped through the unchanged recall metrics.

**Co-change statistics** (development split, 474 tasks; held-out once, 126 tasks): conditional
against Jaccard on development R@5 +.020 [+.007, +.034], R@8 +.001 [-.009, +.011], MRR +.005
[-.006, +.016]; held-out R@3 +.024 [-.000, +.053], R@5 +.009 [-.013, +.034], R@8 -.011 [-.026, +.004],
MRR +.024 [-.003, +.051]. Lift is worse or within noise. Inconclusive; Jaccard stays the default and
the switches remain for ablation. Full table in
[retrieval-benchmark.md](retrieval-benchmark.md#co-change-statistics-measured-and-declined-2026-09-23).

**Evidence label:** `anchored` for the top window on 468 of 474 development and all 126 held-out
tasks, so the benchmark also reports the leader's label; the 5 to 6 held-out tasks whose leading file
has only lexical evidence score R@8 .60 to .67 against .79 to .80. A stratum, not a threshold.

**Lifecycle demo** (`python3 -B evals/memory/demo.py`): build (3 events), a behavior query ranked
`app/sessions.py` first with plan `behavior`, status `ok`, co-change evidence "changed in 2 of the 2
eligible events containing app/sessions.py; 2 eligible events in the window"; a receipt-backed record
(`checked_success`, an asserted one refused); a candidate claim with two families, scope `app`,
`exact` match, current evidence; after a source change the claim is `changed` and the experience layer
is `use_limited`; after correcting one episode there is no candidate; after forgetting the other the
packet is the baseline packet; a digest keeps a negated hypothesis, a pending question and a failed
check through compaction.

**End-to-end pilot** (`evals/end_to_end`, Claude Code 2.1.267, `claude-opus-5` at high effort,
subscription auth, the five-task sqlglot suite `dist/suites/big`, two repetitions, stock versus
Dispatcher with this branch's package, automated acceptance checks only; the blind review step was
not run, so claim-accuracy and intervention metrics are unrated). Smoke: 4 of 4 valid. Pilot: 20 of
20 evaluable, no invalid attempts, treatment compliance 10 of 10, the context packet delivered inline
in every Dispatcher trial. Stock 9 of 10, Dispatcher 8 of 10: eight pairs both passed, one pair both
failed and one regressed, all three failures on `executor_offset`'s HAVING-before-LIMIT check (the
same check that failed on both sides in the earlier `big-v4` and `big-v6` pilots; not a retrieval
miss). Cost: Dispatcher $30.05 total against $33.81 (median $2.92 against $3.18, cheaper on 8 of 10
pairs); time: 74 against 76 minutes (median 440 against 458 s, faster on 5 of 10 pairs); measured
cost per verified success $3.76 on both sides. With ten pairs this is parity on quality and a small
cost saving, and the run cannot attribute anything to the new plan, status or consolidation code,
which does not change rankings; it confirms the package works end to end on a real repository.

## Defaults, opt-ins, privacy, rollback

No default changed. New keys: `git.statistic` (`jaccard`), `git.shrinkage` (0.0), `git.min_lift` (1.0)
in `retrieval.DEFAULTS`, used only through the benchmark's `--variant`; `repository_memory.CONSOLIDATION`
(`min_families` 2, 20 candidates) and `WORKING_MEMORY` (window 12, 400-character text, 40 per bucket,
64 KiB) are module constants, not settings. Consolidation reads the experience store and writes
nothing; digests write one owner-only file per task under the private state directory's
`working-memory/` and are removed with `digest forget`. No schema migration was needed: the experience
store and the index store are unchanged, and a deep index built before this release yields its
co-change denominators from the commits it already stores (`repo_store.history_stats`). Rollback is `git revert` of
this change; no persistent state depends on it.

## Next experiment

The profile-stratified cap sweep was run on the development split (five variants, paired per
profile): no cap improves a stratum with an interval clear of zero, twelve neighbors per seed helps
`behavior` requests at the border while costing the `exact` majority, and a second hop costs half
again the latency for nothing; see
[retrieval-benchmark.md](retrieval-benchmark.md#expansion-caps-by-retrieval-profile-measured-and-declined-2026-09-23).
The benchmark's requests are 79% `exact`, so a profile-specific policy needs a task set with more
behavioral and change-impact requests before it can be decided. For memory, the missing measurement
is still agent-acquired experience rather than oracle records: the `warm_experience` end-to-end arm
with real observations, now that consolidation can show what those records would support.
