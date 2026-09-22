"""Historical repository memory: eligible commits, admitted changes, lineage and hotspots.

Everything here reads Git through one hardened wrapper: argument arrays, a scrubbed
environment, no pager, no external diff or textconv, no replacement objects, no lazy fetch,
no prompt, strict byte and time limits, and NUL-framed output that is validated field by
field. Nothing checks out, resets, applies or fetches. Only a commit reachable from the
trusted boundary (the current HEAD, resolved once per operation) can become an event, and only
the bounded window of the newest eligible commits is enumerated: never `--all`, reflogs, tags
or an arbitrary object id a caller happens to know.

Historical paths pass the same admission policy as current source (credential names,
generated directories, task exclusions) on both sides of a change before a blob id is kept.
Messages, paths and patch text are redacted before they are stored or shown. A commit record
is an observation that a change happened; its message is prose, not proof of anything.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
import difflib
import math
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import shutil
import subprocess
import time
import warnings

SCHEMA = 1
HEX = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
MAX_SUBJECT = 200
MAX_BODY = 1500
MAX_CHANGES = 200  # Changes kept per event; the total is still recorded.
MAX_REFS = 12
MAX_HUNKS = 12
MAX_HUNK_LINES = 60
MAX_SYMBOLS = 60  # Changed symbols kept per file per event.
LIMITS = {"seconds": 30, "bytes": 32 * 1024 * 1024, "blob_bytes": 256 * 1024, "parsed_bytes": 16 * 1024 * 1024}
_RAW = re.compile(rb"^:(\d{6}) (\d{6}) ([0-9a-f]{40,64}) ([0-9a-f]{40,64}) ([ACDMRTUX])(\d{0,3})$")
_ZERO = re.compile(r"0+\Z")
_PR_MERGE = re.compile(r"^Merge pull request #(\d{1,7})")
_PR_SQUASH = re.compile(r"\(#(\d{1,7})\)\s*$")
_FIX = re.compile(r"\b(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?)\s*:?\s+(?:#|GH-)(\d{1,7})\b", re.I)
_URL_REF = re.compile(r"https?://[^\s/]+/([\w.-]+)/([\w.-]+)/(issues|pull)/(\d{1,7})")
_MENTION = re.compile(r"(?<![\w/#])#(\d{1,7})\b")
_REVERT = re.compile(r"This reverts commit ([0-9a-f]{7,64})")
_EMAIL = re.compile(r"<[^<>\s]+@[^<>\s]+>")
_TRAILER = re.compile(r"^[A-Za-z][A-Za-z-]{1,40}: .*@.*$")
_RELEASE = re.compile(r"^(?:release|bump|version|chore\(release\)|prepare release|v?\d+\.\d+(?:\.\d+)?\b)", re.I)
_FIXWORD = re.compile(r"\b(?:fix(?:es|ed)?|bug|regression|crash|hotfix)\b", re.I)


class HistoryError(ValueError):
    """Bounded diagnostic; never echoes repository content, paths or object ids."""


_SIBLINGS = {}


def _sibling(name):
    """Packaged code by exact path; never an import that could resolve inside the inspected project."""
    if name not in _SIBLINGS:
        path = Path(__file__).resolve().with_name(name + ".py")
        namespace = {"__name__": "_dispatcher_history_" + name, "__file__": str(path)}
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
        _SIBLINGS[name] = namespace
    return _SIBLINGS[name]


def safe_path(path):
    return (isinstance(path, str) and 0 < len(path) <= 4096 and not PurePosixPath(path).is_absolute()
            and PurePosixPath(path).as_posix() == path and "\\" not in path
            and not any(part in {"", ".", ".."} for part in path.split("/"))
            and not any(ord(c) < 32 or ord(c) == 127 for c in path))


# ---------------------------------------------------------------- hardened git invocation


def git(project, args, *, seconds=LIMITS["seconds"], limit=LIMITS["bytes"], stdin=None):
    """Run one read-only Git command with strict limits -> (stdout bytes, exit code, hit a limit).

    Defense in depth against a repository that configures helpers: external diff, textconv and
    pagers are disabled on the command line, `GIT_*` environment is dropped, replacement objects
    are ignored, lazy fetching of promisor objects is refused (Git 2.46+, ignored earlier), and no
    credential prompt can open. The caller passes an argument array; nothing is shell-parsed.
    """
    executable = shutil.which("git")
    if not executable:
        raise HistoryError("Git is unavailable.")
    root = Path(project)
    if not root.is_absolute() or not root.is_dir():
        raise HistoryError("Repository path must be an existing absolute directory.")
    if not isinstance(args, (list, tuple)) or not args or any(not isinstance(a, str) or "\0" in a for a in args):
        raise HistoryError("Invalid Git argument vector.")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1",
                "GIT_PAGER": "cat", "PAGER": "cat", "GIT_ASKPASS": "", "SSH_ASKPASS": ""})
    command = [executable, "--no-replace-objects", "-C", str(root),
               "-c", "core.fsmonitor=false", "-c", "core.quotepath=off", "-c", "core.pager=cat",
               "-c", "diff.external=", "-c", "diff.noprefix=false", "-c", "core.abbrev=40",
               "-c", "protocol.allow=never", *args]
    try:
        process = subprocess.Popen(command, cwd=root, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
    except OSError:
        raise HistoryError("Git could not be started.") from None
    output, limited = bytearray(), False
    deadline = time.monotonic() + seconds
    try:
        if stdin is not None:
            try:
                process.stdin.write(stdin)  # Bounded payloads only (a few KiB of object ids).
                process.stdin.close()
            except OSError:
                pass
        with selectors.DefaultSelector() as ready:
            ready.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    limited = True
                    break
                if not ready.select(min(remaining, 0.25)):
                    continue
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > limit:
                    del output[limit:]
                    limited = True
                    break
        if limited:
            process.kill()
        code = process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        process.kill()
        process.wait()
        raise HistoryError("Git did not finish within its limits.") from None
    finally:
        process.stdout.close()
    return bytes(output), code, limited


def repository(project):
    """Resolve the trusted history boundary (HEAD) once, plus what kind of clone this is."""
    info = {"available": False, "boundary": None, "object_format": None, "shallow": False, "partial": False, "reason": None}
    try:
        out, code, _ = git(project, ["rev-parse", "--verify", "--quiet", "HEAD^{commit}"], seconds=10, limit=4096)
    except HistoryError as exc:
        info["reason"] = str(exc)
        return info
    head = out.decode("ascii", "replace").strip()
    if code != 0 or not HEX.fullmatch(head):
        info["reason"] = "no commit history (not a Git repository, or an unborn HEAD)"
        return info
    info.update(available=True, boundary=head, object_format="sha256" if len(head) == 64 else "sha1")
    try:
        out, code, _ = git(project, ["rev-parse", "--is-shallow-repository"], seconds=10, limit=4096)
        info["shallow"] = code == 0 and out.strip() == b"true"
        out, code, _ = git(project, ["config", "--get-regexp", r"^(extensions\.partialclone|remote\..*\.promisor)$"], seconds=10, limit=65536)
        info["partial"] = code == 0 and bool(out.strip())
    except HistoryError:
        pass
    return info


def is_ancestor(project, older, newer):
    if not (HEX.fullmatch(older or "") and HEX.fullmatch(newer or "")):
        return False
    try:
        return git(project, ["merge-base", "--is-ancestor", older, newer], seconds=10, limit=4096)[1] == 0
    except HistoryError:
        return False


def count_commits(project, boundary, max_commits):
    try:
        out, code, _ = git(project, ["rev-list", "--count", f"--max-count={int(max_commits)}", boundary], seconds=20, limit=4096)
        return int(out.strip()) if code == 0 else None
    except (HistoryError, ValueError):
        return None


# ---------------------------------------------------------------- event enumeration


def _parse_log(raw):
    """NUL-framed `git log --format=%x00%H%x00%P%x00%ct%x00%at%x00%B --raw -z` -> records, malformed count.

    Every record is `"" H P ct at message [raw-entry path [path]]...`; the empty token comes from
    the format's leading %x00 and can only appear there (a path or raw line is never empty, a
    message cannot contain NUL). A record that breaks the grammar is dropped, counted, and parsing
    resynchronizes at the next empty token: nothing is guessed from a broken frame.
    """
    tokens = raw.split(b"\0")
    records, malformed, i, n = [], 0, 0, len(tokens)
    while i < n:
        if tokens[i] != b"":
            malformed += 1
            while i < n and tokens[i] != b"":
                i += 1
            continue
        while i < n and tokens[i] == b"":
            i += 1
        if i >= n:
            break
        if i + 5 > n:
            malformed += 1
            break
        head, parents, committed, authored, message = tokens[i:i + 5]
        i += 5
        try:
            head, parents = head.decode("ascii"), parents.decode("ascii").split()
            committed, authored = int(committed), int(authored)
            if not HEX.fullmatch(head) or any(not HEX.fullmatch(p) for p in parents):
                raise ValueError()
        except (UnicodeError, ValueError):
            malformed += 1
            while i < n and tokens[i] != b"":
                i += 1
            continue
        changes, broken = [], False
        while i < n and tokens[i] != b"":
            match = _RAW.match(tokens[i].lstrip(b"\n"))
            count = 2 if match and match.group(5) in (b"R", b"C") else 1
            if not match or i + count >= n or any(tokens[i + k] == b"" for k in range(1, count + 1)):
                broken = True
                break
            changes.append((match.group(1).decode(), match.group(2).decode(), match.group(3).decode(), match.group(4).decode(),
                            match.group(5).decode(), int(match.group(6) or 0), tokens[i + 1:i + 1 + count]))
            i += 1 + count
        if broken:
            malformed += 1
            while i < n and tokens[i] != b"":
                i += 1
            continue
        records.append({"id": head, "parents": parents, "ct": committed, "at": authored, "message": message, "changes": changes})
    return records, malformed


def sanitize_message(message, scrub, *, max_subject=MAX_SUBJECT, max_body=MAX_BODY):
    """Redacted, bounded subject and body: no e-mail addresses, no trailer identities, no control bytes."""
    text = message.decode("utf-8", "replace") if isinstance(message, bytes) else str(message)
    text = "".join(c for c in text if c in "\n\t" or ord(c) >= 32 and ord(c) != 127)
    lines = [line.rstrip() for line in text.split("\n") if not _TRAILER.match(line.strip())]
    lines = [_EMAIL.sub("<redacted>", line) for line in lines]
    subject = scrub(lines[0].strip() if lines else "")[:max_subject]
    body = scrub("\n".join(lines[1:]).strip())[:max_body]
    return subject, body


def references(subject, body):
    """Issue/PR references with their link kind: a mention is never a proven fix."""
    strength = {"declares_fix": 3, "merges": 2, "squashed": 2, "mentions": 1}
    found = {}

    def note(number, kind, link, owner=None, repo=None):
        key = (owner, repo, number)
        if key not in found or strength[link] > strength[found[key]["link"]]:
            found[key] = {"kind": kind, "number": number, "link": link, "repository": f"{owner}/{repo}" if owner else None}

    text = subject + "\n" + body
    match = _PR_MERGE.match(subject)
    if match:
        note(int(match.group(1)), "pr", "merges")
    match = _PR_SQUASH.search(subject)
    if match:
        note(int(match.group(1)), "pr", "squashed")
    for match in _FIX.finditer(text):
        note(int(match.group(1)), "issue", "declares_fix")
    for owner, repo, kind, number in _URL_REF.findall(text):
        note(int(number), "issue" if kind == "issues" else "pr", "mentions", owner, repo)
    for match in _MENTION.finditer(text):
        note(int(match.group(1)), "unknown", "mentions")
    rows = sorted(found.values(), key=lambda r: (-strength[r["link"]], r["number"]))
    return rows[:MAX_REFS]


def _event(record, admit, scrub, *, max_commit_files, max_changes=MAX_CHANGES):
    """One eligible commit as a bounded, sanitized observation."""
    changes, withheld, omitted = [], 0, 0
    for old_mode, new_mode, old, new, status, score, raw_paths in record["changes"]:
        if "160000" in (old_mode, new_mode) or "120000" in (old_mode, new_mode):
            omitted += 1  # Submodules and symlinks carry no readable source.
            continue
        try:
            paths = [p.decode("utf-8") for p in raw_paths]
        except UnicodeError:
            withheld += 1
            continue
        # Both sides of a change must be admitted: a credential file renamed to a harmless name stays withheld.
        if any(not safe_path(p) or admit(p) is not None or scrub(p) != p for p in paths):
            withheld += 1
            continue
        entry = {"path": paths[-1], "kind": status, "old": None if _ZERO.fullmatch(old) else old, "new": None if _ZERO.fullmatch(new) else new}
        if status in ("R", "C"):
            entry.update({"from": paths[0], "score": score or 100})
        changes.append(entry)
    subject, body = sanitize_message(record["message"], scrub)
    revert = _REVERT.search(body)
    event = {"id": record["id"], "parents": record["parents"], "ct": record["ct"], "at": record["at"],
             "subject": subject, "body": body, "changes": changes[:max_changes], "total_changes": len(changes),
             "withheld": withheld, "omitted": omitted, "merge": len(record["parents"]) > 1,
             "bulk": len(changes) > max_commit_files, "release": bool(_RELEASE.match(subject)),
             "revert_of": revert.group(1) if revert and subject.startswith("Revert ") else None,
             "refs": references(subject, body)}
    event["completeness"] = ("metadata_only" if event["merge"] or not changes else
                             "truncated" if len(changes) > max_changes else "full")
    return event


def enumerate_events(project, boundary, *, admit, scrub, max_commits, max_commit_files, inclusive=True,
                     since=None, seconds=LIMITS["seconds"], limit=LIMITS["bytes"]):
    """Eligible events, newest first, from the boundary's own ancestry only.

    `since` (an older boundary) enumerates `since..boundary` for an incremental refresh. Merge
    commits are metadata-only events: their first-parent diff would repeat the non-merge commits
    that are indexed individually, so a logical change is attributed once. Conflict-resolution
    edits made in a merge are therefore not attributed to files (documented limitation).
    """
    if not HEX.fullmatch(boundary or "") or (since is not None and not HEX.fullmatch(since)):
        raise HistoryError("History boundary must be a resolved commit id.")
    target = f"{since}..{boundary}" if since else boundary
    args = ["log", target, f"-n{int(max_commits)}", "--format=%x00%H%x00%P%x00%ct%x00%at%x00%B", "--raw", "--no-abbrev",
            "-M", "-z", "--no-color", "--no-ext-diff", "--no-textconv", "--relative"]
    if not inclusive:
        args.append("--skip=1")
    raw, code, limited = git(project, args, seconds=seconds, limit=limit)
    if code != 0 and not limited:
        raise HistoryError("Git history could not be read.")
    if limited:  # Never trust a cut frame: drop everything after the last complete record.
        raw = raw[:raw.rfind(b"\0\0")] if b"\0\0" in raw else b""
    records, malformed = _parse_log(raw)
    events = [_event(r, admit, scrub, max_commit_files=max_commit_files) for r in records]
    return events, {"malformed": malformed, "truncated": limited, "count": len(events)}


# ---------------------------------------------------------------- blobs, diffs, symbols


def read_blobs(project, ids, *, scrub, max_bytes=LIMITS["blob_bytes"], seconds=LIMITS["seconds"]):
    """{blob id: (redacted text | None, reason)} for validated ids, sizes checked before bytes are read."""
    wanted = [i for i in dict.fromkeys(ids) if HEX.fullmatch(i)]
    out = {i: (None, "invalid object id") for i in ids if i not in wanted}
    if not wanted:
        return out
    payload = "".join(i + "\n" for i in wanted).encode("ascii")
    check, code, _ = git(project, ["cat-file", "--batch-check"], stdin=payload, seconds=seconds, limit=1024 * 1024)
    sizes = {}
    for line in check.decode("ascii", "replace").split("\n"):
        parts = line.split()
        if len(parts) == 3 and parts[1] == "blob" and parts[2].isdigit():
            sizes[parts[0]] = int(parts[2])
        elif len(parts) >= 1 and parts[0] in wanted:
            out[parts[0]] = (None, "object missing or not a blob")
    readable = [i for i in wanted if i in sizes and sizes[i] <= max_bytes]
    for i in wanted:
        if i in sizes and sizes[i] > max_bytes:
            out[i] = (None, "blob exceeds the read limit")
        elif i not in sizes and i not in out:
            out[i] = (None, "object missing or not a blob")
    if not readable:
        return out
    total = sum(sizes[i] for i in readable) + len(readable) * 128
    raw, code, limited = git(project, ["cat-file", "--batch"], stdin="".join(i + "\n" for i in readable).encode("ascii"),
                             seconds=seconds, limit=max(total, 4096))
    position, context = 0, _sibling("context")
    while position < len(raw):
        end = raw.find(b"\n", position)
        if end < 0:
            break
        header = raw[position:end].decode("ascii", "replace").split()
        position = end + 1
        if len(header) != 3 or not header[2].isdigit():
            break
        size, blob = int(header[2]), header[0]
        data = raw[position:position + size]
        position += size + 1
        if len(data) != size:
            out[blob] = (None, "blob read was cut short")
            continue
        if b"\0" in data:
            out[blob] = (None, "binary file withheld")
            continue
        try:
            out[blob] = (context["_redact_source"](data.decode("utf-8"), scrub), None)
        except UnicodeError:
            out[blob] = (None, "non-UTF-8 file withheld")
    for i in readable:
        out.setdefault(i, (None, "blob unavailable"))
    return out


def _python_spans(text):
    """(qualified name, kind, first line incl. decorators, last line) for every definition, nested included."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        tree = ast.parse(text)
    spans, pending = [], [(node, "") for node in tree.body]
    while pending:
        node, parent = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            name = f"{parent}.{node.name}" if parent else node.name
            kind = "class" if isinstance(node, ast.ClassDef) else "method" if parent else "function"
            spans.append((name, kind, start, node.end_lineno or node.lineno))
            pending.extend((child, name) for child in node.body)
        elif isinstance(node, (ast.If, ast.Try)) and not parent:
            pending.extend((child, parent) for child in node.body)
    return spans


