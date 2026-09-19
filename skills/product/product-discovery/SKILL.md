---
name: product-discovery
description: Find the real problem behind a feature request before anyone scopes a solution — whose job is stuck, what evidence exists already, and what observation would prove the assumption wrong. Use when a request arrives phrased as a solution ("add a dashboard", "we need notifications"), when a team is about to build on a belief nobody has checked, or when asked whether something is worth building at all. Not for writing the spec once the problem is settled, not for ranking work that is already understood, and never a licence to contact users without permission.
---

# Product discovery

A feature request is an answer. Discovery is recovering the question it answers, and finding out
whether the question is real. Most of the evidence you need already exists and nobody has read it.

## When this fires

A request names a solution and not a problem; a plan rests on a belief about users that has never
been checked; someone asks whether a thing is worth building. It does not fire when the problem
and its evidence are already established and the job is to write the scope — that is
`prd-and-stories`.

## Procedure

1. **Split the request into solution and problem.** Write the request verbatim, then write the
   sentence under it: who is trying to do what, and what happens today instead. If you cannot
   write that second sentence from what you were given, that gap is the finding — say so before
   going further.
2. **Name the person and the job.** A named role doing a specific task on a specific occasion
   ("a support agent closing a ticket after a refund"), not a segment. Ask who is *not* affected
   too — a problem everyone allegedly has usually belongs to nobody in particular.
3. **Read what the product already does.** Find the current path through the code, the existing
   screens, the config, the feature flags. Half of all requests are for something that exists,
   is disabled, or is two clicks away from where the user looked. Report that outcome as a result,
   not as a failure to find work.
4. **Harvest evidence already in reach before asking for any.** Issue tracker and its duplicates,
   support tickets, changelog and past attempts at this, analytics and logs already collected,
   prior docs and decision records. Quote what you found with its source; a claim you cannot
   attribute is an assumption.
5. **Grade every piece of evidence.** Three grades, and keep them apart: **observed** (behaviour
   in logs, tickets, recordings, a failing workflow you traced), **reported** (a person says so —
   including the requester and the loudest stakeholder), **assumed** (nobody has checked). Say the
   grade next to the claim. Most "user needs" collapse a grade when written down honestly.
6. **Write the load-bearing assumption as one falsifiable sentence.** The one that, if wrong,
   makes the whole idea pointless. Phrase it so it can fail: "agents abandon refunds because the
   audit log is on another screen" — not "agents want a better experience".
7. **Say what would falsify it, and what it would cost to look.** Name the cheapest honest check
   that could return "no": a query against data you already have, a count of tickets matching a
   pattern, tracing five real cases end to end, watching the current workflow being used. Prefer
   a check you can run over one that needs someone else's calendar.
8. **Run the checks you are permitted to run.** Reading existing data and code is yours to do.
   Anything that reaches a person — a survey, an interview request, a message to a customer, a
   posted question, an experiment served to live traffic — is outward-facing: draft it, then stop
   and ask. Discovery never sends on its own initiative.
9. **Report the decision the evidence supports, not the one that was hoped for.** Three honest
   endings: the problem is real and here is what we know; the problem is real but different from
   the request; there is no evidence yet and here is the cheapest way to get some. "Proceed
   anyway" is a legitimate call for someone else to make — say what is being bet on.

## Checklist

- [ ] The request is written down separately from the problem it claims to solve
- [ ] A specific person and a specific occasion are named, not a segment
- [ ] Current product behaviour was actually inspected, not assumed absent
- [ ] Existing evidence was searched before any new research was proposed
- [ ] Every claim carries a grade: observed, reported, or assumed
- [ ] One load-bearing assumption is written so that it could fail
- [ ] A named check that could falsify it, with its cost
- [ ] Anything that would contact a user was drafted and paused for approval, not sent
- [ ] What is still unknown is listed, not smoothed over

## Failure handling

- **No evidence exists anywhere.** That is a finding, and a common one. Say the belief is
  unvalidated, give the cheapest check, and do not launder the requester's confidence into
  "user research shows".
- **The only evidence is one loud stakeholder.** Record it as reported, with the name. It may
  still be right; it is not yet observed.
- **Analytics disagree with what people say.** Report both and say which question each answers.
  Logs show what happened; people explain why. Neither overrides the other by default.
- **The problem is real but the requested solution does not address it.** Say so plainly, keep
  the problem, and hand the solution question on. Do not quietly redesign the request.
- **Discovery would need to contact users and you have no approval.** Stop. Prepare the questions
  and say what you would learn. An unapproved outreach is worse than an unanswered question.
- **The pressure is to confirm.** If every check you propose can only return "yes", you have
  designed a formality. Rewrite one that can return "no".

## Evidence to report

The request as received and the problem statement derived from it; the person and job named; what
the product does today, with file or screen references; every source you read, quoted, with its
grade; the load-bearing assumption in falsifiable form; the checks run and what they returned,
distinguished from the checks proposed but not run; and the list of open unknowns. "We validated
the need" with no quoted source, no grade and no check is not evidence.
