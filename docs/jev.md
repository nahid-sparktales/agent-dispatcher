# The optional Jev decision engine

`agent-dispatcher` works with no Jev account and no API key, and **ships with Jev switched off on
every decision.** This document is about the part you can switch on, and mostly about why you
probably should not.

A **decision engine** answers the dispatcher's bounded choices: which of 27 roles owns a task,
which one to five skills that role loads, which of 19 registered servers are relevant. Those are
classifications over a fixed candidate set — a different shape of work from the reasoning,
coding, design and research the specialist then does.

```text
Claude   →  complex reasoning, planning, code, design, research, execution
Jev      →  bounded structured decisions, in a few hundred milliseconds
```

That framing is what motivated the integration. The evaluation then tested it, and the answer is
in **Results** below: on this repository's own fixtures Claude matched or beat Jev on every
decision, so quality is not a reason to enable it. Latency and cost still are.

| | Default | Jev |
| --- | --- | --- |
| Requires | nothing | your own provider credential |
| Network | none | one or two HTTPS requests per task |
| Agent | the model reading `SKILL.md` | a typed choice over the roster, with a confidence |
| Skills | the model, from the role's loadout | a relevance score per candidate |
| Tools | the model, from `mcp_recommended` | a relevance score per registered server |
| Cost | none | yours, billed to the account that owns the key |
| On by default | yes, all of it | **no — every scope is off** |

Everything downstream is identical either way: same context plan, same context engine, same
permission enforcement, same specialist execution, same verification.

## Architecture

```text
                          USER TASK
                              │
                              ▼
                      Decision Engine            default  ·  jev
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
            Agent           Skills           Tools
              │               │               │
              └───────────────┼───────────────┘
                              ▼
                        Context Plan  →  Context Engine  →  CLAUDE  →  Verification
```

Running alongside it, and never touched by any of it:

```text
              PERMISSION / AUTHORIZATION
       enforced by the runtime, independently
         never granted or widened by a decision
```

`DecisionEngine` (`decision/engine.py`) has two implementations: `DefaultDecisionEngine`, which
is the behaviour that already existed, and `JevDecisionEngine`, which talks to a provider in
`decision/providers/`. The context engine consumes `AgentDecision`, `SkillDecision` and
`ToolDecision` from `decision/types.py` and has no way to tell which produced them — that is
what lets a different engine arrive without touching anything above this layer.

## Setup

```bash
export TYPESAFE_API_KEY="your-own-key"
export AGENT_DISPATCHER_DECISION_SCOPES=skills,tools   # nothing runs without this
python3 -m decision status
```

TypeSafe's own HTTP API is the only transport, because it is the only route they publish a REST
contract for. A Vercel AI Gateway transport existed briefly and was removed: Vercel documents
evaluation as available through their TypeScript SDK only, so it targeted an undocumented
endpoint and could never be verified against a live account. Carrying an unverifiable
integration that handles a credential, for a feature that is off by default, was the wrong
trade. `decision/providers/` is still the seam if another route is worth adding.

`install.sh` never asks for a key, never writes one, and installs the engine inert.

## Modes and scopes

```text
off        never used. No credential needed, no request made.
auto       the default. Use Jev where a scope is enabled, fall back where it fails.
required   fail with a clear error instead of falling back.
```

Modes decide *whether* Jev may answer; **scopes decide what it is asked**, and all five ship off,
so `auto` with no scope enabled is indistinguishable from `off`.

**`auto`** falls back to the default engine on a timeout, an HTTP error, a rate limit, a
malformed body, an answer whose ids do not resolve, or a confidence below the floor — recording
a diagnostic each time. An optional optimisation must never be why a task fails.

**`required`** never falls back, so you can be sure Jev actually ran. For evaluation, and for
developers who want an error rather than a silent downgrade.

**`off`**, or `AGENT_DISPATCHER_OFFLINE=1`, for privacy-sensitive, offline and baseline work.

