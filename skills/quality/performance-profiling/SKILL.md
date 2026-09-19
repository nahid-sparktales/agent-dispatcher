---
name: performance-profiling
description: Find where the time actually goes before changing anything — define the metric and workload, build a repeatable baseline with its spread, profile on the right axis, confirm the suspected hotspot by removing its work, then re-measure under identical conditions. Use when something is slow, when an optimization is about to be written from a hunch, or when a speedup is being claimed without comparable numbers. Not for reading code to guess what is expensive, not for micro-tuning with no measured user impact, and not a licence to profile production without asking.
---

# Performance profiling

The function that looks expensive and the function that is expensive are two different populations
with a modest overlap. Every optimization written before a profile is a guess with a diff attached.

## When this fires

- Something is measurably slow, or a latency, memory or throughput target is being missed.
- An optimization is about to be written on the strength of how the code reads.
- A speedup is being reported without a baseline, a spread, or comparable conditions.

It does not fire for correctness work, and it does not fire for a change whose only justification
is that a faster construct exists — a faster loop inside 2% of the runtime is not an improvement,
it is churn.

## Procedure

1. **Define the metric and the workload.** "Slow" is not a metric. Pick one: p95 latency of this
   request under this load, peak resident memory, time to first byte, wall-clock of this job,
   rows per second. Say which environment, which data, and what would count as good enough.
2. **Reproduce the slowness in a harness you can run repeatedly**, with representative data.
   Toy input profiles a different program: an N+1 query is invisible at ten rows, and a quadratic
   scan is free at n=12.
3. **Establish the baseline properly.** Run it several times and record every run, not the best
   one. Report the median and the spread. If the spread is wider than the improvement you are
   chasing, the harness is not ready and nothing measured on it will be believable.
4. **Profile rather than guess, on the axis that matches the metric.** Wall-clock sampling for
   "it takes too long", a CPU profile for compute, an allocation or heap profile for memory, the
   browser's performance trace for rendering and main-thread work, the database's own query plan
   for a slow query, distributed traces for a request crossing services. Use whatever the runtime
   ships; name the tool you used in the report.
5. **Read the profile carefully before believing it.** Separate self time from inclusive time — a
   frame near the top of the list may be cheap itself and merely called by everything. Check
   whether the time is spent computing or waiting: a CPU profile of an I/O-bound program shows an
   idle program, and chasing its top frame is the single most common wrong turn here.
6. **Confirm the hotspot before optimizing it.** Delete, stub or short-circuit the suspected work
   in a scratch copy and re-measure. If the total does not move, it was not the bottleneck however
   bad the code looked. This experiment costs minutes and prevents days.
7. **Ask whether the work can be avoided before making it faster.** Fewer round trips, less data
   fetched, computed once instead of per item, the right index, the result cached at a layer where
   invalidation is tractable. The cheapest optimization is the work that no longer happens.
8. **Change one thing.** Two changes measured together give you one number and no attribution.
9. **Re-measure under identical conditions** — same machine, data, build configuration, warm or
   cold state, same number of runs. A release build against a debug baseline is not a result.
10. **Check correctness alongside speed.** Caching, concurrency, laziness and batching all change
    semantics. Run the test suite and state the new invariants someone now has to maintain:
    invalidation, ordering, memory ceiling, error handling under partial failure.
11. **Report absolutes with their spread**, name the fraction attributable to the change, and say
    what the bottleneck is now. Then remove the harness, or promote it deliberately to a
    repeatable benchmark that someone owns.

## The plausible-but-wrong hotspot

- **The nested loop over a list of twelve.** It reads badly and costs nothing.
- **The frame with the most samples that is merely popular.** Inclusive time is not self time.
- **A debug build, or profiler overhead.** Instrumentation distorts small hot functions most;
  cross-check a sampling profile against plain wall-clock timing of the whole workload.
- **The first run.** Cold caches, JIT warm-up, connection pools and lazy imports are paid once.
  Decide whether the metric is the cold path or the warm one, then measure that one consistently.
- **The micro-benchmark the compiler optimized away.** A result nobody consumes may never be
  computed; a number too good to be true usually is.
- **The environment that is not the user's.** A local SSD and a loopback network hide precisely
  the I/O and latency costs that make production slow.

## Checklist

- [ ] Metric, workload and environment written down before measuring
- [ ] Baseline taken from multiple runs, all recorded, with spread
- [ ] A profile was taken, on an axis that matches the metric
- [ ] Self time and inclusive time distinguished; compute separated from waiting
- [ ] The hotspot was confirmed by removing its work and re-measuring
- [ ] One change at a time
- [ ] After-measurement under identical conditions
- [ ] Correctness re-checked and new invariants named
- [ ] Remaining bottleneck stated

## Failure handling

- **No profiler for this runtime** — bracket timers around segments and bisect the region by
  halving, the same way you would isolate a bug. Say plainly that the attribution is coarse.
- **The difference is inside the noise** — report the change as unproven. A percentage quoted from
  two single runs is noise with a decimal point.
- **It only reproduces in production** — do not attach a profiler to production on your own
  judgement. Profiling costs overhead and can take load; stop and ask, and prefer a staging replay,
  a captured trace, or existing telemetry.
- **The bottleneck is in a dependency or in infrastructure** — report it with the evidence. Do not
  rewrite a library or resize infrastructure on a hunch.
- **The improvement requires a destructive or outward-facing step to validate** — a schema
  migration, a cache flush, a config change on a shared environment. Stop and ask; measure against
  a local or branch copy first.

## Evidence to report

The metric and workload; the harness command; machine, data and build configuration; every
baseline run, not the best one; the profile itself — top frames, query plan or trace — and how it
was taken; the confirmation experiment; the after-numbers under the same conditions with spread;
the correctness run; and the bottleneck that is now next. Measured, optimized and verified are
three different claims: "2x faster" with none of the above is a fourth one, which is a guess.
