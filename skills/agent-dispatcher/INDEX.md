# Skill index

Look up the ids your role's loadout names, then read those skills. A local id is its
own directory name, so `**/<id>/SKILL.md` finds it in either layout — the paths below
are repo-relative, and an install puts the same tree under the pack's `lib/`.

Two uses, and only two. **Resolve** an id a loadout named. **Match** a request against
the `signals` line when you need a capability your loadout does not already name, or
when the skill it named is not installed — the capability map at the end says which
ids are interchangeable. Not for browsing: normally zero to two guides load initially, and a
skill selected because it appeared in this list is the failure the whole layer exists
to prevent.

Each skill's own `description` carries when it fires and what it is not for; read it
when two look close. A `+` marks a verification skill: its job is evidence, not work.

## design

- `accessibility` — UI is being built, changed or repaired and it has to be operable by keyboard and assistive technology — including turning an audit finding into an actual code change. · `skills/design/accessibility/SKILL.md`
  signals: screen reader, keyboard navigation, aria label, make it accessible, focus trap, alt text, a11y fix
- `accessibility-verification`+ — Someone is about to claim a screen or flow is accessible, keyboard-operable, screen-reader usable or WCAG-conformant, or an accessibility fix needs re-checking. · `skills/design/accessibility-verification/SKILL.md`
  signals: is this accessible, verify accessibility, wcag compliant, accessibility audit, axe scan, accessibility sign off
- `design-systems` — The project already has design tokens, a component library or a shared theme, and UI is being added or changed inside it. · `skills/design/design-systems/SKILL.md`
  signals: design tokens, component library, our design system, new button variant, theme tokens, reuse existing component
- `design-to-code` — A design, mockup, Figma frame or screenshot is the source for a UI change, or an existing implementation is being compared against one. · `skills/design/design-to-code/SKILL.md`
  signals: figma, build this mockup, screenshot to code, match the design, implement this design, pixel perfect, design handoff
- `frontend-design` — A new or reshaped UI surface needs a visual direction decided — hierarchy, type, colour, spacing, density — and no design system already decides it. · `skills/design/frontend-design/SKILL.md`
  signals: looks generic, feels templated, visual direction, make it look good, style from scratch, new landing page
- `motion-design` — Transitions, animated state changes, gesture movement or loading indicators are being added, tuned or reviewed, or an interface reads as janky or sluggish. · `skills/design/motion-design/SKILL.md`
  signals: animation, transition, feels janky, hover effect, loading spinner, reduced motion
- `responsive-design` — A layout has to hold across viewport widths — building it, repairing an overflow or collapse at some size, or filling in the sizes a single-width design never specified. · `skills/design/responsive-design/SKILL.md`
  signals: mobile layout, breakpoint, overflows on mobile, responsive, media query, doesnt fit on phone
- `ui-audit` — An interface already exists and someone needs to know what is wrong with it, ranked and concrete enough to act on. · `skills/design/ui-audit/SKILL.md`
  signals: review this screen, critique this ui, feels off, design feedback, usability issues, ux review
- `ux-writing` — Interface strings are being written, reviewed or repaired — labels, errors, empty states, confirmations, form hints — or a control's wording is causing hesitation. · `skills/design/ux-writing/SKILL.md`
  signals: error message, button label, empty state copy, microcopy, confirmation wording, tooltip text

## frontend

- `component-architecture` — A component is being added, has grown props or responsibilities, or a structure is under review for whether it will hold. · `skills/frontend/component-architecture/SKILL.md`
  signals: split this component, too many props, where should state live, prop drilling, component is huge, lift state up, restructure this component
- `frontend-performance` — A page is reported slow, a Core Web Vital or bundle size is named, or a change is about to be described as a performance improvement. · `skills/frontend/frontend-performance/SKILL.md`
  signals: page is slow, lcp, bundle size, lighthouse score, core web vitals, layout shift, slow first load
- `shadcn-ui` — Adding, customizing or debugging a shadcn/ui component in a repo with components.json and a vendored UI directory. · `skills/frontend/shadcn-ui/SKILL.md`
  signals: shadcn, radix, shadcn component, aschild, vendored ui folder, shadcn cli overwrote
