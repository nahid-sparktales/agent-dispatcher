#!/usr/bin/env python3
"""Explicit local check receipts; no observation hooks or host configuration writes.

Receipts contain hashes, redacted command identity and structured outcomes, never raw output.
They are editable local records, not tamper-proof attestations. Runner summaries
report counts, never behavioral coverage or deployment/browser correctness.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import types

FORMAT_VERSION = 1
OWNER = "agent-dispatcher-verification"
MAX_ENTRIES = 20
MAX_RECEIPT_BYTES = 16 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_SCAN_BYTES = 64 * 1024 * 1024
MAX_SCAN_SECONDS = 10
MAX_STDIN_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 1024 * 1024
MAX_FILES = 10000
HASH = re.compile(r"[0-9a-f]{64}\Z")
OUTCOMES = {"tests_passed", "zero_tests", "tests_failed", "command_failed",
            "command_succeeded", "executed_unknown", "timeout", "denied", "not_run", "launch_failed"}


class VerificationError(ValueError):
    """Diagnostics deliberately do not echo untrusted arguments or file contents."""


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, "verification.py: invalid arguments; use --help. Input values withheld.\n")


def _runtime(pack=None):
    # Load only an adjacent packaged module; the caller's cwd never supplies imports.
    path = Path(__file__).resolve().with_name("context.py")
    module = types.ModuleType("_dispatcher_verification_context")
    module.__file__ = str(path)
    try:
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)
        resolved = module.find_pack(pack)
        return module, module._scrubber(resolved)
    except (OSError, ValueError, AttributeError, ImportError):
        raise VerificationError("Required packaged context/redaction helpers are unavailable; repair the pack.") from None


def _project(value):
    try:
        path = Path(value).expanduser().resolve(strict=True)
        if not path.is_dir():
            raise ValueError()
        return path
    except (OSError, ValueError, TypeError):
        raise VerificationError("Project must be an existing directory.") from None


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _project_id(project):
    return _digest(os.fsencode(str(project)))


def _safe_text(value, scrub, limit=240):
    if not isinstance(value, str):
        raise VerificationError("Labels and reasons must be text; values withheld.")
    # Scrub with headroom before truncation, so a recognizable credential at the
    # visible boundary cannot survive as a shortened fragment.
    value = scrub(value[:4096])
    return " ".join(value.split())[:limit]


def _receipt_path(project, value):
    try:
        path = Path(os.path.abspath(Path(value).expanduser()))
        for parent in (path, *path.parents):
            if parent.is_symlink():
                raise ValueError()
        if path.is_relative_to(project) or not path.parent.is_dir():
            raise ValueError()
        parent = path.parent.stat()
        if parent.st_uid != os.getuid():
            raise ValueError()
        if path.exists():
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                raise ValueError()
        return path
    except (OSError, ValueError, TypeError):
        raise VerificationError("Receipt must be outside the project, in an existing directory you own, with no symlinks or unowned files.") from None


def _validate_snapshot(snapshot):
    if (not isinstance(snapshot, dict) or set(snapshot) != {"files", "complete", "omitted", "inspected_bytes", "diagnostics"}
            or type(snapshot["complete"]) is not bool or not isinstance(snapshot["files"], dict)
            or len(snapshot["files"]) > MAX_FILES or not isinstance(snapshot["omitted"], dict)
            or not isinstance(snapshot["diagnostics"], list) or len(snapshot["diagnostics"]) > 20
            or any(not isinstance(x, str) or len(x) > 300 for x in snapshot["diagnostics"])
            or type(snapshot["inspected_bytes"]) is not int or not 0 <= snapshot["inspected_bytes"] <= MAX_SCAN_BYTES):
        raise ValueError()
    for key, value in snapshot["files"].items():
        if not HASH.fullmatch(key) or not isinstance(value, str) or not HASH.fullmatch(value):
            raise ValueError()
    if any(not isinstance(k, str) or len(k) > 80 or type(v) is not int or v < 0 for k, v in snapshot["omitted"].items()):
        raise ValueError()


def _valid_count(value):
    return type(value) is int and 0 <= value <= 10**12


def _validate_observation(entry, snapshots):
    base_keys = {"label", "provenance", "outcome", "execution", "before_complete", "changed_during_check", "snapshot", "recorded_at_unix"}
    if (not isinstance(entry, dict) or entry.get("outcome") not in OUTCOMES
            or entry.get("provenance") not in {"observed_execution", "reported_note"}
            or not isinstance(entry.get("label"), str) or len(entry["label"]) > 240
            or type(entry.get("before_complete")) is not bool
            or not _valid_count(entry.get("recorded_at_unix"))
            or not isinstance(entry.get("execution"), dict)
            or not isinstance(entry.get("changed_during_check"), dict)):
        raise ValueError()
    if entry["provenance"] == "reported_note":
        if (set(entry) != base_keys | {"reason"} or entry["outcome"] not in {"denied", "not_run"}
                or entry["snapshot"] is not None or entry["execution"] or entry["changed_during_check"]
                or not isinstance(entry["reason"], str) or len(entry["reason"]) > 240):
            raise ValueError()
        return
    if (set(entry) != base_keys or entry["snapshot"] not in snapshots
            or set(entry["changed_during_check"]) != {"added", "deleted", "modified"}
            or not all(_valid_count(v) for v in entry["changed_during_check"].values())):
        raise ValueError()
    execution = entry["execution"]
    if (set(execution) != {"kind", "runner", "exit_code", "test_counts", "stdout_bytes", "stderr_bytes", "output_truncated", "output_sha256", "command", "stdin"}
            or execution["kind"] not in {"tests", "check"} or execution["runner"] not in {None, "unittest", "pytest"}
            or execution["exit_code"] is not None and type(execution["exit_code"]) is not int
            or not all(_valid_count(execution[k]) for k in ("stdout_bytes", "stderr_bytes"))
            or type(execution["output_truncated"]) is not bool
            or execution["output_sha256"] is not None and not HASH.fullmatch(execution["output_sha256"])):
        raise ValueError()
    input_evidence = execution["stdin"]
    if (not isinstance(input_evidence, dict) or set(input_evidence) != {"provided", "bytes", "sha256"}
            or type(input_evidence["provided"]) is not bool or not _valid_count(input_evidence["bytes"])
            or input_evidence["bytes"] > MAX_STDIN_BYTES
            or input_evidence["sha256"] is not None and not HASH.fullmatch(input_evidence["sha256"])):
        raise ValueError()
    command = execution["command"]
    if (not isinstance(command, dict) or set(command) != {"argv", "complete"}
            or not isinstance(command["argv"], list) or len(command["argv"]) > 65
            or any(not isinstance(v, str) or len(v) > 240 for v in command["argv"])
            or type(command["complete"]) is not bool):
        raise ValueError()
    counts = execution["test_counts"]
    if counts is not None:
        keys = {"run", "skipped", "failed", "errors", "runner_reported_pass"}
        if (not isinstance(counts, dict) or set(counts) not in (keys, keys | {"passed"})
                or type(counts["runner_reported_pass"]) is not bool
                or not all(_valid_count(v) for k, v in counts.items() if k != "runner_reported_pass")):
            raise ValueError()


def _read_receipt(path, project, *, missing=False):
    if not path.exists():
        if missing:
            return {"format_version": FORMAT_VERSION, "owner": OWNER, "owner_uid": os.getuid(),
                    "project_id": _project_id(project), "observations": [], "snapshots": {}}, None
        raise VerificationError("Receipt does not exist.")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                raise ValueError()
            raw = handle.read(MAX_RECEIPT_BYTES + 1)
        if len(raw) > MAX_RECEIPT_BYTES:
            raise ValueError()
        receipt = json.loads(raw)
        if (not isinstance(receipt, dict) or set(receipt) != {"format_version", "owner", "owner_uid", "project_id", "observations", "snapshots"}
                or receipt["format_version"] != FORMAT_VERSION or receipt["owner"] != OWNER
                or receipt["owner_uid"] != os.getuid() or receipt["project_id"] != _project_id(project)
                or not isinstance(receipt["observations"], list) or len(receipt["observations"]) > MAX_ENTRIES
                or not isinstance(receipt["snapshots"], dict) or len(receipt["snapshots"]) > MAX_ENTRIES):
            raise ValueError()
        for key, snapshot in receipt["snapshots"].items():
            if not HASH.fullmatch(key):
                raise ValueError()
            _validate_snapshot(snapshot)
            if key != _digest(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()):
                raise ValueError()
        for entry in receipt["observations"]:
            _validate_observation(entry, receipt["snapshots"])
        return receipt, _digest(raw)
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        raise VerificationError("Receipt is malformed, belongs to another project, or is not an owned Dispatcher receipt; it was not overwritten.") from None


def _write_receipt(path, receipt, expected, project):
    raw = json.dumps(receipt, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    if len(raw) > MAX_RECEIPT_BYTES:
        raise VerificationError("Receipt reached its size limit; use a fresh explicitly authorized receipt path.")
    _receipt_path(project, path)
    if _existing_digest(path) != expected:
        raise VerificationError("Receipt changed during the check; no replacement was performed.")
    fd, temp_name = tempfile.mkstemp(prefix=".dispatcher-receipt-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        # The parent is an explicitly chosen owned directory. Recheck the destination
        # before replacement; no arbitrary existing file can be adopted as a receipt.
        if path.exists():
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                raise VerificationError("Receipt destination changed; no replacement was performed.")
            os.replace(temp_name, path)
        else:
            os.link(temp_name, path)
            os.unlink(temp_name)
    except OSError:
        raise VerificationError("Could not atomically save the owned receipt; check its destination.") from None
    finally:
        if os.path.lexists(temp_name):
            os.unlink(temp_name)


def _existing_digest(path):
    if not path.exists():
        return None
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_RECEIPT_BYTES:
                raise ValueError()
            return _digest(handle.read(MAX_RECEIPT_BYTES + 1))
    except (OSError, ValueError):
        raise VerificationError("Receipt changed or could not be read safely.") from None


def _snapshot(project, runtime):
    diagnostics = []
    paths = runtime._enumerate(project, diagnostics)
    complete = not diagnostics
    omitted = Counter()
    result = {}
    consumed = 0
    deadline = time.monotonic() + MAX_SCAN_SECONDS
    for relative in paths:
        if time.monotonic() >= deadline:
            omitted["scan time limit"] += 1
            complete = False
            break
        # Hash dependency locks and binary source assets too; only credentials and
        # host/state metadata are intentionally outside the freshness contract.
        if runtime._skip(relative) == "credential file withheld":
            omitted["credential files"] += 1
            continue
        if ".git" in PurePosixPath(relative).parts:
            continue
        path = project / relative
        try:
            cursor = project
            for part in PurePosixPath(relative).parts:
                cursor /= part
                if cursor.is_symlink():
                    raise ValueError("symlink")
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
            with os.fdopen(fd, "rb") as handle:
                before = os.fstat(handle.fileno())
                if not stat.S_ISREG(before.st_mode):
                    raise ValueError("nonregular")
                if before.st_size > MAX_FILE_BYTES or consumed + before.st_size > MAX_SCAN_BYTES:
                    raise ValueError("size")
                digest = hashlib.sha256()
                read_bytes = 0
                while True:
                    if time.monotonic() >= deadline:
                        raise ValueError("time")
                    chunk = handle.read(min(65536, MAX_FILE_BYTES + 1 - read_bytes))
                    if not chunk:
                        break
                    read_bytes += len(chunk)
                    consumed += len(chunk)
                    if read_bytes > MAX_FILE_BYTES or consumed > MAX_SCAN_BYTES:
                        raise ValueError("size")
                    digest.update(chunk)
                after = os.fstat(handle.fileno())
                if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise ValueError("changing")
                result[_digest(relative.encode())] = digest.hexdigest()
        except FileNotFoundError:
            # Git lists deleted tracked paths too; absence is represented by the
            # missing manifest key and can be compared against the earlier check.
            continue
        except (OSError, ValueError):
            omitted["unreadable, unsafe, changing or oversized files"] += 1
            complete = False
    return {"files": result, "complete": complete, "omitted": dict(omitted),
            "inspected_bytes": min(consumed, MAX_SCAN_BYTES), "diagnostics": diagnostics[:20]}


def _difference(before, after):
    old, new = before["files"], after["files"]
    return {"added": len(new.keys() - old.keys()) if before["complete"] else 0,
            "deleted": len(old.keys() - new.keys()) if after["complete"] else 0,
            "modified": sum(old[key] != new[key] for key in old.keys() & new.keys())}


def _python_invocation(command):
    name = Path(command[0]).name.lower()
    if not re.fullmatch(r"python(?:3(?:\.\d+)?)?(?:\.exe)?", name):
        return set(), None
    rest = list(command[1:])
    options = set()
    while rest and rest[0] in {"-B", "-I", "-E", "-s", "-u", "-P"}:
        options.add(rest.pop(0))
    # Stop at -m, a script path, or an unsupported option. Flags after the
    # module/script name belong to that program, never to the interpreter.
    return options, rest


def _python_module(command):
    return _python_invocation(command)[1]


def _runner(command, project):
    options, rest = _python_invocation(command)
    if rest is None or len(rest) < 2 or rest[0] != "-m" or rest[1] not in {"unittest", "pytest"}:
        return None
    interpreter = command[0]
    resolved = Path(shutil.which(interpreter) or interpreter)
    if not resolved.is_absolute():
        resolved = project / resolved
    if resolved.resolve().is_relative_to(project):
        return None
    # Python -m normally imports from cwd and PYTHONPATH. A same-name project
    # module cannot establish that the recognized runner produced the summary.
    module = rest[1]
    if "-I" not in options and "-P" not in options:
        if (project / (module + ".py")).exists() or (project / module).exists():
            return None
    if "-I" not in options and "-E" not in options and os.environ.get("PYTHONPATH"):
        return None
    return module


def _test_summary(runner, output):
    if runner == "unittest":
        matches = list(re.finditer(r"(?m)^Ran (\d+) tests? in [0-9.]+s\s*$", output))
        if len(matches) != 1:
            return None
        tail = output[matches[0].end():].strip()
        okay = re.fullmatch(r"OK(?: \(skipped=(\d+)\))?", tail)
        failed = re.fullmatch(r"FAILED \(([^\n]+)\)", tail)
        if not okay and not failed and not (int(matches[0][1]) == 0 and tail == "NO TESTS RAN"):
            return None
        counts = {"run": int(matches[0][1]), "skipped": int(okay[1] or 0) if okay else 0,
                  "failed": 0, "errors": 0, "runner_reported_pass": bool(okay)}
        if failed:
            for key, value in re.findall(r"(failures|errors|skipped)=(\d+)", failed[1]):
                counts[{"failures": "failed"}.get(key, key)] = int(value)
        return counts
    if runner == "pytest":
        # Require a final summary, not a collection/progress line or echoed prose.
        last = output.strip().splitlines()[-1:] or [""]
        line = last[0].strip("= ")
        match = re.fullmatch(r"(.+?) in \d+(?:\.\d+)?s(?: \([^\n]+\))?", line)
        if not match:
            return None
        body = match[1]
        if body == "no tests ran":
            return {"run": 0, "skipped": 0, "failed": 0, "errors": 0, "runner_reported_pass": False}
        pairs = re.findall(r"(\d+) (passed|failed|skipped|deselected|xfailed|xpassed|warnings?|errors?)", body)
        if not pairs or re.sub(r"\d+ (?:passed|failed|skipped|deselected|xfailed|xpassed|warnings?|errors?)", "", body).strip(", "):
            return None
        counts = Counter()
        for value, key in pairs:
            counts[key.rstrip("s") if key in {"warnings", "errors"} else key] += int(value)
        return {"run": sum(counts[x] for x in ("passed", "failed", "skipped", "xfailed", "xpassed")),
                "passed": counts["passed"], "skipped": counts["skipped"] + counts["xfailed"],
                "failed": counts["failed"] + counts["xpassed"], "errors": counts["error"],
                "runner_reported_pass": counts["passed"] > 0 and not (counts["failed"] or counts["error"] or counts["xpassed"])}
    return None


def _kill_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    finally:
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def _command_identity(command, scrub):
    result = []
    complete = len(command) <= 64
    hide_next = False
    for index, arg in enumerate(command[:64]):
        if hide_next:
            result.append("[redacted argument]")
            complete = False
            hide_next = False
            continue
        if index:
            inline = re.match(r"^(--(?:command|eval|execute))(?:=|$)|^(-[ce])", arg)
            if inline:
                result.extend([inline[1] or inline[2], "[inline payload omitted]"])
                complete = False
                break
            flag, separator, value = arg.partition("=")
            if (flag.startswith("-") and re.search(
                    r"(?:^|[-_.])(?:password|passwd|passphrase|secret|token|api[-_]?key|credential)s?$",
                    flag.lstrip("-"), re.I)):
                safe_flag = _safe_text(flag, scrub, 200)
                result.append(safe_flag + "=[redacted argument]" if separator else safe_flag)
                complete = False
                hide_next = not separator
                continue
        safe = _safe_text(arg, scrub, 240)
        result.append(safe)
        complete = complete and safe == arg
    return {"argv": result, "complete": complete}


def _execute(project, command, timeout, kind, stdin_data=None):
    runner = _runner(command, project)
    evidence = {"kind": kind, "runner": runner, "exit_code": None, "test_counts": None,
                "stdout_bytes": 0, "stderr_bytes": 0, "output_truncated": False,
                "output_sha256": None, "stdin": {"provided": stdin_data is not None,
                    "bytes": len(stdin_data) if stdin_data is not None else 0,
                    "sha256": _digest(stdin_data) if stdin_data is not None else None}}
    try:
        # Do not write Python bytecode in the project merely to observe a check.
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        process = subprocess.Popen(command, cwd=project, shell=False, stdin=subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                                   start_new_session=True)
    except PermissionError:
        return "denied", evidence
    except OSError:
        return "launch_failed", evidence
    deadline = time.monotonic() + timeout
    output = bytearray()
    digest = hashlib.sha256()
    timed_out = False
    try:
        with selectors.DefaultSelector() as selector:
            for name, handle in (("stdout", process.stdout), ("stderr", process.stderr)):
                selector.register(handle, selectors.EVENT_READ, name)
            input_offset = 0
            if stdin_data is not None:
                os.set_blocking(process.stdin.fileno(), False)
                selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    _kill_group(process)
                    break
                for key, _ in selector.select(min(remaining, 0.1)):
                    if key.data == "stdin":
                        try:
                            if input_offset < len(stdin_data):
                                input_offset += os.write(key.fd, stdin_data[input_offset:input_offset + 4096])
                            if input_offset >= len(stdin_data):
                                selector.unregister(key.fileobj)
                                process.stdin.close()
                        except BrokenPipeError:
                            selector.unregister(key.fileobj)
                            process.stdin.close()
                        continue
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    evidence[key.data + "_bytes"] += len(chunk)
                    digest.update(key.data.encode() + b"\0" + chunk)
                    available = MAX_OUTPUT_BYTES - len(output)
                    output.extend(chunk[:available])
                    if len(chunk) > available:
                        evidence["output_truncated"] = True
            if not timed_out:
                try:
                    process.wait(timeout=max(0.001, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    timed_out = True
                    _kill_group(process)
    finally:
        if process.poll() is None:
            _kill_group(process)
        process.stdout.close()
        process.stderr.close()
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
    evidence["exit_code"] = process.returncode
    evidence["output_sha256"] = digest.hexdigest()
    if timed_out:
        return "timeout", evidence
    if kind == "tests" and not evidence["output_truncated"]:
        try:
            evidence["test_counts"] = _test_summary(runner, output.decode("utf-8", errors="replace"))
        except (ValueError, OverflowError):
            evidence["test_counts"] = None
        if evidence["test_counts"] and any(not _valid_count(v) for k, v in evidence["test_counts"].items() if k != "runner_reported_pass"):
            evidence["test_counts"] = None
    counts = evidence["test_counts"]
    if counts and counts["run"] == 0 and not counts["errors"]:
        return "zero_tests", evidence
    if process.returncode != 0:
        return "tests_failed" if counts and (counts["failed"] or counts["errors"]) else "command_failed", evidence
    if kind == "check":
        return "command_succeeded", evidence
    if counts and counts["runner_reported_pass"] and counts["run"] > counts["skipped"]:
        return "tests_passed", evidence
    return "executed_unknown", evidence


def _inspection(receipt, current, scrub):
    observations = []
    for entry in receipt["observations"]:
        entry = json.loads(json.dumps(entry))
        snapshot = receipt["snapshots"].get(entry.pop("snapshot"))
        changes = _difference(snapshot, current) if snapshot is not None else None
        if entry["provenance"] == "reported_note":
            freshness = "not_applicable"
        elif any(entry["changed_during_check"].values()) or changes and any(changes.values()):
            freshness = "stale"
        elif not entry["before_complete"] or not snapshot["complete"] or not current["complete"]:
            freshness = "unknown"
        else:
            freshness = "current"
        entry["label"] = _safe_text(entry["label"], scrub)
        if "reason" in entry:
            entry["reason"] = _safe_text(entry["reason"], scrub)
        if entry["execution"]:
            command = entry["execution"]["command"]
            safe_command = [_safe_text(value, scrub) for value in command["argv"]]
            command["complete"] = command["complete"] and safe_command == command["argv"]
            command["argv"] = safe_command
        entry.update(freshness=freshness, changes_since_check=changes)
        observations.append(entry)
    return {"format_version": FORMAT_VERSION, "observations": observations,
            "snapshot": {k: v for k, v in current.items() if k != "files"} | {"file_count": len(current["files"])},
            "limitations": ["Counts are runner reports, not proof of behavioral coverage.",
                            "Freshness covers bounded ignore-aware files; ignored files, credentials, Dispatcher state and external dependencies are outside it.",
                            "Receipts are editable local records, not tamper-proof attestations."]}


def run_check(project, receipt, command, *, kind="tests", label="", timeout=120, pack=None, stdin_data=None):
    """Run one explicitly authorized argv and append its observed result to a receipt."""
    runtime, scrub = _runtime(pack)
    project = _project(project)
    path = _receipt_path(project, receipt)
    record, expected = _read_receipt(path, project, missing=True)
    if len(record["observations"]) >= MAX_ENTRIES:
        raise VerificationError("Receipt has 20 observations; use a fresh explicitly authorized receipt path.")
    if (kind not in {"tests", "check"} or not isinstance(command, (list, tuple)) or not command
            or len(command) > 256 or any(not isinstance(arg, str) or "\0" in arg or len(arg) > 65536 for arg in command)
            or not command[0] or isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0.01 <= timeout <= 3600):
        raise VerificationError("Invalid check kind, command or timeout; values withheld.")
    if stdin_data is not None and (not isinstance(stdin_data, bytes) or len(stdin_data) > MAX_STDIN_BYTES):
        raise VerificationError("Explicit stdin must be bytes and at most 64 KiB; the check was not started.")
    rest = _python_module(command)
    if rest and rest[0] == "-" and stdin_data is None:
        raise VerificationError("Python stdin checks require --stdin with an explicit bounded payload; the check was not started.")
    label = _safe_text(label, scrub) or ("Tests" if kind == "tests" else "Check")
    if not os.access(path.parent, os.W_OK):
        raise VerificationError("Receipt directory is not writable; the check was not started.")
    before = _snapshot(project, runtime)
    outcome, execution = _execute(project, list(command), timeout, kind, stdin_data)
    execution["command"] = _command_identity(command, scrub)
    after = _snapshot(project, runtime)
    snapshot_id = _digest(json.dumps(after, sort_keys=True, separators=(",", ":")).encode())
    record["snapshots"][snapshot_id] = after
    record["observations"].append({"label": label, "provenance": "observed_execution", "outcome": outcome,
                                   "execution": execution, "before_complete": before["complete"],
                                   "changed_during_check": _difference(before, after), "snapshot": snapshot_id,
                                   "recorded_at_unix": int(time.time())})
    _write_receipt(path, record, expected, project)
    return _inspection(record, after, scrub)


def inspect_receipt(project, receipt, *, pack=None):
    """Read a receipt and compare it to today's bounded local source inventory."""
    runtime, scrub = _runtime(pack)
    project = _project(project)
    record, _ = _read_receipt(_receipt_path(project, receipt), project)
    return _inspection(record, _snapshot(project, runtime), scrub)


