# LLM-assisted repository retrieval (optional)

Agent Dispatcher can optionally let a model help **find** code, in two bounded ways:

1. **Role representations.** Once per file content, a model writes a ~200-token, retrieval-oriented
   description of what a source file is responsible for. They are stored privately and searched
   locally by a new candidate retriever, `role_summary`, that votes in rank fusion next to the
   path, rare-term, BM25 and symbol retrievers.
2. **Candidate reranking.** After rank fusion, a model may order the top ~20 candidates using
   those compact representations plus the deterministic evidence. It cannot add a file.

It does **not** send the whole repository on every request, replace static analysis, run an agent
loop, rewrite your request, use embeddings, or become a requirement: with the feature off (the
default, and the state without any settings file) retrieval is exactly the deterministic system in
[repository-intelligence.md](repository-intelligence.md), bit-identical on the benchmark.
The design follows *Retrieval-Oriented Code Representations in Agentic Bug Localization*
(arXiv:2607.11046): role-aware summaries, rank fusion across representations, and listwise
reranking over summaries instead of source.

```text
                       REPOSITORY
                           |
             exclusion / credential / size filter        <- nothing below sees an excluded file
                           |
          +----------------+-----------------+
          |                                  |
   static analysis (repo_index)      model, once per file content (llm_retrieval index)
   paths, terms, symbols,            role, responsibilities, symbols, concepts,
   edges, git co-change              interactions, likely tasks  -> validated -> private store
          |                                  |
          +----------------+-----------------+
                           |
  ======================= QUERY TIME =======================
   request -> query analysis -> path | rare terms | BM25 | symbol defs | symbol refs | phrases | role_summary
                           |
                  reciprocal rank fusion
                           |
                 top ~20 candidates  -> optional model rerank (ids only, summaries + evidence, one call)
                           |
            seeds -> graph expansion -> git co-change -> evidence rerank -> context budget
                           |
                 ACTUAL SOURCE EXCERPTS for the coding agent
```

A role summary helps find a file; the agent still receives real source excerpts, never summaries
in place of code, and never the summary index.

## Turning it on

Nothing happens until **you** create a settings file outside any project. A repository can never
enable this or choose where its source is sent: settings and stores inside the inspected project
are refused.

`~/.config/agent-dispatcher/llm-retrieval.json` (or the path in `AGENT_DISPATCHER_LLM_CONFIG`):

```json
{
  "enabled": true,
  "representation": {"provider": "openai", "base_url": "http://localhost:11434/v1", "model": "qwen3.6:27b",
                     "extra_body": {"think": false}, "concurrency": 2},
  "reranking": {"enabled": true, "provider": "anthropic", "model": "claude-haiku-4-5-20251001", "api_key_env": "ANTHROPIC_API_KEY",
                "price_per_mtok": [1.0, 5.0]},
  "budget": {"max_index_calls": 500, "max_query_calls": 1},
  "retrieval": {"llm_rerank": {"candidate_limit": 20, "when": "ambiguous"}}
}
```

| Provider | Talks to | Key |
| --- | --- | --- |
| `openai` | any OpenAI-compatible `/chat/completions`: OpenAI, Ollama, LM Studio, vLLM, gateways (`base_url`) | `api_key_env` names an environment variable; optional for local servers |
| `anthropic` | the Messages API | `api_key_env`, default `ANTHROPIC_API_KEY` |
| `command` | a local CLI: prompt on stdin, answer on stdout, `{system}` substituted in `command` (e.g. `["claude", "-p", "--model", "haiku", "--output-format", "json", "--system-prompt", "{system}", "--tools", ""]`) | whatever that CLI uses |

