---
id: ship-feature
name: "Ship a feature"
summary: "Get a feature from request to merged, with the smallest set of specialists the work actually needs."
use_when: "A feature is requested that touches more than one file and someone will review it."
capabilities: quality.debugging, quality.tests, quality.strategy
roles: explorer, planner, implementer, tester, reviewer
---

# Ship a feature

## The default shape

`explorer → planner → implementer → tester → reviewer`

## What to cut, and when

This is a default, not a chain that must run. Cut aggressively:

- **Skip `explorer`** when you already know where the change goes. It earns its place in an
  unfamiliar codebase or when the blast radius is unknown.
- **Skip `planner`** for anything a competent implementer can hold in their head. A plan for a
  two-file change is ceremony. It earns its place when there is migration risk, several
  dependencies, or a decision that wants agreement before code exists.
- **Skip `tester` as a separate step** when the implementer's own tests cover the acceptance
  criteria and the user did not ask for independent verification.
- **Never skip `reviewer`** when the change is going to be merged by someone else — but it does
  not have to be a separate agent if the user only wants a self-check, as long as you say that is
  what it was.

Trivial work is `implementer` alone. Say so rather than running the full shape at low value.

## Steps

1. **Scope.** Name the acceptance criteria before writing anything. If they cannot be stated, that
   is the finding — go back to the user or route to `product-manager`.
2. **Locate.** Find every place the change touches, including callers. A fix in one caller when
   four share the defect is a second bug.
3. **Build.** Smallest change that satisfies the criteria, in the codebase's existing idiom.
4. **Verify.** Run what exists. Add a test that fails without the change.
5. **Review.** Against the criteria from step 1, not against taste.

## Gates

- Acceptance criteria exist before implementation starts.
- The test suite ran, and its actual output is reported — not "tests should pass".
- A reviewer who is also the author says so explicitly.
