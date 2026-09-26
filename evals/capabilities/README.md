# Capability intelligence: offline demonstration and microbenchmark

```sh
python3 -B evals/capabilities/demo.py            # human-readable walkthrough
python3 -B evals/capabilities/demo.py --json     # machine-readable summary
python3 -B evals/capabilities/bench.py --rounds 50
```

The demo uses the real modules against a fake host that it builds in a temporary home and then removes. The
fake host has a Claude configuration, plugins, a project and a PATH containing only a fixture binary. The
demo needs no model, network, key or installed client.

The demo shows eight steps:

1. **Inventory.** It lists fixture skills, plugins and CLIs, and synthetic host observations
   (`fixtures/observations.json`). Hooks, dynamic context commands and binaries are never run; sentinel
   files prove it.
2. **Health states.** Distinct states appear: valid guidance, broken metadata, guidance with an absent
   optional CLI, auth-required, callable-but-untested, and a policy-disabled item.
3. **Production route.** A production database diagnosis keeps the Database Engineer role. The failed
   preferred connection has no equivalent fallback: a staging connection targets a different environment,
   and a local CLI has no established target. The plan therefore reports a no-connection route with its
   limit. A staging task binds its equivalent connection.
4. **Discovery.** It searches `fixtures/offline-source.json`. Remote sources are disabled and never
   contacted.
5. **Quarantine and static review.** Nothing is executed or installed. The "popular" risky package lands
   in `static_review_only`.
6. **Experiment.** It prepares and validates an experiment with zero model calls. The live launch is
   refused because live evaluation is disabled. Paired **synthetic** records go through the real analysis:
   one controlled-mode compliance failure invalidates the primary estimate.
7. **Recommendation.** The model/host/effort-scoped recommendation is "use no additional skill", because
   synthetic evidence never counts.
8. **Governed proposal.**
   - Refusals: a proposal from a synthetic report, a global scope from a repository proposal, and a
     test-only runner's report in a production namespace.
   - In a test namespace: approval, promotion, adoption into a temporary target, then rollback to the base
     generation, after which adoption is refused again.

Every number in step 6 is fixture data labelled `SYNTHETIC FIXTURE DEMONSTRATION`. The demo proves wiring,
not that any skill helps.

`bench.py` measures the existing loadout lookup, the context gate, a cold passive inspection and a cached
resolution. It reports the median and p95 and the environment. Results for one run are in
[docs/capability-intelligence.md](../../docs/capability-intelligence.md#measured-overhead).

The native runner's skill arms are exercised offline by `tests/e2e/test_skill_arms.py` with a fake client:
- staging and cleanup
- exposure accounting
- pair reconciliation
- blind A/B packets
- the report path
