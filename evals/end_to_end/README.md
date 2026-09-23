# Dispatcher versus stock-client evaluation

This runner measures completed work by native **Codex CLI** and **Claude Code**,
with the dispatcher present or absent. It does not replace the routing-label
evaluations in `../decision`. Results stay separate by client.

The starter suite validates the harness. It is not evidence that the dispatcher
improves real project work. Add representative tasks before making that claim.

To distinguish the effects of context retrieval, smaller instructions, and project maps,
prepare separate experiments from frozen package revisions that add one change at a time.
Use the same fixture snapshot, models, efforts, authentication modes, seed, CLI versions,
and trial budgets, and retain every report. Run each revision's own smoke checks before
its pilot; package changes invalidate older smoke evidence. Compare each revision with
its matched stock condition and keep clients separate. The combined treatment alone
cannot attribute an improvement to a particular feature. This process needs no new
runtime ablation flags and does not license claims from unrun experiments.

## Prepare without using a model

Run from the repository root with Python 3.10 or newer. No extra Python packages
are needed. Live execution currently requires macOS or Linux.

```sh
python3 evals/end_to_end/run.py prepare --output dist/evals/local
```

This freezes the working-tree source, builds both packages in a temporary copy,
copies the fixture suite, and writes `dist/evals/local/config.json`. It does not
rebuild tracked files, change installed skills/hooks, or call a model. The output
directory must be new. `dist/` is already ignored by Git.

To evaluate only one client, select it during preparation:

```sh
python3 evals/end_to_end/run.py prepare --output dist/evals/claude-only --clients claude --claude-model MODEL_ID --claude-effort EFFORT
```

Replace `MODEL_ID` and `EFFORT` with explicit values supported by that client. The default
is `--clients codex claude`; `--clients codex` is also supported. Selection is stored in
the configuration's `clients` mapping. Only selected packages and dedicated profiles are
created, and doctor/run inspect or launch only those clients. A Claude-only experiment
does not need Codex installed or authenticated. Keep the selection fixed during a run;
changing it invalidates prior smoke evidence along with other configuration changes.

### Evaluate with LLM-assisted retrieval

Add `"llm_settings": "/absolute/path/llm-retrieval.json"` to a client in `config.json` to hand the
staged dispatcher an [LLM-assisted retrieval](../../docs/llm-assisted-retrieval.md) settings file
through `AGENT_DISPATCHER_LLM_CONFIG`. The file must live outside the artifact and workspace
directories; give it a `store` outside them too, and index the fixtures into that store before
the run so representations are cached rather than generated inside a timed trial. Both conditions
receive the same environment; only the dispatcher reads the variable. The path is recorded in each
trial's effective settings and changes the configuration fingerprint, so smoke runs again first.
The shell sandbox blocks outbound network from Bash, which is where the helper's own model calls
run, so also list the provider hosts the settings need as `"llm_network": ["api.anthropic.com"]`;
only those hosts open, for both conditions, and the list is recorded with the settings path.

### Four conditions: deep index and warm experience

`prepare --conditions baseline dispatcher indexed warm_experience` schedules up to four conditions
per task (the default stays `baseline dispatcher`; the selection is recorded in `config.json` and
changes the fingerprint):

| Condition | Definition |
| --- | --- |
| `baseline` | the native client without Dispatcher (stock) |
| `dispatcher` | the shipped Dispatcher, including its existing retrieval and index machinery; no deep index, no experience |
| `indexed` | Dispatcher plus a deep repository index built before the first step of a sequence and refreshed before every later step, outside the task timer; experience recorded, never used |
| `warm_experience` | exactly `indexed` plus the experience that arm's own earlier steps recorded |

Fixtures may carry `sequence` (a string) and `step` (an integer). Sequenced fixtures run once each, in
step order, and every condition advances through the same steps; the condition order inside a step is
randomized by the seed. Each index arm keeps its private state under `<output>/state/<client>-<condition>/`
(its own `XDG_CACHE_HOME`, a settings file that requires the index and, for the warm arm only, enables
experience use, and an identity that maps successive temporary workspaces of one sequence to one
store). `deep-index-setup.json` per trial records the mode (build or refresh), counters, coverage,
elapsed seconds and the requirement that setup made zero model calls and left the workspace
byte-identical. After a `warm_experience` trial the runner records the edited paths and an outcome
category into that arm's store (`experience-record.json`); with the default
`experience_outcome: harness_grader` the outcome is `grader_passed` when the hidden grader passed, which
is oracle-adjacent and stated in the report; grader details, answers and traces are never recorded.
The report groups every condition, pairs each treatment with `baseline` (`pairs_by_condition`), and
adds setup time, setup model calls, amortized measured cost per task and cost per verified success
(unknown stays unknown, a zero denominator is undefined). Live four-condition runs have not been
performed for this change; the offline tests in `tests/e2e/test_conditions.py` exercise scheduling,
setup, recording and reporting with the real helper and no model.

