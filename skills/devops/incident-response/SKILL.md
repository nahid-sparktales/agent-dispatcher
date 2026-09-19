---
name: incident-response
description: Stabilize a system that is failing right now — name the signal that flagged it, size the blast radius in numbers, keep a timestamped log written as you go, find the last known-good state, then propose the smallest reversible mitigation and confirm recovery against that same signal. Use when production is degraded or down and time to mitigation matters more than a complete explanation. Not for a defect that is not currently failing (systematic-debugging), not for the root-cause investigation or the postmortem that follows, and never authorization to touch production without asking first.
---

# Incident response

Mitigation comes before explanation. The cause keeps; the outage does not. Every step here exists
to stop you from applying an unrecorded change you cannot undo and then calling a coincidence a fix.

## When this fires

A production system is failing or degraded **now** and the harm is ongoing. It stops firing the
moment the signal is stable again — then it is a debugging problem and a postmortem, not this.

If the symptom has already passed on its own, do not start mitigating. Preserve evidence and hand
it to investigation.

## Procedure

1. **Name the flagging signal exactly** — which alert, dashboard, query or user report, what
   threshold, and the first bad timestamp. Everything you do later is judged against this one
   signal. If nobody can name it, you do not yet know that anything is wrong.
2. **Open the log before investigating.** Append-only, UTC timestamps, one line per observation,
   action and decision, each action recording who ran it and what happened. A timeline written
   afterwards is a story assembled from memory of a stressful hour.
3. **Size the blast radius in numbers**: who (users, tenants, regions), what (endpoints, jobs,
   features), how much (share and absolute count of affected requests), since when — and whether it
   is growing, flat or shrinking. "Lots of users" is not a blast radius.
4. **Say the impact out loud early, and leave comms to a human.** Status pages, customer notices and
   broadcast messages are outward-facing: draft them if asked, stop before posting.
5. **Enumerate what changed before the first bad timestamp** — deploys, config edits, feature-flag
   flips, migrations, scaling changes, dependency bumps, credential or certificate rotation, traffic
   shifts, upstream vendor status. List them before forming a causal theory; a theory formed first
   will pick whichever change it likes.
6. **Rank mitigations by reversibility and blast radius, not by how likely they are to be the
   cause.** Revert the deploy, flip the flag off, drain or fail over the bad instance, scale out,
   shed load or rate-limit, restart. A mitigation does not need to know the cause. Writing a
   forward fix during an outage is the least reversible option available — treat it as the last one.
7. **Before applying anything, state four things**: the expected effect on the flagging signal, the
   window you expect it in, the risk the action itself carries, and exactly how to undo it. Then
   **stop and ask.** Every production-affecting action needs its own confirmation, and "while I am
   in there" changes are never included in it.
8. **Apply one change at a time and record the time it went in.** Two simultaneous changes buy an
   uninterpretable recovery and a mitigation nobody can safely remove later.
9. **Preserve evidence before it ages out.** Copy the log excerpts, the metric graph with its time
   range, traces, failing payloads and the exact error strings into the incident log. Never delete
   logs, rotate files, drop tables or clear a queue to make a symptom disappear — that is
   irreversible data loss during the one hour it matters most; stop and ask.
10. **Confirm recovery against the flagging signal**, over a window long enough to outlast a
    coincidental dip and to cover at least one full cycle of whatever failed. A green build, a
    passing test, a healthy synthetic check and "I am not seeing errors now" are none of them
    recovery evidence.
11. **If the mitigation did not work, undo it before trying the next one.** An incident carrying
    three abandoned mitigations has become a second incident with no known-good state.
12. **Hand off explicitly**: what is mitigated and by what, what is still unexplained, every change
    still in place and how to remove it, and where the preserved evidence is. Root cause goes to
    systematic debugging once the bleeding has stopped.

## Checklist

- [ ] The flagging signal is named, with its threshold and first bad timestamp
- [ ] A timestamped log exists and was written during, not after
- [ ] Blast radius stated in numbers, with its direction of travel
- [ ] Recent changes enumerated before any causal theory was offered
- [ ] Mitigation options ranked by reversibility, with the undo written down
- [ ] Each production-affecting action confirmed individually before it was applied
- [ ] One change at a time, each with the time it was applied
- [ ] Evidence preserved before retention could drop it
- [ ] Recovery confirmed on the flagging signal over a stated window
- [ ] Handoff names what is mitigated, what is unexplained, and what must still be removed

## Failure handling

- **The signal recovered but your change could not have reached it** — different region, tenant or
  code path — it is a coincidence. Do not close the incident on it; keep watching.
- **Nothing changed in the window** — not every incident is self-inflicted. Check upstream provider
  status, expired certificates, exhausted quotas or licences, full disks and volumes, rotated
  credentials, and the slowly growing resource (connections, queue, retention, ids) that crossed a
  threshold with no deploy at all.
- **Several things broke at once** — look for the shared dependency before treating them as
  separate incidents.
- **Monitoring itself is degraded** — absence of alerts is now unknown, not healthy. Say so and
  fall back to a signal you can read directly.
- **"Just restart it"** — acceptable as a mitigation when it is reversible and recorded, but a
  restart destroys the process state that would have explained the failure. Capture what you can
  first, and expect it to return.
- **Pressure to apply a fix without confirmation** — urgency is not authorization. State the
  proposed action and its undo, and wait.

## Evidence to report

The timestamped log itself, verbatim — it is the deliverable, not a summary of it. The flagging
signal with its query, and its values before and after with timestamps. Each action with the time
applied, who confirmed it, and its observed effect on that signal. Then state plainly what is
**mitigated** (the symptom stopped) versus what is **fixed** (the cause is gone) — conflating these
is how a mitigation gets removed a week later and takes the site down again. List what remains
unexplained, and every temporary change still holding the system up, each with an owner.
