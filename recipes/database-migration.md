---
id: database-migration
name: "Migrate a database"
summary: "Change a live schema without losing data, with the rollback rehearsed before it is needed."
use_when: "A schema change has to reach an environment that already holds data people care about."
capabilities: database.schema, database.migrations, verification.database, database.integrity
roles: explorer, database-engineer, planner, implementer, tester, reviewer
---

# Migrate a database

## Steps

1. **Read the current schema and its consumers.** Every reader and writer of the affected tables,
   including jobs and analytics. → `schema-design`
2. **Choose the shape.** Expand/contract for anything that cannot take downtime: add, backfill,
   switch reads, stop writes to the old, then drop — in separate deployments. → `migrations`
3. **Plan the rollback before writing the migration.** Some steps are not reversible; name them
   explicitly so the decision to proceed is made knowingly.
4. **Write the migration and the backfill separately.** A backfill inside a schema migration holds
   locks for as long as the data takes.
5. **Run it against a copy** with production-like volume. A migration that is instant on ten rows
   can lock a table for minutes on ten million.
6. **Verify.** Row counts, checksums on touched columns, constraint and foreign-key checks, NULL
   rates on backfilled columns. → `database-migration-verification`
7. **Have it reviewed by someone who did not write it.**

## Gates

- The rollback path is written down, and anything irreversible is named.
- The migration ran against realistic data, and the timing is reported.
- Post-migration integrity was checked by comparison against the source, not by the migration
  reporting success.
- "The migration file exists" is never reported as "the migration ran".
