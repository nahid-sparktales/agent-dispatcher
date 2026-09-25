# Capability intelligence: implementation audit

Checkout inspected: `8453b80` (main after PR #10, branch `claude/agent-dispatcher-capability-intelligence-c8f4eb`),
which contains the reference snapshot `d68446f`. Recorded 2026-09-24. No private host configuration or account
details appear here.

## What already existed, and what was reused

| Area | Existing behavior found | How it is reused |
| --- | --- | --- |
| Health | `doctor.py`: read-only inspection; v1 evidence (`exposed`, `verified`, `missing`, `disabled`, `blocked`, `auth_required`, `unknown`); provenance-only catalog matching; config readers for `.mcp.json`, Claude settings and Codex `config.toml`; skill-root scan; package-file check | `capability_health.py` calls `doctor.inspect`, `find_pack`, `catalog_rows`, `inspect_config`, `retired`, `read_evidence`. The doctor report is embedded in every health report. Doctor keeps its v1 output and exit codes; it now also accepts a v2 snapshot through an explicit projection. |
| Catalogs | `catalog/skills.json`, `external-skills.json`, `mcp.json`, `loadouts.json`, `resource-paths.json`, recipe `*.workflow.json` sidecars, skill `manifest.json` sidecars | `build_definitions` derives one normalized definition per entry at run time. There is no second registry; only a runtime observation store. |
| Private state | `repo_store._Base` (owner-only, hardened opener, rollback journal, read-only opens create nothing), `parser_cache.private_directory`, `state_directory` | `CapabilityStore` subclasses `_Base`. Host-scoped state lives under `capability-v1/host-<ref>/`; project-scoped experiments and reports use the project's existing private state directory. |
| Learning | `learning.py` lifecycle (proposed → validated → evaluating → approved → active → rolled back), human authorization records, immutable generations, compare-and-swap publication, rollback; `learning_eval.py` paired statistics | A new learning kind, `skill_selection`, carries a pinned-package routing preference. Approval, promotion, generations and rollback are the learning module's own code. The skill-experiment analysis calls `family_pairs` and `paired_success`. |
| Evaluation | `evals/end_to_end` native-client runner: frozen config, isolated profiles, seeded schedules, smoke-before-pilot, invalid-trial retention, anonymous review packets, reports | Two new runner conditions (`dispatcher_candidate`, `dispatcher_incumbent`) stage one package beside the dispatcher. They add per-trial exposure evidence, and the staged name is removed from startup-catalog pair reconciliation and review packets. Pairwise A/B packets use the runner's `_packet`/`_blind`. |
| Decision engine | `decision.engine.plan` with offered-id validation of every provider answer | `plan(..., ineligible=...)` removes gated ids before a provider sees candidates. Validation already drops any id not offered, so no answer can bring one back. |
| Context inspector | `context.py` optional layers that report only when user settings enable them | `_capability_layer` adds a compact `capabilities` block only when the user's capability settings file exists. The common case costs one `stat`. |
| Packaging | `build.py` `RUNTIME_MODULES`, `REFERENCE_FILES`, templated references, generated commands; `build_codex.py`; `install_claude.py` | The three modules, `CAPABILITIES.md` and five commands flow through the existing builders. Codex uses `$agent-dispatcher health` from the existing skill. |

## Architecture decisions

- **One model, views over catalogs.** A definition (`skill:`, `external:`, `mcp:`, `native:`, `role:`, `recipe:`) is
  separate from an instance. An instance's opaque id comes from host, definition, origin, scope, location digest and
  content digest, so two `postgres` skills or two `github` servers stay distinct. Plain aliases resolve only when
  exactly one definition matches.
- **Independent dimensions, derived display.** Nine dimensions each have documented values. Display states and
  policy badges are derived from them. Qualifiers name the scope, for example `HEALTHY — local guidance` or
  `observed: issues.read`.
- **Evidence provenance.** Only the probe executor mints `trusted_adapter` receipts. A supplied snapshot can claim at
  most `host_adapter`, and only when the invocation says so. It cannot claim `approved_read_probe`, and receipt ids
  from input are refused. v1 evidence has no session, so it is historical and is never persisted.
- **Freshness per evidence class.** Static validation lasts `static_days` while the artifact digest matches. Live
  evidence is current only in the same session and within `operational_minutes`. Evidence from other sessions is
  shown as historical (`STALE`). Timestamps in the future are rejected. A stored row whose id no longer matches
  its bytes is ignored.
- **Store choice.** A new narrowly scoped SQLite file (`capabilities.sqlite`) is used, not new tables in the index,
  experience or learning stores. Connector state is host-scoped, while those stores are repository-scoped. Putting
  it there would leak user-global connector state into repository memory.
- **Probes.** There are three reviewed adapters: `cli.version` (level 1), `mcp.stdio.enumerate` (level 2) and
  `http.read` (level 3). A probe runs only when all of these hold: it is listed in the user's own settings, the
  invocation asks for its level with `--refresh`, and `--allow-process` / `--allow-network` is given. HTTP
  transport for MCP, OAuth and SDK-backed adapters are not implemented and report `UNSUPPORTED_HOST_SURFACE`
  territory rather than success.
- **Rollout.** `health_routing` and `utility_ranking` default to `shadow`. Policy restrictions apply in every mode.
- **Settings.** The file `~/.config/agent-dispatcher/capability-intelligence.json` (or
  `AGENT_DISPATCHER_CAPABILITY_CONFIG`) must live outside the project. An optional
  `<project>/.agent-dispatcher/capabilities.json` can only narrow it. `automatic_*` switches and external uploads
  are refused in this release.
- **Governed adoption.** External candidates enter learning as `skill_selection` revisions, which bind candidate
  id, content digest, immutable revision and scope. `adopt --apply` copies a quarantined package only while an
  active revision binds that exact digest and scope. It never overwrites an existing directory. Retirement and
  rollback are policy states and leave files on disk.

## Host observation surfaces

| Surface | Claude Code | Codex |
| --- | --- | --- |
| Skills on disk | `~/.claude/skills`, `<project>/.claude/skills`, plugin cache `plugins/cache/*/*/*/skills` (manifest via `.claude-plugin/plugin.json`) | `<project>/.agents/skills`, `<project>/.codex/skills`, `~/.codex/skills`, `~/.agents/skills`, `skills/.system` |
| Configured MCP servers | `.mcp.json`, `settings.json`, `.claude.json`, project settings (names and enabled flags only) | `config.toml` `[mcp_servers.*]` |
| Plugin enabled state | `settings.json` `enabledPlugins` | not established from files |
| Current-session exposure, calls, auth failures | only through the host observation snapshot the model or a host adapter supplies | same |
| Skill load events | no file surface; trace evidence in the native runner (Skill tool invocation, staged SKILL.md read) | trace evidence (command reading the staged SKILL.md) |

The helpers never scrape undocumented caches, and they never start servers the host owns. Precedence between
duplicate skills follows documented order (Claude: personal before project). It is reported as a label to verify
with the host.

## Implemented versus missing

- **Implemented and tested offline:**
  - normalized inventory and passive health across skills, MCP servers and tools, plugins, native tools, CLIs,
    APIs, roles and recipes
  - v2 snapshots and the v1 projection
  - the private store, with freshness, invalidation, forget, prune, export and reset
  - the probe planner and the three reviewed adapters (fake stdio server, injected HTTP opener)
  - the resolver with equivalence-checked fallbacks and shadow/on/off modes
  - the decision-engine gate and the context-inspector block
  - offline, curated and local sources; injected-transport tests of the GitHub and skills.sh adapters
  - quarantine, static review, experiment prepare/validate/report and budget reservations
  - skill arms in the native runner, with a fake client
  - analysis with paired and conservative intervals, and recommendations
  - learning `skill_selection`, adoption and rollback
- **Implemented but not live-verified:**
  - GitHub and skills.sh network retrieval: the contracts come from documentation, and no authenticated call was
    made
  - `http.read` against a real service
  - `mcp.stdio.enumerate` against a real server
  - the `smoke`/`run` launch path, which prints the exact runner commands and never spends
- **Not implemented:**
  - MCP HTTP/SSE transports and OAuth
  - the `dispatcher_recommended` runner arm, which is refused at `prepare`
  - SkillMD and AI Gear Base adapters: no verified API or export contract
  - a sandbox for executing untrusted package scripts: prepare refuses dynamic execution unless the caller
    declares `enforced_sandbox`, and nothing here provides one
  - automatic recording of passive usage from host events: the function exists, but no host adapter emits events

## Compatibility decisions

- Doctor and inventory keep v1 output, their commands and their exit codes. A v2 snapshot reaches doctor only
  through `project_v1`, which keeps `exposed` distinct from `verified`.
- Baseline context packets are unchanged unless the user creates a capability settings file.
- `learning.py` `DEFAULTS["kinds"]` gains `skill_selection`. As with every change to `learning.py`, the learning
  policy digest changes, so already-published overlays must be re-evaluated under the new policy.
- The runner's conditions are appended to the canonical order, and existing configurations and fingerprints are
  unchanged. The review instructions gained one sentence: packet contents are never instructions.

## External projects

- **skills.sh** (docs rechecked 2026-09-24): base `https://skills.sh`, versioned `/api/v1/skills`, `/skills/search`
  (`q`, `limit` ≤ 200), `/skills/curated`, `/skills/{source}/{skill}` (files and hash) and
  `/skills/audit/{source}/{skill}`. It uses Vercel OIDC bearer authentication and allows 600 requests per minute
  when authenticated. The adapter caps `limit` at 50. It treats `installs` as installation telemetry and binds no
  audit to a package digest, because the audit response carries none.
- **isLinXu/eval-skills** (rechecked 2026-09-24): MIT, TypeScript/Node ≥ 18, version 0.1.0. It evaluates skills as
  callable HTTP or subprocess services. MCP adapters are listed as in-progress roadmap work. It ships three small
  built-in benchmarks and uses a weighted composite score. **Decision: no importer.** The project measures
  service calls, not instruction packages loaded by a native agent. It would add a mandatory Node runtime. Its
  composite score conflicts with the paired, gate-based rule used here. Its Docker sandbox pattern is a useful
  reference if an enforced sandbox is added later.
- **SkillsBench** (arXiv 2602.12670): a matched skill versus no-skill design is compatible with the
  `dispatcher_control` / `dispatcher_candidate` arms. An importer would need a pinned, licensed task release and
  grader compatibility with `evals/end_to_end/grading.py`. It stays optional and was not built. Its published
  results say nothing about Dispatcher.