def _generic_spans(path, text):
    defs = _sibling("repo_index")["_generic_facts"](path, text)[0]
    rows = sorted(defs, key=lambda row: row[2])
    total = text.count("\n") + 1
    spans = []
    for position, (name, kind, line, _, _) in enumerate(rows):
        end = rows[position + 1][2] - 1 if position + 1 < len(rows) else total
        spans.append((name, kind, line, max(line, end)))
    return spans


def spans_of(path, text):
    """Definition spans with their confidence: Python from the AST, other languages from declaration lines."""
    if path.endswith(".py"):
        try:
            return _python_spans(text), "ast"
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            return [], "parse_error"
    return _generic_spans(path, text), "heuristic"


def _own_lines(spans):
    """Lines a definition owns itself: its span minus nested definitions, so a change inside one method
    does not mark its class or sibling methods as changed."""
    owned = {}
    for name, kind, start, end in spans:
        lines = set(range(start, end + 1))
        for other, _, s, e in spans:
            if other != name and s >= start and e <= end and (s, e) != (start, end):
                lines -= set(range(s, e + 1))
        owned[(name, kind)] = lines
    return owned


def changed_symbols(path, old_text, new_text):
    """Definitions textually intersected by the change between two admitted versions of one file.

    Overlap is a textual fact, not a semantic one: a touched span is `modified`, a span only on the
    new side `added`, only on the old side `removed`. Nested definitions and repeated names are
    qualified (`Class.method`), so two methods called `run` in different classes stay distinct.
    """
    old_spans, old_confidence = spans_of(path, old_text or "")
    new_spans, new_confidence = spans_of(path, new_text or "")
    old_lines, new_lines = (old_text or "").split("\n"), (new_text or "").split("\n")
    old_changed, new_changed = set(), set()
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        old_changed.update(range(i1 + 1, i2 + 1))  # Deleted or replaced old lines.
        new_changed.update(range(j1 + 1, j2 + 1))  # Inserted or replaced new lines: where an insertion lands decides.
    old_keys, new_keys = {(n, k) for n, k, _, _ in old_spans}, {(n, k) for n, k, _, _ in new_spans}
    old_own, new_own = _own_lines(old_spans), _own_lines(new_spans)
    result = {"added": [], "removed": [], "modified": [],
              "confidence": "ast" if old_confidence == new_confidence == "ast" else
                            "parse_error" if "parse_error" in (old_confidence, new_confidence) else "heuristic"}
    for key in sorted(new_keys - old_keys):
        result["added"].append(key[0])
    for key in sorted(old_keys - new_keys):
        result["removed"].append(key[0])
    for key in sorted(new_keys & old_keys):
        touched = bool(new_own[key] & new_changed) or bool(old_own[key] & old_changed)
        if touched:
            result["modified"].append(key[0])
    for field in ("added", "removed", "modified"):
        result[field] = result[field][:MAX_SYMBOLS]
    return result