- `stack-detection` — You are about to work in a frontend repo whose stack you have not yet confirmed this session, or about to load framework-specific guidance. · `skills/frontend/stack-detection/SKILL.md`
  signals: what stack, which framework, unfamiliar repo, package manager, project conventions, new codebase
- `tailwind` — Writing or editing Tailwind utility classes in a project that already uses Tailwind. · `skills/frontend/tailwind/SKILL.md`
  signals: tailwind, utility classes, arbitrary value, class conflict, dark mode classes, tailwind config, cn helper
- `visual-verification`+ — A change affects appearance and is about to be called done, or a screenshot-comparison result is about to be trusted as proof. · `skills/frontend/visual-verification/SKILL.md`
  signals: visual regression, screenshot comparison, across viewports, light and dark, baseline screenshots, still looks correct, every breakpoint

## backend

- `api-contract-verification`+ — An endpoint, API client or third-party integration is about to be reported as working, or someone asks whether an integration is actually verified. · `skills/backend/api-contract-verification/SKILL.md`
  signals: verify the integration, does this endpoint work, contract test, hit the real api, confirm it actually works, check someone elses integration
- `api-design` — An HTTP endpoint is being added or reshaped, a response or error shape has to be decided, or a change to a published API has to be judged for breakage. · `skills/backend/api-design/SKILL.md`
  signals: new endpoint, rest api design, status codes, error response shape, pagination, openapi spec, breaking change for consumers
- `authentication` — A credential is issued, accepted, refreshed or revoked — login, logout, sessions, tokens, API keys, or an OAuth/OIDC integration. · `skills/backend/authentication/SKILL.md`
  signals: add login, jwt token, session cookie, oauth sign in, refresh token, who is the user, api keys
- `authorization` — A rule of the form 'only X may do Y to Z' is added, changed or doubted — roles, permissions, per-owner or per-tenant scoping, admin paths. · `skills/backend/authorization/SKILL.md`
  signals: roles and permissions, admin only, rbac, per tenant scoping, restrict access, permission check
- `background-jobs` — Work is being moved off a request path onto a queue or scheduler, or a job ran twice, never ran, ran out of order, or is stuck retrying. · `skills/backend/background-jobs/SKILL.md`
  signals: background job, queue worker, cron job, job ran twice, stuck in retry, move off request path, dead letter queue
- `caching` — A cache is about to be added to a read path, or existing cached data is stale, leaking across users, or being blamed for a bug. · `skills/backend/caching/SKILL.md`
  signals: add caching, redis cache, stale data, cache invalidation, ttl, cdn caching
- `idempotency-and-retries` — An operation with an external side effect has to survive being repeated, a caller needs a retry policy, or duplicate effects have appeared and must be prevented. · `skills/backend/idempotency-and-retries/SKILL.md`
  signals: charged twice, idempotency key, safe to retry, duplicate side effects, exponential backoff, timed out but maybe succeeded
- `webhooks` — A webhook endpoint is being built, integrated or debugged, or the service has to deliver events to external consumers. · `skills/backend/webhooks/SKILL.md`
  signals: webhook endpoint, stripe webhook, signature verification, callback url, provider events, notify other services, webhook fired twice

## database

- `data-integrity` — A rule about what must always be true of the data needs to be enforced in a live schema, or an invariant that was enforced has drifted. · `skills/database/data-integrity/SKILL.md`
  signals: data looks wrong, orphaned rows, duplicate records, reconciliation query, enforce this rule, inconsistent data, detect drift
- `data-pipelines` — A batch or streaming pipeline, scheduled transform or ingestion job is being built, repaired or backfilled, or a run dropped, duplicated or reshaped rows. · `skills/database/data-pipelines/SKILL.md`
  signals: etl job, pipeline failed, backfill, rerun duplicated rows, ingestion job, late events, scheduled transform
- `data-quality` — Checks on a dataset are being written or reviewed, a wrong value reached a consumer with nothing catching it, or an existing check is noisy enough to be ignored. · `skills/database/data-quality/SKILL.md`
  signals: data quality checks, stale data, freshness check, wrong number shipped, noisy alerts, row count dropped, dbt tests
