---
name: visual-verification
description: Prove a UI looks right across every state and viewport it has to survive — enumerate the state matrix, make captures deterministic, compare against a baseline captured the same way, and triage every diff. Use before calling a visual change, a style refactor or a redesign done, when running or trusting a screenshot-comparison suite, and when asked whether a screen still looks correct. Not for judging whether a design is good, not for proving controls actually work, and never on its own sufficient to call a page verified.
---

# Visual verification

A screenshot is evidence that pixels were produced. It is not evidence that they were produced by
your change, that they are correct, or that anything behind them works. This procedure turns
screenshots into an argument that survives being questioned.

## When this fires

Before reporting a change to appearance as done — CSS, layout, theming, spacing, a component's
visual states, a design-system swap. Also when a visual regression suite reports a diff, or
reports none and someone is about to treat that as proof. It does not fire for changes with no
visual surface, and it does not fire when the question is whether the design is any good.

## Procedure

1. **Derive the surface from the change, not from the app.** List the components and routes the
   change can reach. A shared token or a base component reaches far more than the page you edited
   — grep the usages before deciding the surface is one screen.
2. **Write the matrix down before capturing anything.** States × viewports × themes:
   - states — default, empty, loading, error, long content, truncated content, disabled, focused,
     hovered, selected, and whatever this component's own states are
   - viewports — at minimum a desktop width, the narrowest supported mobile width, and any width
     where a breakpoint actually changes the layout
   - themes — light and dark if both ship; RTL and forced-colors if they are supported

   Capturing what is convenient and calling it coverage is the failure this step prevents. Cells
   you decide not to capture stay on the list, marked unchecked.
3. **Make the page deterministic before the first capture.** Every source of natural variation is
   a future false diff: wait for fonts to finish loading and for the network to settle; disable
   animations and transitions; freeze clocks and relative timestamps; seed or fix the data;
   neutralize randomized content such as avatars and placeholder images. Mask genuinely volatile
   regions rather than accepting a permanently noisy diff.
4. **Establish the baseline explicitly.** Either capture the before state yourself in the same
   session under the same conditions, or use committed baselines, or state that no baseline
   exists. A comparison against a baseline captured on another machine, browser, device pixel
   ratio or font set is comparing two unknowns.
5. **Capture each cell with a label that identifies it** — component, state, viewport, theme. An
   unlabeled folder of screenshots cannot be reasoned about later. Prefer an element-scoped
   capture for a component and a viewport-clipped one for a layout; full-page captures stitch and
   scroll, which can trigger lazy loading and scroll-linked effects that change what you see.
6. **Triage every diff into exactly one of three** — a real regression, an intended change, or a
   flake. Intended changes get their baseline updated deliberately and one at a time. Flakes get
   step 3 fixed. **Never widen a diff threshold to make a comparison pass**: that is how a suite
   stops finding anything while still reporting green.
7. **Read the captures yourself, not only the diff.** A diff finds change against a baseline. It
   cannot find something that was wrong in the baseline too — clipped text, an overflowing
   container, an unreadable contrast, a control pushed off screen. Look at each capture as a user
   would.
8. **Cover what pixels cannot** by handing off, not by inferring. Whether controls function is
   rendered/behavioural verification; whether focus order, keyboard reach and announced names are
   right is accessibility work; whether it matches the design is fidelity work. Name which of
   these you did not do.
9. **Stop before anything outward-facing.** Updating committed baselines, approving a run in a
   shared review service, or pushing captures anywhere others consume them changes what future
   runs compare against. Present what you would change and ask.

## What a screenshot cannot prove

- That a control does anything — a dead button is pixel-identical to a live one.
- That the build is current. A stale bundle produces a clean diff and a confident false pass.
- That text is text. An image of a heading and a heading look the same and read differently.
- That nothing is clipped outside the capture, or that overflow does not scroll horizontally.
- Focus order, keyboard reachability, accessible names, or anything a screen reader gets.
- That colors are right for a user in forced-colors, high-contrast, or a different color profile.
- Any state reached only by interaction, unless you drove the interaction and captured it.

## Checklist

- [ ] Surface derived from the change's real usages, not assumed
- [ ] State × viewport × theme matrix written before capturing
- [ ] Fonts, network, animation, clock and data pinned before the first capture
- [ ] Baseline named: captured here, committed, or absent
- [ ] Every cell captured under identical conditions and labeled
- [ ] Each diff triaged as regression, intended, or flake — no threshold widened
- [ ] Captures read directly, not only compared
- [ ] Uncaptured cells and uncovered axes listed by name
- [ ] No baseline updated or run approved without asking

## Failure handling

- **A diff that will not stabilize** — it is non-determinism, not a tolerance problem. Find the
  moving part (a font swapping in late, an animation frame, a timestamp, an unseeded list) and pin
  it. If it cannot be pinned, mask that region and say it is masked.
- **Diffs everywhere after an unrelated change** — suspect the harness before the code: a changed
  browser version, device pixel ratio, platform or font stack shifts anti-aliasing globally. Do
  not accept a wholesale baseline update as a fix for this without saying that is what happened.
- **No baseline exists** — you can describe what the current state looks like. You cannot claim
  anything is unchanged, and saying "looks the same as before" from memory is not a comparison.
- **A capture looks correct but the change is not visible in it** — assume a stale build before
  assuming success, and re-render from a fresh build.
- **Capture tooling is unavailable** — say visual verification could not be performed, name what
  you checked instead, and do not call the appearance verified.

## What this refuses to conclude

Without labeled captures of the named cells, this procedure does not conclude that a UI looks
right — it reports which cells were checked and which were not. Without a baseline captured under
the same conditions, it does not conclude "unchanged". Without a fresh build, it does not conclude
anything at all. And a complete, clean visual pass never, on its own, means the page works: that
claim needs the behavioural check, run separately.

## Evidence to report

The matrix as planned and the cells actually captured; the determinism measures applied and
anything masked; where the baseline came from; each diff with its triage verdict and reasoning;
the captures themselves for anything a sentence cannot carry; every cell and axis left unchecked,
named; and which behavioural, accessibility or design-fidelity checks were not part of this.
