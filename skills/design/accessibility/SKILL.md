---
name: accessibility
description: Build and fix interfaces so they meet WCAG 2.2 AA in practice — native semantics, keyboard paths, focus order and visibility, accessible names, contrast, form errors, live regions, target size. Fires while writing or reviewing UI code, when a component is keyboard- or screen-reader-hostile, or when an audit finding has to be turned into a change. Not for proving the result (accessibility-verification), not for viewport layout work (responsive-design), and not a recital of the standard.
---

# Accessibility in practice

Most barriers are created by replacing something the platform already made accessible. The cheapest
accessible component is the one you did not rebuild.

## When this fires

While building or changing any interactive UI, and when turning an audit finding into a fix. It does
not fire to *prove* a screen is accessible — that is `accessibility-verification`, and it needs a
keyboard and a screen reader, not a code read.

## Procedure

1. **Use the native element first.** `button`, `a[href]`, `input`, `label`, `select`, `details`,
   `dialog`, `table`. Each arrives with a role, keyboard behaviour, focus handling and state
   reporting you would otherwise have to write and maintain. A `div` with a click handler has none
   of it. If the project already has an accessible component for this, reuse that instead.
2. **Get the structure right before the styling.** One `h1` per view, headings in descending order
   with none skipped, real landmarks (`header`, `nav`, `main`, `footer`), lists marked up as lists,
   a unique page title per route. Screen reader users navigate by these; they are the table of
   contents, not decoration.
3. **Give every control a name that matches its visible label.** Visible text is the name where
   possible; `label[for]` for inputs; an `aria-label` only for controls with no visible text, such
   as an icon button. When there is visible text, the accessible name must contain it — a button
   reading "Save" named "Submit form" breaks voice control.
4. **Walk the keyboard path yourself.** Tab reaches everything interactive, in DOM order; Enter and
   Space operate it; Escape closes what opened; focus never gets stuck. Do not use positive
   `tabindex` — fix the DOM order instead. Composite widgets (menus, tabs, grids) take one Tab stop
   and move internally with arrow keys.
5. **Keep focus visible and unobscured.** Never delete an outline without shipping a replacement.
   Style `:focus-visible` so it survives sticky headers, overflow clipping and dark backgrounds, and
   check that a sticky bar or cookie banner does not cover the focused element.
6. **Move focus deliberately when the view changes.** Opening a dialog moves focus into it and traps
   it there; closing returns focus to the element that opened it; a client-side route change moves
   focus to the new heading or main region. Focus left behind on a removed node goes to `body`, and
   the user loses their place silently.
7. **Choose colours that carry the contrast.** 4.5:1 for body text, 3:1 for large text and for the
   boundaries of controls, focus rings and meaningful graphics. Check hover, active, selected and
   error states too, and text sitting over images or gradients. Never let colour alone carry meaning
   — pair it with text, an icon or a pattern.
8. **Make forms explain themselves programmatically.** Associate the error with its field
   (`aria-describedby`), mark the field invalid (`aria-invalid`), and write error text that says what
   is wrong and how to fix it. Use `autocomplete` tokens on personal-data fields. Do not make people
   re-enter information they already gave you in the same flow, and do not block paste in password or
   one-time-code fields.
9. **Announce what changes without a page load.** A status message needs a live region that already
   exists in the DOM before it updates — `aria-live="polite"` for status, `role="alert"` for errors.
   Announce once, keep it short, and do not wire a live region to something that updates constantly.
10. **Respect the user's settings.** Honour `prefers-reduced-motion` by removing movement, not by
    speeding it up. Respect `prefers-color-scheme` and `prefers-reduced-transparency` where the
    design uses them. Never disable zoom in the viewport meta tag.
11. **Cover the WCAG 2.2 additions that bite hardest.** Any drag interaction needs a single-pointer
    alternative (click or button). Interactive targets are at least 24×24 CSS px unless spaced or
    inline in a sentence. Help links stay in the same relative place across pages.
12. **Add ARIA last, and as little as possible.** No ARIA beats wrong ARIA: an incorrect role
    silently overrides the real one. Never put `aria-hidden` on anything focusable, and never invent
    role/state combinations — copy an established pattern and keep its keyboard contract intact.
13. **Stop and ask before changing shared surfaces.** A contrast fix that alters a brand token, or a
    markup change inside a shared design-system component, affects screens you are not looking at.
    Propose the change with the reason; do not push it through on your own authority.

## Checklist

- [ ] Every interactive element is a native control or reuses an existing accessible component
- [ ] Heading order and landmarks make sense read alone, with no skipped levels
- [ ] Every control has a name, and it contains the visible label text
- [ ] Tab reaches everything, in a sensible order, with no trap and no positive `tabindex`
- [ ] Focus is always visible and never covered by sticky or overlaying chrome
- [ ] Dialog and route changes move focus, and closing returns it
- [ ] Text and control boundaries meet contrast in every state, including over imagery
- [ ] Errors are associated with their fields and readable without colour
- [ ] Dynamic messages land in a live region that existed beforehand
- [ ] Reduced motion honoured; zoom not disabled
- [ ] Drag interactions have a click alternative; targets are 24×24 CSS px or spaced
- [ ] ARIA added only where a native element could not do the job

## Failure handling

- **The component is a third-party widget you cannot change** — say so, record the specific barrier,
  and look for a documented accessible mode or a replacement. Do not paper over it with ARIA that
  describes behaviour the widget does not have.
- **The fix needs a design decision** (a token fails contrast, a layout has no room for a 24px
  target) — name the conflict and the options, and let the design owner choose. Do not quietly ship a
  visual change to satisfy a checker.
- **A pattern has no obvious accessible form** — look up the established pattern for it rather than
  inventing roles. If the project pins a component library, check that library's current
  accessibility API before assuming what it supports.
- **A checker passes but the interaction still feels wrong** — trust the interaction. Automated rules
  cannot see whether a name is meaningful or an order is logical.

## Evidence to report

Name the elements changed and why: which control became a `button`, which name was added, where focus
now moves, which token changed and its measured ratio before and after. State plainly that these are
*implementation* changes — they are unverified until someone drives the keyboard and a screen reader.
Hand the claim to `accessibility-verification`; do not call it conformant here.
