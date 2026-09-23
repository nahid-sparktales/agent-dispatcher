#!/usr/bin/env python3
"""Read-only dispatcher health and capability inventory; no probes or setup changes."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import shlex
import sys
from urllib.parse import urlsplit

MAX_BYTES = 2 * 1024 * 1024
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}\Z")
SECRET = re.compile(r"(?:sk-[A-Za-z0-9_-]{16,}|(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{16,}|eyJ[A-Za-z0-9_-]{12,}\.)")
EVIDENCE_STATES = {"exposed", "verified", "missing", "disabled", "blocked", "auth_required", "unknown"}
CATEGORIES = ("bundled_skill", "external_skill", "host_skill", "native_tool", "mcp_tool", "mcp_server", "setup")
LABELS = {"usable": "Usable", "needs_setup": "Needs setup", "blocked": "Blocked", "unknown": "Unknown", "not_recommended": "Not recommended"}


class DoctorError(ValueError):
    """A bounded, non-sensitive diagnostic suitable for the CLI."""


def identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value) or SECRET.search(value):
        raise DoctorError("Invalid capability identifier; use a short tool or catalog name, never credentials.")
    return value


def clean(value, limit=650):
    if not isinstance(value, str):
        return ""
    return SECRET.sub("[redacted]", " ".join(value.split()))[:limit]


def read_json(path):
    try:
        if not Path(path).is_file():
            raise DoctorError("Metadata is not a readable regular file.")
        with Path(path).open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise DoctorError("Metadata exceeds the 2 MiB limit.")
        value = json.loads(data)
        if not isinstance(value, dict):
            raise DoctorError("Metadata must be a JSON object.")
        return value
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, DoctorError):
            raise
        raise DoctorError("Metadata is unreadable or malformed; raw contents were withheld.") from None


def read_evidence(source=None):
    if not source:
        return {"skills": [], "mcps": [], "tools": [], "disabled": [], "host": {}}
    if source == "-" or source.lstrip().startswith("{"):
        # Inline JSON: Claude Code refuses heredocs whose body contains braces.
        try:
            raw = sys.stdin.read(MAX_BYTES + 1) if source == "-" else source
            if len(raw.encode("utf-8")) > MAX_BYTES:
                raise ValueError()
            data = json.loads(raw)
        except (ValueError, UnicodeError, RecursionError):
            raise DoctorError("Session evidence is malformed or exceeds 2 MiB; contents withheld.") from None
    else:
        data = read_json(source)
    if (not isinstance(data, dict) or set(data) - {"schema_version", "skills", "mcps", "tools", "disabled", "host"}
            or type(data.get("schema_version")) is not int or data["schema_version"] != 1):
        raise DoctorError("Evidence needs schema_version 1 and only documented fields.")
    out = {"skills": [], "mcps": [], "tools": [], "disabled": [], "host": {}}
    for kind in ("skills", "mcps", "tools"):
        rows = data.get(kind, [])
        if not isinstance(rows, list) or len(rows) > 10000:
            raise DoctorError("Evidence capability lists must contain at most 10000 entries.")
        seen = set()
        for row in rows:
            allowed = {"id", "status", "catalog_id"} | ({"server"} if kind == "tools" else set())
            if not isinstance(row, dict) or set(row) - allowed or not {"id", "status"} <= set(row):
                raise DoctorError("Evidence capability entries have unsupported or missing fields.")
            value = {"id": identifier(row["id"])}
            if not isinstance(row["status"], str) or row["status"] not in EVIDENCE_STATES:
                raise DoctorError("Evidence status must be a documented readiness state.")
            value["status"] = row["status"]
            for key in ("catalog_id", "server"):
                if key in row:
                    value[key] = identifier(row[key])
            if value["id"] in seen:
                raise DoctorError("Evidence contains duplicate capability identifiers.")
            seen.add(value["id"])
            out[kind].append(value)
    disabled = data.get("disabled", [])
    if not isinstance(disabled, list) or len(disabled) > 10000:
        raise DoctorError("Evidence disabled must be a bounded identifier list.")
    out["disabled"] = [identifier(item) for item in disabled]
    host = data.get("host", {})
    if not isinstance(host, dict) or set(host) - {"activation", "hook_registered", "hook_trust"}:
        raise DoctorError("Evidence host has unsupported fields.")
    if "activation" in host and (not isinstance(host["activation"], str) or host["activation"] not in {"explicit", "enabled", "disabled", "unknown"}):
        raise DoctorError("Evidence host activation is invalid.")
    if "hook_registered" in host and type(host["hook_registered"]) is not bool:
        raise DoctorError("Evidence hook_registered must be a boolean.")
    if "hook_trust" in host and (not isinstance(host["hook_trust"], str) or host["hook_trust"] not in {"trusted", "untrusted", "unknown"}):
        raise DoctorError("Evidence hook_trust is invalid.")
    out["host"] = host
    return out


def find_pack(requested=None):
    origin = Path(requested).expanduser().resolve() if requested else Path(__file__).resolve().parent
    for base in ((origin, origin / "skills/agent-dispatcher") if requested else (origin, origin / "skills/agent-dispatcher", origin.parent)):
        for rel in ("INVENTORY.json", "references/INVENTORY.json"):
            if (base / rel).is_file():
                return base, base / rel
    raise DoctorError("Dispatcher INVENTORY.json not found; pass --pack with a repository or installed pack.")


def catalog_rows(path, key):
    data = read_json(path)
    rows = data.get(key)
    if not isinstance(rows, list):
        raise DoctorError("Catalog metadata is missing an expected list.")
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            raise DoctorError("Catalog entry must be an object.")
        name = identifier(row.get("id"))
        if name in result:
            raise DoctorError("Catalog contains duplicate identifiers.")
        result[name] = row
    return result


def catalog_path(pack):
    for path in (pack / "catalog", pack / "scripts/runtime/catalog", pack.parent.parent / "catalog"):
        if (path / "loadouts.json").is_file():
            return path
    return None


def source_link(meta):
    for key in ("repository", "source"):
        text = clean(meta.get(key, ""))
        match = re.search(r"https://[^\s)]+", text)
        if match:
            value = match.group(0)
            parsed = urlsplit(value)
            if parsed.hostname and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment:
                return value
    return ""


def entry(name, category, status="unknown", detail="No current-session evidence; availability is unknown.", meta=None):
    meta = meta or {}
    return {"id": name, "name": clean(meta.get("name", name), 160), "category": category,
            "status": status, "detail": detail, "purpose": clean(meta.get("purpose", "")),
            "source": source_link(meta), "fallback": clean(meta.get("fallback", ""))}


def apply_status(row, status):
    changes = {
        "exposed": ("usable", "Exposed and callable in the supplied session; connection not tested."),
        "verified": ("usable", "A successful use was observed in the supplied session; only observed operations are verified."),
        "missing": ("needs_setup", "Host evidence reports missing or disconnected; configure only if needed for the task."),
        "auth_required": ("needs_setup", "Host evidence reports authentication required; reconnect through the host's connection settings."),
        "disabled": ("blocked", "Explicitly disabled; do not enable or recommend setup without a new user request."),
        "blocked": ("blocked", "Host or user policy blocks use; keep the restriction."),
        "unknown": ("unknown", "Session evidence could not establish availability; inspect supported host discovery.")}
    row["status"], row["detail"] = changes[status]
    row["evidence"] = status


def safe_file(path):
    try:
        if not path.is_file():
            return False
        with path.open("rb") as stream:
            stream.read(1)
        return True
    except (OSError, ValueError):
        return False


def retired(meta):
    return (meta.get("risk") == "unmaintained" or meta.get("activation") == "never"
            or str(meta.get("activation", "")).lower().startswith("not recommended"))


def inspect_config(host, config, project, issues):
    """Extract server names/enabled flags only; never export commands, URLs, env or auth."""
    servers = {}

    def add(mapping):
        if not isinstance(mapping, dict):
            raise DoctorError("Invalid MCP server configuration.")
        for name, metadata in mapping.items():
            try:
                name = identifier(name)
            except DoctorError:
                issues.append("A configured server name was omitted because it is not a safe identifier.")
                continue
            if not isinstance(metadata, dict):
                raise DoctorError("Invalid MCP server configuration.")
            enabled, disabled = metadata.get("enabled", True), metadata.get("disabled", False)
            if type(enabled) is not bool or type(disabled) is not bool:
                raise DoctorError("Invalid MCP enabled flag.")
            servers[name] = servers.get(name, False) or not enabled or disabled

    def read_config(path):
        if not path.is_file():
            return
        try:
            obj = read_json(path)
            add(obj.get("mcpServers", {}))
            disabled = obj.get("disabledMcpjsonServers", [])
            if not isinstance(disabled, list):
                raise DoctorError("Invalid disabled server metadata.")
            for name in disabled:
                servers[identifier(name)] = True
        except (DoctorError, TypeError):
            issues.append("An MCP configuration file is malformed or unreadable; availability from that file is unknown.")

    read_config(project / ".mcp.json")
    if config and host == "codex":
        path = config / "config.toml"
        if path.is_file():
            try:
                with path.open("rb") as stream:
                    raw = stream.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise ValueError()
                try:
                    import tomllib
                except ImportError:
                    # Python 3.10 fallback only recognizes the documented server tables/flags.
                    current = None
                    mapping = {}
                    for line in raw.decode("utf-8").splitlines():
                        value = line.split("#", 1)[0].strip()
                        if value.startswith("["):
                            if not value.endswith("]"):
                                raise ValueError()
                            found = re.fullmatch(r'\[mcp_servers\.([A-Za-z0-9_-]+|"[A-Za-z0-9_.:/-]+"|\'[A-Za-z0-9_.:/-]+\')\]', value)
                            current = found.group(1).strip("\"'") if found else None
                            if current:
                                mapping.setdefault(current, {})
                        elif current and re.match(r"enabled\s*=", value):
                            enabled = re.fullmatch(r"enabled\s*=\s*(true|false)", value)
                            if not enabled:
                                raise ValueError()
                            mapping[current]["enabled"] = enabled.group(1) == "true"
                    add(mapping)
                    issues.append("Python 3.10: Codex server metadata uses a limited table/flag parser; complete TOML validation was unavailable.")
                else:
                    add(tomllib.loads(raw.decode("utf-8")).get("mcp_servers", {}))
            except (OSError, ValueError, TypeError, UnicodeError):
                issues.append("Codex MCP configuration is malformed or unreadable; raw contents were withheld.")
    elif config and host == "claude":
        for path in (config / "settings.json", config.parent / ".claude.json", project / ".claude/settings.json", project / ".claude/settings.local.json"):
            read_config(path)
    return servers


def scan_skills(pack, config, project, issues):
    roots = [project / ".agents/skills", project / ".claude/skills", project / ".codex/skills"]
    if config:
        roots.extend((config / "skills", config / "skills/.system", config.parent / ".agents/skills"))
        try:
            roots.extend(sorted((config / "plugins/cache").glob("*/*/*/skills")))
        except OSError:
            issues.append("Plugin cache skill discovery could not be completed.")
    result = []
    seen = set()
    for root in roots:
        try:
            files = sorted(root.glob("*/SKILL.md"))
        except OSError:
            issues.append("One skill directory could not be inspected.")
            continue
        for file in files:
            resolved = file.resolve()
            if resolved in seen or resolved == pack / "SKILL.md":
                continue
            seen.add(resolved)
            try:
                name = identifier(file.parent.name)
            except DoctorError:
                issues.append("An installed skill with an unsafe identifier was omitted.")
                continue
            row = entry(name, "host_skill", detail="Skill file found on disk; current-session exposure and provenance are unconfirmed.")
            row["location"] = clean(str(file), 500)
            result.append(row)
    return result


def check_setup(pack, host, config, project, evidence, issues):
    rows = []
    activation = "explicit"
    registered = None
    if host == "codex" and config:
        state_path = config / "agent-dispatcher/state.json"
        if state_path.is_file():
            try:
                state = read_json(state_path)
                if type(state.get("global_enabled")) is not bool or any(
                    not isinstance(state.get(k), list) or any(not isinstance(v, str) for v in state[k])
                    for k in ("projects", "silenced_projects", "silenced_sessions")):
                    raise DoctorError("Invalid activation state.")
                if str(project) in state["silenced_projects"]:
                    activation = "disabled"
                elif state["global_enabled"] or str(project) in state["projects"]:
                    activation = "enabled"
                if state["silenced_sessions"]:
                    issues.append("Session silencing exists; current-session activation requires host evidence.")
            except DoctorError:
                activation = "unknown"
                issues.append("Dispatcher activation state is malformed or unreadable.")
        hook_file = config / "hooks.json"
        expected = "python3 " + shlex.quote(str(pack / "scripts/activate.py")) + " hook --config-dir " + shlex.quote(str(config))
    elif host == "claude" and config:
        if (project / ".agent-dispatcher-off").is_file():
            activation = "disabled"
        elif (config / ".agent-dispatcher-active").is_file():
            activation = "enabled"
        elif (project / ".agent-dispatcher-on").is_file() and (config / ".agent-dispatcher-projects").is_file():
            try:
                if str(project) in (config / ".agent-dispatcher-projects").read_text().splitlines():
                    activation = "enabled"
            except (OSError, UnicodeError):
                activation = "unknown"
        hook_file = config / "settings.json"
        expected = "bash " + shlex.quote(str(config / "hooks/agent-dispatcher-activate.sh"))
        if (config / ".agent-dispatcher-off").is_dir():
            issues.append("Current Claude session silencing was not checked; host evidence can establish it.")
    else:
        activation = "unknown"
        hook_file, expected = None, None
    if hook_file is not None:
        registered = False
        if hook_file.is_file():
            try:
                hooks = read_json(hook_file).get("hooks", {})
                if not isinstance(hooks, dict) or not isinstance(hooks.get("SessionStart", []), list):
                    raise DoctorError("Invalid hook metadata.")
                for group in hooks.get("SessionStart", []):
                    if not isinstance(group, dict) or not isinstance(group.get("hooks", []), list):
                        raise DoctorError("Invalid hook metadata.")
                    for hook in group.get("hooks", []):
                        if not isinstance(hook, dict):
                            raise DoctorError("Invalid hook metadata.")
                        command = hook.get("command")
                        legacy = f'bash "{config}/hooks/agent-dispatcher-activate.sh"'
                        if command == expected or (host == "claude" and command == legacy):
                            registered = True
            except DoctorError:
                registered = None
                issues.append("Hook metadata is malformed or unreadable; registration is unknown.")
    plugin_root = pack.parent.parent
    plugin_hook = (plugin_root / "hooks/hooks.json").is_file() and any(
        (plugin_root / rel).is_file() for rel in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"))
    if plugin_hook and registered is not True:
        issues.append("Plugin hook files exist; host registration and trust are not established by files alone.")
    metadata = evidence.get("host", {})
    activation = metadata.get("activation", activation)
    registered = metadata.get("hook_registered", registered)
    trust = metadata.get("hook_trust", "unknown")
    detail = {"explicit": "Explicit invocation is available; automatic activation is off by default and this is healthy.",
              "enabled": "Automatic activation is enabled for this project; session silencing may still apply unless host evidence covers it.",
              "disabled": "Automatic activation is explicitly disabled; preserve the user's preference.",
              "unknown": "Activation could not be established; select a host or provide host evidence."}[activation]
    rows.append(entry("activation", "setup", "blocked" if activation == "disabled" else "unknown" if activation == "unknown" else "usable", detail))
    hook_detail = "Hook registered" if registered else "Hook not registered" if registered is False else "Hook registration unknown"
    hook_detail += "; trust " + trust + "."
    hook_status = "unknown"
    if registered is True and trust == "trusted":
        hook_status = "usable"
    elif trust == "untrusted":
        hook_status = "blocked"
    elif registered is False and activation == "enabled":
        hook_status = "needs_setup"
        hook_detail += " Re-register the dispatcher hook using the documented activation command."
    elif registered is False and activation == "explicit":
        hook_status = "usable"
        hook_detail += " Optional for explicit invocation; no repair is required."
    rows.append(entry("hook", "setup", hook_status, hook_detail))
    rows.append(learning_row(project, issues))
    if config:
        candidates = [config / "skills/agent-dispatcher", config.parent / ".agents/skills/agent-dispatcher",
                      project / ".agents/skills/agent-dispatcher", project / ".claude/skills/agent-dispatcher"]
        copies = {p.resolve() for p in candidates if (p / "SKILL.md").is_file()}
        if (pack / "SKILL.md").is_file():
            copies.add(pack.resolve())
        if len(copies) > 1:
            rows.append(entry("multiple-copies", "setup", "unknown", "Multiple distinct dispatcher copies were found. Check host discovery for precedence before removing anything."))
    return rows


def learning_row(project, issues):
    """Procedural learning is the user's own switch and off by default; off is healthy, not a repair item."""
    helper = Path(__file__).resolve().with_name("learning.py")
    if not helper.is_file():
        return entry("procedural-learning", "setup", "unknown", "Learning helper is not installed beside doctor.py; repair the pack if learning is wanted.")
    try:
        namespace = {"__name__": "_dispatcher_doctor_learning", "__file__": str(helper)}
        exec(compile(helper.read_text(encoding="utf-8"), str(helper), "exec"), namespace)
        settings = namespace["load_settings"](project=project)
    except (OSError, UnicodeError, SyntaxError, ValueError, TypeError, KeyError):
        issues.append("Procedural learning settings are unreadable or invalid; learned guidance is declined until repaired.")
        return entry("procedural-learning", "setup", "unknown", "Learning settings could not be read; packets use bundled guidance only.")
    if not settings["enabled"]:
        return entry("procedural-learning", "setup", "usable", "Procedural learning is off (default): bundled guidance only, nothing recorded. Enable shadow mode in the user's own settings file to start.")
    return entry("procedural-learning", "setup", "usable", f"Procedural learning is enabled in {settings['mode']} mode; overlays need evaluation and human approval before they compose into packets.")


