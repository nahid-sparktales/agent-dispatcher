# Changelog

## Unreleased

- Evidence-backed repository intelligence iteration (audit and decisions in
  `docs/repository-intelligence-audit.md`). Retrieval results now carry a deterministic plan
  (profile, reason codes, families, caps, stop conditions; policy `observe`, no family is switched
  off), a status kept apart from the ranking (`ok`, `abstained_no_sufficient_local_evidence`,
  `unavailable`, with an evidence label and `partial_coverage`, `budget_exhausted` and
  `provider_failed` conditions), and a displacement report per stage (files graph/git expansion
  or a model rerank introduced into the top window, and the baseline files they pushed out);
  `retrieval.py explain` prints `PLAN`, `STATUS` and `EXPANSION EFFECT`/`RERANK EFFECT`. Co-change
  evidence names its denominators ("changed in 4 of the 5 eligible events containing X; N eligible
  events in the window", also for a deep index's stored history) while packet lines stay
  byte-identical; `git.statistic` (`jaccard` default, `conditional` with `git.shrinkage`, `lift`
  with `git.min_lift`) exists as an ablation over the same event population and was measured on
  the development split and left off. The benchmark reports R@20, a stratum by evidence label and
  the mean expansion effect, and its JSON rows carry `status` and `displacement`.
- Repository memory gains `consolidate` (candidate descriptive claims derived at read time from
  recorded experience: files edited together by at least two independent task families, support
  counted in families so retries and paraphrases count once, contradictions from contrary outcomes,
  a freshness check of every core file, explicit limitations, and a scope match with backoff
  `exact`/`module`/`repository` against a request; nothing is stored, votes or is promoted, and the
  only route to guidance is `learning propose`) and `digest record|compact|show|forget` (explicit,
  task-local working memory: verbatim bounded observations by kind and status, a recent window,
  typed digest buckets that drop confirmed findings before failures, contradictions, unresolved
  questions and pending checks, a loss counter, owner-only 0600 storage, never read by retrieval).
  `evals/memory/demo.py` runs the offline lifecycle (build, retrieve, receipt-backed record,
  consolidate, source change, correction, forgetting, digest) and `tests/test_memory_lifecycle.py`
  keeps it green.
- Fixes found by the audit: `repository_intelligence.py experience record --outcome` no longer
  accepts an asserted `checked_success` (a receipt is the only route; a harness may still label
  `grader_passed` with `--source harness`), and `--edited-from-git` refuses option-like values and
  ranges; an observation without `read` stores `null` instead of an empty list; task-time index
  maintenance no longer marks every inference stale (only cited evidence known to have changed);
  the reranker prompt can no longer exceed its character budget when evidence lines are long, a
  retry the call budget forbids reports the original parse error instead of "budget spent", and a
  representation store too large to load is never overwritten with an empty one; the onboarding
  Explorer counts failed and rejected calls in its accounting; stale model prose no longer shows in
  semantic memory hits; the end-to-end runner's `learned_*` arms are validated as treatments; the
  dead `memory_experience` voter label is gone.

- Add optional, off-by-default procedural learning (`learning.py`, `learning_compose.py`,
  `learning_eval.py`, `docs/procedural-learning.md`, `LEARNING.md`, `/agent-learning`,
  `$agent-dispatcher learning`, `repository_intelligence.py learning`): explicit observations keyed
  to experience events, a deterministic pattern review with host- and provider-assisted proposal
  paths, strict candidate schemas with structural and security validation, immutable
  content-addressed revisions, a controller-owned lifecycle with human approval bound to the exact
  candidate, evaluation, composed bundle and incumbent generation, compare-and-swap publication,
  rollback, revocation with provenance descendants, pruning and forgetting that consult experience
  corrections. Five artifact kinds share the lifecycle: skill overlays, recipe overlays (the debug
  recipe gains a validated `debug-application.workflow.json` sidecar with stable step ids and
  mandatory gates), role method overlays, allowlisted retrieval profiles and verification scheduling
  hints. In `active` mode `context.py --compact` composes admitted overlays onto the guidance it
  already read (labeled `derived`, base digest kept) inside a separate added-guidance budget; reuse
  keys include the learning generation; disabled and shadow packets are unchanged. Evaluation keeps
  three tiers apart with standard-library paired statistics, a labeled test-only runner and an
  authoritative end-to-end batch import; the end-to-end runner gains `learned_*` arms with isolated
  libraries and oracle-adjacent observation recording. An offline fixture demo (`evals/learning`)
  exercises the whole path; no live agent evaluation was run and no benefit is claimed.
- Retrieval reads stack-trace frames (`File "...", line N, in f`, `at f (path:line:col)`) as frames:
  the longest suffix of the frame path that exists in the index votes in the path retriever (the
  innermost frame counts double, never pinned), the frame's line anchors the excerpt and its
  function name is a symbol (`frames`, `full-frames`). Admitted files over the 256 KiB read limit
  now get a structural record (definitions, imports, calls, no text or terms retained), so a
  central module is matched by the symbol it defines instead of by its name alone; it is still
  never excerpted (`structural_records`, `full-structure`).
- Unify task experience: the repository memory layer and the deep index share one SQLite experience
  store, one event shape and one `experience` voter. `repository_memory.py record|correct|forget|prune`
  and `repository_intelligence.py experience ...` write the same records; the memory vocabulary
  (`partial`, `failed_verification`, ...) maps onto the shared outcome categories, which gain
  `reverted_or_invalidated`; corrections are either a path verdict or a superseding outcome. The
  deep index no longer attaches experience on its own (`experience.use` in
  `repository-intelligence.json` is superseded by `experience.retrieval`). Experience recording and
  retrieval are on by default; episodic and semantic retrieval stay in shadow mode; with nothing
  built or recorded a packet is unchanged. `evals/retrieval/chronology.py` replays several
  repositories with pooled, repository-block bootstrap intervals.
- Add optional, opt-in repository memory (`repository_memory.py`, `repo_history.py`, `memory_experience.py`,
  `docs/repository-memory.md`, `MEMORY.md`, `/agent-memory`, `$agent-dispatcher memory`): an episodic
  layer (eligible commits from HEAD's bounded ancestry through one hardened Git wrapper, admitted
  changed paths with both sides policy-checked, sanitized messages, issue/PR references, reverts,
  merge commits as metadata only, bounded Python symbol history, conservative rename lineage,
  explainable hotspots), a semantic layer (deterministic module records with evidence manifests and
  optional model summaries keyed to their evidence, stale on change, never generated at query
  time), and an experience layer (passive, bounded task observations; `verified_scoped_success`
  only from a current verification receipt; corrections supersede, forgetting and pruning are
  logical deletions). Every layer has separate build, retrieval (`off`/`shadow`/`on`) and
  recording controls under one master switch in a settings file outside every project; with it
  off, packets and rankings are unchanged. At query time a deterministic gate (`use`,
  `use_limited`, `ignore_weak`, `ignore_stale`, `ignore_unresolved`, `unavailable`,
  `budget_exhausted`) feeds bounded candidates into the existing fusion as `memory_*` voters,
  only through current admitted files; the packet gains a `memory` section trimmed before any
  excerpt, `retrieval.py explain` a `MEMORY` section, and `examine-commit` a re-authorized,
  bounded patch view by indexed id only. `evals/retrieval/run.py --memory` adds `Hit@k`,
  `All@k` (RepoMem's Accuracy@k), target-count strata and memory arms; `chronology.py` replays a
  repository in commit order with leakage checks and oracle-labeled experience arms.

- Add an explicit, persistent deep repository index (`repository_intelligence.py build|refresh|status|explain`,
  `repo_store.py`, `repo_builder.py`): a complete admitted inventory in deterministic batches with
  checkpoints and resume, per-file records and corpus statistics, stable symbol identities with
  content fingerprints and rename aliases, relationships labeled by method and status, bounded
  `HEAD` history with a recorded horizon, atomic generation publication in the private state
  directory (SQLite, standard library), fast metadata or strict content refresh that reconciles
  the working tree and sweeps only after a complete enumeration. The context helper uses a
  published index automatically (`repository_intelligence.index` in the packet; `--repository-index off`
  restores the previous behavior), ranks verified files beyond the scan's caps and reads them on
  selection, withholds stale evidence, and upserts changed records under the existing cache write
  scope. Optional, off by default and switched separately in the user's own settings file: an
  onboarding Explorer (`explore`, `exploration.py`) that lets a model ask validated read-only
  operations of the index and stores evidence-backed claims labeled as inferences, and explicit
  task experience (`experience record|list|show|correct|forget`, `experience.py`) with fixed
  outcome categories, corrections, forgetting and a bounded half-weight memory retriever. The
  offline retrieval benchmark gains a chronological four-condition sequence mode and the
  end-to-end runner gains `indexed` and `warm_experience` conditions; no live comparison was run.
  See docs/repository-index.md.
- Order the project map's eight-fact task view by the retrieval engine's file ranking instead of
  counting request words in each fact. The context selector hands the map its ranking with
  excerpted files last; each unnamed file contributes one fact, a ranked file appears even when
  no request word occurs in its facts, and `tester`, `debugger` and `reviewer` get up to two
  test commands pinned first (`architect`: decisions). Import lines are facts only for a module
  that defines nothing, one per module (manifest dependencies remain), a documented command is stored once from its first source in
  priority order, and the definition regex recognizes the same keywords as the retrieval index
  (`fn`, `trait`, `impl`, `module`, `namespace`, Go receivers). `evals/retrieval/run.py --map`
  measures the view (`hit`, `gain`, `packet`); map views and import facts from before this change
  are not comparable, and existing maps refresh their withdrawn import facts on the next
  maintenance. Standalone `project_map.py show` still ranks by request words.
- Move the project map and structural graph out of the working tree. Both now persist to
  owner-only private state at `~/.cache/agent-dispatcher/state-v1/<project id>/` (under an
  absolute `XDG_CACHE_HOME` when set), keyed like the parser cache and refused if that
  location would fall inside the project. Index maintenance therefore no longer creates
  `.agent-dispatcher/`, appears in `git status`, or shows up as an out-of-scope change in a task
  audit; packets report `project_read_only: true` even when an index was persisted. An
  in-project `.agent-dispatcher/project-map.json` or `project-graph.json` from an older release
  is still validated and read when no private copy exists, counts as the existing map for
  `build`/`refresh`, and is never rewritten or deleted. Cache write scope is unchanged: the
  logical targets keep their names, and a preview, a restricted or read-only task, or a
  `--writable-path` list that omits them still defers persistence. The end-to-end warm-index
  setup now requires a byte-identical workspace and proves persistence from packet evidence
  (`index_evidence_digest`); warm results from before this change are not comparable. The
  test suite redirects this state to a temporary `XDG_CACHE_HOME`.
- Replace flat "request words -> files" scoring with a repository-intelligence retrieval layer
  (`repo_index.py` facts, `retrieval.py` engine, `context_budget.py` packet). Requests are analyzed
  into paths, dotted modules, symbols, identifiers, concepts and ignored generic words; path,
  rare-term, BM25, symbol-definition, symbol-reference and quoted-literal retrievers vote through
  reciprocal rank fusion (k = 20); the strongest files pull in import, call, test and git
  co-change (Jaccard) neighbors under hop, neighbor, candidate and in-degree bounds; and a budget
  step keeps per-file reasons, matched symbols, relationships and bounded excerpts. Every
  candidate keeps its provenance. `--retrieval legacy` restores the old scorer, which is also the
  automatic fallback; `--explain`, `retrieval.py explain|explain-query` show why each file was
  chosen; `--max-files` and `--max-bytes` tighten the budget. Optional bounded explorer requests
  (`retrieval.py expand`, or `--retrieval full+explorer`) are answered from the index only.
- Exclusions stay ahead of retrieval: the index is built only from texts the scan admitted, so
  symbols, edges, history, explorer requests, excerpts and explain output cannot reach an
  excluded or credential file. `git log` paths outside the universe are dropped before anything
  is counted. New per-file index records and the policy-filtered history live in the existing
  private parser cache, never in the project, and only changed files are re-indexed. Files over
  the 256 KiB read limit can now be ranked by name, imports and history without being read.
- Add an offline file-localization benchmark (`evals/retrieval/`): 600 tasks mined from real
  changes in sqlglot, pip, networkx and zod, committed as text-free manifests with a
  deterministic train/validation/test split, Recall@1-10, MRR, MAP, context size, useful context
  density, latency, cumulative and leave-one-out ablations, candidate overlap, a failure report
  and a regression check. Held-out Recall@8 rose from .368 to .783 and MRR from .206 to .604,
  with retrieval taking about 70 ms instead of 4.8 s per task; graph expansion, git history and
  the model-free explorer did not measurably improve ranking. See `docs/retrieval-benchmark.md`.
- Two retrieval switches, both off: `fusion_groups` (correlated retrievers fused among themselves
  and voting once) and `graph.multi_edge` (`sum` / `soft` over every edge kind between a seed and a
  neighbor). Swept on the development split and declined as defaults; numbers in
  `docs/retrieval-benchmark.md`.
- Query analysis no longer reads a prose parenthetical as a function call (`checkout (see …)` had
  made `checkout` a weight-3 symbol that pulled CI workflows into the seeds) and ignores process
  words task prompts carry (`welcome`, `finish`, `summarize`, `verify`, `claim`, `offline`, …).
  Held-out benchmark: R@1 .363 -> .376, R@10 .791 -> .808, MRR .604 -> .614, no repository worse.
- Keep the compact context packet under the host's inline tool-result limit. Claude Code
  replaces a Bash result over 30,000 characters with a 2 KB preview; the standard packet
  budget (8,000 tokens, about 32 KB) sat just past that, so in the big-repository
  end-to-end evaluation 16 of 18 dispatcher trials received a preview of packet metadata and
  none of the excerpts or guidance. The default packet now serializes under 28,000 characters
  (`budget.max_chars`, excerpts trimmed from the lowest-ranked file first); an explicit
  `--packet-tokens` budget is honored unchanged, and the skill tells the host to read a
  saved-output file if a preview ever appears.
- Add optional, opt-in LLM-assisted retrieval (`llm_retrieval.py`, `docs/llm-assisted-retrieval.md`):
  model-written role representations of source files, generated once per file content from static
  evidence plus bounded source, validated against the index (unsupported symbols and interaction
  targets are dropped), stored privately outside the project and searched locally by a new
  `role_summary` retriever that votes in rank fusion; and a bounded candidate reranker over opaque
  ids with `rrf`, `weighted`, `replace` and seed-only integration, pre- or post-graph placement,
  conditional (`ambiguous`) and shadow modes. Providers are configuration (`openai`-compatible,
  `anthropic`, local `command`); keys come from environment variables. It is enabled only by the
  user's own settings file, never by a project; excluded files never reach a model, a store, a
  candidate list or debug output; every model failure falls back to the deterministic ranking,
  which is bit-identical on the held-out benchmark when the layer is off. `retrieval.py explain`
  shows `role_summary` and `llm_rerank` evidence (`--no-llm` to compare); the benchmark gains
  `--llm-settings`, `--llm-index`, `--refresh-llm`, `--recent` and `evals/retrieval/llm_report.py`
  (candidate recall versus reranking quality, rank movement, task categories, conditional-policy
  replay, bootstrap intervals, index- and query-time cost).
- Project-map task views no longer record `from __future__` imports and list definitions before
  import declarations.
- Pass the request to the context helper as a single-quoted `--task='...'` argument, and inline
  validators as `python3 -B -c`, instead of stdin heredocs. Claude Code refuses heredocs whose
  body contains braces (a denial in `dontAsk`, an approval prompt interactively), so requests
  quoting code or JSON lost the helper; both dispatcher trials of a sqlglot smoke run hit it. The
  eval activity parser now attributes multi-line quoted arguments to one helper call.
- Let the doctor helper take the evidence snapshot inline: `--evidence='{...}'` parses the JSON
  from the argument, so DOCTOR.md no longer documents a heredoc for either host. A file path and
  `-` for standard input still work.
- Scale the project map and structural graph to repositories of about 1,000 source files
  (graph: 1,000 sources, 30,000 nodes, 36,000 edges, 16 MiB; map: 1,000 sources, 6,200 facts,
  4 MiB). Both stop at their byte limit instead of failing to save. The previous 80-source cap
  kept 240 of about 17,000 nodes on a 604-file repository. `project_map.py show`, `build` and
  `refresh` print at most 50 facts without `--task`, with diagnostics first.
- Stop caching per-file syntax trees. Decoding them took 7.5 s where parsing took 1.3 s on a
  585-file corpus, and they crowded the resolved graph out of the 64 MiB host cache. Warm
  preparation on that corpus: 19.1 s with tree caching, 3.3 s without.
- Skip text files over 256 KiB the way binary files are skipped: listed as excluded, never
  indexed, and no longer marking the scan partial. One large generated file used to block map,
  graph and parser-cache persistence for the whole repository.
- Let the context helper decide cache writes: maintenance also defers for roles whose tool
  posture is read-only (`read_only` in the role catalog), and the no-edit guard recognizes more
  wording (alter, fix, implement, apply, hands off, nothing else should change, no new files).
  Agents add `--map-preview` only for edit limits the helper may miss.

- Reuse unchanged redacted sources and map facts through a private authenticated
  host cache populated by unrestricted map maintenance. Preserve exclusions, scan limits,
  read-only and write-scope restrictions; reuse unchanged graphs and resolve cross-file edges
  when scoped source inputs change. Report actual
  source and graph reuse and provide `--no-parser-cache` for a full source reread and extraction.
- Add an explicitly built local project map with source fingerprints, stale-fact exclusion,
  read-only context enrichment, and matching Claude/Codex commands.
- Expand stock-versus-dispatcher evaluation fixtures for multi-file retrieval, stale project
  knowledge, and source-backed architecture discovery, with private acceptance checks.

- Add local, read-only context selection with ranked code passages, source locations,
  bounded scanning and explicit exclusions for Claude Code and Codex.
- Reduce dispatcher entrypoints and the concise context procedure to at most 6 KiB each,
  with roles, controls, delegation and advanced context guidance loaded on demand.

- Stage Claude manual installations before replacing live files, with rollback for failed
  replacements and handled interruptions. Preserve recovery backups and a path mapping if
  rollback cannot finish; report post-commit cleanup failures accurately.
- Add `doctor` / `/agent-doctor` for read-only package health, full skill/tool/MCP inventory,
  session-evidence reconciliation, and role/project-based setup recommendations. Keep unknown,
  configured, exposed, connected, disabled, and retired capabilities distinct. Bundle the
  offline helper in both host packages and add recovery/doctor regression coverage.

- Add a Codex adapter with one discoverable dispatcher skill, all shared roles and supporting
  guides, native role/context/decision controls, a self-contained plugin export, and an owned
  install/update/uninstall path. Add opt-in Codex session activation with separate user-owned
  state and native hook trust review. Extend CI with Codex packaging and lifecycle regressions.
- Add GitHub Actions checks for Python 3.10–3.14 on Linux, Python 3.14 on macOS, generated-file
  drift, installer lifecycle, shell scripts, and workflow syntax. Add full-history and current-file
  Gitleaks scans, CodeQL for the public repository, and Dependabot updates for pinned Actions.
- Refuse malformed installation settings, symlinked targets, and manifest entries outside the
  owned command directory before modifying the installation. Preserve unrelated commands and
  hooks on uninstall, quote paths safely, and migrate older hook registrations on update.
- Ignore malformed decision configuration and require boolean scope flags and finite, bounded
  numeric settings. Recover non-object configuration in the mode command. Document the actual
  environment-over-project precedence.
- Parse provider URLs before allowing the loopback HTTP exception and remove transport-supplied
  error text from credential-bearing requests. Correct the claim of a hard response deadline;
  socket timeouts and late-result rejection do not guarantee an overall wall-clock limit.
- Detect missing and removed generated artifacts, and resolve build paths consistently when
  a checkout is accessed through a symlink. Add release regressions for the above behavior.

## 2.3.4 — 2026-09-19

2.3.3 claimed the silent-no-op class was addressed by running the hook. It was not, and the
claim is withdrawn.

Running the output catches a hook that is *broken*. It cannot catch an edit that never applied,
because the old behaviour was working — nothing is broken, so nothing fails. Moving the shell
into `HOOK.template.sh` did not fix it either: `build.py` still substitutes into that file, and
a `.replace()` whose search string stops matching misses exactly as quietly against a `.sh` file
as against an f-string. The file extension changes nothing about that.

### The actual fix

`sub()` and `render()` in `build.py`. A substitution that matches nothing is now fatal:

    build.py: {{ROLEZ}} is not in the text it was about to replace —
    the substitution would have silently applied to nothing

That is the one place the miss *can* be noticed, because it is the only place that knows a
replacement was intended. The artifact cannot show it — it keeps its old content, so the drift
check compares it against a rebuild that also kept the old content, and the two agree. Every
template substitution in the generator now goes through `sub()`.

It found four of these the moment it was added. `write_router` had been substituting
`{{SKILL_COUNT}}`, `{{EXTERNAL_COUNT}}`, `{{RECIPE_COUNT}}` and `{{MCP_COUNT}}` into
`SKILL.template.md`, which has not contained any of them for several releases. Four calls
quietly doing nothing, across eight commits, with a green suite the whole time.

### Also

- **`HOOK.template.sh`** — the perpetual-mode hook is a shell file rather than a Python
  f-string. That does not make failed edits louder, and the docstring now says so; what it does
  remove is the second escaping layer that produced a `printf` rendering its own escape
  sequences. It was also untracked while `build.py` hard-required it — a fresh clone would have
  died in `install.sh` before installing anything. A new check fails if any template the build
  reads is present locally but not committed, which is the only way to catch that: it builds
  fine for whoever has the file.
- **The preamble budget check was measuring the wrong thing.** It scraped the generated script
  for heredocs and counted those, missing ~1,000 bytes of `printf` output, and — being a regex
  over generated text — it would have passed at *zero bytes measured* if the heredoc marker were
  ever renamed. It now measures the hook's real stdout, with a lower bound so empty output fails.
- **Frontmatter quoting.** Values were emitted with an f-string and parsed by stripping the outer
  quote pair, so `name: "The "Fixer""` round-tripped through this repo agreeing with itself while
  being invalid YAML to anything else. `json.dumps` on the way out, `json.loads` on the way in,
  and an unescaped quote is now rejected with the fix in the message.
- **`--uninstall` deregistered the hook after deleting the script**, leaving `settings.json`
  starting a file that was gone. It also dropped the whole `SessionStart` entry, taking any hook
  of the user's own that shared it. Both fixed, and both pinned by tests that run the real script.
- `install.sh`'s two embedded Python blocks had never been checked to be valid Python, and the
  install and uninstall paths had never been executed by any test. Both now are.

### On the method

Every fix above came from an adversarial review that was told to verify rather than trust, and
several findings were refuted on inspection. The two that mattered most — the no-op guard and
the budget check measuring its own source — were confirmed by reintroducing the defect and
watching the suite go red. An assertion nobody has watched fail is a guess about what it covers.

## 2.3.3 — 2026-09-19

The SessionStart hook was checked by reading it. It is now checked by running it.

### Added

- **17 hook behaviour checks** in `test_build.py`, executing the real script against a temporary
  config dir and project dir with a JSON payload on stdin, the way the runtime invokes it. They
  cover the whole arm/silence matrix: a clean install arming nothing, global arming, session and
  project silencing beating a global arm, one silence not affecting another session or project,
  and the two-step allow-list.

  Three of them exist because of specific failures that every text-level check passed happily
  through:

  - **The escaping one.** A `printf` whose escape is wrong renders `\n` literally instead of a
    newline. The generator is valid Python, the shell script is valid bash, the drift check
    passes because the file matches what the generator produces — and the injected preamble is
    garbage. Caught now by asserting the rendered output contains no literal escape sequences.
    Reintroducing that bug fails the suite.
  - **The silent no-op.** An edit to the generator whose search string does not match leaves the
    artifact unchanged, and drift *passes*, because nothing changed. Running the output catches
    the ones that change behaviour, and only those. Moving the shell into `HOOK.template.sh`
    does not help here at all: a `.replace` against a `.sh` file misses exactly as quietly as one
    against an f-string.
  - **The security one.** The two-step project allow-list is the reason a cloned repository
    cannot switch your sessions into perpetual mode. That property had no test. Removing the
    allow-list check from the generator now fails two checks by name.

Each of the three was verified by reintroducing the defect and watching the suite go red, rather
than by assuming the assertion covers it.

### Fixed

- **Every substitution in `build.py` now refuses to be a no-op.** `sub()`/`render()` raise when
  the search string is absent, and `marked()` raises instead of returning the text when a
  `<!-- name:start -->` region is missing. This is the actual fix for the class above, and the
  only place it can be fixed: the generator is the one component that knows a substitution was
  intended. Nothing downstream can tell "the artifact is correct" from "the artifact was never
  touched" — the drift check compares stale content against a rebuild that is equally stale.

  It found four dead substitutions on its first run. `write_router` had been replacing
  `{{SKILL_COUNT}}`, `{{EXTERNAL_COUNT}}`, `{{RECIPE_COUNT}}` and `{{MCP_COUNT}}` in
  `SKILL.template.md` for several releases after the template stopped containing them. Removed.

  What this still cannot detect: a change someone meant to make and never wrote. That is not
  reachable from anything in the repository.

- **Role frontmatter is emitted and parsed as YAML, not assembled with literal quotes.**
  `write_roles` was building `name: "{value}"` by hand, so a `"` inside a template value produced
  `name: "The "Fixer""` — not YAML. It round-tripped clean: `read_frontmatter` stripped the outer
  pair whenever the first and last characters matched, handed the original string back, and the
  drift check compared a rebuild that made the same mistake. The generator now emits each quoted
  value with `json.dumps` (a JSON string is what YAML means by a double-quoted scalar) and
  `read_frontmatter` parses one with `json.loads`, so an unescaped quote in a template fails the
  build by name instead of shipping. No template carries a quote today, which is exactly why
  nothing static could see it: the check emits a quote-bearing role and parses the file back.

## 2.3.2 — 2026-09-19

Perpetual mode was documented as a set of files to `touch`. It was always a set of commands.

### Changed

- **The README leads with the commands.** `/agent-dispatcher on`, `on here`, `off`, `off here`,
  `off everywhere`, `status` — a six-row table of what you want and what to say. The flag files
  move into a collapsed section for anyone scripting it, which is the only audience that ever
  needed them. Nobody should have been typing `touch ~/.claude/.agent-dispatcher-active`; the
  skill has run that for them since 2.0, and the README simply never said so.
- **The scopes have canonical words.** `on here`, `off here` and `off everywhere` are defined
  forms rather than phrasings the router happened to match. Bare `off` still means *this
  session*, because that is what people mean mid-conversation, and the wider scopes now have to
  be spelled out so nothing global is disarmed by accident.
- **`/agent-dispatcher status` actually reports something.** It was an `ls` on one flag file. It
  now covers global arming, project arming, project and session silencing, and whether the
  SessionStart hook is installed at all — including the state that looks armed but is not: a
  project flag with no matching entry in the allow-list. Arming without the hook does nothing,
  and that was previously invisible.
- The perpetual-mode preamble the hook injects each session now tells Claude that the user says
  `/agent-dispatcher off` and Claude runs the command, rather than reading as instructions to
  hand over. Same mechanism, no longer phrased as homework.

The two-step project allow-list is unchanged and still deliberate: a flag file alone would let
any repository you clone arm your sessions, so the list lives in your own config directory where
a `git clone` cannot reach it. The README now explains that where someone deciding whether to
trust it will read it, rather than as a footnote to a table of shell commands.

## 2.3.1 — 2026-09-19

Two deletions, both because Jev is off by default and carrying weight for a disabled feature is
the wrong trade.

### Removed

- **The Vercel AI Gateway transport.** Vercel documents evaluation as available through their
  TypeScript SDK only, so it targeted an endpoint with no published REST contract, and with no
  gateway account it was never verified against a live provider — unit tests against a mock
  were the whole of its coverage. An unverifiable integration that handles a credential is the
  weakest thing to carry for a feature nobody should currently enable. TypeSafe's own HTTP API
  is now the only transport, and it is the only one either of them publishes a contract for.
  `decision/providers/` remains the seam if another route is worth adding.
- **93 lines of `docs/jev.md`.** The architecture, permission-boundary, credential-handling and
  results sections earn their space. The setup and troubleshooting depth did not, for a document
  that tells you not to enable the thing it documents.

### Changed

- README and `docs/jev.md` now say plainly that inside a Claude Code session the dispatcher
  always *is* already running, so the model turn Jev saves is not actually saved. Its remaining
  case — latency and cost — is for a standalone router, a pre-filter or a batch job, not for the
  path this pack ships on. That was implied before and is now stated.

## 2.3.0 — 2026-09-19

Finished the comparison and let it decide. Jev now installs inert.

### Measured

Three engines, identical fixtures, every decision measured for all three. Registry
`89baa5fa0e0c`:

                              baseline      jev           claude
  agent top-1                 23 / 162      143 / 162     158 / 162
  acceptable route            29 / 162      154 / 162     162 / 162
  near-neighbour top-1         6 / 54        49 / 54       53 / 54
  ambiguous top-1              3 / 27        17 / 27       25 / 27
  skill precision / recall    0.31 / 0.56   0.68 / 0.71   0.74 / 0.90
  tool precision / recall     0.15 / 0.23   0.65 / 0.97   0.69 / 0.95
  median latency              0 ms          358 ms        not comparable

`claude` is the production default path — the model reading the dispatcher's own catalog and
rules, replayed from recorded answers. It **matched or beat Jev on every decision**: decisively
on routing, clearly on skill recall at slightly better precision, and to a tie on tools, where
20 cases cannot separate a 0.04 gap.

Both engines crush the keyword floor, which is roughly what selecting from a loadout rather
than from the task gets you. 2.2 set its defaults against that floor. That was the wrong
comparison; this is the right one.

### Changed

- **Every decision scope is off by default.** Jev is installed, wired, tested and not called.
  Quality is no longer a reason to enable it — the default path is as good or better and costs
  no extra call, because the dispatcher is already running when it decides. Latency and cost
  still are: ~360 ms and a fraction of a cent against a full model turn, which is a real trade
  for a high-volume automated path, a latency budget, or anywhere the dispatcher is not in the
  loop. `AGENT_DISPATCHER_DECISION_SCOPES=skills,tools` turns on what you want.
- `status` says so plainly rather than looking broken: *idle — credential configured, no
  decision scope enabled*.

This is the architecture working. It was built so each decision could use whichever mechanism
the evidence supports, and the evidence came back for the default path. The integration stays
because the finding could change — a metadata rewrite, a new model version, a different fixture
set — and because the harness that produced this answer is now the thing that would notice.

### Added

- `replay.py` now serves skill and tool selections as well as routes, and distinguishes "not
  measured" from "selected nothing" rather than scoring a question nobody asked as a zero.
- `evals/decision/routes-claude.json` carries all three decisions for all 206 fixtures, with
  its method written down.

### Known holes

Unchanged and worth repeating: no end-to-end comparison exists, so nothing here shows a better
decision produces better work. The Claude column is a reconstruction — a focused subagent per
case, no competing work — which cuts against the conclusion rather than for it. And nothing
measures cost or throughput at volume, which is the case for Jev that remains.

## 2.2.1 — 2026-09-19

Ran the comparison v2.2 said had not been run, and changed a default because of what it said.

### Measured

Three engines, the same 162 routing fixtures, registry `89baa5fa0e0c`:

                              baseline      jev           claude
  agent top-1                 23 / 162      142 / 162     158 / 162
  acceptable route            29 / 162      153 / 162     162 / 162
  near-neighbour top-1         6 / 54        49 / 54       53 / 54
  ambiguous acceptable         9 / 27        26 / 27       27 / 27
  skill precision / recall    0.31 / 0.56   0.68 / 0.73   not measured
  tool precision / recall     0.15 / 0.23   0.66 / 0.97   not measured
  median latency              0 ms          357 ms        not comparable

`claude` is the production default path — the model reading the router's own catalog, replayed
from recorded routes. **It beats Jev on agent routing and is not close**, winning hardest where
the decision is hard: 53/54 near-neighbour against 49/54, 25/27 ambiguous against 17/27, and
162/162 acceptable against 153. It is also free in production, because the dispatcher is already
running. Jev wins skill and tool relevance by a wide margin.

### Changed

- **Agent selection is off by default.** The dispatcher keeps routing, as it always did. Switch
  it on with `AGENT_DISPATCHER_DECISION_SCOPES=agent,skills,tools` if your situation differs — a
  latency budget, a high-volume automated path. The abstraction exists precisely so each decision
  can use the mechanism the evidence supports, and this is that being used.
- Skill and tool relevance stay on: precision 0.31 → 0.68 for skills, with the share of
  selections carrying a known-irrelevant id falling 0.36 → 0.01, and 0.15/0.23 → 0.66/0.97 for
  tools.
- The candidate roster now includes `dispatcher`, which it wrongly excluded. `SKILL.md` keeps it
  in the catalog the model reads, so leaving it out asked the engines a different question than
  the default path answers and made five fixtures unwinnable for everyone.

### Added

- `evals/decision/replay.py` and `run.py --engine claude --routes <file>`: score decisions made
  out of band, so the production default path can be compared at all. Claude is the model running
  the dispatcher, not a service the harness can call.
- `evals/decision/routes-claude.json`: one recorded run of all 162 fixtures, with its method
  written down, so the comparison is repeatable without re-spending.
- `run.py --engine` is repeatable and takes `all`.

## 2.2.0 — 2026-09-19

Decision Engine v1. Routing answered *who*; the context engine answered *what with*. This release
names the layer that makes those bounded choices, and makes it swappable.

```text
request → decision engine → agent + skills + tools → context plan → context engine → specialist
```

The default path is unchanged. A clean installation needs no account, no key and no network, and
behaves exactly as 2.1 did.

### Added

- **A generic Decision Engine contract** (`decision/`) — `choose_agent`, `choose_skills`,
  `choose_tools`, plus `rank_context` and `evaluate_verification` declared for later. The context
  engine consumes `AgentDecision`/`SkillDecision`/`ToolDecision` and cannot tell which engine
  produced them, so a future reranker or local classifier arrives without reshaping anything above
  it. Strongly typed inputs and outputs, standard library only, no new dependency.
- **`DefaultDecisionEngine`** — the behaviour that already existed, expressed in the contract. It
  does not route: `SKILL.md` and the model still do, as always. Skills come from the loadout's
  `skills_core` and `skills_preferred`, tools from its `mcp_recommended`.
- **`JevDecisionEngine`** — optional, for users who supply their own credentials. One typed
  `choice` over the role roster with a confidence, one `noul` per candidate skill and per
  registered server. Two requests per task, not thirty-two; one when the user named a role.
  Providers for TypeSafe's documented HTTP API (default) and the Vercel AI Gateway, plus a mock.
- **Three modes** — `off` (no credential, no request), `auto` (the default: use it when it is
  there, fall back and record a diagnostic when it is not), `required` (fail clearly instead of
  falling back, so evaluation is controlled). `AGENT_DISPATCHER_OFFLINE=1` forces the default
  engine for local-only work.
- **`/agent-decision`** and `python3 -m decision status | mode | plan` — inspect and switch. Never
  prints a credential, never asks for one in chat.
- **`evals/decision/`** — 162 routing fixtures across all 27 roles (obvious, near-neighbour,
  ambiguous with multiple acceptable routes, and negative), 24 skill-selection and 20
  tool-relevance fixtures scored for precision as well as recall, and a harness that compares
  engines on identical inputs and reports observed accuracy per confidence band.
- **`test_decision.py`** — mode behaviour, fallback on timeout / 401 / 429 / 529 / malformed body /
  unknown id / low confidence, `required` erroring on each of those, forced-role precedence, the
  permission boundary, what a request is allowed to contain, and provider wire handling. No
  network, no credential, no cost.
- **[docs/jev.md](docs/jev.md)** — architecture, setup, modes, what is actually sent, cost
  responsibility, the permission boundary, the measured results and the calibration behind the
  thresholds.

### Changed

- `catalog/loadouts.json` now carries each role's `summary`, `use_when`, `not_for` and `tags`.
  That is the routing metadata, and it lives in the registry the build already generates so the
  decision layer has one canonical candidate source and no registry of its own.
- The context plan schema gains `selected_by` (`forced` · `recipe` · `default` · `jev`) and
  `confidence` on agents, skills and tools, plus a `decision` block recording the engine, whether
  it fell back, and the registry digest. Schema version 2.2.0.
- `CONTEXT.md` gains section 0, the decision engine, and says in three places that relevance,
  availability and authorization are three different facts.
- `/agent-context` names the engine that answered, shows a fallback rather than hiding one, and
  keeps the full candidate ranking behind `explain`.
- `install.sh` installs the engine and the registries it reads, and runs `test_decision.py`. It
  stays non-interactive and never asks for or writes a credential.

### Measured

162 routing fixtures against `jev-latest`, registry `89baa5fa0e0c`:

| | Lexical baseline | Jev |
| --- | --- | --- |
| Agent top-1 | 23 / 162 | 138 / 162 |
| Acceptable route | 28 / 162 | 150 / 162 |
| Near-neighbour top-1 | 6 / 54 | 48 / 54 |
| Skill precision / recall | 0.31 / 0.56 | 0.68 / 0.73 |
| Tool precision / recall | 0.15 / 0.23 | 0.64 / 0.97 |
| Median latency | 0 ms | 366 ms |

The baseline is a keyword floor, not what a real installation does — production hands routing to
the model, which cannot be scored offline. Confidence proved informative (0.98 observed accuracy
above 0.90, collapsing to 0.38 below 0.70), so the thresholds in `decision/config.py` are derived
from that table rather than guessed. No end-to-end comparison has been run.

### Security

- No credential is committed, embedded or shipped. The key lives in the environment; configuration
  exposes the variable's name and whether it is set, never its value; the provider reads it at
  request time and does not store it.
- A decision cannot authorize. No type has a field that could carry one, `assert_no_authorization()`
  raises if one appears, and the suite runs it against "deploy to production" and "delete the
  production database" with the relevant tool at 100%.
- A request carries the scrubbed, capped task text, detected technology names and compact registry
  metadata. Not repository source, file contents, environment or conversation history.
- Every id an external engine returns is validated against the registry before it reaches a plan,
  and is character-filtered before being echoed into a diagnostic.
- The transport refuses a credential a header cannot carry, refuses a non-https base URL, and
  refuses redirects — urllib's default handler replays `Authorization` across hosts on a 302.
  Exceptions from below the provider are replaced rather than wrapped, and `required`-mode
  errors are raised `from None`, so no traceback can quote a request header.
- The response is size-capped and read against a wall-clock deadline; `timeout` alone is
  per socket read and does not bound the exchange.
- The project config file can no longer set the diagnostics log path — a cloned repository
  should not choose a file to create and append to — and a bad value in it is dropped rather
  than raised.
- The mock transport is not reachable from configuration. A test double a user can select is a
  test double that can fabricate a plan and have it rendered as a real one.

## 2.1.0 — 2026-09-19

Context Engine v1. Routing already answered *who does this work*; this release answers *what are
they given*, and makes that decision inspectable.

```text
request → routing → context plan → context engine → specialist → verification
```

### Added

- **Context plan** ([`catalog/context-plan.schema.json`](catalog/context-plan.schema.json)) — a
  compact schema for what an agent needs before it starts: the role and why, the capabilities, the
  skills and why each, the detected stack, what to retrieve, which tools materially help, what is
  actually *known* about authorization, the verification contract, the budget, and the diagnostics
  for what could not be established. It deliberately has no `steps` field — `test_build.py` fails
  if one appears. A context plan says what is needed; an execution plan says what will be done, and
  the specialist owns the second.
- **Context engine** (`CONTEXT.template.md` → `skills/agent-dispatcher/CONTEXT.md`, with the signal
  reference split into `SIGNALS.md` beside it) — the procedure:
  resolve the agent, resolve skills by capability, detect the project, search and rank the
  workspace, resolve tools and known permission, fix the verification contract, enforce a budget.
  Read on demand, and explicitly proportional: a rename gets no plan, one known file gets four
  lines, the full plan is for unfamiliar work and for fan-outs.
- **Signal registry** ([`catalog/signals.json`](catalog/signals.json), 50 entries) — every
  `skills_if_<condition>` bucket now has a definition. `project` signals are decided by file globs
  and `<glob> contains <literal>` checks; `task` signals by phrases in the request; `runtime`
  signals by what the session actually provides. Each carries `when_unknown` — the specific wrong
  inference to avoid — and the default is always *do not load the skill, and say the condition was
  not established*. Rendered into `skills/agent-dispatcher/SIGNALS.md`, because an install never
  receives `catalog/`.
- **Workspace retrieval** — lexical, path, symbol-shaped and structural search, plus one bounded
  hop along local imports. A transparent additive ranking whose score is explicitly ordinal, a
  noise list, deduplication, a 3–12 artifact cap by task size, and provenance on every retained
  item: path, why, match type, rank, and symbol and line range when known. No embeddings, no index,
  no code graph.
- **`task_signals`** on all 79 skill manifests — three to seven short phrases a user would actually
  write when that skill is the right one. `test_build.py` rejects any phrase shared by more than
  two skills, because a signal that fires everywhere routes nothing. Rendered into `INDEX.md`,
  alongside a map of the capabilities with more than one provider, so the substitution rule is
  actionable after an install — `catalog/` is not installed.
- **`retrieval_hints`** on all 27 role templates — the two to six kinds of artifact that role reads
  first, seeding the search before the task's own nouns do. Rendered into each role file, which
  also now carries the detection rule for every conditional bucket it declares.
- **`/agent-context`** — renders the plan for the current request without doing the work.
  `explain` adds why this role over the near-miss, why each skill and tool, and one deliberate
  exclusion; `verbose` adds candidates, excluded files and the budget split.
- **Documentation** — [`docs/context-engine.md`](docs/context-engine.md), plus a section in
  `docs/security.md` on retrieved context as untrusted input.

### Changed

- **`build.py`** refuses to build on a `skills_if_<condition>` bucket that `catalog/signals.json`
  does not define, a signal no role uses, a skill with no `task_signals` or one whose signals are
  not short lowercase phrases, a role with no `retrieval_hints`, a project signal with no way to
  decide it, a runtime signal pretending to be decidable from the repository, and a malformed
  content check.
- **`build.py`** also refuses two signals decided by identical evidence, a plan-schema field with
  no `title` to render, and a role whose core + preferred plus its largest conditional bucket
  exceeds seven — conditional skills compete for the same one-to-five slots rather than forming a
  second always-on tier.
- **`test_build.py`** adds the context-engine block: placeholders resolved, signal coverage both
  ways, the worked example **validated** against the plan schema by a small built-in checker
  (required fields, enums, types, no stray keys — no new dependency), no signal carrying a
  permission or tool field, no signal without a `when_unknown`, every role seeding retrieval, and
  byte caps on the artifacts whose cost is paid without the agent choosing to read them: the
  perpetual-mode preamble, the router, `CONTEXT.md`, `SIGNALS.md` and `INDEX.md`. The two
  hand-written role counts in `.claude-plugin/` are now checked too.
- **`SKILL.md`** gains a short *Context before execution* section with the proportionality rules,
  and its handoff contract now says each subagent gets its **own** context plan — objective, scope,
  accepted decisions, artifacts, acceptance criteria, expected verification, open questions —
  rather than the parent's conversation.
- Schema version `2.1.0`.

### Honest about the runtime

No tool or API enumerates installed skills, lists configured MCP servers, or reads the active
permission mode — and *not inspectable by API* is not the same as *unknowable*. A pack skill is
established by `**/<id>/SKILL.md`; a host skill by the session's own skill listing, which carries
every loaded skill's name and description from the start; a server by whether its tools are in the
session. The permission mode is not establishable at all, so a permission is `known` only with the
observation behind it and `unknown` is the common, correct answer. Selecting a skill grants nothing,
and detecting a stack grants nothing.

### Compatibility

No breaking change for users. Every command, role id, slug and category is preserved, and
`/agent-context` is additive. For **authors**, three build requirements are new and will fail an
existing fork until satisfied: `task_signals` on every skill manifest, `retrieval_hints` on every
role template, and a `catalog/signals.json` entry for every conditional bucket.

## 2.0.0 — 2026-09-19

Evolves the pack from 27 standalone role prompts into a composable capability system. Roles keep
their identity and working method; specialist knowledge moves into skills that load on demand.

### Added

- **Skill layer.** 79 local skills under `skills/<category>/<id>/`, each a standard Agent Skill
  (`SKILL.md` with `name` + `description`) plus a `manifest.json` sidecar holding pack metadata, so
  the skill stays portable to any Agent Skills runtime.
- **External skill registry** (`catalog/external-skills.json`) — 31 skills from Anthropic, Vercel,
  Next.js, Microsoft Playwright and two community sources. Referenced with full provenance, never
  vendored, never fetched at runtime. Each records source, licence, version, verification date,
  trust level, whether it ships scripts, and the fallback when it is absent.
- **MCP registry** (`catalog/mcp.json`) — 19 servers, each verified against the vendor's own
  documentation by two independent research passes, recording write posture, risk, read-only path,
  activation condition and fallback.
- **Recipes** — 8 multi-step workflow shapes, each of which names what to cut.
- **Verification family** — skills with `verifies: true`, plus `docs/verification.md` holding the
  matrix that keeps *created / executed / tested / reviewed / deployed / verified* apart.
- **Loadouts.** Every role declares `skills_core` / `skills_preferred` / `skills_optional` /
  `skills_if_<condition>`, `mcp_recommended` / `mcp_conditional`, `recipes` and `verification` in
  its frontmatter. Generated into `catalog/loadouts.json`, which doubles as the dispatcher's
  capability registry.
- **Documentation** — `docs/architecture.md`, `skills.md`, `mcps.md`, `recipes.md`,
  `verification.md`, `security.md`, `adding-a-skill.md`, `adding-an-agent.md`.
- **Adapters** — `adapters/claude-code/` documents what is rendered where and why;
  `adapters/locus/` carries a portable catalog export.

### Changed

- **Repository layout.** Canonical roles moved from `skills/agent-dispatcher/roles/` to
  `templates/<category>/<id>.md`. The roles under `skills/agent-dispatcher/roles/` are now
  *generated* renderings carrying the Claude-specific loadout block, so the canonical definition
  stays free of runtime syntax.
- **`build.py`** is a validator as much as a generator. It now refuses to build on an unknown
  category, a loadout pointing at a skill that does not exist, a capability no skill provides, a
  tool id absent from the MCP registry, a missing declared reference file, a skill named as
  verification that does not declare it, **a role whose core + preferred exceeds five**, or **two
  skills providing the same capability in always-considered tiers**.
- **`test_build.py`** grew from a consistency check into a validation suite: generated-versus-source
  agreement, cross-reference resolution, standard SKILL.md frontmatter, body length bounds,
  credential and absolute-path scanning, registry completeness, and docs-versus-catalog counts.
- **`install.sh`** installs every skill category, not only the dispatcher.
- Schema version `2.0.0`. Role ids, slugs, commands and categories are unchanged.

### Compatibility

No breaking change for existing users. Every command (`/agent-*`), role id, slug and category is
preserved. Loadout fields are additive: a role with no loadout still works, and every role remains
useful with no optional skill or MCP installed.

## 1.1.0 — 2026-09-19

- Roles became the source of truth; `build.py` became an indexer over them.
- Added `version-control`, `data-engineer`, `incident-responder` (24 → 27).
- Skills and commands outrank routing; subagents are routed per job rather than inheriting the
  caller's role; perpetual mode gained per-session and per-project scopes.
- Shipped as a Claude Code plugin.

## 1.0.0 — 2026-09-18

- Initial router: 24 roles adapted from the Locus Agent Template Pack, per-role commands, and a
  SessionStart hook for perpetual mode.
