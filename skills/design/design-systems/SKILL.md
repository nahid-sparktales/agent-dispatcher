---
name: design-systems
description: Build UI inside an existing design system — find its tokens and components, reuse before adding, decide between extending a component and introducing a new one, and preserve conventions you did not set. Use when a project already has design tokens, a component library, a theme or a shared Figma library and you are about to add or change UI inside it. Not for establishing a visual direction where no system exists, and not for reviewing an interface's usability.
---

# Working inside a design system

A system's value is that everything in it agrees. The expensive mistakes are not ugly components —
they are the private token, the one-off override and the sixth button variant, each individually
reasonable, which together turn a system back into a pile of CSS.

## When this fires

The project already has tokens, a component library, a theme or a shared library, and you are
adding or changing UI inside it. It does not fire when there is no system and the decisions are
yours — that is `frontend-design`.

## Procedure

1. **Find the system before writing anything.** Locate the token source, the component directory,
   its documentation, and two or three real usage sites. Say where each lives. If the system is a
   third-party library, read its current documentation rather than recalling its API — versions
   move and a guessed prop is a silent fork.
2. **Read the conventions you did not set**: token naming and whether tokens are primitive or
   semantic, how variants are expressed (props, classes, compound components), how theming and
   dark mode resolve, file and export layout, and what the existing components already handle that
   you were about to reimplement.
3. **Take the highest rung that holds**, in this order:
   1. An existing component, as it is.
   2. An existing component with an existing variant or prop.
   3. Existing primitives composed together.
   4. An existing component extended with a new variant.
   5. A new component in the system.
   6. A local one-off, explicitly marked as not part of the system.

   Most work stops at rung 1 or 2. Reaching rung 5 for a single screen is almost always rung 3
   misread.
4. **Extend when the need is the same concept under a new condition** and the component's API stays
   coherent afterwards — a new size, a new tone of the same control. **Add when it is genuinely a
   different concept** and at least two or three real, existing uses want it. One speculative use
   is not a system component; build it locally and promote it when the second use arrives.
5. **Never hardcode a value a token covers.** If no token covers what you need, that gap is the
   finding: report it and choose the nearest token, or ask. Inventing a private token beside the
   system is how the system stops being one.
6. **Treat a shared component as every screen that uses it.** Before changing one, list its call
   sites. Changing a default, renaming or removing a prop, or altering a token's value is a change
   to all of them — stop and ask before doing it, and name the consumers in the question.
7. **Follow the convention even where you disagree.** Say your disagreement once, in the report,
   and then match what is there. A locally better choice that breaks the pattern costs more than
   it gains.
8. **Render what you built inside the real system**, not in isolation: every theme the system
   ships, both a small and a large viewport, and the component's own states. Token and variant
   changes are invisible in a diff and show up only on screen.
9. **Document the addition where the system documents things** — the same place, the same shape,
   with a usage example and the case it is *not* for. An undocumented component is one somebody
   reimplements next quarter.

## Checklist

- [ ] Token source, component directory and real usage sites located and named
- [ ] Existing components checked before anything new was written
- [ ] The chosen rung is named, and why the one above it did not hold
- [ ] No raw value used where a token exists; every gap reported rather than patched privately
- [ ] Call sites listed before any shared component or token was touched
- [ ] Shared-surface changes were asked about, not assumed
- [ ] Rendered in every theme and at two viewports
- [ ] New or extended components documented where the system documents things

## Failure handling

- **No system is findable** — say so before proceeding. Do not invent one mid-task; either the
  work is `frontend-design`, or the system exists somewhere you have not looked yet. Ask.
- **The system contradicts itself** — two patterns for the same thing. Follow the one in newer or
  more numerous use, say which you followed and that the conflict exists. Do not resolve it by
  adding a third.
- **The design calls for something the system cannot express.** Report the gap with the specific
  case. Do not override the system to fake it; an override is invisible to the next reader and
  survives longer than the reason for it.
- **A token change looks right on your screen.** It is not verified until rendered in each theme —
  a value that reads well on light can fail contrast on dark.
- **The system is owned by another team.** Proposing a change to it is outward-facing work: prepare
  it, stop, and let the user take it to them.

## Evidence to report

Where the system lives — token file, component path, documentation. Which rung you took and what
ruled out the one above. Every token and component reused, by name. Any gap found. For a shared
change: the call sites, and the approval you were given. Screenshots per theme and viewport. State
plainly what was reused versus created, and whether the result was rendered or only built —
composed from system parts is not the same as seen working.
