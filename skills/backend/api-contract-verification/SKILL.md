---
name: api-contract-verification
description: Prove an API integration actually works by executing it — success path, documented failure paths, auth failure — and leave behind a contract test that catches the next break. Use before reporting any endpoint, client or third-party integration as working, when asked whether an integration is verified, or when checking someone else's integration work. Not for load or performance testing, not for rendered UI verification, and not a substitute for reading the provider's own documentation.
---

# API contract verification

Code that compiles against an API is not an integration. A client that type-checks, matches the
docs and reads correctly in the diff can still 404, send the wrong content type, retry a 401
forever, or pass every test against a stub nobody replaced.

Keep the verbs apart, because this procedure exists to stop them merging: **created** is the code
written; **executed** is a request actually sent and a response actually read; **tested** is a
check that will run again without you; **reviewed** is a human or agent reading it; **deployed** is
running somewhere real; **verified** is the conclusion, and it is available only after execution.

## When this fires

Before any endpoint, API client or third-party integration is reported as working — your own or
someone else's — and whenever a claim of "the integration works" needs backing.

## Procedure

1. **Write the contract down before calling anything:** environment and base URL, method and path,
   auth scheme, request shape, the success status and the fields you depend on, and the documented
   failure statuses. Take it from the provider's specification or current documentation, not from
   memory. If you cannot write it, you do not yet know what you are verifying.
2. **Choose the environment deliberately and name it.** Local stub, sandbox, staging. A call
   against production can charge money, send mail or mutate records — that is an outward-facing
   action: **stop and ask** before executing one, and prefer a disposable record over real data.
   The same applies to any write verb, even in staging, when the data is shared.
3. **Execute the success path.** Capture the request line, the status, the headers that matter
   (content type, rate limit, pagination), and the body or the fields you assert on. A 200 with an
   error object inside it is a failure — read the body, never the status alone.
4. **Assert on the parsed value your code uses**, not on the transport. "It returned 200" proves
   reachability. The contract is proven when the deserialized field arrives with the type, units
   and shape the calling code expects.
5. **Execute the documented failure paths:** invalid input, a resource that does not exist, and at
   least one transport-level failure — timeout, connection refused, or a 5xx — forced by pointing
   the client at an unroutable or stubbed endpoint. What is being verified is your side: does it
   retry, surface a typed error, or take the whole request down.
6. **Execute the auth failure path separately:** no credential, then an invalid or expired one.
   Confirm the status is a refusal, that the client does not loop retrying it, and that the
   credential appears in no log line or error message. An integration exercised only with a valid
   key has not been verified.
7. **Exercise the boring cases that break in production:** the second page of a paginated result,
   an empty result set, a legitimately null field, a date or amount where timezone or units are
   ambiguous, and the content type actually sent versus the one documented.
8. **Write the contract test, and say what it is worth.** Against a recorded or stubbed response it
   catches *your client* drifting and runs in CI. Against the live sandbox it catches *the
   provider* drifting, needs credentials, and will be flaky. Prefer both, kept separate, and assert
   the fields the code reads rather than the whole payload — a whole-payload snapshot fails on
   every unrelated provider change until someone stops reading it.
9. **Rerun from a clean state.** Fresh checkout or cleared fixtures, credentials from the
   documented source rather than whatever is already exported in your shell. A test that passes
   only in your session is not coverage.
10. **Report with the right verb**, and name the environment. "Verified in sandbox" and "verified"
    are different claims; do not print the second when you did the first.

## What this refuses to conclude

- **Without an executed call** — nothing at all. Reading the client against the specification is a
  review; say "reviewed", not "verified".
- **Without the failure paths** — only that the happy path works. Nothing about resilience,
  retries, or what a user sees when the provider is down.
- **Without the auth-failure call** — nothing about the integration's behaviour when credentials
  expire, which is how it will eventually fail.
- **From a passing stub test alone** — that your client parses that stub. It is silent on whether
  the provider still returns that shape.
- **From green CI over mocked transport** — that nothing changed on your side. It is not evidence
  the integration works.
- **From a sandbox pass** — nothing about production limits, data volumes, or permissions.

## Checklist

- [ ] Contract written from the provider's own source before execution
- [ ] Environment named; anything production-touching or destructive was asked about first
- [ ] Success path executed, body read, not just the status
- [ ] Assertions on parsed fields the code actually uses
- [ ] Invalid input, missing resource, and a timeout or 5xx executed
- [ ] Missing and invalid credential executed; no credential in logs; no retry loop
- [ ] Pagination, empty set, null field, and units or timezone checked
- [ ] Contract test committed, with its stub-versus-live value stated
- [ ] Suite rerun from a clean state
- [ ] The report's verb matches what was actually done

## Failure handling

- **The provider is unreachable or the sandbox is down** — that is the result. Report the
  integration as unverified with the error captured; do not fall back to reading the code and
  calling it verified.
- **The response differs from the documentation** — trust the observed response, record both, and
  raise the mismatch. Do not quietly widen your parser until it stops throwing.
- **The failure will not reproduce** — say so with what was tried and how often. An intermittent
  integration reported as fixed is worse than one reported as intermittent.
- **Only production credentials exist** — stop. Ask before executing, and say plainly that
  verification is blocked on a safe environment rather than executing anyway.

## Evidence to report

The environment and the exact requests executed, each with its status and the asserted fields; the
failure and auth-failure responses as they came back; the contract test's path and its command,
with its output; what the test is worth (stub or live); and every path left unexecuted, named. A
claim of "integration verified" carrying none of that is the thing this skill exists to refuse.
