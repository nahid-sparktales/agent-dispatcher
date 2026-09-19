---
id: research-technical-decision
name: "Research a technical decision"
summary: "Turn an open technical question into a decision with the evidence and the tradeoffs visible."
use_when: "A choice between approaches or technologies has consequences that outlast the sprint."
capabilities: research.deep, research.sources
roles: researcher, architect, planner
---

# Research a technical decision

## Steps

1. **State the decision and what would change it.** A question with no falsifiable criterion
   produces a survey, not a decision.
2. **Gather from primary sources** — the project's own documentation and repository, not a
   summary of a summary. → `deep-research`, `source-evaluation`
3. **Compare on the criteria that matter here**, including the constraints this project actually
   has. Generic comparison tables decide nothing.
4. **Make a recommendation**, with what would make it wrong.
5. **Only then** design against it (`architect`) and sequence the work (`planner`).

## What to cut

All three roles are rarely warranted. A question with an obvious answer gets a researcher and a
paragraph. Reserve the full chain for decisions that are expensive to reverse.

## Gates

- Claims are cited to something a reader can open.
- Recency is checked: a confident answer about a fast-moving library is worth less than the date on
  its source.
- The recommendation says what it is trading away, not only what it gains.
