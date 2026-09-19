---
name: design-to-code
description: Turn a design, mockup, Figma frame or screenshot into implementation that actually matches it — mapping values to the codebase's existing tokens and components, covering the states the design never drew, and listing what the design left ambiguous instead of guessing. Use when handed a design to build, when asked whether an implementation matches its source, or when a build has drifted from the design. Not for deciding what the design should be, and not by itself proof that the screen works.
---

# Design to code

A design is a set of still frames of the happy path. The implementation is every state, every
width, and every interaction. Most of the gap between them is not fidelity — it is the frames that
were never drawn.

## When this fires

A design file, mockup, screenshot or redline is the source for a UI change, or an existing
implementation is being compared against one. It does not fire when there is no design source and
the visual direction is yours to invent.

## Procedure

1. **Read the source for structure before pixels.** Find the repeating unit, the hierarchy, and
   which pieces are instances of something the design system already has versus one-offs drawn for
   this screen. Building a one-off as a component, or a component as a one-off, costs more later
   than any spacing error.
2. **Take values from the source, not from the picture.** Where the design tool exposes variables,
   tokens, styles or layer measurements, read them. Measuring a screenshot yields a scaled
   approximation, and approximations accumulate. If you only have an image, say so — that changes
   what "matches" can mean.
3. **Map every value onto what the codebase already has.** Its spacing scale, type ramp, color
   tokens, radii, and existing components. A design value a hair off an existing token is that
   token. A value genuinely outside the system is a finding: name it and ask whether the system
   or the design should move. Do not silently add a parallel scale, and do not change shared
   tokens to fit one screen without asking.
4. **Build structure and semantics first.** The right element for the job, heading order, labelled
   inputs, focus order, accessible names. A design shows how a control looks, not what it is —
   semantics and keyboard reachability are yours to supply and are not optional fidelity.
5. **Apply the visual layer from the mapped tokens**, not from raw hex and pixel values copied out
   of the design.
6. **Implement the states the design did not draw.** At minimum: hover, focus-visible, active,
   disabled; loading; error; empty; long text and overflow; and the widths between the drawn
   breakpoints. Each of these you invented rather than read is an assumption to report.
7. **Compare side by side at the design's own width.** Toggle or overlay rather than judging from
   memory, and check in this order: layout and alignment, spacing rhythm, type size / weight /
   line-height, color, radius, then shadow and border. Eyeballing from a remembered frame finds
   the large errors and none of the small ones.
8. **Write down every ambiguity as a question, and ask rather than guess** where guessing wrong is
   expensive. The recurring ones: what happens on submit or on failure; which content is real
   versus placeholder; how it behaves between the drawn breakpoints; what the empty and error
   states look like; whether anything animates; what truncates versus wraps; and whether the
   fonts, icons and images are licensed for this use.
9. **Separate what matched from what did not.** Matched to the source, approximated within a
   stated tolerance, substituted with an existing component or token, and unspecified-so-invented
   are four different claims. Report them as four.

## Checklist

- [ ] Structure and component reuse decided before any styling
- [ ] Values read from tokens or layer data, or the image-only limitation stated
- [ ] Every value mapped to an existing token, or the mismatch raised
- [ ] Semantics, labels and focus order supplied, not inherited from the design
- [ ] Interactive, loading, error, empty and overflow states implemented or listed as missing
- [ ] Compared side by side at the source's width, not from memory
- [ ] Ambiguities listed as questions; the expensive ones asked before building on them
- [ ] Matched / approximated / substituted / invented reported separately

## Failure handling

- **The design contradicts the design system** — do not resolve it silently in either direction.
  Implement the system's version, and report the conflict with both values.
- **The design is physically impossible with real data** — text that cannot fit, a column count
  that cannot survive a long name. Implement what degrades honestly and report it as a design
  finding, not as an implementation compromise.
- **Only a screenshot is available** — state that measurements are derived from an image, keep to
  the codebase's scale rather than inventing precise-sounding values, and mark the whole comparison
  as approximate.
- **Assets or fonts need exporting or downloading** — that is a separate action with licence
  implications. Ask before pulling them in; never write back into a design file unless the user
  asked for that specifically.
- **It matches the design** — that is a fidelity result and nothing more. It is not evidence that
  the screen renders in a real browser, that controls work, or that the console is clean. Hand
  that to browser verification and do not merge the two claims.

## Evidence to report

The source referenced (file, frame, or image) and how values were obtained; the mapping from
design values to codebase tokens and components, including every mismatch; a side-by-side or
overlay comparison at the stated width; the list of states implemented and the list inferred; the
open questions; and a plain statement of what remains unverified in a running browser.
