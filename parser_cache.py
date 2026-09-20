"""Private, authenticated incremental source/parser cache; never project authority.

Only redacted source is retained. A hit checks the current source's metadata and
accessibility, not its bytes: callers needing independent content verification
must disable this optimization. Cache failures always fall back to fresh work.
"""
from __future__ import annotations

import ast
import base64
from contextlib import contextmanager
import copy
import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import stat
import sys
import warnings

SCHEMA = 1
MAX_FILE_BYTES = 256 * 1024
MAX_BYTES = 64 * 1024 * 1024
MAX_ITEM_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 12000
MAX_AST_NODES = 50000
FAILURES = (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError, MemoryError)


def _encoded(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_encoded(value)).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def _signature(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
            info.st_mode, info.st_uid, info.st_nlink]


def _safe_path(relative):
    return (isinstance(relative, str) and 0 < len(relative) <= 4096
            and not PurePosixPath(relative).is_absolute()
            and PurePosixPath(relative).as_posix() == relative
            and not any(part in {"", ".", ".."} for part in relative.split("/"))
            and "\\" not in relative
            and not any(ord(char) < 32 or ord(char) == 127 for char in relative))


@contextmanager
def _source(project, relative):
    if not _safe_path(relative) or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise ValueError()
    current = os.open(project, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    source = None
    try:
        parts = PurePosixPath(relative).parts
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            os.close(current)
            current = child
        source = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=current)
        before = os.fstat(source)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError()
        yield source, before
    finally:
        if source is not None:
            os.close(source)
        os.close(current)


def _policy(extra=None):
    root = Path(__file__).resolve().parent
    files = {}
    for name in ("parser_cache.py", "context.py", "project_map.py", "project_graph.py", "doctor.py"):
        path = root / name
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    for candidate in (root / "decision/redact.py", root / "runtime/decision/redact.py",
                      root.parent.parent / "decision/redact.py"):
        if candidate.is_file():
            files["decision/redact.py"] = hashlib.sha256(candidate.read_bytes()).hexdigest()
            break
    # Content identity survives copying the same package into an evaluation.
    return _digest({"schema": SCHEMA, "python": list(sys.version_info[:3]), "files": files, "extra": extra})


def _ast_encode(value, budget=None, depth=0):
    budget = [MAX_AST_NODES] if budget is None else budget
    budget[0] -= 1
    if budget[0] < 0 or depth > 200:
        raise ValueError()
    if isinstance(value, ast.AST):
        return {"node": type(value).__name__,
                "fields": {name: _ast_encode(getattr(value, name), budget, depth + 1)
                           for name in value._fields if hasattr(value, name)},
                "attributes": {name: _ast_encode(getattr(value, name), budget, depth + 1)
                               for name in value._attributes if hasattr(value, name)}}
    if isinstance(value, list):
        return [_ast_encode(item, budget, depth + 1) for item in value]
    if type(value) is bytes:
        return {"constant": "bytes", "value": base64.b64encode(value).decode("ascii")}
    if type(value) is complex:
        return {"constant": "complex", "value": [repr(value.real), repr(value.imag)]}
    if type(value) is float:
        return {"constant": "float", "value": repr(value)}
    if value is Ellipsis:
        return {"constant": "ellipsis"}
    if value is None or type(value) in (str, int, bool):
        return value
    raise ValueError()


def _ast_decode(value, budget=None, depth=0):
    budget = [MAX_AST_NODES] if budget is None else budget
    budget[0] -= 1
    if budget[0] < 0 or depth > 200:
        raise ValueError()
    if isinstance(value, list):
        return [_ast_decode(item, budget, depth + 1) for item in value]
    if value is None or type(value) in (str, int, bool):
        return value
    if not isinstance(value, dict):
        raise ValueError()
    if "constant" in value:
        tag = value["constant"]
        if tag == "ellipsis" and set(value) == {"constant"}:
            return Ellipsis
        if set(value) != {"constant", "value"}:
            raise ValueError()
        if tag == "bytes" and isinstance(value["value"], str):
            return base64.b64decode(value["value"], validate=True)
        if tag == "float" and isinstance(value["value"], str):
            return float(value["value"])
        if (tag == "complex" and isinstance(value["value"], list) and len(value["value"]) == 2
                and all(isinstance(item, str) for item in value["value"])):
            return complex(*map(float, value["value"]))
        raise ValueError()
    if set(value) != {"node", "fields", "attributes"} or not isinstance(value["node"], str):
        raise ValueError()
    kind = getattr(ast, value["node"], None)
    if not isinstance(kind, type) or not issubclass(kind, ast.AST) or kind is ast.AST:
        raise ValueError()
    fields, attributes = value["fields"], value["attributes"]
    if (not isinstance(fields, dict) or not isinstance(attributes, dict)
            or set(fields) != set(kind._fields) or not set(attributes) <= set(kind._attributes)):
        raise ValueError()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = kind(**{name: _ast_decode(item, budget, depth + 1) for name, item in fields.items()})
    for name, item in attributes.items():
        setattr(result, name, _ast_decode(item, budget, depth + 1))
    return result


