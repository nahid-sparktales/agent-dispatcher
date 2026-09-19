---
name: frontend-design
description: Establish a visual direction for new or reshaped UI so it reads as designed for this product rather than assembled from defaults — hierarchy, typography, colour, spacing, density. Use when building a new surface, when something looks templated and needs a direction rather than a tweak, or when asked to make an interface feel considered. Prefer the official Anthropic frontend-design skill when it is installed; this is the local counterpart for when it is not. Not for critiquing an existing interface, and not for work inside a design system that already decides these things.
---

# Frontend design

Defaults compose into something that looks like everyone else's work. A direction is a small set
of decisions made once, deliberately, and applied consistently — not decoration added at the end.

## When this fires

A surface is new, or is being reshaped, and the visual decisions are genuinely yours to make. It
does not fire when a design system already decides type, colour and spacing — there, overriding it
is a defect rather than a direction, and `design-systems` applies. It does not fire for judging an
interface that already exists; that is `ui-audit`.

## Procedure

1. **Look before deciding.** Read the screens that ship next to this one, any existing tokens or
   brand material, and the platform's own conventions. A direction that ignores its neighbours is
   a second direction, not a better one. If brand material exists and you have not read it, stop
   and read it.
2. **Name the register in one sentence** — who it is for, what it should feel like, and one thing
   it must *not* feel like. "Dense and factual, for people who live in it all day; not a marketing
   page." Every decision below gets checked against that sentence. Skip this and you will pick by
   reflex, which is how defaults win.
3. **Choose the one structural idea** the screen is organised around, before styling anything:
   what the eye lands on first, and what the layout is a layout *of*. A screen with no structural
   idea reads as a template no matter how good the type is.
4. **Set type first.** Pick the pairing (or one family with a real weight range), a scale with a
   deliberate ratio, and the four to six sizes you will actually use — not a continuum. Fix
   measure (roughly 45–75 characters) and line height per role: tighter for headings, looser for
   body. Typography carries more of "this looks designed" than colour does.
5. **Build colour from the neutrals out.** A neutral ramp does most of the work. Derive semantic
   roles — surface, raised surface, border, muted text, body text, accent, status — rather than
   collecting swatches. One accent that means something and therefore appears rarely. Check text
   contrast at the sizes you actually ship, in every theme you ship.
6. **One spacing scale, then a density decision.** Pick a step and use only its steps. Then set
   density deliberately against step 2: a monitoring console and a signup page are not the same
   product and must not share padding.
7. **Build hierarchy with size, weight, colour and space — in that order.** Reach for a border,
   card or box only after those four have failed. Most "everything is a card" layouts are a
   hierarchy problem solved with containers.
8. **Spend detail where it is seen** — the primary action, the empty state, the first screen — and
   let everything else be quiet. Motion is functional: it says where a thing came from. Honour
   reduced-motion.
9. **Render it and look at it**, desktop and mobile, with real content: the longest string, the
   empty case, the error. A direction you have only seen in source is not a direction.
10. **Squint at the result.** What reads first, second, third? If that is not the task's priority
    order, fix the hierarchy — not the saturation.

## Template tells

Each of these is a decision that was never made. Fix the decision, not the symptom.

- Three equal-weight cards in a row because there happened to be three things.
- One radius and one shadow applied to everything on the page.
- A gradient headline with no relationship to the product.
- A single text size everywhere, with bold standing in for hierarchy.
- Icons decorating labels that already say the same thing.
- Everything centred, including prose meant to be read.
- Colour used for variety instead of meaning.
- Emoji standing in for an icon set.

## Checklist

- [ ] Existing screens, tokens and brand material were read first
- [ ] The register sentence is written down, including the "not"
- [ ] Type scale, colour roles and spacing step exist as named values, not ad-hoc numbers
- [ ] Contrast checked at real sizes, in every theme that ships
- [ ] Hierarchy achieved before any container was added
- [ ] Rendered at desktop and mobile with long, empty and error content
- [ ] Anything left unrendered or unresolved is named

## Failure handling

- **The stack constrains the direction** — a component library with strong opinions. Work inside
  it and say what you could not change. Fighting it half way ships both directions at once.
- **A design system already exists.** The system wins unless the user says otherwise. Switch to
  `design-systems` rather than styling around it.
- **You cannot render anything.** Say the direction is visually unverified, and do not describe it
  as looking right. Applied in code is not the same as seen.
- **"Make it pop."** Translate to a hierarchy question — what should be read first — before
  touching saturation or size.
- **A change here touches shared components or tokens.** That is an edit to every other consumer:
  stop and ask before changing shared defaults, rather than absorbing the blast radius silently.

## Evidence to report

The register sentence. The type scale, colour roles and spacing step, as actual values. Screenshots
at both viewports with real content. What you deliberately left alone, and why. What remains
unrendered. Say plainly which of designed / implemented / rendered / verified you reached — a
direction applied in code and looked at once is implemented and seen, not tested.
