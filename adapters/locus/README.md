# Locus adapter

Locus is the runtime 24 of these roles originally targeted. This directory holds what a Locus
importer would need, and nothing that assumes an API that has not been verified.

## Status

**Metadata only.** No Locus import API is documented publicly that this repository has verified, so
nothing here writes to Locus. `locus.json` is a portable export of the role catalog in the shape
Locus's own template pack used, so an importer can be written without re-deriving it.

## Mapping

| This repository | Locus concept |
| --- | --- |
| `templates/<cat>/<id>.md` body | role instructions / custom instructions |
| `summary` | description |
| `use_when` / `not_for` | routing: use_when / do_not_route_for |
| `tags` | capability tags |
| `category` | category |
| `slug` | existing specialty fallback |
| loadout frontmatter | no native equivalent — carried as extension metadata |
| Mode section in the body | mode-specific guidance (Ask / Work / Plan / Grill) |

## What does not transfer

The skill, recipe and MCP layers have no Locus equivalent that this repository has verified. An
importer should carry them as opaque extension metadata rather than dropping them, so a round trip
does not lose the loadouts.

The role bodies were adapted **away** from Locus vocabulary — its runtime, mode, memory-scope and
access-level settings were replaced with Claude Code's equivalents, because naming settings that do
not exist misdirects an agent. Importing back into Locus means re-adapting those specific lines,
not reverting the file.
