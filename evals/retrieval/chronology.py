#!/usr/bin/env python3
"""Chronological replay: does memory built strictly before each task help, and does accumulated experience?

    python3 -B evals/retrieval/chronology.py --dataset dist/retrieval-datasets/sqlglot.jsonl \
        --dataset dist/retrieval-datasets/pip.jsonl --dataset dist/retrieval-datasets/networkx.jsonl --split dev --blocks 4

Every repository's tasks are ordered by their base commit's date and replayed in that order, one
repository after another, each in its own clone. For each task the clone is checked out at the base
commit, the episodic store is built in memory with the boundary pinned to the base commit and its own
event excluded, and a leakage check confirms that the fix commit is neither in the store nor reachable
from the boundary. Arms, all sharing the identical current index:

    full                       the deterministic baseline
    full+memory                gated episodic memory
    full+memory+exp-frozen     plus experience records from the first block only
    full+memory+exp-accum      plus experience accumulated from every earlier non-probe task of that repository

Experience is ORACLE-labeled and goes through the shipped experience module (`experience.build_event`,
outcome `grader_passed`, source `harness`) and the shipped memory layer (`repository_memory.experience_candidates`):
after a task is scored, its gold target files are recorded as the edited files of a harness-graded
task, never as verified success, and never for probe tasks (every --probe-every-th task), whose
queries and results enter nothing. This measures whether recorded experience could help retrieval;
it says nothing about an agent's ability to acquire that experience. Results are pooled over every
repository and reported per repository and per chronological block with paired-bootstrap intervals
against `full` (task-level, and repository-block for the pooled table), because a rising curve alone
may reflect easier later tasks or shared file contents, and a one-task difference on one repository
must not decide a verdict.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import random
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
from run import Memo, MemoryLayer, _engine, _score, split_matches  # noqa: E402
from llm_report import interval  # noqa: E402

ARMS = ("full", "full+memory", "full+memory+exp-frozen", "full+memory+exp-accum")
METRICS = ("R@5", "R@8", "All@8", "MRR")


def commit_time(clone, sha):
    return int(subprocess.run(["git", "-C", str(clone), "log", "-1", "--format=%ct", sha], capture_output=True, text=True, check=True).stdout)


def experience_rows(query, prepared, index, settings):
    """The shipped memory layer's experience path over an in-memory prepared list."""
    items, rows, decision = repository_memory.experience_candidates(query, {"prepared": prepared, "events": len(prepared)}, index, settings)
    usable = decision["state"] in ("use", "use_limited") and bool(rows)
    return {"extra": {"experience": rows} if usable else {}, "boost_only": ("experience",) if usable and decision["state"] == "use_limited" else (),
            "weights": {"experience": settings["retrieval"]["rrf_weights"]["experience"]}, "state": decision["state"], "candidates": len(rows)}


def replay(tasks, clone, memory, *, blocks, probe_every, progress=True):
    scrub = context._scrubber(context.find_pack(str(ROOT)))
    memo = Memo(clone)
    config = retrieval.configure("full")
    settings = copy.deepcopy(memory.settings)
    settings["experience"]["retrieval"] = "on"
    settings["experience"]["eligible_outcomes"] = ["grader_passed"]
    eligible = ("grader_passed",)
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
            prepared = experience_module.prepare(records, [], eligible) if records else []
            rows = experience_rows(query, prepared, index, settings) if prepared else {"extra": {}, "boost_only": (), "weights": {}, "state": "unavailable", "candidates": 0}
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
            event = experience_module.build_event(project=clone, task_id=task["id"], task=query_text, scrub=scrub, edited=task["target_files"],
                                                  outcome="grader_passed", source="harness")
            event["recorded"] = commit_time(clone, task["base_commit"])  # Recency follows the replayed clock, not today's.
            accumulated.append(event)
        if progress and (number % 10 == 9 or number + 1 == len(tasks)):
            print(f"  {task['repo']}: {number + 1}/{len(tasks)} (block {block}, {len(accumulated)} records)", file=sys.stderr, flush=True)
    return results


def _mean(rows, name, metric):
    return statistics.fmean(r["strategies"][name][metric] for r in rows) if rows else float("nan")


def _block_bootstrap(results, name, base, metric, rounds=2000):
    """Repository-block bootstrap: repositories are resampled, so a pooled interval respects the few dependence units."""
    repos = sorted({r["repo"] for r in results})
    if len(repos) < 2:
        return None
    by_repo = {repo: [r for r in results if r["repo"] == repo] for repo in repos}
    rng, deltas = random.Random(0), []
    for _ in range(rounds):
        sample = [by_repo[rng.choice(repos)] for _ in repos]
        rows = [r for block in sample for r in block]
        deltas.append(_mean(rows, name, metric) - _mean(rows, base, metric))
    deltas.sort()
    return deltas[int(0.025 * len(deltas))], deltas[int(0.975 * len(deltas)) - 1]


