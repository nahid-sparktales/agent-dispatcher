#!/usr/bin/env python3
"""Validation suite. Run directly, or via install.sh, which runs it before installing anything.

Checks the structure the generator cannot check for itself: that generated artifacts agree with
their canonical sources, that nothing references something that does not exist, that no secret or
absolute local path leaked in, and that the docs do not contradict the catalog.
"""
import collections
import json
import pathlib
import re
import sys

import build

ROOT = pathlib.Path(__file__).parent
FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        FAILURES.append(f"{name}: {detail}")
        print(f"  FAIL {name} — {detail}")


GENERATED = ["skills/agent-dispatcher/SKILL.md", "skills/agent-dispatcher/INDEX.md",
             "skills/agent-dispatcher/CONTEXT.md", "skills/agent-dispatcher/SIGNALS.md",
             "catalog/skills.json", "catalog/loadouts.json", "README.md",
             "docs/skills.md", "docs/mcps.md", "docs/recipes.md",
             "docs/context-engine.md"]


def drift():
    """A generated file edited by hand is a change that the next build silently discards."""
    before = {}
    for rel in GENERATED:
        p = ROOT / rel
        if p.exists():
            before[rel] = p.read_bytes()
    for p in list((build.ADAPTER / "roles").glob("*.md")) + list(build.CMDS.glob("agent-*.md")) \
            + list(build.HOOKS.glob("*")):
        before[str(p.relative_to(ROOT))] = p.read_bytes()
    build.main()
    return [rel for rel, old in before.items()
            if (ROOT / rel).exists() and (ROOT / rel).read_bytes() != old]


SKIP = {"node_modules", ".git", "dist", "build", "__pycache__", ".venv", "vendor"}


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
    check("router catalog == templates",
          set(re.findall(r"^### `([a-z0-9-]+)`", router, re.M)) == ids)
    cmds = sorted(build.CMDS.glob("agent-*.md"))
    # Two generated commands are not roles: the context-plan inspector, and the switch for the
    # optional decision engine.
    NON_ROLE_CMDS = ("agent-context.md", "agent-decision.md")
    role_cmds = [c for c in cmds if c.name not in NON_ROLE_CMDS]
    check("one command per role, plus the inspector and the decision switch",
          len(role_cmds) == len(roles)
          and all((build.CMDS / n).exists() for n in NON_ROLE_CMDS),
          f"{len(cmds)} files vs {len(roles)} roles")
    for c in role_cmds:
        m = re.search(r"roles/([a-z0-9-]+)\.md", c.read_text())
        check(f"command {c.name} points at a real role", m and m.group(1) in ids)
    inspector = (build.CMDS / "agent-context.md").read_text()
    check("inspector sends the reader to CONTEXT.md", "CONTEXT.md" in inspector)
    check("inspector does not do the work", "Do not do the work." in inspector)
    check("inspector names the decision engine", "decision engine" in inspector.lower())
    check("inspector refuses to print a credential",
          "never print a credential" in inspector.lower())
    switch = (build.CMDS / "agent-decision.md").read_text()
    check("the decision switch offers all three modes",
          all(f"`{m}`" in switch for m in ("off", "auto", "required")))
    check("the decision switch never asks for a credential in chat",
          "Never ask the user to paste a credential" in switch)
    hook = (build.HOOKS / "agent-dispatcher-activate.sh").read_text()
    check("hook index == templates", set(re.findall(r"^- `([a-z0-9-]+)`", hook, re.M)) == ids)
    rendered = sorted((build.ADAPTER / "roles").glob("*.md"))
    check("one rendered role per template", len(rendered) == len(roles))

    print("\ncontext engine")
    context = (build.ADAPTER / "CONTEXT.md").read_text()
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
          "SIGNALS.md" in context and all(f"`{s}`" in context for s in sigs))
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
    fences = re.findall(r"```json\n(.*?)```", context, re.S)
    check("CONTEXT.md carries a worked example", len(fences) >= 1)
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
    hook_out = "".join(re.findall(r"<<'DISPATCH'\n(.*?)\nDISPATCH", hook, re.S))
    # The two artefacts billed without the agent choosing to read them.
    check("perpetual-mode preamble stays affordable", len(hook_out) < 12000,
          f"{len(hook_out)} bytes injected into every armed session")
    check("router stays affordable", len(router) < 34000, f"{len(router)} bytes")
    # CONTEXT.md is read on demand, but it defines a ~12k-token standard budget; reading it must
    # not eat that budget.
    for name, cap in (("CONTEXT.md", 24000), ("SIGNALS.md", 32000), ("INDEX.md", 44000)):
        size = (build.ADAPTER / name).stat().st_size
        check(f"{name} fits the budget it is read against", size < cap, f"{size} bytes")

    print("\ncross-references resolve")
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

    print("\nhygiene")
    tracked = [p for p in ROOT.rglob("*")
               if p.is_file() and ".git/" not in str(p) and "__pycache__" not in str(p)]
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
