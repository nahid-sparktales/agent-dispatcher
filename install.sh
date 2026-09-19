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
set -euo pipefail
cd "$(dirname "$0")"
case "${1:-}" in
  ""|--uninstall) ;;
  --help|-h) echo "Usage: ./install.sh [--uninstall]"; exit 0 ;;
  *) echo "Usage: ./install.sh [--uninstall]" >&2; exit 2 ;;
esac
[ "$#" -le 1 ] || { echo "Usage: ./install.sh [--uninstall]" >&2; exit 2; }
D="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
# Manifest entries and hook paths must stay valid when called from another directory.
D=$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$D")
MANIFEST="$D/.agent-dispatcher-installed"

# The manifest records command files and proves a prior manual installation owned the
# fixed skill directory and hook path, including installations from older releases.
uninstall_previous() {
  [ -f "$MANIFEST" ] || return 0
  while IFS= read -r f; do
    [ -n "$f" ] && rm -f "$f"
  done < "$MANIFEST"
  rm -f "$MANIFEST"
}

# Validate settings and deletion targets before either path touches the installation.
require_valid_settings() {
  python3 -c '
import json, pathlib, re, sys
d = pathlib.Path(sys.argv[1])
try:
    for rel in ("settings.json", "settings.json.bak-agent-dispatcher", "skills", "commands",
                "hooks", "skills/agent-dispatcher", "hooks/agent-dispatcher-activate.sh",
                ".agent-dispatcher-installed"):
        if (d / rel).is_symlink():
            raise ValueError("an installation target is a symlink")
        if (d / rel).exists():
            directory = rel in ("skills", "commands", "hooks", "skills/agent-dispatcher")
            if (d / rel).is_dir() != directory:
                raise ValueError("an installation target has the wrong file type")
    p = d / "settings.json"
    s = json.loads(p.read_text()) if p.exists() else {}
    if not isinstance(s, dict) or not isinstance(s.get("hooks", {}), dict):
        raise ValueError("settings must contain objects")
    starts = s.get("hooks", {}).get("SessionStart", [])
    if not isinstance(starts, list):
        raise ValueError("SessionStart must be an array")
    for e in starts:
        if not isinstance(e, dict) or not isinstance(e.get("hooks", []), list):
            raise ValueError("invalid SessionStart entry")
        if any(not isinstance(h, dict) or not isinstance(h.get("command", ""), str)
               for h in e.get("hooks", [])):
            raise ValueError("invalid hook entry")
    manifest = d / ".agent-dispatcher-installed"
    if manifest.exists():
        for name in manifest.read_text().splitlines():
            if not name:
                continue
            p = pathlib.Path(name)
            if (p.parent != d / "commands" or not re.fullmatch(r"agent-[a-z0-9-]+\.md", p.name)
                    or p.is_symlink()):
                raise ValueError("installed-file manifest has an unsafe entry")
    elif any((d / rel).exists() for rel in
             ("skills/agent-dispatcher", "hooks/agent-dispatcher-activate.sh")):
        print("Existing dispatcher skill or hook has no installation manifest; nothing was changed. "
              "Move the conflicting files aside before installing, or restore the original "
              "manifest if this was a previous manual installation.", file=sys.stderr)
        sys.exit(1)
except (OSError, ValueError) as exc:
    print(f"Installation settings are not valid JSON or have an unsafe layout ({exc.__class__.__name__}); nothing was changed", file=sys.stderr)
    sys.exit(1)
' "$D"
}

require_valid_settings
if [ "${1:-}" = "--uninstall" ]; then
  # Without a recorded installation, even a matching hook registration is not ours.
  [ -f "$MANIFEST" ] || { echo "No recorded manual installation in $D; nothing was changed"; exit 0; }
  # Deregister before deleting. The other order leaves settings.json starting a hook script the
  # same run has already removed, and every later session errors on it.
  python3 - "$D" <<'PY'
import json, pathlib, shlex, shutil, sys
d = pathlib.Path(sys.argv[1])
p = d / "settings.json"
script = str(d / "hooks" / "agent-dispatcher-activate.sh")
owned = {"bash " + shlex.quote(script), f'bash "{script}"'}
if p.exists():
    s = json.loads(p.read_text())
    starts = s.get("hooks", {}).get("SessionStart", [])
    kept = []
    for e in starts:
        # Drop our hook, not the entry around it — a hook of the user's own may share it.
        hooks = [h for h in e.get("hooks", [])
                 if h.get("command", "") not in owned]
        if hooks or not e.get("hooks"):
            kept.append(e if hooks == e.get("hooks", []) else {**e, "hooks": hooks})
    if kept != starts:
        bak = p.with_suffix(".json.bak-agent-dispatcher")
        if not bak.exists():
            shutil.copy(p, bak)
        s["hooks"]["SessionStart"] = kept
        p.write_text(json.dumps(s, indent=2) + "\n")
        print("removed SessionStart hook")
PY
  uninstall_previous
  rm -rf "$D/skills/agent-dispatcher"
  rm -f "$D/hooks/agent-dispatcher-activate.sh"
  echo "uninstalled from $D (flag files left alone)"
  exit 0
fi

python3 build.py
python3 test_build.py
python3 test_decision.py

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
  if [ -e "$target" ] || [ -L "$target" ]; then
    echo "skipped $(basename "$f") — a file of that name already exists and was not installed by this script"
    continue
  fi
  cp "$f" "$target"
  echo "$target" >> "$MANIFEST"
done

python3 - "$D" <<'PY'
import json, pathlib, shlex, shutil, sys
d = pathlib.Path(sys.argv[1]); p = d / "settings.json"
cmd = "bash " + shlex.quote(str(d / "hooks" / "agent-dispatcher-activate.sh"))
s = json.loads(p.read_text()) if p.exists() else {}
hooks = s.setdefault("hooks", {}).setdefault("SessionStart", [])
changed = False
# Earlier versions wrote a double-quoted path. Upgrade it in place, both to avoid a second
# hook registration and to remove shell expansion from paths containing dollars/backticks.
legacy = f'bash "{d}/hooks/agent-dispatcher-activate.sh"'
for entry in hooks:
    for hook in entry.get("hooks", []):
        if hook.get("command") == legacy and legacy != cmd:
            hook["command"] = cmd
            changed = True
if not any(h.get("command") == cmd for e in hooks for h in e.get("hooks", [])):
    hooks.append({"matcher": "startup|resume|clear|compact",
                  "hooks": [{"type": "command", "command": cmd, "timeout": 5}]})
    changed = True
if changed:
    bak = p.with_suffix(".json.bak-agent-dispatcher")
    if p.exists() and not bak.exists():
        shutil.copy(p, bak)
    p.write_text(json.dumps(s, indent=2) + "\n")
    print("registered SessionStart hook")
else:
    print("SessionStart hook already registered")
PY
echo "installed to $D"
