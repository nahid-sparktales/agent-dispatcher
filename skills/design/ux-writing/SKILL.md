---
name: ux-writing
description: Write or repair the words inside an interface — button labels, empty states, error messages, confirmation dialogs, form hints, success and loading text — so a reader knows what just happened and what to do next. Use when a screen's copy is being written or reviewed, when an error says something unhelpful, when a confirmation is vague about what it will do, or when users hesitate at a control. Not for marketing or landing-page copy, not for documentation, and not for deciding layout or visual design.
---

# UX writing

Interface copy is read mid-task by someone who did not come to read. Every word is either doing
work — naming an outcome, removing a doubt, offering the next move — or it is in the way.

## When this fires

A screen's strings are being written, reviewed or translated; an error, empty state or
confirmation is unclear; a control's label does not match what it does. It does not fire for
prose the user chose to read: docs, marketing pages, release notes.

## Procedure

1. **Collect the actual strings.** Grep the component, route or feature for every user-visible
   string, including the ones not on screen right now — error branches, empty results, disabled
   reasons, toast text. Copy you never saw is copy you never fixed.
2. **Name the reader and the moment.** What were they doing one action ago, what do they already
   know, and what do they need to decide next. Write to that person, not to a persona.
3. **Fix labels first.** A label names the outcome in the reader's words, not the mechanism in
   yours: "Save changes", not "Submit"; "Delete project", not "Confirm". Avoid Yes/No button
   pairs — a button that repeats the verb can be answered without re-reading the question.
4. **Rewrite errors to be actionable.** Say what happened, why when you actually know, and what
   the reader can do. Never blame the reader, never show a raw exception or bare status code as
   the whole message, and keep any support-quotable identifier alongside plain words rather than
   instead of them. Do not promise a retry, a saved draft or a notification that the code does
   not perform.
5. **Separate the three empty states.** Nothing yet (say what will appear here and give one way
   to start), filtered to nothing (name the filter and offer to clear it), and failed to load
   (that is an error, not an empty state — do not let it read as "you have none").
6. **Make confirmations specific.** State the object by name, state the consequence, and repeat
   the verb on the primary button. For anything destructive, say what is lost and whether it can
   be undone — if the code has no undo, the copy must not imply one. When the copy and the code
   disagree about reversibility, stop and raise it; do not paper over it with softer wording.
7. **Cut the words carrying no information.** Padding ("please", "simply", "just"), fake cheer
   ("Oops!"), exclamation marks, and restating the screen's own title. Then check the result
   still sounds like the rest of the product — consistency beats each string being individually
   clever.
8. **Check every string against what the code does.** A label that describes behaviour the
   function does not have is a bug report, not a copy edit. Report it as a bug.
9. **Check the string survives contact with reality.** Longest plausible value, truncation,
   sentence-case consistency with neighbours, and an accessible name for every icon-only control.
   If the product is localized, note that changed strings need re-translation and that other
   languages run longer.

## Checklist

- [ ] Every user-visible string in the changed surface was listed, including unrendered branches
- [ ] Buttons name outcomes; no ambiguous Yes/No pair
- [ ] Each error says what happened and what to do, with no raw exception as the message
- [ ] Empty, filtered-empty and failed-to-load are distinguishable
- [ ] Destructive confirmations name the object and state reversibility truthfully
- [ ] Copy matches actual code behaviour; mismatches reported, not smoothed over
- [ ] Icon-only controls have accessible names
- [ ] Translation and length impact noted where it applies

## Failure handling

- **The right words depend on behaviour you cannot determine** — read the handler. If it is still
  ambiguous, write the copy that is true of both branches and flag the question rather than
  inventing the more reassuring version.
- **Legal, consent, pricing, security or privacy wording** — propose, do not replace. These are
  approved text somewhere; stop and ask before changing them.
- **The string is a translation key or appears in many places** — check every use before editing.
  A label reworded for one screen can be wrong on three others.
- **The real problem is the flow, not the sentence** — say so. Copy that has to apologize for an
  interaction is a design finding; writing around it hides the defect.

## Evidence to report

The before and after of each changed string, with the file and the state it appears in; the
mismatches you found between copy and code; the strings you deliberately left alone and why; and
anything that needs approval or re-translation. "Improved the microcopy" with no strings quoted is
not evidence.