`context` (ranking retrieved files) and `verification` (judging whether evidence is sufficient)
are declared in the `DecisionEngine` interface and unimplemented — designed for, not shipped.

## Configuration

Precedence, highest first: an explicit flag → `.agent-dispatcher-decision.json` in the project →
the environment → the defaults.

| Key | Env | Default |
| --- | --- | --- |
| `mode` | `AGENT_DISPATCHER_DECISION_MODE` | `auto` |
| `scopes` | `AGENT_DISPATCHER_DECISION_SCOPES` | *(none)* |
| `model` | `AGENT_DISPATCHER_DECISION_MODEL` | `jev-latest` |
| `timeout_seconds` | `AGENT_DISPATCHER_DECISION_TIMEOUT` | `10` |
| `max_task_chars` | `AGENT_DISPATCHER_DECISION_MAX_TASK_CHARS` | `2000` |
| `thresholds` | `AGENT_DISPATCHER_DECISION_THRESHOLDS` | see calibration |
| `log` | `AGENT_DISPATCHER_DECISION_LOG` | off — env only, never the project file |

The credential is deliberately not in that table. It is never a config key, never written to a
file by this pack, and never carried on a config object. The provider reads it from the
environment at the moment of the request.

## Privacy: what is actually sent

For agent selection, the state is:

```json
{"task": "<scrubbed, capped task text>", "detected_stack": ["Next.js", "Postgres"]}
```

plus the compact routing metadata already in `catalog/loadouts.json` — each role's `summary`,
`use_when` and `not_for`, about 9 KB for all 27. For skills and tools, the same plus the selected
role and the candidates its loadout already named.

Not sent: repository source, file contents, environment variables, conversation history, git
data, or the 27 full role prompts. `decision/redact.py` caps the task at 2,000 characters and
scrubs recognisable credential shapes — a pasted 400-line log almost never changes which
specialist owns the work and very often contains something that should not leave the machine.

Redaction is defensive, not a guarantee. It catches token shapes; it cannot catch a password
that looks like a word. It also deliberately does not fire on ordinary prose — *"the auth token
is expired"* is routing signal and survives, *"the password is hunter2hunter2"* does not. If the
task text itself is sensitive, use `off` for that task.

Enabling Jev means an external provider sees your task text. That is the trade, stated plainly.

## Cost

You supply the key and you pay the provider. At the time of writing TypeSafe prices Jev input
tokens only, and the full 206-case evaluation cost roughly two cents — but pricing changes, so
check the provider rather than this file. Nothing in the runtime hardcodes a price.

This repository ships no key, proxies nothing through a maintainer account, and makes no
background or idle calls.

## Permission boundary

```text
Jev:      "this task appears to need the deployment capability"  — relevance
Runtime:  "is deployment authorized?"                            — authorization
```

A decision result cannot grant a workspace write, a database write, a deployment, a message
send, an external publication, an OAuth scope, or an exemption from a user approval. A tool at
100% relevance is a tool that would help; whether it may be *used* is a question the runtime
answers and never asks this layer about.

Enforced, not just asserted:

- No type in `decision/types.py` has a field that could carry an authorization.
- `assert_no_authorization()` walks a decision payload and raises on any permission-shaped key,
  matching on tokens so `permissionGranted` and `granted_permissions` both fail.
- `test_decision.py` runs it against *"deploy to production"* and *"delete the production
  database"* with the relevant tool scored at 100%, and fails the build if anything appears.
- `test_build.py` fails if a candidate's criteria text carries a `writes` or `risk` posture — a
  relevance model is never shown them.

Same rule the rest of the pack lives by: a skill teaches without authorizing, a detected stack
activates guidance without authorizing, a configured server is availability and not permission.

## How the credential is protected

The key lives in the environment and nowhere else. The transport is written so redaction is
never the last line of defence:

- A credential carrying anything a header cannot hold — a line break from a wrapped paste — is
  **refused before the request is built**, with a message quoting none of it. Otherwise
  `http.client` raises a `ValueError` that quotes the whole `Bearer <key>` line.
