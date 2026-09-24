# Efficiency and reliability pass: audit and decisions (2026-09-24)

Checkout: branch `claude/agent-dispatcher-optimization-4d3438`, fast-forwarded from `af24ee4` to `main`
`d68446f` (the repository-intelligence merge the ri-v1 evaluation ran on). Build and test commands:
`python3 build.py`, `python3 -B -m tests` (838 unittest cases across 29 groups before any change,
893 after, all passing, plus the script-style build and routing checks). No model, judge or network
call was made; every number below is offline.

The objective was a lower cost per verified successful outcome without weaker verification or
retrieval security. This pass does not show that: the only live data is ri-v1, which predates it.
It fixes measurable defects, adds instrumentation, and prepares the next live comparison.

## 1. Evidence audit (ri-v1)

Batches: pilot `20260923T195951Z-2589d21a` (20 trials), smoke `20260923T192921Z-be246511` (4 trials),
in the repository-intelligence worktree's `dist/evals/ri-v1`. The archived tree was not modified
(SHA-256 manifest identical before and after every read). Corrections are additive:
`python3 -B evals/end_to_end/run.py audit --batch <smoke> --batch <pilot>` re-derives every value
from the saved events and labels it `verified` (re-derived and equal to the stored value),
`derived`, `stored_only` or `unavailable`; output in `dist/evals/ri-v1-audit/audit.json`.

| Reported | Status | What the artifacts show |
| --- | --- | --- |
| CLI 2.1.267, `claude-opus-5`, high effort, subscription auth | verified | `result.json` `cli_version`, `effective_settings`; `apiKeySource: none`, rate-limit windows, no overage |
| 9/10 stock vs 8/10 Dispatcher acceptance | verified, **corrected cause** | Stock's failure (`executor_offset` rep 1) passed all 5 acceptance checks; it failed the scope check because `fuzz_offset.py` was left beside the project. Both Dispatcher failures are the HAVING check. On that check: stock 2/2, Dispatcher 0/2 (n = 2 each; two-sided Fisher p ≈ 0.33) |
| $33.81 vs $30.05 | verified | 33.8077325 / 30.051383 (fsum of per-trial `total_cost_usd`, equal to the stored values) |
| Cost per verified success $3.76 each | verified | 3.7564147 vs 3.7564229 |
| "~$42 for smoke plus pilot" | **wrong** | 42.281748 = smoke 12.230365 + the pilot's Dispatcher arm only. Smoke + pilot = **76.0894805** |
| Dollar figures | **relabelled** | `modelUsage.costBasis = list`; `total_cost_usd` reproduces from token counts in all 24 trials. Runtime-reported list-price estimates of API-equivalent cost, not billed spend under subscription |
| Token usage | **incomplete before** | The runner dropped cache creation: 802,857 vs 829,089 tokens in the pilot, 23.7% and 27.6% of arm cost. `input_tokens` is uncached input only (median ~115) |
| Packet ≈ 27.6 KB near a 28k cap | verified, units | 27,027–27,990 characters; UTF-8 bytes = chars + 4; UTF-16 units = chars. The cap is 28,000 Python code points of the compact JSON; the host truncates Bash results at 30,000 characters |
| ≈ 7k tokens (2k excerpts, 5k metadata) | **estimate wrong** | `ceil(chars/4)` gave 6.8–7.0k; usage deltas give 12.0–13.3k (upper bound; ~2.1–2.3 chars/token). Excerpt source text was 32% of bytes, role guidance 20%, context rows 11%, hex ids ~9% (reuse was off) |
| Helper call hidden by `cd … &&` | **corrected cause** | The `cd` prefix was already handled; the missed call ended in `2>&1 \| head -200`. All 12 Dispatcher trials ran the helper once successfully |
| Treatment compliance 10/10 | **different meaning** | It counts the `/agent-dispatcher` skill expansion the harness injects, not helper execution. A separate helper-execution row now exists |
| Wall-minus-model 97 s vs 78 s; indexing suspected | **indexing ruled out as the main cause** | `duration_ms − duration_api_ms` equals the union of tool spans within 0.2–2.3 s. The helper took 4.3–4.8 s. The paired median residual difference (+14.8 s) tracks the paired Bash-span difference (+14.3 s), dominated by ~20 s test-suite runs |
| `group_by_order`: no edited file in the packets | verified | `sqlglot/parser.py` (401,319 B) was edited in all 4 trials; over the 256 KiB read limit it had definitions but no terms and ranked 91st |
| `sqlite_group_concat`: 1 of 5 edited files | verified | `generators/sqlite.py` in both pilot packets; the smoke packet had only `tests/dialects/test_mysql.py` |
| Workers reread packet files | refined | 31 post-packet Reads of listed files: 0 within a supplied span, 13 extending one, 18 elsewhere in the file; 6.4% of lines read fell inside supplied spans. 28 of 107 edits had no earlier Read, so rereads are not all mandatory |
| Confound not reported | **found** | Dispatcher packets carried the operator's global preferences (`effort: low`, `eli5-succinct`) from `~/.config`, which stock never saw. Trials also share `TMPDIR` |

