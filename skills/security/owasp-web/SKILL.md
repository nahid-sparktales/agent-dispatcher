---
name: owasp-web
description: Hunt the web failure classes that actually recur — broken access control, injection, XSS by output context, SSRF, unsafe deserialization and mass assignment, session and token handling, secrets leakage, file handling — as patterns to find in this codebase. Use when writing or reviewing request handlers, queries, URL fetches, templates, uploads or auth code, or when asked to check a web app for the common vulnerability classes. Not for design-stage modeling (threat-modeling), not infrastructure or network hardening, and not a list to recite without reading code.
---

# Web failure classes

These classes recur because frameworks make the unsafe version shorter to write. Finding them is
reading for a pattern — untrusted input reaching somewhere that treats it as instruction — not
reciting a taxonomy. A class you name without a file and a path is not a finding.

## When this fires

Code that receives requests, builds queries, renders output, fetches URLs, parses serialized data,
handles sessions or accepts files is being written or reviewed. Use it inside a review pass, or on
its own when asked to sweep an app for the usual suspects.

## Procedure

1. **Enumerate the untrusted entry points first.** Route tables and handlers, GraphQL resolvers
   and their nested fields, webhook receivers, queue consumers, file uploads, CLI and admin
   scripts, anything parsing a header or cookie. Every class below is checked *from* these, not by
   browsing files alphabetically.
2. **Broken access control, before anything else.** It is the most common and the least visible to
   tooling. Look for a handler taking an id from the path, body or query and fetching without
   scoping to the caller; middleware applied by opt-in so a new route is unprotected by default;
   bulk and batch endpoints checking only the first item; a role or tenant id read from the
   request. See the `authorization` skill for the model itself.
3. **Injection — find where data reaches an interpreter as syntax.** SQL built by concatenation or
   template literals, an ORM's raw escape hatch, a shell invoked with a command string rather than
   an argument vector, a query object built straight from a JSON body, an LDAP or XPath filter, a
   template rendered from a user-supplied string, `eval` and its relatives. The fix is
   parameterization or passing arguments as data — hand-rolled escaping is a defect with a delay.
4. **XSS is an output-context question.** Ask where the string lands: HTML body, attribute, URL
   attribute, inside a script, inside CSS. Look for raw-HTML sinks (`innerHTML` and each
   framework's dangerous-HTML prop), auto-escaping turned off, user text interpolated into an
   inline script or a `href`, Markdown rendered to HTML without sanitisation, and SVG or HTML
   uploads served from the app's own origin. Escaping correct for one context is wrong in another.
5. **SSRF — anywhere the server fetches a URL a user influenced.** Webhook targets, avatar and
   image fetchers, link previews, PDF and screenshot renderers, import-from-URL, identity
   discovery documents. Check for an allowlist of destinations, whether redirects are followed
   blindly, and whether the check happens before or after DNS resolution. Blocking metadata
   addresses by string match is not a control: alternate encodings, IPv6, redirects and rebinding
   all walk past it.
6. **Deserialization and object binding.** Untrusted bytes reaching a language's native
   deserializer, a YAML loader that constructs arbitrary types, or JSON that names its own class,
   is remote code execution waiting for a gadget. Alongside it: mass assignment binding a whole
   request body onto a model (`isAdmin` arrives free), and merge helpers in JavaScript that let a
   body reach the prototype chain.
7. **Sessions and tokens.** Where is a session created, rotated on privilege change, and
   invalidated on logout and password change? Cookie flags set? Password-reset tokens random,
   single-use and short-lived? For signed tokens, check that verification pins the algorithm and
   the key and checks expiry and audience — accepting whatever algorithm the token names is the
   classic hole.
8. **Secrets and inadvertent disclosure.** Keys committed to the repository or baked into a client
   bundle by a public-prefixed environment variable, tokens in URLs and logs, stack traces and
   debug routes reachable in production, error messages distinguishing "no such user" from "wrong
   password" where that matters.
9. **File handling.** Path traversal in download and upload names, archive extraction writing
   outside its target directory, trusting a client-declared content type, and serving user files
   from the application's origin where they inherit its cookies and permissions.
10. **Dependencies: audit output is leads, not findings.** Run the ecosystem's audit, then check
    whether the vulnerable code path is actually reachable from step 1's entry points. Reporting an
    advisory list as a security review is how real findings get ignored.
11. **Confirm reachability before reporting.** Source, sink, and a path between them that survives
    the checks in between. Without that path, report it as hardening and label it so.

**Sending payloads at a running system is a different act from reading code.** It stops and asks
first, names the target, and does not happen against production or anything the user has not said
they own. Reading is always in scope; probing is not implied by it.

## Checklist

- [ ] Entry points enumerated before any class was checked
- [ ] Access control checked per handler, including bulk endpoints and new-route defaults
- [ ] Every interpreter boundary found and checked for parameterization
- [ ] Output sinks checked per context, including uploads served from the app origin
- [ ] Every server-side fetch of a user-influenced URL identified
- [ ] Deserializers, model binding and merge helpers traced back to untrusted input
- [ ] Session lifecycle and token verification read, not assumed
- [ ] Repository, logs, bundles and error paths checked for secrets and disclosure
- [ ] File name, archive and content-type handling checked
- [ ] Dependency advisories triaged for reachability
- [ ] Each reported item has a source, a sink and a path; hardening labelled as hardening
- [ ] Nothing was probed against a live system without asking

## Failure handling

- **The pattern appears but the input turns out to be trusted** — drop it or downgrade it to
  hardening. A false positive costs more than a missed low-severity issue: it teaches the reader to
  skim.
- **A framework may already neutralise it** — check the framework's actual behaviour for that
  version rather than assuming either way, and say which behaviour you relied on.
- **The sink is reached through code you cannot follow** (dynamic dispatch, generated code, a
  vendored blob) — report it as an unresolved path with what you traced, not as safe.
- **A class cannot be checked at all** — no access to the templates, the infra config, the
  dependency lockfile — name it as unchecked in the report. Silence reads as a pass.
- **Something looks exploitable** — that is a hypothesis until it is run by someone authorized to
  run it. Write it as "reachable by inspection", not "exploitable".

## Evidence to report

Per finding: file and line, the untrusted input, the sink, the path between them, the concrete
consequence to a named asset, and the smallest fix. Per review: which entry points were
enumerated, which classes were checked, which were not checked and why, audit output with its
reachability triage, and everything reasoned about but not run, said so plainly.
