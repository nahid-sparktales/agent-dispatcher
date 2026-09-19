---
id: security-review
name: "Security review"
summary: "Find real, reachable security problems and prove the remediation closed them — checked by someone who did not write the fix."
use_when: "Code touching authentication, authorization, sensitive data, or an external trust boundary needs review before it ships."
capabilities: security.threat-modeling, security.review, security.web
roles: security-auditor, implementer, reviewer
---

# Security review

## Steps

1. **Map the trust boundaries** before reading code. What crosses from untrusted to trusted, what
   the attacker can control, what is worth defending here. → `threat-modeling`
2. **Read where the bugs cluster** — the boundary crossings, not the whole codebase. →
   `secure-code-review`, `owasp-web`
3. **For each finding, establish reachability.** An unreachable weakness is a note, not a finding.
   Say which it is.
4. **Report with the trigger condition, the consequence, and the evidence.** Severity calibrated to
   actual impact, not to how alarming the category sounds.
5. **Remediate** — a separate step, and often a separate agent.
6. **Re-test the original boundary.** → `security-remediation` behaviour lives in
   `secure-code-review`; the point is that the fix is tested against the same input that exposed
   the problem.

## Gates

- **The author of a fix does not approve their own fix.** Verification comes from the auditor or an
  independent reviewer, and if the same session produced both, say so plainly.
- No destructive testing without explicit authorization for that specific system.
- A clean review is reported as "no findings in the reviewed scope", never as "the system is
  secure".