Other observations: the parser cache failed to persist in 6 of the 10 pilot trials (write
attempted, `write_failures: 1`; the other 4 were not allowed to write; cause not established);
every pilot packet was trimmed to the cap (0–8 excerpts evicted, whole files dropped without a
path-level warning); the relationship graph cost ~49% of helper time and was trimmed to
0 nodes in 10 of 12 packets.

## 2. `executor_offset` failure

Replayed offline on the pre-task snapshot with each trial's final files (archived workspaces
untouched). Without `ORDER BY` the planner puts both `LIMIT` and `HAVING` on the Aggregate step,
whose group loop stops at the limit before `HAVING` filters. Both stock patches disable that early
exit when a `HAVING` condition exists; both Dispatcher patches only widen it to `limit + offset`.
The Dispatcher patches fail all four hidden `HAVING` cases, three of which use `OFFSET`, so the
verdict does not hinge on the one `LIMIT`-only case in tension with "keep all other behavior
unchanged". The check compares counts and membership, so it does not depend on row order.

Observed differences, not explanations: both stock runs probed `HAVING … LIMIT` without `ORDER BY`
before editing and fixed what they saw; Dispatcher rep 1 saw it and reported it as a
"pre-existing bug, unchanged"; Dispatcher rep 2 tested `HAVING` only together with `ORDER BY`,
which never reaches the faulty path. Neither Dispatcher packet contained `planner.py` or the
aggregate code, but both agents read those files in full. Competing hypotheses (role wording on
scope, the leaked `effort: low` preference, chance at n = 2) cannot be separated with this data.
This task is now in-sample for any claim about the verification contract below.

## 3. What changed

Defaults are unchanged unless the table says otherwise. Tests are in the named files.

