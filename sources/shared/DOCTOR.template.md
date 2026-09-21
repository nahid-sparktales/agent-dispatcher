# Dispatcher doctor

Run only when the user requests a doctor or health check. This is a read-only inspection,
not routing, installation, authentication, or permission approval. Preserve the active role,
activation state, output preference, and disabled-skill preferences.

## Commands

- `doctor` or `doctor all`: package health plus every bundled guide, catalog external skill,
  catalog MCP, and additional skill/tool/server the current host exposes.
- `doctor skills`, `doctor tools`, `doctor mcps`: limit the inventory section to that category.
- `doctor setup`: show items needing setup or investigation, including blocked/retired items.
- Add a role id, alias, or name, such as `doctor all reviewer`, to focus recommendations.
  This does not switch the current role or hide other entries from the full inventory.
- Claude also provides `/agent-doctor`; Codex uses `$agent-dispatcher doctor`.

## Gather current evidence

1. Read INVENTORY.md and INVENTORY.json beside this reference. Reuse its status rules and
   full-catalog procedure. Do not load all skill bodies. Catalog entries are candidates, not
   installed or connected services.
2. Collect metadata for the host's visible skills, callable native tools, MCP servers, and
   individual MCP tools. Use supported discovery if available; a deferred discovery result
   is not proof of a callable tool. Include items outside the catalog. Match external skills
   using source repository/path or equivalent provenance, never a similar name alone.
3. Reuse relevant successful calls and known authentication failures from this session.
   Exposed tools can be usable without a connection having been tested. A registered server,
   installed CLI, credential variable, or service-related skill does not prove connectivity.
   Do not call every tool, make network probes, or inspect credential values to fill gaps.
4. Build a minimal evidence object using the schema below. Report unknown when host discovery
   is incomplete. Explicit user-disabled items are blocked and must not be recommended for
   activation. Only say missing when an authoritative host result establishes absence.
5. Run the bundled helper with that evidence. `PACK` is the installed skill directory;
   `PROJECT` is the user's project, not PACK. Quote each resolved path as a separate argument.

Claude helper: `python3 -B PACK/doctor.py all --pack PACK --project PROJECT --host claude --evidence - --json`

Codex helper: `python3 -B PACK/scripts/doctor.py all --pack PACK --project PROJECT --host codex --evidence - --json`

Pass the evidence as JSON on standard input. Use the host's structured process input or a
quoted heredoc; never interpolate raw tool descriptions or task text into shell code. Change
`all` to the requested category and add `--role reviewer` (or the resolved role) if requested.
Use `--config-dir PATH` only for a known custom host config directory. Outside a host session,
the helper still checks files and metadata but cannot discover live connections itself.
If the helper cannot run, use the inventory procedure and state which health checks were unavailable.

## Evidence format

`--evidence FILE` reads a sanitized snapshot; `--evidence -` reads standard input. The snapshot
describes observations from this session, not a server configuration or authorization grant.
Collect a fresh snapshot for each report; do not reuse connection results from another session.
Do not pass raw configuration, environment variables, headers, tokens, accounts, or tool results.

```json
{
  "schema_version": 1,
  "skills": [{"id": "host-skill-id", "catalog_id": "matched-catalog-id", "status": "exposed"}],
  "mcps": [{"id": "github", "catalog_id": "github", "status": "verified"}],
  "tools": [{"id": "mcp__github__list_issues", "server": "github", "status": "verified"}],
  "disabled": ["user-disabled-skill-id"],
  "host": {"activation": "explicit", "hook_registered": true, "hook_trust": "unknown"}
}
```

The entries above illustrate syntax, not this user's connection state. Omit fields without
evidence. `catalog_id` is optional and must be backed by a provenance match. For host-only
entries use a stable id without claiming a catalog match. IDs must contain only letters,
digits, underscores, dashes, dots, colons or slashes, at most 160 characters; normalize display
names when necessary and preserve the mapping in your report.

Entry statuses: `exposed`, `verified`, `missing`, `disabled`, `blocked`, `auth_required`, or
`unknown`. `verified` means a relevant successful operation was observed, not all operations
were tested. Host activation is `explicit`, `enabled`, `disabled`, or `unknown`; hook trust
is `trusted`, `untrusted`, or `unknown`. The helper rejects unsupported fields/statuses.

## Report and recommend

Lead with installation health, inventory totals, and discovery limits. Then show every entry
in the requested scope, grouped into bundled guides, external/other skills, native tools, and
MCP servers/tools. Include `Name | Status | Usable for / next step`; preserve evidence that
distinguishes a callable tool from a verified connection. Show existing fallbacks. Compact
output means short rows, not dropping items. Split long reports with explicit continuations.

Finish with a ranked shortlist of relevant setup recommendations, with the benefit, reason,
current status, smallest next step, and catalog source/fallback. Use the requested role and
observed project stack; otherwise state the assumed use case. The helper's deterministic
recommendations are a starting point: before presenting them, check whether observed native
or alternate tools already cover each recommended capability for this task. Remove redundant
suggestions and explain any reprioritization from the user's actual work. The standalone CLI
matches catalog identities; it cannot prove equivalence between different host tools.
Do not recommend unmaintained entries, blocked/disabled resources, reference-only packages,
or another connection when an equivalent usable capability already covers the need. Unknown
items get a verification step, not an assertion that installation is required. Do not present
community entries as mandatory. Check current official docs before giving version-specific
setup commands; catalog links are references, not a fresh vendor-documentation check.

Activation being off is a supported explicit-invocation mode, not a broken installation.
Registered hooks do not prove trust or execution. Skill usability as guidance does not prove
its optional tools are connected. State that no setup changes were made; any requested setup
is a separate action within the user's authorization.