- `database-migration-verification`+ — A migration has been applied to some environment and someone is about to report it as working, or that claim is being reviewed. · `skills/database/database-migration-verification/SKILL.md`
  signals: did the migration work, verify the migration, migration already ran, confirm backfill completed, migration succeeded, check before signing off
- `migrations` — A schema or data migration is being written, reviewed or sequenced against a database that holds real data and has live readers. · `skills/database/migrations/SKILL.md`
  signals: write a migration, zero downtime migration, add a column safely, drop a column, rename column, rollback plan, alter table lock
- `postgres` — The project runs on Postgres and the decision depends on engine behaviour — a column type, an index kind, a plan to read, an isolation level, DDL lock behaviour, or a row-level security policy. · `skills/database/postgres/SKILL.md`
  signals: postgres, row level security, rls policy, isolation level, jsonb, which index type, supabase database
- `query-optimization` — A specific statement is slow and the database is the suspect, a query plan needs interpreting, or an index is being proposed without evidence. · `skills/database/query-optimization/SKILL.md`
  signals: slow query, explain plan, should i add an index, query times out, endpoint is slow, report takes forever
- `schema-design` — New tables are being designed, ORM models or migration DDL are under review, or a defect traces back to the data model permitting a state that should be impossible. · `skills/database/schema-design/SKILL.md`
  signals: design the tables, data model, new table, normalize, foreign key, orm models, nullable column

## ai

- `agent-design` — An agent or subagent is being scoped, granted tools, or reviewed after looping, over-reaching or reporting work it did not do. · `skills/ai/agent-design/SKILL.md`
  signals: build an agent, subagent, agent keeps looping, agent does too much, agent tool permissions, multi agent system
- `agent-evals`+ — A prompt, model, tool definition or retrieval change is about to be called an improvement, agent behaviour must not silently regress, or a production failure needs to become a case that cannot come back. · `skills/ai/agent-evals/SKILL.md`
  signals: evals, eval suite, did this improve, seems better, agent regression, llm as judge
- `context-engineering` — A prompt, agent or session loads substantial material, quality decays as context grows, or context has to be trimmed, summarized or split between inlining and retrieval. · `skills/ai/context-engineering/SKILL.md`
  signals: context window, too much context, running out of context, context rot, compaction, inline or retrieve
- `llm-observability` — An agent fails in ways that will not reproduce, cost or latency is unaccounted for, or failure modes must be found before evals can be written. · `skills/ai/llm-observability/SKILL.md`
  signals: tracing, cannot reproduce, sometimes fails, where cost is going, slow agent runs, instrument llm calls
- `mcp-design` — An MCP server is being written, an internal system is being wrapped as one, or a third-party server is being assessed before it is wired into a project. · `skills/ai/mcp-design/SKILL.md`
  signals: mcp server, build an mcp, wrap api as mcp, mcp transport, third party mcp, mcp credentials
- `memory-design` — An agent must carry facts, preferences or decisions past the current context, or an existing memory store has become noisy, contradictory or wrongly scoped. · `skills/ai/memory-design/SKILL.md`
  signals: agent forgets, remember across sessions, persistent memory, stale memories, memory leaking between users, store user preferences
- `model-routing` — More than one model is in play and a call has to be assigned to one, or cost, latency or a silently firing fallback has become a problem. · `skills/ai/model-routing/SKILL.md`
  signals: which model to use, cheaper model, haiku vs sonnet, model fallback, cut inference cost
- `prompt-engineering` — A prompt is being written or patched, its output is inconsistent or the wrong shape, a model version changed, or someone has declared a prompt improved. · `skills/ai/prompt-engineering/SKILL.md`
  signals: write a prompt, improve this prompt, system prompt, model ignores instructions, inconsistent output, few shot examples
- `prompt-injection-defense` — An agent ingests content it did not author — retrieval, browsing, email, files, MCP tool results, subagent output — and also holds tools that can act. · `skills/ai/prompt-injection-defense/SKILL.md`
  signals: prompt injection, jailbreak, untrusted content, agent reads web pages, data exfiltration, is my agent safe
- `retrieval-rag` — A retrieval-backed system returns wrong or thin answers, or an index is being designed, chunked, embedded or rebuilt. · `skills/ai/retrieval-rag/SKILL.md`
  signals: rag, chunking, embeddings, vector search, retrieval misses, hallucinating from docs
