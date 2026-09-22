#!/usr/bin/env python3
"""Chronological replay: does memory built strictly before each task help, and does accumulated experience?

    python3 -B evals/retrieval/chronology.py --dataset dist/retrieval-datasets/sqlglot.jsonl --split dev --blocks 4

Tasks of one repository are ordered by their base commit's date and replayed in that order. For each
task the clone is checked out at the base commit, the episodic store is built in memory with the
boundary pinned to the base commit and its own event excluded, and a leakage check confirms that the
fix commit is neither in the store nor reachable from the boundary. Arms, all sharing the identical
current index:

    full                       the deterministic baseline
    full+memory                gated episodic memory
    full+memory+exp-frozen     plus experience records from the first block only
    full+memory+exp-accum      plus experience accumulated from every earlier non-probe task

Experience here is ORACLE-labeled: after a task is scored, its gold target files are recorded as a
`partial` observation asserted by the harness ("benchmark gold target files"), never as verified
success, and never for probe tasks (every --probe-every-th task), whose queries and results enter
nothing. This measures whether recorded experience could help retrieval; it says nothing about an
agent's ability to acquire that experience. Results are reported per chronological block with a
paired-bootstrap 95% interval against `full`, because a rising curve alone may reflect easier later
tasks or shared file contents.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import context  # noqa: E402
import experience as experience_module  # noqa: E402
import repo_history  # noqa: E402
import repository_memory  # noqa: E402
import retrieval  # noqa: E402
from run import KS, Memo, MemoryLayer, _engine, _score, split_matches  # noqa: E402
from llm_report import interval  # noqa: E402

ARMS = ("full", "full+memory", "full+memory+exp-frozen", "full+memory+exp-accum")


def commit_time(clone, sha):
    return int(subprocess.run(["git", "-C", str(clone), "log", "-1", "--format=%ct", sha], capture_output=True, text=True, check=True).stdout)


def experience_rows(query, records, index, settings):
    """Gated experience candidates from an in-memory record list (the same code path as the packet)."""
    items = experience_module.search(query, records, index, top_k=settings["experience"]["max_records"])
    for item in items:
        item["identifier_support"] = sum(1 for t in item["matched"] if query["terms"].get(t, 0) >= 3.0)
        item["concept_matches"] = len(item["matched"]) - item["identifier_support"]
        item["resolved"] = [{"path": p, "label": "exact"} for p in item["files"]]
    rows = experience_module.candidates(items, max_records=settings["experience"]["max_records"], max_files=settings["retrieval"]["max_files_per_event"])
    decision = repository_memory.gate(items, {r["file"]: r["score"] for r in rows}, settings=settings, freshness="current", layer="experience")
    usable = decision["state"] in ("use", "use_limited") and bool(rows)
    return {"extra": {"memory_experience": rows} if usable else {}, "boost_only": ("memory_experience",) if usable and decision["state"] == "use_limited" else (),
            "weights": {"memory_experience": settings["retrieval"]["rrf_weights"]["memory_experience"]}, "state": decision["state"], "candidates": len(rows)}


def replay(tasks, clone, memory, *, blocks, probe_every, progress=True):
    scrub = context._scrubber(context.find_pack(str(ROOT)))
    memo = Memo(clone)
    config = retrieval.configure("full")
    settings = copy.deepcopy(memory.settings)
    settings["experience"]["retrieval"] = "on"
    admit = repository_memory.admission(())
    accumulated, frozen, results = [], None, []
    size = max(1, -(-len(tasks) // blocks))
    for number, task in enumerate(tasks):
        block = number // size
        if frozen is None and block >= 1:
            frozen = list(accumulated)
        subprocess.run(["git", "-C", str(clone), "checkout", "-q", "-f", "--detach", task["base_commit"]], check=True)
        diagnostics, withheld, oversized = [], [], []
        paths = context._enumerate(clone, diagnostics)
        texts, hashes, _, _ = context._scan_sources(clone, paths, (), [], memo, scrub, withheld, diagnostics, oversized)
        history = context._git_history(clone, retrieval.DEFAULTS["git"]["max_commits"])
        index = retrieval.build_index(texts, hashes, context._kind, cache=memo, history=history, config=config, path_only=oversized)
        query_text = scrub(task["query"])[:context.MAX_TASK_CHARS]
        query = retrieval.analyze_query(query_text, config)
        episodic, built = memory.prepare(clone, index, scrub, task["base_commit"])
        ids = {e["id"] for e in episodic["events"]}
        leak = {"fix_in_store": task["fix_commit"] in ids,
                "fix_reachable_from_boundary": repo_history.is_ancestor(clone, task["fix_commit"], task["base_commit"]),
                "boundary_event_in_store": task["base_commit"] in ids}
        if any(leak.values()):
            raise SystemExit(f"leakage check failed for {task['id']}: {leak}")
        git_rows = memory.candidates(query, episodic, index, "")
        arms = {"full": None, "full+memory": git_rows}
        for name, records in (("full+memory+exp-frozen", frozen or []), ("full+memory+exp-accum", accumulated)):
            rows = experience_rows(query, records, index, settings) if records else {"extra": {}, "boost_only": (), "weights": {}, "state": "unavailable", "candidates": 0}
            arms[name] = {"extra": {**git_rows["extra"], **rows["extra"]}, "boost_only": (*git_rows["boost_only"], *rows["boost_only"]),
                          "weights": {**git_rows["weights"], **rows["weights"]}, "report": {"state": rows["state"], "candidates": rows["candidates"], "files": []}}
        row = {"id": task["id"], "repo": task["repo"], "split": task["split"], "block": block, "order": number, "probe": number % probe_every == 0,
               "prior_records": len(accumulated), "targets": task["target_files"], "unreachable": [t for t in task["target_files"] if t not in texts],
               "memory_build": built, "leak": leak, "strategies": {}}
        for name, rows in arms.items():
            found = _engine(query_text, index, config, None, rows)
            scored = _score(found, task["target_files"])
            if rows:
                scored["memory"] = {"state": rows["report"]["state"], "candidates": rows["report"]["candidates"]}
            row["strategies"][name] = scored
        results.append(row)
        if not row["probe"]:
            record = experience_module.new_record(
                {"task": query_text, "category": "bug", "modified": task["target_files"], "outcome": "partial",
                 "assertions": [{"by": "host", "claim": "benchmark gold target files (oracle label, not an agent observation)"}]},
                admit=admit, scrub=scrub, hashes=index.hashes, snapshot_commit=task["base_commit"], now=commit_time(clone, task["base_commit"]))
            accumulated.append(record)
        if progress and (number % 10 == 9 or number + 1 == len(tasks)):
            print(f"  {task['repo']}: {number + 1}/{len(tasks)} (block {block}, {len(accumulated)} records)", file=sys.stderr, flush=True)
    return results


def report(results, blocks):
    lines = [f"CHRONOLOGICAL REPLAY  ({len(results)} tasks, {sum(r['probe'] for r in results)} held-out probes, {blocks} blocks)",
             f"{'Arm':<26}{'block':>6}{'n':>5}{'R@8':>7}{'All@8':>7}{'MRR':>7}{'prior':>7}"]
    for name in ARMS:
        for block in range(blocks):
            rows = [r for r in results if r["block"] == block]
            if not rows:
                continue
            mean = lambda key: statistics.fmean(r["strategies"][name][key] for r in rows)  # noqa: E731
            lines.append(f"{name:<26}{block:>6}{len(rows):>5}{mean('R@8'):>7.3f}{mean('All@8'):>7.3f}{mean('MRR'):>7.3f}"
                         f"{statistics.fmean(r['prior_records'] for r in rows):>7.0f}")
    lines.append("")
    lines.append("Paired bootstrap 95% interval of the difference from `full` over all tasks (an interval containing 0 is not evidence)")
    for name in ARMS[1:]:
        for metric in ("R@8", "All@8", "MRR"):
            low, high = interval(results, name, "full", metric)[:2]
            mean = statistics.fmean(r["strategies"][name][metric] - r["strategies"]["full"][metric] for r in results)
            lines.append(f"  {name:<26}{metric:<7} {mean:+.3f}  [{low:+.3f}, {high:+.3f}]")
    probes = [r for r in results if r["probe"]]
    if probes:
        lines.append("")
        lines.append("Held-out probes only (never recorded):")
        for name in ARMS:
            lines.append(f"  {name:<26}R@8 {statistics.fmean(r['strategies'][name]['R@8'] for r in probes):.3f}  "
                         f"All@8 {statistics.fmean(r['strategies'][name]['All@8'] for r in probes):.3f}")
    states = {name: statistics.fmean(1.0 for r in results if r["strategies"][name].get("memory", {}).get("state", "").startswith("use")) if any(
        r["strategies"][name].get("memory", {}).get("state", "").startswith("use") for r in results) else 0.0 for name in ARMS[1:]}
    lines.append("")
    lines.append("Memory used (share of tasks with a use/use_limited gate): " + ", ".join(f"{n} {v:.2f}" for n, v in states.items()))
    lines.append("Leakage checks: " + ("none violated" if not any(any(r["leak"].values()) for r in results) else "VIOLATED"))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--repos-dir", default=str(ROOT / "dist/retrieval-repos"))
    parser.add_argument("--split", default="dev", choices=("train", "validation", "test", "dev", "all"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--blocks", type=int, default=4)
    parser.add_argument("--probe-every", type=int, default=5)
    parser.add_argument("--memory-settings")
    parser.add_argument("--json")
    args = parser.parse_args(argv)
    tasks = [json.loads(line) for line in Path(args.dataset).read_text(encoding="utf-8").splitlines() if line.strip()]
    tasks = [t for t in tasks if split_matches(t, args.split)]
    repos = {t["repo"] for t in tasks}
    if len(repos) != 1:
        raise SystemExit("chronology.py replays one repository per run")
    clone = (Path(args.repos_dir) / repos.pop()).resolve()
    if not (clone / ".git").exists():
        raise SystemExit(f"Missing clone {clone}; see evals/retrieval/README.md.")
    tasks.sort(key=lambda t: (commit_time(clone, t["base_commit"]), t["id"]))
    tasks = tasks[:args.limit]
    memory = MemoryLayer(args.memory_settings, boundary="exclusive")
    started = time.perf_counter()
    results = replay(tasks, clone, memory, blocks=args.blocks, probe_every=args.probe_every)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(results), encoding="utf-8")
    print(report(results, args.blocks))
    print(f"\n{(time.perf_counter() - started):.0f} s total; memory build {memory.timing['build_ms'] / max(1, memory.timing['tasks']):.0f} ms per task")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
