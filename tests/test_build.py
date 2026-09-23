#!/usr/bin/env python3
"""Validation suite. Run directly, or via install.sh, which runs it before installing anything.

Checks the structure the generator cannot check for itself: that generated artifacts agree with
their canonical sources, that nothing references something that does not exist, that no secret or
absolute local path leaked in, and that the docs do not contradict the catalog.
"""
import collections
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

import build

ROOT = pathlib.Path(__file__).resolve().parents[1]
FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        FAILURES.append(f"{name}: {detail}")
        print(f"  FAIL {name} — {detail}")


GENERATED = ["skills/agent-dispatcher/DOCTOR.md", "skills/agent-dispatcher/doctor.py", "skills/agent-dispatcher/INVENTORY.md", "skills/agent-dispatcher/INVENTORY.json", "skills/agent-dispatcher/ACTIVITY.md", "skills/agent-dispatcher/SKILL.md", "skills/agent-dispatcher/INDEX.md",
             "skills/agent-dispatcher/CONTEXT.md", "skills/agent-dispatcher/SIGNALS.md",
             "catalog/skills.json", "catalog/loadouts.json", "README.md",
             "docs/catalog.md", "docs/skills.md", "docs/mcps.md", "docs/recipes.md",
             "docs/context-engine.md"]
GENERATED += ["skills/agent-dispatcher/" + name for name in build.REFERENCE_FILES]
GENERATED.extend("skills/agent-dispatcher/" + name for name in build.RUNTIME_MODULES)
GENERATED.append("catalog/resource-paths.json")


def drift():
    """A generated file edited by hand is a change that the next build silently discards."""
    def snapshot():
        paths = {ROOT / rel for rel in GENERATED}
        paths.update((build.ADAPTER / "roles").glob("*.md"))
        paths.update(build.CMDS.glob("agent-*.md"))
        paths.update(p for p in build.HOOKS.glob("*") if p.is_file())
        return {str(p.relative_to(ROOT)): p.read_bytes() if p.is_file() else None
                for p in paths}
    before = snapshot()
    build.main()
    after = snapshot()
    return sorted(rel for rel in before.keys() | after.keys()
                  if before.get(rel) != after.get(rel))


SKIP = {"node_modules", ".git", "dist", "build", "__pycache__", ".venv", "vendor"}


