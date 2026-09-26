#!/usr/bin/env python3
"""Capability Intelligence, health half: one normalized capability model over the existing catalogs and host observations.

    definitions   views over catalog/skills.json, external-skills.json, mcp.json, loadouts.json and recipe workflows;
                  never a second hand-maintained registry
    instances     what one host actually has: bundled guides, scanned skills, configured servers, plugins, approved CLIs,
                  API credential references, and capabilities a host observation snapshot reports
    receipts      bounded evidence: who observed what operation, when, in which session, with which outcome
    health        independent dimensions (presence, configuration, exposure, connectivity, authentication,
                  authorization, compatibility, policy, freshness) and a derived display state with a scope qualifier

Default inspection is passive: local metadata, the host's own observation snapshot and stored receipts. No network
request, process start, package manager, browser, login, hook or model call happens unless a reviewed probe adapter
is explicitly approved in the user's own settings file AND the invocation asks for that probe level. A health record
never grants a permission; the host's authorization is rechecked at execution time.

Storage: `capabilities.sqlite` through repo_store's hardened owner-only opener. Host-scoped connector evidence lives
under `capability-v1/host-<ref>/` in the private cache; project-scoped experiments and recommendations live in the
project's private state directory. Neither lives inside a working tree.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import copy
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

EVIDENCE_SCHEMA = 2
SNAPSHOT_SCHEMA = 1
STORE_FILE = "capabilities.sqlite"
MAX_BYTES = 2 * 1024 * 1024
MAX_SKILL_BYTES = 256 * 1024
MAX_PACKAGE_FILES = 500
MAX_EXPLANATION = 240
CLOCK_SKEW = 300
KINDS = ("skill", "mcp_server", "mcp_tool", "plugin", "native_tool", "cli", "api", "role", "recipe")
DIMENSIONS = {
    "presence": ("installed", "absent", "unknown"),
    "configuration": ("valid", "invalid", "unknown", "not_applicable"),
    "exposure": ("callable", "deferred", "not_exposed", "unknown"),
    "connectivity": ("verified", "failed", "untested", "not_applicable"),
    "authentication": ("authenticated", "required", "unknown", "not_applicable"),
    "authorization": ("allowed", "denied", "unknown", "not_applicable"),
    "compatibility": ("compatible", "incompatible", "unknown"),
    "policy": ("enabled", "disabled", "blocked", "quarantined", "retired"),
    "freshness": ("fresh", "stale", "expired", "unknown"),
}
DISPLAY = ("HEALTHY", "DEGRADED", "AUTH_REQUIRED", "MISCONFIGURED", "UNAVAILABLE", "UNTESTED")
POLICY_BADGES = {"disabled": "DISABLED", "blocked": "BLOCKED", "quarantined": "QUARANTINED", "retired": "RETIRED"}
OBSERVATION_TYPES = ("static_validation", "host_exposure", "transport_negotiation", "tool_enumeration", "approved_read_probe",
                     "observed_task_call", "user_report")
LIVE_TYPES = OBSERVATION_TYPES[1:]
# Evidence provenance. Only the probe executor in this module mints trusted_adapter receipts; a caller-supplied snapshot
# can claim at most host_adapter, and only when the invocation says so.
SOURCES = {"trusted_adapter": 3, "host_adapter": 2, "model_snapshot": 1, "host_evidence_v1": 1, "user_report": 0}
SUPPLIED_SOURCES = ("host_adapter", "model_snapshot", "user_report")
OUTCOMES = ("success", "failure", "skipped", "unsupported")
DISCOVERY = ("complete", "partial", "unsupported", "failed", "not_requested")
REASONS = ("OK", "MISSING_REQUIRED_DEPENDENCY", "OPTIONAL_DEPENDENCY_UNAVAILABLE", "HOST_DISCOVERY_PARTIAL", "CALLABLE_NOT_CONNECTION_TESTED",
           "AUTHENTICATION_REQUIRED", "PERMISSION_DENIED", "RATE_LIMITED", "TRANSPORT_TIMEOUT", "SERVICE_UNAVAILABLE", "SCHEMA_CHANGED",
           "VERSION_INCOMPATIBLE", "STALE_SESSION_EVIDENCE", "UNSUPPORTED_HOST_SURFACE", "POLICY_DISABLED", "DEPENDENCY_CYCLE",
           "INVALID_METADATA", "MISSING_REFERENCE", "DYNAMIC_CONTENT_NOT_EXECUTED", "APPROVAL_MISSING", "CIRCUIT_OPEN",
           "PACKAGE_MANAGER_LAUNCHER", "WORKSPACE_SHADOWED_BINARY", "DESTINATION_REFUSED", "REDIRECT_REFUSED", "RESPONSE_TOO_LARGE",
           "CALLBACK_REFUSED", "MALFORMED_RESPONSE", "CREDENTIAL_REFERENCE_ABSENT", "SYMLINK_ESCAPE", "SENSITIVE_PATH_WITHHELD",
           "UNSUPPORTED_METADATA", "SHADOWED_DUPLICATE", "VERIFICATION_CAPABILITY_MISSING", "NOT_INSTALLED_CATALOG_ONLY", "PROCESS_FAILED")
FAILURE_REASONS = ("AUTHENTICATION_REQUIRED", "PERMISSION_DENIED", "RATE_LIMITED", "TRANSPORT_TIMEOUT", "SERVICE_UNAVAILABLE", "SCHEMA_CHANGED",
                   "VERSION_INCOMPATIBLE", "MALFORMED_RESPONSE", "REDIRECT_REFUSED", "RESPONSE_TOO_LARGE", "DESTINATION_REFUSED", "PROCESS_FAILED")
TRANSIENT = ("RATE_LIMITED", "TRANSPORT_TIMEOUT", "SERVICE_UNAVAILABLE")
MODES = ("off", "shadow", "on")
PACKAGE_MANAGER_LAUNCHERS = {"npx", "uvx", "pipx", "bunx", "pnpx", "yarn", "pnpm", "npm", "bun", "deno", "uv", "pip", "pip3", "brew", "go", "cargo", "gem"}
KNOWN_CLIS = ("git", "gh", "psql", "docker", "supabase", "vercel", "wrangler", "playwright", "sentry-cli")
SUPPORTED_MCP_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
SENSITIVE_NAMES = (".env", "credentials", "secrets", ".pgpass", ".netrc", ".npmrc", ".pypirc", "id_rsa", "id_ed25519", "id_ecdsa")
SENSITIVE_SUFFIXES = (".tfvars", ".pem", ".key", ".p12", ".pfx", ".keystore")
SKILL_SPEC_FIELDS = ("name", "description", "license", "compatibility", "metadata", "allowed-tools")
HOST_SKILL_EXTENSIONS = {
    "claude": {"argument-hint", "disable-model-invocation", "user-invocable", "model", "context", "agent", "hooks", "when_to_use",
               "version", "effort", "paths", "shell"},
    "codex": set(),
}
DEFAULT_SETTINGS = {
    "schema_version": 1,
    "health_routing": "shadow",
    "utility_ranking": "shadow",
    "automatic_network_refresh": False,
    "automatic_process_probes": False,
    "automatic_installation": False,
    "automatic_activation": False,
    "sources": {"local": {"enabled": True}, "offline": {"enabled": True}, "curated": {"enabled": True},
                "github": {"enabled": False, "credential_env": None}, "skills_sh": {"enabled": False, "credential_env": None}},
    "probes": {"approved": [], "local_targets": [], "max_concurrency": 4, "probe_timeout_seconds": 10, "total_deadline_seconds": 60,
               "max_response_bytes": 262144, "cooldown_seconds": 300, "max_retries": 1},
    "clis": {"approved": []},
    "apis": [],
    "disabled": [],
    "freshness": {"static_days": 30, "operational_minutes": 60, "historical_days": 30},
    "evaluations": {"live_enabled": False, "judge_enabled": False, "max_trials": 0, "max_wall_seconds": 0, "max_spend_usd": None},
    "recommendation_gates": {"min_tasks": 10, "min_valid_pairs": 20, "practical_threshold_pp": 5.0, "harm_margin_pp": 5.0,
                             "max_cost_increase_ratio": 0.25, "confidence": 0.95},
    "telemetry": {"external_uploads": False},
    "retention_days": 90,
}
PROBE_ADAPTERS = {"cli.version": 1, "mcp.stdio.enumerate": 2, "http.read": 3}
SECRET = re.compile(r"(?:sk-[A-Za-z0-9_-]{16,}|(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{16,}|eyJ[A-Za-z0-9_-]{12,}\.|AKIA[0-9A-Z]{16}"
                    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|xox[abprs]-[A-Za-z0-9-]{10,}|[A-Za-z][A-Za-z0-9+.-]*://[^\s/@]+:[^\s/@]+@)")
CONTROL = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|[\x00-\x08\x0b-\x1f\x7f]")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,159}\Z")


class CapabilityError(ValueError):
    """Bounded, non-sensitive diagnostic; never echoes configuration, stderr, response bodies or credentials."""


_SIBLINGS = {}


def _sibling(name):
    if name not in _SIBLINGS:
        path = Path(__file__).resolve().with_name(name + ".py")
        namespace = {"__name__": "_dispatcher_capability_" + name, "__file__": str(path)}
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
        _SIBLINGS[name] = namespace
    return _SIBLINGS[name]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def opaque(prefix, *parts):
    return prefix + "-" + digest(list(parts))[:20]


def now():
    return int(time.time())


def clean(value, limit=MAX_EXPLANATION):
    """Sanitized single-line text: no terminal escapes, no recognizable credentials, bounded."""
    if not isinstance(value, str):
        return ""
    return SECRET.sub("[redacted]", " ".join(CONTROL.sub("", value).split()))[:limit]


def identifier(value, what="identifier"):
    if not isinstance(value, str) or not ID.fullmatch(value) or SECRET.search(value):
        raise CapabilityError(f"Invalid {what}; use a short capability name, never a credential.")
    return value


def sensitive(name):
    lower = PurePosixPath(str(name)).name.lower()
    return lower.startswith(SENSITIVE_NAMES) or lower.endswith(SENSITIVE_SUFFIXES)


# ---------------------------------------------------------------- settings


def settings_path():
    explicit = os.environ.get("AGENT_DISPATCHER_CAPABILITY_CONFIG")
    if explicit:
        return Path(explicit).expanduser()
    config = os.environ.get("XDG_CONFIG_HOME")
    return (Path(config) if config and Path(config).is_absolute() else Path.home() / ".config") / "agent-dispatcher" / "capability-intelligence.json"


def _merge(base, overrides):
    out = copy.deepcopy(base)
    for key, value in overrides.items():
        out[key] = _merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else copy.deepcopy(value)
    return out


def _read_json_file(path, limit=MAX_BYTES):
    path = Path(path)
    try:
        if path.is_symlink() or not path.is_file():
            raise CapabilityError("Expected a regular JSON file.")
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise CapabilityError("JSON file exceeds its size limit.")
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
    except CapabilityError:
        raise
    except (OSError, UnicodeError, ValueError, RecursionError):
        raise CapabilityError("JSON file is unreadable or malformed; contents withheld.") from None


def _unique(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise CapabilityError("Duplicate JSON field; ambiguous input refused.")
        out[key] = value
    return out


def _mode(value, what):
    if value not in MODES:
        raise CapabilityError(f"{what} must be off, shadow or on.")
    return value


def validate_settings(settings):
    s = settings
    if s.get("schema_version") != 1:
        raise CapabilityError("Capability settings need schema_version 1.")
    _mode(s["health_routing"], "health_routing")
    _mode(s["utility_ranking"], "utility_ranking")
    for key in ("automatic_network_refresh", "automatic_process_probes", "automatic_installation", "automatic_activation"):
        if s[key] is not False:
            raise CapabilityError(f"{key} is not supported in this release; refresh, probes, installation and activation are explicit actions.")
    if s["telemetry"].get("external_uploads") is not False:
        raise CapabilityError("External telemetry uploads do not exist in this release.")
    for name, source in s["sources"].items():
        if name not in DEFAULT_SETTINGS["sources"] or not isinstance(source, dict) or type(source.get("enabled")) is not bool:
            raise CapabilityError("sources must map known source names to {enabled: bool}.")
        env = source.get("credential_env")
        if env is not None and (not isinstance(env, str) or not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,63}", env)):
            raise CapabilityError("credential_env must name an environment variable, never hold a value.")
    probes = s["probes"]
    for key, low, high in (("max_concurrency", 1, 16), ("probe_timeout_seconds", 1, 120), ("total_deadline_seconds", 1, 900),
                           ("max_response_bytes", 1024, 8 * 1024 * 1024), ("cooldown_seconds", 0, 86400), ("max_retries", 0, 3)):
        if type(probes[key]) is not int or not low <= probes[key] <= high:
            raise CapabilityError(f"probes.{key} must be an integer between {low} and {high}.")
    if not isinstance(probes["approved"], list) or len(probes["approved"]) > 100:
        raise CapabilityError("probes.approved must be a bounded list.")
    probes["approved"] = [_validate_probe(p) for p in probes["approved"]]
    if not isinstance(probes["local_targets"], list) or any(not isinstance(t, str) or not re.fullmatch(r"[a-z0-9.-]+(?::\d{1,5})?", t) for t in probes["local_targets"]):
        raise CapabilityError("probes.local_targets must list exact host[:port] authorities.")
    clis = s["clis"]["approved"]
    if not isinstance(clis, list) or any(not isinstance(c, dict) or set(c) - {"name", "path"} or not isinstance(c.get("path"), str)
                                         or not Path(c["path"]).is_absolute() for c in clis):
        raise CapabilityError("clis.approved entries need a name and an absolute path.")
    if not isinstance(s["apis"], list) or any(not isinstance(a, dict) or set(a) - {"id", "credential_env", "operations"} for a in s["apis"]):
        raise CapabilityError("apis entries are {id, credential_env, operations}.")
    for api in s["apis"]:
        identifier(api.get("id"), "api id")
        if not isinstance(api.get("credential_env"), str) or not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,63}", api["credential_env"]):
            raise CapabilityError("apis.credential_env must name an environment variable.")
    if not isinstance(s["disabled"], list):
        raise CapabilityError("disabled must be a list of capability ids.")
    s["disabled"] = [identifier(v) for v in s["disabled"]]
    fresh = s["freshness"]
    for key, low, high in (("static_days", 1, 365), ("operational_minutes", 1, 1440), ("historical_days", 1, 365)):
        if type(fresh[key]) is not int or not low <= fresh[key] <= high:
            raise CapabilityError(f"freshness.{key} must be an integer between {low} and {high}.")
    ev = s["evaluations"]
    if type(ev["live_enabled"]) is not bool or type(ev["judge_enabled"]) is not bool:
        raise CapabilityError("evaluations switches must be booleans.")
    for key in ("max_trials", "max_wall_seconds"):
        if type(ev[key]) is not int or not 0 <= ev[key] <= 100000:
            raise CapabilityError(f"evaluations.{key} must be a non-negative integer.")
    if ev["max_spend_usd"] is not None and (isinstance(ev["max_spend_usd"], bool) or not isinstance(ev["max_spend_usd"], (int, float)) or ev["max_spend_usd"] < 0):
        raise CapabilityError("evaluations.max_spend_usd must be null or a non-negative number.")
    gates = s["recommendation_gates"]
    for key in ("min_tasks", "min_valid_pairs"):
        if type(gates[key]) is not int or not 1 <= gates[key] <= 100000:
            raise CapabilityError(f"recommendation_gates.{key} must be a positive integer.")
    for key, low, high in (("practical_threshold_pp", 0, 100), ("harm_margin_pp", 0, 100), ("max_cost_increase_ratio", 0, 10), ("confidence", 0.5, 0.999)):
        value = gates[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
            raise CapabilityError(f"recommendation_gates.{key} is out of range.")
    if type(s["retention_days"]) is not int or not 1 <= s["retention_days"] <= 3650:
        raise CapabilityError("retention_days must be a positive integer.")
    return s


def _validate_probe(probe):
    if not isinstance(probe, dict) or set(probe) - {"id", "adapter", "instance", "operation", "argv", "url", "credential_env", "local_target"}:
        raise CapabilityError("Each approved probe is {id, adapter, instance, operation, argv|url, credential_env, local_target}.")
    identifier(probe.get("id"), "probe id")
    identifier(probe.get("instance"), "probe instance")
    if probe.get("adapter") not in PROBE_ADAPTERS:
        raise CapabilityError("Approved probe names an adapter that is not a reviewed implementation.")
    if probe["adapter"] in ("cli.version", "mcp.stdio.enumerate"):
        argv = probe.get("argv")
        if not isinstance(argv, list) or not argv or len(argv) > 32 or any(not isinstance(a, str) or "\0" in a or len(a) > 400 for a in argv):
            raise CapabilityError("Process probes need an argv list; free-form shell strings are refused.")
        if not Path(argv[0]).is_absolute():
            raise CapabilityError("Process probe executables must be absolute paths; PATH lookup is refused.")
        if Path(argv[0]).name in PACKAGE_MANAGER_LAUNCHERS:
            raise CapabilityError("Package-manager launchers can download code and are never probe executables.")
    if probe["adapter"] == "http.read":
        if not isinstance(probe.get("url"), str) or len(probe["url"]) > 2000:
            raise CapabilityError("http.read probes need a URL.")
        parts = urlsplit(probe["url"])
        if parts.username or parts.password or parts.fragment or parts.scheme not in ("https", "http"):
            raise CapabilityError("Probe URLs must be credential-free http(s) URLs.")
    env = probe.get("credential_env")
    if env is not None and (not isinstance(env, str) or not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,63}", env)):
        raise CapabilityError("credential_env must name an environment variable.")
    if "local_target" in probe and type(probe["local_target"]) is not bool:
        raise CapabilityError("local_target must be a boolean.")
    return probe


def _outside(path, project):
    if project is None:
        return
    try:
        inside = Path(path).expanduser().resolve().is_relative_to(Path(project).expanduser().resolve())
    except OSError:
        inside = False
    if inside:
        raise CapabilityError("Capability settings must live outside the inspected project.")


def narrow(user, project_overrides):
    """Project settings may only narrow the user's settings: lower modes, disable sources, disable live work, disable items.

    A writable repository file can never widen host access, approve a probe, or turn a quarantined package into a trusted one.
    """
    out = copy.deepcopy(user)
    if not isinstance(project_overrides, dict):
        raise CapabilityError("Project capability settings must be a JSON object.")
    allowed = {"schema_version", "health_routing", "utility_ranking", "sources", "evaluations", "disabled"}
    if set(project_overrides) - allowed:
        raise CapabilityError("Project capability settings may only narrow modes, sources, live evaluations and disabled items.")
    for key in ("health_routing", "utility_ranking"):
        if key in project_overrides:
            requested = _mode(project_overrides[key], key)
            out[key] = MODES[min(MODES.index(requested), MODES.index(out[key]))]
    for name, value in (project_overrides.get("sources") or {}).items():
        if name in out["sources"] and isinstance(value, dict) and value.get("enabled") is False:
            out["sources"][name]["enabled"] = False
    for key in ("live_enabled", "judge_enabled"):
        if (project_overrides.get("evaluations") or {}).get(key) is False:
            out["evaluations"][key] = False
    extra = project_overrides.get("disabled") or []
    if not isinstance(extra, list):
        raise CapabilityError("Project disabled must be a list.")
    out["disabled"] = sorted(set(out["disabled"]) | {identifier(v) for v in extra})
    return out


def load_settings(path=None, project=None):
    """User settings (outside every project) narrowed by an optional project file `.agent-dispatcher/capabilities.json`."""
    location = Path(path).expanduser() if path else settings_path()
    _outside(location, project)
    if location.exists() or location.is_symlink():
        loaded = _read_json_file(location, 64 * 1024)
        if not isinstance(loaded, dict):
            raise CapabilityError("Capability settings must be a JSON object.")
        unknown = set(loaded) - set(DEFAULT_SETTINGS)
        if unknown:
            raise CapabilityError("Capability settings carry an unknown field.")
        settings = validate_settings(_merge(DEFAULT_SETTINGS, loaded))
        settings["_source"] = "user"
    else:
        settings = validate_settings(copy.deepcopy(DEFAULT_SETTINGS))
        settings["_source"] = "defaults"
    if project is not None:
        local = Path(project) / ".agent-dispatcher" / "capabilities.json"
        if local.exists() or local.is_symlink():
            settings = narrow(settings, _read_json_file(local, 64 * 1024))
            settings["_project_narrowed"] = True
    return settings


def settings_digest(settings):
    return digest({k: v for k, v in settings.items() if not k.startswith("_")})


# ---------------------------------------------------------------- bounded, containment-checked reads


def read_bounded(path, root, limit=MAX_SKILL_BYTES):
    """(bytes, reason). Refuses symlink escapes, non-regular files, replacement between check and read, and sensitive names."""
    path, root = Path(path), Path(root)
    if sensitive(path.name):
        return None, "SENSITIVE_PATH_WITHHELD"
    try:
        real_root = root.resolve(strict=True)
        real = path.resolve(strict=True)
        if not real.is_relative_to(real_root):
            return None, "SYMLINK_ESCAPE"
        fd = os.open(real, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except (OSError, RuntimeError):
        return None, "MISSING_REFERENCE"
    try:
        info = os.fstat(fd)
        after = os.stat(real, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != (after.st_dev, after.st_ino):
            return None, "INVALID_METADATA"
        data = os.read(fd, limit + 1)
        if len(data) > limit:
            return None, "INVALID_METADATA"
        return data, "OK"
    finally:
        os.close(fd)


def package_files(root, limit=MAX_PACKAGE_FILES, depth=5):
    """Relative file list of a package without following links; reports links that escape the package."""
    root = Path(root)
    real_root = root.resolve()
    files, problems = [], []
    stack = [(root, 0)]
    while stack:
        current, level = stack.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda e: e.name)
        except OSError:
            problems.append(("unreadable directory", str(current.relative_to(root)) if current != root else "."))
            continue
        for entry in entries:
            relative = str(Path(entry.path).relative_to(root))
            if entry.name in ("__pycache__", ".git", "node_modules", ".venv", "venv"):
                problems.append(("excluded dependency or cache directory", relative))
                continue
            if entry.is_symlink():
                try:
                    target = Path(entry.path).resolve(strict=True)
                except (OSError, RuntimeError):
                    problems.append(("SYMLINK_ESCAPE", relative))
                    continue
                if not target.is_relative_to(real_root):
                    problems.append(("SYMLINK_ESCAPE", relative))
                    continue
            if entry.is_dir(follow_symlinks=False):
                if level >= depth:
                    problems.append(("depth limit", relative))
                    continue
                stack.append((Path(entry.path), level + 1))
            elif entry.is_file(follow_symlinks=True):
                files.append(relative)
                if len(files) > limit:
                    problems.append(("file limit", relative))
                    return files[:limit], problems
    return sorted(files), problems


# ---------------------------------------------------------------- skill metadata


def parse_frontmatter(text):
    """A strict subset of YAML frontmatter: `key: value`, quoted scalars, `>`/`|` blocks and one level of nested maps.

    Anything else is kept as an unparsed string with a warning; duplicate keys fail closed. No YAML library, no tags, no
    anchors, no object construction.
    """
    if not text.startswith("---"):
        raise CapabilityError("SKILL.md has no frontmatter block.")
    lines = text.split("\n")
    if lines[0].strip() != "---":
        raise CapabilityError("SKILL.md frontmatter must open with a --- line.")
    try:
        end = next(i for i in range(1, min(len(lines), 400)) if lines[i].strip() == "---")
    except StopIteration:
        raise CapabilityError("SKILL.md frontmatter is not closed.") from None
    data, warnings, index = {}, [], 1
    body = lines[1:end]
    while index - 1 < len(body):
        line = body[index - 1]
        index += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.match(r"([A-Za-z_][A-Za-z0-9_-]{0,63}):(?:\s+(.*))?$", line)
        if not match or line[0].isspace():
            raise CapabilityError("SKILL.md frontmatter has a line that is not a simple key: value pair.")
        key, value = match.group(1), (match.group(2) or "").strip()
        if key in data:
            raise CapabilityError("SKILL.md frontmatter repeats a key.")
        if value in (">", "|", ">-", "|-", ""):
            block = []
            while index - 1 < len(body) and (body[index - 1].startswith((" ", "\t")) or not body[index - 1].strip()):
                block.append(body[index - 1])
                index += 1
            if value == "" and block and all(re.match(r"\s+[A-Za-z_][A-Za-z0-9_.-]*:\s", b + " ") or not b.strip() for b in block):
                nested = {}
                for b in block:
                    if b.strip():
                        k, _, v = b.strip().partition(":")
                        nested[k.strip()] = _scalar(v.strip())
                data[key] = nested
            elif value == "" and block and all(b.strip().startswith("- ") or not b.strip() for b in block):
                data[key] = [_scalar(b.strip()[2:].strip()) for b in block if b.strip()]
            else:
                joiner = "\n" if value.startswith("|") else " "
                data[key] = joiner.join(b.strip() for b in block).strip()
            continue
        if value.startswith(("[", "{", "&", "*", "!")) and not value.startswith("[") :
            warnings.append(f"frontmatter field {key} uses YAML syntax this parser keeps as text")
        data[key] = _scalar(value)
    return data, warnings, "\n".join(lines[end + 1:])


def _scalar(value):
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    if value in ("true", "false"):
        return value == "true"
    if value.startswith("[") and value.endswith("]"):
        return [_scalar(v.strip()) for v in value[1:-1].split(",") if v.strip()]
    return value


DYNAMIC = re.compile(r"!`[^`\n]{1,400}`")
LINK = re.compile(r"\]\(([^)\s]+)\)|`((?:references|scripts|assets|examples|templates)/[^`\s]+)`")


def validate_skill(directory, *, host=None, root=None, sidecar=True, strict=False):
    """Schema validity, host compatibility warnings, references and declared dependencies of one skill package.

    Reads SKILL.md and an optional manifest.json sidecar, both bounded; lists files without reading them. Nothing is
    executed: dynamic context commands, scripts, hooks and installers are reported as data.
    """
    directory = Path(directory)
    result = {"valid": False, "errors": [], "warnings": [], "name": None, "description": None, "digest": None, "references": [],
              "dynamic_commands": 0, "scripts": [], "hooks_declared": False, "dependencies": None, "files": 0, "metadata_fields": []}
    containment = Path(root) if root else directory
    try:
        containment.resolve(strict=True)
    except (OSError, RuntimeError):
        result["errors"].append("MISSING_REFERENCE")
        return result
    data, reason = read_bounded(directory / "SKILL.md", containment)
    if data is None:
        result["errors"].append(reason)
        return result
    result["digest"] = hashlib.sha256(data).hexdigest()
    try:
        text = data.decode("utf-8")
        meta, warnings, body = parse_frontmatter(text)
    except (UnicodeError, CapabilityError) as exc:
        result["errors"].append("INVALID_METADATA")
        result["warnings"].append(clean(str(exc)) if isinstance(exc, CapabilityError) else "SKILL.md is not UTF-8")
        return result
    result["warnings"].extend(warnings)
    result["metadata_fields"] = sorted(meta)
    name, description = meta.get("name"), meta.get("description")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?", name) or "--" in name:
        result["errors"].append("INVALID_METADATA")
        result["warnings"].append("name must be 1-64 lowercase letters, digits and single hyphens (Agent Skills specification)")
    elif name != directory.name and directory.name != name:
        result["warnings"].append("name differs from its directory name; the Agent Skills specification expects them to match")
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        result["errors"].append("INVALID_METADATA")
        result["warnings"].append("description is required and at most 1024 characters")
    if isinstance(meta.get("compatibility"), str) and len(meta["compatibility"]) > 500:
        result["warnings"].append("compatibility exceeds 500 characters")
    extensions = HOST_SKILL_EXTENSIONS.get(host or "", set())
    for key in meta:
        if key in SKILL_SPEC_FIELDS:
            continue
        if key in extensions:
            continue
        result["warnings"].append(f"UNSUPPORTED_METADATA: field {key} is not in the Agent Skills specification"
                                  + (f" or the documented {host} extensions" if host else "") + "; it is ignored, not an error")
    if "hooks" in meta:
        result["hooks_declared"] = True
    result["name"] = name if isinstance(name, str) else None
    result["description"] = clean(description, 300) if isinstance(description, str) else None
    result["dynamic_commands"] = len(DYNAMIC.findall(body))
    if result["dynamic_commands"]:
        result["warnings"].append("DYNAMIC_CONTENT_NOT_EXECUTED: dynamic context commands are reported, never run during discovery")
    files, problems = package_files(directory)
    result["files"] = len(files)
    escapes = [relative for problem, relative in problems if problem == "SYMLINK_ESCAPE"]
    if escapes:
        # A candidate package with an escaping link is refused; an installed skill keeps working as guidance, and the links are never followed.
        (result["errors"] if strict else result["warnings"]).append("SYMLINK_ESCAPE" if strict else
                                                                     f"SYMLINK_ESCAPE: {len(escapes)} link(s) leave the package and are never followed")
    for problem in sorted({p for p, _ in problems if p != "SYMLINK_ESCAPE"}):
        result["warnings"].append(f"package listing: {problem} ({sum(1 for p, _ in problems if p == problem)})")
    result["scripts"] = [f for f in files if f.startswith("scripts/") or f.endswith((".sh", ".py", ".js", ".ts", ".rb", ".ps1"))][:50]
    seen = set()
    for match in LINK.finditer(body):
        target = (match.group(1) or match.group(2) or "").split("#")[0]
        if not target or "://" in target or target.startswith(("mailto:", "#")) or target in seen:
            continue
        seen.add(target)
        pure = PurePosixPath(target)
        if pure.is_absolute() or ".." in pure.parts:
            result["references"].append({"path": clean(target, 160), "status": "outside_package"})
            result["warnings"].append("a reference points outside the package; it is not followed")
            continue
        if sensitive(pure.name):
            result["references"].append({"path": clean(target, 160), "status": "withheld"})
            continue
        candidate = directory / target
        status = "present"
        try:
            if candidate.is_symlink() and not candidate.resolve(strict=True).is_relative_to(containment.resolve()):
                status = "escapes"
                result["errors"].append("SYMLINK_ESCAPE")
            elif not candidate.exists():
                status = "missing"
                result["warnings"].append("MISSING_REFERENCE: " + clean(target, 120))
        except (OSError, RuntimeError):
            status = "missing"
        result["references"].append({"path": clean(target, 160), "status": status})
    if sidecar and (directory / "manifest.json").exists():
        raw, why = read_bounded(directory / "manifest.json", containment, 64 * 1024)
        try:
            manifest = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique) if raw is not None else None
            if raw is None:
                result["warnings"].append("manifest.json unreadable: " + why)
            elif isinstance(manifest, dict):
                result["dependencies"] = normalize_dependencies(manifest.get("dependencies"), manifest.get("tools"))
        except (UnicodeError, ValueError, CapabilityError):
            result["errors"].append("INVALID_METADATA")
            result["warnings"].append("manifest.json sidecar is malformed")
    result["valid"] = not result["errors"]
    return result


def _tool_ref(name):
    return "native:workspace" if name == "workspace" else name if ":" in name else "mcp:" + name


def normalize_dependencies(declared=None, tools=None):
    """{all_of, any_of, optional, conditional}. Existing sidecars list `tools` as potential execution dependencies (optional)."""
    out = {"all_of": [], "any_of": [], "optional": [], "conditional": {}}
    if tools:
        if not isinstance(tools, list):
            raise CapabilityError("tools must be a list.")
        out["optional"] = sorted({_tool_ref(identifier(t)) for t in tools if t != "workspace"})
    if declared is None:
        return out
    if not isinstance(declared, dict) or set(declared) - set(out):
        raise CapabilityError("dependencies are {all_of, any_of, optional, conditional}.")
    out["all_of"] = sorted({_tool_ref(identifier(v)) for v in declared.get("all_of") or []})
    groups = declared.get("any_of") or []
    if not isinstance(groups, list) or any(not isinstance(g, list) or not g for g in groups):
        raise CapabilityError("any_of is a list of non-empty alternative lists.")
    out["any_of"] = [sorted({_tool_ref(identifier(v)) for v in g}) for g in groups]
    out["optional"] = sorted(set(out["optional"]) | {_tool_ref(identifier(v)) for v in declared.get("optional") or []})
    conditional = declared.get("conditional") or {}
    if not isinstance(conditional, dict):
        raise CapabilityError("conditional maps an operation to its required dependencies.")
    out["conditional"] = {identifier(k): sorted({_tool_ref(identifier(v)) for v in vs}) for k, vs in conditional.items()}
    return out


# ---------------------------------------------------------------- definitions: views over existing catalogs


def find_pack(requested=None):
    return _sibling("doctor")["find_pack"](requested)


def catalog_dir(pack):
    return _sibling("doctor")["catalog_path"](Path(pack))


def catalog_digest(pack):
    base = catalog_dir(pack)
    if base is None:
        return None
    parts = {}
    for name in ("skills.json", "external-skills.json", "mcp.json", "loadouts.json"):
        try:
            parts[name] = hashlib.sha256((base / name).read_bytes()).hexdigest()
        except OSError:
            parts[name] = None
    return digest(parts)


def build_definitions(pack):
    """Normalized capability definitions derived from the canonical catalogs; aliases keep plain ids resolvable."""
    pack = Path(pack)
    base = catalog_dir(pack)
    if base is None:
        raise CapabilityError("Catalog metadata not found beside the pack.")
    skills = _read_json_file(base / "skills.json")
    external = _read_json_file(base / "external-skills.json")
    servers = _read_json_file(base / "mcp.json")
    loadouts = _read_json_file(base / "loadouts.json")
    defs = {}
    providers = {}

    def add(record):
        if record["id"] in defs:
            raise CapabilityError("Two catalog entries normalize to one capability id.")
        defs[record["id"]] = record
        if record.get("capability"):
            providers.setdefault(record["capability"], []).append(record["id"])

    for item in skills["skills"]:
        add({"id": "skill:" + item["id"], "kind": "skill", "name": item["id"], "purpose": clean(item.get("summary") or item.get("use_when", ""), 300),
             "capability": item.get("capability"), "operations": ["guidance"] + (["execute"] if item.get("scripts") else []),
             "source": {"catalog": "local", "repository": None, "path": item.get("path"), "revision": "bundled", "license": "bundled", "trust": "local"},
             "dependencies": normalize_dependencies(None, item.get("tools")), "fallbacks": [], "verification": bool(item.get("verifies")),
             "declared": {"network": None, "scripts": bool(item.get("scripts")), "writes": None}, "aliases": [item["id"]], "retired": False})
    for item in external["skills"]:
        requires = normalize_dependencies({"conditional": {"execute": item.get("required_tools") or []}}) if item.get("required_tools") else normalize_dependencies()
        add({"id": "external:" + item["id"], "kind": "skill", "name": item.get("name", item["id"]), "purpose": clean(item.get("purpose", ""), 300),
             "capability": item.get("capability"), "operations": ["guidance"] + (["execute"] if item.get("scripts_included") else []),
             "source": {"catalog": "external", "repository": item.get("repository"), "path": item.get("path"), "revision": item.get("version"),
                        "license": clean(item.get("license", ""), 120), "trust": item.get("trust")},
             "dependencies": requires, "fallbacks": [{"text": clean(item.get("fallback", ""), 240), "semantic_limit": "guidance fallback; not the external original"}],
             "verification": False, "declared": {"network": item.get("network_usage"), "scripts": item.get("scripts_included"), "writes": None},
             "aliases": [item["id"]], "retired": False})
    for item in servers["servers"]:
        native = item["id"] == "workspace"
        add({"id": ("native:" if native else "mcp:") + item["id"], "kind": "native_tool" if native else "mcp_server", "name": item.get("name", item["id"]),
             "purpose": clean(item.get("purpose", ""), 300), "capability": None, "operations": ["read"] + (["write"] if item.get("writes") else []),
             "source": {"catalog": "mcp", "repository": item.get("source") if str(item.get("source", "")).startswith("https://") else None,
                        "path": None, "revision": item.get("version"), "license": clean(item.get("license", ""), 120), "trust": "official" if item.get("official") else "community"},
             "dependencies": normalize_dependencies(), "fallbacks": [{"text": clean(item.get("fallback", ""), 240),
                                                                      "semantic_limit": "a fallback reduces scope; it is not the same operation, target or identity"}],
             "verification": False, "declared": {"network": item.get("transport") not in ("native", None), "scripts": None, "writes": item.get("writes")},
             "aliases": [item["id"]], "retired": _sibling("doctor")["retired"](item),
             "auth": clean(item.get("auth", ""), 160), "risk": item.get("risk")})
    for role in loadouts["roles"]:
        tiers = role.get("skills", {})
        refs = lambda names: [_resolve_plain(n, defs) for n in names]
        add({"id": "role:" + role["id"], "kind": "role", "name": role.get("name", role["id"]), "purpose": clean(role.get("summary", ""), 300),
             "capability": None, "operations": ["guidance"], "source": {"catalog": "role", "repository": None, "path": None, "revision": "bundled",
                                                                           "license": "bundled", "trust": "local"},
             "dependencies": {"all_of": refs(tiers.get("core", [])), "any_of": [], "optional": refs(tiers.get("preferred", []) + tiers.get("optional", []))
                              + refs(role.get("mcps", {}).get("recommended", [])),
                              "conditional": {k: refs(v) for k, v in tiers.get("conditional", {}).items()}},
             "verification_checks": refs(role.get("verification", [])), "fallbacks": [], "verification": False,
             "declared": {"network": None, "scripts": None, "writes": None}, "aliases": [role["id"], role.get("slug")], "retired": False})
    resources = _read_json_file(base / "resource-paths.json")
    for recipe_id, relative in (resources.get("recipes") or {}).items():
        sidecar = (pack / relative).with_name(PurePosixPath(relative).stem + ".workflow.json")
        if not sidecar.is_file():
            sidecar = (base.parent / relative).with_name(PurePosixPath(relative).stem + ".workflow.json")
        steps = []
        if sidecar.is_file():
            try:
                steps = _read_json_file(sidecar).get("steps", [])
            except CapabilityError:
                steps = None
        groups = [sorted(providers.get(s["capability"], [])) or ["capability:" + s["capability"]] for s in steps or [] if s.get("capability")]
        add({"id": "recipe:" + recipe_id, "kind": "recipe", "name": recipe_id, "purpose": "", "capability": None, "operations": ["guidance"],
             "source": {"catalog": "recipe", "repository": None, "path": relative, "revision": "bundled", "license": "bundled", "trust": "local"},
             "dependencies": {"all_of": [], "any_of": groups, "optional": [], "conditional": {}}, "fallbacks": [], "verification": False,
             "declared": {"network": None, "scripts": None, "writes": None}, "aliases": [recipe_id], "retired": False,
             "workflow": "invalid" if steps is None else ("present" if steps else "none")})
    return defs


def _resolve_plain(name, defs):
    for prefix in ("skill:", "external:", "mcp:", "native:"):
        if prefix + name in defs:
            return prefix + name
    return "missing:" + name


def resolve_alias(ident, defs):
    """Canonical id for a plain or canonical id; ambiguity is an error, never a guess."""
    if ident in defs:
        return ident
    matches = [d for d in defs.values() if ident in (d.get("aliases") or [])]
    if len(matches) == 1:
        return matches[0]["id"]
    if len(matches) > 1:
        raise CapabilityError("Capability alias is ambiguous; use the canonical id.")
    return None


# ---------------------------------------------------------------- evidence snapshots (v2) and the v1 projection


def upgrade_v1(document):
    """A v1 doctor evidence object -> a v2 snapshot. v1 carries no session identity, so its live claims stay report-local:
    they are never persisted as durable operational proof and never count as fresh in a later invocation."""
    v1 = _sibling("doctor")["read_evidence"](json.dumps(document)) if isinstance(document, dict) else document
    caps, observations = [], []
    for kind, target in (("skills", "skill"), ("mcps", "mcp_server"), ("tools", "tool")):
        for row in v1.get(kind, []):
            record_kind = target if target != "tool" else ("mcp_tool" if "server" in row else "native_tool")
            cap = {"id": row["id"], "kind": record_kind}
            for key in ("catalog_id", "server"):
                if key in row:
                    cap[key] = row[key]
            status = row["status"]
            cap["exposure"] = {"exposed": "callable", "verified": "callable", "missing": "not_exposed"}.get(status, "unknown")
            if status in ("disabled", "blocked"):
                cap["policy"] = status
            caps.append(cap)
            if status == "verified":
                observations.append({"capability": row["id"], "type": "observed_task_call", "operation": "observed", "outcome": "success", "reason": "OK"})
            elif status == "auth_required":
                observations.append({"capability": row["id"], "type": "observed_task_call", "operation": "observed", "outcome": "failure",
                                     "reason": "AUTHENTICATION_REQUIRED"})
            elif status == "missing":
                observations.append({"capability": row["id"], "type": "host_exposure", "operation": "exposure", "outcome": "failure",
                                     "reason": "SERVICE_UNAVAILABLE"})
    host = dict(v1.get("host", {}))
    return {"schema_version": 2, "host": dict(host, session=None, discovery={}), "capabilities": caps, "observations": observations,
            "disabled": list(v1.get("disabled", [])), "_source": "host_evidence_v1"}


def project_v1(snapshot):
    """The compatibility projection a v1 consumer (doctor.py) reads: `exposed` stays callable-but-untested."""
    rows = {"skills": [], "mcps": [], "tools": []}
    successes, auth, missing = set(), set(), set()
    for obs in snapshot.get("observations", []):
        if obs["outcome"] == "success" and obs["type"] in ("observed_task_call", "approved_read_probe", "tool_enumeration", "transport_negotiation"):
            successes.add(obs["capability"])
        if obs.get("reason") == "AUTHENTICATION_REQUIRED":
            auth.add(obs["capability"])
        if obs.get("reason") == "SERVICE_UNAVAILABLE" and obs["type"] == "host_exposure":
            missing.add(obs["capability"])
        if obs["outcome"] == "failure" and obs.get("reason") in ("TRANSPORT_TIMEOUT", "SERVICE_UNAVAILABLE", "PROCESS_FAILED"):
            missing.add(obs["capability"])  # v1 `missing` means missing or disconnected
    missing -= successes
    for cap in snapshot.get("capabilities", []):
        kind = {"skill": "skills", "mcp_server": "mcps", "mcp_tool": "tools", "native_tool": "tools"}.get(cap["kind"])
        if kind is None:
            continue  # plugins, CLIs and APIs have no v1 representation
        status = ("disabled" if cap.get("policy") == "disabled" else "blocked" if cap.get("policy") in ("blocked", "quarantined") else
                  "auth_required" if cap["id"] in auth else "missing" if cap["id"] in missing else
                  "verified" if cap["id"] in successes else "exposed" if cap.get("exposure") == "callable" else "unknown")
        row = {"id": cap["id"], "status": status}
        if cap.get("catalog_id") and kind != "tools":
            row["catalog_id"] = cap["catalog_id"]
        if kind == "tools" and cap.get("server"):
            row["server"] = cap["server"]
        rows[kind].append(row)
    host = {k: v for k, v in (snapshot.get("host") or {}).items() if k in ("activation", "hook_registered", "hook_trust")}
    return {"schema_version": 1, **rows, "disabled": list(snapshot.get("disabled", [])), "host": host}


def read_snapshot(source=None, *, supplied_as="model_snapshot"):
    """Validate a host observation snapshot (v2) or a v1 doctor evidence object. Untrusted input: strict schema, bounded."""
    if not source:
        return {"schema_version": 2, "host": {"session": None, "discovery": {}}, "capabilities": [], "observations": [], "disabled": [], "_source": None}
    if isinstance(source, dict):
        data = source
    else:
        try:
            raw = sys.stdin.read(MAX_BYTES + 1) if source == "-" else source if source.lstrip().startswith("{") else None
            if raw is None:
                data = _read_json_file(source)
            else:
                if len(raw.encode("utf-8")) > MAX_BYTES:
                    raise ValueError()
                data = json.loads(raw, object_pairs_hook=_unique)
        except CapabilityError:
            raise
        except (ValueError, UnicodeError, RecursionError):
            raise CapabilityError("Host observation snapshot is malformed or exceeds 2 MiB; contents withheld.") from None
    if not isinstance(data, dict):
        raise CapabilityError("Host observation snapshot must be a JSON object.")
    if data.get("schema_version") == 1:
        return upgrade_v1(data)
    if supplied_as not in SUPPLIED_SOURCES:
        raise CapabilityError("Supplied evidence may claim host_adapter, model_snapshot or user_report provenance only.")
    if set(data) - {"schema_version", "host", "capabilities", "observations", "disabled"} or data.get("schema_version") != EVIDENCE_SCHEMA:
        raise CapabilityError("Snapshot needs schema_version 2 and only documented fields.")
    host = data.get("host") or {}
    if not isinstance(host, dict) or set(host) - {"name", "version", "session", "discovery", "activation", "hook_registered", "hook_trust"}:
        raise CapabilityError("Snapshot host has unsupported fields.")
    if host.get("session") is not None:
        identifier(host["session"], "session reference")
    for key in ("name", "version"):
        if host.get(key) is not None:
            identifier(host[key], "host " + key)
    discovery = host.get("discovery") or {}
    if not isinstance(discovery, dict) or any(k not in ("skills", "mcps", "tools", "plugins") or v not in DISCOVERY for k, v in discovery.items()):
        raise CapabilityError("Snapshot discovery maps skills/mcps/tools/plugins to complete|partial|unsupported|failed|not_requested.")
    caps = data.get("capabilities") or []
    if not isinstance(caps, list) or len(caps) > 10000:
        raise CapabilityError("Snapshot capabilities must be a bounded list.")
    seen, out_caps = set(), []
    for cap in caps:
        allowed = {"id", "kind", "catalog_id", "server", "plugin", "connection", "exposure", "policy", "protocol_capabilities", "operations", "source"}
        if not isinstance(cap, dict) or set(cap) - allowed or not {"id", "kind"} <= set(cap):
            raise CapabilityError("Snapshot capability entries have unsupported or missing fields.")
        item = {"id": identifier(cap["id"]), "kind": cap["kind"]}
        if cap["kind"] not in KINDS or cap["kind"] in ("role", "recipe"):
            raise CapabilityError("Snapshot capability kind is not a host-observable kind.")
        for key in ("catalog_id", "server", "plugin", "connection"):
            if cap.get(key) is not None:
                item[key] = identifier(cap[key])
        if cap.get("exposure", "unknown") not in DIMENSIONS["exposure"]:
            raise CapabilityError("Snapshot exposure is not a documented state.")
        item["exposure"] = cap.get("exposure", "unknown")
        if cap.get("policy") is not None:
            if cap["policy"] not in ("enabled", "disabled", "blocked"):
                raise CapabilityError("Snapshot policy may only report enabled, disabled or blocked; quarantine is Dispatcher-owned.")
            item["policy"] = cap["policy"]
        if cap.get("source") is not None:
            if not isinstance(cap["source"], dict) or set(cap["source"]) - {"repository", "path", "revision"}:
                raise CapabilityError("Snapshot capability source is {repository, path, revision}.")
            item["source"] = {k: clean(v, 200) for k, v in cap["source"].items() if isinstance(v, str)}
        protocol = cap.get("protocol_capabilities") or []
        if not isinstance(protocol, list) or any(p not in ("tools", "resources", "prompts", "logging", "completions") for p in protocol):
            raise CapabilityError("protocol_capabilities lists MCP server capability names.")
        item["protocol_capabilities"] = sorted(set(protocol))
        item["operations"] = [_operation(op) for op in (cap.get("operations") or [])][:100]
        if item["id"] in seen:
            raise CapabilityError("Snapshot contains duplicate capability ids.")
        seen.add(item["id"])
        out_caps.append(item)
    observations = data.get("observations") or []
    if not isinstance(observations, list) or len(observations) > 20000:
        raise CapabilityError("Snapshot observations must be a bounded list.")
    out_obs = []
    for obs in observations:
        allowed = {"capability", "type", "operation", "outcome", "reason", "observed_at", "elapsed_ms"}
        if not isinstance(obs, dict) or set(obs) - allowed or not {"capability", "type", "outcome"} <= set(obs):
            raise CapabilityError("Snapshot observations need capability, type and outcome; receipt ids are never accepted from input.")
        if obs["capability"] not in seen:
            raise CapabilityError("Snapshot observation names a capability the snapshot does not list.")
        if obs["type"] not in LIVE_TYPES or obs["type"] == "approved_read_probe":
            raise CapabilityError("Only the probe executor records approved_read_probe; supplied evidence cannot claim it.")
        if obs["outcome"] not in OUTCOMES:
            raise CapabilityError("Observation outcome is not documented.")
        reason = obs.get("reason", "OK" if obs["outcome"] == "success" else None)
        if reason not in REASONS or (obs["outcome"] == "success" and reason != "OK") or (obs["outcome"] == "failure" and reason in (None, "OK")):
            raise CapabilityError("Observation reason must be a documented code consistent with its outcome.")
        kind = next(c["kind"] for c in out_caps if c["id"] == obs["capability"])
        if obs["type"] in ("tool_enumeration", "transport_negotiation") and kind not in ("mcp_server", "plugin"):
            raise CapabilityError("Enumeration and negotiation observations apply to MCP servers only.")
        item = {"capability": obs["capability"], "type": obs["type"], "operation": identifier(obs.get("operation") or obs["type"]),
                "outcome": obs["outcome"], "reason": reason}
        if obs.get("observed_at") is not None:
            if type(obs["observed_at"]) is not int:
                raise CapabilityError("observed_at must be epoch seconds.")
            item["observed_at"] = obs["observed_at"]
        if obs.get("elapsed_ms") is not None:
            if type(obs["elapsed_ms"]) is not int or not 0 <= obs["elapsed_ms"] <= 86_400_000:
                raise CapabilityError("elapsed_ms must be a bounded integer.")
            item["elapsed_ms"] = obs["elapsed_ms"]
        out_obs.append(item)
    disabled = data.get("disabled") or []
    if not isinstance(disabled, list):
        raise CapabilityError("Snapshot disabled must be a list.")
    return {"schema_version": 2, "host": {k: v for k, v in host.items()}, "capabilities": out_caps, "observations": out_obs,
            "disabled": [identifier(v) for v in disabled], "_source": supplied_as}


OPERATION_FIELDS = ("name", "access", "environment", "resource", "identity", "sensitivity")


def _operation(value):
    """Operation descriptor used for fallback equivalence; resource and identity are opaque references, never raw names."""
    if not isinstance(value, dict) or set(value) - set(OPERATION_FIELDS) or "name" not in value:
        raise CapabilityError("Operation descriptors are {name, access, environment, resource, identity, sensitivity}.")
    out = {"name": identifier(value["name"]), "access": value.get("access", "unknown"), "environment": value.get("environment", "unknown"),
           "resource": value.get("resource"), "identity": value.get("identity"), "sensitivity": value.get("sensitivity", "unknown")}
    if out["access"] not in ("read", "write", "unknown") or out["environment"] not in ("production", "staging", "development", "local", "unknown") \
            or out["sensitivity"] not in ("public", "internal", "confidential", "unknown"):
        raise CapabilityError("Operation descriptor has an undocumented access, environment or sensitivity.")
    for key in ("resource", "identity"):
        if out[key] is not None:
            identifier(out[key], "operation " + key)
    return out


# ---------------------------------------------------------------- receipts


def make_receipt(instance_id, *, source, type, operation, outcome, reason="OK", observed=None, session=None, connection=None,
                 fingerprints=None, elapsed_ms=None, explanation="", ttl=None):
    if source not in SOURCES or type not in OBSERVATION_TYPES or outcome not in OUTCOMES or reason not in REASONS:
        raise CapabilityError("Receipt uses an undocumented source, type, outcome or reason.")
    observed = observed if observed is not None else now()
    record = {"schema_version": 1, "instance_id": instance_id, "source": source, "type": type, "operation": operation, "outcome": outcome,
              "reason": reason, "observed": observed, "expires": observed + ttl if ttl else None, "session": session,
              "connection": connection, "fingerprints": fingerprints or {}, "elapsed_ms": elapsed_ms, "explanation": clean(explanation)}
    record["receipt_id"] = "rc-" + digest(record)[:24]
    return record


def classify(receipt, *, session, at, settings):
    """current | historical | expired | rejected (clock anomaly). Live evidence is session-scoped; TTL alone never proves continuity."""
    if receipt["observed"] > at + CLOCK_SKEW:
        return "rejected"
    if receipt["type"] == "static_validation":
        return "current" if at - receipt["observed"] <= settings["freshness"]["static_days"] * 86400 else "expired"
    if receipt["source"] == "host_evidence_v1" or not receipt.get("session") or receipt["session"] != session or session is None:
        return "historical"
    if receipt.get("expires") is not None and at > receipt["expires"]:
        return "expired"
    return "current"


# ---------------------------------------------------------------- instances and assessment


def _dims(**values):
    out = {"presence": "unknown", "configuration": "unknown", "exposure": "unknown", "connectivity": "untested", "authentication": "unknown",
           "authorization": "unknown", "compatibility": "unknown", "policy": "enabled", "freshness": "unknown"}
    out.update(values)
    for key, value in out.items():
        if value not in DIMENSIONS[key]:
            raise CapabilityError("Internal: undocumented dimension value.")
    return out


def _instance(definition_id, kind, name, *, host, origin, scope, location=None, content=None, parent=None, **extra):
    location_ref = digest({"location": str(location)})[:16] if location else None
    record = {"instance_id": opaque("ci", host, definition_id, kind, name, origin, scope, location_ref, content, parent),
              "definition_id": definition_id, "kind": kind, "name": clean(name, 160), "host": host, "origin": origin, "scope": scope,
              "location_ref": location_ref, "artifact_digest": content, "parent": parent, "shadowed_by": None, "children": [],
              "dimensions": _dims(), "operations": [], "reasons": [], "evidence": [], "discovery": "complete", "notes": []}
    record.update(extra)
    return record


def _skill_roots(host, config, project):
    """Documented discovery roots in host precedence order (earlier wins for duplicate names)."""
    roots = []
    if host == "claude":
        if config:
            roots.append(("user", config / "skills"))
        roots.append(("project", project / ".claude/skills"))
    elif host == "codex":
        roots.append(("project", project / ".agents/skills"))
        roots.append(("project", project / ".codex/skills"))
        if config:
            roots += [("user", config / "skills"), ("user", config.parent / ".agents/skills"), ("system", config / "skills/.system")]
    else:
        roots += [("project", project / ".agents/skills"), ("project", project / ".claude/skills"), ("project", project / ".codex/skills")]
    return roots


def _plugins(host, config, issues):
    """Plugin packages: manifests and component inventory, read as data. Hooks are counted, never executed or started."""
    out = []
    if not config:
        return out
    cache = config / "plugins/cache"
    marker = ".claude-plugin/plugin.json" if host == "claude" else ".codex-plugin/plugin.json"
    try:
        manifests = sorted(cache.glob("*/*/*/" + marker))[:200]
    except OSError:
        issues.append("Plugin cache could not be listed; plugin discovery partial.")
        return out
    enabled_map = {}
    if host == "claude" and (config / "settings.json").is_file():
        try:
            value = _read_json_file(config / "settings.json").get("enabledPlugins", {})
            enabled_map = value if isinstance(value, dict) else {}
        except CapabilityError:
            issues.append("Host settings unreadable; plugin enabled state unknown.")
    installed = _installed_plugins(config, issues) if host == "claude" else None
    roots = [m.parent.parent for m in manifests]
    for key, paths in (installed or {}).items():
        # An installed plugin without a manifest (an LSP-only plugin, for example) is still an installed plugin.
        for path in paths:
            if path.is_dir() and path not in {r.resolve() for r in roots} and path.is_relative_to(cache.resolve()):
                roots.append(path)
    for root in roots:
        manifest = root / marker
        try:
            meta = _read_json_file(manifest, 256 * 1024) if manifest.is_file() else {}
            name = identifier(str(meta.get("name") or root.parent.name))
        except CapabilityError:
            issues.append("A plugin manifest is malformed; that plugin was reported as misconfigured.")
            meta, name = None, None
        marketplace = root.parent.parent.name
        key = f"{name}@{marketplace}" if name else None
        enabled = enabled_map.get(key) if key else None
        definitions = {"mcp": {}, "lsp": {}}
        declared = [(meta or {}).get("mcpServers"), (meta or {}).get("lspServers")]
        if (root / ".mcp.json").is_file():
            try:
                raw = _read_json_file(root / ".mcp.json")
                definitions["mcp"].update(raw.get("mcpServers") if isinstance(raw.get("mcpServers"), dict) else raw)
            except CapabilityError:
                issues.append("A plugin MCP declaration is malformed.")
        if (root / ".lsp.json").is_file():
            try:
                definitions["lsp"].update(_read_json_file(root / ".lsp.json"))
            except CapabilityError:
                issues.append("A plugin LSP declaration is malformed.")
        entry = _marketplace_entry(config, marketplace, name, issues) if name else {}
        for kind, value in (("mcp", declared[0]), ("lsp", declared[1]), ("mcp", entry.get("mcpServers")), ("lsp", entry.get("lspServers"))):
            if isinstance(value, dict):
                definitions[kind].update(value)
        servers = []
        for server in sorted(definitions["mcp"]):
            try:
                servers.append(identifier(server))
            except CapabilityError:
                issues.append("A plugin MCP server with an unsafe name was omitted.")
        requirements = [_server_requirement(kind, server, spec, root) for kind in ("mcp", "lsp") for server, spec in sorted(definitions[kind].items())
                        if isinstance(spec, dict) and ID.fullmatch(str(server))]
        skills = sorted(p.parent for p in (root / "skills").glob("*/SKILL.md"))[:200] if (root / "skills").is_dir() else []
        record = (installed or {}).get(key) if key else None
        out.append({"root": root, "name": name or root.parent.name, "marketplace": marketplace, "version": clean(str((meta or {}).get("version") or root.name), 40),
                    "valid": meta is not None, "manifest": manifest.is_file(), "enabled": enabled,
                    "installed": None if installed is None or key not in installed else root.resolve() in record, "hooks": (root / "hooks/hooks.json").is_file() or bool((meta or {}).get("hooks")),
                    "agents": len(list((root / "agents").glob("*.md"))) if (root / "agents").is_dir() else 0, "servers": servers, "skills": skills,
                    "commands": len(list((root / "commands").glob("*.md"))) if (root / "commands").is_dir() else 0,
                    "requirements": requirements})
    return out


def _marketplace_entry(config, marketplace, name, issues, _cache={}):
    """A plugin's entry in its marketplace manifest (inline mcpServers/lspServers for non-strict plugins); {} when absent."""
    path = config / "plugins/marketplaces" / marketplace / ".claude-plugin/marketplace.json"
    if path not in _cache:
        try:
            data = _read_json_file(path, 4 * 1024 * 1024) if path.is_file() else {}
            _cache[path] = {str(p.get("name")): p for p in data.get("plugins", []) if isinstance(p, dict)}
        except CapabilityError:
            issues.append("A plugin marketplace manifest is unreadable; inline server definitions are unknown.")
            _cache[path] = {}
    return _cache[path].get(name) or {}


