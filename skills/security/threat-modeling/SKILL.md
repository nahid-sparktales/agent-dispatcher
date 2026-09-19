---
name: threat-modeling
description: Work out what is actually worth defending in this system — the trust boundaries data crosses, the assets behind them, what an attacker can already do, and the small number of threats that justify a control. Use when designing or changing a system's shape, before building auth, payments, uploads, file sharing or multi-tenancy, when adding an integration that crosses a boundary, or when asked whether a design is safe. Not for finding bugs in code that already exists (that is secure-code-review), not a compliance questionnaire, and not incident response.
---

# Threat modeling

Most threat models fail by being complete. A list of every conceivable attack tells nobody what to
build. The output that is worth having is short: a handful of threats with a capability behind
them, each attached to one control, plus the assumptions that would invalidate the whole thing.

## When this fires

A system's shape is being decided or changed — a new service, a new integration, a new class of
data, a new kind of user. Also when someone asks "is this secure?" about a design rather than
about code. It does not fire for an internal refactor that moves no data across a boundary.

## Procedure

1. **Draw what exists, from the repository.** Routes, jobs, queues, stores, third-party calls,
   clients. Follow the data, not the org chart. If the architecture doc disagrees with the code,
   the code is the system. Anything you cannot find, ask about rather than assume.
2. **Mark the trust boundaries.** A boundary is any place data moves between different levels of
   trust: browser to server, service to service, one tenant to another, user content to a renderer,
   your code to a vendor API, CI to production, admin tooling to live data. Boundaries are where
   controls have to live; a flow that crosses none needs no model.
3. **Name the assets concretely, most attractive first.** Credentials and tokens, then personal
   data, then money and entitlements, then the integrity and availability of records. Write the
   actual table, bucket, queue or environment variable. "User data" names nothing and defends
   nothing.
4. **Name attacker capability, not attacker identity.** What can this adversary already do:
   an unauthenticated internet caller, a signed-up customer, a neighbouring tenant, someone holding
   a stolen session, a compromised dependency in the build, an employee with read access to the
   database. A threat with no capability behind it is fiction and will crowd out real work.
5. **Walk each boundary once against the recurring failure classes** — spoofing identity, tampering
   with data in transit or at rest, actions that cannot be attributed afterwards, disclosure to the
   wrong party, exhaustion of a shared resource, and gaining privilege you were not granted. One
   pass per boundary, not per box, or the list explodes.
6. **Write each threat as one sentence:** *this capability* can *do this* to *this asset* because
   *this control is missing or weak*. If it will not fit that sentence, it is a worry, not a threat.
   Delete it or find the missing half.
7. **Rank by consequence and reachability, not by ingenuity.** A dull unauthenticated read of the
   whole customer table outranks an elegant chain requiring three prior compromises.
8. **Cut hard, and write down what you are accepting.** Most models should end with a few threats
   worth building against. An accepted risk recorded with its reason is a decision; an unlisted one
   is an oversight nobody can find later.
9. **Attach each surviving threat to exactly one control, at one place.** Name the layer and, where
   it exists, the file or component. Two controls that can disagree are worse than one in an
   awkward spot. Say what the control does not cover.
10. **Record the assumptions holding the model up** — that this queue is written only by us, that
    this bucket is private, that this network is not reachable, that this vendor validates its
    input. Each assumption is something to re-check, and the first thing to test when the model
    later turns out to have been wrong.
11. **Hand off residual work as findings, not as homework.** Threats that need code-level
    confirmation go to a code review; threats that need a running system go to whoever is
    authorized to test it. Modeling does not prove anything about the running system.
12. **Re-run on boundary change, not on a calendar.** A new public endpoint, a new tenancy model, a
    new integration or a new data class invalidates the map. A sprint boundary does not.

**Proving a threat is a separate, authorized act.** Scanning, probing or exploiting a live system —
even to confirm something in this model — stops and asks first, names the target, and never runs
against production on the strength of a model alone.

## Checklist

- [ ] Diagram derived from the actual code, with gaps asked about rather than assumed
- [ ] Every trust boundary marked, including service-to-service and tenant-to-tenant
- [ ] Assets named as concrete stores, ordered by what an attacker wants
- [ ] Attacker capabilities listed; every threat traces to one of them
- [ ] Each boundary walked once against the recurring failure classes
- [ ] Each threat written in the one-sentence form
- [ ] Ranked by consequence and reachability
- [ ] Accepted risks written down with their reason
- [ ] Each surviving threat attached to one control at one place
- [ ] Assumptions listed as things that can go stale
- [ ] No claim made about the running system that only a test could support

## Failure handling

- **The list will not stop growing** — the boundaries are drawn too finely, or threats are being
  written without capabilities. Go back to step 4 and drop everything with no attacker behind it.
- **Nobody can say what the data is worth** — that is a finding, not a blocker. Model on the
  strictest plausible reading, say which assumption you used, and name who can settle it.
- **The design has no boundary to defend** — say so and stop. A model produced to satisfy a process
  teaches nothing and costs the next reader real time.
- **Code contradicts the intended design** — report the gap as its own finding. Modeling the
  intended system while the deployed one differs is the most expensive way to be wrong.
- **A threat needs live evidence you are not authorized to gather** — record it as unconfirmed with
  what evidence would settle it. Never upgrade a hypothesis to a vulnerability by reasoning.

## Evidence to report

The boundary diagram or its written equivalent, with the files and routes it was derived from; the
asset list; the attacker capabilities considered; each threat in sentence form with its rank; what
was explicitly accepted and why; each control with its single location; the assumptions; and what
remains unconfirmed and what would confirm it. A model with no accepted risks and no unknowns has
not been finished, it has been formatted.
