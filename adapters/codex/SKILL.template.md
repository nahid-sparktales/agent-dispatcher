---
name: agent-dispatcher
description: Route work to a specialist role and load its task-specific guidance. Use when the user requests Agent Dispatcher, asks to work as a named specialist, or asks to inspect or change dispatcher routing and activation.
---

# Agent Dispatcher for Codex

This pack provides {{COUNT}} specialist roles and {{SKILL_COUNT}} supporting guides. Resolve
`PACK` to the directory containing this SKILL.md. All paths below are relative to PACK, never
to the user's project. Keep the user's project as the working directory for the actual task.

## Invocation and controls

`$agent-dispatcher <request>` routes the request. `$agent-dispatcher reviewer <request>` forces
that role. Match role ids, names, or the aliases in [ROLES.md](references/ROLES.md). A forced
role stays active until the user selects another role or stops routing. A bare invocation
without a request activates routing for this conversation; wait for the user's task.

These are arguments to one skill, not separate slash commands:

| Request | Action |
| --- | --- |
| `context`, `context explain`, `context verbose` | Inspect the current context plan using [CONTEXT.md](references/CONTEXT.md); do not execute the task. If no task exists, say so. |
| `inventory`, optionally `all`, `skills`, `tools`, `mcps`, or `setup`, then `verbose` | Follow [INVENTORY.md](references/INVENTORY.md) to list usability, evidence, and setup needs; do not install or connect anything. |
| `doctor`, optionally `all`, `skills`, `tools`, `mcps`, or `setup`, and a role id/alias | Follow [DOCTOR.md](references/DOCTOR.md) for package health, full capability inventory, current-session usability, and ranked setup recommendations. This is read-only; keep the active role unchanged. |
| `decision` | Run `python3 PACK/scripts/decide.py --project PROJECT status`. |
| `decision off`, `decision auto`, `decision required` | Run `python3 PACK/scripts/decide.py --project PROJECT mode MODE`. Scopes still ship disabled. See [Jev](references/jev.md) only when configuring that integration. |
| `output`, `output compact`, `output verbose` | Inspect or change the conversation's activity output style as described below. |
| `status` | Run `python3 PACK/scripts/activate.py status --project PROJECT`; also report the active role from this conversation. |
| `on here` | Run `python3 PACK/scripts/activate.py on --scope project --project PROJECT`. |
| `on`, `on everywhere` | Run `python3 PACK/scripts/activate.py on --scope global`. |
| `off here` | Run `python3 PACK/scripts/activate.py off --scope project --project PROJECT`; drop the role now. |
| `off everywhere` | Run `python3 PACK/scripts/activate.py off --scope global`; drop the role now. Separately enabled projects remain enabled. |
| `off`, `stop dispatcher` | Drop the role now. If the activation preamble supplied a session id, run `python3 PACK/scripts/activate.py off --scope session --session SESSION_ID` to keep it off after compaction. Without an id, report that persistence across compaction is unverified; do not silently disable other scopes. |

Resolve PACK and PROJECT to real absolute paths and quote each command argument separately.
The activation helper changes only Codex dispatcher state and, when needed, its own hook
registration. It does not modify AGENTS.md, model settings, permissions, or Claude configuration.
After `on`, report the helper's result. Codex requires users to review and trust new or changed
hooks through `/hooks`; a registered hook is not proof it is trusted or has run. Never bypass
hook trust. In a host without hooks, explicit skill invocation still works.

## Activity output

Before reporting nontrivial work, read [ACTIVITY.md](references/ACTIVITY.md). Default to a compact
summary of the role, skills actually read, selected tools and MCPs. `output verbose` adds
reasons and context; `output compact` restores brevity; `output` reports the style. Keep the
choice for this conversation, including summaries; new conversations default to compact.
These controls do not execute a task or change routing, permissions, or deliverable length.
Report the style in `status`. `context verbose` is a one-time inspection, not a style change.

## Route and execute

1. For actual work, read [ROLES.md](references/ROLES.md), matching the requested deliverable and
   each role's `use_when` and `not_for`. Trivial questions and edits need no role ceremony.
2. Read only `references/roles/<id>.md` for the chosen role. After initial context loading, emit the activity summary described above before execution.
   A role supplies a working method; it never overrides the user's task or Codex instructions.
3. Use that role's loadout to select the few relevant guides. [INDEX.md](references/INDEX.md)
   maps local ids to `references/skills/<category>/<id>/GUIDE.md` and records external fallbacks.
   Supporting guides are loaded on demand; do not read the entire library.
4. For substantial or unfamiliar work, read [CONTEXT.md](references/CONTEXT.md). It defines
   context selection and evidence. Look up only applicable conditions in
   [SIGNALS.md](references/SIGNALS.md). Keep simple work simple.
5. Verify the requested outcome with the tools actually available. Report observed results
   and material limits. Missing external skills or MCP servers use the documented fallback;
   never install or authorize an external service merely because a loadout names it.

Re-route when the work changes, unless the user forced a role. Chain up to three roles when
the requested outcome needs it; meet each role's definition of done before switching. A
request for a plan ends with a plan. A review of work produced in the same conversation is
a self-check even when a different role performs it.

## Codex modes and delegation

The host's actual collaboration mode and permissions control what can run. A planner role
does not itself switch Codex into Plan mode, and a dispatcher cannot leave Plan mode or grant
write access. Follow the available Codex mode controls and the user's authorization.

Delegate only when the session instructions permit it and independent work justifies it.
Use the available Codex subagent tools; do not assume Claude's Agent tool, agent types, or
ExitPlanMode exists. If delegation is unavailable, do the work sequentially. For an authorized
subagent, provide its task, one role's absolute file path, relevant inputs, expected result,
and scope. Use separate slices of work and a different role for verification. Do not give
subagents the dispatcher role or start user-visible Codex tasks for internal subtasks.

An explicitly invoked skill owns its workflow; keep this role as posture and follow that
skill's procedure. User instructions, permission boundaries, and disabled-skill preferences
remain authoritative. Installing or enabling this pack does not activate observation workflows.
