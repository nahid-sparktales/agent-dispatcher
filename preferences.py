#!/usr/bin/env python3
"""Dispatcher-owned reporting and effort preferences, shared by both hosts.

These are requested preferences, not host model configuration. No host credentials,
settings, or project files are read or written.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import uuid


SCHEMA_VERSION = 1
OWNER = "agent-dispatcher"
MAX_BYTES = 64 * 1024
OUTPUTS = ("eli5-succinct", "detailed")
EFFORTS = ("low", "medium", "high", "host")
DEFAULTS = {"output": "eli5-succinct", "effort": "host"}
FILENAME = "preferences.json"


class PreferencesError(ValueError):
    """Preferences could not be used safely; existing bytes are preserved."""


def _directory(state_dir):
    if state_dir is not None:
        return Path(os.path.abspath(Path(state_dir).expanduser()))
    config = os.environ.get("XDG_CONFIG_HOME")
    if config and Path(config).is_absolute():
        return Path(config) / OWNER
    return Path.home() / ".config" / OWNER


def _project_key(project):
    if project is None:
        return None
    try:
        path = Path(project).expanduser().resolve(strict=True)
        if not path.is_dir():
            raise PreferencesError("Project must be an existing directory.")
        return hashlib.sha256(os.path.normcase(str(path)).encode("utf-8")).hexdigest()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise PreferencesError("Project must be an existing directory.") from exc


def _external_directory(directory, project):
    if project is not None and directory.resolve().is_relative_to(Path(project).expanduser().resolve()):
        raise PreferencesError("Preferences must be stored outside the selected project.")
    return directory


def _owned(info):
    return not hasattr(os, "getuid") or info.st_uid == os.getuid()


def _open_directory(directory, create=False):
    """Pin the final state directory so file operations cannot follow its symlink."""
    try:
        if create:
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            info = directory.lstat()
        except FileNotFoundError:
            return None
        if not stat.S_ISDIR(info.st_mode) or not _owned(info):
            raise PreferencesError("Preference directory must be an owned directory, not a symlink.")
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(directory, flags)
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            os.close(descriptor)
            raise PreferencesError("Preference directory changed while opening it.")
        return descriptor
    except OSError as exc:
        raise PreferencesError("Preference directory is unavailable; existing state was preserved.") from exc


def _empty():
    return {"schema_version": SCHEMA_VERSION, "owner": OWNER, "global": {}, "projects": {}}


def _validate_values(values):
    if not isinstance(values, dict) or set(values) - set(DEFAULTS):
        raise PreferencesError("Unknown preference fields; existing state was preserved.")
    for key, allowed in (("output", OUTPUTS), ("effort", EFFORTS)):
        if key in values and values[key] not in allowed:
            raise PreferencesError("Invalid preference value; existing state was preserved.")


def _validate(data):
    if (not isinstance(data, dict) or set(data) != {"schema_version", "owner", "global", "projects"}
            or type(data["schema_version"]) is not int or data["schema_version"] != SCHEMA_VERSION
            or data["owner"] != OWNER or not isinstance(data["projects"], dict)):
        raise PreferencesError("Unrecognized preference ownership or schema; existing state was preserved.")
    _validate_values(data["global"])
    for key, values in data["projects"].items():
        if not isinstance(key, str) or len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise PreferencesError("Invalid project preference key; existing state was preserved.")
        _validate_values(values)
    return data


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise PreferencesError("Duplicate preference fields; existing state was preserved.")
        value[key] = item
    return value


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _read(descriptor):
    if descriptor is None:
        return _empty(), None
    handle = None
    try:
        try:
            info = os.stat(FILENAME, dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return _empty(), None
        if not stat.S_ISREG(info.st_mode) or not _owned(info) or info.st_nlink != 1:
            raise PreferencesError("Preference file must be an owned regular file, not a link.")
        if info.st_size > MAX_BYTES:
            raise PreferencesError("Preference file exceeds its size limit; existing state was preserved.")
        handle = os.open(FILENAME, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                         | getattr(os, "O_NONBLOCK", 0), dir_fd=descriptor)
        opened = os.fstat(handle)
        if _identity(opened) != _identity(info):
            raise PreferencesError("Preference file changed while opening it.")
        with os.fdopen(handle, "rb") as stream:
            handle = None
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise PreferencesError("Preference file exceeds its size limit; existing state was preserved.")
        return _validate(json.loads(raw, object_pairs_hook=_unique_object)), _identity(info)
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise PreferencesError("Preference file is unreadable or invalid; existing state was preserved.") from exc
    finally:
        if handle is not None:
            os.close(handle)


def _result(data, identity, directory, key):
    values, sources = dict(DEFAULTS), {name: "default" for name in DEFAULTS}
    for scope, scoped in (("global", data["global"]), ("project", data["projects"].get(key, {}))):
        values.update(scoped)
        sources.update({name: scope for name in scoped})
    return {
        "schema_version": SCHEMA_VERSION, "source": "dispatcher_preferences",
        **values, "requested_effort": values["effort"], "effective_effort": "unknown",
        "requires_host_confirmation": True,
        "effort_note": "Requested preference only; the host must confirm its actual effort setting.",
        "sources": sources, "project_key": key, "scope": "project" if key else "global",
        "storage_path": str(directory / FILENAME), "saved": identity is not None,
        "diagnostics": [],
    }


def get_preferences(project=None, state_dir=None):
    """Read global preferences plus explicit project overrides without writing files.

    ``state_dir`` is the dispatcher directory containing ``preferences.json``.
    Invalid or unsafe existing state raises :class:`PreferencesError`.
    """
    key = _project_key(project)
    directory = _external_directory(_directory(state_dir), project)
    descriptor = _open_directory(directory)
    try:
        data, identity = _read(descriptor)
        return _result(data, identity, directory, key)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def set_preferences(*, output=None, effort=None, project=None, state_dir=None):
    """Atomically update requested preferences, leaving host configuration untouched."""
    updates = {name: value for name, value in (("output", output), ("effort", effort)) if value is not None}
    if not updates:
        raise PreferencesError("Specify an output style or requested effort to save.")
    _validate_values(updates)
    key = _project_key(project)
    directory = _external_directory(_directory(state_dir), project)
    descriptor = _open_directory(directory, create=True)
    temporary = None
    try:
        data, identity = _read(descriptor)
        target = data["global"] if key is None else data["projects"].setdefault(key, {})
        target.update(updates)
        payload = (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")
        if len(payload) > MAX_BYTES:
            raise PreferencesError("Updated preferences exceed their size limit; existing state was preserved.")
        temporary = f".preferences-{uuid.uuid4().hex}.tmp"
        handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=descriptor)
        with os.fdopen(handle, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # Refuse a concurrent replacement instead of discarding newly saved state.
        try:
            current = _identity(os.stat(FILENAME, dir_fd=descriptor, follow_symlinks=False))
        except FileNotFoundError:
            current = None
        if current != identity:
            raise PreferencesError("Preference file changed during save; retry after inspecting it.")
        os.replace(temporary, FILENAME, src_dir_fd=descriptor, dst_dir_fd=descriptor)
        temporary = None
        data, identity = _read(descriptor)
        return _result(data, identity, directory, key)
    except OSError as exc:
        raise PreferencesError("Preferences could not be saved; inspect dispatcher state before retrying.") from exc
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary, dir_fd=descriptor)
            except FileNotFoundError:
                pass
        os.close(descriptor)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("show", "set"):
        command = commands.add_parser(name)
        command.add_argument("--project", help="Apply explicit overrides for this existing project.")
        command.add_argument("--state-dir", help="Dispatcher preferences directory override.")
        command.add_argument("--json", action="store_true")
        if name == "set":
            command.add_argument("--output", choices=OUTPUTS)
            command.add_argument("--effort", choices=EFFORTS)
    args = parser.parse_args(argv)
    try:
        if args.command == "set":
            result = set_preferences(output=args.output, effort=args.effort, project=args.project,
                                     state_dir=args.state_dir)
        else:
            result = get_preferences(project=args.project, state_dir=args.state_dir)
    except PreferencesError as exc:
        if args.json:
            print(json.dumps({"schema_version": SCHEMA_VERSION, "error": str(exc)}))
        else:
            print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Output: {result['output']} ({result['sources']['output']})")
        print(f"Requested effort: {result['requested_effort']} ({result['sources']['effort']})")
        print("Actual host effort: unknown; confirm in your host. Host configuration was not changed.")
        if args.command == "set":
            print(f"Saved dispatcher preferences: {result['storage_path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
