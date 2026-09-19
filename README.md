# agent-dispatcher

A Claude Code skill that routes each request to one of 27 specialist agent roles and works as that
specialist — chaining roles inside a turn when the work needs it.

## Use

- `/agent-dispatcher` — routes this request and every one after it, for as long as the session
  lasts. Nothing persists past the session.
- `/agent-dispatcher on` — perpetual mode: a SessionStart hook arms the dispatcher in **every future
  session, in every project**. `on` in one project only: `touch .agent-dispatcher-on` in its root.
- `/agent-dispatcher off` — stops it for this session. Per project: `touch .agent-dispatcher-off`
  in its root. Everywhere: `rm ~/.claude/.agent-dispatcher-active`. Silencing beats arming.
- `/agent-uidesigner`, `/agent-reviewer`, `/agent-tester`, … — force a role directly (27 commands).

When a role fans out, each subagent is routed to its own role rather than inheriting the caller's,
and a verifier never carries the role that produced the work.

Roles chain inside a turn when the work needs it (`planner → implementer`), up to three. An
installed skill or slash command that covers the request outranks routing — the role stays as
posture and the skill owns the method.

## Install

As a plugin (recommended — nothing is copied into your config, and it uninstalls cleanly):

```bash
claude plugin marketplace add nahid-sparktales/agent-dispatcher
```

then install `agent-dispatcher` from that marketplace. Or manually:

```bash
git clone https://github.com/nahid-sparktales/agent-dispatcher && cd agent-dispatcher && ./install.sh
```

`./install.sh --uninstall` reverses it, removing only the files it installed. Use one path or the
other, not both.

## The 27 roles

Each role carries its own working method, deliverable, definition of done, boundaries, and tool
posture. The dispatcher picks one from the request; the command forces it.

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

## Adding or editing a role

Role files are the source of truth. Drop a new `skills/agent-dispatcher/roles/<id>.md` in — copy an
existing one for the shape — and run `./install.sh`. Its frontmatter drives everything generated:

```yaml
---
id: version-control        # must match the filename
slug: git                  # becomes /agent-git
name: "Version Control"
category: "Engineering"    # Core | Engineering | Product & Design | Knowledge & Business | anything else -> Other
summary: "One sentence, shown in the command and the README."
use_when: "One sentence: when the dispatcher should route here."
not_for: "The neighbouring territory this role cedes — this is what keeps near-miss roles out."
tags: git, history, rebase, merge, recovery
---
```

Write `not_for` as territory other roles own, not as a list of bad habits — routing matches against
it, so "casual force-pushing" excludes nothing while "authoring the code change itself" excludes
`implementer`.

## Layout

    skills/agent-dispatcher/roles/*.md    SOURCE — one file per role, frontmatter + working method
    SKILL.template.md                     SOURCE — the router: activation, routing, chaining, contract
    build.py                              indexes the role files into everything below
    test_build.py                         asserts the generated files agree with the role files
    install.sh                            build, test, copy to ~/.claude, register the hook
    skills/agent-dispatcher/SKILL.md      generated router
    commands/agent-*.md                   generated per-role slash commands
    hooks/agent-dispatcher-activate.sh    generated perpetual-mode hook
    hooks/hooks.json                      plugin hook wiring
    .claude-plugin/                       plugin + marketplace manifests

Never edit a generated file; edit the role file or the template and rebuild.

## Provenance

MIT licensed. 24 of the roles began as the Locus Agent Template Pack v1.0.0 — an unlicensed,
unattributed content pack generated for this repo's author — with that pack's runtime, mode,
memory-scope, and access-level vocabulary replaced by Claude Code's equivalents; the working methods
are substantially its text. `version-control`, `data-engineer`, and `incident-responder` are
original here. Not affiliated with Locus. See NOTICE.
