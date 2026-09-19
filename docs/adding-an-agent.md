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
---
```

Then the body: ROLE, WHEN TO USE, WORKING METHOD (numbered), DELIVERABLE, DEFINITION OF DONE,
ROLE BOUNDARIES, TRAP, followed by tool posture, response style, mode and carrying context. Copy
the shape from a sibling template; `templates/engineering/debugger.md` is a good model.

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

Run `python3 build.py` then `python3 test_build.py`. The build regenerates the router, the role
rendering, the command, the hook index and the registries; the test suite checks they agree.

## What stays out of the template

Runtime-specific syntax, the loadout block's prose (generated), and detailed specialist knowledge
that belongs in a skill. The role keeps enough method to be useful with **no** optional skill
installed — that is the floor, and it is deliberate.

## Conditions worth reusing

`react`, `nextjs`, `tailwind`, `shadcn`, `ui_task`, `security_sensitive`, `postgres`, `supabase`,
`docker`, `vercel`, `browser_available`, `notebook`. Prefer conditions detectable from the
repository — `package.json`, `components.json`, `wrangler.toml`, `Dockerfile`,
`.github/workflows/`, `vercel.json`, `supabase/`.

Detection activates knowledge. It never grants permission: `vercel.json` means load deployment
guidance, not that the agent may deploy.
