---
name: background-jobs
description: Design queued and scheduled work so it survives duplicates, retries, crashes and restarts — job contract, idempotency, transactional enqueue, backoff, dead letters, leases and the ordering guarantees you actually have. Use when moving work off a request path, adding a worker or cron, or debugging a job that ran twice, never ran, ran out of order, or is stuck retrying forever. Not for in-request async concurrency, and not for stream processing topology design.
---

# Background jobs

Every queue gives you at-least-once delivery and no useful ordering. Everything else — exactly
once, in order, eventually — is something you build on top, or something you are assuming and
will be paged about. Design for the guarantee you have, not the one you want.

## When this fires

Work is being moved out of a request path; a queue, worker, scheduler or cron entry is being
added or changed; or a job misbehaved — ran twice, silently vanished, processed stale data,
or filled a dead-letter queue. It does not fire for concurrency inside a single request, and
not for designing a streaming topology.

## Procedure

1. **Check it belongs off the request path.** If the caller needs the result to respond, it is
   not a job — making it one just moves the wait somewhere the user cannot see. Enqueue work
   that is slow, retryable, and whose completion the caller can learn about later.
2. **Define the job contract.** Small, serializable payload. Prefer passing an identifier and
   re-reading current state in the worker over embedding a snapshot — with one exception: when
   the job must act on the values as they were at enqueue time, embed them and say why. Never
   enqueue a live object, a connection, or anything whose meaning depends on the sender's memory.
3. **Make the handler idempotent before anything else.** Assume every job runs at least twice,
   sometimes concurrently. Give the work a natural idempotency key, and either guard with a
   unique constraint on the effect, or check-and-claim the row before acting. "It only runs
   twice if something crashes" is a statement about how often, not whether.
4. **Enqueue transactionally.** Enqueue inside the transaction and the worker can pick up a job
   for a row that never committed; enqueue after commit and a crash in the gap loses the job
   silently. Pick one and cover the gap: write the job to an outbox table in the same
   transaction and have a relay publish it, or enqueue after commit and add a sweep that finds
   rows whose job never ran. Say which you chose; both are acceptable, silence is not.
5. **Separate retryable from permanent failures.** A timeout, a 503 and a deadlock are worth
   retrying. A validation error, a 404 and a malformed payload are not — retrying them burns
   the queue and delays everything behind them. Fail those immediately and visibly.
6. **Set backoff, jitter and a cap.** Exponential backoff with random jitter, so a downstream
   outage does not produce a synchronized retry wave that keeps it down. Cap the attempts; an
   uncapped retry is an infinite loop with a network bill.
7. **Give poison messages somewhere to land, and someone to read it.** After the cap, move the
   job to a dead-letter queue or a failed-jobs table carrying the payload, the error and the
   attempt count. A dead-letter queue nobody monitors is a deletion with extra steps, so name
   the alert in the same change. Replaying a dead-letter queue re-executes real side effects —
   charges, emails, webhooks — so it stops and asks before replay, every time.
8. **Match the lease to the work.** Queues hand out a message with a visibility timeout or
   lease; if the handler is still running when it expires, the message is redelivered and you
   now have two workers on the same job. Set the lease above the p99 runtime, extend it by
   heartbeat for long jobs, or split the job until it fits. This is the single most common
   source of "it ran twice".
9. **State the ordering you actually have.** Across a queue: none. Within a partition or a FIFO
   group key: order holds only while concurrency is one and nothing is retried — one retry puts
   a message behind its successor. So either serialize per entity with a key and a single
   consumer, or make the updates order-independent: carry a version or timestamp and ignore
   anything older than what is already applied. Do not design around order you cannot name.
10. **For scheduled work, handle the four schedule failures.** Cron running on N instances fires
    N times — take a lock or have exactly one scheduler. Decide whether a run missed during
    downtime is skipped or caught up, because the default is skip and nobody notices. Guard
    overlap when a run outlives its interval. Pin the timezone explicitly: local-time schedules
    lose or repeat an hour at DST transitions.
11. **Emit the four numbers.** Queue depth, age of the oldest unprocessed message, failure rate,
    and attempts per job. Alert on **age**, not depth — a deep queue that is draining is fine, a
    shallow queue whose oldest message is an hour old is broken.
12. **Test the handler directly.** It is a function: call it twice with the same input and assert
    the effect happened once; make its dependency throw and assert the retry classification; feed
    it the payload that killed it in production. Enqueuing a job in a test asserts nothing about
    the handler.

## Checklist

- [ ] The caller genuinely does not need the result inline
- [ ] Payload is small, serializable, and either an id or a justified snapshot
- [ ] Handler is idempotent, with the guard named (unique constraint, claim, idempotency key)
- [ ] Enqueue is transactional, or the gap is covered by an outbox or a sweep
- [ ] Retryable vs permanent failures are distinguished in code, not by hope
- [ ] Backoff has jitter and an attempt cap
- [ ] Dead letters land somewhere and an alert names them
- [ ] Lease/visibility timeout exceeds p99 runtime, or is heartbeated
- [ ] The ordering guarantee is stated, and the design does not need more than it has
- [ ] Scheduled work: single-firing, missed-run policy, overlap guard, explicit timezone
- [ ] Queue age is monitored and alerted, not just depth
- [ ] Handler tested twice-called and failure-path tested

## Failure handling

- **Job ran twice** — look at the lease before the enqueue code. A handler that outlives its
  visibility timeout is redelivered, and no amount of enqueue-side deduplication prevents it.
  Fix idempotency first; it is the only durable fix.
- **Job never ran** — establish which it is: never enqueued, enqueued and lost, or consumed and
  failed silently. These have different fixes, and the logs distinguish them. Check the
  dead-letter queue before concluding it vanished.
- **Queue backing up** — check age of oldest and failure rate together. Rising age with a rising
  failure rate is a retry storm feeding itself, not a capacity problem; adding workers makes it
  worse. Stop the retry storm first.
- **Worker stuck on one message** — a poison message with no attempt cap. Find it, cap the
  attempts, and route it to dead letters. Purging the queue to clear it is destructive and
  discards unrelated work: stop and ask, and say how many messages would be lost.
- **Cannot reproduce locally** — expected. Single-worker local runs hide every concurrency,
  redelivery and ordering failure this skill exists for. Report it as unreproduced, not as fixed.

## Evidence to report

Distinguish plainly: the job was **created** (code written), **executed** (a worker picked it up
and the run is in the logs), **succeeded** (the effect is visible in the data), and **tested**
(the handler was called twice and the duplicate was absorbed). Report the delivery guarantee, the
idempotency key, the retry policy and cap, the lease value against measured runtime, the ordering
guarantee relied on, and where dead letters go and who is alerted. Name what was not exercised —
concurrent duplicate delivery, the enqueue crash gap, and DST behaviour are usually among them.