LAUNCHER_HINTS = {"npx": "Node.js (npx)", "uvx": "uv (uvx)", "bunx": "Bun (bunx)", "docker": "Docker", "node": "Node.js", "python3": "Python 3", "python": "Python",
                  "sourcekit-lsp": "Xcode or the Swift toolchain", "gopls": "the Go toolchain's gopls", "rust-analyzer": "rust-analyzer",
                  "pyright-langserver": "Pyright", "typescript-language-server": "typescript-language-server", "clangd": "clangd (LLVM)",
                  "jdtls": "Eclipse JDT Language Server", "kotlin-language-server": "kotlin-language-server", "lua-language-server": "lua-language-server"}


def _server_requirement(kind, name, spec, root):
    """What one declared server needs, as facts: a program on PATH, environment variables by name, or a sign-in. Never values."""
    text = json.dumps(spec)
    env_names = sorted(set(re.findall(r"\$\{([A-Z][A-Z0-9_]{0,63})(?::-[^}]*)?\}", text)) - {"CLAUDE_PLUGIN_ROOT", "CLAUDE_PROJECT_DIR", "HOME", "PATH"})
    out = {"kind": kind, "server": name, "transport": spec.get("type") or ("stdio" if spec.get("command") else "unknown"),
           "env_missing": [v for v in env_names if not os.environ.get(v)], "env_names": env_names}
    command = spec.get("command")
    if isinstance(command, str) and command:
        command = command.replace("${CLAUDE_PLUGIN_ROOT}", str(root))
        found = _resolve_program(command)
        out.update(program=Path(command).name, program_found=found is not None, program_hint=LAUNCHER_HINTS.get(Path(command).name),
                   downloads_on_start=Path(command).name in ("npx", "uvx", "bunx", "pnpx"))
    url = spec.get("url")
    if isinstance(url, str) and url:
        host = urlsplit(url).hostname
        out["endpoint"] = host if host and not re.search(r"\$\{", host) else None
        out["sign_in"] = out["transport"] in ("http", "sse", "streamable-http") and not any("authorization" in k.lower() for k in (spec.get("headers") or {}))
    return out


