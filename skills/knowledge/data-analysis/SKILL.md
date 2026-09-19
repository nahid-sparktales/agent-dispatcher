---
name: data-analysis
description: Get a defensible answer out of a dataset — grain and denominators pinned, missing data accounted for, aggregates checked against their segments, and every number reproducible from raw input by a script. Use when asked what a dataset shows, when a number needs explaining or two numbers disagree, or before any finding from data is reported to someone who will act on it. Not for defining product metrics or instrumentation, not for building the pipeline that produced the data, and not for designing an experiment.
---

# Data analysis

Wrong analyses rarely come from wrong arithmetic. They come from a denominator drawn from a
different population, rows that silently disappeared, an aggregate whose segments all point the
other way, or a correlation written up with a causal verb.

## When this fires

A dataset has to answer a question, a reported number needs explaining or reconciling, or a finding
from data is about to be shown to someone who will decide something. It does not fire when the
task is only to render an agreed number as a chart.

## What a result is allowed to claim

Pick the weakest rung that the evidence supports and write the sentence at that rung:

- **Described** — this is what the data contains, for this population and window.
- **Associated** — these move together; the confounders are named and unresolved.
- **Predictive** — this pattern held out of sample, on data the fitting never saw.
- **Causal** — an experiment or a design with an identified counterfactual supports it.

Most exploratory work stops at the first two. Writing a rung you did not earn is the failure this
procedure exists to prevent.

## Procedure

1. **Write the question and the decision it serves** before loading anything, plus the result that
   would be surprising. Analysis with no decision behind it expands without limit.
2. **Establish provenance and grain.** Where the data came from, what exactly one row represents,
   the time window it covers, and what was already filtered out before it reached you. A table of
   currently-active accounts cannot answer a question about churn — that filter is survivorship,
   and it is invisible once the rows are gone.
3. **Count before you conclude.** Row count, distinct count on the claimed key, minimum and maximum
   date, nulls per column, duplicates at the stated grain. Report these numbers. They catch more
   bad analyses than any modelling step, and a key that is not unique changes every join downstream.
4. **Pin every denominator.** Numerator and denominator drawn from the same population and the same
   window, at the same unit of aggregation. A per-event numerator over a per-user denominator is
   silent and common. Write the rate out in words before computing it.
5. **Account for missing data rather than dropping it.** Distinguish an absent row from a null,
   from a real zero, from a placeholder (`0`, `-1`, `1970-01-01`, `N/A`, `unknown`). Then ask
   whether the missingness is related to what you are measuring — if it is, removing those rows
   moves the answer. Every exclusion goes in a written list with its row count.
6. **Look at the distribution before quoting a summary.** Mean against median, the tails, whether
   it is bimodal. Quote a spread or an interval alongside any average; an average with no shape
   behind it hides the thing worth reporting.
7. **Segment before believing an aggregate.** Split by the obvious dimensions and check whether the
   overall direction survives. A total that moves because the population mix changed is a
   composition effect, not the effect you were asked about, and it reverses within segments often
   enough to be assumed until checked.
8. **Compare against normal variation.** Establish what week-to-week or group-to-group movement
   looks like when nothing happened. A change inside that band is not a finding, however much it is
   wanted. If you sliced the data many ways before something stood out, say how many.
9. **Name the confounders and stay at the right rung.** List what else differs between the groups
   being compared and could produce the pattern. Say what would be needed to move up a rung —
   usually a randomized test or a design with a credible counterfactual — and route that to
   experiment design rather than improvising one.
10. **Make it reproducible from raw input.** Every reported number comes from a script or query
    that runs top to bottom from the original source in one pass, with seeds fixed and version
    pinned where randomness or library behaviour matters. No figure hand-copied out of an
    interactive session. Re-run it clean before reporting: if a number moves, it was never a result.
11. **Reconcile the headline figure against something independent** — a different source, a
    manual count for one day, a known total. Quote both numbers and the gap.
12. **Stop and ask before anything with consequences**: running writes against a production
    database, exporting or joining data containing personal information, combining datasets in a
    way that could re-identify people, deleting or overwriting source data, or publishing a number
    others will act on. Propose it, name what it touches, and wait.

## Checklist

- [ ] Question and the decision behind it written down
- [ ] Source, grain, window and pre-existing filters stated
- [ ] Row counts, key uniqueness, date range, nulls and duplicates reported
- [ ] Every rate has its denominator, population, window and unit named
- [ ] Missing and placeholder values classified; exclusions listed with counts
- [ ] Distribution inspected; a spread reported with every average
- [ ] Aggregates checked against their segments for composition effects
- [ ] The move compared against normal variation, and slicing count disclosed
- [ ] Confounders named and the claim written at the rung the evidence supports
- [ ] The whole thing re-run clean from raw input and the numbers matched
- [ ] Headline figure reconciled against an independent source
- [ ] Production writes, personal data and publication proposed rather than done

## Failure handling

- **The data cannot answer the question** — say which part is unanswerable and what would be needed.
  A confident answer from insufficient data is the most expensive output here.
- **Two sources disagree** — do not average them or pick the convenient one. Take one narrow slice
  and trace it through both until the divergence has a named cause: a filter, a timezone, a
  deduplication rule, a different grain.
- **The re-run produces different numbers** — the earlier numbers are void, not "close enough".
  Find the source of the difference before reporting anything from either run.
- **The key is not unique** — stop and fix the grain. Every join and count after that point is
  wrong in a way that looks plausible.
- **An outlier drives the result** — report both figures, with and without it, and say what the
  outlier actually is. Never remove it silently.
- **The result is null or boring** — report it. A clean null result is a finding; searching for a
  slice that produces a headline is how noise gets published.
- **Personal or sensitive fields appear in the data** — stop, name the fields, and raise it before
  querying further or exporting anything.

## Evidence to report

The question and the decision. Source, grain, window and every filter applied, including those
applied before you received the data. The profiling counts. Each rate written out in full. The
exclusion list with row counts. Distributions and spreads, not only point estimates. The segment
check. The path to the script that reproduces every number end to end, and the fact that it was
re-run. The reconciliation, both figures and the gap. The confounders. And the claim stated at its
rung — with the questions you could not answer named rather than approximated.
