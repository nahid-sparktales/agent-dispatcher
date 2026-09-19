#!/usr/bin/env python3
"""Index the pack's hand-written canonical sources into every generated artifact.

Canonical, hand-edited, never written by this script:

    templates/<category>/<id>.md        AGENT   — who is responsible for the work
    skills/<category>/<id>/SKILL.md     SKILL   — how to perform one specialized thing
    skills/<category>/<id>/manifest.json         pack metadata, kept out of SKILL.md so the
                                                 skill stays a standard Agent Skill
    recipes/<id>.md                     RECIPE  — how capabilities combine into one run
    catalog/mcp.json                    MCP     — external systems an agent can reach
    catalog/external-skills.json                 skills maintained outside this repo

Generated (Claude Code adapter + registries):

    skills/agent-dispatcher/SKILL.md, roles/*.md, INDEX.md
    commands/agent-*.md, hooks/agent-dispatcher-activate.sh, hooks/hooks.json
    catalog/skills.json, catalog/loadouts.json
    README.md tables, docs/*.md tables
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).parent
TEMPLATES = ROOT / "templates"
SKILLS = ROOT / "skills"
RECIPES = ROOT / "recipes"
CATALOG = ROOT / "catalog"
DOCS = ROOT / "docs"
CMDS = ROOT / "commands"
HOOKS = ROOT / "hooks"
ADAPTER = SKILLS / "agent-dispatcher"
SKILL_DIR = "~/.claude/skills/agent-dispatcher"

SCHEMA_VERSION = "2.0.0"

# Role categories -> directory under templates/
CATEGORIES = {"Core": "core", "Engineering": "engineering",
              "Product & Design": "product-design", "Knowledge & Business": "knowledge-business"}
# Skill categories -> directory under skills/
SKILL_CATEGORIES = ["design", "frontend", "backend", "database", "ai", "quality",
                    "security", "devops", "product", "knowledge"]
TIERS = ["core", "preferred", "optional"]


# ------------------------------------------------------------------ frontmatter

def read_frontmatter(path):
    """Flat `key: value`, values optionally double-quoted. Fails loudly, never guesses."""
    text = path.read_text()
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise SystemExit(f"{path}: missing frontmatter")
    out = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        k, sep, v = line.partition(":")
        if not sep:
            raise SystemExit(f"{path}: frontmatter line is not `key: value` (wrapped?): {line!r}")
        v = v.strip()
        if not v:
            raise SystemExit(f"{path}: frontmatter key '{k.strip()}' has no value")
        out[k.strip()] = v[1:-1] if len(v) > 1 and v[0] == v[-1] == '"' else v
    return out, text[m.end():]


def require(path, fm, keys):
    missing = set(keys) - set(fm)
    if missing:
        raise SystemExit(f"{path}: frontmatter missing {sorted(missing)}")


def listval(fm, key):
    return [x.strip() for x in fm.get(key, "").split(",") if x.strip()]


# ------------------------------------------------------------------ parsing

def parse_role(path):
    fm, body = read_frontmatter(path)
    require(path, fm, ["id", "slug", "name", "category", "summary", "use_when", "not_for", "tags"])
    if fm["category"] not in CATEGORIES:
        raise SystemExit(f"{path}: unknown category {fm['category']!r} — one of {list(CATEGORIES)}")
    if path.parent.name != CATEGORIES[fm["category"]]:
        raise SystemExit(f"{path}: category {fm['category']!r} but it sits in "
                         f"templates/{path.parent.name}/")
    if fm["id"] != path.stem:
        raise SystemExit(f"{path}: id '{fm['id']}' does not match the filename")
    fm["tags"] = listval(fm, "tags")
    fm["capabilities"] = listval(fm, "capabilities")
    fm["skills"] = {t: listval(fm, f"skills_{t}") for t in TIERS}
    fm["skills"]["conditional"] = {k[len("skills_if_"):]: listval(fm, k)
                                   for k in fm if k.startswith("skills_if_")}
    fm["mcps"] = {"recommended": listval(fm, "mcp_recommended"),
                  "conditional": listval(fm, "mcp_conditional")}
    fm["recipes"] = listval(fm, "recipes")
    fm["verification"] = listval(fm, "verification")
    fm["body"] = body
    fm["path"] = str(path.relative_to(ROOT))
    return fm


def parse_skill(path):
    """SKILL.md holds standard Agent Skills frontmatter; manifest.json holds pack metadata."""
    fm, _ = read_frontmatter(path)
    require(path, fm, ["name", "description"])
    mpath = path.parent / "manifest.json"
    if not mpath.exists():
        raise SystemExit(f"{path.parent}: missing manifest.json beside SKILL.md")
    man = json.loads(mpath.read_text())
    for key in ("id", "capability", "category", "use_when", "not_for", "provenance"):
        if key not in man:
            raise SystemExit(f"{mpath}: missing {key!r}")
    if man["id"] != path.parent.name:
        raise SystemExit(f"{mpath}: id '{man['id']}' does not match its directory")
    if man["category"] not in SKILL_CATEGORIES:
        raise SystemExit(f"{mpath}: unknown category {man['category']!r}")
    if path.parent.parent.name != man["category"]:
        raise SystemExit(f"{mpath}: category {man['category']!r} but it sits in "
                         f"skills/{path.parent.parent.name}/")
    for rel in man.get("references", []) + man.get("scripts", []):
        if not (path.parent / rel).exists():
            raise SystemExit(f"{mpath}: declares {rel!r} but that file does not exist")
    man["name"] = fm["name"]
    man["description"] = fm["description"]
    man["path"] = str(path.relative_to(ROOT))
    man.setdefault("tools", [])
    man.setdefault("verifies", False)
    man.setdefault("summary", man["use_when"])
    return man


def parse_recipe(path):
    fm, body = read_frontmatter(path)
    require(path, fm, ["id", "name", "summary", "use_when"])
    if fm["id"] != path.stem:
        raise SystemExit(f"{path}: id '{fm['id']}' does not match the filename")
    fm["capabilities"] = listval(fm, "capabilities")
    fm["roles"] = listval(fm, "roles")
    fm["path"] = str(path.relative_to(ROOT))
    return fm


def load_registry(path, key):
    if not path.exists():
        return {}
    rows = json.loads(path.read_text()).get(key, [])
    out = {}
    for r in rows:
        if r["id"] in out:
            raise SystemExit(f"{path}: duplicate id {r['id']!r}")
        out[r["id"]] = r
    return out


def load():
    roles = sorted((parse_role(p) for p in TEMPLATES.glob("*/*.md")), key=lambda r: r["name"])
    if not roles:
        raise SystemExit(f"no templates found under {TEMPLATES} — refusing to build an empty pack")
    for key in ("id", "slug"):
        seen = {}
        for r in roles:
            if r[key] in seen:
                raise SystemExit(f"duplicate role {key} '{r[key]}': {seen[r[key]]} and {r['id']}")
            seen[r[key]] = r["id"]

    skills = sorted((parse_skill(p) for p in SKILLS.glob("*/*/SKILL.md")
                     if p.parent.parent.name in SKILL_CATEGORIES), key=lambda s: s["id"])
    recipes = sorted((parse_recipe(p) for p in RECIPES.glob("*.md")
                      if p.name not in ("INDEX.md", "README.md")), key=lambda r: r["id"])
    external = load_registry(CATALOG / "external-skills.json", "skills")
    mcp = load_registry(CATALOG / "mcp.json", "servers")

    skill_ids = {s["id"] for s in skills}
    dupes = skill_ids & set(external)
    if dupes:
        raise SystemExit(f"ids used by both a local skill and an external one: {sorted(dupes)}")
    known = skill_ids | set(external)
    recipe_ids = {r["id"] for r in recipes}
    role_ids = {r["id"] for r in roles}
    verifiers = {s["id"] for s in skills if s["verifies"]}

    for r in roles:
        refs = [(i, "skill", known) for t in TIERS for i in r["skills"][t]]
        refs += [(i, "skill", known) for v in r["skills"]["conditional"].values() for i in v]
        refs += [(i, "skill", known) for i in r["verification"]]
        refs += [(i, "recipe", recipe_ids) for i in r["recipes"]]
        refs += [(i, "mcp", set(mcp)) for i in r["mcps"]["recommended"] + r["mcps"]["conditional"]]
        for ref, kind, pool in refs:
            if ref not in pool:
                raise SystemExit(f"role {r['id']}: unknown {kind} '{ref}'")
        by_id = {x["id"]: x for x in skills}
        always_ids = r["skills"]["core"] + r["skills"]["preferred"]
        always_bytes = sum((ROOT / by_id[i]["path"]).stat().st_size
                           for i in always_ids if i in by_id)
        if always_bytes > 30000:
            raise SystemExit(
                f"role {r['id']}: skills_core + skills_preferred is {always_bytes} bytes of skill "
                f"text that loads before any condition is evaluated. Budget is 30000. Move the "
                f"largest entries into skills_optional or a skills_if_<condition> bucket.")
        always = len(always_ids)
        if always > 5:
            raise SystemExit(
                f"role {r['id']}: skills_core + skills_preferred is {always}. Those two tiers load "
                f"before any condition is evaluated, and a normal task should reach for one to five "
                f"skills. Push the overflow into skills_optional or a skills_if_<condition> bucket.")
        caps_declared = {}
        for tier in TIERS:
            for i in r["skills"][tier]:
                src = next((x for x in skills if x["id"] == i), None) or external.get(i)
                cap = src.get("capability") if src else None
                if not cap:
                    continue
                if cap in caps_declared and caps_declared[cap] != i:
                    raise SystemExit(
                        f"role {r['id']}: '{i}' and '{caps_declared[cap]}' both provide capability "
                        f"'{cap}' and are both in always-considered tiers. Declare one, and make the "
                        f"other conditional on the first being unavailable.")
                caps_declared[cap] = i
        for v in r["verification"]:
            if v in skill_ids and v not in verifiers:
                raise SystemExit(f"role {r['id']}: '{v}' is named as verification but that skill "
                                 f"does not set verifies: true")
    for s in skills:
        for t in s["tools"]:
            if t not in mcp:
                raise SystemExit(f"skill {s['id']}: unknown mcp/tool '{t}'")
    for rec in recipes:
        for rid in rec["roles"]:
            if rid not in role_ids:
                raise SystemExit(f"recipe {rec['id']}: unknown role '{rid}'")
    caps = {c for s in skills for c in [s["capability"]]}
    for rec in recipes:
        for c in rec["capabilities"]:
            if c not in caps:
                raise SystemExit(f"recipe {rec['id']}: capability '{c}' is provided by no skill")
    for r in roles:
        for c in r["capabilities"]:
            if c not in caps:
                raise SystemExit(f"role {r['id']}: capability '{c}' is provided by no skill")

    return {"roles": roles, "skills": skills, "recipes": recipes,
            "external": external, "mcp": mcp, "capabilities": sorted(caps)}


# ------------------------------------------------------------------ generating

SKILL_RULE = """## Skills for this role

