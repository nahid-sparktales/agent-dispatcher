# Contributing

Everything here is generated from a small set of hand-edited sources. The most common mistake is
editing the wrong file, so start with what is canonical.

## Canonical, and the only things worth editing

```
templates/<category>/<id>.md          a role
skills/<category>/<id>/SKILL.md       a skill, plus its manifest.json sidecar
recipes/<id>.md                       a workflow shape
catalog/mcp.json                      the MCP registry
catalog/external-skills.json          externally maintained skills
catalog/signals.json                  how each conditional skill bucket is decided
catalog/context-plan.schema.json      the shape of a context plan
sources/shared/SKILL.template.md      the router body
sources/shared/ACTIVITY.template.md   compact/verbose activity reporting shared by both hosts
sources/shared/INVENTORY.template.md  availability and setup inspection shared by both hosts
sources/shared/DOCTOR.template.md, doctor.py read-only health checks and setup recommendations
install_claude.py                     staged manual Claude installation and rollback
sources/shared/CONTEXT.template.md, context.py concise context procedure and local excerpt selector
context_packet.py, context_reuse.py   complete packet budget and retained-context evidence reuse
sources/shared/PROJECT-MAP.template.md, project_map.py source-linked facts, automatic maintenance, and freshness
project_graph.py                     deterministic structural index and task/role projection
repo_index.py                        repository facts: per-file records, symbols, edges, git co-change (no scores)
retrieval.py                         query analysis, candidate retrievers, rank fusion, expansion, explorer, explain CLI
context_budget.py                    context optimizer: files, reasons and excerpts within a byte/token/file budget
evals/retrieval/                     offline file-localization benchmark (mine.py builds datasets, run.py evaluates)
sources/shared/VERIFICATION.template.md, verification.py task-scoped check receipts and completion evidence
change_audit.py                       task baseline, actual file changes, scope and cleanup
preferences.py                       saved output and requested-effort settings
sources/shared/CONTEXT-REFERENCE.template.md advanced context reference and worked plan example
sources/shared/CONTROLS.template.md   Claude activation and configuration details
sources/shared/DELEGATION.template.md on-demand chaining and delegation guidance
sources/shared/HOOK.template.sh       the perpetual-mode SessionStart hook
decision/                             the optional decision engine
adapters/codex/                       Codex entrypoint template and activation/CLI helpers
build_codex.py, install_codex.py       Codex export and installation
evals/decision/                       decision fixtures and the comparison harness
tests/                                offline validation suites and shared runner
docs/*.md                             prose only — the tables inside markers are generated
```

Everything under `skills/agent-dispatcher/`, `commands/`, `hooks/`, `catalog/skills.json`,
`catalog/loadouts.json`, and every region between `<!-- name:start -->` markers is generated.
`tests/test_build.py` fails if a generated file has been hand-edited, because the next build would
silently discard the change.

## Before opening a PR

```bash
python3 build.py       # regenerate committed artifacts
python3 -B -m tests    # run every offline test group
```

Tests live under `tests/`. Run one group with `python3 -B -m tests.test_project_map`,
substituting the module name. End-to-end support tests live under `tests/e2e/` and are collected
by `tests.test_e2e`.

CI runs the validation suites before any separate build step, so regeneration cannot hide
missing or stale committed files. It checks Python 3.10–3.14 on Linux and Python 3.14 on macOS,
then requires a clean checkout. `tests/test_release.py` installs into temporary directories and is
deliberately not called by `install.sh`, which would recursively invoke installation tests.

Workflow and shell checks use actionlint and ShellCheck. The security workflow runs Gitleaks
against the full fetched history and current files; CodeQL scans Python and Actions once the
repository is public. No API key or live model call is part of CI. Actions are pinned to commit
SHAs and updated by Dependabot. The actionlint and Gitleaks binary versions and SHA-256 checksums
are pinned in the workflows; update those together after verifying upstream release checksums.

