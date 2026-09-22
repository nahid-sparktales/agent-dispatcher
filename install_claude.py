#!/usr/bin/env python3
"""Stage, validate, and transactionally install the Claude manual dispatcher pack."""
import argparse
import contextlib
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
MANIFEST = ".agent-dispatcher-installed"
PACK = Path("skills/agent-dispatcher")
HOOK = Path("hooks/agent-dispatcher-activate.sh")
SETTINGS = Path("settings.json")
SETTINGS_BACKUP = Path("settings.json.bak-agent-dispatcher")


def validate_settings(settings):
    if not isinstance(settings, dict) or not isinstance(settings.get("hooks", {}), dict):
        raise ValueError("settings must contain objects")
    starts = settings.get("hooks", {}).get("SessionStart", [])
    if not isinstance(starts, list):
        raise ValueError("SessionStart must be an array")
    for entry in starts:
        if not isinstance(entry, dict) or not isinstance(entry.get("hooks", []), list):
            raise ValueError("invalid SessionStart entry")
        if any(not isinstance(h, dict) or not isinstance(h.get("command", ""), str)
               for h in entry.get("hooks", [])):
            raise ValueError("invalid hook entry")


def hook_settings(settings, config, remove=False):
    """Return updated settings without mutating the input or writing any live files."""
    validate_settings(settings)
    result = copy.deepcopy(settings)
    script = str(config / HOOK)
    command = "bash " + shlex.quote(script)
    legacy = f'bash "{script}"'
    if remove:
        starts = result.get("hooks", {}).get("SessionStart", [])
        kept = []
        for entry in starts:
            hooks = [h for h in entry.get("hooks", [])
                     if h.get("command", "") not in {command, legacy}]
            if hooks or not entry.get("hooks"):
                kept.append(entry if hooks == entry.get("hooks", []) else {**entry, "hooks": hooks})
        if kept != starts:
            result["hooks"]["SessionStart"] = kept
    else:
        starts = result.setdefault("hooks", {}).setdefault("SessionStart", [])
        for entry in starts:
            for hook in entry.get("hooks", []):
                if hook.get("command") == legacy:
                    hook["command"] = command
        if not any(h.get("command") == command for e in starts for h in e.get("hooks", [])):
            starts.append({"matcher": "startup|resume|clear|compact",
                           "hooks": [{"type": "command", "command": command, "timeout": 5}]})
    return result


def manifest_paths(manifest, config):
    owned = []
    for name in manifest.read_text().splitlines():
        if not name:
            continue
        target = Path(name)
        if (target.parent != config / "commands"
                or not re.fullmatch(r"agent-[a-z0-9-]+\.md", target.name)
                or target.is_symlink() or (target.exists() and not target.is_file())):
            raise ValueError("installed-file manifest has an unsafe entry")
        if target not in owned:
            owned.append(target)
    return owned


def preflight(config):
    """Keep legacy plain-path manifests, but refuse unsafe or unowned targets."""
    directories = {Path("."), Path("skills"), Path("commands"), Path("hooks"), PACK}
    for relative in directories | {SETTINGS, SETTINGS_BACKUP, HOOK, Path(MANIFEST)}:
        target = config / relative
        if target.is_symlink():
            raise ValueError("an installation target is a symlink")
        if target.exists():
            valid_type = target.is_dir() if relative in directories else target.is_file()
            if not valid_type:
                raise ValueError("an installation target has the wrong file type")
    settings_file = config / SETTINGS
    settings = json.loads(settings_file.read_text()) if settings_file.exists() else {}
    validate_settings(settings)
    manifest = config / MANIFEST
    owned = []
    if manifest.exists():
        owned = manifest_paths(manifest, config)
    elif any((config / relative).exists() for relative in (PACK, HOOK)):
        raise ValueError("existing dispatcher skill or hook has no installation manifest; "
                         "move the conflicting files aside or restore its original manifest")
    return settings, owned


def fingerprint(path):
    """Detect target changes while staging, including mode changes and symlinks."""
    if path.is_symlink():
        return ("link", os.readlink(path))
    if not path.exists():
        return None
    mode = path.stat().st_mode
    if path.is_dir():
        return (mode, tuple((p.name, fingerprint(p)) for p in sorted(path.iterdir())))
    if not path.is_file():
        return (mode, "special-file")
    return (mode, hashlib.sha256(path.read_bytes()).hexdigest())


def remove_path(path):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


@contextlib.contextmanager
def interruptible():
    """Turn catchable termination into rollback; SIGKILL/power loss cannot be caught."""
    def interrupt(signum, frame):
        raise KeyboardInterrupt(f"interrupted by signal {signum}")
    saved = {}
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        saved[signum] = signal.signal(signum, interrupt)
    try:
        yield
    finally:
        for signum, handler in saved.items():
            signal.signal(signum, handler)


