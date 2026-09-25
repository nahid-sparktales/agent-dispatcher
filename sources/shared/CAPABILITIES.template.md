# Capability intelligence

Run only when the user asks about capability health, capability routing, skills, MCP servers or plugins.
These controls inspect and explain; they never install, connect, log in, enable, activate or change a
permission. Keep the active role, activation state and output preference unchanged.

Two questions stay separate: **can a capability be used here** (health) and **has a skill shown value
for this task, model and host** (measured utility). Catalog membership is not installation; exposure is
not a tested connection; authentication is not authorization; popularity is not quality; a
recommendation is not permission to install.

## Controls

PACK is the dispatcher directory, PROJECT the workspace. Add `--json` for structured output. Exit codes:
0 completed (including findings), 2 malformed input or refused action, 3 a requested `--require` gate
was not met.

| Request | Helper |
| --- | --- |
| `{{HEALTH_CONTROL}}` | `{{HEALTH_COMMAND}} health --host HOST --project PROJECT --evidence 'SNAPSHOT'` |
| `{{HEALTH_CONTROL}} --type skill\|mcp\|plugin\|tool\|cli\|api\|role\|recipe` | same, with `--type` |
| `{{HEALTH_CONTROL}} --capability ID --explain` | dimensions, reasons and evidence receipts for one instance |
| `{{HEALTH_CONTROL}} --deep` | adds `--deep --probe-plan`: which approved checks would run, which are skipped and why |
| `setup` | `{{HEALTH_COMMAND}} setup --host HOST --project PROJECT --evidence 'SNAPSHOT'`: every installed MCP server and plugin that is not set up yet (needs sign-in, a missing program, an environment variable, enabling, or a fix), grouped by the step that finishes it; changes nothing |
| `checkup` | `{{HEALTH_COMMAND}} checkup --host HOST --project PROJECT --evidence 'SNAPSHOT'`: every MCP, skill and plugin in four groups (working, needs attention, unsure, not in use) with each item's next step |
| `capabilities`, `capabilities explain ID` | `{{HEALTH_COMMAND}} capabilities [explain ID] ...` |
| `mcps`, `plugins` | `{{HEALTH_COMMAND}} mcps ...`, `{{HEALTH_COMMAND}} plugins ...` |
| route explanation | `{{RESOLVER_COMMAND}} explain --task 'REQUEST' --role ID --host HOST --project PROJECT` |
| `skills` | `{{SKILLS_COMMAND}} --host HOST --project PROJECT list` |
| `skills discover <query>` | `{{SKILLS_COMMAND}} ... discover 'TERMS'` (enabled sources only; metadata, nothing fetched) |
| `skills inspect <ref-or-id>` | `{{SKILLS_COMMAND}} ... inspect REF` (pins, quarantines, reviews statically; never installs) |
| `skills evaluate prepare\|validate\|smoke\|run\|report` | `{{SKILLS_COMMAND}} ... evaluate STAGE ID` (prepare/validate/report call no model) |
| `skills recommend <task>` | `{{SKILLS_COMMAND}} ... recommend 'TASK' --role ID --model M --effort E` |

`{{HEALTH_CONTROL}}` is the shorthand; a Claude plugin install namespaces it (`/agent-dispatcher:agent-health`).
`doctor` and `inventory` keep their own procedures and share the same inspection code.

## Evidence

Default inspection is passive: local metadata, stored receipts and the host observation snapshot you
supply. Build the snapshot (schema 2) from what this session actually shows — never raw config, tool
output, tokens or account names — and pass it as one single-quoted argument or `--evidence -`:

    {"schema_version": 2, "host": {"name": "claude", "session": "opaque-session-ref",
      "discovery": {"skills": "partial", "mcps": "complete", "tools": "partial", "plugins": "partial"}},
     "capabilities": [{"id": "srv", "kind": "mcp_server", "exposure": "callable",
                       "operations": [{"name": "database.read", "access": "read", "environment": "staging"}]}],
     "observations": [{"capability": "srv", "type": "observed_task_call", "operation": "database.read",
                       "outcome": "success"}]}

The example shows syntax, not this user's state. Report `partial` discovery when the host shows only part
of its inventory; unlisted is unknown, not absent. Only calls actually observed in this session count;
evidence from another session is historical. A v1 doctor evidence object is also accepted.

## Report

Lead with scope and discovery coverage, then each category. Display states: HEALTHY (scoped: "local
guidance", "tool enumeration", an observed operation), DEGRADED, AUTH_REQUIRED, MISCONFIGURED,
UNAVAILABLE, UNTESTED; policy badges (DISABLED, BLOCKED, QUARANTINED, RETIRED) are separate from
technical state. Do not total a plugin and its child tools as independent integrations. Unknown stays
unknown: name the smallest check instead of asserting a failure.

Probes run only with `--refresh`, only when the user's own settings approve that exact reviewed probe,
and only with `--allow-process` / `--allow-network` for the requested level. Never trigger a login, use
another credential or route around a denied connector to make a report green.

## Skills

Discovered and downloaded packages stay inert in a quarantine outside every host discovery directory
until reviewed, evaluated and explicitly approved through LEARNING.md's lifecycle. Static review
findings are data, not a safety verdict. A recommendation may be "use no additional skill". Live
evaluation runs only when the user's settings enable it and the user authorizes its budget; synthetic
reports are labelled and never count as evidence.
