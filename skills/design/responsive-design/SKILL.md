---
name: responsive-design
description: Make a layout hold from 320px to wide desktop — content-driven breakpoints, intrinsic layout before media queries, fluid type that still zooms, touch targets, reflow without hiding content, and what to check at each width. Fires when building or fixing layout, when something overflows or collapses at a size, or when a design only exists at one width. Not for proving it renders (browser-verification) and not for semantics or screen readers (accessibility).
---

# Responsive design

Most responsive bugs are a layout that was designed at one width and then defended with media
queries. Layouts that adapt on their own need fewer breakpoints and break in fewer places.

## When this fires

Building or repairing any layout that will be seen at more than one width, and whenever a design
hand-off shows a single desktop frame. It does not fire for the proving pass — screenshots, console
and interaction checks belong to `browser-verification`.

## Procedure

1. **Let the content choose the breakpoints.** Widen and narrow until the layout actually breaks —
   a line gets too long, a card squashes, a nav wraps badly — and put a breakpoint there. Device
   names are marketing; the content is the constraint.
2. **Start from the small layout and add.** Write the base styles for the narrow case, then use
   `min-width` queries to add complexity. Going the other way means every small screen pays to undo
   desktop rules, and undoing is where the leaks are.
3. **Reach for intrinsic layout before a media query.** `flex-wrap`, `grid-template-columns:
   repeat(auto-fit, minmax(…, 1fr))`, `min()`/`max()`/`clamp()`, and container queries where the
   component's size — not the viewport's — is what should drive it. A component that adapts to its
   own container survives being moved; a viewport-keyed one does not.
4. **Make type fluid without breaking zoom.** A `clamp()` with a `rem` term in the middle scales with
   the viewport *and* still responds to the user's font size and browser zoom. A size expressed in
   `vw` alone does not — it ignores zoom entirely, which is a genuine accessibility failure, not a
   stylistic choice. Keep an explicit floor and ceiling; line length around 45–75 characters.
5. **Keep spacing on one scale.** Fluid gutters and section padding from the same tokens as the type
   scale. Ad-hoc pixel values per breakpoint are how layouts drift apart over time.
6. **Size targets for fingers, not cursors.** 24×24 CSS px is the floor for any interactive target,
   with clear spacing between adjacent ones; make primary and frequently-tapped actions comfortably
   larger. Check the real hit area, not the icon — padding counts, a bare glyph does not.
7. **Reflow, never remove.** At narrow widths, content stacks, wraps, collapses into a disclosure or
   moves into a menu. It does not disappear. Anything only reachable on desktop is a feature that
   does not exist on mobile — if a design asks for that, stop and ask, because it changes what the
   product does rather than how it looks.
8. **Handle media explicitly.** Responsive images with `srcset`/`sizes` so small screens do not
   download desktop assets; an `aspect-ratio` or explicit dimensions so nothing jumps as images load;
   `object-fit` so crops behave. Long tables, code blocks and diagrams are the legitimate exception —
   give them their own horizontal scroll container rather than shrinking the page around them.
9. **Distrust viewport units on mobile.** `100vh` is taller than the visible area while browser
   chrome is showing; prefer the dynamic/small viewport units with a plain fallback underneath.
   Where a layout goes edge to edge on a notched device, pad with the safe-area environment
   variables and set the viewport meta to cover — and never disable user scaling.
10. **Do not tie behaviour to width.** Wide does not mean mouse and narrow does not mean touch. Gate
    hover-only affordances on `@media (hover: hover)` and make sure anything revealed on hover has a
    tap or focus path too.
11. **Check at sizes, not at one size.** Walk 320, 375, 768, 1024 and 1440 CSS px, plus 1280 at 400%
    zoom — which is the same reflow constraint as 320 and catches the zoom bugs that resizing misses.
    **Reload after each change**, do not just drag the window: layout-time breakpoints, container
    query registration and device gates only re-run on load.
12. **At every size, look for the same six things.** Horizontal page scroll; clipped or overlapping
    content; text squeezed under ~40 characters or stretched past ~80; targets and their spacing;
    images loading at the right size with no jump; and whether the reading order still matches the
    visual order after items reflow.

## Checklist

- [ ] Breakpoints correspond to where content broke, not to device names
- [ ] Base styles are the narrow case; complexity added with `min-width`
- [ ] Intrinsic layout used where it removes a media query
- [ ] Fluid type keeps a `rem` term, a floor and a ceiling; zoom still works
- [ ] Every interactive target is at least 24×24 CSS px with real spacing
- [ ] No content removed at small sizes — reflowed, collapsed or moved instead
- [ ] No horizontal page scroll at 320px; exceptions scoped to their own container
- [ ] Images sized responsively and reserve their space before loading
- [ ] `100vh` assumptions and safe areas handled; scaling not disabled
- [ ] Hover-only affordances have a tap and focus equivalent
- [ ] Each width was **reloaded**, not just resized
- [ ] 1280 at 400% zoom checked alongside 320px

## Failure handling

- **Something overflows and the culprit is not obvious** — find the element wider than its container
  before changing anything. Long unbroken strings, fixed pixel widths, negative margins and `100vw`
  inside a padded parent cause most of it. Do not apply `overflow: hidden` to the page: it hides the
  symptom and clips content for everyone.
- **The design only exists at one width** — say which breakpoints you inferred and why, and get them
  confirmed. Inventing the mobile layout silently and calling it done is how two people ship two
  different products.
- **A fix at one width breaks another** — re-walk the whole set of widths after every fix, not just
  the one you were working on. This is the most common regression in this area.
- **A third-party or embedded component will not reflow** — contain it and its scroll, record it as a
  known limit, and do not claim the page reflows cleanly.
- **You cannot open a browser** — report the layout as changed but unchecked. Reading CSS is not
  checking layout, and resizing without reloading is not checking breakpoints.

## Evidence to report

The widths walked and whether each was reloaded; a screenshot per width where the layout meaningfully
differs; what overflowed or clipped and what fixed it; the breakpoints added or moved, with the
content reason for each; the zoom result at 400%; and the sizes, states or components **not** checked.
"Made it responsive" without the width list is not evidence — hand the rendered proof to
`browser-verification`.