def _resolve_program(command):
    """Absolute path of a program without running it: an absolute command must exist; a bare name is looked up on absolute PATH entries."""
    if os.path.isabs(command):
        return command if os.path.isfile(command) and os.access(command, os.X_OK) else None
    if "/" in command:
        return None
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(entry) / command
        if entry and Path(entry).is_absolute() and candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _installed_plugins(config, issues):
    """Claude's own install record: plugin key -> resolved install paths. None when the host keeps no record we can read."""
    path = config / "plugins/installed_plugins.json"
    if not path.is_file():
        return None
    try:
        data = _read_json_file(path, 1024 * 1024).get("plugins")
        if not isinstance(data, dict):
            raise CapabilityError("unexpected shape")
        out = {}
        for key, rows in data.items():
            if isinstance(rows, list):
                out[str(key)] = [Path(r["installPath"]).expanduser().resolve() for r in rows if isinstance(r, dict) and isinstance(r.get("installPath"), str)]
        return out
    except (CapabilityError, OSError, ValueError, TypeError):
        issues.append("The host's plugin install record is unreadable; which cached copy is installed is not established.")
        return None


def _cli_instances(project, settings, host, issues, referenced=()):
    """Approved binaries from the user's settings, plus well-known names resolved on PATH without executing anything.

    A PATH entry inside the workspace (or a relative entry) that would win resolution marks the name shadowed; it is never run.
    """
    rows = []
    project = Path(project).resolve()
    approved = {Path(c["path"]).name if not c.get("name") else c["name"]: Path(c["path"]) for c in settings["clis"]["approved"]}
    path_entries = os.environ.get("PATH", "").split(os.pathsep)
    for name in sorted(set(KNOWN_CLIS) | set(approved) | set(referenced)):
        resolved, shadowed = None, False
        if name in approved:
            candidate = approved[name]
            if candidate.is_file() and os.access(candidate, os.X_OK):
                resolved = candidate
        else:
            for entry in path_entries:
                if not entry or not Path(entry).is_absolute():
                    candidate = Path(entry or ".") / name
                    if candidate.is_file():
                        shadowed = True
                        break
                    continue
                candidate = Path(entry) / name
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    try:
                        if candidate.resolve().is_relative_to(project) or Path(entry).resolve().is_relative_to(project):
                            shadowed = True
                            break
                    except OSError:
                        continue
                    resolved = candidate
                    break
        if resolved is None and not shadowed:
            if name in approved or name in referenced:
                # A declared dependency or approved binary that this process's PATH does not provide: authoritative for this PATH only.
                inst = _instance("cli:" + name, "cli", name, host=host, origin="path_scan", scope="user")
                inst["dimensions"] = _dims(presence="absent", configuration="unknown", connectivity="not_applicable", authentication="not_applicable",
                                           authorization="not_applicable")
                inst["notes"].append("Not found on this process's PATH; another shell or host session may differ.")
                rows.append(inst)
            continue
        inst = _instance("cli:" + name, "cli", name, host=host, origin="approved_cli" if name in approved else "path_scan", scope="user",
                         location=resolved)
        inst["approved"] = name in approved
        if shadowed:
            inst["dimensions"] = _dims(presence="unknown", configuration="invalid", connectivity="not_applicable", authentication="unknown",
                                       policy="blocked", compatibility="unknown")
            inst["reasons"].append("WORKSPACE_SHADOWED_BINARY")
            inst["notes"].append("A workspace or relative PATH entry would resolve this name first; it is never executed.")
        else:
            inst["dimensions"] = _dims(presence="installed", configuration="valid", exposure="unknown", connectivity="not_applicable",
                                       authentication="unknown", compatibility="unknown")
            if name in PACKAGE_MANAGER_LAUNCHERS:
                inst["reasons"].append("PACKAGE_MANAGER_LAUNCHER")
            if not inst["approved"]:
                inst["notes"].append("Found on PATH; not approved for version probes. A binary is not evidence of access to any target.")
            inst["operations"] = [{"name": "cli.local", "access": "unknown", "environment": "unknown", "resource": None, "identity": None, "sensitivity": "unknown"}]
        rows.append(inst)
    return rows