Editing the perpetual-mode hook means editing `sources/shared/HOOK.template.sh`, not
`hooks/agent-dispatcher-activate.sh` — the second is generated from the first with the role
index substituted in. The template is an ordinary shell file, so
`bash -n sources/shared/HOOK.template.sh`
parses it — which catches a syntax error and nothing else. What catches behaviour is the suite
running the rendered hook against a temporary config dir instead of only reading it.

Substitutions in `build.py` go through `sub()`/`render()`, and generated regions of a hand-edited
file through `marked()`. All three raise when their search string or marker is absent. Do not
route around them with a bare `str.replace`: a replace that matches nothing leaves the artifact
as it was, and the drift check then compares stale content against an equally stale rebuild and
passes.

All validation commands must pass. `tests/test_decision.py` needs no network and no key: every external answer comes
from a mock provider, so CI stays free and deterministic. The build is a validator as much as a generator — it rejects an unknown category, a
loadout pointing at a skill that does not exist, a capability no skill provides, an unknown tool id,
a missing referenced file, a verification skill that does not declare itself, more than five or more
than 30KB of always-on skills per role, and two skills providing one capability in always-considered
tiers.

`python3 build_codex.py` exports the shared sources to `dist/codex/plugins/agent-dispatcher/`.
Do not commit or hand-edit that build output. The Codex adapter translates host-specific paths
and controls, while supporting guide contents remain identical to the canonical sources.
`python3 verify_codex_runtime.py` optionally verifies discovery using an installed Codex CLI;
it requires neither authentication nor a model call and is not part of the offline CI matrix.
See [the Codex adapter](adapters/codex/README.md) for installation and hook trust details.

## Adding a role

See [docs/adding-an-agent.md](docs/adding-an-agent.md). Write `not_for` as territory another role
owns — that line is what keeps near-miss roles out of the routing, and a list of bad habits excludes
nothing.

Keep the loadout small. A normal task should reach for one to five skills; a role with six
always-on skills is a role that loads everything and reads nothing.

`summary`, `use_when`, `not_for` and `tags` are also the routing metadata the optional decision
engine reads. `build.py` carries them into `catalog/loadouts.json`, and that is the whole of what
it takes for a new role to become a candidate — there is no Jev prompt to update, and adding a
second registry would be a bug. Write `not_for` precisely: it is the line that decides
near-neighbour routing for the model as well as for a reader.

Then add fixtures to `evals/decision/agents.json` — at least one obvious case and one
near-neighbour case against whichever role yours is easiest to confuse with. `tests/test_decision.py`
fails if a role has no gold label anywhere, and validates every id against the registry.

## Adding a skill

See [docs/adding-a-skill.md](docs/adding-a-skill.md). Procedural, not encyclopedic: numbered steps
in running order, a walkable checklist, failure handling, and what evidence to report. 60–150 lines.

Split two things when they have different activation conditions; merge them when they always fire
together. Check `catalog/external-skills.json` first — if a maintained official skill already covers
the capability, reference it there rather than writing a local duplicate.

A registered skill is automatically eligible for decision-engine selection in every role whose
loadout names it, from its canonical `description` and `not_for`. Nothing else to register.

## Adding an external skill or MCP

Verify before you reference. An entry must record source, repository, path, licence, version or
commit, verification date, trust level, whether it ships scripts, whether it uses the network, the
tools it needs, and the fallback for when it is absent.

Nothing is vendored and nothing is fetched at runtime. If a skill ships scripts, read them and say
so in the entry — see the checklist in [docs/security.md](docs/security.md).

Do not add an integration to raise a count. A smaller, well-understood set beats a large one.

## What gets rejected

- A generated file edited by hand.
- A skill or MCP referenced without verifying it exists, and without a licence and a fallback.
- A loadout that grows because a skill is good rather than because the role's work needs it.
- Prose that restates a role's working method inside a skill, or vice versa.
- A claim that something was verified when the check could not run.
