#!/usr/bin/env python3
"""Opt-in Codex activation. Hook execution reads state and emits context; it writes nothing."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
import tempfile

PACK = Path(__file__).resolve().parent.parent
SESSION = re.compile(r"[A-Za-z0-9_-]{1,160}\Z")


def config_dir():
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser().resolve()


def defaults():
    return {"global_enabled": False, "projects": [], "silenced_projects": [], "silenced_sessions": []}


def read_state(config):
    path = config / "agent-dispatcher" / "state.json"
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("refusing symlinked activation state")
    if not path.exists():
        return defaults()
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or type(value.get("global_enabled")) is not bool:
        raise ValueError("invalid dispatcher activation state")
    for key in ("projects", "silenced_projects", "silenced_sessions"):
        if not isinstance(value.get(key), list) or any(not isinstance(v, str) for v in value[key]):
            raise ValueError("invalid dispatcher activation state")
    return {key: value[key] for key in defaults()}


def atomic_json(path, value):
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("refusing a symlinked dispatcher state or hook file")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".agent-dispatcher-", delete=False) as stream:
        staged = Path(stream.name)
        try:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.close()
            if path.exists():
                staged.chmod(path.stat().st_mode & 0o777)
            staged.replace(path)
        finally:
            staged.unlink(missing_ok=True)


def command(pack=PACK, config=None):
    config = config or config_dir()
    return ("python3 " + shlex.quote(str(pack / "scripts" / "activate.py"))
            + " hook --config-dir " + shlex.quote(str(config)))


def plugin_hook(pack=PACK):
    root = pack.parent.parent
    return ((root / ".codex-plugin" / "plugin.json").is_file()
            and (root / "hooks" / "hooks.json").is_file())


def hook_settings(config):
    path = config / "hooks.json"
    if path.is_symlink():
        raise ValueError("refusing to edit symlinked hooks.json")
    value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(value, dict) or not isinstance(value.get("hooks", {}), dict):
        raise ValueError("hooks.json must contain a hooks object")
    starts = value.get("hooks", {}).get("SessionStart", [])
    if not isinstance(starts, list):
        raise ValueError("SessionStart must be an array")
    for group in starts:
        if not isinstance(group, dict) or not isinstance(group.get("hooks", []), list):
            raise ValueError("invalid SessionStart group")
        if any(not isinstance(h, dict) for h in group.get("hooks", [])):
            raise ValueError("invalid SessionStart handler")
    return value


def registered(config, pack=PACK):
    if plugin_hook(pack):
        return True
    return any(h.get("command") == command(pack, config)
               for g in hook_settings(config).get("hooks", {}).get("SessionStart", [])
               for h in g.get("hooks", []))


def manage_hook(config, pack=PACK, remove=False):
    """Edit only the exact handler installed for this skill; never alter hook trust."""
    if plugin_hook(pack):
        return
    value = hook_settings(config)
    original = json.dumps(value, sort_keys=True)
    starts = value.get("hooks", {}).get("SessionStart", [])
    if remove:
        kept = []
        for group in starts:
            handlers = [h for h in group.get("hooks", []) if h.get("command") != command(pack, config)]
            if handlers or not group.get("hooks"):
                kept.append({**group, "hooks": handlers} if handlers != group.get("hooks", []) else group)
        if kept == starts:
            return
        value["hooks"]["SessionStart"] = kept
    elif not registered(config, pack):
        value.setdefault("hooks", {}).setdefault("SessionStart", []).append({
            "matcher": "startup|resume|clear|compact", "hooks": [
                {"type": "command", "command": command(pack, config), "timeout": 5}]})
    if json.dumps(value, sort_keys=True) != original:
        path = config / "hooks.json"
        backup = config / "hooks.json.bak-agent-dispatcher"
        if backup.is_symlink():
            raise ValueError("refusing a symlinked hook backup")
        if path.exists() and not backup.exists():
            shutil.copyfile(path, backup)
        atomic_json(path, value)


def is_active(state, project, session=""):
    return (project not in state["silenced_projects"]
            and session not in state["silenced_sessions"]
            and (state["global_enabled"] or project in state["projects"]))


def emit_hook(config):
    try:
        raw = sys.stdin.read(65537)
        if len(raw) > 65536:
            return
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return
        cwd, session = payload.get("cwd"), payload.get("session_id", "")
        if not isinstance(cwd, str) or not Path(cwd).is_absolute():
            return
        if not isinstance(session, str) or (session and not SESSION.fullmatch(session)):
            return
        state = read_state(config)
        if not is_active(state, str(Path(cwd).resolve()), session):
            return
        # No task, repository prose, or tool output enters this preamble.
        message = ("AGENT DISPATCHER ACTIVE for Codex. The user opted into specialist routing. "
                   f"Read the skill at {json.dumps(str(PACK / 'SKILL.md'))} before routing work. "
                   "Select the role from the request. For substantial work, the first discretionary workspace action "
                   "is its read-only context helper with the full unchanged task, before listings, searches or source/contract reads "
                   "(mandatory host instructions excepted); preserve its exclusion_policy, "
                   "then read only that role and needed guides at returned exact resource paths. "
                   "Honor the user's current instructions and host permissions. "
                   "Use inline read-only validators; verify removal of any necessary owned scratch files. "
                   "Stop routing immediately when the user asks. "
                   f"Current session id: {session or '(unavailable)'}. "
                   "Use $agent-dispatcher off to stop this session, off here for this project, "
                   "or off everywhere for global activation.")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                "additionalContext": message}}))
    except (OSError, ValueError):
        return  # Malformed state or payload must not interrupt session startup.


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "on", "off", "hook"))
    parser.add_argument("--scope", choices=("global", "project", "session"), default="global")
    parser.add_argument("--project", default=os.getcwd())
    parser.add_argument("--session", default="")
    parser.add_argument("--config-dir", type=Path, default=None,
                        help="Codex config directory (default: CODEX_HOME or the user Codex directory)")
    args = parser.parse_args(argv)
    config = (args.config_dir or config_dir()).expanduser().resolve()
    if args.action == "hook":
        emit_hook(config)
        return 0
    try:
        state = read_state(config)
        project = str(Path(args.project).resolve())
        if args.action == "status":
            print(json.dumps({**state, "project": project,
                              "active_for_project": is_active(state, project, args.session),
                              "hook_registered": registered(config),
                              "hook_trust": "not checked; inspect /hooks in Codex"}, indent=2))
            return 0
        if args.scope == "session":
            if args.action != "off" or not SESSION.fullmatch(args.session):
                raise ValueError("session scope needs off and a valid --session id")
            if args.session not in state["silenced_sessions"]:
                state["silenced_sessions"].append(args.session)
        elif args.scope == "global":
            state["global_enabled"] = args.action == "on"
        else:
            enabled, disabled = state["projects"], state["silenced_projects"]
            add, discard = (enabled, disabled) if args.action == "on" else (disabled, enabled)
            if project not in add:
                add.append(project)
            if project in discard:
                discard.remove(project)
        state_path = config / "agent-dispatcher" / "state.json"
        if state_path.is_symlink() or state_path.parent.is_symlink():
            raise ValueError("refusing symlinked activation state")
        if args.action == "on":
            manage_hook(config)
        atomic_json(state_path, state)
        print(f"Codex dispatcher {args.action}: {args.scope}")
        if args.action == "on":
            print("Hook registered. Review and trust it in Codex /hooks before expecting automatic activation.")
        elif args.scope == "global":
            print("Individually enabled projects remain enabled.")
        return 0
    except (OSError, ValueError) as exc:
        print(f"Dispatcher activation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
