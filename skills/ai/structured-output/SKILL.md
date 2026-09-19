---
name: structured-output
description: Get parseable, trustworthy structured results out of a model — schema design, the enforcement mechanism the provider actually offers, validation at the boundary, bounded retry that feeds the error back, and recognising where a schema stops buying correctness. Use when a model's output feeds code rather than a human, when parsing keeps failing or fields come back plausible-but-wrong, or when designing an extraction, classification or grading step. Not for designing the tools an agent calls (tool-design), and not for free-form prose quality.
---

# Structured output

A schema constrains shape, never truth. It buys you `parse()` succeeding; it does not buy you a
correct value in the field. Most structured-output work is deciding which of those two problems you
actually have.

## When this fires

Any model output that code consumes: extraction, classification, routing, scoring, grading, filling
a record. Also when parsing fails intermittently, when required fields arrive empty or invented, or
when a downstream system trips over a value that validated fine. It does not fire for output a human
reads.

## Procedure

1. **Decide what the code truly needs.** Every field is something the model must get right and you
   must validate. A schema with three well-defined fields outperforms one with twelve where four are
   guesses. Drop anything no caller reads.
2. **Use the strongest enforcement the provider gives you, and know which one it is.** Ranked:
   constrained decoding against the schema, where the provider guarantees conformance; a tool or
   function call carrying the schema; a prompt asking for JSON, parsed defensively. The third is not
   a guarantee. Check the provider's current documentation for which mode applies and which JSON
   Schema keywords it supports — unsupported keywords are commonly ignored rather than rejected, and
   an ignored constraint fails later as a mysterious bad value.
3. **Make illegal values unrepresentable.** Closed enums instead of free strings for anything with a
   known set. Numbers as numbers, with bounds. Dates in one stated format. No field that means two
   things depending on another field. Flat beats deeply nested: nesting and recursion cost accuracy
   and are the first thing a strict mode refuses.
4. **Name fields so the schema teaches the task.** `refund_reason_code` with an enum and a one-line
   description does work no prompt sentence has to repeat. Put the per-field instruction in the
   schema description, not scattered in the prompt.
5. **Give uncertainty somewhere to go.** Add an explicit `unknown` or `not_stated` enum member and a
   nullable field where absence is genuine. Without it, a required field forces a fabrication — the
   schema converts "I don't know" into a confident wrong answer. A refusal or safety stop also needs
   a representable path; do not model it as a parse error.
6. **Order the fields so reasoning precedes conclusion.** Where a decision needs thinking, put a
   short rationale field before the verdict, or take the reasoning outside the object entirely. A
   verdict emitted first and justified afterwards is a rationalization, not a reason.
7. **Validate at the boundary, every time.** Parse with the real validator — the schema library the
   project already uses — and then check what the schema cannot: does the id exist, is the date in
   range, do the extracted spans appear in the source, does the total match the line items. Never
   let unvalidated model output into a database, a query, a shell command or a URL.
8. **Retry narrowly, bounded, with the error fed back.** On a validation failure, return the
   validator's message and the offending output, and ask for a correction. One or two attempts, then
   fail loudly. An unbounded repair loop hides a broken schema and bills for it. Escalating to a
   larger model or splitting the task beats a third retry.
9. **Know when to stop adding schema.** A schema cannot make a field accurate, cannot resolve a
   genuinely ambiguous source, cannot enforce a relationship between fields, and cannot stop
   confident invention. When failures are wrong values rather than wrong shapes, the fix is
   upstream: better retrieval, a smaller task, an example or two, a split into separate calls — not
   another constraint. Say this plainly instead of tightening a schema that is already conforming.
10. **Measure on a fixed set before trusting it.** Twenty to fifty labelled cases including the ugly
    ones — missing data, ambiguity, adversarial text, empty input. Record parse rate and field
    accuracy separately; they fail for different reasons and a high parse rate hides a low accuracy.
    Re-run it when the schema, prompt or model changes.
11. **Stop at the boundary.** Producing validated output is *extracted*. Writing it into a system of
    record, sending it onward, or acting on it is a separate, outward-facing step — and where the
    output drives a destructive action, it stops and asks first.

## Checklist

- [ ] Every field is read by a caller; the rest are gone
- [ ] Enforcement mechanism named, and confirmed against current provider documentation
- [ ] Enums closed, numbers bounded, one date format, no overloaded fields
- [ ] Nesting kept shallow and supported by the mode in use
- [ ] Per-field meaning lives in the schema description
- [ ] `unknown` / null paths exist so the model need not fabricate; refusal is representable
- [ ] Rationale precedes verdict where a judgement is made
- [ ] Output validated with a real validator, plus the semantic checks the schema cannot make
- [ ] Retry bounded, error message fed back, hard failure after the bound
- [ ] Fixed evaluation set run; parse rate and field accuracy reported separately

## Failure handling

- **Parse fails intermittently** — prose around the JSON, a truncated response hitting the token
  limit, or a mode that was never actually enforcing. Check the finish reason before blaming the
  prompt.
- **It validates but the values are wrong** — a schema problem no longer. Go to step 9.
- **A required field is always filled and sometimes invented** — you removed the model's escape
  hatch. Add `unknown`.
- **The schema is rejected by the provider** — an unsupported keyword or too much nesting. Simplify
  the schema rather than dropping to unenforced prompting.
- **Retries succeed often enough to look fine** — that is a defect rate you are paying to hide.
  Report the pre-retry rate.
- **No labelled cases exist** — say the accuracy is unmeasured. "Parses reliably" is not "is
  correct", and the two must never be reported as one claim.

## Evidence to report

The schema as shipped. The enforcement mode, named, with what it does and does not guarantee.
Validation code and the semantic checks beyond the schema. Results on the fixed set: parse rate
before retries, parse rate after, field-level accuracy, and the failure cases with their inputs.
Keep the verbs apart — *parses*, *validates* and *is correct* are three different results, and only
the third needs labelled data to claim.