def hunks(old_text, new_text, *, max_hunks=MAX_HUNKS, max_lines=MAX_HUNK_LINES, context_lines=3):
    """Bounded unified hunks with original line ranges: [{old: [start, end], new: [start, end], lines: [...]}]."""
    old_lines, new_lines = (old_text or "").split("\n"), (new_text or "").split("\n")
    if old_text is None:
        old_lines = []
    if new_text is None:
        new_lines = []
    out, truncated = [], False
    for group in difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False).get_grouped_opcodes(context_lines):
        if len(out) >= max_hunks:
            truncated = True
            break
        first, last = group[0], group[-1]
        lines = []
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                lines.extend(" " + line for line in old_lines[i1:i2])
                continue
            if tag in ("replace", "delete"):
                lines.extend("-" + line for line in old_lines[i1:i2])
            if tag in ("replace", "insert"):
                lines.extend("+" + line for line in new_lines[j1:j2])
        cut = len(lines) > max_lines
        out.append({"old": [first[1] + 1, last[2]], "new": [first[3] + 1, last[4]], "lines": lines[:max_lines], "truncated": cut})
        truncated = truncated or cut
    return out, truncated


# ---------------------------------------------------------------- lineage and hotspots


def lineage(events, current_paths, *, max_depth=8):
    """Map historical paths to current admitted paths through rename evidence, conservatively.

    `exact`: the path exists now. `supported_rename`: one rename chain (similarity >= 50) reaches a
    current path. `ambiguous`: copies or diverging chains. `unresolved`: deleted, or renamed beyond
    the window. A rename proves a file moved, not that every symbol kept its meaning; callers keep
    that label next to anything they infer from it.
    """
    current = set(current_paths)
    edges = defaultdict(list)
    for event in events:
        for change in event.get("changes", ()):
            if change["kind"] in ("R", "C") and change.get("from"):
                edges[change["from"]].append((change["path"], change["kind"], change.get("score", 100)))
    historical = {c["path"] for e in events for c in e.get("changes", ())} | set(edges)
    out = {}
    for path in sorted(historical - current):
        seen, cursor, label, via = {path}, path, "unresolved", None
        for _ in range(max_depth):
            targets = {(t, k, s) for t, k, s in edges.get(cursor, ())}
            if not targets:
                break
            if len({t for t, _, _ in targets}) > 1 or any(k == "C" for _, k, _ in targets):
                label = "ambiguous"
                break
            target, kind, score = next(iter(targets))
            if score < 50 or target in seen:
                label = "ambiguous"
                break
            seen.add(target)
            cursor, via = target, cursor
            if target in current:
                label = "supported_rename"
                break
        out[path] = {"current": cursor if label == "supported_rename" else None, "label": label}
    return out


