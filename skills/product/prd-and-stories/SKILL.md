---
name: prd-and-stories
description: Write a scope someone else can build from without asking you what you meant — problem, users, the flow end to end including its unhappy states, acceptance criteria phrased as observable behaviour, and explicit non-goals. Use when turning a settled problem into a brief, spec, PRD, epic or set of stories, or when repairing a ticket that is too vague to estimate or to check. Not for deciding whether the problem is real (product-discovery), not for ranking work (prioritization), and not for choosing the implementation.
---

# PRD and stories

The test of a scope is not that it reads well. It is that two people building from it
independently produce the same behaviour, and a third can tell whether they did.

## When this fires

A problem is settled and the work needs a written scope before it is designed or built; a ticket
is too vague to estimate, to build, or to check. It does not fire while the problem is still in
question — go back to `product-discovery` and say why.

## Procedure

1. **Check the problem is actually settled.** One paragraph: who, doing what, blocked how, and
   what evidence says so — with the grade it came with (observed, reported, assumed). If you are
   writing that paragraph from imagination, stop and say the scope is resting on an unchecked
   belief.
2. **State the change in the world.** What will be true after this ships that is not true now,
   expressed as user behaviour or outcome, not as a shipped artifact. "An agent can see the audit
   trail while closing a refund", not "we add an audit panel".
3. **Inspect the surface you are scoping.** Read the current screens, routes, data model and
   permissions before describing the new ones. A scope that contradicts what exists costs more to
   discover in review than to prevent here, and existing conventions are usually load-bearing.
4. **Write the primary flow end to end.** Entry point (how does anyone arrive), each step and its
   decision points, the exit and what the user sees when it worked. Number the steps. If a step
   needs data the system does not have, name that now — it is the most common hidden dependency.
5. **Write the states that are not the happy path.** Empty, loading, partial, error, offline or
   slow, no permission, and the boundary values (zero, one, very many, very long, duplicate,
   concurrent). Each one gets a stated intended behaviour. Unspecified states are not neutral:
   somebody will invent them, and reviewers will not know what to check against.
6. **Write acceptance criteria as observable behaviour.** One checkable statement per criterion,
   in the form "given … when … then …" or a plain sentence a tester can execute. Each must name
   what is done and what can be seen. Forbidden in a criterion: "works correctly", "is intuitive",
   "is performant" with no number, and any verb about the process rather than the product —
   *created*, *executed*, *tested*, *reviewed*, *deployed* and *verified* describe what a team
   did, and none of them is a behaviour a user can observe. If a criterion cannot fail, it is a
   description, so delete it or sharpen it.
7. **Write the non-goals explicitly.** The adjacent things a reasonable reader would assume are
   included: the admin view, the bulk case, the other platform, the migration of old data, the
   analytics event. Naming them as out is what stops silent scope growth later.
8. **Cover the cross-cutting requirements that are usually skipped.** Who is allowed to do this
   (permissions, roles, tenancy); what data is stored, shown or logged, and what must not be;
   keyboard and screen-reader access to the new controls; what operations need to see when it
   misbehaves. Write the ones that apply and say the rest do not.
9. **Split into stories only along lines that ship.** Each story is independently buildable and
   independently checkable, and carries its own acceptance criteria. Split by user-visible slice —
   one flow working end to end for one case — not by layer. "Build the API", "build the UI" is a
   task list wearing a story's clothes: neither half can be checked against a user.
10. **List the open questions with an owner and a blocking flag.** A question you invented an
    answer for is the failure mode this step exists to prevent. Mark which ones must be answered
    before building and which can be answered while building.
11. **Hand over with the decided and the open kept apart.** The scope fixes behaviour and
    constraints; it does not choose the implementation. Where you have a preference about how, say
    it is a preference. Leave design and architecture their decisions.

## Checklist

- [ ] Problem paragraph present, with the evidence grade it carries
- [ ] Outcome stated as a change in what a user can do
- [ ] Current behaviour was read, not assumed
- [ ] Primary flow numbered from entry point to exit
- [ ] Empty, error, permission-denied and boundary states each have stated behaviour
- [ ] Every acceptance criterion is observable and can fail
- [ ] No criterion uses created / executed / tested / reviewed / deployed / verified as its behaviour
- [ ] Non-goals written, including the obvious adjacent ones
- [ ] Permissions, data, accessibility and operational needs covered or explicitly N/A
- [ ] Stories split by shippable slice, each with its own criteria
- [ ] Open questions listed with owners, blocking ones marked
- [ ] Nothing in the scope dictates implementation without saying it is a preference

## Failure handling

- **A required answer does not exist.** Write the question, not a plausible answer. A spec's
  invented detail is indistinguishable from a decided one by the time it reaches a developer.
- **The scope will not fit the time available.** That is a prioritization problem, not a writing
  problem. Name the smallest slice that delivers the outcome, and say what was cut — do not
  shrink the criteria until everything fits.
- **A criterion depends on a number nobody has.** Propose the number, label it a proposal, and
  name who confirms it. A target presented as agreed when it was guessed is a defect in the spec.
- **Existing behaviour contradicts the new scope.** Raise it as a decision — change it, keep it,
  or scope around it — and do not resolve it silently in the spec's wording.
- **The scope touches deletion, money, messaging users, or anything else irreversible.** Specify
  the confirmation and the recovery path as part of the behaviour, and flag it for explicit
  sign-off. Writing it down is not approval to build or run it.
- **You are being asked to sign off on the work as well as write the scope.** Decline the second
  half. Whoever wrote the criteria is not the evidence that they pass.

## Evidence to report

The written scope itself; the source of the problem paragraph; which files or screens you read to
describe current behaviour; the states you specified and any you deliberately left out; the
acceptance criteria, each one checkable; the non-goals; and the open questions with owners. A
brief with no non-goals and no open questions is usually not complete — it is unexamined.
