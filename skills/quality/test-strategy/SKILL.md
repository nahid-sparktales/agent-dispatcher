---
name: test-strategy
description: Decide what to test and at which level before any tests get written — enumerate failure modes by consequence, give each one the cheapest level that can actually observe it, and name what is deliberately left uncovered. Use when starting testing on a feature or a codebase, when asked for a test plan or why coverage sits where it does, or when a suite is large and still missing bugs. Not for writing the tests themselves, and not for proving a finished change works.
---

# Test strategy

Coverage percentage measures which lines ran, not which failures would be caught. A suite can be
90% green and blind to every way the system actually breaks, because tests get written where they
are easy to write — pure helpers, config objects, getters — and failures happen at boundaries.

This produces a short written allocation: risks, the level each is tested at, and what is not
tested. It does not produce tests.

## When this fires

Before writing a batch of tests, when planning a feature's coverage, when a suite is slow or
expensive and nobody can say what it buys, or after an escaped bug when the question is why nothing
caught it. It does not fire for adding one test to an existing pattern.

## Procedure

1. **Enumerate failure modes, not features.** For each one: what goes wrong, who notices, and what
   it costs — corrupted data, money moved twice, a silent wrong number, a page that will not load,
   a cosmetic slip. Rank by consequence times plausibility. A feature list produces even coverage;
   a failure list produces useful coverage.
2. **Get the history before trusting your instincts.** Bug-fix commits, issue tracker, incident
   notes, the files that change most often. Where this system has broken before is the best
   available predictor of where it breaks next, and it is usually not where anyone guessed.
3. **Find the boundaries.** Every place data crosses into or out of your control — HTTP, database,
   queue, filesystem, clock, third party, the user. Most real defects live at boundaries or in the
   logic that decides which side of one to take.
4. **Assign each risk the lowest level that can actually observe that failure.** Lowest is
   cheapest and most precise — but "lowest" is bounded by observability: a bug that only exists in
   the interaction between two components cannot be caught by a unit test that mocks the seam it
   lives in. Choosing a level a mock makes blind is the most common way a green suite misses.
5. **Say what each level is for in this system**, in one line each, because the words are used
   differently everywhere: unit (logic in isolation, no I/O), integration (real adapter against a
   real dependency — database, HTTP, queue), end-to-end (a whole journey through the running
   system). Write the definitions you are using; do not argue the pyramid.
6. **Set a budget in seconds, not in counts.** How long the suite may take on a developer's machine
   and in CI. A budget forces the allocation to be real: if every risk lands at the top level, the
   suite will be slow, flaky and eventually ignored, which is worse coverage than fewer honest
   tests.
7. **Name what you are choosing not to test, and why.** Generated code, framework behaviour, third
   party internals, exact copy, throwaway spikes, anything whose failure is cheap and obvious. An
   unlisted gap is an accident; a listed one is a decision.
8. **Name what cannot be tested automatically at all** — a payment provider's production behaviour,
   a physical device, a rendered judgement call — and say what the manual check is and when it
   runs. Do not silently let the hard parts fall off the plan.
9. **State what a green suite will license you to claim.** "These journeys and these boundaries
   were exercised" is a claim; "the feature works" is not, unless the plan actually covers it.
   Writing the claim down is what stops *tested* being reported as *verified* later.
10. **Check for the untestable design.** If a risk cannot be reached at any level without elaborate
    mocking, that is a finding about the code — a boundary in the wrong place, hidden state, work
    done in a constructor. Report it as a design finding rather than building the elaborate mock.
11. **Write the allocation down** as a table a reviewer can argue with: risk, level, what would have
    to be true for it to be caught, and its owner if it is manual.

## Checklist

- [ ] Failure modes listed with consequence, not a feature list
- [ ] Repository and issue history consulted for where breakage actually happened
- [ ] Boundaries identified and each one assigned a level
- [ ] Every risk placed at the lowest level that can still observe it
- [ ] Level definitions written for this system
- [ ] Runtime budget stated for local and CI
- [ ] Deliberate non-coverage listed with reasons
- [ ] Manual-only checks named with an owner and a trigger
- [ ] The claim a green suite supports is written down
- [ ] Untestable-by-design findings raised rather than mocked around

## Failure handling

- **Asked for a coverage percentage target** — give the allocation, and say which risks are covered
  and which are not. A number can be met without touching a single risk on the list.
- **No history available** (new code, fresh repository) — say so, and lean on boundaries and on
  consequence ranking instead. Do not present intuition as evidence.
- **Everything looks high risk** — rank anyway, by blast radius. A plan that calls all of it
  critical allocates nothing.
- **Existing suite is large and unloved** — measure before proposing: runtime, failure history, how
  often a red run found a real bug. Deleting tests is a real deletion of someone else's work:
  recommend it with the evidence and **ask** before removing anything.
- **The plan implies changing production code to be testable** — that is a legitimate outcome, but
  it is a separate change with its own review. Name it, do not smuggle it in.

## Evidence to report

The risk list with each item's assigned level and the reason that level can see it; the level
definitions used; the runtime budget; the explicit not-covered list; the manual checks with owners;
and the single sentence saying what a green run of this plan does and does not prove. A plan
without a not-covered list is not finished.
