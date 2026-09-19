# MCP servers

19 servers, every one verified against the vendor's own source on 2026-09-19 by two
independent research passes. **This repository installs none of them.** It records what exists,
what each can do, and what an agent should do when one is absent.

Availability is not authorization. A configured server does not widen what an agent may do: the
runtime's permission layer is unchanged, and a mutating call still stops and asks. See
[security.md](security.md).

| Server | Official | Writes | Risk | Read-only path |
| --- | --- | --- | --- | --- |
| `axe-devtools` | yes | yes | medium | Use its scan tools without acting on the remediate tool's  |
| `chrome-devtools` | yes | yes | high | — |
| `cloudflare` | yes | yes | high | No flag. Contain it by granting narrow permissions at the  |
| `context7` | yes | no | low | read-only by nature — its tools are resolve-library-id and |
| `datadog` | yes | yes | high | Permission-scoped: Datadog checks the matching permission  |
| `figma` | yes | yes | medium | Use only the read tools (get_design_context, get_metadata, |
| `github` | yes | yes | medium | --read-only flag; GITHUB_TOOLSETS scopes which of the 22 t |
| `google-workspace` | yes | yes | high | Scope-based: request read-only OAuth scopes. |
| `grafana` | yes | yes | high | Disable the write-capable tool groups; 29+ tools are enabl |
| `linear` | yes | yes | medium | yes — `https://mcp.linear.app/mcp/readonly` |
| `notion` | yes | yes | medium | — |
| `playwright` | yes | yes | high | — |
| `postgres-community` | no | yes | high | --access-mode=restricted. The default is not unrestricted, |
| `postgres-reference` | yes | no | unmaintained | — |
| `sentry` | yes | yes | medium | — |
| `slack` | yes | yes | high | — |
| `supabase` | yes | yes | high | Point it at a local or branch project rather than producti |
| `vercel` | yes | yes | high | — |
| `workspace` | yes | yes | medium | The runtime's permission mode; a read-only role simply doe |

### `axe-devtools` — axe DevTools MCP (Deque)

Automated accessibility scanning with code-level remediation guidance.

- **Source** https://github.com/dequelabs/axe-mcp-server-public
- **Licence** proprietary (stated on the repository) · **Version** 4.0.0
- **Transport** Docker or npm, per Deque's documentation
- **Auth** Deque axe DevTools account
- **Writes** yes · **Risk** medium
- **Read-only** Use its scan tools without acting on the remediate tool's edits automatically.
- **Activate when** Accessibility must be checked and the organization has axe DevTools.
- **When absent** axe-core via the browser or @axe-core/playwright, plus the manual keyboard and screen-reader checks a scanner cannot make.
- **Conditional for** `ui-ux-designer`, `tester`, `reviewer`

> Official Deque server. Its remediate tool produces code changes — review them, do not apply blind. An automated scan catches roughly a third of WCAG issues: it never proves accessibility on its own.

### `chrome-devtools` — Chrome DevTools MCP

Drive Chrome with DevTools access: performance traces, network, console, DOM, plus full interaction.

- **Source** https://github.com/ChromeDevTools/chrome-devtools-mcp
- **Licence** Apache-2.0 · **Version** v1.9.0 (2026-09-08)
- **Transport** Local: npx -y chrome-devtools-mcp@latest
- **Auth** none; a non-isolated profile carries the user's logins
- **Writes** yes · **Risk** high
- **Read-only** None. It clicks, fills, uploads and evaluates scripts.
- **Activate when** The question needs DevTools-grade evidence — a performance trace, detailed network timing — beyond what plain browser control gives.
- **When absent** The playwright MCP or the host's own browser tools.
- **Conditional for** `performance-engineer`, `debugger`, `ui-ux-designer`, `tester`

> Official Google/Chrome. Strongest choice for performance profiling of a real page; overlaps playwright for plain interaction.

### `cloudflare` — Cloudflare MCP servers

Cloudflare account and platform: API/config, docs, observability, Workers builds and bindings, Radar, browser rendering.

- **Source** https://developers.cloudflare.com/agents/model-context-protocol/mcp-servers-for-cloudflare/ (code: https://github.com/cloudflare/mcp-server-cloudflare)
- **Licence** Apache-2.0 (repo); the endpoints are a hosted Cloudflare service · **Version** docs updated 2026-07-28
- **Transport** Remote, one endpoint per server. Main API: https://mcp.cloudflare.com/mcp; docs: https://docs.mcp.cloudflare.com/mcp; observability: https://observability.mcp.cloudflare.com/mcp
- **Auth** OAuth with per-permission consent, or a scoped Cloudflare API token as a bearer header
- **Writes** yes · **Risk** high
- **Read-only** No flag. Contain it by granting narrow permissions at the OAuth screen or minting a read-only API token.
- **Activate when** The project runs on Cloudflare — wrangler.toml, Workers, Cloudflare DNS — and the server is configured.
- **When absent** Read wrangler.toml and CI config from the repository; treat live edge state as unknown.
- **Conditional for** `devops-release`, `api-integration-engineer`, `security-auditor`, `debugger`

> The main API server is read AND write over 2,500+ endpoints including DNS, Workers and Zero Trust. The docs and observability endpoints are the safe ones. Container and Browser Run endpoints spend billable resources.

### `context7` — Context7

Fetch current, version-aware documentation for a library or framework instead of relying on stale model knowledge.

- **Source** https://github.com/upstash/context7
- **Licence** MIT · **Version** @upstash/context7-mcp@4.1.1 (2026-09-14)
- **Transport** remote https://mcp.context7.com/mcp; npm @upstash/context7-mcp; CLI ctx7
- **Auth** API key for higher rate limits; usable without one
- **Writes** no · **Risk** low
- **Read-only** read-only by nature — its tools are resolve-library-id and query-docs
- **Activate when** A framework or library API matters and its current behaviour is not knowable from the repository.
- **When absent** Official documentation via the browser; cite what was read.
- **Recommended for** `implementer`, `researcher`, `api-integration-engineer`, `ai-agent-engineer`
- **Conditional for** `planner`, `architect`, `database-engineer`, `devops-release`, `documentation-writer`, `data-engineer`

> Do not reach for it to answer questions the repository already answers. Library entries are community-contributed, so treat a returned snippet as evidence to check, not as authority.

### `datadog` — Datadog MCP

Query metrics, logs, traces, monitors and incidents.

- **Source** https://docs.datadoghq.com/mcp_server/ (examples: https://github.com/datadog-labs/mcp-server)
- **Licence** MIT on the datadog-labs examples repo; the server itself is Datadog-hosted · **Version** managed service; no version shown
- **Transport** Remote https://mcp.datadoghq.com/v1/mcp
- **Auth** Datadog OAuth / API credentials
- **Writes** yes · **Risk** high
- **Read-only** Permission-scoped: Datadog checks the matching permission (e.g. monitors_write) on each tool call, so a read-only key yields a read-only server.
- **Activate when** The project's telemetry is in Datadog and the question needs production evidence.
- **When absent** Whatever telemetry is reachable locally; say what could not be observed.
- **Conditional for** `debugger`, `incident-responder`, `devops-release`, `performance-engineer`, `security-auditor`

> Datadog does publish an official managed MCP server, contrary to a common assumption. The public repo under datadog-labs holds docs and examples, not the server.

### `figma` — Figma MCP Server

Inspect design files, components, variables and design tokens, and compare an implementation against the design.

- **Source** https://developers.figma.com/docs/figma-mcp-server/
- **Licence** proprietary — hosted service, no public repository
- **Transport** remote https://mcp.figma.com/mcp; desktop http://127.0.0.1:3845/mcp
- **Auth** Figma account; the remote server is available on all seats and plans, the desktop server needs a Dev or Full seat on a paid plan
- **Writes** yes · **Risk** medium
- **Read-only** Use only the read tools (get_design_context, get_metadata, get_screenshot, get_variable_defs and the rest); the write and Weave tool groups change or generate canvas content.
- **Activate when** The task references a Figma file or a design system held in Figma, and the server is configured.
- **When absent** Work from the repository's own design tokens, existing components and screenshots. Never invent what a design says.
- **Conditional for** `ui-ux-designer`, `product-manager`, `implementer`

> Three tool groups: read, write, and Weave (which runs tools and uploads assets). Figma for Government supports only the desktop server — the remote one is not available there, and MCP is outside Figma's FedRAMP audit scope.

### `github` — GitHub MCP Server

Repositories, files, issues, pull requests, commits, Actions and code search as an authoritative source of repository state.

- **Source** https://github.com/github/github-mcp-server
- **Licence** MIT · **Version** v1.12.2 (2026-09-16)
- **Transport** remote https://api.githubcopilot.com/mcp/ (OAuth or PAT); local ghcr.io/github/github-mcp-server via Docker
- **Auth** GITHUB_PERSONAL_ACCESS_TOKEN, or OAuth against the remote endpoint
- **Writes** yes · **Risk** medium
- **Read-only** --read-only flag; GITHUB_TOOLSETS scopes which of the 22 toolsets are exposed at all
- **Activate when** The task needs repository state that is not on local disk — issues, PRs, CI runs, another repo.
- **When absent** git and the gh CLI against the local checkout; say which repository facts could not be confirmed.
- **Recommended for** `explorer`, `implementer`, `reviewer`, `tester`, `security-auditor`, `devops-release`, `api-integration-engineer`, `ai-agent-engineer`, `documentation-writer`, `version-control`, `dispatcher`
- **Conditional for** `planner`, `researcher`, `architect`, `debugger`, `performance-engineer`, `refactoring-migration-specialist`, `product-manager`

> Prefer --read-only for review and audit roles. Writing an issue, a PR or a comment is an outward-facing action and needs its own confirmation.

### `google-workspace` — Google Workspace MCP servers

Gmail, Calendar, Drive, Docs, Sheets, Slides, Chat and People as first-party MCP endpoints.

- **Source** https://developers.google.com/workspace/guides/configure-mcp-servers
- **Licence** not published — hosted Google services · **Version** Developer Preview
- **Transport** One remote endpoint per product, e.g. Gmail https://gmailmcp.googleapis.com/mcp/v1, Drive https://drivemcp.googleapis.com/mcp/v1
- **Auth** Google OAuth with per-product scopes
- **Writes** yes · **Risk** high
- **Read-only** Scope-based: request read-only OAuth scopes.
- **Activate when** The user has connected the specific product and the task needs it.
- **When absent** Ask the user for the content; never guess at the contents of a mailbox or calendar.
- **Conditional for** `automation-operations`, `product-manager`, `growth-marketing-strategist`

> Google now publishes first-party Workspace MCP servers (Developer Preview) — community servers are no longer the only option and should not be used in preference. Google's own docs warn that these clients have powerful access and should be treated accordingly. Sending mail or creating events is outward-facing: confirm each one.

### `grafana` — Grafana MCP

Query Prometheus/Loki, read dashboards and alerts, inspect incidents and profiles.

- **Source** https://github.com/grafana/mcp-grafana
- **Licence** Apache-2.0 · **Version** v1.5.1 (2026-09-17)
- **Transport** Local: uvx mcp-grafana, docker grafana/mcp-grafana, or go install
- **Auth** Grafana service account token
- **Writes** yes · **Risk** high
- **Read-only** Disable the write-capable tool groups; 29+ tools are enabled by default.
- **Activate when** The project's observability lives in Grafana and a question needs real telemetry.
- **When absent** Logs and metrics reachable from the workspace; state what was not observed.
- **Conditional for** `debugger`, `incident-responder`, `devops-release`, `performance-engineer`

> Default tool set can create and update dashboards, alert rules, annotations and incidents — that is production observability config, not just reads.

### `linear` — Linear MCP

Find, create and update issues, projects and comments.

- **Source** https://linear.app/docs/mcp
- **Licence** not published — hosted service · **Version** actively maintained
- **Transport** Remote https://mcp.linear.app/mcp — read-only variant https://mcp.linear.app/mcp/readonly
- **Auth** Linear OAuth
- **Writes** yes · **Risk** medium
- **Read-only** A purpose-built read-only endpoint: https://mcp.linear.app/mcp/readonly — use it unless the task genuinely requires filing or editing issues.
- **Activate when** The team tracks work in Linear and the task needs issue context.
- **When absent** Work from what the user pasted or from the repository's own issue references.
- **Conditional for** `product-manager`, `automation-operations`, `dispatcher`, `planner`

> The only server in this catalog shipping a dedicated read-only endpoint. Creating or updating an issue is outward-facing and needs confirmation.

### `notion` — Notion MCP

Search, read, create and update Notion pages and databases.

- **Source** https://developers.notion.com/docs/get-started-with-mcp (self-host: https://github.com/makenotion/notion-mcp-server)
- **Licence** hosted service not published; the self-hosted server is MIT · **Version** self-hosted v2.1.0
- **Transport** Remote https://mcp.notion.com/mcp; or local npx -y @notionhq/notion-mcp-server
- **Auth** Notion OAuth, or NOTION_TOKEN for the self-hosted server
- **Writes** yes · **Risk** medium
- **Read-only** None. Restrict by sharing only the pages the integration needs.
- **Activate when** The team's docs or specs live in Notion and the task needs them.
- **When absent** Ask for the content, or work from the repository's own docs.
- **Conditional for** `product-manager`, `documentation-writer`, `automation-operations`, `growth-marketing-strategist`

> Write tools create, update, move and duplicate pages and databases — shared workspace content. Some tools are plan-gated. Self-hosted v2.0.0 was a breaking change: database tools became data-source tools.

### `playwright` — Playwright MCP

Drive a real browser: navigate, screenshot, interact, emulate viewports, read console and network.

- **Source** https://github.com/microsoft/playwright-mcp
- **Licence** Apache-2.0 · **Version** v0.0.82 (2026-09-18)
- **Transport** npx @playwright/mcp@latest
- **Auth** none by default; a persistent profile carries whatever the browser is logged into
- **Writes** yes · **Risk** high
- **Read-only** None. --isolated gives an in-memory profile and is the real containment control.
- **Activate when** Rendered behaviour has to be observed rather than inferred — UI work, a browser-only bug, Core Web Vitals.
- **When absent** The host's own browser tools, or a local Playwright script. With neither, report that rendered verification was unavailable and never describe the UI as verified.
- **Recommended for** `ui-ux-designer`, `tester`
- **Conditional for** `implementer`, `debugger`, `performance-engineer`, `reviewer`

> Its README states plainly: "Playwright MCP is not a security boundary." --allowed-origins is NOT a security control either — the README says it "does not serve as a security boundary and does not affect redirects". A non-isolated profile can act as the logged-in user on any site.

### `postgres-community` — Postgres MCP (community alternatives)

Generic Postgres access where no vendor server applies.

- **Source** https://github.com/crystaldba/postgres-mcp
- **Licence** MIT · **Version** main @ 2026-08-16
- **Transport** Local: pipx install postgres-mcp / uvx postgres-mcp / docker crystaldba/postgres-mcp
- **Auth** a Postgres connection string
- **Writes** yes · **Risk** high
- **Read-only** --access-mode=restricted. The default is not unrestricted, but confirm the mode before pointing it anywhere real.
- **Activate when** Only with the user's explicit say-so, against a local or throwaway database.
- **When absent** psql through the workspace against a local database, and the repository's migrations as the schema source of truth.
- **Conditional for** `database-engineer`, `data-engineer`, `data-analyst`, `debugger`, `performance-engineer`

> NOT official — published by Crystal DBA, an independent company. It is the most-cited successor to the archived reference server, but it is a third party holding a database connection string. Never point it at production. For Neon, Neon publishes its own official server (https://neon.com/docs/ai/neon-mcp-server), which its own docs warn grants broad database management.

### `postgres-reference` — Reference Postgres MCP server (archived)

Recorded so nobody adds it: the Model Context Protocol reference Postgres server is no longer maintained.

- **Source** https://github.com/modelcontextprotocol/servers-archived/tree/main/src/postgres
- **Licence** MIT · **Version** archived; last push 2025-05-28
- **Transport** n/a — do not adopt
- **Auth** n/a
- **Writes** no · **Risk** unmaintained
- **Read-only** n/a
- **Activate when** never
- **When absent** For Supabase projects use the supabase entry. Otherwise use psql and the project's own migration tooling through the workspace, and keep production credentials out of the agent's reach.

> It was removed from modelcontextprotocol/servers and moved to servers-archived. Any guide still recommending it is stale.

### `sentry` — Sentry MCP

Inspect issues, events, traces and releases; triage.

- **Source** https://mcp.sentry.dev/ (code: https://github.com/getsentry/sentry-mcp)
- **Licence** FSL-1.1-Apache-2.0 (Functional Source License, Apache-2.0 future licence) · **Version** 0.39.0
- **Transport** Remote https://mcp.sentry.dev/mcp, optionally scoped .../mcp/{org}/{project}
- **Auth** Sentry OAuth; the documented scopes include write scopes (project:write, team:write, event:write)
- **Writes** yes · **Risk** medium
- **Read-only** None published. Scope the endpoint to one org/project and keep to inspection tools.
- **Activate when** The project uses Sentry and an error or regression needs real production evidence.
- **When absent** Application logs through the workspace; say that production error data was not available.
- **Conditional for** `debugger`, `incident-responder`, `devops-release`, `performance-engineer`

> Sentry describes it as "primarily designed for human-in-the-loop coding agents". docs.sentry.io/product/sentry-mcp/ now redirects to mcp.sentry.dev.

### `slack` — Slack MCP

Read channels and threads, search history, and send messages.

- **Source** https://docs.slack.dev/ai/slack-mcp-server/
- **Licence** not published — hosted service · **Version** GA since 2026-02-17
- **Transport** Remote https://mcp.slack.com/mcp
- **Auth** Slack OAuth; workspace admins approve MCP client integrations
- **Writes** yes · **Risk** high
- **Read-only** None. Keep to search and read tools.
- **Activate when** The task genuinely needs Slack content, and the workspace admin has approved the integration.
- **When absent** Ask the user to paste the thread.
- **Conditional for** `automation-operations`, `incident-responder`, `product-manager`

> The highest-consequence server here: it sends messages to real people, creates canvases and uploads files. Every send is an outward-facing action requiring explicit per-message confirmation — drafting is not sending.

### `supabase` — Supabase MCP

Inspect and operate a Supabase project — schema, SQL, edge functions, logs, advisors.

- **Source** https://github.com/supabase/mcp
- **Licence** Apache-2.0 · **Version** mcp-server-supabase-v0.13.0 (2026-09-17)
- **Transport** hosted https://mcp.supabase.com/mcp; local via the Supabase CLI at http://localhost:54321/mcp
- **Auth** Supabase personal access token or project credentials
- **Writes** yes · **Risk** high
- **Read-only** Point it at a local or branch project rather than production, and prefer its read-only mode where the deployment offers one.
- **Activate when** The project actually uses Supabase — supabase/ directory, a Supabase client dependency, or the user says so.
- **When absent** Read migrations and schema files from the repository; state that live database state was not inspected.
- **Conditional for** `database-engineer`, `api-integration-engineer`, `implementer`, `architect`, `debugger`, `data-analyst`, `data-engineer`

> The repository was renamed from supabase-community/supabase-mcp to supabase/mcp; the old URL still redirects. Never assume production access — apply migrations to a branch or local project first.

### `vercel` — Vercel MCP

Inspect Vercel projects, deployments, logs and configuration, and run Vercel CLI operations.

- **Source** https://vercel.com/docs/mcp/vercel-mcp
- **Licence** proprietary — hosted service, no public repository · **Version** Beta; docs last updated 2026-09-15
- **Transport** remote https://mcp.vercel.com
- **Auth** OAuth against the user's Vercel account
- **Writes** yes · **Risk** high
- **Read-only** none published — scope by using only the inspection tools
- **Activate when** The project deploys to Vercel — vercel.json, a linked project, or the user says so.
- **When absent** Read vercel.json and CI configuration from the repository; treat deployment state as unknown.
- **Conditional for** `devops-release`, `implementer`, `debugger`, `performance-engineer`

> Vercel's own documentation says connecting "grants the AI system you're using the same access as your Vercel user account", and its purchase tools "execute real, non-refundable charges". Deployment and purchase are separately authorized actions — preparing a deployment is not permission to run one.

### `workspace` — Workspace files and terminal

Read, search and edit files in the project, and run commands.

- **Source** Built into the host runtime (Claude Code: Read/Write/Edit/Grep/Glob/Bash). Not an MCP server and nothing to install.
- **Licence** n/a
- **Transport** native
- **Auth** none — governed by the runtime's permission mode
- **Writes** yes · **Risk** medium
- **Read-only** The runtime's permission mode; a read-only role simply does not call the mutating tools.
- **Activate when** always available
- **When absent** none needed
- **Recommended for** `dispatcher`, `explorer`, `implementer`, `tester`, `reviewer`, `debugger`, `refactoring-migration-specialist`, `version-control`, `documentation-writer`, `data-engineer`

> Listed so loadouts can name it explicitly. It is the baseline every other entry is measured against.