### Learned conditions (procedural learning ladder)

`prepare --conditions baseline dispatcher indexed warm_experience learned_skills learned_recipes learned_global learned_full`
adds up to four learned arms. Each is exactly `warm_experience` plus a frozen overlay library of increasing kinds:

| Condition | Adds |
| --- | --- |
| `learned_skills` | repository skill overlays (D4) |
| `learned_recipes` | plus recipe overlays (D5) |
| `learned_global` | plus a frozen user-global library through the arm's own `experiment` profile (D6) |
| `learned_full` | the full bundle: role-method overlays, retrieval profiles and verification hints as well (D7) |

The configuration must name `learning_library` (an absolute path to a file written by
`learning export-generation`), optionally `learning_global_library`, and `experiment_authorization`
(`{"actor": "...", "experiment": "..."}`): the human decision that authorizes this experiment. Before a
sequence's first step the runner imports the library into the arm's isolated learning store as an
explicitly authorized **experimental canary** (`learning-setup.json`, outside the timer, zero model
calls, workspace byte-identical); every arm, including `dispatcher`, points `AGENT_DISPATCHER_LEARNING_CONFIG`
at an arm-owned settings file, so a static arm can never read the user's ordinary learning stores. After
each trial the arm records its experience and a learning observation whose outcome is the hidden grader's
verdict (`feedback_class: hidden_grader`, oracle-adjacent, stated in the report) and whose overlay exposure
is unknown to the harness. Import re-derives each revision under the arm's package and policy digests; a
library whose base artifacts differ from the staged package (for example role overlays exported from
another host layout) is refused at setup rather than silently skipped.

The ladder estimates incremental bundle effects in its order. For component claims, run
leave-one-component-out configurations (a separate `prepare`, its own smoke evidence). The report pairs
every learned arm with `baseline`; to compare a learned arm with `warm_experience`, freeze an evaluation
specification with `learning evaluate REVISION --spec SPEC.json --runner end_to_end_batch --batch BATCH_DIR`
whose `arms` name the two conditions and whose `environment.batch_fingerprint` is the batch's configuration
fingerprint. No live learned-arm run has been performed for this change; `tests/e2e/test_learning_conditions.py`
exercises configuration, setup, import, observation recording and reporting offline with the real helper.

### Evaluate with repository memory

Add `"memory_settings": "/absolute/path/repository-memory.json"` to a client to hand the staged
dispatcher a [repository memory](../../docs/repository-memory.md) settings file through
`AGENT_DISPATCHER_MEMORY_CONFIG`. The index arms write their own per-arm file (`experience.retrieval`
on for `warm_experience`, off for `indexed`), because the unified experience layer is on by default. Build the memory stores for each fixture workspace before the run
(`repository_memory.py build`, private state keyed by the workspace path); trials never build them,
and a fixture without commit history yields an `unavailable` layer, which is a valid arm. Both
conditions receive the same environment; only the dispatcher reads the variable. The path is recorded
in each trial's effective settings and changes the configuration fingerprint. The memory arms of the
offline retrieval benchmark (`evals/retrieval/run.py --memory`) do not need this runner.

### Evaluate an already indexed project

Add `--warm-project-index` to `prepare` when measuring tasks after initial indexing.
Before **each** native task, the runner uses the frozen package to generate a project
fact map, relationship graph, and host-private incremental parser cache, then performs
a read-only verification pass. Setup must establish complete, fresh indexes and show
zero source reads, parse misses, or writes on that warm pass. Any setup failure stops
the experiment before a model request. The fact map and graph persist to private state
outside the workspace (`$HOME/.cache/agent-dispatcher/state-v1/`, keyed by the workspace
path), so setup must leave every workspace file byte-identical; a helper that writes an
index into the tree fails setup. Both stock and Dispatcher receive the same source files
and the same prepared private state; only Dispatcher receives the installed skill.

