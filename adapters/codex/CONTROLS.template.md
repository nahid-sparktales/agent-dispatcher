# Codex dispatcher controls

PACK is the installed dispatcher; PROJECT is the workspace.
Pass these controls as `$agent-dispatcher` arguments.

| Request | Action |
| --- | --- |
| `decision` | Run `python3 PACK/scripts/decide.py --project PROJECT status`. |
| `decision off`, `decision auto`, `decision required` | Run `python3 PACK/scripts/decide.py --project PROJECT mode MODE`. Scopes ship disabled. Read [Jev](jev.md) only to configure it. |
| `status` | Run `python3 PACK/scripts/activate.py status --project PROJECT`; also report the active role and activity output style from this conversation. |
| `on here` | Run `python3 PACK/scripts/activate.py on --scope project --project PROJECT`. |
| `on`, `on everywhere` | Run `python3 PACK/scripts/activate.py on --scope global`. |
| `off here` | Run `python3 PACK/scripts/activate.py off --scope project --project PROJECT`; drop the role now. |
| `off everywhere` | Run `python3 PACK/scripts/activate.py off --scope global`; drop the role now. Separately enabled projects remain enabled. |
| `off`, `stop dispatcher` | Drop the role now. If the activation preamble supplied a session id, run `python3 PACK/scripts/activate.py off --scope session --session SESSION_ID` to keep it off after compaction. Without an id, report that persistence across compaction is unverified; do not silently disable other scopes. |

Resolve PACK and PROJECT to real absolute paths and quote each command argument separately.
The activation helper changes only Codex dispatcher state and its hook registration.
After `on`, report the helper's result. Codex requires users to review and trust new or changed
hooks through `/hooks`; a registered hook is not proof it is trusted or has run. Never bypass
hook trust. In a host without hooks, explicit skill invocation still works.
