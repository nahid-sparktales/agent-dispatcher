# Changelog

## Unreleased

- Stage Claude manual installations before replacing live files, with rollback for failed
  replacements and handled interruptions. Preserve recovery backups and a path mapping if
  rollback cannot finish; report post-commit cleanup failures accurately.
- Add `doctor` / `/agent-doctor` for read-only package health, full skill/tool/MCP inventory,
  session-evidence reconciliation, and role/project-based setup recommendations. Keep unknown,
  configured, exposed, connected, disabled, and retired capabilities distinct. Bundle the
  offline helper in both host packages and add recovery/doctor regression coverage.

- Add a Codex adapter with one discoverable dispatcher skill, all shared roles and supporting
  guides, native role/context/decision controls, a self-contained plugin export, and an owned
  install/update/uninstall path. Add opt-in Codex session activation with separate user-owned
  state and native hook trust review. Extend CI with Codex packaging and lifecycle regressions.
- Add GitHub Actions checks for Python 3.10–3.14 on Linux, Python 3.14 on macOS, generated-file
  drift, installer lifecycle, shell scripts, and workflow syntax. Add full-history and current-file
  Gitleaks scans, CodeQL for the public repository, and Dependabot updates for pinned Actions.
- Refuse malformed installation settings, symlinked targets, and manifest entries outside the
  owned command directory before modifying the installation. Preserve unrelated commands and
  hooks on uninstall, quote paths safely, and migrate older hook registrations on update.
- Ignore malformed decision configuration and require boolean scope flags and finite, bounded
  numeric settings. Recover non-object configuration in the mode command. Document the actual
  environment-over-project precedence.
- Parse provider URLs before allowing the loopback HTTP exception and remove transport-supplied
  error text from credential-bearing requests. Correct the claim of a hard response deadline;
  socket timeouts and late-result rejection do not guarantee an overall wall-clock limit.
- Detect missing and removed generated artifacts, and resolve build paths consistently when
  a checkout is accessed through a symlink. Add release regressions for the above behavior.

## 2.3.4 — 2026-09-19

2.3.3 claimed the silent-no-op class was addressed by running the hook. It was not, and the
claim is withdrawn.

Running the output catches a hook that is *broken*. It cannot catch an edit that never applied,
because the old behaviour was working — nothing is broken, so nothing fails. Moving the shell
into `HOOK.template.sh` did not fix it either: `build.py` still substitutes into that file, and
a `.replace()` whose search string stops matching misses exactly as quietly against a `.sh` file
as against an f-string. The file extension changes nothing about that.

### The actual fix

`sub()` and `render()` in `build.py`. A substitution that matches nothing is now fatal:

    build.py: {{ROLEZ}} is not in the text it was about to replace —
    the substitution would have silently applied to nothing

That is the one place the miss *can* be noticed, because it is the only place that knows a
replacement was intended. The artifact cannot show it — it keeps its old content, so the drift
check compares it against a rebuild that also kept the old content, and the two agree. Every
template substitution in the generator now goes through `sub()`.

It found four of these the moment it was added. `write_router` had been substituting
`{{SKILL_COUNT}}`, `{{EXTERNAL_COUNT}}`, `{{RECIPE_COUNT}}` and `{{MCP_COUNT}}` into
`SKILL.template.md`, which has not contained any of them for several releases. Four calls
quietly doing nothing, across eight commits, with a green suite the whole time.

### Also

- **`HOOK.template.sh`** — the perpetual-mode hook is a shell file rather than a Python
  f-string. That does not make failed edits louder, and the docstring now says so; what it does
  remove is the second escaping layer that produced a `printf` rendering its own escape
  sequences. It was also untracked while `build.py` hard-required it — a fresh clone would have
  died in `install.sh` before installing anything. A new check fails if any template the build
  reads is present locally but not committed, which is the only way to catch that: it builds
  fine for whoever has the file.
- **The preamble budget check was measuring the wrong thing.** It scraped the generated script
  for heredocs and counted those, missing ~1,000 bytes of `printf` output, and — being a regex
  over generated text — it would have passed at *zero bytes measured* if the heredoc marker were
  ever renamed. It now measures the hook's real stdout, with a lower bound so empty output fails.
- **Frontmatter quoting.** Values were emitted with an f-string and parsed by stripping the outer
  quote pair, so `name: "The "Fixer""` round-tripped through this repo agreeing with itself while
  being invalid YAML to anything else. `json.dumps` on the way out, `json.loads` on the way in,
  and an unescaped quote is now rejected with the fix in the message.
