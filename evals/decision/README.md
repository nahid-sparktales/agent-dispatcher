# Decision engine evaluation

Whether an optional decision engine actually helps is a question with an answer, and this is
where it gets one.

```bash
python3 evals/decision/run.py                  # the keyword baseline — free, no network
python3 evals/decision/run.py --engine claude --routes evals/decision/routes-claude.json
python3 evals/decision/run.py --engine all --routes evals/decision/routes-claude.json
```

`--engine` is repeatable; `both` is default+jev and `all` adds claude. Only `jev` costs money,
and only when you supply a credential.

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
  `devops-release` vs `incident-responder`, `security-auditor` vs `reviewer`. A third of the set
  on its own — two thirds of it is non-obvious in some way — because telling close specialist
  territories apart is the actual job.
- **ambiguous** — several owners are genuinely defensible. Scored against `acceptable`, because
  forcing one gold label on a real tie measures the fixture, not the engine.
- **negative** — a keyword matcher sends it to the wrong role; the gold is elsewhere.

Skill and tool cases carry `required`, `acceptable` and `irrelevant`. The last one is what makes
them measure **precision**: a system that selects every candidate has perfect recall and no
value, and `irrelevant` is how that shows up as a number.

Every id in every fixture is validated against the canonical registry by `tests/test_decision.py`, so a
renamed role or a removed skill fails the build rather than quietly scoring zero.

## Engines

`default` is `LexicalDecisionEngine` in `baseline.py` — inverse-frequency term overlap against
role metadata. A **measurement floor**: what the numbers look like with no model at all.

`claude` is the production default path, the model reading the router's own catalog. It is not a
service this harness can call, so `replay.py` scores routes recorded out of band and handed in
with `--routes`. `routes-claude.json` is one such run, with its method written down: one focused
subagent per fixture, given the dispatcher's routing rules and role catalog verbatim and nothing
else. That is a close reconstruction, not the thing itself — a real session also carries the
conversation — and its latency is not comparable, because in production routing costs no extra
call. Record your own the same way and pass it in.

`jev` is the real engine through whichever provider is configured. It costs money, billed to the
account that owns the key, and is not run without one — the report says `not run`, which is not
the same as `passed`.

The comparison is what set the shipped defaults, and it did not go the way the integration
would have liked: Claude matched or beat Jev on every decision, so `DEFAULT_SCOPES` in
`decision/config.py` is all-off and Jev installs inert. What survives for Jev is latency and
cost, not quality. [docs/jev.md](../../docs/jev.md) carries the table and the caveats.

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

- There is no end-to-end comparison yet — whether a route produces better *work* rather than a
  better label. The fixture schema supports it; the runs do not exist.
- The recorded Claude answers are a reconstruction of the default path, not a capture of it:
  one focused subagent per case, no conversation, no competing work. A real in-session
  dispatcher could do worse, which cuts against the conclusion drawn from them.
- Tool selection is 20 cases. The Claude-Jev gap there is noise and is reported as a tie.
- Nothing here measures cost or throughput at volume, which is the case for Jev that remains.
- 162 cases over 27 roles is 4 to 9 gold labels each, so macro numbers lean on the best-covered
  roles.
- A handful of fixtures paraphrase the registry's own `use_when` lines, which inflates accuracy
  on those cases. They were left alone rather than tuned toward the answer.

## Adding cases

Add to the relevant file and run `python3 -B -m tests.test_decision`. A new role needs at least one
obvious case and one near-neighbour case against whichever role it is easiest to confuse with;
the suite fails if any role has no gold label anywhere.
