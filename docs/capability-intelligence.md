# Capability intelligence

Capability intelligence answers two separate questions, each with explicit evidence:

- **Which capabilities can this host actually use** for this operation, in this environment, right now?
  `capability_health.py` answers this.
- **Which eligible skills have demonstrated value** for this task, repository, model and host configuration?
  `skill_intelligence.py` answers this.

`capability_resolver.py` combines both answers into a task-scoped routing plan. Nothing here installs, connects,
logs in, activates or grants a permission. The implementation audit is in
[capability-intelligence-audit.md](capability-intelligence-audit.md).

## Commands

| Host | Health | Skills |
| --- | --- | --- |
| Claude, manual install | `/agent-health`, `/agent-setup`, `/agent-checkup`, `/agent-capabilities`, `/agent-mcps`, `/agent-plugins` | `/agent-skills` |
| Claude, plugin | `/agent-dispatcher:agent-health` (and so on) | `/agent-dispatcher:agent-skills` |
| Codex | `$agent-dispatcher health` | `$agent-dispatcher skills` |
| Direct | `python3 -B PACK/capability_health.py health ...` (Codex: `PACK/scripts/`) | `python3 -B PACK/skill_intelligence.py ...` |

`/agent-doctor`, `doctor` and `inventory` keep working unchanged and share the same inspection code.

```bash
python3 -B capability_health.py health --host claude --project . --evidence '<snapshot>'
python3 -B capability_health.py health --type mcp --json
python3 -B capability_health.py checkup --host claude --evidence '<snapshot>'   # every MCP/skill/plugin: working · needs attention · unsure · not in use
python3 -B capability_health.py health --capability ci-... --explain
python3 -B capability_health.py health --deep --probe-plan          # plan only; nothing runs
python3 -B capability_resolver.py explain --task 'Diagnose the failing signup' --role database-engineer --host claude
python3 -B skill_intelligence.py --offline-manifest m.json discover 'postgres debugging'
python3 -B skill_intelligence.py --offline-manifest m.json inspect offline:label/name
python3 -B skill_intelligence.py evaluate prepare sc-... --spec spec.json
python3 -B skill_intelligence.py recommend 'debug slow queries' --role database-engineer --model M --effort E
```

Exit codes: 0 means completed, including findings. 2 means malformed input or a refused action. 3 means a
requested `--require healthy|usable` gate was not met. JSON goes to stdout, diagnostics to stderr, and secrets to
neither.

## Health model

A **definition** is a view over a catalog entry. An **instance** is what one host has. Instance ids are opaque and
built from host, origin, scope, location digest and content digest, so same-name skills or servers from different
sources stay distinct.

| Dimension | Values |
| --- | --- |
| presence | installed, absent, unknown |
| configuration | valid, invalid, unknown, not_applicable |
| exposure | callable, deferred, not_exposed, unknown |
| connectivity | verified, failed, untested, not_applicable |
| authentication | authenticated, required, unknown, not_applicable |
| authorization | allowed, denied, unknown, not_applicable (per observed operation; never a grant) |
| compatibility | compatible, incompatible, unknown |
| policy | enabled, disabled, blocked, quarantined, retired |
| freshness | fresh, stale, expired, unknown |

Each instance gets one display state, derived from these dimensions:

- `HEALTHY` carries a scope qualifier, such as `local guidance`, `tool enumeration` or `observed: <operation>`.
- `DEGRADED` means a usable subset remains, or an optional part is impaired.
- `AUTH_REQUIRED`, `MISCONFIGURED`, `UNAVAILABLE` and `UNTESTED` complete the set.

Policy badges (`DISABLED`, `BLOCKED`, `QUARANTINED`, `RETIRED`) and freshness badges are shown separately. A
plugin summarizes its children, and its children are counted as components, not as independent integrations.

### Evidence

The default mode is passive. It reads local metadata, stored receipts and the host observation snapshot you
supply (schema 2: host, session reference, discovery coverage, capabilities with operation descriptors, and
observations). A v1 doctor evidence object is accepted and projected. Its successes stay report-local because it
carries no session identity.

Every receipt records: source, type, operation, outcome, reason code, observed/expiry time, session, fingerprints
and a sanitized explanation.

- Only the probe executor records `trusted_adapter` receipts.
- Snapshots cannot claim `approved_read_probe`.
- Receipt ids from input are refused.
- Evidence from another session is historical. `worked yesterday` is shown as `STALE`, never as current
  connectivity.

### Probes

Probes are never automatic. A probe runs only when all three hold:

1. It is listed in the user's own settings file (`probes.approved`).
2. The invocation asks for its level with `--deep N --refresh`.
3. The matching `--allow-process` or `--allow-network` flag is given.

