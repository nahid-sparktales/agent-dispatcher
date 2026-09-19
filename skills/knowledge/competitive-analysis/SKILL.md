---
name: competitive-analysis
description: Compare products, libraries or approaches on criteria derived from your own constraints rather than from anyone's feature list, and fill each cell with evidence you obtained — hands-on trial, primary docs, source, issue tracker — marking clearly what is only a vendor claim. Use when choosing between real alternatives, when asked how something stacks up against the competition, or when a decision is being made from a marketing comparison table. Not for general investigation method, not for judging a single source, and not for writing positioning or marketing copy.
---

# Competitive analysis

Whoever sets the criteria wins the comparison. If the criteria come from a vendor's feature matrix,
the analysis was decided before it started — and every row on that matrix was chosen because they
win it.

## When this fires

A choice between real alternatives has to be defended: a library, a service, a vendor, two designs,
build versus buy. It also fires when someone arrives with a comparison table and a conclusion. It
does not fire for a reversible choice nobody will revisit — make it and move on.

## Procedure

1. **State the decision and who makes it.** What gets adopted, by whom, and what changes the day
   after. A comparison with no decision behind it becomes a feature table nobody reads.
2. **Derive the criteria from your own constraints, before opening any product page** — your actual
   workload, scale, team skills, runtime, compliance and budget. Then weight them: must-have,
   tie-breaker, irrelevant. Criteria written after reading the vendors are the vendors' criteria.
3. **Pick the comparison set honestly.** Include the status quo, "do nothing", and "build the small
   version" as candidates. Omitting the incumbent or stacking the field with obvious losers is how
   a predetermined answer gets dressed as analysis.
4. **Decide, per criterion, what evidence would settle it** and what it costs to get: a hands-on
   trial, the primary documentation, reading the source, the issue tracker, the licence, a
   benchmark you can reproduce. Match evidence to criterion before gathering anything.
5. **Use the thing where the criterion is about behaviour.** Build the smallest real task on each
   candidate — the same task on all of them. Ten minutes in a sandbox outranks any amount of
   documentation about ergonomics, error messages and defaults. Anything that requires creating an
   account, accepting terms, entering payment details, or spending money **stops and asks the user**.
6. **Read the primary artifacts, not the landing page.** Documentation, changelog and release
   cadence, open-issue ages and how maintainers answer, the licence text, the source where it is
   open. A marketing page is a claim; treat it with `source-evaluation`.
7. **Check what no comparison page lists**: total cost at *your* projected scale including seats,
   overage and egress; migration cost in and out; data export and lock-in; maintenance health (last
   release, contributor count, bus factor); support terms; security and compliance posture.
   Decisions get reversed by these, not by the feature checkboxes.
8. **Mark every cell with its provenance.** Verified-by-us, documented, vendor-claimed, or untested
   — with the date and the version tried. An untested cell that looks the same as a tested one is
   the single most common way this artifact misleads.
9. **Test each candidate at the version you would actually adopt**, and run the same task on each.
   A comparison across versions, configurations or effort levels measures your effort, not them.
10. **Apply the same scepticism to the home team.** When your own product is in the table, its
    claims need the same evidence, and its weaknesses belong in the same column.
11. **Break near-ties on reversibility and cost of exit**, not on feature count. When the paper
    result is close, the cheaper mistake to undo is the right choice.
12. **Write the recommendation with its flip condition** — what would have to be true to change it —
    plus what you are trading away, and the explicit list of criteria you could not test.
13. **Publishing is a separate, outward-facing act.** A comparison naming competitors that goes into
    a blog post, sales deck or public doc stops and asks first; every claim about a named third
    party must carry its source, version and date.

## Checklist

- [ ] Decision, decider and consequence written down
- [ ] Criteria derived from own constraints before reading any vendor material, and weighted
- [ ] Status quo and build-it-yourself included as candidates
- [ ] Evidence type chosen per criterion before gathering
- [ ] Same real task attempted hands-on on each candidate, at the version under consideration
- [ ] Cost at projected scale, exit cost and maintenance health all assessed
- [ ] Every cell marked verified / documented / vendor-claimed / untested, with date
- [ ] Own product held to the same standard when it is in the table
- [ ] Recommendation states its flip condition and what it trades away
- [ ] Untested criteria listed rather than left looking tested

## Failure handling

- **Trial is gated behind sales, signup or payment** — stop and ask the user; do not create the
  account. If access never comes, mark those criteria untested and say the comparison is incomplete
  on them rather than filling them from the documentation.
- **The only benchmark is the vendor's own** — report it as vendor-claimed with its configuration,
  and say what an independent run would need. Never restate it as a measured result.
- **Candidates are at different maturities** — say so plainly. Comparing a mature product with a
  young one on feature count, without noting the difference, is a false result either way.
- **The incumbent is winning only on sunk cost** — separate switching cost from fit and price them
  both. Sunk cost is a real number in the decision, but it belongs on its own line.
- **Everything ties** — the criteria were not discriminating. Return to step 2 with the constraints
  that actually hurt, rather than adding more rows.
- **Nobody can be tested in the time available** — deliver the criteria and the evidence plan, say
  the comparison was not performed, and do not let a documentation-only read be reported as a trial.

## Evidence to report

The weighted criteria and where each came from; the candidate set including the status quo; the
same task you ran on each, with versions, dates and what actually happened; the comparison table
with every cell's provenance marked; cost at scale and cost of exit; the recommendation with its
flip condition and its tradeoff; and the list of criteria left untested. A table without provenance
per cell is marketing, whichever side wrote it.