- **`--uninstall` deregistered the hook after deleting the script**, leaving `settings.json`
  starting a file that was gone. It also dropped the whole `SessionStart` entry, taking any hook
  of the user's own that shared it. Both fixed, and both pinned by tests that run the real script.
- `install.sh`'s two embedded Python blocks had never been checked to be valid Python, and the
  install and uninstall paths had never been executed by any test. Both now are.

### On the method

Every fix above came from an adversarial review that was told to verify rather than trust, and
several findings were refuted on inspection. The two that mattered most — the no-op guard and
the budget check measuring its own source — were confirmed by reintroducing the defect and
watching the suite go red. An assertion nobody has watched fail is a guess about what it covers.

## 2.3.3 — 2026-09-19

The SessionStart hook was checked by reading it. It is now checked by running it.

### Added

- **17 hook behaviour checks** in `test_build.py`, executing the real script against a temporary
  config dir and project dir with a JSON payload on stdin, the way the runtime invokes it. They
  cover the whole arm/silence matrix: a clean install arming nothing, global arming, session and
  project silencing beating a global arm, one silence not affecting another session or project,
  and the two-step allow-list.

  Three of them exist because of specific failures that every text-level check passed happily
  through:

  - **The escaping one.** A `printf` whose escape is wrong renders `\n` literally instead of a
    newline. The generator is valid Python, the shell script is valid bash, the drift check
    passes because the file matches what the generator produces — and the injected preamble is
    garbage. Caught now by asserting the rendered output contains no literal escape sequences.
    Reintroducing that bug fails the suite.
  - **The silent no-op.** An edit to the generator whose search string does not match leaves the
    artifact unchanged, and drift *passes*, because nothing changed. Running the output catches
    the ones that change behaviour, and only those. Moving the shell into `HOOK.template.sh`
    does not help here at all: a `.replace` against a `.sh` file misses exactly as quietly as one
    against an f-string.
  - **The security one.** The two-step project allow-list is the reason a cloned repository
    cannot switch your sessions into perpetual mode. That property had no test. Removing the
    allow-list check from the generator now fails two checks by name.

Each of the three was verified by reintroducing the defect and watching the suite go red, rather
than by assuming the assertion covers it.

### Fixed

- **Every substitution in `build.py` now refuses to be a no-op.** `sub()`/`render()` raise when
  the search string is absent, and `marked()` raises instead of returning the text when a
  `<!-- name:start -->` region is missing. This is the actual fix for the class above, and the
  only place it can be fixed: the generator is the one component that knows a substitution was
  intended. Nothing downstream can tell "the artifact is correct" from "the artifact was never
  touched" — the drift check compares stale content against a rebuild that is equally stale.

  It found four dead substitutions on its first run. `write_router` had been replacing
  `{{SKILL_COUNT}}`, `{{EXTERNAL_COUNT}}`, `{{RECIPE_COUNT}}` and `{{MCP_COUNT}}` in
  `SKILL.template.md` for several releases after the template stopped containing them. Removed.

  What this still cannot detect: a change someone meant to make and never wrote. That is not
  reachable from anything in the repository.

- **Role frontmatter is emitted and parsed as YAML, not assembled with literal quotes.**
  `write_roles` was building `name: "{value}"` by hand, so a `"` inside a template value produced
  `name: "The "Fixer""` — not YAML. It round-tripped clean: `read_frontmatter` stripped the outer
  pair whenever the first and last characters matched, handed the original string back, and the
  drift check compared a rebuild that made the same mistake. The generator now emits each quoted
  value with `json.dumps` (a JSON string is what YAML means by a double-quoted scalar) and
  `read_frontmatter` parses one with `json.loads`, so an unescaped quote in a template fails the
  build by name instead of shipping. No template carries a quote today, which is exactly why
  nothing static could see it: the check emits a quote-bearing role and parses the file back.

## 2.3.2 — 2026-09-19

Perpetual mode was documented as a set of files to `touch`. It was always a set of commands.

### Changed

- **The README leads with the commands.** `/agent-dispatcher on`, `on here`, `off`, `off here`,
  `off everywhere`, `status` — a six-row table of what you want and what to say. The flag files
  move into a collapsed section for anyone scripting it, which is the only audience that ever
  needed them. Nobody should have been typing `touch ~/.claude/.agent-dispatcher-active`; the
  skill has run that for them since 2.0, and the README simply never said so.
- **The scopes have canonical words.** `on here`, `off here` and `off everywhere` are defined
  forms rather than phrasings the router happened to match. Bare `off` still means *this
  session*, because that is what people mean mid-conversation, and the wider scopes now have to
  be spelled out so nothing global is disarmed by accident.
