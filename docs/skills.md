# Skills

<!-- counts:start -->79 local skills and 31 externally maintained ones, across 79 capabilities.<!-- counts:end --> A ✓ marks a verification skill — one whose job is to
produce evidence, not to produce work. Each skill's own `description` says when it fires and what
it is not for; the router's `INDEX.md` is the same list in the form an agent resolves ids against.

Nothing here is loaded until a role's loadout names it and the task calls for it. See
[architecture.md](architecture.md) for the three disclosure levels, and
[adding-a-skill.md](adding-a-skill.md) to write one.

## Local

<!-- local:start -->

**design** (9) — [`accessibility`](../skills/design/accessibility/SKILL.md), [`accessibility-verification`](../skills/design/accessibility-verification/SKILL.md)✓, [`design-systems`](../skills/design/design-systems/SKILL.md), [`design-to-code`](../skills/design/design-to-code/SKILL.md), [`frontend-design`](../skills/design/frontend-design/SKILL.md), [`motion-design`](../skills/design/motion-design/SKILL.md), [`responsive-design`](../skills/design/responsive-design/SKILL.md), [`ui-audit`](../skills/design/ui-audit/SKILL.md), [`ux-writing`](../skills/design/ux-writing/SKILL.md)

**frontend** (6) — [`component-architecture`](../skills/frontend/component-architecture/SKILL.md), [`frontend-performance`](../skills/frontend/frontend-performance/SKILL.md), [`shadcn-ui`](../skills/frontend/shadcn-ui/SKILL.md), [`stack-detection`](../skills/frontend/stack-detection/SKILL.md), [`tailwind`](../skills/frontend/tailwind/SKILL.md), [`visual-verification`](../skills/frontend/visual-verification/SKILL.md)✓

**backend** (8) — [`api-contract-verification`](../skills/backend/api-contract-verification/SKILL.md)✓, [`api-design`](../skills/backend/api-design/SKILL.md), [`authentication`](../skills/backend/authentication/SKILL.md), [`authorization`](../skills/backend/authorization/SKILL.md), [`background-jobs`](../skills/backend/background-jobs/SKILL.md), [`caching`](../skills/backend/caching/SKILL.md), [`idempotency-and-retries`](../skills/backend/idempotency-and-retries/SKILL.md), [`webhooks`](../skills/backend/webhooks/SKILL.md)

**database** (8) — [`data-integrity`](../skills/database/data-integrity/SKILL.md), [`data-pipelines`](../skills/database/data-pipelines/SKILL.md), [`data-quality`](../skills/database/data-quality/SKILL.md), [`database-migration-verification`](../skills/database/database-migration-verification/SKILL.md)✓, [`migrations`](../skills/database/migrations/SKILL.md), [`postgres`](../skills/database/postgres/SKILL.md), [`query-optimization`](../skills/database/query-optimization/SKILL.md), [`schema-design`](../skills/database/schema-design/SKILL.md)

**ai** (12) — [`agent-design`](../skills/ai/agent-design/SKILL.md), [`agent-evals`](../skills/ai/agent-evals/SKILL.md)✓, [`context-engineering`](../skills/ai/context-engineering/SKILL.md), [`llm-observability`](../skills/ai/llm-observability/SKILL.md), [`mcp-design`](../skills/ai/mcp-design/SKILL.md), [`memory-design`](../skills/ai/memory-design/SKILL.md), [`model-routing`](../skills/ai/model-routing/SKILL.md), [`prompt-engineering`](../skills/ai/prompt-engineering/SKILL.md), [`prompt-injection-defense`](../skills/ai/prompt-injection-defense/SKILL.md), [`retrieval-rag`](../skills/ai/retrieval-rag/SKILL.md), [`structured-output`](../skills/ai/structured-output/SKILL.md), [`tool-design`](../skills/ai/tool-design/SKILL.md)

**quality** (7) — [`browser-verification`](../skills/quality/browser-verification/SKILL.md)✓, [`e2e-testing`](../skills/quality/e2e-testing/SKILL.md), [`performance-profiling`](../skills/quality/performance-profiling/SKILL.md), [`regression-testing`](../skills/quality/regression-testing/SKILL.md), [`systematic-debugging`](../skills/quality/systematic-debugging/SKILL.md), [`test-design`](../skills/quality/test-design/SKILL.md), [`test-strategy`](../skills/quality/test-strategy/SKILL.md)

**security** (7) — [`agent-security`](../skills/security/agent-security/SKILL.md), [`auth-security`](../skills/security/auth-security/SKILL.md), [`dependency-security`](../skills/security/dependency-security/SKILL.md), [`owasp-web`](../skills/security/owasp-web/SKILL.md), [`secrets-management`](../skills/security/secrets-management/SKILL.md), [`secure-code-review`](../skills/security/secure-code-review/SKILL.md), [`threat-modeling`](../skills/security/threat-modeling/SKILL.md)

