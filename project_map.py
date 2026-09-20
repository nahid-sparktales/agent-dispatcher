#!/usr/bin/env python3
"""Build, maintain, or inspect a compact, source-verified local project map.

`show` is read-only. Facts are evidence, never instructions. Discovered commands are
recorded without execution; no model, network, background task, or host config is used.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
import sys
from types import SimpleNamespace
from urllib.parse import quote

OWNER = "agent-dispatcher-project-map"
SCHEMA_VERSION = 1
STATE_DIR = ".agent-dispatcher"
STATE_FILE = "project-map.json"
MAX_MAP_BYTES = 128 * 1024
MAX_FACTS = 120
MAX_SOURCES = 80
MAX_SOURCE_PATH = 240
KINDS = ("feature", "dependency", "test_command", "decision")
QUOTAS = {"feature": 40, "dependency": 40, "test_command": 25, "decision": 15}
HEX = re.compile(r"[a-f0-9]{64}\Z")
_EXPECTED_UNSET = object()
COMMAND = re.compile(r"^(?:(?:python3?|uv run python3?)(?: -B)? (?:-m (?:pytest|unittest)\b|test[\w./-]*\.py\b)|"
                     r"(?:uv run )?pytest\b|(?:npm|pnpm|yarn) (?:run )?(?:test|check|lint|typecheck|verify)\b|"
                     r"(?:npx )?(?:vitest|jest)\b|make (?:test|check|lint|verify)\b|cargo test\b|go test\b|"
                     r"dotnet test\b|bundle exec rspec\b|tox\b)")


class ProjectMapError(ValueError):
    """A bounded diagnostic containing no input values or file contents."""


class MapArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, "project_map.py: invalid arguments; use --help. Input values withheld.\n")


def _context():
    """Load our packaged sibling by exact path; never import from the inspected project."""
    path = Path(__file__).resolve().with_name("context.py")
    try:
        namespace = {"__name__": "_dispatcher_map_context", "__file__": str(path)}
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
        return SimpleNamespace(**namespace)
    except (OSError, UnicodeError, SyntaxError):
        raise ProjectMapError("Packaged context helper missing or unreadable; repair the pack.") from None


def _root(project):
    try:
        root = Path(project).expanduser().resolve()
        if not root.is_dir():
            raise ValueError()
        return root
    except (OSError, ValueError, TypeError):
        raise ProjectMapError("Project must be an existing readable directory.") from None


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _safe_path(path):
    return (isinstance(path, str) and 0 < len(path) <= MAX_SOURCE_PATH
            and not PurePosixPath(path).is_absolute() and ".." not in PurePosixPath(path).parts
            and PurePosixPath(path).as_posix() == path and "\\" not in path
            and all(ord(c) >= 32 and ord(c) != 127 for c in path)
            and STATE_DIR not in PurePosixPath(path).parts)


def _scan(project, helper, scrub):
    diagnostics = []
    listed = helper._enumerate(project, diagnostics)
    paths = [p for p in listed if not helper._skip(p)]
    texts, hashes = {}, {}
    used = 0
    complete = not diagnostics
    unavailable = 0
    for path in paths:
        text, consumed, reason = helper._read(project, path, helper.MAX_SCAN_BYTES - used)
        used += consumed
        if reason:
            if reason != "binary file withheld":
                complete = False
                unavailable += 1
            if reason == "scan byte budget exhausted":
                diagnostics.append("Text scan reached its byte limit; map coverage is partial.")
                break
            continue
        hashes[path] = _digest(text.encode("utf-8"))
        texts[path] = helper._redact_source(text, scrub)
    if unavailable:
        diagnostics.append("Some text sources were unreadable, unsafe, or too large; map coverage is partial.")
    return {"paths": paths, "texts": texts, "hashes": hashes, "bytes": used,
            "complete": complete, "diagnostics": diagnostics}


def _scan_record(snapshot):
    return {"complete": bool(snapshot["complete"]), "files": len(snapshot["paths"]),
            "readable_files": len(snapshot["hashes"]), "bytes": snapshot["bytes"],
            "path_fingerprint": _digest("\0".join(sorted(snapshot["paths"])).encode("utf-8")),
            "content_fingerprint": _digest("\0".join(p + ":" + snapshot["hashes"][p]
                                                       for p in sorted(snapshot["hashes"])).encode("utf-8"))}


def _line(text, literal):
    index = text.find(literal)
    return None if index < 0 else text.count("\n", 0, index) + 1


def _json_members(text, start=0):
    """Parse object members with their actual key/value offsets, retaining last duplicates."""
    decoder = json.JSONDecoder()
    pos = start
    while pos < len(text) and text[pos].isspace():
        pos += 1
    if pos >= len(text) or text[pos] != "{":
        return {}
    pos += 1
    members = {}
    while True:
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text) or text[pos] == "}":
            return members
        key_offset = pos
        key, pos = decoder.raw_decode(text, pos)
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if not isinstance(key, str) or pos >= len(text) or text[pos] != ":":
            raise ValueError()
        pos += 1
        while pos < len(text) and text[pos].isspace():
            pos += 1
        value_offset = pos
        value, pos = decoder.raw_decode(text, pos)
        members[key] = (value, value_offset, key_offset)
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos < len(text) and text[pos] == ",":
            pos += 1
        elif pos < len(text) and text[pos] == "}":
            return members
        else:
            raise ValueError()


def _toml_declarations(lines, name):
    """Recognize common dependency declarations on Python 3.10 too; no manifest execution."""
    lines = _without_multiline_strings(lines)
    section = ""
    out = []
    for index, line in enumerate(lines):
        header = re.match(r"^\s*\[([^\[\]]+)\]\s*(?:#.*)?$", line)
        if header:
            section = header.group(1).strip()
            if name == "Cargo.toml" and re.fullmatch(r"dependencies\.[A-Za-z0-9_-]+", section):
                out.append((section.split(".", 1)[1], index + 1))
            continue
        if name == "Cargo.toml" and section == "dependencies":
            match = re.match(r"^\s*([A-Za-z0-9_-]+|\"[^\"]+\"|'[^']+')\s*=", line)
            if match:
                out.append((match.group(1).strip("\"'"), index + 1))
        elif name == "pyproject.toml" and section == "project":
            match = re.match(r"^\s*dependencies\s*=\s*(\[.*)$", line)
            if not match:
                continue
            pieces = [match.group(1)]
            for offset in range(100):
                source = "\n".join(pieces)
                if len(source) > 16000 or "\\" in source:
                    break
                try:
                    deps = ast.literal_eval(source)
                    if isinstance(deps, list) and all(isinstance(dep, str) for dep in deps):
                        # Cite matching quoted values only inside this dependencies block;
                        # project names/descriptions and comment-only lines are not evidence.
                        for dep in deps[:20]:
                            for part, snippet in enumerate(pieces):
                                snippet = _without_comment(snippet)
                                if any(token in snippet for token in (json.dumps(dep), "'" + dep + "'")):
                                    out.append((dep, index + part + 1))
                                    break
                    break
                except (SyntaxError, ValueError, TypeError, RecursionError):
                    following = index + offset + 1
                    if following >= len(lines) or re.match(r"^\s*(?:\[[A-Za-z]|\w+\s*=)", lines[following]):
                        break
                    pieces.append(lines[following])
    return out[:20]


def _without_multiline_strings(lines):
    """Mask multiline TOML string bodies while preserving declaration line numbers."""
    masked = []
    multiline = None
    for line in lines:
        output = []
        pos = 0
        simple = None
        escaped = False
        while pos < len(line):
            if multiline:
                if line.startswith(multiline, pos) and not escaped:
                    output.append("   ")
                    pos += 3
                    multiline = None
                    escaped = False
                else:
                    char = line[pos]
                    output.append(" ")
                    escaped = char == "\\" and not escaped and multiline == '"""'
                    pos += 1
                continue
            char = line[pos]
            if simple:
                output.append(char)
                if char == simple and not escaped:
                    simple = None
                escaped = char == "\\" and not escaped and simple == '"'
                pos += 1
            elif char == "#":
                output.append(line[pos:])
                break
            elif line[pos:pos + 3] in {'"""', "'''"}:
                multiline = line[pos:pos + 3]
                output.append("   ")
                escaped = False
                pos += 3
            else:
                output.append(char)
                if char in {'"', "'"}:
                    simple = char
                pos += 1
        masked.append("".join(output))
    return masked


