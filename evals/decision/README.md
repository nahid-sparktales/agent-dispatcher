# Decision engine evaluation

Whether an optional decision engine actually helps is a question with an answer, and this is
where it gets one.

```bash
python3 evals/decision/run.py                  # the offline baseline — free, no network
python3 evals/decision/run.py --engine both    # add Jev; needs your own credential
python3 evals/decision/run.py --engine jev --json out.json
```

## Fixtures

| File | Cases | What it measures |
| --- | --- | --- |
| `agents.json` | 162 | which role owns a task, across all 27 roles |
| `skills.json` | 24 | which skills from a role's own loadout the task turns on |
| `tools.json` | 20 | which registered servers are relevant |

Every routing case carries `expected` (the single best owner), `acceptable` (every defensible
owner) and `not_routes` (owners that would be clearly wrong), and one of four kinds:

- **obvious** — unmistakably one role's territory.
- **near-neighbour** — a sibling role looks right and is not. `debugger` vs `implementer`,
  `architect` vs `planner`, `database-engineer` vs `data-engineer`, `reviewer` vs `tester`,
  `devops-release` vs `incident-responder`, `security-auditor` vs `reviewer`. Two thirds of the
  set, because telling close specialist territories apart is the actual job.
- **ambiguous** — several owners are genuinely defensible. Scored against `acceptable`, because
  forcing one gold label on a real tie measures the fixture, not the engine.
- **negative** — a keyword matcher sends it to the wrong role; the gold is elsewhere.

Skill and tool cases carry `required`, `acceptable` and `irrelevant`. The last one is what makes
them measure **precision**: a system that selects every candidate has perfect recall and no
value, and `irrelevant` is how that shows up as a number.

Every id in every fixture is validated against the canonical registry by `test_decision.py`, so a
renamed role or a removed skill fails the build rather than quietly scoring zero.

## Engines

`default` is `LexicalDecisionEngine` — inverse-frequency term overlap against role metadata. It
is a **measurement floor**, not what a real installation does. The production default engine
hands agent routing to the model, which this harness cannot score offline. Every report repeats
that caveat, and so should anyone quoting a number from it.

`jev` is the real engine through whichever provider is configured. It costs money, billed to the
account that owns the key, and is not run without one — the report says `not run`, which is not
the same as `passed`.

## Reading the output

Beyond top-1 and acceptable rates, the report carries per-kind breakdowns (obvious cases are
supposed to be easy; near-neighbour accuracy is the informative number), latency, failures,
fallbacks, and **observed accuracy per confidence band**. That last table is the only honest
basis for a routing threshold. `decision/config.py` carries the thresholds derived from it, with
the numbers in the comment; [docs/jev.md](../../docs/jev.md) carries the table and the results.

To re-derive a threshold instead of trusting the committed one:

```bash
AGENT_DISPATCHER_DECISION_THRESHOLDS=skill_relevance=0.7 python3 evals/decision/run.py --engine jev
```

Results are local. Nothing is sent anywhere, and no eval output is committed — the registry
digest in every report is there so a stale number can be spotted rather than trusted.

## Known limits

- The baseline is a keyword floor, so the gap to Jev overstates the gap to production.
- There is no end-to-end comparison yet — whether a route produces better *work* rather than a
  better label. The fixture schema supports it; the runs do not exist.
- 162 cases over 27 roles is 4 to 9 gold labels each, so macro numbers lean on the best-covered
  roles.
- A handful of fixtures paraphrase the registry's own `use_when` lines, which inflates accuracy
  on those cases. They were left alone rather than tuned toward the answer.

## Adding cases

Add to the relevant file and run `python3 test_decision.py`. A new role needs at least one
obvious case and one near-neighbour case against whichever role it is easiest to confuse with;
the suite fails if any role has no gold label anywhere.
