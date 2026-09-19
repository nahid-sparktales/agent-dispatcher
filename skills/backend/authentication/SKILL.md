---
name: authentication
description: Establish who the caller is — session cookies, bearer tokens, refresh, and OAuth/OIDC flows — and put each where it belongs. Use when adding or changing login, logout, signup, session handling, token issuance or refresh, an identity-provider integration, or when a request arrives with a credential nobody validates. Not for deciding what an authenticated caller may then do (that is authorization), not for the login screen's design, and not for hand-rolling crypto.
---

# Authentication

Authentication answers one question: **who is making this request?** Every answer it produces is an
input to authorization, never a substitute for it. A skill that conflates the two produces an app
where being logged in is the only permission that exists.

## When this fires

A credential is issued, accepted, refreshed or revoked. Adding login, wiring an identity provider,
introducing an API key or token, changing session lifetime or cookie flags. It does not fire for
"this user should not see that" — that is authorization.

## Procedure

1. **Find the mechanism that already exists before adding one.** Grep for session middleware, an
   auth library in the dependency manifest, existing cookie names, a provider SDK, `Authorization`
   header handling. Most "add auth" tasks are "extend auth". Two parallel auth systems is how a
   bypass gets built.
2. **Name the client type, in writing, before any code.** First-party browser app → server session
   with a cookie. Third-party, native or mobile client → bearer token. Service to service →
   client-credentials token or mutual TLS. This choice determines everything below; making it
   implicitly is how a browser app ends up storing a long-lived token in `localStorage`.
3. **Use the framework's or provider's implementation.** Do not write password hashing, token
   signing, or an OAuth flow yourself. If passwords are stored at all, hash with a memory-hard
   algorithm (argon2id, scrypt, bcrypt) through a maintained library — never a bare SHA, never a
   homemade salt scheme. When the library's current API matters, look it up rather than recalling
   it; auth APIs change and a stale call silently weakens the result.
4. **Sessions:** identifier from a CSPRNG, state held server-side or in a signed cookie you can
   invalidate. Cookie flags `HttpOnly`, `Secure`, `SameSite`, a scoped `Path`, and an explicit
   expiry — all four, not three. Rotate the session identifier on login and on any privilege
   change. Logout deletes server-side state, not just the cookie.
5. **Tokens:** validate signature, issuer, audience and expiry on every request, and pin the
   accepted algorithm on your side — never take the algorithm from the token's own header, and
   reject `none`. Verify against the provider's published key set, fetched and cached with
   rotation in mind. Short access-token lifetime is the containment; a stateless token cannot be
   recalled once issued.
6. **Refresh and revocation are one design, not two.** Keep refresh tokens in server-side state so
   they can be revoked, rotate them on each use, and treat reuse of a rotated token as theft:
   invalidate the family and force re-login. If you cannot revoke, say so plainly rather than
   implying you can.
7. **OAuth / OIDC:** authorization code with PKCE for anything user-facing. Implicit flow and
   resource-owner password grant are not options. Validate `state` on the callback, validate
   `nonce` in the ID token, and exact-match the redirect URI against an allowlist — prefix matching
   is an open redirect. The client secret never reaches a browser or a shipped binary; code is
   exchanged for tokens server-side.
8. **Resolve identity at one choke point.** Middleware turns a request into a principal or into
   anonymous, once. Handlers read that principal; they never parse the raw credential themselves.
   Scattered credential parsing guarantees one handler parses it differently.
9. **Fail closed and fail uniformly.** Missing or bad credential → 401, generic message. Do not
   reveal whether an account exists, and keep the response shape and timing identical for unknown
   user and wrong password. Rate-limit and back off on credential endpoints, including password
   reset and token exchange.
10. **Secrets come from the environment or a secret manager.** Never a committed file, never a
    default baked into code. Before rotating a signing key, changing a cookie name or shortening
    session lifetime on a running system, **stop and ask** — each of those logs every user out.
11. **Prove it by executing it.** An auth change is verified by requests actually sent: valid
    credential, absent credential, malformed credential, expired credential, and the refresh path.
    Reading the diff is a review. Hand the proof to `api-contract-verification`.

## Checklist

- [ ] Existing mechanism found and extended, or its absence confirmed
- [ ] Client type named, and the session/token choice follows from it
- [ ] No hand-written crypto; library and its current API confirmed
- [ ] Cookie flags set, or token validation pins issuer, audience, expiry and algorithm
- [ ] Session identifier rotates on login and privilege change
- [ ] Refresh tokens revocable and rotated, or the absence of revocation stated
- [ ] OAuth: PKCE, `state`, `nonce`, exact redirect-URI match, secret server-side only
- [ ] One resolution point; handlers read a principal, not a credential
- [ ] Unauthenticated responses uniform, generic, rate-limited
- [ ] Secrets out of the repository; anything that logs users out was asked about first
- [ ] Valid, missing, malformed, expired and refresh paths executed, not reasoned about

## Failure handling

- **Login works but the session does not persist** — read the actual `Set-Cookie` on the wire
  before touching code. Domain, `Path`, `Secure` over plain HTTP, and `SameSite` on a cross-site
  callback account for most of these, and none of them are visible in the source.
- **Token validates in one service and not another** — compare issuer, audience and clock skew
  before suspecting the key. Shared secrets that "work locally" usually mean validation is being
  skipped somewhere.
- **The provider's flow does not behave as documented** — capture the exact callback parameters and
  error code and report them. Do not loosen redirect-URI matching, disable state checks, or skip
  signature verification to get past it. That is not a workaround, it is the vulnerability.
- **No way to test the provider without production credentials** — say the flow is unverified and
  name which step is unproven. Do not report an OAuth integration as working because the code
  compiles.

## Evidence to report

Which mechanism is in use and why that client type chose it; the cookie flags or the exact token
claims validated; where identity is resolved, as a file and function; the requests actually
executed and their statuses, including the failure and refresh paths; anything that could not be
executed, named. "Auth added" with none of that is a claim, not evidence.
