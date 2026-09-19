---
name: data-quality
description: Decide what must be true of a dataset and where that assertion belongs — freshness against event time, volume floors and bands, distribution and referential checks, source reconciliation, and whether it should be a schema constraint, a blocking publish gate or an alert. Use when adding or reviewing data checks, when a wrong number reached a consumer and nothing caught it, or when a check fires so often it is being ignored. Not for proving a specific migration did what it claimed (database-migration-verification), not for building the pipeline itself (data-pipelines), and not for interpreting what the numbers mean.
---

# Data quality assertions

A wrong number looks exactly like a right one. Nothing about a dashboard, a type check or a green
job reveals that the load was half-empty, that a join fanned out, or that a column has been null
since Tuesday. The only thing that reveals it is an assertion someone wrote in advance — placed
where it fires before a consumer acts on the number, not after.

## When this fires

Checks are being added to or reviewed on a dataset; a bad value reached a consumer and no check
caught it; or an existing check is noisy enough that people are muting it. It does not fire for a
one-off verification of a migration, for enforcing an invariant inside a single application write
path, or for deciding what a metric means.

## Procedure

1. **Start from the failure that hurt, not from a catalog of check types.** Which wrong value
   reached whom, how long it took to notice, and what would have caught it earliest. Generic
   not-null checks generated across four hundred columns produce noise, and a noisy channel is a
   muted channel — that is a net loss, not a neutral one.

2. **Place each assertion on the lowest rung that can hold it.** This is the load-bearing decision
   and it is usually made by accident:
   - *A schema constraint* — NOT NULL, UNIQUE, a foreign key, a CHECK. It cannot be bypassed by
     any writer and fails at write time. If the rule can be a constraint, it is a constraint
     (`schema-design` covers designing it).
   - *A gate at the pipeline's write boundary* — runs before publish and blocks it. Use when the
     rule needs the whole batch, or the destination cannot express the constraint.
   - *A scheduled check against the landed table* — alerts after the fact. Use when the rule needs
     cross-table or historical context that only exists once the data is landed.
   - *A check in the consumer's own query or report* — last resort. Cheapest to add, latest to
     fire, and the easiest for everyone to scroll past.

   For each assertion, record the rung and why not the one above it.

3. **Write every assertion as a query that returns the offending rows**, not a boolean and not a
   count. Zero rows is the pass; a non-zero result hands the next person the reproduction case
   instead of a number to go and re-derive.

4. **Assert freshness against event time, not against the job.** A job that succeeded and wrote
   nothing passes every liveness check there is. Assert that the maximum event timestamp in the
   table is within the consumer's stated tolerance of now, per partition or per source, and
   derive that tolerance from what the consumer actually needs rather than from how often the job
   happens to run.

5. **Assert volume with both a floor and a band.** An absolute floor catches the empty load. A
   relative band against comparable recent windows — same weekday, same hour — catches the
   half-load that a floor sails past. Neither alone is enough: a floor misses a fifty percent drop,
   a band alone fires every holiday and every launch. State the comparison window you chose.

6. **Assert distribution on the fields decisions depend on.** Null rate, distinct cardinality,
   category mix against the known set of allowed values, numeric range, and a mean or percentile
   within a band. A column full of schema-valid wrong values passes every type check in the stack.
   Anchor to a known-correct set — an enum, a dimension table, a reference feed — wherever one
   exists; comparing to yesterday only inherits yesterday's defects.

7. **Assert referential integrity and grain in the same pass.** Orphans at each join key (fact rows
   with no matching dimension row, and the reverse where it matters), and uniqueness of the key
   that defines the grain. Then check fan-out explicitly: a join emitting more rows than its left
   side is a duplicate-key defect, and it inflates every sum computed downstream of it while
   leaving each individual row looking correct.

8. **Reconcile against the system of record, not just internally.** Row count and the sums of
   additive measures per window, compared to the source. Internal consistency proves the transform
   agrees with itself. State the tolerance and where it comes from; a tolerance chosen after seeing
   the discrepancy is not a tolerance.

9. **Give every check a severity, an owner and an action, decided at the same time as the
   threshold.** Blocking the publish, or alerting a named person. A check with no action is a
   metric. A blocking check with no recorded override path gets deleted during the first incident
   where someone needs the data anyway — provide the override and log its use instead.

10. **Make each check fail on purpose before trusting it.** Run it against a deliberately broken
    fixture or a slice you have corrupted — a nulled column, a dropped day, a duplicated key.
    An assertion never observed failing is not known to work, and this is the step almost every
    check skips. A check that cannot be made to fail is asserting nothing.

11. **Stop before touching data to satisfy a check.** Quarantining, deleting, overwriting or
    excluding rows so a check passes is destructive and is the user's call, not yours. So is
    wiring a check to page a team. Report the offending rows; propose the remedy; ask.

12. **Keep the words apart in the report** — asserted, executed, failed on purpose, reconciled,
    deployed. A check that exists in a file is written, not running.

## Checklist

- [ ] Assertions derived from a real failure or a real consumer need
- [ ] Each one placed on a named rung, with the reason it is not one rung lower
- [ ] Every check returns offending rows rather than a boolean
- [ ] Freshness measured on event time, against a consumer-stated tolerance
- [ ] Volume has both an absolute floor and a relative band, with the comparison window named
- [ ] Distribution checks cover the fields decisions depend on, anchored to a known-correct set
- [ ] Orphan, grain-uniqueness and fan-out checks all present
- [ ] Source reconciliation run, with a tolerance set in advance
- [ ] Severity, owner, action and override path recorded per check
- [ ] Each check observed failing against a broken fixture
- [ ] Anything left unasserted stated explicitly

## Failure handling

- **A check fires and the data is fine** — that is a defect in the check. Tune the threshold using
  the observed history or delete it. Muting it is deleting it while pretending otherwise.
- **A check fires and the data is wrong** — capture the offending keys before anything reruns or
  overwrites them; those rows are the reproduction case, and the next run may erase them.
- **Reconciliation is off by a small amount** — do not widen the tolerance to cover it. Find which
  rows account for the difference; a persistent small gap is usually a systematic rule, not noise.
- **Nobody can state a freshness or volume expectation** — say the check is unanchored rather than
  inventing a threshold. An invented threshold fires on the wrong things and teaches people the
  channel is unreliable.
- **Only read access to the target** — the assertions still stand as queries and still run. Report
  them as run and any gating or scheduling as not installed, rather than downgrading the whole
  thing to an opinion.

## Evidence to report

Each assertion: the query verbatim, the rung it sits on, the threshold and where the threshold came
from. The result of running it now, as rows or as an explicit zero. The deliberate-failure run that
showed it works. The reconciliation figures against the source, per window, with the tolerance
stated in advance. The severity, owner and action for each check. Then the fields, tables and
windows deliberately left unasserted — the gap is part of the report, not an omission from it.
