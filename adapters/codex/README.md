# Codex adapter

The Codex adapter exports the shared role, skill, recipe, and decision catalogs as one native
Agent Skill. It also builds a Codex plugin bundle. Claude Code's package remains supported.

## Install and update

From a clone of this repository, with Python 3.10+ available:

```bash
python3 install_codex.py
```

The installer writes `~/.agents/skills/agent-dispatcher/`. Start a new Codex task and select
**Agent Dispatcher** in the skill picker, or use `$agent-dispatcher` in the CLI or editor.
Run the same installer after updating the clone to update the skill.

```text
$agent-dispatcher Debug the failing test and verify the fix.
$agent-dispatcher reviewer Review the current diff.
$agent-dispatcher uidesigner Improve the settings page.
$agent-dispatcher output verbose
$agent-dispatcher output compact
$agent-dispatcher inventory
$agent-dispatcher inventory setup verbose
$agent-dispatcher doctor
$agent-dispatcher doctor all reviewer
$agent-dispatcher context explain
$agent-dispatcher decision
$agent-dispatcher status
```

Role ids, names, and the short aliases from the main README are accepted. Codex uses arguments
to a single skill rather than the Claude `/agent-*` commands. The optional decision engine
ships disabled and needs no credential for ordinary routing.

The installer replaces only a directory bearing its ownership marker and refuses unowned or
symlinked targets. It does not edit AGENTS.md, model settings, or permissions. Supporting guides
are packaged as `GUIDE.md` references so Codex discovers only one skill, with the other methods
loaded on demand. Skill selection follows the host's normal behavior and your instructions.

## Inventory

`$agent-dispatcher inventory` lists this pack's bundled and referenced skills alongside skills,
tools, and MCP servers exposed by the host. Use `skills`, `tools`, `mcps`, or `setup` to filter;
append `verbose` for evidence and setup details. Each row distinguishes usable, needs setup,
blocked, unknown, and not recommended. Tool exposure is not proof of a working connection or
permission for every action. Missing discovery produces an explicit unknown, not an invented
installation result. The command makes no account probes or setup changes.

`$agent-dispatcher doctor` adds package integrity, activation/hook checks, and ranked setup
recommendations to the complete inventory. Append `all reviewer` to focus recommendations,
or `skills`, `tools`, `mcps`, or `setup` to filter the inventory. The helper lives at
`scripts/doctor.py`; its shared procedure is `references/DOCTOR.md`. Session evidence distinguishes
callable tools from connections that have successfully been used. The offline CLI reports unknown
when it has no session evidence. Neither form connects accounts or changes configuration.

## Local context

`$agent-dispatcher context build <request>` returns relevant workspace passages with line numbers,
reasons and an estimated budget, without doing the requested work. Substantial or unfamiliar
workspace tasks use `scripts/context.py` after role selection. Small obvious edits skip this step.
The helper is local and read-only, with no model requests, persistent index or account setup.
Existing context inspection modes remain available. Entry instructions and `references/CONTEXT.md`
are capped at 6 KiB each; additional references load only when their workflow is needed.

`$agent-dispatcher map build` records a local source-linked project map; `map show <request>`
inspects relevant facts and `map refresh` updates it. The helper is `scripts/project_map.py`
with instructions in `references/PROJECT-MAP.md`. Only build/refresh writes the map, to private
state outside the project (`~/.cache/agent-dispatcher/state-v1/`). Context selection validates existing map
facts, withholds stale claims, and reports incomplete coverage without changing the map.

## Activity output

Compact summaries name the role, skills/guides actually read, selected built-in tools, and
selected MCP servers. `output verbose` adds reasons, context read, recipes, missing resources,
and verification plans. `output compact` restores the short format; `output` reports the style.
The preference lasts for this conversation and defaults to compact in a new task. It does not
change routing or permissions. `context verbose` inspects a plan once without changing this
preference. The final report distinguishes actual tool use and checks from planned selections.

## Optional session activation

Explicit invocation works without a hook. To opt into future sessions, invoke:

```text
$agent-dispatcher on here
```

This adds the current project's absolute path to the user-owned activation state and registers
a `SessionStart` hook. **Review and trust the hook through Codex's `/hooks` interface** before
expecting automatic activation. Registration alone does not establish trust. New or changed
hook code may require another review. If your host does not offer hooks, use explicit invocation.

| Arguments after `$agent-dispatcher` | Effect |
| --- | --- |
| `on here` | Enable this project for future sessions. |
| `on` or `on everywhere` | Enable future sessions across projects. |
| `off` | Stop routing now; when the hook supplied a session id, persist silence for that session. |
| `off here` | Silence this project, including when globally enabled. |
| `off everywhere` | Disable global activation; individually enabled projects remain enabled. |
| `status` | Show activation state and hook registration; hook trust still needs inspection in Codex. |

Without a session id, `off` cannot promise persistence after compaction. Use `off here` when
you want to persistently silence this project. Project and session silences override activation.

State lives in `${CODEX_HOME:-~/.codex}/agent-dispatcher/state.json`; manual hook registration
lives in the same config directory's `hooks.json`. The helper backs up existing hook settings
before its first edit and preserves unrelated handlers. Claude flags and repository-local
activation files do not arm Codex. The hook reads state, writes nothing, and makes no network
request. Malformed state or hook input produces no routing preamble.

`python3 install_codex.py --with-hook` registers the hook in advance but does not enable
activation or trust the hook. You can set a custom skill directory with `--skills-dir PATH`
and config directory with `--config-dir PATH`. The skill directory must be one Codex discovers;
for a project install use `.agents/skills`. `CODEX_HOME` is honored when no config override is
given. When controlling an installation with a custom config directory, run Codex with the
matching `CODEX_HOME`, or pass `--config-dir PATH` directly to the activation helper.

## Uninstall

```bash
python3 install_codex.py --uninstall
```

Use the same directory overrides if you installed elsewhere. Uninstall removes the owned
skill and its exact manual hook registration, preserving unrelated skills, hooks, and activation
state. Reinstalling can therefore restore previously enabled scopes.

## Build and validate

```bash
python3 build_codex.py
python3 -B -m tests.test_codex
# Optional: requires an installed Codex CLI; no model call or hook execution.
python3 verify_codex_runtime.py
```

The generated plugin is `dist/codex/plugins/agent-dispatcher/`, with a
`.codex-plugin/plugin.json` manifest and native `hooks/hooks.json`. It is a self-contained
bundle for a Codex marketplace; the repository's existing Claude marketplace is not a Codex
marketplace. For a direct installation, use the skill installer above. Use one distribution
method per host to avoid duplicate skills or hooks.

Edit `adapters/codex/SKILL.template.md` and the adapter helpers for Codex behavior. Edit the
canonical roles and guides for shared methods. `build_codex.py` adapts host paths, tool language,
and mode controls during export; generated output is ignored by Git.

CI checks package contents and references, offline role selection, project configuration,
install/update/uninstall, ownership and rollback, hook output, and activation/silence scopes
on Linux and macOS. The optional runtime check asks Codex itself to discover the skill and
verifies the supporting guides do not become separate skills. It does not test live model
behavior or establish hook trust.

Host contracts: [Codex skills](https://learn.chatgpt.com/docs/build-skills),
[Codex hooks](https://learn.chatgpt.com/docs/hooks), and
[Codex plugins](https://developers.openai.com/plugins/build/plugins).
