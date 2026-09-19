# agent-dispatcher

**Capability-aware specialist routing for Claude Code.**

Routes each request to one of 27 specialist roles, keeps the role focused on responsibility, and
composes only the skills, tools and verification the job actually needs. Roles chain inside a turn
when a handoff materially improves the outcome; simple tasks stay simple.

<!-- counts:start -->**27 roles · 79 local skills · 31 external skills · 8 recipes · 19 MCP servers**<!-- counts:end -->

```text
request
  → smallest suitable specialist
  → relevant skills          (1–5, not everything installed)
  → available MCPs/tools     within existing permission
  → execution
  → verification             evidence, not confidence
  → review or handoff        only when warranted
  → result
```

Six concepts, deliberately not collapsed into each other:

**Agent** = responsibility · **Skill** = reusable method · **MCP/tool** = external capability ·
**Recipe** = reusable workflow · **Permission** = authorization · **Verification** = evidence.

Knowledge is not capability, and capability is not authorization.

## Use

```text
/agent-dispatcher            route this request and the rest of the session
/agent-dispatcher on         perpetual mode, every future session
/agent-dispatcher off        stop for this session
```

Perpetual mode runs through a `SessionStart` hook. Scopes:

| Scope | Arm | Silence |
| --- | --- | --- |
| Session | `/agent-dispatcher` | `/agent-dispatcher off` |
| Project | `touch .agent-dispatcher-on` **and** add the project path to `~/.claude/.agent-dispatcher-projects` | `touch .agent-dispatcher-off` |
| Everywhere | `touch ~/.claude/.agent-dispatcher-active` | delete that file |

Silencing beats arming. Project arming takes two steps on purpose: a flag file alone would let any
repository you clone switch your sessions into perpetual mode, so the allow-list lives in your own
config directory. Silencing stays repo-local, because it can only ever reduce behaviour.

Force a role directly with `/agent-uidesigner`, `/agent-debugger`, `/agent-reviewer` — 27 commands,
one per role.

When work fans out, each subagent is routed to the role that fits **its** assignment rather than
inheriting the caller's, and a verifier never carries the role that produced the work.

## Install

> The repository is currently **private**, so these URLs resolve only for accounts with access.

As a plugin — nothing is copied into your config, and it uninstalls cleanly:

```bash
claude plugin marketplace add nahid-sparktales/agent-dispatcher
```

Then install `agent-dispatcher` from that marketplace. Or manually:

```bash
git clone https://github.com/nahid-sparktales/agent-dispatcher
cd agent-dispatcher
./install.sh
```

`./install.sh --uninstall` reverses it. Use one path or the other, not both.

Everything lands under a single directory, `~/.claude/skills/agent-dispatcher/`, with skill
categories under its `lib/`. The pack never claims a top-level name like `security` or `design` in
your skills directory, never overwrites a command file it did not write, and backs up
`settings.json` before touching it.

# How the system works

## Agents own outcomes

Each role defines when to route to it, the neighbouring territory it cedes, its working method,
deliverable, definition of done, boundaries, tool posture and verification expectations. A role is
a stable operating contract, not an encyclopedia.

## Skills own reusable methods

79 focused skills — `frontend-design`, `accessibility`, `browser-verification`,
`systematic-debugging`, `api-design`, `migrations`, `threat-modeling` — shared across roles. A
designer uses `accessibility` to design, an implementer to build, a tester to check, a reviewer to
read evidence.

They load progressively: compact discovery metadata first, the full `SKILL.md` only once chosen,
references and scripts only when a step calls for them. A local id is its own directory name, so
`**/<id>/SKILL.md` finds it without reading any index.

Project signals — `package.json`, `next.config.*`, `components.json`, `supabase/`, `Dockerfile`,
`.github/workflows/`, `vercel.json` — activate conditional guidance. Detection never grants
permission.

The build enforces the restraint the design depends on: no role may carry more than five, or more
than 30KB of, always-on skills, and two skills providing the same capability cannot both sit in
tiers that load unconditionally.