- A non-`https` base URL is refused (loopback excepted, for a local stub).
- **Redirects are refused.** urllib's default handler copies every header except content-type
  and content-length into the redirected request, replaying `Authorization` to whatever host a
  302 names.
- Any exception from below the provider is replaced, not wrapped — the class name survives, the
  message does not. `required`-mode errors are raised `from None` so a traceback cannot
  resurrect it.
- The response is size-capped and read against a wall-clock deadline; urllib's `timeout` is per
  socket read and does not bound the exchange.
- Ids an external engine returns are character-filtered and truncated before being echoed into a
  diagnostic, even when the next thing that happens is rejecting them.
- The plan's own `task` field carries the scrubbed, capped text, because it is rendered,
  serialised with `--json`, and shown by an agent.

## Validation

External model output is untrusted input. Every returned id is resolved against the canonical
registry before it reaches a context plan, and one that does not exist is discarded and recorded
rather than invented. Candidates come from the registry, so Jev selects among what it was given
and cannot add to the set. A route below the confidence floor is rejected. A response that is not
JSON, carries no `answers`, or answers nothing usable is an error — and an error is a fallback.

There is no second registry. A role becomes a candidate because `templates/<category>/<id>.md`
gave it routing metadata and `build.py` carried that into `catalog/loadouts.json`; a skill
because its `manifest.json` reached `catalog/skills.json`. Adding one the normal way is all it
takes — see [adding-an-agent.md](adding-an-agent.md).

## Evaluation

```bash
python3 evals/decision/run.py                     # the keyword baseline — free, offline
python3 evals/decision/run.py --engine all --routes evals/decision/routes-claude.json
```

162 routing fixtures cover all 27 roles — obvious cases, near-neighbour cases where a sibling
role is the trap, genuinely ambiguous cases with several acceptable routes, and negative cases a
keyword matcher would misroute. Plus 24 skill and 20 tool fixtures scored for precision as well
as recall, because a system that selects everything has perfect recall and no value.
[evals/decision/README.md](../evals/decision/README.md) has the method.

### Results

`jev-latest` through the TypeSafe API, registry `89baa5fa0e0c`, 2026-09-19. Three engines,
identical fixtures, every decision measured for all three.

| | Keyword baseline | Jev | Claude |
| --- | --- | --- | --- |
| Agent top-1 | 23 / 162 | 143 / 162 | **158 / 162** |
| Acceptable route | 29 / 162 | 154 / 162 | **162 / 162** |
| Obvious, top-1 | 9 / 54 | 52 / 54 | **54 / 54** |
| Near-neighbour, top-1 | 6 / 54 | 49 / 54 | **53 / 54** |
| Ambiguous, top-1 | 3 / 27 | 17 / 27 | **25 / 27** |
| Negative, top-1 | 5 / 27 | 25 / 27 | **26 / 27** |
| Skill precision / recall | 0.31 / 0.56 | 0.68 / 0.71 | **0.74 / 0.90** |
| Tool precision / recall | 0.15 / 0.23 | 0.65 / **0.97** | **0.69** / 0.95 |
| Median decision latency | 0 ms | 358 ms | not comparable |

`Claude` is the production default path, replayed from `evals/decision/routes-claude.json` — one
focused subagent per fixture, handed the dispatcher's own rules and the same candidate set the
engine gets, and nothing else. Its latency is not comparable: in production, deciding costs no
extra call, because the dispatcher is already running.

**Claude matched or beat Jev on every decision.** Routing is not close. Skill selection it wins
on recall by a wide margin at slightly better precision. Tool relevance is a tie — on 20 cases a
0.04 gap is noise.

**Both crush the floor.** The keyword baseline is roughly what selecting from a loadout rather
than from the task gets you, and it is what the first cut of these defaults was measured
against. That was the wrong comparison.

So every scope ships off. That is this architecture working: it was built so each decision could
use whichever mechanism the evidence supports, and the evidence came back for the default path.