@contextlib.contextmanager
def defer_interrupts():
    saved = {s: signal.signal(s, signal.SIG_IGN)
             for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    try:
        yield
    finally:
        for signum, handler in saved.items():
            signal.signal(signum, handler)


def commit(changes, workspace, state):
    """Swap staged paths into place and restore exact originals on any caught failure.

    Entries are (target, staged source or None for deletion, expected fingerprint).
    Backups stay on the destination filesystem and are never reconstructed from JSON.
    """
    for target, source, expected in changes:
        if fingerprint(target) != expected:
            raise ValueError("installation target changed during staging; retry the installation")
    # Recovery instructions survive a rollback failure; no configuration contents are stored.
    (workspace / "recovery.json").write_text(json.dumps({
        "operation": "restore each existing backup to its target; remove new targets if present",
        "entries": [{"target": str(target), "backup": f"previous-{index}",
                     "staged": str(source.relative_to(workspace)) if source else None,
                     "had_original": expected is not None}
                    for index, (target, source, expected) in enumerate(changes)]
    }, indent=2) + "\n")
    journal = []
    created_dirs = []
    try:
        for index, (target, source, expected) in enumerate(changes):
            if source is not None and not target.parent.exists():
                target.parent.mkdir()
                created_dirs.append(target.parent)
            backup = workspace / f"previous-{index}"
            # Record before renaming so an interrupt immediately after a rename is reversible.
            journal.append((target, source, backup, expected is not None))
            if expected is not None:
                os.replace(target, backup)
            if source is not None:
                os.replace(source, target)
        state["committed"] = True
    except BaseException:
        state["committed"] = False
        errors = []
        with defer_interrupts():
            for target, source, backup, existed in reversed(journal):
                try:
                    if backup.exists() or backup.is_symlink():
                        remove_path(target)
                        os.replace(backup, target)
                    elif not existed and source is not None and not source.exists():
                        remove_path(target)
                except OSError as exc:
                    errors.append(exc)
            for directory in reversed(created_dirs):
                try:
                    directory.rmdir()
                except OSError:
                    pass
        if errors:
            raise RuntimeError(f"Rollback could not finish; recovery files preserved in {workspace}") from errors[0]
        raise


def copy_file(source, target):
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"installation source is missing or unsafe: {source.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if fingerprint(source) != fingerprint(target):
        raise ValueError(f"staged copy did not validate: {source.name}")


def copy_tree(source, target):
    if source.is_symlink() or not source.is_dir():
        raise ValueError(f"installation source is missing or unsafe: {source.name}")
    target.mkdir(parents=True, exist_ok=True)
    for item in sorted(source.iterdir()):
        if item.name == "__pycache__" or item.suffix == ".pyc":
            continue
        if item.is_symlink():
            raise ValueError("installation source contains a symlink")
        if item.is_dir():
            copy_tree(item, target / item.name)
        else:
            copy_file(item, target / item.name)


def stage_pack(repo, destination):
    copy_tree(repo / "skills/agent-dispatcher", destination)
    for source in sorted((repo / "skills").iterdir()):
        if source.name != "agent-dispatcher" and source.is_dir():
            copy_tree(source, destination / "lib" / source.name)
    for name in ("recipes", "decision", "catalog"):
        copy_tree(repo / name, destination / name)
    for name in ("doctor.py", "context.py", "context_packet.py", "context_reuse.py", "parser_cache.py", "project_map.py", "project_graph.py",
                 "repo_index.py", "retrieval.py", "context_budget.py", "llm_retrieval.py",
                 "resources.py", "verification.py", "preferences.py", "change_audit.py"):
        copy_file(repo / name, destination / name)
    for name in ("LICENSE", "NOTICE"):
        copy_file(repo / name, destination / name)
    manifest_path = destination / "catalog/resource-paths.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["layout"] = "claude_manual"
    manifest["roles"] = {ident: "roles/" + ident + ".md" for ident in manifest["roles"]}
    manifest["guides"] = {ident: path.replace("skills/", "lib/", 1) for ident, path in manifest["guides"].items()}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    required = ("resources.py", "catalog/resource-paths.json", "SKILL.md", "INDEX.md", "CONTEXT.md", "CONTEXT-REFERENCE.md", "ROLES.md",
                "CONTROLS.md", "DELEGATION.md", "PROJECT-MAP.md", "VERIFICATION.md", "verification.py", "preferences.py", "jev.md", "roles", "lib", "recipes",
                "decision/__main__.py", "decision/redact.py", "catalog/loadouts.json", "doctor.py", "context.py", "project_map.py",
                "context_packet.py", "context_reuse.py", "parser_cache.py", "project_graph.py", "change_audit.py",
                "repo_index.py", "retrieval.py", "context_budget.py", "llm_retrieval.py")
    if any(not (destination / name).exists() for name in required):
        raise ValueError("staged dispatcher pack is incomplete")


def build_and_validate(repo):
    subprocess.run([sys.executable, str(repo / "build.py")], cwd=repo, check=True)
    for module in ("tests.test_build", "tests.test_decision"):
        subprocess.run([sys.executable, "-B", "-m", module], cwd=repo, check=True)


def install(config, repo=ROOT, uninstall=False):
    config = Path(os.path.abspath(Path(config).expanduser()))
    settings, owned = preflight(config)
    if uninstall and not (config / MANIFEST).exists():
        print(f"No recorded manual installation in {config}; nothing was changed")
        return
    # Capture state before building/staging, not just before overwriting it.
    targets = {config / p for p in (PACK, HOOK, SETTINGS, SETTINGS_BACKUP, Path(MANIFEST))} | set(owned)
    commands = [] if uninstall else sorted((repo / "commands").glob("agent-*.md"))
    targets.update(config / "commands" / p.name for p in commands)
    initial = {p: fingerprint(p) for p in targets}
    if not uninstall:
        build_and_validate(repo)
        commands = sorted((repo / "commands").glob("agent-*.md"))
        if not commands:
            raise ValueError("no generated commands to install")
        # Newly generated command names also need collision protection.
        for command in commands:
            target = config / "commands" / command.name
            initial.setdefault(target, fingerprint(target))
    config_existed = config.exists()
    config.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix=".agent-dispatcher-stage-", dir=config))
    preserve = False
    state = {"committed": False}
    try:
        changes = []
        def add(relative, source=None):
            target = config / relative
            changes.append((target, source, initial[target]))
        # Deregister first on uninstall; register only after every install file is ready.
        staged_settings = hook_settings(settings, config, remove=uninstall)
        settings_changes = []
        if staged_settings != settings:
            if initial[config / SETTINGS] is not None and initial[config / SETTINGS_BACKUP] is None:
                backup = workspace / "settings-backup"
                copy_file(config / SETTINGS, backup)
                settings_changes.append((config / SETTINGS_BACKUP, backup, None))
            staged = workspace / "settings.json"
            staged.write_text(json.dumps(staged_settings, indent=2) + "\n")
            if (config / SETTINGS).exists():
                shutil.copymode(config / SETTINGS, staged)
            validate_settings(json.loads(staged.read_text()))
            settings_changes.append((config / SETTINGS, staged, initial[config / SETTINGS]))
        if uninstall:
            changes.extend(settings_changes)
            for target in owned:
                add(target.relative_to(config))
            add(PACK)
            add(HOOK)
            add(Path(MANIFEST))
        else:
            staged_pack = workspace / "pack"
            stage_pack(repo, staged_pack)
            add(PACK, staged_pack)
            staged_hook = workspace / "hook.sh"
            copy_file(repo / "hooks/agent-dispatcher-activate.sh", staged_hook)
            staged_hook.chmod(staged_hook.stat().st_mode | 0o111)
            add(HOOK, staged_hook)
            installed_commands = []
            for source in commands:
                target = config / "commands" / source.name
                if initial[target] is not None and target not in owned:
                    print(f"skipped {source.name} — a file of that name already exists and was not installed by this script")
                    continue
                staged = workspace / "commands" / source.name
                copy_file(source, staged)
                add(target.relative_to(config), staged)
                installed_commands.append(target)
            for obsolete in sorted(set(owned) - set(installed_commands)):
                add(obsolete.relative_to(config))
            changes.extend(settings_changes)
            manifest = workspace / MANIFEST
            manifest.write_text("".join(str(p) + "\n" for p in installed_commands))
            if manifest_paths(manifest, config) != installed_commands:
                raise ValueError("staged command manifest is incomplete")
            add(Path(MANIFEST), manifest)
        # Revalidate parent directories, ownership, and unchanged settings, including inputs
        # not changed by this update. A user edit during staging must not be overwritten.
        preflight(config)
        if any(fingerprint(p) != expected for p, expected in initial.items()):
            raise ValueError("installation target changed during staging; retry the installation")
        try:
            commit(changes, workspace, state)
        except RuntimeError:
            preserve = True
            raise
    except KeyboardInterrupt:
        if not state["committed"]:
            raise
        # Once the commit completed, interruption during cleanup must not claim rollback.
    finally:
        if not preserve:
            with defer_interrupts():
                try:
                    shutil.rmtree(workspace)
                except OSError:
                    outcome = "Installation committed" if state["committed"] else "Previous installation preserved"
                    print(f"{outcome}; temporary/recovery files could not be removed: {workspace}", file=sys.stderr)
                if not config_existed:
                    try:
                        config.rmdir()
                    except OSError:
                        pass
    print(f"uninstalled from {config} (flag files left alone)" if uninstall else f"installed to {config}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args(argv)
    config = os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))
    try:
        with interruptible():
            install(config, uninstall=args.uninstall)
    except KeyboardInterrupt:
        parser.exit(130, "Installation interrupted.\n")
    except subprocess.CalledProcessError:
        parser.exit(1, "Build or validation failed; the installation was not changed.\n")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Installation failed: settings are not valid JSON, an unsafe layout was found, "
                       f"or staging/commit failed ({exc}); previous installation preserved.\n")
    except RuntimeError as exc:
        parser.exit(1, f"Installation failed: {exc}\n")


if __name__ == "__main__":
    main()
