---
name: schema-design
description: Turn what a system must guarantee into tables, keys and constraints — normalization judgement, nullability, foreign key behaviour, and naming that survives. Use when designing new tables, reviewing ORM models or a migration's DDL, or when a bug reduces to "the database allowed a row that should be impossible". Not for tuning a slow query, not for engine-specific syntax and features, and not for writing or running the migration that ships the change.
---

# Schema design

The schema is the last place a rule is still enforced. Application code, a background job, a psql
session and next year's import script all write to the same tables; only the constraints apply to
all of them.

## When this fires

Designing new tables, adding columns to existing ones, reviewing ORM models or DDL in a migration,
or when a defect traces back to the data model permitting an impossible state. It does not fire
for a query that is merely slow — that is a plan problem, not a modelling one.

## Procedure

1. **Read the existing schema before proposing anything.** Get the real DDL, constraints and
   indexes for the tables involved — `\d+` in psql, `information_schema`, or the migration files
   if that is all the access you have. Note the conventions already in use: plural or singular
   table names, key style, timestamp columns. You are joining a schema, not starting one.
2. **Write each invariant as one sentence.** "An order belongs to exactly one customer." "A
   subscription has at most one active period at a time." "An email identifies at most one
   account." Derive these from behaviour and from what breaks when they are violated, not from the
   nouns in the request. Each will become a constraint or fail to; the ones that fail are your
   risk list.
3. **Separate entities from attributes.** A thing that is only ever reached through its parent and
   is never queried, counted or referenced on its own is a column, not a table. A thing with its
   own lifecycle, identity or history is a table even when there is currently one of them.
4. **Normalize to third normal form by default** — one fact, one place. Denormalize only with a
   measured read problem and a written mechanism that keeps the copy honest (generated column,
   trigger, materialized view, or an application invariant plus a reconciliation job that can
   detect drift). "It will be faster" with no measurement is not a reason, and the measured answer
   is usually an index, not a duplicated column.
5. **Choose keys deliberately.** Every table gets a primary key. A surrogate key is the default
   because natural keys change — but adding one does not excuse you from declaring the natural
   uniqueness as its own UNIQUE constraint, or duplicates become legal and will appear. For a pure
   join table the composite of the two foreign keys is usually the right primary key.
6. **Encode invariants as constraints, not intentions.** NOT NULL for anything the system cannot
   operate without; UNIQUE, including a partial unique index for "at most one active X per Y";
   CHECK for ranges, allowed values and cross-column rules; FOREIGN KEY with an ON DELETE action
   chosen on purpose, since RESTRICT, CASCADE and SET NULL are three different operational
   promises. Any invariant you cannot express declaratively gets named in the design along with
   where it is enforced instead.
7. **Decide what NULL means for each nullable column.** "Not yet known", "not applicable" and
   "none" are three different facts and at most one of them should be NULL; the others want a
   sentinel, a separate flag, or a separate table. Remember NULL compares equal to nothing,
   including itself, so uniqueness and CHECK behave differently around it than readers expect.
8. **Pick types for meaning, not convenience.** Instants as timezone-aware timestamps, dates as
   dates, money as exact decimal and never float, identifiers as the type they actually are. For
   what a specific engine offers, read the engine's own skill rather than guessing.
9. **Name so the name survives.** Follow the existing convention over your preference. snake_case,
   foreign keys as `<referenced_table>_id`, no type in the name, no abbreviation only you
   understand, no reserved words, no column called `data` or `info`. Renaming later is a
   coordinated change across every reader in every deployed version.
10. **Check the model against the queries it will serve.** List the three to five real access
    patterns. If a common one needs a join no key supports, or a scan of an unbounded table, or a
    column that does not exist yet, the model is wrong — fix it now, not with an index later.
11. **Make the change shippable.** Expand then contract: add the new nullable or defaulted column,
    backfill, start writing both, move reads, then drop the old one — with each step deployable
    while the previous application version is still running. Applying any of it to a shared or
    production database is a separate authorized step: hand over the DDL and stop there.

## Checklist

- [ ] Current DDL, constraints and indexes read, not inferred from models
- [ ] Every invariant written down, and each mapped to the constraint that enforces it
- [ ] Invariants that cannot be enforced declaratively are named, with where they are enforced
- [ ] Primary key on every table; natural uniqueness declared even where a surrogate key exists
- [ ] Every foreign key has a deliberate ON DELETE action
- [ ] Every nullable column has a stated meaning for NULL
- [ ] Naming matches the conventions already in the schema
- [ ] The real access patterns were checked against the model
- [ ] The rollout is expand/contract and compatible with the running application version
- [ ] Nothing was applied to a shared database

## Failure handling

- **Only the ORM models are visible.** Design against them, and say plainly that the live schema
  was not inspected — ORM definitions drift from the database, and indexes and CHECK constraints
  often exist in only one of the two.
- **Existing rows violate a constraint you want to add.** Count them first. The count decides the
  plan: clean the data, scope the constraint with a partial index, or enforce it only for new rows.
  Adding a constraint that the current data fails is a failed deployment, not a design.
- **An invariant needs cross-row or cross-table logic.** Say so rather than pretending a CHECK can
  do it. Name the alternative — a partial unique index, an exclusion constraint, a trigger, or a
  serializable transaction — and its cost.
- **Pressure to add a column "for later".** Do not. An unused nullable column is a claim nobody
  maintains; add it when the behaviour arrives.
- **Disagreement about normalization.** Resolve it with the invariant, not with taste: if two
  copies of a fact can disagree and nothing detects it, that settles it.

## Evidence to report

The proposed DDL; the invariant list with the constraint enforcing each; the invariants left
unenforced and where they are enforced instead; row counts for anything an existing table would
have to satisfy; the access patterns checked. Be exact about status — a schema that has been
*designed* or *reviewed* is not one that has been *applied*, and neither is one that has been
*tested* against representative data.
