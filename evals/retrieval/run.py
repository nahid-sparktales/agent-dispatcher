#!/usr/bin/env python3
"""Offline file-localization benchmark: can retrieval rank the files a real change touched?

    python3 -B evals/retrieval/run.py --dataset dist/retrieval-datasets/sqlglot.jsonl --strategy current,full

Needs only a local clone per dataset repository (see README.md); no network, model or API key.
Each task checks out the parent of the real fix, scans it through the context helper's own
exclusion/credential/size filter, and asks each strategy to rank files. Git history is read at
that parent, so the fix itself never leaks into co-change statistics.

Metrics (means over tasks): Recall@k = share of a task's target files ranked in the top k;
MRR = 1 / rank of the first target; MAP = mean precision at each target's rank (a missing
target contributes 0). Context: files, bytes and estimated tokens (bytes / 4) of what the
strategy would hand the agent. Useful Context Density = excerpt bytes that belong to target
files / all excerpt bytes. CtxRecall = share of targets present in that context.
Latency is ranking plus context selection over a built index; index time is reported apart.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import context  # noqa: E402
import retrieval  # noqa: E402

KS = (1, 3, 5, 8, 10)
LADDER = ["current"] + [name for name, _ in retrieval._LADDER]
LEAVE_ONE_OUT = ["full"] + sorted(name for name in retrieval.STRATEGIES if name.startswith("full-"))
LEGACY_TIER = "standard"  # The current helper's default size: 8 files, 6000 excerpt tokens.


class Memo:
    """Cross-commit memo standing in for the private parser cache: redacted text and index records by content."""

    def __init__(self, project):
        self.project, self.redacted, self.store = project, {}, {}

    def read(self, relative, remaining, reader, redact):
        text, used, reason = reader(self.project, relative, remaining)
        if reason:
            return None, used, reason, None
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if sha not in self.redacted:
            self.redacted[sha] = redact(text)
        return self.redacted[sha], used, None, sha

    def get(self, kind, key):
        return self.store.get(json.dumps([kind, key]))

    def put(self, kind, key, value):
        self.store[json.dumps([kind, key])] = value


class LLMLayer:
    """Optional model-backed layer (llm_retrieval.py). One content-addressed store per repository, shared by every
    commit of it: a file is summarized once per content, exactly as an incremental index would do it."""

    def __init__(self, settings, store, generate, refresh):
        import llm_retrieval
        self.module, self.generate, self.settings = llm_retrieval, generate, llm_retrieval.load_settings(settings)
        self.store = llm_retrieval.Store(store)
        # Reranker answers live apart from representations, so an evaluation never rewrites the file an indexing run is growing.
        self.answers = llm_retrieval.Store(Path(store).with_suffix(".rerank.json"))
        self.reranker = llm_retrieval.make_reranker(self.settings, self.answers, refresh)
        self.indexing = Counter()

    def prepare(self, index):
        if self.generate:
            report = self.module.generate(index, self.settings, self.store)
            self.indexing.update({key: report[key] for key in ("generated", "cached", "failed", "calls", "input_tokens", "output_tokens", "ms")})
        attached = self.module.attach(index, self.store, self.settings)
        eligible = [path for path in index.paths if not self.module.eligible(path, index)]
        return {"represented": attached, "eligible": len(eligible),
                "source_chars": sum(len(index.texts[path]) for path in index.representations),
                "representation_chars": sum(len(self.module.render(rep)) for rep in index.representations.values())}


def split_matches(task, wanted):
    return wanted == "all" or task["split"] == wanted or (wanted == "dev" and task["split"] in {"train", "validation"})


def _legacy(task, texts, hashes, scrub):
    """The pre-upgrade helper, scored exactly as it ranks and excerpts today."""
    started = time.perf_counter()
    terms, identifiers, phrases, _ = context._terms(task)
    explicit = context._explicit_paths(task, texts)
    candidates = {path: c for path, text in texts.items()
                  if (c := context._candidate(path, text, terms, identifiers, phrases, explicit, set(), None))}
    count = len(candidates)
    ranked = [c["path"] for c in context._legacy_rank(dict(candidates), texts)]
    cap, budget = context.LIMITS[LEGACY_TIER]
    rows, excerpts, _ = context._legacy_selection(candidates, texts, cap, budget, [], scrub, False, hashes, [])
    elapsed = (time.perf_counter() - started) * 1000
    sizes = Counter()
    for excerpt in excerpts:
        sizes[excerpt["path"]] += len(excerpt["content"].encode("utf-8"))
    total = sum(sizes.values()) + len(json.dumps(rows).encode("utf-8"))
    return {"ranked": ranked, "candidates": count, "files": [row["path"] for row in rows], "bytes": total,
            "excerpt_bytes": dict(sizes), "ms": elapsed, "lists": {}}


def _engine(task, index, config, reranker=None):
    started = time.perf_counter()
    outcome = retrieval.run(task, index, config, reranker=reranker)
    elapsed = (time.perf_counter() - started) * 1000
    sizes = {item["path"]: sum(len(e["content"].encode("utf-8")) for e in item["excerpts"]) for item in outcome["packet"]["files"]}
    return {"ranked": [row["path"] for row in outcome["ranked"]], "candidates": len(outcome["ranked"]),
            "files": list(sizes), "bytes": outcome["packet"]["bytes"], "excerpt_bytes": sizes, "ms": elapsed,
            "lists": {name: [row["file"] for row in rows] for name, rows in outcome["lists"].items()},
            "overlap": outcome["trace"]["overlap"], "additions": (outcome["trace"]["graph_additions"], outcome["trace"]["git_additions"]),
            "llm": outcome.get("llm"), "confidence": outcome["trace"].get("confidence"), "first": outcome["first"]}


def _score(found, targets):
    ranks = {target: found["ranked"].index(target) + 1 if target in found["ranked"] else None for target in targets}
    hits = sorted(rank for rank in ranks.values() if rank)
    excerpt_total = sum(found["excerpt_bytes"].values())
    row = {f"R@{k}": sum(1 for rank in hits if rank <= k) / len(targets) for k in KS}
    row.update(MRR=1 / hits[0] if hits else 0.0,
               MAP=sum((position + 1) / rank for position, rank in enumerate(hits)) / len(targets),
               candidates=found["candidates"], files=len(found["files"]), bytes=found["bytes"],
               tokens=math.ceil(found["bytes"] / 4), ms=found["ms"],
               density=sum(found["excerpt_bytes"].get(t, 0) for t in targets) / excerpt_total if excerpt_total else 0.0,
               ctx_recall=sum(t in found["files"] for t in targets) / len(targets), ranks=ranks)
    return row


def parse_overrides(items):
    """["graph.max_hops=2", "rrf_k=30"] -> {"graph": {"max_hops": 2}, "rrf_k": 30}"""
    overrides = {}
    for item in items:
        key, value = item.split("=", 1)
        cursor = overrides
        for part in key.split(".")[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[key.split(".")[-1]] = json.loads(value)
    return overrides


def evaluate(tasks, clone, strategies, overrides=None, variants=None, progress=True, llm=None):
    scrub = context._scrubber(context.find_pack(str(ROOT)))
    memo = Memo(clone)
    configs = {name: retrieval.configure(name, overrides) for name in strategies if name != "current"}
    for name, (base, changes) in (variants or {}).items():
        configs[name] = retrieval.configure(base, retrieval._merge(overrides or {}, changes))
    strategies = [*strategies, *(variants or {})]
    results = []
    for number, task in enumerate(tasks, 1):
        subprocess.run(["git", "-C", str(clone), "checkout", "-q", "-f", "--detach", task["base_commit"]], check=True)
        started = time.perf_counter()
        diagnostics, withheld = [], []
        paths = context._enumerate(clone, diagnostics)
        oversized = []
        texts, hashes, _, _ = context._scan_sources(clone, paths, (), [], memo, scrub, withheld, diagnostics, oversized)
        scan_ms = (time.perf_counter() - started) * 1000
        query = scrub(task["query"])[:context.MAX_TASK_CHARS]
        stats, indexes, coverage = {}, {}, {}
        history = context._git_history(clone, retrieval.DEFAULTS["git"]["max_commits"])

        def index_for(config):
            """One index per distinct co-change setting; every other knob is applied at query time."""
            key = json.dumps([config["git"][k] for k in ("max_commit_files", "min_support", "half_life_days")])
            if key not in indexes:
                indexes[key] = retrieval.build_index(texts, hashes, context._kind, cache=memo, history=history,
                                                     config=config, stats=stats if not indexes else {}, path_only=oversized)
                if llm:
                    coverage.update(llm.prepare(indexes[key]))
            return indexes[key]

        index_for(retrieval.STRATEGIES["full"])
        row = {key: task[key] for key in ("id", "repo", "split", "query_source", "names_target")}
        row.update(targets=task["target_files"], unreachable=[t for t in task["target_files"] if t not in texts],
                   name_only=[t for t in task["target_files"] if t in oversized],
                   universe=len(texts), scan_ms=scan_ms, index_ms=stats["index_ms"],
                   record_misses=stats["record_misses"], strategies={})
        if llm:
            row["llm"] = dict(coverage, targets_represented=[t for t in task["target_files"]
                                                             if t in getattr(index_for(retrieval.STRATEGIES["full"]), "representations", {})])
        for name in strategies:
            found = (_legacy(query, texts, hashes, scrub) if name == "current" else
                     _engine(query, index_for(configs[name]), configs[name], llm.reranker if llm else None))
            scored = _score(found, task["target_files"])
            place = lambda paths: {t: paths.index(t) + 1 if t in paths else None for t in task["target_files"]}  # noqa: E731
            scored["first_ranks"] = place(found.get("first", []))
            if found.get("llm"):  # Candidate recall apart from reranking quality: where was each target before and after the model?
                asked = found["llm"]
                scored["llm"] = {"error": asked.get("error"), "usage": asked.get("usage"), "ms": asked["ms"], "invalid": asked.get("invalid", 0),
                                 "candidates": len(asked["candidates"]), "before": place(asked["candidates"]), "after": place(asked.get("order", [])),
                                 "reasons": asked.get("reasons", {})}
            scored["confidence"] = found.get("confidence")
            scored["top"] = found["ranked"][:30]
            scored["source_ranks"] = {target: {source: files.index(target) + 1 for source, files in found["lists"].items() if target in files}
                                      for target in task["target_files"]}
            scored["overlap"], scored["additions"] = found.get("overlap", {}), found.get("additions", (0, 0))
            row["strategies"][name] = scored
        results.append(row)
        if llm:
            llm.answers.save()  # Paid-for answers survive an interrupted run.
        if progress and (number % 10 == 0 or number == len(tasks)):
            print(f"  {task['repo']}: {number}/{len(tasks)}", file=sys.stderr, flush=True)
    return results


METRICS = [f"R@{k}" for k in KS] + ["MRR", "MAP"]


def table(results, strategies, title):
    if not results:
        return f"{title}: no tasks"
    lines = [f"{title}  ({len(results)} tasks, {sum(len(r['targets']) for r in results)} targets, "
             f"{sum(len(r['unreachable']) for r in results)} with unread content, of which "
             f"{sum(len(r.get('name_only', ())) for r in results)} rankable by name only)",
             f"{'Strategy':<22}" + "".join(f"{m:>6}" for m in METRICS) + f"{'Cand':>6}{'Files':>6}{'KB':>7}{'Tok':>7}{'UCD':>6}{'CtxR':>6}{'ms':>8}",
             "-" * 105]
    for name in strategies:
        rows = [r["strategies"][name] for r in results if name in r["strategies"]]
        if not rows:
            continue
        mean = lambda key: statistics.fmean(row[key] for row in rows)  # noqa: E731
        lines.append(f"{name:<22}" + "".join(f"{mean(m):>6.3f}".replace("0.", " .", 1) for m in METRICS)
                     + f"{mean('candidates'):>6.0f}{mean('files'):>6.1f}{mean('bytes') / 1000:>7.1f}{mean('tokens'):>7.0f}"
                     + f"{mean('density'):>6.2f}{mean('ctx_recall'):>6.2f}{mean('ms'):>8.1f}")
    return "\n".join(lines)


def overlap_report(results, strategy):
    rows = [r["strategies"][strategy] for r in results if strategy in r["strategies"]]
    if not rows:
        return ""
    pairs, unique, found = defaultdict(list), Counter(), Counter()
    for row in rows:
        for pair, count in row["overlap"].items():
            pairs[pair].append(count)
        for ranks in row["source_ranks"].values():
            top = {source for source, rank in ranks.items() if rank <= 10}
            found.update(top)
            if len(top) == 1:
                unique.update(top)
    lines = [f"Candidate overlap for '{strategy}' (mean shared files per task)"]
    lines += [f"  {pair:<42}{statistics.fmean(counts):>6.1f}" for pair, counts in sorted(pairs.items())]
    lines.append("Targets a source ranked in its own top 10 (and how many only it found)")
    lines += [f"  {source:<22}{found[source]:>5}  unique {unique[source]:>4}" for source in sorted(found)]
    lines.append(f"  mean graph additions {statistics.fmean(r['additions'][0] for r in rows):.1f}, "
                 f"git additions {statistics.fmean(r['additions'][1] for r in rows):.1f}")
    return "\n".join(lines)


def failure_report(results, strategy, limit):
    """Per missed target: where each retriever ranked it, and a mechanical reading of where it was lost."""
    lines, shown = [f"Failures for '{strategy}' (Recall@8 < 1)"], 0
    causes = Counter()
    for result in results:
        row = result["strategies"].get(strategy)
        if not row or row["R@8"] >= 1:
            continue
        detail = [f"\nTASK {result['id']}  ({result['query_source']} query, split {result['split']})"]
        for target, rank in row["ranks"].items():
            sources = row["source_ranks"][target]
            if rank and rank <= 8:
                cause = None
            elif target in result["unreachable"] and target not in result.get("name_only", ()):
                cause = "unreachable: outside the scanned universe (skipped or unreadable)"
            elif target in result.get("name_only", ()):
                cause = "name only: over the read limit, so only its path, imports and history can rank it"
            elif not sources:
                cause = "candidate generation: no retriever found it (query extraction or vocabulary mismatch)"
            elif min(sources.values()) <= 8:
                cause = "rank fusion/rerank: a retriever had it in its top 8 but the fused rank is lower"
            elif set(sources) <= {"graph", "git"}:
                cause = "expansion only: structural or history evidence was too weak against lexical candidates"
            else:
                cause = "weak evidence: every retriever that found it ranked it low"
            detail.append(f"  {target:<55} fused rank {rank or 'not retrieved'}"
                          + (f"  [{', '.join(f'{s} #{r}' for s, r in sorted(sources.items()))}]" if sources else ""))
            if cause:
                causes[cause.split(":")[0]] += 1
                detail.append(f"    POSSIBLE CAUSE {cause}")
        if shown < limit:
            lines += detail
            shown += 1
    lines += ["", "Missed targets by stage:"] + [f"  {cause:<32}{count}" for cause, count in causes.most_common()]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", action="append", default=[], help="JSONL produced by mine.py; repeatable")
    parser.add_argument("--repos-dir", default=str(ROOT / "dist/retrieval-repos"), help="Holds one clone per dataset `repo`")
    parser.add_argument("--strategy", default="current,bm25,hybrid,hybrid+graph,full",
                        help="Comma list, or 'ladder' (cumulative ablation) or 'leave-one-out'")
    parser.add_argument("--split", default="dev", choices=("train", "validation", "test", "dev", "all"),
                        help="dev = train + validation. Tune on those; report 'test' only as held-out.")
    parser.add_argument("--limit", type=int, help="First N tasks per dataset (smoke runs)")
    parser.add_argument("--recent", action="store_true", help="Order each dataset newest base commit first before --limit: a subset "
                        "chosen by date alone, whose commits share most file contents (keeps model-backed indexing affordable)")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=JSON", help="Override a config value, e.g. rrf_k=30 or graph.max_hops=2")
    parser.add_argument("--variant", action="append", default=[], metavar="NAME=BASE:KEY=JSON;KEY=JSON",
                        help="An extra named configuration for parameter sweeps, e.g. k20=full:rrf_k=20")
    parser.add_argument("--failures", type=int, default=0, help="Show this many failed tasks in detail")
    parser.add_argument("--analyze", default="full", help="Strategy used for overlap and failure analysis")
    parser.add_argument("--llm-settings", help="llm_retrieval settings JSON; turns on role representations and the reranker for strategies that use them")
    parser.add_argument("--llm-store-dir", default=str(ROOT / "dist/retrieval-llm"), help="One representation/rerank store per repository lives here")
    parser.add_argument("--llm-index", action="store_true", help="Generate missing representations at each task's commit (model calls); otherwise use only what is stored")
    parser.add_argument("--refresh-llm", action="store_true", help="Ignore stored reranker answers and ask the model again")
    parser.add_argument("--json", help="Write per-task results here")
    parser.add_argument("--report", action="append", default=[], help="Re-print tables from saved --json files instead of running")
    parser.add_argument("--check", help="Baseline JSON {strategy: {metric: value}}; exit 1 when the chosen split regresses beyond --tolerance")
    parser.add_argument("--tolerance", type=float, default=0.03)
    args = parser.parse_args(argv)
    strategies = {"ladder": LADDER, "leave-one-out": LEAVE_ONE_OUT}.get(args.strategy) or args.strategy.split(",")
    overrides = parse_overrides(args.set)
    variants = {}
    for item in args.variant:
        name, rest = item.split("=", 1)
        base, _, changes = rest.partition(":")
        variants[name] = (base, parse_overrides([c for c in changes.split(";") if c]))
    strategies = [name for name in strategies if name]
    results = []
    for saved in args.report:
        results += [r for r in json.loads(Path(saved).read_text(encoding="utf-8")) if split_matches(r, args.split)]
    for dataset in args.dataset:
        tasks = [json.loads(line) for line in Path(dataset).read_text(encoding="utf-8").splitlines() if line.strip()]
        tasks = [task for task in tasks if split_matches(task, args.split)]
        if args.recent:
            stamp = lambda task: int(subprocess.run(["git", "-C", str(Path(args.repos_dir) / task["repo"]), "log", "-1", "--format=%ct",  # noqa: E731
                                                     task["base_commit"]], capture_output=True, text=True, check=True).stdout)
            tasks.sort(key=lambda task: (-stamp(task), task["id"]))
        tasks = tasks[:args.limit]
        for repo in sorted({task["repo"] for task in tasks}):
            clone = Path(args.repos_dir) / repo
            if not (clone / ".git").exists():
                print(f"Missing clone {clone}; see evals/retrieval/README.md.", file=sys.stderr)
                return 2
            layer = LLMLayer(args.llm_settings, Path(args.llm_store_dir) / f"{repo}.json", args.llm_index, args.refresh_llm) if args.llm_settings else None
            results += evaluate([task for task in tasks if task["repo"] == repo], clone.resolve(), strategies, overrides, variants, llm=layer)
            if layer and args.llm_index:
                print(f"  {repo} indexing: " + json.dumps(dict(layer.indexing)), file=sys.stderr, flush=True)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(results), encoding="utf-8")
    present = list(dict.fromkeys(name for r in results for name in r["strategies"]))
    shown = [name for name in [*strategies, *variants] if name in present] + (
        [name for name in present if name not in strategies and name not in variants] if args.report else [])
    held_out = args.split == "test"
    label = "HELD-OUT (test split)" if held_out else f"DEVELOPMENT ({args.split} split) - not held-out performance"
    print(table(results, shown, "ALL REPOSITORIES - " + label))
    for repo in sorted({r["repo"] for r in results}):
        print("\n" + table([r for r in results if r["repo"] == repo], shown, repo))
    if results:
        print(f"\nIndex: mean {statistics.fmean(r['index_ms'] for r in results):.0f} ms per task with unchanged records reused; "
              f"scan {statistics.fmean(r['scan_ms'] for r in results):.0f} ms; "
              f"cold first build {max(r['index_ms'] for r in results):.0f} ms (largest)")
    if args.analyze in shown:
        print("\n" + overlap_report(results, args.analyze))
        if args.failures:
            print("\n" + failure_report(results, args.analyze, args.failures))
    if args.check:
        baseline = json.loads(Path(args.check).read_text(encoding="utf-8"))[args.split]
        failed = []
        for name, metrics in baseline.items():
            if not isinstance(metrics, dict):
                continue
            rows = [r["strategies"][name] for r in results if name in r["strategies"]]
            for metric, expected in metrics.items():
                if rows and statistics.fmean(row[metric] for row in rows) < expected - args.tolerance:
                    failed.append(f"{name} {metric}: {statistics.fmean(row[metric] for row in rows):.3f} < {expected:.3f} - {args.tolerance}")
        print("\nRegression check: " + ("FAILED\n  " + "\n  ".join(failed) if failed else "passed"))
        return 1 if failed else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