def project_signals(project, issues):
    signals = set()
    for name, files in {"supabase": ["supabase/config.toml"], "vercel": ["vercel.json", ".vercel/project.json"],
                        "cloudflare": ["wrangler.toml", "wrangler.json", "wrangler.jsonc"]}.items():
        if any((project / file).is_file() for file in files):
            signals.add(name)
    if (project / ".github").is_dir():
        signals.add("github")
    if (project / "package.json").is_file():
        try:
            package = read_json(project / "package.json")
            deps = set()
            for key in ("dependencies", "devDependencies", "peerDependencies"):
                if isinstance(package.get(key, {}), dict):
                    deps.update(package.get(key, {}))
            for name, prefixes in {"react": ("react",), "nextjs": ("next",), "supabase": ("@supabase/",),
                                   "sentry": ("@sentry/",), "playwright": ("@playwright/", "playwright"),
                                   "cloudflare": ("wrangler", "@cloudflare/")}.items():
                if any(dep == prefix or (prefix.endswith("/") and dep.startswith(prefix)) for dep in deps for prefix in prefixes):
                    signals.add(name)
            if signals & {"react", "nextjs"}:
                signals.add("frontend_stack")
        except DoctorError:
            issues.append("Project package metadata could not be read; stack recommendations are limited.")
    return signals


