# Verification

These words are not interchangeable, and most of this pack exists to keep them apart:

```
created  ≠  executed  ≠  tested  ≠  reviewed  ≠  deployed  ≠  verified
```

- A migration **file existing** does not mean the migration ran.
- A migration **running** does not mean the data is correct.
- A page **compiling** does not mean the interface works.
- A test **being written** does not mean it passed.
- A deployment command **succeeding** does not mean the service is healthy.
- A reviewer **finding nothing** does not prove the system is secure.

## The matrix

The minimum evidence for each kind of work, **when the tooling to produce it exists**. When it does
not, the agent says which check could not be performed — it does not quietly downgrade the claim.

| Work | Minimum verification | Skill |
| --- | --- | --- |
| UI | Render the changed route, operate the controls, check desktop and mobile, read the console | `browser-verification` |
| UI across states | States × viewports × themes, or comparison against a baseline | `visual-verification` |
| Accessibility | Automated scan **plus** keyboard path and focus order — a scanner alone catches roughly a third | `accessibility-verification` |
| API | Success and failure paths, auth failure, contract test | `api-contract-verification` |
| Database | Migration run on realistic data, row counts, checksums, constraint checks, rollback rehearsed | `database-migration-verification` |
| Bug fix | The original reproduction re-run, plus a regression test confirmed to fail without the fix | `regression-testing` |
| Performance | Baseline and comparable after-measurement, same conditions, not one fast run | `performance-profiling` |
| Security fix | The original boundary re-tested with the input that exposed it — by someone who did not write the fix | `secure-code-review` |
| Deployment | The revision actually serving, health signals, a smoke path — not "the command returned 0" | `release-verification` |
| Documentation | Source-backed reports: verify citations and claims; runnable guides: execute relevant commands/examples when available | `documentation-verification` |
| Agent or prompt change | A representative eval suite, with the regression detected | `agent-evals` |
| MCP integration | Success, failure, and authorization-failure paths | `api-contract-verification` |

## Degrading honestly

Implementation checks can use the shared [task receipt helper](../skills/agent-dispatcher/VERIFICATION.md).
It records command outcomes and file fingerprints, then reports whether the result still
matches the workspace. Inspect immediately before reporting; later changes require affected
checks to be rerun. Zero tests, unknown counts, failed checks, denied/not-run notes and stale
results are distinct. A receipt does not prove browser behavior, external dependency state,
cleanup or whole-task completion. It is editable local evidence, not a security attestation.
No observer or automatic test execution is enabled. By default, an authorized check uses a
private temporary receipt and verifies removal before returning. Explicit `--receipt` paths
remain available for multi-check tasks; `show --cleanup` inspects and removes only the owned
receipt, never its parent. Unexpected files, replaced paths, symlinks and failed removal produce
an unresolved cleanup report. Abrupt process termination can still leave files; no background
sweep is installed. This cleanup covers Dispatcher state, not files created by a test command.

For preservation claims, add `--audit` to the first context preparation when temporary storage
is authorized. Finish the returned audit before reporting, supplying the actual permitted edit
paths. It compares against the task's starting files rather than Git HEAD, includes untracked
and ignored helper caches, and preserves pre-existing edits in the baseline. The report names
added, modified, deleted and out-of-scope files. `.git` internals are outside its stated scope;
exclusions, unreadable files and bounds prevent a blanket preservation claim. Finishing also
removes the owned audit state. Without a baseline, disclose the gap instead of inventing one.

Final summaries default to ELI5 succinct: a brief explanation of the change, observed results
and remaining gaps. Detailed output expands the evidence; it cannot upgrade uncertainty.

The failure mode this pack cares most about is a confident report of a check that never ran.

> **Wrong:** "UI verified successfully."
> **Right:** "Source-level checks completed; rendered browser verification was unavailable, so the
> interface is unverified."

Same shape everywhere: Context7 absent → read official documentation through the browser and cite
it. Figma not connected → work from the repository's tokens and current implementation, and never
invent what a design says. A specialized skill not installed → use the role's own method and say so.

An optional enhancement being missing is never a reason to fail work that is otherwise achievable.

## Independence

A verifier must not carry the role that produced the work. `implementer` writes; `reviewer` or
`tester` judges. When the same session produced both, that is a self-check and the report says so.

This matters most for security: the author of a remediation does not approve their own fix.

## Uncertain mutations

```
attempt → timeout or uncertain result → inspect actual state → determine whether it happened
        → retry only when safe
```

Never retry a mutation blind. It matters most for deployment, messages, tickets, database writes,
cloud resources, payments and publishing — the actions where a duplicate is as bad as a failure.
