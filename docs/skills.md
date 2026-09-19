# Skills

79 local skills and 31 externally maintained ones, across
79 capabilities. A ✓ marks a verification skill —
one whose job is to produce evidence, not to produce work.

Nothing here is loaded until a role's loadout names it and the task calls for it. See
[architecture.md](architecture.md) for the three disclosure levels, and
[adding-a-skill.md](adding-a-skill.md) to write one.

## Local

### design (9)

| Skill | Capability | Fires when |
| --- | --- | --- |
| `accessibility` | `design.accessibility` | UI is being built, changed or repaired and it has to be operable by keyboard and assistive technology — including turning an audit finding into an actual code change. |
| `accessibility-verification` ✓ | `verification.accessibility` | Someone is about to claim a screen or flow is accessible, keyboard-operable, screen-reader usable or WCAG-conformant, or an accessibility fix needs re-checking. |
| `design-systems` | `design.systems` | The project already has design tokens, a component library or a shared theme, and UI is being added or changed inside it. |
| `design-to-code` | `design.implementation` | A design, mockup, Figma frame or screenshot is the source for a UI change, or an existing implementation is being compared against one. |
| `frontend-design` | `design.ui.direction` | A new or reshaped UI surface needs a visual direction decided — hierarchy, type, colour, spacing, density — and no design system already decides it. |
| `motion-design` | `design.motion` | Transitions, animated state changes, gesture movement or loading indicators are being added, tuned or reviewed, or an interface reads as janky or sluggish. |
| `responsive-design` | `design.responsive` | A layout has to hold across viewport widths — building it, repairing an overflow or collapse at some size, or filling in the sizes a single-width design never specified. |
| `ui-audit` | `design.ux.audit` | An interface already exists and someone needs to know what is wrong with it, ranked and concrete enough to act on. |
| `ux-writing` | `design.ux-writing` | Interface strings are being written, reviewed or repaired — labels, errors, empty states, confirmations, form hints — or a control's wording is causing hesitation. |

### frontend (6)

| Skill | Capability | Fires when |
| --- | --- | --- |
| `component-architecture` | `frontend.architecture` | A component is being added, has grown props or responsibilities, or a structure is under review for whether it will hold. |
| `frontend-performance` | `frontend.performance` | A page is reported slow, a Core Web Vital or bundle size is named, or a change is about to be described as a performance improvement. |
| `shadcn-ui` | `frontend.shadcn` | Adding, customizing or debugging a shadcn/ui component in a repo with components.json and a vendored UI directory. |
| `stack-detection` | `frontend.detection` | You are about to work in a frontend repo whose stack you have not yet confirmed this session, or about to load framework-specific guidance. |
| `tailwind` | `frontend.tailwind` | Writing or editing Tailwind utility classes in a project that already uses Tailwind. |
| `visual-verification` ✓ | `verification.visual` | A change affects appearance and is about to be called done, or a screenshot-comparison result is about to be trusted as proof. |

### backend (8)

| Skill | Capability | Fires when |
| --- | --- | --- |
| `api-contract-verification` ✓ | `verification.api` | An endpoint, API client or third-party integration is about to be reported as working, or someone asks whether an integration is actually verified. |
| `api-design` | `backend.api` | An HTTP endpoint is being added or reshaped, a response or error shape has to be decided, or a change to a published API has to be judged for breakage. |
| `authentication` | `backend.authn` | A credential is issued, accepted, refreshed or revoked — login, logout, sessions, tokens, API keys, or an OAuth/OIDC integration. |
| `authorization` | `backend.authz` | A rule of the form 'only X may do Y to Z' is added, changed or doubted — roles, permissions, per-owner or per-tenant scoping, admin paths. |
| `background-jobs` | `backend.jobs` | Work is being moved off a request path onto a queue or scheduler, or a job ran twice, never ran, ran out of order, or is stuck retrying. |
| `caching` | `backend.caching` | A cache is about to be added to a read path, or existing cached data is stale, leaking across users, or being blamed for a bug. |
| `idempotency-and-retries` | `backend.reliability` | An operation with an external side effect has to survive being repeated, a caller needs a retry policy, or duplicate effects have appeared and must be prevented. |
| `webhooks` | `backend.webhooks` | A webhook endpoint is being built, integrated or debugged, or the service has to deliver events to external consumers. |

### database (8)