def recommend(rows, role, signals, metadata):
    weights = {}
    reasons = {}
    if role:
        for tier, score in (("core", 95), ("preferred", 80)):
            for name in role.get("skills", {}).get(tier, []):
                weights[name], reasons[name] = score, "Used by the selected role's " + tier + " loadout."
        for name in role.get("verification", []):
            weights[name], reasons[name] = 85, "Used for verification by the selected role."
        for name in role.get("mcps", {}).get("recommended", []):
            weights[name], reasons[name] = 65, "Recommended by the selected role; check whether this task needs the external context."
        for condition, names in role.get("skills", {}).get("conditional", {}).items():
            if condition in signals:
                for name in names:
                    weights[name], reasons[name] = 75, "Selected role and observed project signal: " + condition + "."
    for name in ("supabase", "vercel", "cloudflare", "sentry", "playwright", "github"):
        if name in signals:
            weights[name], reasons[name] = 80, "Relevant project configuration or dependency found: " + name + "."
    if signals & {"react", "nextjs"}:
        weights["context7"], reasons["context7"] = 55, "Framework dependencies found; current official API documentation may help."
    result = []
    for row in rows:
        name = row["id"]
        if row["status"] in {"usable", "blocked", "not_recommended"}:
            continue
        meta = metadata.get(name, {})
        if meta.get("trust") == "community" or name == "postgres-community":
            continue
        if row["category"] == "bundled_skill" and row["status"] == "needs_setup":
            weight, reason = 100, "A bundled guide is missing or unreadable."
            action = "Repair or reinstall this dispatcher pack from its trusted source."
        elif name in {"package-files", "catalog-references"} and row["status"] == "needs_setup":
            weight, reason = 100, "Required dispatcher files or role references are missing."
            action = "Repair or reinstall this dispatcher pack from its trusted source."
        elif name == "hook" and row["status"] == "needs_setup":
            weight, reason = 90, "Automatic routing is enabled but the hook is missing."
            action = "Use the host's documented dispatcher activation command and review hook trust."
        elif name not in weights:
            continue
        else:
            weight, reason = weights[name], reasons[name]
            if row["status"] == "unknown":
                action = "Check current-session discovery and permissions first; installation has not been shown missing."
            elif row.get("evidence") == "auth_required":
                action = "Reconnect through the host's connection settings if this task needs the service."
            else:
                action = "Configure the optional capability through the host if this task needs it; use the fallback meanwhile."
        result.append({"id": name, "priority": weight, "reason": reason, "action": action,
                       "source": row["source"], "fallback": row["fallback"]})
    return [dict(item, rank=rank) for rank, item in enumerate(sorted(result, key=lambda r: (-r["priority"], r["id"]))[:8], 1)]


