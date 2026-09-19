---
name: auth-security
description: Attack and harden an existing auth surface — session fixation and rotation, token verification, horizontal and vertical privilege escalation, password reset and account recovery, MFA bypass. Use when reviewing login, session, token, reset, invite, impersonation or role-elevation code, when someone reports seeing another user's data or an account takeover, or when auth changes are about to ship. Not for designing the login mechanism or permission model in the first place (authentication, authorization), not for infrastructure IAM, and never run against a system you have not been told you may test.
---

# Auth security

Auth code is reviewed by the person who wrote it and trusted by everyone else. This procedure
looks for the specific ways it fails: identity taken from the wrong place, a session that outlives
the reason it was issued, and a recovery flow that is a second, weaker login nobody audited.

## When this fires

A credential-handling path is being reviewed, changed, or doubted — login, logout, refresh,
session storage, tokens, reset, invite, impersonation, role change, MFA. Also fires on a report of
one account reaching another's data. It does not fire when the mechanism is still being designed,
or when the question is what a caller may do rather than whether the system knows who they are.

## Procedure

1. **Confirm what you are allowed to touch, before touching it.** Name the environment and get it
   agreed. Reading code needs no permission; sending crafted requests does. Testing against
   production, another tenant, or anyone's real account stops and asks — every time, including
   when the fix looks obvious.
2. **Map the surface.** Enumerate every route that issues, accepts, refreshes or revokes a
   credential, and every place identity is derived from a request. Grep for session middleware,
   token verification, `reset`, `invite`, `impersonate`, `switch_user`, admin guards. The list is
   the first artifact; a path nobody listed is the one nobody checked.
3. **Check where identity comes from, per endpoint.** The subject must be read from the validated
   credential, never from a body field, query parameter, path segment or header the caller
   controls. A `user_id` in the request that is used rather than compared is the whole bug.
4. **Walk the session lifecycle.** Is the session identifier rotated at login and at every
   privilege change, including entering and leaving impersonation — a session that survives login
   unchanged is fixation. Does logout invalidate server-side state or only clear the cookie. Are
   sessions revoked on password change, reset and MFA enrollment. Is there a way to list and kill
   a user's sessions at all.
5. **Read the real headers, not the config.** Observe an actual `Set-Cookie`: HttpOnly, Secure,
   SameSite, and the narrowest path and domain that works. Check where a token is stored on the
   client, and that no credential ever appears in a URL, a redirect target, a referrer or a log.
6. **Verify the token verification.** Signature, algorithm fixed by the server rather than read
   from the token, issuer, audience, expiry, and clock skew. Find every call site that *decodes*
   a token where it should *verify* it — that is the most common token bug in real code. For
   stateless tokens, ask what revocation means; if the answer is "it expires eventually", say so
   plainly and size the window.
7. **Test escalation with two real accounts** in the authorized environment. Horizontal: replay
   one account's request with the other's credential and an object id it does not own. Vertical:
   send the privileged request with the unprivileged credential; try setting a role, tenant or
   flag field the client should not control; call the admin route directly rather than through
   the navigation that hides it.
8. **Take recovery apart.** Reset and invite flows are a second login: token entropy, single use,
   short expiry, bound to one account, invalidating existing sessions, and no account enumeration
   through differing responses, status codes or timing. Check email-change and phone-change flows
   the same way — they are account takeover with extra steps.
9. **Check what protects the credential endpoints from volume** — login, reset, refresh, MFA
   submission, invite acceptance — and whether lockout can be aimed at a victim as a denial of
   service.
10. **Follow every path that ends in a session** and ask whether MFA is enforced on all of them:
    recovery, remembered devices, long-lived API tokens, OAuth callbacks, legacy endpoints. A
    factor enforced on one path is not enforced.
11. **Label each finding by how you know it.** Read in the code is a hypothesis. A request and its
    response is evidence. Do not report the first as the second, and never report a fix as
    verified because the reasoning that produced it was sound.
12. **Fix at the shared enforcement point, then retest.** A guard added to the one route in the
    report leaves every sibling caller exposed. After fixing, re-run the exact request that
    demonstrated the problem and keep both transcripts.
13. **Stop before anything outward-facing.** Revoking live sessions, forcing a password reset for
    real users, filing a public issue, or notifying anyone is a decision with the owner, not a
    step in this procedure.

## Checklist

- [ ] Authorized environment named and agreed before any crafted request
- [ ] Every credential-issuing, accepting and revoking route enumerated
- [ ] Subject derived from the validated credential on every endpoint checked
- [ ] Session identifier rotation at login and privilege change confirmed
- [ ] Logout, password change and reset shown to invalidate server-side state
- [ ] Actual cookie attributes observed, not read from configuration
- [ ] Every decode-vs-verify call site checked; algorithm fixed server-side
- [ ] Horizontal and vertical escalation attempted with two accounts
- [ ] Reset, invite and email-change flows walked end to end
- [ ] Each finding labelled as read-in-code or executed-and-observed
- [ ] Fixes retested with the original request, not argued

## Failure handling

- **No authorized environment exists** — do the code review, report every finding as unconfirmed,
  and say exactly which request would confirm each. Do not test production to close the gap.
- **The escalation attempt returned 200 with an empty body** — that is not a pass. Check whether
  the object exists at all before concluding the check held; a missing record and a blocked
  request look identical.
- **A finding will not reproduce** — report it as intermittent with what you tried. Auth bugs that
  depend on timing, caching or a replica are real and reporting them as fixed is worse than
  reporting them as flaky.
- **The fix is a framework upgrade or a library swap** — that is a migration with its own blast
  radius, not a one-line patch. Scope it separately and say what is exposed in the meantime.
- **You found a live compromise** — stop testing, preserve what you have, and hand it to the owner.
  Continuing to probe destroys the evidence an incident response needs.

## Evidence to report

The environment tested and the authorization for it. The route inventory. Per finding: the request
sent, the response observed, the account and privilege level used, and the file and line of the
cause. Which findings were executed and which are code-reading only. The retest transcript for
each fix. And the list of paths not tested — the ones you could not reach, and the ones you could
not test without permission you did not have.
