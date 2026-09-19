# Claude Code adapter

What `build.py` renders, and why these paths are what they are.

| Canonical source | Rendered to | Why there |
| --- | --- | --- |
| `templates/<cat>/<id>.md` | `skills/agent-dispatcher/roles/<id>.md` | ships inside the skill so one install carries it |
| — | `skills/agent-dispatcher/SKILL.md` | Claude Code auto-discovers `skills/*/SKILL.md` |
| — | `skills/agent-dispatcher/INDEX.md` | level-1 discovery, read on demand |
| `CONTEXT.template.md` + `catalog/context-plan.schema.json` | `skills/agent-dispatcher/CONTEXT.md` | the context engine, read on demand |
| `catalog/signals.json` | `skills/agent-dispatcher/SIGNALS.md` | rendered in because an install never receives `catalog/`; split from `CONTEXT.md` for the same reason `INDEX.md` is split from `SKILL.md` |
| `templates/` | `commands/agent-<slug>.md` | Claude Code auto-discovers `commands/*.md` |
| — | `commands/agent-context.md`, `commands/agent-decision.md` | the inspector; generated because the build clears `commands/agent-*.md` |
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

The manual install manifest also records ownership of the fixed dispatcher skill and hook paths.
If either path already exists without that manifest, installation and uninstall refuse to change
it. Move conflicting files aside before installing, or restore the original manifest for a prior
manual installation. Without a manifest and without either file, uninstall leaves settings alone.

## Adding another runtime

Write a renderer beside this one. The canonical `templates/`, `skills/`, `recipes/` and `catalog/`
need no changes — that is the test of whether the separation is real.