## MCPs and tools provide real capability

19 servers in the registry, every one verified against its vendor's own documentation and recorded
with its write posture, risk, read-only path and — most importantly — what to do when it is absent.
GitHub for repository state, Playwright for rendered behaviour, Context7 for current framework
docs, Figma for design artifacts, Supabase for database state, Vercel and Cloudflare for
deployment, Sentry/Datadog/Grafana for production evidence.

**This repository installs none of them.** A configured server does not widen what an agent may do.

## Recipes provide proven workflows

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

Defaults, not pipelines. Every recipe names what to cut; the dispatcher shortens for small work and
extends when risk warrants.

## Verification is first-class

The system keeps **created, executed, tested, reviewed, deployed** and **verified** apart. A
migration file existing is not a migration that ran. A page compiling is not an interface that
works. A deploy command returning 0 is not a healthy service.

| Work | Evidence when available |
| --- | --- |
| UI | Render + interact + responsive inspection |
| Bug fix | Original reproduction + regression test that fails without the fix |
| API | Contract tests + failure and auth-failure paths |
| Database | Migration run on realistic data + integrity checks + rehearsed rollback |
| Performance | Comparable before/after measurement, not one fast run |
| Security | Re-test the affected boundary — and not by the author of the fix |
| Deployment | Correct revision serving + health signals |
| Documentation | Every command run, every link followed, every example executed |
| Agent change | Representative eval suite |

When verification cannot run, the report says so. "Source-level checks completed; rendered browser
verification was unavailable" — never "UI verified". See [docs/verification.md](docs/verification.md).

# The 27 roles

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

# Capability-aware routing

The dispatcher reasons about capabilities, not role names. For *"redesign and implement the
settings page and make sure it works on mobile"* it identifies `design.ui.direction`,
`frontend.architecture`, `design.responsive`, `verification.browser` and
`verification.accessibility`, then routes `UI/UX Designer → Implementer → Tester`.

A label change routes straight to Implementer. Multiple agents are justified by dependencies,
independent verification or real specialist boundaries — never by task length.

# Skill and MCP loadouts

A role declares its loadout in frontmatter. This is discovery and routing metadata, not a
permission grant:

```yaml
skills_core: anthropic-frontend-design, accessibility
skills_preferred: responsive-design, design-systems
skills_optional: motion-design, component-architecture
skills_if_existing_ui: ui-audit
skills_if_implementing_ui: design-to-code
skills_if_tailwind: tailwind
skills_if_shadcn: shadcn-ui
mcp_recommended: workspace, playwright
mcp_conditional: figma, axe-devtools, chrome-devtools
recipes: build-production-ui
verification: browser-verification, visual-verification, accessibility-verification
```

Generated into [`catalog/loadouts.json`](catalog/loadouts.json), which doubles as the dispatcher's
capability registry.

# Skills

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

Full table with triggers: [docs/skills.md](docs/skills.md).

# Third-party skill trust

External skills are dependencies. 31 are referenced — from Anthropic, Vercel, Next.js, Microsoft
Playwright and two community sources — and **none are vendored**. This repository records where
each lives and never copies its contents or runs its installer.

```text
Official → Verified → Community → Local
```

Each entry records source, repository, path, licence, version, verification date, trust level,
whether it ships scripts, whether it uses the network, the tools it needs, and the fallback for
when it is absent. Two licence findings worth knowing:

- The `frontend-design` skill in `anthropics/claude-code` sits under Anthropic's **Commercial
  Terms**, not an open-source licence. The byte-identical copy in `anthropics/skills` carries
  per-skill Apache-2.0 — that is the one cited here.
- `vercel-labs/agent-skills` states MIT in its README and in four skills' frontmatter, but has no
  LICENSE file at the repository root. Recorded as a caveat rather than assumed.

Before enabling any skill that ships scripts: read them, identify filesystem, network and
subprocess effects, and confirm it does not expand the agent's permissions. See
[docs/security.md](docs/security.md).

# MCP registry

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

