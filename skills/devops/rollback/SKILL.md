---
name: rollback
description: Get back to a known-good state, and know in advance which parts of a release cannot come back — destructive migrations, data the old version cannot read, messages already sent, published artifacts, cache and CDN state. Use while writing a release plan, when a deploy is going wrong, or when someone asks whether a change can be undone. Not the health check that decides you should revert (release-verification), not incident coordination, and it never runs a production revert without explicit per-action confirmation.
---

# Rollback

Rollback is not the absence of a deploy. It is another deploy, made under time pressure, against a
system whose state has already moved. Most failed rollbacks fail for that reason: the code went
back and the data did not.

## When this fires

While planning a release — the rollback path is part of the plan, not a thing to invent later — and
again the moment a release is going badly. It fires before the decision to revert, not after it.

## Procedure

1. **Name the known-good state as an artifact id.** The commit, digest or build you would return
   to, confirmed still deployable — the image still present in the registry, the release still
   installable. "The previous version" is not an address, and a rollback target that was garbage
   collected is not a rollback target.

2. **Classify every part of the change** into three buckets, before you need them:
   - *Reversible* — redeploying the old artifact restores the old behavior.
   - *Forward-only* — the way back is a new fix, not the old code.
   - *Irreversible* — nothing restores the prior state; only mitigation exists.

3. **Find the one-way doors.** These are the ones that turn a rollback into an incident:
   - Dropped columns or tables, and rewritten-in-place rows with no preserved original.
   - Data the new version wrote in a shape the old version cannot read — the most common cause of a
     rollback that crashes worse than the thing it was reverting.
   - Messages, emails, notifications and webhooks already delivered.
   - Published packages, pushed image tags, git tags others have fetched.
   - Caches and CDN objects holding the new format, and clients holding new responses.
   - Third-party state: charges, external records, DNS changes still propagating under their TTL.
   Write the list down. It belongs in the release plan next to the rollback command.

4. **Check the data direction before reverting code.** If the new revision has been writing under a
   schema or format the old one does not understand, code rollback is not safe on its own. This is
   what expand/contract buys you: the old code keeps working against the new schema, so the code
   can move back alone. When that property does not hold, the honest answer is forward-only, and it
   is better to say so before the deploy than to discover it mid-revert. See `migrations`.

5. **Choose the cheapest reversible lever that works.** A feature flag beats a redeploy; a redeploy
   beats a traffic shift to a standby; any of those beat a restore from backup. Reach for the
   biggest lever last, not first — a restore loses everything written since its recovery point, and
   that loss is itself irreversible.

6. **Rehearse it.** A rollback that has never been executed is a plan with a hopeful tone. Run it in
   a non-production environment against the same shape of change: time it end to end, record how
   long, and for a restore record the recovery point it lands on and the data that would be lost.
   Never rehearse against the environment people are using — if the only copy available is
   production, stop and ask. Re-rehearse when the delivery path changes.

7. **Write it into the release record before deploying**: the target artifact, the exact steps, the
   rehearsed duration, who is able to run it, and the abort condition that triggers it — the signal
   and threshold, decided in advance. A rollback plan first written during the outage is a guess.

8. **Stop and ask before executing.** A revert is a production change with its own blast radius,
   including whatever the old code does to data the new code created. Present the target, the
   lever, the irreversible list from step 3, what is expected to break during the transition, and
   the rehearsed duration; then wait for explicit confirmation. "Fix it" is not confirmation of a
   specific revert, and a restore that discards data needs its own separate yes naming the data.

9. **Execute with the clock and the record running.** Timestamp each step and its output. If a step
   fails midway, establish what actually happened before retrying — a half-reverted fleet is worse
   than either end state.

10. **Verify the recovery against the signal that flagged the problem**, not against a green build
    or a passing test. Full procedure in `release-verification`; the short version is that the
    revision now serving must be read from the running system, on every instance.

11. **Clean up the residue** the revert left: items partially processed by the new code, rows
    half-migrated, cache and CDN entries in the new format, in-flight jobs enqueued with a payload
    the old consumer cannot parse. This is where the second outage comes from.

12. **Preserve the failed artifact and its logs** before rebuilding over them. The rollback ended
    the symptom; it also removed most of the evidence. Hand that evidence to `systematic-debugging`
    while it still exists.

## Checklist

- [ ] Known-good artifact named and confirmed still deployable
- [ ] Change classified: reversible / forward-only / irreversible
- [ ] One-way doors listed explicitly, including data, sends and published artifacts
- [ ] Old code confirmed able to run against the current data shape, or forward-only declared
- [ ] Cheapest sufficient lever chosen, restore kept as last resort
- [ ] Rollback executed in rehearsal, with a recorded duration, or marked unrehearsed
- [ ] Steps, trigger condition and duration written into the release record before the deploy
- [ ] Explicit confirmation obtained for the revert itself, and separately for any data loss
- [ ] Recovery verified against the flagging signal, on the running system
- [ ] Residue handled; failed artifact and logs preserved

## Failure handling

- **The rollback target no longer exists or will not build** — say so immediately; it changes the
  decision from revert to fix-forward, and the sooner that is known the better.
- **The rehearsal fails** — the change is not reversible. Report that as a finding about the
  release, not a chore to retry later; it usually changes whether the release should ship at all.
- **The revert makes things worse** — stop, do not oscillate between revisions. Capture the state,
  and treat it as an incident whose mitigation may now be forward-only.
- **Nowhere to rehearse** — report the rollback as unrehearsed and give an estimated duration
  labeled as an estimate. Do not rehearse on the live system to fill the gap.
- **Asked to revert without confirmation, or to restore over live data** — stop and ask, naming the
  data at risk and the recovery point. Urgency in the request does not supply the authorization.

## Evidence to report

The known-good artifact id and the environment. The three buckets, with the irreversible list
written out. The lever used and why that one. The rehearsal: that it ran, where, and how long.
Timestamped steps of the actual revert with their output. What the flagging signal did afterwards.
The residue found and what was done about it. And plainly: what was *not* recovered, because a
rollback that restored the service while losing data is both of those things, not just the first.
