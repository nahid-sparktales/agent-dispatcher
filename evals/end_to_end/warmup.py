"""Deterministic project-index setup, outside native model execution and timing."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

from . import runtime as rt

INDEX_PATHS = (".agent-dispatcher/project-map.json", ".agent-dispatcher/project-graph.json")


def warm_project_indexes(config, client, workspace):
    """Prepare both conditions identically, then check read-only warm retrieval.

    Failure is setup failure, never a model task failure. Helper output is reduced
    to bounded status/counter metadata; no retrieved source or guidance is saved.
    """
    from .adapters import _environment
    spec = config["clients"][client]
    env = _environment(client, spec, Path(spec["profile_dir"]))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    package = Path(config["output_dir"]) / "packages" / client
    helper = package / ("scripts/context.py" if client == "codex" else "context.py")
    report = {"schema_version": 1, "requested": True, "ok": False,
              "excluded_from_task_timing": True, "elapsed_seconds": 0.0,
              "index_paths": list(INDEX_PATHS), "stages": [], "diagnostics": []}
    try:
        before = rt.tree_files(workspace, rt.EXCLUDED)
        for mode in ("maintain", "preview"):
            execution = rt.execute(
                [sys.executable, "-B", str(helper), "--project", str(workspace),
                 "--task", "Prepare project index", "--role", "architect",
                 "--map-" + mode, "--json"],
                cwd=workspace, env=env, prompt="", timeout=120, output_limit=256_000)
            elapsed = execution["elapsed_seconds"]
            report["elapsed_seconds"] += elapsed
            if (execution["returncode"] or execution["timed_out"] or execution.get("cancelled")
                    or execution["output_overflow"] or execution.get("cleanup_warning")):
                raise ValueError("Index setup helper failed or exceeded its execution limit.")
            packet = json.loads(execution["stdout"])
            if not isinstance(packet, dict):
                raise ValueError("Index setup returned an invalid context packet.")
            stage = {"mode": mode, "elapsed_seconds": elapsed, "indexes": {}}
            for name in ("project_map", "project_graph"):
                item = packet.get(name, {})
                if not isinstance(item, dict):
                    raise ValueError("Index setup returned invalid index evidence.")
                coverage = item.get("coverage", {})
                if (not isinstance(coverage, dict)
                        or item.get("cache_status") != "fresh" or item.get("status") != "fresh"
                        or coverage.get("scan_complete") is not True
                        or coverage.get("task_filtered") is not False
                        or coverage.get("excluded_files") != 0):
                    raise ValueError("Index setup did not establish complete, fresh project indexes.")
                stage["indexes"][name] = {
                    "status": item["status"], "coverage": coverage,
                    "maintenance_action": item.get("maintenance", {}).get("action"),
                }
            stats = packet.get("parser_cache")
            if not isinstance(stats, dict) or stats.get("enabled") is not True:
                raise ValueError("Index setup did not report incremental parser cache evidence.")
            # Retain only known counters/flags, never private cache paths, task
            # text, source contents, or arbitrary nested values.
            stage["parser_cache"] = {key: stats[key] for key in (
                "enabled", "write_allowed", "source_hits", "source_misses", "source_bytes_read",
                "parsed_files", "reused_parses", "writes", "fact_hits", "fact_misses",
                "graph_hits", "graph_misses", "logical_source_bytes", "records_saved", "write_failures")
                if key in stats}
            counters = ("source_hits", "source_misses", "source_bytes_read", "parsed_files", "reused_parses", "writes")
            if any(type(stats.get(key)) is not int or stats[key] < 0 for key in counters):
                raise ValueError("Index setup returned invalid parser-cache counters.")
            if stats.get("write_allowed") is not (mode == "maintain"):
                raise ValueError("Index setup returned unexpected parser-cache write scope.")
            if mode == "preview" and any(stats[key] for key in
                                         ("source_misses", "source_bytes_read", "parsed_files", "writes")):
                raise ValueError("Warm index preview did not reuse unchanged source/parser state without writes.")
            if mode == "preview" and (type(stats.get("graph_hits")) is not int
                                      or stats["graph_hits"] != 1 or stats.get("graph_misses", 0) != 0):
                raise ValueError("Warm index preview did not reuse the unchanged relationship graph.")
            report["stages"].append(stage)
            after = rt.tree_files(workspace, rt.EXCLUDED)
            if any(before.get(path) != after.get(path)
                   for path in set(before) | set(after) if path not in INDEX_PATHS):
                raise ValueError("Index setup changed files outside its two permitted project indexes.")
            if not all(path in after for path in INDEX_PATHS):
                raise ValueError("Index setup did not save both project indexes.")
            if mode == "preview" and after != maintained:
                raise ValueError("Warm preview unexpectedly changed project files.")
            maintained = after
        report["index_files_digest"] = rt.digest_files({p: maintained[p] for p in INDEX_PATHS})
        report["ok"] = True
    except (OSError, ValueError, TypeError, KeyError) as error:
        report["diagnostics"].append(str(error) if isinstance(error, ValueError)
                                     else "Index setup could not be validated: " + type(error).__name__)
    return report


def fixture_after_warmup(fixture, initial_dir):
    """Keep scope grading relative to setup, protecting caches on limited tasks."""
    result = deepcopy(fixture)
    result["source_dir"] = str(initial_dir)
    for check in result["checks"]:
        if check["kind"] == "unchanged":
            check["paths"] = list(dict.fromkeys([*check["paths"], *INDEX_PATHS]))
    return result


def grade_warm_fixture(fixture, initial_dir, final_dir, final_answer):
    """Keep private evaluators' relative source lookups on the warm baseline.

    Evaluators are copied verbatim into an owned temporary fixture, with the
    captured initial files as its source tree. No assertions or task edits change.
    """
    import tempfile
    from .grading import grade
    source = Path(fixture["source_dir"])
    fixture_root = source.parent
    original = rt.tree_files(source, {"__pycache__"})
    initial = rt.tree_files(initial_dir, {"__pycache__"})
    if any(original.get(path) != initial.get(path)
           for path in set(original) | set(initial) if path not in INDEX_PATHS):
        raise ValueError("Warm grading baseline changed original source files outside the project indexes.")
    with tempfile.TemporaryDirectory(prefix="dispatcher-warm-grade-") as temporary:
        staged = Path(temporary).resolve() / "fixture"
        private = {path: data for path, data in rt.tree_files(fixture_root, {"__pycache__"}).items()
                   if not path.startswith(source.name + "/")}
        rt.copy_files(private, staged)
        rt.copy_files(initial, staged / source.name)
        adjusted = fixture_after_warmup(fixture, staged / source.name)
        for check in adjusted["checks"]:
            if check["kind"] != "python":
                continue
            original_script = Path(check["script"])
            copied_script = staged / original_script.relative_to(fixture_root)
            if original_script.read_bytes() != copied_script.read_bytes():
                raise ValueError("Private evaluator bytes changed during warm grading setup.")
            check["script"] = str(copied_script)
        return grade(adjusted, final_dir, final_answer)
