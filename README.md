# agent-dispatcher

A Claude Code skill that routes each request to one of the 24 Locus agent-template roles and works as
that specialist. Generated from `locus-agent-templates.json`.

## Use

- `/agent-dispatcher` — route the current request (and the ones after it).
- `/agent-dispatcher on` / `off` — perpetual mode: arms the dispatcher at the start of every session
  via a SessionStart hook, flagged by `~/.claude/.agent-dispatcher-active`.
- `/agent-uidesigner`, `/agent-reviewer`, `/agent-tester`, … — pick a role directly (24 commands).

Roles chain inside a turn when the work needs it (`planner → implementer → tester`), up to three.

## The 24 roles

Each role carries its own working method, deliverable, definition of done, boundaries, and tool
posture. The dispatcher picks one from the request; the command forces it.

<!-- roles:start -->

### Core

| Command | Role | What it does |
| --- | --- | --- |
| `/agent-orchestrator` | Dispatcher | Coordinates bounded work, chooses available specialists, and owns the combined outcome. |
| `/agent-planner` | Planner | Turns a goal into an evidence-grounded, executable plan with acceptance criteria. |
| `/agent-researcher` | Researcher | Investigates questions, evaluates sources, and produces decision-ready findings. |
| `/agent-implementer` | Implementer | Builds focused, maintainable changes and verifies them against the task. |
| `/agent-tester` | Tester | Checks observable behavior, builds regression coverage, and reports reproducible failures. |
| `/agent-reviewer` | Reviewer | Independently evaluates a change or artifact and reports actionable, evidence-backed findings. |
| `/agent-generalist` | Generalist | Handles everyday tasks end to end and adapts depth and tools to the actual goal. |

### Engineering

| Command | Role | What it does |
| --- | --- | --- |
| `/agent-explorer` | Explorer | Maps an unfamiliar workspace and finds the exact code, files, and execution paths relevant to a task. |
| `/agent-architect` | Architect | Designs system boundaries, contracts, and tradeoffs that fit the existing product and constraints. |
| `/agent-debugger` | Debugger | Reproduces failures, tests hypotheses, and fixes the underlying cause with regression evidence. |
| `/agent-security` | Security Auditor | Reviews authorized systems for concrete security weaknesses and practical remediation. |
| `/agent-devops` | DevOps & Release Engineer | Builds reproducible delivery workflows and prepares or executes authorized releases with recovery checks. |
| `/agent-api` | API & Integration Engineer | Connects services with correct contracts, authorization, retry behavior, and failure handling. |
| `/agent-database` | Database Engineer | Designs and changes data storage with integrity, compatibility, and safe migration behavior. |
| `/agent-performance` | Performance Engineer | Measures bottlenecks and makes targeted improvements with reproducible before-and-after evidence. |
| `/agent-refactor` | Refactoring & Migration Specialist | Improves internal structure or moves systems to a new contract while preserving required behavior. |
| `/agent-aiengineer` | AI & Agent Engineer | Builds and evaluates agent prompts, routing, tools, memory, and execution behavior. |

### Product & Design

| Command | Role | What it does |
| --- | --- | --- |
| `/agent-pm` | Product Manager | Turns a vague request into a focused product scope, user flow, and measurable success criteria. |
| `/agent-uidesigner` | UI/UX Designer | Designs clear, distinctive interfaces and interaction flows, with implementation-ready details. |

### Knowledge & Business

| Command | Role | What it does |
| --- | --- | --- |
| `/agent-docs` | Documentation Writer | Produces accurate, task-oriented documentation grounded in the actual product. |
| `/agent-dataanalyst` | Data Analyst | Turns datasets into reproducible, decision-relevant analysis with clear limitations. |
| `/agent-marketing` | Growth & Marketing Strategist | Develops evidence-grounded positioning, channel plans, and measurable marketing experiments. |
| `/agent-copywriter` | Content Writer & Copywriter | Writes distinctive, accurate content matched to the audience, channel, and desired action. |
| `/agent-automation` | Automation & Operations Assistant | Handles repeatable administrative workflows through authorized services with reliable state checks. |
<!-- roles:end -->

## Layout

    locus-agent-templates.json   source catalog: 24 role templates
    build.py             generator — reads the template JSON, writes everything below
    SKILL.template.md    the router: activation, routing, chaining, shared contract ({{ROLES}} slot)
    install.sh           build + copy to ~/.claude + register the SessionStart hook
    skills/agent-dispatcher/SKILL.md      generated router
    skills/agent-dispatcher/roles/*.md    24 role files, loaded on demand
    commands/agent-*.md                   24 per-role slash commands
    hooks/agent-dispatcher-activate.sh    perpetual-mode hook (carries a compact role index)

Edit `SKILL.template.md` or `build.py`, then `./install.sh`. Never edit the generated files.

Source: Locus Agent Template Pack v1.0.0 (content pack, adapted here for Claude Code — the Locus
runtime, mode, memory-scope, and access-level settings were mapped to this harness's equivalents).
