#!/usr/bin/env python3
"""What did the optional LLM layer buy, and what did it cost? Reads run.py --json files; calls no model.

    python3 -B evals/retrieval/llm_report.py dist/retrieval-results/p10-test-*.json --base full \
        --stores dist/retrieval-llm --price 1.0,5.0

Sections: strategy table with paired-bootstrap intervals against --base, candidate recall (what a
reranker could possibly fix), rank movement and per-target diagnosis (candidate generation versus
reranking), results by task category, conditional-reranking policies replayed from recorded
confidence signals, query-time cost and latency, and index-time cost and compression from the stores.
Prices are yours to state: --price INPUT,OUTPUT in dollars per million tokens; without it only tokens.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import random
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run as bench  # noqa: E402

SHOWN = ("R@1", "R@3", "R@5", "R@8", "R@10", "MRR", "MAP")


def mean(values):
    values = list(values)
    return statistics.fmean(values) if values else 0.0


def percentile(values, share):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))] if ordered else 0.0


def interval(results, name, base, metric, rounds=2000):
    """Paired bootstrap over tasks: 95% interval of mean(name) - mean(base). Small benchmarks deserve wide honesty."""
    pairs = [(r["strategies"][name][metric], r["strategies"][base][metric]) for r in results if name in r["strategies"] and base in r["strategies"]]
    if not pairs or name == base:
        return None
    rng, deltas = random.Random(0), []
    for _ in range(rounds):
        sample = [pairs[rng.randrange(len(pairs))] for _ in pairs]
        deltas.append(mean(a for a, _ in sample) - mean(b for _, b in sample))
    return percentile(deltas, 0.025), percentile(deltas, 0.975)


def categories(result, base):
    """Mechanical task traits, read from the deterministic run so that no model output defines them."""
    row = result["strategies"][base]
    sources = row["source_ranks"].values()
    lexical = min((ranks.get("bm25", 999) for ranks in sources), default=999)
    found = {"explicit path": result["names_target"],
             "explicit symbol": any(ranks.get("symbol_definitions", 999) <= 3 for ranks in sources),
             "strong lexical (a target in raw BM25 top 10)": lexical <= 10,
             "weak lexical (no target in raw BM25 top 10)": lexical > 10,
             "cross-file (2+ targets)": len(result["targets"]) > 1,
             "multi-directory targets": len({PurePosixPath(t).parent for t in result["targets"]}) > 1}
    return [name for name, holds in found.items() if holds]


def policy(results, llm, base, agreement, gap):
    """Replay 'ask the model only when deterministic evidence is not decisive' from recorded signals; no new calls."""
    rows, asked = [], 0
    for result in results:
        signal = result["strategies"][llm].get("confidence") or {}
        decisive = signal.get("pinned") or (signal.get("agreement", 0) >= agreement and signal.get("gap", 0) >= gap)
        asked += not decisive
        rows.append(result["strategies"][base if decisive else llm])
    return {metric: mean(row[metric] for row in rows) for metric in ("R@5", "R@8", "MRR")}, asked / len(results)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results", nargs="+", help="Per-task JSON written by run.py --json")
    parser.add_argument("--base", default="full", help="Deterministic strategy every other one is compared with")
    parser.add_argument("--split", default="test", choices=("train", "validation", "test", "dev", "all"))
    parser.add_argument("--stores", help="Directory of representation stores, for index-time cost and compression")
    parser.add_argument("--price", help="INPUT,OUTPUT dollars per million tokens, to turn measured tokens into estimated cost")
    parser.add_argument("--examples", type=int, default=3, help="Largest improvements and regressions to show per reranked strategy")
    args = parser.parse_args(argv)
    price = [float(v) for v in args.price.split(",")] if args.price else None
    dollars = lambda tokens_in, tokens_out: (tokens_in * price[0] + tokens_out * price[1]) / 1e6 if price else None  # noqa: E731
    results = [r for name in args.results for r in json.loads(Path(name).read_text(encoding="utf-8")) if bench.split_matches(r, args.split)]
    if not results:
        print("No tasks in that split.")
        return 1
    names = list(dict.fromkeys(name for r in results for name in r["strategies"]))
    label = "HELD-OUT (test split)" if args.split == "test" else f"DEVELOPMENT ({args.split} split) - not held-out performance"
    print(bench.table(results, names, "LLM-ASSISTED RETRIEVAL - " + label))
    coverage = [r["llm"] for r in results if r.get("llm")]
    if coverage:
        targets = sum(len(r["targets"]) for r in results if r.get("llm"))
        print(f"\nRole-representation coverage: {mean(c['represented'] / max(1, c['eligible']) for c in coverage):.0%} of eligible files per task; "
              f"{sum(len(c['targets_represented']) for c in coverage)}/{targets} targets represented")

    print(f"\nDifference from '{args.base}' with a paired-bootstrap 95% interval (an interval containing 0 is not evidence of a change)")
    for name in names:
        if name != args.base:
            parts = []
            for metric in ("R@5", "R@8", "MRR"):
                low, high = interval(results, name, args.base, metric)
                delta = mean(r["strategies"][name][metric] - r["strategies"][args.base][metric] for r in results if name in r["strategies"])
                parts.append(f"{metric} {delta:+.3f} [{low:+.3f}, {high:+.3f}]")
            print(f"  {name:<28}" + "   ".join(parts))

    print("\nCandidate recall before any model runs: share of targets inside the fused top K (a reranker can only reorder these)")
    for name in names:
        ranks = [rank for r in results if name in r["strategies"] for rank in r["strategies"][name].get("first_ranks", {}).values()]
        if ranks:
            print(f"  {name:<28}" + "  ".join(f"top{k}: {sum(1 for rank in ranks if rank and rank <= k) / len(ranks):.3f}" for k in (5, 10, 20, 30)))

    reranked = [name for name in names if any(r["strategies"].get(name, {}).get("llm") for r in results)]
    for name in reranked:
        rows = [(r, r["strategies"][name]) for r in results if r["strategies"].get(name, {}).get("llm")]
        asked = [(r, row) for r, row in rows if not row["llm"].get("error")]
        moves, diagnosis = [], {"candidate generation (never offered to the model)": 0, "reranker improved": 0, "reranker unchanged": 0, "reranker worsened": 0}
        for result, row in asked:
            for target, before in row["llm"]["before"].items():
                after = row["llm"]["after"].get(target)
                if not before or not after:
                    diagnosis["candidate generation (never offered to the model)"] += 1
                    continue
                moves.append((before - after, result["id"], target, before, after, row["llm"].get("reasons", {})))
                diagnosis["reranker improved" if after < before else "reranker worsened" if after > before else "reranker unchanged"] += 1
        print(f"\n[{name}] model asked on {len(asked)}/{len(rows)} tasks; failures that fell back to deterministic ranking: {len(rows) - len(asked)}; "
              f"discarded ranking entries: {sum(row['llm'].get('invalid', 0) for _, row in asked)}")
        if moves:
            befores, afters = [m[3] for m in moves], [m[4] for m in moves]
            print(f"  target rank inside the candidate set: mean {mean(befores):.2f} -> {mean(afters):.2f}, median {statistics.median(befores)} -> {statistics.median(afters)}; "
                  f"mean delta {mean(m[0] for m in moves):+.2f}, median delta {statistics.median(m[0] for m in moves):+}")
        print("  " + "; ".join(f"{key}: {value}" for key, value in diagnosis.items()))
        final = [(r["strategies"][args.base]["ranks"][t], row["ranks"][t]) for r, row in rows for t in r["targets"]
                 if r["strategies"][args.base]["ranks"].get(t) and row["ranks"].get(t)]
        if final:
            print(f"  final ranking against '{args.base}': improved {sum(a < b for b, a in final)}, unchanged {sum(a == b for b, a in final)}, "
                  f"worsened {sum(a > b for b, a in final)} of {len(final)} targets ranked by both")
        for title, chosen in (("largest improvements", [m for m in sorted(moves, key=lambda m: -m[0])[:args.examples] if m[0] > 0]),
                              ("largest regressions", [m for m in sorted(moves, key=lambda m: m[0])[:args.examples] if m[0] < 0])):
            for delta, task, target, before, after, reasons in chosen:
                print(f"    {title[:-1]}: {task} {target} #{before} -> #{after}" + (f"  model: {reasons[target]}" if reasons.get(target) else ""))
        usage = [row["llm"].get("usage") or {} for _, row in asked]
        fresh = [u for u in usage if not u.get("cached")] or usage
        tokens_in, tokens_out = mean(u.get("input_tokens", 0) for u in usage), mean(u.get("output_tokens", 0) for u in usage)
        latency = [u.get("ms", 0) for u in fresh]
        spent = dollars(tokens_in, tokens_out)
        print(f"  query cost: {len(asked) / len(rows):.0%} of tasks call the model once; {tokens_in:.0f} input + {tokens_out:.0f} output tokens per call"
              + (f"; ~${spent * len(asked) / len(rows):.5f} per task at the stated price" if spent is not None else "")
              + f"; model latency p50 {percentile(latency, 0.5):.0f} ms, p95 {percentile(latency, 0.95):.0f} ms; deterministic part {mean(row['ms'] for _, row in rows) - mean(row['llm']['ms'] for _, row in rows):.0f} ms")

    print("\nBy task category (R@5 / R@8 / MRR; n = tasks). Categories come from the deterministic run and overlap.")
    grouped = {}
    for result in results:
        if args.base in result["strategies"]:
            for category in categories(result, args.base):
                grouped.setdefault(category, []).append(result)
    for category, members in grouped.items():
        print(f"  {category}  (n={len(members)})")
        for name in names:
            rows = [r["strategies"][name] for r in members if name in r["strategies"]]
            if rows:
                print(f"    {name:<28}" + " / ".join(f"{mean(row[m] for row in rows):.3f}" for m in ("R@5", "R@8", "MRR")))

    for name in reranked:
        if all(r["strategies"].get(name, {}).get("confidence") for r in results):
            print(f"\nConditional reranking replayed for [{name}]: ask only when deterministic evidence is not decisive (agreement >= A and lead >= G, or a named file)")
            always = {m: mean(r["strategies"][name][m] for r in results) for m in ("R@5", "R@8", "MRR")}
            never = {m: mean(r["strategies"][args.base][m] for r in results) for m in ("R@5", "R@8", "MRR")}
            print(f"    {'never':<18} asked   0%  " + "  ".join(f"{m} {v:.3f}" for m, v in never.items()))
            for agreement, gap in ((2, 0.05), (2, 0.15), (3, 0.05), (3, 0.15), (3, 0.30), (4, 0.15)):
                scores, rate = policy(results, name, args.base, agreement, gap)
                print(f"    {f'A={agreement} G={gap}':<18} asked {rate:>4.0%}  " + "  ".join(f"{m} {v:.3f}" for m, v in scores.items()))
            print(f"    {'always':<18} asked 100%  " + "  ".join(f"{m} {v:.3f}" for m, v in always.items()))

    if args.stores:
        print("\nIndex-time cost (paid once per file content, then only for changed files) and compression")
        for store in sorted(Path(args.stores).glob("*.json")):
            loaded = json.loads(store.read_text(encoding="utf-8"))
            entries = [e for e in loaded.get("entries", {}).values() if isinstance(e, dict) and "rep" in e] if isinstance(loaded, dict) else []
            if not entries:
                continue
            metas = [e["meta"] for e in entries]
            source, size = [m["source_chars"] / 4 for m in metas], [m["chars"] / 4 for m in metas]
            tokens_in, tokens_out = sum(m["input_tokens"] for m in metas), sum(m["output_tokens"] for m in metas)
            spent = dollars(tokens_in, tokens_out)
            print(f"  {store.stem}: {len(entries)} representations, {sum(m['calls'] for m in metas)} calls, {tokens_in} input + {tokens_out} output tokens"
                  + (f", ~${spent:.2f} at the stated price" if spent is not None else "") + f", {sum(m['ms'] for m in metas) / 1000 / 60:.0f} model-minutes")
            print(f"    source tokens/file mean {mean(source):.0f} median {statistics.median(source):.0f}; representation tokens/file mean {mean(size):.0f} "
                  f"median {statistics.median(size):.0f}; compression {sum(source) / sum(size):.1f}x (median file {statistics.median(a / b for a, b in zip(source, size)):.1f}x)")
            print(f"    validation: {sum(bool(m['validation']['dropped_symbols']) for m in metas)} files had unsupported symbols removed "
                  f"({sum(len(m['validation']['dropped_symbols']) for m in metas)} names), {sum(m['validation']['dropped_interactions'] for m in metas)} "
                  f"unresolvable interaction targets dropped, {sum(m['validation']['trimmed'] for m in metas)} trimmed to the size target, "
                  f"{sum(m['calls'] > 1 for m in metas)} needed a retry")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
