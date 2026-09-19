---
name: seo
description: Make a page findable for a real query — match the intent behind it, structure the page around that intent, and clear the technical floor that decides whether it can be crawled and indexed at all. Use when a page is written for search, when traffic drops or a page is missing from results, when someone asks "how do we rank for X", or before publishing content meant to be found. Not for writing the copy itself, not for page speed work, and not for paid search or social distribution.
---

# SEO

Most search work that fails is not outranked — it is never eligible. The page is blocked, not
indexed, duplicated across three URLs, or written for a phrase nobody types with the intent the
page actually serves. Fix eligibility and intent before touching anything else, and never present
a published page as a ranking one.

## When this fires

A page is being written or revised to be found in search; traffic to a page fell; someone asks
which query a page should target, or why a page is not appearing. It does not fire for ad copy,
email, social distribution, or for a page deliberately kept out of search.

## Five states — keep them apart

**Published** → **crawlable** → **indexed** → **ranking for a query** → **earning clicks that
convert**. Each is checked differently and each can fail while the one before it succeeded. "The
page is live" is a statement about the first only. Never report a later state you did not observe.

## Procedure

1. **Name one query and the intent behind it.** Informational, navigational, transactional, or
   comparison-shopping. Write the intent down as a sentence about what the person wants next.
2. **Read the current results page for that query** before deciding anything. What already ranks
   is the clearest available evidence of the intent the engine has settled on: if the whole page
   is comparison tables and yours is a product pitch, the format is the mismatch, not the wording.
   If you cannot see the results page, say so and treat the intent as assumed.
3. **Check no page you own already targets it.** Two pages after one intent split their own
   signals and neither wins. Decide: extend the existing page, or pick a genuinely different
   intent. Merging or redirecting existing URLs is a live-traffic change — propose it, do not do it.
4. **Structure the page around the intent.** The answer near the top, not after the preamble.
   One `h1` naming the subject; sub-headings that mirror the actual sub-questions a reader has,
   in the order they have them. Title and description written to be chosen from a list of ten
   results, not to repeat the keyword back.
5. **Clear the technical floor, by observation not assumption.** For the live URL, confirm: it
   returns 200; `robots.txt` does not disallow it; no `noindex` in the meta or response headers;
   one self-referential canonical; a real `<a href>` path to it from somewhere already indexed;
   it is in the sitemap; the URL is stable and readable. Record what each check actually returned.
6. **Check what a crawler receives, not what a browser renders.** Fetch the raw HTML, or load the
   page with JavaScript disabled. Main content and internal links that exist only after client-side
   rendering are content you cannot count on. Name any that are missing from the source.
7. **Give internal links a job.** Link to the page from pages that are already indexed and related,
   with anchor text that describes the destination. This is the one ranking input entirely inside
   your control; orphan pages are the most common self-inflicted failure.
8. **Add structured data only where a genuine type applies** and only describing what is visibly on
   the page. Marking up content the visitor cannot see is a penalty risk, not an optimization.
9. **Hand speed and layout stability to the performance work** rather than guessing at it here, and
   confirm the page is usable on a phone — that is where most search traffic reads it.
10. **Measure from the site's own search console.** Query, impressions, clicks, average position,
    for a stated date range, for that URL. An estimate from a third-party rank tracker is an
    estimate; label it as one. Indexing status comes from the index-inspection report, not from
    the fact that the page loads for you.
11. **Stop and ask before anything that can remove traffic**: editing `robots.txt`, adding
    `noindex`, changing a canonical, creating or changing redirects, deleting or merging live
    URLs, or publishing. These are outward-facing and several are hard to reverse. Draft the
    change, show the current value and the proposed one, and wait.

## What no longer moves anything

Say so plainly when asked for these, and spend the effort on intent and structure instead: keyword
density targets and repeating the phrase into the copy; the meta keywords tag; a separate thin page
per keyword variant; doorway pages; word-count targets treated as a quality signal; spun or
near-duplicate text produced for volume; keyword-stuffed alt text and filenames; changing publish
dates to look fresh without changing content; hidden text; exact-match anchor text used at scale;
and buying links, which is a manual-action risk rather than an ineffective tactic.

## Checklist

- [ ] One query named, with its intent written as a sentence
- [ ] Current results for that query read, or the intent marked as assumed
- [ ] No second page of yours chasing the same intent
- [ ] Status code, robots directive, canonical and sitemap entry each checked and recorded
- [ ] Raw HTML inspected — main content and links present without JavaScript
- [ ] At least one internal link from an indexed, related page
- [ ] Console data quoted with its date range, or its absence stated
- [ ] Every robots / canonical / redirect / publish change proposed rather than made

## Failure handling

- **Page is not in the index** — report it as not indexed and name the checks that passed and
  failed. Do not conclude a penalty; the ordinary causes are a blocking directive, a canonical
  pointing elsewhere, no internal links, or simply that not enough time has passed.
- **Traffic dropped** — separate the candidates before explaining: fewer impressions (demand or
  visibility), same impressions with fewer clicks (title, description, or a results-page feature
  taking the click), or the page dropping out of the index entirely. Each has a different fix.
- **Rankings move day to day** — that is normal variation. A single-day comparison is not a result;
  use a window long enough that the change survives it.
- **No console access and no crawl data** — say which states could not be observed. Report on the
  technical floor you could check and stop at "eligible", never at "will rank".
- **The request is to rank for a query the page does not serve** — say that, and offer the query
  the page does serve. Writing for the wrong intent wastes the page.

## Evidence to report

The URL and the query with its intent. What the results page for that query currently looks like.
Each technical check with the value it returned, not a tick. What the raw HTML did and did not
contain. The internal links pointing at the page. Console figures with their date range and source.
The changes proposed but not made, with their current values. And the list of states you did not
observe — usually indexing and ranking, which arrive later than the work does.
