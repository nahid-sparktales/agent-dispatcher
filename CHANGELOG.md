# Changelog

## 2.2.1 — 2026-09-19

Ran the comparison v2.2 said had not been run, and changed a default because of what it said.

### Measured

Three engines, the same 162 routing fixtures, registry `89baa5fa0e0c`:

                              baseline      jev           claude
  agent top-1                 23 / 162      142 / 162     158 / 162
  acceptable route            29 / 162      153 / 162     162 / 162
  near-neighbour top-1         6 / 54        49 / 54       53 / 54
  ambiguous acceptable         9 / 27        26 / 27       27 / 27
  skill precision / recall    0.31 / 0.56   0.68 / 0.73   not measured
  tool precision / recall     0.15 / 0.23   0.66 / 0.97   not measured
  median latency              0 ms          357 ms        not comparable

`claude` is the production default path — the model reading the router's own catalog, replayed
from recorded routes. **It beats Jev on agent routing and is not close**, winning hardest where
the decision is hard: 53/54 near-neighbour against 49/54, 25/27 ambiguous against 17/27, and
162/162 acceptable against 153. It is also free in production, because the dispatcher is already
running. Jev wins skill and tool relevance by a wide margin.

### Changed

- **Agent selection is off by default.** The dispatcher keeps routing, as it always did. Switch
  it on with `AGENT_DISPATCHER_DECISION_SCOPES=agent,skills,tools` if your situation differs — a
  latency budget, a high-volume automated path. The abstraction exists precisely so each decision
  can use the mechanism the evidence supports, and this is that being used.
- Skill and tool relevance stay on: precision 0.31 → 0.68 for skills, with the share of
  selections carrying a known-irrelevant id falling 0.36 → 0.01, and 0.15/0.23 → 0.66/0.97 for
  tools.
- The candidate roster now includes `dispatcher`, which it wrongly excluded. `SKILL.md` keeps it
  in the catalog the model reads, so leaving it out asked the engines a different question than
  the default path answers and made five fixtures unwinnable for everyone.

### Added

- `evals/decision/replay.py` and `run.py --engine claude --routes <file>`: score decisions made
  out of band, so the production default path can be compared at all. Claude is the model running
  the dispatcher, not a service the harness can call.
- `evals/decision/routes-claude.json`: one recorded run of all 162 fixtures, with its method
  written down, so the comparison is repeatable without re-spending.
- `run.py --engine` is repeatable and takes `all`.

## 2.2.0 — 2026-09-19

Decision Engine v1. Routing answered *who*; the context engine answered *what with*. This release
names the layer that makes those bounded choices, and makes it swappable.

```text
request → decision engine → agent + skills + tools → context plan → context engine → specialist
```

The default path is unchanged. A clean installation needs no account, no key and no network, and
behaves exactly as 2.1 did.

### Added

- **A generic Decision Engine contract** (`decision/`) — `choose_agent`, `choose_skills`,
  `choose_tools`, plus `rank_context` and `evaluate_verification` declared for later. The context
  engine consumes `AgentDecision`/`SkillDecision`/`ToolDecision` and cannot tell which engine
  produced them, so a future reranker or local classifier arrives without reshaping anything above
  it. Strongly typed inputs and outputs, standard library only, no new dependency.
- **`DefaultDecisionEngine`** — the behaviour that already existed, expressed in the contract. It
  does not route: `SKILL.md` and the model still do, as always. Skills come from the loadout's
  `skills_core` and `skills_preferred`, tools from its `mcp_recommended`.
- **`JevDecisionEngine`** — optional, for users who supply their own credentials. One typed
  `choice` over the role roster with a confidence, one `noul` per candidate skill and per
  registered server. Two requests per task, not thirty-two; one when the user named a role.
  Providers for TypeSafe's documented HTTP API (default) and the Vercel AI Gateway, plus a mock.
- **Three modes** — `off` (no credential, no request), `auto` (the default: use it when it is
  there, fall back and record a diagnostic when it is not), `required` (fail clearly instead of
  falling back, so evaluation is controlled). `AGENT_DISPATCHER_OFFLINE=1` forces the default
  engine for local-only work.
