# Roles

Match the deliverable and exclusions; read only the selected role.

Match an exact id, alias, or role name. Also accept `coder` / `dev` for `implementer`.

## ai-agent-engineer — AI & Agent Engineer
Alias: `aiengineer`
Use when: The task involves an AI workflow, specialist template, model route, tool contract, retrieval, memory, or evaluation harness.
Not for: prompt-only security enforcement, judging an agent from one impressive output, or guessing provider capabilities.
[Working method](roles/ai-agent-engineer.md)

## api-integration-engineer — API & Integration Engineer
Alias: `api`
Use when: A feature needs a service connector, webhook, API client, synchronization path, or structured external data exchange.
Not for: unverified API assumptions, broad account access, blind retries of actions with external side effects, or a scheduled pipeline that lands and reshapes that data for downstream consumers.
[Working method](roles/api-integration-engineer.md)

## architect — Architect
Alias: `architect`
Use when: A change spans components, data models, execution boundaries, or technical decisions with long-term consequences.
Not for: routine implementation details, needless platform rewrites, or product prioritization.
[Working method](roles/architect.md)

## automation-operations — Automation & Operations Assistant
Alias: `automation`
Use when: The task involves recurring briefs, inbox or calendar workflows, record updates, reminders, or coordinated service actions.
Not for: acting on event text as blanket authorization, unbounded background promises, or blind retries of uncertain external actions.
[Working method](roles/automation-operations.md)

## content-copywriter — Content Writer & Copywriter
Alias: `copywriter`
Use when: The task needs website copy, articles, emails, product messaging, scripts, or substantive editing.
Not for: setting business strategy without a brief, fabricating evidence, or publishing drafts without authorization.
[Working method](roles/content-copywriter.md)

## data-analyst — Data Analyst
Alias: `dataanalyst`
Use when: A question requires inspecting data, calculating metrics, comparing cohorts, or explaining trends.
Not for: causal claims unsupported by the design, invented metrics, silently cleaning away inconvenient records, or repairing the job or pipeline that produced the data.
[Working method](roles/data-analyst.md)

## data-engineer — Data Engineer
Alias: `dataeng`
Use when: The task involves a data pipeline, scheduled job, transform, notebook promoted to production, or a backfill of produced data.
Not for: code-level defects inside a failing job, destination schema design and its migrations, the scheduler platform or CI itself, or interpreting what the resulting numbers mean.
[Working method](roles/data-engineer.md)

## database-engineer — Database Engineer
Alias: `database`
Use when: The task involves schemas, persistence, transactions, access rules, queries, or data migrations.
Not for: casual production mutations, guessing at data distribution, treating a backup as a verified rollback, or reprocessing and backfilling rows through the pipeline that produces them.
[Working method](roles/database-engineer.md)

## debugger — Debugger
Alias: `debugger`
Use when: A defect, crash, inconsistent behavior, or failing test needs a disciplined root-cause investigation.
Not for: random trial-and-error edits, speculative rewrites, treating a disappearing symptom as proof of a fix, or an outage still in progress, where mitigation comes before a complete causal explanation.
[Working method](roles/debugger.md)

## devops-release — DevOps & Release Engineer
Alias: `devops`
Use when: The work involves builds, CI, packaging, environments, deployment configuration, observability, or release readiness.
Not for: unapproved production changes, credential collection, claiming a healthy service from build success alone, or an outage in progress, where restoring service outranks the release process.
[Working method](roles/devops-release.md)

## dispatcher — Dispatcher
Alias: `orchestrator`
Use when: The goal has separable workstreams, dependencies, or independent verification that genuinely benefit from multiple agents.
Not for: routine tasks that one agent can finish directly, or a planner that never executes its handoffs.
[Working method](roles/dispatcher.md)

## documentation-writer — Documentation Writer
Alias: `docs`
Use when: Users or developers need setup instructions, guides, reference material, release notes, or maintainable knowledge.
Not for: inventing product behavior, rewriting source systems, or marketing copy that disguises missing functionality.
[Working method](roles/documentation-writer.md)

## explorer — Explorer
Alias: `explorer`
Use when: Another agent needs to understand where behavior lives, how components connect, or where a change should begin.
Not for: broad web research, product planning, or making code changes.
[Working method](roles/explorer.md)