Read a local skill by globbing `**/<id>/SKILL.md` — every id is its own directory name. The
index beside this file (`../INDEX.md` from here) is for the externally maintained ids and for when
a glob misses. One to five skills is a normal task.
"""


def loadout_block(r, d):
    """The Claude-facing rendering of a role's loadout. Canonical templates stay portable."""
    by_id = {s["id"]: s for s in d["skills"]}
    by_id.update(d["external"])
    lines = []
    for tier, label in (("core", "Core"), ("preferred", "Preferred"), ("optional", "Optional")):
        ids = r["skills"][tier]
        if ids:
            lines.append(f"- **{label}** — " + ", ".join(f"`{i}`" for i in ids))
    for cond, ids in sorted(r["skills"]["conditional"].items()):
        lines.append(f"- **When {cond.replace('_', ' ')}** — " + ", ".join(f"`{i}`" for i in ids))
    if r["verification"]:
        lines.append("- **Verification** — " + ", ".join(f"`{i}`" for i in r["verification"])
                     + " — run it when the tooling exists; when it does not, report what was and "
                       "was not checked rather than calling the work verified.")
    if r["recipes"]:
        lines.append("- **Recipes** — " + ", ".join(f"`{i}`" for i in r["recipes"])
                     + " — a default shape for the work, not a chain that must run in full.")
    def mcp_ids(ids):
        out = []
        for i in ids:
            fb = d["mcp"].get(i, {}).get("fallback", "")
            fb = fb.rstrip(".")
            fb = fb[0].lower() + fb[1:] if fb and fb[:2] not in ("Re", "Th", "Of", "Wo") else fb
            out.append(f"`{i}`" + (f" (absent: {fb})" if fb else ""))
        return ", ".join(out)

    mcps = []
    if r["mcps"]["recommended"]:
        mcps.append("recommended: " + mcp_ids(r["mcps"]["recommended"]))
    if r["mcps"]["conditional"]:
        mcps.append("conditional: " + mcp_ids(r["mcps"]["conditional"]))
    if mcps:
        lines.append("- **MCP / tools** — " + "; ".join(mcps)
                     + ". Availability is not authorization: check the server is actually "
                       "configured, and keep every mutating call inside the permission the user "
                       "already gave. When one is not configured, name the check that could not be "
                       "performed and continue with this role's own method — an absent server is "
                       "not a failure, and never a reason to report a result you could not obtain.")
    if not lines:
        return ""
    return SKILL_RULE + "\n" + "\n".join(lines) + "\n"


