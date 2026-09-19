# Security

## Reporting a vulnerability

Open a private security advisory through GitHub's **Security → Report a vulnerability** on this
repository. Please do not open a public issue for anything exploitable.

Useful in a report: what an attacker controls, what they gain, and the smallest reproduction.

## What this repository is

Text and two scripts of its own. It contains no credentials, fetches nothing at runtime, and runs
no third-party installer.

- **`install.sh`** copies the pack into `${CLAUDE_CONFIG_DIR:-$HOME/.claude}` — one directory,
  `skills/agent-dispatcher/`, plus `commands/agent-*.md` and one hook. It records every command
  file it writes, refuses to overwrite one it did not write, backs up `settings.json` before adding
  a `SessionStart` entry, and `--uninstall` removes only what its manifest lists.
- **`hooks/agent-dispatcher-activate.sh`** runs at `SessionStart` when perpetual mode is armed and
  prints a routing preamble. It reads flag files, writes nothing but a weekly prune of its own
  session-silence directory, makes no network call, and its output is a fixed heredoc — a
  repository cannot inject text through it.

Arming is not repo-controlled: a project-local `.agent-dispatcher-on` is honoured only when that
project's absolute path also appears in `~/.claude/.agent-dispatcher-projects`. Silencing flags
*are* repo-local, because they can only reduce behaviour.

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
