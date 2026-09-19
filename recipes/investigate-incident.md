---
id: investigate-incident
name: "Investigate an incident"
summary: "Stabilize a system that is failing right now, then hand off the root cause."
use_when: "Production is degraded or down and time to mitigation matters more than a complete explanation."
capabilities: devops.incident, devops.rollback, devops.observability, verification.deployment
roles: incident-responder, debugger, devops-release
---

# Investigate an incident

Reproduce-first is the wrong instinct here. Mitigation comes before explanation; the root cause
keeps.

## Steps

1. **Establish blast radius** and open a timestamped log, written as you go. A timeline
   reconstructed afterwards is a story, not a record.
2. **Find the last known-good state** — recent deploy, config change, dependency bump, traffic
   shift — before forming any causal theory.
3. **Propose the smallest reversible mitigation** and confirm before applying it: revert, feature
   flag, scale, shed load. → `rollback`
4. **Confirm recovery against the same signal that flagged the incident.** Not a green build, not
   a passing test. → `release-verification`
5. **Hand the root cause to `debugger`** once the bleeding has stopped.
6. **Write the timeline up** while it is still accurate.

## Gates

- Nothing touching production happens without explicit per-action confirmation.
- Recovery is claimed only against the flagging signal.
- The handoff states what was mitigated, what remains unexplained, and what was changed.
