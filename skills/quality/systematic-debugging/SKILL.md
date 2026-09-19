---
name: systematic-debugging
description: Find the cause of a failure by evidence — reproduce it, read what the system actually did, form hypotheses that predict something you have not looked at yet, bisect to the smallest failing case, fix where all callers route through, then re-run the original reproduction. Use when something is broken and the cause is not yet known, when a previous fix did not hold, or when an edit is about to be made because the code "looks wrong". Not for an outage still burning (mitigate first), not for a cause already established that only needs implementing, and not a licence to skip reading the stack trace.
---

# Systematic debugging

The symptom is where the failure surfaced, not where it came from. Editing the line the report
names is how a bug gets moved rather than fixed.

## When this fires

- A defect, crash, wrong output, corrupted state or failing test whose cause is not yet known.
- A second attempt at a fix, after the first one did not hold or held for reasons unknown.
- Before any edit whose only justification is that the code looks suspicious.

It does not fire during a live outage — mitigation comes first and the explanation comes after —
and it does not fire when the mechanism is already established and only the patch remains.

## Procedure

1. **State the failure precisely.** Expected versus actual, the exact input, the version and
   environment, and when it started. "Login is broken" is not a failure statement. "POST /login
   returns 500 on staging for accounts created before the column was added" is one.
2. **Reproduce it before touching anything.** Record the exact command or step list and its
   output. If it will not reproduce, that is the finding — report how you tried and how often it
   fires. Do not proceed to a fix whose effect you have no way to observe.
3. **Capture evidence before theorising.** The full stack trace, not the last frame. The log lines
   either side of the failure. The failing input. What changed recently in the code and in its
   dependencies. Read all of it. A large share of bugs are already named in evidence nobody read.
4. **Bound it.** Which inputs fail and which succeed, which callers, which versions, which
   environments. A failure confined to one input class is already half diagnosed.
5. **Write hypotheses down, ranked.** Each one must predict something you have not yet looked at —
   "if it is the stale cache, this key holds the old value" — and then you go and look. A
   hypothesis that only explains what you have already seen cannot be tested.
6. **Test one at a time, cheapest first.** Change one variable per experiment. A log line, a
   breakpoint or a query beats a speculative edit: reading adds no new variables, editing does.
7. **Isolate to the smallest failing case.** Bisect whichever axis you can halve — the history,
   the input, the configuration, the code path. Stop when removing one more thing makes it pass.
8. **Name the causal mechanism in one sentence** before you edit. If the best you have is
   "something about async timing", you are not ready to fix; you are ready to keep isolating.
9. **Fix the cause where all callers route through it.** Grep every caller of the function you are
   about to change. Patching only the path the ticket named leaves the siblings broken; one guard
   in the shared function is both the smaller diff and the actual fix.
10. **Prove it.** Re-run the reproduction from step 2. Add a regression test that fails on the old
    code (`regression-testing`). Run the surrounding suite to see the fix broke nothing adjacent.
11. **Remove your instrumentation** — debug prints, extra logging, loosened timeouts. Anything
    worth keeping is kept deliberately and said out loud, not left in the diff by accident.

## Anti-patterns — the random-patch loop

The loop this skill exists to break: change something plausible, see whether the symptom moves,
repeat. Every round adds a variable, and the run that finally passes is indistinguishable from
coincidence.

- **Fix by disappearance.** The symptom stopped after five edits, so one of them worked. You do
  not know which, or whether it merely became less frequent.
- **A delay is not a fix.** A sleep or a retry makes a race rarer. Report it as a mitigation with
  the race still unexplained, never as a root cause.
- **Suppression is not a fix.** A broad catch, a disabled assertion, a loosened check — the
  failure is now invisible rather than absent.
- **Anchoring.** The first plausible story gets all the evidence read into it. Ask what the
  evidence would look like if that story were wrong, then check for that.
- **Rewriting the region.** A rewrite that happens to pass has not been diagnosed; it has replaced
  a known bug with unknown ones.

## Checklist

- [ ] Reproduction captured as an exact command or step list, and run before any edit
- [ ] Full stack trace and surrounding logs read
- [ ] Hypotheses written down, each predicting something unobserved
- [ ] Smallest failing case in hand
- [ ] Causal mechanism stated in one sentence
- [ ] Every caller of the changed code checked, not only the reported path
- [ ] Original reproduction re-run after the fix
- [ ] Regression test confirmed to fail against the old code
- [ ] Instrumentation removed, or deliberately kept and said so

## Failure handling

- **Will not reproduce** — report it as not reproduced, with the conditions tried. If a
  low-risk speculative fix ships anyway, label it unverified in plain words. An intermittent
  failure announced as fixed is worse than one announced as intermittent.
- **Reproduction is slow or manual** — build a cheap one first, a script or a failing test. You
  are going to run it dozens of times.
- **No logs, no traces, nothing to read** — adding instrumentation is a step, not a fix. Record
  the observability gap as a finding in its own right.
- **Every hypothesis falls** — widen the frame to what you assumed and never checked: the
  environment, a dependency version, the data, the clock, another process, the build itself.
- **Testing it needs something destructive or outward-facing** — deleting data, writing to a
  shared environment, calling a live third party, deploying. Stop and ask. Reproduce against a
  local or throwaway copy instead.

## Evidence to report

The reproduction command and its output before the fix; the evidence that ruled each hypothesis in
or out; the causal mechanism in one sentence; the diff; the regression test with proof it fails
without the fix; and the reproduction re-run and now passing. Name what remains untested and any
hypothesis you could not eliminate. A fix that was written and a fix that was proven are different
claims — "fixed" without the re-run reproduction is the first one wearing the second one's clothes.
