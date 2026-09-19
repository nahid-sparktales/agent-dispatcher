#!/bin/bash
# Install the generated agent-dispatcher skill, per-role commands, and perpetual-mode hook.
set -e
cd "$(dirname "$0")"
python3 build.py
D="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
rm -rf "$D/skills/agent-dispatcher"
mkdir -p "$D/skills" "$D/commands" "$D/hooks"
cp -R skills/agent-dispatcher "$D/skills/agent-dispatcher"
rm -f "$D"/commands/agent-*.md
cp commands/agent-*.md "$D/commands/"
cp hooks/agent-dispatcher-activate.sh "$D/hooks/"
chmod +x "$D/hooks/agent-dispatcher-activate.sh"
python3 - "$D" <<'PY'
import json, sys, pathlib, shutil
d = pathlib.Path(sys.argv[1]); p = d / "settings.json"
cmd = f'bash "{d}/hooks/agent-dispatcher-activate.sh"'
s = json.loads(p.read_text()) if p.exists() else {}
hooks = s.setdefault("hooks", {}).setdefault("SessionStart", [])
if not any(h.get("command") == cmd for e in hooks for h in e.get("hooks", [])):
    if p.exists(): shutil.copy(p, p.with_suffix(".json.bak-agent-dispatcher"))
    hooks.append({"matcher": "startup|resume|clear|compact",
                  "hooks": [{"type": "command", "command": cmd, "timeout": 5}]})
    p.write_text(json.dumps(s, indent=2) + "\n")
    print("registered SessionStart hook")
else:
    print("SessionStart hook already registered")
PY
echo "installed to $D"