| Area | Change | Default | Tests |
| --- | --- | --- | --- |
| Accounting (`evals/end_to_end/adapters.py`, `reporting.py`) | Usage split (uncached input, cache creation 1h/5m, cache read), `cost_source`/`cost_basis`, runtime fields (`duration_ms`, `duration_api_ms`, `num_turns`); cost labelled as a runtime list-price estimate with the auth basis; arm totals, lower bounds when some cost is unknown, invalid attempts apart, cost per verified success null with a reason (`zero_verified_successes`, `cost_unknown`, `outcomes_pending`) | on (additive) | `tests/e2e/test_adapters.py`, `test_reporting.py` |
| Audit (`run.py audit`) | Read-only re-derivation of every trial and totals with provenance labels; combined block across batches | new command | `tests/e2e/test_reporting.py` (hash-checked read-only) |
| Attribution (`activity.py`) | A helper call with an output-only suffix (`2>&1`, `\| head/tail -N`) is attributed; a piped call counts as a success only with versioned JSON; helper rows record payload size, wall time and the helper's timing block | on | `tests/e2e/test_activity.py` |
| Runner isolation | Every trial gets an empty trial-owned `XDG_CONFIG_HOME`, so operator preferences no longer reach one arm | on | `tests/test_e2e.py`, `tests/e2e/test_integration.py` |
| Packet-mode arms | `dispatcher_lean`, `dispatcher_evidence`; `prepare --packet-tokens N` sets the target for both | opt-in | `tests/e2e/test_conditions.py` |
| Oversized source files (`context.py`, `retrieval.py`) | Eligible files over 256 KiB get lexical terms from the one bounded read (≤ 4 MiB each, 16 MiB per scan), same exclusion and redaction; a longer file is indexed as a line-aligned prefix (`partial_lexical`); only excerpt spans are served, re-read and hash-checked, else withheld as stale; coverage states in `retrieval_status` | **on** (`oversized.lexical`; `full-oversized-structural` restores the old behavior) | `tests/test_context.py`, `test_retrieval.py`, `test_retrieval_security.py` |
| Oversized graph edges | Those terms add no term-reference edges (`oversized.references: false`) | **on** (`full-oversized-references` restores them) | `tests/test_retrieval.py` |
| Security and freshness fixes | Binary sniff before the size verdict (not charged to the scan budget); oversized-record cache keyed on the full file signature (a same-size, same-mtime edit served stale definitions before); deep-index evidence limited to the current ignore-aware listing (a newly ignored file was served before); explain applies automatic exclusions to deep-index evidence (pre-existing leak) | on | `tests/test_parser_cache.py`, `test_repository_index.py`, `test_cache_scope.py` |
| Packet modes (`context_packet.py`, `context.py`) | `--packet-mode lean\|evidence` or `AGENT_DISPATCHER_PACKET`: role body without frontmatter, ranked rows with span references and one short reason, coverage and a `next_action`, no project graph or telemetry; evidence adds at most two highest-priority spans per file. A soft target (`--packet-tokens`, `AGENT_DISPATCHER_PACKET_TOKENS`, default 4,000 estimated tokens) covers SKILL.md plus the packet; a hard limit of 28,000 UTF-16 units applies to the final payload | **legacy** stays the default; its packet code path is unchanged (same output for the same retrieval results, except `--explain`, which now adds timing) | `tests/test_context_packet.py`, `test_context.py` |
| Helper timing | Phase spans (`perf_counter_ns`), inclusive total, labelled unaccounted time, observed cache state; failures name their phase | lean/evidence packets; legacy only with `--explain` | `tests/test_context.py` |
| Verification contract (`build.py`, role templates) | One shared block in implementer, tester and debugger: check each stated requirement directly, the nearest failure, the riskiest neighbor on the changed path (with filtering, ordering, pagination, aggregation and early termination varied alone and combined), and treat a pre-existing defect that blocks a stated requirement as in scope | on (682 bytes; implementer role 5,253 → 5,941 bytes) | `tests/test_build.py` |
| Query interpretation (`retrieval.py`) | `names.case_only: resolved` weighs a capitalization-only name by repository resolution and ambiguity; `names.slash_words: resolved` keeps an `A/B` token as a path only when it resolves | **off** (did not meet the promotion rule) | `tests/test_retrieval.py` |
| Diagnostics | `evals/retrieval/snapshot_diag.py` (hit@k, recall@k, reciprocal rank over pre-task snapshots with evaluator-side labels) | tool | `--self-check` |

The Lean packet on the unmerged branch `claude/e2e-explored-condition` was not ported: its
provenance labels mark almost every row "strong" and it overrides `--max-files`. Its shape informed
the lean mode here.

## 4. Offline measurements

All in-sample development evidence: the 5 sqlglot tasks are the ones the pass was designed on,
and the benchmark's development split was used for every decision. The held-out test split was
never run.

### Retrieval on the five pre-task snapshots

15 task strings (5 manifest prompts, 10 helper task strings from the trials). Labels are the union
of files edited in any trial (12 implementation, 9 test files); that is not complete ground truth.