def write_roles(d):
    """Render canonical templates into the Claude adapter's role files."""
    roles_dir = ADAPTER / "roles"
    roles_dir.mkdir(parents=True, exist_ok=True)
    for old in roles_dir.glob("*.md"):
        old.unlink()
    for r in d["roles"]:
        fm = [f"id: {r['id']}", f"slug: {r['slug']}", f'name: "{r["name"]}"',
              f'category: "{r["category"]}"', f'summary: "{r["summary"]}"',
              f'use_when: "{r["use_when"]}"', f'not_for: "{r["not_for"]}"',
              f"tags: {', '.join(r['tags'])}"]
        for t in TIERS:
            if r["skills"][t]:
                fm.append(f"skills_{t}: {', '.join(r['skills'][t])}")
        for cond, ids in sorted(r["skills"]["conditional"].items()):
            fm.append(f"skills_if_{cond}: {', '.join(ids)}")
        for k, v in (("mcp_recommended", r["mcps"]["recommended"]),
                     ("mcp_conditional", r["mcps"]["conditional"]),
                     ("recipes", r["recipes"]), ("verification", r["verification"])):
            if v:
                fm.append(f"{k}: {', '.join(v)}")
        body = re.sub(r"\n## Carrying context\n.*?(?=\n## |\Z)", "\n", r["body"], flags=re.S)
        block = loadout_block(r, d)
        if block:
            marker = "\n## Tool posture"
            body = (body.replace(marker, "\n" + block + marker, 1) if marker in body
                    else body.rstrip() + "\n\n" + block)
        (roles_dir / f"{r['id']}.md").write_text("---\n" + "\n".join(fm) + "\n---\n" + body)