def hygiene_files(root):
    """Check repository content, including new source, without scanning ignored local output."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        result = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-C", str(root), "ls-files",
             "--cached", "--others", "--exclude-standard", "-z", "--", "."],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, timeout=10)
        if result.returncode == 0:
            paths = {root / os.fsdecode(name) for name in result.stdout.split(b"\0") if name}
            return sorted(path for path in paths if path.is_file())
    except (OSError, subprocess.TimeoutExpired):
        pass
    # Source archives have no Git metadata; retain the established generated-tree exclusions.
    return sorted(path for path in root.rglob("*")
                  if path.is_file() and not SKIP.intersection(path.relative_to(root).parts))


def detect(signal, root):
    """Evaluate a project signal against a tree. Proves the rules are machine-evaluable.

    Deliberately the dumb version — glob the files, grep the contents. If a rule cannot be
    evaluated this way, an agent standing in a repository cannot evaluate it either.
    """
    def hits(pattern):
        try:
            return [m for m in root.glob(pattern)
                    if not SKIP & set(m.relative_to(root).parts)]
        except (ValueError, IndexError):
            return []
    for pattern in signal.get("files", []):
        if hits(pattern.rstrip("/*") if pattern.endswith("/**") else pattern):
            return True
    for rule in signal.get("content", []):
        pattern, _, literal = rule.partition(" contains ")
        for match in hits(pattern):
            if match.is_file() and literal in match.read_text(errors="ignore"):
                return True
    return False


def validate(value, spec, path, errors):
    """Enough of JSON Schema to give catalog/context-plan.schema.json a job.

    No dependency: the repo installs nothing, and the six keywords the plan schema actually uses
    are cheaper to check than to justify a requirement for.
    """
    t = spec.get("type")
    if t == "object" and not isinstance(value, dict):
        return errors.append(f"{path}: expected object, got {type(value).__name__}")
    if t == "array" and not isinstance(value, list):
        return errors.append(f"{path}: expected array, got {type(value).__name__}")
    if t == "string" and not isinstance(value, str):
        return errors.append(f"{path}: expected string, got {type(value).__name__}")
    if t == "integer" and not isinstance(value, int):
        return errors.append(f"{path}: expected integer, got {type(value).__name__}")
    if t == "boolean" and not isinstance(value, bool):
        return errors.append(f"{path}: expected boolean, got {type(value).__name__}")
    if "enum" in spec and value not in spec["enum"]:
        errors.append(f"{path}: {value!r} is not one of {spec['enum']}")
    if isinstance(value, list):
        for i, item in enumerate(value):
            validate(item, spec.get("items", {}), f"{path}[{i}]", errors)
    if isinstance(value, dict):
        props = spec.get("properties", {})
        for key in spec.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required '{key}'")
        extra = spec.get("additionalProperties")
        for key, v in value.items():
            if key in props:
                validate(v, props[key], f"{path}.{key}", errors)
            elif extra is False:
                errors.append(f"{path}: '{key}' is not a field of this object")
            elif isinstance(extra, dict):
                validate(v, extra, f"{path}.{key}", errors)



def run_hook(config_dir, project_dir, session_id=None, cwd=None):
    """Run the real hook the way the runtime does: JSON on stdin, config dir in the env.

    Everything else about the hook is checked by reading its text, which cannot catch a
    generator edit that silently did not apply, a printf whose escaping is wrong, or arming
    logic that lets a cloned repository switch the dispatcher on. Those only show up when the
    script actually runs.
    """
    payload = {}
    if session_id is not None:
        payload["session_id"] = session_id
    if cwd is not None:
        payload["cwd"] = cwd
    env = dict(os.environ, CLAUDE_CONFIG_DIR=str(config_dir))
    env.pop("CLAUDE_SESSION_ID", None)
    out = subprocess.run(["bash", str(build.HOOKS / "agent-dispatcher-activate.sh")],
                         input=json.dumps(payload), capture_output=True, text=True,
                         cwd=str(project_dir), env=env)
    return out.returncode, out.stdout


def hook_behaviour(roles):
    """The arm/silence matrix, executed rather than read."""
    ids = {r["id"] for r in roles}
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        cfg, proj, other = root / "config", root / "project", root / "other"
        for d in (cfg, proj, other):
            d.mkdir()

        code, out = run_hook(cfg, proj, "s-1", str(proj))
        check("a clean install arms nothing", code == 0 and out == "", repr(out[:80]))

        (cfg / ".agent-dispatcher-active").touch()
        code, out = run_hook(cfg, proj, "s-1", str(proj))
        check("arming everywhere injects the preamble",
              "AGENT DISPATCHER ACTIVE" in out, repr(out[:80]))
        # Billed to every armed session without the agent choosing to read it.
        check("perpetual-mode preamble stays affordable", 0 < len(out) < 12000,
              f"{len(out)} bytes injected into every armed session")
        check("the injected preamble carries the role index",
              set(re.findall(r"^- `([a-z0-9-]+)`", out, re.M)) == ids,
              "the roles the hook prints are not the roles that exist")
        # Ids alone are not routing. The preamble tells the agent to match "not for" as carefully
        # as "route here when", so both texts have to survive into what the hook actually prints.
        # Asserting the text rather than the line format keeps this independent of build.py's
        # f-string: editing the index format in build.py and in the drift check together still
        # fails here if a field stops being printed.
        thin = [r["id"] for r in roles
                if r["use_when"] not in out or r["not_for"] not in out]
        check("the injected index carries each role's route-here and not-for text", not thin,
              f"printed without their routing text: {thin[:4]}")
        check("the injected preamble has no unreplaced placeholder",
              "{" not in out.replace("${", ""), "a generator placeholder reached the output")

        # The failure that started this: a printf whose escaping is wrong renders its own
        # escape sequences instead of newlines, and every text-level check still passes.
        check("the stop guidance renders, rather than printing its escapes",
              "/agent-dispatcher off" in out and "\\n" not in out,
              "literal escape sequences in the hook output")
        check("the stop guidance fills in the real session id",
              f"{cfg}/.agent-dispatcher-off/s-1" in out, "the session id was not substituted")
        check("the stop guidance names all three scopes",
              all(w in out for w in ("this session", "this project", "everywhere")),
              "a scope is missing from the guidance")

        silenced = cfg / ".agent-dispatcher-off"
        silenced.mkdir()
        (silenced / "s-1").touch()
        code, out = run_hook(cfg, proj, "s-1", str(proj))
        check("silencing a session beats arming everywhere", out == "", repr(out[:80]))
        code, out = run_hook(cfg, proj, "s-2", str(proj))
        check("silencing one session leaves the others armed", "AGENT DISPATCHER" in out)

        (proj / ".agent-dispatcher-off").touch()
        code, out = run_hook(cfg, proj, "s-2", str(proj))
        check("silencing a project beats arming everywhere", out == "", repr(out[:80]))
        code, out = run_hook(cfg, other, "s-2", str(other))
        check("silencing one project leaves the others armed", "AGENT DISPATCHER" in out)
        (proj / ".agent-dispatcher-off").unlink()
        (cfg / ".agent-dispatcher-active").unlink()

        # The security property the two-step allow-list exists for.
        (proj / ".agent-dispatcher-on").touch()
        code, out = run_hook(cfg, proj, "s-3", str(proj))
        check("a cloned repository cannot arm itself", out == "",
              "a flag file alone armed the dispatcher — the allow-list is not being enforced")
        (cfg / ".agent-dispatcher-projects").write_text(str(other) + "\n")
        code, out = run_hook(cfg, proj, "s-3", str(proj))
        check("an allow-list entry for another project does not arm this one", out == "")
        (cfg / ".agent-dispatcher-projects").write_text(str(proj) + "\n")
        code, out = run_hook(cfg, proj, "s-3", str(proj))
        check("a project armed by its own allow-list entry does arm", "AGENT DISPATCHER" in out)
        code, out = run_hook(cfg, other, "s-3", str(other))
        check("arming one project does not arm another", out == "")

        # Role metadata is substituted into the hook, so it is a shell-injection surface if
        # the heredoc around it is ever unquoted. A malicious role file in a PR is the threat.
        hostile = ("- `evil` \u2014 $(touch " + str(root / "PWNED") + ") `id` \"q\u2019 "
                   "{{ROLES}} ${HOME} " + chr(92) + " tail")
        probe = root / "hostile.sh"
        probe.write_text((build.SHARED_SOURCES / "HOOK.template.sh").read_text().replace("{{ROLES}}", hostile))
        (cfg / ".agent-dispatcher-active").touch()          # arm, so there is output to inspect
        out = subprocess.run(["bash", str(probe)], input='{"session_id":"s","cwd":"/tmp"}',
                             capture_output=True, text=True, cwd=str(root),
                             env=dict(os.environ, CLAUDE_CONFIG_DIR=str(cfg)))
        (cfg / ".agent-dispatcher-active").unlink()
        check("role metadata cannot inject shell into the hook",
              not (root / "PWNED").exists() and hostile in out.stdout,
              "the role index is expanded rather than printed — the heredoc lost its quotes")

        # A payload with no session id still has to work; only the stop line changes.
        code, out = run_hook(cfg, proj, None, str(proj))
        check("a payload with no session id still arms", "AGENT DISPATCHER" in out)
        check("and says the session id is missing rather than printing an empty path",
              "did not carry" in out, repr(out[-400:]))


def install_settings():
    """Exercise the installer's settings transformation against common host layouts."""
    import install_claude as installer
    script = (build.HOOKS / "agent-dispatcher-activate.sh").name
    theirs = {"matcher": "startup", "hooks": [{"type": "command", "command": "echo theirs"}]}
    seeds = {"no settings.json": {},
             "settings.json without hooks": {"model": "opus"},
             "settings.json with another hook": {"model": "opus",
                                                 "hooks": {"SessionStart": [theirs]}}}
    for label, seed in seeds.items():
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            installed = installer.hook_settings(seed, d)
            ours = [e for e in installed["hooks"]["SessionStart"]
                    if any(script[:-3] in h.get("command", "") for h in e.get("hooks", []))]
            check(f"installer registers the SessionStart hook — {label}",
                  len(ours) == 1, f"{len(ours)} registered")
            check(f"and registers the path the installer copies the script to — {label}",
                  bool(ours) and shlex.split(ours[0]["hooks"][0].get("command", ""))
                  == ["bash", str(d / "hooks" / script)], repr(ours))
            check(f"a second install registers it once, not twice — {label}",
                  installer.hook_settings(installed, d) == installed)
            removed = installer.hook_settings(installed, d, remove=True)
            check(f"uninstall removes its hook again — {label}",
                  not any(script[:-3] in h.get("command", "")
                          for e in removed.get("hooks", {}).get("SessionStart", [])
                          for h in e.get("hooks", [])))
            check(f"and leaves the rest of settings.json alone — {label}",
                  all(removed.get(k) == value for k, value in seed.items()), str(removed)[:200])
    return installer