| Arm | Impl. MRR | Impl. hit@8 | Impl. pooled R@8 | Impl. pooled R@20 | All-label pooled R@8 |
| --- | --- | --- | --- | --- | --- |
| before (`d68446f`) | .341 | .733 | 15/39 | 25/39 | 28/68 |
| final default | .337 | .867 | 17/39 | 27/39 | 29/68 |
| final + both name switches | .438 | .867 | 20/39 | 27/39 | 32/68 |

`sqlglot/parser.py` on `group_by_order` moves from rank 91 (and unranked on both trial task
strings) to 7, 8 and 8. Losses: `planner.py` 33 → 55 on one executor string, `expressions/json.py`
122 → unranked on the tsql prompt and 74 → 127 on one tsql string, `expressions/query.py`
13 → 19 on the group_by strings.
Retrieval call median 39 ms before, 112 ms after (excerpt loading of oversized files; rank-only
time ~17 ms in both). Raw data: `dist/evals/optimization-2026-09-23/final/fixtures/`.

### Retrieval benchmark, development split (474 tasks, 4 repositories)

Development split only (train 357 + validation 117); paired bootstrap over tasks, 10,000
resamples; `*` marks an interval that excludes zero. Full tables: `docs/retrieval-benchmark.md`.

| Arm | R@1 | R@5 | R@8 | R@20 | MRR | R@8 Δ vs final |
| --- | --- | --- | --- | --- | --- | --- |
| final default | .352 | .667 | .727 | .820 | .561 | — |
| reference edges on (pre-adoption default) | .352 | .667 | .725 | .818 | .561 | −.002 [−.006, +.000] |
| coverage off (pre-pass oversized behavior) | .346 | .643 | .725 | .810 | .552 | −.002 [−.019, +.014]; R@5 −.024* |
| `names.case_only` resolved | .361 | .668 | .722 | .820 | .565 | −.005 [−.014, +.004] |
| `names.slash_words` resolved | .350 | .670 | .727 | .822 | .560 | −.000 [−.004, +.003] |
| both name switches | .354 | .670 | .718 | .820 | .562 | −.009 [−.019, −.001]* |

Strata for coverage off vs final: tasks with a target over 256 KiB (20 tasks, all sqlglot
`parser.py`/`generator.py`) R@8 −.445 [−.620, −.278]*; the other 454 tasks +.017 [+.005, +.031]*
(post hoc, defined by target labels). Coverage therefore trades a large gain on the few tasks that
need a big file for a small loss elsewhere; no change in overall R@8 is detectable (the interval
includes zero) and R@5 rises.

### Packets

15 runs per configuration through the real CLI, cold cache, implementer role. Characters equal
UTF-16 units; UTF-8 bytes are characters + 4. Estimated tokens cover SKILL.md (5,812 B) plus the
packet, at `ceil(bytes/2)` (the old `chars/4` figure in parentheses).

| Configuration | Packet chars | Est. tokens | Rows | Excerpts | Impl. labels as row / excerpted | Target met | Helper wall (median) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| before, legacy | 26,643–27,948 | 16,230–16,883 (8,112–8,439) | 5–8 | 13–17 | 13/39 / 13/39 | n/a | 4.4 s |
| final, legacy | 26,983–27,967 | 16,400–16,892 (8,197–8,443) | 5–8 | 15–18 | 15/39 / 15/39 | n/a | 4.5 s |
| final, lean (default target 4,000) | 8,370–8,615 | 7,094–7,216 (3,544–3,605) | 8 | 0 | 17/39 / 0 | no (minimum packet) | 2.2 s graph skipped, 4.5 s built |
| final, evidence (target 12,000) | 17,200–18,088 | 11,509–11,953 (5,752–5,974) | 8 | 12–16, ≤ 2 per file | 17/39 / 17/39 | yes | 2.2 s graph skipped, 4.6 s built |

All 60 payloads are within the host limit. Lean and evidence skip the relationship graph only when
the task restricts cache writes (6 of 15 strings); otherwise it is built for persistence (about
2.1 s) although the slim packet never shows it. No coverage warning or `next_action` arose on these
fixtures; tests cover both.