def resolve(path, current_paths, lineage_map):
    """(current path or None, label) for a historical path."""
    if path in current_paths:
        return path, "exact"
    row = lineage_map.get(path)
    if not row:
        return None, "unresolved"
    return row["current"], row["label"]


def _log_norm(values):
    top = max((math.log1p(v) for v in values.values()), default=0.0)
    return {k: (math.log1p(v) / top if top else 0.0) for k, v in values.items()}


def hotspots(events, index_paths, lineage_map, *, in_degree=None, symbols=None, weights=None, selector="diversified",
             limit=200, share=0.15, min_support=2):
    """Explainable hotspot selection over eligible events: where summarization effort should go first.

    Signals are normalized to [0, 1] with log scaling and averaged with their weights; a signal that
    is unknown for a file (no symbol data) is left out of that file's average rather than counted as
    zero. Release-only and bulk participation are penalties. Diversity: a directory cap and a reserve
    for high in-degree entry points and uncovered top-level modules. `selector="frequency"` keeps the
    raw edit count only, as an ablation. Scores rank investment; they are not defect probabilities.
    """
    weights = weights or {"edits": 1.0, "recency": 0.5, "fixes": 1.0, "incidents": 1.0, "symbols": 0.5, "cochange": 0.5, "penalty": 1.0}
    current, symbols = set(index_paths), symbols or {}
    edits, recency, fixes, incidents, diversity, release_only, commits = Counter(), {}, Counter(), defaultdict(set), defaultdict(set), Counter(), []
    total = max(1, len(events))
    for position, event in enumerate(events):
        if event.get("merge"):
            continue
        touched = set()
        for change in event.get("changes", ()):
            target, _ = resolve(change["path"], current, lineage_map)
            if target:
                touched.add(target)
                for name in symbols.get(event["id"], {}).get(change["path"], ()):
                    diversity[target].add(name)
        if event.get("bulk"):
            for path in touched:
                release_only[path] += 1
            continue
        fix = any(r["link"] == "declares_fix" for r in event.get("refs", ())) or bool(_FIXWORD.search(event.get("subject", "")))
        for path in touched:
            edits[path] += 1
            recency.setdefault(path, 1.0 - position / total)
            if fix:
                fixes[path] += 1
            for ref in event.get("refs", ()):
                incidents[path].add((ref.get("repository"), ref["number"]))
            if event.get("release"):
                release_only[path] += 1
        if 2 <= len(touched):
            commits.append((event.get("ct", 0), sorted(touched)))
    partners = _sibling("repo_index")["cochange"](commits, min_support=min_support) if commits else {}
    support = Counter({path: len(rows) for path, rows in partners.items()})
    scaled = {"edits": _log_norm(edits), "fixes": _log_norm(fixes), "incidents": _log_norm({p: len(v) for p, v in incidents.items()}),
              "symbols": _log_norm({p: len(v) for p, v in diversity.items()}), "cochange": _log_norm(support)}
    rows = []
    for path in edits:
        features, available = {}, 0.0
        for name in ("edits", "recency", "fixes", "incidents", "symbols", "cochange"):
            if name == "recency":
                features[name] = round(recency.get(path, 0.0), 4)
            elif name == "symbols" and path not in diversity and not symbols:
                continue  # Unknown, not zero: symbol history was not computed.
            else:
                features[name] = round(scaled[name].get(path, 0.0), 4)
            available += weights.get(name, 0.0)
        penalty = release_only[path] / (edits[path] + release_only[path]) if (edits[path] + release_only[path]) else 0.0
        score = sum(weights.get(n, 0.0) * v for n, v in features.items()) / available if available else 0.0
        score -= weights.get("penalty", 1.0) * penalty * 0.5
        if selector == "frequency":
            score = edits[path]
        reasons = [name for name, _ in sorted(features.items(), key=lambda item: -item[1] * weights.get(item[0], 0.0))[:2]]
        rows.append({"path": path, "score": round(score, 4), "features": features, "penalty": round(penalty, 4), "reasons": reasons})
    rows.sort(key=lambda row: (-row["score"], row["path"]))
    target = min(limit, max(1, math.ceil(len(current) * share))) if current else min(limit, len(rows))
    if selector != "diversified":
        chosen = rows[:target]
    else:
        per_directory, cap, chosen, skipped = Counter(), max(2, math.ceil(target * 0.3)), [], []
        for row in rows:
            directory = PurePosixPath(row["path"]).parent.as_posix()
            if len(chosen) >= target:
                skipped.append(row)
            elif per_directory[directory] >= cap:
                skipped.append(dict(row, reasons=row["reasons"] + ["directory cap"]))
            else:
                per_directory[directory] += 1
                chosen.append(row)
        chosen_paths = {row["path"] for row in chosen}
        reserve = max(1, math.ceil(target * 0.1))
        degree = in_degree or {}
        for path in sorted((p for p in current if p not in chosen_paths and degree.get(p, 0) > 0), key=lambda p: (-degree[p], p))[:reserve]:
            chosen.append({"path": path, "score": 0.0, "features": {}, "penalty": 0.0, "reasons": ["reserve: high in-degree entry point"]})
            chosen_paths.add(path)
        covered = {PurePosixPath(p).parts[0] for p in chosen_paths if len(PurePosixPath(p).parts) > 1}
        for row in rows:
            top = PurePosixPath(row["path"]).parts[0]
            if len(PurePosixPath(row["path"]).parts) > 1 and top not in covered and row["path"] not in chosen_paths:
                chosen.append(dict(row, reasons=row["reasons"] + ["reserve: uncovered module"]))
                chosen_paths.add(row["path"])
                covered.add(top)
    modules = {PurePosixPath(p).parent.as_posix() for p in current}
    coverage = {"admitted_files": len(current), "files_with_history": len(edits), "hotspots": len(chosen),
                "modules": len(modules), "modules_covered": len({PurePosixPath(r["path"]).parent.as_posix() for r in chosen}),
                "selector": selector, "target": target}
    return chosen, coverage, {path: [list(row) for row in rows_] for path, rows_ in partners.items()}