def install_script(installer):
    """Run the real uninstall entry point against isolated settings and ownership fixtures.

    This branch skips installation validation, so calling it from this suite cannot recurse.
    """
    script_name = (build.HOOKS / "agent-dispatcher-activate.sh").name
    theirs = {"type": "command", "command": "bash /theirs.sh"}
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        script = d / "hooks" / script_name

        def armed(settings):
            """What a finished install leaves behind, minus the file copying."""
            script.parent.mkdir(exist_ok=True)
            script.write_text("#!/bin/bash\n")
            (d / ".agent-dispatcher-installed").touch()
            (d / "settings.json").write_text(json.dumps(settings) + "\n")
            (d / "settings.json").write_text(json.dumps(installer.hook_settings(settings, d)) + "\n")
            return json.loads((d / "settings.json").read_text())

        def uninstall():
            return subprocess.run(["bash", str(ROOT / "install.sh"), "--uninstall"],
                                  capture_output=True, text=True,
                                  env=dict(os.environ, CLAUDE_CONFIG_DIR=str(d)))

        # A hook of the user's own, sharing the entry ours was appended to. Filtering by entry
        # rather than by hook deletes it, and the user's settings.json is the one place nothing
        # can be restored from.
        s = armed({"model": "opus"})
        s["hooks"]["SessionStart"][0]["hooks"].append(theirs)
        (d / "settings.json").write_text(json.dumps(s) + "\n")
        uninstall()
        left = [h for e in json.loads((d / "settings.json").read_text())["hooks"]["SessionStart"]
                for h in e.get("hooks", [])]
        check("--uninstall removes our hook and leaves a user hook sharing its entry alone",
              left == [theirs], f"{left} — the filter is dropping the entry, not our hook")

        # settings.json hand-edited since the install into something that will not parse.
        armed({"model": "opus"})
        (d / "settings.json").write_text('{"model": "opus",}\n')
        r = uninstall()
        check("--uninstall changes nothing when settings.json will not parse",
              r.returncode != 0 and script.exists(),
              "the hook script was deleted before the settings.json rewrite that failed — "
              "settings.json is now left starting a script that is no longer there")
        check("and says so rather than printing a traceback",
              "not valid JSON" in r.stdout + r.stderr, (r.stdout + r.stderr).strip()[-160:])

        # The ordering itself, which the check above cannot pin: it trips the guard at the top
        # of the branch, so it passes whichever side of the `rm -f` the rewrite sits on. A
        # settings.json can be valid JSON and still be one the rewrite chokes on — `"command":
        # null` from a hand edit is enough — and then only the order decides what is left.
        armed({"model": "opus"})
        s = json.loads((d / "settings.json").read_text())
        s["hooks"]["SessionStart"][0]["hooks"].append({"type": "command", "command": None})
        (d / "settings.json").write_text(json.dumps(s) + "\n")
        uninstall()
        still_registered = script_name[:-3] in (d / "settings.json").read_text()
        check("--uninstall never leaves settings.json starting a script it has already deleted",
              not (still_registered and not script.exists()),
              "the settings.json rewrite ran after the `rm -f` and did not finish — every "
              "session start from here on errors on a hook script that is gone")


