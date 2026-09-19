---
description: "Show or set the decision engine used for routing - mode, provider, credentials and status. Never prints a credential."
argument-hint: "[status | off | auto | required | plan <request>]"
---

Inspect or configure the **decision engine** - the optional layer that answers the dispatcher's bounded choices (which role, which skills, which servers are relevant). It is optional by design: with nothing configured, agent-dispatcher routes exactly as it always has.

Run these from the directory holding the agent-dispatcher skill — `~/.claude/skills/agent-dispatcher` for a manual install, the plugin's own directory for a plugin install, or glob `**/agent-dispatcher/decision/` to find it. From anywhere else, put that directory on `PYTHONPATH` instead:

```bash
PYTHONPATH=~/.claude/skills/agent-dispatcher python3 -m decision status
```

| `$ARGUMENTS` | Run |
| --- | --- |
| empty or `status` | `python3 -m decision status` |
| `off` / `auto` / `required` | `python3 -m decision mode <value>` - writes `.agent-dispatcher-decision.json` in the project |
| `plan <request>` | `python3 -m decision plan --task "<request>"` |

Then show the output as it came back, and add nothing to it.

- **`off`** - never used. The default engine answers everything. No credential needed, no request made.
- **`auto`** - the recommended setting and the default. Uses the engine when it is configured and healthy; falls back to the default engine on a timeout, an error or an answer that does not validate, and records that in diagnostics.
- **`required`** - fails with a clear error instead of falling back. For evaluation and for developers who want to know the engine actually ran.

Rules:

- **Never ask the user to paste a credential into the conversation, and never write one into a file in this repository.** The credential lives in the environment; the commands above read it there and report only `configured` or `not configured`.
- If the user asks to enable it, tell them which environment variable to set and point at `docs/jev.md`. Do not set it for them, and do not echo it back if they paste one.
- Usage is billed to the account that owns the key the user supplied. Say so rather than implying it is free.
- The engine decides relevance. It never grants a permission, and the runtime's permission layer never reads its output.

$ARGUMENTS
