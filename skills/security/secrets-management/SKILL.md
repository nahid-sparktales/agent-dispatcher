---
name: secrets-management
description: Keep credentials out of code, logs, bundles and history — one supply path, scoped per environment, rotatable on demand — and run the rotate-first response when one has already leaked. Use when adding or moving a key, token, connection string or signing secret, when a scanner or reviewer finds one committed, when a credential appears in logs or a client bundle, or when rotation is due. Not for deciding what a credential may access, and not for vulnerability advisories in dependencies.
---

# Secrets management

Two different jobs share one skill because the second is always urgent and the first is what stops
it recurring. If a secret has already leaked, start at **When one has leaked** and come back after.

## When this fires

A credential is being introduced, moved, shared or rotated; a scanner, review or log inspection
turns one up; a key needs to reach a new environment or service. It does not fire for deciding
what a credential is permitted to do once valid.

## Procedure — keeping them out

1. **Inventory what counts.** API keys, database URLs carrying passwords, private and signing keys,
   OAuth client secrets, webhook signing secrets, session secrets, cloud credentials. For each:
   which environments it exists in, who owns it, where it is stored, how it is rotated. A secret
   nobody owns is a secret nobody rotates.
2. **Establish one supply path and make everything else a defect.** Injected at runtime from the
   platform's secret store or environment, read once at startup through a single config module.
   Committed `.env` files, hardcoded fallback defaults, secrets in CI configuration files, build
   arguments and image layers are all the same failure with different file extensions.
3. **Search the working tree, then search the history separately.** They are different questions. A
   key rotated out of the current tree is still exposed if it sits in a commit anyone can fetch.
4. **Put prevention in the path, not in a habit.** Scanning at commit time and in CI so the build
   fails, plus the host's push protection where it exists. Say plainly that pattern scanners miss
   custom and high-entropy-free formats — they lower the rate, they do not close the hole.
5. **Close the log path, which leaks more than git does.** Application logs, error messages, stack
   traces, HTTP client debug output, crash and analytics reporters, and URL query strings. Redact
   at the logging boundary so a new call site inherits it, and never place a credential in a URL.
6. **Check the client bundle.** Anything shipped to a browser or mobile app is public no matter how
   it is named. Confirm that only the deliberately public values carry a public prefix, and search
   the built output rather than the source.
7. **Scope and separate.** A distinct credential per service and per environment, with the narrowest
   permission that works, and short-lived where the provider issues short-lived ones. One key shared
   everywhere means one leak rotates everything at once.
8. **Make rotation routine before it is an emergency.** Know whether each secret can be rotated
   without downtime — most providers allow two valid keys briefly, and that overlap is what makes a
   clean rotation possible. A rotation procedure that has never been executed is a document, not a
   capability; rehearse it in a non-production environment.
9. **Review who can read the store.** People, CI jobs, and any workflow that runs on contributions
   from outside the team. Secrets exposed to builds triggered by forks are a standing leak.

## When one has leaked

1. **Treat it as compromised from the moment it was written**, regardless of how briefly, how
   private the repository is, or who "could realistically have seen it". Private repositories get
   cloned, forked and made public.
2. **Rotate or revoke first** — but revoking a live credential can take a service down, so name the
   credential, its blast radius and the dependents, and get the owner's decision before executing.
   Prepare the rotation, do not silently perform it.
3. **Establish the window and the audience.** When it entered, through which channel, who or what
   could read it in that period, and whether it also reached a third party such as a log or error
   service. An external sink counts as exposure.
4. **Look for use.** The provider's audit log for calls in the window from unexpected sources. Say
   explicitly that finding nothing there is not proof it was unused — most providers do not log
   enough to support that claim.
5. **Purge afterwards, never instead.** History rewriting is disruptive, needs coordination with
   everyone holding a clone, and still leaves the old objects in forks, caches and mirrors.
   Rewriting shared history is a stop-and-ask action. Rotation is the control; removal is cleanup.
6. **Fix the path that let it in** — the missing scanner, the example file that became real, the
   log line — and write the incident down: what leaked, when, what was rotated, what was checked.

## Checklist

- [ ] Every secret has an owner, a store, an environment scope and a rotation method
- [ ] One documented supply path; no credential in code, CI config, build args or image layers
- [ ] Working tree and history searched as separate passes
- [ ] Commit-time and CI scanning in place, with its blind spots stated
- [ ] Redaction at the logging boundary; no secret in any URL
- [ ] Built client bundle inspected, not just the source
- [ ] Credentials distinct per service and environment, least privilege
- [ ] Rotation rehearsed somewhere real, with the overlap behaviour known
- [ ] On a leak: rotation proposed with blast radius before anything is revoked
- [ ] On a leak: exposure window, provider audit check and written incident record

## Failure handling

- **Rotation would break production** — that is a finding, not a reason to skip it. Report the
  dependency that blocks it, propose the overlap plan, and let the owner schedule it.
- **The secret is embedded in a deployed client** — rotation alone does not help, because the new
  value ships the same way. The fix is moving the call server-side; say so rather than rotating in
  a circle.
- **The scanner flags a false positive** — confirm it is genuinely an example or a test fixture
  before dismissing it, and make it obviously fake so the next reviewer does not re-litigate it.
- **A secret was only in a log, not in code** — same exposure, different medium. Rotate, then find
  the log sink's retention and who reads it.
- **You cannot tell whether it was ever valid** — treat it as valid. Verifying by using the
  credential is an action against someone's system; ask the owner instead.

## Evidence to report

Where each secret now comes from and where it no longer appears — the file, the log line, the
bundle path. The scan performed, the tool used, and what it cannot catch. For a leak: the exposure
window, the channel, what was rotated and by whom, what the provider's audit log showed for that
window, whether history was purged and what that does not reach, and the prevention now in the
path. Naming rotation as "handled" without saying who executed it is not evidence.
