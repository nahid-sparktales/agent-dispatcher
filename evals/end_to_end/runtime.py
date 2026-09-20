"""File and subprocess boundaries shared by the evaluation runner."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import threading
import time

EXCLUDED = {".git", ".agents", ".claude", "__pycache__", ".pytest_cache"}
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TREE_BYTES = 64 * 1024 * 1024


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def tree_files(root, exclude=()):
    """Return bounded regular files, never follow a candidate-created symlink."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("artifact root must be a real directory")
    result = {}
    size = 0
    for folder, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in exclude)
        for name in dirs + sorted(files):
            path = Path(folder) / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise ValueError("symlinks are not allowed in task artifacts")
            if stat.S_ISDIR(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("special files are not allowed in task artifacts")
            if info.st_size > MAX_FILE_BYTES:
                raise ValueError("artifact file exceeds 8 MiB limit")
            size += info.st_size
            if size > MAX_TREE_BYTES:
                raise ValueError("artifact tree exceeds 64 MiB limit")
            result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


def copy_files(files, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe relative artifact path")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def digest_files(files):
    digest = hashlib.sha256()
    for name, content in sorted(files.items()):
        digest.update(name.encode() + b"\0" + str(len(content)).encode() + b"\0" + content)
    return digest.hexdigest()


def digest_tree(root, exclude=()):
    return digest_files(tree_files(root, exclude))


def scrub_text(text, env=None):
    # Remove actual credentials supplied to the subprocess before shape-based filtering.
    for key, value in (env or {}).items():
        if any(word in key.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD")) and len(value) >= 8:
            text = text.replace(value, "[redacted]")
    from decision.redact import scrub
    return scrub(text)


def sanitize(value, env=None):
    if isinstance(value, str):
        return scrub_text(value, env)
    if isinstance(value, dict):
        return {k: sanitize(v, env) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v, env) for v in value]
    return value


def sanitize_stream(stdout, env=None):
    lines = []
    for line in stdout.splitlines():
        try:
            lines.append(json.dumps(sanitize(json.loads(line), env), ensure_ascii=False))
        except ValueError:
            lines.append(scrub_text(line, env))
    return "\n".join(lines) + ("\n" if lines else "")


def execute(argv, *, cwd, env, prompt, timeout, output_limit=20 * 1024 * 1024):
    """Capture bounded streams and terminate the whole process group on timeout/cancel."""
    if os.name != "posix":
        raise ValueError("native eval execution currently requires macOS or Linux")
    started = time.monotonic()
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            start_new_session=True)
    chunks = {"stdout": [], "stderr": []}
    overflow = threading.Event()

    def read_stream(name, stream):
        length = 0
        while True:
            data = stream.read(65536)
            if not data:
                break
            remaining = max(0, output_limit - length)
            chunks[name].append(data[:remaining])
            length += len(data)
            if length > output_limit:
                overflow.set()
        stream.close()

    readers = [threading.Thread(target=read_stream, args=(name, getattr(proc, name)), daemon=True)
               for name in chunks]
    for reader in readers:
        reader.start()

    def input_writer():
        try:
            proc.stdin.write(prompt.encode("utf-8"))
            proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            proc.stdin.close()

    writer = threading.Thread(target=input_writer, daemon=True)
    writer.start()
    timed_out = False
    cancelled = False
    cleanup_warning = None

    def terminate():
        nonlocal cleanup_warning
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        for reader in readers:
            reader.join(timeout=0.1)
        # A descendant may close its streams and ignore TERM. Kill the group even
        # after its leader/readers exit, rather than using pipe closure as proof.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            # Darwin can return EPERM for a group containing only reparented
            # zombies. Preserve the uncertainty rather than claiming cleanup.
            cleanup_warning = "Could not confirm complete process-group cleanup."

    try:
        while proc.poll() is None or any(r.is_alive() for r in readers):
            if time.monotonic() - started >= timeout:
                timed_out = True
                break
            if overflow.wait(0.025):
                break
    except KeyboardInterrupt:
        cancelled = True
    finally:
        terminate()
        proc.wait()
        for reader in readers:
            reader.join(timeout=2)
        writer.join(timeout=2)
    return {"stdout": b"".join(chunks["stdout"]).decode("utf-8", errors="replace"),
            "stderr": b"".join(chunks["stderr"]).decode("utf-8", errors="replace"),
            "returncode": proc.returncode, "timed_out": timed_out,
            "cancelled": cancelled,
            "cleanup_warning": cleanup_warning,
            "output_overflow": overflow.is_set(), "elapsed_seconds": time.monotonic() - started}


def audit_trial_parent(workspace, *, max_entries=10000, max_seconds=5):
    """Inspect metadata in the owned trial parent before teardown, never contents.

    This does not inspect the host or authentication profile. A before/after
    project snapshot cannot see siblings, while this bounded audit can preserve
    their existence without following links or collecting arbitrary file data.
    """
    workspace = Path(workspace)
    root = workspace.parent
    result = {"schema_version": 1, "scope": "owned trial directory outside project",
              "availability": "complete", "entries": [], "entry_count": 0, "clean": None,
              "limits": {"max_entries": max_entries, "max_seconds": max_seconds}, "diagnostics": []}
    started = time.monotonic()
    pending = [Path(".")]
    root_fd = None
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        root_fd = os.open(root, flags)
        while pending:
            if time.monotonic() - started >= max_seconds:
                result["availability"] = "partial"
                result["diagnostics"].append("Owned trial metadata inspection reached its time limit.")
                break
            relative = pending.pop()
            folder_fd = os.dup(root_fd)
            try:
                # Reopen each component relative to an anchored descriptor.
                # A candidate-created/replaced symlink is never traversed.
                for component in relative.parts:
                    child_fd = os.open(component, flags, dir_fd=folder_fd)
                    os.close(folder_fd)
                    folder_fd = child_fd
                with os.scandir(folder_fd) as stream:
                    for entry in stream:
                        if relative == Path(".") and entry.name == workspace.name:
                            continue
                        if time.monotonic() - started >= max_seconds or result["entry_count"] >= max_entries:
                            result["availability"] = "partial"
                            result["diagnostics"].append("Owned trial metadata inspection reached its time or entry limit.")
                            pending.clear()
                            break
                        info = entry.stat(follow_symlinks=False)
                        mode = info.st_mode
                        kind = "symlink" if stat.S_ISLNK(mode) else "directory" if stat.S_ISDIR(mode) else "file" if stat.S_ISREG(mode) else "special"
                        name = relative / entry.name
                        result["entries"].append({"path": name.as_posix(), "kind": kind,
                                                  "size": info.st_size if kind == "file" else None})
                        result["entry_count"] += 1
                        if kind == "directory":
                            pending.append(name)
            finally:
                os.close(folder_fd)
            if result["availability"] == "partial" and not pending:
                break
    except OSError:
        result["availability"] = "partial" if result["entries"] else "unavailable"
        result["diagnostics"].append("Owned trial metadata could not be completely inspected.")
    finally:
        if root_fd is not None:
            os.close(root_fd)
    result["entries"].sort(key=lambda item: item["path"])
    result["clean"] = False if result["entries"] else True if result["availability"] == "complete" else None
    return result