def inspect(pack=None, project=None, host=None, config_dir=None, role=None, evidence=None, scope="all"):
    pack, inventory_path = find_pack(pack)
    project = Path(project or os.getcwd()).expanduser().resolve()
    if host is None:
        host = "codex" if (pack / "references/INVENTORY.json").is_file() else None
    config = Path(config_dir).expanduser().resolve() if config_dir else (
        Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser().resolve() if host == "codex" else
        Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser().resolve() if host == "claude" else None)
    if host is None and config is not None:
        raise DoctorError("--config-dir requires --host when the package does not identify its host.")
    issues = []
    evidence = evidence or read_evidence()
    inventory = {key: catalog_rows(inventory_path, key) for key in ("local_skills", "external_skills", "tools_and_mcps")}
    catalog = catalog_path(pack)
    roles = {}
    if catalog:
        roles = catalog_rows(catalog / "loadouts.json", "roles")
        for key, filename, listkey in (("external_skills", "external-skills.json", "skills"), ("tools_and_mcps", "mcp.json", "servers")):
            if (catalog / filename).is_file():
                for name, data in catalog_rows(catalog / filename, listkey).items():
                    if name in inventory[key]:
                        inventory[key][name] = {**data, **inventory[key][name]}
    else:
        issues.append("Role loadout metadata is missing; role-aware recommendations are unavailable.")
    selected = None
    if role:
        matches = [r for r in roles.values() if role.casefold() in {r["id"].casefold(), str(r.get("slug", "")).casefold(), str(r.get("name", "")).casefold()}]
        if len(matches) != 1:
            raise DoctorError("Role was not found unambiguously; use an id, command alias, or name from the role catalog.")
        selected = matches[0]
    rows = []
    metadata = {}
    for key, category in (("local_skills", "bundled_skill"), ("external_skills", "external_skill"), ("tools_and_mcps", "mcp_server")):
        for name, meta in inventory[key].items():
            category_here = "native_tool" if name == "workspace" and key == "tools_and_mcps" else category
            row = entry(name, category_here, meta=meta)
            metadata[name] = meta
            if category == "bundled_skill":
                paths = meta.get("paths", [])
                if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
                    raise DoctorError("Bundled guide paths are malformed.")
                found = next((pack / p for p in paths if safe_file(pack / p)), None)
                row["status"] = "usable" if found else "needs_setup"
                row["detail"] = "Bundled guide is readable; it was not activated or executed." if found else "Bundled guide is missing or unreadable; repair this pack."
            rows.append(row)
    known = {r["id"]: r for r in rows}
    observed = scan_skills(pack, config, project, issues)
    rows.extend(observed)
    configured = inspect_config(host, config, project, issues)
    config_rows = {}
    for name, disabled in configured.items():
        # Configuration aliases are arbitrary. Never claim an official catalog identity
        # from a matching server name alone.
        row = entry("configured:" + name, "mcp_server", detail="Local server alias " + name + ": configured; identity and current-session connection are unconfirmed.")
        row["configured"] = True
        row["server_alias"] = name
        if disabled:
            apply_status(row, "disabled")
        config_rows[name] = row
        rows.append(row)
    blocked = set(evidence.get("disabled", []))
    blocked_aliases = {name for name, disabled in configured.items() if disabled}
    server_map = {}
    native_groups = {}
    evidence_targets = set()
    for kind in ("skills", "mcps", "tools"):
        for item in evidence.get(kind, []):
            category = "host_skill" if kind == "skills" else "mcp_server" if kind == "mcps" else "mcp_tool" if "server" in item else "native_tool"
            target = item.get("catalog_id")
            aggregate = None
            if target:
                aggregate = known.get(target)
                allowed = {"bundled_skill", "external_skill"} if kind == "skills" else {"mcp_server"} if kind == "mcps" else {"native_tool"}
                if aggregate is None or aggregate["category"] not in allowed or (kind == "tools" and "server" in item):
                    raise DoctorError("Evidence catalog_id does not match a catalog entry in this category; map MCP identity in mcps, not tools.")
            # Every actual callable tool retains its own row, even when several tools
            # jointly establish the aggregate native workspace capability.
            row = aggregate if aggregate is not None and kind != "tools" else None
            local = config_rows.get(item["id"]) if kind == "mcps" else None
            if row is None:
                row = local or entry(item["id"], category)
                row["id"] = item["id"]
                if local is None:
                    rows.append(row)
            elif local is not None:
                rows.remove(local)
                row["configured"] = True
            key = (kind, item["id"] if kind == "tools" else target or item["id"])
            if key in evidence_targets:
                raise DoctorError("Multiple evidence rows map to the same catalog capability.")
            evidence_targets.add(key)
            apply_status(row, item["status"])
            if kind == "skills" and item["status"] == "exposed":
                row["detail"] = "Skill exposed in the supplied session; no skill scripts were run."
            if kind == "mcps":
                server_map[item["id"]] = row
            if kind == "tools" and "server" in item:
                row["server"] = item["server"]
            if item["status"] in {"blocked", "disabled"} or item["id"] in blocked_aliases:
                blocked.add(item["id"])
                if target and kind != "tools":
                    blocked.add(target)
            if item["id"] in blocked or (target and target in blocked):
                row["status"], row["detail"] = "blocked", "Explicitly disabled or blocked; preserve the restriction."
                if kind == "mcps":
                    blocked_aliases.add(item["id"])
            if kind == "tools" and aggregate is not None:
                row["catalog_id"] = target
                aggregate.setdefault("tools", []).append(item["id"])
                native_groups.setdefault(target, []).append(row)
    for target, members in native_groups.items():
        aggregate = known[target]
        usable = [member for member in members if member["status"] == "usable"]
        if target in blocked:
            aggregate["status"] = "blocked"
            aggregate["detail"] = "Explicitly disabled or blocked; preserve the restriction."
        elif usable:
            aggregate["status"] = "usable"
            aggregate["evidence"] = "exposed"
            aggregate["detail"] = "Some native tools are exposed; check each listed tool's readiness and permissions."
        else:
            aggregate["status"] = "unknown"
            aggregate["detail"] = "No usable native tool was established by the supplied evidence; inspect individual tool states."
    # Exposed individual tools establish partial server exposure, not every operation's access.
    for row in list(rows):
        server = row.get("server")
        if not server:
            continue
        srv = server_map.get(server) or config_rows.get(server)
        if srv is None:
            srv = entry(server, "mcp_server")
            rows.append(srv)
            server_map[server] = srv
        srv.setdefault("tools", []).append(row["id"])
        if row["status"] == "usable" and srv["status"] == "unknown":
            srv["status"] = "usable"
            srv["detail"] = "Some tools are exposed; only listed operations are available. Connection not tested unless their row says verified."
    for row in rows:
        if (row["id"] in blocked or row.get("catalog_id") in blocked or row.get("server_alias") in blocked or row.get("server") in blocked
                or row.get("server") in blocked_aliases
                or (row.get("server") in server_map and server_map[row["server"]]["status"] == "blocked")):
            row["status"], row["detail"] = "blocked", "Explicitly disabled or blocked; preserve the restriction."
        elif retired(metadata.get(row["id"], {})):
            row["status"], row["detail"] = "not_recommended", "Catalog marks this capability unmaintained or not recommended; use its maintained fallback."
        parent = server_map.get(row.get("server"))
        if parent and row["status"] != "blocked" and parent.get("evidence") in {"auth_required", "missing"}:
            if row.get("evidence") == "verified":
                row["detail"] += " Server-level failure evidence conflicts with this success; availability is limited to the observed operation."
                parent["partial_success"] = True
            else:
                row["status"] = "needs_setup"
                row["detail"] = "The supplied server evidence reports authentication required or a missing connection; tool exposure alone does not override that blocker."
        dependencies = metadata.get(row["id"], {}).get("required_tools", [])
        if dependencies and row["category"] in {"bundled_skill", "external_skill"}:
            row["dependencies"] = [{"id": name, "status": known.get(name, {}).get("status", "unknown")} for name in dependencies if isinstance(name, str)]
    ref_base = pack / "references" if (pack / "references/INVENTORY.json").is_file() else pack
    required = [pack / "SKILL.md"] + [ref_base / name for name in (
        "INDEX.md", "CONTEXT.md", "CONTEXT-REFERENCE.md", "ROLES.md", "CONTROLS.md",
        "DELEGATION.md", "PROJECT-MAP.md", "MEMORY.md", "VERIFICATION.md", "jev.md", "DOCTOR.md")]
    required += [ref_base / "roles" / (name + ".md") for name in roles]
    required += [pack / "scripts" / name if ref_base != pack else pack / name
                 for name in ("doctor.py", "context.py", "context_packet.py", "context_reuse.py", "parser_cache.py", "project_map.py", "project_graph.py",
                 "repo_index.py", "retrieval.py", "context_budget.py", "llm_retrieval.py", "repo_store.py", "repo_builder.py", "exploration.py", "experience.py", "repository_intelligence.py",
                 "repository_memory.py", "repo_history.py",
                              "resources.py", "verification.py", "preferences.py", "change_audit.py")]
    runtime = catalog.parent if catalog else (pack / "scripts/runtime" if ref_base != pack else pack)
    required += [runtime / "catalog/loadouts.json", runtime / "catalog/resource-paths.json", runtime / "decision/redact.py"]
    missing_files = [path for path in required if not safe_file(path)]
    health = entry("package-files", "setup", "needs_setup" if missing_files else "usable",
                   str(len(missing_files)) + " required package files missing or unreadable; repair or reinstall the dispatcher." if missing_files else "Entrypoint, core references, role files and local helpers are readable.")
    health["missing_files"] = [os.path.relpath(path, pack) for path in missing_files]
    rows.append(health)
    rows.extend(check_setup(pack, host, config, project, evidence, issues))
    # Check references in role loadouts against this inventory without loading role bodies.
    missing_refs = set()
    for item in roles.values():
        skills = item.get("skills", {})
        references = [name for tier in ("core", "preferred", "optional") for name in skills.get(tier, [])]
        references.extend(name for names in skills.get("conditional", {}).values() for name in names)
        references.extend(item.get("verification", []))
        references.extend(name for names in item.get("mcps", {}).values() for name in names)
        missing_refs.update(name for name in references if name not in known)
    if missing_refs:
        rows.append(entry("catalog-references", "setup", "needs_setup", "Role loadouts reference missing inventory entries; rebuild or reinstall the pack."))
    signals = project_signals(project, issues)
    recommendations = recommend(rows, selected, signals, metadata)
    if scope == "skills":
        visible = [r for r in rows if r["category"].endswith("skill")]
    elif scope == "mcps":
        visible = [r for r in rows if r["category"] == "mcp_server"]
    elif scope == "tools":
        visible = [r for r in rows if r["category"] in {"native_tool", "mcp_tool"}]
    elif scope == "setup":
        visible = [r for r in rows if r["status"] != "usable"]
    else:
        visible = rows
    visible.sort(key=lambda r: (CATEGORIES.index(r["category"]), r["id"], r.get("location", "")))
    displayed = {(r["id"], r["category"]) for r in visible}
    recommendations = [r for r in recommendations if any(name == r["id"] for name, category in displayed)]
    limits = ["Catalog entries are candidates, not proof of installation or connection.",
              "Only selected local directories and supplied current-session evidence were inspected; this is not a complete machine or account inventory.",
              "Configured servers do not prove connectivity. Exposed tools are untested unless a successful session use was supplied.",
              "Session evidence is caller-supplied, not a live probe. Disabled preferences must be supplied when the host does not expose them.",
              "No network probes, tool execution, installations, authentication, permission changes, or file writes were performed."]
    if not evidence.get("skills") and not evidence.get("mcps") and not evidence.get("tools"):
        limits.append("No current-session capability evidence supplied; use --evidence to include host skills, MCPs and individual callable tools.")
    if scope == "setup":
        limits.append("The setup filter excludes usable entries; counts describe only the displayed subset.")
    return {"schema_version": 1, "read_only": True, "scope": scope, "host": host or "unknown",
            "role": selected["id"] if selected else None, "project_signals": sorted(signals),
            "counts": dict(Counter(r["status"] for r in visible)),
            "category_counts": {category: dict(Counter(r["status"] for r in visible if r["category"] == category)) for category in CATEGORIES if any(r["category"] == category for r in visible)},
            "entries": visible, "recommendations": recommendations, "issues": sorted(set(issues)), "limits": limits}