At the default 4,000 target no mode can meet the target for the implementer role: SKILL.md alone
is about 2,906 estimated tokens and the role body about 2,240. Both modes then deliver the minimum
packet and say so (`target_met: false`, `protected_content_exceeds_target`). Evidence mode needs a
larger target to carry spans; 12,000 is the planning value for the next experiment.

### Helper runtime (one fixture, 341 files, 11.2 MB; n = 3 per row; machine under load)

| Scenario | Observed cache state | Wall (median) |
| --- | --- | --- |
| Cold | cold | 4.7 s |
| Immediate repeat | partial | 0.95 s |
| After a one-line edit | partial | 3.2 s (graph rebuild 2.3 s) |
| Deep index build / refresh after edit | n/a | 1.9 s / 0.4 s |

`warm` is never reached on this suite: 25 small binary files are re-read on every call. On helper
time alone a deep index does not pay back within 20 tasks, because the graph rebuild dominates.
These are helper measurements, not end-to-end results.

## 5. Decisions

- Oversized lexical coverage stays on: it is the completion requirement, and on the development
  split it raises R@5 and the oversized-target stratum. It has a measured post-hoc cost on tasks
  without an oversized target (see the benchmark section). Two span-bounded scoring designs were
  tried and rejected on the train split: scoring spans as documents made large files win more
  often, and capping by spans lost the oversized targets. Only the reference-edge change passed.
- The name switches stay off. Neither met the rule declared before the run.
- Packet modes stay opt-in; legacy stays the default. The 4,000 target is kept as the configured
  starting value; it is infeasible for this role, which is itself a finding.
- The verification contract is on for all packet modes alike, so later comparisons hold it
  constant. It changes the implementer role that every packet inlines (+688 bytes), and oversized
  coverage changes which rows and excerpts legacy packets carry, so legacy packets are not those of
  ri-v1; the archived ri-v1 package remains the reproducible pre-pass path.

## 6. Next experiments (prepared, not run)

Commands, schedule, smoke gate and interpretation limits are in `evals/end_to_end/README.md`.
`prepare`, `load_config` and the schedule were validated offline with no network; `doctor` starts
the `claude` CLI and was not run.

- **A. Delivery ablation:** `baseline`, `dispatcher_lean`, `dispatcher_evidence`, one packet target
  for both packet arms (12,000 proposed; at 4,000 the two arms are identical), 2 repetitions, 36
  trials with smoke. Planning estimate from ri-v1 list prices: about $122 at the baseline arm's
  pilot mean ($3.38 per trial; about $115 at the all-trial mean of $3.19), $189 at the observed
  maximum per trial.
- **B. Held-out validation:** a frozen suite from untuned repositories (pip, networkx, docutils or
  pygments), baseline versus the shipped package; sources need a network clone, which was not done.
- **C. Amortized reuse:** the `indexed` arm's setup was validated; `--warm-project-index` fails setup
  on this suite (the small-binary re-reads above), so it is blocked.

Each needs explicit approval of its spend. Estimates are planning assumptions, not billed amounts.
Commit the pass and rebuild before any `prepare`, and record the package digest.

## 7. Remaining risks

- No live evidence yet: whether coverage, lean/evidence delivery or the contract change task
  outcomes is unknown. One regression in ri-v1 establishes nothing durable either way.
- Oversized coverage costs development-split recall on tasks without an oversized target; the
  mechanism is only partly understood (large vocabularies in the lexical retrievers).
- Redaction false positives (`Token = Token(...)`) still make large Python modules fall back to
  regex definitions without imports or calls; unchanged here.
- The host inline limit is assumed to count UTF-16 units; the Codex host's limit is unknown.
- The conservative estimator (`ceil(bytes/2)`) is calibrated on one model and is not a tokenizer.
- `TMPDIR` is still shared across trials; preference isolation is verified only offline.
- `_read` still checks intermediate path components with `is_symlink()` before opening, which is not
  race-free against concurrent writes to the project tree (pre-existing).