| Skill | Capability | Fires when |
| --- | --- | --- |
| `data-integrity` | `database.integrity` | A rule about what must always be true of the data needs to be enforced in a live schema, or an invariant that was enforced has drifted. |
| `data-pipelines` | `data.pipelines` | A batch or streaming pipeline, scheduled transform or ingestion job is being built, repaired or backfilled, or a run dropped, duplicated or reshaped rows. |
| `data-quality` | `data.quality` | Checks on a dataset are being written or reviewed, a wrong value reached a consumer with nothing catching it, or an existing check is noisy enough to be ignored. |
| `database-migration-verification` ✓ | `verification.database` | A migration has been applied to some environment and someone is about to report it as working, or that claim is being reviewed. |
| `migrations` | `database.migrations` | A schema or data migration is being written, reviewed or sequenced against a database that holds real data and has live readers. |
| `postgres` | `database.postgres` | The project runs on Postgres and the decision depends on engine behaviour — a column type, an index kind, a plan to read, an isolation level, DDL lock behaviour, or a row-level security policy. |
| `query-optimization` | `database.performance` | A specific statement is slow and the database is the suspect, a query plan needs interpreting, or an index is being proposed without evidence. |
| `schema-design` | `database.schema` | New tables are being designed, ORM models or migration DDL are under review, or a defect traces back to the data model permitting a state that should be impossible. |

### ai (12)

| Skill | Capability | Fires when |
| --- | --- | --- |
| `agent-design` | `ai.agent-design` | An agent or subagent is being scoped, granted tools, or reviewed after looping, over-reaching or reporting work it did not do. |
| `agent-evals` ✓ | `ai.evaluation` | A prompt, model, tool definition or retrieval change is about to be called an improvement, agent behaviour must not silently regress, or a production failure needs to become a case that cannot come back. |
| `context-engineering` | `ai.context` | A prompt, agent or session loads substantial material, quality decays as context grows, or context has to be trimmed, summarized or split between inlining and retrieval. |
| `llm-observability` | `ai.observability` | An agent fails in ways that will not reproduce, cost or latency is unaccounted for, or failure modes must be found before evals can be written. |
| `mcp-design` | `ai.mcp-design` | An MCP server is being written, an internal system is being wrapped as one, or a third-party server is being assessed before it is wired into a project. |
| `memory-design` | `ai.memory` | An agent must carry facts, preferences or decisions past the current context, or an existing memory store has become noisy, contradictory or wrongly scoped. |
| `model-routing` | `ai.routing` | More than one model is in play and a call has to be assigned to one, or cost, latency or a silently firing fallback has become a problem. |
| `prompt-engineering` | `ai.prompting` | A prompt is being written or patched, its output is inconsistent or the wrong shape, a model version changed, or someone has declared a prompt improved. |
| `prompt-injection-defense` | `ai.security` | An agent ingests content it did not author — retrieval, browsing, email, files, MCP tool results, subagent output — and also holds tools that can act. |
| `retrieval-rag` | `ai.retrieval` | A retrieval-backed system returns wrong or thin answers, or an index is being designed, chunked, embedded or rebuilt. |
| `structured-output` | `ai.structured-output` | A model's output feeds code rather than a human — extraction, classification, routing, scoring — or parsing keeps failing, fields arrive invented, or a schema is being designed for a model to fill. |
| `tool-design` | `ai.tool-design` | A tool or function an LLM calls is being added or reshaped, or an agent is selecting the wrong tool, passing malformed arguments, looping, or stalling after a call. |

### quality (7)

| Skill | Capability | Fires when |
| --- | --- | --- |
| `browser-verification` ✓ | `verification.browser` | A change touches rendered UI and someone is about to claim it works, or you are asked whether a screen actually functions. |
| `e2e-testing` | `quality.e2e` | An automated end-to-end suite is being created, extended, triaged for flake, or pruned, or a case has to be placed at or below this level. |
| `performance-profiling` | `quality.profiling` | Something is slow, or an optimization is about to be written from a hunch rather than from a measurement. |
| `regression-testing` | `quality.regression` | A bug has just been fixed, or keeps coming back, and the fix needs a test that is proven to fail without it. |
| `systematic-debugging` | `quality.debugging` | Something is broken, the cause is not yet known, and someone is about to start editing code to find out. |
| `test-design` | `quality.tests` | Unit or integration tests are being written or repaired — new coverage, pinning a reported bug, or a suite that stays green while the behaviour is wrong. |
| `test-strategy` | `quality.strategy` | Coverage has to be planned or defended — before writing a batch of tests, when a suite is slow and nobody can say what it buys, or after a bug escaped and nothing caught it. |