def build_inventory(pack=None, project=None, host=None, config_dir=None, snapshot=None, settings=None, *, store=None, session=None, at=None):
    """Instances with scoped health for one host, plus discovery coverage and the doctor report they share code with."""
    doctor = _sibling("doctor")
    at = at if at is not None else now()
    pack, _ = doctor["find_pack"](pack)
    project = Path(project or os.getcwd()).expanduser().resolve()
    settings = settings or load_settings(project=project)
    snapshot = snapshot or read_snapshot()
    host = host or (snapshot.get("host") or {}).get("name") or ("codex" if (pack / "references/INVENTORY.json").is_file() else None)
    if host not in ("claude", "codex", None):
        host = None
    config = Path(config_dir).expanduser().resolve() if config_dir else (
        Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser().resolve() if host == "codex" else
        Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser().resolve() if host == "claude" else None)
    session = session if session is not None else (snapshot.get("host") or {}).get("session")
    host_label = host or "unknown"
    issues = []
    doctor_report = doctor["inspect"](pack, project, host, config_dir, None, doctor["read_evidence"](json.dumps(project_v1(snapshot))) if snapshot.get("capabilities") else None, "all")
    defs = build_definitions(pack)
    instances = []
    by_def = {}
    disabled = set(settings["disabled"]) | set(snapshot.get("disabled", []))

    def register(inst):
        instances.append(inst)
        by_def.setdefault(inst["definition_id"], []).append(inst)
        return inst

    inventory = doctor["catalog_rows"](doctor["find_pack"](pack)[1], "local_skills")
    for ident, meta in inventory.items():
        definition = "skill:" + ident
        found = next((pack / p for p in meta.get("paths", []) if (pack / p).is_file()), None)
        inst = _instance(definition, "skill", ident, host=host_label, origin="bundled", scope="package", location=found.parent if found else None)
        if found is None:
            inst["dimensions"] = _dims(presence="absent", configuration="unknown", connectivity="not_applicable", authentication="not_applicable",
                                       authorization="not_applicable")
            inst["reasons"].append("MISSING_REFERENCE")
        else:
            data, why = read_bounded(found, found.parent)
            ok = data is not None and data.lstrip().startswith(b"---")
            inst["artifact_digest"] = hashlib.sha256(data).hexdigest() if data else None
            inst["dimensions"] = _dims(presence="installed", configuration="valid" if ok else "invalid", exposure="unknown",
                                       connectivity="not_applicable", authentication="not_applicable", authorization="not_applicable",
                                       compatibility="compatible" if ok else "unknown")
            if not ok:
                inst["reasons"].append("INVALID_METADATA" if data is not None else why)
        register(inst)
    for ident, definition in defs.items():
        if definition["kind"] not in ("role", "recipe"):
            continue
        inst = _instance(ident, definition["kind"], definition["name"], host=host_label, origin="bundled", scope="package")
        deps = definition["dependencies"]
        unresolved = [d for d in deps["all_of"] + deps["optional"] + [x for g in deps["any_of"] for x in g]
                      + [x for v in deps["conditional"].values() for x in v] if d.startswith("missing:")]
        checks = definition.get("verification_checks") or []
        missing_checks = [c for c in checks if c.startswith("missing:")]
        invalid = bool(unresolved or missing_checks or definition.get("workflow") == "invalid")
        inst["dimensions"] = _dims(presence="installed", configuration="invalid" if invalid else "valid", connectivity="not_applicable",
                                   authentication="not_applicable", authorization="not_applicable", compatibility="compatible" if not invalid else "unknown")
        if unresolved:
            inst["reasons"].append("MISSING_REFERENCE")
        if missing_checks:
            inst["reasons"].append("VERIFICATION_CAPABILITY_MISSING")
            inst["notes"].append("Mandatory verification capability is missing: this is a verification blocker, not an optional gap.")
        inst["verification_checks"] = checks
        register(inst)
    # Host skills on disk, in documented precedence order. Same name + different content or root = different instances.
    names = {}
    for scope, root in _skill_roots(host, config, project):
        try:
            candidates = sorted(root.glob("*/SKILL.md"))[:1000]
        except OSError:
            issues.append("A skill root could not be listed; skill discovery partial.")
            continue
        for skill_file in candidates:
            directory = skill_file.parent
            if directory.resolve() == pack.resolve():
                continue
            if directory.is_symlink():
                # An installation symlink is allowed; its contents are contained by the resolved target.
                containment = directory.resolve()
            else:
                containment = directory
            check = validate_skill(directory, host=host, root=containment)
            try:
                name = identifier(directory.name)
            except CapabilityError:
                issues.append("A skill directory with an unsafe name was omitted.")
                continue
            definition = _match_external(directory, check, defs) or "host-skill:" + name
            inst = _instance(definition, "skill", name, host=host_label, origin="local_scan", scope=scope, location=directory, content=check["digest"])
            inst["validation"] = {k: check[k] for k in ("valid", "errors", "warnings", "references", "dynamic_commands", "hooks_declared", "files")}
            inst["validation"]["scripts"] = len(check["scripts"])
            inst["dependencies"] = check["dependencies"]
            inst["dimensions"] = _dims(presence="installed", configuration="valid" if check["valid"] else "invalid", exposure="unknown",
                                       connectivity="not_applicable", authentication="not_applicable", authorization="not_applicable",
                                       compatibility="compatible" if check["valid"] and not any(w.startswith("UNSUPPORTED_METADATA") for w in check["warnings"]) else
                                       "unknown" if check["valid"] else "incompatible")
            inst["reasons"].extend(sorted(set(check["errors"])))
            if check["dynamic_commands"]:
                inst["reasons"].append("DYNAMIC_CONTENT_NOT_EXECUTED")
            if name in names:
                inst["shadowed_by"] = names[name]
                inst["reasons"].append("SHADOWED_DUPLICATE")
            else:
                names[name] = inst["instance_id"]
            register(inst)
    configured = doctor["inspect_config"](host, config, project, issues)
    for alias, is_disabled in configured.items():
        inst = _instance("configured:" + alias, "mcp_server", alias, host=host_label, origin="config", scope="host")
        inst["dimensions"] = _dims(presence="installed", configuration="valid", exposure="unknown", connectivity="untested",
                                   policy="disabled" if is_disabled else "enabled")
        inst["notes"].append("Configured alias; catalog identity is never inferred from a matching name.")
        register(inst)
    plugin_seen = {}
    for plugin in sorted(_plugins(host, config, issues), key=lambda p: (p["name"], p["marketplace"], p["installed"] is not True, str(p["root"]))):
        inst = _instance("plugin:" + plugin["name"] + "@" + plugin["marketplace"], "plugin", plugin["name"] + " " + plugin["version"], host=host_label,
                         origin="plugin", scope="user", location=plugin["root"], content=plugin["version"])
        key = "plugin:" + plugin["name"] + "@" + plugin["marketplace"]
        inst["install_state"] = {True: "installed", False: "cached copy, not the installed one", None: "install record unavailable"}[plugin["installed"]]
        if plugin["installed"] is False:
            inst["shadowed_by"] = plugin_seen.get(key) or "install-record"
            inst["notes"].append("A cached copy the host's install record does not point to; the installed copy is used.")
        elif key in plugin_seen:
            inst["duplicate_unresolved"] = True
            inst["notes"].append("Another cached version exists and no install record says which one the host loads.")
        else:
            plugin_seen[key] = inst["instance_id"]
        inst["components"] = {"skills": len(plugin["skills"]), "agents": plugin["agents"], "commands": plugin["commands"],
                              "hooks": plugin["hooks"], "mcp_servers": len(plugin["servers"]),
                              "lsp_servers": sum(1 for r in plugin["requirements"] if r["kind"] == "lsp")}
        inst["requirements"] = plugin["requirements"]
        inst["enable_state"] = plugin["enabled"]
        inst["install_record"] = plugin["installed"]
        connectors = bool(plugin["servers"])
        inst["dimensions"] = _dims(presence="installed", configuration=("valid" if plugin["manifest"] else "unknown") if plugin["valid"] else "invalid",
                                   exposure="unknown", connectivity="untested" if connectors else "not_applicable",
                                   authentication="unknown" if connectors else "not_applicable",
                                   authorization="unknown" if connectors else "not_applicable",
                                   compatibility="compatible" if plugin["valid"] else "unknown",
                                   policy="disabled" if plugin["enabled"] is False else "enabled")
        if plugin["hooks"]:
            inst["notes"].append("Plugin declares hooks; inspection never runs them.")
        if plugin["enabled"] is None:
            inst["notes"].append("Enabled state not established from host settings.")
        register(inst)
        for skill_dir in plugin["skills"]:
            check = validate_skill(skill_dir, host=host, root=plugin["root"])
            child = _instance("plugin-skill:" + plugin["name"] + ":" + skill_dir.name, "skill", plugin["name"] + ":" + skill_dir.name, host=host_label,
                              origin="plugin", scope="user", location=skill_dir, content=check["digest"], parent=inst["instance_id"])
            child["dimensions"] = _dims(presence="installed", configuration="valid" if check["valid"] else "invalid", connectivity="not_applicable",
                                        authentication="not_applicable", authorization="not_applicable",
                                        compatibility="compatible" if check["valid"] else "incompatible", policy=inst["dimensions"]["policy"])
            child["reasons"].extend(sorted(set(check["errors"])))
            child["shadowed_by"] = inst["shadowed_by"]  # a superseded plugin copy supersedes its components too
            inst["children"].append(child["instance_id"])
            register(child)
        for server in plugin["servers"]:
            child = _instance("plugin-mcp:" + plugin["name"] + ":" + server, "mcp_server", plugin["name"] + ":" + server, host=host_label,
                              origin="plugin", scope="user", parent=inst["instance_id"])
            child["dimensions"] = _dims(presence="installed", configuration="valid", connectivity="untested", policy=inst["dimensions"]["policy"])
            child["shadowed_by"] = inst["shadowed_by"]
            child["requirement"] = next((r for r in plugin["requirements"] if r["kind"] == "mcp" and r["server"] == server), None)
            if child["requirement"] and child["requirement"].get("program") and not child["requirement"]["program_found"]:
                child["dimensions"]["presence"] = "absent"
                child["reasons"].append("MISSING_REQUIRED_DEPENDENCY")
                child["notes"].append("The program this server starts with is not on PATH.")
            inst["children"].append(child["instance_id"])
            register(child)
    referenced = set()
    for inst in instances:
        deps = inst.get("dependencies") or {}
        names = list(deps.get("all_of", [])) + list(deps.get("optional", [])) + [d for g in deps.get("any_of", []) for d in g] \
            + [d for v in (deps.get("conditional") or {}).values() for d in v]
        referenced |= {d.split(":", 1)[1] for d in names if d.startswith("cli:") and re.fullmatch(r"[A-Za-z0-9_.+-]{1,64}", d.split(":", 1)[1])}
    for cli in _cli_instances(project, settings, host_label, issues, referenced):
        register(cli)
    for api in settings["apis"]:
        present = bool(os.environ.get(api["credential_env"]))
        inst = _instance("api:" + api["id"], "api", api["id"], host=host_label, origin="api_reference", scope="user")
        inst["dimensions"] = _dims(presence="unknown", configuration="valid" if present else "invalid", connectivity="untested", authentication="unknown")
        inst["reasons"].append("OK" if present else "CREDENTIAL_REFERENCE_ABSENT")
        inst["notes"].append("A credential reference being present is configuration evidence only, never authentication.")
        inst["operations"] = [_operation(op) for op in api.get("operations") or []]
        register(inst)
    # Host-observed capabilities (current-session snapshot).
    observed_ids = {}
    for cap in snapshot.get("capabilities", []):
        definition = None
        if cap.get("catalog_id"):
            definition = resolve_alias(cap["catalog_id"], defs)
            if definition is None:
                raise CapabilityError("Snapshot catalog_id does not match a catalog capability.")
            if cap.get("source") and defs[definition]["source"].get("repository") and cap["source"].get("repository") \
                    and cap["source"]["repository"].rstrip("/") != defs[definition]["source"]["repository"].rstrip("/"):
                raise CapabilityError("Snapshot catalog_id conflicts with the capability's recorded provenance.")
        kind = cap["kind"]
        definition = definition or {"skill": "host-skill:", "mcp_server": "host-mcp:", "mcp_tool": "host-tool:", "plugin": "plugin:",
                                    "native_tool": "native:", "cli": "cli:", "api": "api:"}[kind] + cap["id"]
        existing = next((i for i in by_def.get(definition, []) if i["origin"] in ("bundled", "config", "local_scan") and i["kind"] == kind
                         and (i["origin"] != "config" or i["name"] == cap["id"]) and not i.get("shadowed_by")), None)
        if existing is None and kind == "mcp_server" and not cap.get("catalog_id"):
            # Claude names a plugin's server `plugin:<plugin>:<server>`; the plugin's own .mcp.json declares `<server>`.
            existing = next((i for i in instances if i["kind"] == "mcp_server" and i["origin"] == "plugin" and not i.get("shadowed_by")
                             and cap["id"] in ("plugin:" + i["name"], i["name"])
                             and i["instance_id"] not in {x["instance_id"] for x in observed_ids.values()}), None)
        if existing is None and kind == "skill" and not cap.get("catalog_id"):
            # The host lists a skill by the name it loads it under; a scanned or plugin copy with that name is the same instance.
            existing = next((i for i in instances if i["kind"] == "skill" and i["name"] == cap["id"] and i["origin"] in ("local_scan", "plugin")
                             and not i.get("shadowed_by") and i["instance_id"] not in {x["instance_id"] for x in observed_ids.values()}), None)
        if existing is None and kind == "mcp_server":
            existing = next((i for i in by_def.get("configured:" + cap["id"], [])), None)
            if existing is not None and cap.get("catalog_id"):
                by_def[existing["definition_id"]].remove(existing)
                existing["definition_id"] = definition
                by_def.setdefault(definition, []).append(existing)
        inst = existing or register(_instance(definition, kind, cap["id"], host=host_label, origin="host_evidence", scope="session",
                                              connection=cap.get("connection")))
        if existing is None and kind == "skill":
            # Where a host-listed skill comes from, when the files say so: a command file, or an installed plugin of that prefix.
            if config and ":" not in cap["id"] and (config / "commands" / (cap["id"] + ".md")).is_file():
                inst["provided_by"] = "~/.claude/commands" if host == "claude" else "commands"
            elif ":" in cap["id"] and any(p["kind"] == "plugin" and p["name"].split(" ")[0] == cap["id"].split(":")[0] for p in instances):
                inst["provided_by"] = "plugin " + cap["id"].split(":")[0]
        inst["dimensions"]["exposure"] = cap["exposure"]
        if cap["exposure"] in ("callable", "deferred") and inst["dimensions"]["presence"] == "unknown":
            inst["dimensions"]["presence"] = "installed"
        if cap.get("policy") in ("disabled", "blocked"):
            inst["dimensions"]["policy"] = cap["policy"]
        if kind in ("mcp_server", "mcp_tool", "api"):
            inst["dimensions"]["connectivity"] = inst["dimensions"]["connectivity"] if inst["dimensions"]["connectivity"] != "not_applicable" else "untested"
        if kind == "native_tool":
            inst["dimensions"].update(authentication="not_applicable", connectivity="not_applicable")
        if cap.get("protocol_capabilities"):
            inst["protocol_capabilities"] = cap["protocol_capabilities"]
        if cap.get("server"):
            inst["server"] = cap["server"]
        if cap.get("plugin"):
            inst["plugin_ref"] = cap["plugin"]
        inst["operations"] = cap.get("operations") or inst["operations"]
        observed_ids[cap["id"]] = inst
    # Tools attach to their server (partial exposure means only those operations).
    for inst in instances:
        if inst.get("server") and inst["server"] in observed_ids:
            parent = observed_ids[inst["server"]]
            inst["parent"] = parent["instance_id"]
            parent["children"].append(inst["instance_id"])
    # Receipts: static validation (computed now), supplied observations, stored history.
    receipts = []
    for inst in instances:
        if inst["kind"] in ("skill", "role", "recipe") and inst["dimensions"]["presence"] == "installed":
            receipts.append(make_receipt(inst["instance_id"], source="trusted_adapter", type="static_validation", operation="guidance",
                                         outcome="success" if inst["dimensions"]["configuration"] == "valid" else "failure",
                                         reason="OK" if inst["dimensions"]["configuration"] == "valid" else (inst["reasons"] or ["INVALID_METADATA"])[0]
                                         if (inst["reasons"] or ["INVALID_METADATA"])[0] in REASONS else "INVALID_METADATA",
                                         observed=at, fingerprints={"artifact": inst["artifact_digest"]}))
    source = snapshot.get("_source") or "model_snapshot"
    for obs in snapshot.get("observations", []):
        inst = observed_ids[obs["capability"]]
        observed = obs.get("observed_at", at)
        receipts.append(make_receipt(inst["instance_id"], source=source, type=obs["type"], operation=obs["operation"], outcome=obs["outcome"],
                                     reason=obs["reason"], observed=observed, session=session if source != "host_evidence_v1" else None,
                                     connection=next((c.get("connection") for c in snapshot["capabilities"] if c["id"] == obs["capability"]), None),
                                     elapsed_ms=obs.get("elapsed_ms"), ttl=settings["freshness"]["operational_minutes"] * 60))
    if store is not None:
        known = {i["instance_id"] for i in instances}
        receipts.extend(r for r in store.receipts(known) if r["receipt_id"] not in {x["receipt_id"] for x in receipts})
    by_instance = {}
    rejected = 0
    for receipt in receipts:
        state = classify(receipt, session=session, at=at, settings=settings)
        if state == "rejected":
            rejected += 1
            continue
        by_instance.setdefault(receipt["instance_id"], []).append(dict(receipt, state=state))
    if rejected:
        issues.append(f"{rejected} receipt(s) carried impossible future timestamps and were ignored (clock anomaly).")
    breakers = store.breakers() if store is not None else {}
    retired_defs = {d for d, v in defs.items() if v.get("retired")}
    for inst in instances:
        policy = inst["dimensions"]["policy"]
        if inst["definition_id"] in retired_defs:
            policy = "retired"
        names_for_policy = {inst["definition_id"], inst["name"], inst["definition_id"].split(":", 1)[-1], inst["instance_id"]}
        if names_for_policy & disabled:
            policy = "disabled"
        if store is not None and inst["kind"] == "skill" and store.candidate_state_for(inst["artifact_digest"]) == "quarantined":
            # An installed copy of a package still under review: reported, never silently disabled or enabled.
            inst["notes"].append("SKILL.md matches a candidate still under review in quarantine; its approval state is not established.")
        inst["dimensions"]["policy"] = policy
        assess(inst, by_instance.get(inst["instance_id"], []), defs, settings)
        if inst["instance_id"] in breakers:
            inst["circuit"] = breakers[inst["instance_id"]]
    _aggregate_parents(instances)
    _dependency_health(instances, defs, by_def)
    discovery = dict((snapshot.get("host") or {}).get("discovery") or {})
    for key in ("skills", "mcps", "tools", "plugins"):
        discovery.setdefault(key, "partial" if key in ("skills", "plugins") and config else "not_requested" if not snapshot.get("capabilities") else "partial")
    catalog_only = sorted(d for d, v in defs.items() if v["kind"] in ("skill", "mcp_server") and d not in by_def and not d.startswith("skill:"))
    return {"schema_version": 2, "host": host_label, "session": session, "project_ref": _project_ref(project), "definitions": defs,
            "instances": instances, "by_definition": {k: [i["instance_id"] for i in v] for k, v in by_def.items()}, "discovery": discovery,
            "catalog_only": catalog_only, "issues": sorted(set(issues)), "doctor": doctor_report, "created": at,
            "fingerprints": {"catalog": catalog_digest(pack), "settings": settings_digest(settings),
                             "config": digest(sorted(configured.items())), "host": host_label, "evidence_source": snapshot.get("_source")}}


