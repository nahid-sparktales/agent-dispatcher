#!/usr/bin/env python3
"""Index and retrieval cost on one checkout, through the real private parser cache (in a temp dir).

    python3 -B evals/retrieval/perf.py dist/retrieval-repos/sqlglot "Fix executor OFFSET handling in execute()"

Reports: cold index build (nothing cached), warm build (every record reused), incremental build
(one file's content changed), and per-request retrieval + context time over a built index.
Offline and read-only for the measured repository.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import context  # noqa: E402
import parser_cache  # noqa: E402
import retrieval  # noqa: E402


def build(project, directory, scrub, mutate=None):
    cache = parser_cache.Cache(project, writable=True, directory=directory)
    diagnostics, withheld, oversized, stats = [], [], [], {}
    started = time.perf_counter()
    paths = context._enumerate(project, diagnostics)
    texts, hashes, _, _ = context._scan_sources(project, paths, (), [], cache, scrub, withheld, diagnostics, oversized)
    if mutate:  # Same universe, one file with new content: what an edit between two tasks looks like.
        texts[mutate] += "\n# edited\n"
        hashes[mutate] = hashlib.sha256(texts[mutate].encode("utf-8")).hexdigest()
    scanned = time.perf_counter()
    history = context._git_history(project, retrieval.DEFAULTS["git"]["max_commits"], cache)
    index = retrieval.build_index(texts, hashes, context._kind, cache=cache, history=history, stats=stats, path_only=oversized)
    built = time.perf_counter()
    cache.finish()
    return index, {"files": len(texts), "scan_ms": (scanned - started) * 1000, "index_ms": (built - scanned) * 1000,
                   "save_ms": (time.perf_counter() - built) * 1000, "reused": stats["record_hits"], "recomputed": stats["record_misses"]}


def main(argv):
    project = Path(argv[1]).resolve()
    task = argv[2] if len(argv) > 2 else "Fix the parser so nested expressions keep their order"
    scrub = context._scrubber(context.find_pack(str(ROOT)))
    with tempfile.TemporaryDirectory() as directory:
        directory = str(Path(directory).resolve() / "parser-v1")
        _, cold = build(project, directory, scrub)
        index, warm = build(project, directory, scrub)
        victim = sorted(index.records, key=lambda p: -index.records[p]["len"])[len(index.records) // 2]
        _, incremental = build(project, directory, scrub, mutate=victim)
    for label, row in (("cold", cold), ("warm", warm), ("one file changed", incremental)):
        print(f"{label:<17} {row['files']} files: scan {row['scan_ms']:.0f} ms, index {row['index_ms']:.0f} ms "
              f"({row['reused']} records reused, {row['recomputed']} recomputed), cache save {row['save_ms']:.0f} ms")
    config = retrieval.configure("full")
    timings = []
    for _ in range(20):
        started = time.perf_counter()
        retrieval.run(task, index, config)
        timings.append((time.perf_counter() - started) * 1000)
    print(f"retrieval+context  median {statistics.median(timings):.1f} ms, max {max(timings):.1f} ms over 20 runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
