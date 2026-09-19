#!/usr/bin/env python3
"""Install/update the Codex skill without changing Claude or Codex permission settings."""
import argparse
import importlib.util
from pathlib import Path
import shutil
import tempfile

import build
from build_codex import export_package

ROOT = Path(__file__).resolve().parent
OWNER = ".agent-dispatcher-owned"
OWNED = "agent-dispatcher Codex skill v1\n"


def activation_module():
    spec = importlib.util.spec_from_file_location("codex_activation", ROOT / "adapters/codex/activate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_target(target):
    if target.is_symlink():
        raise ValueError("refusing to replace a symlinked skill")
    if target.exists():
        marker = target / OWNER
        if not target.is_dir() or marker.is_symlink() or not marker.is_file() or marker.read_text() != OWNED:
            raise ValueError("agent-dispatcher already exists and was not installed by this installer")


def install(skills_dir, config, uninstall=False, with_hook=False):
    skills_dir = Path(skills_dir).expanduser().resolve()
    target = skills_dir / "agent-dispatcher"
    check_target(target)
    activation = activation_module()
    config = Path(config).expanduser().resolve()
    # Refuse malformed hook configuration before replacing an existing installation.
    if uninstall or with_hook:
        activation.hook_settings(config)
    if uninstall:
        activation.manage_hook(config, target, remove=True)
        if target.exists():
            shutil.rmtree(target)
        print(f"Removed Codex dispatcher from {target}; activation state preserved")
        return target
    data = build.main()
    skills_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".agent-dispatcher-install-", dir=skills_dir) as tmp:
        root = Path(tmp)
        staged = export_package(root / "plugin", data)
        backup = root / "previous"
        if target.exists():
            target.rename(backup)
        try:
            staged.rename(target)
            if with_hook:
                activation.manage_hook(config, target)
        except BaseException:
            if target.exists():
                shutil.rmtree(target)
            if backup.exists():
                backup.rename(target)
            raise
    print(f"Installed Codex skill: {target}")
    print("Invoke $agent-dispatcher in a new Codex task. Automatic activation is off unless previously enabled.")
    if with_hook:
        print("Review and trust the hook in Codex /hooks before enabling automatic activation.")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-dir", type=Path, default=Path.home() / ".agents" / "skills")
    parser.add_argument("--config-dir", type=Path, default=None)
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--with-hook", action="store_true", help="also register the inert, opt-in SessionStart hook")
    args = parser.parse_args()
    try:
        install(args.skills_dir, args.config_dir or activation_module().config_dir(),
                args.uninstall, args.with_hook)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Codex installation failed: {exc}\n")


if __name__ == "__main__":
    main()