- `structured-output` — A model's output feeds code rather than a human — extraction, classification, routing, scoring — or parsing keeps failing, fields arrive invented, or a schema is being designed for a model to fill. · `skills/ai/structured-output/SKILL.md`
  signals: json output, invalid json, parsing fails, json schema, extract fields, classify into categories
- `tool-design` — A tool or function an LLM calls is being added or reshaped, or an agent is selecting the wrong tool, passing malformed arguments, looping, or stalling after a call. · `skills/ai/tool-design/SKILL.md`
  signals: tool description, agent picks wrong tool, malformed arguments, function calling, too many tools, tool error messages

## quality

- `browser-verification`+ — A change touches rendered UI and someone is about to claim it works, or you are asked whether a screen actually functions. · `skills/quality/browser-verification/SKILL.md`
  signals: check in the browser, does it render, blank screen, console errors, screenshot the page, verify the ui, check on mobile
- `e2e-testing` — An automated end-to-end suite is being created, extended, triaged for flake, or pruned, or a case has to be placed at or below this level. · `skills/quality/e2e-testing/SKILL.md`
  signals: e2e tests, playwright suite, cypress, flaky specs, end to end, intermittently red, user journey test
- `performance-profiling` — Something is slow, or an optimization is about to be written from a hunch rather than from a measurement. · `skills/quality/performance-profiling/SKILL.md`
  signals: its slow, profile this, p95 latency, bottleneck, speed this up, high memory usage, optimize performance
- `regression-testing` — A bug has just been fixed, or keeps coming back, and the fix needs a test that is proven to fail without it. · `skills/quality/regression-testing/SKILL.md`
  signals: regression test, test for the fix, bug came back, keeps regressing, stays fixed, cover this defect
- `systematic-debugging` — Something is broken, the cause is not yet known, and someone is about to start editing code to find out. · `skills/quality/systematic-debugging/SKILL.md`
  signals: bug, crash, why is this failing, intermittent failure, unexpected behaviour, still broken, root cause
- `test-design` — Unit or integration tests are being written or repaired — new coverage, pinning a reported bug, or a suite that stays green while the behaviour is wrong. · `skills/quality/test-design/SKILL.md`
  signals: write unit tests, integration tests, add tests, mock this, green but broken, test this function
- `test-strategy` — Coverage has to be planned or defended — before writing a batch of tests, when a suite is slow and nobody can say what it buys, or after a bug escaped and nothing caught it. · `skills/quality/test-strategy/SKILL.md`
  signals: test plan, what should we test, coverage gaps, testing approach, tests missed it, how much testing

## security

- `agent-security` — An agent or subagent is being granted tools, credentials or MCP access, is about to reach a shared or production system, or acted beyond what the requester could have done. · `skills/security/agent-security/SKILL.md`
  signals: agent permissions, mcp server access, subagent tools, agent credentials, tool approval, agent went rogue, give agent access
- `auth-security` — An existing auth path is reviewed, changed or doubted — sessions, tokens, reset and invite flows, impersonation, role elevation, MFA — or someone reports reaching another account's data. · `skills/security/auth-security/SKILL.md`
  signals: account takeover, another users data, session hijacking, password reset flow, mfa bypass, jwt verification, privilege escalation
- `dependency-security` — An advisory or audit finding needs judging, a dependency is being added or bumped, a lockfile diff needs review, or someone asks whether a named CVE affects this project. · `skills/security/dependency-security/SKILL.md`
  signals: cve, npm audit, dependabot alert, vulnerable package, lockfile review, bump dependency, does this affect us
- `owasp-web` — Web code that takes requests, builds queries, renders output, fetches URLs, deserializes data, handles sessions or accepts files is being written or reviewed, or an app needs a sweep for the recurring vulnerability classes. · `skills/security/owasp-web/SKILL.md`
  signals: sql injection, xss, ssrf, mass assignment, insecure deserialization, common vulnerabilities, unsafe input
- `secrets-management` — A credential is added, moved, shared or due for rotation, or one has turned up in code, history, logs or a client bundle. · `skills/security/secrets-management/SKILL.md`
  signals: hardcoded api key, secret committed, rotate credentials, leaked token, key in logs, env file, secret in bundle