def _project_ref(project):
    try:
        return _sibling("parser_cache")["state_directory"](project).name[:20]
    except OSError:
        return None


def _match_external(directory, check, defs):
    """A local skill matches an external catalog entry only by recorded provenance (sidecar source), never by name."""
    raw, _ = read_bounded(directory / "manifest.json", directory, 64 * 1024) if (directory / "manifest.json").exists() else (None, None)
    if not raw:
        return None
    try:
        source = (json.loads(raw.decode("utf-8")) or {}).get("source") or {}
    except (ValueError, UnicodeError):
        return None
    if not isinstance(source, dict):
        return None
    for ident, definition in defs.items():
        src = definition["source"]
        if definition["kind"] == "skill" and src.get("repository") and source.get("repository") == src["repository"] and source.get("path") == src.get("path"):
            return ident
    return None


def assess(inst, receipts, defs, settings):
    """Derive dimensions from receipts, then the display state, a scope qualifier and reason codes. Mutates `inst`."""
    d = inst["dimensions"]
    current = [r for r in receipts if r["state"] == "current"]
    historical = [r for r in receipts if r["state"] == "historical"]
    expired = [r for r in receipts if r["state"] == "expired"]
    live_current = [r for r in current if r["type"] != "static_validation"]
    inst["evidence"] = [{"receipt_id": r["receipt_id"], "type": r["type"], "operation": r["operation"], "outcome": r["outcome"], "reason": r["reason"],
                         "state": r["state"], "source": r["source"], "observed": r["observed"]} for r in sorted(receipts, key=lambda r: -r["observed"])[:12]]
    ops = {}
    for r in sorted(live_current, key=lambda r: r["observed"]):
        ops[r["operation"]] = r
    inst["operation_status"] = {op: {"outcome": r["outcome"], "reason": r["reason"], "type": r["type"], "source": r["source"]} for op, r in ops.items()}
    connection_kinds = ("mcp_server", "mcp_tool", "api", "plugin")
    if inst["kind"] in connection_kinds and d["connectivity"] != "not_applicable":
        successes = [r for r in live_current if r["outcome"] == "success" and r["type"] in ("transport_negotiation", "tool_enumeration", "approved_read_probe", "observed_task_call")]
        failures = [r for r in live_current if r["outcome"] == "failure" and r["reason"] in ("TRANSPORT_TIMEOUT", "SERVICE_UNAVAILABLE", "PROCESS_FAILED", "MALFORMED_RESPONSE")]
        d["connectivity"] = "verified" if successes else "failed" if failures and not successes else "untested"
        if any(r["reason"] == "AUTHENTICATION_REQUIRED" for r in ops.values()):
            d["authentication"] = "required"
        elif any(r["outcome"] == "success" and r["type"] in ("approved_read_probe", "observed_task_call") for r in live_current):
            d["authentication"] = "authenticated"
        denied = [op for op, r in ops.items() if r["reason"] == "PERMISSION_DENIED"]
        allowed = [op for op, r in ops.items() if r["outcome"] == "success" and r["type"] in ("approved_read_probe", "observed_task_call")]
        d["authorization"] = "denied" if denied and not allowed else "allowed" if allowed else "unknown"
        if any(r["reason"] in ("VERSION_INCOMPATIBLE", "SCHEMA_CHANGED") for r in ops.values()):
            d["compatibility"] = "incompatible"
        elif any(r["type"] in ("transport_negotiation", "tool_enumeration") and r["outcome"] == "success" for r in live_current):
            d["compatibility"] = "compatible"
        if any(r["type"] == "host_exposure" and r["reason"] == "SERVICE_UNAVAILABLE" for r in live_current):
            d["presence"] = "absent" if inst.get("discovery") == "complete" else d["presence"]
    static = [r for r in current if r["type"] == "static_validation"]
    if live_current or (static and not historical and not expired):
        d["freshness"] = "fresh"
    elif expired:
        d["freshness"] = "expired"
    elif historical:
        d["freshness"] = "stale"
        inst["reasons"].append("STALE_SESSION_EVIDENCE")
    reasons = inst["reasons"]
    display, qualifier = "UNTESTED", "no adequate current evidence"
    partial = [op for op, r in ops.items() if r["outcome"] == "failure"]
    worked = [op for op, r in ops.items() if r["outcome"] == "success"]
    if d["configuration"] == "invalid" or d["compatibility"] == "incompatible":
        display, qualifier = "MISCONFIGURED", "configuration or compatibility error established"
    elif d["authentication"] == "required":
        host_reported = any(r["reason"] == "AUTHENTICATION_REQUIRED" and r["type"] == "host_exposure" for r in ops.values())
        display, qualifier = ("DEGRADED", "some operations work; authentication required for others") if worked else \
            ("AUTH_REQUIRED", "host reports authentication required" if host_reported else "authentication failure observed")
        reasons.append("AUTHENTICATION_REQUIRED")
    elif d["presence"] == "absent" or (d["connectivity"] == "failed" and not worked):
        failed_reasons = sorted({r["reason"] for r in ops.values() if r["outcome"] == "failure"})
        display, qualifier = "UNAVAILABLE", ("connection failed in this session: " + ", ".join(failed_reasons) if failed_reasons and d["presence"] != "absent"
                                             else "authoritative evidence of absence")
        reasons.extend(failed_reasons)
    elif inst["kind"] in ("skill", "role", "recipe"):
        if d["presence"] == "installed" and d["configuration"] == "valid" and d["freshness"] == "fresh":
            display, qualifier = "HEALTHY", "local guidance" + ("; exposed in this session" if d["exposure"] == "callable" else "")
        elif d["presence"] == "installed" and d["configuration"] == "valid":
            display, qualifier = "UNTESTED", "guidance present; static validation not current"
        elif d["exposure"] == "callable" and d["configuration"] == "unknown":
            display, qualifier = "HEALTHY", "exposed in this session; package not locally readable, contents not validated"
        elif d["exposure"] == "deferred":
            display, qualifier = "UNTESTED", "deferred: listed by discovery, not yet loaded"
    elif inst["kind"] == "native_tool":
        if d["exposure"] == "callable":
            display, qualifier = "HEALTHY", "exposed in the current session" + ("; use observed" if worked else "")
        elif d["exposure"] == "deferred":
            display, qualifier = "UNTESTED", "deferred: listed by discovery, loads on demand"
    elif inst["kind"] == "cli":
        display, qualifier = (("UNTESTED", "binary located; not executed") if d["presence"] == "installed" else
                              ("UNAVAILABLE", "not found on PATH") if d["presence"] == "absent" else ("MISCONFIGURED", "shadowed by a workspace PATH entry"))
    elif partial and worked:
        display, qualifier = "DEGRADED", "works: " + ", ".join(sorted(worked))[:80] + "; failed: " + ", ".join(sorted(partial))[:80]
        reasons.extend(r["reason"] for r in ops.values() if r["outcome"] == "failure")
    elif worked:
        named = sorted(worked)
        qualifier = "tool enumeration" if named == ["tools/list"] or all(ops[o]["type"] == "tool_enumeration" for o in named) else \
            "transport negotiation" if all(ops[o]["type"] == "transport_negotiation" for o in named) else "observed: " + ", ".join(named)[:120]
        display = "HEALTHY"
    elif d["exposure"] == "callable":
        display, qualifier = "UNTESTED", "callable; connection not tested"
        reasons.append("CALLABLE_NOT_CONNECTION_TESTED")
    elif d["exposure"] == "deferred":
        display, qualifier = "UNTESTED", "deferred: tools load on demand; connection not tested"
    elif partial:
        display, qualifier = "DEGRADED", "failed: " + ", ".join(sorted(partial))[:120]
        reasons.extend(r["reason"] for r in ops.values() if r["outcome"] == "failure")
    if d["policy"] != "enabled":
        reasons.append("POLICY_DISABLED")
    inst["display"], inst["qualifier"] = display, qualifier
    inst["badges"] = [b for b in (POLICY_BADGES.get(d["policy"]), "STALE" if d["freshness"] == "stale" else "EXPIRED" if d["freshness"] == "expired" else None,
                                  ("OLD COPY" if inst["kind"] == "plugin" or inst.get("origin") == "plugin" else "SHADOWED") if inst.get("shadowed_by") else None) if b]
    inst["eligible"] = d["policy"] == "enabled" and display not in ("MISCONFIGURED", "UNAVAILABLE") and not inst.get("shadowed_by")
    inst["reasons"] = sorted(set(r for r in reasons if r and r != "OK"))
    return inst


def _aggregate_parents(instances):
    """Plugin health summarizes its children without counting them as independent working integrations."""
    by_id = {i["instance_id"]: i for i in instances}
    for inst in instances:
        if inst["kind"] != "plugin" or inst["display"] == "MISCONFIGURED":
            continue
        if not inst["children"]:
            if inst["dimensions"]["configuration"] == "valid":
                inst["display"], inst["qualifier"] = "HEALTHY", "manifest valid; local components only (authentication not applicable)"
            elif inst["dimensions"]["configuration"] == "unknown":
                lsp = [r for r in inst.get("requirements") or [] if r["kind"] == "lsp"]
                missing = [r["program"] for r in lsp if r.get("program") and not r["program_found"]]
                if missing:
                    inst["display"], inst["qualifier"] = "UNAVAILABLE", "language server program not on PATH: " + ", ".join(missing)
                    inst["reasons"].append("MISSING_REQUIRED_DEPENDENCY")
                elif lsp:
                    inst["display"], inst["qualifier"] = "UNTESTED", "language server " + ", ".join(r.get("program") or r["server"] for r in lsp) + " found on PATH (not run)"
                else:
                    inst["display"], inst["qualifier"] = "UNTESTED", "installed, but no plugin manifest to inspect"
            continue
        states = [by_id[c]["display"] for c in inst["children"] if c in by_id]
        connectors = [by_id[c] for c in inst["children"] if c in by_id and by_id[c]["kind"] == "mcp_server"]
        if any(s == "AUTH_REQUIRED" for s in states) and any(s == "HEALTHY" for s in states):
            inst["display"], inst["qualifier"] = "DEGRADED", "local components usable; a connector requires authentication"
        elif states and all(s == "HEALTHY" for s in states):
            inst["display"], inst["qualifier"] = "HEALTHY", "plugin components"
        elif not connectors and all(s == "HEALTHY" for s in states):
            inst["display"], inst["qualifier"] = "HEALTHY", "local components (no connectors; authentication not applicable)"
        elif any(s in ("UNAVAILABLE", "MISCONFIGURED", "DEGRADED") for s in states) and any(s == "HEALTHY" for s in states):
            inst["display"], inst["qualifier"] = "DEGRADED", "some components usable; others failing"
        elif any(s == "HEALTHY" for s in states):
            untested = sum(1 for s in states if s == "UNTESTED")
            inst["display"], inst["qualifier"] = "HEALTHY", f"local components; {untested} component(s) untested"
        inst["child_summary"] = {s: states.count(s) for s in sorted(set(states))}


def _dependency_health(instances, defs, by_def):
    """Skills and roles: required vs optional dependencies against the best instance of each dependency."""
    best = {}
    for definition, members in by_def.items():
        ranked = sorted(members, key=lambda i: (not i["eligible"], DISPLAY.index(i["display"]) if i["display"] in DISPLAY else 9))
        best[definition] = ranked[0]
    for inst in instances:
        definition = defs.get(inst["definition_id"]) or {}
        deps = inst.get("dependencies") or definition.get("dependencies")
        if not deps:
            continue
        report = dependency_status(inst["definition_id"], defs, lambda ident: _dep_state(best.get(ident)), deps=deps)
        inst["dependency_status"] = report
        if report["status"] == "cycle":
            inst["reasons"].append("DEPENDENCY_CYCLE")
            inst["display"], inst["qualifier"] = "MISCONFIGURED", "dependency cycle"
        elif report["missing_required"]:
            inst["reasons"].append("MISSING_REQUIRED_DEPENDENCY")
            if inst["display"] == "HEALTHY":
                inst["display"], inst["qualifier"] = "DEGRADED", inst["qualifier"] + "; required dependency missing: " + ", ".join(report["missing_required"])[:120]
        elif report["missing_optional"]:
            inst["reasons"].append("OPTIONAL_DEPENDENCY_UNAVAILABLE")
            if inst["display"] == "HEALTHY" and inst["kind"] == "skill":
                inst["display"], inst["qualifier"] = "DEGRADED", "guidance works; optional dependency absent: " + ", ".join(report["missing_optional"])[:120]
        inst["reasons"] = sorted(set(inst["reasons"]))


def _dep_state(inst):
    if inst is None:
        return "unknown"
    if not inst["eligible"] or inst["display"] == "UNAVAILABLE" or inst["dimensions"]["presence"] == "absent":
        return "missing"
    if inst["display"] in ("HEALTHY", "DEGRADED"):
        return "available"
    return "unknown"


def dependency_status(root, defs, state_of, *, deps=None, operation=None):
    """Deterministic evaluation of all_of / any_of / optional / operation-conditional dependencies with cycle detection.

    state_of(id) -> available | missing | unknown. Unknown dependencies stay unknown; they are not treated as missing.
    """
    out = {"status": "satisfied", "missing_required": [], "missing_optional": [], "unknown": [], "cycle": [], "unresolved_ids": []}
    visiting = []

    def required_of(ident, declared=None):
        spec = declared or (defs.get(ident) or {}).get("dependencies") or {"all_of": [], "any_of": [], "optional": [], "conditional": {}}
        required = list(spec.get("all_of", []))
        if operation and operation in (spec.get("conditional") or {}):
            required += spec["conditional"][operation]
        return spec, required

    def walk(ident, declared=None):
        if ident in visiting:
            out["cycle"] = visiting[visiting.index(ident):] + [ident]
            return
        visiting.append(ident)
        spec, required = required_of(ident, declared)
        for dep in required:
            if dep.startswith("missing:") or (dep not in defs and not dep.startswith(("cli:", "api:", "host-", "native:", "mcp:", "capability:"))):
                out["unresolved_ids"].append(dep)
                out["missing_required"].append(dep)
                continue
            state = state_of(dep)
            if state == "missing":
                out["missing_required"].append(dep)
            elif state == "unknown":
                out["unknown"].append(dep)
            if dep in defs and not out["cycle"]:
                walk(dep)
        for group in spec.get("any_of", []):
            states = [state_of(dep) for dep in group]
            if "available" in states:
                continue
            if all(s == "missing" for s in states):
                out["missing_required"].append("any_of(" + "|".join(group) + ")")
            else:
                out["unknown"].append("any_of(" + "|".join(group) + ")")
        for dep in spec.get("optional", []):
            if state_of(dep) == "missing":
                out["missing_optional"].append(dep)
        visiting.pop()

    walk(root, deps)
    for key in ("missing_required", "missing_optional", "unknown", "unresolved_ids"):
        out[key] = sorted(set(out[key]))
    out["status"] = "cycle" if out["cycle"] else "missing" if out["missing_required"] else "unknown" if out["unknown"] else \
        "degraded" if out["missing_optional"] else "satisfied"
    return out


# ---------------------------------------------------------------- private store


_REPO_STORE = None


def _store_base():
    global _REPO_STORE
    if _REPO_STORE is None:
        _REPO_STORE = _sibling("repo_store")
    return _REPO_STORE


