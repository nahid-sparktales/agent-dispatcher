#!/usr/bin/env python3
"""Chronological sequence benchmark: does a maintained deep index, and experience from earlier tasks, localize better?

    python3 -B evals/retrieval/sequence.py --dataset dist/retrieval-datasets/sqlglot.jsonl --split test \\
        --conditions basic,indexed,warm-experience --experience-source oracle --json dist/sequence.json

Each repository's tasks are ordered by the timestamp of their base commit and advanced through the same
predetermined snapshots for every condition. Before task t only the repository as of its base commit and
experience from tasks strictly before t exist. Conditions:

    basic            the shipped retrieval (`full`): a fresh in-memory index of the scan for every task
    indexed          a deep index built at the first snapshot and refreshed at each later one; experience
                     recorded but never used
    warm-experience  exactly `indexed` plus eligible experience accumulated earlier in the same sequence

The offline benchmark has no agent, so its experience must come from somewhere: `--experience-source oracle`
records each task's gold target files as an accepted outcome. That arm is an ORACLE DIAGNOSTIC of the memory
mechanism, not evidence that Dispatcher learned from real work. `--experience-source events FILE` replays
events recorded from actual trials (one JSON object per line: task_id, query, edited, outcome) instead.

Stock (a native client without Dispatcher) has no retrieval to measure here; it exists only in the
end-to-end runner. No model is called. Private state for each arm lives in a temporary directory that is
removed at the end unless --state-dir names one.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import context  # noqa: E402
import experience  # noqa: E402
import repo_builder  # noqa: E402
import repo_store  # noqa: E402
import retrieval  # noqa: E402
from evals.retrieval import run as offline  # noqa: E402

CONDITIONS = ("basic", "indexed", "warm-experience")
THIRDS = ("early", "middle", "late")


def commit_time(clone, sha):
    return int(subprocess.run(["git", "-C", str(clone), "log", "-1", "--format=%ct", sha], capture_output=True, text=True, check=True).stdout)


def families(tasks):
    """Near-duplicate grouping: tasks that modify the same set of target files form one fix family."""
    for task in tasks:
        task["family"] = hashlib.sha256("\0".join(sorted(task["target_files"])).encode()).hexdigest()[:12]
    seen = Counter()
    for task in tasks:
        task["family_repeat"] = seen[task["family"]] > 0
        seen[task["family"]] += 1
    return tasks


class Arm:
    """One condition's private state for one repository sequence: an index store and an experience store."""

    def __init__(self, name, directory, scrub, use_experience, eligible):
        self.name, self.directory, self.scrub = name, Path(directory), scrub
        self.use_experience, self.eligible = use_experience, tuple(eligible)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.built = False
        self.setup = Counter()
        self.setup_ms = 0.0

    def advance(self, clone):
        """Build at the first snapshot, refresh at every later one; setup cost is accounted apart from queries."""
        started = time.perf_counter()
        with repo_store.IndexStore(self.directory, create=not self.built) as store:
            report = repo_builder.Builder(clone, store, self.scrub).run(mode="refresh" if self.built else "build")
        self.built = True
        self.setup_ms += (time.perf_counter() - started) * 1000
        for key in ("reads", "parses", "records_reused", "bytes_read", "swept", "edges_written"):
            self.setup[key] += report["counters"].get(key, 0)
        self.setup["model_calls"] += report["model_calls"]
        self.setup["publications"] += int(report["published"])
        return report

    def index(self, texts, hashes, oversized, config, stats):
        """The query-time wiring the context helper uses: store records, reused partners, attached experience."""
        with repo_store.IndexStore(self.directory, readonly=True) as store:
            history = store.meta("history") or {}
            head = repo_builder.git_state(Path(store.meta("project")["path"]))["head"]
            partners = store.partners_map() if history.get("head") and history["head"] == head else None
            index = retrieval.build_index(texts, hashes, context._kind, config=config, stats=stats, path_only=oversized, store=store, partners=partners)
        attached = 0
        if self.use_experience:
            try:
                with repo_store.ExperienceStore(self.directory, readonly=True) as events:
                    attached = experience.attach(index, events.events(), events.corrections(), self.eligible)
            except ValueError:
                attached = 0
        return index, attached

    def record(self, clone, task, edited, outcome):
        event = experience.build_event(project=clone, task_id=task["id"], task=task["query"], scrub=self.scrub, edited=edited,
                                       outcome=outcome, source="harness")
        with repo_store.ExperienceStore(self.directory, create=True) as store:
            return experience.record(store, event, self.eligible)


