---
id: debug-application
name: "Debug an application"
summary: "Reproduce, isolate, fix, and prove the fix with the original reproduction plus a regression test."
use_when: "Something is broken and the cause is not yet known."
capabilities: quality.debugging, quality.regression, verification.browser
roles: debugger, implementer, tester
---

# Debug an application

`reproduce → gather evidence → hypothesize → isolate → fix → regression test → reproduce again`

The loop this replaces is: change something plausible, see if the symptom moves, repeat. That loop
produces fixes that are indistinguishable from coincidence.

## Steps

1. **Reproduce it first.** If it cannot be reproduced, say so and stop guessing — an intermittent
   failure reported as fixed is worse than one reported as intermittent.
2. **Gather evidence before theorizing.** Logs, stack traces, the failing input, what changed
   recently. → `systematic-debugging`
3. **Form a hypothesis that predicts something** you have not looked at yet, then look.
4. **Isolate.** Bisect the change, the input, or the code path until the smallest failing case is
   in hand.
5. **Fix the cause, not the path the report named.** Grep every caller of what you are about to
   change: a guard in the shared function is a smaller diff than a guard in each caller, and it
   leaves no siblings broken.
6. **Write the regression test** — it must fail against the old code. A test that passes both ways
   proves nothing. → `regression-testing`
7. **Run the original reproduction again.**

## Gates

- The original reproduction was run after the fix, not just the new test.
- The regression test was confirmed to fail without the fix.
- A timing change (a delay, a retry) is never reported as a root-cause fix without evidence of the
  actual race.

## When it is an outage instead

If the system is failing **right now**, this is the wrong recipe — mitigation comes before
explanation. Use `investigate-incident`.