def record_unrun(project, receipt, *, status, reason, label="", pack=None):
    """Append a clearly attributed note; it is never observed execution evidence."""
    runtime, scrub = _runtime(pack)
    project = _project(project)
    path = _receipt_path(project, receipt)
    record, expected = _read_receipt(path, project, missing=True)
    if status not in {"not_run", "denied"} or len(record["observations"]) >= MAX_ENTRIES:
        raise VerificationError("Notes require not_run or denied, with fewer than 20 observations.")
    reason = _safe_text(reason, scrub)
    if not reason:
        raise VerificationError("Notes require a short reason.")
    record["observations"].append({"label": _safe_text(label, scrub) or "Check", "provenance": "reported_note",
                                   "outcome": status, "reason": reason, "execution": {}, "before_complete": False,
                                   "changed_during_check": {}, "snapshot": None, "recorded_at_unix": int(time.time())})
    _write_receipt(path, record, expected, project)
    empty = {"files": {}, "complete": False, "omitted": {}, "inspected_bytes": 0, "diagnostics": ["Note only; source was not scanned."]}
    current = _snapshot(project, runtime) if record["snapshots"] else empty
    return _inspection(record, current, scrub)


def render(result):
    """Short everyday-language output; JSON preserves the detailed evidence."""
    words = {"tests_passed": "tests passed", "zero_tests": "no tests ran", "tests_failed": "tests failed",
             "command_failed": "command failed", "command_succeeded": "command succeeded",
             "executed_unknown": "command finished; test count unknown", "timeout": "timed out",
             "denied": "permission denied", "not_run": "not run", "launch_failed": "could not start"}
    lines = []
    entries = result["observations"]
    for entry in entries[-4:]:
        label = " ".join(entry["label"].split()[:6])
        text = words[entry["outcome"]]
        count = entry["execution"].get("test_counts")
        if count:
            text += f" ({count['run']} reported; {count['skipped']} skipped)"
        if entry["freshness"] == "stale":
            text += "; files changed—rerun needed"
        elif entry["freshness"] == "unknown" and entry["provenance"] == "observed_execution":
            text += "; file coverage incomplete"
        if entry["provenance"] == "reported_note":
            text += " (reported note, not an observed run)"
            text += "; " + " ".join(entry["reason"].split()[:8])
        lines.append(f"- {label}: {text}.")
    if len(entries) > 4:
        lines.append(f"{len(entries) - 4} earlier checks are in JSON output.")
    lines.append("This checks only the recorded commands and visible local files. Browser, production, ignored files and outside changes are not verified.")
    return "\n".join(lines)