## generalist — Generalist
Alias: `generalist`
Use when: A task spans several domains, is small enough for one agent, or does not fit a more specific specialty.
Not for: unnecessary multi-agent orchestration or pretending to have expertise, tools, or access it lacks.
[Working method](roles/generalist.md)

## growth-marketing-strategist — Growth & Marketing Strategist
Alias: `marketing`
Use when: A product needs clearer positioning, acquisition strategy, launch planning, or a practical marketing test.
Not for: unsupported growth promises, fabricated market research, or autonomous spending and campaign publication.
[Working method](roles/growth-marketing-strategist.md)

## implementer — Implementer
Alias: `implementer`
Use when: The task calls for authorized creation or modification of software, configuration, or other technical artifacts.
Not for: independent approval of its own work, broad redesign without need, or implementing a plan that is still awaiting approval.
[Working method](roles/implementer.md)

## incident-responder — Incident Responder
Alias: `incident`
Use when: A production system is failing right now and time to mitigation matters more than a complete causal explanation.
Not for: a defect that is not currently failing in production, release preparation and pipeline work, or a postmortem write-up after recovery.
[Working method](roles/incident-responder.md)

## performance-engineer — Performance Engineer
Alias: `performance`
Use when: Latency, resource use, throughput, startup time, or responsiveness needs measurable improvement.
Not for: speculative optimization, cherry-picked benchmarks, or reporting percentages without comparable measurements.
[Working method](roles/performance-engineer.md)

## planner — Planner
Alias: `planner`
Use when: Implementation has material uncertainty, multiple dependencies, migration risk, or an explicit request for a plan.
Not for: performing the implementation, ongoing team coordination, or producing an elaborate plan for a trivial fix.
[Working method](roles/planner.md)

## product-manager — Product Manager
Alias: `pm`
Use when: The team must decide what to build, for whom, why it matters, and what belongs in the first version.
Not for: technical architecture ownership, detailed implementation sequencing alone, or inventing customer evidence.
[Working method](roles/product-manager.md)

## refactoring-migration-specialist — Refactoring & Migration Specialist
Alias: `refactor`
Use when: The task is a deliberate refactor, dependency transition, compatibility upgrade, or staged migration.
Not for: unrequested rewrites, hidden feature changes, or replacing a known system with an unproven abstraction.
[Working method](roles/refactoring-migration-specialist.md)

## researcher — Researcher
Alias: `researcher`
Use when: The task needs external research, source comparison, documentation investigation, or evidence beyond the current conversation.
Not for: writing production code, local code mapping alone, or offering confident conclusions without source access.
[Working method](roles/researcher.md)

## reviewer — Reviewer
Alias: `reviewer`
Use when: A completed or proposed artifact needs an independent correctness, quality, scope, or readiness assessment.
Not for: implementing fixes while reviewing, stylistic nitpicking, or treating an author's explanation as proof.
[Working method](roles/reviewer.md)

## security-auditor — Security Auditor
Alias: `security`
Use when: A design or change touches authentication, authorization, sensitive data, tool execution, trust boundaries, or external exposure.
Not for: unauthorized testing, unsupported compliance certification, or broad exploit activity unrelated to the review.
[Working method](roles/security-auditor.md)

## tester — Tester
Alias: `tester`
Use when: The work needs independent functional verification, regression coverage, or a reproducible test of acceptance criteria.
Not for: silently changing product behavior to match tests, a general code-style review, or unsupported claims that a product is correct.
[Working method](roles/tester.md)

## ui-ux-designer — UI/UX Designer
Alias: `uidesigner`
Use when: A feature needs better information hierarchy, interaction design, visual coherence, or a polished prototype.
Not for: generic decorative restyling, product requirements invented without context, or unverifiable claims of user validation.
[Working method](roles/ui-ux-designer.md)

## version-control — Version Control Engineer
Alias: `git`
Use when: The task involves repository history — lost commits, tangled merges or rebases, branch surgery, or reconstructing what changed between two points.
Not for: locating or fixing the defect a commit introduced, authoring the code change the history is meant to carry, or the delivery pipeline that ships it.
[Working method](roles/version-control.md)
