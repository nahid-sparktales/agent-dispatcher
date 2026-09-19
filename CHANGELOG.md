# Changelog

## 2.0.0 — 2026-09-19

Evolves the pack from 27 standalone role prompts into a composable capability system. Roles keep
their identity and working method; specialist knowledge moves into skills that load on demand.

### Added

- **Skill layer.** 79 local skills under `skills/<category>/<id>/`, each a standard Agent Skill
  (`SKILL.md` with `name` + `description`) plus a `manifest.json` sidecar holding pack metadata, so
  the skill stays portable to any Agent Skills runtime.
- **External skill registry** (`catalog/external-skills.json`) — 31 skills from Anthropic, Vercel,
  Next.js, Microsoft Playwright and two community sources. Referenced with full provenance, never
  vendored, never fetched at runtime. Each records source, licence, version, verification date,
  trust level, whether it ships scripts, and the fallback when it is absent.
- **MCP registry** (`catalog/mcp.json`) — 19 servers, each verified against the vendor's own
  documentation by two independent research passes, recording write posture, risk, read-only path,
  activation condition and fallback.
- **Recipes** — 8 multi-step workflow shapes, each of which names what to cut.
- **Verification family** — skills with `verifies: true`, plus `docs/verification.md` holding the
  matrix that keeps *created / executed / tested / reviewed / deployed / verified* apart.
- **Loadouts.** Every role declares `skills_core` / `skills_preferred` / `skills_optional` /
  `skills_if_<condition>`, `mcp_recommended` / `mcp_conditional`, `recipes` and `verification` in
  its frontmatter. Generated into `catalog/loadouts.json`, which doubles as the dispatcher's
  capability registry.
- **Documentation** — `docs/architecture.md`, `skills.md`, `mcps.md`, `recipes.md`,
  `verification.md`, `security.md`, `adding-a-skill.md`, `adding-an-agent.md`.
- **Adapters** — `adapters/claude-code/` documents what is rendered where and why;
  `adapters/locus/` carries a portable catalog export.

### Changed

- **Repository layout.** Canonical roles moved from `skills/agent-dispatcher/roles/` to
  `templates/<category>/<id>.md`. The roles under `skills/agent-dispatcher/roles/` are now
  *generated* renderings carrying the Claude-specific loadout block, so the canonical definition
  stays free of runtime syntax.
- **`build.py`** is a validator as much as a generator. It now refuses to build on an unknown
  category, a loadout pointing at a skill that does not exist, a capability no skill provides, a
  tool id absent from the MCP registry, a missing declared reference file, a skill named as
  verification that does not declare it, **a role whose core + preferred exceeds five**, or **two
  skills providing the same capability in always-considered tiers**.
- **`test_build.py`** grew from a consistency check into a validation suite: generated-versus-source
  agreement, cross-reference resolution, standard SKILL.md frontmatter, body length bounds,
  credential and absolute-path scanning, registry completeness, and docs-versus-catalog counts.
- **`install.sh`** installs every skill category, not only the dispatcher.
- Schema version `2.0.0`. Role ids, slugs, commands and categories are unchanged.

### Compatibility

No breaking change for existing users. Every command (`/agent-*`), role id, slug and category is
preserved. Loadout fields are additive: a role with no loadout still works, and every role remains
useful with no optional skill or MCP installed.

## 1.1.0 — 2026-09-19

- Roles became the source of truth; `build.py` became an indexer over them.
- Added `version-control`, `data-engineer`, `incident-responder` (24 → 27).
- Skills and commands outrank routing; subagents are routed per job rather than inheriting the
  caller's role; perpetual mode gained per-session and per-project scopes.
- Shipped as a Claude Code plugin.

## 1.0.0 — 2026-09-18

- Initial router: 24 roles adapted from the Locus Agent Template Pack, per-role commands, and a
  SessionStart hook for perpetual mode.