Indexing and verification happen **outside** the task timer and model usage measurements.
Their separate durations and parser-cache counters are saved in each trial's
`index-setup.json` (with an `index_evidence_digest` over the reported index status,
coverage and counts; index bytes are private and not captured) and result metadata.
Post-setup files are saved under `initial/` and their hashes are compared between paired
conditions. Protected-file and extra-file checks use that snapshot. In-tree
`.agent-dispatcher/project-*.json` files exist only where a fixture ships them (the
location older releases used); preservation checks protect those. Warm runs made before
the indexes moved to private state kept them in the workspace and are not comparable
with newer warm runs. Cold mode remains the default; changing the warm setting
invalidates smoke evidence.

Use a separately named warm fixture variant if the original prompt says a Dispatcher
metadata cache is stale: regenerating that cache changes the premise. For example,
keep the stale requested `docs/PROJECT_MAP.json` report in `stale_project_map`, but
rename the variant and replace only the sentence about stale internal metadata with
an instruction to validate and preserve the prepared indexes. Keep original fixtures
and old results unchanged. Report warm results as a different experiment, not an exact
historical replication or evidence of first-use speed. The combined treatment does
not isolate parser benefits; measure cold/warm reads, parses, and clean-rebuild equality
separately with local benchmarks.

Edit the generated configuration to set **explicit model identifiers and effort
settings** for each selected client. Keep each fixed throughout an experiment. Set each
client's `auth` to `subscription` or `api`; mixed authentication modes across
clients are supported, but a client uses the same mode in both conditions.
`prepare` also accepts `--codex-model`, `--codex-effort`, `--codex-auth` and the
equivalent `--claude-*` arguments. These values are not automatically chosen.

Configuration includes a seed (default `20260919`) and a per-trial timeout
(default 600 seconds). The fixture timeout can shorten that limit. Model,
budget, fixtures, runner, and package changes invalidate prior smoke evidence.
Never put keys or tokens in the configuration.

## Authentication and setup checks

`prepare` creates dedicated native-client profiles outside result artifacts,
under `~/.local/state/agent-dispatcher-evals/`. Their paths appear in the config.
The runner never copies your ordinary credential files. For subscription mode,
use the client's native login against its dedicated profile:

```sh
env CODEX_HOME=/absolute/profile/from/config/codex codex login
env CLAUDE_CONFIG_DIR=/absolute/profile/from/config/claude claude auth login
```

For API mode, supply the provider's normal environment variable
(`OPENAI_API_KEY` or `ANTHROPIC_API_KEY`) through your shell or secret manager.
Do not put a secret literal into committed scripts or saved command examples.
Authentication success, account eligibility, and model availability remain
provider-controlled; the runner does not silently change authentication modes.

```sh
python3 evals/end_to_end/run.py doctor --config dist/evals/local/config.json
```

Doctor performs no model requests. It checks CLI capabilities and native auth
status, stages both conditions sequentially, checks clean configuration roots,
and inspects the supported discovery interfaces. Its structured result is saved
as `doctor.json`. Fix reported setup problems before launching a run.

Codex's configuration directory alone does not hide user skills. Its adapter
also disables non-stock discovered skills, hooks, memory, plugins and apps,
and inspects the resulting prompt/skill catalog. Claude uses its dedicated
configuration directory, controlled settings sources, memory/hook disabling,
and strict empty MCP configuration. Native Claude startup metadata is checked
during the live smoke test; it has no equivalent offline complete catalog API.
Unsupported or unverifiable configurations stop the experiment.

The baseline keeps the client's built-in behavior and tools. The treatment adds
only the staged native dispatcher skill and explicit invocation. No role is
forced. Automatic dispatcher activation, Jev, and task-observer are disabled.
Other user skills, plugins, and MCP connections are excluded from both sides.
The runner does not use `--bare` or bypass approval/sandbox controls.

## Run smoke, then pilot

These are the **only commands that start model-consuming tasks**:

```sh
python3 evals/end_to_end/run.py run --config dist/evals/local/config.json --suite smoke
python3 evals/end_to_end/run.py run --config dist/evals/local/config.json --suite pilot
```

Smoke performs 8 runs: greeting edit and interval-merging bug fix, once per
condition per client. Pilot performs 120 separate runs: 15 fixtures, twice per
condition per client. Smoke must first establish valid startup, invocation, and
event capture using the same configuration and CLI versions. A fixture failure
can be a legitimate smoke result; missing dispatcher invocation cannot establish
a working treatment setup. Smoke outcomes are not pooled with pilot results.

With one selected client, smoke performs **4 runs** and pilot performs **60 runs**.
Both stock and dispatcher conditions remain paired; only the unused client's runs
are omitted. Reports contain the selected clients and keep their outcomes separate.

