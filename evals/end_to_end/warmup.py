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

LEARNED_CONDITIONS = ("learned_skills", "learned_recipes", "learned_global", "learned_full")
INDEX_CONDITIONS = ("indexed", "warm_experience", *LEARNED_CONDITIONS)
# The ladder: each learned arm is the warm-experience treatment plus a frozen, explicitly authorized overlay library
# restricted to these artifact kinds. Global arms also consume a frozen user-global library through the arm's own profile.
LEARNED_KINDS = {"learned_skills": ["skill_overlay"], "learned_recipes": ["skill_overlay", "recipe_overlay"],
                 "learned_global": ["skill_overlay", "recipe_overlay"],
                 "learned_full": ["skill_overlay", "recipe_overlay", "role_method_overlay", "retrieval_profile", "verification_hint"]}
GLOBAL_CONDITIONS = ("learned_global", "learned_full")
EXPERIMENT_PROFILE = "experiment"


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
    warm = condition != "indexed"  # warm_experience and every learned arm use the experience their own earlier steps recorded
    settings = {"index": {"use": "require", "maintain": {"enabled": True}},
                "exploration": {"enabled": False},
                "experience": {"record": warm, "use": warm,
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
    warm = condition != "indexed"
    # The warm arm is the maximal treatment: every memory layer on (a fixture without commit history leaves the
    # episodic layer unavailable; module records come from the memory build in deep_index_setup).
    settings = {"enabled": True, "git": {"retrieval": "on" if warm else "off"}, "semantic": {"retrieval": "on" if warm else "off"},
                "experience": {"recording": True, "retrieval": "on" if warm else "off",
                               "eligible_outcomes": list(config.get("warm_experience_eligible") or ["grader_passed"])}}
    text = json.dumps(settings, indent=2, sort_keys=True) + "\n"
    if not path.is_file() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
    return path


def learning_settings(config, client, condition):
    """Every arm names its own learning settings file: enabled and active only for learned arms, disabled elsewhere,
    so no arm can read the user's ordinary learning configuration or stores."""
    home = arm_home(config, client, condition)
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = home / "procedural-learning.json"
    learned = condition in LEARNED_CONDITIONS
    settings = {"enabled": learned, "mode": "active" if learned else "shadow", "observation": {"record": learned},
                "kinds": LEARNED_KINDS.get(condition, LEARNED_KINDS["learned_full"]),
                "profile": EXPERIMENT_PROFILE if condition in GLOBAL_CONDITIONS else None,
                # Experimental canaries must outlive the whole sequence; the bounds are recorded in each imported revision.
                "canary": {"max_tasks": 1000, "max_days": 365}}
    text = json.dumps(settings, indent=2, sort_keys=True) + "\n"
    if not path.is_file() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
    return path


def disabled_learning_settings(config):
    """The static dispatcher arm points at an explicitly disabled learning configuration."""
    home = Path(config["output_dir"]) / "state"
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = home / "learning-disabled.json"
    text = json.dumps({"enabled": False}, indent=2) + "\n"
    if not path.is_file() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
    return path


def arm_env(config, client, condition, row, fixture):
    home = arm_home(config, client, condition)
    return {"XDG_CACHE_HOME": str(home / "cache"), "AGENT_DISPATCHER_INDEX_ID": arm_identity(client, condition, row, fixture),
            "AGENT_DISPATCHER_INDEX_CONFIG": str(arm_settings(config, client, condition)),
            "AGENT_DISPATCHER_MEMORY_CONFIG": str(memory_settings(config, client, condition)),
            "AGENT_DISPATCHER_LEARNING_CONFIG": str(learning_settings(config, client, condition))}


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
        # Repository memory stores for the same arm (module records; episodic events only when the workspace has history).
        memory_mode = "refresh" if mode == "refresh" else "build"
        execution = rt.execute([sys.executable, "-B", str(_helper(config, client, "repository_memory.py")), memory_mode, "--project", str(workspace),
                                "--config", index_env["AGENT_DISPATCHER_MEMORY_CONFIG"], "--json"],
                               cwd=workspace, env=env, prompt="", timeout=600, output_limit=1_000_000)
        report["elapsed_seconds"] += execution["elapsed_seconds"]
        if execution["returncode"] or execution["timed_out"] or execution.get("cancelled") or execution["output_overflow"]:
            raise ValueError("Repository memory setup helper failed or exceeded its execution limit: " + rt.scrub_text(execution["stderr"][-300:], env).strip())
        memory_report = json.loads(execution["stdout"])
        report["memory"] = {"action": memory_report.get("action"), "events": memory_report.get("events"),
                            "semantic_records": (memory_report.get("semantic") or {}).get("records"), "stages": memory_report.get("stages")}
        if rt.tree_files(workspace, rt.EXCLUDED) != before:
            raise ValueError("Repository memory setup changed project files; state must stay outside the workspace.")
        built.add(index_env["AGENT_DISPATCHER_INDEX_ID"])
        marker.write_text(json.dumps(sorted(built)), encoding="utf-8")
        report["ok"] = True
    except (OSError, ValueError, TypeError, KeyError) as error:
        report["diagnostics"].append(str(error) if isinstance(error, ValueError) else "Deep index setup could not be validated: " + type(error).__name__)
    return dict(report, _env=index_env)


def learning_setup(config, client, workspace, condition, row, fixture, index_env):
    """Import the frozen overlay library into the arm's isolated store once per sequence, as an explicitly authorized
    experimental canary. Outside task timing, no model, no workspace writes; failure is setup failure."""
    from .adapters import _environment
    spec = config["clients"][client]
    env = _environment(client, dict(spec, index_env=index_env), Path(spec["profile_dir"]))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    marker = arm_home(config, client, condition) / "learning-imported.json"
    imported = set(json.loads(marker.read_text(encoding="utf-8"))) if marker.is_file() else set()
    identity = index_env["AGENT_DISPATCHER_INDEX_ID"]
    authorization = config.get("experiment_authorization") or {}
    report = {"schema_version": 1, "requested": True, "ok": False, "condition": condition, "excluded_from_task_timing": True,
              "elapsed_seconds": 0.0, "model_calls": None, "mode": "already_imported" if identity in imported else "import",
              "libraries": [], "experiment": authorization.get("experiment"), "feedback_class": "hidden_grader", "diagnostics": []}
    try:
        before = rt.tree_files(workspace, rt.EXCLUDED)
        if identity not in imported:
            libraries = [("repo", config["learning_library"], [])]
            if condition in GLOBAL_CONDITIONS and config.get("learning_global_library"):
                libraries.append(("global", config["learning_global_library"], ["--scope", "global", "--profile", EXPERIMENT_PROFILE]))
            for scope, path, extra in libraries:
                execution = rt.execute([sys.executable, "-B", str(_helper(config, client, "learning.py")), "import-generation", "--from", str(path),
                                        "--experiment", str(authorization["experiment"]), "--authorize-as", str(authorization["actor"]),
                                        "--project", str(workspace), "--identity", identity, "--config", index_env["AGENT_DISPATCHER_LEARNING_CONFIG"], "--json", *extra],
                                       cwd=workspace, env=env, prompt="", timeout=300, output_limit=1_000_000)
                report["elapsed_seconds"] += execution["elapsed_seconds"]
                if execution["returncode"] or execution["timed_out"] or execution.get("cancelled") or execution["output_overflow"]:
                    raise ValueError(f"Learning library import ({scope}) failed: " + rt.scrub_text(execution["stderr"][-300:], env).strip())
                packet = json.loads(execution["stdout"])
                if not isinstance(packet.get("installed"), list) or packet.get("state") != "experimental_canary":
                    raise ValueError("Learning library import did not record an experimental canary.")
                report["libraries"].append({"scope": scope, "installed": len(packet["installed"]), "state": packet["state"]})
            if rt.tree_files(workspace, rt.EXCLUDED) != before:
                raise ValueError("Learning library import changed project files; state must stay outside the workspace.")
            imported.add(identity)
            marker.write_text(json.dumps(sorted(imported)), encoding="utf-8")
        report.update(ok=True, model_calls=0)
    except (OSError, ValueError, TypeError, KeyError) as error:
        report["diagnostics"].append(str(error) if isinstance(error, ValueError) else "Learning setup could not be validated: " + type(error).__name__)
    return report


def record_trial_observation(config, client, workspace, condition, row, fixture, result, experience_record):
    """After a learned-arm trial: attach an oracle-adjacent observation to the experience event the arm just recorded.

    The harness cannot observe which overlays the agent read, so exposure stays unknown; tokens and duration are
    measured where the client reported them and `unavailable` otherwise. Nothing about the grade's content is handed over.
    """
    from .adapters import _environment
    event_id = (experience_record or {}).get("event_id")
    record = {"schema_version": 1, "condition": condition, "event_id": event_id, "stored": None, "feedback_class": "hidden_grader", "diagnostics": []}
    if not event_id:
        record["diagnostics"].append("no experience event to attach the observation to")
        return record
    spec = config["clients"][client]
    index_env = arm_env(config, client, condition, row, fixture)
    env = _environment(client, dict(spec, index_env=index_env), Path(spec["profile_dir"]))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    usage = result.get("usage") or {}
    tokens = None
    if all(type(usage.get(k)) is int for k in ("input_tokens", "output_tokens")):
        tokens = usage["input_tokens"] + usage["output_tokens"]
    measured = lambda value: {"value": value, "provenance": "measured"} if isinstance(value, (int, float)) and not isinstance(value, bool) else {"value": None, "provenance": "unavailable"}  # noqa: E731
    observation = {"schema_version": 1, "event_id": event_id, "task_family": f"{client}:{fixture['id']}",
                   "sequence": {"harness": row.get("sequence"), "position": row.get("step")} if row.get("sequence") is not None else None,
                   "exposure": [], "workflow": {"retrieval": {"history_expansion": "unknown"}},
                   "failure_categories": ["infrastructure"] if result.get("status") == "infrastructure_error" else [],
                   "feedback_class": "hidden_grader", "user_accepted": None,
                   "resources": {"tokens": measured(tokens), "cost_usd": measured(usage.get("cost_usd")), "duration_s": measured(result.get("elapsed_seconds"))},
                   "limits_of_observation": ["overlay exposure and reads were not observed by the harness", "outcome is the hidden grader's verdict (oracle-adjacent)"]}
    observation = {k: v for k, v in observation.items() if v is not None}
    argv = [sys.executable, "-B", str(_helper(config, client, "learning.py")), "observe", "--event", event_id, "--observation-file", "-",
            "--project", str(workspace), "--identity", index_env["AGENT_DISPATCHER_INDEX_ID"], "--config", index_env["AGENT_DISPATCHER_LEARNING_CONFIG"], "--json"]
    try:
        execution = rt.execute(argv, cwd=workspace, env=env, prompt=json.dumps(observation), timeout=120, output_limit=200_000)
        if execution["returncode"] or execution["timed_out"]:
            raise ValueError("Learning observation helper failed: " + rt.scrub_text(execution["stderr"][-300:], env).strip())
        reply = json.loads(execution["stdout"])
        record.update(stored=reply.get("stored"), task_family=reply.get("task_family"))
    except (OSError, ValueError, TypeError, KeyError) as error:
        record["diagnostics"].append(str(error) if isinstance(error, ValueError) else "Learning observation could not be validated: " + type(error).__name__)
    return record


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
