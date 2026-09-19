---
name: release-verification
description: Prove a deployment is healthy rather than merely finished — the revision actually serving asked of the running system, every instance moved, smoke paths walked against the real environment, error rate and latency compared to a pre-deploy baseline. Use after any deploy to a shared environment, before a release is called good, or when checking someone else's claim that it went fine. Not for planning the rollout (deployment) or executing a revert (rollback); it never accepts a green pipeline, a 200 from a health endpoint, or a passing test suite as proof.
---

# Release verification

"The deploy finished" is a fact about a pipeline. It says nothing about which revision is serving,
whether all of it is serving, or whether the thing serving works. Those are three separate
questions and this procedure answers them in that order.

## When this fires

A deploy has completed to any shared environment and someone is about to call the release good —
your deploy or somebody else's. It fires again after every rollback, hotfix and re-run. It does not
fire for a build, and it is not a substitute for tests.

## Procedure

1. **Write down what healthy means before you look.** Which signals, what threshold, over what
   window, compared to what baseline. Deciding after seeing the numbers is how a bad release gets
   talked into being fine.

2. **Capture the pre-deploy baseline**, or declare it missing. Error rate, latency at the
   percentile that matters, throughput, saturation — from before the change. Without it you can
   report absolute numbers but you cannot say the release did not make anything worse. Say that in
   those words.

3. **Ask the running system which revision it is serving.** A version or build-info surface the
   application itself exposes, the image digest reported by the running instances, a revision
   header — something answered by the process handling traffic. The deploy tool's own success
   message is the claim under test, not evidence for it. If nothing exposes the revision, that is a
   finding worth fixing, and today's verification is weaker for it.

4. **Confirm every instance moved.** Replicas, regions, edge locations, workers. Sampling one
   response cannot distinguish a complete rollout from a half-finished one — a mixed fleet answers
   correctly most of the time. Count what is running each revision.

5. **Read health and readiness for what they actually prove.** A handler returning a static 200
   proves the process is up. It does not prove the database is reachable, the cache is warm, the
   queue is consumed or credentials in this environment are valid. Check the dependency the release
   touched directly.

6. **Walk the smoke paths against the deployed environment.** The few journeys whose failure means
   the release is bad: sign in, the primary read, one authenticated write, and any path this change
   touched. Real requests to the real deployment — not localhost, not a mock, not the test suite
   that already passed on this artifact. For a rendered surface, see `browser-verification`.

7. **Check the asynchronous surface**, which fails later and more quietly than requests: background
   jobs draining, scheduled work firing, queue depth flat rather than climbing, webhook deliveries
   succeeding, dead-letter counts unchanged. A release that broke only the consumers looks perfect
   from the front door.

8. **Compare the signals to the baseline over a stated window.** Error rate, latency, saturation
   and traffic volume, by revision where your telemetry can split it. Name the window. Two minutes
   of clean traffic at 3am is evidence about two minutes of traffic at 3am.

9. **Check what the release depended on, in the deployed environment**: migrations recorded as
   applied there (see `database-migration-verification`), feature flags at their intended values,
   caches and CDN serving the new assets rather than stale ones, third-party integrations
   authenticating with this environment's credentials.

10. **Report with the verbs kept apart** — built, deployed, serving, smoke-tested, verified, and
    *watched for how long*. This procedure exists because those get collapsed into "it's live".

## What this refuses to conclude

- **Without asking the running system:** that the intended revision is serving. A pipeline's exit
  code is not a statement about production.
- **Without counting instances:** that the rollout is complete.
- **Without a baseline:** that the release did not degrade anything.
- **Without walking the smoke paths:** that the application works — a healthy process can serve
  errors perfectly reliably.
- **Without checking jobs and queues:** anything about asynchronous work.
- **Without a stated observation window:** that it is stable. Verified at low traffic is not
  verified at peak, and the report says which one it was.
- **Against a different environment:** anything. A pass on staging is evidence about staging.

## Checklist

- [ ] Health defined — signals, thresholds, window — before looking
- [ ] Baseline captured, or its absence stated as a limit
- [ ] Serving revision read from the running system and matched to the intended artifact
- [ ] Instance / replica / region count reconciled, not sampled once
- [ ] Dependency the release touched checked directly, not via a static health handler
- [ ] Smoke paths walked against the deployed environment, including one write path
- [ ] Jobs, queues, schedules and webhooks checked
- [ ] Signals compared to baseline over a named window
- [ ] Migrations, flags, caches and integrations confirmed in this environment
- [ ] Everything unchecked listed by name

## Failure handling

- **The serving revision is not the one deployed** — stop verifying and report it. Everything after
  that point is evidence about the wrong build.
- **A signal is degraded** — capture the evidence before anything changes it: the failing request,
  the error text, the timestamp, the revision. Then hand the decision to `rollback`; this skill
  reports, it does not revert, and reverting production is itself a production change needing its
  own confirmation.
- **A smoke path fails intermittently** — report it as intermittent with what you tried. An
  intermittent failure called fixed is worse than one called intermittent.
- **Telemetry is unavailable or cannot split by revision** — say which conclusions that costs you,
  name what you did check, and do not round the result up to verified.
- **Read-only or no access to the environment** — the release is unverified. Report it that way.
  Degrading honestly beats a false pass.

## Evidence to report

The environment and the artifact id, named together. How you asked for the serving revision and
what it answered. The instance counts per revision. Each smoke path and what it actually returned,
not that it "worked". The signals, with the baseline beside them and the window stated. Queue and
job state. Then the explicit list of what was not checked and for how long it was watched. A
summary that says "verified" without these is a claim, not verification.
