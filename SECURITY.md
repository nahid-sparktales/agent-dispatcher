# Security

## Reporting a vulnerability

Use this repository's [private vulnerability reporting form](https://github.com/nahid-sparktales/agent-dispatcher/security/advisories/new)
when available. If reporting is unavailable, open an issue requesting a private contact channel
without including vulnerability details, credentials, or reproduction steps. Please do not
disclose anything exploitable in a public issue.

Useful in a report: what an attacker controls, what they gain, and the smallest reproduction.

## What this repository is

Text, build/install/activation helpers, and one optional Python package. It contains no credentials
and runs no third-party installer. Runtime helpers make no network request unless you configure
the optional decision engine described below.

- **`install.sh`** copies the pack into `${CLAUDE_CONFIG_DIR:-$HOME/.claude}` — one directory,
  `skills/agent-dispatcher/`, plus `commands/agent-*.md` and one hook. It records every command
  file it writes, refuses to overwrite one it did not write, backs up `settings.json` before adding
  a `SessionStart` entry, and `--uninstall` removes only what its manifest lists.
  It validates settings structure and manifest paths before changing the installation, rejects
  symlinked installation targets, and preserves unrelated commands and hook registrations.
- **`install_codex.py`** installs one owned skill in `~/.agents/skills/agent-dispatcher/`, with
  supporting guides and the optional decision engine bundled. It refuses unowned or symlinked
  targets and rolls back the skill update if hook registration fails. No hook or activation state
  is created by default. `--with-hook` registers an inert hook; Codex still requires its own trust
  review. Uninstall removes only the owned skill and its exact hook, preserving unrelated entries.
- **`adapters/codex/activate.py`** stores Codex activation and silence scopes in the user-owned
  Codex config directory. Its native `SessionStart` hook reads this state, writes nothing, and
  makes no network request. It ignores repository activation flags and fails closed on malformed
  input. Enabling activation does not bypass Codex's hook trust review or permission controls.
- **`decision/`** is the optional decision engine. It ships **inert**: no decision scope is
  enabled by default, so nothing in it runs, no credential is read and no socket opens. Enabling
  a scope (`AGENT_DISPATCHER_DECISION_SCOPES`) with a credential in `TYPESAFE_API_KEY` sends the
  scrubbed task text and compact registry metadata to TypeSafe over HTTPS — one or two requests
  per task, never repository source, file contents, environment or conversation. The credential
  is read from the environment at request time and is never stored, logged, rendered or written
  to a file. It cannot grant a permission: relevance and authorization are separate layers, and
  the runtime never consults this one. [docs/jev.md](docs/jev.md) has the full account.
- **`repository_intelligence.py`** builds an optional deep index and a task-experience store in
  the same private, owner-only state directory as the project map (never inside a repository).
  Both are derived facts bound to source fingerprints, never source text: a forged file can
  perturb ranking, not inject content, resurrect an excluded path or authorize a read. Its
  Explorer calls a model only when your own settings file enables it, through registered
  read-only operations the coordinator validates; experience is recorded only when a host hands
  over receipts explicitly. Status and dry-run open state read-only and create nothing. See
  [docs/repository-index.md](docs/repository-index.md).
- **`hooks/agent-dispatcher-activate.sh`** runs at `SessionStart` when perpetual mode is armed and
  prints a routing preamble. It reads flag files, writes nothing but a weekly prune of its own
  session-silence directory, makes no network call, and its output is a fixed heredoc — a
  repository cannot inject text through it.

Claude arming is not repo-controlled: a project-local `.agent-dispatcher-on` is honoured only when that
project's absolute path also appears in `~/.claude/.agent-dispatcher-projects`. Silencing flags
*are* repo-local, because they can only reduce behaviour.
Codex uses its separate `${CODEX_HOME:-~/.codex}/agent-dispatcher/state.json` allow-list and
does not read Claude flags. See [Codex setup](adapters/codex/README.md) for its controls.

## The boundary that actually holds

Prompt text is not a sandbox. A skill can teach how to deploy without granting permission to
deploy; an MCP can expose a deployment tool without the agent being authorized to call it. The
runtime's permission layer is unchanged by anything in this repository and remains the only
boundary that holds. If something must not happen, prevent it there.

## Third-party skills

Treated as dependencies and never vendored. `catalog/external-skills.json` records provenance and
trust for each, and flags the ones that ship scripts. Before enabling one of those: read the
scripts, identify filesystem, network and subprocess effects, identify required secrets, and
confirm it does not expand the agent's permissions. Never run an installer because a README says to.

## MCP risk

`catalog/mcp.json` records, per server, whether it writes, its risk level, how to run it read-only
where that exists, and what its vendor says about its own dangers. The ones needing care — Slack
sends messages to real people; Vercel's purchase tools "execute real, non-refundable charges";
Google Workspace reaches mail and drive; Playwright MCP states it "is not a security boundary" —
are documented in [docs/security.md](docs/security.md).

Prefer the read-only path where one exists: GitHub's `--read-only`, Linear's `/mcp/readonly`,
Datadog's permission-scoped keys, Cloudflare's scoped tokens.