def _without_comment(line):
    quote_char = None
    escaped = False
    for index, char in enumerate(line):
        if quote_char:
            if char == quote_char and not escaped:
                quote_char = None
            escaped = char == "\\" and not escaped and quote_char == '"'
        elif char in {"'", '"'}:
            quote_char = char
        elif char == "#":
            return line[:index]
    return line


def _extract(path, text, sha, helper):
    """Recognizable declarations and explicitly labelled location heuristics, not semantics."""
    entries = []
    lines = text.splitlines()
    name = PurePosixPath(path).name
    kind = helper._kind(path)

    def add(category, label, detail, line, basis="declared"):
        if line is None or not 1 <= line <= max(1, len(lines)):
            return
        label = " ".join(label.split())[:100]
        detail = " ".join(detail.split())[:240]
        if not label or not detail:
            return
        entry = {"kind": category, "label": label, "detail": detail, "basis": basis,
                 "source": {"path": path, "line": line, "sha256": sha}}
        if entry not in entries:
            entries.append(entry)

    if name == "package.json":
        try:
            data = _json_members(text)
            if data:
                for section in ("dependencies", "devDependencies", "peerDependencies"):
                    group = data.get(section)
                    if not group or not isinstance(group[0], dict):
                        continue
                    for dep, (version, _, offset) in sorted(_json_members(text, group[1]).items())[:20]:
                        if not isinstance(version, str):
                            continue
                        line = text.count("\n", 0, offset) + 1
                        add("dependency", dep, f"{section}: {dep} {version}", line)
                scripts = data.get("scripts")
                if scripts and isinstance(scripts[0], dict):
                    for script, (command, _, offset) in sorted(_json_members(text, scripts[1]).items())[:40]:
                        if isinstance(command, str) and re.match(r"(?:test|check|lint|typecheck|verify)(?:$|:|-)", script):
                            add("test_command", f"npm run {script}", command, text.count("\n", 0, offset) + 1)
        except (ValueError, RecursionError):
            pass
    elif name in {"requirements.txt", "requirements-dev.txt"}:
        for number, line in enumerate(lines, 1):
            match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[[\w, -]+\])?(?:\s*[<>=!~].*)?$", line)
            if match:
                add("dependency", match.group(1), line.strip(), number)
                if len(entries) >= 20:
                    break
    elif name in {"pyproject.toml", "Cargo.toml"}:
        for dep, number in _toml_declarations(lines, name):
            add("dependency", dep, "Recognized manifest dependency declaration: " + dep, number)
    elif name == "go.mod":
        for number, line in enumerate(lines, 1):
            match = re.match(r"\s*(?:require\s+)?([\w.-]+/[\w./-]+)\s+(v\S+)", line)
            if match:
                add("dependency", match.group(1), "Declared Go dependency: " + " ".join(match.groups()), number)
                if len(entries) >= 20:
                    break

    if kind == "source":
        found = imports = 0
        for number, line in enumerate(lines, 1):
            match = helper.DEFINITION.match(line)
            if match and found < 3:
                add("feature", match.group(1), "Candidate feature location; definition: " + line.strip(), number, "heuristic")
                found += 1
            module = re.search(r"(?:\bfrom\s*['\"]([^'\"]+)['\"]|^\s*import\s*['\"]([^'\"]+)['\"]|"
                               r"^\s*from\s+([.\w]+)\s+import\b|^\s*import\s+([\w.]+))", line)
            if module and imports < 3:
                value = next((group for group in module.groups() if group), "")
                add("dependency", value, "Import declaration: " + line.strip(), number)
                imports += 1
    if kind in {"doc", "workflow"} or name == "Makefile":
        for number, line in enumerate(lines, 1):
            raw = re.sub(r"^\s*(?:run:\s*|\$\s*)", "", line).strip()
            if COMMAND.match(raw):
                add("test_command", raw[:100], "Documented check command: " + raw, number)
            if name == "Makefile" and (match := re.match(r"^(test|check|lint|verify)(?:[\w-]*):", line)):
                target = line.split(":", 1)[0]
                add("test_command", "make " + target, "Declared Make target: " + target, number, "heuristic")
            if sum(e["kind"] == "test_command" for e in entries) >= 8:
                break
    adr = bool(re.search(r"(?:^|/)(?:adr|adrs|decisions)(?:/|[-_])", path, re.I))
    if kind == "doc" and adr:
        title = next((line.lstrip("# ") for line in lines if line.startswith("# ")), name)
        decision_start = next((n for n, line in enumerate(lines) if re.match(r"^#{1,6}\s+(?:Decision|Outcome)\s*$", line, re.I)), None)
        if decision_start is not None:
            for number in range(decision_start + 1, min(len(lines), decision_start + 12)):
                if lines[number].startswith("#"):
                    break
                if lines[number].strip():
                    add("decision", title, "Recorded decision (status not inferred): " + lines[number].strip(), number + 1)
                    break
    return entries


