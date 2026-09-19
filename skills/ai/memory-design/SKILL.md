---
name: memory-design
description: Decide what an agent should remember, which layer holds it, who it is scoped to, and how a stale or contradicted memory is detected and retired. Use when an agent forgets something across sessions, when a memory or persistent-context feature is being designed, or when stored memories have grown noisy, wrong, or are leaking between users. Not for retrieval over a document corpus, not for prompt or context-window packing, and not for conversation transcript storage.
---

# Memory design

Memory is the only part of an agent that keeps being wrong after you stop looking. A retrieval bug
shows up in the next answer; a stale memory sits there being quietly confident for months. Design
the retirement path before the write path.

## When this fires

An agent needs a fact to survive past the current context — across turns, tasks or sessions — or
an existing memory store has grown noisy, contradictory, or is surfacing one subject's data to
another. It does not fire for retrieval over a document corpus (that is retrieval-rag), and not
for keeping a transcript: a transcript is a log, not memory.

## Procedure

1. **Name the repeat failure first.** What did the agent forget, how often, and what did it cost —
   a re-asked question, a redone decision, a wrong assumption. Memory added without a named repeat
   failure is speculative storage, and storage you cannot justify is storage you will not prune.
2. **Classify what is actually worth keeping**, because the class decides everything after it:
   - *stable facts and preferences* — this user's stack, conventions, how they want to be addressed
   - *decisions and their rationale* — true until explicitly reversed, and the rationale is the
     part that matters later
   - *working state* — what this task is mid-way through; it dies with the task
   - *derived summaries* — regenerable from the source; store only when regeneration is expensive
   Everything else is a log. Do not promote a log to memory.
3. **Put each class in the shallowest layer that holds it.** Working state belongs in a task file
   or thread state, not a long-term store. Stable facts and decisions belong in a durable record.
   If the store is a vector index, it is a retrieval system and inherits the retrieval-rag
   procedure, including the requirement to measure recall — unevaluated vector memory is a wish.
4. **Scope every record explicitly** at write time: the subject it is about (this user, this
   project, this repository, this organization) and who may read it. Default to the narrowest
   scope. Widening a memory's scope so it crosses users or tenants is a data boundary change —
   raise it and get an explicit decision, do not infer permission from convenience.
5. **Write memories as assertions with provenance**, not as free prose: the claim, when it was
   learned, what it was learned from (session, message, file, commit), and what would make it
   false. A memory with no source cannot be retired safely, because nothing can be checked against
   the thing it came from.
6. **Choose the write trigger deliberately.** Writing on every turn produces noise that buries the
   few records that matter. The triggers that earn a write: the user says to remember, a decision
   is settled, a correction is issued, or a fact was expensively discovered. A user correcting the
   agent is the highest-value write there is — never drop one.
7. **Refuse to store secrets and sensitive personal data.** Credentials, tokens, keys, payment and
   identity data do not go into memory, even when they appeared in the conversation. If one is
   already stored, stop and tell the user rather than quietly acting on it.
8. **Check for staleness at read time, not only on a schedule.** Three detectors, cheapest first:
   *contradiction* — a new statement conflicts with a stored one; *expiry* — the record was
   time-boxed at write (current sprint, active branch, "for now"); *reference decay* — it names a
   file, person, project or setting that no longer exists. Verify a load-bearing memory against
   the live source before acting on it.
9. **Supersede rather than silently overwrite.** The replacing record points at what it replaced
   and says why. History of a reversed decision is often more useful than the decision.
10. **Treat deletion as destructive.** Retiring or clearing memory the user gave you removes
    something they may be relying on. Propose the retirement with the list of what would go, and
    ask. Never bulk-delete a memory store to fix a formatting problem.
11. **Bound the store and measure usefulness.** Set a cap and an eviction rule based on when a
    record was last *read*, not when it was written. Track what fraction of stored memories have
    been read at all in the last N sessions; a large unread tail is cost with no return, and it is
    the signal to tighten the write trigger from step 6.
12. **Exercise the full loop before calling it done**: write a memory, start a genuinely fresh
    session, confirm it is retrieved and used. Then change the underlying fact and confirm the old
    record is superseded rather than duplicated, and that the new answer reflects the new fact.

## Checklist

- [ ] The repeat failure this memory exists to fix is named
- [ ] Each stored class mapped to a layer, with working state kept out of the durable store
- [ ] Every record carries subject scope and read visibility
- [ ] Every record carries source, timestamp, and a falsification condition
- [ ] Write triggers are explicit; corrections are always captured
- [ ] Secrets and sensitive personal data excluded at the write path
- [ ] Contradiction, expiry and reference-decay checks run before a memory is acted on
- [ ] Supersession preserves what was replaced and why
- [ ] Deletion is proposed to the user, never performed silently
- [ ] Cross-session round trip exercised, including the changed-fact case

## Failure handling

- **Two memories contradict each other** — do not pick by recency alone. Check both against the
  live source; if it cannot be resolved, surface the conflict to the user rather than acting on a
  coin flip.
- **The agent recalls a fact that is no longer true** — the defect is in the retirement path, not
  in retrieval. Fix the expiry or contradiction detector; deleting the one bad record leaves the
  next one to be found by the user.
- **A memory from one subject surfaced under another** — stop, treat it as a data exposure, report
  it with the scope that was wrong. Do not continue the feature work first.
- **The store is large and nothing is measurably better** — that is a result. Report the unread
  fraction and propose narrowing the write trigger.
- **No durable store is available in this environment** — say so, keep the fact in the task's own
  working state, and do not describe behaviour as persistent when it is not.

## Evidence to report

The classes stored and the layer each lives in; a sample record showing scope, source, timestamp
and falsification condition; the write triggers as implemented; the staleness checks that run and
where they run; the cross-session round trip actually performed, including the changed-fact case,
with what was recalled; and the read-rate of the store if it has been running long enough to have
one. "It remembers now" without a fresh-session round trip is a claim, not evidence.
