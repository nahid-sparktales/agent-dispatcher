---
name: ui-audit
description: Review an existing interface and return ranked, concrete findings — each with its location, the user consequence, and a specific fix — instead of taste notes. Use when asked to critique, audit or review a screen or flow, when someone's UI work needs judging, or when an interface "feels off" and the problem needs naming. Not for proving a change renders and functions, not for inventing a new visual direction, and not for an accessibility conformance audit, which is its own discipline.
---

# UI audit

An audit that returns "the spacing feels cramped and the blue is a bit harsh" is worth nothing: it
cannot be prioritised, argued with, or fixed. Every finding names a place, a consequence to a
person trying to do something, and a change.

## When this fires

An interface already exists and someone wants to know what is wrong with it — your work or theirs,
a shipped screen or a prototype. It does not fire to prove a change works (`browser-verification`)
or to establish a direction where none exists (`frontend-design`).

## Procedure

1. **Get the interface in front of you, rendered.** Source is not the interface. If you can only
   see screenshots or code, say so up front and mark the audit partial — several lens passes below
   are simply not available to you, and pretending otherwise is the main way these go wrong.
2. **Establish what the screen is for** before judging it: the primary task, who does it, and how
   often. An audit without this produces preferences. If nobody can tell you, write down your
   assumption and audit against it explicitly.
3. **Walk the primary task end to end**, as the user, at realistic data volume — not the demo
   three rows. Note every point you hesitated, guessed, backtracked or re-read. Those moments are
   the findings; everything after this is structure for them.
4. **Pass in fixed lenses**, in this order, so the cheap and structural problems surface before
   cosmetics:
   - **Hierarchy** — does what matters most read first? Is anything shouting that shouldn't?
   - **Language** — do labels say what the thing does, in the user's words? Any jargon, any
     ambiguous verb, any button whose name doesn't match what happens?
   - **Affordance and feedback** — is it obvious what is clickable? Does every action acknowledge
     itself? Is destructive action distinguishable from routine action?
   - **States** — empty, loading, error, partial permission, very long content, zero results.
     Reach them if you can; list the ones you could not reach.
   - **Density and scan** — can the eye find one row among many? Is the whitespace doing work or
     just filling?
   - **Accessibility basics** — text contrast, visible focus, target size, keyboard reachability
     of every action, semantic structure and label association. Basics only: a conformance audit
     is separate work and should be named as such, not implied by this pass.
   - **Consistency** — with the rest of this product, and with platform convention. A local
     improvement that breaks a product-wide pattern is a finding against itself.
5. **Write each finding as four parts**: where it is, what a user does wrong or slowly because of
   it, the evidence (screenshot, the string, the state you reached), and one concrete fix. If you
   cannot name the user consequence, it is a preference — drop it, or put it in a clearly separate
   "taste, not defect" list the reader can ignore.
6. **Rank by user cost times frequency**, never by how easy the fix is. The cheap fix at the bottom
   of a ranked list still gets done first; a list sorted by cheapness hides the expensive problem
   that actually matters.
7. **Band the findings**: blocks the task / costs time or confidence / polish. Three bands, so the
   reader can stop after the first.
8. **Report; do not rebuild.** Changing the interface is separate work with separate authorization.
   If you were asked to fix as well as audit, fix after the findings are agreed, and keep the
   before/after evidence.

## Checklist

- [ ] The interface was rendered, or the audit is explicitly marked partial
- [ ] The primary task is stated, from the product or as a written assumption
- [ ] The task was walked end to end at realistic data volume
- [ ] Every lens was passed, or named as not passed
- [ ] Each finding has location, consequence, evidence and a fix
- [ ] Findings are ranked by user cost and frequency, and banded
- [ ] Preferences are separated from defects, not blended into them
- [ ] States and paths you could not reach are listed

## Failure handling

- **Screenshots only.** Audit hierarchy, language, density and visible contrast; say that
  interaction, keyboard, focus order and every non-visible state went unchecked. Do not infer that
  a control works because it looks like one.
- **A state you cannot reach** — say which, and what would be needed. An unreachable error state
  is itself worth reporting if real users reach it.
- **A finding that will not reproduce** — report it as intermittent with what you did. An
  intermittent problem reported as fixed is worse than one reported as intermittent.
- **The fix is not local** — it belongs to a shared component or a token. Say so, and hand it to
  `design-systems` rather than proposing a local override that forks the system.
- **You designed this screen.** Say so in the report. A self-audit is still useful, but the reader
  must know it is not an independent review.
- **Everything looks fine.** That is a legitimate result if you walked the task and passed the
  lenses. Report what you checked; do not manufacture findings to look thorough.

## Evidence to report

The route or screen and the viewports seen. The task you walked, and where you hesitated. Per
finding: the screenshot or quoted string that shows it. The lenses passed and the states reached,
plus the ones not reached. Say plainly that this is a review, not verification — an audit proves
nothing about whether the interface works, and the fixes it recommends remain untested until
someone renders and operates them.
