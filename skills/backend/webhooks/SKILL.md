---
name: webhooks
description: Receive or send HTTP webhooks correctly — signature verification on the raw body, fast acknowledgement, deduplication, out-of-order handling, retry and dead-letter behaviour, and the delivery contract a consumer needs. Use when adding or debugging a webhook endpoint, when integrating a provider's events, or when your own service has to notify others of changes. Not for internal queue or event-bus messages that never cross an HTTP boundary, and not for general outbound API retry policy.
---

# Webhooks

A webhook is an untrusted HTTP request that claims to be an event. Almost every webhook bug is one
of four things: the signature was checked against a re-serialized body, the handler did its work
before acknowledging, the same event arrived twice, or events arrived out of order.

## When this fires

Building or reviewing a webhook receiver, integrating a provider's events, or designing outbound
event delivery to consumers. It does not fire for an internal queue consumer — that has no HTTP
trust boundary, though its idempotency requirements are the same.

## Procedure — receiving

1. **Verify before you parse.** Compute the signature over the **raw request body exactly as
   received**, before any JSON decode or middleware re-serialization, and compare in constant time.
   Check the signed timestamp against a tolerance window so an old capture cannot be replayed. A
   request that fails verification gets a 4xx and nothing else — no logging of the payload as if it
   were real, no side effects. Never identify the sender by a field inside the payload.
2. **Confirm the secret's source.** Per-endpoint secret from configuration, never committed, and
   the verification path must fail closed when the secret is missing rather than skipping the check.
3. **Acknowledge fast, work later.** Persist the raw body and headers, return 2xx, and process
   asynchronously. A handler that does its work inline will eventually exceed the sender's timeout,
   the sender will retry, and you will get duplicates on top of the original that actually
   succeeded.
4. **Deduplicate on the provider's event id.** A persisted record with a unique constraint is the
   arbiter; a read-then-write check is a race, not a guard. At-least-once delivery is the norm — a
   second delivery of an event you already applied must be a no-op that still returns 2xx.
5. **Do not trust arrival order.** Order by the event's own sequence number, version, or emitted
   timestamp, and ignore an event whose version is older than the state you already hold. Where the
   payload is thin or ordering matters more than latency, treat the event as a signal and fetch
   current state from the provider's API instead of applying the payload.
6. **Make the effect idempotent**, not just the dispatch — see `idempotency-and-retries`. Dedupe
   keeps you from processing twice; idempotent effects keep you correct when it happens anyway.
7. **Use status codes to mean what the sender thinks they mean.** 2xx: delivered, stop retrying.
   4xx: permanent — the sender will not retry and may disable the endpoint, so return it only for
   events you will never be able to process. 5xx: retry me. Never return 2xx to silence a failure
   you have not recorded, and never return 5xx for a malformed event that will fail identically
   forever.
8. **Dead-letter after the retry budget**, keeping the raw body, headers, receipt time and failure
   reason. Provide a deliberate replay path. Replaying events into a production system is an
   outward-facing action with real side effects: stop and ask before running one.
9. **Log without secrets.** Event id, type, verification result, outcome. Not the signature header,
   not tokens or card data inside the payload.

## Procedure — sending

10. **Publish the contract before the first delivery.** Event types and their payload schemas, a
    stable event id, an emitted timestamp, the signature scheme and which bytes it covers, the
    delivery headers, the retry schedule, and — stated plainly — the ordering guarantee you actually
    offer, which is usually none. Promise at-least-once and tell consumers to be idempotent.
11. **Sign every delivery** with a per-endpoint secret, include the timestamp in the signed
    material, and support two active secrets so a consumer can rotate without dropping events.
12. **Retry with exponential backoff plus jitter**, a capped attempt count, and a per-endpoint
    concurrency limit so one slow consumer cannot drain your workers. Disabling a customer's
    endpoint after sustained failure is a customer-visible action — notify, and ask before doing it
    by hand.
13. **Treat the destination URL as hostile.** It is user-supplied: block private and link-local
    address ranges, resolve and check the address actually connected to, refuse redirects to
    internal hosts, set connect and read timeouts, and cap the response size you read. This is the
    SSRF surface of your whole cluster.
14. **Version payloads additively.** Adding a field is safe only if consumers were told to ignore
    unknown ones; removing or re-typing a field needs a new event type or version.

## Checklist

- [ ] Signature verified on raw bytes, constant time, with a timestamp window
- [ ] Missing or misconfigured secret fails closed
- [ ] Endpoint acknowledges before doing the work, within the sender's timeout
- [ ] Duplicate delivery of the same event id is a no-op, enforced by a unique constraint
- [ ] Out-of-order and stale events are detected by version or timestamp, not ignored
- [ ] 2xx / 4xx / 5xx each returned for the case the sender interprets them as
- [ ] Dead-letter store keeps raw body and headers, with a replay path that asks first
- [ ] Outbound: contract published, deliveries signed, backoff bounded, destination URL restricted
- [ ] Verified against a real signed delivery, or stated as only exercised with a sample payload

## Failure handling

- **Signature fails against a known-good delivery** — suspect body mutation first: a framework that
  parses and re-serializes, a proxy that rewrites encoding, trailing-newline handling. Do not
  "solve" it by weakening or skipping verification; an endpoint that accepts unsigned requests is a
  remote write primitive for anyone who learns the URL.
- **Events arrive but nothing happens** — check the async path, not the endpoint. A 2xx from a
  receiver whose queue consumer is dead looks perfect from outside.
- **Duplicate side effects in production** — this is the dedupe or idempotency gap, not the
  provider misbehaving. At-least-once means exactly what it says.
- **Cannot receive a real delivery locally** — say the handler was exercised with a constructed
  payload and that live delivery is unverified. A tunnelled or sandbox delivery is better evidence;
  a unit test with a hand-made signature is the weakest and must be labelled as such.
- **Provider's documented headers or schema are uncertain** — read their current documentation
  rather than assuming. Header names, signature formats and tolerance windows differ per provider
  and change.

## Evidence to report

The verification path and what bytes it covers. One delivery you actually observed — event id,
type, status returned, elapsed time to acknowledge. The duplicate test: the same event id delivered
twice, and proof of one effect. An out-of-order or stale event, and what the handler did with it.
For outbound work, the published contract and the retry schedule's actual numbers. And which of
these were executed against a real signed delivery versus only constructed in a test — never let
"the webhook works" stand in for either.
