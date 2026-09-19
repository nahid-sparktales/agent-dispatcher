# The optional Jev decision engine

`agent-dispatcher` works with no Jev account, no Vercel account and no API key. This document is
about the part you can switch on if you want to, and why you might not.

A **decision engine** answers the dispatcher's bounded choices: which of 27 roles owns a task,
which one to five skills that role should load, which of 19 registered servers are relevant.
Those are classification problems with a fixed candidate set — a different shape of work from
the reasoning, coding, design and research the specialist then does.

```text
Claude   →  complex reasoning, planning, code, design, research, execution
Jev      →  bounded structured decisions, in a few hundred milliseconds
```

There are two engines and one contract.

| | Default | Jev |
| --- | --- | --- |
| Requires | nothing | your own provider credential |
| Network | none | one or two HTTPS requests per task |
| Agent | the dispatcher's own routing, as always | a typed choice over the roster, with a confidence |
| Skills | the role's `skills_core` + `skills_preferred` | a relevance score per candidate in the loadout |
| Tools | the role's `mcp_recommended` | a relevance score per registered server |
| Cost | none | yours, billed to the account that owns the key |

Everything downstream is identical. Same context plan, same context engine, same permission
enforcement, same specialist execution, same verification. Jev changes how a bounded choice is
made; it does not create a second execution path.

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
                        Context Plan
                              ▼
                       Context Engine
                              ▼
                           CLAUDE
                              ▼
                        Verification
```

Running alongside it, and never touched by any of it:

```text
              PERMISSION / AUTHORIZATION
                        │
       enforced by the runtime, independently
                        │
         never granted or widened by a decision
```

The abstraction is deliberately named for the job, not the vendor:

```text
DecisionEngine                      decision/engine.py
├── DefaultDecisionEngine           decision/default.py    — the behaviour that already existed
├── LexicalDecisionEngine           decision/default.py    — an offline measurement baseline
└── JevDecisionEngine               decision/jev.py
        └── provider                decision/providers/    — typesafe · vercel · mock
