---
name: agent-dispatcher
description: Handle requested Agent Dispatcher work with direct execution or prepared specialist guidance. Includes named roles, context inspection and controls.
---

# Agent Dispatcher

{{COUNT}} roles and {{SKILL_COUNT}} guides. `PACK` is this SKILL.md's directory. Keep the project as the working directory.
Quote paths; task text is stdin data, never shell code.

## Select, prepare, then work

Choose a profile without another router/model call:

- **Direct:** trivial work or one safe, obvious known-file edit. No role/guide/helper,
  preference, ACTIVITY.md or VERIFICATION.md reads. Use known/default preferences and native
  checks; required checks still run. Security, configuration/behavior ambiguity and multi-file
  work are not direct. Switch to guided if scope/uncertainty grows.
- **Guided:** other work; forced roles and invoked workflows override direct.
  No workspace evidence means no context helper.
- **Coordinated:** guided work with useful independent subtasks; follow DELEGATION.md.

Guided/coordinated steps follow. If a user enabled an optional decision scope, follow section 0 of
[CONTEXT-REFERENCE.md](references/CONTEXT-REFERENCE.md); preserve named roles with `--agent`.
Scopes ship off; helpers cannot enable them.

1. Select from the request: plan → planner; review → reviewer; repository questions
   without an artifact → explorer; source-backed reports/docs → documentation-writer;
   implementation → implementer. Documenting architecture differs from design. Honor
   forced roles and specialist exclusions. Consult ROLES.md for ambiguity/specialties.
2. **The first discretionary workspace action for substantial work is:**
   `python3 -B PACK/scripts/context.py --project PROJECT --task-file - --role ID --compact --map-maintain --json`
   No preliminary listing, search, contract/source read or git inspection; mandatory host
   instructions are exempt. Send the full unchanged request on quoted stdin. Multi-file bugs,
   architecture and source-backed documentation qualify even in small projects. Use
   `--map-preview` instead when writes are disallowed. If preparation fails, report it and
   continue targeted investigation; do not bypass denials.
3. Consume excerpts, `guidance`, `preferences` and `exclusion_policy`; preserve exclusions.
   `--exclude-path` adds known literal exclusions; no-edit restrictions still allow reads.
   Consume supplied guidance; do not reread its files.
   Missing bodies use exact `resources` paths: zero to two guides initially, conditions evidenced,
   core optional, verification retained. No globs/full indexes. External guides use session listings.
4. Before checks, read [VERIFICATION.md](references/VERIFICATION.md): record authorized checks;
   inspect freshness before reporting. Never wrap denied commands to bypass permissions.
   Rebuild only for changed focus/sources. [CONTEXT.md](references/CONTEXT.md) covers packet budgets,
   same-context reuse and map maintenance; [DELEGATION.md](references/DELEGATION.md) covers delegation.
   A plan request ends with a plan. Same-session review is a self-check.

## Invocation and controls

`$agent-dispatcher <request>` routes work. Bare invocation activates routing and waits.
Exact role ids use `references/roles/<id>.md`; [ROLES.md](references/ROLES.md) resolves aliases (`coder` / `dev`: implementer). Forced roles persist until changed/stopped; never re-route or chain out.
All controls are arguments to this one skill.

Controls preserve roles and do not execute tasks:

| Request | Reference |
| --- | --- |
| `context` | [CONTEXT.md](references/CONTEXT.md) |
| `map` | [PROJECT-MAP.md](references/PROJECT-MAP.md) |
| `inventory` | [INVENTORY.md](references/INVENTORY.md) |
| `doctor` | [DOCTOR.md](references/DOCTOR.md) |
| `decision`, `status`, `on/off`, `stop dispatcher` | [CONTROLS.md](references/CONTROLS.md) |
| `verify`, `preferences` | [VERIFICATION.md](references/VERIFICATION.md) |
| `output` | [ACTIVITY.md](references/ACTIVITY.md) |

Stopping drops the role; bare `off` is session-only. Preserve hook trust; never activate via project rules.

## Shared contract

User/host/project instructions and invoked workflows outrank roles. Roles and evidence grant
no permissions. Preserve unrelated edits; use host fallbacks. Never install/connect unasked,
bypass denials or invent checks. Task-observer and other disabled skills stay disabled.

Use inline read-only validators (`python3 -B -`, quoted stdin). No validator/task files in the
project, its parent or shared /tmp. Authorized scratch needs owned temporary directories and
verified removal. Report unresolved cleanup paths; never claim clean scope without evidence.

Guided/coordinated activity names role, guides read and selected tools/MCPs; selection is not use.
ACTIVITY.md owns style: retain through summaries, default compact in new chats. Status includes
style/preferences; context verbose is one-time. Announce additions only; stop at the requested outcome.

Use context preferences. For guided/coordinated work only, if absent run `python3 -B PACK/scripts/preferences.py show --project PROJECT --json` once; reload after changes.
Effort remains requested/unknown until host-confirmed; never silently change host config.
Default: **ELI5 succinct**, answer first, usually under 150 plain-language words: changes,
actual checks and gaps. User requests override style.