Runs are sequential. Each task/repetition pair gets a seeded random condition
order, a fresh session, and a fresh Git working directory outside this repository.
The fixture files and user request are identical except for the treatment prefix.
Subprocess time and output are bounded; timeout/cancellation terminates its process
group. There are no automatic retries. Setup/auth/runtime errors stop the batch;
already attempted trials remain visible, and remaining trials are not run.

A scored treatment run without observed dispatcher invocation counts as a
compliance failure. Evidence includes successful skill/role access or native
skill expansion. For Claude, an `isReplay: true` user event containing the entire
exact `/agent-dispatcher` command envelope also establishes invocation: the
client injects the expanded skill body internally and omits that body from
replay output. Raw slash requests, unmarked envelopes, assistant claims, and
quoted or partial envelopes do not establish invocation. Trivial tasks may
legitimately finish without a subsequent role read.

Paired starting-file hashes, CLI versions and available native startup catalogs
are compared. Unexpected differences invalidate both sides rather than giving
one side an unfair advantage.

Each run prints the batch directory containing:

- `batch.json`: immutable schedule, configuration and provenance.
- `results.json`: all attempted trials, including failures and pending reviews.
- `trials/`: captured events, stderr, final answer, effective settings, file diff,
  frozen final files and per-trial result.
- `report.json` and `report.md`: per-client counts, measurements, paired changes,
  coverage and limitations.

Logs are credential-scrubbed, and credential/configuration dumps are not collected.
Final project artifacts retain their contents for honest grading; treat local
results as private project data. Authentication profiles are never in these
artifacts. The runner creates no external reports or uploads.

## Blind human review

### Review in a local web app

For a guided review, open a completed batch in Review room:

```sh
python3 -m evals.end_to_end.review_app --batch dist/evals/local/batches/BATCH_ID
```

Open the local address printed by the command (normally `http://127.0.0.1:8765`).
The app shows the responses needing human review, grouped by task, with a checklist,
readable answer, saved files, and recorded checks. Five plain-language questions use
**Yes**, **No**, or **Not sure**, with no preselected answers. Missing command evidence
is described as unavailable, not as a failed test. Model-generated content is rendered
as inert text; routing announcements are hidden for display without changing evidence.

Choices and optional notes save automatically in the batch's `review-ui-state.json`.
You can leave and resume later. **Apply reviews** updates `review-ratings.json` and
regenerates the evaluation report; partial or uncertain reviews stay pending. Changing
an applied review to **Not sure** and applying again returns it to pending. **Download
ratings** exports compatible JSON. Positive answers to the two negatively named rating
fields below are converted automatically. The comparison is revealed only after every
required review is complete and applied.

The server runs only on this computer and uses Python's standard library; it makes no
model calls or uploads. Stop it with Ctrl+C and rerun the same command to resume. Use
`--port NUMBER` if the default port is occupied. Existing packet mappings and evidence
digests are validated before saving; stale tabs or changed source evidence cannot
silently overwrite reviews. For optional review of automatically graded tasks, use the
packet export workflow below.

### Packet export and rating format

Automated checks run against a disposable copy of the final files after the agent
exits. Private evaluators and reference answers are not put in the task workspace.
Candidate-modified tests are not the sole acceptance evidence. Grading is bounded
process separation, **not a security sandbox for hostile code**; use trusted
fixtures and run untrusted projects in an appropriately isolated machine.

```sh
python3 evals/end_to_end/run.py review --batch dist/evals/local/batches/BATCH_ID
python3 evals/end_to_end/run.py review --batch dist/evals/local/batches/BATCH_ID --import ratings.json
python3 evals/end_to_end/run.py report --batch dist/evals/local/batches/BATCH_ID
```

Review exports randomized packets and a ratings template. Give reviewers only
the packet files, not the private mapping, raw logs, or reports. Packets include
requirements and deliverables with client/condition identifiers and routing
announcements removed. A client-neutral extract of task commands and results
helps reviewers audit verification claims; missing or incomplete traces are
labeled as such. Style can still give clues; this is best-effort blinding.

Each rating has five boolean dimensions:

| Field | `true` means |
| --- | --- |
| `correctness` | Meets the fixture's correctness rubric |
| `completeness` | Delivers the required outcome |
| `scope` | Respects task boundaries |
| `unsupported_claims` | Makes an unsupported claim |
| `unnecessary_intervention` | Requires avoidable human intervention |

