# Claude Code adapter

What `build.py` renders, and why these paths are what they are.

| Canonical source | Rendered to | Why there |
| --- | --- | --- |
| `templates/<cat>/<id>.md` | `skills/agent-dispatcher/roles/<id>.md` | ships inside the skill so one install carries it |
| — | `skills/agent-dispatcher/SKILL.md` | Claude Code auto-discovers `skills/*/SKILL.md` |
| — | `skills/agent-dispatcher/INDEX.md` | level-1 discovery, read on demand |
| `templates/` | `commands/agent-<slug>.md` | Claude Code auto-discovers `commands/*.md` |
| — | `hooks/agent-dispatcher-activate.sh`, `hooks/hooks.json` | `hooks/hooks.json` is auto-loaded |

The root paths are fixed by Claude Code's plugin auto-discovery, not by preference. That is the
whole reason the canonical roles live in `templates/` instead: so the portable definition is not
hostage to one runtime's directory layout.

## What the adapter adds

Rendering a template injects a **loadout block** above the role's tool posture: the skills by tier,
the conditional buckets, the recipes, the verification, the MCPs — plus the standing rule that a
skill is guidance rather than authorization and that an absent one is not a blocker. None of that
prose lives in the canonical template.

Skill categories nest one level deeper (`skills/<category>/<id>/SKILL.md`), which keeps them out of
Claude Code's `skills/*/SKILL.md` auto-discovery. That is deliberate: eighty skill descriptions in
every session's system prompt is exactly the cost progressive disclosure exists to avoid. They are
reached by path, from the index, when a loadout names them.

## Installing

Plugin (`.claude-plugin/plugin.json` + `marketplace.json`), or `./install.sh` for a manual install
into `~/.claude` with a manifest so uninstall removes only what it wrote. Running both
double-installs the skill.

## Adding another runtime

Write a renderer beside this one. The canonical `templates/`, `skills/`, `recipes/` and `catalog/`
need no changes — that is the test of whether the separation is real.
