---
name: e2e-testing
description: Build and keep end-to-end suites that are worth their runtime — which journeys belong at this level, selectors that survive refactors, waiting on state instead of sleeping, per-spec data isolation, and flake triage that finds the cause. Use when adding or repairing an e2e suite, when specs are slow or intermittently red, or when deciding whether a case belongs here at all. Not for one-off checking that a change renders, not for unit or integration tests, and not for load testing.
---

# End-to-end testing

The end-to-end level is the most expensive coverage available and the only level that can prove a
journey holds together. Suites die when those two facts are confused: everything gets tested here,
the suite gets slow and flaky, reruns become routine, and a red run stops meaning anything.

A suite whose failures are ignored is worse than no suite — it costs runtime and provides a false
signal.

## When this fires

Creating, extending, triaging or pruning an automated end-to-end suite. It does not fire for
manually confirming that a change renders and works (`browser-verification`), nor for coverage that
a unit or integration test could hold (`test-design`).

## Procedure

1. **Admit a journey only if it loses its meaning at a lower level.** Signup through first use;
   add to cart through payment confirmation; a permission boundary spanning UI, API and database.
   If a unit or integration test can observe the same failure, it belongs there — cheaper, faster,
   and it names the cause instead of the symptom. Validation-message wording, per-field rules and
   error formatting do not belong here.
2. **One spec is one journey with one reason to fail.** A spec that walks six unrelated features
   tells you only that one of six broke, and it breaks six times as often.
3. **Set up state through the API or a fixture, and assert through the UI.** Driving the UI to
   create preconditions triples the runtime and makes every spec fail whenever an unrelated screen
   changes. The journey under test is the part you click.
4. **Log in once, not per spec.** Authenticate through an API call or a seeded session/storage state
   and reuse it. The login form itself is one spec's journey, not every spec's preamble.
5. **Give every spec its own data.** A unique account, tenant or record per run, created by the spec
   and torn down or left disposable. Shared seed data makes specs order-dependent and turns parallel
   execution into cross-talk. Never rely on a record another spec created.
6. **Select by role and accessible name, or by a dedicated test id.** In that order. CSS class
   chains, `nth-child` and user-visible copy all break on changes that break nothing real — and
   role-based selection tests something true about the page while it does it.
7. **Wait for states, never for durations.** Wait for the element to be visible and enabled, for the
   request to settle, for the URL or the rendered text to change. Use the framework's retrying
   assertions with an explicit timeout. A fixed sleep is either slower than necessary or shorter
   than reality, usually both on the same day.
8. **Assert something a user could see.** Text on the screen, the URL, a value in a field, an item
   that disappeared. Asserting on a network call or on internal state is an integration test
   wearing a browser.
9. **Pin the environment.** A named build, seeded data, a fixed viewport, timezone and locale, and
   animations reduced. These are the four things that differ between a laptop and CI. **Never point
   the suite at production** — it creates real records, sends real mail and can touch real people;
   that is outward-facing, so stop and ask, and use a disposable environment instead.
10. **Capture the artifact on failure** — trace, video, screenshot, console log, the failing
    selector. A failure with no artifact costs a full reproduction cycle; with one, triage is
    usually a minute.
11. **Allow at most one retry, and treat a pass-on-retry as a failure to investigate**, not a pass.
    Record which specs needed a retry, because that record is the flake list.
12. **Triage each flake to a cause before touching it.** Four causes, four different fixes: a race
    in the test (wait on the right state), a race in the application (a real bug — fix the app, not
    the wait), shared or leaked state (isolate), or an unstable dependency (stub it at the network
    boundary, or drop the journey). "Fixed" by adding a sleep is not fixed; it is a longer suite
    with the same defect.
13. **Prove stability before believing it.** Run the suite twice back to back on the same build, and
    once with spec order shuffled or parallelism increased. Green once is not green.
14. **Prune on evidence.** For a suite that hurts, measure: runtime per spec, failure history, how
    often a red run found a real defect. Quarantine anything unfixable with an owner and a date, and
    propose deletions with the numbers attached. Deleting specs removes someone's coverage —
    **ask before removing them**, and never quarantine as a way of silencing a real failure.

## Checklist

- [ ] Every spec is a journey that no lower level could observe
- [ ] One journey per spec, one reason to fail
- [ ] Preconditions created by API or fixture, not by clicking
- [ ] Authentication seeded once and reused
- [ ] Data unique per spec and per run; no cross-spec dependency
- [ ] Selectors are role or test-id based, not classes, positions or copy
- [ ] No fixed sleeps anywhere; every wait names a state
- [ ] Assertions are on user-visible outcomes
- [ ] Environment pinned: build, seed, viewport, timezone, locale, animations
- [ ] Traces or screenshots retained on failure
- [ ] Retries capped at one and every retry recorded
- [ ] Suite run twice and shuffled before being called stable
- [ ] Quarantine list has owners and dates; nothing silenced without one

## Failure handling

- **Passes locally, fails in CI** — compare the four usual suspects first: viewport, timezone and
  locale, animation and network timing, and parallel workers sharing data. Read the trace before
  changing the test.
- **Fails once, passes on rerun** — that is a flake, not a pass. Log it and triage it to a cause.
  Reporting it as green is how a real race reaches production.
- **Suite is green but the feature is broken** — the coverage is at the wrong level or the
  assertions are not user-visible. Say which, and fix the level rather than adding more specs.
- **A journey cannot be automated** (third-party payment page, real email or SMS, a device
  capability) — stub at the network boundary if that keeps the journey meaningful, otherwise state
  plainly that this path is manually checked, by whom and when. Do not simulate it and call it
  covered.
- **Browser or runner unavailable** — say the end-to-end level could not be run, name what was
  checked instead, and do not describe the journeys as passing.
- **Under pressure to skip a failing spec to unblock a release** — that is a release decision, not a
  test change. Report what the spec covers and what shipping without it risks, and let the owner
  decide.

## Evidence to report

The journeys covered and, explicitly, the ones that are not; the command that runs the suite with
its real output; the result of two consecutive runs and one shuffled run; traces or screenshots for
every failure; the retry and quarantine list with owners and dates; and the environment the suite
ran against, named. A suite described as passing without a second run and an environment name is a
single sample.
