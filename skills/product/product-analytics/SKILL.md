---
name: product-analytics
description: Define a product metric so it means one thing — event, denominator, population, window — and check the instrumentation exists before anyone reports a number. Use when asked "how do we measure this", when a funnel or activation/retention/conversion metric is being defined, when two dashboards disagree, or before adding tracking to a feature. Not for choosing what to build (prioritization), not for designing an A/B test (experimentation), and not for general data analysis of a dataset that is already trusted.
---

# Product analytics

A metric is a claim about the world. Most disputed numbers are not wrong arithmetic — they are two
people using the same word for two different denominators, or a dashboard built on an event that
was never emitted on the path that matters.

## When this fires

Someone is about to define, report or argue about a product number: activation, conversion,
retention, funnel drop-off, adoption of a feature. It also fires *before* instrumentation is added,
which is the cheapest moment to get it right. It does not fire when the metric definition is
already settled and the task is only to compute or chart it.

## Four states, not one

Keep these apart in every sentence you write, because conflating them is how a metric that does not
exist ends up on a slide:

- **Defined** — written down with numerator, denominator, population, window.
- **Instrumented** — the emitting code exists on every path that should count.
- **Collecting** — events are arriving in the destination, from real traffic, since a known date.
- **Reconciled** — the number has been checked against an independent source and agrees.

Only the fourth is a number you may quote without a caveat.

## Procedure

1. **Name the decision the metric serves.** Who changes what behaviour at which threshold. If no
   answer, say so — a metric nobody will act on is not worth the instrumentation cost, and saying
   that is a legitimate result of this procedure.
2. **Write it as a rate with both halves visible.** Numerator, denominator, the population each is
   drawn from, and the time window. "Activation rate" is not a definition. "Accounts created in
   week W that reached first successful import within 7 days / accounts created in week W" is.
3. **Fix the unit of aggregation** — user, account, session, device, request — and use the same
   unit on both halves. A per-session numerator over a per-user denominator is the most common
   silent error in this whole area, and it never announces itself.
4. **Specify each event precisely**: the name, the exact moment it fires, the properties carried,
   and the near-miss cases it deliberately excludes (retries, server-side replays, internal or
   test accounts, bot traffic). Write the exclusions down; they are the part that gets lost.
5. **Find the emitting code before believing the event exists.** Search the repository for the
   event name and read every call site. Check the paths nobody remembers: the mobile client, the
   API-only path, the error branch, the redirect that returns early. Absent call site means the
   metric is defined, not instrumented — report that, do not estimate around it.
6. **For a funnel, pin the entry cohort once** and carry it through. Decide and record: must the
   steps occur in order; what attribution window each step has; are users who enter twice counted
   twice. A funnel whose steps each have their own population is four unrelated numbers in a row.
7. **Add a guardrail or counter-metric.** Any metric that can be moved by degrading something else
   — speed at the cost of errors, signups at the cost of retention — gets the opposing metric
   defined alongside it, or it will be gamed by accident.
8. **State the trustworthy-from date.** The first date the current definition and the current
   instrumentation both held. Before that date the series is a different metric wearing the same
   name; do not chart across the boundary without marking it.
9. **Reconcile against something independent** before publishing: a database count, billing
   records, a manual count for one day, the previous system. Report the gap as a number and its
   likely cause. Agreement within a stated tolerance is the evidence; "looks about right" is not.
10. **Stop and ask before anything outward-facing.** Adding tracking to production, changing the
    semantics of an event other dashboards already use, publishing a dashboard others will act on,
    or collecting a new property about people. Especially: never add personal data — email, name,
    free-text input, precise location, anything identifying — to event properties on your own
    judgement. Propose it, name the field, and wait.

## Checklist

- [ ] The decision this metric informs is written down, or its absence is flagged
- [ ] Numerator, denominator, population and window are all stated
- [ ] Both halves use the same unit of aggregation
- [ ] Every event's firing moment, properties and exclusions are specified
- [ ] Each event was located in the emitting code, on every path that should count
- [ ] Funnel entry cohort, step ordering and attribution windows are fixed
- [ ] A guardrail metric exists for anything that can be gamed
- [ ] The trustworthy-from date is stated
- [ ] The number was reconciled against an independent source, with the gap quoted
- [ ] Any new tracking or new property was proposed, not added

## Failure handling

- **Two sources disagree** — do not average them and do not pick the friendlier one. Take one
  narrow slice (one day, one account) and trace it through both until the divergence is a named
  cause: a missing call site, a timezone, a deduplication rule, a filter on one dashboard.
- **The event is not instrumented** — the finding is "not measurable today", with the list of paths
  that would need to emit. An estimate derived from a proxy is a proxy: label it as one, every
  time it is quoted.
- **The event fires more than once per real occurrence** — say whether the metric counts events or
  distinct units, and fix the definition rather than the data.
- **Historical data does not go back far enough** — report the window you actually have. Never
  backfill by assumption and present the result as history.
- **The definition already exists somewhere** — use it, or change it deliberately and say so. A
  second definition of an existing name is worse than a bad definition of a new one.
- **Personal or sensitive data appears in event properties** — stop, name the field and where it is
  emitted, and raise it. Do not quietly keep querying it.

## Evidence to report

The metric written out in full — numerator, denominator, population, window, unit. The file paths
and call sites where each event is emitted, and the paths found to be missing it. The exclusion
list. The trustworthy-from date. The reconciliation: both numbers, the gap, the explanation. And
the parts still unmeasurable, named as such rather than approximated into the table.
