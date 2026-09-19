# Recipes

<!-- counts:start -->8<!-- counts:end --> default shapes for multi-step work. A recipe is **not** a chain that must run in full —
the dispatcher shortens it when the work is small and extends it when risk warrants. Every one of
them names what to cut.

Recipes reference capabilities rather than agent names wherever they can, so the dispatcher maps a
capability onto whichever role is actually available.

<!-- recipes:start -->

### `build-production-ui` — Build production UI

Design and implement an interface, then prove in a browser that it renders, responds and is reachable.

- **Use when** An interface is being created or redesigned and it will be shipped to real users.
- **Roles** ui-ux-designer, implementer, tester
- **Capabilities** design.ui.direction, design.systems, design.accessibility, design.responsive, verification.browser, verification.accessibility
- [read it](../recipes/build-production-ui.md)

### `database-migration` — Migrate a database

Change a live schema without losing data, with the rollback rehearsed before it is needed.

- **Use when** A schema change has to reach an environment that already holds data people care about.
- **Roles** explorer, database-engineer, planner, implementer, tester, reviewer
- **Capabilities** database.schema, database.migrations, verification.database, database.integrity
- [read it](../recipes/database-migration.md)

### `debug-application` — Debug an application

Reproduce, isolate, fix, and prove the fix with the original reproduction plus a regression test.

- **Use when** Something is broken and the cause is not yet known.
- **Roles** debugger, implementer, tester
- **Capabilities** quality.debugging, quality.regression, verification.browser
- [read it](../recipes/debug-application.md)

### `investigate-incident` — Investigate an incident

Stabilize a system that is failing right now, then hand off the root cause.

- **Use when** Production is degraded or down and time to mitigation matters more than a complete explanation.
- **Roles** incident-responder, debugger, devops-release
- **Capabilities** devops.incident, devops.rollback, devops.observability, verification.deployment
- [read it](../recipes/investigate-incident.md)

### `research-technical-decision` — Research a technical decision

Turn an open technical question into a decision with the evidence and the tradeoffs visible.

- **Use when** A choice between approaches or technologies has consequences that outlast the sprint.
- **Roles** researcher, architect, planner
- **Capabilities** research.deep, research.sources
- [read it](../recipes/research-technical-decision.md)

### `review-pull-request` — Review a pull request

Judge a change against its stated intent and the evidence supplied, and say plainly what was not checked.

- **Use when** A change is proposed for merge and someone needs an assessment of whether it is ready.
- **Roles** reviewer, security-auditor, ui-ux-designer
- **Capabilities** quality.strategy, security.review, design.accessibility
- [read it](../recipes/review-pull-request.md)

### `security-review` — Security review

Find real, reachable security problems and prove the remediation closed them — checked by someone who did not write the fix.

- **Use when** Code touching authentication, authorization, sensitive data, or an external trust boundary needs review before it ships.
- **Roles** security-auditor, implementer, reviewer
- **Capabilities** security.threat-modeling, security.review, security.web
- [read it](../recipes/security-review.md)

### `ship-feature` — Ship a feature

Get a feature from request to merged, with the smallest set of specialists the work actually needs.

- **Use when** A feature is requested that touches more than one file and someone will review it.
- **Roles** explorer, planner, implementer, tester, reviewer
- **Capabilities** quality.debugging, quality.tests, quality.strategy
- [read it](../recipes/ship-feature.md)

<!-- recipes:end -->