def render(report):
    lines = ["Dispatcher doctor — read-only", "Scope: " + report["scope"] + "; host: " + report["host"] + "; role: " + (report["role"] or "project signals only"),
             "Counts: " + ", ".join(LABELS[k] + " " + str(v) for k, v in sorted(report["counts"].items()))]
    for limit in report["limits"]:
        lines.append("Note: " + limit)
    for issue in report["issues"]:
        lines.append("Attention: " + issue)
    for category, counts in report["category_counts"].items():
        lines.extend(("", category.replace("_", " ").title() + " (" + str(sum(counts.values())) + ")", "Name | Status | Evidence / next step", "--- | --- | ---"))
        for row in report["entries"]:
            if row["category"] != category:
                continue
            details = row["detail"]
            if row["purpose"]:
                details += " Purpose: " + row["purpose"]
            if row.get("missing_files"):
                details += " Missing files: " + ", ".join(row["missing_files"])
            if row.get("location"):
                details += " File: " + row["location"]
            if row.get("server"):
                details += " Server: " + row["server"]
            if row.get("tools"):
                details += " Exposed tools: " + ", ".join(row["tools"])
            if row.get("dependencies"):
                details += " Execution dependencies: " + ", ".join(d["id"] + " (" + d["status"] + ")" for d in row["dependencies"])
            if row["source"]:
                details += " Source: " + row["source"]
            if row["fallback"]:
                details += " Fallback: " + row["fallback"]
            lines.append(row["id"] + " | " + LABELS[row["status"]] + " | " + details.replace("|", "\\|"))
    lines.extend(("", "Ranked recommendations"))
    for i, item in enumerate(report["recommendations"], 1):
        lines.append(str(i) + ". " + item["id"] + ": " + item["reason"] + " " + item["action"])
        if item["source"]:
            lines.append("   Source: " + item["source"])
        if item["fallback"]:
            lines.append("   Fallback: " + item["fallback"])
    if not report["recommendations"]:
        lines.append("No targeted additions or repairs identified from the available evidence. Select --role for role-specific checks.")
    lines.extend(("", "No setup changes were made."))
    return "\n".join(lines)


