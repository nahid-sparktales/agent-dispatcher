#!/usr/bin/env python3
"""Build a self-contained Codex skill/plugin from the shared canonical pack.

The default output is ignored build output, not another hand-maintained skill catalog.
"""
import argparse
import json
from pathlib import Path
import shutil
import tempfile

import build

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "adapters" / "codex"
DEFAULT_OUTPUT = ROOT / "dist" / "codex" / "plugins" / "agent-dispatcher"
MARKER = ".agent-dispatcher-codex-build"


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def adapt(text):
    """Translate host vocabulary; role methods and loadouts stay shared."""
    return (text.replace("**/<id>/SKILL.md", "PACK/references/skills/**/<id>/GUIDE.md")
            .replace("write tools gated until the user approves via ExitPlanMode",
                     "follow Codex's current collaboration mode and permission controls")
            .replace("`/agent-context`", "`$agent-dispatcher context`")
            .replace("`/agent-context", "`$agent-dispatcher context")
            .replace("Read/Grep/Glob", "file-reading and search tools")
            .replace("non-mutating Bash", "non-mutating terminal commands")
            .replace("Do not Edit or Write files", "Do not edit or write files")
            .replace("WebSearch/WebFetch", "Web search and page-reading tools")
            .replace("an official Anthropic one", "a host-provided one"))


def export_package(destination, data):
    """Write only into an empty staging directory supplied by the caller."""
    plugin = Path(destination)
    plugin.mkdir(parents=True, exist_ok=True)
    if any(plugin.iterdir()):
        raise ValueError("Codex export requires an empty staging directory")
    pack = plugin / "skills" / "agent-dispatcher"
    refs = pack / "references"
    skill = build.render((SOURCE / "SKILL.template.md").read_text(), {
        "{{COUNT}}": len(data["roles"]), "{{SKILL_COUNT}}": len(data["skills"])})
    write(pack / "SKILL.md", skill)
    write(pack / "agents" / "openai.yaml", 'interface:\n'
          '  display_name: "Agent Dispatcher"\n'
          '  short_description: "Route tasks to focused specialist roles"\n')

    for role in data["roles"]:
        rid = role["id"]
        text = adapt((build.ADAPTER / "roles" / f"{rid}.md").read_text())
        if "ExitPlanMode" in text:
            raise ValueError(f"unadapted Claude mode control in {rid}")
        write(refs / "roles" / f"{rid}.md", text)
    for name in build.REFERENCE_FILES:
        if name == "jev.md":
            continue  # The decision guide gets its host-specific preamble below.
        text = adapt(build.reference_text(name, data, "codex") if name in build.TEMPLATED_REFERENCES
                     else (build.ADAPTER / name).read_text())
        for skill_meta in data["skills"]:
            original = skill_meta["path"]
            relative = original.replace("/SKILL.md", "/GUIDE.md")
            text = text.replace(original, "references/" + relative)
        if name == "INDEX.md":
            text = build.sub(text,
                             "are repo-relative, and an install puts the same tree under the pack's `lib/`.",
                             "are relative to PACK, the directory holding the dispatcher SKILL.md.")
            for recipe in data["recipes"]:
                text = text.replace(f"`recipes/{recipe['id']}.md`", f"`references/recipes/{recipe['id']}.md`")
        write(refs / name, text)
    inventory = json.loads((build.ADAPTER / "INVENTORY.json").read_text())
    by_id = {item["id"]: item for item in data["skills"]}
    for item in inventory["local_skills"]:
        item["paths"] = ["references/" + by_id[item["id"]]["path"].replace("/SKILL.md", "/GUIDE.md")]
    write(refs / "INVENTORY.json", json.dumps(inventory, indent=2) + "\n")
    # GUIDE.md avoids recursive skill discovery adding all 79 descriptions to every session.
    for skill_meta in data["skills"]:
        src = ROOT / skill_meta["path"]
        target = refs / "skills" / skill_meta["category"] / skill_meta["id"]
        shutil.copytree(src.parent, target)
        (target / "SKILL.md").rename(target / "GUIDE.md")
    shutil.copytree(ROOT / "recipes", refs / "recipes")
    write(refs / "jev.md", "# Codex invocation\n\nFor this package, use `python3 PACK/scripts/decide.py --project PROJECT`\n"
          "in place of `python3 -m decision` in the shared guide below. PACK is the skill\n"
          "directory and PROJECT is the user's project. Do not run configuration commands\n"
          "from inside the installed package without selecting the project.\n\n"
          + build.decision_guide())

    scripts = pack / "scripts"
    runtime = scripts / "runtime"
    shutil.copytree(ROOT / "decision", runtime / "decision",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(ROOT / "catalog", runtime / "catalog")
    write(runtime / "catalog/resource-paths.json", json.dumps({
        "schema_version": 1, "layout": "codex",
        "roles": {r["id"]: f"references/roles/{r['id']}.md" for r in data["roles"]},
        "guides": {s["id"]: "references/" + s["path"].replace("/SKILL.md", "/GUIDE.md") for s in data["skills"]},
    }, indent=2) + "\n")
    for name in ("activate.py", "decide.py"):
        shutil.copyfile(SOURCE / name, scripts / name)
    for name in ("doctor.py", "context.py", "context_packet.py", "context_reuse.py", "parser_cache.py", "project_map.py", "project_graph.py",
                 "repo_index.py", "retrieval.py", "context_budget.py", "llm_retrieval.py",
                 "repository_memory.py", "repo_history.py", "experience.py",
                 "resources.py", "verification.py", "preferences.py", "change_audit.py"):
        shutil.copyfile(ROOT / name, scripts / name)
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    manifest["skills"] = "./skills/"
    manifest["interface"] = {
        "displayName": "Agent Dispatcher", "shortDescription": "Specialist routing for Codex",
        "longDescription": "Route tasks to focused roles, load relevant guidance, and verify outcomes.",
        "developerName": manifest["author"]["name"], "category": "Productivity",
        "capabilities": ["Read", "Write"],
        "defaultPrompt": ["Use $agent-dispatcher to review this project."]}
    write(plugin / ".codex-plugin" / "plugin.json", json.dumps(manifest, indent=2) + "\n")
    hook = {"hooks": {"SessionStart": [{"matcher": "startup|resume|clear|compact",
            "hooks": [{"type": "command", "timeout": 5,
                       "command": 'python3 "${PLUGIN_ROOT}/skills/agent-dispatcher/scripts/activate.py" hook'}]}]}}
    write(plugin / "hooks" / "hooks.json", json.dumps(hook, indent=2) + "\n")
    for name in ("LICENSE", "NOTICE"):
        shutil.copyfile(ROOT / name, plugin / name)
        shutil.copyfile(ROOT / name, pack / name)
    write(plugin / MARKER, "agent-dispatcher Codex build v1\n")
    write(pack / ".agent-dispatcher-owned", "agent-dispatcher Codex skill v1\n")
    return pack


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.absolute()
    marker = output / MARKER
    if output.is_symlink() or (output.exists() and (
            marker.is_symlink() or not marker.is_file()
            or marker.read_text() != "agent-dispatcher Codex build v1\n")):
        parser.error("refusing to overwrite a directory not owned by the Codex builder")
    data = build.main()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".codex-build-", dir=output.parent) as tmp:
        staged = Path(tmp) / "agent-dispatcher"
        export_package(staged, data)
        if output.exists():
            shutil.rmtree(output)
        staged.rename(output)
    print(f"Codex plugin: {output}")


if __name__ == "__main__":
    main()
