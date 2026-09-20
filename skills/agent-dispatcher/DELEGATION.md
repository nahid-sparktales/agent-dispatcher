# Chaining and delegation

Read only when the requested work calls for chaining roles or independent subagents.
Host capabilities and session instructions determine whether delegation is available.

## Chaining roles inside one turn

Real requests often need more than one kind of work. Switch roles mid-turn rather than stretching one role over work it is not for.

- Report each switch with an activity summary — and meet each role's **definition of done** before moving on. The previous role's deliverable is the next role's input.
- Read the next role's file when you switch to it. Never blend two roles into one voice, and never carry a role's boundaries into the next one.
- Stop at the deliverable the user actually asked for. "Give me a plan" ends at `planner`; do not chain into building it. A request that names both — "plan it and build it" — authorizes moving to the next role without re-asking, and the plan it produces is not "awaiting approval" for the role that follows. It is not authorization for any step that needs its own confirmation: destructive and outward-facing actions still stop and ask, in every role.
- A forced role suppresses chaining as well as routing: stay in it and say what it does not cover, unless the user asked for the chain.
- Three roles per turn is the practical ceiling. Past that, drop the lowest-value hop; route to the `dispatcher` role only when the work is genuinely separable workstreams that need orchestrating.
- When a verifying role (`reviewer`, `tester`, `security-auditor`) closes a chain, say plainly that it is judging work produced in the same session — that is a self-check, not independent review.
- If the split is unclear and guessing wrong would waste real work, ask once before starting the chain.

Common chains — each runs only as far as the request goes: `planner → implementer` · `explorer → debugger` · `ui-ux-designer → implementer` · `researcher → architect → planner` · `product-manager → ui-ux-designer`. Append `→ tester` or `→ reviewer` only when the user asked for the work to be verified or checked.

## Delegating to subagents

When the host permits fan-out, route each subagent's job the way you route your own turn:
read [ROLES.md](ROLES.md) for **that job**, not for the turn that spawned it. Use the host's
available subagent mechanism; do not assume another host's tools or built-in agent types
exist. If delegation is unavailable, work sequentially. Never create user-visible tasks
for internal subtasks.

- **Name the role and give the path.** Do not assume a subagent inherits the needed context.
  Its prompt carries the role, its absolute file path, scoped job, concrete inputs (files,
  revision, diff range), deliverable and return shape, and exclusions. Resolve PACK from
  the dispatcher SKILL.md already in use; confirm `PACK/roles/<id>.md` exists before sending it.
  A guessed installation path can silently leave the subagent without its role.
- **Never point several subagents carrying your own role at the same evidence.** That returns N versions of one blind spot, not N opinions. The same role many times over *disjoint* slices is right and often the point — one `explorer` per package, one `reviewer` per directory, independent attempts you intend to compare, a round that repeats until it comes back empty. Say in each prompt which slice, attempt, or round it owns.
- **A verifier must not carry the role that produced the work.** `implementer` writes, `reviewer` or `tester` judges. Name the artifact and revision under judgement in the verifier's prompt and say it is judging another agent's output. Work your own session produced is still a self-check when a subagent reviews it — tell the user that.
- **Give different lenses on purpose** when a finding can fail in more than one way: `security-auditor` and `performance-engineer` on one diff see different things.
- **A mechanical job gets no role.** One grep, one fetch, one command whose output you will read yourself — a plain prompt. Roles are for judgement; don't spend a role file on a tool call.
- **A built-in agent type that fits better wins**, when this host actually provides one
  (for example, a search or repo-specific review agent). It replaces the role: no role
  name or path in that prompt. Otherwise carry the role on a general-purpose subagent.
- **An installed skill or workflow that defines its own subagents keeps its prompts.** Don't inject roles into `code-review`, a `gsd-*` command, or anything else that already encodes its fan-out. This section is for fan-outs you author.
- **One role per subagent**, unless the job is a short chain you would have run yourself — then name the chain explicitly (`explorer → debugger`, both paths in the prompt). A job needing three roles is scoped too large.
- **Never hand a subagent the `dispatcher` role.** A workstream that needs its own split comes back to you for the split; it does not sub-dispatch.
- The three-role ceiling counts chain hops in your own turn. Parallel subagents are not chained and don't count against it — a fan-out is as wide as the work is separable.
- Under a forced role, fan out **that** role over disjoint slices rather than routing around the user's instruction. Only the verifier is exempt.

### The handoff

Build the subagent its **own** context plan, for its job — not a copy of yours, and not the
conversation that produced it. Its prompt carries: the **objective**, its **scope**, the **decisions
already accepted** so they are not relitigated, the **evidence** it needs, the **artifacts it owns**,
its **constraints** and **dependencies**, the **expected output**, the **acceptance checks**, the
**verification** expected of it, and the **open questions** it is not expected to settle. What comes
back adds: the verification actually performed, and what remains **unresolved**.

Pass the smallest context that is sufficient. Conversation history is transcript, not context — do
not dump it into a handoff, and do not make a two-line job carry a ten-field contract. The ceremony
is for work that warrants it; [CONTEXT.md](CONTEXT.md) explains context building and
[CONTEXT-REFERENCE.md](CONTEXT-REFERENCE.md) supplies the full plan schema and example.
