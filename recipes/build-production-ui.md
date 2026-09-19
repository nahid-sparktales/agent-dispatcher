---
id: build-production-ui
name: "Build production UI"
summary: "Design and implement an interface, then prove in a browser that it renders, responds and is reachable."
use_when: "An interface is being created or redesigned and it will be shipped to real users."
capabilities: design.ui.direction, design.systems, design.accessibility, design.responsive, verification.browser, verification.accessibility
roles: ui-ux-designer, implementer, tester
---

# Build production UI

Source code compiling is not evidence that an interface works. This recipe exists to keep those
two things apart.

## Steps

1. **Inspect the product.** What exists now, what the user is trying to do on this screen, where
   this screen sits in the flow.
2. **Inspect the design system.** Tokens, components, conventions already in use. Extending what
   is there beats inventing beside it. → `design-systems`
3. **Identify the user task and the problems in the current design.** Hierarchy, disclosure,
   labels, states — before colour and decoration. → `ui-audit`
4. **Choose a direction** and say what it is, so the result can be judged against an intention
   rather than a preference. → `frontend-design`
5. **Detect the stack** before loading any framework guidance. React, Next.js, Tailwind, shadcn —
   whatever the repository actually says. → `stack-detection`
6. **Implement**, specifying states as you go: empty, loading, error, long content.
7. **Render it.** Desktop, then mobile with a reload. → `browser-verification`
8. **Interact** with every control the change touches.
9. **Check accessibility** — automated scan plus keyboard path and focus order. →
   `accessibility-verification`
10. **Read the console**, on load and after interaction.
11. **Fix, then render again.** A fix is not verified by the reasoning that produced it.
12. **Report** what was checked, at which sizes, and what was not.

## Gates

- The rendered interface was inspected at desktop and mobile sizes, or the report says plainly
  that browser tooling was unavailable and the UI is therefore unverified.
- Every control the change touches was operated, not just rendered.
- Accessibility was checked by keyboard, not only by a scanner — a scanner catches roughly a third
  of WCAG issues and proves nothing on its own.

## What to cut

A copy change or a spacing fix does not need all twelve steps. Keep step 7 and step 10 regardless:
rendering and the console are cheap and catch the embarrassing failures.
