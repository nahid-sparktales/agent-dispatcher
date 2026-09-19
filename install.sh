#!/bin/bash
# Manual install: copy the skill, the per-role commands, and the perpetual-mode hook into
# ~/.claude and register the hook in settings.json.
#
# Prefer the plugin install (see README) — it needs no file copying and uninstalls cleanly.
# Use this only if you are not installing as a plugin; running both double-installs the skill.
#
#   ./install.sh            install or update
#   ./install.sh --uninstall  remove everything this script installed
#
# Non-interactive, and it never asks for a credential. The optional decision engine is installed
# inert; enabling it is a separate, opt-in step documented in docs/jev.md.
set -e
cd "$(dirname "$0")"
D="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
MANIFEST="$D/.agent-dispatcher-installed"

# Remove only files a previous run of this script installed.
uninstall_previous() {
  [ -f "$MANIFEST" ] || return 0
  while IFS= read -r f; do
    [ -n "$f" ] && rm -f "$f"
  done < "$MANIFEST"
  rm -f "$MANIFEST"
}

if [ "$1" = "--uninstall" ]; then
  uninstall_previous
  for f in commands/agent-*.md; do
    t="$D/commands/$(basename "$f")"
    [ -f "$t" ] && grep -q "agent-dispatcher skill" "$t" 2>/dev/null && rm -f "$t"
  done
  rm -rf "$D/skills/agent-dispatcher"
  rm -f "$D/hooks/agent-dispatcher-activate.sh"
  python3 - "$D" <<'PY'
import json, pathlib, shutil, sys
p = pathlib.Path(sys.argv[1]) / "settings.json"
if p.exists():
    s = json.loads(p.read_text())
    starts = s.get("hooks", {}).get("SessionStart", [])
    kept = [e for e in starts
            if not any("agent-dispatcher-activate" in h.get("command", "") for h in e.get("hooks", []))]
    if len(kept) != len(starts):
        s["hooks"]["SessionStart"] = kept
        p.write_text(json.dumps(s, indent=2) + "\n")
        print("removed SessionStart hook")
PY
  echo "uninstalled from $D (flag files left alone)"
  exit 0
fi

python3 build.py
python3 test_build.py
python3 test_decision.py
python3 -c "import json,pathlib,sys; p=pathlib.Path(sys.argv[1])/'settings.json'; p.exists() and json.loads(p.read_text())" "$D" \
  || { echo "$D/settings.json is not valid JSON — fix it first; nothing was installed"; exit 1; }

uninstall_previous
mkdir -p "$D/skills" "$D/commands" "$D/hooks"
# Everything the pack owns lives under one directory. Category names like "security" and
# "design" are far too collision-prone to claim at the top level of someone's skills dir.
rm -rf "$D/skills/agent-dispatcher"
mkdir -p "$D/skills/agent-dispatcher/lib"
cp -R skills/agent-dispatcher/. "$D/skills/agent-dispatcher/"
for dir in skills/*/; do
  name=$(basename "$dir")
  [ "$name" = "agent-dispatcher" ] && continue
  cp -R "$dir" "$D/skills/agent-dispatcher/lib/$name"
done
cp -R recipes "$D/skills/agent-dispatcher/recipes"
# The optional decision engine and the registries it reads. Both are inert without a provider
# credential, which this script neither asks for nor writes anywhere: the engine reads it from
# the environment at request time. Installing with no key configured is the normal case.
cp -R decision "$D/skills/agent-dispatcher/decision"
rm -rf "$D/skills/agent-dispatcher/decision/__pycache__" \
       "$D/skills/agent-dispatcher/decision/providers/__pycache__"
cp -R catalog "$D/skills/agent-dispatcher/catalog"
cp hooks/agent-dispatcher-activate.sh "$D/hooks/"
chmod +x "$D/hooks/agent-dispatcher-activate.sh"
: > "$MANIFEST"
for f in commands/agent-*.md; do
  target="$D/commands/$(basename "$f")"
  if [ -e "$target" ]; then
    echo "skipped $(basename "$f") — a file of that name already exists and was not installed by this script"
    continue
  fi
  cp "$f" "$target"
  echo "$target" >> "$MANIFEST"
done

python3 - "$D" <<'PY'
import json, pathlib, shutil, sys
d = pathlib.Path(sys.argv[1]); p = d / "settings.json"
cmd = f'bash "{d}/hooks/agent-dispatcher-activate.sh"'
s = json.loads(p.read_text()) if p.exists() else {}
hooks = s.setdefault("hooks", {}).setdefault("SessionStart", [])
if not any(h.get("command") == cmd for e in hooks for h in e.get("hooks", [])):
    bak = p.with_suffix(".json.bak-agent-dispatcher")
    if p.exists() and not bak.exists():
        shutil.copy(p, bak)
    hooks.append({"matcher": "startup|resume|clear|compact",
                  "hooks": [{"type": "command", "command": cmd, "timeout": 5}]})
    p.write_text(json.dumps(s, indent=2) + "\n")
    print("registered SessionStart hook")
else:
    print("SessionStart hook already registered")
PY
echo "installed to $D"