- **`/agent-dispatcher status` actually reports something.** It was an `ls` on one flag file. It
  now covers global arming, project arming, project and session silencing, and whether the
  SessionStart hook is installed at all — including the state that looks armed but is not: a
  project flag with no matching entry in the allow-list. Arming without the hook does nothing,
  and that was previously invisible.
- The perpetual-mode preamble the hook injects each session now tells Claude that the user says
  `/agent-dispatcher off` and Claude runs the command, rather than reading as instructions to
  hand over. Same mechanism, no longer phrased as homework.

The two-step project allow-list is unchanged and still deliberate: a flag file alone would let
any repository you clone arm your sessions, so the list lives in your own config directory where
a `git clone` cannot reach it. The README now explains that where someone deciding whether to
trust it will read it, rather than as a footnote to a table of shell commands.

## 2.3.1 — 2026-09-19

Two deletions, both because Jev is off by default and carrying weight for a disabled feature is
the wrong trade.

### Removed

- **The Vercel AI Gateway transport.** Vercel documents evaluation as available through their
  TypeScript SDK only, so it targeted an endpoint with no published REST contract, and with no
  gateway account it was never verified against a live provider — unit tests against a mock
  were the whole of its coverage. An unverifiable integration that handles a credential is the
  weakest thing to carry for a feature nobody should currently enable. TypeSafe's own HTTP API
  is now the only transport, and it is the only one either of them publishes a contract for.
  `decision/providers/` remains the seam if another route is worth adding.
- **93 lines of `docs/jev.md`.** The architecture, permission-boundary, credential-handling and
  results sections earn their space. The setup and troubleshooting depth did not, for a document
  that tells you not to enable the thing it documents.

### Changed

- README and `docs/jev.md` now say plainly that inside a Claude Code session the dispatcher
  always *is* already running, so the model turn Jev saves is not actually saved. Its remaining
  case — latency and cost — is for a standalone router, a pre-filter or a batch job, not for the
  path this pack ships on. That was implied before and is now stated.

## 2.3.0 — 2026-09-19

Finished the comparison and let it decide. Jev now installs inert.

### Measured

Three engines, identical fixtures, every decision measured for all three. Registry
`89baa5fa0e0c`:

                              baseline      jev           claude
  agent top-1                 23 / 162      143 / 162     158 / 162
  acceptable route            29 / 162      154 / 162     162 / 162
  near-neighbour top-1         6 / 54        49 / 54       53 / 54
  ambiguous top-1              3 / 27        17 / 27       25 / 27
  skill precision / recall    0.31 / 0.56   0.68 / 0.71   0.74 / 0.90
  tool precision / recall     0.15 / 0.23   0.65 / 0.97   0.69 / 0.95
  median latency              0 ms          358 ms        not comparable

`claude` is the production default path — the model reading the dispatcher's own catalog and
rules, replayed from recorded answers. It **matched or beat Jev on every decision**: decisively
on routing, clearly on skill recall at slightly better precision, and to a tie on tools, where
20 cases cannot separate a 0.04 gap.

Both engines crush the keyword floor, which is roughly what selecting from a loadout rather
than from the task gets you. 2.2 set its defaults against that floor. That was the wrong
comparison; this is the right one.

### Changed

- **Every decision scope is off by default.** Jev is installed, wired, tested and not called.
  Quality is no longer a reason to enable it — the default path is as good or better and costs
  no extra call, because the dispatcher is already running when it decides. Latency and cost
  still are: ~360 ms and a fraction of a cent against a full model turn, which is a real trade
  for a high-volume automated path, a latency budget, or anywhere the dispatcher is not in the
  loop. `AGENT_DISPATCHER_DECISION_SCOPES=skills,tools` turns on what you want.
- `status` says so plainly rather than looking broken: *idle — credential configured, no
  decision scope enabled*.

This is the architecture working. It was built so each decision could use whichever mechanism
the evidence supports, and the evidence came back for the default path. The integration stays
because the finding could change — a metadata rewrite, a new model version, a different fixture
set — and because the harness that produced this answer is now the thing that would notice.

### Added

- `replay.py` now serves skill and tool selections as well as routes, and distinguishes "not
  measured" from "selected nothing" rather than scoring a question nobody asked as a zero.
- `evals/decision/routes-claude.json` carries all three decisions for all 206 fixtures, with
  its method written down.

### Known holes

Unchanged and worth repeating: no end-to-end comparison exists, so nothing here shows a better
decision produces better work. The Claude column is a reconstruction — a focused subagent per
case, no competing work — which cuts against the conclusion rather than for it. And nothing
measures cost or throughput at volume, which is the case for Jev that remains.

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