- `secure-code-review` — A pull request, feature or repository needs a security read before shipping — especially anything touching auth, money, tenancy, uploads, deserialization or secrets — or someone reports reaching data they should not have. · `skills/security/secure-code-review/SKILL.md`
  signals: security review, review this pr, security pass, before we ship, audit this change, look for security bugs
- `threat-modeling` — A system's shape is being designed or changed — new service, integration, tenancy model, uploads, payments or auth — and someone needs to know which few things are actually worth defending. · `skills/security/threat-modeling/SKILL.md`
  signals: threat model, is this design safe, trust boundaries, new integration, what could go wrong, before we build

## devops

- `ci-cd` — A delivery pipeline is being designed or restructured, something broken reached an environment through a passing pipeline, or a stage is claiming more than it actually ran. · `skills/devops/ci-cd/SKILL.md`
  signals: build pipeline, pipeline stages, what blocks merge, merge gate, green build shipped broken, restructure our ci, delivery pipeline
- `deployment` — A change is going to an environment other people use, or the path that takes it there is being built or changed. · `skills/devops/deployment/SKILL.md`
  signals: deploy to production, ship it, release plan, rollout strategy, canary release, blue green deploy, how do we deploy
- `docker` — A Dockerfile is being written, changed or reviewed, an image build is slow, bloated or non-deterministic, or configuration and secrets need a route into a container. · `skills/devops/docker/SKILL.md`
  signals: dockerfile, container image, image is huge, docker build slow, multi stage build, containerize this app
- `github-actions` — A GitHub Actions workflow is being added, changed or reviewed, or CI is slow, flaky, or reporting green when it should be red. · `skills/devops/github-actions/SKILL.md`
  signals: github actions, workflow yaml, flaky ci, ci takes forever, actions secrets, ci passed but broken, cache in ci
- `incident-response` — Production is failing or degraded right now and stopping the ongoing harm matters more than a complete causal explanation. · `skills/devops/incident-response/SKILL.md`
  signals: production is down, site is down, outage right now, users are affected, prod degraded, got paged, everything is 500ing
- `observability` — A service or a new critical path is going to production, an incident ended with a question the data could not answer, or a dependency, queue or job is being added whose failure would otherwise be silent. · `skills/devops/observability/SKILL.md`
  signals: add monitoring, metrics and alerts, no visibility, we had no data, structured logging, tracing setup, alert on errors
- `release-verification`+ — A deploy has completed to a shared environment and someone is about to call the release good, or that claim is being checked. · `skills/devops/release-verification/SKILL.md`
  signals: did the deploy work, verify the release, is it actually live, smoke test production, which version is serving, confirm it is healthy
- `rollback` — A release plan needs its way back written and rehearsed, or a deploy is going wrong and someone is deciding whether it can be undone. · `skills/devops/rollback/SKILL.md`
  signals: roll back, undo the deploy, revert the release, can we undo this, back to previous version, way back out

## product

- `experimentation` — An A/B or online experiment is being designed, sized, sanity-checked or interpreted — including deciding whether the traffic can support one at all. · `skills/product/experimentation/SKILL.md`
  signals: ab test, split test, sample size, statistically significant, how long to run, stop the test early, result is flat
- `prd-and-stories` — A settled problem needs a written scope others can build and check against — a brief, PRD, epic or stories — or a ticket is too vague to estimate or verify. · `skills/product/prd-and-stories/SKILL.md`
  signals: write a prd, user stories, acceptance criteria, spec this out, ticket too vague, write the epic
- `prioritization` — The candidate list is longer than the capacity, someone asks what to cut or what ships first, or an existing order cannot be justified. · `skills/product/prioritization/SKILL.md`
  signals: what to cut, what ships first, too much backlog, rank these, cant do everything, why did we pick
- `product-analytics` — A product metric, funnel or dashboard number is being defined, disputed, or about to be instrumented — including before tracking is added to a feature. · `skills/product/product-analytics/SKILL.md`
  signals: how do we measure, funnel drop off, retention rate, dashboards disagree, add tracking, define the metric
