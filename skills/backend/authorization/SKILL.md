---
name: authorization
description: Decide what an authenticated caller may do — pick the permission model, put the check at one enforcement point close to the data, and default to deny. Use when adding roles or permissions, scoping data per tenant or per owner, building an admin-only path, reviewing an endpoint that trusts a client-supplied id, or when someone reports seeing data that is not theirs. Not for establishing identity (that is authentication), and hiding a control in the UI is never the enforcement.
---

# Authorization

Authentication says who is calling. Authorization says what that caller may do to **this** resource.
Being logged in is not a permission, and a hidden button is not a check — the request still leaves
the browser exactly the same way.

## When this fires

A rule of the form "only X may do Y to Z" is being added, changed, or doubted. Roles, admin areas,
per-owner or per-tenant data, sharing, feature gating that carries money or privacy. Also fires on
any report that a caller reached a resource they should not have.

## Procedure

1. **Write the rule as one sentence:** *who* may do *what action* to *which resource*, under *what
   condition*. If it will not fit in a sentence, either the model is wrong or there are two rules.
   Do this before opening an editor — most authorization bugs are unwritten rules.
2. **Choose the smallest model the rules need.** A handful of fixed roles → a role check. Rules
   that read the resource (owner, tenant, state, amount) → an attribute or ownership check. "A may
   see it because B shared it" → a relationship check. Do not stand up a policy engine for three
   roles; do not fake relationships with an ever-growing enum.
3. **Reuse the existing mechanism.** Grep for the project's guard, policy, `can`/`ability` helper,
   route middleware, decorator, or database row-level security. A second authorization system
   beside the first is where the gap will be.
4. **Put the check as close to the data as it can go, once.** Ownership and tenant scoping belong
   in the query itself — or in row-level security — not in a filter applied after the rows come
   back. A post-fetch filter has already loaded the row, often logged it, and will be skipped by
   the next query someone writes.
5. **Default deny.** The check allows only on an explicit match. Unknown role, absent tenant, null
   owner, a new enum value, an endpoint added next month: all deny. If a new route is permitted by
   default, the model is inverted.
6. **Enumerate every entry point to the resource, not the one in the ticket.** Routes, batch and
   bulk endpoints, GraphQL resolvers and nested fields, background jobs, webhooks, CSV export,
   admin scripts, internal service calls. The classic hole is an endpoint that takes an id list and
   checks only the first, or an "internal" service that trusts its caller.
7. **Never trust client-supplied identity or scope.** A user id, tenant id, role or permission
   arriving in a body, query string, path or header is input, not fact. Derive them from the
   authenticated principal. Accepting `?userId=` is not authorization, it is a parameter.
8. **Choose the refusal deliberately and apply it consistently.** 403 when the resource's existence
   is not itself sensitive; 404 when it is. Mixing them across neighbouring endpoints leaks exactly
   the fact the 404 was meant to hide.
9. **Mirror the rule in the UI after the server enforces it, never instead.** Hiding a control is
   usability, so users do not walk into refusals. It changes nothing an attacker can reach.
10. **Log the decision, not the payload:** principal, action, resource id, allow or deny. Denials
    are what an investigation reads; bodies are what a breach report quotes.
11. **Write the negative tests — they are the deliverable.** For each rule: the permitted caller
    succeeds, and *each* non-permitted caller is refused, including the neighbouring tenant and the
    anonymous caller. A rule tested only from the allowed side is untested.
12. **A change to an existing rule moves real people in or out.** Widening access on a live system,
    or removing a role someone currently holds, **stops and asks** first, and the report names who
    gains or loses access. Silent widening is the failure this step exists to prevent.

## Checklist

- [ ] Each rule written as a sentence before implementation
- [ ] Model chosen deliberately; no policy engine for three roles
- [ ] Existing mechanism reused, or the absence of one confirmed
- [ ] Enforcement is in the query or the closest layer to the data, not a post-fetch filter
- [ ] Deny is the default for unknown roles, missing scope, and new routes
- [ ] Every entry point to the resource enumerated, including jobs, exports and bulk endpoints
- [ ] No identity, tenant or role taken from client-controlled input
- [ ] 403 vs 404 chosen once and applied consistently
- [ ] UI mirrors the rule; it does not implement it
- [ ] Allow and deny decisions logged with principal, action and resource
- [ ] Negative tests exist per rule, including the cross-tenant caller
- [ ] Any widening of access on a live system was asked about before it shipped

## Failure handling

- **A user saw data that is not theirs** — treat it as a scoping defect, not a UI bug. Find every
  caller of the query, not only the screen in the report; the same unscoped query is usually
  reachable from three places. Fixing one leaves the others open.
- **The check is in the wrong layer and moving it is large** — say so and size it rather than
  adding a second check at the new layer. Two enforcement points that can disagree are worse than
  one in an awkward place.
- **The rules contradict each other** — do not invent a precedence. Name the conflict and the
  people or documents that can settle it, and leave the stricter behaviour in place meanwhile.
- **No way to test as another tenant or role** — that is a finding. Report the rule as implemented
  but unverified and name exactly which caller could not be exercised. Never call an access rule
  verified because you read it.

## Evidence to report

Each rule as a sentence, next to the file and function that enforces it; the model chosen and what
it excludes; the list of entry points checked, including the ones found beyond the ticket; the
negative tests and their output; who gains or loses access if the change is a rule change; and the
callers or paths that could not be exercised.
