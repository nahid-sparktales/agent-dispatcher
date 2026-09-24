"""Offline retrieval diagnostics on pinned repository snapshots: where do evaluator-held labels rank, per arm?

Each arm runs in its own interpreter against its own code tree, so old and new helper code never share a process. The
worker calls context.select_context as the helper does (parser cache off, deep index off) and records the engine's full
ranking, retrieval.run(...)["ranked"]. Labels are read only by this parent process; workers never see them.
No model or network call: workers get a scratch HOME/XDG/TMPDIR and no AGENT_DISPATCHER_* variables, so the LLM,
memory and learning layers read no user settings and stay at their offline defaults.

usage: python3 -B evals/retrieval/snapshot_diag.py --snapshots DIR [DIR ...] --queries Q.json --labels L.json
       --arms ARMS.json --home SCRATCH --out OUT.json [--ks 1,3,5,8,20] [--role implementer] [--size standard]
       python3 -B evals/retrieval/snapshot_diag.py --self-check
Q.json     {"<snapshot dir name>": [{"id": "...", "text": "..."}, ...]}
L.json     {"<snapshot dir name>": {"<group>": ["relative/path", ...], ...}}  metrics per group and for their union "all"
ARMS.json  {"<arm>": {"code": "<package root>", "retrieval": "auto" | "<strategy>", "overrides": {<configure overrides>}}}
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def _worker():
    spec = json.load(sys.stdin)
    sys.path.insert(0, spec["code"])
    import context  # noqa: E402  (the arm's own code tree)
    load = context._sibling
    engine = load("retrieval")
    context._sibling = lambda name: engine if name == "retrieval" else load(name)  # One patched engine namespace.
    run, build, configure = engine["run"], engine["build_index"], engine["configure"]
    seen = {}

    def timed(fn, key):
        def call(*args, **kwargs):
            start = time.perf_counter()
            out = fn(*args, **kwargs)
            seen[key] = round((time.perf_counter() - start) * 1000, 1)
            if key == "run_ms":
                seen.setdefault("outcomes", []).append(out)
            return out
        return call
    engine["run"], engine["build_index"] = timed(run, "run_ms"), timed(build, "index_ms")
    if spec.get("overrides"):
        engine["configure"] = lambda strategy="full", overrides=None: configure(strategy, engine["_merge"](overrides or {}, spec["overrides"]))
    stdout, sys.stdout = sys.stdout, sys.stderr  # Only the result JSON goes to stdout.
    rows = []
    for job in spec["jobs"]:
        seen.clear()
        start = time.perf_counter()
        result = context.select_context(job["snapshot"], job["text"], role=spec["role"], size=spec["size"], pack=spec["code"],
                                        parser_cache=False, retrieval=spec["retrieval"], repository_index="off")
        wall = round((time.perf_counter() - start) * 1000, 1)
        outcomes = seen.get("outcomes") or []
        if len(outcomes) != 1:
            raise SystemExit(f"expected one engine run, saw {len(outcomes)}: {result.get('diagnostics')}")
        outcome = outcomes[0]
        rows.append({"ranked": [row["path"] for row in outcome["ranked"]], "packet_rows": [row["path"] for row in result["context"]],
                     "run_ms": seen["run_ms"], "index_ms": seen.get("index_ms"), "select_ms": wall,
                     "engine_latency_ms": (outcome.get("trace") or {}).get("latency_ms"),
                     "profile": (outcome.get("plan") or {}).get("profile"), "diagnostics": result.get("diagnostics", [])})
    json.dump(rows, stdout)


def _metrics(ranked, labels, ks):
    position = {path: rank for rank, path in enumerate(ranked, 1)}
    ranks = {path: position.get(path) for path in labels}
    found = sorted(rank for rank in ranks.values() if rank)
    return {"n_labels": len(labels), "ranks": ranks, "rr": 1 / found[0] if found else 0.0,
            "hit": {k: int(bool(found) and found[0] <= k) for k in ks},
            "recall": {k: sum(1 for rank in found if rank <= k) / len(labels) if labels else None for k in ks}}


def _check():
    m = _metrics(["a", "x", "b"], ["b", "a", "z"], [1, 2, 3])
    assert m["ranks"] == {"b": 3, "a": 1, "z": None} and m["rr"] == 1.0, m
    assert m["hit"] == {1: 1, 2: 1, 3: 1} and m["recall"] == {1: 1 / 3, 2: 1 / 3, 3: 2 / 3}, m
    assert _metrics(["x"], ["a"], [1])["rr"] == 0.0 and _mean([None, 1, 0]) == 0.5
    print("ok")


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--snapshots", nargs="+", required=True)
    parser.add_argument("--queries", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--arms", required=True)
    parser.add_argument("--home", required=True, help="scratch directory for the workers' HOME, XDG_* and TMPDIR")
    parser.add_argument("--out", required=True)
    parser.add_argument("--ks", default="1,3,5,8,20")
    parser.add_argument("--role", default="implementer")
    parser.add_argument("--size", default="standard")
    args = parser.parse_args(argv)
    ks = [int(k) for k in args.ks.split(",")]
    queries, labels, arms = (json.loads(Path(p).read_text()) for p in (args.queries, args.labels, args.arms))
    snapshots = {Path(p).name: str(Path(p).resolve()) for p in args.snapshots}
    home = Path(args.home).resolve()
    env = {k: v for k, v in os.environ.items() if not k.startswith("AGENT_DISPATCHER_")}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"), XDG_CACHE_HOME=str(home / ".cache"),
               XDG_STATE_HOME=str(home / ".state"), TMPDIR=str(home / "tmp"))
    for name in ("tmp", ".config", ".cache", ".state"):
        (home / name).mkdir(parents=True, exist_ok=True)
    jobs = [(name, query) for name in snapshots for query in queries.get(name, [])]
    out = {"ks": ks, "role": args.role, "size": args.size, "arms": {}}
    for arm, spec in arms.items():
        payload = {"code": spec["code"], "retrieval": spec.get("retrieval", "auto"), "overrides": spec.get("overrides") or {},
                   "role": args.role, "size": args.size, "jobs": [{"snapshot": snapshots[n], "text": q["text"]} for n, q in jobs]}
        done = subprocess.run([sys.executable, "-B", __file__, "--worker"], input=json.dumps(payload), capture_output=True,
                              text=True, env=env, check=False)
        if done.returncode:
            raise SystemExit(f"arm {arm} failed: {done.stderr[-2000:]}")
        rows = []
        for (name, query), got in zip(jobs, json.loads(done.stdout)):
            groups = {**labels[name], "all": sorted(set().union(*labels[name].values()))}
            rows.append({"snapshot": name, "query": query["id"], "ranked_length": len(got["ranked"]), "top20": got["ranked"][:20],
                         **{key: got[key] for key in ("packet_rows", "run_ms", "index_ms", "select_ms", "engine_latency_ms", "profile", "diagnostics")},
                         "metrics": {group: _metrics(got["ranked"], paths, ks) for group, paths in groups.items()}})
        groups = sorted({g for row in rows for g in row["metrics"]})
        aggregate = {group: {"n_queries": sum(1 for r in rows if group in r["metrics"]),
                             "mrr": _mean([r["metrics"][group]["rr"] for r in rows if group in r["metrics"]]),
                             "hit": {k: _mean([r["metrics"][group]["hit"][k] for r in rows if group in r["metrics"]]) for k in ks},
                             "recall": {k: _mean([r["metrics"][group]["recall"][k] for r in rows if group in r["metrics"]]) for k in ks}}
                     for group in groups}
        runs = sorted(r["run_ms"] for r in rows)
        out["arms"][arm] = {"spec": spec, "aggregate": aggregate, "rows": rows,
                            "latency_ms": {"retrieval_run_median": runs[len(runs) // 2] if runs else None,
                                           "retrieval_run_min": runs[0] if runs else None, "retrieval_run_max": runs[-1] if runs else None}}
    Path(args.out).write_text(json.dumps(out, indent=1) + "\n")
    for arm, data in out["arms"].items():
        line = " ".join(f"{g}: MRR {a['mrr']:.3f} hit@8 {a['hit'][8] if 8 in ks else '-'} R@8 {a['recall'][8] if 8 in ks else '-'}"
                        for g, a in data["aggregate"].items())
        print(f"{arm:24} {line}")


if __name__ == "__main__":
    {"--worker": _worker, "--self-check": _check}.get(sys.argv[1] if sys.argv[1:] else "", main)()