- `product-discovery` — A request arrives phrased as a solution, or a plan rests on a belief about users that nobody has checked, and the question is whether the problem is real. · `skills/product/product-discovery/SKILL.md`
  signals: worth building, customer asked for, do users need this, nobody validated this, why are we building, users keep complaining

## knowledge

- `competitive-analysis` — A choice between real alternatives — library, service, vendor, build versus buy — has to be defended, or someone arrives with a comparison table and a conclusion. · `skills/knowledge/competitive-analysis/SKILL.md`
  signals: build vs buy, compare these tools, which library, vendor evaluation, alternatives to, comparison table, stacks up against
- `copywriting` — Copy aimed at an audience outside the product is being written or rewritten — landing page, product messaging, email, ad, announcement — or an existing draft's claims need auditing before it ships. · `skills/knowledge/copywriting/SKILL.md`
  signals: landing page copy, marketing email, ad copy, launch announcement, rewrite this headline, punchier copy, sales page
- `data-analysis` — A dataset has to answer a question, a reported number needs explaining or reconciling, or a finding from data is about to reach someone who will act on it. · `skills/knowledge/data-analysis/SKILL.md`
  signals: analyze this dataset, two numbers disagree, what the data shows, reconcile these numbers, csv analysis, explain this number, spreadsheet numbers
- `deep-research` — An open question's answer will change a decision and the evidence is not already in the conversation — unfamiliar, contested or fast-moving material that needs framing, primary sources and a stopping rule. · `skills/knowledge/deep-research/SKILL.md`
  signals: research this, look into, investigate this, find evidence, what are the tradeoffs, background reading
- `documentation-verification`+ — Documentation is about to be called correct, current or ready to publish, or a setup guide, quickstart or onboarding path fails at an unidentified step. · `skills/knowledge/documentation-verification/SKILL.md`
  signals: docs still accurate, setup guide fails, readme is stale, quickstart broken, broken links, onboarding fails, verify the docs
- `positioning` — The product must be described to people who do not know it — homepage, deck, launch, a new segment — or "who is this for" and "how is this different" have no crisp, evidenced answer. · `skills/knowledge/positioning/SKILL.md`
  signals: who is this for, how are we different, value proposition, homepage messaging, target segment, losing to competitor
- `seo` — A page is written or revised to be found in search, search traffic drops, a page is missing from results, or someone asks which query to target. · `skills/knowledge/seo/SKILL.md`
  signals: rank for, search traffic dropped, not showing in google, keyword to target, meta description, seo audit, get indexed
- `source-evaluation` — A claim is about to be relied on, quoted or cited — or sources disagree, a number arrives without its method, or a 'widely reported' fact needs its origin traced. · `skills/knowledge/source-evaluation/SKILL.md`
  signals: is this source reliable, cite this claim, conflicting sources, is this true, citations, trace the claim, trustworthy source
- `technical-writing` — Documentation is being written, restructured or repaired — README, setup guide, how-to, reference, architecture note, release notes, runbook — or a reader cannot get from the docs to a working result. · `skills/knowledge/technical-writing/SKILL.md`
  signals: write a readme, document this, release notes, write a runbook, api reference, docs are confusing, restructure the docs

## maintained elsewhere

Referenced, never vendored. Check it is actually installed before relying on it;
when it is not, use the fallback and say what could not be done. Never fetch and
run one on the fly.

