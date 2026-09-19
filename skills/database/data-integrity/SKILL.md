---
name: data-integrity
description: Keep data correct over time — write the invariants down, push each one to the lowest layer that can enforce it, cover the rest with reconciliation queries, and detect drift before a user reports it. Use when deciding where a rule should be enforced, auditing a schema whose rules live only in application code, building reconciliation or drift checks, or investigating data that looks wrong. Not for sequencing a schema change (migrations) or proving one migration's outcome (database-migration-verification), and it stops before repairing rows in a shared environment.
---

# Data integrity

Application-level validation runs on the paths that call it. A backfill, an admin console, a second
service, a support script and a psql session all bypass it. Anything that must always be true has to
be enforced somewhere every writer goes through, or measured continuously — preferably both.

## When this fires

You are deciding where a rule is enforced, auditing a schema whose rules exist only as guard clauses
in code, building reconciliation or drift checks, or looking at data that is suspected to be wrong.
It does not fire for the sequencing of a specific schema change, or for verifying one migration.

## Procedure

1. **Write the invariants down as sentences about the data.** "An order has exactly one customer."
   "A ledger's entries sum to its stored balance." "A subscription's end is never before its start."
   Harvest them from the domain, from the guard clauses already in the code, and from the bug
   history — past incidents are invariants that were discovered the expensive way. An unwritten
   invariant is enforced inconsistently by definition.

2. **For each one, find where it is enforced today.** Database constraint, application code, a
   nightly job, a convention, or nowhere. Read the catalog for the constraint and grep the code for
   the guard; do not infer either from the model definitions or the ORM declarations, which
   frequently describe a constraint the database does not have.

3. **Push each invariant to the lowest layer that can hold it.** In rough order of strength:
   the column type itself (no money in floating point, no enum as free text, no timestamp as a
   string), then NOT NULL, foreign keys with a deliberate delete behaviour, uniqueness, and check
   constraints; Postgres adds exclusion constraints for overlap rules. What the database enforces
   holds for every writer, including the ones you do not know about.

4. **Before adding a constraint, query for the rows that would violate it.** Dirty data makes the
   statement fail, or — worse — gets it added in an unvalidated form that silently grandfathers
   every bad row in. Report the violation count first; the cleanup is its own decision.

5. **Cover what a constraint cannot hold with a reconciliation query.** Cross-table sums against
   detail, cross-system counts against the upstream source, temporal rules (a state that must never
   move backwards), and derived columns against what they derive from. Write each one to return the
   offending keys, not a boolean — the result is both the alarm and the reproduction case.

6. **Run reconciliation on a schedule and keep the history.** Drift is a trend, not an event: a zero
   today tells you nothing unless yesterday's number is recorded next to it. Alert on the count
   crossing a threshold and on its rate of change. A check that runs but is never read is not a
   control.

7. **When drift is found, capture before you touch anything.** Snapshot the offending keys, find the
   earliest bad row by timestamp, and identify the write path that produced it. Repairing rows
   destroys the evidence of what wrote them, and a repair without the writer means the same drift
   returns next week.

8. **Treat any repair as a data migration.** Batched, resumable, reversible where it can be, and
   rehearsed against a copy. Correcting rows in a shared or production database is destructive and
   outward-facing: present the offending row count, the proposed statement and the reversal, and
   ask. Run it yourself only against a local or disposable copy.

9. **Leave the check behind, not just the fix.** The repaired rows are today's work; the
   reconciliation query and the constraint are what stop the next occurrence. A fix that ships
   without one of those is a fix with a return date.

## Checklist

- [ ] Invariants written down, each with the rule stated as a sentence
- [ ] Current enforcement point located per invariant — catalog and code, not the ORM's claims
- [ ] Each invariant pushed as low as it can go, or its reason for staying in app code recorded
- [ ] Existing violations counted before any constraint was proposed
- [ ] Reconciliation queries written for the rules constraints cannot hold
- [ ] Reconciliation scheduled, its output retained, and an alert attached
- [ ] Offending keys captured before any repair
- [ ] Repair rehearsed on a copy; the shared-environment run left to the user
- [ ] Regression check (constraint or reconciliation query) added alongside the fix

## Failure handling

- **A constraint cannot be added because rows violate it** — that is the finding, not an obstacle.
  Report the count and a sample of keys. Do not delete or coerce rows to make the DDL succeed.
- **Reconciliation finds a discrepancy you cannot explain** — report it unexplained, with the
  queries and the numbers. An unexplained discrepancy reported honestly is more useful than a
  plausible story about rounding.
- **The drift predates your history window** — say the start date is unknown rather than reporting
  the window's first sample as the beginning.
- **The check is expensive to run over the full table** — scope it to a recent window or a sampled
  range, and say which. A scoped check reported as a full check is a false all-clear.
- **You only have read access** — the audit and the reconciliation queries still stand. Report the
  enforcement gaps and the proposed constraints as unapplied.

## Evidence to report

The invariant list with, for each, where it is enforced now and where you propose it should be. The
violation counts, with the query that produced them. The reconciliation queries themselves and their
current output. Where drift was found: the offending key count, the earliest bad timestamp, and the
write path implicated — report keys and counts rather than pasting row contents, which routinely
carry personal data. Then what remains unenforced and unmeasured, named rather than left implicit.
