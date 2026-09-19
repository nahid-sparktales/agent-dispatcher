---
name: shadcn-ui
description: Work with shadcn/ui components and the Radix primitives under them — components are copied into the repo and are your source, so customize them in place, know that re-running the generator overwrites local edits, and know which accessibility behaviour Radix gives you and which it does not. Fires when adding, customizing or debugging a component in a repo with components.json and a vendored UI directory. Not for choosing a component library, not for general component structure, and not an accessibility audit.
---

# shadcn/ui and Radix primitives

These components are not a dependency. The generator copied source into the repository, and from
that moment it is ordinary project code that nobody upstream will patch for you.

## When this fires

Adding, customizing or debugging a shadcn/ui component in a project that has `components.json` and
a vendored UI directory. It does not fire for choosing a component library, for a project using a
conventional installed component package, or for a full accessibility audit.

## Procedure

1. **Confirm the model before assuming it.** `components.json`, a UI directory of component source,
   and `@radix-ui/*` entries in `package.json` together mean copy-in. Read `components.json` for
   the path aliases and conventions the generator will use — it decides where files land.
2. **Check whether the component already exists in the repo** before adding it. Re-running the
   generator for a component that is already there overwrites the file, including every local
   change. If the file exists and has been customized, adding it again is destructive — stop and
   ask rather than regenerating over someone's work.
3. **Add via the project's own generator invocation.** Take the exact command from the project's
   README or scripts; the CLI's package name and flags have changed across versions, so do not
   type one from memory. If the generator cannot be run here, copy the upstream component source
   into the same directory by hand and add the Radix dependency it imports — do not hand-roll a
   substitute primitive, and do not silently skip the dependency.
4. **Customize in place. That is the model, not a workaround.** Editing the vendored file is the
   intended way to change these components. Prefer the two low-damage forms: add a variant to the
   component's existing variant definition, and change appearance through the theme tokens rather
   than by rewriting markup (see `tailwind`).
5. **Wrap instead of edit when the change is product-specific.** A project-specific composition
   (your form field, your confirm dialog) belongs in a wrapper around the primitive, leaving the
   vendored file close to upstream and re-addable. Deep edits to the vendored file are fine, but
   they are the file you can no longer regenerate cheaply.
6. **Record which vendored files carry local edits.** A comment at the top of the file, or a line
   in the project's own notes — whichever the project already does. Without it, the next person
   regenerates and loses the change silently.
7. **Keep the component's class-merge path intact.** These components merge an incoming `className`
   with their own classes through a merge helper; if you rewrite that, caller overrides stop
   working in ways that look like a styling bug.
8. **Use `asChild` correctly when composing triggers.** It renders the primitive's behaviour onto
   your child element instead of its own: the child must be a single element that forwards props
   and ref. A fragment, two children, or a component that drops props produces a control that looks
   right and does nothing.
9. **Know what Radix gives you and what it does not.** Free from the primitive: keyboard
   interaction and focus management for the pattern, focus trapping and restoration in overlays,
   dismissal behaviour, correct roles and state attributes, and the internal wiring between a
   trigger and its content. **Not** free: an accessible name for an icon-only trigger, a label
   associated with your own input, error text wired to the field it describes, colour contrast,
   heading order, honouring reduced-motion, and a visible focus indicator if you removed the ring.
   Those are yours every time.
10. **Verify with the keyboard and the accessibility tree**, not a screenshot — tab to the control,
    operate it, Escape out of it, and check the name it exposes. Rendered verification is
    `browser-verification`.

## Checklist

- [ ] `components.json` read; the component's target path known
- [ ] Existing file checked before any generator run, and overwrite consent obtained if needed
- [ ] Generator command taken from the project, not from memory
- [ ] Customization done in place, preferring variants and theme tokens
- [ ] Product-specific behaviour put in a wrapper, not baked into the primitive
- [ ] Local edits to vendored files recorded
- [ ] `className` merge path intact; caller overrides still apply
- [ ] Every `asChild` usage has exactly one prop-and-ref-forwarding child
- [ ] Icon-only controls have accessible names; inputs have associated labels
- [ ] Focus visible, keyboard path walked, Escape/dismiss checked

## Failure handling

- **A caller's `className` does nothing** — the merge helper was bypassed or the class conflicts
  with the component's own. Fix the merge, not with `!important`.
- **A trigger renders but does not open** — suspect `asChild` with a child that swallows props or
  ref, or two children where one is required.
- **The component switches between controlled and uncontrolled** — a value prop that starts
  `undefined` and later becomes defined. Pick one mode and keep it.
- **"Upgrade shadcn" is asked for** — there is no upgrade command for code you own. Diff the
  current upstream source against each vendored file and apply changes deliberately, file by file,
  keeping local edits. Say which files you did not touch.
- **The generator is unavailable or offline** — say so, copy the source manually or stop; do not
  invent an approximation of a primitive and present it as the component.
- **Accessibility looks handled because Radix is present** — it is not a conclusion you can draw
  from the import. The list in step 9 is checked by hand or reported as unchecked.

## Evidence to report

Which components were added or edited and at what paths; whether each vendored file now carries
local changes; how customization was done (variant, token, wrapper, direct edit); the keyboard and
accessibility-tree checks you actually performed and what they showed; and anything from the
step-9 list you did not check.
