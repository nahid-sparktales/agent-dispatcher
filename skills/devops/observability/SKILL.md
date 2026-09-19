---
name: observability
description: Instrument a service so the questions asked during an incident are answerable from data already being collected — rate, errors, latency distribution and saturation per route, structured events carrying a correlation id that survives process and queue boundaries, and alerts on symptoms users feel. Use before a service or a new critical path goes to production, after an incident that ended in "we had no data for that", or when adding a dependency, queue or job whose failure would be silent. Not for fighting a live outage (incident-response), not for profiling a known-slow path (performance-profiling), and not for tracing agent or LLM runs (llm-observability).
---

# Observability

Telemetry is written before the incident and read during it. A dashboard nobody had a question for
is a screensaver; a log line nobody can correlate is a receipt for an event you cannot find.

## When this fires

A service is about to carry real traffic, a new critical path is added, or a review asks how a
failure here would be noticed. It fires hardest immediately after an incident where the answer was
not in the data — that is the only moment the gap is precisely known.

It does not fire for a live outage (mitigate first), for a slow path you can already reproduce and
measure, or for LLM/agent run traces.

## Procedure

1. **Write the questions down first.** "Is it up, is it wrong, is it slow, which dependency, which
   deploy, which tenant." Each signal you add answers a named question. Instrumentation added
   without one becomes cost and noise that later gets sampled away.
2. **Cover every request path with four numbers**: request rate, error rate, duration distribution,
   and saturation of whichever resource is actually constrained (connections, workers, memory, queue
   depth). Per route, job and consumer — a global error rate hides one broken endpoint completely.
3. **Emit structured events, not prose.** One event per unit of work, with stable field names:
   timestamp, service, version, environment, correlation id, route or job name, outcome, duration,
   error class. A field you can filter on beats a sentence you have to regex.
4. **Propagate one correlation id everywhere** — inbound request, outbound calls, log lines,
   emitted messages, and the background job that consumes them. Most traces die at the queue
   boundary, which is exactly where the unexplained latency lives.
5. **Instrument the boundaries you do not control**: database, cache, third-party APIs, queues.
   Record attempt, outcome, duration and retry count separately from the caller's total. Use the
   tracing library the project already depends on rather than inventing a span format, and check
   its current API instead of recalling it.
6. **Record distributions, not averages.** Keep p50/p95/p99 plus count. Percentiles cannot be
   recovered from a mean after the fact, and the tail is what the complaint is about.
7. **Bound label cardinality deliberately.** User id, email, session, full URL and raw paths
   containing ids do not belong in metric labels — they belong in logs and traces. Write the
   allowed label values per metric; an unbounded label is the usual cause of a telemetry bill.
8. **Redact at the boundary, before anything leaves the process.** Decide per field: kept, hashed,
   truncated, dropped. Authorization headers, cookies, tokens, request bodies and payment data are
   dropped. Exporting telemetry to a third-party backend is a data-export decision — raise it, do
   not enable it as a default.
9. **Separate liveness, readiness and dependency health.** A check that returns 200 because the
   process is alive, while its database is unreachable, teaches the load balancer to keep sending
   traffic to a broken instance.
10. **Instrument the silent failures by name**: retries, timeouts, queue depth *and age*, dead
    letters, dropped messages, circuit-breaker state, cache hit rate, job lag, clock skew. Nothing
    pages when a backlog grows unless something counts it.
11. **Carry version and deploy identity in the telemetry** so "which release" is answerable by
    filtering rather than by asking in chat.
12. **Alert on symptoms users feel** — error rate, latency against the stated objective, queue age —
    not on causes like CPU. Each alert names the first thing the responder should do and links the
    query behind it. An alert nobody can act on gets muted, and the mute outlives the reason.
13. **Propose thresholds; do not arm them.** Creating alert rules, dashboards, retention or sampling
    policy changes shared production configuration and usually costs money. Write the rule and the
    query, then stop and ask before creating anything in the account.
14. **Drill it before you need it.** In a non-production environment force an error, a dependency
    timeout and a slow request, then answer the step-1 questions using only the queries and
    dashboards. Every question you could not answer is the gap — fix it now, not at 3am.

## Checklist

- [ ] The questions this telemetry answers are written down
- [ ] Rate, errors, duration distribution and saturation exist per route and per job
- [ ] Events are structured with stable field names, including version and environment
- [ ] A correlation id crosses process, HTTP and queue boundaries end to end
- [ ] External calls and retries are timed separately from the caller
- [ ] Percentiles recorded, not averages
- [ ] Metric labels bounded; no user-level identifiers in label sets
- [ ] Redaction decided per field; third-party export raised rather than assumed
- [ ] Queue age, retries, timeouts and dead letters are counted
- [ ] Alerts are symptom-based and each links its query and first action
- [ ] The failure drill was run and the unanswered questions listed

## Failure handling

- **All signals green, users complaining** — you are measuring the wrong point. Move measurement
  closer to what the user experiences, past the load balancer, CDN and client.
- **Telemetry cost spiked** — look for an unbounded label or a debug-level log left on in
  production before touching sampling.
- **Trace stops halfway** — context is not propagating across an async, queue or thread boundary.
  Fix the propagation; a partial trace invites a confident wrong conclusion.
- **Nothing was recorded for the window that mattered** — sampling or retention dropped it. Say
  that plainly. Do not reconstruct the window from what seems likely.
- **No telemetry backend available** — instrument to structured local logs with the same field
  names and say so. Local output is not evidence about production behaviour.

## Evidence to report

Name what was **instrumented** (code emitting signals), what was **observed** (a real event or
query result you read back), and what remains untested — these are different claims. Quote one
emitted event with its real field names, and the query that returns it. Give the drill result as a
list of the step-1 questions with answered / not answered against each. List alerts **proposed**
separately from any **created**, and who approved the ones created. Code that compiles but has not
been seen to emit anything is instrumented, not verified.