def main():
    print("building...")
    changed = drift()
    check("no generated file was hand-edited", not changed,
          f"these differ from what build.py produces: {changed[:6]}")
    d = build.load()
    roles, skills, recipes = d["roles"], d["skills"], d["recipes"]
    ids = {r["id"] for r in roles}
    slugs = [r["slug"] for r in roles]
    skill_ids = {s["id"] for s in skills}

    print("\nidentity")
    check("role ids unique", len(ids) == len(roles))
    check("role slugs unique", len(set(slugs)) == len(slugs))
    check("skill ids unique", len(skill_ids) == len(skills))
    check("no id collides with an external skill",
          not (skill_ids & set(d["external"])), str(skill_ids & set(d["external"])))

    print("\ngenerated artifacts agree with sources")
    router = (build.ADAPTER / "SKILL.md").read_text()
    check("router has no unreplaced placeholder", "{{" not in router)
    role_index = (build.ADAPTER / "ROLES.md").read_text()
    check("on-demand role catalog == templates",
          set(re.findall(r"^## ([a-z0-9-]+) —", role_index, re.M)) == ids)
    check("entrypoint points to roles instead of embedding their catalog",
          "ROLES.md" in router and not re.search(r"^### `([a-z0-9-]+)`", router, re.M))
    check("informal implementation aliases remain reachable",
          all(alias in role_index for alias in ("`coder`", "`dev`", "`implementer`")))
    for role in roles:
        check(f"role index preserves {role['id']} alias and routing boundaries",
              all(text in role_index for text in (f"Alias: `{role['slug']}`", role['use_when'], role['not_for'])))
    cmds = sorted(build.CMDS.glob("agent-*.md"))
    # Inspection and configuration commands do not force a specialist role.
    NON_ROLE_CMDS = ("agent-context.md", "agent-decision.md", "agent-inventory.md", "agent-doctor.md", "agent-map.md",
                     "agent-memory.md", "agent-learning.md", "agent-verify.md", "agent-preferences.md")
    role_cmds = [c for c in cmds if c.name not in NON_ROLE_CMDS]
    check("one command per role, plus inspection and configuration commands",
          len(role_cmds) == len(roles)
          and all((build.CMDS / n).exists() for n in NON_ROLE_CMDS),
          f"{len(cmds)} files vs {len(roles)} roles")
    for c in role_cmds:
        m = re.search(r"roles/([a-z0-9-]+)\.md", c.read_text())
        check(f"command {c.name} points at a real role", m and m.group(1) in ids)
    inspector = (build.CMDS / "agent-context.md").read_text()
    map_command = (build.CMDS / "agent-map.md").read_text()
    check("project map control reaches its guide without executing the task",
          "PROJECT-MAP.md" in map_command and "inspection is read-only" in map_command
          and "Do not execute discovered commands" in map_command)
    check("inspector sends the reader to CONTEXT.md", "CONTEXT.md" in inspector)
    memory_command = (build.CMDS / "agent-memory.md").read_text()
    check("memory control reaches its guide and treats hits as evidence",
          "MEMORY.md" in memory_command and "never" in memory_command and "do not apply a historical patch" in memory_command)
    check("inspector does not do the work", "Do not do the work." in inspector)
    check("inspector offers local context build without executing the task",
          "build <request>" in inspector and "Stop after inspection" in inspector)
    check("inspector names the decision engine", "decision engine" in inspector.lower())
    check("inspector refuses to print a credential",
          "never print a credential" in inspector.lower())
    switch = (build.CMDS / "agent-decision.md").read_text()
    check("the decision switch offers all three modes",
          all(f"`{m}`" in switch for m in ("off", "auto", "required")))
    check("the decision switch never asks for a credential in chat",
          "Never ask the user to paste a credential" in switch)
    # These two are the only commands built by substitution rather than by f-string, so they are
    # the only ones where the placeholder can go missing and leave the text standing. Asserting
    # the path literal here rather than build.py's SKILL_DIR is the point: comparing the artifact
    # to the generator agrees with itself when the substitution silently applied to nothing.
    for name, txt in (("agent-context.md", inspector), ("agent-decision.md", switch)):
        check(f"{name} has no unreplaced placeholder", "{{" not in txt and "{skill_dir}" not in txt,
              re.findall(r"\{\{?[A-Za-z_]+\}?\}", txt)[:3])
        check(f"{name} says where the skill is installed",
              "~/.claude/skills/agent-dispatcher" in txt,
              "the skill path was substituted into nothing")
    hook = (build.HOOKS / "agent-dispatcher-activate.sh").read_text()
    check("hook index == templates", set(re.findall(r"^- `([a-z0-9-]+)`", hook, re.M)) == ids)
    check("activation invokes the non-executable helper through Python",
          "python3 -B PACK/context.py --project PROJECT --task='REQUEST' --role ID" in hook)
    rendered = sorted((build.ADAPTER / "roles").glob("*.md"))
    check("one rendered role per template", len(rendered) == len(roles))

    print("\ncontext engine")
    context = (build.ADAPTER / "CONTEXT.md").read_text()
    context_reference = (build.ADAPTER / "CONTEXT-REFERENCE.md").read_text()
    check("Claude optional decisions preserve the project working directory",
          "PYTHONPATH=RUNTIME python3 -m decision plan" in context_reference
          and "Keep the project as the working directory" in context_reference
          and "plugin root" in context_reference)
    check("CONTEXT.md has no unreplaced placeholder", "{{" not in context)
    sigs = d["signals"]
    used = {c for r in roles for c in r["skills"]["conditional"]}
    check("every conditional bucket has a signal", not (used - set(sigs)), str(sorted(used - set(sigs))))
    check("every signal is used by a role", not (set(sigs) - used), str(sorted(set(sigs) - used)))
    signals_md = (build.ADAPTER / "SIGNALS.md").read_text()
    check("SIGNALS.md carries every signal — an install never receives catalog/",
          all(f"`{s}`" in signals_md and sigs[s]["when_unknown"] in signals_md for s in sigs),
          str([s for s in sigs if f"`{s}`" not in signals_md][:5]))
    check("CONTEXT.md names the vocabulary and delegates the detail",
          "SIGNALS.md" in context and all(f"`{s}`" in context_reference for s in sigs))
    banned = {"permission", "permissions", "grants", "allows", "authorizes", "tools", "mcp"}
    leaky = [s["id"] for s in sigs.values() if banned & set(s)]
    check("no signal carries a permission or tool field", not leaky,
          f"{leaky} — a signal says how a condition is decided, never what it opens up")
    reg = json.loads((build.CATALOG / "signals.json").read_text())
    check("signals.json states that detection grants nothing",
          "never grants authorization" in reg.get("purpose", ""))
    vague = [s["id"] for s in sigs.values() if len(s["when_unknown"]) < 40]
    check("every signal says what follows from not knowing", not vague, str(vague))
    schema = d["plan_schema"]["properties"]
    check("the plan schema holds no execution plan", not ({"steps", "plan", "tasks", "actions"}
          & set(schema)), "a context plan says what is needed, not what will be done")
    fences = re.findall(r"```json\n(.*?)```", context_reference, re.S)
    check("advanced context reference carries a worked example", len(fences) >= 1)
    errors = []
    for i, fence in enumerate(fences):
        try:
            example = json.loads(fence)
        except json.JSONDecodeError as exc:
            errors.append(f"example {i} does not parse: {exc}")
            continue
        validate(example, d["plan_schema"], f"example[{i}]", errors)
    check("worked example validates against the plan schema", not errors, str(errors[:4]))
    def titled(node, where):
        bad = []
        for name, sub in node.get("properties", {}).items():
            if "title" not in sub and where == "":
                bad.append(name)
        return bad
    check("every top-level plan field has a title to render",
          not titled(d["plan_schema"], ""), str(titled(d["plan_schema"], "")))
    for r in roles:
        check(f"role {r['id']} seeds retrieval", bool(r["retrieval_hints"]))

    project = {s["id"]: s for s in sigs.values() if s["kind"] == "project"}
    fired = {i for i, s in project.items() if detect(s, ROOT)}
    # This repository is a skill-authoring project and is not a Next.js app. If the rules cannot
    # tell those apart from the files on disk, they are decoration.
    check("project signals evaluate from files alone", "authoring_skills" in fired,
          f"authoring_skills did not fire here; fired: {sorted(fired)}")
    check("project signals discriminate", "nextjs" not in fired and "tailwind" not in fired,
          f"fired on a repo with no such stack: {sorted(fired)}")

    print("\ncontext cost of what is read")
    # The preamble's cost is billed against what the hook prints, not against the heredocs in its
    # source: scraping the source misses the printf'd stop guidance, and a renamed heredoc marker
    # would scrape nothing and pass the budget at zero bytes. Measured in hook_behaviour instead.

    # A substitution whose search string stops matching leaves the artifact alone, so the drift
    # check compares two copies of the stale content and passes. build.py is the only place that
    # knows a substitution was meant to happen; these two pin that it still says so out loud.
    try:
        build.sub("nothing here", "{{MISSING}}", "x")
        check("a substitution that matches nothing is fatal", False, "sub() returned quietly")
    except SystemExit as e:
        check("a substitution that matches nothing is fatal", "{{MISSING}}" in str(e), str(e))
    try:
        build.marked("no markers here", "roles", "body")
        check("a generated region with no markers is fatal", False, "marked() returned the text")
    except SystemExit as e:
        check("a generated region with no markers is fatal", "roles:start" in str(e), str(e))

    tmpl = (build.SHARED_SOURCES / "HOOK.template.sh").read_text()

    # Grepping build.py for a quote style, and comparing the hook to the template, both pass when
    # the generator has stopped reading the template and ships its own byte-identical copy: the
    # template is then decoration, and the next edit to it does nothing. Drift cannot see that —
    # the rebuild produces the same bytes it did before — and the comparison only fails later,
    # after someone has already made the edit that vanished. Rebuilding from a template that was
    # changed on purpose is the only check that fails while the copy is still identical.
    with tempfile.TemporaryDirectory() as tmp:
        sandbox = pathlib.Path(tmp)
        shared = sandbox / "sources" / "shared"
        shared.mkdir(parents=True)
        (shared / "HOOK.template.sh").write_text(tmpl + "# edit-reaches-the-hook\n")
        saved = build.ROOT, build.SHARED_SOURCES, build.HOOKS
        build.ROOT, build.SHARED_SOURCES, build.HOOKS = sandbox, shared, sandbox / "hooks"
        try:
            build.write_hook(d)
            rebuilt = (sandbox / "hooks" / "agent-dispatcher-activate.sh").read_text()
        except (SystemExit, OSError) as exc:  # no longer reading a template at that path
            rebuilt = f"write_hook failed: {exc}"
        finally:
            build.ROOT, build.SHARED_SOURCES, build.HOOKS = saved
    check("an edit to HOOK.template.sh reaches the generated hook",
          "# edit-reaches-the-hook" in rebuilt,
          f"build.py is not rendering the template — editing it does nothing ({rebuilt[:80]!r})")

    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as fh:
        fh.write(tmpl.replace("{{ROLES}}", "- `placeholder` — x"))
        probe = fh.name
    syntax = subprocess.run(["bash", "-n", probe], capture_output=True, text=True)
    pathlib.Path(probe).unlink()
    # bash -n parses; it does not run. It would not have caught the printf escaping bug — only
    # hook_behaviour below does that. It is here for the clearer message, not the coverage.
    check("the hook template parses as bash", syntax.returncode == 0,
          syntax.stderr.strip()[:200])
    check("the generated hook is the template plus the index",
          (build.HOOKS / "agent-dispatcher-activate.sh").read_text().replace(
              "\n".join(f"- `{r['id']}` — {r['use_when']}\n    not for: {r['not_for']}"
                        for r in roles), "{{ROLES}}") == tmpl,
          "the generator is doing something to the shell beyond substituting the index")

    # A source file that exists locally but was never `git add`ed builds fine for whoever has it
    # and dies in every fresh clone. Reading the file cannot catch that; only asking git can.
    ls = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True)
    if ls.returncode == 0:
        known = set(ls.stdout.split("\0"))
        loose = [str(f.relative_to(ROOT)) for f in sorted(build.SHARED_SOURCES.glob("*.template.*"))
                 if str(f.relative_to(ROOT)) not in known]
        check("every template the build reads is committed, not just present locally",
              not loose, f"{loose} would be missing from a fresh clone")

    print("\nthe hook, actually run")
    hook_behaviour(roles)
    check("router stays within 6 KiB UTF-8", len(router.encode("utf-8")) <= 6144,
          f"{len(router.encode('utf-8'))} bytes")
    # CONTEXT.md is read on demand, but it defines a ~12k-token standard budget; reading it must
    # not eat that budget.
    for name, cap in (("CONTEXT.md", 6144), ("SIGNALS.md", 32000), ("INDEX.md", 44000)):
        size = (build.ADAPTER / name).stat().st_size
        check(f"{name} fits the budget it is read against", size <= cap, f"{size} bytes")

    print("\ncross-references resolve")
    for name in ("SKILL.md", *build.REFERENCE_FILES):
        reference = build.ADAPTER / name
        broken = [link for link in re.findall(r"\]\(([^)]+)\)", reference.read_text())
                  if not re.match(r"[a-z]+://|#", link)
                  and not (reference.parent / link.split("#")[0]).is_file()]
        check(f"Claude {name} links resolve", not broken, str(broken))
    loadouts = json.loads((build.CATALOG / "loadouts.json").read_text())
    empty = [r["id"] for r in loadouts["roles"]
             if not any(r["skills"][t] for t in build.TIERS) and not r["skills"]["conditional"]]
    check("every role has a loadout", not empty, f"empty: {empty}")
    index = (build.ADAPTER / "INDEX.md").read_text()
    check("index lists every local skill",
          all(f"`{s['id']}`" in index for s in skills))
    verifiers = {s["id"] for s in skills if s["verifies"]}
    check("at least one verification skill exists per major area", len(verifiers) >= 5,
          f"only {len(verifiers)}")

    print("\nskill files")
    for s in skills:
        p = ROOT / s["path"]
        fm, body = build.read_frontmatter(p)
        extra = set(fm) - {"name", "description", "allowed-tools", "license"}
        check(f"{s['id']} SKILL.md frontmatter is standard", not extra, f"extra keys {sorted(extra)}")
        n = len(body.splitlines())
        check(f"{s['id']} body is a skill, not a book", 30 <= n <= 220, f"{n} lines")
    shared = collections.Counter(sig for s in skills for sig in s["task_signals"])
    noisy = [sig for sig, n in shared.items() if n > 2]
    check("task signals discriminate between skills", not noisy,
          f"{noisy} fire for three or more skills, so they route nothing")

    print("\nthe generator refuses to substitute into nothing")
    # build.sub/build.marked raising is the only thing standing between a search string that
    # stopped matching and an artifact that stays stale while every check agrees with it. Drift
    # cannot catch that class — it compares a rebuild that also did nothing — so the guard itself
    # is what gets pinned here. Reverting either to `return txt` fails this.
    def refuses(fn):
        try:
            fn()
        except SystemExit:
            return True
        return False
    check("a replace that matches nothing stops the build",
          refuses(lambda: build.sub("no placeholder here", "{{ROLES}}", "x")),
          "build.sub substituted into nothing and let the build succeed")
    check("a missing generated region stops the build",
          refuses(lambda: build.marked("no markers here", "counts", "x")),
          "build.marked left the file stale and let the build succeed")

    # Same class again, in the frontmatter the roles are emitted with. A `"` inside a template
    # value used to be pasted straight into `name: "..."`, and the reader stripped the outer pair
    # back off, so template and artifact agreed while the file was no longer YAML. No template
    # carries a quote today, so nothing static sees it: the only check that can is emitting a
    # quote-bearing role and parsing the file back.
    r = dict(roles[0], name='The "Fixer"', not_for='not a "quick" fix.')
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        real, build.ADAPTER = build.ADAPTER, tmp
        try:
            build.write_roles({**d, "roles": [r]})
            fm, _ = build.read_frontmatter(tmp / "roles" / f"{r['id']}.md")
        except SystemExit as exc:
            fm = {"name": f"unreadable — {exc}", "not_for": ""}
        finally:
            build.ADAPTER = real
        bad = tmp / "bad.md"
        bad.write_text('---\nname: "The "Fixer""\n---\n')
        check("an unescaped quote in a template is rejected, not round-tripped",
              refuses(lambda: build.read_frontmatter(bad)),
              "read_frontmatter stripped the outer pair and handed malformed YAML back as a value")
    check("a quote inside a role value survives the emit/parse round trip",
          (fm["name"], fm["not_for"]) == (r["name"], r["not_for"]),
          f"{fm['name']!r} / {fm['not_for']!r}")

    # Verify registration behavior and the real uninstaller against throwaway settings.
    install_script(install_settings())

    print("\nhygiene")
    with tempfile.TemporaryDirectory() as temp:
        sample = pathlib.Path(temp)
        (sample / "dist").mkdir()
        for name in ("tracked.md", "new.py", "dist/fixture.json", "dist/local.json", "ignored.md"):
            (sample / name).write_text("fixture")
        (sample / ".gitignore").write_text("dist/\nignored.md\n")
        check("archive hygiene excludes generated trees while retaining source",
              {str(path.relative_to(sample)) for path in hygiene_files(sample)}
              == {".gitignore", "tracked.md", "new.py", "ignored.md"})
        if shutil.which("git"):
            sample_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
            subprocess.run(["git", "init", "--quiet", str(sample)], check=True,
                           capture_output=True, env=sample_env)
            subprocess.run(["git", "-C", str(sample), "add", "--force", "--", ".gitignore", "tracked.md",
                            "dist/fixture.json"], check=True, capture_output=True, env=sample_env)
            check("repository hygiene retains tracked ignored files and new source, excluding local output",
                  {str(path.relative_to(sample)) for path in hygiene_files(sample)}
                  == {".gitignore", "tracked.md", "new.py", "dist/fixture.json"})
    tracked = hygiene_files(ROOT)
    secret = re.compile(r"(gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|"
                        r"-----BEGIN [A-Z ]*PRIVATE KEY-----)")
    hits = [str(p.relative_to(ROOT)) for p in tracked if p.suffix in (".md", ".json", ".sh", ".py")
            and secret.search(p.read_text(errors="ignore"))]
    check("no credentials committed", not hits, str(hits))
    home = [str(p.relative_to(ROOT)) for p in tracked
            if p.suffix in (".md", ".json") and "/Users/" in p.read_text(errors="ignore")
            and not str(p).endswith("research.json")]
    check("no absolute local paths in content", not home, str(home[:5]))

    print("\ncatalogs")
    for name in ("mcp.json", "external-skills.json", "skills.json", "loadouts.json",
                 "signals.json", "context-plan.schema.json"):
        p = build.CATALOG / name
        check(f"{name} parses", p.exists() and json.loads(p.read_text()) is not None)
    mcp = json.loads((build.CATALOG / "mcp.json").read_text())["servers"]
    check("every MCP records its risk and write posture",
          all("writes" in m and "risk" in m and "fallback" in m for m in mcp))
    ext = json.loads((build.CATALOG / "external-skills.json").read_text())["skills"]
    check("every external skill records provenance",
          all(all(k in e for k in ("repository", "license", "trust", "verified", "fallback"))
              for e in ext))
    check("no external skill is vendored", all(not e.get("vendored") for e in ext))

    print("\ndocs match reality")
    readme = (ROOT / "README.md").read_text()
    counts = readme.split("<!-- counts:start -->")[1].split("<!-- counts:end -->")[0]
    for n, label in ((len(roles), "roles"), (len(skills), "local skills"),
                     (len(recipes), "recipes"), (len(mcp), "MCP servers"),
                     (len(d["signals"]), "detection signals")):
        check(f"README counts state {n} {label}", re.search(rf"\b{n} {label}\b", counts),
              f"counts region reads: {counts.strip()[:90]}")
    for doc, n in (("skills.md", len(skills)), ("mcps.md", len(mcp)), ("recipes.md", len(recipes)),
                   ("context-engine.md", len(d["signals"]))):
        body = (ROOT / "docs" / doc).read_text()
        region = body.split("<!-- counts:start -->")[1].split("<!-- counts:end -->")[0]
        check(f"docs/{doc} count is generated, not stale", str(n) in region, region.strip()[:60])
    for f in (".claude-plugin/plugin.json", ".claude-plugin/marketplace.json"):
        body = (ROOT / f).read_text()
        check(f"{f} states the current role count", f"{len(roles)} specialist agent roles" in body,
              "its description is hand-written and nothing else checks it")
    for doc in ("architecture.md", "security.md", "adding-a-skill.md", "context-engine.md",
                "jev.md"):
        check(f"docs/{doc} exists", (ROOT / "docs" / doc).exists())

    print("\ndecision layer agrees with the canonical registries")
    sys.path.insert(0, str(ROOT))
    from decision.registry import Registry
    reg = Registry(root=build.CATALOG)
    agents = reg.agent_candidates()
    check("every decision candidate maps to a real role",
          {c.id for c in agents} <= ids, "a candidate id has no template behind it")
    check("every role in the router's catalog is a decision candidate",
          {c.id for c in agents} == ids, str(sorted(ids - {c.id for c in agents})))
    check("candidate ids are unique", len({c.id for c in agents}) == len(agents))
    check("routing metadata reaches the registry the engine reads",
          all(r.get("summary") and r.get("use_when") and r.get("not_for")
              for r in json.loads((build.CATALOG / "loadouts.json").read_text())["roles"]),
          "loadouts.json lost the lines that tell one role from another")
    known_skills = {s["id"] for s in skills} | set(d["external"])
    check("every decision skill candidate maps to a registered skill",
          all(c.id in known_skills for r in ids for c in reg.skill_candidates(r)),
          "a loadout names a skill the registries do not carry")
    check("every decision tool candidate maps to a registered server",
          {c.id for c in reg.tool_candidates()} == {s["id"] for s in mcp},
          "the tool roster and catalog/mcp.json disagree")
    check("the decision layer builds no registry of its own",
          not list(build.CATALOG.glob("jev-*.json"))
          and not list((ROOT / "decision").glob("*-registry.json")),
          "a duplicated candidate registry appeared")
    check("no decision candidate carries a permission or write posture",
          not any(w in c.criteria.lower() for c in reg.tool_candidates()
                  for w in ("permission", "authoriz", "risk:", "writes:")),
          "permission-adjacent metadata reached a relevance model")
    check("the decision layer needs no third-party package",
          not any(line.startswith(("import ", "from ")) and
                  line.split()[1].split(".")[0] in ("requests", "httpx", "openai", "anthropic",
                                                    "ai", "pydantic", "aiohttp")
                  for f in (ROOT / "decision").rglob("*.py")
                  for line in f.read_text().splitlines()),
          "something outside the standard library was imported")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print(f"all checks passed — {len(roles)} roles, {len(skills)} skills, {len(recipes)} recipes, "
          f"{len(d['external'])} external, {len(mcp)} mcp, {len(d['signals'])} signals")


if __name__ == "__main__":
    main()