Per-server detail, activation conditions and fallbacks: [docs/mcps.md](docs/mcps.md).

# Adding or editing a role

Canonical roles live in `templates/<category>/<id>.md`. Copy a sibling for the shape, then run
`./install.sh`.

```yaml
---
id: version-control
slug: git
name: "Version Control Engineer"
category: "Engineering"
summary: "Repairs, reshapes, and explains repository history without losing work."
use_when: "Git history, branches, merges, rebases, bisects, worktrees, or recovery are central."
not_for: "Locating or fixing the defect a commit introduced, or authoring the change itself."
tags: git, history, rebase, merge, recovery
---
```

Write `not_for` as territory another role owns. It is routing data, not a list of bad habits — it
is what keeps near-miss roles out. Full guide: [docs/adding-an-agent.md](docs/adding-an-agent.md).

# Adding a skill

A skill is narrower than an agent. `systematic-debugging`, `browser-verification`, `migrations`,
`accessibility` — never something that recreates an entire engineer.

```text
skills/<category>/<id>/
  SKILL.md        standard Agent Skills frontmatter: name + description only
  manifest.json   pack metadata, kept out of SKILL.md so the skill stays portable
  references/     loaded only when a step calls for them
  scripts/
```

Keep discovery metadata compact and disclose deeper content progressively. A skill improves method;
it does not redefine responsibility or authorization. Full guide:
[docs/adding-a-skill.md](docs/adding-a-skill.md).

# Repository layout

```text
templates/<category>/<id>.md          SOURCE — one role per file, loadout in frontmatter
skills/<category>/<id>/SKILL.md       SOURCE — standard Agent Skill + manifest.json sidecar
recipes/<id>.md                       SOURCE — workflow shapes
catalog/mcp.json                      SOURCE — MCP registry
catalog/external-skills.json          SOURCE — external skills with provenance
SKILL.template.md                     SOURCE — the router body
docs/                                 architecture, skills, mcps, recipes, verification, security
adapters/claude-code/                 what is rendered where, and why
adapters/locus/                       portable catalog export

build.py                              indexes sources, generates and validates
test_build.py                         validation suite
install.sh                            build, test, install, register

skills/agent-dispatcher/              GENERATED — router, rendered roles, index
commands/agent-*.md                   GENERATED — direct role commands
hooks/                                GENERATED — SessionStart hook
catalog/{skills,loadouts}.json        GENERATED — registries
```

**Edit canonical source; generate derived artifacts.** Never hand-edit a generated file — the test
suite fails the build if you do, because the next build would silently discard it. Every table and
count in this README and in `docs/` is generated between markers for the same reason.

# Evaluations

`build.py` and `test_build.py` run on every install. The suite checks generated-versus-source
agreement, generated-file drift, cross-reference resolution, standard `SKILL.md` frontmatter, body
length bounds, credential and absolute-path scanning, registry completeness, and docs-versus-catalog
counts.

Role files carry example tasks and boundary traps. Extending that into repeatable evals —
happy-path, ambiguous task, missing tool, tool failure, permission boundary, adversarial
instruction, overreach, underreach, verification, handoff — is the natural next step, comparing
`generalist` vs `specialist` vs `specialist + skill` vs `multi-agent recipe` on task success, missed
requirements, unsupported claims, verification completeness, unnecessary tool calls, context use and
scope creep. More agents and more skills are not automatically better.

# Provenance

MIT. 24 of the roles began as the Locus Agent Template Pack v1.0.0 — an unlicensed, unattributed
content pack generated for this repository's author — with that pack's runtime, mode, memory-scope
and access-level vocabulary replaced by Claude Code's equivalents. `version-control`,
`data-engineer` and `incident-responder` are original here, as are all local skills, recipes and
registries. Not affiliated with Locus. See [NOTICE](NOTICE).

# Design principle

```text
correct specialist
+ correct context
+ correct skill
+ correct tool
+ correct permission
+ correct verification
```

The goal is not the largest agent or skill library. It is a dispatcher that assembles the smallest
trustworthy capability stack for the requested outcome.
