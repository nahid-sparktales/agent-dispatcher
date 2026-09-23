# Procedural learning: offline fixture demonstration

```sh
python3 -B evals/learning/demo.py            # human-readable walkthrough
python3 -B evals/learning/demo.py --json     # machine-readable summary
```

The demo runs the complete lifecycle on four synthetic repository families defined in
`fixtures/families.json` (three enrolled, one held out) with the real storage, validation,
composition, evaluation and lifecycle code, inside an isolated cache and config home that it
creates and removes. It needs no model, network, key or installed client and writes nothing to the
user's real state.

What it demonstrates, in order:

1. explicit fixture observations recorded against experience events (`feedback_class: synthetic_fixture`);
2. a review that finds the recurring weak-verification failure and the history-helped pattern, and
   reports `no_change` for a family that only paraphrased one task and for tasks where history was irrelevant;
3. a repository-scoped skill overlay proposal imported as untrusted data and validated (Tier A);
4. a candidate that would remove verification, one that claims approval, one that targets a protected
   role section and one that inserts an executable step, each rejected with a bounded reason;
5. Tier B component checks and a Tier C evaluation with the labeled `fake_test_runner`; approval and
   promotion succeed only because the store is a test namespace, and the same report is refused in a
   production namespace;
6. effective guidance changing for the matching debugger task and staying pristine for others;
7. a dependency invalidation (revoking a parent takes its refinement with it) with safe fallback to the base,
   then a rollback to the earlier compatible generation;
8. a sanitized generalization across the three independent enrolled families and a held-out transfer
   specification whose synthetic outcomes show negative transfer, so the global candidate fails;
9. an efficiency objective where the cheaper recipe is less correct and therefore fails its margin;
10. a forgotten support event whose descendants lose support and leave the active generation.

Synthetic evidence never enters a production library: `propose` and `promote` refuse it outside a
test namespace, and the demo's test namespace is created through the Python API only. Nothing here
measures a real agent; the fake runner consumes supplied outcomes to exercise state transitions.
