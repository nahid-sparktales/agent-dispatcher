"""Private, bounded observations from native tool events; never execute trace text.

These observations describe visible calls/results, not hidden model context or an
OS audit. Package identity is captured before a trial from its staged file tree.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shlex

MAX_ACTIONS = 2000
MAX_EVENTS = 50000
MAX_COMMAND = 65536
MAP_STATUSES = {"fresh", "stale", "partial", "missing", "invalid", "unavailable"}
READ_TOOLS = {"read", "read_file", "readfile"}
SHELL_TOOLS = {"bash", "exec_command", "command_execution", "shell_command"}
WRITE_TOOLS = {"write", "edit", "write_file", "edit_file", "multiedit"}
SEARCH_TOOLS = {"grep", "glob", "search", "search_files"}
LIST_TOOLS = {"list_directory", "list_files"}
INSTRUCTION_FILES = {"AGENTS.md", "CLAUDE.md"}


@dataclass
class Bindings:
    workspace: str
    package: str | None
    files: dict[str, str]
    roles: dict[str, str]
    aliases: dict[str, str]
    recorded: bool = False


def bind(workspace: Path, skill: Path | None) -> Bindings:
    """Read only harness-owned staged instructions before launching the client."""
    root = str(Path(workspace).resolve())
    files, roles, aliases = {}, {}, {}
    if skill is not None:
        skill = Path(skill).resolve()
        for path in sorted(skill.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(skill).as_posix()
            files[str(path)] = relative
            if re.fullmatch(r"(?:references/)?roles/[\w-]+\.md", relative):
                role = path.stem
                roles[relative] = role
                aliases[role] = role
                aliases[role.replace("-", " ")] = role
                # Metadata only, from the known staged role rather than the trace.
                for key, value in re.findall(r"^(slug|name):\s*[\"']?([^\n\"']+)", path.read_text()[:4096], re.M):
                    aliases[value.strip().lower()] = role
        if "implementer" in aliases:
            aliases.update(coder="implementer", dev="implementer")
    return Bindings(root, str(skill) if skill is not None else None, files, roles, aliases)


def empty(availability="unavailable"):
    return {"schema_version": 1, "source": "native tool events", "availability": availability,
            "actions": [], "summary": {name: 0 for name in (
                "helper_attempts", "helper_successes", "guidance_reads", "guidance_unique_paths",
                "guidance_repeated_reads", "guidance_returned_chars", "failed_paths",
                "permission_denials", "observed_writes")},
            "route": {"role": None, "basis": "unknown", "consistent": None},
            "preparation": {"schema_version": 1, "status": "unknown", "availability": "unavailable"},
            "omitted_actions": 0,
            "limits": ["Only visible native events are measured; missing or partial evidence is not zero activity.",
                       "Returned characters are not token counts or the amount of hidden startup context.",
                       "Tool-observed writes do not establish final residue or whole-machine confinement."]}


def _text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(b["text"] for b in value if isinstance(b, dict)
                         and b.get("type") == "text" and isinstance(b.get("text"), str))
    if isinstance(value, dict):
        return "\n".join(value[k] for k in ("stdout", "stderr", "output") if isinstance(value.get(k), str))
    return ""


def _absolute_path(value, binding, cwd=None):
    candidate = value if os.path.isabs(value) else os.path.join(cwd or binding.workspace, value)
    # Retrospective bindings come from verified immutable package bytes and
    # captured roots. Current symlinks or replacement profile files are irrelevant.
    return os.path.normpath(candidate) if binding.recorded else os.path.realpath(candidate)


def _path(value, binding, cwd=None):
    if not isinstance(value, str) or not value or len(value) > 4096 or "\x00" in value:
        return None, None
    absolute = _absolute_path(value, binding, cwd)
    if absolute in binding.files:
        return "package/" + binding.files[absolute], binding.files[absolute]
    if binding.package and (absolute == binding.package or absolute.startswith(binding.package + os.sep)):
        return "package/" + os.path.relpath(absolute, binding.package), None
    if absolute == binding.workspace or absolute.startswith(binding.workspace + os.sep):
        return "project/" + os.path.relpath(absolute, binding.workspace), None
    parent = os.path.dirname(binding.workspace)
    if absolute == parent or absolute.startswith(parent + os.sep):
        return "trial/" + os.path.relpath(absolute, parent), None
    # Never publish profile names, usernames, credentials, or arbitrary host paths.
    return "outside-owned-trial", None


def _read_target(path, binding, cwd=None):
    target, relative = _path(path, binding, cwd)
    if target is None:
        return None
    row = {"kind": "path_lookup", "target": target}
    if relative and relative.endswith(".md"):
        row["kind"] = "guidance_read"
        if relative in binding.roles:
            row["role"] = binding.roles[relative]
    elif target.startswith("project/"):
        row["kind"] = "instruction_discovery" if Path(target).name in INSTRUCTION_FILES else "project_investigation"
        row["operation"] = "read"
    return row


def _investigation(paths, binding, cwd, operation, *, instructions_only=False):
    rows = []
    for path in paths:
        target, _ = _path(path, binding, cwd)
        if target and target.startswith("project/"):
            exempt = instructions_only or Path(target).name in INSTRUCTION_FILES
            rows.append({"kind": "instruction_discovery" if exempt else "project_investigation",
                         "target": target, "operation": operation})
        elif target and target.startswith("package/"):
            rows.append({"kind": "package_discovery", "target": target, "operation": operation})
    return rows


def _instruction_pattern(pattern):
    return isinstance(pattern, str) and pattern.removeprefix("**/") in INSTRUCTION_FILES


def _shell_investigation(words, binding, cwd):
    """Recognize a small literal read/search/list subset, never execute it."""
    program, args = Path(words[0]).name, words[1:]
    paths, patterns = [], []
    if program in {"cat", "head", "tail", "bat", "sed"}:
        index, expression = 0, program != "sed"
        while index < len(args):
            arg = args[index]
            if arg == "--":
                paths.extend(args[index + 1:])
                break
            if arg in {"-n", "-c"} and program in {"head", "tail"}:
                index += 1
                if index >= len(args) or not args[index].isdigit():
                    return [], False
            elif arg.startswith("-"):
                if not (arg in {"-n", "-b", "-s", "-E", "-T", "-v", "-A", "-p", "--plain"} or re.fullmatch(r"-\d+", arg)):
                    return [], False
            elif not expression:
                # Only a print-range sed program can establish a read.
                if not re.fullmatch(r"\d+(?:,\d+|,\$)?p", arg):
                    return [], False
                expression = True
            else:
                paths.append(arg)
            index += 1
        if not paths or not expression:
            return [], False
        return [row for path in paths if (row := _read_target(path, binding, cwd))], True
    if program == "ls":
        for arg in args:
            if arg == "--":
                continue
            if arg.startswith("-"):
                if not re.fullmatch(r"-[alAFhRd1]+", arg):
                    return [], False
            else:
                paths.append(arg)
        return _investigation(paths or ["."], binding, cwd, "explore"), True
    if program == "find":
        index, branch_pattern, all_branches_pattern, print_before_filter = 0, False, True, False
        while index < len(args) and not args[index].startswith("-"):
            paths.append(args[index])
            index += 1
        while index < len(args):
            arg = args[index]
            if arg in {"-name", "-iname", "-type", "-maxdepth", "-mindepth"}:
                index += 1
                if index >= len(args):
                    return [], False
                if arg in {"-name", "-iname"}:
                    patterns.append(args[index])
                    branch_pattern = True
                elif arg == "-type" and args[index] not in {"f", "d"}:
                    return [], False
                elif arg in {"-maxdepth", "-mindepth"} and not args[index].isdigit():
                    return [], False
            elif arg not in {"-print", "-print0", "-o", "-a"}:
                return [], False
            elif arg == "-o":
                all_branches_pattern = all_branches_pattern and branch_pattern
                branch_pattern = False
            elif arg in {"-print", "-print0"} and not branch_pattern:
                print_before_filter = True
            index += 1
        exempt = not print_before_filter and all_branches_pattern and branch_pattern and all(_instruction_pattern(pattern) for pattern in patterns)
        return _investigation(paths or ["."], binding, cwd, "search", instructions_only=exempt), True
    if program == "rg":
        index, files, explicit_pattern = 0, False, False
        while index < len(args):
            arg = args[index]
            if arg == "--":
                paths.extend(args[index + 1:])
                break
            if arg in {"-g", "--glob", "-e", "--regexp", "-m", "--max-count"}:
                index += 1
                if index >= len(args):
                    return [], False
                if arg in {"-g", "--glob"}:
                    patterns.append(args[index])
                elif arg in {"-e", "--regexp"}:
                    explicit_pattern = True
                elif not args[index].isdigit():
                    return [], False
            elif arg == "--files":
                files = True
            elif arg.startswith("-"):
                if arg not in {"-n", "-l", "-i", "-F", "-S", "-H", "--hidden", "--no-ignore", "--no-config", "--line-number", "--files-with-matches"}:
                    return [], False
            elif not files and not explicit_pattern:
                explicit_pattern = True
            else:
                paths.append(arg)
            index += 1
        exempt = bool(patterns) and all(_instruction_pattern(pattern) for pattern in patterns)
        return _investigation(paths or ["."], binding, cwd, "search", instructions_only=exempt), True
    if program in {"rm", "unlink"}:
        for arg in args:
            if program == "rm" and arg in {"-f", "--"}:
                continue
            if not arg or arg.startswith("-"):
                return [], False
            paths.append(arg)
        if not paths or (program == "unlink" and len(paths) != 1):
            return [], False
        rows, supported = [], True
        for path in paths:
            target, _ = _path(path, binding, cwd)
            if target and target.startswith("trial/") and target != "trial/.":
                rows.append({"kind": "cleanup_attempt", "target": target, "remaining_state": "unknown"})
            else:
                supported = False
        return rows, supported
    return [], False


def _literal_tokens(command):
    """Small shell-word lexer for a deliberately literal command subset.

    Keep operator tokens distinct from quoted text. Expansions, globs, comments,
    substitutions and line continuations are outside this attribution grammar.
    Adjacent quoted pieces and escaped apostrophes remain ordinary literal words.
    """
    tokens, index = [], 0
    while index < len(command):
        if command[index] in " \t\r":
            index += 1
            continue
        if command[index] == "\n":
            return None
        if command[index] in ";&|<>()":
            start = index
            while index < len(command) and command[index] in ";&|<>()":
                index += 1
            tokens.append(("operator", command[start:index]))
            continue
        word = []
        while index < len(command) and command[index] not in " \t\r\n;&|<>()":
            character = command[index]
            if character == "'":
                end = command.find("'", index + 1)
                if end < 0:
                    return None
                word.append(command[index + 1:end])
                index = end + 1
            elif character == '"':
                index += 1
                while index < len(command) and command[index] != '"':
                    character = command[index]
                    if character in "$`":
                        return None
                    if character == "\\":
                        index += 1
                        if index >= len(command) or command[index] not in '\\"$`':
                            return None
                        character = command[index]
                    word.append(character)
                    index += 1
                if index >= len(command):
                    return None
                index += 1
            elif character == "\\":
                index += 1
                if index >= len(command) or command[index] == "\n":
                    return None
                word.append(command[index])
                index += 1
            elif character in "$`~*?[]{}#":
                return None
            else:
                word.append(character)
                index += 1
        tokens.append(("word", "".join(word)))
    return tokens


def _literal_helper_pipeline(command, binding, cwd):
    """Attribute only [literal cd &&] [literal printf |] one bound helper."""
    tokens = _literal_tokens(command.strip())
    if tokens is None:
        # Do not lose quote/expansion provenance through the legacy shlex or
        # shell-wrapper fallback. Uncertain syntax cannot become literal later.
        return [], False
    if not any(kind == "operator" for kind, _ in tokens):
        return None
    if len(tokens) >= 3 and tokens[0] == ("word", "cd") and tokens[1][0] == "word" and tokens[2] == ("operator", "&&"):
        directory = tokens[1][1]
        if not directory or directory.startswith("-"):
            return [], False
        cwd = _absolute_path(directory, binding, cwd)
        tokens = tokens[3:]
    piped = False
    if len(tokens) >= 4 and tokens[0] == ("word", "printf"):
        if tokens[1][0] != "word" or tokens[1][1] not in {"%s", "%s\\n"} or tokens[2][0] != "word" or tokens[3] != ("operator", "|"):
            return [], False
        tokens = tokens[4:]
        piped = True
    if not tokens or any(kind != "word" for kind, _ in tokens):
        return [], False
    words = [value for _, value in tokens]
    if not re.fullmatch(r"python(?:3(?:\.\d+)?)?", Path(words[0]).name):
        return [], False
    args = words[1:]
    while args and args[0] in {"-B", "-u", "--"}:
        args.pop(0)
    if not args:
        return [], False
    target, relative = _path(args[0], binding, cwd)
    if relative not in {prefix + helper + ".py" for prefix in ("", "scripts/") for helper in ("context", "project_map", "resources", "doctor")}:
        return [], False
    if piped and not any(args[index:index + 2] == ["--task-file", "-"] for index in range(len(args) - 1)):
        return [], False
    return [{"kind": "helper", "target": target, "helper": Path(relative).stem}], True


def _shell_calls(command, binding, depth=0, cwd=None):
    """Conservative argv attribution. Compound output is not assigned to a file."""
    if not isinstance(command, str) or len(command) > MAX_COMMAND or depth > 2:
        return [], False
    # Literal heredoc bodies are task data, not shell syntax. Do not feed their
    # apostrophes/quotes into shlex, and do not attribute appended commands.
    lines = command.splitlines()
    heredoc = re.search(r"<<\s*(['\"])([A-Za-z_][A-Za-z0-9_]*)\1\s*$", lines[0]) if lines else None
    if heredoc:
        endings = [index for index, line in enumerate(lines[1:], 1) if line == heredoc[2]]
        if not endings or any(line.strip() for line in lines[endings[0] + 1:]):
            return [], False
        command = lines[0][:heredoc.start()].rstrip()
    literal = _literal_tokens(command.strip())
    if literal is None:
        return [], False
    if len(literal) >= 3 and literal[0] == ("word", "cd") and literal[1][0] == "word" and literal[2] == ("operator", "&&"):
        directory = literal[1][1]
        if not directory or directory.startswith("-"):
            return [], False
        # Requote literal words rather than reinterpreting payload metacharacters.
        remainder = " ".join(shlex.quote(value) if kind == "word" else value for kind, value in literal[3:])
        return _shell_calls(remainder, binding, depth + 1, _absolute_path(directory, binding, cwd))
    composed = _literal_helper_pipeline(command, binding, cwd)
    if composed is not None:
        return composed
    if "\n" in command:
        # The literal lexer refuses unquoted newlines, so these sit inside quoted words,
        # such as a multi-line --task='...' request: one operator-free command.
        tokens = [value for _, value in literal]
    else:
        try:
            lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
            lexer.whitespace_split = True
            tokens = list(lexer)
        except ValueError:
            return [], False
    if not tokens:
        return [], True
    if Path(tokens[0]).name in {"sh", "bash", "zsh"}:
        for index, token in enumerate(tokens[:-1]):
            if token in {"-c", "-lc"}:
                return _shell_calls(tokens[index + 1], binding, depth + 1, cwd)
    if any(token in {"<<", "<<<"} for token in tokens):
        return [], False
    if any(token in {";", "&&", "||", "|", "&", ">", ">>"} for token in tokens):
        return [], False
    program = Path(tokens[0]).name
    if re.fullmatch(r"python(?:3(?:\.\d+)?)?", program):
        args = tokens[1:]
        while args and args[0] in {"-B", "-u", "--"}:
            args.pop(0)
        if args:
            target, relative = _path(args[0], binding, cwd)
            if relative in {prefix + helper + ".py" for prefix in ("", "scripts/") for helper in ("context", "project_map", "resources", "doctor")}:
                helper = Path(relative).stem
                return [{"kind": "helper", "target": target, "helper": helper}], True
        return [], False
    if program in {"echo", "printf", "pwd", "true", "false"}:
        return [], True
    return _shell_investigation(tokens, binding, cwd)


def _outcome(call):
    if not call["complete"]:
        return "unknown"
    output = call["output"].lower()
    if call.get("denied") or (call.get("error") and re.search(r"permission.*denied|not allowed|not permitted", output)):
        return "denied"
    if type(call.get("exit_code")) is int:
        return "succeeded" if call["exit_code"] == 0 else "failed"
    if call.get("error") is True:
        return "failed"
    if call["name"] == "command_execution":
        return "unknown"
    return "succeeded" if call.get("error") is False or call.get("result_received") else "unknown"


def _context_exclusions(payload):
    """Keep only bounded measurements, never task phrases or excluded paths."""
    policy = payload.get("exclusion_policy")
    if not isinstance(policy, dict):
        return {"availability": "unavailable"}
    counts = {"availability": "complete"}
    if type(policy.get("automatic_enabled")) is bool:
        counts["automatic_enabled"] = policy["automatic_enabled"]
    else:
        counts["availability"] = "partial"
    for name, limit in (("automatic", 64), ("manual", 64), ("applied", 128), ("unresolved", 64)):
        value = policy.get(name)
        valid = isinstance(value, list) and len(value) <= limit
        if valid and name == "unresolved":
            valid = all(isinstance(row, dict) and all(isinstance(row.get(key), str) and len(row[key]) <= 240
                        for key in ("phrase", "reason")) for row in value)
        elif valid:
            valid = all(isinstance(item, str) and len(item) <= 4096 for item in value)
        if valid:
            counts[name + "_count"] = len(value)
        else:
            counts["availability"] = "partial"
    total = policy.get("unresolved_total")
    if type(total) is int and 0 <= total <= 10000 and total >= counts.get("unresolved_count", 0):
        counts["unresolved_total"] = total
    else:
        counts["availability"] = "partial"
    return counts


def _preparation(measurements, uncertain_lines, *, any_event, interrupted, terminal):
    attempts = [row for row in measurements if row["context"]]
    attempt = attempts[0] if attempts else None
    successful = [row for row in attempts if row["outcome"] == "succeeded"]
    first = min(successful, key=lambda row: (row["result_line"], row["index"])) if successful else None
    prefix = [row for row in measurements if first is None or row["line"] < first["result_line"]]
    preceding = [row for row in prefix if first is None or row["index"] < first["index"]]
    unknown = sum(not row["known"] for row in prefix)
    uncertain = (interrupted or any(line <= first["result_line"] for line in uncertain_lines)) if first else (interrupted or bool(uncertain_lines) or not terminal)
    counts = {kind: sum(kind in row["operations"] for row in preceding) for kind in ("read", "search", "explore")}
    investigated = sum(bool(row["operations"]) for row in preceding)
    before_result = sum(bool(row["operations"]) for row in prefix)
    writes = sum(row["project_write"] for row in preceding)
    writes_before_result = sum(row["project_write"] for row in prefix)
    guide_reads = sum(row["role_guides"] for row in preceding)
    guides_before_result = sum(row["role_guides"] for row in prefix)
    before_attempt = [row for row in measurements if attempt and row["index"] < attempt["index"]]
    early_unknown = interrupted or any(line <= attempt["line"] for line in uncertain_lines) if attempt else True
    attempt_events = sum(bool(row["operations"]) for row in before_attempt)
    attempt_writes = sum(row["project_write"] for row in before_attempt)
    attempt_guides = sum(row["role_guides"] for row in before_attempt)
    attempt_timing = ("late" if attempt_events or attempt_writes or attempt_guides else "unknown" if early_unknown or any(not row["known"] for row in before_attempt)
                      else "early" if attempt else "not_observed")
    if not attempt and any_event and not uncertain and not unknown:
        attempt_timing = "not_observed"
    status = ("after_investigation" if first and (before_result or writes_before_result or guides_before_result) else "unknown" if uncertain or unknown or not any_event
              else "before_investigation" if first else "not_observed")
    return {"schema_version": 1, "status": status,
            "availability": "unavailable" if not any_event else "partial" if uncertain or unknown else "complete",
            "first_context_call_event_line": first["line"] if first else None,
            "first_context_result_event_line": first["result_line"] if first else None,
            "first_context_attempt_event_line": attempt["line"] if attempt else None,
            "first_context_attempt_outcome": attempt["outcome"] if attempt else None,
            "attempt_timing": attempt_timing,
            "project_events_before_first_attempt": attempt_events,
            "project_writes_before_first_attempt": attempt_writes,
            "role_guide_reads_before_first_attempt": attempt_guides,
            "preceding_project_events": investigated, "preceding_project_events_by_operation": counts,
            "preceding_project_writes": writes,
            "preceding_role_guide_reads": guide_reads,
            "project_events_before_context_result": before_result,
            "project_writes_before_context_result": writes_before_result,
            "role_guide_reads_before_context_result": guides_before_result,
            "unknown_preceding_tool_calls": unknown,
            "exempt_instruction_events": sum(row["instructions"] for row in preceding),
            "exempt_package_events": sum(row["package"] for row in preceding),
            "note": "Visible event ordering only. Before means the first successful context result preceded project investigation, observed project writes, and selected role/body guide reads. Attempt timing separately preserves early denied or failed preparation. Mandatory instruction discovery and package entrypoint discovery are exempt; unsupported calls remain unknown. This is not a task-quality score."}


def analyze(client, stdout, binding, *, interrupted=False):
    """Return a private, sanitized-shape ledger; caller performs credential scrubbing."""
    from evals.end_to_end.adapters import _event_shape_errors
    result = empty("complete")
    calls, order, declarations, uncertain_lines = {}, [], [], []
    partial, terminal, any_event = interrupted, False, False

    def add(ident, name, inputs, line):
        nonlocal partial
        if not isinstance(ident, str) or not isinstance(name, str) or not isinstance(inputs, dict):
            partial = True
            uncertain_lines.append(line)
            return None
        if ident not in calls:
            calls[ident] = {"name": name.lower(), "inputs": inputs, "line": line,
                            "complete": False, "output": "", "error": None}
            order.append(ident)
        return calls[ident]

    def declare(text, line):
        for raw in text.splitlines():
            match = re.match(r"^\s*(?:→\s*|(?:\*\*)?Role(?:\*\*)?\s*:\s*)([^·|\n]+)", raw, re.I)
            if match:
                label = match[1].strip(" *_`.").lower()
                if label in binding.aliases:
                    declarations.append((binding.aliases[label], line))

    for line_number, line in enumerate(stdout.splitlines(), 1):
        if line_number > MAX_EVENTS:
            partial = True
            uncertain_lines.append(line_number)
            break
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            partial = True
            uncertain_lines.append(line_number)
            continue
        if not isinstance(event, dict):
            partial = True
            uncertain_lines.append(line_number)
            continue
        any_event = True
        if _event_shape_errors(client, event):
            partial = True
            uncertain_lines.append(line_number)
            continue
        kind = event.get("type")
        if client == "codex":
            if kind in {"turn.completed", "turn.failed"}:
                terminal = True
            item = event.get("item", {})
            if not isinstance(item, dict):
                partial = True
                uncertain_lines.append(line_number)
                continue
            if kind in {"item.started", "item.updated", "item.completed"}:
                if item.get("type") == "agent_message":
                    if kind == "item.completed":
                        declare(_text(item.get("text")), line_number)
                elif item.get("type") == "file_change":
                    changes = item.get("changes")
                    if not isinstance(changes, list):
                        partial = True
                        uncertain_lines.append(line_number)
                        continue
                    for index, change in enumerate(changes):
                        if not isinstance(change, dict) or not isinstance(change.get("path"), str):
                            partial = True
                            uncertain_lines.append(line_number)
                            continue
                        ident = str(item.get("id", "event-" + str(line_number))) + ":file:" + str(index)
                        call = add(ident, "write_file", {"path": change["path"]}, line_number)
                        if call:
                            status = item.get("status")
                            call.update(complete=kind == "item.completed", result_line=line_number, error=True if status == "failed" else False if status == "completed" else None,
                                        result_received=kind == "item.completed" and status == "completed")
                elif item.get("type") in {"command_execution", "tool_call", "mcp_tool_call"}:
                    name = "command_execution" if item["type"] == "command_execution" else item.get("tool", item.get("name"))
                    inputs = item if name == "command_execution" else item.get("arguments", {})
                    ident = str(item.get("id", "event-" + str(line_number)))
                    call = add(ident, name, inputs, line_number)
                    if call:
                        call.update(output=_text(item.get("aggregated_output", item.get("result", item.get("output")))),
                                    complete=kind == "item.completed", result_line=line_number, error=item.get("error", item.get("status") == "failed"),
                                    exit_code=item.get("exit_code"), result_received=kind == "item.completed")
        elif client == "claude":
            if kind == "result":
                terminal = True
                declare(_text(event.get("result")), line_number)
                for denial in event.get("permission_denials", []) if isinstance(event.get("permission_denials", []), list) else []:
                    if isinstance(denial, dict):
                        ident = denial.get("tool_use_id")
                        if isinstance(ident, str) and ident in calls:
                            calls[ident].update(denied=True, complete=True, result_line=line_number)
                        else:
                            call = add(str(ident or "denial-" + str(line_number)), denial.get("tool_name", "unknown"), denial.get("tool_input", {}), line_number)
                            if call:
                                call.update(denied=True, complete=True, result_line=line_number)
            if kind not in {"assistant", "user"}:
                continue
            message = event.get("message")
            if not isinstance(message, dict):
                partial = True
                uncertain_lines.append(line_number)
                continue
            blocks = message.get("content", [])
            if isinstance(blocks, str):
                blocks = [{"type": "text", "text": blocks}]
            if not isinstance(blocks, list):
                partial = True
                uncertain_lines.append(line_number)
                continue
            for block in blocks:
                if not isinstance(block, dict):
                    partial = True
                    uncertain_lines.append(line_number)
                    continue
                if kind == "assistant" and block.get("type") == "text":
                    declare(_text(block.get("text")), line_number)
                elif kind == "assistant" and block.get("type") == "tool_use":
                    add(block.get("id"), block.get("name"), block.get("input", {}), line_number)
                elif kind == "user" and block.get("type") == "tool_result":
                    ident = block.get("tool_use_id")
                    call = calls.get(ident) if isinstance(ident, str) else None
                    if call is None:
                        partial = True
                        uncertain_lines.append(line_number)
                        continue
                    extra = event.get("tool_use_result", {})
                    call.update(complete=True, result_received=True, result_line=line_number, output=_text(block.get("content")),
                                error=block.get("is_error"), exit_code=block.get("exit_code", extra.get("exit_code") if isinstance(extra, dict) else None))
    trace_partial = partial or not terminal
    guidance = []
    roles = set()
    summary = result["summary"]
    measurements, written = [], {}
    for call_index, ident in enumerate(order):
        call = calls[ident]
        inputs, name, outcome = call["inputs"], call["name"], _outcome(call)
        rows, attributable = [], True
        cwd = inputs.get("workdir", inputs.get("cwd", binding.workspace))
        if not isinstance(cwd, str) or not cwd or "\x00" in cwd:
            partial = True
            uncertain_lines.append(call["line"])
            continue
        cwd = _absolute_path(cwd, binding)
        if name in READ_TOOLS:
            row = _read_target(inputs.get("file_path", inputs.get("path")), binding, cwd)
            rows = [row] if row else []
            attributable = row is not None
        elif name in SEARCH_TOOLS | LIST_TOOLS:
            path = inputs.get("path", inputs.get("directory", "."))
            if not isinstance(path, str) or not path or "\x00" in path:
                attributable = False
            else:
                exempt = name == "glob" and _instruction_pattern(inputs.get("pattern"))
                rows = _investigation([path], binding, cwd, "search" if name in SEARCH_TOOLS else "explore", instructions_only=exempt)
        elif name in SHELL_TOOLS:
            rows, attributable = _shell_calls(inputs.get("command", inputs.get("cmd")), binding, cwd=cwd)
        elif name in WRITE_TOOLS:
            target, _ = _path(inputs.get("file_path", inputs.get("path")), binding, cwd)
            rows = [{"kind": "write", "target": target}] if target else []
            attributable = target is not None
        else:
            attributable = False
        measurements.append({"index": call_index, "line": call["line"], "result_line": call.get("result_line", call["line"]),
                             "outcome": outcome, "known": attributable and outcome != "unknown",
                             "context": any(row.get("helper") == "context" for row in rows),
                             "project_write": any(row["kind"] == "write" and row["target"].startswith("project/") for row in rows),
                             "role_guides": sum(row["kind"] == "guidance_read" and bool(row.get("role") or re.match(r"package/(?:lib/|references/skills/|skills/)", row["target"])) for row in rows) if outcome == "succeeded" else 0,
                             "operations": {row["operation"] for row in rows if row["kind"] == "project_investigation"},
                             "instructions": any(row["kind"] == "instruction_discovery" for row in rows),
                             "package": any(row["kind"] == "package_discovery" or (row["kind"] == "guidance_read" and not row.get("role") and not re.match(r"package/(?:lib/|references/skills/|skills/)", row["target"])) for row in rows)})
        if not attributable:
            partial = True
        if outcome == "unknown":
            partial = True
        if outcome == "denied":
            summary["permission_denials"] += 1
            if not rows:
                rows = [{"kind": "permission_denial", "target": "unattributed-tool"}]
        path_error = outcome == "failed" and bool(re.search(r"no such file|does not exist|file not found|cannot (?:open|read)|path.*not found", call["output"], re.I))
        if path_error:
            summary["failed_paths"] += 1
        if outcome == "succeeded" and rows and all(row["kind"] == "guidance_read" for row in rows):
            # A direct multi-file read has one returned stream. Count it once,
            # without pretending to know the individual file contributions.
            summary["guidance_returned_chars"] += len(call["output"])
        for row in rows:
            row.update(outcome=outcome, event_line=call["line"])
            if path_error:
                row["path_error"] = True
            if row["kind"] == "helper":
                summary["helper_attempts"] += 1
                if outcome == "succeeded":
                    summary["helper_successes"] += 1
                    try:
                        payload = json.loads(call["output"])
                    except ValueError:
                        payload = None
                    if isinstance(payload, dict):
                        if row["helper"] == "context":
                            row["context_exclusions"] = _context_exclusions(payload)
                        mapping = payload.get("project_map", payload)
                        if isinstance(mapping, dict) and mapping.get("status") in MAP_STATUSES:
                            row["map_status"] = mapping["status"]
                            if mapping.get("cache_status") in MAP_STATUSES:
                                row["map_cache_status"] = mapping["cache_status"]
                            if mapping.get("evidence_origin") in {"none", "stored", "preview"}:
                                row["map_evidence_origin"] = mapping["evidence_origin"]
                            if isinstance(mapping.get("entries"), list):
                                row["map_entries"] = len(mapping["entries"])
            if row["kind"] == "guidance_read" and outcome == "succeeded":
                summary["guidance_reads"] += 1
                guidance.append(row["target"])
                row["returned_chars"] = len(call["output"]) if len(rows) == 1 else None
                if row.get("role"):
                    roles.add(row["role"])
            if row["kind"] == "write" and outcome == "succeeded":
                summary["observed_writes"] += 1
                if row["target"].startswith("trial/"):
                    written[row["target"]] = call.get("result_line", call["line"])
            if row["kind"] == "cleanup_attempt":
                row["matched_prior_write"] = row["target"] in written and written[row["target"]] < call["line"]
            if len(result["actions"]) < MAX_ACTIONS:
                result["actions"].append(row)
            else:
                result["omitted_actions"] += 1
    declared = sorted({role for role, _ in declarations})
    summary.update(guidance_unique_paths=len(set(guidance)), guidance_repeated_reads=len(guidance) - len(set(guidance)),
                   roles_read=sorted(roles), declared_roles=declared)
    chosen = declared or sorted(roles)
    result["route"] = {"role": chosen[0] if len(chosen) == 1 else None,
                       "basis": "declaration" if declared else "role_read" if roles else "unknown",
                       "consistent": (len(chosen) == 1 and (not declared or not roles or set(declared) == roles)) if chosen else None,
                       "availability": "unavailable" if not chosen else "partial" if trace_partial or (not declared and partial) else "complete"}
    result["availability"] = "unavailable" if not any_event else "partial" if partial or not terminal or result["omitted_actions"] else "complete"
    result["preparation"] = _preparation(measurements, uncertain_lines, any_event=any_event, interrupted=interrupted, terminal=terminal)
    return result
