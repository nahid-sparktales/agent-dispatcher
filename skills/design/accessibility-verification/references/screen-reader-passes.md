# Screen-reader passes

One real pairing is the minimum: **VoiceOver + Safari** (macOS/iOS) or **NVDA + Firefox** (Windows).
Reader and browser are tested as a pair — a result from one pairing does not transfer to another, so
always report which one you used.

## VoiceOver (macOS)

- Toggle: `Cmd+F5`. The VO modifier keys are `Ctrl+Option` ("VO").
- Move through the page: `VO+Right` / `VO+Left`. Activate: `VO+Space`.
- Read continuously from here: `VO+A`. Stop any speech: `Ctrl`.
- The rotor: `VO+U`, then Left/Right to switch between headings, links, landmarks, form controls.
  This is the fastest way to check whether structure is usable.
- Interact with a composite widget or table: `VO+Shift+Down` to enter, `VO+Shift+Up` to leave.
- Use the caption panel (VoiceOver Utility) when you need to read exactly what was announced rather
  than transcribe audio from memory.

## NVDA (Windows)

- The NVDA modifier key is `Insert` (or `CapsLock` in laptop layout).
- Read continuously: `NVDA+Down`. Stop: `Ctrl`.
- Browse mode vs focus mode matters: NVDA switches automatically in forms and widgets. `NVDA+Space`
  toggles it manually. A control that only works in one mode is a finding.
- Elements list: `NVDA+F7` — headings, links, landmarks, form fields.
- Jump by element type in browse mode: `H` headings, `D` landmarks, `F` form fields, `B` buttons,
  `T` tables, `1`–`6` heading levels.
- Speech viewer (NVDA menu → Tools) gives you the announced text as copyable lines. Use it for the
  report instead of paraphrasing.

## What the pass is actually looking for

Not "does it speak" — it always speaks. Ask, at each stop:

1. **Name** — is what it says the thing the user sees, and does it distinguish this control from its
   siblings? Five links all announced "Read more" is a finding.
2. **Role** — does it announce what it is, and is that true? A `div` announced as a button that does
   not respond to Space is worse than an unstyled button.
3. **State** — expanded/collapsed, selected, checked, disabled, current, invalid. State that is only
   visual is invisible here.
4. **Order** — does reading start to finish produce a coherent page? Does the tab order match it?
5. **Change** — when something updates without a page load, is it announced, once, at the moment it
   happens? Errors and status messages are where this usually fails.
6. **Completion** — could you finish the real task using only what was announced? That is the whole
   test. Everything above is diagnosis for why not.

Record the exact announced strings for anything you report. "The button was unclear" is not a
finding; `"button" with no name, at the top of the dialog` is.