**devops** (8) — [`ci-cd`](../skills/devops/ci-cd/SKILL.md), [`deployment`](../skills/devops/deployment/SKILL.md), [`docker`](../skills/devops/docker/SKILL.md), [`github-actions`](../skills/devops/github-actions/SKILL.md), [`incident-response`](../skills/devops/incident-response/SKILL.md), [`observability`](../skills/devops/observability/SKILL.md), [`release-verification`](../skills/devops/release-verification/SKILL.md)✓, [`rollback`](../skills/devops/rollback/SKILL.md)

**product** (5) — [`experimentation`](../skills/product/experimentation/SKILL.md), [`prd-and-stories`](../skills/product/prd-and-stories/SKILL.md), [`prioritization`](../skills/product/prioritization/SKILL.md), [`product-analytics`](../skills/product/product-analytics/SKILL.md), [`product-discovery`](../skills/product/product-discovery/SKILL.md)

**knowledge** (9) — [`competitive-analysis`](../skills/knowledge/competitive-analysis/SKILL.md), [`copywriting`](../skills/knowledge/copywriting/SKILL.md), [`data-analysis`](../skills/knowledge/data-analysis/SKILL.md), [`deep-research`](../skills/knowledge/deep-research/SKILL.md), [`documentation-verification`](../skills/knowledge/documentation-verification/SKILL.md)✓, [`positioning`](../skills/knowledge/positioning/SKILL.md), [`seo`](../skills/knowledge/seo/SKILL.md), [`source-evaluation`](../skills/knowledge/source-evaluation/SKILL.md), [`technical-writing`](../skills/knowledge/technical-writing/SKILL.md)

<!-- local:end -->

## Maintained elsewhere

Referenced, never vendored — this repository records where each one lives and what it is
licensed under, and names a fallback for when it is not installed. Provenance for each is in
[`catalog/external-skills.json`](../catalog/external-skills.json); trust levels are defined in
[security.md](security.md).

<!-- external:start -->

### official (20)

