# agent-dispatcher

<p align="center">
  <img src="docs/assets/dispatchtony.png" alt="Tony Tony Chopper at an Agent Dispatcher desk with Claude and GitHub on the monitors." width="960">
</p>

[![CI](https://github.com/nahid-sparktales/agent-dispatcher/actions/workflows/ci.yml/badge.svg)](https://github.com/nahid-sparktales/agent-dispatcher/actions/workflows/ci.yml)
[![Security](https://github.com/nahid-sparktales/agent-dispatcher/actions/workflows/security.yml/badge.svg)](https://github.com/nahid-sparktales/agent-dispatcher/actions/workflows/security.yml)

**Give each Claude Code or Codex task the specialist, context, and skills it needs.**

Agent Dispatcher routes your request to a focused role, loads relevant guidance, and defines
what evidence will count as done. Ask it to debug a failure, design an interface, review a
change, or research a decision. It adapts to the work and keeps small tasks small.

<!-- counts:start -->**27 roles · 79 local skills · 31 external skills · 8 recipes · 19 MCP servers · 50 detection signals**<!-- counts:end -->

[Quick start](#quick-start) · [Usage](#usage) · [Catalog](#catalog) ·
[Documentation](#documentation) · [Contributing](#contributing)

## Why use it?

- **Match the method to the task.** A debugger reproduces the failure; a reviewer evaluates the
  change; a designer works through the interface and interaction.
- **Load context as needed.** Roles select a small set of skills, project files, and available
  tools. Full skill instructions are read only when selected.
- **Make verification explicit.** The role defines the evidence needed and reports which checks
  actually ran, what passed, and what remains unverified.
- **Keep control of routing.** Let the dispatcher choose, force a role yourself, or opt into
  automatic activation for future sessions.

Roles are working instructions the coding agent adopts within a session. It can chain roles or
assign roles to subagents when authorized and useful. Installing the pack does not start a team of
agents or connect external services.

## Quick start

You need an installed, authenticated [Claude Code](https://code.claude.com/docs/en/overview)
or [Codex](https://developers.openai.com/codex/), and Git. The installers, validation suites, and
optional decision engine use Python 3.10+ with no third-party Python packages. The Claude session
hook also uses Bash and standard Unix utilities. CI covers Python 3.10–3.14 on Linux and Python
3.14 on macOS. Native Windows
installation is not covered; use a Unix environment such as WSL.

### Codex

Run in your terminal:

```bash
git clone https://github.com/nahid-sparktales/agent-dispatcher.git
cd agent-dispatcher
python3 install_codex.py
```

Start a new Codex task, select **Agent Dispatcher** from the skill picker or invoke it with `$`:

```text
$agent-dispatcher Find why the tests are failing, fix the cause, and verify the fix.
$agent-dispatcher reviewer Review this change for correctness and missing tests.
$agent-dispatcher context explain
$agent-dispatcher status
```

This installs one skill in `~/.agents/skills/agent-dispatcher/`. It includes all 27 roles and
79 supporting guides from the same sources as Claude. Guides load only when selected.
Automatic session activation is off by default; enabling it requires Codex's hook trust review.
See [Codex setup, controls, and uninstall](adapters/codex/README.md).

### Claude Code plugin

Run in your terminal:

```bash
claude plugin marketplace add nahid-sparktales/agent-dispatcher
claude plugin install agent-dispatcher@agent-dispatcher
```

Start a new Claude Code session in your project, then try:

```text
/agent-dispatcher:agent-dispatcher Find why the tests are failing, fix the cause, and verify the fix.
```

The dispatcher reads the selected role and guides, then announces the role, loaded skills,
and selected tools before starting the task. To inspect the installation and activation state:

```text
/agent-dispatcher:agent-dispatcher status
```

Plugin commands use the `agent-dispatcher:` prefix, following
[Claude Code's plugin namespacing](https://code.claude.com/docs/en/plugins).
For example, the reviewer command is `/agent-dispatcher:agent-reviewer`.

<details>
<summary>Alternative: manual installation</summary>

Run in your terminal:

```bash
git clone https://github.com/nahid-sparktales/agent-dispatcher.git
cd agent-dispatcher
./install.sh
```

The installer builds and validates the pack, copies its skills into
`~/.claude/skills/agent-dispatcher/`, adds role commands under `~/.claude/commands/`, and
registers a `SessionStart` hook. It backs up an existing `settings.json` before adding the hook
and skips command files it does not own. `CLAUDE_CONFIG_DIR` overrides the default config directory.

Updates are staged before live files are replaced. If a replacement fails, the installer
restores the previous pack, commands, hook, settings, and manifest. A failed staging check
leaves the installed version untouched. See [manual installer recovery](adapters/claude-code/README.md#installing)
for the recovery limits.

Start a new Claude Code session and use the shorter command names:

```text
/agent-dispatcher Find why the tests are failing, fix the cause, and verify the fix.
/agent-dispatcher status
```

Use one installation method per host at a time to avoid duplicate commands and hooks.

</details>

No additional API key is needed for normal dispatcher use. Your coding agent's access and usage
requirements still apply. External skills and MCP servers are catalog references; the pack does
not install them.

## Usage

The examples and catalogs below use **Claude Code manual-install command names**. For a Claude plugin install,
add `agent-dispatcher:` after the slash: `/agent-context` becomes
`/agent-dispatcher:agent-context`.

In Codex, use `$agent-dispatcher <request>`. Choose a role with `$agent-dispatcher reviewer`,
inspect context with `$agent-dispatcher context`, and use `$agent-dispatcher decision` for
decision settings. The catalog's `/agent-uidesigner` maps to `$agent-dispatcher uidesigner`,
and the other role aliases work the same way. Activation arguments such as `on here` and
`off everywhere` are shared between hosts; their settings are stored separately.

### Let the dispatcher choose

```text
/agent-dispatcher Redesign the settings page, implement it, and check it on mobile.
/agent-dispatcher Review this change for correctness and missing tests.
/agent-dispatcher Compare the approaches already used in this repository and recommend one.
```

Routing follows the requested deliverable. A UI task can move through designer, implementer,
and tester; a label change goes straight to implementation. Trivial edits need no role or
context plan. While active, the dispatcher re-routes when the kind of work changes.

### Choose a role or inspect a decision

| Command | Purpose |
| --- | --- |
| `/agent-uidesigner` | Work as the UI/UX Designer. |
| `/agent-debugger` | Work as the Debugger. |
| `/agent-reviewer` | Work as the Reviewer. |
| `/agent-inventory` | List skills, tools, and MCPs with usability and setup status. |
| `/agent-doctor` | Check installation health, list every capability, and recommend relevant setup. |
| `/agent-context` | Show the current context plan. |
| `/agent-context explain` | Explain the role, skills, and tools selected. |
| `/agent-context verbose` | Include candidates, dropped files, and the context budget. |
| `/agent-decision` | Show optional decision-engine configuration and status. |

A directly selected role stays active until you choose another or stop the dispatcher.

### See what the dispatcher loads

Compact output is the default. It combines the role and resources into one progress line:

```text
→ reviewer · Skills loaded: secure-code-review · Tools selected: files, terminal · MCPs: none selected
```

For more detail, switch to verbose output. In Codex:

```text
$agent-dispatcher output verbose
$agent-dispatcher output compact
$agent-dispatcher output
```

In Claude Code, use `/agent-dispatcher output verbose` or `output compact` (with the
`agent-dispatcher:` prefix for plugin installations). `output` reports the current style.
You can also say "use verbose output" or "show what you load".

Verbose output explains the selections and names context read, recipes loaded, unavailable
resources and fallbacks, and planned verification. For example:

```text
Role: reviewer — evaluate the change for correctness and regressions
Skills loaded: secure-code-review — inspect the changed security boundary
Tools selected: files, terminal — available; inspect the diff and run checks
MCPs: none selected
Recipe loaded: review-pull-request — structure the review
Verification planned: focused regression checks; not run yet
```

These are examples, not a fixed loadout. Only skills actually read are labeled loaded;
selected MCP servers are marked used only after a call. Later additions get a short update,
and the final report names tools used and checks performed. Trivial tasks skip the summary.

The setting lasts for the conversation; new conversations default to compact. It changes
activity reporting, not routing, permissions, or the length of the requested deliverable.
`context verbose` remains a one-time inspection of the context plan.

### List what is usable and what needs setup

In Codex:

```text
$agent-dispatcher inventory
$agent-dispatcher inventory skills
$agent-dispatcher inventory tools
$agent-dispatcher inventory mcps
$agent-dispatcher inventory setup
$agent-dispatcher inventory setup verbose
```

In Claude Code, use `/agent-inventory` with the same filters, or
`/agent-dispatcher:agent-inventory` for a plugin install. `/agent-dispatcher inventory` also works.

The report covers bundled guides, referenced external skills, other host-exposed skills,
visible tools, and catalog or host-exposed MCP servers. Each entry has a status and a next step:

| Status | Meaning |
| --- | --- |
| Usable | Guidance is readable or the tool is exposed, with no known blocker. Tool connectivity may still be untested. |
| Needs setup | A missing installation, dependency, connection, or authentication step is confirmed. |
| Blocked | A user preference or host permission prevents use. |
| Unknown | Available evidence is insufficient; the report names what to check. |
| Not recommended | The registry records an unmaintained or retired integration and its fallback. |

`setup` filters to entries needing attention. `verbose` adds evidence, prerequisites, source
links, and fallbacks; compact still lists every entry in the requested scope. The command
inspects availability without loading every skill, probing accounts, or installing anything.
It reports discovery limits rather than treating an unseen integration as missing. Usability
is separate from permission to perform a particular action.

### Check health and get setup recommendations

In Codex:

```text
$agent-dispatcher doctor
$agent-dispatcher doctor all reviewer
$agent-dispatcher doctor mcps
$agent-dispatcher doctor setup
```

In Claude Code, use `/agent-doctor` with the same arguments, or
`/agent-dispatcher:agent-doctor` for a plugin install. `/agent-dispatcher doctor` also works.

The default checks the installation and goes through **all bundled guides, referenced external
skills, catalog MCPs, and additional skills/tools exposed in the current session**. Each entry
states what is usable, what connection has been verified, what needs setup, or what remains
unknown. It also checks activation and hook registration; a registered hook does not prove trust.
The full inventory is followed by a ranked shortlist of useful missing capabilities, with a
reason, source link, next step, and existing fallback. A role argument focuses recommendations
without hiding other inventory entries or changing your active role.

Doctor checks availability without loading every guide or calling every integration. It never
connects accounts, enables services, uses stored credentials, or changes permissions. A configured
server is not automatically connected; incomplete host discovery is reported as unknown.
Disabled and retired integrations are not recommended for activation.

For an offline local check from the source checkout:

```bash
python3 -B doctor.py --project /path/to/project --role reviewer
python3 -B doctor.py mcps --project /path/to/project --json
```

The standalone command cannot see a running agent's connections by itself. In-session commands
supply a sanitized observation snapshot using `--evidence`; see
[doctor procedure and evidence format](DOCTOR.template.md). JSON output is available for tooling.

### Activate automatically in future sessions

Automatic activation is opt-in. These commands manage the settings for you:

| Command | Effect |
| --- | --- |
| `/agent-dispatcher on here` | Activate in future sessions in this project. |
| `/agent-dispatcher on` | Activate in future sessions across projects. |
| `/agent-dispatcher off` | Stop routing for this session. |
| `/agent-dispatcher off here` | Silence this project, including when global activation is on. |
| `/agent-dispatcher off everywhere` | Disable global activation; individually armed projects remain armed. |
| `/agent-dispatcher status` | Show activation flags and whether the hook is installed. |

Claude project activation requires both a local flag and an allow-list entry in your Claude
config directory. Codex keeps its allow-list in your Codex config directory and ignores local
activation flags. Cloning a repository with an activation flag is not enough to enable the dispatcher.
Project and session silences take precedence over activation.

### Uninstall

For Codex, run from your clone:

```bash
python3 install_codex.py --uninstall
```

For a Claude plugin install:

```bash
claude plugin uninstall agent-dispatcher@agent-dispatcher
```

For a Claude manual install, run from your clone:

```bash
./install.sh --uninstall
```

The manual uninstaller removes the installed pack, its recorded commands, and its hook
registration. It leaves activation flags in place.

## How it works

```text
Your request
  → specialist role
  → context plan: relevant skills, project files, available tools, verification
  → execution
  → evidence and result
```

A **role** owns the outcome. A **skill** supplies a reusable method. An **MCP server or tool**
provides a capability. A **recipe** suggests a workflow across roles. The context plan assembles
what the specialist needs before it plans the work.

Project signals such as `package.json`, `Dockerfile`, or `components.json` help select relevant
guidance. Missing skills or tools lead to documented fallbacks and explicit verification limits.
The build caps always-on skills at five and 30 KB per role.

These are instructions and validation rules, not a sandbox. **Authorization remains with the
user and the host's permission controls.** Detecting a stack, selecting a tool, or switching
roles does not grant permission to use it.

Verification is specific to the work: a bug fix needs the original reproduction and regression
evidence; a UI change needs rendered interaction checks when a browser is available. A review
of work produced in the same session is a self-check, even when another role performs it.
See [verification expectations](docs/verification.md) and the
[context engine](docs/context-engine.md).

## Catalog

Counts and catalog entries below are generated from the repository's canonical sources.
External skills are referenced, not bundled. The MCP registry includes a workspace-tool entry
and an unmaintained server recorded as a warning; its count is not a list of installed integrations.

<details>
<summary>Specialist roles and commands</summary>

<!-- roles:start -->

### Core

| Command | Role | What it does |
| --- | --- | --- |
| `/agent-orchestrator` | Dispatcher | Coordinates bounded work, chooses available specialists, and owns the combined outcome. |
| `/agent-generalist` | Generalist | Handles everyday tasks end to end and adapts depth and tools to the actual goal. |
| `/agent-implementer` | Implementer | Builds focused, maintainable changes and verifies them against the task. |
| `/agent-planner` | Planner | Turns a goal into an evidence-grounded, executable plan with acceptance criteria. |
| `/agent-researcher` | Researcher | Investigates questions, evaluates sources, and produces decision-ready findings. |
| `/agent-reviewer` | Reviewer | Independently evaluates a change or artifact and reports actionable, evidence-backed findings. |
| `/agent-tester` | Tester | Checks observable behavior, builds regression coverage, and reports reproducible failures. |

### Engineering

| Command | Role | What it does |
| --- | --- | --- |
| `/agent-aiengineer` | AI & Agent Engineer | Builds and evaluates agent prompts, routing, tools, memory, and execution behavior. |
| `/agent-api` | API & Integration Engineer | Connects services with correct contracts, authorization, retry behavior, and failure handling. |
| `/agent-architect` | Architect | Designs system boundaries, contracts, and tradeoffs that fit the existing product and constraints. |
| `/agent-dataeng` | Data Engineer | Builds and repairs the pipelines, jobs, and transforms that produce the data downstream consumers depend on. |
| `/agent-database` | Database Engineer | Designs and changes data storage with integrity, compatibility, and safe migration behavior. |
| `/agent-debugger` | Debugger | Reproduces failures, tests hypotheses, and fixes the underlying cause with regression evidence. |
| `/agent-devops` | DevOps & Release Engineer | Builds reproducible delivery workflows and prepares or executes authorized releases with recovery checks. |
| `/agent-explorer` | Explorer | Maps an unfamiliar workspace and finds the exact code, files, and execution paths relevant to a task. |
| `/agent-incident` | Incident Responder | Stabilizes an actively failing system with the smallest reversible mitigation and a timestamped incident record. |
| `/agent-performance` | Performance Engineer | Measures bottlenecks and makes targeted improvements with reproducible before-and-after evidence. |
| `/agent-refactor` | Refactoring & Migration Specialist | Improves internal structure or moves systems to a new contract while preserving required behavior. |
| `/agent-security` | Security Auditor | Reviews authorized systems for concrete security weaknesses and practical remediation. |
| `/agent-git` | Version Control Engineer | Repairs, reshapes, and explains repository history without losing committed or uncommitted work. |

### Product & Design

| Command | Role | What it does |
| --- | --- | --- |
| `/agent-pm` | Product Manager | Turns a vague request into a focused product scope, user flow, and measurable success criteria. |
| `/agent-uidesigner` | UI/UX Designer | Designs clear, distinctive interfaces and interaction flows, with implementation-ready details. |

### Knowledge & Business

| Command | Role | What it does |
| --- | --- | --- |
| `/agent-automation` | Automation & Operations Assistant | Handles repeatable administrative workflows through authorized services with reliable state checks. |
| `/agent-copywriter` | Content Writer & Copywriter | Writes distinctive, accurate content matched to the audience, channel, and desired action. |
| `/agent-dataanalyst` | Data Analyst | Turns datasets into reproducible, decision-relevant analysis with clear limitations. |
| `/agent-docs` | Documentation Writer | Produces accurate, task-oriented documentation grounded in the actual product. |
| `/agent-marketing` | Growth & Marketing Strategist | Develops evidence-grounded positioning, channel plans, and measurable marketing experiments. |

<!-- roles:end -->

</details>

<details>
<summary>Local skills by category</summary>

<!-- skills:start -->

**design** — `accessibility`, `accessibility-verification`, `design-systems`, `design-to-code`, `frontend-design`, `motion-design`, `responsive-design`, `ui-audit`, `ux-writing`

**frontend** — `component-architecture`, `frontend-performance`, `shadcn-ui`, `stack-detection`, `tailwind`, `visual-verification`

**backend** — `api-contract-verification`, `api-design`, `authentication`, `authorization`, `background-jobs`, `caching`, `idempotency-and-retries`, `webhooks`

**database** — `data-integrity`, `data-pipelines`, `data-quality`, `database-migration-verification`, `migrations`, `postgres`, `query-optimization`, `schema-design`

**ai** — `agent-design`, `agent-evals`, `context-engineering`, `llm-observability`, `mcp-design`, `memory-design`, `model-routing`, `prompt-engineering`, `prompt-injection-defense`, `retrieval-rag`, `structured-output`, `tool-design`

**quality** — `browser-verification`, `e2e-testing`, `performance-profiling`, `regression-testing`, `systematic-debugging`, `test-design`, `test-strategy`

**security** — `agent-security`, `auth-security`, `dependency-security`, `owasp-web`, `secrets-management`, `secure-code-review`, `threat-modeling`

**devops** — `ci-cd`, `deployment`, `docker`, `github-actions`, `incident-response`, `observability`, `release-verification`, `rollback`

**product** — `experimentation`, `prd-and-stories`, `prioritization`, `product-analytics`, `product-discovery`

**knowledge** — `competitive-analysis`, `copywriting`, `data-analysis`, `deep-research`, `documentation-verification`, `positioning`, `seo`, `source-evaluation`, `technical-writing`

<!-- skills:end -->

Read the [skill catalog](docs/skills.md) for triggers and loadouts.

</details>

<details>
<summary>Workflow recipes</summary>

<!-- recipes:start -->

- **`build-production-ui`** — Design and implement an interface, then prove in a browser that it renders, responds and is reachable.
- **`database-migration`** — Change a live schema without losing data, with the rollback rehearsed before it is needed.
- **`debug-application`** — Reproduce, isolate, fix, and prove the fix with the original reproduction plus a regression test.
- **`investigate-incident`** — Stabilize a system that is failing right now, then hand off the root cause.
- **`research-technical-decision`** — Turn an open technical question into a decision with the evidence and the tradeoffs visible.
- **`review-pull-request`** — Judge a change against its stated intent and the evidence supplied, and say plainly what was not checked.
- **`security-review`** — Find real, reachable security problems and prove the remediation closed them — checked by someone who did not write the fix.
- **`ship-feature`** — Get a feature from request to merged, with the smallest set of specialists the work actually needs.
<!-- recipes:end -->

Recipes are adaptable starting points. Each describes when to use it and what to omit for
smaller tasks. See the [recipe guide](docs/recipes.md).

</details>

<details>
<summary>MCP and tool registry</summary>

<!-- mcps:start -->

| MCP | Purpose | Writes | Risk |
| --- | --- | --- | --- |
| `axe-devtools` | Automated accessibility scanning with code-level remediation guidance. | yes | medium |
| `chrome-devtools` | Drive Chrome with DevTools access: performance traces, network, console, DOM, plus full interaction. | yes | high |
| `cloudflare` | Cloudflare account and platform: API/config, docs, observability, Workers builds and bindings, Radar, browser rendering. | yes | high |
| `context7` | Fetch current, version-aware documentation for a library or framework instead of relying on stale model knowledge. | no | low |
| `datadog` | Query metrics, logs, traces, monitors and incidents. | yes | high |
| `figma` | Inspect design files, components, variables and design tokens, and compare an implementation against the design. | yes | medium |
| `github` | Repositories, files, issues, pull requests, commits, Actions and code search as an authoritative source of repository state. | yes | medium |
| `google-workspace` | Gmail, Calendar, Drive, Docs, Sheets, Slides, Chat and People as first-party MCP endpoints. | yes | high |
| `grafana` | Query Prometheus/Loki, read dashboards and alerts, inspect incidents and profiles. | yes | high |
| `linear` | Find, create and update issues, projects and comments. | yes | medium |
| `notion` | Search, read, create and update Notion pages and databases. | yes | medium |
| `playwright` | Drive a real browser: navigate, screenshot, interact, emulate viewports, read console and network. | yes | high |
| `postgres-community` | Generic Postgres access where no vendor server applies. | yes | high |
| `postgres-reference` | Recorded so nobody adds it: the Model Context Protocol reference Postgres server is no longer maintained. | no | unmaintained |
| `sentry` | Inspect issues, events, traces and releases; triage. | yes | medium |
| `slack` | Read channels and threads, search history, and send messages. | yes | high |
| `supabase` | Inspect and operate a Supabase project — schema, SQL, edge functions, logs, advisors. | yes | high |
| `vercel` | Inspect Vercel projects, deployments, logs and configuration, and run Vercel CLI operations. | yes | high |
| `workspace` | Read, search and edit files in the project, and run commands. | yes | medium |
<!-- mcps:end -->

See [MCP documentation](docs/mcps.md) for sources, activation conditions, and fallbacks.

</details>

External skill provenance, license notes, and fallback behavior are recorded in
[`catalog/external-skills.json`](catalog/external-skills.json). Review dependencies that execute
scripts before enabling them; see the [security guide](docs/security.md).

## Optional decision engine

Claude handles routing by default. The pack also includes an opt-in Jev integration for selecting
roles, skills, and tools from the catalog. **All Jev scopes ship disabled.** Normal use requires
no Jev account, key, or configuration.

Enabling Jev sends task text, candidate metadata, and relevant routing context to TypeSafe's API
using your own credential and billed usage. Task redaction is best-effort. See the
[Jev guide](docs/jev.md) for setup, payload details, modes, fallback behavior, and evaluation results.

The recorded comparison favors keeping the default path for routing and skill selection.
These are selection benchmarks, not evidence of better completed work: the Claude results
reconstruct the routing step in isolated cases, and end-to-end task evaluations are still missing.

## Documentation

| Guide | What it covers |
| --- | --- |
| [Architecture](docs/architecture.md) | Roles, skills, tools, recipes, and their boundaries. |
| [Context engine](docs/context-engine.md) | Context selection, budgets, provenance, and inspection. |
| [Skills](docs/skills.md) | Local and external skills, triggers, and loadouts. |
| [MCPs](docs/mcps.md) | Tool registry, availability, risks, and fallbacks. |
| [Recipes](docs/recipes.md) | Workflows and role handoffs. |
| [Verification](docs/verification.md) | Required evidence and reporting limits. |
| [Security](docs/security.md) | Permissions and dependency trust. |
| [Decision-engine evaluations](evals/decision/README.md) | Fixtures, measurement methods, and known limits. |
| [End-to-end evaluations](evals/end_to_end/README.md) | Compare stock Codex and Claude Code with the dispatcher on identical tasks. |
| [Claude Code adapter](adapters/claude-code/README.md) | Installation layout and generated files. |
| [Changelog](CHANGELOG.md) | Release history. |

## Contributing

Bug reports, routing examples, documentation improvements, and focused contributions are welcome.
Read [CONTRIBUTING.md](CONTRIBUTING.md) before editing: this repository keeps canonical sources
separate from generated artifacts.

```text
templates/                 Role definitions
skills/<category>/<id>/    Local skills and manifests
recipes/                   Workflow definitions
catalog/                   Registries and schemas
*.template.*               Dispatcher, context, and hook sources
decision/                  Optional decision-engine implementation
evals/decision/            Selection fixtures and evaluation harness
docs/                      Detailed guides
build.py                   Generator and validator
```

Edit source files, then run from the repository root:

```bash
python3 build.py
python3 test_build.py
python3 test_decision.py
python3 test_doctor.py
```

These checks run offline without provider credentials. They validate generated-file agreement,
references, loadout limits, registry consistency, hook behavior, and decision-engine boundaries.
The manual installer runs them before installation.

To run the offline keyword baseline:

```bash
python3 evals/decision/run.py
```

The keyword baseline is a measurement floor; it does not run Claude's in-session routing.
See [adding a role](docs/adding-an-agent.md) or [adding a skill](docs/adding-a-skill.md) to extend
the catalog. Preserve generated regions between `<!-- name:start -->` and `<!-- name:end -->`
markers in this README and the documentation.

For vulnerabilities, follow [SECURITY.md](SECURITY.md).

## License and provenance

[MIT License](LICENSE). Role origins and adaptation history are documented in [NOTICE](NOTICE).
Referenced third-party skills retain their own licenses. This project is not affiliated with
or endorsed by Anthropic or Locus.
