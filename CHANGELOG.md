# Changelog

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
