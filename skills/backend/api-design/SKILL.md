---
name: api-design
description: Design or change an HTTP API — resources, verbs, status codes, one error shape, pagination, versioning, and an OpenAPI description that cannot drift from the handlers. Use when adding or reshaping endpoints, when asked what a response should return, or when reviewing whether a change to a published API breaks its consumers. Not for choosing between REST, GraphQL and RPC, not for database schema design, and not for implementing the handler's business logic.
---

# API design

The shape of an endpoint is a promise to code you do not control. Most of this skill exists to
stop a change being made casually that a consumer will experience as an outage.

## When this fires

Adding an endpoint, changing a response body, changing validation, or reviewing someone else's
API change. It does not fire for an internal function signature, or for a private endpoint with
exactly one caller in the same deployment unit — there, match the surrounding code and move on.

## Procedure

1. **Read the neighbours before designing anything.** Three or four existing endpoints: their URL
   style, error envelope, auth mechanism, pagination style, date format, casing. An endpoint that
   disagrees with the ones beside it is a defect even when it is individually better. If the
   existing API disagrees with itself, say so and pick the dominant convention — do not silently
   introduce a third.
2. **Name resources, not actions.** Plural nouns; nesting only where the child genuinely cannot
   exist without the parent. When an operation is a verb that resists this (`/orders/{id}/refunds`,
   `/jobs/{id}/cancel`), model it as a subordinate resource or a state transition rather than
   bending the noun.
3. **Pick the verb by its contract, not by convenience.** GET is safe and cacheable and never
   mutates. PUT replaces the whole resource and is idempotent. PATCH is partial — say which patch
   format. DELETE is idempotent in effect. POST is everything else and is the only one a client may
   not blindly repeat. If you want a repeatable POST, that is `idempotency-and-retries`.
4. **Choose status codes deliberately.** 201 with a `Location` for a created resource; 202 when the
   work is queued and the body says how to follow it; 204 only when there is genuinely nothing to
   return. 400 for malformed, 422 for well-formed but invalid; 401 unauthenticated vs 403
   unauthorized; 404 rather than 403 when merely confirming existence leaks information; 409 for a
   conflict with current state; 429 with `Retry-After`. Never return 5xx for a client's mistake, and
   never 200 with an error inside.
5. **Define one error shape for the whole API and reuse it.** A stable machine-readable code, a
   human-readable message, per-field detail for validation, and a correlation id. If the project has
   no precedent, `application/problem+json` is a reasonable default. Errors must not carry stack
   traces, SQL, internal hostnames or another tenant's identifiers.
6. **Pagination: cursor by default.** Opaque cursor, a stable sort key with a unique tiebreaker, a
   server-enforced maximum page size, and a documented answer for what happens when rows change
   mid-scan. Offset paging is acceptable only for small, stable, human-browsed lists. Return the
   next cursor; a total count is a separate, optional, often expensive promise.
7. **Allowlist filtering and sorting fields.** Never pass a client string into a sort or filter
   expression. An unbounded filter surface is both an injection risk and a permanent compatibility
   obligation.
8. **Decide the compatibility rule before shipping, not at the first break.** Within a version,
   additive only: new optional fields, new endpoints, new enum values *only if consumers were told
   to tolerate unknown ones*. Breaking includes removing or renaming a field, tightening validation,
   changing a default, changing an error code, narrowing a type, and changing the meaning of a value
   while keeping its name. Pick one versioning mechanism — URL path, media type, or a date header —
   and do not mix two.
9. **Write the description from the thing that serves the requests.** Generate the OpenAPI document
   from the handlers, types or schemas where the stack allows it. Where it must be hand-written, add
   a contract check that fails CI when the document and the handlers disagree, and treat drift as a
   defect rather than a documentation chore. A spec nobody can fail is decoration.
10. **Walk one real consumer sequence end to end** — authenticate, create, read back, page, hit a
    validation error, hit a 404. Write out the actual requests and responses. Most design mistakes
    surface here and nowhere earlier.
11. **Stop at the boundary.** Writing the route is *created*. Calling it once is *executed*. A
    contract or integration test is *tested*. Publishing it, deploying it, or changing an endpoint
    other teams already call is outward-facing: name the breaking changes and the consumers, and
    ask before shipping.

## Checklist

- [ ] Conventions of the existing API were read, and any deviation is deliberate and stated
- [ ] Every new endpoint has resource, verb, success status, and each error status listed
- [ ] Errors use the project's single error shape and leak nothing internal
- [ ] Collections paginate with a bounded page size and a stable order
- [ ] Filter and sort fields are an allowlist
- [ ] Each change classified as additive or breaking, with the breaking ones named
- [ ] The OpenAPI description is generated or checked against the handlers, not just edited
- [ ] One consumer sequence written out with real requests and responses
- [ ] Auth and authorization stated per endpoint, including who may read another user's row

## Failure handling

- **Cannot tell whether a change is breaking** — treat it as breaking. The cost of a needless
  version is a fraction of the cost of a silent one.
- **Spec and implementation disagree** — the implementation is what consumers have already built
  against; the spec is what they were promised. Report both, change the one that is wrong, and do
  not quietly edit the spec to match a regression.
- **No consumer is known** — that is not the same as no consumer existing. Say the blast radius is
  unknown rather than assuming it is zero.
- **The framework's behaviour is uncertain** (how it serializes, validates, or maps status codes) —
  check its current documentation or test it. Do not describe behaviour you have not confirmed.
- **Asked to design around a database table** — say so. An API that is a view of the schema will
  break every time the schema does.

## Evidence to report

The endpoint table — path, verb, success status, error statuses, auth. One real request and
response per new endpoint, including an error. The diff of the OpenAPI document and the result of
the contract check. An explicit list of breaking changes with the consumers affected, or "none, and
here is why". And the distinction kept honest: which endpoints were merely written, which were
executed, and which have a test that would fail if the contract changed.
