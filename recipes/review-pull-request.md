---
id: review-pull-request
name: "Review a pull request"
summary: "Judge a change against its stated intent and the evidence supplied, and say plainly what was not checked."
use_when: "A change is proposed for merge and someone needs an assessment of whether it is ready."
capabilities: quality.strategy, security.review, design.accessibility
roles: reviewer, security-auditor, ui-ux-designer
---

# Review a pull request

## Steps

1. **Establish the intent and the acceptance criteria.** Review the artifact, not the author's
   summary of it.
2. **Read the diff in context**, following the callers of anything changed.
3. **Check the evidence.** Did tests run, against this revision? Evidence from an earlier revision
   is not evidence for this one.
4. **Add the lenses the change earns** — security when it crosses a trust boundary, accessibility
   when it renders UI, performance when it sits on a hot path. Not all three by default.
5. **Separate blocking findings from suggestions from unverified conditions.**

## Gates

- Findings are tied to the revision reviewed; a changed diff needs a fresh look at what changed.
- A clean review states the scope it covered — it never implies the whole system is fine.
- The reviewer does not implement the fixes and then approve them.
