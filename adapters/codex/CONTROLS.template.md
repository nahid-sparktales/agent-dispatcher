# Codex dispatcher controls

PACK: dispatcher; PROJECT: workspace. Controls are skill arguments.

| Request | Action |
| --- | --- |
| `decision` | Run `python3 PACK/scripts/decide.py --project PROJECT status`. |
| `decision off`, `decision auto`, `decision required` | `python3 PACK/scripts/decide.py --project PROJECT mode MODE`. Scopes default off; [Jev](jev.md) covers configuration. |
| `status` | `python3 PACK/scripts/activate.py status --project PROJECT`; report role, activity style, preferences and unconfirmed effort. |
| `on here` | Run `python3 PACK/scripts/activate.py on --scope project --project PROJECT`. |
| `on`, `on everywhere` | Run `python3 PACK/scripts/activate.py on --scope global`. |
| `off here` | Run `python3 PACK/scripts/activate.py off --scope project --project PROJECT`; drop the role now. |
| `off everywhere` | `python3 PACK/scripts/activate.py off --scope global`; drop the role. Project scopes remain enabled. |
| `off`, `stop dispatcher` | Drop the role. With a preamble session id, run `python3 PACK/scripts/activate.py off --scope session --session SESSION_ID`. Otherwise persistence after compaction is unverified; leave other scopes intact. |

Quote absolute paths and arguments. Only dispatcher state/hooks change. Report `on` results.
Users must trust new/changed hooks through `/hooks`; registration proves neither trust nor
execution. Never bypass trust. Explicit invocation works without hooks.
