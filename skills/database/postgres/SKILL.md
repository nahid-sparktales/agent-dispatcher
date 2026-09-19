---
name: postgres
description: Postgres behaviour worth checking before relying on it — type choices, index kinds and their costs, reading EXPLAIN output, isolation levels and lock behaviour during DDL, and row-level security. Use when the project runs on Postgres (including Postgres-backed services) and a decision depends on what the engine actually does: picking a column type, adding an index, changing isolation, or writing and debugging an RLS policy. Not for engine-neutral modelling decisions, and not for the measure-fix-measure loop on one slow query.
---

# Postgres

Most Postgres surprises come from defaults: the default isolation level, the default lock an
`ALTER TABLE` takes, what happens to a table with RLS enabled and no policy. Check the default
before designing around what you assume it is.

## When this fires

The project is on Postgres and the answer depends on engine behaviour rather than on modelling.
It does not fire as a tour — read the section the decision needs. It does not fire for another
engine, and Postgres-compatible services differ in what they permit, so confirm rather than assume.

## Procedure

1. **Establish what you are actually talking to.** `select version();` and list the installed
   extensions before writing DDL that depends on one. Major versions differ in defaults and in
   available syntax, and an extension you assume is present (`citext`, `pg_stat_statements`,
   `pgcrypto`, `postgis`) is either installed or it is not. If the version is unknown, prefer the
   long-standing form of a feature over the newest one.
2. **Choose types on meaning.** `text` for strings unless a length is a real constraint worth
   enforcing; timezone-aware timestamps for instants and plain `date` for dates; `numeric` for
   money and never a float; `uuid` as a type rather than a string; `jsonb` when the shape is
   genuinely open, with the understanding that it defers validation to every reader. Enum types
   are cheap to extend and awkward to shrink — a lookup table with a foreign key is the reversible
   version.
3. **Know what each index kind is for.** B-tree is the default and serves equality, ranges and
   ordering. GIN suits containment queries over documents, arrays and full-text. GiST suits ranges
   and geometry, and backs exclusion constraints. BRIN is for very large tables whose physical
   order tracks the indexed value. Partial indexes carry a WHERE clause and are the tool for "at
   most one active row"; expression indexes match predicates that wrap the column in a function.
4. **Remember what indexes cost and what they do not do.** Every index is maintained on every
   write. In a multicolumn index, column order decides which queries it can serve. Declaring a
   foreign key does not create an index on the referencing column — a missing one shows up as slow
   cascading deletes and slow parent updates. A unique index treats NULLs as distinct by default,
   so it does not prevent repeated NULL rows.
5. **Get a plan before believing any performance claim.** `EXPLAIN` gives estimates;
   `EXPLAIN (ANALYZE, BUFFERS)` runs the statement and reports what really happened. Because
   ANALYZE executes, run a data-modifying statement inside a transaction you roll back — and on a
   shared database, ask before running it at all. Read the actual-versus-estimated row counts
   first: a large gap means the planner is working from statistics that do not describe this data.
   The per-node loop count multiplies the reported time. The tuning loop itself belongs to the
   query-optimization skill.
6. **Pick an isolation level for what the code needs.** The default, READ COMMITTED, gives each
   statement a fresh snapshot, so two statements in one transaction can legitimately disagree.
   REPEATABLE READ holds one snapshot for the whole transaction. SERIALIZABLE enforces invariants
   no constraint can express, at the price of serialization failures the application must catch
   and retry — choosing it without a retry path converts a rare anomaly into a user-visible error.
   Explicit row locks (`FOR UPDATE`) are the narrower tool when the conflict is one row.
7. **Treat locking as part of any DDL.** Schema changes take table-level locks, and a statement
   waiting for one blocks every query queued behind it, so a fast migration can still stop the
   application. Set a lock timeout, keep each statement short, and build indexes concurrently when
   the table is live — noting that a concurrent build runs outside a transaction block and can
   leave an invalid index behind that has to be dropped and retried. Running any of this against a
   shared or production database is an authorized action: produce the statements, say what they
   will lock, and stop.
8. **Write RLS policies against the role that will run the query.** Enabling row-level security on
   a table with no policy denies everything. `USING` decides which rows are visible or reachable;
   `WITH CHECK` decides which rows may be written — a policy with only `USING` can still let a row
   be written into a state the writer cannot see afterwards. Permissive policies combine with OR,
   restrictive ones with AND. The table owner is not subject to RLS unless the table forces it, so
   testing a policy while connected as the owner proves nothing: test as the application role.
9. **Keep statistics honest.** Run ANALYZE after a bulk load or a large backfill, because a plan
   built on empty-table statistics is not the plan production will get. Correlated columns
   routinely produce bad estimates that no index fixes; extended statistics are the tool for that
   case. Long-lived transactions hold back cleanup and cause bloat — check for them before
   blaming the query.
10. **Check the connection layer before debugging session state.** Under transaction-level pooling,
    session-scoped things — `SET`, advisory locks, temporary tables — do not reliably belong to the
    next statement your code runs. If an RLS context or a timeout is set per session, confirm the
    pooling mode supports it.

## Checklist

- [ ] Server version and installed extensions confirmed, not assumed
- [ ] Types chosen for meaning; no float money, no string-typed timestamps
- [ ] Index kind and column order justified by the predicate and ordering it must serve
- [ ] Any performance claim backed by a plan, not by reasoning about the query text
- [ ] Isolation level named, with the retry path if serialization failures are possible
- [ ] DDL's lock behaviour stated; nothing run against a shared database without authorization
- [ ] RLS policies cover read and write, and were exercised as the application role
- [ ] Statistics refreshed after any bulk data change that precedes a measurement

## Failure handling

- **A feature is missing or the syntax is rejected.** Check version and extensions before
  rewriting the query; a managed Postgres service may also withhold superuser-level operations
  entirely. Report the restriction instead of routing around it with something weaker.
- **The plan on your machine does not match production.** Different data volume, different
  statistics, different configuration. State which environment produced the plan; a plan from a
  small dataset supports no conclusion about production.
- **RLS "works" in testing.** Confirm the role. Owner and bypass-privileged roles skip policies,
  and a policy that was never actually applied looks exactly like one that permits everything.
- **A migration hangs.** It is waiting on a lock, and it is now also blocking everything behind it.
  Find the blocking transaction rather than retrying. Cancel and reschedule instead of waiting it
  out during traffic.
- **An index was added and nothing got faster.** The planner may be right to ignore it. Re-read the
  plan before adding another; two unused indexes cost more than one.

## Evidence to report

The version and extensions you confirmed; the exact DDL or SQL; plans quoted as output rather than
described; which role and which database the check ran as; lock and rollout implications for
anything not yet applied. Say which environment each result came from, and never describe DDL you
have only written as DDL that has been executed, tested or deployed.