Anything else is `skipped` with a reason, never `failed`.

| Adapter | Level | What it does |
| --- | --- | --- |
| `cli.version` | 1 | Runs an approved absolute binary with argv only. Minimal environment, temporary working directory, bounded output, process-group kill. Package-manager launchers are refused. |
| `mcp.stdio.enumerate` | 2 | Negotiates MCP (versions 2024-11-05 to 2025-11-25) and lists tools with bounded pagination. Server-initiated sampling, elicitation and roots requests are refused. Zero tools with other capabilities is success. |
| `http.read` | 3 | One GET to an exact authority. Private and metadata addresses are refused unless listed in `local_targets`. Redirects are refused. A credential header stays inside the request. The body is measured and discarded. |

Probes have bounded concurrency, per-probe timeouts, a total deadline, one retry with backoff for transient
failures, and a per-instance circuit breaker. A rate limit never blacklists anything. "Read-only" still creates
access logs and consumes quota.

### Setup

`setup` lists every **installed** MCP server and plugin that is not set up yet, grouped by the action that finishes it, one item per
line with the exact step:

| Action | Detected from |
| --- | --- |
| Sign in | the session reports authentication required; a plugin's own connector points to `/mcp`, other connectors to Settings → Connectors (or `/mcp`) |
| Install a missing program | a plugin's MCP `command` or LSP server program is not on PATH (looked up, never run) |
| Set an environment variable | a server definition references `${NAME}` that is unset (names only, never values) |
| Enable the plugin | the install record has it, but `enabledPlugins` does not |
| Fix | a malformed plugin manifest |
| Reconnect | a configured server the session reports failing |

Catalog suggestions that are not installed belong to `doctor setup`; explicitly disabled plugins are listed as left alone and never
suggested. PATH and environment are this process's, and sign-in state comes from the session snapshot.

### Checkup

`checkup` lists every MCP server, skill and plugin individually, in four groups, with the reason and the smallest next step:

| Group | Meaning |
| --- | --- |
| working | evidence exists: a successful use this session, host exposure, or a valid readable file the host also lists |
| needs attention | a failure is established: authentication required, misconfigured, unavailable or partly failing |
| unsure | no evidence either way: deferred, callable but unused, found but never run, or a valid file this session did not list |
| not in use | turned off by settings, or superseded by another copy (for example an older cached plugin version) |

Items are grouped under their shared next step, and sources are named without absolute paths (`~/.claude/skills`, a plugin, `~/.claude/commands`,
the host). The dispatcher's own bundled guides appear as one summary line unless `--include-bundled` is passed. `--type` narrows the
groups to `mcp`, `skill`, `plugin`, `tool` or `cli`. Nothing is called or probed to fill a gap; unsure is not broken.

## Routing

The resolver keeps the role and changes only bindings. It runs these stages in order:

1. **Deterministic gates.** Disabled, blocked, quarantined and retired items are rejected in every mode.
2. **Operation requirements.** These are inferred from the task (labelled heuristic) or passed as
   `--operation name:read|write:environment:resource`.
3. **Equivalent fallback.** A fallback must match operation, access, environment, resource, identity boundary
   and sensitivity. A local CLI with no established target never counts as production access. Without an
   equivalent, the plan uses a no-connection route and states that the target's state remains unverified.
4. **Mandatory verification checks.** These are carried through unchanged. A missing one is listed as a
   `verification_blocker`.

`health_routing` (`off`, `shadow` or `on`, default `shadow`) controls whether proposed changes apply. The decision
engine removes gated ids before any provider sees candidates. Only ids are passed, never health or account data.

## Skills

Candidates move through this lifecycle:

```text
discovered -> quarantined -> statically reviewed -> eligible_for_isolated_evaluation | static_review_only
           -> evaluated -> proposed -> approved -> active -> superseded | retired | rolled_back
```

- **Sources.**
  - `local` and `curated` are built from `external-skills.json` (metadata only).
  - `offline` reads a user-supplied manifest.
  - `github` and `skills_sh` are disabled by default. `github` pins a ref to a commit and uses no clone, hooks
    or submodules. `skills_sh` uses Vercel OIDC through a configured credential reference.
  - A disabled source is never constructed.
  - Queries are reduced to short technology terms before leaving the machine.
- **Quarantine.** Packages go under `capability-v1/quarantine/<id>/payload/`, outside every host discovery root,
  with every file suffixed `.quarantined`. Integrity is rechecked at every load.
- **Static review.** Findings carry a severity and a location. No findings does not mean safe.
- **Experiments.** `prepare` freezes the package digest, arms, fixtures, model, effort, host, budgets, and a
  preregistered decision rule. It stages the package for the native runner's `dispatcher_candidate` arm and makes
  zero model calls.
  - Controlled mode adds an explicit activation line. A trial whose trace does not show the staged package loaded
    counts as a compliance failure.
  - Natural mode keeps non-triggered trials as outcomes.
