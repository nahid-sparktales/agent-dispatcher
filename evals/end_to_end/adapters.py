"""Native CLI adapters for paired, local dispatcher evaluations.

These adapters isolate *discovered customization*, not hostile code.  A dedicated
native-auth profile is required; credentials are never copied or read.  The
caller owns subprocess lifetime, artifact redaction and fixture staging.
Doctor performs no model requests.  Codex discovery/prompt probes can populate
the dedicated profile's ordinary built-in skill cache.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import shlex
import shutil
import subprocess
import threading
import time
from typing import Any


class AdapterError(ValueError):
    """A launch cannot satisfy the declared evaluation configuration."""


# Preserve ordinary executable/locale lookup, not the embedding agent's settings,
# endpoint overrides, hooks, tool connectors, or unrelated credentials.
_ENV_KEYS = {
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "TEMP", "TMP",
    "LANG", "LC_ALL", "LC_CTYPE", "TERM", "SYSTEMROOT", "WINDIR",
}
_CODEX_FEATURES = ("hooks", "memories", "plugins", "apps")
_CLAUDE_FLAGS = (
    "--setting-sources", "--strict-mcp-config", "--mcp-config", "--settings",
    "--no-session-persistence", "--output-format", "--verbose", "--model",
    "--effort", "--permission-mode", "--input-format", "--replay-user-messages",
)
_CODEX_FLAGS = (
    "--json", "--ephemeral", "--ignore-user-config", "--ignore-rules",
    "--sandbox", "--model", "--cd",
)


def _spec(client: str, spec: dict, workspace: Path, skill_dir: Path | None):
    if client not in ("codex", "claude"):
        raise AdapterError(f"Unsupported client: {client}")
    for key in ("executable", "model", "effort", "auth", "profile_dir"):
        if not isinstance(spec.get(key), str) or not spec[key].strip():
            raise AdapterError(f"Missing nonempty client setting: {key}")
    if spec["auth"] not in ("subscription", "api"):
        raise AdapterError("auth must be subscription or api")
    profile = Path(spec["profile_dir"]).expanduser()
    workspace = Path(workspace)
    if not profile.is_absolute() or not workspace.is_absolute():
        raise AdapterError("profile_dir and workspace must be absolute paths")
    if profile.is_symlink():
        raise AdapterError("The evaluation auth profile must not be a symlink")
    profile = profile.resolve()
    workspace = workspace.resolve()
    defaults = (Path.home() / ".codex", Path.home() / ".claude")
    if profile == Path.home().resolve() or any(
        profile == p.resolve() or p.resolve() in profile.parents for p in defaults
    ):
        raise AdapterError("Use a dedicated evaluation auth profile outside personal CLI profiles")
    if not profile.is_dir() or not workspace.is_dir():
        raise AdapterError("The dedicated profile and workspace must already exist")
    skill = Path(skill_dir).resolve() if skill_dir is not None else None
    if skill is not None:
        expected = (workspace / ".agents/skills/agent-dispatcher" if client == "codex"
                    else profile / "skills/agent-dispatcher")
        if skill != expected.resolve() or not (skill / "SKILL.md").is_file():
            raise AdapterError("Treatment skill must be staged at the client's declared native skill path")
    executable = shutil.which(spec["executable"])
    if not executable:
        raise AdapterError(f"Client executable not found: {spec['executable']}")
    return str(Path(executable).resolve()), profile, workspace, skill


def _environment(client: str, spec: dict, profile: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in _ENV_KEYS}
    if client == "codex":
        env["CODEX_HOME"] = str(profile)
        if spec["auth"] == "api":
            key = os.environ.get("CODEX_API_KEY") or os.environ.get("OPENAI_API_KEY")
            if key:
                env["CODEX_API_KEY"] = key
    else:
        env.update({
            "CLAUDE_CONFIG_DIR": str(profile),
            "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
            "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        })
        if spec["auth"] == "api" and os.environ.get("ANTHROPIC_API_KEY"):
            env["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_API_KEY"]
    # Experiment knob: the dispatcher's LLM-assisted retrieval settings (a path, never a secret). Set for both
    # conditions so their environments stay identical; only the staged dispatcher reads it.
    if spec.get("llm_settings"):
        env["AGENT_DISPATCHER_LLM_CONFIG"] = spec["llm_settings"]
    return env


def _customization_errors(client: str, profile: Path, workspace: Path,
                          skill: Path | None) -> list[str]:
    errors = []
    # Inspect names only. Never open auth.json, .credentials.json, .claude.json,
    # login caches, keychains, or arbitrary user configuration contents.
    files = ("config.toml", "hooks.json", "AGENTS.md", "AGENTS.override.md") if client == "codex" else (
        "settings.json", "settings.local.json", "CLAUDE.md", "CLAUDE.local.md",
    )
    for name in files:
        if (profile / name).exists():
            errors.append(f"Unexpected customization in dedicated profile: {name}")
    dirs = ("hooks", "agents", "rules") if client == "codex" else (
        "commands", "agents", "hooks", "rules", "output-styles",
    )
    for name in dirs:
        path = profile / name
        if path.exists() and (not path.is_dir() or any(path.iterdir())):
            errors.append(f"Unexpected customization directory in dedicated profile: {name}")
    if client == "claude":
        # Plugin caches can be generated by native startup, but installed-plugin
        # records and cached custom packages make a stock run unverifiable.
        plugins = profile / "plugins"
        if plugins.exists() and any(plugins.iterdir()):
            errors.append("Unexpected plugin state in dedicated Claude profile")
    skills_root = profile / "skills"
    if skills_root.exists():
        for entry in skills_root.iterdir():
            if client == "codex" and entry.name == ".system":
                continue
            if skill is not None and entry.resolve() == skill:
                continue
            errors.append(f"Unexpected skill in dedicated profile: {entry.name}")
    # Codex config layering is independent of skill discovery. Fixtures must
    # not add a configuration layer; ordinary code/doc task inputs remain intact.
    if client == "codex":
        for root in (workspace, *workspace.parents):
            if (root / ".codex/config.toml").exists():
                errors.append("A workspace ancestor contains .codex/config.toml")
                break
    # Managed settings cannot be neutralized by a user preference. Refuse a
    # stock label instead of overriding organization policy.
    if client == "claude":
        managed = (
            Path("/Library/Application Support/ClaudeCode/managed-settings.json"),
            Path("/Library/Application Support/ClaudeCode/CLAUDE.md"),
            Path("/Library/Application Support/ClaudeCode/.claude/skills"),
            Path("/etc/claude-code/managed-settings.json"),
            Path("/etc/claude-code/CLAUDE.md"),
            Path("/etc/claude-code/.claude/skills"),
        )
        if any(p.exists() for p in managed):
            errors.append("Managed Claude customization exists; a stock baseline cannot be verified")
    return errors


def _command(argv: list[str], env: dict[str, str], cwd: Path, timeout: int = 25):
    try:
        return subprocess.run(argv, env=env, cwd=cwd, input="", text=True,
                              capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        # Do not return arbitrary subprocess output: native login failures can
        # contain credential metadata. The exception class is enough for doctor.
        raise AdapterError(f"Native CLI probe failed ({type(exc).__name__})") from exc


def _codex_config(spec: dict, disabled: list[str] | None = None) -> list[str]:
    values = {
        "model": json.dumps(spec["model"]),
        "model_reasoning_effort": json.dumps(spec["effort"]),
        "approval_policy": '"never"',
        "sandbox_mode": '"workspace-write"',
        "project_doc_max_bytes": "0",
        "mcp_servers": "{}",
        "web_search": '"disabled"',
        "memories.use_memories": "false",
        "memories.generate_memories": "false",
        "shell_environment_policy.inherit": '"core"',
        "shell_environment_policy.ignore_default_excludes": "false",
        "allow_login_shell": "false",
    }
    values.update({f"features.{key}": "false" for key in _CODEX_FEATURES})
    if disabled is not None:
        values["skills.config"] = "[" + ",".join(
            "{path=" + json.dumps(path) + ",enabled=false}" for path in sorted(set(disabled))
        ) + "]"
    result = []
    for key, value in values.items():
        result.extend(["-c", f"{key}={value}"])
    return result


def _codex_rpc(executable: str, spec: dict, env: dict[str, str], workspace: Path,
               disabled: list[str] | None = None) -> dict:
    """Request skill inventory and managed-policy presence; no turn/start."""
    argv = [executable, "app-server", "--listen", "stdio://", *_codex_config(spec, disabled)]
    messages: queue.Queue = queue.Queue()
    try:
        proc = subprocess.Popen(argv, cwd=workspace, env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    except OSError as exc:
        raise AdapterError("Cannot start Codex discovery probe") from exc

    def reader():
        try:
            for line in proc.stdout:
                try:
                    messages.put(json.loads(line))
                except ValueError:
                    pass
        finally:
            messages.put(None)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()

    def request(rid, method, params):
        try:
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": rid,
                                         "method": method, "params": params}) + "\n")
            proc.stdin.flush()
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                reply = messages.get(timeout=max(.1, deadline - time.monotonic()))
                if reply is None:
                    raise AdapterError("Codex discovery exited before returning evidence")
                if reply.get("id") == rid:
                    if "error" in reply:
                        raise AdapterError(f"Codex discovery does not support {method}")
                    return reply["result"]
        except (BrokenPipeError, queue.Empty, KeyError) as exc:
            raise AdapterError(f"Codex discovery failed at {method}") from exc
        raise AdapterError(f"Codex discovery timed out at {method}")

    try:
        request(1, "initialize", {"clientInfo": {"name": "dispatcher_e2e", "version": "1"}})
        proc.stdin.write('{"jsonrpc":"2.0","method":"initialized","params":{}}\n')
        proc.stdin.flush()
        inventory = request(2, "skills/list", {"cwds": [str(workspace)], "forceReload": True})
        requirements = request(3, "configRequirements/read", {})
        if requirements.get("requirements"):
            raise AdapterError("Managed Codex policy is present; a stock baseline cannot be verified")
        rows = []
        for entry in inventory.get("data", []):
            if entry.get("errors"):
                raise AdapterError("Codex reported skill discovery errors")
            rows.extend(entry.get("skills", []))
        if not rows or any(not {"name", "scope", "path", "enabled"} <= row.keys() for row in rows):
            raise AdapterError("Codex skill discovery evidence is incomplete")
        return {"skills": rows, "managed_policy": False}
    finally:
        if proc.stdin:
            proc.stdin.close()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        thread.join(timeout=1)
        if proc.stdout:
            proc.stdout.close()


def _codex_isolation(executable, spec, env, workspace, skill):
    initial = _codex_rpc(executable, spec, env, workspace)
    expected = (skill / "SKILL.md").resolve() if skill is not None else None
    disabled = [row["path"] for row in initial["skills"]
                if row["scope"] != "system" and Path(row["path"]).resolve() != expected]
    verified = _codex_rpc(executable, spec, env, workspace, disabled)
    enabled = [row for row in verified["skills"] if row["enabled"]]
    if any(row["scope"] != "system" and Path(row["path"]).resolve() != expected for row in enabled):
        raise AdapterError("Unexpected non-system Codex skill remains enabled after isolation")
    treatment = [row for row in enabled if row["name"] == "agent-dispatcher"]
    if (skill is None and treatment) or (skill is not None and len(treatment) != 1):
        raise AdapterError("Codex dispatcher discovery does not match the assigned condition")
    probe = _command([executable, "debug", "prompt-input", *_codex_config(spec, disabled)],
                     env, workspace)
    if probe.returncode:
        raise AdapterError("Codex cannot render the isolated prompt without a model request")
    try:
        prompt = json.loads(probe.stdout)
    except ValueError as exc:
        raise AdapterError("Codex prompt probe did not return valid JSON") from exc
    if not isinstance(prompt, list):
        raise AdapterError("Unsupported Codex prompt probe shape")
    serialized = json.dumps(prompt, sort_keys=True)
    if ("agent-dispatcher" in serialized) != (skill is not None):
        raise AdapterError("Codex prompt contains missing or unexpected dispatcher context")
    if "task-observer" in serialized:
        raise AdapterError("Disabled task-observer appears in the Codex prompt")
    # A catalog-disable override must remove every excluded file from the
    # model-visible prompt, not only change an inventory boolean.
    if any(path in serialized for path in disabled):
        raise AdapterError("A disabled Codex skill remains in the model-visible prompt")
    return disabled, {
        "skill_catalog": [{"name": row["name"], "scope": row["scope"]} for row in enabled],
        "disabled_external_skill_count": len(disabled),
        "prompt_sha256": hashlib.sha256(serialized.encode()).hexdigest(),
        "prompt_checked": True, "managed_policy": False,
    }


def build_launch(client: str, spec: dict, workspace: Path,
                 skill_dir: Path | None = None) -> dict:
    """Build a shell-free native launch. env is secret-bearing; NEVER serialize it."""
    executable, profile, workspace, skill = _spec(client, spec, workspace, skill_dir)
    errors = _customization_errors(client, profile, workspace, skill)
    if errors:
        raise AdapterError("; ".join(errors))
    env = _environment(client, spec, profile)
    effective = {
        "client": client, "model": spec["model"], "effort": spec["effort"],
        "auth": spec["auth"], "condition": "dispatcher" if skill else "baseline",
        "native_system_prompt": True, "memory": False, "hooks": False,
        "external_mcp": False, "personal_plugins": False,
        "isolation": "customization-discovery; not an OS security boundary",
        "llm_retrieval_settings": spec.get("llm_settings"),
    }
    if client == "codex":
        disabled, proof = _codex_isolation(executable, spec, env, workspace, skill)
        argv = [executable, "exec", "--json", "--ephemeral", "--ignore-user-config",
                "--ignore-rules", "--sandbox", "workspace-write", "--model", spec["model"],
                "--cd", str(workspace), *_codex_config(spec, disabled), "-"]
        effective.update({"input_format": "text", "permission_mode": "workspace-write/never",
                          "preflight": proof})
        prefix = "$agent-dispatcher " if skill else ""
    else:
        settings = {
            "disableAllHooks": True, "autoMemoryEnabled": False,
            "enabledPlugins": {}, "permissions": {"defaultMode": "dontAsk"},
            "sandbox": {"enabled": True, "failIfUnavailable": True,
                        "autoAllowBashIfSandboxed": True,
                        "allowUnsandboxedCommands": False,
                        "network": {"allowedDomains": []}},
        }
        argv = [executable, "--print", "--output-format", "stream-json", "--verbose",
                "--input-format", "stream-json", "--replay-user-messages",
                "--no-session-persistence", "--setting-sources", "user",
                "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                "--settings", json.dumps(settings, separators=(",", ":")),
                "--model", spec["model"], "--effort", spec["effort"],
                "--permission-mode", "dontAsk", "--allowedTools",
                "Read,Edit,Write,Skill,Bash(python3 *),Bash(python *),Bash(git diff *)",
                "--no-chrome"]
        effective.update({"input_format": "stream-json", "permission_mode": "dontAsk",
                          "shell_sandbox": "required; no unsandboxed fallback",
                          "preflight": {"profile_customization_checked": True,
                                        "runtime_startup_check_required": True}})
        prefix = "/agent-dispatcher " if skill else ""
    return {"argv": argv, "env": env, "stdin_prefix": prefix, "effective": effective}


def doctor(client: str, spec: dict, workspace: Path,
           skill_dir: Path | None = None) -> dict:
    result = {"ok": False, "version": None, "errors": [], "warnings": [], "evidence": {}}
    try:
        executable, profile, workspace, skill = _spec(client, spec, workspace, skill_dir)
        env = _environment(client, spec, profile)
        version = _command([executable, "--version"], env, workspace)
        if version.returncode or not version.stdout.strip():
            raise AdapterError("Client version could not be established")
        result["version"] = version.stdout.strip().splitlines()[0]
        help_argv = [executable, "exec", "--help"] if client == "codex" else [executable, "--help"]
        help_result = _command(help_argv, env, workspace)
        required = _CODEX_FLAGS if client == "codex" else _CLAUDE_FLAGS
        missing = [flag for flag in required if flag not in help_result.stdout]
        if help_result.returncode or missing:
            raise AdapterError("Client lacks required isolation/capture options: " + ", ".join(missing))
        result["errors"].extend(_customization_errors(client, profile, workspace, skill))
        if result["errors"]:
            return result
        if spec["auth"] == "api":
            key = "CODEX_API_KEY" if client == "codex" else "ANTHROPIC_API_KEY"
            if not env.get(key):
                raise AdapterError(f"API authentication requires {key}" +
                                   (" or OPENAI_API_KEY" if client == "codex" else ""))
            result["evidence"]["auth"] = "provider-native API environment present; not contacted"
        else:
            argv = [executable, "login", "status"] if client == "codex" else [executable, "auth", "status", "--json"]
            status = _command(argv, env, workspace)
            if client == "codex":
                logged_in = status.returncode == 0 and "chatgpt" in (status.stdout + status.stderr).lower()
            else:
                try:
                    data = json.loads(status.stdout)
                except ValueError:
                    data = {}
                logged_in = (status.returncode == 0 and data.get("loggedIn") is True and
                             str(data.get("authMethod", "")).lower() in ("claude.ai", "oauth"))
            if not logged_in:
                raise AdapterError("Native subscription login is not verified in the dedicated evaluation profile")
            result["evidence"]["auth"] = "native subscription login verified; credential content not captured"
        if client == "codex":
            launch = build_launch(client, spec, workspace, skill)
            result["evidence"].update(launch["effective"]["preflight"])
        else:
            # --init-only is documented but hidden from some versions' help.
            # It runs initialization/hooks only; with hooks disabled it never
            # starts a model turn. Unknown versions fail on an unsupported flag.
            launch = build_launch(client, spec, workspace, skill)
            init = _command([*launch["argv"], "--init-only"], env, workspace)
            if init.returncode:
                raise AdapterError("Claude cannot validate isolated initialization without a model request")
            if '"type":"assistant"' in init.stdout.replace(" ", ""):
                raise AdapterError("Unexpected assistant output from Claude initialization probe")
            result["evidence"].update(launch["effective"]["preflight"])
            result["evidence"]["native_init_only"] = True
            result["warnings"].append(
                "Claude has no no-model prompt/catalog export; score only after live system/init validation. "
                "Compare stock tool/skill catalogs between paired trials."
            )
        result["warnings"].append("Native CLI authentication validity does not establish model entitlement.")
        result["ok"] = True
    except (AdapterError, OSError, ValueError) as exc:
        result["errors"].append(str(exc))
    return result


def _number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        return None
    try:
        return value if math.isfinite(value) else None
    except OverflowError:
        return None


def _event_shape_errors(client: str, event: dict) -> list[str]:
    """Reject unsupported nested shapes before accessing provider fields."""
    errors = []
    kind = event.get("type")
    if client == "codex":
        if kind == "item.completed":
            item = event.get("item")
            if not isinstance(item, dict):
                errors.append("Codex item.completed has invalid item")
            elif item.get("type") == "agent_message" and not isinstance(item.get("text", ""), str):
                errors.append("Codex agent message text is not a string")
        if kind == "turn.completed" and "usage" in event and not isinstance(event["usage"], dict):
            errors.append("Codex terminal usage is not an object")
    else:
        if kind in ("assistant", "user"):
            message = event.get("message")
            if not isinstance(message, dict):
                errors.append("Claude message is not an object")
            elif not isinstance(message.get("content", []), (list, str)):
                errors.append("Claude message content is not text or a list")
            elif isinstance(message.get("content"), list):
                for block in message["content"]:
                    if not isinstance(block, dict):
                        errors.append("Claude content block is not an object")
                    elif block.get("type") == "text" and not isinstance(block.get("text", ""), str):
                        errors.append("Claude text block has invalid text")
                    elif block.get("type") == "tool_use" and (
                        not isinstance(block.get("id"), str) or not isinstance(block.get("name"), str)
                    ):
                        errors.append("Claude tool call lacks a string id/name")
                    elif block.get("type") == "tool_result" and not isinstance(block.get("tool_use_id"), str):
                        errors.append("Claude tool result lacks a string id")
        if kind == "result":
            if "usage" in event and not isinstance(event["usage"], dict):
                errors.append("Claude terminal usage is not an object")
            if not isinstance(event.get("result", ""), str):
                errors.append("Claude terminal result is not a string")
            if not isinstance(event.get("errors", []), list):
                errors.append("Claude terminal errors is not a list")
            denials = event.get("permission_denials", [])
            if not isinstance(denials, list) or any(not isinstance(x, dict) for x in denials):
                errors.append("Claude permission denials is not a list of objects")
    return errors


def _read_evidence(name: str, inputs: Any, output: Any = None) -> bool:
    """Recognize successful access to actual dispatcher instructions, not claims."""
    if not isinstance(name, str) or not isinstance(inputs, dict):
        return False
    if name.lower() == "skill":
        return str(inputs.get("skill", "")).split(":")[-1] == "agent-dispatcher"
    path = str(inputs.get("file_path", inputs.get("path", "")))
    matches = bool(re.search(r"(?:^|[/\\])agent-dispatcher[/\\](?:SKILL\.md|(?:references[/\\])?roles[/\\][^/\\]+\.md)$", path))
    if name.lower() in ("read", "read_file", "readfile"):
        return matches
    command = str(inputs.get("command", inputs.get("cmd", "")))
    if name.lower() in ("bash", "exec_command", "command_execution", "shell_command"):
        return bool(output) and _shell_instruction_read(command)
    return False


def _native_claude_dispatcher_replay(event: dict) -> bool:
    """Recognize the native command envelope, never an unmarked invocation claim.

    Claude 2.1.150 expands a slash skill before querying the model, but marks its
    body isMeta and omits it from replay output. The native user replay contains
    this exact envelope even when trivial work legitimately needs no role read.
    """
    if event.get("type") != "user" or event.get("isReplay") is not True:
        return False
    message = event.get("message")
    if not isinstance(message, dict) or message.get("role") != "user":
        return False
    content = message.get("content")
    if not isinstance(content, str):
        return False
    return re.fullmatch(
        r"<command-message>agent-dispatcher</command-message>\n"
        r"<command-name>/agent-dispatcher</command-name>"
        r"(?:\n<command-args>[\s\S]*</command-args>)?", content,
    ) is not None


def _shell_instruction_read(command: str, depth: int = 0) -> bool:
    """Conservatively identify read commands; echoed command text is not a read."""
    if depth > 2:
        return False
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|\n")
        lexer.whitespace_split = True
        lexer.whitespace = " \t\r"
        tokens = list(lexer)
    except ValueError:
        return False
    segments = [[]]
    for token in tokens:
        if token and all(c in ";&|\n" for c in token):
            segments.append([])
        else:
            segments[-1].append(token)
    for segment in segments:
        if not segment:
            continue
        program = Path(segment[0]).name
        if program in ("sh", "bash", "zsh"):
            for index, token in enumerate(segment[:-1]):
                if token.startswith("-") and "c" in token[1:]:
                    if _shell_instruction_read(segment[index + 1], depth + 1):
                        return True
        if program in ("cat", "sed", "head", "tail", "bat"):
            if any(re.search(r"agent-dispatcher[/\\](?:SKILL\.md|(?:references[/\\])?roles[/\\][\w-]+\.md)$", token)
                   for token in segment[1:]):
                return True
    return False


def parse_events(client: str, stdout: str) -> dict:
    if client not in ("codex", "claude"):
        raise AdapterError(f"Unsupported client: {client}")
    result = {
        "final_answer": "", "usage": {"input_tokens": None, "output_tokens": None,
                                         "cached_input_tokens": None, "cost_usd": None},
        "treatment_invoked": False, "usage_observed": False, "diagnostics": [], "startup": {},
        "status": "infrastructure_error", "errors": [],
    }
    seen_result = False
    tools = {}
    malformed = 0
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            malformed += 1
            continue
        if not isinstance(event, dict):
            malformed += 1
            continue
        shape_errors = _event_shape_errors(client, event)
        if shape_errors:
            result["errors"].extend(shape_errors)
            continue
        kind = event.get("type")
        if client == "codex":
            if kind == "thread.started":
                result["startup"]["thread_started"] = True
                for key in ("model", "tools", "skills", "mcp_servers", "plugins"):
                    if key in event:
                        result["startup"][key] = event[key]
            elif kind == "item.completed":
                item = event.get("item", {})
                if item.get("type") == "agent_message":
                    result["final_answer"] = item.get("text", "")
                elif item.get("type") == "command_execution" and item.get("exit_code") == 0:
                    result["treatment_invoked"] |= _read_evidence("command_execution", item, item.get("aggregated_output"))
                elif item.get("type") in ("tool_call", "mcp_tool_call"):
                    if not item.get("error") and item.get("status") in (None, "completed"):
                        result["treatment_invoked"] |= _read_evidence(
                            item.get("tool", item.get("name", "")), item.get("arguments", {}), item.get("result"))
            elif kind == "turn.completed":
                seen_result = True
                usage = event.get("usage", {})
                result["usage_observed"] = "usage" in event
                for key in ("input_tokens", "output_tokens", "cached_input_tokens"):
                    result["usage"][key] = _number(usage.get(key))
                result["status"] = "completed"
            elif kind in ("error", "turn.failed"):
                payload = event.get("error", event)
                message = payload.get("message", "Codex run failed") if isinstance(payload, dict) else str(payload)
                result["errors"].append(str(message))
        else:
            if kind == "system" and event.get("subtype") == "init":
                keys = ("model", "tools", "skills", "slash_commands", "mcp_servers", "plugins",
                        "plugin_errors", "permissionMode", "memory_paths", "agents", "output_style",
                        "claude_code_version", "apiKeySource")
                result["startup"] = {key: event[key] for key in keys if key in event}
                result["startup"]["init_received"] = True
            elif kind in ("assistant", "user"):
                result["treatment_invoked"] |= _native_claude_dispatcher_replay(event)
                message = event.get("message", {})
                blocks = message.get("content", []) if isinstance(message, dict) else []
                if isinstance(blocks, str):
                    blocks = [{"type": "text", "text": blocks}]
                for block in blocks:
                    if not isinstance(block, dict):
                        continue
                    if kind == "assistant" and block.get("type") == "tool_use":
                        tools[block.get("id")] = (block.get("name", ""), block.get("input", {}))
                    elif kind == "user" and block.get("type") == "tool_result":
                        call = tools.get(block.get("tool_use_id"))
                        if call and not block.get("is_error"):
                            result["treatment_invoked"] |= _read_evidence(*call, block.get("content"))
                    elif kind == "user" and block.get("type") == "text":
                        text = block.get("text", "")
                        # Some clients also emit the full native skill expansion.
                        # Raw slash text or an unmarked command envelope is not proof.
                        if ("Base directory for this skill:" in text and
                            re.search(r"agent-dispatcher(?:[/\\]|\s|$)", text) and
                            ("# Agent Dispatcher" in text or "Route each request" in text)):
                            result["treatment_invoked"] = True
            elif kind == "result":
                seen_result = True
                result["final_answer"] = event.get("result", "")
                usage = event.get("usage", {})
                result["usage_observed"] = "usage" in event
                result["usage"].update({
                    "input_tokens": _number(usage.get("input_tokens")),
                    "output_tokens": _number(usage.get("output_tokens")),
                    "cached_input_tokens": _number(usage.get("cache_read_input_tokens")),
                    "cost_usd": _number(event.get("total_cost_usd")),
                })
                if event.get("is_error") or event.get("subtype") not in (None, "success"):
                    errors = event.get("errors", [])
                    result["errors"].extend(str(x) for x in errors)
                    if not errors:
                        result["errors"].append(str(event.get("result") or event.get("subtype") or "Claude run failed"))
                else:
                    result["status"] = "completed"
                for denial in event.get("permission_denials", []):
                    result["diagnostics"].append("permission_denied:" + str(denial.get("tool_name", "unknown")))
            elif kind == "system" and event.get("subtype") == "api_retry":
                result["diagnostics"].append("api_retry:" + str(event.get("error", "unknown")))
    if malformed:
        result["errors"].append(f"{malformed} malformed or non-JSON trace lines")
    if not seen_result:
        result["errors"].append("Native CLI trace has no terminal result")
    error_text = " ".join(result["errors"]).lower()
    if re.search(r"authenticat|not logged in|invalid.{0,10}(?:api.?key|token)|unauthori[sz]ed|\b401\b|login required", error_text):
        result["status"] = "authentication_failure"
    elif result["errors"]:
        result["status"] = "infrastructure_error"
    return result


def validate_startup(client: str, spec: dict, parsed: dict, condition: str) -> list[str]:
    """Fail a run with unknown/contaminated startup, not an ignored treatment."""
    startup = parsed.get("startup", {})
    errors = []
    if not isinstance(startup, dict):
        return ["Native startup metadata is not an object"]
    for key in ("tools", "skills", "slash_commands", "plugins", "mcp_servers", "agents", "plugin_errors"):
        if key in startup and not isinstance(startup[key], list):
            errors.append(f"Native startup {key} is not a list")
    for key in ("tools", "skills", "slash_commands", "agents"):
        if isinstance(startup.get(key), list) and any(not isinstance(x, str) for x in startup[key]):
            errors.append(f"Native startup {key} contains a non-string entry")
    if errors:
        return errors
    treatment = condition in ("dispatcher", "treatment", "on")
    if client == "codex":
        if not startup.get("thread_started"):
            errors.append("Missing Codex thread.started evidence")
        if startup.get("model") and startup["model"] != spec["model"]:
            errors.append("Codex reported an unexpected model")
    elif client == "claude":
        required = {"init_received", "model", "tools", "skills", "plugins", "mcp_servers", "permissionMode"}
        if not required <= startup.keys():
            errors.append("Claude startup metadata cannot establish isolation")
        if startup.get("model") != spec["model"]:
            errors.append("Claude reported an unexpected model; use an exact model ID")
        if startup.get("permissionMode") != "dontAsk":
            errors.append("Claude reported an unexpected permission mode")
        if startup.get("memory_paths"):
            errors.append("Claude startup loaded memory")
        if startup.get("plugin_errors"):
            errors.append("Claude startup reported plugin loading errors")
        # Empty roots + explicit settings sources establish builtin provenance;
        # preserve the client's builtins, and compare catalogs across the pair.
        skills = startup.get("skills", [])
        if any("task-observer" in str(name) for name in skills):
            errors.append("Disabled task-observer appeared in Claude startup")
        dispatcher_present = any(str(name).split(":")[-1] == "agent-dispatcher" for name in skills)
        if dispatcher_present != treatment:
            errors.append("Claude dispatcher catalog does not match the assigned condition")
    else:
        return [f"Unsupported client: {client}"]
    if startup.get("plugins"):
        errors.append("Unexpected plugins in native startup")
    if startup.get("mcp_servers"):
        errors.append("Unexpected MCP servers in native startup")
    if any(str(name).startswith("mcp__") for name in startup.get("tools", [])):
        errors.append("Unexpected MCP tools in native startup")
    if not treatment and parsed.get("treatment_invoked"):
        errors.append("Baseline accessed dispatcher instructions")
    return errors
