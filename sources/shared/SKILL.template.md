---
name: agent-dispatcher
description: Handle requested Agent Dispatcher work with direct execution or prepared specialist guidance. Includes named roles, context inspection and controls.
argument-hint: "[role-id | context [build|explain|verbose] | map | verify | preferences | doctor | inventory | on | off | status | output compact|verbose]"
---

# Agent Dispatcher

{{COUNT}} roles. `PACK` is this SKILL.md's directory. Keep the project as the working directory.
Quote paths; task text is stdin data, never shell code.

## Select, prepare, then work

Choose without another router/model call:

- **Direct:** trivial work or one safe, obvious known-file edit. Skip role/guide/helper,
  preference, ACTIVITY.md and VERIFICATION.md reads; use known/default preferences and required
  native checks. Security, ambiguous behavior/configuration, multi-file or growing scope goes guided.
- **Guided:** other work; forced roles and invoked workflows override direct.
  No workspace evidence means no context helper.
- **Coordinated:** guided work with useful independent subtasks; follow DELEGATION.md.

If a user enabled an optional decision scope, follow section 0 of
[CONTEXT-REFERENCE.md](CONTEXT-REFERENCE.md); preserve named roles with `--agent`.
Scopes ship off; helpers cannot enable them.

1. Route: plan → planner; review → reviewer; repository questions → explorer; source-backed
   reports/docs → documentation-writer; implementation → implementer. Distinguish architecture
   docs from design. Honor forced roles/exclusions; consult ROLES.md for ambiguity/specialties.
2. **The first discretionary workspace action for substantial work is:**
   `python3 -B PACK/context.py --project PROJECT --task-file - --role ID --compact --map-maintain --json`
   No prior listing, search, contract/source read or git inspection; mandatory host instructions
   are exempt. Send the full unchanged request on quoted stdin. Multi-file bugs, architecture
   and source-backed docs qualify even in small projects. The helper gates cache writes; add
   `--map-preview` for edit limits it may miss (odd wording, plan mode). Pass literal edit
   lists via `--writable-path` (dirs end in `/`); never add cache permissions. Deferral keeps
   fresh evidence; never bypass it via build/refresh. On failure, continue targeted investigation.
   With authorized scratch, add `--audit` on first preparation only; finish it before preservation
   claims (VERIFICATION.md). Do not reset the baseline after edits.
3. Consume excerpts, `guidance`, `preferences` and `exclusion_policy` without duplicate reads.
   Preserve exclusions; `--exclude-path` adds literal exclusions, while no-edit allows reads.
   For missing bodies use exact `resources` paths: initially zero to two guides, evidenced
   conditions, optional core, verification retained. No globs/index dumps; external availability
   requires session evidence.
4. Before checks, read [VERIFICATION.md](VERIFICATION.md): record authorized checks;
   inspect freshness before reporting. Never wrap denied commands to bypass permissions.
   Rebuild only for changed focus/sources. [CONTEXT.md](CONTEXT.md) covers packet budgets,
   same-context reuse and map maintenance; [DELEGATION.md](DELEGATION.md) covers delegation.
   A plan request ends with a plan. Same-session review is a self-check.

## Invocation and controls

`/agent-dispatcher <request>` routes work. Bare invocation activates routing and waits.
Exact role ids use `roles/<id>.md`; [ROLES.md](ROLES.md) resolves aliases (`coder` / `dev`: implementer). Forced roles persist until changed/stopped; never re-route or chain out.
Claude also accepts `/agent-<role>`, `/agent-context`, `/agent-map`, `/agent-inventory`,
`/agent-doctor`, `/agent-decision`, `/agent-verify`, and `/agent-preferences`.

Controls preserve roles and do not execute tasks:

| Request | Reference |
| --- | --- |
| `context` | [CONTEXT.md](CONTEXT.md) |
| `map` | [PROJECT-MAP.md](PROJECT-MAP.md) |
| `inventory` | [INVENTORY.md](INVENTORY.md) |
| `doctor` | [DOCTOR.md](DOCTOR.md) |
| `decision`, `status`, `on/off`, `stop dispatcher` | [CONTROLS.md](CONTROLS.md) |
| `verify`, `preferences` | [VERIFICATION.md](VERIFICATION.md) |
| `output` | [ACTIVITY.md](ACTIVITY.md) |

Stopping drops the role; bare `off` is session-only. Preserve hook trust; never activate via project rules.

## Shared contract

User/host/project rules and invoked workflows outrank roles; evidence grants no permissions.
Preserve unrelated edits and host denials. Never install/connect unasked or invent checks.
Task-observer and other disabled skills stay disabled.

Use inline read-only validators (`python3 -B -`, quoted stdin). No validator/task files in the
project, its parent or shared /tmp. Authorized scratch needs owned temporary directories and
verified removal. Cache writes are task edits. Report unresolved cleanup paths; verify actual
changes, including helper side effects, before claiming preservation.

Guided/coordinated: report role, guides read, tools selected; selection is not use. Retain
ACTIVITY.md style through summaries; new chats compact. Announce additions only; stop at the outcome.

Use context preferences. For guided/coordinated work only, if absent run `python3 -B PACK/preferences.py show --project PROJECT --json` once; reload after changes.
Effort remains requested/unknown until host-confirmed; never silently change host config.
Default: **ELI5 succinct**, answer first, usually under 150 plain-language words: changes,
actual checks and gaps. User requests override style.