- **`/agent-decision`** and `python3 -m decision status | mode | plan` — inspect and switch. Never
  prints a credential, never asks for one in chat.
- **`evals/decision/`** — 162 routing fixtures across all 27 roles (obvious, near-neighbour,
  ambiguous with multiple acceptable routes, and negative), 24 skill-selection and 20
  tool-relevance fixtures scored for precision as well as recall, and a harness that compares
  engines on identical inputs and reports observed accuracy per confidence band.
- **`test_decision.py`** — mode behaviour, fallback on timeout / 401 / 429 / 529 / malformed body /
  unknown id / low confidence, `required` erroring on each of those, forced-role precedence, the
  permission boundary, what a request is allowed to contain, and provider wire handling. No
  network, no credential, no cost.
- **[docs/jev.md](docs/jev.md)** — architecture, setup, modes, what is actually sent, cost
  responsibility, the permission boundary, the measured results and the calibration behind the
  thresholds.

### Changed

- `catalog/loadouts.json` now carries each role's `summary`, `use_when`, `not_for` and `tags`.
  That is the routing metadata, and it lives in the registry the build already generates so the
  decision layer has one canonical candidate source and no registry of its own.
- The context plan schema gains `selected_by` (`forced` · `recipe` · `default` · `jev`) and
  `confidence` on agents, skills and tools, plus a `decision` block recording the engine, whether
  it fell back, and the registry digest. Schema version 2.2.0.
- `CONTEXT.md` gains section 0, the decision engine, and says in three places that relevance,
  availability and authorization are three different facts.
- `/agent-context` names the engine that answered, shows a fallback rather than hiding one, and
  keeps the full candidate ranking behind `explain`.
- `install.sh` installs the engine and the registries it reads, and runs `test_decision.py`. It
  stays non-interactive and never asks for or writes a credential.

### Measured

162 routing fixtures against `jev-latest`, registry `89baa5fa0e0c`:

| | Lexical baseline | Jev |
| --- | --- | --- |
| Agent top-1 | 23 / 162 | 138 / 162 |
| Acceptable route | 28 / 162 | 150 / 162 |
| Near-neighbour top-1 | 6 / 54 | 48 / 54 |
| Skill precision / recall | 0.31 / 0.56 | 0.68 / 0.73 |
| Tool precision / recall | 0.15 / 0.23 | 0.64 / 0.97 |
| Median latency | 0 ms | 366 ms |

The baseline is a keyword floor, not what a real installation does — production hands routing to
the model, which cannot be scored offline. Confidence proved informative (0.98 observed accuracy
above 0.90, collapsing to 0.38 below 0.70), so the thresholds in `decision/config.py` are derived
from that table rather than guessed. No end-to-end comparison has been run.

### Security

- No credential is committed, embedded or shipped. The key lives in the environment; configuration
  exposes the variable's name and whether it is set, never its value; the provider reads it at
  request time and does not store it.
- A decision cannot authorize. No type has a field that could carry one, `assert_no_authorization()`
  raises if one appears, and the suite runs it against "deploy to production" and "delete the
  production database" with the relevant tool at 100%.
- A request carries the scrubbed, capped task text, detected technology names and compact registry
  metadata. Not repository source, file contents, environment or conversation history.
- Every id an external engine returns is validated against the registry before it reaches a plan,
  and is character-filtered before being echoed into a diagnostic.
- The transport refuses a credential a header cannot carry, refuses a non-https base URL, and
  refuses redirects — urllib's default handler replays `Authorization` across hosts on a 302.
  Exceptions from below the provider are replaced rather than wrapped, and `required`-mode
  errors are raised `from None`, so no traceback can quote a request header.
- The response is size-capped and read against a wall-clock deadline; `timeout` alone is
  per socket read and does not bound the exchange.
- The project config file can no longer set the diagnostics log path — a cloned repository
  should not choose a file to create and append to — and a bad value in it is dropped rather
  than raised.
- The mock transport is not reachable from configuration. A test double a user can select is a
  test double that can fabricate a plan and have it rendered as a real one.

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