**What is left for Jev is latency and cost** — ~360 ms and a fraction of a cent against a full
model turn. That is a real trade for a high-volume automated path, a hard latency budget, or
anywhere the dispatcher is not already in the loop: a standalone router, a pre-filter, a batch
job. Be clear-eyed that inside a Claude Code session the dispatcher always *is* already running,
so the saved turn is not saved. Throughput is the reason to switch it on; quality is not.

### Confidence calibration

Observed top-1 accuracy per confidence band, same run:

| Confidence | Jev n | Jev top-1 | Claude n | Claude top-1 |
| --- | --- | --- | --- | --- |
| 0.90 – 1.00 | 109 | 0.98 | 99 | 1.00 |
| 0.80 – 0.90 | 18 | 0.94 | 42 | 0.98 |
| 0.70 – 0.80 | 13 | 0.69 | 14 | 0.93 |
| 0.50 – 0.70 | 16 | 0.38 | 7 | 0.71 |
| below 0.50 | 6 | 0.67 | 0 | — |

Both are informative, and Jev's collapses harder and sooner. `agent_confidence` is **0.80** for
anyone who switches agent selection on: above it Jev was right 96% of the time, below it the
default path is safer. TypeSafe's own guidance puts the absolute floor at 0.50; this is stricter
because routing a whole task is not a cheap action to get wrong. The relevance floors are the
precision knee from a sweep over the same fixtures — past 0.60 skill recall falls away for no
precision gain — so **0.60**.

Numbers move a little between runs: five runs of the routing set scored 136–143 out of 162, with
the shape holding every time. Re-derive rather than trusting the table, especially after role
metadata changes:

```bash
AGENT_DISPATCHER_DECISION_THRESHOLDS=skill_relevance=0.7 python3 evals/decision/run.py --engine jev
```

### What this does not establish

- **No end-to-end comparison.** Whether a better decision produces better *work* is untested.
- The Claude column is a reconstruction — a focused subagent per case, no conversation, no
  competing work. A real in-session dispatcher could do worse. That cuts against the conclusion
  drawn from it, and it is the biggest hole in it.
- Tool selection is 20 cases; the gap there is reported as a tie rather than a win.
- 4 to 9 gold labels per role, so macro numbers lean on the best-covered roles.
- Nothing measures cost or throughput at volume, which is the case for Jev that remains.

## Diagnostics and troubleshooting

`/agent-context` names the engine that answered, the confidence beside each selection, and any
fallback:

```text
Decision Engine
  Default
  jev attempted but unavailable: timeout
  Fallback: successful
```

Nothing is sent anywhere. Local records — engine, decision type, latency, candidate count,
selection, confidence, fallback, error kind, token usage — stay in memory unless you ask:
`AGENT_DISPATCHER_DECISION_LOG=~/.claude/decision-log.jsonl`. A record has no field that could
hold a credential, and provider errors are recorded as a kind rather than verbatim.

| Symptom | Cause |
| --- | --- |
| `status` says *idle* | no decision scope is enabled. That is the shipped default; set `AGENT_DISPATCHER_DECISION_SCOPES`. |
| `status` says *not configured* | no credential in `TYPESAFE_API_KEY`. Also a supported state. |
| `/agent-context` says Default unexpectedly | the mode is `off`, the scope is off, the session is offline, or a fallback happened — the diagnostics line says which. |
| *credential rejected (401)* | wrong or revoked key. |
| *rate limited (429)* / *overloaded (529)* | provider throttled. `auto` already fell back; `required` will keep erroring. |
| Routes look wrong | `/agent-context explain` for the full ranking, then `python3 evals/decision/run.py --engine all --routes evals/decision/routes-claude.json`. |
| `ModuleNotFoundError: decision` | run from the pack directory, or `PYTHONPATH=~/.claude/skills/agent-dispatcher python3 -m decision status`. (`AGENT_DISPATCHER_HOME` relocates the registries, not the module.) |