### security (7)

| Skill | Capability | Fires when |
| --- | --- | --- |
| `agent-security` | `security.agents` | An agent or subagent is being granted tools, credentials or MCP access, is about to reach a shared or production system, or acted beyond what the requester could have done. |
| `auth-security` | `security.auth` | An existing auth path is reviewed, changed or doubted — sessions, tokens, reset and invite flows, impersonation, role elevation, MFA — or someone reports reaching another account's data. |
| `dependency-security` | `security.dependencies` | An advisory or audit finding needs judging, a dependency is being added or bumped, a lockfile diff needs review, or someone asks whether a named CVE affects this project. |
| `owasp-web` | `security.web` | Web code that takes requests, builds queries, renders output, fetches URLs, deserializes data, handles sessions or accepts files is being written or reviewed, or an app needs a sweep for the recurring vulnerability classes. |
| `secrets-management` | `security.secrets` | A credential is added, moved, shared or due for rotation, or one has turned up in code, history, logs or a client bundle. |
| `secure-code-review` | `security.review` | A pull request, feature or repository needs a security read before shipping — especially anything touching auth, money, tenancy, uploads, deserialization or secrets — or someone reports reaching data they should not have. |
| `threat-modeling` | `security.threat-modeling` | A system's shape is being designed or changed — new service, integration, tenancy model, uploads, payments or auth — and someone needs to know which few things are actually worth defending. |

### devops (8)

| Skill | Capability | Fires when |
| --- | --- | --- |
| `ci-cd` | `devops.pipeline` | A delivery pipeline is being designed or restructured, something broken reached an environment through a passing pipeline, or a stage is claiming more than it actually ran. |
| `deployment` | `devops.deployment` | A change is going to an environment other people use, or the path that takes it there is being built or changed. |
| `docker` | `devops.containers` | A Dockerfile is being written, changed or reviewed, an image build is slow, bloated or non-deterministic, or configuration and secrets need a route into a container. |
| `github-actions` | `devops.ci` | A GitHub Actions workflow is being added, changed or reviewed, or CI is slow, flaky, or reporting green when it should be red. |
| `incident-response` | `devops.incident` | Production is failing or degraded right now and stopping the ongoing harm matters more than a complete causal explanation. |
| `observability` | `devops.observability` | A service or a new critical path is going to production, an incident ended with a question the data could not answer, or a dependency, queue or job is being added whose failure would otherwise be silent. |
| `release-verification` ✓ | `verification.deployment` | A deploy has completed to a shared environment and someone is about to call the release good, or that claim is being checked. |
| `rollback` | `devops.rollback` | A release plan needs its way back written and rehearsed, or a deploy is going wrong and someone is deciding whether it can be undone. |

### product (5)

| Skill | Capability | Fires when |
| --- | --- | --- |
| `experimentation` | `product.experiments` | An A/B or online experiment is being designed, sized, sanity-checked or interpreted — including deciding whether the traffic can support one at all. |
| `prd-and-stories` | `product.definition` | A settled problem needs a written scope others can build and check against — a brief, PRD, epic or stories — or a ticket is too vague to estimate or verify. |
| `prioritization` | `product.prioritization` | The candidate list is longer than the capacity, someone asks what to cut or what ships first, or an existing order cannot be justified. |
| `product-analytics` | `product.analytics` | A product metric, funnel or dashboard number is being defined, disputed, or about to be instrumented — including before tracking is added to a feature. |
| `product-discovery` | `product.discovery` | A request arrives phrased as a solution, or a plan rests on a belief about users that nobody has checked, and the question is whether the problem is real. |

### knowledge (9)

