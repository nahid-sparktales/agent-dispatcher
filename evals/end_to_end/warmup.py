"""Deterministic project-index setup, outside native model execution and timing."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

from . import runtime as rt

# Indexes persist to private state outside the workspace. These in-tree paths are where older
# releases (and some frozen fixtures) keep them; when present they are inputs to preserve.
INDEX_PATHS = (".agent-dispatcher/project-map.json", ".agent-dispatcher/project-graph.json")
PERSISTED = {"built", "refreshed", "unchanged"}


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
              "index_storage": "private_state", "stages": [], "diagnostics": []}
    try:
        before = rt.tree_files(workspace, rt.EXCLUDED)
        for mode in ("maintain", "preview"):
            execution = rt.execute(
                [sys.executable, "-B", str(helper), "--project", str(workspace),
                 # No role: index setup is not role work, and read-only roles defer cache writes.
                 "--task", "Prepare project index", "--map-" + mode, "--json"],
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
                action = item.get("maintenance", {}).get("action")
                if mode == "maintain" and action not in PERSISTED:
                    raise ValueError("Index setup did not save both project indexes.")
                stage["indexes"][name] = {"status": item["status"], "coverage": coverage, "maintenance_action": action}
                # Counts only: enough to show both conditions were prepared alike, never index contents.
                for key in ("fresh_facts", "omitted"):
                    if isinstance(item.get(key), (int, dict)) and type(item[key]) is not bool:
                        stage["indexes"][name][key] = item[key]
            stats = packet.get("parser_cache")
            if not isinstance(stats, dict) or stats.get("enabled") is not True:
                raise ValueError("Index setup did not report incremental parser cache evidence.")
            # Retain only known counters/flags, never private cache paths, task
            # text, source contents, or arbitrary nested values.
            stage["parser_cache"] = {key: stats[key] for key in (
                "enabled", "write_allowed", "source_hits", "source_misses", "source_bytes_read",
                "parsed_files", "writes", "fact_hits", "fact_misses",
                "graph_hits", "graph_misses", "logical_source_bytes", "records_saved", "write_failures")
                if key in stats}
            counters = ("source_hits", "source_misses", "source_bytes_read", "parsed_files", "writes")
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
            # A fresh preview after maintenance proves the saved indexes are readable; the workspace
            # itself, including any index files a fixture ships, must be byte-identical throughout.
            if rt.tree_files(workspace, rt.EXCLUDED) != before:
                raise ValueError("Index setup changed project files; indexes must persist to private state outside the workspace.")
        evidence = json.dumps(report["stages"][-1]["indexes"], sort_keys=True).encode("utf-8")
        report["index_evidence_digest"] = rt.digest_files({"index-evidence.json": evidence})
        report["ok"] = True
    except (OSError, ValueError, TypeError, KeyError) as error:
        report["diagnostics"].append(str(error) if isinstance(error, ValueError)
                                     else "Index setup could not be validated: " + type(error).__name__)
    return report


def fixture_after_warmup(fixture, initial_dir):
    """Keep scope grading relative to setup, protecting in-tree index files a baseline contains."""
    result = deepcopy(fixture)
    result["source_dir"] = str(initial_dir)
    present = [path for path in INDEX_PATHS if (Path(initial_dir) / path).is_file()]
    for check in result["checks"]:
        if check["kind"] == "unchanged":
            check["paths"] = list(dict.fromkeys([*check["paths"], *present]))
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


# ---------------------------------------------------------------- deep-index conditions

INDEX_CONDITIONS = ("indexed", "warm_experience")


def arm_home(config, client, condition):
    """Private state for one arm of one experiment: never the user's cache, never shared between arms."""
    return Path(config["output_dir"]) / "state" / f"{client}-{condition}"


def arm_identity(client, condition, row, fixture):
    return f"{client}:{condition}:{row.get('sequence') or fixture['id']}"


