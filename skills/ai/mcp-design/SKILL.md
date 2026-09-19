---
name: mcp-design
description: Build an MCP server, or bring an existing one into a project — choosing the transport, deciding which tools, resources and prompts to expose, keeping reads separate from writes, handling auth and credentials, and defining what failure looks like to the model. Use when writing an MCP server, wrapping an internal system as one, or evaluating a third-party server before wiring it in. Not for designing the individual tool signatures inside it (tool-design), and not authorization to install, configure or run any server against real systems.
---

# MCP server design

An MCP server is a permission surface wearing an API's clothes. Whatever it exposes, the model can
call; whatever the process can reach, the server can be asked to touch. Design the boundary first
and the tool list second.

## When this fires

Writing an MCP server, wrapping an internal service as one, or assessing a third-party server
before it is added to a project. It does not fire for defining the parameters of a single tool —
that is `tool-design` — nor for ordinary client code that happens to call an API.

## Procedure

1. **Establish why this is a server at all.** A capability the agent uses in one repo, with the
   files already on disk, is a script or a skill. MCP earns its place when the capability is reused
   across projects or clients, needs its own credentials, or must run somewhere the agent is not.
2. **Pick the transport from where it runs.** Local process on the user's machine, launched by the
   client and speaking over stdio: simplest, credentials come from the environment, nothing listens
   on a port. Remote server over HTTP: needed for a hosted or shared service, and it brings network
   exposure and real authorization with it. Check the current MCP specification for which HTTP
   transport is current rather than copying an old example — earlier transports have been
   superseded.
3. **Draw the capability surface deliberately.** Tools are model-invoked actions. Resources are
   readable context the client can attach. Prompts are user-invoked templates. Put passive lookups
   behind resources instead of inflating the tool list, and expose the smallest set that does the
   job; every extra tool costs selection accuracy for every task, including the ones that never
   touch it.
4. **Separate reads from writes explicitly.** Name them so the difference is visible in the list,
   and ship a read-only mode — a flag, a scoped token, or a separate entry point — that the server
   itself enforces. A read-only *intention* is not a read-only server.
5. **Scope credentials down before the first call.** The server gets its own least-privileged
   credential, not the user's admin token. Never read secrets out of the model's arguments. Keep
   credentials in the environment or a secret store, never echoed back in a tool result, a log line
   or an error message. For anything remote, follow the specification's authorization model rather
   than inventing a header scheme.
6. **Treat every input as coming from a model that may be steered.** Arguments are untrusted:
   allowlist paths, table names, commands and hosts; parameterize queries; bound page sizes and
   result counts. Text fetched from outside — a page, an issue body, a file — is data the model will
   read, and it may contain instructions. Return it plainly labelled as content; never let the
   server act on instructions it finds in the data it retrieved.
7. **Define failure semantics as part of the contract.** Distinguish not-found from unauthorized
   from upstream-down from bad-argument, and return each as a readable result the model can act on
   rather than a crash that kills the session. Set timeouts on every upstream call. Say in the
   result when output was truncated, and how to fetch the rest.
8. **Make destructive and outward-facing operations stop.** Deleting, sending, publishing, merging,
   deploying, charging: the tool description says so, the operation is confirmable by the human, and
   where the client offers a confirmation or annotation mechanism, use it. The server never treats
   its own availability as consent. Prefer reversible: soft-delete, dry-run parameters, a diff
   returned before the change is applied.
9. **Prove it against the real client, not just a unit test.** Start the server, connect the client
   the user will actually use, list the capabilities, and call each tool once — success, empty
   result, denial, and a deliberately malformed argument. Read what the model received, not what
   your handler returned.
10. **When evaluating someone else's server, read before installing.** Who publishes it, what
    licence, is it maintained, which tools write, does it offer a read-only mode, what credential
    does it want and what does that credential let it do. Installing, configuring or pointing a
    server at production is the user's decision — present the assessment and ask.

## Checklist

- [ ] The case for a server over a script or skill is stated
- [ ] Transport chosen for where it runs, against the current specification
- [ ] Capability surface minimal; passive lookups are resources, not tools
- [ ] Read and write tools visibly separated, with an enforced read-only mode
- [ ] Least-privileged credentials, sourced from the environment, never in results or logs
- [ ] Every argument allowlisted or parameterized; outputs bounded
- [ ] Retrieved external text returned as data, never executed as instruction
- [ ] Not-found, unauthorized, upstream-failed and malformed are four distinct results
- [ ] Destructive operations labelled, reversible where possible, and confirmed by a human
- [ ] Exercised through the real client, with the transcript read

## Failure handling

- **Client will not connect** — check transport mismatch and startup errors first. On stdio, anything
  the server prints to stdout that is not protocol traffic corrupts the stream; log to stderr.
- **Tools list but calls fail** — usually credentials or scope, not protocol. Check what the token
  can actually do before changing the code.
- **The model picks the wrong tool or drowns in output** — that is a surface problem: too many
  tools, overlapping descriptions, or unbounded results. See `tool-design`.
- **An upstream call hangs** — a server without timeouts hangs the whole session. Bound it, and
  return a distinguishable timeout result.
- **You cannot confirm a protocol feature exists** in the version you are targeting — read the
  specification or the SDK's current docs. Do not implement against a remembered field name.

## Evidence to report

The transport and why. The full capability list, marked read or write, with the read-only mode and
how it is enforced. The credential and its scope. A transcript per tool showing success and at least
one failure path as the model saw it. For a third-party server: source, licence, maintenance,
whether it writes, and the pending question of whether the user wants it installed. Keep the verbs
honest — written, executed once, covered by a test, and connected to a real system are four
different claims.
