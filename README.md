# agent-dispatcher

A Claude Code skill that routes each request to one of the 24 Locus agent-template roles and works as
that specialist. Generated from `locus-agent-templates.json`.

## Use

- `/agent-dispatcher` — route the current request (and the ones after it).
- `/agent-dispatcher on` / `off` — perpetual mode: arms the dispatcher at the start of every session
  via a SessionStart hook, flagged by `~/.claude/.agent-dispatcher-active`.
- `/agent-uidesigner`, `/agent-reviewer`, `/agent-tester`, … — pick a role directly (24 commands).

Roles chain inside a turn when the work needs it (`planner → implementer → tester`), up to three.

## Layout

    locus-agent-templates.json   source catalog: 24 role templates
    build.py             generator — reads the template JSON, writes everything below
    SKILL.template.md    the router: activation, routing, chaining, shared contract ({{ROLES}} slot)
    install.sh           build + copy to ~/.claude + register the SessionStart hook
    skills/agent-dispatcher/SKILL.md      generated router
    skills/agent-dispatcher/roles/*.md    24 role files, loaded on demand
    commands/agent-*.md                   24 per-role slash commands
    hooks/agent-dispatcher-activate.sh    perpetual-mode hook (carries a compact role index)

Edit `SKILL.template.md` or `build.py`, then `./install.sh`. Never edit the generated files.

Source: Locus Agent Template Pack v1.0.0 (content pack, adapted here for Claude Code — the Locus
runtime, mode, memory-scope, and access-level settings were mapped to this harness's equivalents).
