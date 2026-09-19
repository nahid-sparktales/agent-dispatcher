---
name: ci-cd
description: Design the shape of a delivery pipeline — what each stage actually proves, what gates what, where verification belongs, and how a run reports the truth instead of a green tick. Use when a pipeline is being designed or restructured, when a release got through a passing pipeline broken, when deciding what blocks a merge or a deploy, or when a stage claims more than it ran. Not for provider-specific workflow YAML (github-actions), image authoring (docker), writing the tests themselves (test-design), or handling an outage in progress.
---

# Pipeline design

A pipeline is a chain of claims about a commit. Each stage is entitled to exactly one claim, and
almost every bad release is a stage that made a bigger one than it earned.

Keep the words apart, because the pipeline will not:

- **built** — it compiled and packaged. Nothing ran.
- **executed** — the code ran. Nobody asserted anything about what it did.
- **tested** — assertions ran against it and passed. Only the assertions that exist.
- **reviewed** — a human or an agent read it. No execution is implied.
- **deployed** — the artifact reached an environment. It may be crash-looping.
- **verified** — the deployed thing was observed doing the intended work, in that environment.

A pipeline that reports "deployed" as "verified" is the single most expensive defect in this
document.

## When this fires

A pipeline is being designed, restructured, or reviewed; something broken reached an environment
through a passing pipeline; the gate policy is in question; or a stage's reported meaning does not
match what it ran. It does not fire for one workflow file's syntax, nor during an active incident,
where restoring service outranks fixing the pipeline that let it through.

## Procedure

1. **Map the pipeline that exists before proposing one.** Triggers, stages in order, what each
   stage runs, which are required checks, who can bypass them, where the deployed artifact comes
   from, and what happens on failure. Draw it from the configuration and from recent runs, not from
   what the README says it does.
2. **Write the claim each stage is entitled to make**, in the vocabulary above, in one line each. A
   stage that cannot state its claim is either redundant or is silently trusted for something it
   does not check. This step alone finds most of the holes.
3. **Order stages by how cheaply they rule things out.** Fast, broad checks first — format, lint,
   types, unit tests — then integration, then the artifact build, then tests against a deployed
   environment. The pipeline should spend its first two minutes eliminating the most common
   failures, not compiling for twelve.
4. **Build the artifact once and promote that exact artifact.** Rebuilding per environment means the
   thing you tested is not the thing you shipped. Give it an immutable identity — a digest or an
   immutable tag, plus the commit SHA — and carry that identity through every subsequent stage and
   into the deployment record.
5. **Separate gates from signals, and mean it.** A gate blocks; a signal informs. Anything advisory
   must be genuinely non-blocking, and anything blocking must be worth blocking for. A gate that is
   routinely overridden has already stopped being a gate — either enforce it or demote it, but do
   not leave it as theatre.
6. **Put verification after the thing it verifies, against the running system.** Post-deploy checks
   hit the deployed environment, assert the revision identity they expect, and exercise at least one
   real path through the application. A 200 from a health endpoint proves a process is listening —
   it is not evidence that the new code is the code answering.
7. **Design rollback with the deploy, not after it.** Name the rollback action, how long it takes,
   and who runs it. It is only credible if it has been executed, so record when it was last
   exercised. A schema or data migration that cannot be reversed makes rollback a lie: sequence it
   expand-then-contract so the previous version keeps working against the new schema.
8. **Keep environments and their credentials separate.** Each environment holds its own secrets, and
   a stage gets only the credentials for the environment it acts on. A pipeline where every stage
   can reach production is a pipeline where every stage is a production risk, including the one that
   runs contributed test code.
9. **Require explicit authorization for consequential steps.** Production deploys, publishing
   packages, destroying infrastructure, and data migrations belong behind a human approval. An agent
   prepares these and stops: proposing automatic deploy on merge changes who can ship, so say that
   consequence out loud and get confirmation before making it so.
10. **Make skipped and cached work legible.** Conditional stages that skip must not aggregate into a
    green summary as though they ran, and a stage restored from cache must say so. Check the failure
    path deliberately: introduce a failure on a branch and confirm the pipeline goes red at the
    right stage, with a message naming what failed.
11. **Handle flakes as defects with owners.** Retry-until-green converts an unreliable test into an
    unreliable pipeline and hides real intermittent bugs. Quarantine the test out of the gate, with
    a name, an owner, and a date, and report retries in the run rather than absorbing them.
12. **Measure the things that decide whether it is trusted**: time to feedback on a change, how
    often the main branch is red, and how often the gate is bypassed. A slow or noisy pipeline is
    routed around, and a routed-around pipeline verifies nothing regardless of how well it is
    designed.
13. **Change the pipeline the way you change production code.** On a branch, with a full run
    observed end to end, including at least one deliberate failure. Then merge.

## Checklist

- [ ] Existing pipeline mapped from configuration and real runs
- [ ] Every stage has a one-line claim in the built/executed/tested/reviewed/deployed/verified vocabulary
- [ ] One artifact build, with an immutable identity carried to deployment
- [ ] Gates and signals distinguished; every gate is one someone would actually stop for
- [ ] Post-deploy verification asserts the deployed revision and one real path
- [ ] Rollback named, time-bounded, and last-exercised date recorded
- [ ] Credentials scoped per environment
- [ ] Consequential steps require explicit approval; nothing irreversible runs unattended
- [ ] Skipped and cached stages are visible in the summary
- [ ] Failure path exercised — the pipeline observed going red for the right reason

## Failure handling

- **A broken release passed a green pipeline.** Do not add a stage yet. Find which stage should have
  caught it and what it actually ran; usually the check exists but asserts something weaker than
  assumed, or ran against a different artifact. Fix the claim before adding coverage.
- **The pipeline is red and nobody knows why.** Distinguish infrastructure failure, flake, and a
  real regression before any retry. Re-running first destroys the evidence and teaches the team that
  red means "try again".
- **A stage cannot run here** — no environment, no credentials, no runner. That stage is unrun.
  Report which claim in the chain is now missing, and do not let the stages that did run stand in
  for it.
- **Deploy succeeded but the service is unhealthy.** Deployed is not verified. Roll back or stop
  the rollout first, then diagnose; do not push a fix forward through a pipeline whose verification
  you have just seen fail to catch this.
- **Asked to disable or bypass a gate to get something out.** That is a decision with an owner, not
  a pipeline edit. Say what the gate was protecting against and what is lost by skipping it, and let
  the human decide and record it.

## Evidence to report

The stage list with each stage's claim, and which stages actually ran in the run you are reporting
on. The artifact identity — digest and commit — as it appeared at build and as observed in the
target environment. The post-deploy check that ran and what it asserted. The result of the
deliberate failure test. Timings per stage. And an explicit list of claims not made: which
environments, paths, and failure modes this pipeline does not cover.