def write_router(d):
    rows = "\n".join(
        f"### `{r['id']}` — {r['name']}\n{r['summary']}\n"
        f"- **Route here when:** {r['use_when']}\n"
        f"- **Not for:** {r['not_for']}\n"
        f"- **Signals:** {', '.join(r['tags'])}\n"
        for r in d["roles"])
    tmpl = (ROOT / "SKILL.template.md").read_text()
    (ADAPTER / "SKILL.md").write_text(
        tmpl.replace("{{ROLES}}", rows)
            .replace("{{COUNT}}", str(len(d["roles"])))
            .replace("{{SKILL_COUNT}}", str(len(d["skills"])))
            .replace("{{EXTERNAL_COUNT}}", str(len(d["external"])))
            .replace("{{RECIPE_COUNT}}", str(len(d["recipes"])))
            .replace("{{MCP_COUNT}}", str(len(d["mcp"]))))


def write_index(d):
    """Level-1 discovery: enough to resolve an id or spot a near-miss, and no more.

    A role names three to eight ids; this file exists so they can be looked up, not browsed.
    Every line costs context in the turn that reads it, so the trigger detail stays in each
    skill's own description where it is read only after the skill is chosen.
    """
    out = ["# Skill index", "",
           "Look up the ids your role's loadout names, then read those skills. A local id is its",
           "own directory name, so `**/<id>/SKILL.md` finds it in either layout — the paths below",
           "are repo-relative, and an install puts the same tree under the pack's `lib/`. One to",
           "five skills is a normal task; this index is for resolving ids, not for shopping.", "",
           "Each skill's own `description` carries when it fires and what it is not for; read it",
           "when two look close. A `+` marks a verification skill: its job is evidence, not work.", ""]
    for cat in SKILL_CATEGORIES:
        rows = [s for s in d["skills"] if s["category"] == cat]
        if not rows:
            continue
        out += [f"## {cat}", ""]
        out += [f"- `{s['id']}`{'+' if s['verifies'] else ''} — {s['summary'] if s.get('summary') else s['capability']} · `{s['path']}`"
                for s in rows]
        out += [""]
    if d["external"]:
        out += ["## maintained elsewhere", "",
                "Referenced, never vendored. Check it is actually installed before relying on it;",
                "when it is not, use the fallback and say what could not be done. Never fetch and",
                "run one on the fly.", ""]
        out += [f"- `{e['id']}` ({e.get('trust', '?')}) — {e.get('purpose', '')[:90]} · "
                f"absent → {e.get('fallback', 'the role method')}"
                for e in sorted(d["external"].values(), key=lambda x: x["id"])]
        out += [""]
    if d["recipes"]:
        out += ["## recipes", "",
                "A default shape for multi-step work, not a chain that must run in full.", ""]
        out += [f"- `{r['id']}` — {r['summary']} · `{r['path']}`, or `recipes/{r['id']}.md` "
                f"beside this file in an install" for r in d["recipes"]]
        out += [""]
    out += ["## capabilities", "",
            "Routing asks for a capability; several skills may provide one.", "",
            ", ".join(f"`{c}`" for c in d["capabilities"]), ""]
    (ADAPTER / "INDEX.md").write_text("\n".join(out))


