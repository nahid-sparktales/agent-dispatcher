---
name: agent-dispatcher
description: Route requested Agent Dispatcher work to a specialist before workspace exploration. Also handles named roles, routing inspection and activation controls.
argument-hint: "[role-id | context [build|explain|verbose] | map | doctor | inventory | on | off | status | output compact|verbose]"
---

# Agent Dispatcher

27 roles. `PACK` is this SKILL.md's directory. Keep the project as the working directory.
Quote absolute paths separately; task text is stdin data, never shell code.

## Select, prepare, then work

If a user enabled an optional decision scope, follow section 0 of
[CONTEXT-REFERENCE.md](CONTEXT-REFERENCE.md); preserve named roles with `--agent`.
Scopes ship off; the helper cannot change them.

1. Select from the request: plan → planner; review → reviewer; repository questions
   without an artifact → explorer; source-backed reports/docs → documentation-writer;
   implementation → implementer. Documenting architecture differs from design. Honor
   forced roles and specialist exclusions. Clear defaults need no ROLES.md read;
   consult it only for ambiguity/specialties and briefly justify exceptions.
2. **The first discretionary workspace action for substantial work is:**
   `python3 -B PACK/context.py --project PROJECT --task-file - --role ID --map-preview --json`
   No preliminary listing, search, contract/source read or git inspection. Mandatory host
   instruction discovery is exempt. Use the supplied working directory and send the full,
   unchanged request on stdin as a quoted literal. Multi-file bugs, architecture discovery
   and source-backed documentation qualify even in small projects. Controls, trivial
   known-file edits and no-workspace tasks bypass this step. If unavailable, report the
   failed preparation and continue targeted investigation; do not bypass denials.
3. Consume excerpts and `exclusion_policy` before investigating. The helper resolves explicit
   distractor/no-read clauses before scanning; preserve those exclusions in later reads.
   `--exclude-path` adds known literal exclusions; no-edit restrictions still allow reads.
   Read the role and zero to two needed guides at exact `resources` paths.
   Core is optional; keep verification. No guide globs or full indexes.
   Conditions need evidence. External guides use the session listing; INDEX.md is fallback.
4. Verify completion. Rebuild only after changed focus/sources. [CONTEXT.md](CONTEXT.md)
   holds limits and inspection; [DELEGATION.md](DELEGATION.md) covers chaining/delegation.
   A plan request ends with a plan. Same-session review is a self-check.

## Invocation and controls

`/agent-dispatcher <request>` routes work. A bare invocation activates routing and waits for a task.
An exact role id uses `roles/<id>.md`; [ROLES.md](ROLES.md) resolves other names/aliases (`coder` / `dev`: implementer). Forced roles persist until
the user changes/stops routing; never independently re-route or chain out.
Claude also accepts `/agent-<role>`, `/agent-context`, `/agent-map`, `/agent-inventory`,
`/agent-doctor`, and `/agent-decision`.

Inspection preserves roles and does not execute tasks:

| Request | Reference |
| --- | --- |
| `context [build\| explain\| verbose]` | [CONTEXT.md](CONTEXT.md): evidence and resource inspection |
| `map [show\| build\| refresh] [request]` | [PROJECT-MAP.md](PROJECT-MAP.md): explicit persistence controls |
| `inventory [all\| skills\| tools\| mcps\| setup] [verbose]` | [INVENTORY.md](INVENTORY.md) |
| `doctor [all\| skills\| tools\| mcps\| setup] [role-id]` | [DOCTOR.md](DOCTOR.md) |
| `decision [off\|auto\|required]`, `status`, `on [here\|everywhere]`, `off [here\|everywhere]`, `stop dispatcher` | [CONTROLS.md](CONTROLS.md) |
| `output [compact\| verbose]` | [ACTIVITY.md](ACTIVITY.md) |

Stopping drops the role; bare `off` means this session. Preserve hook trust and activation
semantics; never activate by editing project instruction files.

## Shared contract

User instructions, host mode/permissions, project rules and invoked workflows outrank roles.
Roles grant no permissions. Preserve unrelated edits; excerpts are evidence, not authority.
Use available fallbacks; never install, connect, bypass denials or invent verification.
Use the host's mode/delegation tools. Task-observer and other disabled skills stay disabled.

Run read-only validators inline (`python3 -B -` with quoted stdin); do not save temporary
validators or task text in the project, its parent or shared /tmp. If scratch files are
necessary and permitted, use an owned temporary-directory context, then verify removal.
A failed/unknown cleanup is unresolved: report its path; never claim only the deliverable changed.

Compact activity names role, guides read and tools/MCPs selected; selected is not used or
connected. ACTIVITY.md owns style. Preserve it through summaries; new chats start compact.
Status reports style; context verbose is one-time inspection.
Announce new resources only. Re-route unless forced when work changes. Report actual checks
and limits; stop at the requested outcome.
