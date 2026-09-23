"""Bounded local delivery ledger for source evidence in explicitly retained context.

This records fingerprints, never source text or task prose. It cannot establish that
another worker, compacted context, or remote model remembers a previous packet. The
caller must provide a new scope whenever retained context changes. Prepare before
packet trimming, then commit exactly the packet that will be delivered. Neither
phase writes inside the inspected project. Invalid state falls back to full evidence.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat

MAX_STATE_BYTES = 128 * 1024
MAX_ENTRIES = 256
HEX = re.compile(r"[0-9a-f]{64}\Z")
FIELDS = {"schema_version", "project_sha256", "scope_sha256", "policy_sha256", "entries"}
FAILURES = (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError)


def _encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_encoded(value)).hexdigest()


def _hex(value):
    return isinstance(value, str) and HEX.fullmatch(value) is not None


def _fingerprint(item):
    """Independently bind IDs to the delivered source/range, including after trimming."""
    if not isinstance(item, dict) or not _hex(item.get("id")) or not _hex(item.get("source_sha256")):
        raise ValueError()
    path, lines, content = item.get("path"), item.get("lines"), item.get("content")
    if (not isinstance(path, str) or not path or len(path) > 4096
            or PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts
            or any(ord(char) < 32 or ord(char) == 127 for char in path)
            or not isinstance(lines, str) or not re.fullmatch(r"[1-9][0-9]{0,9}-[1-9][0-9]{0,9}", lines)
            or not isinstance(content, str) or len(content) > 1024 * 1024):
        raise ValueError()
    start, end = map(int, lines.split("-"))
    if start > end:
        raise ValueError()
    return _digest({key: item[key] for key in ("id", "source_sha256", "path", "lines", "content")})


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
            info.st_mode, info.st_uid, info.st_nlink)


@contextmanager
def _parent(state_path, project):
    """Walk with no-follow directory handles; reject unsafe leaf parents and project writes."""
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise ValueError()
    supplied = Path(os.path.expanduser(os.fspath(state_path)))
    if not supplied.is_absolute():
        raise ValueError()
    path = Path(os.path.abspath(supplied))
    root = Path(project).resolve(strict=True)
    if not root.is_dir() or path == root or root in path.parents or path.name in ("", ".", ".."):
        raise ValueError()
    current = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            os.close(current)
            current = next_fd
        info = os.fstat(current)
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ValueError()
        yield current, path.name, path
    finally:
        os.close(current)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def _load(parent_fd, name):
    try:
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None, None
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
            or before.st_mode & 0o077 or before.st_nlink != 1
            or before.st_size > MAX_STATE_BYTES):
        raise ValueError()
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
    try:
        if _signature(os.fstat(fd)) != _signature(before):
            raise ValueError()
        raw = bytearray()
        while len(raw) <= MAX_STATE_BYTES:
            chunk = os.read(fd, min(65536, MAX_STATE_BYTES + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        if len(raw) > MAX_STATE_BYTES or _signature(os.fstat(fd)) != _signature(before):
            raise ValueError()
    finally:
        os.close(fd)
    state = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(state, dict) or set(state) != FIELDS | {"checksum"}:
        raise ValueError()
    checksum = state.pop("checksum")
    if (type(state["schema_version"]) is not int or state["schema_version"] != 1
            or any(not _hex(state[key]) for key in ("project_sha256", "scope_sha256", "policy_sha256"))
            or not isinstance(state["entries"], dict) or len(state["entries"]) > MAX_ENTRIES
            or any(not _hex(key) or not _hex(value) for key, value in state["entries"].items())
            or not _hex(checksum) or checksum != _digest(state)):
        raise ValueError()
    return state, (_signature(before), hashlib.sha256(raw).hexdigest())


def _status(result, status, references=(), diagnostic=None):
    result["reuse"] = {"status": status, "emitted_count": len(result.get("excerpts", [])),
                       "reused_count": len(references), "references": list(references)}
    if diagnostic:
        result["reuse"]["diagnostic"] = diagnostic
    return result


def prepare_reuse(result, state_path=None, scope=None):
    """Replace exact previously delivered excerpts with refs; return packet and commit handle.

    The explicit file must have an existing owner-controlled parent outside project.
    A malformed, unsafe or unavailable ledger remains untouched and yields full text.
    """
    output = copy.deepcopy(result)
    if state_path is None and scope is None:
        return _status(output, "disabled"), None
    try:
        if state_path is None or not isinstance(scope, str) or not scope.strip() or len(scope) > 4096:
            raise ValueError()
        project = str(Path(result["project"]).resolve(strict=True))
        policy = result["exclusion_policy"]
        if not isinstance(policy, dict) or len(_encoded(policy)) > 64 * 1024:
            raise ValueError()
        # An admitted learning generation is part of the delivery policy: evidence reused under a revoked or changed
        # overlay set is a new delivery. Without learning the key is exactly what it was before.
        learning_key = (result.get("learning") or {}).get("reuse_key") if isinstance(result.get("learning"), dict) else None
        if learning_key is not None and not _hex(learning_key):
            raise ValueError()
        identity = {"schema_version": 1, "project_sha256": _digest(project), "scope_sha256": _digest(scope),
                    "policy_sha256": _digest(policy) if learning_key is None else _digest([policy, learning_key])}
        excerpts = result["excerpts"]
        if not isinstance(excerpts, list) or len(excerpts) > MAX_ENTRIES:
            raise ValueError()
        fingerprints = {item["id"]: _fingerprint(item) for item in excerpts}
        if len(fingerprints) != len(excerpts):
            raise ValueError()
        with _parent(state_path, project) as (parent_fd, name, absolute):
            state, snapshot = _load(parent_fd, name)
        entries = state["entries"] if state and all(state[key] == value for key, value in identity.items()) else {}
        references, emitted = [], []
        for item in output["excerpts"]:
            if entries.get(item["id"]) == fingerprints[item["id"]]:
                references.append({key: item[key] for key in ("id", "path", "lines")})
            else:
                emitted.append(item)
        output["excerpts"] = emitted
        pending = {"state_path": absolute, "project": project, "identity": identity,
                   "snapshot": snapshot, "entries": entries, "fingerprints": fingerprints,
                   "originals": copy.deepcopy(excerpts), "references": copy.deepcopy(references)}
        return _status(output, "prepared", references), pending
    except FAILURES:
        return _status(output, "unavailable", diagnostic=
                       "Reuse unavailable; full evidence retained. Check the explicit local ledger and retained-context scope."), None


def _save(parent_fd, name, state):
    """Replace only after a complete, private, bounded file has been flushed."""
    # Preserve insertion order in entries: it is the bounded retention order.
    raw = json.dumps({**state, "checksum": _digest(state)}, ensure_ascii=True,
                     separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    if len(raw) > MAX_STATE_BYTES:
        raise ValueError()
    temporary = ".dispatcher-reuse-" + secrets.token_hex(16)
    fd = None
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=parent_fd)
        offset = 0
        while offset < len(raw):
            written = os.write(fd, raw[offset:])
            if written <= 0:
                raise OSError()
            offset += written
        os.fsync(fd)
        os.close(fd)
        fd = None
        os.replace(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
    finally:
        if fd is not None:
            os.close(fd)
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            pass


def commit_reuse(result, pending):
    """Record only unchanged full excerpts surviving packet trimming; fail open to full text."""
    if pending is None:
        return result
    output = copy.deepcopy(result)
    references = output.get("reuse", {}).get("references", [])
    try:
        if not isinstance(references, list) or any(ref not in pending["references"] for ref in references):
            raise ValueError()
        entries = dict(pending["entries"])
        for item in output["excerpts"]:
            try:
                fingerprint = _fingerprint(item)
            except FAILURES:
                continue
            if fingerprint == pending["fingerprints"].get(item["id"]):
                entries.pop(item["id"], None)
                entries[item["id"]] = fingerprint
        # References refresh retention priority without asserting a new source delivery.
        for ref in references:
            if ref["id"] in entries:
                fingerprint = entries.pop(ref["id"])
                entries[ref["id"]] = fingerprint
        entries = dict(list(entries.items())[-MAX_ENTRIES:])
        with _parent(pending["state_path"], pending["project"]) as (parent_fd, name, _):
            _, snapshot = _load(parent_fd, name)
            if snapshot != pending["snapshot"]:
                raise ValueError()
            _save(parent_fd, name, {**pending["identity"], "entries": entries})
        return _status(output, "committed", references)
    except FAILURES:
        # Restore only refs still in the final packet; intentional omissions stay omitted.
        kept = {ref.get("id") for ref in references if isinstance(ref, dict)} if isinstance(references, list) else set()
        present = {item.get("id") for item in output.get("excerpts", []) if isinstance(item, dict)}
        for item in pending["originals"]:
            if item["id"] in kept and item["id"] not in present:
                output["excerpts"].append(copy.deepcopy(item))
        # Preserve retrieval priority if the caller must fit the expanded packet again.
        positions = {item["id"]: index for index, item in enumerate(pending["originals"])}
        output["excerpts"].sort(key=lambda item: positions.get(item.get("id"), len(positions)))
        return _status(output, "commit_failed", diagnostic=
                       "Reuse ledger was not updated; retained references restored to full evidence.")
