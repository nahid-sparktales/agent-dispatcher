---
name: experimentation
description: Design an A/B test that can answer its question — hypothesis, randomization unit, power, duration, pre-registered analysis — and read the result honestly, including a null. Use when someone proposes testing a change, asks how long a test must run or whether a result is real, when a test is about to be stopped early, or when a flat result is being read as "no difference". Not for defining the metric itself (product-analytics), not for a change too small or too rare to power, and not for authorizing a rollout.
---

# Experimentation

Most experiments fail before they launch: an unmeasurable hypothesis, a unit that leaks between
arms, or a sample that was never going to detect the effect anyone cared about. Reading results is
the short part. The design is where the answer is won or lost.

## When this fires

A change is about to be tested, a running test is about to be read or stopped, or a result is being
turned into a decision. It also fires as a refusal: when the traffic cannot support a test worth
running, saying that early is the valuable output.

## Five states, not one

- **Designed** — hypothesis, unit, primary metric, power and duration written down.
- **Launched** — assignment is live and exposures are being logged.
- **Read** — analysed at the pre-registered time, after sanity checks pass.
- **Conclusive** — the result distinguishes the hypothesis from its absence at the stated power.
- **Shipped** — a human decided to roll it out. Never a consequence of the other four.

## Procedure

1. **Write a falsifiable hypothesis with a direction and a size.** "Moving the plan selector above
   the fold will increase trial starts by at least 5% relative, because users currently scroll past
   it." Without a size there is no power calculation, and without that there is no experiment —
   only a period of waiting.
2. **Choose one primary metric, before any data exists.** One. Add guardrails (the metrics that
   must not degrade) and secondaries (interesting, never decisive). If the primary metric is not
   already defined to the standard of `product-analytics`, define it first — an experiment on a
   vague metric produces a vague result at full cost.
3. **Pick the randomization unit so that interference stays inside an arm.** User or account for
   anything with memory across sessions; session-level assignment gives a user both arms and
   smears the effect. If users interact with each other or share a workspace, the unit is the
   group, not the person. State the unit and the reason.
4. **Make the analysis unit match the randomization unit.** Randomize by user, analyse by user.
   Analysing per-event data from user-randomized arms understates the variance and manufactures
   significance.
5. **Compute the sample size from the baseline rate and the minimum effect worth acting on**, using
   the standard two-proportion (or two-sample mean) sample-size calculation, per arm, at the
   significance and power you state — conventionally 5% and 80%, said out loud, not assumed.
   Then convert to duration with the real traffic reaching that surface, not total site traffic.
6. **Sanity-check the duration before committing.** Run whole weeks, at least one full business
   cycle, so day-of-week mix is balanced. If the required duration is longer than anyone will wait,
   the honest moves are: raise the minimum detectable effect, pick a surface with more traffic,
   test a bolder version of the change, or decide without an experiment. Running it anyway
   underpowered is the one option that produces a confident wrong answer.
7. **Pre-register the analysis and write it down before launch**: primary metric, guardrails, unit,
   arms and split, start and planned end date, the segments you are permitted to cut, and what each
   outcome means for the decision. This document is what makes a later null result credible.
8. **Before reading anything, run the sanity checks.** Sample ratio mismatch — the observed split
   against the intended split, tested rather than eyeballed; a mismatch invalidates the comparison
   and is a bug, not a result. Then: exposures logged in both arms, no other experiment or launch
   overlapping the same surface, no outage or campaign inside the window.
9. **Read at the pre-registered time.** Peeking and stopping on a good day inflates the false
   positive rate badly. If you need to look early, that decision belongs at step 7 as a sequential
   or group-sequential design with its own thresholds — not as an improvisation at step 9.
10. **Report the effect with its confidence interval**, in both relative and absolute terms, plus
    the guardrails. A point estimate alone hides everything that matters about certainty.
11. **Be precise about a null.** A flat result is not "no difference". It is: the data are
    consistent with effects between the interval's bounds, and the test was powered to detect an
    effect of at least the MDE. Say which. A wide interval means the experiment was uninformative —
    a different statement from "the change did nothing", and a more useful one.
12. **Treat post-hoc segments as hypothesis generation only.** A subgroup that "won" in a test
    designed for the whole population is a candidate for the next experiment, never a conclusion,
    and never a reason to ship to that subgroup.
13. **Stop and ask before rolling out, ramping, or ending a test early.** Producing the result is
    this procedure's job; changing what users get is a decision with an owner who is not you. Say
    what the data support and hand it over.

## Checklist

- [ ] Hypothesis states direction, size and mechanism
- [ ] One primary metric, fixed before data; guardrails named
- [ ] Randomization unit stated, with interference argued
- [ ] Analysis unit matches the randomization unit
- [ ] Sample size per arm computed from baseline, MDE, significance and power — all stated
- [ ] Duration derived from real traffic, in whole weeks
- [ ] Analysis pre-registered in writing before launch
- [ ] Sample ratio checked; exposures present in both arms; no overlapping change in the window
- [ ] Result read at the pre-registered time, with confidence intervals
- [ ] A null result reported as "could not detect an effect larger than X", not "no difference"
- [ ] Rollout proposed to a human, not performed

## Failure handling

- **Sample ratio mismatch** — stop analysing. Something in assignment, exposure logging or
  filtering is broken; any effect measured through it is uninterpretable. Report it as a bug.
- **A guardrail moved against you while the primary won** — that is the result, both halves of it.
  Do not report the win alone.
- **A secondary metric moved and the primary did not** — a new hypothesis, not a finding. Say so
  plainly; this is the most common way a dead experiment gets resurrected as a claim.
- **The test was stopped early** — say when and why, and treat the p-value as optimistic. If the
  early stop was for harm, that decision stands; the statistics just do not transfer.
- **An overlapping launch, outage or campaign landed inside the window** — name it, say which
  direction it plausibly biases, and do not quietly report the number as clean.
- **Traffic cannot power the test** — return that as the answer, with the numbers: baseline rate,
  weekly eligible traffic, detectable effect at the maximum acceptable duration. A well-argued
  "this cannot be tested here, decide another way" is a complete deliverable.

## Evidence to report

The pre-registration as written before launch. The power calculation with its inputs visible —
baseline rate, MDE, significance, power, resulting sample per arm, traffic, duration. The sample
ratio check as observed-versus-expected counts. The primary metric with its confidence interval,
relative and absolute, and every guardrail. The exact window analysed and anything known to have
happened inside it. And, for a null, the effect size the test could not have ruled out.