def host_directory(host, config_dir=None):
    base = os.environ.get("XDG_CACHE_HOME", "")
    home = Path(base).resolve() if base and Path(base).is_absolute() else Path.home().resolve() / ".cache"
    return home / "agent-dispatcher" / "capability-v1" / ("host-" + digest({"host": host or "unknown", "config": str(config_dir or "")})[:24])


def quarantine_root():
    base = os.environ.get("XDG_CACHE_HOME", "")
    home = Path(base).resolve() if base and Path(base).is_absolute() else Path.home().resolve() / ".cache"
    return home / "agent-dispatcher" / "capability-v1" / "quarantine"


def project_directory(project):
    return _store_base()["state_directory"](project)


def _store_class():
    base = _store_base()["_Base"]

    class CapabilityStore(base):
        """Snapshots, receipts, breakers, candidates, experiments, recommendations and passive usage. One authoritative store per scope."""

        file_name = STORE_FILE
        tables = (
            "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY, created INTEGER NOT NULL, session TEXT, complete INTEGER NOT NULL, record TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS receipts(receipt_id TEXT PRIMARY KEY, instance_id TEXT NOT NULL, observed INTEGER NOT NULL, session TEXT,"
            " type TEXT NOT NULL, record TEXT NOT NULL)",
            "CREATE INDEX IF NOT EXISTS receipts_instance ON receipts(instance_id)",
            "CREATE TABLE IF NOT EXISTS breakers(instance_id TEXT NOT NULL, operation TEXT NOT NULL, failures INTEGER NOT NULL, open_until INTEGER NOT NULL,"
            " reason TEXT NOT NULL, PRIMARY KEY(instance_id, operation))",
            "CREATE TABLE IF NOT EXISTS candidates(candidate_id TEXT PRIMARY KEY, created INTEGER NOT NULL, state TEXT NOT NULL, digest TEXT, record TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS candidate_events(id INTEGER PRIMARY KEY, candidate_id TEXT NOT NULL, state TEXT NOT NULL, reason TEXT, created INTEGER NOT NULL)",
            "CREATE TABLE IF NOT EXISTS experiments(experiment_id TEXT PRIMARY KEY, created INTEGER NOT NULL, record TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS reports(report_id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL, created INTEGER NOT NULL, record TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS recommendations(id TEXT PRIMARY KEY, created INTEGER NOT NULL, capability TEXT, record TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS usage(id TEXT PRIMARY KEY, created INTEGER NOT NULL, capability TEXT, record TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS tombstones(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, ident TEXT NOT NULL, reason TEXT, created INTEGER NOT NULL)",
        )

        def _dump(self, value):
            return json.dumps(value, sort_keys=True, separators=(",", ":"))

        def publish_snapshot(self, record):
            with self.transaction():
                self.connection.execute("INSERT INTO snapshots(created, session, complete, record) VALUES(?,?,1,?)",
                                        (record["created"], record.get("session"), self._dump(record)))

        def latest_snapshot(self):
            row = self.connection.execute("SELECT record FROM snapshots WHERE complete=1 ORDER BY id DESC LIMIT 1").fetchone()
            if row is None:
                return None
            try:
                value = json.loads(row[0])
            except ValueError:
                return None
            return value if isinstance(value, dict) and value.get("schema_version") == SNAPSHOT_SCHEMA else None

        def add_receipts(self, receipts):
            with self.transaction():
                for r in receipts:
                    self.connection.execute("INSERT OR IGNORE INTO receipts(receipt_id, instance_id, observed, session, type, record) VALUES(?,?,?,?,?,?)",
                                            (r["receipt_id"], r["instance_id"], r["observed"], r.get("session"), r["type"], self._dump(r)))

        def receipts(self, instance_ids=None, limit=5000):
            rows = self.connection.execute("SELECT record FROM receipts ORDER BY observed DESC LIMIT ?", (limit,)).fetchall()
            out = []
            for (raw,) in rows:
                try:
                    record = json.loads(raw)
                except ValueError:
                    continue
                if instance_ids is None or record.get("instance_id") in instance_ids:
                    if record.get("receipt_id") == "rc-" + digest({k: v for k, v in record.items() if k != "receipt_id"})[:24]:
                        out.append(record)  # a tampered row no longer names itself and is ignored
            return out

        def breakers(self):
            out = {}
            for instance_id, operation, failures, open_until, reason in self.connection.execute("SELECT instance_id, operation, failures, open_until, reason FROM breakers"):
                out.setdefault(instance_id, {})[operation] = {"failures": failures, "open_until": open_until, "reason": reason}
            return out

        def record_breaker(self, instance_id, operation, success, reason, cooldown, at):
            with self.transaction():
                if success:
                    self.connection.execute("DELETE FROM breakers WHERE instance_id=? AND operation=?", (instance_id, operation))
                    return
                row = self.connection.execute("SELECT failures FROM breakers WHERE instance_id=? AND operation=?", (instance_id, operation)).fetchone()
                failures = (row[0] if row else 0) + 1
                self.connection.execute("INSERT OR REPLACE INTO breakers(instance_id, operation, failures, open_until, reason) VALUES(?,?,?,?,?)",
                                        (instance_id, operation, failures, at + cooldown * min(failures, 8), reason))

        def candidate_state_for(self, content_digest):
            if not content_digest:
                return None
            row = self.connection.execute("SELECT state FROM candidates WHERE digest=? ORDER BY created DESC LIMIT 1", (content_digest,)).fetchone()
            return "quarantined" if row and row[0] not in ("active",) else None

        def put_candidate(self, record, state, reason):
            with self.transaction():
                self.connection.execute("INSERT OR REPLACE INTO candidates(candidate_id, created, state, digest, record) VALUES(?,?,?,?,?)",
                                        (record["candidate_id"], record["created"], state, record.get("skill_md_digest"), self._dump(record)))
                self.connection.execute("INSERT INTO candidate_events(candidate_id, state, reason, created) VALUES(?,?,?,?)",
                                        (record["candidate_id"], state, (reason or "")[:240], now()))

        def candidate(self, candidate_id):
            row = self.connection.execute("SELECT record, state FROM candidates WHERE candidate_id=?", (candidate_id,)).fetchone()
            return dict(json.loads(row[0]), state=row[1]) if row else None

        def candidates(self):
            return [dict(json.loads(r[0]), state=r[1]) for r in self.connection.execute("SELECT record, state FROM candidates ORDER BY created, candidate_id")]

        def candidate_history(self, candidate_id):
            return [{"state": s, "reason": r, "created": c} for s, r, c in self.connection.execute(
                "SELECT state, reason, created FROM candidate_events WHERE candidate_id=? ORDER BY id", (candidate_id,))]

        def put(self, table, key, record, *, capability=None, experiment_id=None):
            with self.transaction():
                if table == "experiments":
                    self.connection.execute("INSERT OR REPLACE INTO experiments(experiment_id, created, record) VALUES(?,?,?)", (key, now(), self._dump(record)))
                elif table == "reports":
                    self.connection.execute("INSERT OR REPLACE INTO reports(report_id, experiment_id, created, record) VALUES(?,?,?,?)",
                                            (key, experiment_id, now(), self._dump(record)))
                elif table in ("recommendations", "usage"):
                    self.connection.execute(f"INSERT OR REPLACE INTO {table}(id, created, capability, record) VALUES(?,?,?,?)",
                                            (key, now(), capability, self._dump(record)))
                else:
                    raise CapabilityError("Unknown store table.")

        def get(self, table, key):
            column = {"experiments": "experiment_id", "reports": "report_id"}.get(table, "id")
            row = self.connection.execute(f"SELECT record FROM {table} WHERE {column}=?", (key,)).fetchone()
            return json.loads(row[0]) if row else None

        def all(self, table, **where):
            query, args = f"SELECT record FROM {table}", []
            if where:
                query += " WHERE " + " AND ".join(f"{k}=?" for k in where)
                args = list(where.values())
            return [json.loads(r[0]) for r in self.connection.execute(query + " ORDER BY created", args)]

        def forget(self, capability):
            """Delete observations about one capability and every derived recommendation that cited it."""
            with self.transaction():
                ids = [r[0] for r in self.connection.execute("SELECT DISTINCT instance_id FROM receipts WHERE instance_id=? OR record LIKE ?",
                                                             (capability, '%"instance_id":"' + capability + '"%'))]
                removed = self.connection.execute("DELETE FROM receipts WHERE instance_id=?", (capability,)).rowcount
                removed += self.connection.execute("DELETE FROM usage WHERE capability=?", (capability,)).rowcount
                derived = self.connection.execute("DELETE FROM recommendations WHERE capability=? OR record LIKE ?",
                                                  (capability, '%' + capability + '%')).rowcount
                self.connection.execute("DELETE FROM breakers WHERE instance_id=?", (capability,))
                self.connection.execute("INSERT INTO tombstones(kind, ident, reason, created) VALUES('capability', ?, 'forgotten', ?)", (capability, now()))
            return {"receipts_and_usage": removed, "recommendations_invalidated": derived, "instances": len(ids)}

        def prune(self, max_age_days, at=None):
            cutoff = (at or now()) - max_age_days * 86400
            with self.transaction():
                receipts = self.connection.execute("DELETE FROM receipts WHERE observed < ?", (cutoff,)).rowcount
                snapshots = self.connection.execute("DELETE FROM snapshots WHERE created < ? AND id NOT IN (SELECT max(id) FROM snapshots)", (cutoff,)).rowcount
                usage = self.connection.execute("DELETE FROM usage WHERE created < ?", (cutoff,)).rowcount
            return {"receipts": receipts, "snapshots": snapshots, "usage": usage}

        def counts(self):
            return {t: self.connection.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                    for t in ("snapshots", "receipts", "breakers", "candidates", "experiments", "reports", "recommendations", "usage", "tombstones")}

    return CapabilityStore


_STORE_CLASS = None


def open_store(directory, *, create=False, readonly=True):
    global _STORE_CLASS
    if _STORE_CLASS is None:
        _STORE_CLASS = _store_class()
    try:
        return _STORE_CLASS(directory, create=create, readonly=readonly)
    except _store_base()["StoreError"] as exc:
        message = str(exc).replace("Repository index", "Capability store").replace("repository index", "capability store")
        raise CapabilityError(message) from None


def store_exists(directory):
    target = Path(directory) / STORE_FILE
    return target.is_symlink() or target.exists()


def compact_snapshot(inventory, settings):
    """What routing reads: bounded per-instance health, never locations, descriptions or evidence bodies."""
    rows = []
    for inst in inventory["instances"]:
        rows.append({"instance_id": inst["instance_id"], "definition_id": inst["definition_id"], "kind": inst["kind"], "name": inst["name"],
                     "display": inst["display"], "qualifier": inst["qualifier"], "eligible": inst["eligible"], "policy": inst["dimensions"]["policy"],
                     "dimensions": inst["dimensions"], "operations": inst["operations"], "operation_status": inst.get("operation_status", {}),
                     "reasons": inst["reasons"], "parent": inst["parent"], "origin": inst["origin"]})
    return {"schema_version": SNAPSHOT_SCHEMA, "created": inventory["created"], "session": inventory["session"], "host": inventory["host"],
            "fingerprints": inventory["fingerprints"], "discovery": inventory["discovery"], "instances": rows,
            "settings_digest": settings_digest(settings)}


# ---------------------------------------------------------------- probes: planner and reviewed adapters


def plan_probes(inventory, settings, *, level=0, allow_process=False, allow_network=False, targets=None, store=None, at=None):
    """Which checks would run, and why each other check is skipped. Missing approval is `skipped`, never a failed connection."""
    at = at if at is not None else now()
    instances = {i["instance_id"]: i for i in inventory["instances"]}
    by_def = inventory["by_definition"]
    breakers = store.breakers() if store is not None else {}
    plan = []
    for probe in settings["probes"]["approved"]:
        ids = [probe["instance"]] if probe["instance"] in instances else by_def.get(probe["instance"], [])
        adapter_level = PROBE_ADAPTERS[probe["adapter"]]
        for ident in ids or [None]:
            inst = instances.get(ident)
            item = {"probe_id": probe["id"], "adapter": probe["adapter"], "level": adapter_level, "instance_id": ident,
                    "name": (inst or {}).get("name") or probe["instance"],
                    "operation": probe.get("operation") or probe["adapter"], "status": "authorized", "reason": "OK"}
            if targets and ident not in targets and probe["instance"] not in targets:
                continue
            if inst is None:
                item.update(status="unsupported", reason="MISSING_REFERENCE")
            elif adapter_level > level:
                item.update(status="skipped", reason="APPROVAL_MISSING", detail=f"requires --deep level {adapter_level}")
            elif inst["dimensions"]["policy"] != "enabled":
                item.update(status="skipped", reason="POLICY_DISABLED")
            elif probe["adapter"] in ("cli.version", "mcp.stdio.enumerate") and not allow_process:
                item.update(status="skipped", reason="APPROVAL_MISSING", detail="process start not requested (--allow-process)")
            elif probe["adapter"] == "http.read" and not allow_network:
                item.update(status="skipped", reason="APPROVAL_MISSING", detail="network access not requested (--allow-network)")
            elif breakers.get(ident, {}).get(item["operation"], {}).get("open_until", 0) > at:
                item.update(status="skipped", reason="CIRCUIT_OPEN", detail="cooling down after recent failures")
            elif probe["adapter"] in ("cli.version", "mcp.stdio.enumerate") and _untrusted_executable(probe["argv"][0], inventory):
                item.update(status="skipped", reason="WORKSPACE_SHADOWED_BINARY", detail="executable inside the project or quarantine is never started")
            item["_probe"] = probe
            plan.append(item)
    unapproved = [i for i in inventory["instances"] if i["kind"] in ("mcp_server", "cli", "api") and not any(p.get("instance_id") == i["instance_id"] for p in plan)]
    for inst in unapproved[:200]:
        plan.append({"probe_id": None, "adapter": None, "level": None, "instance_id": inst["instance_id"], "name": inst["name"], "operation": None, "status": "skipped",
                     "reason": "APPROVAL_MISSING", "detail": "no reviewed probe approved for this capability in the user's settings"})
    return plan


def _untrusted_executable(path, inventory):
    try:
        resolved = Path(path).resolve()
    except OSError:
        return True
    for base in (quarantine_root(),):
        if resolved.is_relative_to(base):
            return True
    project = inventory.get("_project")
    return bool(project and resolved.is_relative_to(Path(project).resolve()))


def _minimal_env(home):
    return {"PATH": "/usr/bin:/bin", "HOME": str(home), "LANG": "C", "LC_ALL": "C"}


def _spawn(argv, cwd, env):
    return subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=cwd, env=env,
                            start_new_session=True, close_fds=True)


def _kill_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    for stream in (process.stdin, process.stdout):
        try:
            if stream is not None:
                stream.close()
        except OSError:
            pass


def probe_cli_version(probe, *, timeout, max_bytes):
    """Level 1: an approved absolute binary with its version flag; argv array, no shell, minimal env, temp cwd, bounded output."""
    argv = probe["argv"]
    if Path(argv[0]).name in PACKAGE_MANAGER_LAUNCHERS:
        return "failure", "PACKAGE_MANAGER_LAUNCHER", {}
    with tempfile.TemporaryDirectory(prefix="dispatcher-probe-") as temp:
        try:
            process = _spawn(argv, temp, _minimal_env(temp))
        except OSError:
            return "failure", "PROCESS_FAILED", {}
        try:
            output, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_group(process)
            return "failure", "TRANSPORT_TIMEOUT", {}
        finally:
            _kill_group(process)
    if len(output) > max_bytes:
        return "failure", "RESPONSE_TOO_LARGE", {}
    if process.returncode != 0:
        return "failure", "PROCESS_FAILED", {}
    match = re.search(rb"\d+\.\d+(?:\.\d+)?", output[:4096])
    return "success", "OK", {"version": match.group(0).decode() if match else None}


def probe_mcp_stdio(probe, *, timeout, max_bytes):
    """Level 2: negotiate MCP over stdio and enumerate tools. Server-initiated requests (sampling, elicitation, roots) are
    refused with an error reply: they never consume model credits, request secrets or trigger further actions."""
    deadline = time.monotonic() + timeout
    counters = {"callbacks_refused": 0, "bytes": 0}
    with tempfile.TemporaryDirectory(prefix="dispatcher-mcp-probe-") as temp:
        try:
            process = _spawn(probe["argv"], temp, _minimal_env(temp))
        except OSError:
            return "failure", "PROCESS_FAILED", {}
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        buffer = b""

        def send(message):
            process.stdin.write((json.dumps(message) + "\n").encode())
            process.stdin.flush()

        def receive(ident):
            nonlocal buffer
            while True:
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        message = json.loads(line)
                    except ValueError:
                        raise _ProbeFailure("MALFORMED_RESPONSE")
                    if not isinstance(message, dict):
                        raise _ProbeFailure("MALFORMED_RESPONSE")
                    if "method" in message and "id" in message:
                        counters["callbacks_refused"] += 1
                        send({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "not supported by the health adapter"}})
                        continue
                    if message.get("id") == ident:
                        return message
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _ProbeFailure("TRANSPORT_TIMEOUT")
                if not selector.select(timeout=remaining):
                    raise _ProbeFailure("TRANSPORT_TIMEOUT")
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    raise _ProbeFailure("SERVICE_UNAVAILABLE")
                counters["bytes"] += len(chunk)
                if counters["bytes"] > max_bytes:
                    raise _ProbeFailure("RESPONSE_TOO_LARGE")
                buffer += chunk

        try:
            send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": SUPPORTED_MCP_VERSIONS[0], "capabilities": {},
                "clientInfo": {"name": "agent-dispatcher-health", "version": "1"}}})
            reply = receive(1)
            if "error" in reply:
                return "failure", "VERSION_INCOMPATIBLE", counters
            result = reply.get("result") or {}
            version = result.get("protocolVersion")
            if version not in SUPPORTED_MCP_VERSIONS:
                return "failure", "VERSION_INCOMPATIBLE", dict(counters, negotiated=clean(str(version), 20))
            capabilities = result.get("capabilities") or {}
            send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            details = dict(counters, negotiated=version, protocol_capabilities=sorted(k for k in capabilities if k in
                                                                                     ("tools", "resources", "prompts", "logging", "completions")))
            if "tools" not in capabilities:
                details["tools"] = 0
                return "success", "OK", details  # zero tools is legitimate when other capabilities are offered
            names, cursor = [], None
            for page in range(5):
                send({"jsonrpc": "2.0", "id": 2 + page, "method": "tools/list", "params": {"cursor": cursor} if cursor else {}})
                listing = receive(2 + page)
                if "error" in listing:
                    return "failure", "SCHEMA_CHANGED", details
                tools = (listing.get("result") or {}).get("tools")
                if not isinstance(tools, list):
                    return "failure", "MALFORMED_RESPONSE", details
                names += [clean(str(t.get("name")), 80) for t in tools if isinstance(t, dict)]
                cursor = (listing.get("result") or {}).get("nextCursor")
                if not cursor:
                    break
            details.update(tools=len(names), schema_fingerprint=digest(sorted(names))[:16], callbacks_refused=counters["callbacks_refused"])
            return "success", "OK", details
        except _ProbeFailure as failure:
            return "failure", failure.reason, counters
        except (OSError, ValueError):
            return "failure", "PROCESS_FAILED", counters
        finally:
            selector.close()
            _kill_group(process)


