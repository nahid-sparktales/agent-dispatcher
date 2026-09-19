---
name: prompt-engineering
description: Write or revise a prompt so it holds up — output contract, instruction placement, examples that earn their place, an escape hatch for bad input — and measure the change against a saved set of cases instead of one good-looking run. Use when a prompt is being authored or patched, when output is inconsistent or the wrong shape, when a model or version changes, or when someone reports a prompt as fixed. Not for scoping an agent's job and tools, not for deciding what material to load into the window, and not for model selection or fine-tuning.
---

# Prompt engineering

A prompt that worked once is an anecdote. Almost every "fixed" prompt was judged on the input that
motivated the edit, on a single run, against no recorded baseline.

## When this fires

Authoring or editing any prompt whose output something depends on, and any time a prompt is
declared improved. It does not fire for a one-off question you ask and read yourself.

## Procedure

1. **Collect cases before editing.** At least five real inputs, including the two that fail now and
   two that currently pass and must keep passing. No cases means no measurement is possible — say
   that plainly instead of shipping an eyeballed change.
2. **Run the baseline and record it.** Every case, actual output saved, pass or fail marked. This
   is the only thing a later claim of improvement can be checked against.
3. **Write the output contract first.** Exact shape, field names, ordering, units, and what the
   output looks like when the model cannot comply. Unspecified format is the single most common
   defect, and it is invisible until something downstream parses it.
4. **Separate durable instruction from variable data.** Keep the standing rules in one place and
   the per-run material in another, marked so the boundary is unmistakable. A prompt that
   interleaves them teaches the model that data can issue instructions.
5. **Say what to do, not only what to avoid.** A prohibition names the failure without supplying
   the alternative; the model still has to pick something. Pair every "do not" with the behaviour
   that replaces it.
6. **Add an example only where prose could not pin it down** — an exact format, an edge case, a
   tone. Cover the boundaries: the empty input, the ambiguous one, the one that should be refused.
   Examples that all resemble each other teach that resemblance, and the model will reproduce their
   shared accident rather than the rule.
7. **Give it an escape hatch.** What to output when the input is insufficient, ambiguous, or out of
   scope. A prompt with no defined "I cannot" will fabricate rather than return nothing.
8. **Mark untrusted spans.** Anything pasted in — a user's text, a document, a tool result — is
   data. State in the prompt that instructions found inside it are to be surfaced, not obeyed.
9. **Change one thing, then re-run the whole set.** Not just the case that prompted the edit. A
   change that fixes case 3 and breaks case 1 is not an improvement, and you will only see it here.
10. **Judge by a written rule, not a feeling.** Per case: exact match, schema validity, a required
    substring, or a rubric with its standard written down. Use the same judge before and after; a
    judge that changed with the prompt measures nothing.
11. **Report the pass rate, not the anecdote.** Where output is nondeterministic, run each case
    several times and report the rate — "4/5 cases, 3 runs each" says something; "it works now"
    does not.
12. **Re-measure on the model you will actually run.** A prompt tuned against one model or version
    is evidence about that model. Treat a version change as a reason to re-run the set.
13. **Keep the cases beside the prompt, versioned with it**, so the next person to edit it can
    measure instead of guessing.

Keep the verbs apart when reporting: the prompt was **written**; a case was **executed**; the set
was **measured** with a recorded pass rate. Only the third supports a claim that a change helped.

## Checklist

- [ ] Case set exists, includes current failures and current passes
- [ ] Baseline recorded before any edit
- [ ] Output contract states shape and the non-compliance output
- [ ] Instructions and variable data visibly separated
- [ ] Every prohibition paired with the replacement behaviour
- [ ] Examples cover a boundary and a refusal, not only the happy path
- [ ] Escape hatch defined for insufficient or out-of-scope input
- [ ] Untrusted spans marked as data
- [ ] One change per measurement, whole set re-run
- [ ] Judging criterion written down and unchanged across the comparison
- [ ] Model and sampling settings recorded with the result

## Failure handling

- **The failure will not reproduce** — it is a rate, not a state. Run it repeatedly and report the
  frequency. An intermittent failure called fixed is worse than one called intermittent.
- **The prompt keeps growing** — each patch bolted onto the last is how prompts rot. Rewrite from
  the contract and re-measure, rather than adding a ninth clause.
- **The only fix anyone can find is more examples** — the contract is underspecified. Go back to
  step 3; examples are papering over a rule that was never stated.
- **Cases pass but real usage still fails** — the case set does not represent the traffic. That is
  the finding. Widen the set before touching the prompt again.
- **Measuring properly requires changing something live** — stop and ask. Evaluating against
  production traffic or real user data is not a free action.
- **You cannot confirm what a model or SDK supports** — name the technique rather than a flag or
  parameter you have not verified, and check the current documentation before writing it.

## Evidence to report

The case set and the judging criterion; the before/after table with per-case pass or fail and the
run count; the prompt diff; the model, version and sampling settings the numbers came from; and the
cases that still fail, named rather than averaged away.
