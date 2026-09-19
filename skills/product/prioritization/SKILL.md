---
name: prioritization
description: Choose what not to do and make the tradeoff legible — the constraint being spent, each candidate's cost and value with the evidence behind it, what is reversible, and what would change the answer. Use when a list is longer than the capacity, when asked what to cut or what ships first, or when a decision was made and nobody can reconstruct why. Not for deciding whether a problem is real (product-discovery), not for writing the scope of what wins (prd-and-stories), and not for committing the team on their behalf.
---

# Prioritization

Ranking is easy and useless. The decision that matters is what gets dropped, and the artifact that
matters is a reason someone can disagree with in three months.

## When this fires

More candidates than capacity; a request to say what ships first or what to cut; an existing
priority order nobody can justify. It does not fire for a list of two items with an obvious
dependency between them — say the order in one line and move on.

## Procedure

1. **Name the constraint you are allocating.** One release, one sprint, one person for two weeks,
   one review slot. Priority without a stated capacity is just an opinion about importance, and it
   is why ranked lists get agreed and then ignored.
2. **Make the list comparable.** Candidates at wildly different sizes cannot be ranked against
   each other. Split the boulders into the first shippable slice, and say explicitly that what is
   being compared is the slice, not the ambition behind it.
3. **Write the cost honestly, in the unit of the constraint.** Your estimate, its basis, and its
   uncertainty as a range where you have one. Include the costs that hide outside the build:
   migration, support load, the thing that now needs maintaining, the review it will consume.
4. **Write the value claim with its evidence grade.** What changes for whom, and whether that is
   **observed** (data or traced cases), **reported** (someone said so), or **assumed**. Two items
   claiming equal value where one is observed and one is assumed are not equal, and collapsing
   that difference is the most common way a bad bet wins.
5. **Check dependency and sequencing before any scoring.** What is blocked by what, what unblocks
   several others, what has an external date attached. Order that is forced is not a priority
   judgment — settle it first so the real tradeoff is what remains.
6. **Sort by reversibility, not only by size.** A cheap one-way door — a public API, a data
   migration, a pricing change, a URL scheme, anything users will build habits on — deserves more
   scrutiny than an expensive change you can undo on Friday. Say which candidates are one-way.
7. **Ask what changes if each waits one cycle.** Some costs grow (a migration through a growing
   dataset, an outage risk, a security gap), some shrink, most stay flat. Decay is what separates
   "later" from "never", and it is usually the only honest argument for doing a low-value item
   now.
8. **Make the cut, and write the line under it.** Say what is in, what is out, and what is out
   *for now* with the condition that would bring it back. A list where nothing is out has not
   prioritized anything.
9. **Record the reasoning in a few lines, without ceremony.** What the constraint was, which
   tradeoff decided it, and what evidence would flip it. Reach for a scoring framework only when
   many comparable items must be ranked by several people; for one team and a dozen items, a
   score is decoration that hides its own weights. Numbers invented to look objective are worse
   than a sentence that can be argued with.
10. **Present it as a recommendation.** The people who own the roadmap decide, and commitments to
    customers, dates, or other teams are theirs to make — offer the cut and the reasoning, and
    let them take it. Do not announce, message, or record the decision anywhere outward-facing on
    your own initiative.

## Checklist

- [ ] The capacity being allocated is stated
- [ ] Items are comparable in size, or explicitly sliced to be
- [ ] Every item has a cost with its basis, in the constraint's unit
- [ ] Every value claim carries an evidence grade
- [ ] Forced ordering (dependencies, external dates) resolved before judgment calls
- [ ] One-way doors identified as such
- [ ] Decay checked: what gets worse or cheaper by waiting
- [ ] Something is actually out, and "out for now" has a return condition
- [ ] Reasoning written in a few lines; no scoring theatre
- [ ] Delivered as a recommendation, with the decision left where it belongs

## Failure handling

- **Two items are genuinely tied.** Say so and break it on reversibility or on which one teaches
  you more. Manufacturing a tenth of a point to separate them is false precision.
- **Someone has already promised an item externally.** Then it is a constraint, not a candidate.
  Move it above the line, say it was a commitment rather than a ranking, and rank what is left.
- **The evidence is thin everywhere.** Prioritize the cheapest thing that produces evidence, and
  say that is what you are optimizing for. Do not dress up an assumption as a value score.
- **The list is all urgent.** Ask what breaks, for whom, and when, if each waits a cycle. Urgency
  that survives that question is real; the rest was volume.
- **You are being asked to rank someone else's domain.** Rank the effect on the outcome you can
  see, name the expertise you lack, and route the call. A confident ranking of work you do not
  understand is a liability.
- **The decision has already been made and you are being asked for justification.** Say what the
  reasoning would have to be for it to hold, and whether the evidence supports it. Do not
  reverse-engineer a rationale.

## Evidence to report

The constraint; the candidate list with cost, value and evidence grade per item; the forced
ordering and why; which items are one-way doors; what was cut and what was deferred with its
return condition; and the one or two facts that would change the answer. A ranked list with no
capacity, no costs and nothing below the line is a preference, not a prioritization.
