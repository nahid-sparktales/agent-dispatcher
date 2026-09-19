---
name: dependency-security
description: Judge dependency risk instead of reciting it — resolve the advisory to a real path through the lockfile, decide whether the vulnerable code is reachable in this codebase, and pick upgrade, override, removal or a written acceptance. Use when an audit or advisory alert fires, before adding a new dependency, when a lockfile change needs reviewing, or when someone asks whether a named CVE actually affects this project. Not for finding vulnerabilities in code you wrote, not for secret scanning, and a clean audit output is not a claim that the application is secure.
---

# Dependency security

A vulnerability scanner reports what is installed, not what is exploitable. Most of the work is
deciding which advisories are real here, and the answer is in the lockfile and the call sites,
not in the severity badge.

## When this fires

An audit tool or advisory alert produces findings; a dependency is about to be added or bumped; a
lockfile diff needs review; someone asks whether a specific CVE affects this project. It does not
fire for vulnerabilities in first-party code.

## Procedure

1. **Establish what actually ships.** Which manifests and lockfiles exist, which dependencies are
   production versus development versus build-only, and what ends up in the deployed artifact or
   image. An advisory in a test runner and one in the request path are not the same finding.
2. **Read the lockfile, not the manifest.** The manifest states a range; the lockfile states the
   version that runs. Where several lockfiles or workspaces exist, say which one you resolved —
   the answer differs per workspace.
3. **Run the ecosystem's own audit tool and keep the exact output.** Note which tool, which
   database it consulted, and when. If no audit tool exists for this ecosystem, that gap is itself
   the finding — do not report "no vulnerabilities found" when what happened is "nothing looked".
4. **Resolve each advisory to a path.** Which direct dependency pulls the vulnerable package in,
   and at what depth. A transitive finding is usually fixed in the parent's range, not the child's,
   and that changes who has to move.
5. **Decide reachability.** Read what the advisory actually says is affected — a function, a
   parser, an option, a platform — then look for it here: is that entry point imported, called, and
   fed input an attacker influences? Three verdicts only: reachable, not reachable with the reason,
   or cannot determine. Treat cannot-determine as reachable whenever the fix is cheap.
6. **Score it for this system, not in the abstract.** A published severity is a guess about an
   average deployment. What matters here: is the component internet-facing, what data does it
   touch, does exploitation need authentication or a specific configuration, and is there
   known exploitation in the wild. A high severity that is unreachable outranks nothing.
7. **Choose one of four outcomes per finding** and write down which: upgrade to a fixed version;
   constrain the transitive version through the package manager's override mechanism; remove or
   replace the dependency; or accept, with the reason, the compensating control and a date it gets
   revisited. An acceptance without a date is a forgotten finding.
8. **Apply the change through the package manager**, never by hand-editing a lockfile. Keep
   unrelated upgrades out of the same commit so the diff stays reviewable and revertible.
9. **Build and run the test suite afterwards, and report what ran.** A lockfile that resolves is
   not an application that works. Upgrading is not testing, testing is not deploying, and none of
   them is verification that the vulnerability is gone — say which of the three you actually did.
10. **Check the things a CVE database never reports** whenever a dependency is added or replaced:
    an unmaintained or single-maintainer package, a name one character from a popular one, a recent
    ownership transfer, install-time scripts, and a transitive footprint out of proportion to what
    it does. This check belongs before adoption; afterwards it is archaeology.
11. **Keep lockfile discipline enforceable.** Lockfile committed, CI installing from it rather than
    re-resolving, no floating tags in production builds, and lockfile diffs reviewed like code. An
    unexplained resolution change in a diff nobody reads is exactly what a compromised package
    looks like.
12. **Stop at the deploy.** Shipping the upgrade is a separate, owner-approved decision, and so is
    publishing an advisory or filing anything public about a third-party package.

## Checklist

- [ ] Production, development and build-only dependencies separated
- [ ] Versions resolved from the lockfile, with the workspace named
- [ ] Audit tool named, output kept, database and date recorded
- [ ] Every advisory resolved to the direct dependency that pulls it in
- [ ] Reachability verdict recorded per finding, with the call site or the reason it is unknown
- [ ] Exposure judged for this deployment, not from the severity label alone
- [ ] One of upgrade / override / remove / accept-with-date chosen per finding
- [ ] Lockfile changed through the package manager only
- [ ] Build and tests run after the change, with their output reported
- [ ] New dependencies checked for maintenance, ownership and install scripts before adoption

## Failure handling

- **No fixed version exists upstream** — mitigate rather than wait: disable the affected option,
  remove the feature, constrain input ahead of it, or replace the package. Record the mitigation
  and what it does not cover.
- **The fix needs a major-version bump** — that is a migration, not a patch. Scope it as one, say
  what the exposure is meanwhile, and do not smuggle breaking changes in under a security label.
- **The audit tool reports nothing** — check that it ran against the right lockfile and had a
  database to consult. Silence and a clean result look identical in a log.
- **A transitive override resolves the alert but the parent still bundles its own copy** — verify
  by re-resolving and inspecting the installed tree, not by re-running the tool that first
  reported it.
- **The finding is in a dependency of the build, not of the product** — still real, different blast
  radius: it runs in CI with CI's credentials. Say which of the two you are talking about.

## Evidence to report

The audit command and its exact output. Per finding: the advisory id, the resolved version, the
dependency path to a direct dependency, the reachability verdict with the file and line or the
reason it is undetermined, the exposure judgement, and the decision with its owner and date. Then
the lockfile diff, the build and test output after the change, and the findings deliberately left
open with the reason. "Ran the audit, all clear" is not a report.
