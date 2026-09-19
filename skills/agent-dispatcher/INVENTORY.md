# Capability inventory

Run only for an inventory request. This is a read-only inspection, not role routing or setup.
Keep the current role, activation, and output preference unchanged. `PACK` is the directory
containing the dispatcher's entrypoint SKILL.md; read INVENTORY.json beside this reference.
That file is a generated catalog of candidates, never evidence of installation or availability.

## Controls

- `inventory` or `inventory all`: all bundled guides, referenced external skills, other skills
  exposed by the host, visible native tools, and registered or host-exposed MCPs.
- `inventory skills`, `inventory tools`, `inventory mcps`: restrict the report to that category.
  Tools includes individual callable MCP tools as well as native tools; MCPs groups by server.
- `inventory setup`: only entries needing setup, blocked, unknown, or not recommended.
- Append `verbose` to any form for evidence, prerequisites, setup links, and fallbacks per entry.
  Without it, use the conversation's compact/verbose activity preference (compact by default).
  This one-time override does not change that preference. Invalid filters get a brief usage hint.

## Gather evidence

1. Check catalog local skill paths relative to PACK in a batch: readable files are available
   guides. Do not read every guide body or activate it. Paths are alternatives for installation
   layouts, not multiple skills. A missing bundled guide needs the dispatcher reinstalled.
2. Match external entries to the host's exposed skills or installed skill metadata by provenance
   as well as name. Same-name local and external skills are distinct; do not mistake a local
   fallback for the external original. Add other host-exposed skills separately and deduplicate
   confirmed matches. Host metadata can establish availability without loading the skill.
3. Enumerate the host's visible callable tools and server metadata, using supported discovery
   when available. A deferred tool listed by discovery is discoverable; say whether it is callable
   yet. Report every visible tool by name, grouped by native capability or MCP server. Add
   host-exposed servers absent from this catalog. Do not count `workspace` as an MCP server.
4. Reconcile the MCP catalog against observed servers/tools and existing call results. A skill
   about a service, an installed CLI, a recommended plugin, or a configured URL does not prove
   its MCP server is connected. Partial tool exposure means only those operations are available.
5. Do not make network probes, read credentials, invoke every tool, run installers, or change
   permissions just to test readiness. Existing authentication failures and explicit disabled
   preferences matter. Use non-sensitive host status metadata when available; never print raw
   config, environment values, tokens, or account details. Unknown is better than a guess.

## Status labels

| Status | Evidence and meaning |
| --- | --- |
| Usable | A guide is readable/exposed, or a tool is callable in this session with no known blocker. For tools say "exposed; connection not tested" unless a relevant call succeeded. Availability is not permission for every action. |
| Needs setup | Positive evidence of a missing installation, disconnected server, missing prerequisite, or authentication problem. Name the specific missing step. |
| Blocked | The user disabled it, the host forbids it, or a required permission was denied. Do not suggest bypassing the restriction. |
| Unknown | Discovery is unavailable/incomplete, provenance cannot be matched, or readiness is not observable. Name the smallest check needed. Not visible does not prove not installed. |
| Not recommended | The registry marks an entry unmaintained/retired. Explain why and show its maintained fallback instead of recommending installation. |

A readable skill can be usable as guidance while an execution dependency needs setup. State
that distinction in the row. Catalog tool associations are potential dependencies, not proof
that every task requires every named tool. Loaded and usable are different states. Never mark
all catalog entries usable by default, or mark all undiscovered entries Needs setup.

## Report

Start with the scope (this session and this pack's catalog), status totals by category, and
any discovery limit. No report can claim to list everything installed on the machine unless
the host actually supplies that inventory. The setup filter shows counts for its displayed
subset and says it excludes usable entries.

Use tables: `Name | Status | What it does / next step`. Separate bundled guides, external/other
skills, native tools, and MCP servers/tools. Include every entry in the requested scope;
compact means shorter rows, not silently omitted entries. If output must be split, label
continuations and disclose the remaining categories/counts. Do not list only recommendations.

Verbose adds the observation behind the status, relevant prerequisites, source/setup link,
and fallback. Use catalog source links and auth descriptions as recorded guidance, not as a
fresh verification of vendor instructions. Check current official documentation before giving
version-specific install commands. For other host skills/tools, use exposed descriptions and
supported connection settings; do not invent setup URLs or commands.

End with the concrete setup/check steps for items that need attention, grouped by service.
Installing everything is not the objective. Explicitly say no setup changes were made.