def evaluate(tasks, clone, conditions, *, state_dir, experience_source="oracle", events=None, eligible=("grader_passed",),
             overrides=None, progress=True):
    scrub = context._scrubber(context.find_pack(str(ROOT)))
    memo = offline.Memo(clone)
    configs = {"basic": retrieval.configure("full", overrides), "indexed": retrieval.configure("full", overrides),
               "warm-experience": retrieval.configure("full+experience", overrides)}
    arms = {name: Arm(name, Path(state_dir) / name, scrub, name == "warm-experience", eligible) for name in conditions if name != "basic"}
    replay = defaultdict(list)
    for event in events or ():
        replay[event["task_id"]].append(event)
    results = []
    for number, task in enumerate(tasks, 1):
        subprocess.run(["git", "-C", str(clone), "checkout", "-q", "-f", "--detach", task["base_commit"]], check=True)
        setup = {}
        for name, arm in arms.items():
            report = arm.advance(clone)
            setup[name] = {"published": report["published"], "counters": report["counters"], "elapsed_ms": report["elapsed_ms"],
                           "coverage": {k: report["coverage"].get(k) for k in ("discovered", "indexed", "pending", "complete_within_policy")}}
        started = time.perf_counter()
        diagnostics, withheld, oversized = [], [], []
        paths = context._enumerate(clone, diagnostics)
        texts, hashes, _, _ = context._scan_sources(clone, paths, (), [], memo, scrub, withheld, diagnostics, oversized)
        scan_ms = (time.perf_counter() - started) * 1000
        query = scrub(task["query"])[:context.MAX_TASK_CHARS]
        history = context._git_history(clone, retrieval.DEFAULTS["git"]["max_commits"]) if "basic" in conditions else None
        row = {key: task[key] for key in ("id", "repo", "split", "query_source", "names_target", "family", "family_repeat")}
        row.update(position=number, targets=task["target_files"], unreachable=[t for t in task["target_files"] if t not in texts],
                   universe=len(texts), scan_ms=scan_ms, setup=setup, conditions={})
        for name in conditions:
            stats = {}
            if name == "basic":
                index = retrieval.build_index(texts, hashes, context._kind, cache=memo, history=history, config=configs[name], stats=stats, path_only=oversized)
                attached = 0
            else:
                index, attached = arms[name].index(texts, hashes, oversized, configs[name], stats)
            found = offline._engine(query, index, configs[name])
            scored = offline._score(found, task["target_files"])
            scored.update(any_hit=scored["R@8"] > 0, candidate_recall=sum(t in found["ranked"] for t in task["target_files"]) / len(task["target_files"]),
                          experience_attached=attached, experience_candidates=len(found["lists"].get("experience", ())),
                          experience_hit=sum(t in found["lists"].get("experience", ()) for t in task["target_files"]) / len(task["target_files"]),
                          record_hits=stats.get("record_hits", 0), record_misses=stats.get("record_misses", 0), index_ms=stats.get("index_ms"),
                          top=found["ranked"][:20])
            row["conditions"][name] = scored
        # Record each arm's own experience before advancing: strictly before-t evidence for the next task.
        recorded = {}
        for name, arm in arms.items():
            if experience_source == "oracle":
                recorded[name] = arm.record(clone, task, task["target_files"], "grader_passed")
            elif experience_source == "events":
                for event in replay.get(task["id"], ()):
                    recorded[name] = arm.record(clone, dict(task, query=event.get("query", task["query"])), event["edited"], event["outcome"])
        row["recorded"] = {name: {"outcome": r["outcome"], "eligible": r["eligible"], "stored": r["stored"]} for name, r in recorded.items()}
        results.append(row)
        if progress and (number % 10 == 0 or number == len(tasks)):
            print(f"  {task['repo']}: {number}/{len(tasks)}", file=sys.stderr, flush=True)
    for name, arm in arms.items():
        results.append({"repo": tasks[0]["repo"], "arm_summary": name, "setup_ms_total": round(arm.setup_ms, 1), "setup_counters": dict(arm.setup),
                        "disk_bytes": sum(p.stat().st_size for p in arm.directory.iterdir() if p.is_file())})
    return results