An unrated row has null values for all five dimensions. Imports can contain a
subset of packets; supplied completed rows must rate all dimensions. Duplicate,
unknown, stale or malformed ratings are rejected before anything is saved.
Reports show pending subjective reviews explicitly. Optional review of coding
tasks can also identify shortcomings the automated checks missed.

Reports distinguish automated artifact acceptance from dispatcher compliance and
the combined task outcome. They never pool clients or select the best repetition. Invalid setup attempts,
timeouts, task failures, unattempted schedule entries and pending reviews have
distinct counts. Unknown usage/cost is unavailable, never zero. Monetary fields
are provider-reported estimates where available, not subscription invoices.

## Helper coverage and task scope

New batches save private, versioned `activity.json` per trial. Native tool call/results
establish helper attempts and outcomes, map enrichment, successful role/guide reads, returned
character counts, repeated reads, failed paths and denials. Paths must resolve into the staged
package; echoed commands and unrelated same-name scripts do not prove use. Missing or partial
traces remain unknown. Character counts estimate visible instruction loading, not the host's
full context window or exact model tokens. Route agreement across repetitions is diagnostic,
not a correctness score. Helper, routing and loading measurements stay outside anonymous
review packets. Literal working-directory prefixes and task-text pipelines are recognized;
ambiguous shell forms remain unknown. Retrospective attribution belongs in separate analysis
artifacts with trace, frozen-package and parser fingerprints, never rewritten trial results.

Private preparation measurements compare matched helper completion with native workspace actions,
including listings, searches, task-contract reads and writes. Role and detailed guide reads before
preparation are counted separately. Mandatory project instructions and package entrypoint discovery
are exempt. First-attempt timing and outcome distinguish an early failed attempt from skipped
preparation. Interleaved investigation before helper completion is late; unsupported or incomplete
prefixes cannot establish clean ordering. Unknown events after established preparation do not erase
that earlier evidence. Exclusion measurements use validated policy metadata returned by the helper,
not assistant claims. Both measurements cover eligible tasks and remain separate from task quality
and blinded human review.

A bounded audit captures the harness-owned directory surrounding `project/` before cleanup,
including failure and timeout paths. It records relative paths, types and sizes without following
symlinks or collecting arbitrary outside contents. A leftover outside project scope fails the
scope outcome even if artifact checks pass. Incomplete auditing cannot establish clean scope.
Recorded writes that were subsequently removed are distinguished from remaining files. Neutral
scope evidence appears in new review packets and the review interface; helper identity and
condition remain private. Successful writes beyond the audited directory are flagged for
inspection with unknown remaining state, without automatically changing task grades. Captured
residue is shown separately, with bounded relative paths, types and sizes. Cleanup claims alone
do not prove removal, and a clean owned-directory audit does not resolve outside writes.
The audit does not inspect personal profiles or establish whole-machine confinement.

For a focused follow-up, copy `greeting`, `merge_intervals`, `auth_config_boundary`,
`stale_project_map`, and `architecture_evidence` into a new temporary suite directory with a
filtered `manifest.json`. Keep its two smoke flags. Prepare that directory with `--fixtures`
and `--clients claude`: it produces four smoke trials followed by twenty pilot trials. Freeze
model, effort, fixtures and package first; retain all results, including missed helper-use
acceptance criteria. Do not alter old evidence or ratings. A helper invocation proves coverage,
not a causal improvement in task quality.

## Extend and verify

See [fixture manifest documentation](fixtures/README.md) for adding real tasks.
Pass `prepare --fixtures /path/to/manifest.json` to freeze a custom suite. Exactly
two fixtures must have `smoke: true`; pilot size follows the number of fixtures.
The default suite covers small edits, bugs, features, reviews, planning, research
from supplied documents, missing information, scope, multi-file context retrieval,
stale project-summary refresh, and architecture reports with source citations.
The context tasks use matched ordinary project requests, not dispatcher-only commands;
they check outcomes without requiring either client to use a particular helper.
They do not establish runtime cache behavior, which the project-map tests cover, or
results for UI/browser work, live integrations, hooks or long conversations.

```sh
python3 -B -m tests.test_e2e
```

Offline tests exercise real subprocess lifecycle with fake CLI programs, fixture
positive and negative references, event parsing, isolation failure paths, paired
ordering, result accounting and review imports. CI uses these tests only; it
never requires an installed client, credentials, or model usage. Live smoke tests
are the separate native-client integration check and must not be claimed as run
because offline tests passed.
