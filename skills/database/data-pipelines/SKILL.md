---
name: data-pipelines
description: Build and repair batch and streaming pipelines that can be run twice without lying — lineage, event-time windowing, late arrivals, re-runnable writes and bounded backfills. Use when writing or fixing a pipeline, scheduled transform or job that produces data someone reads, when a run dropped or duplicated rows, or when planning a backfill. Not for designing the destination schema or its migrations, not for the standing assertions that guard the data afterwards (data-quality), and not for interpreting what the numbers mean.
---

# Data pipelines

Exit code zero says a process ended. It does not say the partition is complete, that the rows
match the source, or that running it again will not double every total downstream. Most pipeline
damage is done by a rerun that looked like a repair.

## When this fires

A pipeline, scheduled transform, ingestion job or notebook-promoted-to-job is being written,
changed or debugged; or a backfill is being planned. It fires when a run dropped, duplicated or
reshaped rows. It does not fire for a code defect unrelated to data movement, for the destination
schema's design, or for the scheduler platform itself.

## Procedure

1. **Trace lineage before editing anything.** Every upstream input, each transform step, the
   destination tables, and everything that reads them — reports, dashboards, downstream jobs,
   feature tables, exports. The blast radius is what you enumerate, not what you assume. Name the
   readers you found and say plainly which you could not enumerate.

2. **Write down the current contract**, even if nobody else has. The grain (one row per *what*),
   the partition or batch key, the expected volume per window, the freshness the consumer relies
   on, and the existing duplicate and late-arrival behaviour. Where you inferred this from the
   data rather than from documentation, say it is inferred.

3. **Separate the three clocks and pick one.** *Event time* is when the thing happened, *ingestion
   time* when it landed, *processing time* when the job touched it. Partition and window on event
   time; reprocessing changes the other two, and any result that depends on them changes when you
   rerun. Record the timezone and whether the boundary is inclusive — an off-by-one-hour partition
   is indistinguishable from data loss in a count.

4. **Say what closes a window.** A window that never closes never emits; one that closes too early
   drops the stragglers. Fix an allowed lateness against observed arrival lag, not a round number,
   and give data that arrives after the boundary a defined destination: reprocess the window, route
   it to a late-arrival table, or drop it *with a counter*. A silent drop is the default nobody
   chose deliberately.

5. **Make the write re-runnable.** Replace the partition, or merge on a deterministic business key
   derived from the input — never blind append. Then state in one sentence what a second run of the
   same input does. If the answer is "duplicates", the pipeline is not finished. Deriving the output
   key from wall-clock time or a random id makes a rerun a new row every time.

6. **Bound the unit of work** to one partition, date or batch, so a failure retries a slice instead
   of the history. Persist the cursor or high-water mark where it survives the process dying;
   in-memory progress is no progress.

7. **Reproduce a reported problem on one bounded slice**, not by rerunning the pipeline. Compare
   that slice to the source on row count, distinct key count and the sums of additive measures,
   then walk the transforms until the step where they diverge. A rerun that appends can hide the
   original loss behind fresh duplicates and destroys the evidence.

8. **Keep the transform separable from its I/O** so it can be exercised on a fixture with known
   input and known expected output. A transform that only runs under the scheduler cannot be
   tested, only observed in production. If the work arrived as a notebook, restructure it to run
   top to bottom in a fresh kernel — out-of-order state is the standing hazard, and a notebook that
   works only in the current session is not a job.

9. **Plan a backfill as its own change.** Which windows, in what order, what the write does to
   partitions that already hold rows, and what a consumer reads while it is half-done. Reconcile
   each window against the source as you go rather than at the end. Write to a separate target and
   swap where the destination supports it. Overwriting historic partitions in a table people are
   reading is destructive and outward-facing: present the window list, the overwrite semantics and
   the reconciliation plan, and ask before running it.

10. **Leave one standing assertion behind** — the freshness or volume check that fails when this
    stops working. Where it belongs and how it is written is `data-quality`; that it exists is
    this procedure's responsibility.

11. **Report with the words kept apart** — written, executed on a slice, backfilled, reconciled,
    deployed. This procedure exists partly because they get conflated, and "the job ran" is the
    weakest of them.

## Checklist

- [ ] Lineage traced to every reader, with the unenumerated ones named
- [ ] Grain, partition key, expected volume and freshness written down
- [ ] Event time chosen as the partition clock; timezone and boundary stated
- [ ] Allowed lateness set, and late data given a destination other than silence
- [ ] Second-run behaviour stated in one sentence, and it is not "duplicates"
- [ ] Work bounded per partition, with a durable cursor
- [ ] Problem reproduced on a slice and compared against the source
- [ ] Transform runnable on a fixture outside the scheduler
- [ ] Backfill windows reconciled individually; destructive overwrite left for the user to approve
- [ ] One standing assertion in place
- [ ] Windows still unreconciled named, not rounded away

## Failure handling

- **Counts disagree with the source** — that is the result. Report the window and the comparison
  query. Do not rerun over the top to make the numbers agree; that converts a known loss into an
  unknown mixture of loss and duplication.
- **A run half-completed** — resume from the cursor. With no cursor you cannot distinguish done
  windows from undone ones without a full comparison; say that rather than rerunning blind.
- **Late data keeps arriving after the window closes** — the lateness bound is wrong, not the data.
  Measure the actual arrival lag distribution before moving the bound.
- **The slice reconciles but the full run does not** — something is scale- or ordering-dependent.
  Do not extrapolate the slice's pass; report it as covering the slice only.
- **The source itself is unreadable or has changed shape** — stop. A pipeline reconciled against a
  source you cannot read is reconciled against nothing.

## Evidence to report

The lineage, including readers you could not enumerate. The contract as you found it and as you
left it. Per window touched: source count, output count, the additive sums compared, and the
reconciliation query verbatim. What a second run does. The backfill windows completed, and those
still outstanding. The assertion left behind, and what it fires on. Then the explicit list of
windows and consumers **not** checked.
