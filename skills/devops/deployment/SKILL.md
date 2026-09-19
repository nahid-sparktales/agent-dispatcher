---
name: deployment
description: Prepare and run a release you can explain and undo — exact artifact identity, environment parity, config and secrets, a rollout strategy matched to blast radius, and a preflight that names the abort condition in advance. Use when planning or performing a deploy, building a release path, or when someone says "ship it" and the steps are not written down anywhere. Not for proving the deployed thing is healthy (release-verification) or for getting back out (rollback), and it never treats a green build or an approved plan as permission to deploy.
---

# Deployment

A release has two halves that get conflated constantly: preparing it, which you can do freely, and
executing it, which is an outward-facing action against a system other people depend on. This skill
covers both and keeps the line between them visible.

## When this fires

A change is heading for an environment other people use, or the path that takes it there is being
built or changed. It does not fire for running something locally, and it does not fire while an
incident is in progress — restoring service outranks release process.

## Procedure

1. **Name the artifact exactly.** A commit SHA, an image digest, a build number — something that
   resolves to one immutable thing. "main", "latest" and "the current branch" are not artifact
   identities; they are queries whose answer changes while you work. Everything downstream, from
   the rollback target to the verification, depends on this being pinned.

2. **Read the delivery path that already exists** before designing one. CI config, deploy scripts,
   the platform's own project settings, and however the last release actually went out. Most
   "we need a deploy pipeline" tasks are really "the existing one has one gap."

3. **Write down how the target environment differs from where you tested.** Data volume and shape,
   scale and replica count, feature-flag values, external dependencies and their credentials,
   network egress, region. Parity is never total — the value is in naming the deltas, because
   every deploy surprise lives in one of them.

4. **Reconcile configuration and secrets against the target.** Every config key the new revision
   reads must already exist in that environment, with a value that is valid there. A missing
   variable typically fails at boot, which is after traffic has been pointed at it. Secrets stay
   references — never inline in a manifest, a log line, a commit, or your report. If a secret needs
   to be created or rotated, that is the user's action, not yours; say which one is missing.

5. **Order the steps that cannot be reordered.** Schema before code, and backward-compatible in
   both directions so old and new run side by side during the rollout; feature flag off before the
   code that reads it ships; a consumer that understands a new message shape before the producer
   emits it. Expand, migrate, contract — in separate releases. See `migrations` for the schema half.

6. **Pick the rollout strategy the blast radius justifies**, and know what each one costs:
   - *Replace in place* — simplest, has a real gap of downtime, fine for internal or low-traffic.
   - *Rolling* — no downtime, but old and new serve simultaneously, so both must tolerate the same
     schema, the same cache entries and the same in-flight jobs.
   - *Blue-green* — a whole second environment, instant cutover, instant switch back; costs double
     capacity and needs shared state to work for both sides.
   - *Canary* — a fraction of traffic first, judged on real signals; only meaningful if you have
     per-revision telemetry to judge it with, and a stated threshold decided before you look.

7. **Write the preflight and the abort condition together.** Preflight: build and tests green on
   *this* artifact, migrations applied and verified, config present, dependencies reachable, the
   rollback target named and still deployable. Abort condition: the specific signal and threshold
   that stops the rollout mid-flight. Decide it now — the moment to define "bad enough to stop" is
   never while watching it happen.

8. **Rehearse in a non-production environment** whose differences from production you listed in
   step 3. A staging deploy proves the mechanism, not the outcome; it does not transfer to
   production, and saying so is part of the report.

9. **Stop at the line.** Preparing is complete; executing is a separate, authorized act. Present:
   the artifact id, the target environment, the strategy, the steps that cannot be undone, the
   rollback path and its rehearsed duration, and anything you could not check. Then ask, in the
   same message, for explicit approval to run it. Production deploys, package publication, DNS
   changes and infrastructure destruction each need their own yes — an earlier "ship it" does not
   cover a step the user has not seen. If approval does not come, the deliverable is a prepared
   release, and it is reported with that word.

10. **Execute with the record open.** One timestamped line per command with its actual output.
    Never run a deploy step whose failure mode you have not thought about. If a step fails
    midway, stop and reconcile what actually happened before re-running anything that could create
    a duplicate release, a second resource, or a half-migrated state.

11. **Hand off to verification.** The deploy command exiting zero is the end of this skill, not the
    end of the release. Go to `release-verification` before the word "deployed" becomes "working".

## Checklist

- [ ] Artifact pinned to an immutable id, used everywhere downstream
- [ ] Existing delivery path read before anything new was written
- [ ] Environment deltas from the test environment written down
- [ ] Every config key present in the target; secrets by reference only
- [ ] Irreversible ordering handled — schema, flags, producers and consumers
- [ ] Strategy chosen against blast radius, with its cost stated
- [ ] Preflight checks and an abort threshold written before starting
- [ ] Rollback target named, and rehearsed or explicitly marked unrehearsed
- [ ] Execution approval asked for separately, per consequential action
- [ ] Timestamped record of what ran and what it returned

## Failure handling

- **A preflight check fails** — that is the result. Report it and stop. A preflight you waive is
  not a preflight.
- **The rollout fails partway** — do not retry blindly. Establish which instances are on which
  revision first; a retry over an unknown state is how you get three revisions serving at once.
- **The deploy tool reports success but you cannot confirm it** — report exactly that. "The command
  succeeded" and "the new revision is serving" are different claims, and the second belongs to
  `release-verification`.
- **You lack access to the target environment** — say so and deliver the prepared release. Do not
  route around missing access with credentials found in the repository.
- **Approval is ambiguous** — treat it as absent. Ask once, plainly, naming the exact action.

## Evidence to report

The artifact id and the environment, named together. The strategy and why that one. The preflight
results, each as its own line. What ran, when, and what it returned. Which steps are irreversible
and what the rollback path is. Then the honest verb: *prepared*, *executed*, or *executed and
handed to verification* — never "deployed" as a stand-in for "working".
