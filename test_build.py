#!/usr/bin/env python3
"""Validation suite. Run directly, or via install.sh, which runs it before installing anything.

Checks the structure the generator cannot check for itself: that generated artifacts agree with
their canonical sources, that nothing references something that does not exist, that no secret or
absolute local path leaked in, and that the docs do not contradict the catalog.
"""
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
             "catalog/skills.json", "catalog/loadouts.json", "README.md"]


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
    check("one command per role", len(cmds) == len(roles), f"{len(cmds)} vs {len(roles)}")
    for c in cmds:
        m = re.search(r"roles/([a-z0-9-]+)\.md", c.read_text())
        check(f"command {c.name} points at a real role", m and m.group(1) in ids)
    hook = (build.HOOKS / "agent-dispatcher-activate.sh").read_text()
    check("hook index == templates", set(re.findall(r"^- `([a-z0-9-]+)`", hook, re.M)) == ids)
    rendered = sorted((build.ADAPTER / "roles").glob("*.md"))
    check("one rendered role per template", len(rendered) == len(roles))

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
    for name in ("mcp.json", "external-skills.json", "skills.json", "loadouts.json"):
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
    for n, label in ((len(roles), "roles"), (len(skills), "skills")):
        check(f"README states {label} count {n}", str(n) in readme)
    for doc in ("architecture.md", "security.md", "adding-a-skill.md"):
        check(f"docs/{doc} exists", (ROOT / "docs" / doc).exists())

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print(f"all checks passed — {len(roles)} roles, {len(skills)} skills, {len(recipes)} recipes, "
          f"{len(d['external'])} external, {len(mcp)} mcp")


if __name__ == "__main__":
    main()
