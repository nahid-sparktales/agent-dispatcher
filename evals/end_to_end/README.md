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

Edit the generated configuration to set **explicit model identifiers and effort
settings** for both clients. Keep each fixed throughout an experiment. Set each
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

Runs are sequential. Each task/repetition pair gets a seeded random condition
order, a fresh session, and a fresh Git working directory outside this repository.
The fixture files and user request are identical except for the treatment prefix.
Subprocess time and output are bounded; timeout/cancellation terminates its process
group. There are no automatic retries. Setup/auth/runtime errors stop the batch;
already attempted trials remain visible, and remaining trials are not run.

A scored treatment run that ignores the skill counts as a compliance failure.
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
python3 test_e2e.py
```

Offline tests exercise real subprocess lifecycle with fake CLI programs, fixture
positive and negative references, event parsing, isolation failure paths, paired
ordering, result accounting and review imports. CI uses these tests only; it
never requires an installed client, credentials, or model usage. Live smoke tests
are the separate native-client integration check and must not be claimed as run
because offline tests passed.