- **Reports.**
  - The unit is the task: effects are percentage points of task-level success rates, and repetitions are
    averaged within a task.
  - The bootstrap interval is paired with a conservative Hoeffding bound, which is used when the bootstrap
    degenerates.
  - Costs use the ratio of sums and the median paired difference. An unknown cost stays unknown.
  - Outcome categories are `insufficient_evidence`, `promising_exploratory`, `confirmed_within_scope` (held-out
    confirmation set only, and it needs both the interval above the threshold and an exact sign test below α on
    the discordant tasks), `no_demonstrated_benefit` and `regression_detected`.
  - Synthetic records are banner-labelled and never count as evidence.
- **Recommendations.** "Use no additional skill" is always available. Evidence counts only when the exact package
  digest, host, model and effort match. Anything else is labelled a transfer heuristic or `unevaluated`.
  Popularity is a discovery signal only.
- **Adoption.** `propose` creates a learning `skill_selection` revision. Evaluation, approval, promotion and
  rollback use `learning.py`. `adopt` shows a dry-run plan, and `adopt --apply --authorize-as NAME` copies the
  quarantined package only while an active revision binds its digest and scope.

## Settings and privacy

The settings file is `~/.config/agent-dispatcher/capability-intelligence.json` (or
`AGENT_DISPATCHER_CAPABILITY_CONFIG`) and must sit outside the project. Defaults:

```json
{"schema_version": 1, "health_routing": "shadow", "utility_ranking": "shadow",
 "automatic_network_refresh": false, "automatic_process_probes": false, "automatic_installation": false, "automatic_activation": false,
 "sources": {"local": {"enabled": true}, "offline": {"enabled": true}, "curated": {"enabled": true},
             "github": {"enabled": false, "credential_env": null}, "skills_sh": {"enabled": false, "credential_env": null}},
 "probes": {"approved": [], "local_targets": [], "max_concurrency": 4, "probe_timeout_seconds": 10, "total_deadline_seconds": 60,
            "max_response_bytes": 262144, "cooldown_seconds": 300, "max_retries": 1},
 "clis": {"approved": []}, "apis": [], "disabled": [],
 "freshness": {"static_days": 30, "operational_minutes": 60, "historical_days": 30},
 "evaluations": {"live_enabled": false, "judge_enabled": false, "max_trials": 0, "max_wall_seconds": 0, "max_spend_usd": null},
 "recommendation_gates": {"min_tasks": 10, "min_valid_pairs": 20, "practical_threshold_pp": 5.0, "harm_margin_pp": 5.0,
                          "max_cost_increase_ratio": 0.25, "confidence": 0.95},
 "telemetry": {"external_uploads": false}, "retention_days": 90}
```

These defaults are conservative choices, not values derived from research.

The optional project file `<project>/.agent-dispatcher/capabilities.json` may only narrow these settings: lower a
mode, disable a source, disable live evaluations or add disabled items. A field that would widen anything is
refused, and runtime denials always win.

- **Credentials.** Credentials are referenced by environment-variable name only. Values never enter receipts,
  ids, reports, caches or exceptions.
- **Exports.** Exports are redacted by default (`export`, `export --preview`, `export --detailed`).
- **Retention and deletion.**
  - `forget <instance>` deletes receipts and usage for that instance, and invalidates recommendations that
    cited it.
  - `prune` applies `retention_days`.
  - `reset --confirm` removes the host store.
- **Not in the store.** Quarantined packages, staged experiment copies and runner batches stay under the private
  cache or the evaluation output directory. None of it is in the working tree.

## Measured overhead

`python3 -B evals/capabilities/bench.py --rounds 50` was run on 2026-09-24. Setup: macOS 26.4.1 arm64, 12 CPUs,
Python 3.14.6, 125 fixture instances.

| Path | Median | p95 |
| --- | --- | --- |
| existing loadout lookup | 0.19 ms | 0.23 ms |
| context gate without settings (one stat) | 0.004 ms | 0.004 ms |
| cold passive inspection (`health`) | 45.8 ms | 47.6 ms |
| cached resolution (snapshot read + plan) | 4.3 ms | 4.8 ms |

These numbers describe one machine and one fixture. They are not a guarantee.

## Limits

- Health describes named operations in a named session. It is not a permission.
- Static review is a filter, not a sandbox.
- The resolver's operation inference is a keyword heuristic.
- The offline demo's evaluation numbers are synthetic.
- No live provider, registry or model run was performed for this change.
