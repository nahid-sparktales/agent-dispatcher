---
name: query-optimization
description: Make one slow query fast without guessing — capture the plan, find where the time actually goes, change one thing, and measure again on comparable data. Use when a query, endpoint or report is slow and the database is the suspect, when a plan needs reading, or when someone proposes an index with no evidence. Not for modelling decisions about tables and constraints, not an engine feature reference, and not for system-wide performance work where the database has not yet been shown to be the bottleneck.
---

# Query optimization

An index added on a hunch is a permanent write cost bought with no evidence. The work here is
measurement: the plan before, one change, the plan after, on data that resembles the data that is
actually slow.

## When this fires

A specific statement is slow, or a plan needs interpreting, or a proposed index needs justifying.
It does not fire before the database has been shown to be where the time goes — if that is still
open, measure the request end to end first. It does not fire for redesigning the tables.

## Procedure

1. **Get the exact statement and its parameters.** Not "the dashboard is slow" — the SQL text as
   the database received it, with the bind values, and where it runs from. A statement-statistics
   view, the ORM's query log or the application log will have it. The parameters matter: the same
   query can take different plans for different values.
2. **Confirm the database is the bottleneck.** Compare the statement's own time against the total
   request time. If the query is 40ms of a 3s request, stop here and say so. Note whether the cost
   is one slow statement or many fast ones — an N+1 is fixed in the calling code, not by an index.
3. **Reproduce it on comparable data.** Row counts, value distribution and index state have to
   resemble production, because a table small enough to sit in memory makes every plan look fine.
   If comparable data is not available, that limitation is the headline of your report, not a
   footnote.
4. **Capture the plan before changing anything**, with actual execution and buffer statistics, and
   keep the output. This is your *before*, and without it there is no after. Where the statement
   modifies data, run it inside a transaction you roll back — and on a shared or production
   database, ask before running anything at all.
5. **Read the plan for the node that actually costs**, not the top line. Work from the largest
   actual time, remembering that a node's reported time is per loop and multiplies by its loop
   count. Then compare estimated rows against actual rows at that node: a large gap means the
   planner's information is wrong, and fixing the information often beats fixing the query.
6. **Classify what you found before proposing anything.** A sequential scan of a large table under
   a selective predicate points at a missing or unusable index. A huge row count discarded by a
   filter after an index scan points at the wrong index. A nested loop with an enormous loop count
   usually points at a bad estimate upstream. A sort or hash spilling to disk points at memory
   limits or an avoidable sort. A function evaluated per row points at the expression, not the
   index.
7. **Try the cheapest fix first.** Remove work before adding structure: fewer columns, fewer rows,
   a bounded result, a join that was never needed, a repeated query collapsed into one. Then make
   the predicate usable by an index — a column wrapped in a function cannot use an ordinary index
   on that column, so either unwrap it or index the expression. Only then add or adjust an index.
   Materialized or denormalized copies come after that, and engine configuration last.
8. **Choose the index to match the predicate and the ordering.** Equality columns come before range
   columns in a multicolumn index; the ordering the query needs can remove a sort. A partial index
   fits a query that always carries the same filter. Before creating anything, list the existing
   indexes and check whether one already covers the access pattern — a near-duplicate index is
   pure cost.
9. **Change one thing and re-measure identically.** Same data, same parameters, same method,
   several runs. Report cold and warm separately or not at all, because the second run of anything
   is faster and that difference is not your fix.
10. **Check what else moved.** An index changes write latency and can change plans for other
    statements. If you dropped or replaced one, name the queries that were using it. If the fix was
    a schema or configuration change, say what else it touches.
11. **Stop before applying it to a shared database.** Creating, dropping or rebuilding an index on
    a live system takes locks and time. Hand over the statement, the expected lock behaviour, and
    the measured benefit, and let the decision to run it be made explicitly.

## Checklist

- [ ] Exact statement and parameters captured
- [ ] The database was shown to be the bottleneck, with the share of total time
- [ ] Dataset size and distribution stated, and their comparability to production assessed
- [ ] Before plan captured with actual execution statistics and kept
- [ ] The expensive node identified, with estimated-versus-actual rows read
- [ ] Exactly one change made per measurement
- [ ] Existing indexes listed before a new one was proposed
- [ ] After plan and timings captured the same way as the before
- [ ] Write cost and effects on other queries considered
- [ ] Nothing applied to a shared or production database without authorization

## Failure handling

- **The query is fast when you run it.** Something else is the real difference — parameters, cache
  state, concurrency, connection setup, or the client fetching every row. Do not conclude "no
  problem found"; report what you measured and what still differs from the slow environment.
- **Only a small dataset is available.** Say it. Results from a table that fits in memory are not
  transferable, and an index recommendation from one is a guess wearing a measurement's clothes.
- **Estimates are far from actuals.** Refresh statistics and re-plan before touching indexes. Stale
  statistics produce bad plans that new indexes will not repair, and correlated columns need a
  different remedy from a missing index.
- **The improvement is within run-to-run noise.** It is not an improvement. Run more iterations or
  drop the change.
- **The real fix is the data model.** Say so, and do not paper over it with indexes — hand it to
  the schema work with the plan as evidence.
- **No access to production-like data or plans.** Report the query as *analyzed*, not as
  *optimized*. An unmeasured change is a proposal.

## Evidence to report

The statement and parameters; the before and after plans as output, not paraphrase; timings with
the number of runs and the cache state; the dataset's row counts; the single change made; existing
indexes considered; write-side and cross-query effects; anything left unmeasured. Keep the words
honest — *analyzed*, *changed*, *measured* and *deployed* describe four different states, and only
a measured before and after supports the word *faster*.
