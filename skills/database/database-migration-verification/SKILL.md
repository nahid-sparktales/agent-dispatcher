---
name: database-migration-verification
description: Prove a migration did what it claimed — before/after row counts, column checksums, constraint and index state, invariant queries, an exercised application read path, and a rehearsed rollback. Use after a migration has been applied to any environment and before anyone reports it as working, or when reviewing someone else's claim that a migration succeeded. Not for planning or sequencing the migration (that is migrations), and it does not treat a clean exit code, a green CI run, or a backup's existence as proof.
---

# Database migration verification

"The migration ran" is a fact about a process exiting. It is not a fact about the data. A migration
can apply cleanly and still drop rows, leave a column half-backfilled, declare a constraint it
never validated, or build an index nothing uses.

## When this fires

A migration has been applied somewhere — local, branch, staging, production — and someone is about
to call it done, or you are checking that claim. It fires again after any re-run or fix. It does
not fire for a migration that has only been written.

## Procedure

1. **Write down the claim as checkable statements** before running anything. "Every order has a
   currency." "No order row was lost." "`total` equals the sum of its line items." A claim that
   cannot be expressed as a query cannot be verified here — mark it unverifiable rather than
   quietly dropping it.

2. **Get the before-state, or declare it missing.** Row counts, aggregate checksums and constraint
   state captured before the migration ran. If nobody captured them, you can still check the
   after-state against the schema and the invariants — but you cannot prove nothing was lost. Say
   that in those words; do not let the rest of the evidence imply it.

3. **Confirm what actually ran.** Read the migration history in the database and compare it to the
   files in the repository: which versions are recorded, in what order, at what time. A successful
   command exit is not the record. A migration file present in the repo but absent from the history
   is a finding.

4. **Count rows per affected table** and compare to the before-state with the delta you predicted
   in advance. A mismatch is a defect. A match is necessary, not sufficient — equal counts are
   consistent with every value being wrong.

5. **Checksum the columns that moved.** For each copied or transformed column, compare an
   order-independent aggregate against the source column or the before-state: sum, min/max, count
   of distinct values, count of nulls, and a hash aggregate over key plus value. Aggregate over the
   whole table, not a sample, unless the table is too large to scan — and if you sample, say you
   sampled and how.

6. **Check constraint and index state, not constraint and index existence.** Every constraint
   added must be validated rather than left unvalidated — read the catalog, do not infer it from
   the DDL. Every index must be valid (a failed concurrent build leaves one that is not) and must
   actually be chosen by the query it was added for; read the execution plan. An index the planner
   ignores is built, not verified.

7. **Run the invariant queries** for orphaned foreign keys, nulls in columns intended to be
   non-null, duplicates in columns intended to be unique, values outside their intended range, and
   any domain rule from step 1. Write them to return offending rows, not a boolean — zero rows
   returned is the evidence, and a non-zero result hands you the defect directly.

8. **Exercise the application's read path.** A correct schema does not mean the code reads it.
   Run the real code path against the migrated database — the test that covers it, or the request
   that hits it — and check the values it returns, not just that it did not throw.

9. **Rehearse the rollback on a copy.** Take a copy or branch at the migrated state, run the down
   path, and re-run the counts and invariant queries against the result. An unexecuted rollback is
   a plan. Where the rollback is a restore from backup, the rehearsal is an actual restore into a
   disposable target — time it and record the recovery point it lands on. Never rehearse a rollback
   against the environment people are using; if the only copy available is production, stop and ask.

10. **Report with the words kept apart** — written, applied, executed, tested, rolled back in
    rehearsal, verified. Each one names something different, and this procedure exists because they
    get conflated.

## What this refuses to conclude

- **Without a before-state:** that no data was lost. Counts after the fact cannot establish it.
- **Without checksums:** that a transformed column is correct. A column full of the right *shape*
  of wrong value passes every count.
- **Without a validated constraint read from the catalog:** that the constraint is enforced.
- **Without an executed rollback:** that the migration is reversible.
- **Without exercising the read path:** that the application works against the new schema.
- **Without running against the environment in question:** anything about that environment. A pass
  on staging is evidence about staging.

## Checklist

- [ ] Claims written as queries before running anything
- [ ] Before-state present, or its absence stated as a limit on the conclusion
- [ ] Migration history read and reconciled against the repository
- [ ] Row counts compared per table against a predicted delta
- [ ] Column checksums compared for every transformed or copied column
- [ ] Constraints confirmed validated from the catalog; indexes confirmed valid and chosen
- [ ] Invariant queries run, returning rows rather than booleans
- [ ] Application read path exercised against the migrated database
- [ ] Rollback executed on a copy, with counts re-checked and timing recorded
- [ ] Environment named; unverified claims listed explicitly

## Failure handling

- **A count or checksum disagrees** — that is the result. Report the discrepancy and the query that
  found it. Do not re-run the backfill over the top to make the numbers match; that hides which
  rows were wrong.
- **Invariant query returns rows** — capture the offending keys before anything else changes them.
  Those rows are the reproduction case.
- **The rollback fails in rehearsal** — the migration is not reversible. Report it as such
  immediately; that fact usually changes the deployment decision.
- **No non-production copy exists to rehearse against** — say the rollback is unrehearsed. Do not
  rehearse on the live system to fill the gap.
- **Read-only access only** — the read-side checks still stand. Report them as done and the rollback
  rehearsal as not performed, rather than downgrading the whole verification to an opinion.

## Evidence to report

The environment. The queries you ran, verbatim, with their results — before and after side by side.
The migration versions recorded in the history. Constraint and index state as read from the catalog.
Which read path was exercised and what it returned. The rollback rehearsal: that it ran, how long,
and what the post-rollback counts were. Then the explicit list of what was **not** checked. A
summary that says "verified" without these is a claim, not verification.