def _read_stdin():
    if sys.stdin.isatty():
        raise VerificationError("Pass an explicit stdin pipe or heredoc; interactive input is not supported.")
    if stat.S_ISREG(os.fstat(sys.stdin.fileno()).st_mode):
        data = os.read(sys.stdin.fileno(), MAX_STDIN_BYTES + 1)
        if len(data) > MAX_STDIN_BYTES:
            raise VerificationError("Explicit stdin exceeds 64 KiB; the check was not started.")
        return data
    deadline = time.monotonic() + 10
    data = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(sys.stdin, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise VerificationError("Explicit stdin did not finish within ten seconds; the check was not started.")
            if not selector.select(min(remaining, 0.1)):
                continue
            chunk = os.read(sys.stdin.fileno(), min(4096, MAX_STDIN_BYTES + 1 - len(data)))
            if not chunk:
                return bytes(data)
            data.extend(chunk)
            if len(data) > MAX_STDIN_BYTES:
                raise VerificationError("Explicit stdin exceeds 64 KiB; the check was not started.")


def main(argv=None):
    parser = SafeParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True, parser_class=SafeParser)
    for name in ("run", "show", "note"):
        command = sub.add_parser(name)
        command.add_argument("--project", required=True)
        command.add_argument("--receipt", required=True)
        command.add_argument("--json", action="store_true")
        command.add_argument("--pack")
        if name != "show":
            command.add_argument("--label", default="")
        if name == "run":
            command.add_argument("--kind", choices=("tests", "check"), default="tests")
            command.add_argument("--timeout", type=float, default=120)
            command.add_argument("--stdin", action="store_true", help="Read up to 64 KiB of explicit stdin and pass it to the command.")
            command.add_argument("command", nargs=argparse.REMAINDER)
        if name == "note":
            command.add_argument("--status", choices=("not_run", "denied"), required=True)
            command.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "run":
            command = args.command[1:] if args.command[:1] == ["--"] else args.command
            result = run_check(args.project, args.receipt, command, kind=args.kind, label=args.label, timeout=args.timeout, pack=args.pack,
                               stdin_data=_read_stdin() if args.stdin else None)
        elif args.action == "show":
            result = inspect_receipt(args.project, args.receipt, pack=args.pack)
        else:
            result = record_unrun(args.project, args.receipt, status=args.status, reason=args.reason, label=args.label, pack=args.pack)
        print(json.dumps(result, indent=2, sort_keys=True) if args.json else render(result))
        if args.action == "run" and result["observations"][-1]["outcome"] in {"tests_failed", "command_failed", "timeout", "denied", "launch_failed", "zero_tests"}:
            return 1
        return 0
    except (VerificationError, OSError):
        # Generic OSError handling avoids printing credential-shaped arguments or
        # subprocess exception reprs. Deliberately authored errors are safe text.
        error = sys.exc_info()[1]
        print(str(error) if isinstance(error, VerificationError) else "Verification could not finish; local input or receipt I/O failed.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
