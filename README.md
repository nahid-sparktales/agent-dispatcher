# agent-dispatcher

An agent capability system for Claude Code. One skill routes each request to the right specialist
role, that role loads only the skills the work actually needs, and verification skills keep
"I wrote code" from being reported as "it works".

<!-- counts:start -->

**27 roles · 79 local skills · 31 external skills · 8 recipes · 19 MCP servers**<!-- counts:end -->

```
/agent-uidesigner "Redesign the settings modal"

→ ui-ux-designer
    loads  frontend-design · design-systems · accessibility
    detects Next.js + Tailwind + shadcn in the repo
    loads  nextjs · tailwind · shadcn-ui
    designs, implements
    renders it — desktop, then mobile, reloaded
    operates every control it touched
    checks the console and the keyboard path
    reports what was verified, and what was not
```

```
/agent-debugger "Login occasionally hangs"

→ debugger
    loads  systematic-debugging
    reproduces first — no reproduction, no diagnosis
    gathers evidence, forms a hypothesis that predicts something unseen
    isolates, fixes the cause rather than the reported path
    writes a regression test, confirms it fails without the fix
    runs the original reproduction again
```

Nothing above is loaded until it is needed. A role's frontmatter names skill ids; the agent
resolves them against an index and reads one to five of them. The other seventy stay on disk.

## Use

- `/agent-dispatcher` — routes this request and every one after it, for as long as the session
  lasts.
- `/agent-dispatcher on` — perpetual mode: a SessionStart hook arms the dispatcher in every future
  session, in every project. For one project only: `touch .agent-dispatcher-on` in its root.
- `/agent-dispatcher off` — stops it for this session. Per project: `touch .agent-dispatcher-off`.
  Everywhere: `rm ~/.claude/.agent-dispatcher-active`. Silencing beats arming.
- `/agent-uidesigner`, `/agent-reviewer`, `/agent-tester`, … — force a role directly.

Roles chain inside a turn when the work needs it (`planner → implementer`), up to three. When a
role fans out to subagents, each subagent is routed to its own role rather than inheriting the
caller's, and a verifier never carries the role that produced the work.

## Install

> The repository is currently **private**, so the URLs below resolve only for accounts with
> access. Clone it however you already can, or make it public first.

As a plugin — nothing is copied into your config, and it uninstalls cleanly:

```bash
claude plugin marketplace add nahid-sparktales/agent-dispatcher
```

then install `agent-dispatcher` from that marketplace. Or manually:

```bash
git clone https://github.com/nahid-sparktales/agent-dispatcher && cd agent-dispatcher && ./install.sh
```

`./install.sh --uninstall` reverses it, removing only the files it installed. Use one path or the
other, not both.

## The layers

| Layer | Answers | Lives in |
| --- | --- | --- |
| **Agent** | who is responsible | `templates/<category>/<id>.md` |
| **Recipe** | how capabilities combine into one run | `recipes/<id>.md` |
| **Skill** | how to perform one specialized thing | `skills/<category>/<id>/SKILL.md` |
| **Reference** | the detail one step needs | `skills/<category>/<id>/references/` |
| **MCP / tool** | what external state can be reached | `catalog/mcp.json` |
| **Verification** | evidence the outcome works | skills with `verifies: true` |

A skill teaches; it never authorizes. An MCP can reach something; that is not permission to change
it. See [docs/architecture.md](docs/architecture.md).

## Roles

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

## Skills

Local, written here. External and officially-maintained skills are referenced with provenance in
[`catalog/external-skills.json`](catalog/external-skills.json) — never vendored, never fetched at
runtime.

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

## Recipes

Default shapes for multi-step work, not chains that must run in full.

<!-- recipes:start -->

- **`build-production-ui`** — Design and implement an interface, then prove in a browser that it renders, responds and is reachable.
- **`database-migration`** — Change a live schema without losing data, with the rollback rehearsed before it is needed.
- **`debug-application`** — Reproduce, isolate, fix, and prove the fix with the original reproduction plus a regression test.
- **`investigate-incident`** — Stabilize a system that is failing right now, then hand off the root cause.
- **`research-technical-decision`** — Turn an open technical question into a decision with the evidence and the tradeoffs visible.
- **`review-pull-request`** — Judge a change against its stated intent and the evidence supplied, and say plainly what was not checked.
- **`security-review`** — Find real, reachable security problems and prove the remediation closed them — checked by someone who did not write the fix.
- **`ship-feature`** — Get a feature from request to merged, with the smallest set of specialists the work actually needs.<!-- recipes:end -->

## MCP servers

Recommended, not installed. Every entry was verified against the vendor's own documentation, and
records whether it writes, what it needs, and what to do when it is absent. See
[docs/mcps.md](docs/mcps.md) and [docs/security.md](docs/security.md).

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
| `workspace` | Read, search and edit files in the project, and run commands. | yes | medium |<!-- mcps:end -->

## Editing

Canonical sources are hand-edited; everything else is generated by `build.py` and validated by
`test_build.py`.

    templates/<category>/<id>.md          the role, plus its loadout in frontmatter
    skills/<category>/<id>/SKILL.md       standard Agent Skills frontmatter
    skills/<category>/<id>/manifest.json  pack metadata, kept out of SKILL.md
    recipes/<id>.md                       a workflow shape
    catalog/mcp.json                      MCP registry
    catalog/external-skills.json          external skills with provenance

    ./install.sh          build, validate, install
    python3 build.py      regenerate
    python3 test_build.py validate

Never edit a generated file: `skills/agent-dispatcher/`, `commands/`, `hooks/`,
`catalog/skills.json`, `catalog/loadouts.json`, or the tables in this README.

Adding things: [docs/adding-a-skill.md](docs/adding-a-skill.md),
[docs/adding-an-agent.md](docs/adding-an-agent.md).

## Provenance

MIT. 24 of the roles began as the Locus Agent Template Pack v1.0.0 — an unlicensed, unattributed
content pack generated for this repository's author — with that pack's runtime, mode, memory-scope
and access-level vocabulary replaced by Claude Code's equivalents. `version-control`,
`data-engineer` and `incident-responder` are original here, as are all local skills, recipes and
registries. Not affiliated with Locus. See [NOTICE](NOTICE).