def report(results, blocks):
    repos = sorted({r["repo"] for r in results})
    lines = [f"CHRONOLOGICAL REPLAY  ({len(results)} tasks over {len(repos)} repositories: {', '.join(repos)}; "
             f"{sum(r['probe'] for r in results)} held-out probes; {blocks} blocks per repository)", "",
             "Pooled over every repository", f"{'Arm':<26}{'n':>5}{'R@5':>7}{'R@8':>7}{'All@8':>7}{'MRR':>7}   paired 95% interval of R@8 / MRR vs full (tasks; repositories)"]
    for name in ARMS:
        row = f"{name:<26}{len(results):>5}" + "".join(f"{_mean(results, name, m):>7.3f}" for m in METRICS)
        if name != "full":
            task_r8, task_mrr = interval(results, name, "full", "R@8")[:2], interval(results, name, "full", "MRR")[:2]
            repo_r8 = _block_bootstrap(results, name, "full", "R@8")
            row += f"   R@8 {_mean(results, name, 'R@8') - _mean(results, 'full', 'R@8'):+.3f} [{task_r8[0]:+.3f}, {task_r8[1]:+.3f}]"
            row += f" ({repo_r8[0]:+.3f}, {repo_r8[1]:+.3f})" if repo_r8 else ""
            row += f"; MRR {_mean(results, name, 'MRR') - _mean(results, 'full', 'MRR'):+.3f} [{task_mrr[0]:+.3f}, {task_mrr[1]:+.3f}]"
        lines.append(row)
    for repo in repos:
        rows = [r for r in results if r["repo"] == repo]
        lines += ["", f"{repo}  ({len(rows)} tasks)", f"{'Arm':<26}{'block':>6}{'n':>5}{'R@8':>7}{'All@8':>7}{'MRR':>7}{'prior':>7}   all blocks: R@8 diff vs full [95%]"]
        for name in ARMS:
            for block in range(blocks):
                inside = [r for r in rows if r["block"] == block]
                if not inside:
                    continue
                line = f"{name:<26}{block:>6}{len(inside):>5}{_mean(inside, name, 'R@8'):>7.3f}{_mean(inside, name, 'All@8'):>7.3f}{_mean(inside, name, 'MRR'):>7.3f}" \
                       f"{statistics.fmean(r['prior_records'] for r in inside):>7.0f}"
                if block == 0 and name != "full":
                    low, high = interval(rows, name, "full", "R@8")[:2]
                    line += f"   {_mean(rows, name, 'R@8') - _mean(rows, 'full', 'R@8'):+.3f} [{low:+.3f}, {high:+.3f}]"
                lines.append(line)
    probes = [r for r in results if r["probe"]]
    if probes:
        lines += ["", f"Held-out probes only ({len(probes)}, never recorded):"]
        for name in ARMS:
            lines.append(f"  {name:<26}R@8 {_mean(probes, name, 'R@8'):.3f}  All@8 {_mean(probes, name, 'All@8'):.3f}  MRR {_mean(probes, name, 'MRR'):.3f}")
    used = {name: statistics.fmean(1.0 if r["strategies"][name].get("memory", {}).get("state", "").startswith("use") else 0.0 for r in results)
            for name in ARMS[1:]}
    lines += ["", "Memory used (share of tasks with a use/use_limited gate): " + ", ".join(f"{n} {v:.2f}" for n, v in used.items()),
              "Leakage checks: " + ("none violated" if not any(any(r["leak"].values()) for r in results) else "VIOLATED")]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", action="append", default=[], help="JSONL produced by mine.py; repeatable, one repository each")
    parser.add_argument("--repos-dir", default=str(ROOT / "dist/retrieval-repos"))
    parser.add_argument("--split", default="dev", choices=("train", "validation", "test", "dev", "all"))
    parser.add_argument("--limit", type=int, help="First N tasks per repository after ordering")
    parser.add_argument("--blocks", type=int, default=4)
    parser.add_argument("--probe-every", type=int, default=5)
    parser.add_argument("--memory-settings")
    parser.add_argument("--json")
    parser.add_argument("--report", action="append", default=[], help="Re-print the report from saved --json files instead of running")
    args = parser.parse_args(argv)
    if not args.dataset and not args.report:
        parser.error("give --dataset (to run) or --report (to re-print)")
    results = []
    for saved in args.report:
        results += json.loads(Path(saved).read_text(encoding="utf-8"))
    started = time.perf_counter()
    memory = MemoryLayer(args.memory_settings, boundary="exclusive")
    for dataset in ([] if args.report else args.dataset):
        tasks = [json.loads(line) for line in Path(dataset).read_text(encoding="utf-8").splitlines() if line.strip()]
        tasks = [t for t in tasks if split_matches(t, args.split)]
        repos = {t["repo"] for t in tasks}
        if len(repos) != 1:
            raise SystemExit(f"{dataset}: one repository per dataset")
        clone = (Path(args.repos_dir) / repos.pop()).resolve()
        if not (clone / ".git").exists():
            raise SystemExit(f"Missing clone {clone}; see evals/retrieval/README.md.")
        tasks.sort(key=lambda t: (commit_time(clone, t["base_commit"]), t["id"]))
        results += replay(tasks[:args.limit], clone, memory, blocks=args.blocks, probe_every=args.probe_every)
    if args.json and not args.report:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(results), encoding="utf-8")
    print(report(results, args.blocks))
    if not args.report:
        print(f"\n{(time.perf_counter() - started):.0f} s total; memory build {memory.timing['build_ms'] / max(1, memory.timing['tasks']):.0f} ms per task")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