# ---------------------------------------------------------------- reporting

METRICS = ("R@1", "R@3", "R@5", "R@8", "R@10", "MRR", "candidate_recall", "ctx_recall", "any_hit")


def _mean(rows, key):
    values = [r[key] for r in rows if r.get(key) is not None]
    return statistics.fmean(values) if values else float("nan")


def table(results, conditions, title):
    rows = [r for r in results if "conditions" in r]
    if not rows:
        return f"{title}: no tasks"
    lines = [f"{title}  ({len(rows)} tasks, {sum(r['family_repeat'] for r in rows)} family repeats)",
             f"{'Condition':<18}" + "".join(f"{m:>9}" for m in METRICS) + f"{'files':>7}{'tok':>7}{'ms':>8}{'exp':>6}"]
    lines.append("-" * len(lines[1]))
    for name in conditions:
        scored = [r["conditions"][name] for r in rows if name in r["conditions"]]
        if not scored:
            continue
        active = sum(1 for s in scored if s["experience_candidates"])
        lines.append(f"{name:<18}" + "".join(f"{_mean(scored, m):>9.3f}" for m in METRICS)
                     + f"{_mean(scored, 'files'):>7.1f}{_mean(scored, 'tokens'):>7.0f}{_mean(scored, 'ms'):>8.1f}{active:>6}")
    return "\n".join(lines)