def arm_settings(config, client, condition):
    """The trusted settings file each arm hands the staged dispatcher: index required, experience used only by the warm arm."""
    home = arm_home(config, client, condition)
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = home / "repository-intelligence.json"
    settings = {"index": {"use": "require", "maintain": {"enabled": True}},
                "exploration": {"enabled": False},
                "experience": {"record": condition == "warm_experience", "use": condition == "warm_experience",
                               "eligible_outcomes": list(config.get("warm_experience_eligible") or ["grader_passed"])}}
    text = json.dumps(settings, indent=2, sort_keys=True) + "\n"
    if not path.is_file() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
    return path


def memory_settings(config, client, condition):
    """The unified experience switch lives in the repository-memory settings: retrieval on for the warm arm only."""
    home = arm_home(config, client, condition)
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = home / "repository-memory.json"
    settings = {"enabled": True, "git": {"retrieval": "off"}, "semantic": {"retrieval": "off"},
                "experience": {"recording": True, "retrieval": "on" if condition == "warm_experience" else "off",
                               "eligible_outcomes": list(config.get("warm_experience_eligible") or ["grader_passed"])}}
    text = json.dumps(settings, indent=2, sort_keys=True) + "\n"
    if not path.is_file() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
    return path


def arm_env(config, client, condition, row, fixture):
    home = arm_home(config, client, condition)
    return {"XDG_CACHE_HOME": str(home / "cache"), "AGENT_DISPATCHER_INDEX_ID": arm_identity(client, condition, row, fixture),
            "AGENT_DISPATCHER_INDEX_CONFIG": str(arm_settings(config, client, condition)),
            "AGENT_DISPATCHER_MEMORY_CONFIG": str(memory_settings(config, client, condition))}


def _helper(config, client, name):
    package = Path(config["output_dir"]) / "packages" / client
    return package / (f"scripts/{name}" if client == "codex" else name)


def deep_index_setup(config, client, workspace, condition, row, fixture):
    """Build (first snapshot of a sequence) or refresh (later snapshots) the deep index for an index arm.

    Outside task timing and model usage: the helper calls no model. The identity maps successive
    temporary workspaces of one sequence to one store, and the arm's cache home isolates it from every
    other arm. Failure is setup failure; no model task starts.
    """
    from .adapters import _environment
    spec = config["clients"][client]
    index_env = arm_env(config, client, condition, row, fixture)
    env = _environment(client, dict(spec, index_env=index_env), Path(spec["profile_dir"]))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    (Path(index_env["XDG_CACHE_HOME"])).mkdir(parents=True, exist_ok=True, mode=0o700)
    marker = arm_home(config, client, condition) / "built.json"
    built = set(json.loads(marker.read_text(encoding="utf-8"))) if marker.is_file() else set()
    mode = "refresh" if index_env["AGENT_DISPATCHER_INDEX_ID"] in built else "build"
    report = {"schema_version": 1, "requested": True, "ok": False, "condition": condition, "mode": mode,
              "excluded_from_task_timing": True, "elapsed_seconds": 0.0, "model_calls": None, "index_env": {k: v for k, v in index_env.items() if k != "XDG_CACHE_HOME"},
              "index_storage": "arm_private_state", "counters": {}, "coverage": {}, "diagnostics": []}
    try:
        before = rt.tree_files(workspace, rt.EXCLUDED)
        execution = rt.execute([sys.executable, "-B", str(_helper(config, client, "repository_intelligence.py")), mode, "--project", str(workspace),
                                "--identity", index_env["AGENT_DISPATCHER_INDEX_ID"], "--config", index_env["AGENT_DISPATCHER_INDEX_CONFIG"], "--json"],
                               cwd=workspace, env=env, prompt="", timeout=600, output_limit=1_000_000)
        report["elapsed_seconds"] = execution["elapsed_seconds"]
        if execution["returncode"] or execution["timed_out"] or execution.get("cancelled") or execution["output_overflow"]:
            raise ValueError("Deep index setup helper failed or exceeded its execution limit: " + rt.scrub_text(execution["stderr"][-300:], env).strip())
        packet = json.loads(execution["stdout"])
        if not isinstance(packet, dict) or packet.get("published") is not True:
            raise ValueError("Deep index setup did not publish a complete generation.")
        if packet.get("model_calls") != 0:
            raise ValueError("Deep index setup reported model calls; deterministic setup must make none.")
        report["model_calls"] = 0
        report["counters"] = {k: v for k, v in packet.get("counters", {}).items() if type(v) is int}
        coverage = packet.get("coverage", {})
        report["coverage"] = {k: coverage.get(k) for k in ("discovered", "indexed", "pending", "failed", "complete_within_policy")}
        if coverage.get("complete_within_policy") is not True:
            raise ValueError("Deep index setup did not cover every admitted file.")
        if rt.tree_files(workspace, rt.EXCLUDED) != before:
            raise ValueError("Deep index setup changed project files; state must stay outside the workspace.")
        built.add(index_env["AGENT_DISPATCHER_INDEX_ID"])
        marker.write_text(json.dumps(sorted(built)), encoding="utf-8")
        report["ok"] = True
    except (OSError, ValueError, TypeError, KeyError) as error:
        report["diagnostics"].append(str(error) if isinstance(error, ValueError) else "Deep index setup could not be validated: " + type(error).__name__)
    return dict(report, _env=index_env)


