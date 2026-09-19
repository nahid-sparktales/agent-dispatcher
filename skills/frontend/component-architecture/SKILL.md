---
name: component-architecture
description: Decide where a component's boundaries go, where state lives, what its props should be, and whether to split it — using composition instead of configuration flags. Fires when adding a component to an existing tree, when a component has grown props or responsibilities, or when a review asks whether a structure will hold. Not for visual design decisions, not for styling systems, and not a licence to restructure code the task did not ask you to touch.
---

# Component architecture

Structure is decided by where change arrives, not by file length. A 300-line component with one
reason to change is fine; a 40-line one that both fetches and renders is not.

## When this fires

Adding a component to an existing tree, changing one whose props or responsibilities have grown,
or reviewing whether a proposed structure will survive the next feature. It does not fire for
styling-only edits or for copy changes.

## Procedure

1. **Read the neighbours before designing.** Open two or three components in the same directory.
   The project has already answered most of these questions — prop naming, where data is fetched,
   whether state lives in a store or in the tree. Matching an existing pattern beats importing a
   better one into one file.
2. **State the component's one responsibility in a sentence.** If the sentence needs "and", you
   have either two components or one component with a helper. Write the sentence down; it is the
   boundary.
3. **Place each piece of state at the lowest node that reads it.** Then move it up only when a
   second reader actually appears — not when you predict one. State owned above where it is read
   re-renders subtrees that do not care; state owned below its readers gets lifted in a panic later.
4. **Keep derived values derived.** A value computable from existing state is not new state.
   Duplicating it creates two sources of truth and a synchronisation bug.
5. **Separate the data edge from the rendering.** Fetching, subscriptions and effects belong at a
   route or container boundary; leaves take data as props. A leaf that fetches cannot be reused,
   previewed or tested without standing up its whole world.
6. **Respect the framework's own boundary** where one exists — server vs client, island vs static.
   State, effects and event handlers force the interactive side, so push that boundary as far down
   the tree as it will go rather than marking a whole page interactive for one button.
7. **Design props as what, not how.** A prop names a fact about the data or the situation
   (`status`, `items`, `onSelect`), not an instruction about rendering (`shouldShowRedBorder`).
   Prefer one `variant`-style union over several booleans that can contradict each other.
8. **Reach for composition before configuration.** When a component needs to vary in a place, take
   `children` or a slot rather than adding a flag. Three or four booleans that toggle regions is
   the signal: expose the regions as sub-components and let the caller arrange them.
9. **Split on one of these triggers only** — two independent reasons to change; a prop that is only
   read on one branch; a piece that a second caller genuinely needs; or the component cannot be
   exercised without mocking things unrelated to what it renders. Do **not** split for line count,
   and do not create an abstraction with a single caller.
10. **Before changing a shared component's API, find every caller** and read them. A rename or a
    required-prop addition in shared code is a breaking change across the app — if the task did not
    ask for it, stop and ask rather than fanning the edit out.
11. **Check the result against the checklist, then verify it renders** — structure that type-checks
    can still mount wrong (see `browser-verification`).

## Checklist

- [ ] The component's responsibility fits one sentence without "and"
- [ ] Each state atom sits at the lowest node that reads it
- [ ] Nothing derivable is stored
- [ ] Data fetching sits at a container/route edge, not in a leaf
- [ ] The interactive boundary is as low in the tree as it goes
- [ ] No boolean prop combination can contradict another
- [ ] Varying regions are `children`/slots, not flags
- [ ] Every split has a named trigger; no single-caller abstraction was created
- [ ] Callers of any changed shared API were read, and breaking ones were raised

## Failure handling

- **A prop is drilled three or more levels** — try composition first (pass the rendered element
  down), context second, a global store last. Reaching for the store first is how a local concern
  becomes an app-wide one.
- **Everything re-renders on one keystroke** — locate the state owner before optimising. Memoising
  around misplaced state hides the cause and adds a cache to keep correct.
- **A component needs several unrelated mocks to render** — that is the split trigger, not a
  testing problem.
- **Two components look alike but change for different reasons** — leave them duplicated. Merging
  them produces a component with a flag for every difference within two features.
- **The existing pattern is genuinely bad** — say so once, in one line, with what you would do
  instead. Do not refactor the surrounding tree inside an unrelated task.

## Evidence to report

The responsibility sentence for each component you created or changed; where each piece of state
now lives and why; props added or removed with the reason; each split and the trigger that forced
it; what you deliberately left alone; and the callers you checked for any shared-API change. "Made
it cleaner" is not evidence.