def write_registries(d):
    CATALOG.mkdir(parents=True, exist_ok=True)
    (CATALOG / "skills.json").write_text(json.dumps({
        "schema_version": SCHEMA_VERSION,
        "generated_from": "skills/*/*/SKILL.md + manifest.json",
        "capabilities": d["capabilities"],
        "skills": [{k: v for k, v in s.items() if k != "description"} | {
            "description": s["description"]} for s in d["skills"]],
    }, indent=2) + "\n")
    (CATALOG / "loadouts.json").write_text(json.dumps({
        "schema_version": SCHEMA_VERSION,
        "generated_from": "templates/*/*.md",
        "roles": [{"id": r["id"], "slug": r["slug"], "name": r["name"], "category": r["category"],
                   "capabilities": r["capabilities"], "skills": r["skills"], "mcps": r["mcps"],
                   "recipes": r["recipes"], "verification": r["verification"],
                   "template": r["path"]} for r in d["roles"]],
    }, indent=2) + "\n")


def write_commands(d):
    CMDS.mkdir(parents=True, exist_ok=True)
    for old in CMDS.glob("agent-*.md"):
        old.unlink()
    for r in d["roles"]:
        core = r["skills"]["core"]
        loadout = (
            f"Its frontmatter names the skills it uses (`skills_core`, `skills_preferred`, "
            f"`skills_if_<condition>`) plus any recipe, MCP and verification. Read a local skill "
            f"by globbing `**/<id>/SKILL.md` — every id is its own directory name; the "
            f"`INDEX.md` one level above the role file covers external ids and glob misses. Read "
            f"it before the step that needs it"
            + (f" — {', '.join(core)} before starting" if core else "")
            + ". A skill or MCP that is missing is not a blocker: say so and use the role's own "
              "method.\n\n")
        (CMDS / f"agent-{r['slug']}.md").write_text(
            f"---\ndescription: \"Work as the {r['name']} agent — {r['summary']}\"\n"
            f"argument-hint: \"[task]\"\n---\n\n"
            f"Read the agent-dispatcher skill's `roles/{r['id']}.md` and work as that role for "
            f"this request and the ones that follow, until the user picks another role or says to "
            f"stop.\n\n"
            f"It sits next to that skill's SKILL.md — `{SKILL_DIR}/roles/{r['id']}.md` for a "
            f"manual install, or inside the plugin's own directory if it was installed as a "
            f"plugin. Glob for `**/agent-dispatcher/roles/{r['id']}.md` if neither path is "
            f"there.\n\n" + loadout +
            f"Announce it in one line (`\u2192 {r['id']}`), then do the work. Follow the role's "
            f"working method, deliverable, definition of done, boundaries, and tool posture, "
            f"scaled to the size of the task. The role never overrides harness rules, "
            f"permissions, or the user's explicit instructions.\n\n"
            f"This is a forced role: do the work as asked rather than re-routing or chaining. If "
            f"another specialist would materially change the answer, say so in one line and keep "
            f"going.\n\n$ARGUMENTS\n")