def trial_outcome(result, policy="harness_grader"):
    """The outcome category a harness may record. `harness_grader` maps the hidden grader's verdict to the
    oracle-adjacent `grader_passed`; nothing about the grade's content is recorded."""
    if policy != "harness_grader":
        return "insufficient_evidence"
    status = result.get("status")
    if status == "timeout" or result.get("cancelled"):
        return "cancelled"
    if status in ("completed", "task_failure"):
        auto = result.get("auto_grade") or {}
        if status == "completed" and auto.get("passed") is True and auto.get("checks"):
            return "grader_passed"
        return "failed_checks"
    return "infrastructure_error"


def record_trial_experience(config, client, workspace, condition, row, fixture, result, initial, final):
    """After a warm-experience trial: record edited paths and the outcome category into that arm's own store.

    The task text is the fixture prompt the agent saw; edited files are those whose bytes changed; no grader
    detail, answer text or trace is handed over.
    """
    from .adapters import _environment
    spec = config["clients"][client]
    index_env = arm_env(config, client, condition, row, fixture)
    env = _environment(client, dict(spec, index_env=index_env), Path(spec["profile_dir"]))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    edited = sorted(name for name in set(initial) | set(final) if name in final and initial.get(name) != final.get(name))
    outcome = trial_outcome(result, config.get("experience_outcome", "harness_grader"))
    argv = [sys.executable, "-B", str(_helper(config, client, "repository_intelligence.py")), "experience", "record", "--project", str(workspace),
            "--identity", index_env["AGENT_DISPATCHER_INDEX_ID"], "--config", index_env["AGENT_DISPATCHER_INDEX_CONFIG"], "--json",
            "--task-id", row["id"], "--task", fixture["prompt"], "--outcome", outcome, "--source", "harness"]
    for name in edited[:200]:
        argv += ["--edited", name]
    record = {"schema_version": 1, "condition": condition, "outcome": outcome, "edited": len(edited), "stored": None, "eligible": None, "diagnostics": []}
    try:
        execution = rt.execute(argv, cwd=workspace, env=env, prompt="", timeout=120, output_limit=200_000)
        if execution["returncode"] or execution["timed_out"]:
            raise ValueError("Experience recording helper failed.")
        reply = json.loads(execution["stdout"])
        record.update(stored=reply.get("stored"), eligible=reply.get("eligible"), event_id=reply.get("id"))
    except (OSError, ValueError, TypeError, KeyError) as error:
        record["diagnostics"].append(str(error) if isinstance(error, ValueError) else "Experience recording could not be validated: " + type(error).__name__)
    return record
