---
name: motion-design
description: Decide what an animation is communicating, then give it a duration, an easing curve, an interruption behaviour and a reduced-motion fallback. Use when adding or reviewing transitions, when a screen feels sluggish or jumpy, when implementing motion specified in a design, or when animation needs to survive users who ask for less of it. Not for static visual design, and not for general performance profiling of code that has no animation.
---

# Motion design

Motion is a sentence about what just changed. An animation that does not say where something came
from, that input registered, or that work is under way is decoration the user waits through.

## When this fires

Transitions, animated state changes, gesture-driven movement or loading indicators are being
added, changed or reviewed — or an interface reads as janky, slow, or unexplained.

## Procedure

1. **Give each motion a job, in one sentence.** The honest jobs are: continuity (this came from
   there), feedback (your input registered), status (something is still happening), and attention
   (this changed and you would have missed it). Motion with no job gets cut — that is the cheapest
   improvement available here.
2. **Set duration from the size of the change, not from taste.** Small local feedback is nearly
   instant (around a tenth of a second); ordinary component transitions sit in the low hundreds of
   milliseconds; large or full-screen surfaces take somewhat longer. Past roughly half a second
   the user is waiting on you, and it must buy something. Shorter is the safer error.
3. **Choose easing from the direction of travel.** Elements entering the screen decelerate into
   place; elements leaving accelerate out; elements moving between two on-screen positions ease
   both ends. Reserve linear for continuous or indeterminate loops, where easing would read as a
   pulse.
4. **Anchor the movement to its trigger.** A panel opens from the control that opened it; a row
   expands in place; a dismissed item leaves the way a user pushed it. Movement that starts
   somewhere unrelated to the tap breaks the continuity it was meant to provide.
5. **Make it interruptible.** A second input during an animation must be honoured immediately and
   the motion must reverse or retarget from where it currently is, not restart from the beginning
   and not queue. A transition that swallows input, or that must finish before the UI responds,
   is a defect regardless of how it looks.
6. **Implement the reduced-motion path deliberately.** Respect the OS-level reduced-motion
   preference, and treat it as a substitution rather than a deletion: a cross-fade or an immediate
   state change, so the change is still legible. Never carry information only in the movement —
   if the animation is the only thing saying an item was added or removed, the still frame must
   say it too.
7. **Keep stagger small and bounded.** A short per-item delay across the first few items, then
   nothing. A list that ripples for a second is slower than a list that appears.
8. **Prefer properties the compositor can animate** — transform and opacity — over animating
   layout geometry, which recomputes layout every frame. When a property's cost is not obvious,
   measure rather than assume.
9. **Watch it run, repeatedly, on the slowest target you have.** Loop it; play it with the CPU
   throttled; play it on a device, not only a desktop browser. Motion is the thing that reads
   correct in the source and wrong on screen, and what you notice on the tenth viewing the user
   notices on the second. Reading the CSS is not watching the animation.

## Checklist

- [ ] Each animation's job stated, or the animation removed
- [ ] Durations scaled to the size of the moving element, nothing gratuitously long
- [ ] Easing matches enter / exit / move-between; linear only for continuous loops
- [ ] Motion originates at its trigger
- [ ] Interrupting mid-flight reverses or retargets, and input is never blocked
- [ ] Reduced-motion path substitutes rather than strips, and no meaning lives only in movement
- [ ] Observed running, at least once on a slow path, not only inferred from code
- [ ] Loading and indeterminate states still readable at their slowest

## Failure handling

- **"It feels slow"** — separate the animation from the wait behind it. Shortening a transition
  that is covering a two-second fetch fixes nothing; the fix is a status motion plus a faster
  fetch, and those are two different findings.
- **Stutter or dropped frames** — profile before tuning. Guessing at duration when the cause is a
  layout-thrashing property produces a shorter bad animation.
- **It looks right in the browser and wrong on device** — trust the device. Say which one you
  observed on; never generalize one smooth desktop run to "animation verified".
- **No way to observe it running** — say motion was not observed, report what the code specifies,
  and do not describe it as checked. Reduced-motion behaviour in particular is only confirmed by
  running with the preference set.
- **A motion carries meaning nothing else carries** — that is an accessibility defect, not a
  tuning question. Raise it rather than quietly shortening the animation.

## Evidence to report

Each animation, its stated job, its duration and easing, and the property it animates; what you
saw when you interrupted it; what the reduced-motion path does and whether you actually ran with
the preference set; the device or throttling conditions you observed under; and any motion you
changed the timing of without being able to watch it.