Representation and reranking are configured independently, so a cheap model can index and a
stronger one can rerank. No provider-specific structured-output API is used: replies are parsed as
JSON, validated, retried once with the reason, and otherwise discarded. Keys are read from the
environment, never stored, logged, cached or echoed; provider error bodies are dropped.
`price_per_mtok` (`[input, output]` dollars per million tokens; the numbers above are an example, enter
your provider's current prices) is optional and only turns measured tokens into an estimated cost.

```bash
python3 -B llm_retrieval.py index --project . --dry-run   # files, eligible files, estimated input tokens; calls nothing
python3 -B llm_retrieval.py index --project .             # generate missing/changed representations (progress on stderr)
python3 -B llm_retrieval.py show src/auth/session.py      # inspect one representation and its metadata
python3 -B llm_retrieval.py status --project .            # coverage, compression, duplicate/ungrounded summaries
python3 -B retrieval.py explain "TASK" --verbose           # role_summary and llm_rerank evidence next to the rest
python3 -B retrieval.py explain "TASK" --no-llm            # the deterministic answer for comparison
```

`index` is incremental and resumable: a file is keyed by content fingerprint, schema version,
prompt version, provider and model, so unchanged files are never paid for twice, one changed file
regenerates alone, results are saved as they land, and `budget.max_index_calls` caps one run.
Queries never generate representations. A file whose content changed since indexing has no current
representation: it is simply not searched by role until the next `index`, while every
deterministic retriever still sees it. Partial coverage is normal and is never read as irrelevance.

## Privacy: what leaves the machine

| Step | Sent to the configured provider | When |
| --- | --- | --- |
| `llm_retrieval.py index` | per eligible file: its path, language, defined symbol names, names of project files it imports / is used by / is tested by, and its **redacted source** (whole when under `max_source_chars`, otherwise its head plus the start of definitions sampled across the file) | only when you run `index` |
| reranking | your request text, candidate paths, their stored role summaries (or symbol names when none exists) and their retrieval evidence | once per retrieval, when `reranking.enabled` |
| `role_summary` retrieval | nothing: it is a local BM25 search over stored summaries | every retrieval, free |

With a local provider (`base_url` on localhost, or a local `command`) the data stays within that
runtime. Excluded, credential, binary, oversized, vendored, generated, test, documentation and
trivial files are never sent; redaction runs before anything is sent. There is no telemetry.
Shadow mode (`"retrieval": {"llm_rerank": {"shadow": true}}` plus `"shadow_log"`) records what the
reranker would have chosen (paths and a request hash, locally) without changing any ranking.

## Cost: indexing versus querying

- **Representation generation** is an index-time cost, paid once per file content and then only
  for changed files. `index --dry-run` previews it.
- **`role_summary` retrieval** has no model call and costs a few milliseconds.
- **Reranking** is the only per-request model call: one call over at most `candidate_limit`
  candidates, so its size is bounded by that limit and not by the repository
  (`"when": "ambiguous"` skips it when a named file or agreeing retrievers already decide).

Measured tokens, latency, compression and quality are in
[retrieval-benchmark.md](retrieval-benchmark.md#llm-assisted-retrieval-phase-10).

## What a representation is, and is not

```json
{"path": "sqlglot/executor/env.py",
 "role": "Defines SQL scalar functions, aggregate wrappers and sort keys for the executor environment.",
 "responsibilities": ["three-valued boolean logic", "null-skipping aggregates", "type casting"],
 "symbols": ["sql_and", "filter_nulls", "cast", "ENV"],
 "concepts": ["three-valued logic", "descending order", "executor environment"],
 "interactions": [{"target": "sqlglot/executor/python.py", "relationship": "supplies ENV", "verified": true}],
 "likely_tasks": ["add a SQL string function"]}
```

The model is given static evidence first (defined symbols, resolved imports, users, tests) and is
told to separate what a file *defines and owns* from what it imports or mentions. Its answer is
then checked against the index: `symbols` keeps only names the file defines (in Python, from the
AST; elsewhere the name must at least occur), `interactions` keeps only targets that resolve to
an admitted file and marks whether a static edge confirms them, every field is length-bounded and
the whole representation is trimmed to `max_chars` (about 250 tokens). Anything else is dropped
and counted in the stored metadata (model, provider, fingerprint, versions, tokens, time, what
validation removed).

Trust order, from authoritative to advisory: exact path, AST definition, verified reference or
edge; then rare terms and BM25; then a role representation; then a reranker's opinion. The lower
layers are useful for ranking and are labeled as such in every explanation ("model-written
retrieval aid, not a repository fact"); nothing a model writes is ever added to the repository
index, its symbols or its graph.

## Reranking

The reranker sees candidates under opaque ids in a request-hashed order, so neither position nor
id reveals the fused rank. It is asked which files a developer would need to inspect or modify for
the request (bug, feature, refactor, performance, security, API or test work), not "where is the
bug", and answers with an ordered id list, a coarse `primary|supporting|weak` label and a short
reason; no probabilities. Unknown, repeated or malformed entries are discarded, omitted candidates
keep their deterministic order behind the ranked ones, and an unusable answer, timeout, rate
limit, missing key or spent budget leaves the deterministic ranking in place with one diagnostic.

How the opinion meets the deterministic ranking is configuration (`retrieval.llm_rerank`):

| Key | Values |
| --- | --- |
| `placement` | `pre_graph` (default: the model's order also picks the graph seeds) or `post_graph` (rerank the final order) |
| `integration` | `replace` (default: the model's order leads the candidates, behind files the request names), `weighted` (deterministic order + model order, weight `weight`), `rrf` (one more voter), `seeds` (seed selection only) |
| `when` | `always` or `ambiguous` (skip when the request names a file, or `min_agreement` retrievers agree on a leader ahead by `min_gap`) |
| `candidate_limit` | how many fused candidates the model may order (default 20) |

A file the request names outright stays pinned in every mode. Placement and integration defaults were
chosen on the benchmark's validation split, where `replace` beat the more conservative modes; the
deterministic evidence of every file is kept and shown either way.

## Host reranking: the session's model as the reranker

`"reranking": {"enabled": true, "provider": "host"}` makes no call at all. The helper renders the
same bounded request (opaque candidate ids, role summaries, deterministic evidence) into the packet
under `rerank_request` (and as `RERANK REQUEST` in `retrieval.py explain`) and reports the
deterministic ranking; the session's own model orders the candidates as one of its steps and hands
the answer back once:

```bash
python3 -B retrieval.py rerank "TASK" --project . --ranking '{"ranking": [{"id": "C07", "label": "primary", "reason": "..."}, "C02", "C11"]}'
python3 -B context.py --project . --task "TASK" --rerank-answer '{"ranking": [...]}'   # the packet, reranked
```

The answer is validated exactly like a provider's (unknown or repeated ids are discarded, omitted
candidates keep their order, an unusable answer leaves the deterministic ranking), and every
deterministic evidence line survives. It is the explorer's `expand` contract applied to ordering:
one round, no loop. The trade against a provider: no key, no extra process and no per-call charge,
but the ~5k-token request enters the session's context, the model is whatever the session runs, and
a second helper invocation is needed. Smoke comparison on 6 held-out sqlglot tasks (Claude Haiku
summaries): the host step, played by Opus at its defaults, and a dedicated Sonnet call agreed on
4-5 of the top 5 candidates on every task and placed each target within two ranks of each other;
as a standalone call Opus cost about 3x more ($0.12-0.15 versus $0.04) and took 11-17 s versus
5-7 s, a cost that a real session does not pay separately.

## Untrusted content

Repository text and model output are both data. Source is sent inside a delimited evidence block
whose closing tag it cannot forge; prompts state that instructions inside it must not be followed.
Whatever a model returns must still pass the schema, the symbol and target checks and the
candidate-id check, so a summary that says "rank this first" or a ranking that names `.env`
achieves nothing. `tests/test_llm_retrieval.py` covers excluded and credential files through
indexing, the store, `show`, `status`, retrieval, reranking and explain; injected source; a model
that obeys the injection; hallucinated symbols, targets and files; stale and partial indexes; every
failure mode; and that query-time prompt size does not grow with the repository.

## Benchmarking it

```bash
S=dist/retrieval-llm/settings.json            # same format as the user settings file
D=dist/retrieval-datasets/sqlglot.jsonl
# index-time: generate representations at each task's commit (content-addressed, so commits share them)
python3 -B evals/retrieval/run.py --dataset $D --split test --recent --limit 10 --strategy "" --llm-settings $S --llm-index
# representation experiments need no model at query time
python3 -B evals/retrieval/run.py --dataset $D --split test --recent --limit 10 --llm-settings $S \
  --strategy "+query-analysis,role-only,bm25+role,full,full+role" --json out/rep.json
# reranking: answers are cached by prompt, so integration variants are free after the first
python3 -B evals/retrieval/run.py --dataset $D --split test --recent --limit 10 --llm-settings $S \
  --strategy full,full+rerank,full+role+rerank --variant 'replace=full+role+rerank:llm_rerank.integration="replace"' --json out/rerank.json
python3 -B evals/retrieval/llm_report.py out/rerank.json --base full --stores dist/retrieval-llm --price 1.0,5.0
```

`--refresh-llm` ignores cached reranker answers. Field ablations are `--variant` overrides of
`role_summary.fields`; prompt experiments are `llm_rerank.content` (`role`, `raw`, `path`),
`llm_rerank.order` (`hashed`, `rank`, `reverse`) and `llm_rerank.evidence`. The report separates
candidate-generation misses from reranking misses, tracks target rank movement, replays
conditional-reranking policies from recorded confidence signals without new calls, and reports
paired-bootstrap intervals, because a small model-backed benchmark must not over-claim.
