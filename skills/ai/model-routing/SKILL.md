---
name: model-routing
description: Pick a model per job and degrade sensibly when one fails — a quality bar per call site, candidates compared on the same task set, a readable routing rule, and an explicit retry-versus-fallback path with pinned model ids. Use when cost or latency has become a problem, when adding a cheaper or larger model to an existing system, or when a fallback fires silently and quality drops without anyone noticing. Not for prompt authoring, not for retrieval tuning, and not for capacity or infrastructure planning.
---

# Model routing

Routing is a claim that one job needs less than another. That claim is either measured or it is a
guess with a billing line attached. The expensive mistake is not picking the wrong model — it is
switching models and having no way to notice what got worse.

## When this fires

A system calls more than one model, or is about to, and someone needs to decide which call goes
where and what happens when a call fails. It also fires when a fallback exists and nobody can say
how often it triggers. It does not fire for a single call site with no cost or latency pressure —
there, one capable model and no routing layer is the correct design.

## Procedure

1. **Enumerate the jobs, not the models.** Each call site is a job with its own latency budget,
   output shape, error tolerance, and whether a human sees the output before it has an effect.
   Routing decisions belong per job; a single global "which model do we use" question has no
   answer.
2. **Write the quality bar for each job before looking at any candidate.** What output counts as
   acceptable, and how that is checked: exact match, schema validity, a rubric, a graded sample,
   human spot check. Without a bar, "the cheap one is fine" is an opinion that cannot be argued
   with or refuted.
3. **Do not build a routing layer before there is a measured problem.** One capable model
   everywhere, instrumented for cost and latency per job, is the right starting point. Routing
   added on anticipation is a permanent source of drift for a saving nobody has sized.
4. **Build a task set per job** — 20–50 real inputs with known-acceptable outputs, drawn from
   production traffic where possible, including the awkward ones. Every candidate is judged on the
   identical set; a candidate evaluated on its own examples proves nothing.
5. **Run each candidate against it and compare in this order**: pass rate against the bar first,
   then latency, then cost per *accepted* output. Cost per token is the wrong unit — a cheap model
   that fails a third of the time and needs a retry, a repair pass, or a human is not cheap.
6. **Re-tune the prompt per candidate before concluding.** A prompt shaped around one model's
   habits can fail on another for reasons that have nothing to do with capability. If you did not
   re-tune, say the comparison is provisional.
7. **Route on observable properties of the request**: input size, whether structured output is
   required, whether tools are called, whether the result is user-facing, whether a human reviews
   it. Keep the rule as a readable table mapping condition to model. Do not add a classifier to
   choose a model until the table has been measured and found wanting.
8. **Pin model identifiers explicitly and record them with every result.** Moving aliases drift
   under you, and an evaluation whose exact model id and date were not recorded cannot be compared
   with anything later. Check the provider's current documentation for the id rather than
   recalling one.
9. **Separate retry from fallback in the failure path.** A rate limit, timeout or transient
   overload is a retry against the same model with backoff and jitter. A refusal, a persistently
   failing validation, or a provider outage is a fallback to a different model. Wire the retry
   mechanics from the idempotency-and-retries skill; a retried call with a side effect needs an
   idempotency key regardless of which model answered.
10. **Validate the fallback's output the same way you validate the primary's.** The common
    production failure is a fallback that returns quickly, passes no check, and is served.
11. **Make degradation visible.** Every response records which model answered, whether it was the
    fallback, and whether validation failed first. Alert on fallback rate, not only on errors — a
    silent fallback converts a quality regression into a mystery weeks later.
12. **Cap the chain.** A budget per request and per session, a maximum number of hops, and a
    defined behaviour when the cap is hit: refuse, queue, or ask the user. An unbounded fallback
    chain turns one bad request into an unbounded bill.
13. **Keep the routing rule in configuration**, so a bad route is a config change rather than a
    deploy. One table, one place — not a per-call-site conditional scattered through the codebase.
14. **Re-measure after the routing change lands**, per job: pass rate, cost per accepted output,
    latency, and fallback rate. An average that improves while one job's pass rate halves is a
    regression that the average is hiding.

## Checklist

- [ ] Jobs enumerated with their own latency, structure and review requirements
- [ ] A written quality bar and a check method per job
- [ ] One task set per job, used unchanged for every candidate
- [ ] Prompts re-tuned per candidate, or the comparison labelled provisional
- [ ] Candidates compared on pass rate, then latency, then cost per accepted output
- [ ] Routing rule expressed as a readable table on observable request properties
- [ ] Model ids pinned and recorded with every measurement and every response
- [ ] Retry and fallback distinguished, with backoff and jitter on the retry path
- [ ] Fallback output validated with the same check as the primary
- [ ] Which model answered, and any fallback, is recorded and alertable
- [ ] Budget and hop caps set, with a defined behaviour at the cap
- [ ] Post-change per-job measurements taken, not just an aggregate

## Failure handling

- **A candidate wins on average but loses on a subset** — that subset is a job. Split it and route
  it separately; do not average it away.
- **The task set is too small to separate two candidates** — say so and report the result as
  inconclusive. A five-example difference is noise, and shipping on it is how quality drifts.
- **The cheaper model passes but the outputs are subtly worse** — the bar is too loose. Fix the
  bar before re-running; a check the bad output passes is not a check.
- **Fallback rate is high** — treat it as a capacity or provider problem first. Routing more
  traffic to the fallback hides the signal instead of resolving it.
- **Switching a production route** — that changes what users receive. Propose it with the numbers
  and ask; roll it out behind the config from step 13 so it can be reverted without a deploy.
- **A provider's published numbers are the only evidence** — they are not comparable across
  vendors and were not measured on your task. Cite them as context, never as the result.

## Evidence to report

The job table with each job's quality bar; the task set size and where its inputs came from;
per-candidate pass rate, latency and cost per accepted output, with exact model ids and the date
run; whether prompts were re-tuned per candidate; the routing rule as written; the retry and
fallback paths with their caps; and, after the change, per-job before-and-after numbers plus the
observed fallback rate. "We route the easy ones to the small model" with no task set and no model
ids is a preference, not a measurement.
