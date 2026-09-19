---
name: secure-code-review
description: Review a change or a codebase for security defects with a deliberate reading order — where bugs cluster, trace source to sink, confirm reachability, and write a finding someone can actually fix. Use when asked to security-review a pull request, feature or repository, or before shipping anything touching auth, money, tenancy, uploads or secrets. Not a scanner run (its output is leads), not design-stage threat modeling, and not a penetration test — nothing here authorizes touching a running system.
---

# Secure code review

A reviewer who reads files in the order the diff lists them finds what a linter finds. The value is
in reading in the order defects cluster, following untrusted input to where it does damage, and
writing findings precise enough that a fix lands in the right place.

## When this fires

A change is about to ship and it touches authentication, authorization, money, personal data,
tenancy, uploads, deserialization, URLs or secrets; or a repository needs a security pass. Also on
a report that someone reached something they should not have.

## Procedure

1. **Fix the scope and the ground rules in writing.** What is in scope, what the code is supposed
   to do, and — explicitly — that this is a reading exercise. Running the application, sending
   payloads, scanning a host or touching production is a separate, authorized act: propose it and
   **stop and ask**, naming the target and the environment.
2. **Get the ground truth.** For a change: the actual diff, plus the callers of anything it
   changed — a guard removed in one file is a defect in every file that relied on it. For a
   repository: the route table, the entry points, and the dependency manifest.
3. **Read in the order defects cluster, not in file order.** New or changed entry points; anything
   touching identity or permissions; anything building a query, command, path, URL or template;
   anything handling money, credentials, personal data or tenant scope; configuration and
   middleware (ordering, CORS, cookie flags, content security policy, dependency bumps); and last,
   everything labelled temporary, commented out, or added late under pressure.
4. **Trace each candidate both directions.** Backwards to an untrusted source, forwards to the
   dangerous sink, and check what the path in between actually enforces. A finding is a source, a
   sink, and a path. Without the path it is a hardening suggestion — still worth saying, but say
   which it is. Use the `owasp-web` skill for the class-by-class patterns.
5. **Check the cases the author did not write a test for.** The other tenant, the anonymous caller,
   the expired or replayed token, the second identical request, the bulk endpoint, the id belonging
   to a different scope, the empty and the enormous input.
6. **Ask what changed about the rules, not only about the lines.** A relaxed database constraint, a
   middleware registered earlier or later, a default that flipped, a dependency major version, a
   feature flag now on by default. These are invisible in a diff read line by line and they move
   the security properties of code nobody touched.
7. **Do not turn into a scanner.** A tool hit you cannot connect to a reachable path is a lead to
   triage, not a finding to report. Noise trains the reader to skim the one finding that mattered.
8. **Say exactly what you did, per finding.** Read, executed, tested, reproduced — these are
   different claims. "Reachable by inspection" is honest; "exploitable" requires having run it, in
   an environment you were authorized to run it in, and you name that environment.
9. **Group by root cause, not by occurrence.** One unscoped shared query reachable from four
   handlers is one finding with four locations and one fix — at the choke point every caller goes
   through. Four findings invite four local patches and leave the fifth caller open.
10. **Write each finding so it can be fixed without you**: file and line, the untrusted input, the
    path to the sink, the concrete consequence to a named asset, the smallest correct fix, and your
    confidence with what evidence would settle it.
11. **Rank by consequence and reachability.** Unauthenticated, no preconditions, hits credentials
    or the whole dataset, at the top. A category name is not a severity: not every injection
    outranks every access-control gap, and usually the reverse.
12. **Report coverage and blind spots in the same document.** What was read, what was skipped, what
    could not be assessed and why. A review with no stated limits reads as a clean bill of health
    it did not earn.
13. **Fixing and disclosing are separate decisions.** Proposing a patch is part of the review;
    committing it, pushing it, or writing an unfixed vulnerability into a public issue or PR
    comment is outward-facing — **stop and ask** before any of those.

## Checklist

- [ ] Scope agreed, and no running system touched without an explicit ask
- [ ] Diff read together with the callers of everything it changed
- [ ] Clustered reading order followed, config and middleware included
- [ ] Each candidate traced source → path → sink; hardening labelled separately
- [ ] Negative cases considered: other tenant, anonymous, replay, bulk, expired
- [ ] Rule changes (constraints, defaults, ordering, dependency majors) examined
- [ ] Tool output triaged for reachability, not pasted
- [ ] Read / executed / tested / reproduced distinguished in every claim
- [ ] Findings grouped by root cause, with the fix at the shared choke point
- [ ] Severity argued from consequence and reachability
- [ ] Coverage and blind spots stated
- [ ] Nothing committed, pushed or published without asking

## Failure handling

- **You cannot tell whether input is trusted** — say so and name what would settle it (the caller,
  the middleware, the schema). An assumed-safe input is how the interesting bugs survive review.
- **The path runs through code you cannot follow** — dynamic dispatch, generated code, a vendored
  binary — report the trace as far as it goes and mark it unresolved. Unresolved is not safe.
- **The fix is architectural and large** — size it and say so rather than proposing a local patch
  that adds a second enforcement point. Two checks that can disagree are worse than one badly
  placed.
- **You find something serious in unrelated code** — report it; do not quietly widen the change.
  Scope is about what you touch, not about what you are allowed to notice.
- **Nothing was found** — say what was read and what was not. "No findings in the six handlers and
  the auth middleware; the queue consumers and the infrastructure config were not reviewed" is a
  result. "Looks fine" is not.
- **The change is already merged or deployed** — that changes urgency and sequencing, not the
  review. Report first, and let the people who own the system decide on rollback or a fix forward.

## Evidence to report

The scope and what was read, by file or area; per finding, the location, the source-to-sink trace,
the consequence, the fix and the confidence; the severity ranking with its reasoning; tool output
with its triage; the explicit list of what was not reviewed and what could not be assessed; and, for
anything you ran, exactly what you ran and against which environment.