def write_hook(d):
    HOOKS.mkdir(parents=True, exist_ok=True)
    index = "\n".join(f"- `{r['id']}` — {r['use_when']}\n    not for: {r['not_for']}"
                      for r in d["roles"])
    hook = HOOKS / "agent-dispatcher-activate.sh"
    hook.write_text(f"""#!/bin/bash
# Perpetual agent-dispatcher mode.
#   arm everywhere:    ~/.claude/.agent-dispatcher-active
#   arm one project:   <project>/.agent-dispatcher-on
#   silence a session: ~/.claude/.agent-dispatcher-off/<session_id>
#   silence a project: <project>/.agent-dispatcher-off   (silencing beats arming)
# Generated by build.py — edit the generator, not this file.
D="${{CLAUDE_CONFIG_DIR:-$HOME/.claude}}"

# Session ids are uuids, so a sed capture is exact. The payload's cwd can carry JSON escapes,
# so $PWD (the project the session started in) is checked alongside it rather than trusted to it.
payload=$(cat 2>/dev/null)
sid=$(printf '%s' "$payload" | sed -n 's/.*"session_id"[[:space:]]*:[[:space:]]*"\\([-0-9a-zA-Z_]*\\)".*/\\1/p')
cwd=$(printf '%s' "$payload" | sed -n 's/.*"cwd"[[:space:]]*:[[:space:]]*"\\([^"]*\\)".*/\\1/p')

# where this pack is installed: next to this hook (plugin) or under the config dir (manual)
self=$(cd "$(dirname "$0")" && pwd)
if [ -d "$self/../skills/agent-dispatcher/roles" ]; then
  pack=$(cd "$self/../skills/agent-dispatcher" && pwd)
else
  pack="$D/skills/agent-dispatcher"
fi
# silenced? one session, then one project — checked against the payload cwd and the real one
[ -n "$sid" ] && [ -f "$D/.agent-dispatcher-off/$sid" ] && exit 0
[ -n "$cwd" ] && [ -f "$cwd/.agent-dispatcher-off" ] && exit 0
[ -f "$PWD/.agent-dispatcher-off" ] && exit 0

# armed? globally by ~/.claude/.agent-dispatcher-active, or per project by ./.agent-dispatcher-on
# A project arms itself only if the user allow-listed it. Silencing stays repo-local because it
# can only ever reduce behaviour; arming from a cloned repo would not be the user's choice.
armed=""
[ -f "$D/.agent-dispatcher-active" ] && armed=1
for p in "$cwd" "$PWD"; do
  [ -n "$p" ] && [ -f "$p/.agent-dispatcher-on" ] \
    && [ -f "$D/.agent-dispatcher-projects" ] \
    && grep -qxF "$p" "$D/.agent-dispatcher-projects" && armed=1
done
[ -n "$armed" ] || exit 0
# forget session silences older than a week
[ -d "$D/.agent-dispatcher-off" ] && find "$D/.agent-dispatcher-off" -type f -mtime +7 -delete 2>/dev/null

printf 'AGENT DISPATCHER ACTIVE (perpetual mode) — this pack lives at %s\\n\\n' "$pack"
cat <<'DISPATCH'

Route each request that involves real work to the best-fit specialist role below, then work as that
role. Match the "not for" line as carefully as the "route here when" line.
Read PACK/roles/<id>.md before acting as one; read PACK/SKILL.md for the full catalog, the
chaining rules, or to break a tie.

A role's frontmatter names its skills (skills_core, skills_preferred, skills_if_<condition>), its
MCPs, its recipes and its verification. Read a local skill by globbing **/<id>/SKILL.md —
every id is its own directory name; PACK/INDEX.md covers external ids and glob misses. One to five for
ordinary work, not everything that exists. A skill supplies the method; the role still owns scope,
deliverable and what done means, and neither grants permission. A skill or MCP that is missing is
not a blocker: say what could not be checked and continue with the role's own method.

A slash command or an installed skill that covers the request owns the turn: load it, work inside
its procedure, keep the role as posture only, and skip the role announcement.

When you fan out, route each subagent's job to its own role; put the role name, the absolute path to
PACK/roles/<id>.md, the job, its inputs and the expected return in the prompt. Never point several
subagents carrying your own role at the same evidence — the same role over disjoint slices, attempts
or rounds is fine, and each prompt says which it owns. A verifier never carries the role that
produced the work. A mechanical job gets no role, a skill that defines its own subagents keeps its
prompts, and no subagent gets the dispatcher role. Parallel subagents are not chain hops and do not
count against the three-per-turn ceiling.

Announce each role on its own line (-> reviewer) and re-route when the kind of work changes.
Chain roles inside a turn when the work needs it (planner -> implementer -> tester), meeting each
role's definition of done before switching; three per turn is the ceiling. Stop at the deliverable
the user asked for, and scale the deliverable to the task. A plain question, a typo fix, a rename, a
one-line edit: answer or do it, no role and no announcement. A role sets how you work; it never
overrides harness rules, permissions, or the user's explicit instructions.
The user can force a role at any time (/agent-<role>, "stay in tester") - honor it, keep it for the
requests that follow, and do not route or chain out of it until they name another role or say stop.
DISPATCH

if [ -n "$sid" ]; then
  printf 'To stop routing: this session only, run\\n  mkdir -p "%s/.agent-dispatcher-off" && touch "%s/.agent-dispatcher-off/%s"\\n' "$D" "$D" "$sid"
else
  printf 'To stop routing this session, ask the user for the session id first (the payload carried none).\\n'
fi
printf 'For this project, touch .agent-dispatcher-off in its root; everywhere, rm -f "%s/.agent-dispatcher-active".\\n\\n' "$D"

cat <<'DISPATCH'
ROLES
{index}
DISPATCH
""")
    hook.chmod(0o755)
    (HOOKS / "hooks.json").write_text(
        '{\n  "hooks": {\n    "SessionStart": [\n      {\n'
        '        "matcher": "startup|resume|clear|compact",\n        "hooks": [\n          {\n'
        '            "type": "command",\n'
        '            "command": "bash \\"${CLAUDE_PLUGIN_ROOT}/hooks/agent-dispatcher-activate.sh\\"",\n'
        '            "timeout": 5\n          }\n        ]\n      }\n    ]\n  }\n}\n')


