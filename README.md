# Agent Dispatcher

[![CI](https://github.com/nahid-sparktales/agent-dispatcher/actions/workflows/ci.yml/badge.svg)](https://github.com/nahid-sparktales/agent-dispatcher/actions/workflows/ci.yml)
[![Security](https://github.com/nahid-sparktales/agent-dispatcher/actions/workflows/security.yml/badge.svg)](https://github.com/nahid-sparktales/agent-dispatcher/actions/workflows/security.yml)

**Repository retrieval and context for Claude Code and Codex.**

Agent Dispatcher finds the code a task needs using symbols, source text, code relationships,
and Git history. It assembles relevant source excerpts, pairs the work with specialist
guidance, and makes verification explicit. Use it to explore a repository, debug a failure,
build a feature, or review a change.

<!-- counts:start -->**27 roles · 79 local skills · 31 external skills · 8 recipes · 19 MCP servers · 50 detection signals**<!-- counts:end -->

[Quick start](#quick-start) · [Usage](#everyday-use) · [Catalog](docs/catalog.md) ·
[Documentation](#documentation) · [Changelog](CHANGELOG.md)

## Quick start

You need an installed, authenticated Claude Code or Codex, Git, and Python 3.10+.
The helpers use Python's standard library. Use macOS, Linux, or a Unix environment such as WSL;
native Windows installation is not covered. Normal use needs no additional API key.

### Codex

Run in your terminal:

```bash
git clone https://github.com/nahid-sparktales/agent-dispatcher.git
cd agent-dispatcher
python3 install_codex.py
```

Start a new Codex task in your project and invoke the skill:

```text
$agent-dispatcher Find why the tests are failing, fix the cause, and verify the fix.
```

This installs one skill at `~/.agents/skills/agent-dispatcher/`, with roles and supporting
guides loaded as needed. See [Codex setup](adapters/codex/README.md) for updates and uninstall.

### Claude Code

Run in your terminal:

```bash
claude plugin marketplace add nahid-sparktales/agent-dispatcher
claude plugin install agent-dispatcher@agent-dispatcher
```

Start a new Claude Code session in your project:

```text
/agent-dispatcher:agent-dispatcher Find why the tests are failing, fix the cause, and verify the fix.
```

Prefer a manual install? Follow the [manual setup guide](docs/usage.md#manual-claude-code-installation).
Use one installation method per host to avoid duplicate commands and hooks.

## Everyday use

In Codex, add your request or a control after `$agent-dispatcher`:

```text
$agent-dispatcher Redesign the settings page and check it on mobile.
$agent-dispatcher reviewer Review this change for correctness and missing tests.
$agent-dispatcher debugger Find why checkout fails after login.
```

Claude plugin users use `/agent-dispatcher:agent-dispatcher` for routing and controls, or a
role command such as `/agent-dispatcher:agent-reviewer`. These prefixes follow
[Claude's plugin command names](https://code.claude.com/docs/en/plugins).
Manual installs use `/agent-dispatcher` and `/agent-reviewer`.

| Add after the dispatcher invocation | What it does |
| --- | --- |
| `context explain` | Explain the current role, skills, and context selection. |
| `context build <request>` | Find relevant source passages without executing the request. |
| `doctor` | Check installation health and recommend relevant setup. |
| `inventory setup` | List capabilities with missing setup or unresolved availability. |
| `output verbose` / `output compact` | Change how much activity detail is shown. |
| `status` | Show activation state and current settings. |
| `on here` / `off here` | Enable or silence automatic activation for this project. |

Automatic activation is opt-in. Codex requires you to review and trust its hook through
`/hooks`. A chosen role stays active until you select another or stop routing.
See [all commands and configuration](docs/usage.md).

## What it does

- **Finds relevant code.** Retrieval combines paths, symbols, source text, stack-trace frames,
  code relationships, and Git history. A bounded context packet includes actual source
  excerpts and the reasons each file was selected.
- **Reuses project knowledge.** Source-linked project maps and private caches reuse unchanged
  evidence. An explicitly built deep index adds broader repository coverage, resumable
  onboarding, and incremental refresh.
- **Can use task experience.** Explicitly recorded outcomes, verification receipts, and
  corrections share one private store. Repository memory can also use eligible commit history
  and module summaries, with freshness checks before they influence retrieval.
- **Matches the work to a specialist.** Roles cover engineering, design, testing, research,
  writing, and operations. Small, obvious edits take a direct path; substantial tasks get
  specialist guidance. Independent subtasks can use the host's subagents when authorized.
- **Makes checks visible.** Verification receipts distinguish passed checks, failures, zero
  tests, and work left unverified. Optional change audits report which files actually changed.
  Replies default to short, plain language; saved preferences control presentation.
- **Adapts to available tools.** Inventory and health checks distinguish usable capabilities,
  missing setup, and unknown connections. Referenced external skills and MCP integrations
  have documented fallbacks.

Roles are instructions your coding agent adopts. Claude Code or Codex supplies the model,
tools, and permission controls; Dispatcher respects the host's model and effort settings.
Installing the pack does not connect external services or start background agents.

## Defaults and optional features

Standard retrieval runs locally without model or network calls. Project indexes and memory
stay in private storage outside the working tree. Model-assisted features require your own
configuration and may send task or source information to the provider you select.

| Feature | Default and next step |
| --- | --- |
| [Deep repository index](docs/repository-index.md) | Build explicitly; later context preparation uses the published index automatically. |
| [Task experience](docs/repository-memory.md) | Recording and retrieval enabled; records must be supplied explicitly. No records means no effect. |
| [History and semantic memory](docs/repository-memory.md) | Build explicitly; retrieval starts in shadow mode, reporting candidates without changing rankings. |
| [Model-assisted retrieval](docs/llm-assisted-retrieval.md) | Off; optionally generate file summaries and rerank a bounded candidate set. |
| [Onboarding Explorer](docs/repository-index.md#onboarding-explorer) | Off; optionally use a model to investigate the index and save evidence-backed notes. |
| [Jev decision engine](docs/jev.md) | All scopes off; optionally delegate catalog selection to an external API. |

The [catalog](docs/catalog.md) lists bundled skills and referenced integrations. External
skills and MCP servers are not installed by this pack. Your agent's usage costs still apply;
optional providers have their own access and billing requirements.

## Documentation

| Start here | What you will find |
| --- | --- |
| [Usage and configuration](docs/usage.md) | Commands, output preferences, context controls, activation, and uninstall. |
| [Catalog](docs/catalog.md) | Every role, local skill, workflow recipe, and MCP registry entry. |
| [Repository intelligence](docs/repository-intelligence.md) | How files are found, ranked, and selected for context. |
| [Project intelligence](docs/project-intelligence.md) | Project maps, caching, and context budgets. |
| [Benchmarks](docs/retrieval-benchmark.md) · [End-to-end evaluations](evals/end_to_end/README.md) | Measured results, methodology, and limits. |
| [Architecture](docs/architecture.md) · [Verification](docs/verification.md) · [Security](docs/security.md) | Design, evidence requirements, and trust boundaries. |
| [Changelog](CHANGELOG.md) | Detailed changes and release history. |

## Contributing

Bug reports, routing examples, and focused contributions are welcome. Read
[CONTRIBUTING.md](CONTRIBUTING.md) for canonical sources and generated files, then run:

```bash
python3 build.py
python3 -B -m tests
```

These checks run offline without provider credentials. To extend the pack, see
[adding a role](docs/adding-an-agent.md) or [adding a skill](docs/adding-a-skill.md).
Report vulnerabilities through [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE). See [NOTICE](NOTICE) for role origins, adaptations, and attribution.
Referenced third-party skills retain their own licenses. This is an independent project,
not affiliated with or endorsed by OpenAI, Anthropic, or Locus.