class Cache:
    """One bounded project cache; writes occur only at explicitly writable finish()."""

    def __init__(self, project, *, enabled=True, writable=False, directory=None, policy_extra=None):
        self.project = Path(project).resolve()
        self.enabled = bool(enabled)
        self.writable = bool(writable) and self.enabled
        self.directory = Path(directory).expanduser().absolute() if directory is not None else (
            Path.home().resolve() / ".cache" / "agent-dispatcher" / "parser-v1")
        self.stats = {name: 0 for name in ("source_hits", "source_misses", "source_bytes_read",
                                          "parsed_files", "reused_parses", "writes", "records_saved", "write_failures")}
        self.entries, self.touched, self.sizes = {}, set(), {}
        self.dirty = False
        self.key = None
        self.record_digest = None
        self.usable = self.enabled
        self.identity = self.policy = self.name = None
        try:
            info = self.project.stat()
            self.identity = _digest({"path": str(self.project), "dev": info.st_dev, "ino": info.st_ino})
            self.policy = _policy(policy_extra)
            self.name = self.identity + ".json"
            if self.directory == self.project or self.project in self.directory.parents:
                raise ValueError()
            if self.enabled:
                self._load()
        except FAILURES:
            self.usable = False
        self.stats["cache_available"] = self.usable

    @contextmanager
    def _directory(self, create=False):
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
            raise ValueError()
        path = self.directory
        if not path.is_absolute() or ".." in path.parts:
            raise ValueError()
        current = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for index, part in enumerate(path.parts[1:], 1):
                try:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
                except FileNotFoundError:
                    if not create:
                        raise
                    os.mkdir(part, 0o700, dir_fd=current)
                    self.stats["writes"] = 1
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
                info = os.fstat(child)
                leaf = index == len(path.parts) - 1
                if ((leaf and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700))
                        or (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX)):
                    os.close(child)
                    raise ValueError()
                os.close(current)
                current = child
            yield current
        finally:
            os.close(current)

    @staticmethod
    def _read_private(parent, name, limit):
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            before = os.fstat(descriptor)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                    or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1
                    or before.st_size > limit):
                raise ValueError()
            chunks = []
            total = 0
            while total <= limit:
                chunk = os.read(descriptor, min(65536, limit + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            if total > limit or _signature(before) != _signature(os.fstat(descriptor)):
                raise ValueError()
            return b"".join(chunks)
        finally:
            os.close(descriptor)

    def _load(self):
        try:
            with self._directory() as parent:
                try:
                    self.key = self._read_private(parent, "key", 32)
                except FileNotFoundError:
                    return
                if len(self.key) != 32:
                    raise ValueError()
                try:
                    raw = self._read_private(parent, self.name, MAX_BYTES)
                except FileNotFoundError:
                    return
        except FileNotFoundError:
            return
        self.record_digest = hashlib.sha256(raw).hexdigest()
        envelope = json.loads(raw, object_pairs_hook=_unique)
        if not isinstance(envelope, dict) or set(envelope) != {"payload", "signature"}:
            raise ValueError()
        payload, signature = envelope["payload"], envelope["signature"]
        if (not isinstance(signature, str)
                or not hmac.compare_digest(signature, hmac.new(self.key, _encoded(payload), hashlib.sha256).hexdigest())
                or not isinstance(payload, dict) or set(payload) != {"schema", "project", "policy", "entries"}
                or payload["schema"] != SCHEMA or payload["project"] != self.identity):
            raise ValueError()
        if payload["policy"] != self.policy:
            return
        if not isinstance(payload["entries"], dict) or len(payload["entries"]) > MAX_ENTRIES:
            raise ValueError()
        for key, value in payload["entries"].items():
            if not isinstance(key, str) or len(key) != 64:
                raise ValueError()
            size = len(_encoded(value))
            if size > MAX_ITEM_BYTES:
                raise ValueError()
            self.sizes[key] = size
        self.entries = payload["entries"]

    def get(self, kind, key):
        if not self.usable:
            return None
        try:
            identity = _digest([kind, key])
            if identity not in self.entries:
                return None
            self.touched.add(identity)
            return copy.deepcopy(self.entries[identity])
        except FAILURES:
            return None

    def touch(self, kind, key):
        if not self.usable:
            return False
        try:
            identity = _digest([kind, key])
            if identity in self.entries:
                self.touched.add(identity)
                return True
        except FAILURES:
            pass
        return False

    def put(self, kind, key, value):
        if not self.usable:
            return
        try:
            identity = _digest([kind, key])
            size = len(_encoded(value))
            if size > MAX_ITEM_BYTES or (identity not in self.entries and len(self.entries) >= MAX_ENTRIES):
                return
            if sum(self.sizes.values()) - self.sizes.get(identity, 0) + size > MAX_BYTES - 1024 * 1024:
                return
            self.touched.add(identity)
            if self.entries.get(identity) != value:
                self.entries[identity] = copy.deepcopy(value)
                self.sizes[identity] = size
                self.dirty = True
        except FAILURES:
            pass

    def read(self, relative, remaining, reader, redact):
        """Read permitted source only; caller must apply exclusions before this call."""
        if not self.usable:
            text, used, reason = reader(self.project, relative, remaining)
            self.stats["source_misses"] += 1
            self.stats["source_bytes_read"] += used
            return (redact(text), used, None, hashlib.sha256(text.encode("utf-8")).hexdigest()) if reason is None else (None, used, reason, None)
        consumed = 0
        try:
            with _source(self.project, relative) as (descriptor, before):
                if before.st_size > MAX_FILE_BYTES:
                    return None, 0, "file exceeds 256 KiB limit", None
                if before.st_size > remaining:
                    return None, 0, "scan byte budget exhausted", None
                identity = [relative, _signature(before)]
                cached = self.get("source", identity)
                if (isinstance(cached, dict) and set(cached) == {"text", "sha256", "size"}
                        and isinstance(cached["text"], str) and type(cached["size"]) is int
                        and cached["size"] == before.st_size and isinstance(cached["sha256"], str)
                        and len(cached["sha256"]) == 64
                        and _signature(before) == _signature(os.fstat(descriptor))):
                    self.stats["source_hits"] += 1
                    return cached["text"], before.st_size, None, cached["sha256"]
                self.stats["source_misses"] += 1
                limit = min(MAX_FILE_BYTES, remaining)
                chunks = []
                while consumed <= limit:
                    chunk = os.read(descriptor, min(65536, limit + 1 - consumed))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    consumed += len(chunk)
                self.stats["source_bytes_read"] += consumed
                if consumed > limit or _signature(before) != _signature(os.fstat(descriptor)):
                    return None, consumed, "file changed or exceeds read budget", None
                data = b"".join(chunks)
            if b"\0" in data:
                return None, consumed, "binary file withheld", None
            text, sha = redact(data.decode("utf-8")), hashlib.sha256(data).hexdigest()
            self.put("source", identity, {"text": text, "sha256": sha, "size": consumed})
            return text, consumed, None, sha
        except (OSError, UnicodeError, ValueError):
            return None, consumed, "unreadable or unsafe source withheld", None

    def parse(self, path, text):
        key = [path, hashlib.sha256(text.encode("utf-8")).hexdigest()]
        cached = self.get("ast", key)
        if cached is not None:
            try:
                tree = _ast_decode(cached)
                if not isinstance(tree, ast.Module):
                    raise ValueError()
                self.stats["reused_parses"] += 1
                return tree
            except FAILURES:
                pass
        self.stats["parsed_files"] += 1
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(text)
        try:
            self.put("ast", key, _ast_encode(tree))
        except FAILURES:
            pass
        return tree

    def _write_private(self, parent, name, raw):
        temporary = ".parser-" + secrets.token_hex(16)
        descriptor = None
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=parent)
            self.stats["writes"] = 1
            view = memoryview(raw)
            while view:
                count = os.write(descriptor, view)
                if count <= 0:
                    raise OSError()
                view = view[count:]
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass

    def finish(self):
        if not self.writable or not self.usable or not self.dirty:
            return
        try:
            with self._directory(create=True) as parent:
                try:
                    key = self._read_private(parent, "key", 32)
                except FileNotFoundError:
                    # Publish an exclusive key; never replace another process's key.
                    key = secrets.token_bytes(32)
                    descriptor = os.open("key", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                         0o600, dir_fd=parent)
                    self.stats["writes"] = 1
                    try:
                        if os.write(descriptor, key) != len(key):
                            raise OSError()
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
                if len(key) != 32 or (self.key is not None and key != self.key):
                    raise ValueError()
                # Existing unsafe files are never replaced, including symlinks.
                try:
                    current = self._read_private(parent, self.name, MAX_BYTES)
                except FileNotFoundError:
                    current = None
                if (hashlib.sha256(current).hexdigest() if current is not None else None) != self.record_digest:
                    raise ValueError()
                payload = {"schema": SCHEMA, "project": self.identity, "policy": self.policy,
                           "entries": {key: value for key, value in self.entries.items() if key in self.touched}}
                raw = _encoded({"payload": payload,
                                "signature": hmac.new(key, _encoded(payload), hashlib.sha256).hexdigest()})
                if len(raw) > MAX_BYTES:
                    return
                self._write_private(parent, self.name, raw)
                self.key = key
                self.record_digest = hashlib.sha256(raw).hexdigest()
                self.stats["records_saved"] += 1
                self.dirty = False
        except FAILURES:
            self.stats["write_failures"] += 1
