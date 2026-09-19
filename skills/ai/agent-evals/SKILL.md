---
name: agent-evals
description: Build an eval suite that can actually detect a regression — cases pulled from real traffic, graders that check properties rather than vibes, a recorded baseline, and per-case diffs in both directions. Use before claiming a prompt, model or agent change is an improvement, when agent behaviour must not regress, or when someone reports "it seems better" after eyeballing a handful of outputs. Not for tracing what one run did (llm-observability), not for testing deterministic code, and never as evidence that behaviour the suite does not measure is safe.
---

# Agent evals

"It seems better" is a sample of three, remembered favourably. An eval exists to turn a change in a
prompt, model, tool or retrieval step into a number you can defend — and to tell you honestly how
much of the system that number covers.

## When this fires

Before a prompt, model, tool definition or retrieval change is called an improvement; when agent
behaviour is depended on and must not silently regress; when a production failure needs to become
something that cannot come back. It does not fire for deterministic code paths, which are tests.

## Procedure

1. **Name the decision the eval serves** — "is this change an improvement", "can this ship", "which
   of these two prompts". A suite with no decision attached gets built once and read never. Write
   the decision above the suite.
2. **Take cases from real traffic, not imagination.** Pull them from logs, traces, support tickets
   and the failure that prompted this work. Invented cases test the behaviour you already thought
   of, which is the behaviour least likely to be broken. Freeze the set and version it with the
   code.
3. **Stratify, and write the strata down.** Happy path, ambiguous input, missing or empty data,
   long context, multi-step tool use, cases where the right answer is a refusal, and adversarial
   input. Record roughly how many cases sit in each. The strata you have no cases for are part of
   the result and get reported as uncovered.
4. **Pin the expected outcome at the granularity that actually exists.** Exact match only where
   there is one right answer. Otherwise a checkable property: parses against the schema, contains
   the account id it was given, calls the lookup tool before the write tool, stays under the token
   cap, refuses. A grader for "sounds good" measures nothing.
5. **Grade with code wherever code can.** Schema validation, regex and substring checks, tool-call
   sequence assertions, numeric tolerance, latency and token ceilings. Deterministic, cheap, and
   free of the judgment you are trying to measure.
6. **If a model grades, the grader is itself under test.** Give it explicit criteria rather than a
   quality adjective, label a held-out slice by hand, and report the grader's agreement with those
   labels. Pin the grader's model and prompt and version them with the suite — changing the grader
   silently changes every historical number. An uncalibrated grader produces a figure of unknown
   meaning, and saying so is better than quoting it.
7. **Run each case more than once.** Sampling is nondeterministic, so a single pass cannot separate
   a real change from noise. Report pass rate with the trial count, and run at the sampling settings
   the system actually ships with, not only at the most deterministic setting available.
8. **Record the baseline before changing anything.** Run the suite against the current production
   configuration and store the result with the configuration that produced it. A change with no
   recorded "before" is not measurable, only assertable.
9. **Make one command run it.** A suite that needs a manual setup step is skipped exactly when it
   matters. Keep it cheap enough to run on every change to the prompt.
10. **Diff per case, in both directions.** An unchanged aggregate routinely hides equal numbers of
    new passes and new failures. Report which specific cases flipped to passing and which flipped to
    failing; the second list is the finding.
11. **Gate on the flips, not the average.** Decide in advance which subset is blocking — safety,
    required refusals, output contract, anything with an external side effect. A regression there
    stops and asks rather than being absorbed into a better mean.
12. **Run it where the change lands**, pre-merge or pre-release. The eval informs a release
    decision; it does not make one. Deploying on a green suite is a separate, separately authorized
    action.
13. **Feed every production failure back in as a case.** The suite's value is the accumulated real
    failures it now refuses to let back through.

## Checklist

- [ ] The decision this suite supports is written down
- [ ] Cases come from real traffic, including the failure that prompted the work
- [ ] Strata listed, with the uncovered ones named rather than omitted
- [ ] Every case has a checkable expectation, not an impression
- [ ] Deterministic graders used wherever a property can be checked in code
- [ ] Any model grader is calibrated against hand labels, and its agreement is reported
- [ ] Trials per case stated; pass rates carry their trial count
- [ ] Baseline recorded against a named configuration before the change
- [ ] Per-case flips reported in both directions
- [ ] Blocking subset defined, and a regression in it stops and asks

## Failure handling

- **Pass rate moved by a point or two** — that is probably sampling. Increase trials or say the
  result is within noise. Do not narrate a rounding error as an improvement.
- **The suite passes but production still fails** — the case set is unrepresentative, not the
  production report. Add the failure as a case before touching anything else.
- **A model grader disagrees with humans** — fix the rubric or replace it with a code grader.
  Reporting the grader's number while knowing it disagrees is fabrication with a decimal point.
- **Cases were written by looking at current outputs** — they encode today's behaviour as correct
  and will pass forever. Rebuild them from the requirement or from real traffic.
- **The suite is too slow or costly to run** — shrink it to the blocking subset and say which cases
  are now only run on demand. An unrun suite is not a control.

## Evidence to report

Name the suite: how many cases, where they came from, the strata and the uncovered ones. Then the
numbers with their conditions — baseline and post-change pass rates, trials per case, the
configuration and grader version behind each. Then the per-case flip lists, both directions. Quote
the actual run output; a claimed pass rate is not a measured one.

Distinguish plainly what happened: the suite was **written**, **executed** against a named
configuration, and produced a **measured** difference. A suite that has been written but not run
proves nothing at all.

## What a pass does not prove

A green suite says the measured cases behaved as expected under the sampled runs, on that
configuration. It does not establish that unmeasured inputs are handled, that the system is safe
against adversarial input it was never given, that latency or cost is acceptable unless graders
measured them, or that anything is working in production. Refuse to report "evaluated" without the
recorded baseline, the trial count and the flip lists — with any of those missing, the honest claim
is that the suite ran, not that the change is an improvement.