- `anthropic-agent-development` (official) — Authoring subagents: frontmatter, triggering conditions, system-prompt design. · absent → The local agent-design skill.
- `anthropic-brand-guidelines` (official) — Applying a brand's voice and visual guidelines. · absent → The local copywriting skill plus the project's own brand material.
- `anthropic-claude-api` (official) — Current Claude API surface: model ids, pricing, tool use, caching, agents. · absent → Official Anthropic documentation via the browser.
- `anthropic-claude-security` (official) — Security review guidance from Anthropic. · absent → The local secure-code-review skill.
- `anthropic-doc-coauthoring` (official) — Co-authoring documents with a person in the loop. · absent → The local technical-writing skill.
- `anthropic-frontend-design` (official) — Distinctive, intentional visual design: aesthetic direction, typography, avoiding template · absent → The local frontend-design skill.
- `anthropic-mcp-builder` (official) — Building an MCP server. · absent → The local mcp-design skill.
- `anthropic-mcp-integration` (official) — Wiring MCP servers into a plugin (.mcp.json, transports, auth). · absent → The local mcp-design skill.
- `anthropic-plugin-structure` (official) — Plugin layout, manifest and auto-discovery conventions. · absent → The role's own method; this pack's own layout is the worked example.
- `anthropic-skill-creator` (official) — Authoring Agent Skills: structure, progressive disclosure, description quality. · absent → The agent-design skill, plus the role's own method.
- `anthropic-skill-development` (official) — Skill structure and progressive disclosure for Claude Code plugins. · absent → anthropic-skill-creator when installed, otherwise the agent-design skill and the role's own method.
- `anthropic-webapp-testing` (official) — Testing web applications through a real browser. · absent → The local browser-verification skill.
- `community-frontend-ui-ux` (community) — Single-file doctrine: Nielsen heuristics, Fitts/Hick/Miller laws, WCAG 2.2 AA, Core Web Vi · absent → The local accessibility and ui-audit skills, which cover the same ground.
- `community-playwright-skill` (community) — Community Playwright automation skill, versioned and released. · absent → microsoft-playwright-cli, or the playwright MCP.
- `microsoft-playwright-cli` (official) — Automating browser interactions and working with Playwright tests from the CLI. · absent → The local browser-verification skill.
- `microsoft-playwright-component-testing` (official) — Playwright component testing. · absent → The local browser-verification skill.
- `microsoft-playwright-trace` (official) — Inspecting Playwright trace files: actions, requests, console, errors, snapshots. · absent → The local browser-verification skill.
- `nextjs-next-cache-components-adoption` (official) — Turning on Cache Components and working through the errors it surfaces. · absent → Official Next.js documentation, or Context7.
- `nextjs-next-cache-components-optimizer` (official) — Tuning Cache Components once adopted. · absent → Official Next.js documentation, or Context7.
- `nextjs-next-dev-loop` (official) — The Next.js development loop. · absent → Official Next.js documentation, or Context7.
- `nextjs-next-partial-prefetching-adoption` (official) — Adopting partial prefetching. · absent → Official Next.js documentation, or Context7.
- `nextjs-next-partial-prefetching-optimizer` (official) — Tuning partial prefetching. · absent → Official Next.js documentation, or Context7.
- `vercel-composition-patterns` (verified) — Component composition patterns. · absent → The local equivalent skill, or official documentation.
- `vercel-deploy-to-vercel` (verified) — Deploying a project to Vercel. · absent → The local equivalent skill, or official documentation.
- `vercel-react-best-practices` (verified) — Current React patterns and pitfalls. · absent → The local equivalent skill, or official documentation.
- `vercel-react-native-skills` (verified) — React Native implementation guidance. · absent → The local equivalent skill, or official documentation.
- `vercel-react-view-transitions` (verified) — View Transitions in React. · absent → The local equivalent skill, or official documentation.
- `vercel-vercel-cli-with-tokens` (verified) — Driving the Vercel CLI with tokens. · absent → The local equivalent skill, or official documentation.
- `vercel-vercel-optimize` (verified) — Vercel cost and performance audit for a deployed project: usage metrics, config and code s · absent → The local equivalent skill, or official documentation.
- `vercel-web-design-guidelines` (verified) — Vercel's web design guidelines. · absent → The local equivalent skill, or official documentation.
- `vercel-writing-guidelines` (verified) — Vercel's writing guidelines. · absent → The local equivalent skill, or official documentation.

## recipes

A default shape for multi-step work, not a chain that must run in full.

