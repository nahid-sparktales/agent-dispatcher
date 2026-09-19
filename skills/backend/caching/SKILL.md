---
name: caching
description: Decide what to cache, at which layer, for how long, and how it gets invalidated — before any cache is added. Use when someone proposes caching to make a read path faster, when stale or cross-user data is suspected, when adding a TTL or a Redis/CDN layer, or when reviewing a change that introduces one. Not for fixing a slow query or an N+1 (do that first — a cache over a bad query hides it), and not for HTTP header tuning with no server-side store.
---

# Caching

A cache is a second copy of the truth that is allowed to be wrong. Adding one trades a
latency problem for a correctness problem, and the correctness problem arrives later, in
production, as "why is this user seeing yesterday's number".

Never add a cache before you can say, in one sentence each: what is cached, keyed by what,
for how long, and what makes it wrong.

## When this fires

A read path is slow and caching is being proposed; a cache already exists and data is stale
or leaking across users; a review touches a TTL, a memoize decorator, a Redis client, or a
CDN rule. It does not fire for a write path, or for a slow query nobody has profiled yet.

## Procedure

1. **Measure the uncached path first.** Get a real number — p50 and p95, and how often it is
   called. Without it you cannot tell afterwards whether the cache helped, and you have no
   basis for the TTL. A cache added on a hunch is a guess with extra failure modes.
2. **Try to make the cache unnecessary.** A missing index, an N+1, a payload fetching columns
   nobody reads, or a call made in a loop are all cheaper to fix than to cache, and the fix has
   no staleness. Only cache what is genuinely expensive *and* genuinely re-read.
3. **Classify the data by staleness tolerance**, and let that pick the TTL — not the other way
   round. Ask the person who owns the data, in seconds: how long may this be wrong? Pricing,
   permissions, balances and anything a user just edited usually answer "not at all", which
   means either no cache or write-through invalidation, never a hopeful TTL.
4. **Pick the layer deliberately.** Each one fails differently — see below. Caching the same
   value at three layers means three different answers and three invalidation paths.
5. **Design the key before the read.** The key must contain every input that changes the value:
   identity or tenant, authorization scope, locale, feature flags, API version, and the query
   parameters that matter. A key missing the tenant is a cross-tenant data leak, and it will
   look exactly like a cache working well. Never key on a mutable object's memory identity.
6. **Write the invalidation path in the same change as the read path.** Decide which of these
   you are using and say so: TTL expiry only; explicit delete or overwrite on every write;
   or versioned keys (put a version or updated-at in the key so a change makes old entries
   unreachable and eviction cleans them up). Versioned keys are the least fragile — nothing to
   purge, no fan-out — and are the default worth reaching for.
7. **Decide what happens when the cache is unavailable.** A cache whose outage takes the app
   down is not a cache, it is an undeclared database. The read path should fall through to the
   source on error and timeout, with a short timeout, and the fallback must be load the source
   can actually survive.
8. **Handle the stampede.** When a hot key expires under load, every concurrent request misses
   at once and hits the source together. Mitigate with a single-flight lock per key, a jittered
   TTL so keys do not expire in lockstep, or serving stale while one worker refreshes.
9. **Decide about negative results.** Caching "not found" stops a hammering miss, but it also
   caches a race: a row created right after the negative entry stays invisible for the TTL.
   Cache negatives for seconds, not minutes, and invalidate them on create.
10. **Make it observable.** Emit hit rate, miss rate, and error/fallback count per cache. A hit
    rate you cannot see is a cache you cannot reason about, and a hit rate near zero means you
    have added a network hop and nothing else.
11. **Re-measure, then prove invalidation.** Write a value, read it back through the cached
    path, and confirm the new value appears. This is the step that is skipped and the one that
    catches real bugs — a fast wrong answer is worse than the slow right one.

## The layers and how each one fails

- **Browser / HTTP response cache.** Cannot be invalidated, only expired — anything cached here
  is out of your hands until the TTL passes. Never cache a personalized or authorized response
  in a shared cache; get the public/private distinction wrong and one user's page is served to
  another. Version the URL when you need a hard cut.
- **CDN / edge.** Same exposure, plus: purges are eventually consistent across locations, and
  keying is by URL unless you declare which request headers vary the response. A missing vary
  declaration is the classic cross-user leak. Purging production edge cache is an outward-facing
  action — say what will be purged and ask before doing it.
- **In-process (LRU, memoize, module-level dict).** Cheapest and most local. But each instance
  holds its own truth, so N replicas give N answers and invalidation does not fan out; entries
  live in the heap and an unbounded one is a memory leak; it empties on deploy, which is why
  bugs here vanish when you restart and come back an hour later. Fine for immutable or
  derived-from-input data, dangerous for anything a user can edit.
- **Shared cache (Redis, memcached).** One truth for all instances and invalidation that fans
  out, at the cost of a network hop and a new dependency you must be able to lose. Under memory
  pressure it evicts — including keys you assumed were there — so nothing may be stored only in
  the cache. Flushing a shared production cache is destructive: it can stampede the database.
  Stop and ask before any flush; prefer deleting the specific keys.
- **Database-side (materialized view, summary table).** Consistent with the source at refresh
  time and queryable, but stale between refreshes and the refresh itself costs and may lock.
  Know what a refresh does to concurrent readers before scheduling one.
- **Write-through denormalized column.** Fastest read of all; the correctness burden moves onto
  every writer. One write path that forgets to update it — a migration, a backfill, an admin
  script, a second service — leaves the value permanently wrong with no TTL to heal it. Only
  take this on with a reconciliation job that can detect and repair drift.

## Checklist

- [ ] Uncached cost measured, not assumed
- [ ] Cheaper non-cache fix considered and ruled out in one line
- [ ] Staleness tolerance stated in seconds by someone who owns the data
- [ ] Layer chosen, with its failure mode named
- [ ] Key contains tenant/identity, authorization scope, and every varying input
- [ ] Invalidation strategy written in the same change as the read
- [ ] Behaviour on cache outage and on stampede is defined
- [ ] Hit rate and fallback count are emitted
- [ ] Write-then-read-back actually executed and observed

## Failure handling

- **Stale data reported in production** — do not raise the TTL question first. Find which layer
  is serving it: check the source, then each cache in front of it, and find where the answers
  diverge. The layer that diverges is the one with the broken invalidation.
- **One user seeing another user's data** — treat as a security incident, not a cache bug. Stop,
  report it, and check the key and any vary declaration before anything else.
- **Hit rate near zero** — the key varies more than the data does. Usually a timestamp, a
  request id, or a serialized object with unstable ordering is in the key. Remove the cache
  until the key is fixed; it is currently pure overhead.
- **It got faster but you cannot say by how much** — you skipped step 1. Say so rather than
  reporting an improvement you did not measure.
- **Cannot reproduce staleness locally** — expected, and not evidence it is fixed. Single-instance
  local runs hide per-instance cache divergence entirely. Say it is unreproduced locally.

## Evidence to report

Before and after numbers from the same measurement, with the method named. The cache key format
written out literally. The TTL and the staleness tolerance it came from. The invalidation path,
and the result of the write-then-read-back check. Which layers now hold a copy of this value.
What is still unverified — multi-instance behaviour, cache-down fallback, and stampede under
load are the three most commonly claimed and least commonly tested.
