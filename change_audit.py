#!/usr/bin/env python3
"""Explicit before/after file evidence, including ignored helper side effects.

No observer, project writes, source contents, or background processes. Snapshots
are bounded observations, not a filesystem sandbox or tamper-proof attestation.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import time
import types

OWNER = "agent-dispatcher-change-audit"
SCHEMA_VERSION = 1
STATE_FILE = "audit.json"
MAX_FILES = 10000
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_SCAN_BYTES = 64 * 1024 * 1024
MAX_SCAN_SECONDS = 10
MAX_STATE_BYTES = 16 * 1024 * 1024
MAX_PATHS = 64
MAX_DEPTH = 64
HASH = re.compile(r"[a-f0-9]{64}\Z")


class AuditError(ValueError):
    """Sanitized failure; untrusted state and arguments are never echoed."""


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, "change_audit.py: invalid arguments; use --help. Values withheld.\n")


def _verification():
    path = Path(__file__).resolve().with_name("verification.py")
    module = types.ModuleType("_dispatcher_audit_verification")
    module.__file__ = str(path)
    try:
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)
        return module
    except (OSError, ValueError, ImportError):
        raise AuditError("Required adjacent verification helpers are unavailable.") from None


def _literal(value, *, directory=True):
    if (not isinstance(value, str) or not value or len(value) > 512 or value.startswith(("/", "~"))
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or any(c in value for c in "\\:*?[]") or value.endswith("/") and not directory):
        return False
    plain = value[:-1] if value.endswith("/") else value
    return bool(plain and all(part not in {"", ".", ".."} for part in plain.split("/"))
                and str(PurePosixPath(plain)) == plain)


def _paths(values):
    if not isinstance(values, (list, tuple)) or len(values) > MAX_PATHS or any(not _literal(p) for p in values):
        raise AuditError("Paths must be bounded literal relative files or subtrees ending in /.")
    return list(dict.fromkeys(values))


def _matches(path, paths):
    return any(path == value or value.endswith("/") and path.startswith(value) for value in paths)


def _snapshot(project, exclusions):
    """Walk descriptors without following directory or file links, ignoring no caches."""
    files, unknown, omitted = {}, {}, Counter()
    scanned = entries = 0
    inventory_complete = True
    started = time.monotonic()
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)

    def omit(path, reason, *, inventory=False):
        nonlocal inventory_complete
        omitted[reason] += 1
        if len(unknown) < MAX_FILES:
            unknown[path] = reason
        if inventory:
            inventory_complete = False

    def visit(fd, prefix="", depth=0):
        nonlocal scanned, entries, inventory_complete
        if depth > MAX_DEPTH:
            omit(prefix, "depth_limit", inventory=True)
            return
        before = os.fstat(fd)
        names = []
        try:
            with os.scandir(fd) as listing:
                for entry in listing:
                    if entries >= MAX_FILES or time.monotonic() - started > MAX_SCAN_SECONDS:
                        omit(prefix, "scan_limit", inventory=True)
                        break
                    entries += 1
                    names.append(entry.name)
        except OSError:
            omit(prefix, "unreadable_directory", inventory=True)
            return
        for name in sorted(names):
            relative = prefix + name
            if name == ".git":
                continue  # Declared scope: Git's bookkeeping, including nested repos, is outside this audit.
            if _matches(relative, exclusions) or _matches(relative + "/", exclusions):
                omit(relative, "excluded")
                continue
            if not _literal(relative, directory=False):
                omit(prefix, "unsupported_path", inventory=True)
                continue
            if time.monotonic() - started > MAX_SCAN_SECONDS:
                omit(prefix, "time_limit", inventory=True)
                break
            try:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    omit(relative, "symlink")
                    continue
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(name, directory_flags, dir_fd=fd)
                    try:
                        opened = os.fstat(child)
                        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                            omit(relative + "/", "changed_during_scan", inventory=True)
                        else:
                            visit(child, relative + "/", depth + 1)
                    finally:
                        os.close(child)
                    continue
                if not stat.S_ISREG(info.st_mode):
                    omit(relative, "not_regular")
                    continue
                if info.st_size > MAX_FILE_BYTES:
                    omit(relative, "file_size_limit")
                    continue
                if info.st_size > MAX_SCAN_BYTES - scanned:
                    omit(relative, "byte_limit")
                    continue
                source = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0), dir_fd=fd)
                try:
                    opened = os.fstat(source)
                    if (not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)):
                        omit(relative, "changed_during_scan")
                        continue
                    digest, used = hashlib.sha256(), 0
                    while True:
                        if time.monotonic() - started > MAX_SCAN_SECONDS:
                            omit(relative, "time_limit")
                            break
                        amount = min(65536, MAX_FILE_BYTES - used + 1, MAX_SCAN_BYTES - scanned + 1)
                        chunk = os.read(source, amount)
                        if not chunk:
                            current = os.fstat(source)
                            signature = lambda meta: (meta.st_dev, meta.st_ino, meta.st_size, meta.st_mtime_ns, meta.st_ctime_ns, meta.st_mode)
                            if signature(current) != signature(info):
                                omit(relative, "changed_during_scan")
                            else:
                                files[relative] = {"sha256": digest.hexdigest(), "mode": stat.S_IMODE(current.st_mode)}
                            break
                        scanned += len(chunk)
                        used += len(chunk)
                        if used > MAX_FILE_BYTES or scanned > MAX_SCAN_BYTES:
                            omit(relative, "byte_limit")
                            break
                        digest.update(chunk)
                finally:
                    os.close(source)
            except OSError:
                omit(relative, "unreadable", inventory=True)
        after = os.fstat(fd)
        if (before.st_mtime_ns, before.st_ctime_ns) != (after.st_mtime_ns, after.st_ctime_ns):
            omit(prefix, "directory_changed_during_scan", inventory=True)

    try:
        root = os.open(project, directory_flags)
        try:
            visit(root)
        finally:
            os.close(root)
    except OSError:
        omit("", "unreadable_project", inventory=True)
    return {"files": files, "unknown": unknown, "complete": not omitted and not exclusions,
            "inventory_complete": inventory_complete, "omitted": dict(sorted(omitted.items())),
            "inspected_bytes": min(scanned, MAX_SCAN_BYTES), "visited_entries": entries}


def _coverage(snapshot):
    return {key: snapshot[key] for key in ("complete", "inventory_complete", "omitted", "inspected_bytes", "visited_entries")} | {"fingerprinted_files": len(snapshot["files"])}


def _valid_snapshot(value):
    if (not isinstance(value, dict) or set(value) != {"files", "unknown", "complete", "inventory_complete", "omitted", "inspected_bytes", "visited_entries"}
            or type(value["complete"]) is not bool or type(value["inventory_complete"]) is not bool
            or not isinstance(value["files"], dict) or len(value["files"]) > MAX_FILES
            or not isinstance(value["unknown"], dict) or len(value["unknown"]) > MAX_FILES
            or not isinstance(value["omitted"], dict) or len(value["omitted"]) > 20
            or type(value["inspected_bytes"]) is not int or not 0 <= value["inspected_bytes"] <= MAX_SCAN_BYTES
            or type(value["visited_entries"]) is not int or not 0 <= value["visited_entries"] <= MAX_FILES):
        raise AuditError("Audit snapshot is malformed; state left untouched.")
    for path, item in value["files"].items():
        if (not _literal(path, directory=False) or not isinstance(item, dict) or set(item) != {"sha256", "mode"}
                or not isinstance(item["sha256"], str) or not HASH.fullmatch(item["sha256"])
                or type(item["mode"]) is not int or not 0 <= item["mode"] <= 0o7777):
            raise AuditError("Audit snapshot is malformed; state left untouched.")
    if (any(path != "" and not _literal(path) or not isinstance(reason, str) or len(reason) > 80 for path, reason in value["unknown"].items())
            or any(not isinstance(reason, str) or len(reason) > 80 or type(count) is not int or count < 1 for reason, count in value["omitted"].items())
            or value["complete"] and (value["unknown"] or value["omitted"] or not value["inventory_complete"])):
        raise AuditError("Audit snapshot is malformed; state left untouched.")


def _read_state(helper, project, state):
    try:
        path = helper._receipt_path(project, state)
        if path.name != STATE_FILE:
            raise ValueError()
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
                    or info.st_size > MAX_STATE_BYTES or info.st_mode & 0o077):
                raise ValueError()
            with os.fdopen(fd, "rb", closefd=False) as handle:
                raw = handle.read(MAX_STATE_BYTES + 1)
            if len(raw) > MAX_STATE_BYTES:
                raise ValueError()
        finally:
            os.close(fd)
        data = json.loads(raw)
        if (not isinstance(data, dict) or set(data) != {"owner", "schema_version", "owner_uid", "project_id", "directory_identity", "exclude_paths", "before"}
                or data["owner"] != OWNER or type(data["schema_version"]) is not int or data["schema_version"] != SCHEMA_VERSION
                or type(data["owner_uid"]) is not int or data["owner_uid"] != os.getuid()
                or data["project_id"] != helper._project_id(project)
                or not isinstance(data["directory_identity"], list) or len(data["directory_identity"]) != 2
                or any(type(value) is not int or value < 0 for value in data["directory_identity"])):
            raise ValueError()
        parent = path.parent.stat()
        if parent.st_mode & 0o077 or [parent.st_dev, parent.st_ino] != data["directory_identity"]:
            raise ValueError()
        _paths(data["exclude_paths"])
        _valid_snapshot(data["before"])
        return path, data, {"identity": (info.st_dev, info.st_ino), "sha256": hashlib.sha256(raw).hexdigest()}
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        raise AuditError("Audit state is malformed, unsafe, or belongs to another project; left untouched.") from None


def start_audit(project, *, exclude_paths=(), pack=None):
    """Capture a baseline before any task/helper writes; return its private state path."""
    helper = _verification()
    runtime, scrub = helper._runtime(pack)
    project = helper._project(project)
    exclusions = _paths(exclude_paths)
    before = _snapshot(project, exclusions)
    directory, identity = helper._temporary_directory(project)
    path = directory / STATE_FILE
    data = {"owner": OWNER, "schema_version": SCHEMA_VERSION, "owner_uid": os.getuid(),
            "project_id": helper._project_id(project), "directory_identity": list(identity),
            "exclude_paths": exclusions, "before": before}
    raw = (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode()
    created = None
    try:
        if len(raw) > MAX_STATE_BYTES:
            raise AuditError("Audit state exceeded its storage bound.")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as handle:
            info = os.fstat(handle.fileno())
            # Pin the inode we exclusively created, never a later pathname occupant.
            # A failed partial write cannot match the intended full-content digest
            # and is conservatively retained with a cleanup diagnostic.
            created = {"identity": (info.st_dev, info.st_ino), "sha256": hashlib.sha256(raw).hexdigest()}
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except (OSError, ValueError):
        cleaned = helper._cleanup_owned_file(path, created, directory_identity=identity, remove_directory=True, scrub=scrub)
        message = "Could not create private audit state; no project files changed."
        if cleaned.get("status") != "removed":
            message += " Cleanup refused; retained state: " + cleaned.get("leftover_path", "location unavailable")
        raise AuditError(message) from None
    return {"schema_version": SCHEMA_VERSION, "state": str(path), "coverage": _coverage(before),
            "read_only": False, "project_read_only": True,
            "scope": "Project files, including ignored and untracked files; .git bookkeeping excluded.",
            "limits": ["No file contents are saved. Incomplete scans cannot establish preservation."]}


def cleanup_audit(project, state, *, pack=None):
    """Remove only validated state and its original empty private directory."""
    helper = _verification()
    _, scrub = helper._runtime(pack)
    project = helper._project(project)
    path, data, expected = _read_state(helper, project, state)
    return helper._cleanup_owned_file(path, expected, directory_identity=tuple(data["directory_identity"]),
                                      remove_directory=True, scrub=scrub)


def finish_audit(project, state, *, writable_paths=None, pack=None, cleanup=True):
    """Compare with the task baseline, then remove validated temporary state by default."""
    helper = _verification()
    _, scrub = helper._runtime(pack)
    project = helper._project(project)
    if type(cleanup) is not bool:
        raise AuditError("Cleanup must be a boolean.")
    allowed = None if writable_paths is None else _paths(writable_paths)
    path, data, expected = _read_state(helper, project, state)
    before, after = data["before"], _snapshot(project, data["exclude_paths"])

    def absent(name, snapshot):
        return (snapshot["inventory_complete"] and name not in snapshot["files"]
                and not any(unknown == "" or name == unknown or unknown.endswith("/") and name.startswith(unknown)
                            for unknown in snapshot["unknown"]))

    old, new = before["files"], after["files"]
    changes = {"added": sorted(name for name in new.keys() - old.keys() if absent(name, before)),
               "deleted": sorted(name for name in old.keys() - new.keys() if absent(name, after)),
               "modified": sorted(name for name in old.keys() & new.keys() if old[name] != new[name])}
    changed = sorted(set().union(*changes.values()))
    outside = [] if allowed is None else [name for name in changed if not _matches(name, allowed)]
    complete = before["complete"] and after["complete"]
    status = ("not_provided" if allowed is None else "out_of_scope" if outside else "within_scope" if complete else "incomplete")
    result = {"schema_version": SCHEMA_VERSION, "changes": {kind: [scrub(name) for name in paths] for kind, paths in changes.items()},
              "out_of_scope": [scrub(name) for name in outside], "scope_status": status,
              "complete": complete, "preserved": False if changed else True if complete else None,
              "coverage": {"before": _coverage(before), "after": _coverage(after)},
              "project_read_only": True, "read_only": not cleanup,
              "scope": "Changes since this baseline; pre-existing edits are not attributed to this task. .git excluded.",
              "limits": ["Only observed file bytes and permission modes are compared; no claim about transient writes or external paths.",
                         "Excluded, linked, unreadable, oversized, or unscanned paths prevent blanket preservation claims."]}
    result["cleanup"] = (helper._cleanup_owned_file(path, expected, directory_identity=tuple(data["directory_identity"]),
                                                    remove_directory=True, scrub=scrub)
                         if cleanup else {"requested": False, "removed": False})
    return result


def render(result):
    if "state" in result:
        return "Change audit started. State: " + result["state"] + "\nCoverage: " + ("complete" if result["coverage"]["complete"] else "incomplete")
    lines = ["Changes since task baseline:"]
    for kind, paths in result["changes"].items():
        lines.extend(kind + ": " + path for path in paths)
    if not any(result["changes"].values()):
        lines.append("No changes observed." if result["complete"] else "No changes observed in the inspected subset; preservation unverified.")
    lines.append("Edit scope: " + result["scope_status"].replace("_", " "))
    if not result["complete"]:
        lines.append("Coverage incomplete; cannot claim all other files were preserved.")
    cleanup = result.get("cleanup", {})
    if cleanup.get("status") == "removed":
        lines.append("Temporary audit state removed and absence verified.")
    elif cleanup.get("status") == "refused":
        lines.append("Temporary audit cleanup refused; retained state: " + cleanup.get("leftover_path", "location unavailable"))
    else:
        lines.append("Temporary audit state retained by request.")
    return "\n".join(lines)


def main(argv=None):
    parser = SafeParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("start", "finish"):
        child = sub.add_parser(action)
        child.add_argument("--project", required=True)
        child.add_argument("--pack")
        child.add_argument("--json", action="store_true")
        if action == "start":
            child.add_argument("--exclude-path", action="append", default=[])
        else:
            child.add_argument("--state", required=True)
            child.add_argument("--writable-path", action="append")
    args = parser.parse_args(argv)
    result = None
    try:
        if args.action == "start":
            result = start_audit(args.project, exclude_paths=args.exclude_path, pack=args.pack)
        else:
            result = finish_audit(args.project, args.state, writable_paths=args.writable_path, pack=args.pack)
        print(json.dumps(result, ensure_ascii=False) if args.json else render(result), flush=True)
        return int(args.action == "finish" and (not result["complete"] or bool(result["out_of_scope"])
                                                 or result["cleanup"].get("status") != "removed"))
    except (AuditError, OSError, ValueError, TypeError) as exc:
        if args.action == "start" and result is not None:
            try:
                cleaned = cleanup_audit(args.project, result["state"], pack=args.pack)
                if cleaned.get("status") != "removed":
                    print("Audit cleanup refused; retained state: " + cleaned.get("leftover_path", "location unavailable"), file=sys.stderr)
            except (AuditError, OSError, ValueError, TypeError):
                print("Audit state could not be cleaned safely after output delivery failed.", file=sys.stderr)
        safe_error = isinstance(exc, AuditError) or exc.__class__.__name__ == "VerificationError"
        print(str(exc) if safe_error else "Change audit could not complete safely; no preservation claim is available.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
