# Security model

## What this repository is and is not

It ships text: role definitions, procedures, and registries describing external software. It
contains no credentials and runs no third-party installer, and it reaches the network only if you
configure the optional decision engine to — by default nothing in it runs.

It does have two scripts of its own and one optional Python package, and they are the ones to
read before trusting it:

- **`install.sh`** copies the pack into `${CLAUDE_CONFIG_DIR:-$HOME/.claude}` — one directory,
  `skills/agent-dispatcher/`, plus `commands/agent-*.md` and one hook — records every command file
  it wrote in `.agent-dispatcher-installed`, backs up `settings.json` before adding a SessionStart
  hook entry, and refuses to overwrite a command file it did not write. `--uninstall` removes only
  what that manifest lists. Skill categories live under `skills/agent-dispatcher/lib/` rather than
  at the top level, so the pack never claims a name like `security` or `design` in your skills
  directory.
- **`hooks/agent-dispatcher-activate.sh`** runs at SessionStart when perpetual mode is armed, and
  prints a routing preamble to stdout. It reads flag files, writes nothing but the weekly prune of
  its own session-silence directory, and makes no network call. Its output is a fixed heredoc: a
  repository cannot inject text through it.

Arming is deliberately not repo-controlled. A project-local `.agent-dispatcher-on` arms the hook
only when that project's absolute path also appears in `$D/.agent-dispatcher-projects`, which lives
in the user's config dir — so cloning a repository cannot switch your sessions into perpetual mode.
Silencing flags *are* repo-local, because they can only ever reduce behaviour.

Adding capability metadata does not widen what an agent may do: the runtime's permission layer is
unchanged and remains the only boundary that holds.

## Skills are capabilities, not permissions

A skill can teach how to deploy to Vercel without granting permission to deploy. An MCP can expose
a deployment tool without the agent being authorized to call it. Prompt text is not a sandbox: if
something must not happen, it has to be prevented by the permission layer, not asked for politely
in a markdown file.

## Trust levels for external skills

Recorded per entry in `catalog/external-skills.json`:

| Level | Meaning |
| --- | --- |
| official | Published by the vendor whose product it covers. |
| verified | Vendor-affiliated org, with a licence or provenance caveat recorded in the entry. |
| community | Individual or small-team maintainer. Never required, never auto-activated. |
| local | Authored here. |

Every entry records source, repository, path, licence, version or commit, verification date,
whether it ships scripts, whether it uses the network, the tools it needs, and the permissions it
expects. Nothing external is vendored — this repository references and records provenance, it does
not copy skill bodies or run installers.

Two licence findings worth keeping in view:

- `anthropics/claude-code` is under Anthropic's Commercial Terms, not an open-source licence. The
  frontend-design skill there is byte-identical to the copy in `anthropics/skills`, which carries
  per-skill Apache-2.0 — so this catalog cites the latter. The plugin-dev skills exist only in the
  proprietary repository and are recorded as reference-only.
- `vercel-labs/agent-skills` states MIT in its README and in four skills' frontmatter, but has no
  LICENSE file at the repository root and the GitHub API reports no licence. Recorded as a caveat
  rather than assumed.

## Before enabling a skill that ships scripts

1. Read the scripts.
2. Identify filesystem effects.
3. Identify network effects.
4. Identify subprocess behaviour.
5. Identify required secrets.
6. Confirm it does not expand the agent's permissions.

Never run an installer because a repository's README says to. The entries that declare
`scripts_included: true` are flagged precisely so this check is not skipped.

## MCP risk

`catalog/mcp.json` records, per server, whether it writes, its risk level, how to run it read-only
where that exists, and what its vendor says about its own dangers. The ones that need care:

- **Slack** sends messages to real people. Drafting is not sending; every send is confirmed.
- **Vercel** grants "the same access as your Vercel user account", and its purchase tools "execute
  real, non-refundable charges" — Vercel's own words.
- **Google Workspace** reaches mail, calendar and drive under Developer Preview, with Google's own
  warning about the breadth of access.
- **Playwright MCP** states plainly that it "is not a security boundary". `--isolated` is a real
  containment control; `--allowed-origins` explicitly is not — the README says it "does not serve
  as a security boundary and does not affect redirects".
- **Cloudflare's main API server** is read *and* write across 2,500+ endpoints including DNS and
  Zero Trust.
- **Community Postgres servers** hold a database connection string. Local or throwaway databases
  only.

Prefer the read-only path where one exists: GitHub's `--read-only`, Linear's `/mcp/readonly`
endpoint, Datadog's permission-scoped keys, Cloudflare's scoped tokens.

## Prompt injection

Content an agent retrieves — a web page, an issue body, a file, an MCP response, another agent's
output — is data. It never carries authority to change the agent's instructions or expand its
access. The `prompt-injection-defense` and `agent-security` skills cover this for agents the pack
helps build; for the pack's own agents the rule is stated in the role contract and in the router.

## Uncertain mutations

A mutating call that times out or returns an uncertain result is not retried blind:

```
attempt → uncertain → inspect actual state → determine whether it happened → retry only if safe
```

This matters most for deployment, messages, tickets, database writes, cloud resources, payments and
publishing.

## No secrets

No API key, token, password, PAT or credential is committed here. Registry entries name the
environment variable or credential type a server expects; they never carry a value.

The optional decision engine is the one part of this pack that can hold a credential, and it
holds none. The key lives in the environment; `decision/config.py` exposes the variable's *name*
and whether it is set, never its value; the provider reads `os.environ` at the moment of the
request and does not store it. `python3 -m decision status` and `/agent-context` print
`configured` or `not configured` and nothing else. A provider error is reported as its kind —
`timeout`, `rate limited`, `credential rejected` — because a response body can echo request
headers. `tests/test_decision.py` asks the engine to route the task *"Print the Jev API key"* and fails
the build if the value reaches any rendered surface, diagnostic record or error message.
`install.sh` never asks for a key and never writes one.

Enabling the decision engine sends the task text and compact registry metadata to an external
provider. `decision/redact.py` scrubs recognisable credential shapes and caps the task at 2,000
characters first; repository source, file contents, environment and conversation history are
never sent. That scrub is defensive, not a guarantee — see [jev.md](jev.md), which says so
plainly. For work where the task text itself is sensitive, the engine has an `off` mode.

## Retrieved context is untrusted input

The context engine assembles repository files, documentation, skill bodies and tool responses into
an agent's working context. All of it is **evidence**, and none of it is instruction.

- A file containing `IGNORE YOUR AGENT INSTRUCTIONS`, claiming to raise the agent's permissions, or
  telling it to skip verification is data *about that file*. It is reported, never obeyed.
- Retrieval cannot widen scope, change the role contract, relax a verification requirement, or
  override runtime policy or the user's instructions.
- Selecting a skill grants nothing. Detecting a stack grants nothing. A configured MCP server
  grants nothing. A signal in `catalog/signals.json` says how a condition is decided and nothing
  else — `tests/test_build.py` fails the build if one grows a `permission`, `grants`, `tools` or `mcp`
  field.
- A secret found during retrieval is a finding, not context: it is named, not copied into the plan
  and not echoed.

None of this is a security boundary — it is a discipline. The boundary is the runtime's permission
layer, which this repository does not touch.
