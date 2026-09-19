---
name: tool-design
description: Design the tools a model calls — names, parameter shapes, what a result returns, and error text written as an instruction the model can act on. Use when adding or reshaping a tool or function an LLM invokes, when an agent keeps calling the wrong tool or passing malformed arguments, or when reviewing a tool surface someone else defined. Not for building the MCP server that hosts the tools (mcp-design), not for forcing a model's final answer into a schema (structured-output), and not for prompt wording outside the tool definition.
---

# Tool design

A tool definition is a prompt. The model never sees your implementation — it sees the name, the
description, the parameter schema, and whatever came back last time. Most "the model is bad at
using tools" is a tool that told the model the wrong thing.

## When this fires

Adding a tool to an agent, changing an existing tool's parameters or return value, or diagnosing
an agent that picks the wrong tool, passes bad arguments, loops, or stalls after a call. It does
not fire for an internal function no model ever invokes.

## Procedure

1. **Start from the task, not the API.** List the things the agent must accomplish, then define one
   tool per accomplishment. A thin one-to-one wrapper over an existing HTTP API pushes the
   orchestration into the model, which pays for it in extra turns and wrong guesses. Prefer one
   `schedule_meeting` over `list_calendars` + `get_availability` + `create_event` unless the agent
   genuinely needs the intermediate steps.
2. **Count the tools.** A large, overlapping surface is the main cause of wrong-tool selection. If
   two tools could plausibly answer the same request, either merge them or make each description
   state explicitly when the *other* one is correct.
3. **Name it for what it does, from the caller's side.** Verb plus object, unambiguous when read
   alone in a list: `cancel_order`, not `order_v2` or `process`. Names sharing a prefix by domain
   (`docs_search`, `docs_create`) help the model group them; near-identical names across domains
   defeat it.
4. **Write the description to be selected correctly, not to be complete.** First line: what it does
   and when to reach for it. Then the boundary — what it does *not* do and which tool covers that
   instead. Then anything non-obvious: required ordering, what must be fetched first, side effects.
   Write it for a competent stranger with no access to your codebase.
5. **Shape parameters so a wrong call is hard to express.** Flat over nested. Enums over free
   strings whenever the set is known. Explicit types, formats and units in the field description
   (`"ISO 8601 date, e.g. 2026-03-01"`, `"amount in minor units"`). Required only what is truly
   required; every optional parameter is another thing to get wrong. Never accept a raw query
   language, a SQL string or a path the model composed unless the implementation constrains it.
6. **Do not make the model supply what you already know.** Ids from the session, the current user,
   the project root, an auth token — bind them server-side. A parameter the model must invent is a
   parameter it will eventually hallucinate.
7. **Return what the model needs for the next step, and cut the rest.** Resolved human-readable
   values over opaque ids; the fields that drive a decision over the full record. On a paged or
   truncated result, say so in the payload and say how to get more. A response that blows the
   context window is a failed call, even when the API returned 200.
8. **Write errors as instructions.** "Invalid request" teaches nothing. "No customer with id 'X';
   search by email with `find_customer` first" gets the next call right. Name what was wrong, what
   is valid, and what to do now. Return it as a normal tool result the model can read and act on —
   a thrown exception that never reaches the model turns a recoverable mistake into a dead turn.
9. **Distinguish empty from broken.** Zero results, a permission denial, an upstream outage and a
   malformed argument must be four distinguishable responses. Collapsing them makes the agent retry
   the same call forever or give up on data that exists.
10. **Make the destructive ones announce themselves.** A tool that deletes, sends, publishes,
    charges or deploys says so in its first sentence, and the agent stops and asks before it fires.
    A tool description never grants the permission — it only makes the consequence visible. Where
    the operation can be repeated, give it an idempotency key rather than hoping for one call.
11. **Exercise it before believing it.** Give the model five to ten realistic requests, including
    the ambiguous ones and the ones that should select a *different* tool, and read the actual
    calls: which tool, which arguments, what it did with the result and with the error. Fix the
    description and the schema, not the prompt around them, and run the set again.

## Checklist

- [ ] Each tool maps to a task the agent must accomplish, not to one endpoint
- [ ] No two tools plausibly answer the same request without saying which wins
- [ ] Names readable in isolation; descriptions state when *not* to use the tool
- [ ] Enums and formats used wherever the value set is known; units stated
- [ ] Nothing required from the model that the server already knows
- [ ] Results carry the fields the next step needs, truncation is declared, size bounded
- [ ] Every error names the cause and the corrective action, and reaches the model as a result
- [ ] Empty, denied, upstream-failed and malformed are distinguishable
- [ ] Destructive and outward-facing tools are labelled, and stop for confirmation
- [ ] Run against realistic requests, wrong-tool cases included, and the transcripts read

## Failure handling

- **Wrong tool chosen** — a description problem before a model problem. Add the boundary sentence
  to both tools. Overlap that cannot be written away should be a merge.
- **Malformed or invented arguments** — tighten the schema first (enum, format, fewer optionals),
  then the field descriptions. A retry prompt that patches a loose schema will keep paying for it.
- **The agent loops on the same call** — the error text is not actionable, or success and empty
  look alike. Read the exact tool result the model saw, not your log line.
- **It works in your handful of examples** — that is *executed*, not *tested*. A tool surface is
  tested when a fixed set of requests runs against it and asserts the selected tool and arguments.
- **Unsure whether the framework supports a schema feature** you want to rely on — check its current
  documentation rather than assuming. Silently dropped schema keywords fail as bad model behaviour.

## Evidence to report

The tool list with each name, one-line purpose, and the boundary it cedes. The full schema of every
added or changed tool. Real transcripts: the request, the tool chosen, the arguments, the returned
payload, and at least one error path showing the model recovering. What was merely defined, what was
executed once, and what has a repeatable selection check behind it.
