# Retrieval benchmark: file localization

Given the text of a real issue, pull request or commit, can repository retrieval rank the
files that the real change modified? This is an offline, deterministic measurement of the
context helper's retrieval layer. It needs no model, network or API key once a dataset and
the repository clones exist. It does not measure whether an agent then solves the task.

## Two separate steps

| Step | Script | Network | Output |
| --- | --- | --- | --- |
| Dataset generation | `mine.py` | optional: `--github` reads public PR/issue text through an authenticated `gh` CLI; responses are cached under `dist/retrieval-cache/` | a committed, text-free **manifest** and a git-ignored **dataset** with the query text |
| Offline evaluation | `run.py`, `perf.py` | never | tables, failure report, optional JSON |

The manifests in `datasets/` pin every task (commits, PR and issue numbers, target files, split)
without redistributing anyone's issue or PR description. Hydrate them once into datasets:

```bash
# one-time: clones live in the git-ignored dist/ directory; history depth matters for co-change
git clone --depth 2500 --single-branch https://github.com/tobymao/sqlglot dist/retrieval-repos/sqlglot

# rebuild the dataset for a committed manifest (network once, then cached)
python3 -B evals/retrieval/mine.py --repo dist/retrieval-repos/sqlglot --github tobymao/sqlglot \
  --hydrate evals/retrieval/datasets/sqlglot.manifest.jsonl --out dist/retrieval-datasets/sqlglot.jsonl

# offline evaluation
D=dist/retrieval-datasets/sqlglot.jsonl
python3 -B evals/retrieval/run.py --dataset $D --strategy current,bm25,hybrid,hybrid+graph,full
python3 -B evals/retrieval/run.py --dataset $D --strategy ladder           # cumulative ablation
python3 -B evals/retrieval/run.py --dataset $D --strategy leave-one-out    # what each part is worth
python3 -B evals/retrieval/run.py --dataset $D --strategy full --failures 10
python3 -B evals/retrieval/run.py --dataset $D --split test --strategy current,full --check evals/retrieval/baseline.json
python3 -B evals/retrieval/perf.py dist/retrieval-repos/sqlglot            # index build, incremental update, latency

# mine a new repository (any language): writes both files
python3 -B evals/retrieval/mine.py --repo dist/retrieval-repos/NAME --name NAME --url https://github.com/OWNER/NAME \
  --github OWNER/NAME --manifest evals/retrieval/datasets/NAME.manifest.jsonl --out dist/retrieval-datasets/NAME.jsonl
```

Upstreams used here: `tobymao/sqlglot`, `pypa/pip`, `networkx/networkx`, `colinhacks/zod` (TypeScript).
Without `--github`, queries are commit messages only, and no network is used at all.

## Task format

```json
{"id": "sqlglot-8579d7ca12", "repo": "sqlglot", "url": "https://github.com/tobymao/sqlglot",
 "base_commit": "<parent of the fix>", "fix_commit": "<the fix>", "split": "train", "pr": "8395", "issue": null,
 "query_source": "issue", "query": "issue, PR or commit text (dataset only, not the manifest)", "names_target": false,
 "target_files": ["sqlglot/executor/python.py"], "test_files": ["tests/test_executor.py"], "added_files": []}
```

- `target_files` are the non-test source files the change **modified**. Primary metrics use only these.
- `test_files` (modified tests) and `added_files` (cannot exist in the parent tree) are kept apart.
- `query` prefers the linked issue, then the PR description, then the commit message; `query_source` says which.
- `names_target` marks queries that literally contain a target's file name, for honest stratification.
- A task is evaluated at `base_commit`. Git history is read at that commit, so the fix never leaks into co-change.

## Splits

`split = sha256(task id) mod 10`: 0-5 `train`, 6-7 `validation`, 8-9 `test`. The split depends on
nothing but the id. Tune on `train`, choose between configurations on `validation`
(`--split dev` is both), and report `--split test` only as held-out. `run.py` labels every
table with the split it used; a development number is never a held-out number.

## Metrics (means over tasks)

| Metric | Definition |
| --- | --- |
| Recall@k (k = 1, 3, 5, 8, 10) | targets ranked in the top k / targets of the task |
| MRR | 1 / rank of the first target, 0 when none is ranked |
| MAP | mean over targets of (targets at or above this rank / this rank); a missing target adds 0 |
| Cand | files in the final ranking |
| Files, KB, Tok | what the strategy would hand the agent: files, bytes of the rendered repository context (for `current`: excerpt bytes plus its JSON rows), and bytes / 4 |
| UCD (Useful Context Density) | excerpt bytes belonging to target files / all excerpt bytes |
| CtxR | targets present in that context / targets |
| ms | ranking plus context selection over a built index. Index and scan time are printed separately |

Each table header counts targets whose content the scan could not read. Files over the 256 KiB
read limit can still be ranked by name, imports and history (never excerpted); skipped or
unreadable ones are misses for every strategy. Either way the ceiling is visible.

## Strategies

`current` is the pre-upgrade flat scorer, run through the same code the helper still uses for
`--retrieval legacy`. The ladder adds one component at a time:
`bm25` -> `+query-analysis` -> `+path` -> `+rare-terms` -> `+symbols` -> `+rrf` (= `hybrid`) -> `+graph`
(= `hybrid+graph`) -> `+git` -> `+rerank` -> `+context-optimizer` (= `full`) -> `+explorer`.
`full-<component>` removes exactly one component from `full`. `--set key=json` overrides any value
in `retrieval.DEFAULTS`, for example `--set rrf_k=30 --set graph.max_hops=2`.

## Analysis output

- **Candidate overlap**: mean shared files per pair of sources, and for each source how many
  targets it put in its own top 10 and how many of those no other source found.
- **Failure report** (`--failures N`): per missed target, its rank in every retriever and in the
  fused list, and a mechanical reading of the stage that lost it (unreachable, name only,
  candidate generation, rank fusion/rerank, expansion only, weak evidence). It never changes a weight.
- **Regression guard** (`--check`): fails when a recorded metric drops by more than `--tolerance`
  (default 0.03, about two tasks of the held-out split). Rankings are deterministic, so any
  difference is a code or configuration change, not noise.