```

The context engine consumes `AgentDecision`, `SkillDecision` and `ToolDecision` from
`decision/types.py`. It has no way to tell which engine produced them, which is what lets a
future engine — a reranker, a local classifier, a different provider — arrive without touching
anything above this layer.

## Setup

Jev is reachable two ways. Pick one.

**TypeSafe directly** — the default, and the one to use. TypeSafe publishes the REST contract, so
a Python caller gets a documented, supported integration.

```bash
export TYPESAFE_API_KEY="your-own-key"
```

**Vercel AI Gateway** — for accounts that already bill through the gateway. Vercel's own
documentation says the evaluation modality is "available through the AI SDK only", so this pack
talks to the gateway's evaluation route without a published REST contract behind it. It works,
it is tested, and it is the less-supported of the two. Use it only if the billing relationship
is the reason.

```bash
export AI_GATEWAY_API_KEY="your-own-key"
echo '{"provider": "vercel"}' > .agent-dispatcher-decision.json
```

Then check it:

```bash
python3 -m decision status
```

That is the whole of the setup. `install.sh` never asks for a key, never writes one, and
installs the engine inert.

## Modes

```text
off        never used. No credential needed, no request made, default engine answers.
auto       the default. Use Jev when it is configured and healthy, fall back when it is not.
required   fail with a clear error instead of falling back.
```

```bash
python3 -m decision mode auto        # writes .agent-dispatcher-decision.json
/agent-decision auto                 # the same thing, from inside a session
```

**`auto`** is what you want. With no key configured, or with no scope enabled, it is
indistinguishable from `off` — no lookup, no request, no warning. With a key it uses Jev, and on a timeout, an HTTP error, a rate
limit, a malformed body, an answer whose ids do not resolve, or a confidence below the floor, it
records a diagnostic and falls back to the default engine. An optional optimisation must never
be the reason a task fails.

**`required`** exists so you can be sure Jev actually ran — for evaluation, and for developers
who want an error rather than a silent downgrade. It never falls back.

**`off`** for privacy-sensitive work, offline work, debugging, and baseline runs.
`AGENT_DISPATCHER_OFFLINE=1` has the same effect without changing configuration.

## Configuration

Precedence, highest first: an explicit flag → `.agent-dispatcher-decision.json` in the project →
the environment → the defaults.

| Key | Env | Default |
| --- | --- | --- |
| `mode` | `AGENT_DISPATCHER_DECISION_MODE` | `auto` |
| `provider` | `AGENT_DISPATCHER_DECISION_PROVIDER` | `typesafe` |
| `model` | `AGENT_DISPATCHER_DECISION_MODEL` | `jev-latest` |
| `timeout_seconds` | `AGENT_DISPATCHER_DECISION_TIMEOUT` | `10` |
| `max_task_chars` | `AGENT_DISPATCHER_DECISION_MAX_TASK_CHARS` | `2000` |
| `scopes` | `AGENT_DISPATCHER_DECISION_SCOPES` | `agent,skills,tools` |
| `thresholds` | `AGENT_DISPATCHER_DECISION_THRESHOLDS` | see below |
| `log` | `AGENT_DISPATCHER_DECISION_LOG` | off |

Scopes are per decision, not global, because the right engine for one decision is not
necessarily the right engine for another. All five ship off. Turn on what you want:
`AGENT_DISPATCHER_DECISION_SCOPES=skills,tools`. `context` (ranking retrieved files) and
`verification` (judging whether evidence is sufficient) are declared in the interface and
unimplemented — designed for, not shipped, and enabling them would claim something no
evaluation supports.

The credential is not in that table on purpose. It is never a config key, never written to a
file by this pack, and never carried on a config object. The provider reads it out of the
environment at the moment of the request.

## What is actually sent

For agent selection:

```json
{"task": "<scrubbed, capped task text>", "detected_stack": ["Next.js", "Postgres"]}
```

plus the compact routing metadata already in `catalog/loadouts.json` — each role's `summary`,
`use_when` and `not_for`, about 9KB for all 26 candidates. For skills and tools, the same state
plus the selected role, and the descriptions of the candidates the loadout already named.

Not sent: repository source, file contents, environment variables, conversation history, git
data, the 27 full role prompts, or anything the decision does not need. `decision/redact.py`
scrubs recognisable credential shapes out of the task text first and caps it at 2,000
characters — a pasted 400-line log almost never changes which specialist owns the work and very
often contains something that should not leave the machine.

Redaction is a defensive layer, not a guarantee. It catches token shapes; it cannot catch a
password that looks like a word or an internal identifier that matters to you. It also does not
fire on ordinary prose — "the auth token is expired" is routing signal and survives, while "the
password is hunter2hunter2" does not — which is a deliberate trade in favour of not destroying
the task. If the task text
itself is sensitive, use `off` for that task. That is what the mode is for.

Enabling Jev means an external model provider sees your task text. That is the trade, stated
plainly.

## Cost

You supply the key and you pay the provider. At the time of writing TypeSafe prices Jev input
tokens only, and the full 206-case evaluation in this repository cost roughly two cents — but
pricing changes, so check the provider rather than this file, and nothing in the runtime
hardcodes a price.

This repository ships no key, proxies nothing through a maintainer account, and makes no
background or idle calls. A request happens only when a task needs a decision.

## How the credential is protected

The key lives in the environment and nowhere else. Beyond that, the transport is written so
that redaction is never the thing standing between it and a log file:

- A credential containing anything a header cannot carry — a line break from a wrapped paste, a
  stray space — is **refused before the request is built**, with a message that quotes none of
  it. Otherwise `http.client` raises a `ValueError` that quotes the whole `Bearer <key>` line.
- A base URL that is not `https` is refused (loopback excepted, for a local stub), so the
  header is never sent in cleartext.
- **Redirects are refused.** urllib's default handler copies every header except content-type
  and content-length into the redirected request, which replays `Authorization` to whatever
  host a 302 names.
- Any exception from below the provider's own code is replaced, not wrapped — the class name
  survives and the message does not, because that message is the one thing that might quote a
  request header. `required`-mode errors are raised `from None` so a traceback cannot resurrect
  it either.
- The response body is size-capped and read against a wall-clock deadline, because
  urllib's `timeout` is per socket read and a drip-feed can outlive it indefinitely.
- Ids an external engine returns are filtered to `[A-Za-z0-9._-]` and truncated before being
  echoed into a diagnostic, even when the next thing that happens is rejecting them.
- The plan's own `task` field carries the scrubbed, capped text, not the original — it is
  rendered, serialised with `--json`, and shown by an agent.

## Permission boundary

This is the part worth reading twice.

```text
Jev:      "this task appears to need the deployment capability"  — relevance
Runtime:  "is deployment authorized?"                            — authorization
```

A decision result cannot grant a workspace write, a database write, a deployment, a message
send, an external publication, an OAuth scope, or an exemption from a user approval. A tool at
100% relevance is a tool that would help; whether it may be *used* is a question the runtime
answers and never asks this layer about.

This is enforced, not just asserted:

- No type in `decision/types.py` has a field that could carry an authorization.
- `assert_no_authorization()` in `decision/engine.py` walks a decision payload and raises on any
  permission-shaped key.
- `test_decision.py` runs it against tasks like *"deploy to production"* and *"delete the
  production database"* with the relevant tool scored at 100%, and fails the build if anything
  permission-shaped appears.
- `test_build.py` fails the build if a candidate's criteria text carries a `writes` or `risk`
  posture — a relevance model is not shown them.

It is the same rule the rest of the pack already lives by: a skill teaches without authorizing,
a detected stack activates guidance without authorizing, a configured server is availability and
not permission. A decision engine is one more thing in that list.

## Validation

External model output is untrusted input, and is treated as such:

- Every returned id is resolved against the canonical registry before it reaches a context plan.
  An agent, skill or tool that does not exist is discarded and recorded — never invented.
- Candidates come from the registry. Jev selects among what it was given; it cannot add to the
  set.
- A route below the confidence floor is rejected and the default path answers instead.
- A response that is not JSON, carries no `answers`, or answers nothing usable is an error, and
  an error is a fallback.

There is no second registry. An agent becomes a candidate because
`templates/<category>/<id>.md` gave it routing metadata and `build.py` carried that into
`catalog/loadouts.json`; a skill because its `manifest.json` reached `catalog/skills.json`.
Adding one the normal way is the whole of what it takes.

## Evaluation

```bash
python3 evals/decision/run.py                     # the offline baseline, free
python3 evals/decision/run.py --engine both       # needs your own key
```

162 routing fixtures cover all 27 roles — obvious cases, near-neighbour cases where a sibling
role is the trap, genuinely ambiguous cases with several acceptable routes, and negative cases
that a keyword matcher would send to the wrong specialist. Plus 24 skill-selection and 20
tool-relevance fixtures, scored for precision as well as recall, because a system that selects
everything has perfect recall and no value.

### Results

Run against `jev-latest` through the TypeSafe API, registry `89baa5fa0e0c`, 2026-09-19. Three
engines, identical fixtures, every decision measured for all three.

| | Keyword baseline | Jev | Claude |
| --- | --- | --- | --- |
| Agent top-1 | 23 / 162 | 143 / 162 | **158 / 162** |
| Acceptable route | 29 / 162 | 154 / 162 | **162 / 162** |
| Avoided a forbidden route | 153 / 162 | 162 / 162 | 162 / 162 |
| Obvious cases, top-1 | 9 / 54 | 52 / 54 | **54 / 54** |
| Near-neighbour, top-1 | 6 / 54 | 49 / 54 | **53 / 54** |
| Ambiguous, top-1 | 3 / 27 | 17 / 27 | **25 / 27** |
| Negative, top-1 | 5 / 27 | 25 / 27 | **26 / 27** |
| Skill precision / recall | 0.31 / 0.56 | 0.68 / 0.71 | **0.74 / 0.90** |
| Skill selections carrying a known-irrelevant id | 0.36 | **0.01** | 0.03 |
| Tool precision / recall | 0.15 / 0.23 | 0.65 / **0.97** | **0.69** / 0.95 |
| Median decision latency | 0 ms | 358 ms | not comparable |

`Claude` is the production default path: the model reading the dispatcher's own catalog and
rules. It is not something the harness can call, so it is replayed from
`evals/decision/routes-claude.json` — one focused subagent per fixture, handed the same
candidate set and limit the engine gets and nothing else. A real session also carries the
conversation and is doing other work at the time, so treat it as a close reconstruction rather
than a capture. Its latency is not comparable either: in production, deciding costs no extra
call, because the dispatcher is already running.

**Claude matched or beat Jev on every decision.** Routing is not close — 158 against 143 on
top-1, 162/162 acceptable, and it wins hardest exactly where the decision is hard (53/54
near-neighbour, 25/27 ambiguous). Skill selection it wins on recall by a wide margin at slightly
better precision. Tool relevance is a genuine tie, and on 20 cases a 0.04 gap either way is
noise.

**Both crush the floor.** The keyword baseline — which is what the dispatcher falls back to
when it selects from a loadout rather than from the task — sits at 0.31/0.56 for skills and
0.15/0.23 for tools. The first cut of these defaults was set against *that*, which was the wrong
comparison. Against the path that actually ships, Jev wins nothing on quality.

So **Jev is installed inert. No decision scope is on by default.**

```text
agent selection      off      claude 158/162 · jev 143/162
skill selection      off      claude 0.74/0.90 · jev 0.68/0.71
tool selection       off      claude 0.69/0.95 · jev 0.65/0.97 — a tie
context ranking      off      designed for, not shipped
verification gate    off      designed for, not shipped
```

That is this architecture working, not failing. It was built so each decision could use whichever
mechanism the evidence supports, and the evidence came back for the default path. The integration
stays because the finding could change — a metadata rewrite, a new Jev version, a different
fixture set — and because what Jev still offers is real:

**latency and cost.** ~360 ms and a fraction of a cent against a full model turn. That is a
serious trade for a high-volume automated path, a hard latency budget, or anywhere the
dispatcher is not already in the loop — a standalone router, a pre-filter, a batch job. Quality
is not the reason to switch it on; throughput is.

```bash
AGENT_DISPATCHER_DECISION_SCOPES=skills,tools python3 -m decision plan --task "..."
```

### Confidence calibration

Observed top-1 accuracy per confidence band, same run:

| Confidence | Jev n | Jev top-1 | Claude n | Claude top-1 |
| --- | --- | --- | --- | --- |
| 0.90 – 1.00 | 109 | 0.98 | 99 | 1.00 |
| 0.80 – 0.90 | 18 | 0.94 | 42 | 0.98 |
| 0.70 – 0.80 | 13 | 0.69 | 14 | 0.93 |
| 0.50 – 0.70 | 16 | 0.38 | 7 | 0.71 |
| below 0.50 | 6 | 0.67 | 0 | — |

Both are informative, and Jev's collapses harder and sooner — below 0.70 it is worse than a coin,
where Claude is still at 0.71. `agent_confidence` stays at **0.80** for anyone who switches agent
selection on: above it Jev was right 96% of the time, below it the default path is the safer
answer. TypeSafe's own guidance puts the absolute floor at 0.50; this is stricter
because routing a whole task is not a cheap action to get wrong.

The relevance floors are the precision knee from a sweep over the same fixtures. Skills went
0.63/0.81 precision-recall at 0.50, 0.70/0.77 at 0.60 and 0.70/0.62 at 0.70 — past 0.60 recall
falls away for no precision, so **0.60**. Tools likewise.

These numbers move a little between runs. Five runs of the Jev routing set scored 136–142 out of
162, with band populations shifting by a case or two while the shape held: ~0.98 above 0.90 every
time, and a collapse below 0.70 every time. The table above is one recorded run, not a best-of.
They will move again when role metadata changes, which is why the registry digest is in every
report. Re-derive rather than trusting this table:

```bash
python3 evals/decision/run.py --engine all --routes evals/decision/routes-claude.json
AGENT_DISPATCHER_DECISION_THRESHOLDS=skill_relevance=0.7 python3 evals/decision/run.py --engine jev
```

### What this does not establish

- **No end-to-end comparison.** Whether a better decision produces better *work*, not just a
  better label, is untested. The fixture schema supports it; the runs do not exist.
- The Claude column is a reconstruction — a focused subagent per case, no conversation, no
  competing work. A real in-session dispatcher, juggling the task as well, could do worse. That
  cuts against the conclusion here, and it is the biggest hole in it.
- Tool selection is 20 cases. The Claude-Jev gap there is noise, and it is reported as a tie
  rather than a win for either.
- 162 cases over 27 roles is 4 to 9 gold labels per role, so macro numbers lean on the
  best-covered roles.
- Nothing here measures cost or throughput at volume, which is the case for Jev that remains.
- Some fixtures paraphrase the registry's own `use_when` lines, which inflates accuracy on those
  cases for every engine. They were kept rather than tuned toward the answer.

## Diagnostics

`/agent-context` names the engine that answered, the confidence beside each selection, and a
fallback when one happened:

```text
Decision Engine
  Default
  Jev attempted but unavailable: timeout
  Fallback: successful