| Skill | Source | Licence | Fallback |
| --- | --- | --- | --- |
| `anthropic-agent-development` | [anthropics/claude-code](https://github.com/anthropics/claude-code) `plugins/plugin-dev/skills/agent-development/SKILL.md` | proprietary — anthropics/claude-code is under Anthropic's Co | The local agent-design skill. |
| `anthropic-brand-guidelines` | [anthropics/skills](https://github.com/anthropics/skills) `skills/brand-guidelines/SKILL.md` | Apache-2.0 | The local copywriting skill plus the project's own brand material. |
| `anthropic-claude-api` | [anthropics/skills](https://github.com/anthropics/skills) `skills/claude-api/SKILL.md` | Apache-2.0 | Official Anthropic documentation via the browser. |
| `anthropic-claude-security` | [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official) `plugins/claude-security/skills/claude-security/SKILL.md` | Apache-2.0 | The local secure-code-review skill. |
| `anthropic-doc-coauthoring` | [anthropics/skills](https://github.com/anthropics/skills) `skills/doc-coauthoring/SKILL.md` | Apache-2.0 | The local technical-writing skill. |
| `anthropic-frontend-design` | [anthropics/skills](https://github.com/anthropics/skills) `skills/frontend-design/SKILL.md` | Apache-2.0 (per-skill LICENSE.txt in anthropics/skills) | The local frontend-design skill. |
| `anthropic-mcp-builder` | [anthropics/skills](https://github.com/anthropics/skills) `skills/mcp-builder/SKILL.md` | Apache-2.0 | The local mcp-design skill. |
| `anthropic-mcp-integration` | [anthropics/claude-code](https://github.com/anthropics/claude-code) `plugins/plugin-dev/skills/mcp-integration/SKILL.md` | proprietary — see above | The local mcp-design skill. |
| `anthropic-plugin-structure` | [anthropics/claude-code](https://github.com/anthropics/claude-code) `plugins/plugin-dev/skills/plugin-structure/SKILL.md` | proprietary — see above | The role's own method; this pack's own layout is the worked example. |
| `anthropic-skill-creator` | [anthropics/skills](https://github.com/anthropics/skills) `skills/skill-creator/SKILL.md` | Apache-2.0 | The agent-design skill, plus the role's own method. |
| `anthropic-skill-development` | [anthropics/claude-code](https://github.com/anthropics/claude-code) `plugins/plugin-dev/skills/skill-development/SKILL.md` | proprietary — see above | anthropic-skill-creator when installed, otherwise the agent-design skill and the role's own method. |
| `anthropic-webapp-testing` | [anthropics/skills](https://github.com/anthropics/skills) `skills/webapp-testing/SKILL.md` | Apache-2.0 | The local browser-verification skill. |
| `microsoft-playwright-cli` | [microsoft/playwright](https://github.com/microsoft/playwright) `packages/playwright-core/src/tools/skills/playwright-cli/SKILL.md` | Apache-2.0 | The local browser-verification skill. |
| `microsoft-playwright-component-testing` | [microsoft/playwright](https://github.com/microsoft/playwright) `packages/playwright-core/src/tools/skills/playwright-component-testing/SKILL.md` | Apache-2.0 | The local browser-verification skill. |
| `microsoft-playwright-trace` | [microsoft/playwright](https://github.com/microsoft/playwright) `packages/playwright-core/src/tools/skills/playwright-trace/SKILL.md` | Apache-2.0 | The local browser-verification skill. |
| `nextjs-next-cache-components-adoption` | [vercel/next.js](https://github.com/vercel/next.js) `skills/next-cache-components-adoption/SKILL.md` | MIT | Official Next.js documentation, or Context7. |
| `nextjs-next-cache-components-optimizer` | [vercel/next.js](https://github.com/vercel/next.js) `skills/next-cache-components-optimizer/SKILL.md` | MIT | Official Next.js documentation, or Context7. |
| `nextjs-next-dev-loop` | [vercel/next.js](https://github.com/vercel/next.js) `skills/next-dev-loop/SKILL.md` | MIT | Official Next.js documentation, or Context7. |
| `nextjs-next-partial-prefetching-adoption` | [vercel/next.js](https://github.com/vercel/next.js) `skills/next-partial-prefetching-adoption/SKILL.md` | MIT | Official Next.js documentation, or Context7. |
| `nextjs-next-partial-prefetching-optimizer` | [vercel/next.js](https://github.com/vercel/next.js) `skills/next-partial-prefetching-optimizer/SKILL.md` | MIT | Official Next.js documentation, or Context7. |

### verified (9)

| Skill | Source | Licence | Fallback |
| --- | --- | --- | --- |
| `vercel-composition-patterns` | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) `skills/composition-patterns/SKILL.md` | MIT claimed per-skill; no LICENSE file at the repository roo | The local equivalent skill, or official documentation. |
| `vercel-deploy-to-vercel` | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) `skills/deploy-to-vercel/SKILL.md` | MIT claimed per-skill; no LICENSE file at the repository roo | The local equivalent skill, or official documentation. |
| `vercel-react-best-practices` | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) `skills/react-best-practices/SKILL.md` | MIT claimed per-skill; no LICENSE file at the repository roo | The local equivalent skill, or official documentation. |
| `vercel-react-native-skills` | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) `skills/react-native-skills/SKILL.md` | MIT claimed per-skill; no LICENSE file at the repository roo | The local equivalent skill, or official documentation. |
| `vercel-react-view-transitions` | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) `skills/react-view-transitions/SKILL.md` | MIT claimed per-skill; no LICENSE file at the repository roo | The local equivalent skill, or official documentation. |
| `vercel-vercel-cli-with-tokens` | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) `skills/vercel-cli-with-tokens/SKILL.md` | MIT claimed per-skill; no LICENSE file at the repository roo | The local equivalent skill, or official documentation. |
| `vercel-vercel-optimize` | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) `skills/vercel-optimize/SKILL.md` | MIT claimed per-skill; no LICENSE file at the repository roo | The local equivalent skill, or official documentation. |
| `vercel-web-design-guidelines` | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) `skills/web-design-guidelines/SKILL.md` | MIT claimed per-skill; no LICENSE file at the repository roo | The local equivalent skill, or official documentation. |
| `vercel-writing-guidelines` | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) `skills/writing-guidelines/SKILL.md` | MIT claimed per-skill; no LICENSE file at the repository roo | The local equivalent skill, or official documentation. |

### community (2)

| Skill | Source | Licence | Fallback |
| --- | --- | --- | --- |
| `community-frontend-ui-ux` | [overseek944/frontend-ui-ux-skill](https://github.com/overseek944/frontend-ui-ux-skill) `SKILL.md` | MIT | The local accessibility and ui-audit skills, which cover the same ground. |
| `community-playwright-skill` | [lackeyjb/playwright-skill](https://github.com/lackeyjb/playwright-skill) `skills/playwright-skill/SKILL.md` | MIT | microsoft-playwright-cli, or the playwright MCP. |

<!-- external:end -->