class _ProbeFailure(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class _NoRedirect(__import__("urllib.request").request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def validate_destination(url, *, local_targets=(), resolver=None):
    """Exact-authority check plus address screening: untrusted input can never steer a probe to localhost, link-local cloud
    metadata or a private network unless that authority is on the user's explicit local-target list."""
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname or parts.username or parts.password:
        raise _ProbeFailure("DESTINATION_REFUSED")
    authority = parts.hostname + (f":{parts.port}" if parts.port else "")
    local = authority in local_targets or parts.hostname in local_targets
    if parts.scheme == "http" and not local:
        raise _ProbeFailure("DESTINATION_REFUSED")
    resolver = resolver or (lambda host: [info[4][0] for info in socket.getaddrinfo(host, None)])
    try:
        addresses = resolver(parts.hostname)
    except OSError:
        raise _ProbeFailure("SERVICE_UNAVAILABLE") from None
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified) and not local:
            raise _ProbeFailure("DESTINATION_REFUSED")
    return parts


def probe_http_read(probe, *, timeout, max_bytes, local_targets=(), opener=None, resolver=None, environ=None):
    """Level 3: one reviewed read-only GET to an exact authority. Redirects are refused (never followed with credentials);
    the response body is measured and discarded, never persisted. A GET can still create access logs and consume quota."""
    import urllib.error
    import urllib.request
    environ = os.environ if environ is None else environ
    try:
        validate_destination(probe["url"], local_targets=tuple(local_targets) if probe.get("local_target") else (), resolver=resolver)
    except _ProbeFailure as failure:
        return "failure", failure.reason, {}
    headers = {"User-Agent": "agent-dispatcher-health/1", "Accept": "application/json"}
    if probe.get("credential_env"):
        token = environ.get(probe["credential_env"])
        if not token:
            return "skipped", "CREDENTIAL_REFERENCE_ABSENT", {}
        headers["Authorization"] = "Bearer " + token  # stays inside this request; never logged, stored or returned
    request = urllib.request.Request(probe["url"], headers=headers, method="GET")
    opener = opener or urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            size = len(response.read(max_bytes + 1))
    except urllib.error.HTTPError as error:
        status, size = error.code, 0
    except (TimeoutError, socket.timeout):
        return "failure", "TRANSPORT_TIMEOUT", {}
    except (urllib.error.URLError, OSError):
        return "failure", "SERVICE_UNAVAILABLE", {}
    if 300 <= status < 400:
        return "failure", "REDIRECT_REFUSED", {"status": status}
    if size > max_bytes:
        return "failure", "RESPONSE_TOO_LARGE", {"status": status}
    reason = {401: "AUTHENTICATION_REQUIRED", 403: "PERMISSION_DENIED", 429: "RATE_LIMITED"}.get(status)
    if reason is None and status >= 500:
        reason = "SERVICE_UNAVAILABLE"
    if reason is None and status >= 400:
        reason = "SCHEMA_CHANGED"
    return ("failure", reason, {"status": status}) if reason else ("success", "OK", {"status": status, "bytes": size})


ADAPTER_FUNCTIONS = {"cli.version": probe_cli_version, "mcp.stdio.enumerate": probe_mcp_stdio, "http.read": probe_http_read}


def run_probes(plan, settings, *, session, store=None, adapters=None, at=None, sleep=time.sleep):
    """Execute only authorized plan items: bounded concurrency, per-probe timeout, total deadline, bounded retries with backoff
    for transient failures, and a per-instance circuit breaker. A rate limit or timeout never blacklists a capability."""
    adapters = adapters or ADAPTER_FUNCTIONS
    limits = settings["probes"]
    started = time.monotonic()
    receipts, results = [], []
    authorized = [p for p in plan if p["status"] == "authorized"]

    def one(item):
        probe = item["_probe"]
        attempts = 0
        while True:
            attempts += 1
            remaining = limits["total_deadline_seconds"] - (time.monotonic() - started)
            if remaining <= 0:
                return item, "skipped", "TRANSPORT_TIMEOUT", {"detail": "total deadline reached"}, 0
            timeout = min(limits["probe_timeout_seconds"], remaining)
            began = time.monotonic()
            kwargs = {"timeout": timeout, "max_bytes": limits["max_response_bytes"]}
            if probe["adapter"] == "http.read":
                kwargs["local_targets"] = limits["local_targets"]
            outcome, reason, details = adapters[probe["adapter"]](probe, **kwargs)
            elapsed = int((time.monotonic() - began) * 1000)
            if outcome == "failure" and reason in TRANSIENT and attempts <= limits["max_retries"]:
                sleep(min(2 ** attempts, 5))
                continue
            return item, outcome, reason, details, elapsed

    with ThreadPoolExecutor(max_workers=limits["max_concurrency"]) as pool:
        futures = [pool.submit(one, item) for item in authorized]
        for future in futures:
            try:
                item, outcome, reason, details, elapsed = future.result(timeout=limits["total_deadline_seconds"] + limits["probe_timeout_seconds"])
            except FutureTimeout:
                continue
            kind = {"cli.version": "approved_read_probe", "mcp.stdio.enumerate": "tool_enumeration", "http.read": "approved_read_probe"}[item["adapter"]]
            receipt = make_receipt(item["instance_id"], source="trusted_adapter", type=kind, operation=item["operation"],
                                   outcome=outcome if outcome in OUTCOMES else "failure", reason=reason if reason in REASONS else "PROCESS_FAILED",
                                   session=session, elapsed_ms=elapsed, ttl=settings["freshness"]["operational_minutes"] * 60,
                                   fingerprints={k: v for k, v in details.items() if k in ("schema_fingerprint", "negotiated")},
                                   explanation=f"{item['adapter']} via reviewed adapter")
            receipts.append(receipt)
            results.append({"probe_id": item["probe_id"], "instance_id": item["instance_id"], "adapter": item["adapter"], "outcome": outcome,
                            "reason": reason, "elapsed_ms": elapsed, "details": {k: v for k, v in details.items() if k != "bytes"}})
            if store is not None:
                store.record_breaker(item["instance_id"], item["operation"], outcome == "success", reason, limits["cooldown_seconds"], at or now())
    if store is not None and receipts:
        store.add_receipts(receipts)
    return results, receipts


# ---------------------------------------------------------------- reports


def health_report(inventory, *, kind=None, capability=None, probe_plan=None, probe_results=None, mode="passive"):
    rows = inventory["instances"]
    if kind:
        wanted = {"skill": ("skill",), "mcp": ("mcp_server", "mcp_tool"), "plugin": ("plugin",), "tool": ("native_tool", "mcp_tool"),
                  "cli": ("cli",), "api": ("api",), "role": ("role",), "recipe": ("recipe",)}.get(kind)
        if wanted is None:
            raise CapabilityError("--type must be skill, mcp, plugin, tool, cli, api, role or recipe.")
        rows = [r for r in rows if r["kind"] in wanted]
    if capability:
        rows = [r for r in rows if capability in (r["instance_id"], r["definition_id"], r["name"])]
        if not rows:
            raise CapabilityError("No capability instance matches that id.")
    independent = [r for r in rows if not r["parent"]]
    counts = {}
    for r in independent:
        counts[r["display"]] = counts.get(r["display"], 0) + 1
    entries = []
    for r in sorted(rows, key=lambda r: (KINDS.index(r["kind"]) if r["kind"] in KINDS else 99, r["name"], r["instance_id"])):
        entry = {k: r.get(k) for k in ("instance_id", "definition_id", "kind", "name", "origin", "scope", "display", "qualifier", "badges", "eligible",
                                       "dimensions", "reasons", "parent", "children", "operation_status", "notes", "dependency_status", "validation",
                                       "components", "child_summary", "shadowed_by", "evidence", "protocol_capabilities")
                 if r.get(k) not in (None, [], {})}
        entries.append(entry)
    return {"schema_version": 2, "read_only": probe_results is None, "mode": mode, "host": inventory["host"], "session": inventory["session"] is not None,
            "discovery": inventory["discovery"], "coverage": {
                "unique_instances": len(independent), "child_components": len(rows) - len(independent),
                "policy_disabled": sum(1 for r in independent if r["dimensions"]["policy"] != "enabled"),
                "catalog_only_definitions": len(inventory["catalog_only"]), "display_counts": counts},
            "entries": entries, "probe_plan": [{k: v for k, v in p.items() if not k.startswith("_")} for p in probe_plan or []],
            "probe_results": probe_results or [], "issues": inventory["issues"],
            "doctor": {"counts": inventory["doctor"]["counts"], "setup": [e for e in inventory["doctor"]["entries"] if e["category"] == "setup"]},
            "limits": ["Catalog membership is not installation; installation is not exposure; exposure is not a tested connection.",
                       "Functional evidence covers the named operations only. Authentication is not authorization; availability is not permission.",
                       "Historical observations are not current-session proof; a new session starts untested.",
                       "Supplied snapshots are caller observations, not probes; only reviewed adapters mint trusted receipts.",
                       "Static validation is not security assurance. No setup, login, installation or permission change was made."]
            + ([] if mode != "passive" else ["Mode passive: no network requests, process starts or model calls were made."])}


def render(report, explain=False):
    lines = ["Agent Dispatcher Capability Health", f"Host: {report['host']} / {'current session' if report['session'] else 'no session identity supplied'}",
             "Mode: " + ("passive; no external probes run" if report["mode"] == "passive" else report["mode"]),
             "Discovery: " + ", ".join(f"{k} {v}" for k, v in sorted(report["discovery"].items()))]
    groups = {}
    for entry in report["entries"]:
        if entry.get("parent") and not explain:
            continue
        groups.setdefault(entry["kind"], []).append(entry)
    titles = {"skill": "Skills", "mcp_server": "MCP instances", "mcp_tool": "MCP tools", "plugin": "Plugins", "native_tool": "Native tools",
              "cli": "CLIs", "api": "APIs", "role": "Roles", "recipe": "Recipes"}
    policy = []
    for kind in KINDS:
        if kind not in groups:
            continue
        lines += ["", titles[kind]]
        for e in groups[kind]:
            if e["dimensions"]["policy"] != "enabled":
                policy.append(e)
                continue
            badge = (" [" + ",".join(e["badges"]) + "]") if e.get("badges") else ""
            lines.append(f"  {e['display']:<14}{e['name'][:40]:<42}{e['qualifier']}{badge}")
            if explain:
                lines.append(f"      id {e['instance_id']} def {e['definition_id']}; reasons: {', '.join(e.get('reasons', [])) or 'none'}")
                lines.append("      " + ", ".join(f"{k}={v}" for k, v in e["dimensions"].items()))
                if e.get("child_summary") or e.get("components"):
                    lines.append("      components: " + ", ".join(f"{k} {v}" for k, v in (e.get("components") or {}).items() if v)
                                 + ("; component states " + ", ".join(f"{k} {v}" for k, v in e["child_summary"].items()) if e.get("child_summary") else ""))
                for ev in e.get("evidence", [])[:5]:
                    lines.append(f"      evidence {ev['receipt_id']} {ev['type']} {ev['operation']} {ev['outcome']} {ev['reason']} ({ev['state']}, {ev['source']})")
    if policy:
        lines += ["", "Policy"]
        for e in policy:
            lines.append(f"  {POLICY_BADGES.get(e['dimensions']['policy'], e['dimensions']['policy']).ljust(14)}{e['name'][:40]:<42}"
                         f"technical state {e['display']}; no setup recommended")
    cov = report["coverage"]
    lines += ["", "Coverage", f"  {cov['unique_instances']} unique capability instances; {cov['child_components']} child components counted under their parent;"
              f" {cov['policy_disabled']} policy-restricted; {cov['catalog_only_definitions']} catalog-only definitions (not installation evidence)"]
    if report["probe_plan"]:
        lines += ["", "Probe plan"]
        for p in report["probe_plan"][:50]:
            lines.append(f"  {p['status']:<12}{(p['adapter'] or '-'):<22}{(p.get('name') or p['instance_id'] or '-')[:26]:<28}{p['reason']} {p.get('detail', '')}")
    for issue in report["issues"]:
        lines.append("Attention: " + issue)
    lines += [""] + ["Note: " + limit for limit in report["limits"]]
    return "\n".join(lines)


def export(inventory, *, detailed=False):
    """Redacted by default: states and opaque ids only. `detailed` adds definitions and reasons, still no locations or evidence bodies."""
    rows = []
    for inst in inventory["instances"]:
        row = {"instance_id": inst["instance_id"], "kind": inst["kind"], "display": inst["display"], "policy": inst["dimensions"]["policy"]}
        if detailed:
            row.update(definition_id=inst["definition_id"], name=inst["name"], qualifier=inst["qualifier"], reasons=inst["reasons"], dimensions=inst["dimensions"])
        rows.append(row)
    return {"schema_version": 1, "redacted": not detailed, "host": inventory["host"], "fields": sorted(rows[0]) if rows else [], "instances": rows}


# ---------------------------------------------------------------- checkup: every MCP, skill and plugin, grouped by certainty

CHECKUP_TYPES = {"mcp": ("mcp_server",), "skill": ("skill",), "plugin": ("plugin",), "tool": ("native_tool", "mcp_tool"), "cli": ("cli",)}
CHECKUP_BUCKETS = (("working", "WORKING — confirmed"), ("attention", "NOT WORKING — needs attention"),
                   ("unsure", "UNSURE — not established either way"), ("not_in_use", "NOT IN USE — turned off or superseded"))
KIND_TITLES = {"mcp_server": "MCP servers", "mcp_tool": "MCP tools", "skill": "Skills", "plugin": "Plugins", "native_tool": "Native tools", "cli": "CLIs"}
FIX_BY_REASON = {
    "INVALID_METADATA": "Fix the SKILL.md frontmatter: `name` in lowercase-hyphen form and a non-empty `description`.",
    "SYMLINK_ESCAPE": "A link in the package points outside it; replace it with a real file inside the package.",
    "MISSING_REFERENCE": "A referenced file is missing; restore it or remove the reference.",
    "WORKSPACE_SHADOWED_BINARY": "A workspace PATH entry would run a project-local binary under this name; remove that PATH entry.",
    "VERSION_INCOMPATIBLE": "Update the server or client so they share a supported protocol version.",
    "DEPENDENCY_CYCLE": "Break the dependency cycle in the package's manifest.json.",
    "MISSING_REQUIRED_DEPENDENCY": "Install or connect the required dependency named above, only if a task needs it.",
}


def _checkup_bucket(entry, session_skills_reported=False):
    if entry["dimensions"]["policy"] != "enabled" or entry.get("shadowed_by"):
        return "not_in_use"
    if entry.get("duplicate_unresolved"):
        return "unsure"
    if (entry["display"] == "HEALTHY" and entry["kind"] == "skill" and session_skills_reported and entry["origin"] in ("local_scan", "plugin")
            and entry["dimensions"]["exposure"] != "callable"):
        return "unsure"  # a valid file the host did not list this session: present, but not shown to be loadable
    return {"HEALTHY": "working", "UNTESTED": "unsure"}.get(entry["display"], "attention")


def _checkup_source(entry, by_id):
    if entry.get("provided_by"):
        return entry["provided_by"]
    if entry["origin"] == "plugin" and entry.get("parent") in by_id:
        return "plugin " + by_id[entry["parent"]]["name"].split(" ")[0]
    if entry["origin"] == "host_evidence" and entry["kind"] == "skill":
        return "host (not on this disk)"
    return {"local_scan": {"user": "~/.claude/skills" , "project": "project skills", "system": "system skills"}.get(entry["scope"], "on disk"),
            "host_evidence": "listed by the host", "config": "configured in settings", "plugin": "plugin cache", "bundled": "bundled",
            "path_scan": "PATH", "approved_cli": "approved CLI", "api_reference": "API reference"}.get(entry["origin"], entry["origin"])


def _checkup_basis(entry):
    """Why the item is where it is, in words; and the smallest next step for anything not confirmed working."""
    d, q = entry["dimensions"], entry["qualifier"]
    worked = sorted(op for op, st in (entry.get("operation_status") or {}).items() if st["outcome"] == "success")
    if entry.get("shadowed_by"):
        if entry["kind"] == "plugin" or entry.get("parent"):
            return "cached copy the install record does not use", "Nothing to do; an old cache copy, safe to leave or tidy up."
        return "a duplicate; the host's precedence picks the other copy", "Nothing to do unless you meant to use this copy; rename or remove the duplicate."
    if entry.get("duplicate_unresolved"):
        return "another cached version exists; which one loads is not established", "Check /plugin in Claude to see which version is installed."
    if d["policy"] != "enabled":
        return f"{d['policy']} by settings or policy", "Left alone; re-enable only if you want it back."
    display = entry["display"]
    if display == "HEALTHY":
        if worked:
            return "used successfully this session (" + ", ".join(worked)[:60] + ")", None
        if entry["kind"] == "skill":
            parts = (["valid file"] if d["configuration"] == "valid" else []) + \
                    (["exposed this session"] if d["exposure"] == "callable" else ["not listed by the host this session"] if session_reported(entry) else []) + \
                    (["contents not checked"] if d["configuration"] == "unknown" else [])
            step = None if d["exposure"] == "callable" or not session_reported(entry) else \
                "Present and valid on disk, but this session did not list it; check the host's skill list or restart the session."
            return " · ".join(parts), step
        if entry["kind"] == "native_tool":
            return "exposed this session", None
        return q, None
    if display == "AUTH_REQUIRED":
        return q, _sign_in_step(entry, entry["_by_id"], entry["_plugins"])
    if display == "DEGRADED":
        if "authentication" in q:
            return q, "Sign in to its connector (in Claude Code run /mcp, select it, choose Authenticate); the rest already works."
        if "optional dependency" in q:
            return q, "Works as guidance now; install the optional tool only if a task needs it."
        return q, "Use the working operations; investigate the failing ones: " + ", ".join(entry.get("reasons", []))[:80]
    if display in ("MISCONFIGURED", "UNAVAILABLE"):
        fix = next((FIX_BY_REASON[r] for r in entry.get("reasons", []) if r in FIX_BY_REASON), None)
        if display == "UNAVAILABLE" and entry["kind"] == "cli":
            fix = "Not found on PATH; install it only if a task needs it."
        return q, fix or "Check that it is installed and running; last reasons: " + (", ".join(entry.get("reasons", [])) or "none recorded")
    # UNTESTED: say exactly what is missing.
    if d["freshness"] == "stale":
        return "worked in an earlier session only", "Use it once in this session (a read-only call) to confirm it still works."
    if d["exposure"] == "deferred":
        return "listed by the host but not loaded yet", "Nothing to do; it loads on first use, and that use will confirm it."
    if d["exposure"] == "callable" and entry["kind"] in ("mcp_server", "mcp_tool"):
        return "callable, but not used this session", "One read-only call (for example a list or status tool) confirms the connection."
    if entry["kind"] == "cli":
        return "found on PATH, never run", "Approve a version probe in your capability settings, or just use it once in a task."
    if entry["kind"] == "plugin":
        return q, "Use it once in a task to confirm it; nothing here can inspect its components."
    if d["exposure"] == "unknown" and entry["kind"] == "mcp_server":
        return "configured, but this session did not report it", "Include it in the session snapshot, or open /mcp to see whether it is connected."
    return q, "Supply current-session evidence for it (the session snapshot), or use it once."


def session_reported(entry):
    return bool(entry.get("_session_skills"))


def checkup(inventory, *, types=("mcp", "skill", "plugin"), include_bundled=False):
    """Every MCP server, skill and plugin, one per line, in four groups: confirmed working, needs attention, unsure, not in use.

    Certainty comes from evidence only: a successful use this session, host exposure, or a readable, valid file. Nothing is
    probed or called to fill a gap; an unsure item says what would settle it."""
    kinds = tuple(k for t in types for k in CHECKUP_TYPES[t])
    by_id = {i["instance_id"]: i for i in inventory["instances"]}
    plugins = {i["name"].split(" ")[0] for i in inventory["instances"] if i["kind"] == "plugin" and not i.get("shadowed_by")}
    buckets = {name: [] for name, _ in CHECKUP_BUCKETS}
    bundled = {"working": 0, "other": 0}
    session_skills = any(i["origin"] == "host_evidence" and i["kind"] == "skill" or (i["kind"] == "skill" and i["dimensions"]["exposure"] == "callable")
                         for i in inventory["instances"])
    for entry in inventory["instances"]:
        if entry["kind"] not in kinds:
            continue
        if entry["origin"] == "bundled" and not include_bundled:
            bundled["working" if entry["display"] == "HEALTHY" else "other"] += 1
            continue
        entry = dict(entry, _session_skills=session_skills and entry["origin"] in ("local_scan", "plugin"), _by_id=by_id, _plugins=plugins)
        bucket = _checkup_bucket(entry, session_skills)
        basis, step = _checkup_basis(entry)
        state = entry["display"]
        if bucket == "not_in_use":
            state = ("OLD COPY" if entry["kind"] == "plugin" or entry.get("parent") else "DUPLICATE") if entry.get("shadowed_by") else \
                POLICY_BADGES.get(entry["dimensions"]["policy"], "OFF")
        shown = ("plugin:" + entry["name"]) if entry["kind"] == "mcp_server" and entry["origin"] == "plugin" else entry["name"]
        buckets[bucket].append({"name": shown, "kind": entry["kind"], "state": state, "source": _checkup_source(entry, by_id),
                                "why": basis, "next_step": step, "instance_id": entry["instance_id"],
                                "badges": entry.get("badges", [])})
    for rows in buckets.values():
        rows.sort(key=lambda r: (KINDS.index(r["kind"]) if r["kind"] in KINDS else 99, r["next_step"] or "", r["name"].lower()))
    counts = {name: {KIND_TITLES[k]: sum(1 for r in rows if r["kind"] == k) for k in kinds if any(r["kind"] == k for r in rows)}
              for name, rows in buckets.items()}
    return {"schema_version": 1, "host": inventory["host"], "session": inventory["session"] is not None, "discovery": inventory["discovery"],
            "types": list(types), "buckets": buckets, "counts": counts, "bundled_guides": None if include_bundled else bundled,
            "basis": "Evidence only: successful use this session, host exposure, or a readable valid file. Nothing was called, probed or installed."}


def render_checkup(report):
    lines = ["Capability checkup — " + report["host"] + (" · current session" if report["session"] else " · no session snapshot (disk only)"),
             "Discovery: " + ", ".join(f"{k} {v}" for k, v in sorted(report["discovery"].items())) + ".  " + report["basis"]]
    width = min(max([len(r["name"]) for rows in report["buckets"].values() for r in rows] + [10]), 48)
    for bucket, title in CHECKUP_BUCKETS:
        rows = report["buckets"][bucket]
        lines += ["", f"{title} ({len(rows)})"]
        if not rows:
            lines.append("  (none)")
            continue
        for kind in KINDS:
            group = [r for r in rows if r["kind"] == kind]
            if not group:
                continue
            lines.append(f"  {KIND_TITLES.get(kind, kind)} ({len(group)})")
            current_step = object()
            for row in group:
                if bucket != "working" and row["next_step"] != current_step:
                    current_step = row["next_step"]
                    lines.append(f"    → {current_step}")
                indent = "      " if bucket != "working" else "    "
                state = "" if bucket == "working" else f"{row['state']:<14}"
                lines.append(f"{indent}{row['name'][:width]:<{width}}  {state}{row['why'][:110]}  [{row['source']}]")
    if report.get("bundled_guides"):
        b = report["bundled_guides"]
        lines += ["", f"Bundled dispatcher guides: {b['working']} working, {b['other']} other (not host skills; add --include-bundled to list them)."]
    totals = {bucket: len(rows) for bucket, rows in report["buckets"].items()}
    lines += ["", "Totals: " + ", ".join(f"{title.split(' —')[0].lower()} {totals[b]}" for b, title in CHECKUP_BUCKETS),
              "Unsure is not broken: it means no evidence either way yet. Working means evidence exists for what is named, not for every operation."]
    return "\n".join(lines)


# ---------------------------------------------------------------- setup: installed MCP servers and plugins that are not set up yet

SETUP_ACTIONS = (
    ("sign_in", "Sign in"),
    ("install_program", "Install a missing program"),
    ("set_variable", "Set an environment variable"),
    ("enable", "Enable the plugin"),
    ("fix", "Fix a broken install or configuration"),
    ("reconnect", "Reconnect a server that is failing"),
)


LOCAL_SIGN_IN = "In an interactive Claude Code session run /mcp, select the server, choose Authenticate, and finish the sign-in in the browser."
HOSTED_SIGN_IN = ("Connect each service in Claude's Settings → Connectors (claude.ai or the desktop app), or run /mcp in an interactive "
                  "Claude Code session and choose Authenticate. Organization connectors may need an admin to enable them first.")


def _sign_in_step(entry, by_id, plugins):
    """Local plugin or configured server: /mcp. A connector whose plugin is not on this disk: Settings → Connectors (or /mcp)."""
    parent = by_id.get(entry.get("parent"))
    plugin_name = entry["name"].split(":")[1] if entry["name"].startswith("plugin:") and entry["name"].count(":") >= 2 else None
    local = parent is not None or plugin_name in plugins or entry["origin"] == "config"
    return LOCAL_SIGN_IN if local else HOSTED_SIGN_IN


def setup_report(inventory):
    """Every installed MCP server and plugin that is not set up yet, grouped by the action that finishes it.

    "Installed" means the host listed it this session, a settings file configures it, or the plugin cache holds its enabled
    install. Catalog suggestions that are not installed are not listed here (that is `doctor setup`). Explicitly disabled
    items are left alone. Checks read files, PATH and environment-variable names only: nothing is started, called or changed."""
    by_id = {i["instance_id"]: i for i in inventory["instances"]}
    plugins = {i["name"].split(" ")[0]: i for i in inventory["instances"] if i["kind"] == "plugin" and not i.get("shadowed_by")}
    items, left_alone, seen = [], [], set()

    def add(action, entry, name, detail, step, unlocks=None):
        key = (action, name)
        if key not in seen:
            seen.add(key)
            items.append({"action": action, "name": name, "kind": entry["kind"], "instance_id": entry["instance_id"], "detail": detail,
                          "step": step, "unlocks": unlocks})

    for entry in inventory["instances"]:
        if entry.get("shadowed_by") or entry["origin"] == "bundled" or entry["kind"] not in ("mcp_server", "plugin"):
            continue
        if entry["dimensions"]["policy"] != "enabled":
            left_alone.append({"name": entry["name"], "kind": entry["kind"], "why": entry["dimensions"]["policy"] + " by you or policy; not suggested"})
            continue
        parent = by_id.get(entry.get("parent"))
        plugin_name = (parent["name"].split(" ")[0] if parent else
                       entry["name"].split(":")[1] if entry["name"].startswith("plugin:") and entry["name"].count(":") >= 2 else None)
        if entry["kind"] == "mcp_server":
            requirement = entry.get("requirement") or {}
            if entry["dimensions"]["authentication"] == "required":
                endpoint = requirement.get("endpoint")
                service = entry["name"].split(":")[-1]
                step = _sign_in_step(entry, by_id, plugins)
                add("sign_in", entry, ("plugin:" + entry["name"]) if parent else entry["name"],
                    f"sign in to {service}" + (f" ({endpoint})" if endpoint else "") + (f" · plugin {plugin_name}" if plugin_name else ""),
                    step, unlocks=f"plugin {plugin_name}'s connector" if plugin_name else None)
                continue
            if requirement.get("program") and not requirement.get("program_found"):
                hint = requirement.get("program_hint")
                add("install_program", entry, entry["name"], f"starts with `{requirement['program']}`, which is not on PATH",
                    f"Install {hint or 'the program that provides `' + requirement['program'] + '`'}, make sure it is on PATH, then restart Claude Code.")
            if requirement.get("env_missing"):
                add("set_variable", entry, entry["name"], "needs " + ", ".join(requirement["env_missing"]) + " (not set in this environment)",
                    "Set " + " and ".join(requirement["env_missing"]) + " where Claude Code is launched (shell profile or the plugin's documented settings), then restart.")
            if entry["display"] in ("UNAVAILABLE", "MISCONFIGURED") and not requirement.get("program"):
                add("reconnect", entry, entry["name"], entry["qualifier"],
                    "Run /mcp to see the server's error, fix its command or URL in settings, then reconnect.")
            continue
        # plugins
        if entry["dimensions"]["configuration"] == "invalid":
            add("fix", entry, entry["name"], "plugin manifest is malformed", "Reinstall the plugin: /plugin → uninstall, then install it again.")
        if entry.get("enable_state") is None and entry.get("install_record") is True:
            add("enable", entry, entry["name"], "installed but not turned on in settings", "Run /plugin, select it and enable it (or add it to enabledPlugins).")
        for requirement in entry.get("requirements") or []:
            if requirement["kind"] == "lsp" and requirement.get("program") and not requirement["program_found"]:
                hint = requirement.get("program_hint")
                add("install_program", entry, entry["name"], f"language server `{requirement['program']}` is not on PATH",
                    f"Install {hint or 'the program that provides `' + requirement['program'] + '`'} so `{requirement['program']}` is on PATH, then restart Claude Code.")
            if requirement["kind"] == "lsp" and requirement.get("env_missing"):
                add("set_variable", entry, entry["name"], "language server needs " + ", ".join(requirement["env_missing"]),
                    "Set " + " and ".join(requirement["env_missing"]) + " where Claude Code is launched, then restart.")
    ok = [i["name"] for i in inventory["instances"] if i["kind"] in ("mcp_server", "plugin") and not i.get("shadowed_by")
          and i["dimensions"]["policy"] == "enabled" and i["instance_id"] not in {x["instance_id"] for x in items}]
    counts = {action: sum(1 for i in items if i["action"] == action) for action, _ in SETUP_ACTIONS}
    return {"schema_version": 1, "host": inventory["host"], "session": inventory["session"] is not None, "discovery": inventory["discovery"],
            "items": items, "counts": counts, "total": len(items), "already_set_up": len(ok), "left_alone": left_alone,
            "checks": ["sign-in state reported by this session", "programs on this process's PATH", "environment-variable names in server definitions",
                       "plugin enabled state and install record", "plugin manifests"],
            "limits": ["PATH and environment are this process's; Claude Code launched from another shell may differ.",
                       "Sign-in state comes from the session snapshot; servers this session did not report cannot be judged.",
                       "Nothing was started, called, installed, enabled or changed."]}


def render_setup(report):
    lines = [f"Setup needed — {report['host']}" + (" · current session" if report["session"] else " · no session snapshot (sign-in state unknown)"),
             f"{report['total']} installed MCP server(s) and plugin(s) are not fully set up; {report['already_set_up']} look set up. Nothing was changed."]
    number = 0
    for action, title in SETUP_ACTIONS:
        rows = [i for i in report["items"] if i["action"] == action]
        if not rows:
            continue
        number += 1
        lines += ["", f"{number}. {title} ({len(rows)})"]
        width = min(max(len(r["name"]) for r in rows), 46)
        for step in dict.fromkeys(r["step"] for r in rows):
            group = [r for r in rows if r["step"] == step]
            lines.append(f"   → {step}")
            for row in group:
                extra = f"  (unlocks {row['unlocks']})" if row["unlocks"] and row["kind"] == "mcp_server" and row["unlocks"].startswith("plugin") and "·" not in row["detail"] else ""
                lines.append(f"     {row['name']:<{width}}  {row['detail']}{extra}")
    if not report["items"]:
        lines += ["", "Everything installed looks set up."]
    clean_checks = [title for action, title in SETUP_ACTIONS if not report["counts"][action]]
    lines += ["", "Checked with nothing to do: " + ", ".join(t.lower() for t in clean_checks) + "." if clean_checks else ""]
    if report["left_alone"]:
        lines.append("Left alone (disabled by you): " + ", ".join(r["name"] for r in report["left_alone"]))
    lines += [""] + ["Note: " + limit for limit in report["limits"]]
    return "\n".join(line for line in lines if line is not None)


# ---------------------------------------------------------------- command line


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        print(json.dumps({"error": "Invalid arguments; see --help."}), file=sys.stderr)
        raise SystemExit(2)


def _common(parser):
    parser.add_argument("--pack", type=Path)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--host", choices=("claude", "codex"))
    parser.add_argument("--config-dir", type=Path)
    parser.add_argument("--evidence", help="host observation snapshot (v2) or doctor evidence (v1): inline JSON, file, or -")
    parser.add_argument("--evidence-source", choices=SUPPLIED_SOURCES, default="model_snapshot")
    parser.add_argument("--settings", type=Path, help="capability settings file (default: the user's own, outside the project)")
    parser.add_argument("--json", action="store_true")


def inventory_for(args, *, with_store=False):
    settings = load_settings(args.settings, project=args.project)
    snapshot = read_snapshot(args.evidence, supplied_as=args.evidence_source)
    host = args.host or (snapshot.get("host") or {}).get("name")
    directory = host_directory(host, args.config_dir)
    store = open_store(directory, readonly=True) if with_store and store_exists(directory) else None
    try:
        inventory = build_inventory(args.pack, args.project, args.host, args.config_dir, snapshot, settings, store=store)
    finally:
        if store is not None:
            store.close()
    inventory["_project"] = str(Path(args.project).resolve())
    return inventory, settings, snapshot


def main(argv=None):
    parser = _Parser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                     epilog="Exit codes: 0 completed (including findings), 2 malformed input or internal failure, 3 a requested --require gate was not met.")
    commands = parser.add_subparsers(dest="command", required=True)
    h = commands.add_parser("health", help="scoped health of every capability instance (passive by default)")
    _common(h)
    h.add_argument("--type")
    h.add_argument("--capability")
    h.add_argument("--explain", action="store_true")
    h.add_argument("--deep", type=int, nargs="?", const=3, default=0, choices=(0, 1, 2, 3), help="probe level to plan (and run with --refresh)")
    h.add_argument("--probe-plan", action="store_true", help="show the plan without running anything")
    h.add_argument("--refresh", action="store_true", help="persist this snapshot and run probes the plan authorizes")
    h.add_argument("--allow-process", action="store_true")
    h.add_argument("--allow-network", action="store_true")
    h.add_argument("--require", choices=("healthy", "usable"), help="readiness gate for automation, applied to --capability or every enabled instance")
    for name in ("capabilities", "mcps", "plugins"):
        p = commands.add_parser(name)
        _common(p)
        if name == "capabilities":
            p.add_argument("action", nargs="?", choices=("list", "explain"), default="list")
            p.add_argument("target", nargs="?")
    c = commands.add_parser("checkup", help="every MCP, skill and plugin, one per line: working, needs attention, unsure, not in use")
    _common(c)
    c.add_argument("--type", action="append", choices=tuple(CHECKUP_TYPES), help="repeatable; default mcp, skill and plugin")
    c.add_argument("--include-bundled", action="store_true", help="also list the dispatcher's own bundled guides")
    su = commands.add_parser("setup", help="installed MCP servers and plugins that are not set up yet, with the step that finishes each")
    _common(su)
    e = commands.add_parser("export")
    _common(e)
    e.add_argument("--detailed", action="store_true")
    e.add_argument("--preview", action="store_true", help="list the fields a detailed export would contain, without values")
    f = commands.add_parser("forget")
    _common(f)
    f.add_argument("capability")
    r = commands.add_parser("reset")
    _common(r)
    r.add_argument("--confirm", action="store_true")
    pr = commands.add_parser("prune")
    _common(pr)
    pr.add_argument("--max-age-days", type=int)
    args = parser.parse_args(argv)
    try:
        return _dispatch(args)
    except (CapabilityError, OSError, ValueError, KeyError, TypeError) as exc:
        message = str(exc) if isinstance(exc, (CapabilityError,)) or type(exc).__name__ in ("DoctorError", "StoreError") else \
            "Capability metadata could not be inspected safely: " + type(exc).__name__
        print(json.dumps({"error": clean(message, 400)}), file=sys.stderr)
        return 2