EVIDENCE_HELP = """Session evidence (optional; sanitized JSON, never raw config or tool output):
  {"schema_version":1,
   "skills":[{"id":"host-skill","catalog_id":"external-catalog-id","status":"exposed"}],
   "mcps":[{"id":"host-server","catalog_id":"github","status":"verified"}],
   "tools":[{"id":"mcp__github__list_issues","server":"host-server","status":"exposed"}],
   "disabled":["task-observer"],
   "host":{"activation":"explicit","hook_registered":false,"hook_trust":"unknown"}}
All fields except schema_version are optional. Each capability requires id and status.
Status: exposed, verified, missing, disabled, blocked, auth_required, unknown.
Only use verified after an observed successful use in the CURRENT session.
Only set catalog_id after matching provenance, not just a similar name. Otherwise
host-only entries remain separate. Native tools omit server. IDs use 1-160 letters,
digits, dots, underscores, colons, slashes or hyphens. Free-form fields are rejected.
Host activation: explicit/enabled/disabled/unknown. Hook trust: trusted/untrusted/unknown.
Evidence does not grant authorization and must reflect explicit disabled preferences.
The CLI never probes connections, executes tools, installs services, or changes files.
Exit: 0 for a completed diagnostic (including findings); 2 for invalid inputs/metadata.
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog=EVIDENCE_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scope", nargs="?", default="all", choices=("all", "skills", "mcps", "tools", "setup"))
    parser.add_argument("--pack", type=Path, help="Repository or installed dispatcher pack (auto-detected by default)")
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="Project to inspect without running its code")
    parser.add_argument("--host", choices=("codex", "claude"), help="Host configuration to inspect; Codex packages auto-detect Codex")
    parser.add_argument("--config-dir", type=Path, help="Host configuration directory override")
    parser.add_argument("--role", help="Role id, command alias, or display name for targeted recommendations")
    parser.add_argument("--evidence", help="Sanitized current-session evidence: inline JSON object, JSON file, or - for stdin")
    parser.add_argument("--json", action="store_true", help="Machine-readable report, including every row in scope")
    args = parser.parse_args(argv)
    try:
        report = inspect(args.pack, args.project, args.host, args.config_dir, args.role, read_evidence(args.evidence), args.scope)
    except (DoctorError, OSError, TypeError, KeyError, UnicodeError, AttributeError, ValueError) as exc:
        # Do not echo JSON parser exceptions, paths or untrusted values.
        message = str(exc) if isinstance(exc, DoctorError) else "Metadata could not be inspected safely; raw contents were withheld."
        print(json.dumps({"error": message, "read_only": True}) if args.json else "Doctor: " + message, file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
