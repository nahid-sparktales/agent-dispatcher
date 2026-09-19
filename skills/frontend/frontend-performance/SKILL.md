---
name: frontend-performance
description: Make a page measurably faster — pick the metric that is actually bad, measure it under stated conditions, find the real cause, apply the fix that moves that specific metric, re-measure the same way. Use when a page is called slow, when LCP, CLS, INP, TTFB, a Lighthouse score or bundle size is named, when a bundle has grown, or before claiming an optimization worked. Not for backend query or API latency, not for choosing a framework, and not a substitute for checking the page still works afterwards.
---

# Frontend performance

Most frontend performance work fails in one of two ways: optimizing something that was never the
bottleneck, or reporting an improvement that was measurement noise. Both are avoided by deciding
what to measure before touching anything.

## When this fires

A page is reported slow, a Core Web Vital is out of range, a bundle grew, or a change is about to
be described as a performance improvement. It does not fire for slowness that traces to a server
response or a database query — that is backend work, and the giveaway is a bad TTFB with a fast
render once bytes arrive.

## What actually gets measured

Three Core Web Vitals, at the **75th percentile of real page loads, segmented by device class**:

| Metric | Good | Poor above | What it is |
| --- | --- | --- | --- |
| LCP | ≤ 2.5s | 4.0s | When the largest content element finishes rendering |
| CLS | ≤ 0.1 | 0.25 | Unexpected layout movement over the page's life |
| INP | ≤ 200ms | 500ms | Worst-case latency from an interaction to its next paint |

TTFB and FCP are diagnostics, not Core Web Vitals — useful for locating a cause, not for grading.
**Bundle size is not a Core Web Vital at all.** It is an input that mostly reaches INP (parse,
compile and execute time on the main thread) and reaches LCP only when script blocks the render.

## Procedure

1. **State the metric and the segment.** "The site is slow" is not a target. "Mobile LCP on the
   product page is 4.1s at p75" is. Without a segment you will optimize desktop and ship nothing.
2. **Prefer field data over lab data for the diagnosis.** Real users on real devices and networks
   are what the metric is defined over. Lab tools cannot produce a real INP or a full-session CLS,
   because both depend on what a user did. If there is no field data, say the diagnosis is
   lab-only and treat it as a hypothesis.
3. **Fix the lab conditions and write them down** before the first run: production build (never a
   dev server — unminified code and HMR make the numbers meaningless), mobile emulation with CPU
   and network throttling, cold cache, no extensions, one page at a time.
4. **Run it more than once.** Take the median of five, not one run. A single lab number cannot
   tell a 15% win from ordinary variance, and most reported wins are inside that band.
5. **Identify the specific offender**, not the category. For LCP, name the element the browser
   actually chose. For CLS, name the node that moved and what pushed it. For INP, capture the
   interaction and find the long task. A fix aimed at a category rather than an element is a guess.
6. **Apply the fix that moves that metric** — see the table below. One change at a time; batched
   changes cannot be attributed, and one of them is usually a regression hiding behind the others.
7. **Re-measure with the identical method** from step 3: same build type, same throttling, same
   number of runs, same page. Comparing a fresh measurement to a remembered one proves nothing.
8. **Check the page still works.** An optimization that defers, lazy-loads or splits something can
   break rendering or interaction. Run rendered verification before calling it done.
9. **Report before and after with the conditions attached.** A number without its conditions is
   not a measurement.

## Which fix moves which metric

- **LCP** — the LCP element is usually a hero image or a headline block. Serve it at the right
  size and format; do not lazy-load it; raise its fetch priority and preload it if discovery is
  late; remove render-blocking CSS and script ahead of it; inline the critical styles it needs.
  If TTFB is the bulk of LCP, the fix is caching, CDN or server render cost — nothing in the
  client will help.
- **CLS** — reserve space before content arrives: explicit dimensions or an aspect ratio on every
  image, video, iframe, ad slot and embed; a fixed height for banners and late-injected content;
  never insert above existing content after paint. Web fonts shift text when the fallback has
  different metrics — match the fallback's metrics rather than removing the font. Animate
  transform and opacity, not properties that trigger layout.
- **INP** — this is main-thread contention during an interaction. Break up long tasks and yield
  between them; do less work in the event handler; cut the re-render the interaction triggers;
  defer or remove third-party scripts competing for the thread. Shipping less JavaScript helps
  here, which is the only place bundle work reliably shows up.
- **TTFB** — server, cache and redirect chains. Frontend changes do not move it.
- **Bundle weight** — build with source maps, read the treemap your bundler's analyzer produces,
  and go after the largest single contributors: a whole library imported for one function, a date
  or icon package pulled in entirely, a polyfill set for browsers you do not support, a duplicated
  dependency at two versions. Route-level code splitting is the structural fix; it shrinks the
  initial payload without deleting features. Measure bundle size on the built output, not on
  dependency counts.

Two traps worth naming: **a smaller bundle with an unchanged LCP element does not improve LCP**,
and **a better Lighthouse score is not a better experience** — the score is a weighted lab
composite, and it can rise while the metric a user feels stays flat.

## Checklist

- [ ] The target metric and the device segment are named, not "slow"
- [ ] Field data consulted, or the diagnosis explicitly marked lab-only
- [ ] Measured on a production build under written-down throttling conditions
- [ ] Median of multiple runs, not a single number
- [ ] The specific LCP element / shifting node / long task identified before any fix
- [ ] One change at a time, each re-measured by the same method
- [ ] Rendered behaviour re-checked after the optimization
- [ ] Conditions reported alongside both numbers

## Failure handling

- **The numbers move but the metric does not** — the thing you optimized was not the bottleneck.
  Revert it rather than keeping an unattributed change, and go back to step 5.
- **Before and after are within noise** — report it as no measured change. A 5% lab delta over
  five runs is not a result, and claiming it burns the credibility of the real wins.
- **The bottleneck is a third-party script you do not control** — say so, quantify its cost, and
  offer the options that exist (defer it, load it on interaction, drop it). Removing a vendor's
  tag is a product decision: surface it, do not make it.
- **Field data exists and disagrees with the lab** — the field data is the metric. The lab is a
  reproduction of one device on one network.
- **No measurement tooling is available** — do not estimate. Name the likely causes as hypotheses,
  say nothing was measured, and never report an unmeasured change as an improvement.
- **The fix requires a deploy to observe** (CDN, cache headers, edge config) — stop and ask before
  deploying anything. Field data only updates after real traffic, so a same-day field comparison
  is not available and should not be implied.

## Evidence to report

The metric and segment targeted; the measurement conditions verbatim (build type, throttling,
run count); the before and after values from those runs; the specific element, node or task
identified as the cause; the one change made; the bundle treemap before and after when bundle
work was part of it; and what remains unmeasured — including whether real-user data has confirmed
anything yet. "Improved performance" with no conditions and no numbers is not evidence.