```

Nothing is sent anywhere. Local records — engine, decision type, latency, candidate count,
selection, confidence, whether it fell back, the error kind — are kept in memory for the turn,
and written to a file only if you ask:

```bash
export AGENT_DISPATCHER_DECISION_LOG=~/.claude/decision-log.jsonl
```

A record has no field that could hold a credential, provider errors are reported as a kind
(`timeout`, `rate limited`, `credential rejected`) rather than verbatim, and a response body is
never echoed — it can contain request headers.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `status` says *not configured* | no credential in `TYPESAFE_API_KEY` (or `AI_GATEWAY_API_KEY` for the gateway). This is a supported state; the default engine answers. |
| `/agent-context` says Default when you expected Jev | the mode is `off`, the scope is off, the session is offline, or a fallback happened — the diagnostics line says which. |
| *credential rejected (401)* | the key is wrong, revoked, or belongs to the other provider. |
| *rate limited (429)* / *overloaded (529)* | the provider throttled. `auto` already fell back; `required` will keep erroring. |
| Routes look wrong | run `/agent-context explain` for the full candidate ranking, then `python3 evals/decision/run.py --engine both`. If the baseline is closer, say so — see the section above. |
| `ModuleNotFoundError: decision` | run from the pack directory, or put it on the path: `PYTHONPATH=~/.claude/skills/agent-dispatcher python3 -m decision status`. (`AGENT_DISPATCHER_HOME` relocates the *registries*, not the module — it will not fix this.) |
| It is too slow | lower `timeout_seconds`; `auto` treats a timeout as a fallback. |

## Adding a role or a skill

Nothing Jev-specific. Write the role file with its `summary`, `use_when`, `not_for` and `tags`,
run `python3 build.py`, and it is a routing candidate — those four lines *are* the metadata the
engine reads. Register a skill the normal way and it becomes selectable for every role whose
loadout names it. There are no Jev prompts scattered around the codebase to update, and adding a
candidate registry would be a bug.

Then add fixtures to `evals/decision/agents.json` — at least one obvious case and one
near-neighbour case against the role it is easiest to confuse with. `test_decision.py` fails if
a role has no gold label anywhere.
