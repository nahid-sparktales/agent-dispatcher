---
name: tailwind
description: Work inside an existing Tailwind codebase without degrading it — use the project's theme tokens instead of arbitrary values, extend the theme when a token is genuinely missing, extract repetition into components rather than @apply, resolve class conflicts with the project's merge helper, and make dark mode a token decision. Fires when writing or editing Tailwind classes in a repo that already uses it. Not for deciding whether to adopt Tailwind, not for visual design direction, and not a rendered-output check.
---

# Tailwind

A Tailwind codebase degrades one arbitrary value at a time. Every value you hardcode is a design
decision the theme can no longer make.

## When this fires

Writing or editing Tailwind utility classes in a project that already uses Tailwind. It does not
fire for choosing a styling approach, for visual design direction, or for CSS in a project that
does not use Tailwind.

## Procedure

1. **Read the theme before writing a class.** Tailwind's major versions place theme configuration
   differently — a JS/TS config file in some, a CSS-side theme block in others — so find where
   *this* project defines its tokens (and confirm the version from the lockfile; see
   `stack-detection`). Read the colors, spacing, radius, font and breakpoint tokens that exist.
2. **Read one or two existing components** in the same area. The class vocabulary a team actually
   uses is a stronger constraint than what Tailwind permits.
3. **Reach for a token before a value.** Semantic color tokens over raw palette steps, scale
   spacing over pixel values. If you are about to type a bracketed arbitrary value, first check
   whether a token covers it.
4. **When no token covers it, add the token — do not sprinkle the value.** Ask whether this is a
   one-off (one arbitrary value, with a comment saying why) or a design decision (belongs in the
   theme). Adding a theme token changes the whole app's vocabulary, so say what you are adding and
   why in the report.
5. **Do not extract on the second repetition.** Two similar class lists are cheaper than a wrong
   abstraction. At the third, extract a **component** — the props and boundaries question is
   `component-architecture`, not a CSS question. Reserve `@apply` for a genuinely global primitive
   in the stylesheet; an `@apply` block that reimplements a component is worse than the repetition.
6. **Merge conditional classes with the project's helper.** Later position in the `class` string
   does **not** win a conflict — the generated stylesheet's order decides, so `p-2` and `p-4` in
   one string resolve unpredictably. Use the project's existing `cn`/merge utility for any
   conditional or overridable class, and pass overrides through it rather than concatenating.
7. **Never build a class name from a fragment.** Tailwind finds classes by scanning source text,
   so `bg-${color}-500` produces no CSS. Write full class strings in a lookup map, and confirm the
   file you are editing is inside the project's content/source scan paths — a class in an
   unscanned file silently produces nothing.
8. **Make dark mode a token decision, not a per-utility one.** Check the project's dark-mode
   strategy first (media query vs a class/attribute toggle) and follow it. Prefer semantic tokens
   whose values differ per theme over stacking a `dark:` variant on every utility; add `dark:`
   where the token system genuinely cannot express the difference.
9. **Keep the class order the project keeps.** If a class-sorting formatter is configured, run the
   project's format command rather than hand-sorting.
10. **Look at it in both themes and at the breakpoints you touched.** Class lists are not evidence
    of rendering; hand that off to `browser-verification`.

## Checklist

- [ ] Theme tokens read before classes were written
- [ ] No arbitrary value that an existing token covers
- [ ] Any new token added to the theme, with the reason stated
- [ ] Repetition extracted at the third occurrence, as a component
- [ ] `@apply` used only for a global primitive, if at all
- [ ] Conditional/override classes routed through the project's merge helper
- [ ] No class name assembled from fragments
- [ ] Dark mode expressed through tokens where the system allows it
- [ ] Project formatter run; class order matches the codebase
- [ ] Light and dark rendered and looked at, not inferred

## Failure handling

- **A class is in the source but no style appears** — check, in order: the file is inside the scan
  paths, the class name is a complete literal string, the utility actually exists in this major
  version, and the build was re-run.
- **A style applies but the wrong value wins** — a conflict, not a specificity puzzle. Route both
  classes through the merge helper instead of adding `!important`.
- **Dark mode is right in one place and wrong in another** — the two places are using different
  mechanisms (one token, one `dark:` variant). Unify on the project's strategy.
- **A design needs a value no token has and the theme owner is not you** — use one arbitrary value
  with a comment and raise the missing token. Do not add tokens to a shared theme unasked; that is
  a change to every screen.
- **A theme token's value needs changing** — that repaints the app. Stop and ask before editing an
  existing token's value, even when it looks obviously wrong.

## Evidence to report

The tokens used; any token added, with its file and the reason; the count of arbitrary values left
and why each survived; whether repetition was extracted or deliberately left; and confirmation that
light and dark were both rendered, or a plain statement that they were not.