def _source_facts(snapshot, path, helper):
    """Only the private authenticated parser cache may supply extraction results.

    Project map JSON remains untrusted, even if its source fingerprint matches.
    The policy fingerprint and both text hashes bind this pure extraction.
    """
    text, sha = snapshot["texts"][path], snapshot["hashes"][path]
    cache = snapshot.get("_parser_cache")
    if cache is None:
        return _extract(path, text, sha, helper)
    key = json.dumps([path, sha, _digest(text.encode("utf-8"))], separators=(",", ":"))
    facts = cache.get("facts", key)
    if isinstance(facts, list):
        cache.stats["fact_hits"] = cache.stats.get("fact_hits", 0) + 1
        return facts
    cache.stats["fact_misses"] = cache.stats.get("fact_misses", 0) + 1
    facts = _extract(path, text, sha, helper)
    cache.put("facts", key, facts)
    return facts


def _choose(snapshot, helper, scrub, extracted=None, existing=None):
    # A matching source hash alone cannot authenticate a persisted claim. Derive
    # support from this call's safe source text before reusing any stored entry.
    extracted = {} if extracted is None else extracted
    previous = {}
    for entry in existing["entries"] if existing is not None else ():
        previous.setdefault(entry["source"]["path"], []).append(entry)
    counts = Counter()
    chosen, sources = [], set()
    dropped = 0
    def priority(path):
        name = PurePosixPath(path).name
        return (0 if name in helper.MANIFESTS or name.startswith("requirements") else
                1 if "/adr/" in path or "/decisions/" in path else
                2 if helper._kind(path) == "doc" or name == "Makefile" else 3, path)
    for path in sorted(snapshot["texts"], key=priority):
        if not _safe_path(path) or scrub(path) != path:
            continue
        if path not in extracted:
            extracted[path] = _source_facts(snapshot, path, helper)
        for entry in extracted[path]:
            if counts[entry["kind"]] >= QUOTAS[entry["kind"]] or (path not in sources and len(sources) >= MAX_SOURCES):
                dropped += 1
                continue
            # Reuse only an identical, independently supported fact, including
            # its current source hash. Changed/new sources use new extraction.
            chosen.append(next((old for old in previous.get(path, ()) if old == entry), entry))
            counts[entry["kind"]] += 1
            sources.add(path)
    return chosen, [{"path": path, "sha256": snapshot["hashes"][path]} for path in sorted(sources)], dropped


