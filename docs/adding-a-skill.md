# Adding a skill

A skill is `skills/<category>/<id>/SKILL.md`, plus a `manifest.json` beside it, plus
`references/` and `scripts/` when they earn their place.

Keep the layers apart. A skill says **how to perform one specialized thing**. It does not say who
is responsible (a role), what external system exists (an MCP), or how several capabilities combine
into one repeatable run (a recipe). A skill teaches; it never authorizes.

## The two files

`SKILL.md` carries **standard Agent Skills frontmatter and nothing else** — `name` and
`description`, plus `allowed-tools` if the skill really runs commands. Keeping it standard is what
lets the skill be installed and read by any Agent Skills runtime, not only this pack.

```
---
name: browser-verification
description: One or two sentences that say what this does AND when it fires, in trigger language a
  model can match against a request. Mention what it is NOT for. This is the only part loaded
  during discovery, so it does the whole job of getting the skill chosen or skipped.
---
```

`manifest.json` carries everything this pack needs and the Agent Skills format has no field for:

```json
{
  "id": "browser-verification",          // must match the directory name
  "capability": "verification.browser",  // from the taxonomy below
  "category": "quality",                 // must match the parent directory
  "use_when": "The trigger, one sentence.",
  "not_for": "The neighbouring skill this one cedes — what keeps near-misses out.",
  "task_signals": ["blank screen", "does it render"],  // 3-7 short phrases a USER would write
  "verifies": true,                      // true only for procedures that prove work
  "tools": ["playwright", "workspace"],  // ids from catalog/mcp.json — availability, not permission
  "references": ["references/driving-the-browser.md"],
  "scripts": [],
  "provenance": "local"
}
```

`build.py` fails if an id, category, capability, tool id or referenced file does not line up, and
if `task_signals` is missing or empty.

### Writing `task_signals`

These are the lexical half of discovery: matched against a request, never read as prose. Three to
seven phrases, lowercase, at most five words each.

Write them in the vocabulary of the **request**, not of the skill — `"blank screen"`, not
`"rendered-output verification"`. Make them *discriminate*: read the `not_for` line of every
sibling in the same category and drop any phrase that would fire for one of them instead.
`tests/test_build.py` rejects a phrase shared by more than two skills, because a signal that fires
everywhere routes nothing.

## The body

Procedural, not encyclopedic. A skill earns its place by telling an agent what to do next, in what
order, and how to know it worked.

- **When this fires** — concrete, including when it does not.
- **Procedure** — numbered steps in running order. Each step is an action with its discipline
  attached, not a topic heading.
- **Checklist** — what must be true before this is done, written so it can be walked.
- **Failure handling** — what to do when a step fails, and what not to conclude from it.
- **Evidence** — what to report so a reader can tell the work happened. Name the artifact (a
  command's output, a screenshot, a diff), not the claim.

Do not write "you are an expert at X". Do not restate a role's working method. Do not pad a thin
skill to look substantial — if it is four steps, it is four steps. Aim for 60–150 lines; push
long background material into `references/` so it loads only when that part is needed.

## Progressive disclosure

Three levels, and the build enforces the shape:

1. **Discovery** — `INDEX.md` and the `description` line. This is all an agent sees while deciding.
2. **The skill** — `SKILL.md`, read only once the agent has chosen it.
3. **References and scripts** — read only when a step calls for that specific piece.

Never write a skill that assumes all of it will be in context. One to five skills is a normal task.

## Capability taxonomy

Used for routing and aliasing, so several skills can provide the same capability and a role or
recipe can ask for the capability rather than a repository name. Keep it shallow — two or three
segments:

```
research.*        product.*       design.*        frontend.*
backend.*         database.*      devops.*        security.*
quality.*         ai.*            data.*          knowledge.*
verification.*
```

A namespace exists once a skill declares it. The build rejects a role or recipe asking for a
capability no skill provides, so adding a new top-level prefix means adding the skill that supplies
it in the same change.

## When to split, when to merge

Split when two things have **different activation conditions** — an agent must choose between
them, so they cannot share a trigger. Merge when they always fire together and the procedure runs
straight through. A skill that only restates a role's boundaries is not a skill; delete it.

## Before adding an external skill instead

Check `catalog/external-skills.json` first. If a maintained official skill already covers the
capability, reference it there rather than writing a local duplicate — and record the fallback, so
an agent without it installed still has a path. Write a local skill when no adequate external one
exists, or when the external one cannot be relied on (unmaintained, unclear licence, single-drop
repository).