def marked(txt, name, body, inline=False):
    """Replace the region between <!-- name:start --> and <!-- name:end -->, if both are present."""
    a, b = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
    if a not in txt or b not in txt:
        return txt
    sep = "" if inline else "\n\n"
    tail = "" if inline else "\n"
    return txt[:txt.index(a) + len(a)] + sep + body + tail + txt[txt.index(b):]


def write_docs(d):
    """docs/ tables come from the catalog too — a hand-maintained count goes stale silently."""
    skills = DOCS / "skills.md"
    if skills.exists():
        txt = skills.read_text()
        rows = []
        for cat in SKILL_CATEGORIES:
            ss = [s for s in d["skills"] if s["category"] == cat]
            if not ss:
                continue
            rows += [f"**{cat}** ({len(ss)}) — " + ", ".join(
                f"[`{s['id']}`](../{s['path']}){'✓' if s['verifies'] else ''}" for s in ss), ""]
        txt = marked(txt, "local", "\n".join(rows))
        ext = []
        for trust in ("official", "verified", "community"):
            es = [e for e in sorted(d["external"].values(), key=lambda x: x["id"])
                  if e.get("trust") == trust]
            if not es:
                continue
            ext += [f"### {trust} ({len(es)})", "",
                    "| Skill | Source | Licence | Fallback |", "| --- | --- | --- | --- |"]
            ext += [f"| `{e['id']}` | [{e['repository'].replace('https://github.com/', '')}]"
                    f"({e['repository']}) `{e['path']}` | {e['license'][:60]} | {e['fallback']} |"
                    for e in es]
            ext += [""]
        txt = marked(txt, "external", "\n".join(ext))
        txt = marked(txt, "counts",
                     f"{len(d['skills'])} local skills and {len(d['external'])} externally "
                     f"maintained ones, across {len(d['capabilities'])} capabilities.", inline=True)
        skills.write_text(txt)

    mcps = DOCS / "mcps.md"
    if mcps.exists():
        txt = mcps.read_text()
        rows = ["| Server | Official | Writes | Risk | Read-only path |",
                "| --- | --- | --- | --- | --- |"]
        for m in sorted(d["mcp"].values(), key=lambda x: x["id"]):
            ro = m.get("read_only_option", "")
            ro = "—" if ro.lower().startswith("none") or ro == "n/a" else ro
            rows.append(f"| `{m['id']}` | {'yes' if m.get('official') else 'no'} | "
                        f"{'yes' if m.get('writes') else 'no'} | {m.get('risk', '')} | {ro} |")
        txt = marked(txt, "table", "\n".join(rows))
        detail = []
        for m in sorted(d["mcp"].values(), key=lambda x: x["id"]):
            detail += [f"### `{m['id']}` — {m['name']}", "", m.get("purpose", ""), "",
                       f"- **Source** {m['source']}",
                       f"- **Licence** {m['license']}"
                       + (f" · **Version** {m['version']}" if m.get("version") else ""),
                       f"- **Transport** {m['transport']}", f"- **Auth** {m['auth']}",
                       f"- **Writes** {'yes' if m.get('writes') else 'no'} · "
                       f"**Risk** {m.get('risk')}",
                       f"- **Read-only** {m.get('read_only_option')}",
                       f"- **Activate when** {m.get('activation')}",
                       f"- **When absent** {m.get('fallback')}"]
            if m.get("recommended_for"):
                detail.append("- **Recommended for** "
                              + ", ".join(f"`{x}`" for x in m["recommended_for"]))
            if m.get("conditional_for"):
                detail.append("- **Conditional for** "
                              + ", ".join(f"`{x}`" for x in m["conditional_for"]))
            if m.get("notes"):
                detail += ["", f"> {m['notes']}"]
            detail.append("")
        txt = marked(txt, "detail", "\n".join(detail))
        txt = marked(txt, "counts", f"{len(d['mcp'])} servers", inline=True)
        mcps.write_text(txt)

    recipes = DOCS / "recipes.md"
    if recipes.exists():
        txt = recipes.read_text()
        rows = []
        for r in d["recipes"]:
            rows += [f"### `{r['id']}` — {r['name']}", "", r["summary"], "",
                     f"- **Use when** {r['use_when']}",
                     f"- **Roles** {', '.join(r['roles']) or '—'}",
                     f"- **Capabilities** {', '.join(r['capabilities']) or '—'}",
                     f"- [read it](../{r['path']})", ""]
        txt = marked(txt, "recipes", "\n".join(rows))
        txt = marked(txt, "counts", str(len(d["recipes"])), inline=True)
        recipes.write_text(txt)