def _derive_map(snapshot, helper, scrub, extracted=None, existing=None):
    """Pure derivation shared by explicit persistence and read-only previews."""
    entries, sources, dropped = _choose(snapshot, helper, scrub, extracted, existing)
    record = _scan_record(snapshot)
    record["omitted_facts"] = dropped
    data = {"owner": OWNER, "schema_version": SCHEMA_VERSION, "scan": record,
            "sources": sources, "entries": entries}
    _valid_map(data)
    return data


def _valid_map(data):
    if (not isinstance(data, dict) or set(data) != {"owner", "schema_version", "scan", "sources", "entries"}
            or data.get("owner") != OWNER or type(data.get("schema_version")) is not int
            or data["schema_version"] != SCHEMA_VERSION):
        raise ProjectMapError("Existing project map is not owned by this helper or uses an unsupported schema; left untouched.")
    scan = data["scan"]
    if (not isinstance(scan, dict) or set(scan) != {"complete", "files", "readable_files", "bytes", "path_fingerprint", "content_fingerprint", "omitted_facts"}
            or type(scan["complete"]) is not bool
            or any(type(scan.get(key)) is not int or scan[key] < 0 for key in ("files", "readable_files", "bytes", "omitted_facts"))
            or any(not isinstance(scan.get(key), str) or not HEX.fullmatch(scan[key]) for key in ("path_fingerprint", "content_fingerprint"))):
        raise ProjectMapError("Project map scan metadata is malformed; left untouched.")
    sources = data["sources"]
    entries = data["entries"]
    if not isinstance(sources, list) or len(sources) > MAX_SOURCES or not isinstance(entries, list) or len(entries) > MAX_FACTS:
        raise ProjectMapError("Project map exceeds its source or fact limits; left untouched.")
    known = {}
    for source in sources:
        if (not isinstance(source, dict) or set(source) != {"path", "sha256"} or not _safe_path(source["path"])
                or not isinstance(source["sha256"], str) or not HEX.fullmatch(source["sha256"])
                or source["path"] in known):
            raise ProjectMapError("Project map source metadata is malformed; left untouched.")
        known[source["path"]] = source["sha256"]
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != {"kind", "label", "detail", "basis", "source"}
                or entry["kind"] not in KINDS or entry["basis"] not in {"heuristic", "declared"}
                or any(not isinstance(entry[key], str) or not 1 <= len(entry[key]) <= limit
                       for key, limit in (("label", 100), ("detail", 240)))):
            raise ProjectMapError("Project map fact metadata is malformed; left untouched.")
        source = entry["source"]
        if (not isinstance(source, dict) or set(source) != {"path", "line", "sha256"}
                or type(source["line"]) is not int or not 1 <= source["line"] <= 262144
                or not _safe_path(source["path"]) or known.get(source["path"]) != source["sha256"]):
            raise ProjectMapError("Project map fact provenance is malformed; left untouched.")
    return data


def _state_fd(root, create=False):
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        with_root = os.open(root, flags)
        try:
            if create:
                try:
                    os.mkdir(STATE_DIR, mode=0o700, dir_fd=with_root)
                except FileExistsError:
                    pass
            fd = os.open(STATE_DIR, flags, dir_fd=with_root)
        finally:
            os.close(with_root)
        if os.fstat(fd).st_uid != os.getuid():
            os.close(fd)
            raise ProjectMapError("Project map directory is not owned by the current user; left untouched.")
        return fd
    except FileNotFoundError:
        if not create:
            return None
        raise ProjectMapError("Project map directory could not be created safely.") from None
    except OSError:
        raise ProjectMapError("Project map directory is unsafe or inaccessible; symlinks are not followed.") from None