| Skill | Capability | Fires when |
| --- | --- | --- |
| `competitive-analysis` | `knowledge.competitive` | A choice between real alternatives — library, service, vendor, build versus buy — has to be defended, or someone arrives with a comparison table and a conclusion. |
| `copywriting` | `knowledge.copywriting` | Copy aimed at an audience outside the product is being written or rewritten — landing page, product messaging, email, ad, announcement — or an existing draft's claims need auditing before it ships. |
| `data-analysis` | `data.analysis` | A dataset has to answer a question, a reported number needs explaining or reconciling, or a finding from data is about to reach someone who will act on it. |
| `deep-research` | `research.deep` | An open question's answer will change a decision and the evidence is not already in the conversation — unfamiliar, contested or fast-moving material that needs framing, primary sources and a stopping rule. |
| `documentation-verification` ✓ | `verification.documentation` | Documentation is about to be called correct, current or ready to publish, or a setup guide, quickstart or onboarding path fails at an unidentified step. |
| `positioning` | `knowledge.positioning` | The product must be described to people who do not know it — homepage, deck, launch, a new segment — or "who is this for" and "how is this different" have no crisp, evidenced answer. |
| `seo` | `knowledge.seo` | A page is written or revised to be found in search, search traffic drops, a page is missing from results, or someone asks which query to target. |
| `source-evaluation` | `research.sources` | A claim is about to be relied on, quoted or cited — or sources disagree, a number arrives without its method, or a 'widely reported' fact needs its origin traced. |
| `technical-writing` | `knowledge.writing` | Documentation is being written, restructured or repaired — README, setup guide, how-to, reference, architecture note, release notes, runbook — or a reader cannot get from the docs to a working result. |

## Maintained elsewhere

Referenced, never vendored — this repository records where each one lives and what it is licensed
under, and names a fallback for when it is not installed. Provenance for each is in
[`catalog/external-skills.json`](../catalog/external-skills.json); trust levels are defined in
[security.md](security.md).

### official (20)

