#!/usr/bin/env python3
"""Hot-path microbenchmark for capability intelligence. Offline, isolated temporary home, no model or network.

    python3 -B evals/capabilities/bench.py [--rounds N] [--json]

Measures, in milliseconds (median and p95 over N rounds, after one warm-up):
  existing_path       loadout lookup for a role, as routing did before this feature (catalog read only)
  context_gate        the check context.py adds when the user has no capability settings (one stat)
  cold_inspection     a full passive inventory with scoped health (what `health` does), catalogs and fixture host
  cached_resolution   read the stored snapshot read-only and resolve a task-scoped plan (what routing does)
Numbers describe this machine and fixture only; they are not a performance guarantee.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    path = ROOT / (name + ".py")
    namespace = {"__name__": "_bench_" + name, "__file__": str(path)}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    return namespace


def timed(function, rounds):
    function()
    samples = []
    for _ in range(rounds):
        started = time.perf_counter()
        function()
        samples.append((time.perf_counter() - started) * 1000)
    samples.sort()
    return {"median_ms": round(statistics.median(samples), 3), "p95_ms": round(samples[max(0, int(0.95 * len(samples)) - 1)], 3), "rounds": rounds}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rounds", type=int, default=50)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    home = Path(tempfile.mkdtemp(prefix="capability-bench-")).resolve()
    saved = {k: os.environ.get(k) for k in ("XDG_CACHE_HOME", "XDG_CONFIG_HOME", "AGENT_DISPATCHER_CAPABILITY_CONFIG")}
    os.environ.update(XDG_CACHE_HOME=str(home / "cache"), XDG_CONFIG_HOME=str(home / "config"),
                      AGENT_DISPATCHER_CAPABILITY_CONFIG=str(home / "config/absent.json"))
    try:
        health, resolver = load("capability_health"), load("capability_resolver")
        project = home / "project"
        project.mkdir()
        config = home / "claude-config"
        (config / "skills/example").mkdir(parents=True)
        (config / "skills/example/SKILL.md").write_text("---\nname: example\ndescription: example.\n---\n# x\n")
        pack, _ = health["find_pack"](str(ROOT))
        settings = health["load_settings"](project=project)
        snapshot = health["read_snapshot"](json.loads((ROOT / "evals/capabilities/fixtures/observations.json").read_text()))
        catalog = health["catalog_dir"](pack)

        def existing():
            roles = json.loads((catalog / "loadouts.json").read_text())["roles"]
            role = next(r for r in roles if r["id"] == "database-engineer")
            return role["skills"]["core"] + role["skills"]["preferred"]

        def gate():
            return Path(os.environ["AGENT_DISPATCHER_CAPABILITY_CONFIG"]).exists()

        def cold():
            return health["build_inventory"](pack, project, "claude", config, snapshot, settings)

        inventory = cold()
        with health["open_store"](health["host_directory"]("claude", config), create=True, readonly=False) as store:
            store.publish_snapshot(health["compact_snapshot"](inventory, settings))
        fingerprint = health["catalog_digest"](pack)

        def cached():
            loaded, notes = resolver["load_snapshot"]("claude", config, session="demo-session", catalog_fingerprint=fingerprint)
            return resolver["resolve"]("Diagnose why production signup is failing", pack=pack, role="database-engineer", snapshot=loaded,
                                       settings=settings, snapshot_notes=notes)

        result = {"environment": {"python": platform.python_version(), "platform": platform.platform(), "cpus": os.cpu_count(),
                                  "instances_in_fixture": len(inventory["instances"])},
                  "existing_path": timed(existing, args.rounds), "context_gate": timed(gate, args.rounds),
                  "cold_inspection": timed(cold, max(5, args.rounds // 5)), "cached_resolution": timed(cached, args.rounds)}
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(home, ignore_errors=True)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"environment: {result['environment']}")
        for key in ("existing_path", "context_gate", "cold_inspection", "cached_resolution"):
            print(f"{key:<18} median {result[key]['median_ms']:>9} ms   p95 {result[key]['p95_ms']:>9} ms   rounds {result[key]['rounds']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
