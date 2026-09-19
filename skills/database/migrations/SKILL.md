---
name: migrations
description: Change a live schema without breaking the application on it — expand/contract sequencing, lock-safe DDL, batched backfills, and a rollback that is actually reachable. Use when writing, reviewing or sequencing a migration that will run against a database holding real data with live readers. Not for designing a schema from scratch, not for proving afterwards that a migration did what it claimed (that is database-migration-verification), and it never runs the production step for you.
---

# Live schema migrations

A migration that passes on an empty dev database proves the SQL parses. It says nothing about how
long the lock is held, whether the old application version still reads the column you dropped, or
whether the rollback can reach the data.

## When this fires

You are about to write, review or sequence a schema or data migration against a database that has
rows in it and something reading them. It does not fire for greenfield schema design, for a
throwaway local database, or for a query change with no DDL.

## Procedure

1. **Read the current state before writing any SQL.** The live schema, the migration history, and
   every reader of the objects you are touching — grep the application, the reports, the jobs, the
   other services. A column no code in this repo reads may still be read by a deployed older
   version. Name the readers you found; say if you could not enumerate them.

2. **Classify the change.** *Additive* (new table, new nullable column, new index), *rewriting*
   (type change, adding NOT NULL or a unique constraint to existing data, renaming, dropping), or
   *data-only* (backfill, correction). Only additive is safe to ship as one step. Everything else
   gets sequenced.

3. **Sequence anything non-additive as expand → migrate → contract, across separate deploys.**
   - *Expand* — add the new shape: nullable, unconstrained, unused. Old code is unaffected.
   - *Dual-write* — deploy code that writes both shapes. Wait until every running instance is on
     that version, including anything that scales up from an older image.
   - *Backfill* — fill the historic rows (step 5).
   - *Switch reads* — deploy code that reads the new shape. Watch before going further.
   - *Contract* — drop the old shape in a **later** migration, once no supported version reads it.

   Collapsing these into one migration is the most common way a change described as backward
   compatible takes the application down.

4. **Make the DDL lock-safe.** Every statement takes a lock; what matters is which lock, for how
   long, and what queues behind it. A strong lock waiting on one slow query blocks every read that
   arrives after it.
   - Set a short lock timeout (and statement timeout) for the migration session so blocked DDL
     fails fast instead of stalling the table. Retry; do not wait.
   - Build indexes without holding a write lock where the engine supports it. On Postgres that is
     the concurrent index build — it cannot run inside a transaction block, and a failed one
     leaves an invalid index behind that must be dropped before retrying.
   - Add check and foreign-key constraints unvalidated first, then validate as a separate
     statement, so the full-table scan does not sit under a strong lock.
   - On MySQL, confirm the operation is genuinely online for that version and storage engine, or
     route it through online-schema-change tooling (gh-ost, pt-online-schema-change) instead.
   - Do not assume adding a column is free. Whether it rewrites the table depends on engine,
     version, and whether the default is a constant.

5. **Batch the backfill.** Bounded ranges over the primary key, committed per batch, resumable
   from a recorded cursor, with a pause between batches. A single statement across the whole table
   holds locks for its whole duration, bloats WAL/undo, and cannot be stopped halfway. Backfill
   in the database where the transform is expressible in SQL; reprocessing rows through the
   application pipeline that produced them re-runs its side effects.

6. **Write the rollback and say plainly what it cannot recover.** Dropping a column you just added
   is a real rollback. A down migration after a destructive step re-creates the *shape*, not the
   *data* — that rollback is a restore from backup. When that is the case, say so, name the backup
   that would be used, and state how long a restore takes. Never describe an irreversible
   migration as reversible.

7. **Rehearse on a copy with realistic volume.** Record per-statement duration and what each one
   locked. Timings from a small dataset are not evidence about production.

8. **Stop before the production run.** Applying to a shared or production database is an
   outward-facing and potentially destructive action: present the plan, the rehearsal timings, the
   rollback and its limits, and ask. Apply to a local, branch or disposable database yourself;
   promoting it is the user's call, not yours.

9. **Hand off to verification.** Applying is not verifying. The before-counts and checksums that
   `database-migration-verification` needs have to be captured *before* the migration runs — take
   them in this procedure or they are gone.

## Checklist

- [ ] Every reader of the touched objects enumerated, or the gap named
- [ ] Change classified; anything non-additive split across deploys
- [ ] Contract step is a separate, later migration
- [ ] Lock and statement timeouts set for the migration session
- [ ] Index builds and constraint validation kept off strong locks
- [ ] Backfill batched, resumable, and expressible without re-running app side effects
- [ ] Rollback written, and its limits stated where it cannot restore data
- [ ] Rehearsed on realistic volume, with timings recorded
- [ ] Before-state counts and checksums captured for verification
- [ ] Production application left to the user, with the plan presented

## Failure handling

- **DDL blocks and the timeout fires** — that is the timeout working. Find the blocking session,
  wait for a quieter window, retry. Do not raise the timeout to push it through.
- **A concurrent index build fails** — the leftover index is invalid and will not be used. Drop it
  explicitly before retrying; a retry alone does not clean it up.
- **The backfill dies partway** — resume from the recorded cursor. If there is no cursor, you
  cannot tell done rows from undone ones without a full comparison; say that rather than
  re-running blind.
- **Rehearsal timings look fine but production is much larger** — the rehearsal did not cover it.
  Say the lock duration is unknown at production scale instead of extrapolating.
- **You cannot reach a database at all** — the migration is written, not tested. Report it as
  written, and do not call it safe.

## Evidence to report

The migration files, in the order they deploy. The classification and the deploy boundaries. Per
statement: what lock it takes and how long the rehearsal took, with the row count it ran against.
The backfill's batch size and resume mechanism. The rollback, and what it cannot recover. The
readers you enumerated and the ones you could not. What is still unapplied and awaiting approval —
stated as unapplied, not as done.
