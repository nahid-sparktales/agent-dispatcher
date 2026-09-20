# Claude dispatcher controls

Read this only for activation, stopping, status, or decision settings. Keep the active
role during inspection; configuration controls do not execute the underlying task.

## Activation and status


1. **No argument** — route the request that came with the invocation. If none came with it, say the dispatcher is active, list a few relevant role ids, and wait.
2. **Role argument** (`/agent-dispatcher reviewer`, `/agent-uidesigner`, "be the tester") — that role is forced; skip routing. Match loosely: `uidesigner` → `ui-ux-designer`, `security` → `security-auditor`, `docs` → `documentation-writer`, `coder`/`dev` → `implementer`. If nothing matches, say so and list the closest ids. A forced role holds until the user names another role or says to stop — you do not release it on your own judgement, and you do not chain out of it. When a request falls outside it, do the work as asked and note in one line which role fits better, if that would materially change the answer.
3. **`on`** / `on here` / "always on" / "make this perpetual" — arm the dispatcher for future sessions, at the scope they asked for. `on` means everywhere; `on here` (or "this project", "just this repo") means this project only. Do the file work yourself and report what happened — never hand the user a `touch` command to run.

   - **This project only** (`on here`) — two steps, because a flag file alone would let any cloned repository arm itself:

     ```bash
     D="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"; touch .agent-dispatcher-on && pwd >> "$D/.agent-dispatcher-projects"
     ```

     The hook arms here only when the project's path is in that allow-list, which only the user's own config dir holds.
   - **Everywhere** (the default reading of `on`) — every future session, in every project:

   ```bash
   D="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"; touch "$D/.agent-dispatcher-active"; if grep -q agent-dispatcher-activate "$D/settings.json" 2>/dev/null || grep -q '"agent-dispatcher@' "$D/plugins/installed_plugins.json" 2>/dev/null; then echo "armed + hook installed"; else echo "armed BUT no hook"; fi
   ```

   Either way, report what the check printed. The two greps cover both install paths — a manual install registers the hook in `settings.json`, a plugin install carries its own `hooks/hooks.json`. Only if it says **no hook**: the flag alone does nothing, so say so and point at the source repo's `install.sh` (or a plugin install — not both, they collide). It takes effect in new sessions; this one is already active.
4. **`off`** / `off here` / `off everywhere` / "stop dispatcher" / "normal mode" — stop routing, at the narrowest scope that matches what they asked for. Bare `off` means this session; `off here` means this project; `off everywhere` disarms globally. Drop the role immediately in every case; the flag files only stop the hook re-arming you later.

   - **This session** (the default reading, and the one that survives a compaction — the hook fires on `compact`, so without this a mid-session "stop" comes back):

     ```bash
     D="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"; mkdir -p "$D/.agent-dispatcher-off" && touch "$D/.agent-dispatcher-off/$CLAUDE_SESSION_ID"
     ```

     The perpetual-mode preamble prints this line with the session id already filled in — prefer that one, since `$CLAUDE_SESSION_ID` may not be set.
   - **This project** (`off here`) — `touch .agent-dispatcher-off` in the project root. This also overrides a global arm: silencing always beats arming.
   - **Everywhere** (`off everywhere`) — `rm -f "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/.agent-dispatcher-active"`. Leaves per-project arming alone; say so.

   Ask which they meant only when it is genuinely ambiguous; "stop dispatcher" means this session.
5. **`status`** — one short block, no preamble. Run this and report it as it comes back, plus the active role and the roles announced in the visible transcript (say so if the session was compacted):

   ```bash
   D="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"; P="$PWD"
   [ -f "$D/.agent-dispatcher-active" ] && echo "everywhere: armed" || echo "everywhere: not armed"
   if [ -f "$P/.agent-dispatcher-on" ]; then grep -qxF "$P" "$D/.agent-dispatcher-projects" 2>/dev/null \
     && echo "this project: armed" || echo "this project: flagged but NOT allow-listed — run /agent-dispatcher on here"; \
   else echo "this project: not armed"; fi
   [ -f "$P/.agent-dispatcher-off" ] && echo "this project: SILENCED (overrides any arm)"
   [ -n "$CLAUDE_SESSION_ID" ] && [ -f "$D/.agent-dispatcher-off/$CLAUDE_SESSION_ID" ] && echo "this session: SILENCED"
   grep -q agent-dispatcher-activate "$D/settings.json" 2>/dev/null || grep -q '"agent-dispatcher@' "$D/plugins/installed_plugins.json" 2>/dev/null \
     && echo "hook: installed" || echo "hook: MISSING — arming does nothing until it is"
   ```

   If the hook is missing, say the flags do nothing without it and point at the source repo's `install.sh` or a plugin install — not both, they collide.


## Decision settings

`/agent-decision` reports configuration; `/agent-decision off|auto|required` changes the
local decision mode. Read the command and follow its instructions. Every scope ships
disabled; credentials alone do not activate Jev. Keep the project as the working
directory and run `PYTHONPATH=RUNTIME python3 -m decision status`. RUNTIME is PACK for
a manual install or the plugin root for a plugin install, containing decision/ and
catalog/; substitute a separately quoted absolute path.
Never request or print a credential in chat. Read [Jev](jev.md) only when configuring it.