- `build-production-ui` — Design and implement an interface, then prove in a browser that it renders, responds and is reachable. · `recipes/build-production-ui.md`, or `recipes/build-production-ui.md` beside this file in an install
- `database-migration` — Change a live schema without losing data, with the rollback rehearsed before it is needed. · `recipes/database-migration.md`, or `recipes/database-migration.md` beside this file in an install
- `debug-application` — Reproduce, isolate, fix, and prove the fix with the original reproduction plus a regression test. · `recipes/debug-application.md`, or `recipes/debug-application.md` beside this file in an install
- `investigate-incident` — Stabilize a system that is failing right now, then hand off the root cause. · `recipes/investigate-incident.md`, or `recipes/investigate-incident.md` beside this file in an install
- `research-technical-decision` — Turn an open technical question into a decision with the evidence and the tradeoffs visible. · `recipes/research-technical-decision.md`, or `recipes/research-technical-decision.md` beside this file in an install
- `review-pull-request` — Judge a change against its stated intent and the evidence supplied, and say plainly what was not checked. · `recipes/review-pull-request.md`, or `recipes/review-pull-request.md` beside this file in an install
- `security-review` — Find real, reachable security problems and prove the remediation closed them — checked by someone who did not write the fix. · `recipes/security-review.md`, or `recipes/security-review.md` beside this file in an install
- `ship-feature` — Get a feature from request to merged, with the smallest set of specialists the work actually needs. · `recipes/ship-feature.md`, or `recipes/ship-feature.md` beside this file in an install

## capabilities

Routing asks for a capability, not for a skill id. Most capabilities have exactly one
provider, so the id in the loadout is the answer.

`ai.agent-design`, `ai.context`, `ai.evaluation`, `ai.mcp-design`, `ai.memory`, `ai.observability`, `ai.prompting`, `ai.retrieval`, `ai.routing`, `ai.security`, `ai.structured-output`, `ai.tool-design`, `backend.api`, `backend.authn`, `backend.authz`, `backend.caching`, `backend.jobs`, `backend.reliability`, `backend.webhooks`, `data.analysis`, `data.pipelines`, `data.quality`, `database.integrity`, `database.migrations`, `database.performance`, `database.postgres`, `database.schema`, `design.accessibility`, `design.implementation`, `design.motion`, `design.responsive`, `design.systems`, `design.ui.direction`, `design.ux-writing`, `design.ux.audit`, `devops.ci`, `devops.containers`, `devops.deployment`, `devops.incident`, `devops.observability`, `devops.pipeline`, `devops.rollback`, `frontend.architecture`, `frontend.detection`, `frontend.performance`, `frontend.shadcn`, `frontend.tailwind`, `knowledge.competitive`, `knowledge.copywriting`, `knowledge.positioning`, `knowledge.seo`, `knowledge.writing`, `product.analytics`, `product.definition`, `product.discovery`, `product.experiments`, `product.prioritization`, `quality.debugging`, `quality.e2e`, `quality.profiling`, `quality.regression`, `quality.strategy`, `quality.tests`, `research.deep`, `research.sources`, `security.agents`, `security.auth`, `security.dependencies`, `security.review`, `security.secrets`, `security.threat-modeling`, `security.web`, `verification.accessibility`, `verification.api`, `verification.browser`, `verification.database`, `verification.deployment`, `verification.documentation`, `verification.visual`

These have more than one provider — which matters when the first choice is not
installed, because the substitute has to cover the same capability rather than
merely sound similar:

- `ai.agent-design` — `agent-design`, `anthropic-agent-development`
- `ai.mcp-design` — `anthropic-mcp-builder`, `anthropic-mcp-integration`, `mcp-design`
- `ai.skill-authoring` — `anthropic-skill-creator`, `anthropic-skill-development`
- `design.ui.direction` — `anthropic-frontend-design`, `frontend-design`, `vercel-web-design-guidelines`
- `devops.deployment` — `deployment`, `vercel-deploy-to-vercel`, `vercel-vercel-cli-with-tokens`
- `frontend.architecture` — `component-architecture`, `vercel-composition-patterns`
- `frontend.nextjs` — `nextjs-next-cache-components-adoption`, `nextjs-next-cache-components-optimizer`, `nextjs-next-dev-loop`, `nextjs-next-partial-prefetching-adoption`, `nextjs-next-partial-prefetching-optimizer`
- `knowledge.writing` — `anthropic-doc-coauthoring`, `technical-writing`, `vercel-writing-guidelines`
- `security.review` — `anthropic-claude-security`, `secure-code-review`
- `verification.browser` — `anthropic-webapp-testing`, `browser-verification`, `community-playwright-skill`, `microsoft-playwright-cli`, `microsoft-playwright-component-testing`, `microsoft-playwright-trace`
