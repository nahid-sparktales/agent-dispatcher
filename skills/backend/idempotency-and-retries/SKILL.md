---
name: idempotency-and-retries
description: Make an operation safe to repeat — idempotency keys and their storage, what a replay returns, retry policy with backoff and jitter, and how to reconcile after a timeout whose outcome is unknown. Use when an operation has an external side effect (a charge, an email, a provisioning call), when a caller needs to retry safely, or when duplicates have already appeared in production. Not for webhook receipt mechanics, not for database transaction design, and not for choosing a queue.
---

# Idempotency and retries

A timeout is not a failure. It is an unknown outcome, and the reflex to "just retry" is how one
charge becomes two. Everything here exists to turn an unknown into something you can either repeat
harmlessly or look up.

## When this fires

Any operation with a side effect that is not naturally repeatable — money, messages, provisioning,
counters, external API calls — or any time duplicate effects have been observed. It does not fire
for a pure read, or for a write that is already a full replacement of a value with a value.

## Procedure

1. **Classify the operation first.** Naturally idempotent (set field to X, PUT a whole resource),
   repeat-unsafe (charge, send, increment, append), or read-only. Only the repeat-unsafe class needs
   the machinery below; adding it elsewhere is cost with no benefit.
2. **The key comes from the client and survives the retry.** Generated once per logical intent,
   reused unchanged on every attempt of that intent, and different for a genuinely new intent. A key
   the server generates per request is not an idempotency key. Scope it — per account and per
   endpoint — so one tenant's key cannot collide with or read another's result.
3. **Persist the key before doing the work, and let a unique constraint arbitrate.** Insert the key
   row first; a duplicate insert failing is the success path of deduplication. A read-then-write
   check is a race that will lose under exactly the concurrency that retries create.
4. **Bind the key to the request.** Store a fingerprint of the meaningful request body. Same key with
   a different body is a client bug: reject it explicitly rather than replaying an answer to a
   question that was not asked.
5. **Define what a replay returns.** The stored response and the original status code, so the caller
   cannot distinguish the first success from the second. Record the response at the moment the
   effect is committed — ideally in the same transaction as the effect, so there is no window where
   the work happened and the record did not.
6. **Handle the concurrent duplicate explicitly.** A second attempt arriving while the first is
   still in flight must not proceed: either it waits for the first to settle and returns its result,
   or it returns a "in progress, retry" status. Silently doing the work twice is the failure this
   whole skill exists to prevent.
7. **Pass the key downstream.** When the real side effect lives in someone else's system, their
   idempotency mechanism is the one that matters — send your key (or a stable client reference) with
   the call. Your key only protects your side of the boundary.
8. **State the retention window.** Keys must outlive any retry a client could plausibly make. Say
   what happens to a retry that arrives after expiry, because "the key is gone so we do it again" is
   a duplicate with extra steps.
9. **Retry only what is safe to retry.** Keyed or naturally idempotent operations, on connection
   errors, timeouts, 429 and 5xx — never on 4xx, which will fail identically forever. Exponential
   backoff with jitter, a cap on both attempts and total elapsed time, and `Retry-After` honoured
   when the server sends one. Add a retry budget or circuit breaker: synchronized retries are how a
   slow dependency becomes an outage.
10. **Treat the uncertain result as uncertain.** On a timeout, before re-issuing anything: query the
    downstream system by the idempotency key or your client reference to find out whether the effect
    landed. Re-issuing with the same key is the safe alternative. Re-issuing without one is the
    thing that creates the duplicate.
11. **Reconcile what the request path could not settle.** A sweep over records stuck in
    started-but-unconfirmed, compared against the downstream system of record, producing a report of
    the discrepancies. Automating the *detection* is the job; a correcting write to a production
    system of record — refunding, re-sending, cancelling — is outward-facing and irreversible, so it
    stops and asks.
12. **Push idempotency to every consumer.** At-least-once delivery anywhere in the chain means every
    downstream handler must tolerate a repeat, not just the entry point.

## Checklist

- [ ] Operations classified; machinery applied only to the repeat-unsafe ones
- [ ] Key is client-generated, stable across retries, and scoped to a tenant and operation
- [ ] Uniqueness enforced by a database constraint, not by a prior read
- [ ] Request fingerprint stored; same key with a different body is rejected, not replayed
- [ ] Replay returns the original status and body
- [ ] Concurrent duplicate cannot start the work a second time
- [ ] Key forwarded to the downstream system that holds the real side effect
- [ ] Retry policy names its conditions, backoff, jitter, attempt cap and total time cap
- [ ] There is a stated path from "timed out" to "found out", not straight to "retry"
- [ ] Retention window stated, and the post-expiry behaviour is not a silent duplicate

## Failure handling

- **Duplicate unique-constraint error at insert** — that is the mechanism working. Catch it, return
  the stored result, and log it as *suppressed duplicate*, distinct from a rejected request.
- **Effect committed but the response was lost** — this is the window step 5 closes. If the record
  and the effect are not committed together, say where the window is and how large it is rather
  than claiming exactly-once.
- **Downstream offers no idempotency support** — say so plainly. The fallback is a stable client
  reference plus a lookup-before-retry and a reconciliation report; it is weaker, and calling it
  idempotent would be false.
- **Duplicates already in production** — find how they were created before adding a guard.
  Retry-without-key, a queue redelivery, and a double-submitting client need different fixes, and a
  guard on the wrong path leaves the real one open.
- **Retries make an incident worse** — that is the missing budget or breaker, not a reason to
  retry harder.

## Evidence to report

Name the key: who generates it, its scope, where it is stored, and the constraint that enforces it.
Then the proof — the same request issued twice with one effect observed, the concurrent-duplicate
case, and the mid-flight failure (interrupted between effect and response) with what the next
attempt did. Quote the test output, not the intention. State the retry policy's actual numbers, and
which of these paths were merely written, which were executed once, and which have a test that
would fail if the guard were removed. Without the repeat test, this is designed, not proven.