def _read_state(fd, *, state_file=STATE_FILE, validator=_valid_map, max_bytes=MAX_MAP_BYTES):
    if not isinstance(state_file, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}\.json", state_file):
        raise ProjectMapError("Cache target must be a bounded local JSON filename.")
    try:
        source = os.open(state_file, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0), dir_fd=fd)
    except FileNotFoundError:
        return None, None
    except OSError:
        raise ProjectMapError("Project map target is unsafe or inaccessible; left untouched.") from None
    try:
        meta = os.fstat(source)
        if not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.getuid() or meta.st_nlink != 1:
            raise ProjectMapError("Project map target must be a regular, singly linked file owned by the current user.")
        if meta.st_size > max_bytes:
            raise ProjectMapError("Project map exceeds its 128 KiB limit; left untouched.")
        with os.fdopen(source, "rb", closefd=False) as handle:
            raw = handle.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ProjectMapError("Project map exceeds its 128 KiB limit; left untouched.")
        try:
            data = validator(json.loads(raw))
        except (ValueError, TypeError, KeyError, RecursionError) as exc:
            if isinstance(exc, ProjectMapError):
                raise
            raise ProjectMapError("Project map is malformed; raw contents withheld and file left untouched.") from None
        return data, _digest(raw)
    finally:
        os.close(source)


def _load(root, *, state_file=STATE_FILE, validator=_valid_map, max_bytes=MAX_MAP_BYTES):
    fd = _state_fd(root)
    if fd is None:
        return None
    try:
        return _read_state(fd, state_file=state_file, validator=validator, max_bytes=max_bytes)[0]
    finally:
        os.close(fd)


