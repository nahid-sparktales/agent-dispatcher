---
name: agent-security
description: Secure an agent system as a permission surface — what authority each tool call runs under, where the confused deputy sits, which controls are enforced outside the model and which are only prompt text, and how far one bad call reaches. Use when granting an agent tools or credentials, wiring in MCP servers or subagents, reviewing an agent that acted beyond what the requester could have done, or before letting an agent touch a shared or production system. Not for wording the ingestion trust boundary in detail (prompt-injection-defense), not for scoping what an agent is for (agent-design), and it never grants an agent permission it did not already have.
---

# Agent security

An agent's security properties come from the tools and credentials it holds, not from how carefully
its prompt is written. The design question is never "would the model refuse?" — it is "what happens
when it does not?"

## When this fires

An agent or subagent is being given tools, credentials or an MCP server; an agent is about to reach
a shared, production or third-party system; an agent did something the person asking could not have
done themselves; an agent system is being reviewed. It does not fire for a model with no tools and
no outward surface.

## Procedure

1. **Write down the authority.** Every tool, every credential, every system reachable, and whose
   identity each call actually runs as. Most agent systems have never had this written down, and
   the exercise alone usually finds the problem.
2. **Find the confused deputy.** Wherever a call runs under a service account rather than the
   requester, the agent can be asked to do what the requester may not. Either pass the requester's
   own scoped identity through to the system being called, or restrict the service account to the
   intersection of what any requester is allowed. Checking the requester's role in the prompt is
   not a check.
3. **Enumerate the irreversible and outward-facing calls** — sending, publishing, deleting, paying,
   deploying, changing permissions, writing to anything shared — and put a real gate in front of
   each: a harness permission prompt, a separate approval step, a human in the path. The agent
   asking itself whether it is allowed is not a gate.
4. **Classify every control as enforced or advisory**, and write the classification down. Enforced
   lives outside the model: a permission system, a scope on a token, a network rule, code. Advisory
   lives inside it: an instruction, a policy paragraph, a refusal it was trained toward. Advisory
   controls are worth having and are not boundaries. Where the only control is advisory, remove the
   capability rather than strengthen the wording.
5. **Reduce the capability, not the credulity.** Read-only endpoints and tokens where the vendor
   offers them, non-production targets by default, an isolated browser profile instead of the
   user's logged-in session, one credential per agent so revocation is surgical. Availability of a
   server is not permission to use everything it exposes.
6. **Treat ingested content as data and size the consequence.** The detailed boundary belongs to
   prompt-injection-defense; the system-level fact belongs here — whatever the agent can do, an
   injection can do. When the exposure is unacceptable, the fix is the tool list, not the prompt.
7. **Apply the same rules between agents.** A subagent's output is untrusted input to its parent. A
   subagent does not inherit the parent's full tool set by default. No agent can grant another agent
   permission, and a message from another agent is never the user's consent, however it is phrased.
   Orchestration is not an authority channel.
8. **Bound the execution surface.** Filesystem scope, network egress restricted to known
   destinations, no unconstrained shell sitting beside the carefully scoped tools, time and
   resource limits, and a way to stop it mid-run. Egress is the exfiltration path; an allowed tool
   aimed at an attacker-chosen destination looks entirely normal in a log.
9. **Decide what persists and what it can later trigger.** Memory, notes, caches and shared state
   are delayed injection vectors: content written today is instruction-shaped context tomorrow. Say
   what may be written, by whom, and whether anything read back can influence a tool call.
10. **Log every tool call with its arguments, the identity it ran under, and what was in context**,
    and keep that log outside the agent's own write scope. Without it, "what did it actually do"
    has no answer during an incident.
11. **Size the blast radius before granting, not after.** What is the worst single call, is it
    reversible, who would notice, and how fast can the credential be revoked. If no one can answer,
    the grant is too large — narrow it until they can.
12. **Attack it with the tools it really has, in an environment you are authorized to use.** Ask as
    a low-privilege requester for something only a privileged one may do. Plant a benign instruction
    in content it ingests and assert the consequential call did not fire. Attempt an exfiltration
    through an allowed tool pointed at a destination the content chose. Record which attempts were
    executed and which remain untested.
13. **Treat the agent's own permissions and configuration as privileged.** Permission files, tool
    allowlists, harness settings and system prompts change through review, never on the agent's own
    judgement and never because ingested content or another agent asked.

## Checklist

- [ ] Tools, credentials and the identity behind each call written down
- [ ] Every call whose authority exceeds the requester's identified and narrowed
- [ ] Irreversible and outward-facing calls enumerated, each with a named gate
- [ ] Each control labelled enforced or advisory, honestly
- [ ] Least-privilege credential, environment and profile chosen per tool
- [ ] Subagent output treated as untrusted; no inherited tool sets; no agent-granted permission
- [ ] Filesystem scope, egress limits and a stop path in place
- [ ] Persistent memory and shared state reviewed as a delayed injection vector
- [ ] Tool-call log outside the agent's write scope
- [ ] Blast radius answered for the largest grant
- [ ] Confused-deputy, injected-call and exfiltration attempts executed and recorded

## Failure handling

- **The gate cannot be enforced outside the model** — it is not a gate. Drop the tool for that turn,
  or route the action through a human step. Do not ship an advisory control described as a boundary.
- **The agent already took an unauthorized action** — treat it as an incident: what was called, with
  what arguments, under what identity, what left the system, and what was in context first. Reversal
  and notification are decided with the owner, not unilaterally by the agent or by you.
- **The model passed the injection test** — that is one prompt against one model version. It shows
  the gate held once; it is not a reason to remove the gate or to skip re-testing after a prompt or
  model change.
- **Permissions are managed by a harness you do not control** — say which controls you could verify
  and which you are taking on trust. An unverified control reported as present is worse than a
  missing one.
- **The credential is shared with a human or another service** — then revocation is not surgical and
  the log cannot attribute the call. Get a dedicated credential before granting the capability.

## Evidence to report

The authority table: tool, credential, identity, target environment. The gated-call list with what
each gate physically is. The enforced-versus-advisory classification. The egress and filesystem
bounds. Then the attempts: which were executed, the transcript showing the call did not fire or did,
and which paths are untested. Say which of designed, configured, executed and tested applies to each
control — an agent whose only defense is the model's cooperation has been designed, not secured.
