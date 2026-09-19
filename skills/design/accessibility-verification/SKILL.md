---
name: accessibility-verification
description: Prove an accessibility claim instead of asserting it — automated scan plus the keyboard, focus, zoom and screen-reader passes a scanner structurally cannot make. Fires before anyone says a screen is accessible or WCAG AA, when signing off UI work, or when an audit result needs checking. Not for making the fixes (accessibility), and it never upgrades a clean scan into a conformance claim.
---

# Accessibility verification

A clean automated scan proves that a set of machine-checkable rules found nothing. It says nothing
about whether a name is meaningful, an order is logical, an announcement is useful, or a flow can be
completed without a mouse. Those need a person driving the interface.

## When this fires

Before any claim that a screen, component or flow is accessible, keyboard-operable, screen-reader
usable or WCAG-conformant — your own work or someone else's, and when re-checking after fixes. It
does not fire to write the fixes; that is `accessibility`.

## Procedure

1. **Fix the scope in writing first.** Which routes, which states (empty, loading, error, logged in),
   which viewport, which browser. A claim without a named scope is not a claim — everything outside
   it stays explicitly unverified.
2. **Render the real thing.** The running app at the route that changed, not the source, not
   Storybook alone if the route composes differently. A stale build verifies nothing.
3. **Run an automated scan and record it exactly.** Use whatever the project already has — an
   axe-based checker, the browser's accessibility audit, a CI accessibility step. Record the tool and
   version, the URL, the rule ids that failed and the count. Treat the result as a floor: scanners
   find only a minority of real barriers, and they cannot judge meaning or order at all.
4. **Do the keyboard pass with the pointer unused.** Tab from the top: write down the order, and
   whether it matches the visual order. Check the skip link, every control being reachable and
   operable with Enter/Space/arrows, Escape closing overlays, no trap, focus returning after a dialog
   closes, and the focus indicator being visible *and not covered* by sticky headers or banners.
5. **Do the screen-reader pass on at least one real pairing** — VoiceOver with Safari, or NVDA with
   Firefox. Read the flow start to finish, then complete the task with the screen buffer as your only
   information. Check: does every control announce a name, a role and its state; do headings and
   landmarks describe the page; do errors and status changes get announced when they happen. See
   `references/screen-reader-passes.md` for how to drive each one.
6. **Check zoom, reflow and text spacing.** 200% browser zoom, and a 320 CSS px wide viewport: no
   horizontal scrolling, no content lost, no overlap. Then apply the text-spacing condition
   (line height 1.5×, paragraph spacing 2×, letter spacing 0.12em, word spacing 0.16em) by injecting
   CSS, and confirm nothing is clipped or overlapped.
7. **Measure contrast on the rendered pixels, in every state** — default, hover, focus, selected,
   error, and text over images or gradients. A token that passes in the palette can fail in place.
8. **Reach the non-happy states deliberately** — submit the form empty, trigger the error, load the
   empty list — and verify each announces itself rather than only changing colour.
9. **Re-run the whole pass after fixes.** A fix is verified by repeating step 3 onward, never by the
   reasoning that produced it. Regressions from accessibility fixes are common, especially in focus
   handling.
10. **Stop and ask before anything outward-facing.** Publishing an accessibility statement, filling a
    VPAT or answering a customer conformance questionnaire is a formal representation about the
    product. This procedure supplies evidence for that; it does not authorize making it.

## Checklist

- [ ] Scope written down: routes, states, viewport, browser
- [ ] The running app was exercised, not the source read
- [ ] Automated scan run; tool, version and exact failures recorded
- [ ] Full keyboard pass done with no pointer use; tab order written down
- [ ] Focus visible at every stop and not obscured by overlaying chrome
- [ ] Screen-reader pass on a named reader + browser pairing, completing the real task
- [ ] Names, roles and states confirmed as announced — not assumed from the markup
- [ ] 200% zoom and 320px reflow checked; text-spacing condition applied
- [ ] Contrast measured on rendered pixels in every interactive state
- [ ] Error and status messages heard, not just seen
- [ ] Everything out of scope or unchecked is named in the report

## Failure handling

- **No screen reader available** — report that the screen-reader checks were not performed, list what
  was. The claim then stops at "keyboard-operable and scan-clean on <scope>". Do not substitute the
  accessibility tree for a screen-reader pass: the tree shows what is exposed, not what is announced,
  in what order, or whether it makes sense.
- **The scan reports violations in third-party code** — record them separately with their source. They
  are still barriers for users; they are just not fixable in this diff.
- **A barrier will not reproduce** — say so with what you tried. Screen-reader behaviour varies by
  reader, browser and version; name the exact combination.
- **Scan is clean but the keyboard pass fails** — the keyboard result wins. Report the scan as
  uninformative here, not as a pass.
- **Time ran out mid-pass** — report what was covered and what was not. A partial pass honestly
  scoped is useful; a partial pass reported as complete is worse than none.

## What this refuses to conclude

- Zero automated violations is **not** "accessible" and **not** "WCAG 2.2 AA".
- A passing keyboard pass is **not** a passing screen-reader pass.
- One route verified is **not** the product verified.
- Code that was written following accessible patterns is **not** verified code — it is unverified
  code that will probably pass.
- Conformance is a claim about a defined scope against defined criteria. Without the scope and the
  per-criterion evidence, this procedure produces findings, not conformance.

## Evidence to report

Scope; the scan tool, version and output; the tab order as observed, with any traps or invisible
stops; the reader + browser pairing and what it actually announced at each step, quoted; the zoom,
reflow and text-spacing results; contrast ratios measured, with the states they were measured in;
screenshots where a picture carries what words cannot. Then the list of criteria, routes and states
**not** checked. "Accessibility verified" without those is an assertion, not evidence.
