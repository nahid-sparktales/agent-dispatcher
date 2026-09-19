---
name: github-actions
description: Write and review GitHub Actions workflows that fail honestly and finish fast enough to be trusted — least-privilege permissions, untrusted pull request input, caching keyed on the right thing, matrices that mean something, and secrets that never reach a fork. Use when adding or changing a workflow file, when CI is slow, flaky, or green when it should be red, or when reviewing someone's workflow YAML. Not for provider-neutral pipeline and gate design (ci-cd), image authoring (docker), or writing the tests a workflow runs (test-design).
---

# GitHub Actions

CI has one job: tell the truth about a commit, fast enough that people wait for the answer. A
workflow that is green because a step swallowed its exit code is worse than no CI, because now the
badge is lying with authority.

The workflow file is source code with production credentials in scope, and its most common
triggers are supplied by strangers.

## When this fires

A workflow file is being added or changed, CI is slow or intermittently failing, a failure did not
turn the run red, or you are reviewing workflow YAML. It does not fire for deciding which stages a
pipeline should have at all, or for the content of the tests themselves.

## Procedure

1. **Read the existing workflows first.** Know what already runs on this event, what is already
   cached, and which checks are required on the protected branch. A second workflow on the same
   trigger doubles the minutes and halves the clarity about which run is authoritative.
2. **State the trigger and the question precisely.** Pull request validation, main-branch build,
   scheduled maintenance, and manual dispatch are different workflows with different privileges.
   Narrow with branch and path filters so unrelated commits do not queue work nobody reads.
3. **Add a concurrency group** so superseded pull request runs cancel instead of piling up — keyed
   by workflow and ref. Do not cancel in progress for deployment or release workflows: an
   interrupted deploy leaves state nobody planned for.
4. **Set permissions explicitly and minimally.** Declare read-only at the top level and raise the
   specific permission on the one job that needs it. Default token permissions vary by repository
   and organization setting, so a workflow that never mentions permissions has privileges you have
   not read.
5. **Treat pull request content as hostile input.** Forked pull requests get no secrets and a
   read-only token by design — do not engineer around that. The `pull_request_target` event runs
   with the base repository's token and secrets: never check out and never execute the pull
   request's code under it. Adding it to make a fork workflow "work" is how repositories get taken
   over.
6. **Never interpolate event data into a shell step.** A pull request title, branch name, or body
   pasted directly into a `run:` block is executed by the shell. Pass the value through the step's
   environment and reference the variable inside the script instead. This applies to any
   attacker-controlled field, not just the obvious ones.
7. **Pin third-party actions to a full commit SHA**, with the version in a trailing comment. A tag
   is mutable and points at whatever the author moves it to. First-party setup actions are the
   usual exception teams make deliberately — make it deliberately.
8. **Cache dependencies keyed on the lockfile**, with a looser restore key for partial hits. The
   language setup actions have dependency caching built in; prefer it over hand-rolling. Never
   cache anything whose staleness could let a broken commit pass: build output and test results are
   verification evidence, not cacheable input.
9. **Make the matrix express a real support surface**, not a product of every axis. Each cell costs
   a runner and a queue slot. Keep fail-fast on when the first failure is representative; turn it
   off when you genuinely need to see which cells fail. Add odd one-off combinations through the
   matrix's include list rather than a second job.
10. **Keep failure honest.** No `continue-on-error` and no `|| true` on a step whose result is the
    point of the job. Set a timeout on every job so a hang fails in minutes rather than burning an
    hour. The assertion must be the exit code — a check whose failure only appears in log text
    nobody reads is not a check.
11. **Emit evidence from the run.** Upload test reports, coverage, logs, and screenshots as
    artifacts with a condition that also runs on failure — the failing run is precisely the one
    whose artifacts you need. Write a short summary of what ran and what it proved to the step
    summary, so the answer is visible without opening raw logs.
12. **Handle secrets as references, never values.** Use repository or environment secrets and
    short-lived cloud credentials via OIDC rather than long-lived keys. Log masking is a safety net,
    not a control: a secret that has been base64'd, split, or JSON-encoded is no longer masked. Do
    not echo, do not write to an artifact, do not pass into a `pull_request_target` job.
13. **Keep it fast enough to be trusted.** Look at the actual job durations, find the long pole, and
    split or parallelize that one rather than optimizing everything. When pull request feedback
    takes longer than a coffee, people stop waiting for it and CI stops being a gate.
14. **Deployment workflows are a separate concern and a separate authorization.** Put them behind a
    protected environment with required reviewers. Proposing a workflow that ships on merge changes
    who can deploy and when: describe that consequence and get explicit confirmation before adding
    it. Do not trigger a deployment workflow to test your YAML.
15. **Run it before claiming it works.** Push the branch and read the run. A workflow file is
    written, not working, until a real run on real runners has passed and, ideally, failed for the
    right reason once.

## Checklist

- [ ] Trigger, branch and path filters match the question the workflow answers
- [ ] Concurrency group set for pull request runs, and deliberately absent for deploys
- [ ] `permissions` declared top level, raised only where needed
- [ ] No untrusted event data interpolated into any `run:` block
- [ ] Third-party actions pinned to commit SHAs
- [ ] Cache key derives from the lockfile; no verification output is cached
- [ ] Every job has a timeout; no step masks its own failure
- [ ] Artifacts uploaded on failure, not only on success
- [ ] Secrets referenced only; nothing echoed, nothing crossing a fork boundary
- [ ] Workflow observed passing in a real run, with durations recorded

## Failure handling

- **The run is green but the thing is broken.** Look for a step that continued on error, a command
  piped into something that resets the exit status, a job skipped by an `if:` condition that reads
  as success, or a required check that does not exist under the name the branch rule expects. A
  skipped job is not a passed job — confirm from the run which jobs actually executed.
- **Fails in CI, passes locally.** Compare the environments before touching the test: runner OS and
  version, tool version resolved by the setup action, a cached dependency tree from an earlier
  lockfile, absent env vars, and the clean checkout having no untracked files you rely on.
- **Intermittent failures.** Do not paper over them with a retry. Capture the failing run's
  artifacts and logs, name the flake, and quarantine it with an owner and a date. A retried test
  reported as a pass is a false statement about the commit.
- **A fork's pull request cannot run the full suite.** That is the design, not a bug. Run what the
  read-only token allows, and say clearly which checks could not run on that pull request.
- **No repository access to push and observe a run.** Say the workflow is unrun. Reviewing YAML is
  review, not verification, and the two must not be reported as the same thing.

## Evidence to report

The run URL or id, and its conclusion. Which jobs ran, which were skipped, and why. Wall-clock
duration per job before and after any change you made for speed. Cache hit or miss for the
dependency step. The artifacts produced, by name. For a review with no run: the specific lines you
changed or flagged, and an explicit statement that the workflow has not been executed.
