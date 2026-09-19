---
name: test-design
description: Write unit and integration tests that fail for the right reason — behaviour-level assertions, boundary values, the smallest honest double, deterministic setup and teardown. Use when adding tests for new code, pinning a bug before fixing it, or repairing tests that stay green while the code is broken. Not for deciding what to test or at which level, not for browser journeys, and not a way to call a change verified.
---

# Test design

A test earns its keep only by failing when the behaviour it names is broken. Most bad tests are not
wrong; they are inert — they assert on what the code does rather than what it must do, so they go
red on every refactor and green through every real defect.

Keep the verbs apart: **created** is the test file written; **executed** is a run that happened;
**tested** is a check that will run again without you; **verified** is a conclusion about the
system, and a passing unit test does not supply it.

## When this fires

Adding coverage for new or changed code, pinning a reported bug before fixing it, or fixing a suite
that passes while the behaviour is wrong. It does not fire for choosing which risks to cover at
which level (`test-strategy`), nor for end-to-end journeys (`e2e-testing`).

## Procedure

1. **Name the behaviour in one sentence in the caller's terms** — "a refund over the original
   amount is rejected", not "calls validateAmount". If the sentence needs an internal name to make
   sense, you are about to test the implementation.
2. **Make it fail first, for the reason you expect.** New test: run it before the code exists or
   against the unfixed bug and read the failure message. Existing code: break the line it protects,
   confirm red, restore. A test never observed red is an assumption, not a check.
3. **Arrange the minimum, and inline what the test is about.** Build entities through a factory or
   helper that fills irrelevant fields with defaults, and set the one or two values this test turns
   on explicitly in the test body. A reader should see the input that matters without opening a
   fixture file.
4. **Assert on the observable outcome** — the returned value, the persisted row, the message
   published, the error raised. Asserting that a collaborator was called with certain arguments
   tests your wiring, and it will keep passing after the collaborator starts doing the wrong thing.
5. **One behaviour per test.** A test with several unrelated assertions reports only the first
   failure and hides the rest. Several inputs exercising the *same* behaviour belong in one
   parameterised case, not several copies.
6. **Work the boundaries deliberately.** For each input: zero, one, many; empty and absent (they are
   different); the value at the limit and the value one past it; negative, maximum, and the type's
   overflow or precision edge; duplicates; unicode and length limits on text; the timezone or
   currency-unit ambiguity. Happy path plus three more happy paths with different numbers is one
   test wearing four names.
7. **Choose the smallest honest double.** Prefer the real object; then an in-memory fake; then a
   stub returning a fixed value; a mock that asserts on interactions last, and only when the
   interaction *is* the behaviour (an email was sent, a payment was captured). Never double the
   thing under test. For a real dependency with a real protocol — database, HTTP client, queue —
   prefer an integration test against the real thing over a stub of it.
8. **Back every double with a contract check.** A stub encodes a belief about what the dependency
   returns; if nothing ever executes the real thing, the suite proves only that your code parses
   your own fiction. One integration or contract test per doubled boundary is the minimum price.
9. **Make it deterministic by construction.** Inject the clock and the random source rather than
   freezing globals; no live network; no `sleep`; no dependence on locale, timezone, filesystem
   order or map iteration order; no state shared between tests. Seed randomised data and print the
   seed in the failure output.
10. **Isolate and clean up.** Each test creates the data it needs and leaves nothing behind —
    transaction rollback, a fresh temporary directory, a per-test schema or namespace. Then prove
    it: run the single test alone, and run the file in a randomised order.
11. **Test error paths as contracts.** Assert the specific type and the identifying part of the
    message or code the caller branches on. "Something was raised" passes for a typo in the code
    under test.
12. **Name the test so the failure report reads as a sentence** — subject, condition, expectation.
    The name is what the next person sees at 3am, before the assertion.
13. **Check it is not over-specified.** Refactor the internals without changing behaviour — rename a
    private helper, reorder independent calls. If the test goes red, it is pinned to the
    implementation and will cost more than it catches.

## Checklist

- [ ] Behaviour stated in the caller's terms before writing the test
- [ ] Test observed failing for the intended reason, not just passing
- [ ] Assertions on outcomes and state, not on collaborator calls (unless the call is the behaviour)
- [ ] One behaviour per test; repeated inputs parameterised rather than copied
- [ ] Boundaries enumerated: empty, absent, one, many, limit, limit±1, duplicate, unicode
- [ ] Smallest honest double used; nothing doubled that could be real
- [ ] Every doubled boundary has at least one test against the real dependency
- [ ] Clock, randomness, network, ordering and shared state all controlled
- [ ] Passes alone, passes in a randomised order, leaves no residue
- [ ] Error cases assert the specific type or code the caller depends on
- [ ] Names read as sentences in the failure output

## Failure handling

- **Test passes when you break the code** — it does not test what its name claims. Fix the
  assertion or delete it; a test that cannot fail is a false green with maintenance cost.
- **Test is flaky** — do not add a sleep or a retry. Find the source: shared state, real time, real
  network, ordering, or an actual race in the production code. The last one is a bug, and the flake
  is the only evidence you will get of it.
- **Setup is enormous** — that is a design finding, not a test problem. Too many collaborators to
  construct means too many dependencies; report it rather than building a scaffold that will rot.
- **Snapshot or whole-payload assertion** — it fails on every unrelated change until someone
  regenerates it unread. Use one only where the whole output genuinely is the contract, and assert
  on specific fields everywhere else.
- **Test needs credentials or a shared environment** — stop before pointing it at anything shared or
  production-like. Writing to a real system or a shared account is outward-facing: **ask** first,
  and prefer a local instance or a disposable record.
- **Bug cannot be reproduced in a test** — say so explicitly. A fix shipped without a failing test
  first is a guess; record what was tried and that the regression is unguarded.

## Evidence to report

The test command and its actual output, not a summary of it; for each new test, that it was seen
red and why; the mutation check (what was broken, that it went red, that it was restored); which
boundaries are covered and which inputs are not; which dependencies are doubled and where the real
one is exercised instead; and the isolation result — alone and in randomised order. "Tests added
and passing" without a red observation says only that code was written.
