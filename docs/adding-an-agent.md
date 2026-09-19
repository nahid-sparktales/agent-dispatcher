# Adding an agent

An agent is `templates/<category>/<id>.md`. It is the canonical, portable definition: no
Claude-specific syntax, no skill bodies pasted in. `build.py` renders it into the Claude adapter.

## Frontmatter

Flat `key: value`, comma-separated lists, no nesting — the same parser reads templates and skills,
and it fails loudly rather than guessing.

```
---
id: incident-responder          # must match the filename
slug: incident                  # becomes /agent-incident
name: "Incident Responder"
category: "Engineering"         # Core | Engineering | Product & Design | Knowledge & Business
                                # must match the directory under templates/
summary: "One sentence, shown in the router and the README."
use_when: "When the dispatcher should route here."
not_for: "The neighbouring role this one cedes. This is what keeps near-misses out — write it as
          territory another role owns, never as a list of bad habits."
tags: incident, outage, mitigation, rollback, triage

capabilities: devops.incident, devops.rollback          # what this role is responsible for

skills_core: incident-response, rollback                # 2-4; reached for on most relevant work
skills_preferred: observability, systematic-debugging   # strongly consider when applicable
skills_optional: release-verification                   # occasionally right
skills_if_vercel: deployment                            # only when that condition holds
mcp_recommended: workspace
mcp_conditional: sentry, datadog, grafana
recipes: investigate-incident
verification: release-verification
retrieval_hints: recent deploy records, alerting config, runbooks   # 2-6 artifact kinds it reads first
---
```

Then the body: ROLE, WHEN TO USE, WORKING METHOD (numbered), DELIVERABLE, DEFINITION OF DONE,
ROLE BOUNDARIES, TRAP, followed by tool posture, response style, mode and carrying context. Copy
the shape from a sibling template; `templates/engineering/debugger.md` is a good model.

## Routing metadata

`summary`, `use_when`, `not_for` and `tags` do double duty. They are what a reader sees in the
router and the README, and they are the only thing the optional decision engine is given to tell
your role from the other 26 — `build.py` carries them into `catalog/loadouts.json`, which is the
candidate registry. There is no second place to register a role, and adding one would be a bug.

That makes `not_for` the highest-leverage line in the file. Written as territory a neighbouring
role owns, it decides near-neighbour routing. Written as a list of bad habits ("no sloppy work"),
it excludes nothing and helps neither a reader nor a model.

Then add fixtures to `evals/decision/agents.json`: one obvious case, and one near-neighbour case
against the role yours is easiest to confuse with. `test_decision.py` fails the build if a role
has no gold label anywhere.

## Restraint

A normal task should load one to five skills. `skills_core` with six entries is a role that loads
everything and reads nothing. For each id ask: *would this role reach for it on a typical request?*
Yes → core. Sometimes → preferred. Only under a condition → `skills_if_<condition>`.

Give a role a skill because its work needs it, not because the skill is good.

## The rules the build enforces

- `id` matches the filename; `category` matches the directory.
- Every skill, recipe and MCP id resolves to something that exists.
- Anything named in `verification` is a skill whose manifest declares `verifies: true`.
- Every capability is provided by at least one skill.
- Ids and slugs are unique across all roles.
- Every `skills_if_<condition>` bucket resolves to a signal in `catalog/signals.json`.
- `retrieval_hints` is present and non-empty.

Run `python3 build.py` then `python3 test_build.py`. The build regenerates the router, the role
rendering, the command, the hook index and the registries; the test suite checks they agree.

## What stays out of the template

Runtime-specific syntax, the loadout block's prose (generated), and detailed specialist knowledge
that belongs in a skill. The role keeps enough method to be useful with **no** optional skill
installed — that is the floor, and it is deliberate.

## Retrieval hints

Two to six kinds of workspace artifact this role reads *first* — they seed the context engine's
search before the task's own nouns do. Derive them from the role's own WORKING METHOD: a debugger
opens the failing module, its tests and what changed recently; a version-control role opens the
reflog. A hint list that would fit any role is useless.

## Conditions

Every `skills_if_<condition>` bucket must be defined in
[`catalog/signals.json`](../catalog/signals.json), which says how the condition is decided —
`project` (file globs and `<glob> contains <literal>` checks), `task` (phrases in the request), or
`runtime` (what the environment provides). The build refuses an undefined bucket, and refuses a
signal no role uses.

Reuse an existing signal where one fits; `docs/context-engine.md` lists them all. Prefer `project`
over `task` where the repository can settle it, and prefer a content check over a filename where
the filename alone is weak.

Detection activates knowledge. It never grants permission: `vercel.json` means load deployment
guidance, not that the agent may deploy.