def write_readme(d):
    readme = ROOT / "README.md"
    if not readme.exists():
        return
    txt = readme.read_text()
    out = []
    for cat in CATEGORIES:
        rows = [r for r in d["roles"] if r["category"] == cat]
        if not rows:
            continue
        out += [f"### {cat}", "", "| Command | Role | What it does |", "| --- | --- | --- |"]
        out += [f"| `/agent-{r['slug']}` | {r['name']} | {r['summary']} |" for r in rows]
        out += [""]
    txt = marked(txt, "roles", "\n".join(out))

    caps = []
    for cat in SKILL_CATEGORIES:
        rows = [s for s in d["skills"] if s["category"] == cat]
        if not rows:
            continue
        caps += [f"**{cat}** — " + ", ".join(f"`{s['id']}`" for s in rows), ""]
    txt = marked(txt, "skills", "\n".join(caps))

    mcps = ["| MCP | Purpose | Writes | Risk |", "| --- | --- | --- | --- |"]
    mcps += [f"| `{m['id']}` | {m.get('purpose', '')} | "
             f"{'yes' if m.get('writes') else 'no'} | {m.get('risk', '')} |"
             for m in sorted(d["mcp"].values(), key=lambda x: x["id"])]
    txt = marked(txt, "mcps", "\n".join(mcps) if len(mcps) > 2 else "")

    recs = [f"- **`{r['id']}`** — {r['summary']}" for r in d["recipes"]]
    txt = marked(txt, "recipes", "\n".join(recs))
    txt = marked(txt, "counts",
                 f"**{len(d['roles'])} roles · {len(d['skills'])} local skills · "
                 f"{len(d['external'])} external skills · {len(d['recipes'])} recipes · "
                 f"{len(d['mcp'])} MCP servers**", inline=True)
    readme.write_text(txt)


def main():
    d = load()
    write_roles(d)
    write_router(d)
    write_index(d)
    write_registries(d)
    write_commands(d)
    write_hook(d)
    write_readme(d)
    write_docs(d)
    print(f"indexed {len(d['roles'])} roles, {len(d['skills'])} local skills, "
          f"{len(d['external'])} external, {len(d['recipes'])} recipes, {len(d['mcp'])} mcp, "
          f"{len(d['capabilities'])} capabilities")
    return d


if __name__ == "__main__":
    main()
