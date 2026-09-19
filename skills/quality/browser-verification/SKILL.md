---
name: browser-verification
description: Prove a UI change actually renders and works — desktop and mobile, controls operated, console clean. Use before reporting any change to rendered UI as done, when asked whether a screen actually functions, or when checking someone else's frontend work. Not for judging whether a design is good, and not a substitute for tests you intend to keep.
---

# Browser verification

Reading the source is not verification. A component that compiles, type-checks and looks right in
the diff can still render blank, overflow its container, or throw on mount.

## When this fires

After any change to rendered UI, before that change is reported as working — your own work or
someone else's. It does not fire for a change with no rendered surface. One change, checked
once, is this skill; a matrix of states across viewports and themes, or a comparison against a
screenshot baseline, is `visual-verification`.

## Procedure

1. **Get it running.** Start the dev server or open the deployed URL. If it will not start, that
   is the finding: report it and stop the verification — never verify a stale build. The work
   under test is then reported as unverified, not as failed.
2. **Render the route that changed**, not the home page. Wait for network idle before judging.
3. **Read the console and network first**, before looking at pixels. An error here explains most
   of what you are about to see. Record the exact message, not "some errors".
4. **Inspect desktop.** Screenshot. Does the intended change appear; is anything clipped or
   overlapping; does content overflow; did images and fonts load.
5. **Inspect mobile.** Resize to 375×812 and **reload** — layout-time breakpoints and device gates
   do not re-run on resize alone. Same checks, plus: horizontal scrolling, tap-target reachability,
   text legibility.
6. **Operate every control the change touches.** Click the primary action, submit the form, open
   the menu, type in the input. A control that renders and does nothing is the most common failure
   this procedure exists to catch.
7. **Reach the states that are not the happy path** — empty, loading, error, long content — by the
   cheapest honest route available.
8. **Re-read the console** after interacting. Errors thrown on click do not appear on load.
9. **Fix what you found, then start again from step 2.** A fix is not verified by the reasoning
   that produced it.

## Checklist

- [ ] The changed route was rendered, not just built
- [ ] Desktop screenshot taken and read
- [ ] Mobile viewport reloaded and read
- [ ] Every control the change touches was actually operated
- [ ] Console checked on load and again after interaction
- [ ] Empty / loading / error states reached, or named as unchecked
- [ ] Everything still unverified is named in the report

## Failure handling

- **Server will not start, or the URL is unreachable** — that is the result. Do not fall back to
  reading source and calling it verified.
- **Screenshot looks right but a control does nothing** — trust the interaction, not the picture.
  Check the console: a handler that throws renders identically to one that works.
- **The failure will not reproduce** — say so, with what you tried. An intermittent failure
  reported as fixed is worse than one reported as intermittent.
- **No browser tooling available** — say rendered verification could not be performed, name what
  you did check, and do not call the change verified. Degrading honestly beats a false pass.

## Evidence to report

The route and viewports checked; what each control did when operated; console output quoted, or
"clean" if it genuinely was; screenshots where they show what words cannot; and the list of states
and paths **not** checked. "Verified in the browser" with none of that is not evidence.

See `references/driving-the-browser.md` for which tool to reach for.
