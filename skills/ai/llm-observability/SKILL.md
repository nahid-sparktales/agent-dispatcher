---
name: llm-observability
description: See what an agent actually did — one trace per run with nested model, tool and retrieval spans, token and latency accounted per step, and failures clustered by mechanism instead of read one at a time. Use when an agent misbehaves in ways you cannot reproduce, when cost or latency is unexplained, when "it sometimes fails" is the whole bug report, or before writing evals when you do not yet know which failures exist. Not for judging whether an output is correct (agent-evals), and not a replacement for the application's own monitoring.
---

# LLM observability

An agent run is a tree of decisions, most of which nobody saw. Without a trace you are left
re-running the prompt and hoping the failure happens again while you watch.

## When this fires

A failure that will not reproduce, a cost or latency number nobody can account for, a "sometimes"
bug, or the start of eval work where the failure modes are still unknown. It does not fire for a
single deterministic call whose input and output you already hold.

## Procedure

1. **State the question first.** "Why did run X do Y", "where is the cost going", "which failures
   share a cause". Instrumentation added without a question becomes expensive noise nobody reads.
2. **One trace per run, nested by causality.** The run is the root; each model call, tool call,
   retrieval and retry is a child span in the place it actually happened. A flat log of lines loses
   the one thing you need — which step caused which.
3. **Record per span what cannot be reconstructed afterwards**: model id, prompt or system-prompt
   version, sampling parameters, input and output token counts, stop reason, tool name and
   arguments, result size, error class, retry index, cache hit, and the latency of that span alone.
   If the project already has a tracing library, use it rather than inventing a format; check its
   current API rather than recalling it.
4. **Give every run an id the user can quote.** Surface it in the UI, the log line and the error
   message, so a report maps to a trace instead of to a time range and a guess.
5. **Redact at the boundary, before anything leaves the process.** Prompts, retrieved documents and
   tool arguments carry user data, credentials and PII. Decide per field: stored in full, hashed,
   truncated or dropped. Sending raw prompts to a third-party backend is a data-export decision —
   it stops and asks rather than being enabled as a default.
6. **Account tokens where they are spent.** Per run, then per step. The useful unit is cost per run
   and per step, not per token; the largest line is usually conversation history re-sent each turn,
   retrieved context, or retries nobody counted.
7. **Split latency before attributing it.** Time to first token, time in the model, time in tools,
   time waiting on retries and rate limits. An agent's slow tail is normally one step's worst case
   plus a retry, and the aggregate hides both.
8. **Sample deliberately and say how.** Keep every failure; keep a stated fraction of successes.
   Sampling by what looked interesting produces a corpus that confirms whatever you suspected.
9. **Cluster failures rather than reading them individually.** Group by error class, failing tool,
   stop reason (length cap, refusal, parse failure, tool error), step index and prompt version. Then
   read a few from each cluster. Name each cluster by mechanism — "the model emits prose around the
   JSON when the retrieved chunk is empty" — not by symptom.
10. **Reproduce from the trace.** Replay the recorded inputs into the same configuration. If the
    trace does not contain enough to replay, that gap is the finding: fix the instrumentation before
    theorising about the bug.
11. **Hand the clusters to evals.** Each named mechanism becomes cases in the eval suite. A cluster
    you merely explained will come back.
12. **Propose thresholds; do not arm them.** Error rate, p95 latency and cost per run are worth
    alerting on, but creating alert rules, dashboards or retention settings changes shared
    production configuration — write the proposed thresholds and ask before creating them.

## Checklist

- [ ] The question the instrumentation answers is written down
- [ ] Runs produce one nested trace, not a flat log
- [ ] Spans carry model, prompt version, tokens, stop reason, tool arguments, retries, errors
- [ ] A run id is visible wherever a user or log can quote it
- [ ] Redaction decided per field, with any third-party export raised rather than assumed
- [ ] Tokens and cost attributed per step, not just per run
- [ ] Latency split into first-token, model, tool and retry time
- [ ] Sampling policy stated; all failures retained
- [ ] Failures clustered and each cluster named by mechanism
- [ ] At least one failure replayed from its trace

## Failure handling

- **The trace cannot explain the run** — a field is missing. Add it and wait for the next
  occurrence; do not close the bug with the most plausible story.
- **Nothing reproduces on replay** — check what the replay did not restore: retrieval results,
  tool responses, time, sampling seed, conversation state. An unexplained non-reproduction is a
  finding, not a fix.
- **Cost jumped with no code change** — look at context size and retry counts before the model.
  Growing history and a silently retrying step are the usual causes.
- **One cluster dominates everything** — fix it and re-cluster. The second-largest cause is
  routinely invisible underneath the first.
- **No tracing backend available** — instrument to structured local logs with the same span fields
  and say so. Report that production behaviour was not observed; do not describe local runs as
  production evidence.

## Evidence to report

Quote run ids and the span path that led to the failure. Give the cluster table: mechanism, share of
failures, the sample size it was computed from, and the window it covers. Give token and latency
numbers per step with their units, not a total with an adjective. Say which conclusions came from
**observed** traces and which from a **replayed** run, and name the failures still unexplained —
an unexplained cluster reported as unexplained is a result; one quietly dropped is not.
