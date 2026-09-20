---
name: regression-testing
description: Turn a fixed bug into a test that fails on the old code and passes on the new one. Assert behavior at the cheapest useful level and compare old behavior without reverting unrelated work or leaving scratch files. Use after a fix or when recurring defects lack coverage; not for a new feature's test strategy or an environmental/cosmetic failure.
---

# Regression testing

A test written after the fix, run once, green, proves only that the code currently passes it. It
becomes a regression test at the moment you watch it fail against the old code — until then it may
be asserting nothing at all.

## When this fires

- A bug has been fixed and the fix is about to be reported as done.
- A defect has recurred, so the previous fix had no test or the test did not cover the real case.
- A test exists for a fix but was never observed failing without it.

It does not fire for new-feature coverage, for test strategy, or before the cause is understood —
a test pinning a symptom you cannot explain pins the wrong thing.

## Procedure

1. **Restate the defect as a behavioural assertion.** Given this input and this state, the system
   should do this. If that sentence cannot be written, the diagnosis is not finished
   (`systematic-debugging`), and the test will end up asserting the implementation instead.
2. **Decide whether a test is the right tool at all.** See *When not to write one* below. Write
   nothing rather than something that will be deleted as noise in a month.
3. **Pick the cheapest level that can actually observe the defect.** Unit when the cause lives in
   one function; integration when it lives in the wiring between two; end-to-end only when the bug
   is invisible below the full stack. A slow test at the wrong level catches the bug once and taxes
   every run afterwards.
4. **Assert the observable contract, not the patch.** Assert the returned value, the persisted
   row, the rendered output, the raised error. A test that asserts a mock was called, or pokes a
   private helper the fix introduced, will pass forever and catch nothing — including the same bug
   arriving by another route.
5. **Make the assertion specific to this defect.** "Does not raise" passes for a function that
   returns nothing useful. Assert the value, the message, the count, the order — whatever the bug
   got wrong.
6. **Run it against the old code and watch it fail.** Prefer an isolated in-memory old
   implementation or inline `python3 -B -` check with quoted stdin. Do not stash/revert the
   user's working tree merely to demonstrate failure. If a scratch copy is necessary and
   permitted, use a uniquely owned temporary-directory context with cleanup in `finally`,
   and verify its absence afterward. Never use a shared fixed /tmp name or a project sibling.
   Read the failure. This is the step that makes it a regression test rather than an assertion. The
   failure message should name the defect; if it says "expected true, got false", improve it now,
   because the next person to see it will be debugging under time pressure.
7. **Restore the fix and run it green.** Both observations, in that order, are the deliverable.
8. **Make it deterministic.** No real clock, no network, no sleeps, no dependence on test order or
   on a fixture another test mutates. Run it several times and on its own as well as in the suite.
   A flaky regression test gets skipped, then deleted, and the bug comes back unguarded.
9. **Name it for the behaviour, not the ticket.** `test_expired_token_is_rejected`, with the issue
   link in a comment. `test_bug_4417` tells a future reader nothing about what broke.
10. **Put it where the suite already keeps tests of that kind**, then run the whole file and the
    suite once. A new test that quietly breaks an existing one through a shared fixture is a new
    bug, not coverage.

## When not to write one

- **The failure was environmental** — an expired certificate, a bad deploy value, a full disk. The
  guard belongs in configuration validation, a startup check or monitoring. A unit test asserting
  the certificate is valid tests nothing about the code.
- **The assertion would restate the implementation line for line** — a corrected constant or a
  copy string, where the test is the same edit written twice and fails on every legitimate change.
- **The bug is timing-dependent and only reproduces occasionally.** A test that fires one run in
  fifty is a future flake. Prefer a deterministic reproduction — injected clock, controlled
  scheduler, forced ordering — or assert the invariant that the race violates. If neither is
  reachable, say so rather than committing a coin flip.
- **The bug is in a dependency.** Test your workaround and its trigger condition, not their defect.
- **The code is being deleted or rewritten within the change** — the test would be born stale.

In each case the report says a regression test was deliberately not written, and why. That is a
decision; silence looks like an oversight.

## Checklist

- [ ] The defect is stated as a behavioural assertion
- [ ] The level chosen is the cheapest one that can observe it
- [ ] The assertion is on observable behaviour, not on the fix's internals
- [ ] The test was run against the old code and **seen to fail**
- [ ] The failure message names the defect
- [ ] The test passes with the fix restored
- [ ] It is deterministic — run repeatedly, alone and in the suite
- [ ] The full suite still passes
- [ ] Or: no test was written, and the reason is recorded

## Failure handling

- **It passes against the old code** — it is not testing the defect. Go back to step 1; usually
  the assertion is on the wrong layer or too loose.
- **It fails against the old code for the wrong reason** — an import error, a missing fixture. That
  is not a reproduction. Fix the harness and look again.
- **Old behavior cannot be compared within scope** — report that limitation. Do not expand
  filesystem scope merely to obtain red/green proof. Reconstruct it in memory or use the
  permitted owned-directory procedure above; never edit shared/deployed code to force failure.
- **Cleanup fails or is denied** — report the exact owned path as unresolved. Do not claim
  only the requested files were changed. A clean project diff does not cover temporary writes.
- **Reproducing it needs a real outward-facing or destructive action** — a live payment, a real
  email, production data, a shared account. Stop and ask. Use a sandbox, a fixture or a recorded
  interaction; never wire a test to send real messages or mutate real records.
- **The suite has no place for this kind of test** — say so and propose where it should live.
  Inventing a parallel test setup nobody runs is worse than no test.

## Evidence to report

The test's path and name; the command that runs it; the failure output from the run against the
old code, quoted; the passing output with the fix; and confirmation the rest of the suite still
passes. A test that was created and one that was executed and one that was proven to fail without
the fix are three different claims — report which you have. Where no test was written, report the
reason in its place.