| Skill | Source | Licence | Fallback |
| --- | --- | --- | --- |
| `anthropic-frontend-design` | [anthropics/skills](https://github.com/anthropics/skills) `skills/frontend-design/SKILL.md` | Apache-2.0 (per-skill LICENSE.txt in anthropics/skills) | The local frontend-design skill. |
| `anthropic-webapp-testing` | [anthropics/skills](https://github.com/anthropics/skills) `skills/webapp-testing/SKILL.md` | Apache-2.0 | The local browser-verification skill. |
| `anthropic-skill-creator` | [anthropics/skills](https://github.com/anthropics/skills) `skills/skill-creator/SKILL.md` | Apache-2.0 | docs/adding-a-skill.md in this repository. |
| `anthropic-mcp-builder` | [anthropics/skills](https://github.com/anthropics/skills) `skills/mcp-builder/SKILL.md` | Apache-2.0 | The local mcp-design skill. |
| `anthropic-claude-api` | [anthropics/skills](https://github.com/anthropics/skills) `skills/claude-api/SKILL.md` | Apache-2.0 | Official Anthropic documentation via the browser. |
| `anthropic-claude-security` | [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official) `plugins/claude-security/skills/claude-security/SKILL.md` | Apache-2.0 | The local secure-code-review skill. |
| `anthropic-agent-development` | [anthropics/claude-code](https://github.com/anthropics/claude-code) `plugins/plugin-dev/skills/agent-development/SKILL.md` | proprietary — anthropics/claude-code is under Anthropic's Co | The local agent-design skill. |
| `anthropic-skill-development` | [anthropics/claude-code](https://github.com/anthropics/claude-code) `plugins/plugin-dev/skills/skill-development/SKILL.md` | proprietary — see above | anthropic-skill-creator (Apache-2.0) or docs/adding-a-skill.md. |
| `anthropic-plugin-structure` | [anthropics/claude-code](https://github.com/anthropics/claude-code) `plugins/plugin-dev/skills/plugin-structure/SKILL.md` | proprietary — see above | docs/architecture.md in this repository. |
| `anthropic-mcp-integration` | [anthropics/claude-code](https://github.com/anthropics/claude-code) `plugins/plugin-dev/skills/mcp-integration/SKILL.md` | proprietary — see above | The local mcp-design skill. |
| `anthropic-doc-coauthoring` | [anthropics/skills](https://github.com/anthropics/skills) `skills/doc-coauthoring/SKILL.md` | Apache-2.0 | The local technical-writing skill. |
| `anthropic-brand-guidelines` | [anthropics/skills](https://github.com/anthropics/skills) `skills/brand-guidelines/SKILL.md` | Apache-2.0 | The local copywriting skill plus the project's own brand material. |
| `nextjs-next-cache-components-adoption` | [vercel/next.js](https://github.com/vercel/next.js) `skills/next-cache-components-adoption/SKILL.md` | MIT | Official Next.js documentation, or Context7. |
| `nextjs-next-cache-components-optimizer` | [vercel/next.js](https://github.com/vercel/next.js) `skills/next-cache-components-optimizer/SKILL.md` | MIT | Official Next.js documentation, or Context7. |
| `nextjs-next-dev-loop` | [vercel/next.js](https://github.com/vercel/next.js) `skills/next-dev-loop/SKILL.md` | MIT | Official Next.js documentation, or Context7. |
| `nextjs-next-partial-prefetching-adoption` | [vercel/next.js](https://github.com/vercel/next.js) `skills/next-partial-prefetching-adoption/SKILL.md` | MIT | Official Next.js documentation, or Context7. |
| `nextjs-next-partial-prefetching-optimizer` | [vercel/next.js](https://github.com/vercel/next.js) `skills/next-partial-prefetching-optimizer/SKILL.md` | MIT | Official Next.js documentation, or Context7. |
| `microsoft-playwright-cli` | [microsoft/playwright](https://github.com/microsoft/playwright) `packages/playwright-core/src/tools/skills/playwright-cli/SKILL.md` | Apache-2.0 | The local browser-verification skill. |
| `microsoft-playwright-trace` | [microsoft/playwright](https://github.com/microsoft/playwright) `packages/playwright-core/src/tools/skills/playwright-trace/SKILL.md` | Apache-2.0 | The local browser-verification skill. |
| `microsoft-playwright-component-testing` | [microsoft/playwright](https://github.com/microsoft/playwright) `packages/playwright-core/src/tools/skills/playwright-component-testing/SKILL.md` | Apache-2.0 | The local browser-verification skill. |

### verified (9)

| Skill | Source | Licence | Fallback |
| --- | --- | --- | --- |
| `vercel-vercel-optimize` | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) `skills/vercel-optimize/SKILL.md` | MIT claimed per-skill; no LICENSE file at the repository roo | The local equivalent skill, or official documentation. |
| `vercel-react-best-practices` | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) `skills/react-best-practices/SKILL.md` | MIT claimed per-skill; no LICENSE file at the repository roo | The local equivalent skill, or official documentation. |
| `vercel-web-design-guidelines` | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) `skills/web-design-guidelines/SKILL.md` | MIT claimed per-skill; no LICENSE file at the repository roo | The local equivalent skill, or official documentation. |
| `vercel-writing-guidelines` | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) `skills/writing-guidelines/SKILL.md` | MIT claimed per-skill; no LICENSE file at the repository roo | The local equivalent skill, or official documentation. |
| `vercel-react-native-skills` | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) `skills/react-native-skills/SKILL.md` | MIT claimed per-skill; no LICENSE file at the repository roo | The local equivalent skill, or official documentation. |
| `vercel-react-view-transitions` | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) `skills/react-view-transitions/SKILL.md` | MIT claimed per-skill; no LICENSE file at the repository roo | The local equivalent skill, or official documentation. |
| `vercel-composition-patterns` | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) `skills/composition-patterns/SKILL.md` | MIT claimed per-skill; no LICENSE file at the repository roo | The local equivalent skill, or official documentation. |
| `vercel-deploy-to-vercel` | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) `skills/deploy-to-vercel/SKILL.md` | MIT claimed per-skill; no LICENSE file at the repository roo | The local equivalent skill, or official documentation. |
| `vercel-vercel-cli-with-tokens` | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) `skills/vercel-cli-with-tokens/SKILL.md` | MIT claimed per-skill; no LICENSE file at the repository roo | The local equivalent skill, or official documentation. |

### community (2)

| Skill | Source | Licence | Fallback |
| --- | --- | --- | --- |
| `community-frontend-ui-ux` | [overseek944/frontend-ui-ux-skill](https://github.com/overseek944/frontend-ui-ux-skill) `SKILL.md` | MIT | The local accessibility and ui-audit skills, which cover the same ground. |
| `community-playwright-skill` | [lackeyjb/playwright-skill](https://github.com/lackeyjb/playwright-skill) `skills/playwright-skill/SKILL.md` | MIT | microsoft-playwright-cli, or the playwright MCP. |