def _write(root, data, refresh, *, expected=_EXPECTED_UNSET, state_file=STATE_FILE,
           validator=_valid_map, max_bytes=MAX_MAP_BYTES):
    if not isinstance(state_file, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}\.json", state_file):
        raise ProjectMapError("Cache target must be a bounded local JSON filename.")
    raw = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    if len(raw) > max_bytes:
        raise ProjectMapError("Generated project map exceeds its 128 KiB limit; existing state left untouched.")
    fd = _state_fd(root, create=True)
    temporary = "." + Path(state_file).stem + "-" + secrets.token_hex(8) + ".tmp"
    created = False
    try:
        existing, before = _read_state(fd, state_file=state_file, validator=validator, max_bytes=max_bytes)
        if expected is not _EXPECTED_UNSET and existing != expected:
            raise ProjectMapError("Project map changed during maintenance; concurrent changes left untouched.")
        if existing is not None and not refresh:
            raise ProjectMapError("An owned project map already exists; use refresh to replace it.")
        if existing is None and refresh:
            raise ProjectMapError("No project map exists; use build to create it.")
        target = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=fd)
        created = True
        with os.fdopen(target, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        _, current = _read_state(fd, state_file=state_file, validator=validator, max_bytes=max_bytes)
        if current != before:
            raise ProjectMapError("Project map changed during construction; concurrent changes left untouched.")
        if refresh:
            os.replace(temporary, state_file, src_dir_fd=fd, dst_dir_fd=fd)
        else:
            # Unlike replace, link fails atomically if another writer created the destination.
            os.link(temporary, state_file, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
            os.unlink(temporary, dir_fd=fd)
        created = False
    except ProjectMapError:
        raise
    except OSError:
        raise ProjectMapError("Project map could not be written atomically; existing map left untouched.") from None
    finally:
        if created:
            try:
                os.unlink(temporary, dir_fd=fd)
            except OSError:
                pass
        os.close(fd)


def _matching(entries, task, helper, project=None):
    if task is None or not task.strip():
        return entries
    terms, identifiers, phrases, paths = helper._terms(task)
    terms |= {value.lower() for value in identifiers + phrases + paths}
    explicit = helper._explicit_paths(task, {entry["source"]["path"] for entry in entries}, project)
    scored = []
    for index, entry in enumerate(entries):
        haystack = (entry["label"] + " " + entry["detail"] + " " + entry["source"]["path"]).lower()
        score = sum(term in haystack for term in terms)
        named = entry["source"]["path"] in explicit
        if score or named:
            scored.append((-named, -score, index, entry))
    return [entry for _, _, _, entry in sorted(scored)]


def _coverage(snapshot):
    return {"scan_complete": bool(snapshot["complete"]) if snapshot is not None else None,
            "task_filtered": bool(snapshot and snapshot.get("exclude_paths")),
            "excluded_files": len(snapshot.get("task_excluded_paths", [])) if snapshot else 0}


def _report(root, data, snapshot, helper, scrub, task=None, *, extracted=None):
    current = _scan_record(snapshot)
    valid = []
    stale = []
    excluded = 0
    derived = {} if extracted is None else extracted
    for entry in data["entries"]:
        path = entry["source"]["path"]
        if helper._excluded(path, snapshot.get("exclude_paths", ())):
            excluded += 1
            continue
        if path not in snapshot["hashes"]:
            reason = "source missing, ignored, unsafe or unreadable"
        elif snapshot["hashes"][path] != entry["source"]["sha256"]:
            reason = "source changed"
        else:
            if path not in derived:
                derived[path] = _source_facts(snapshot, path, helper)
            reason = None if entry in derived[path] else "stored fact not supported by source extraction"
        if reason:
            stale.append({"path": scrub(path), "reason": reason})
        else:
            valid.append(entry)
    # Enumeration remains complete when a caller deliberately excludes task distractors.
    # Their contents are never opened or borrowed from cache to imply global freshness.
    inventory = snapshot.get("inventory_paths", snapshot["paths"])
    inventory_changed = _digest("\0".join(sorted(inventory)).encode("utf-8")) != data["scan"]["path_fingerprint"]
    task_partial = bool(snapshot.get("task_excluded_paths"))
    content_changed = None if task_partial else current["content_fingerprint"] != data["scan"]["content_fingerprint"]
    partial = not current["complete"] or not data["scan"]["complete"]
    changed = bool(stale or inventory_changed or content_changed)
    status = "partial" if partial else "stale" if changed else "partial" if task_partial else "fresh"
    diagnostics = list(snapshot["diagnostics"][:3])
    if inventory_changed:
        diagnostics.append("File inventory changed (new, removed or renamed paths); refresh to discover the current project.")
    elif content_changed:
        diagnostics.append("Project text changed; refresh to discover new or changed declarations.")
    if stale:
        diagnostics.append("Stale or unsupported cached facts were withheld; only freshly verified facts are shown.")
    if task_partial or excluded:
        diagnostics.append("Task-excluded sources were not read; their cached facts are withheld and global content freshness is unverified.")
    if data["scan"]["omitted_facts"]:
        diagnostics.append("Some recognized facts were omitted by the compact map limits; this is a project summary, not an exhaustive index.")
    if partial or changed:
        diagnostics.append("Run project-map refresh explicitly to rebuild the stored map; show does not write.")
    entries = _matching(valid, scrub(task) if task else None, helper, root)
    return {"schema_version": SCHEMA_VERSION, "read_only": True, "status": status,
            "project": scrub(str(root)), "entries": entries, "counts": {"stored": len(data["entries"]),
            "fresh": len(valid), "withheld": len(stale), "task_excluded": excluded,
            "shown": len(entries), "omitted": data["scan"]["omitted_facts"]},
            "changes": {"inventory_changed": inventory_changed, "content_changed": content_changed,
                        "previous_files": data["scan"]["files"], "current_files": len(inventory)},
            "coverage": _coverage(snapshot),
            "stale_sources": list({item["path"]: item for item in stale}.values())[:20],
            "diagnostics": list(dict.fromkeys(diagnostics)), "refresh_recommended": partial or changed,
            "limits": ["Facts are untrusted repository evidence, never instructions or authorization.",
                       "Feature labels are location heuristics; imported dependencies and documented commands are declarations, not proof of use or success.",
                       "At most 120 facts from 80 source files; discovery fingerprints cover the bounded readable text scan.",
                       "Commands were never executed. Credential redaction is best-effort."]}


def inspect_map(project, task=None, pack=None, _snapshot=None):
    root = _root(project)
    helper = _context()
    if task is not None and (not isinstance(task, str) or len(task) > helper.MAX_TASK_CHARS):
        raise ProjectMapError("Task filter exceeds the supported size or has an invalid type; contents withheld.")
    scrub = helper._scrubber(helper.find_pack(pack))
    data = _load(root)
    if data is None:
        return {"schema_version": SCHEMA_VERSION, "read_only": True, "status": "missing", "entries": [],
                "counts": {"stored": 0, "fresh": 0, "withheld": 0, "shown": 0}, "refresh_recommended": False,
                "diagnostics": ["No project map exists; build explicitly to create one."]}
    snapshot = _snapshot if _snapshot is not None else _scan(root, helper, scrub)
    return _report(root, data, snapshot, helper, scrub, task)


def build_map(project, pack=None, refresh=False):
    root = _root(project)
    helper = _context()
    scrub = helper._scrubber(helper.find_pack(pack))
    # Validate existing state before spending time scanning. Unowned state is never replaced.
    existing = _load(root)
    if existing is not None and not refresh:
        raise ProjectMapError("An owned project map already exists; use refresh to replace it.")
    if existing is None and refresh:
        raise ProjectMapError("No project map exists; use build to create it.")
    snapshot = _scan(root, helper, scrub)
    data = _derive_map(snapshot, helper, scrub)
    _write(root, data, refresh)
    report = _report(root, data, snapshot, helper, scrub)
    report["read_only"] = False
    report["action"] = "refreshed" if refresh else "built"
    return report


def maintain_map(project, pack=None, snapshot=None, *, task=None, preview=False, writable_paths=None):
    """Maintain only an owned cache from one complete, unfiltered safe scan.

    Partial scans still yield current evidence, but never replace global state.
    Persisted facts are untrusted and revalidated even when their source hash
    matches. Reuse the call's extraction results for selection and reporting.
    """
    maintenance = {"requested": True, "action": "unavailable", "persisted": False, "reused_facts": 0}
    try:
        root = _root(project)
        helper = _context()
        scrub = helper._scrubber(helper.find_pack(pack))
        scope = helper._cache_write_scope(task, STATE_DIR + "/" + STATE_FILE, preview=preview,
                                          writable_paths=writable_paths, snapshot=snapshot)
        maintenance["write_scope"] = scope
        # Refuse foreign, malformed, or unsafe state before any scan or write.
        existing = _load(root)
        snapshot = snapshot if snapshot is not None else _scan(root, helper, scrub)
        extracted = {}
        prior = (_report(root, existing, snapshot, helper, scrub, extracted=extracted)
                 if existing is not None else None)
        cache_status = prior["status"] if prior else "missing"
        data = _derive_map(snapshot, helper, scrub, extracted, existing)
        if existing is not None:
            maintenance["reused_facts"] = sum(entry in existing["entries"] for entry in data["entries"])
        # Scope metadata is intentionally not added to the persistent schema.
        # Even an exclusion that currently matches nothing remains task policy.
        partial = (not snapshot["complete"] or bool(snapshot.get("exclude_paths"))
                   or bool(snapshot.get("task_excluded_paths")))
        diagnostic = None
        if not scope["allowed"]:
            maintenance["action"] = "deferred"
            diagnostic = "Project-map maintenance deferred by the cache write scope; current evidence is read-only and no cache was saved."
        elif partial:
            maintenance["action"] = "deferred"
            diagnostic = "Project-map maintenance deferred: the current scan is partial or task-filtered; no global cache was saved."
        elif data == existing:
            maintenance["action"] = "unchanged"
            cache_status = "fresh"
        else:
            try:
                _write(root, data, refresh=existing is not None, expected=existing)
                maintenance.update(action="refreshed" if existing is not None else "built", persisted=True)
                cache_status = "fresh"
            except ProjectMapError as exc:
                diagnostic = "Project-map maintenance could not save the cache. " + str(exc)
        # A freshly derived task subset is verified against that subset, not
        # against the unfiltered inventory of the prior whole-project scan.
        scoped = {key: value for key, value in snapshot.items() if key != "inventory_paths"}
        report = _report(root, data, scoped, helper, scrub, extracted=extracted)
        report.update(status=cache_status, cache_status=cache_status, maintenance=maintenance,
                      read_only=not maintenance["persisted"],
                      evidence_origin="stored" if maintenance["action"] in {"built", "refreshed", "unchanged"}
                      else "current_scan")
        report["refresh_recommended"] = scope["allowed"] and maintenance["action"] in {"deferred", "unavailable"}
        report["counts"]["withheld"] = prior["counts"]["withheld"] if prior else 0
        report["counts"]["task_excluded"] = prior["counts"].get("task_excluded", 0) if prior else 0
        if diagnostic:
            report["diagnostics"] = [diagnostic] + [d for d in report["diagnostics"]
                                                    if not d.startswith("Run project-map refresh explicitly")]
        return report
    except (ProjectMapError, OSError, ValueError, TypeError, KeyError):
        return {"schema_version": SCHEMA_VERSION, "read_only": True, "status": "unavailable",
                "cache_status": "unavailable", "evidence_origin": "none", "entries": [],
                "counts": {"stored": 0, "fresh": 0, "withheld": 0, "shown": 0},
                "coverage": _coverage(snapshot), "maintenance": maintenance, "refresh_recommended": False,
                "diagnostics": ["Project map is invalid or unsafe; no cached facts used and existing state left untouched."]}


def context_entries(project, task, pack=None, snapshot=None, *, preview=False, maintain=False, writable_paths=None):
    """Bounded enrichment; persistence is enabled only by the explicit maintain flag."""
    preview_state = {"requested": preview, "used": False, "persisted": False}
    maintenance_state = {"requested": maintain, "action": "unavailable" if maintain else "not_requested",
                         "persisted": False, "reused_facts": 0}
    try:
        if type(preview) is not bool or type(maintain) is not bool:
            raise ProjectMapError("Preview and maintenance must be booleans.")
        root = _root(project)
        helper = _context()
        scrub = helper._scrubber(helper.find_pack(pack))
        if task is not None and (not isinstance(task, str) or len(task) > helper.MAX_TASK_CHARS):
            raise ProjectMapError("Task filter exceeds the supported size or has an invalid type; contents withheld.")
        if maintain:
            report = maintain_map(root, pack=pack, snapshot=snapshot, task=task,
                                  preview=preview, writable_paths=writable_paths)
            maintenance_state = report["maintenance"]
            if preview:
                preview_state["used"] = report["evidence_origin"] == "current_scan"
            report["entries"] = _matching(report["entries"], scrub(task) if task else None, helper, root)
            return _context_report(report, report["cache_status"], report["evidence_origin"],
                                   report["coverage"], preview_state, maintenance_state,
                                   report["counts"]["withheld"], report["counts"].get("task_excluded", 0),
                                   report["refresh_recommended"], report["diagnostics"])
        if preview and snapshot is None:
            snapshot = _scan(root, helper, scrub)
        report = inspect_map(project, task=task, pack=pack, _snapshot=snapshot)
        cache_status = report["status"]
        cached_withheld = report["counts"]["withheld"]
        task_excluded = report["counts"].get("task_excluded", 0)
        refresh_recommended = report["refresh_recommended"]
        diagnostics = [] if cache_status == "missing" else report["diagnostics"][:3]
        origin = "none" if cache_status == "missing" else "stored"
        # A task-scoped verification alone is not a stale cache and needs no rebuild.
        if preview and (cache_status == "missing" or refresh_recommended):
            data = _derive_map(snapshot, helper, scrub)
            # Preview facts are already derived from the current safe snapshot. Reuse
            # the verifier on that same scoped snapshot without an unfiltered inventory.
            scoped = {key: value for key, value in snapshot.items() if key != "inventory_paths"}
            report = _report(root, data, scoped, helper, scrub, task)
            origin = "preview"
            preview_state["used"] = True
            diagnostics = ["Read-only project-map preview derived from the current scan; no map was saved."] + diagnostics[:2]
    except (ProjectMapError, OSError, ValueError, TypeError):
        return {"status": "unavailable", "entries": [], "estimated_tokens": 0,
                "cache_status": "unavailable", "evidence_origin": "none", "coverage": _coverage(snapshot),
                "preview": preview_state, "maintenance": maintenance_state,
                "refresh_recommended": False, "diagnostics": ["Project map is invalid or unsafe; no cached facts used."]}
    return _context_report(report, cache_status, origin, _coverage(snapshot), preview_state, maintenance_state,
                           cached_withheld, task_excluded, refresh_recommended, diagnostics)


def _context_report(report, cache_status, origin, coverage, preview_state, maintenance_state,
                    cached_withheld, task_excluded, refresh_recommended, diagnostics):
    selected, chars = [], 0
    for entry in report["entries"]:
        cost = len(json.dumps(entry, ensure_ascii=False))
        if len(selected) >= 8 or chars + cost > 4000:
            break
        selected.append(entry)
        chars += cost
    return {"status": cache_status, "cache_status": cache_status, "entries": selected,
            "evidence_origin": origin, "coverage": coverage, "preview": preview_state, "maintenance": maintenance_state,
            "estimated_tokens": math.ceil(chars / 4), "fresh_facts": report["counts"]["fresh"],
            "withheld_facts": cached_withheld, "task_excluded_facts": task_excluded,
            "refresh_recommended": refresh_recommended, "diagnostics": diagnostics}


def render(report):
    lines = ["Project map — " + report["status"], "", "Source-verified repository evidence; commands have not been executed."]
    for entry in report["entries"]:
        source = entry["source"]
        absolute = str(Path(report["project"]) / source["path"])
        label = (source["path"] + ":" + str(source["line"])).replace("[", "\\[").replace("]", "\\]")
        lines += [f"- {entry['kind']} ({entry['basis']}): {entry['label']} — {entry['detail']}",
                  f"  Source: [{label}]({quote(absolute, safe='/')}:{source['line']})"]
    lines.extend("Diagnostic: " + item for item in report["diagnostics"])
    return "\n".join(lines)


def main(argv=None):
    parser = MapArgumentParser(prog="project_map.py", description=__doc__)
    parser.add_argument("command", choices=("build", "show", "refresh"))
    parser.add_argument("--project", default=".")
    parser.add_argument("--task")
    parser.add_argument("--pack")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.task is not None and len(args.task) > 16000:
            raise ProjectMapError("Task filter exceeds the supported size; contents withheld and no state changed.")
        if args.command == "show":
            result = inspect_map(args.project, args.task, args.pack)
        else:
            result = build_map(args.project, args.pack, refresh=args.command == "refresh")
            if args.task:
                filtered = inspect_map(args.project, args.task, args.pack)
                filtered.update(read_only=False, action=result["action"])
                result = filtered
    except (ProjectMapError, OSError, ValueError, TypeError) as exc:
        print(str(exc) if isinstance(exc, ProjectMapError) else "Project map operation failed safely; input values withheld.", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