def _dispatch(args):
    if args.command == "setup":
        inventory, _, _ = inventory_for(args, with_store=True)
        report = setup_report(inventory)
        print(json.dumps(report, indent=2) if args.json else render_setup(report))
        return 0
    if args.command == "checkup":
        inventory, _, _ = inventory_for(args, with_store=True)
        report = checkup(inventory, types=tuple(args.type or ("mcp", "skill", "plugin")), include_bundled=args.include_bundled)
        print(json.dumps(report, indent=2) if args.json else render_checkup(report))
        return 0
    if args.command in ("health", "mcps", "plugins", "capabilities"):
        inventory, settings, snapshot = inventory_for(args, with_store=True)
        kind = {"mcps": "mcp", "plugins": "plugin"}.get(args.command, getattr(args, "type", None))
        target = getattr(args, "capability", None) or (getattr(args, "target", None) if args.command == "capabilities" else None)
        explain = getattr(args, "explain", False) or (args.command == "capabilities" and args.action == "explain")
        plan = results = None
        mode = "passive"
        if args.command == "health" and (args.deep or args.probe_plan or args.refresh):
            directory = host_directory(inventory["host"], args.config_dir)
            store = open_store(directory, create=args.refresh, readonly=not args.refresh) if args.refresh or store_exists(directory) else None
            try:
                plan = plan_probes(inventory, settings, level=args.deep, allow_process=args.allow_process, allow_network=args.allow_network,
                                   targets={args.capability} if args.capability else None, store=store)
                mode = f"probe plan (level {args.deep})"
                if args.refresh and not args.probe_plan:
                    snapshot_receipts = [make_receipt(i["instance_id"], source="trusted_adapter", type="static_validation", operation="guidance",
                                                      outcome="success" if i["dimensions"]["configuration"] == "valid" else "failure",
                                                      reason="OK" if i["dimensions"]["configuration"] == "valid" else "INVALID_METADATA",
                                                      observed=inventory["created"], fingerprints={"artifact": i["artifact_digest"]})
                                         for i in inventory["instances"] if i["kind"] == "skill" and i["dimensions"]["presence"] == "installed"]
                    supplied = [r for r in _supplied_receipts(inventory, snapshot, settings) if r["session"]]  # v1 or session-less evidence is never durable
                    store.add_receipts(snapshot_receipts + supplied)
                    results, _ = run_probes(plan, settings, session=inventory["session"], store=store)
                    if results:
                        inventory = build_inventory(args.pack, args.project, args.host, args.config_dir, snapshot, settings, store=store)
                        inventory["_project"] = str(Path(args.project).resolve())
                    store.publish_snapshot(compact_snapshot(inventory, settings))
                    mode = f"refresh (probe level {args.deep})"
            finally:
                if store is not None:
                    store.close()
        report = health_report(inventory, kind=kind, capability=target, probe_plan=plan, probe_results=results, mode=mode)
        print(json.dumps(report, indent=2) if args.json else render(report, explain=explain))
        if getattr(args, "require", None):
            wanted = ("HEALTHY",) if args.require == "healthy" else ("HEALTHY", "DEGRADED")
            gated = [e for e in report["entries"] if e["dimensions"]["policy"] == "enabled" and not e.get("parent")]
            if not gated or any(e["display"] not in wanted for e in gated):
                print(json.dumps({"gate": args.require, "met": False}), file=sys.stderr)
                return 3
        return 0
    if args.command == "export":
        inventory, _, _ = inventory_for(args)
        if args.preview:
            print(json.dumps({"detailed_fields": ["instance_id", "kind", "display", "policy", "definition_id", "name", "qualifier", "reasons", "dimensions"],
                              "never_exported": ["locations", "evidence bodies", "credentials", "account identities", "usage history"]}, indent=2))
            return 0
        print(json.dumps(export(inventory, detailed=args.detailed), indent=2))
        return 0
    settings = load_settings(args.settings, project=args.project)
    directory = host_directory(args.host, args.config_dir)
    if args.command == "reset":
        if not args.confirm:
            print(json.dumps({"would_remove": str(directory / STORE_FILE) if store_exists(directory) else None, "confirm": "--confirm"}))
            return 0
        if store_exists(directory):
            (directory / STORE_FILE).unlink()
        print(json.dumps({"reset": True}))
        return 0
    if not store_exists(directory):
        print(json.dumps({"store": None, "note": "no capability store exists for this host"}))
        return 0
    with open_store(directory, readonly=False) as store:
        result = store.forget(args.capability) if args.command == "forget" else store.prune(args.max_age_days or settings["retention_days"])
    print(json.dumps(result, indent=2))
    return 0


def _supplied_receipts(inventory, snapshot, settings):
    by_name = {}
    for inst in inventory["instances"]:
        by_name.setdefault(inst["name"], inst)
    out = []
    source = snapshot.get("_source") or "model_snapshot"
    if source == "host_evidence_v1":
        return out
    for obs in snapshot.get("observations", []):
        inst = by_name.get(obs["capability"])
        if inst is None:
            continue
        out.append(make_receipt(inst["instance_id"], source=source, type=obs["type"], operation=obs["operation"], outcome=obs["outcome"], reason=obs["reason"],
                                observed=obs.get("observed_at", inventory["created"]), session=inventory["session"],
                                elapsed_ms=obs.get("elapsed_ms"), ttl=settings["freshness"]["operational_minutes"] * 60))
    return out


if __name__ == "__main__":
    raise SystemExit(main())