def thirds(results, conditions):
    rows = [r for r in results if "conditions" in r]
    out = []
    by_repo = defaultdict(list)
    for r in rows:
        by_repo[r["repo"]].append(r)
    for repo, group in sorted(by_repo.items()):
        size = len(group)
        for index, label in enumerate(THIRDS):
            part = group[index * size // 3:(index + 1) * size // 3] if size >= 3 else (group if index == 0 else [])
            if part:
                out.append(f"{repo} {label} ({len(part)} tasks): " + "  ".join(f"{c} R@8 {_mean([r['conditions'][c] for r in part if c in r['conditions']], 'R@8'):.3f}" for c in conditions))
    return "\n".join(out)


def paired(results, conditions, base="basic", seed=0, samples=1000):
    """Paired differences per task, with a block bootstrap over repositories (sequences are the dependence unit)."""
    rows = [r for r in results if "conditions" in r]
    lines = []
    repos = sorted({r["repo"] for r in rows})
    rng = random.Random(seed)
    for name in conditions:
        if name == base:
            continue
        pairs = [(r["repo"], r["conditions"][name]["R@8"] - r["conditions"][base]["R@8"]) for r in rows if name in r["conditions"] and base in r["conditions"]]
        if not pairs:
            continue
        better = sum(d > 0 for _, d in pairs)
        worse = sum(d < 0 for _, d in pairs)
        mean = statistics.fmean(d for _, d in pairs)
        by_repo = defaultdict(list)
        for repo, d in pairs:
            by_repo[repo].append(d)
        boots = []
        for _ in range(samples):
            chosen = [rng.choice(repos) for _ in repos]
            values = [d for repo in chosen for d in by_repo.get(repo, [])]
            if values:
                boots.append(statistics.fmean(values))
        boots.sort()
        low, high = (boots[int(0.025 * len(boots))], boots[int(0.975 * len(boots)) - 1]) if boots else (float("nan"), float("nan"))
        negative = [r["id"] for r in rows if name == "warm-experience" and "indexed" in r["conditions"] and name in r["conditions"]
                    and r["conditions"][name]["R@8"] < r["conditions"]["indexed"]["R@8"]]
        lines.append(f"{name} - {base}: mean R@8 difference {mean:+.3f} over {len(pairs)} paired tasks ({better} better, {worse} worse); "
                     f"repository block bootstrap 95% [{low:+.3f}, {high:+.3f}] over {len(repos)} repositories"
                     + (f"; negative transfer versus indexed on {len(negative)} tasks" if name == "warm-experience" else ""))
    return "\n".join(lines)


def costs(results, conditions):
    """Setup cost apart from query cost. No model was called, so monetary cost is unknown, never zero."""
    rows = [r for r in results if "conditions" in r]
    summaries = {r["arm_summary"]: r for r in results if "arm_summary" in r}
    lines = []
    for name in conditions:
        scored = [r["conditions"][name] for r in rows if name in r["conditions"]]
        if not scored:
            continue
        summary = summaries.get(name, {})
        setup_ms = summary.get("setup_ms_total", 0.0)
        query_ms = sum(s["ms"] for s in scored)
        lines.append(f"{name}: {len(scored)} tasks; steady-state query {query_ms / len(scored):.1f} ms/task; "
                     f"setup {setup_ms:.0f} ms total = {setup_ms / len(scored):.1f} ms/task amortized; "
                     f"setup counters {json.dumps(summary.get('setup_counters', {}), sort_keys=True)}; disk {summary.get('disk_bytes', 0)} bytes; "
                     f"model calls 0; monetary cost unknown (no billed calls)")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", action="append", default=[], required=True)
    parser.add_argument("--repos-dir", default=str(ROOT / "dist/retrieval-repos"))
    parser.add_argument("--split", default="test", choices=("train", "validation", "test", "dev", "all"))
    parser.add_argument("--conditions", default=",".join(CONDITIONS))
    parser.add_argument("--limit", type=int, help="First N tasks of each repository's chronological sequence")
    parser.add_argument("--drop-family-repeats", action="store_true", help="Skip later tasks whose target-file family already appeared")
    parser.add_argument("--experience-source", default="oracle", choices=("oracle", "events", "none"),
                        help="oracle: gold targets as accepted outcomes (an ORACLE DIAGNOSTIC); events: replay --events; none: record nothing")
    parser.add_argument("--events", help="JSONL of recorded events for --experience-source events")
    parser.add_argument("--eligible", default="grader_passed", help="Comma list of outcomes the warm arm may use")
    parser.add_argument("--state-dir", help="Keep each arm's private state here (default: a temporary directory)")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=JSON")
    parser.add_argument("--json")
    args = parser.parse_args(argv)
    conditions = [c for c in args.conditions.split(",") if c]
    unknown = [c for c in conditions if c not in CONDITIONS]
    if unknown:
        parser.error(f"unknown conditions: {unknown}")
    events = None
    if args.experience_source == "events":
        if not args.events:
            parser.error("--experience-source events needs --events")
        events = [json.loads(line) for line in Path(args.events).read_text(encoding="utf-8").splitlines() if line.strip()]
    overrides = offline.parse_overrides(args.set)
    results = []
    temporary = None if args.state_dir else tempfile.mkdtemp(prefix="dispatcher-sequence-")
    state_root = Path(args.state_dir or temporary)
    try:
        for dataset in args.dataset:
            tasks = [json.loads(line) for line in Path(dataset).read_text(encoding="utf-8").splitlines() if line.strip()]
            tasks = [t for t in tasks if offline.split_matches(t, args.split)]
            for repo in sorted({t["repo"] for t in tasks}):
                clone = (Path(args.repos_dir) / repo).resolve()
                if not (clone / ".git").exists():
                    print(f"Missing clone {clone}; see evals/retrieval/README.md.", file=sys.stderr)
                    return 2
                sequence = families(sorted([t for t in tasks if t["repo"] == repo], key=lambda t: (commit_time(clone, t["base_commit"]), t["id"])))
                if args.drop_family_repeats:
                    sequence = [t for t in sequence if not t["family_repeat"]]
                sequence = sequence[:args.limit]
                results += evaluate(sequence, clone, conditions, state_dir=state_root / repo, experience_source=args.experience_source,
                                    events=events, eligible=tuple(args.eligible.split(",")), overrides=overrides)
    finally:
        if temporary:
            shutil.rmtree(temporary, ignore_errors=True)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(results), encoding="utf-8")
    label = "HELD-OUT (test split)" if args.split == "test" else f"DEVELOPMENT ({args.split} split) - not held-out performance"
    print(table(results, conditions, "ALL REPOSITORIES - " + label))
    for repo in sorted({r["repo"] for r in results}):
        print("\n" + table([r for r in results if r["repo"] == repo], conditions, repo))
    print("\n" + thirds(results, conditions))
    print("\n" + paired(results, conditions))
    print("\n" + costs(results, conditions))
    if "warm-experience" in conditions and args.experience_source == "oracle":
        print("\nwarm-experience used ORACLE experience (gold target files recorded as grader_passed): a diagnostic of the memory "
              "mechanism, not evidence that Dispatcher learned from real agent work.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
