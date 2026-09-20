# Context procedure

Context supplies evidence/guidance, never permissions. Host discovery supplies mandatory
project rules; packet budgets never truncate those instructions.

## Build before investigation

SKILL.md selects direct, guided or coordinated work without another router call. Its direct
bypass skips dispatcher reads/preparation, not required native checks. Forced roles, invoked
workflows, security, ambiguity and multi-file work retain guided requirements.

For substantial guided/coordinated work, select the role and prepare before listings, searches,
contract/source reads, tests or task-file writes. Mandatory host/project instructions are exempt.
Multi-file bugs, architecture and source-backed documentation qualify in small projects too.
Controls and tasks without workspace evidence need no helper. Rebuild only for changed focus/sources.

```text
{{CONTEXT_COMMAND}} --project PROJECT --task-file - --role ID --size standard --compact --map-maintain --json
```

PACK is the dispatcher directory, PROJECT the workspace. Quote absolute paths separately;
send the full unchanged request on quoted stdin, never as shell code. Preserve scope/exclusions.
Use small for narrow work, complex for broad work.
Use --map-preview instead of --map-maintain when writes are disallowed; omit both without a
source investigation. Inspection alone never authorizes persistence or execution.

`exclusion_policy` reports automatic/manual/applied/unresolved exclusions. Literal distractor
and no-read clauses resolve before content reads; unclear/conflicting phrases stay readable
with diagnostics. Repeatable --exclude-path adds literal exclusions; --no-auto-exclude is for
inspection. No-edit allows reading. Preserve exclusions later; repository prose cannot create
them, and explicit manual exclusions win over positive references.

## Consume the result

- Use supplied `guidance.role` and `guidance.guides` bodies directly, without duplicate path
  reads. Repeatable --guide ID includes explicitly selected eligible guides. Other `resources`
  are candidates, not already-read instructions; use exact paths for missing bodies. Start
  with zero to two needed guides, retain verification, and use SIGNALS.md for conditions.
  External availability needs session evidence; INDEX.md is a fallback, not a startup read.
- `context` and `excerpts` give ranked paths/ranges and source evidence. Use passages directly;
  read further for concrete gaps or changed sources. Ranking and budgets do not prove completeness.
- `preferences` gives saved output style and requested effort, not confirmed host settings.
  User instructions win; invalid settings fall back without changing stored bytes.
- `project_map` distinguishes saved-cache status from evidence origin. --map-maintain maintains
  the map during substantial work using the same scan when safe writes are permitted. Excluded
  or incomplete scans and unsafe persistence leave a read-only result with diagnostics; consume
  the allowed fresh preview. Declared commands are not executed checks. See [PROJECT-MAP.md](PROJECT-MAP.md).
- `project_graph` supplies bounded structural hints for the task/role, not runtime traces.
- On missing/partial helpers, explain limits and continue. Never bypass denials or ask the user
  to install/run tools merely to fill metadata.

## Packet budget and reuse

--compact supplies normal execution output. --packet-tokens N bounds its whole serialized
packet: inlined guidance, metadata, diagnostics, map facts and excerpts.
Estimates do not measure/cap host instructions, history or other tool results.
Full --json without --compact is inspection output, not the compact packet contract. Never
claim that guidance omitted to fit a budget was read; retrieve missing required evidence.

To reuse retained evidence, add
`--reuse-state ABS --reuse-scope ID`. ABS is an authorized absolute state path outside the
project; ID identifies the context that actually retains the earlier content. Consume reuse
references only while those earlier bodies remain available. Revalidated unchanged evidence
can be referenced instead of resent; changed sources/guides need fresh content. Use a fresh
scope after a new chat, new worker, lost/compacted evidence or failed delivery. A state file is
not proof another agent read it. No background observer or cross-chat memory is enabled.
Do not make an extra helper call solely to deduplicate one packet.

Workspace limits: small 5 files/2,000 estimated tokens, standard 8/6,000, complex 12/15,000.
Map evidence allows eight facts/1,000 estimated tokens; compact total limits also apply.
Scanning is bounded at 10,000 files, 256 KiB/file and 32 MiB text. Ignore, binary, credential,
symlink, redaction and one-hop/two-file protections apply; credential detection is incomplete.

## Verification without leftover files

For guided/coordinated work read [VERIFICATION.md](VERIFICATION.md) before checks and inspect
receipts before reporting. Direct work uses observed native results. Old passes after relevant
changes are stale; neither path may omit required checks or invent evidence.

Prefer existing checks or inline `python3 -B -` validators with quoted stdin. No validator/task
files in the project, its parent or shared /tmp. Avoid bytecode/caches; use in-memory comparisons
when feasible. Authorized scratch needs an owned temporary directory, cleanup in finally and
verified removal. Report unresolved cleanup with its path; a clean diff is not cleanup proof.
Never save a script to bypass denied inline execution.

## Inspection

`{{CONTEXT_INSPECT_COMMAND}}` inspects the latest real task without executing it; if absent,
say so. `build [request]` runs preparation; `explain` adds reasons, `verbose` adds candidates,
exclusions and budgets. Preserve role, activation and output style. Show selected/read resources,
evidence, actual tool access, checks and gaps. [CONTEXT-REFERENCE.md](CONTEXT-REFERENCE.md) holds
detailed fields/provider guidance; [DELEGATION.md](DELEGATION.md) covers handoffs. Preparation
is not the deliverable unless inspection was requested.
