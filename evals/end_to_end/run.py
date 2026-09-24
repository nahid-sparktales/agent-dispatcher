#!/usr/bin/env python3
"""Paired native-client evaluation. Only the explicit `run` command calls models."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import difflib
import hashlib
import json
import re
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.end_to_end import runtime as rt

CLIENTS = ("codex", "claude")
CONDITIONS = ("baseline", "dispatcher")
# Every condition the runner can schedule, in canonical order. `indexed` and `warm_experience` add the deep
# repository index (built or refreshed before each task, outside timing) and, for the warm arm only, the
# experience its own earlier tasks recorded. A configuration selects a subset that must include baseline.
ALL_CONDITIONS = ("baseline", "dispatcher", "dispatcher_lean", "dispatcher_evidence", "indexed", "warm_experience", "learned_skills", "learned_recipes", "learned_global", "learned_full")
# Packet-mode arms: exactly the static `dispatcher` arm plus the helper's packet mode (AGENT_DISPATCHER_PACKET).
PACKET_CONDITIONS = {"dispatcher_lean": "lean", "dispatcher_evidence": "evidence"}
# Learned arms: warm_experience plus a frozen, explicitly authorized overlay library of increasing kinds (skills, recipes,
# a frozen user-global library, the full bundle). Each arm keeps its own library, learning store and observations.
LEARNED_CONDITIONS = ("learned_skills", "learned_recipes", "learned_global", "learned_full")


def conditions_of(config):
    return tuple(config.get("conditions") or CONDITIONS)


def now():
    return datetime.now(timezone.utc).isoformat()


def fingerprint(config):
    """Changing a model, fixture, package, budget, or adapter invalidates smoke evidence."""
    value = {k: v for k, v in config.items() if k not in ("created_at", "output_dir")}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def selected_clients(clients=CLIENTS):
    """Use one validated, canonical client order for staging, probing and scheduling."""
    if isinstance(clients, str) or not isinstance(clients, (dict, list, tuple)):
        raise ValueError("clients must be a nonempty selection of codex and/or claude")
    names = list(clients)
    if (not names or any(not isinstance(name, str) or name not in CLIENTS for name in names)
            or len(set(names)) != len(names)):
        raise ValueError("clients must be a nonempty, unique selection of codex and/or claude")
    return tuple(client for client in CLIENTS if client in names)


def check_packet_tokens(tokens, conditions):
    """One soft packet target for both packet arms (AGENT_DISPATCHER_PACKET_TOKENS), in the helper's accepted range."""
    if tokens is None:
        return
    if type(tokens) is not int or not 256 <= tokens <= 100000:
        raise ValueError("packet_tokens must be an integer between 256 and 100000")
    if not any(c in PACKET_CONDITIONS for c in conditions):
        raise ValueError("packet_tokens is only meaningful with dispatcher_lean or dispatcher_evidence")


def validate_config(config, live=False):
    if config.get("schema_version") != 1:
        raise ValueError("unsupported evaluation configuration version")
    if not isinstance(config.get("clients"), dict):
        raise ValueError("configuration clients must be an object")
    selected_clients(config["clients"])
    if type(config.get("seed")) is not int:
        raise ValueError("seed must be an integer")
    if type(config.get("timeout_seconds")) is not int or not 1 <= config["timeout_seconds"] <= 3600:
        raise ValueError("timeout_seconds must be an integer between 1 and 3600")
    if type(config.get("warm_project_index", False)) is not bool:
        raise ValueError("warm_project_index must be a boolean")
    chosen = config.get("conditions", list(CONDITIONS))
    if (not isinstance(chosen, list) or not chosen or "baseline" not in chosen or len(set(chosen)) != len(chosen)
            or any(c not in ALL_CONDITIONS for c in chosen) or chosen != [c for c in ALL_CONDITIONS if c in chosen]):
        raise ValueError("conditions must be a canonical-order subset of " + ", ".join(ALL_CONDITIONS) + " that includes baseline")
    if config.get("experience_outcome", "harness_grader") not in ("harness_grader",):
        raise ValueError("experience_outcome must be harness_grader")
    if any(c in LEARNED_CONDITIONS for c in chosen):
        library = config.get("learning_library")
        if not isinstance(library, str) or not Path(library).is_absolute() or not Path(library).is_file():
            raise ValueError("learning_library must be an absolute path to a frozen library exported with `learning export-generation` when a learned condition is selected")
        authorization = config.get("experiment_authorization")
        if (not isinstance(authorization, dict) or set(authorization) != {"actor", "experiment"}
                or any(not isinstance(authorization[k], str) or not authorization[k].strip() for k in ("actor", "experiment"))):
            raise ValueError("experiment_authorization must name the authorizing person (actor) and the experiment id for learned conditions")
        global_library = config.get("learning_global_library")
        if global_library is not None and (not isinstance(global_library, str) or not Path(global_library).is_absolute() or not Path(global_library).is_file()):
            raise ValueError("learning_global_library must be an absolute path to a frozen global library")
    elif config.get("learning_library") or config.get("learning_global_library"):
        raise ValueError("learning_library is only meaningful with a learned condition")
    check_packet_tokens(config.get("packet_tokens"), chosen)
    eligible = config.get("warm_experience_eligible", ["grader_passed"])
    if not isinstance(eligible, list) or any(not isinstance(v, str) for v in eligible):
        raise ValueError("warm_experience_eligible must be a list of outcome names")
    profiles = []
    for client, spec in config["clients"].items():
        if not isinstance(spec, dict):
            raise ValueError(f"{client}: client settings must be an object")
        if spec.get("auth") not in ("subscription", "api"):
            raise ValueError(f"{client}: auth must be subscription or api")
        if not isinstance(spec.get("executable"), str) or not spec["executable"]:
            raise ValueError(f"{client}: executable is required")
        for key in ("model", "effort"):
            if live and (not isinstance(spec.get(key), str) or not spec[key].strip()):
                raise ValueError(f"{client}: set an explicit {key} before doctor or run")
        profile = Path(spec.get("profile_dir", ""))
        if not profile.is_absolute():
            raise ValueError(f"{client}: profile_dir must be absolute")
        settings = spec.get("llm_settings")
        if settings is not None and (not isinstance(settings, str) or not Path(settings).is_absolute() or not Path(settings).is_file()):
            raise ValueError(f"{client}: llm_settings must be an absolute path to an existing settings file")
        memory = spec.get("memory_settings")
        if memory is not None and (not isinstance(memory, str) or not Path(memory).is_absolute() or not Path(memory).is_file()):
            raise ValueError(f"{client}: memory_settings must be an absolute path to an existing settings file")
        hosts = spec.get("llm_network")
        if hosts is not None and (settings is None or not isinstance(hosts, list) or not hosts
                                  or not all(isinstance(h, str) and re.fullmatch(r"[a-z0-9.-]+", h) for h in hosts)):
            raise ValueError(f"{client}: llm_network must be a nonempty list of hostnames and needs llm_settings")
        if profile.is_symlink():
            raise ValueError("evaluation profiles cannot be symlinks")
        profiles.append(profile.resolve())
    if any(a == b or a in b.parents or b in a.parents
           for index, a in enumerate(profiles) for b in profiles[index + 1:]):
        raise ValueError("clients must have separate evaluation profiles")


def source_snapshot(destination):
    """Freeze working-tree source once; regeneration happens only in this private copy."""
    result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                            cwd=ROOT, capture_output=True, check=True)
    names = sorted(set(result.stdout.decode().split("\0")) - {""})
    files = {}
    for name in names:
        path = ROOT / name
        if path.is_symlink():
            raise ValueError("source snapshot cannot contain symlinks")
        if path.is_file():
            files[name] = path.read_bytes()
    rt.copy_files(files, destination)
    return rt.digest_files(files)


def stage_packages(destination, clients=CLIENTS):
    clients = selected_clients(clients)
    with tempfile.TemporaryDirectory(prefix="dispatcher-eval-build-") as temporary:
        snapshot = Path(temporary) / "source"
        digest = source_snapshot(snapshot)
        output = Path(temporary) / "codex-package"
        command = ([sys.executable, str(snapshot / "build_codex.py"), "--output", str(output)]
                   if "codex" in clients else [sys.executable, str(snapshot / "build.py")])
        build = subprocess.run(command,
                               cwd=snapshot, capture_output=True, text=True, timeout=120)
        if build.returncode:
            raise ValueError("dispatcher package build failed in isolated snapshot: " + rt.scrub_text(build.stderr[-1500:]))
        if "codex" in clients:
            rt.copy_files(rt.tree_files(output / "skills/agent-dispatcher"), destination / "codex")
        if "claude" in clients:
            claude = destination / "claude"
            # Reuse the installer's pure staging function from this frozen
            # snapshot, including layout-specific resource path remapping.
            staging = subprocess.run(
                [sys.executable, "-B", "-c",
                 "from pathlib import Path; import sys; from install_claude import stage_pack; "
                 "stage_pack(Path(sys.argv[1]), Path(sys.argv[2]))", str(snapshot), str(claude)],
                cwd=snapshot, capture_output=True, text=True, timeout=120)
            if staging.returncode:
                raise ValueError("Claude package staging failed in isolated snapshot: " + rt.scrub_text(staging.stderr[-1500:]))
        return {"source_digest": digest,
                "package_digests": {c: rt.digest_tree(destination / c) for c in clients}}


def prepare(output, suite_path=None, models=None, efforts=None, auth=None, seed=20260919, clients=CLIENTS,
            warm_project_index=False, conditions=CONDITIONS, packet_tokens=None):
    from evals.end_to_end.grading import load_suite
    if type(warm_project_index) is not bool:
        raise ValueError("warm_project_index must be a boolean")
    check_packet_tokens(packet_tokens, conditions)  # before the output directory exists
    clients = selected_clients(clients)
    output = Path(output).absolute()
    if output.exists():
        raise ValueError("prepare requires a new output directory; existing results are never overwritten")
    implementation = Path(__file__).parent.resolve()
    if implementation == output.resolve() or implementation in output.resolve().parents:
        raise ValueError("output must be outside the evaluation implementation directory")
    fixtures = load_suite(suite_path)
    suite_source = Path(suite_path).resolve() if suite_path else Path(__file__).parent / "fixtures"
    # Custom suite manifest and its relative resources travel together.
    suite_source = suite_source.parent if suite_source.is_file() else suite_source
    profile_root = Path.home() / ".local/state/agent-dispatcher-evals" / uuid.uuid4().hex
    if output == profile_root or output in profile_root.parents:
        raise ValueError("authentication profiles must be outside artifacts")
    output.mkdir(parents=True)
    provenance = stage_packages(output / "packages", clients)
    staged_fixtures = rt.tree_files(suite_source, {"__pycache__"})
    if suite_path and Path(suite_path).is_file() and Path(suite_path).name != "manifest.json":
        content = staged_fixtures[Path(suite_path).name]
        if "manifest.json" in staged_fixtures and staged_fixtures["manifest.json"] != content:
            raise ValueError("custom suite directory contains a different manifest.json")
        staged_fixtures["manifest.json"] = staged_fixtures.pop(Path(suite_path).name)
    rt.copy_files(staged_fixtures, output / "fixtures")
    copied = load_suite(output / "fixtures")
    if [f["id"] for f in fixtures] != [f["id"] for f in copied]:
        raise ValueError("staged suite does not match source manifest")
    provenance["fixtures_digest"] = rt.digest_tree(output / "fixtures")
    provenance["runner_digest"] = rt.digest_tree(Path(__file__).parent, {"fixtures", "__pycache__"})
    config = {"schema_version": 1, "created_at": now(), "seed": seed, "timeout_seconds": 600,
              "warm_project_index": warm_project_index, "conditions": list(conditions),
              "experience_outcome": "harness_grader", "warm_experience_eligible": ["grader_passed"],
              "output_dir": str(output), "provenance": provenance, "clients": {}}
    if packet_tokens is not None:
        config["packet_tokens"] = packet_tokens  # absent otherwise, so configurations without it keep their shape
    for client in clients:
        profile = profile_root / client
        profile.mkdir(parents=True, mode=0o700)
        (profile / ".dispatcher-eval-profile").write_text("v1\n")
        config["clients"][client] = {"executable": client, "model": (models or {}).get(client),
                                      "effort": (efforts or {}).get(client),
                                      "auth": (auth or {}).get(client, "subscription"),
                                      "profile_dir": str(profile)}
    validate_config(config)
    rt.write_json(output / "config.json", config)
    return output / "config.json"


def load_config(path, live=False):
    path = Path(path).resolve()
    config = rt.read_json(path)
    validate_config(config, live)
    if Path(config["output_dir"]).resolve() != path.parent:
        raise ValueError("config output_dir must be its containing prepared directory")
    output = path.parent
    for client, spec in config["clients"].items():
        profile = Path(spec["profile_dir"]).resolve()
        if output == profile or output in profile.parents or profile in output.parents:
            raise ValueError("authentication profiles must be outside artifact directories")
        marker = profile / ".dispatcher-eval-profile"
        if marker.is_symlink() or not marker.is_file() or marker.read_text() != "v1\n":
            raise ValueError(f"{client}: not an owned evaluation profile; prepare a new evaluation")
    provenance = config["provenance"]
    for client in selected_clients(config["clients"]):
        if rt.digest_tree(output / "packages" / client) != provenance["package_digests"][client]:
            raise ValueError("staged dispatcher package changed; prepare a new evaluation")
    if rt.digest_tree(output / "fixtures") != provenance["fixtures_digest"]:
        raise ValueError("staged fixtures changed; prepare a new evaluation")
    if rt.digest_tree(Path(__file__).parent, {"fixtures", "__pycache__"}) != provenance["runner_digest"]:
        raise ValueError("evaluation runner changed; prepare a new evaluation")
    return config


@contextmanager
def lock(output):
    path = Path(output) / ".run-lock"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError("evaluation is already running; inspect a stale .run-lock before removing it") from exc
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        path.unlink(missing_ok=True)


@contextmanager
def workspace_for(config, client, condition, fixture=None):
    """Install only the treatment skill, cleaning its owned copy even when a run fails."""
    with tempfile.TemporaryDirectory(prefix="dispatcher-eval-trial-") as temporary:
        workspace = Path(temporary).resolve() / "project"
        workspace.mkdir()
        if ROOT == workspace or ROOT in workspace.parents:
            raise ValueError("trial workspaces must be outside the dispatcher repository")
        if fixture:
            files = rt.tree_files(fixture["source_dir"])
            if any(Path(name).parts[0] in (".agents", ".claude", ".git") for name in files):
                raise ValueError("fixtures cannot supply agent configuration or repository history")
            rt.copy_files(files, workspace)
        subprocess.run(["git", "init", "--quiet", str(workspace)], check=True, capture_output=True)
        if client == "codex":
            # The treatment skill lives inside its workspace. Hide that injected
            # package from project indexing in both conditions, without adding a
            # task exclusion that would correctly defer complete-map persistence.
            with (workspace / ".git/info/exclude").open("a", encoding="utf-8") as exclusions:
                exclusions.write("\n.agents/\n")
        skill = None
        expected_digest = None
        if client == "claude":
            target = Path(config["clients"][client]["profile_dir"]) / "skills/agent-dispatcher"
            if target.exists() or target.is_symlink():
                raise ValueError("Claude evaluation profile already contains a dispatcher skill; inspect leftover staging")
        else:
            target = workspace / ".agents/skills/agent-dispatcher"
        try:
            if condition != "baseline":
                source = Path(config["output_dir"]) / "packages" / client
                files = rt.tree_files(source)
                expected_digest = rt.digest_files(files)
                rt.copy_files(files, target)
                skill = target
            yield workspace, skill
            if skill is not None and rt.digest_tree(skill, {"__pycache__"}) != expected_digest:
                raise ValueError("trial modified its dispatcher package")
        finally:
            if client == "claude" and skill is not None:
                if target.is_symlink():
                    target.unlink()
                elif target.exists():
                    shutil.rmtree(target)


def doctor(config):
    from evals.end_to_end import adapters
    validate_config(config, live=True)
    checks = {}
    for client in selected_clients(config["clients"]):
        for condition in conditions_of(config):
            key = client + "/" + condition
            try:
                with workspace_for(config, client, condition) as (workspace, skill):
                    checks[key] = adapters.doctor(client, config["clients"][client], workspace, skill)
            except (ValueError, OSError, subprocess.SubprocessError) as exc:
                checks[key] = {"ok": False, "version": None, "errors": [rt.scrub_text(str(exc))],
                               "warnings": [], "evidence": {}}
    return {"schema_version": 1, "created_at": now(), "ok": all(c["ok"] for c in checks.values()),
            "fingerprint": fingerprint(config), "checks": checks}


def schedule(fixtures, suite, seed, clients=CLIENTS, conditions=CONDITIONS):
    """Randomize condition order within each task; a chronological sequence never reorders its steps.

    Fixtures that carry `sequence` and `step` form ordered sequences (one repetition each, since a later
    step depends on what the arms accumulated); every condition advances through the same steps.
    """
    clients = selected_clients(clients)
    rng = random.Random(seed)
    selected = [f for f in fixtures if f.get("smoke")] if suite == "smoke" else fixtures
    if suite == "smoke" and len(selected) != 2:
        raise ValueError("smoke suite must select exactly two fixtures")
    sequenced = [f for f in selected if f.get("sequence") is not None]
    for fixture in sequenced:
        if not isinstance(fixture["sequence"], str) or type(fixture.get("step")) is not int:
            raise ValueError("a sequenced fixture needs a string sequence and an integer step")
    ordered = sorted(sequenced, key=lambda f: (f["sequence"], f["step"], f["id"])) + [f for f in selected if f.get("sequence") is None]
    rows = []
    for client in clients:
        for fixture in ordered:
            repetitions = 1 if suite == "smoke" or fixture.get("sequence") is not None else 2
            for repetition in range(1, repetitions + 1):
                order = list(conditions)
                rng.shuffle(order)
                for condition in order:
                    row = {"id": f"{client}-{fixture['id']}-{repetition}-{condition}", "client": client, "condition": condition,
                           "fixture_id": fixture["id"], "repetition": repetition}
                    if fixture.get("sequence") is not None:
                        row.update(sequence=fixture["sequence"], step=fixture["step"])
                    rows.append(row)
    return rows


def diff_files(before, after):
    lines = []
    for name in sorted(set(before) | set(after)):
        if before.get(name) == after.get(name):
            continue
        old, new = before.get(name, b""), after.get(name, b"")
        try:
            lines.extend(difflib.unified_diff(old.decode().splitlines(True), new.decode().splitlines(True),
                                              fromfile="before/" + name, tofile="after/" + name))
        except UnicodeDecodeError:
            lines.append(f"Binary file changed: {name}\n")
    return "".join(lines)


@contextmanager
def capture_scope(workspace, result, artifacts, env):
    """Record sibling residue while the owned temporary directory still exists."""
    try:
        yield
    finally:
        audit = rt.audit_trial_parent(workspace)
        result["scope_audit"] = rt.sanitize(audit, env)
        passed = audit["clean"]
        reason = ("No files or directories remained outside the project in the owned trial directory."
                  if passed is True else "Files or directories remained outside the permitted project."
                  if passed is False else "The owned trial directory could not be completely inspected.")
        result["scope_check"] = {"passed": passed, "reason": reason}
        if passed is not True:
            result["diagnostics"].append(reason)
            if result["status"] in {"completed", "task_failure"}:
                if passed is False:
                    result.update(status="task_failure", task_success=False)
                elif result["status"] == "completed":
                    result.update(status="infrastructure_error", task_success=None)
        try:
            rt.write_json(artifacts / "scope-audit.json", result["scope_audit"])
        except OSError:
            if result["status"] == "completed":
                result.update(status="infrastructure_error", task_success=None)
            result["diagnostics"].append("Scope evidence could not be saved.")
            raise


def run_trial(config, batch, row, fixture):
    from evals.end_to_end import adapters, activity
    from evals.end_to_end.grading import grade
    client, condition = row["client"], row["condition"]
    spec = config["clients"][client]
    artifacts = Path(batch) / "trials" / row["id"]
    artifacts.mkdir(parents=True)
    result = {**row, "category": fixture["category"], "status": "infrastructure_error",
              "task_success": None, "auto_grade": {"passed": False, "checks": [],
                                                    "human_required": fixture["human_required"]},
              "treatment_invoked": None, "elapsed_seconds": None,
              "usage": dict.fromkeys(adapters.USAGE_KEYS), "runtime": dict.fromkeys(adapters.RUNTIME_KEYS),
              "final_answer": "", "artifact_dir": str(artifacts.relative_to(batch)),
              "prompt": fixture["prompt"], "acceptance": fixture["acceptance"],
              "rubric": fixture["rubric"], "diagnostics": [], "startup_valid": False}
    started = False
    launch_env = {}
    result["activity"] = activity.empty()
    if row.get("sequence") is not None:
        result.update(sequence=row["sequence"], step=row["step"])
    try:
        with workspace_for(config, client, condition, fixture) as (workspace, skill), \
                tempfile.TemporaryDirectory(prefix="dispatcher-eval-config-") as config_home:
            # Outside the audited trial directory, so it is never scope residue; identical (empty) for every condition.
            spec = dict(spec, config_home=config_home)
            if config.get("warm_project_index", False):
                from evals.end_to_end.warmup import warm_project_indexes
                result["index_setup"] = warm_project_indexes(config, client, workspace)
                rt.write_json(artifacts / "index-setup.json", result["index_setup"])
                if not result["index_setup"]["ok"]:
                    raise ValueError("Warm project-index setup failed; no model task started. " +
                                     " ".join(result["index_setup"]["diagnostics"]))
            from evals.end_to_end import warmup
            if condition in warmup.INDEX_CONDITIONS:
                setup = warmup.deep_index_setup(config, client, workspace, condition, row, fixture)
                spec = dict(spec, index_env=setup.pop("_env"))
                result["deep_index_setup"] = setup
                rt.write_json(artifacts / "deep-index-setup.json", setup)
                if not setup["ok"]:
                    raise ValueError("Deep index setup failed; no model task started. " + " ".join(setup["diagnostics"]))
                if condition in warmup.LEARNED_CONDITIONS:
                    learning = warmup.learning_setup(config, client, workspace, condition, row, fixture, spec["index_env"])
                    result["learning_setup"] = learning
                    rt.write_json(artifacts / "learning-setup.json", learning)
                    if not learning["ok"]:
                        raise ValueError("Learning library setup failed; no model task started. " + " ".join(learning["diagnostics"]))
            elif condition == "dispatcher" or condition in PACKET_CONDITIONS:
                # The static arms never read the user's own learning configuration or stores; packet arms add only the packet mode.
                index_env = {"AGENT_DISPATCHER_LEARNING_CONFIG": str(warmup.disabled_learning_settings(config))}
                if condition in PACKET_CONDITIONS:
                    index_env["AGENT_DISPATCHER_PACKET"] = PACKET_CONDITIONS[condition]
                    if config.get("packet_tokens") is not None:  # the same target for both packet arms
                        index_env["AGENT_DISPATCHER_PACKET_TOKENS"] = str(config["packet_tokens"])
                spec = dict(spec, index_env=index_env)
            initial = rt.tree_files(workspace, rt.EXCLUDED)
            if config.get("warm_project_index", False):
                validate_final_artifacts(initial, {})
                rt.copy_files(initial, artifacts / "initial")
            result["starting_files_digest"] = rt.digest_files(initial)
            check = adapters.doctor(client, spec, workspace, skill)
            result["cli_version"] = check.get("version")
            if not check["ok"]:
                result["status"] = "invalid_configuration"
                result["diagnostics"] = check["errors"]
                return result
            launch = adapters.build_launch(client, spec, workspace, skill)
            launch["effective"]["condition"] = condition
            launch_env = launch["env"]
            result["effective_settings"] = launch["effective"]
            rt.write_json(artifacts / "settings.json", rt.sanitize(launch["effective"]))
            prompt = launch["stdin_prefix"] + fixture["prompt"]
            if launch["effective"].get("input_format") == "stream-json":
                prompt = json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n"
            activity_binding = activity.bind(workspace, skill)
            with capture_scope(workspace, result, artifacts, launch["env"]):
                execution = rt.execute(launch["argv"], cwd=workspace, env=launch["env"],
                                       prompt=prompt,
                                       timeout=min(config["timeout_seconds"], fixture["timeout_seconds"]))
                started = True
                result["elapsed_seconds"] = execution["elapsed_seconds"]
                result["cancelled"] = execution.get("cancelled", False)
                result["exit_status"] = execution["returncode"]
                (artifacts / "events.jsonl").write_text(rt.sanitize_stream(execution["stdout"], launch["env"]))
                (artifacts / "stderr.txt").write_text(rt.scrub_text(execution["stderr"], launch["env"]))
                result["activity"] = activity.analyze(client, execution["stdout"], activity_binding,
                                                      interrupted=bool(execution["timed_out"] or execution.get("cancelled") or execution["output_overflow"]))
                result["activity"] = rt.sanitize(result["activity"], launch["env"])
                rt.write_json(artifacts / "activity.json", result["activity"])
                parsed = adapters.parse_events(client, execution["stdout"])
                result["usage"] = parsed["usage"]
                result["runtime"] = parsed["runtime"]
                result["usage_observed"] = parsed.get("usage_observed", False)
                result["startup"] = parsed.get("startup", {})
                result["final_answer"] = rt.scrub_text(parsed["final_answer"], launch["env"])
                result["treatment_invoked"] = parsed["treatment_invoked"] if condition != "baseline" else None
                result["diagnostics"] = parsed.get("diagnostics", []) + parsed.get("errors", [])
                if execution.get("cleanup_warning"):
                    result["diagnostics"].append(execution["cleanup_warning"])
                (artifacts / "answer.md").write_text(result["final_answer"])
                startup_errors = adapters.validate_startup(client, spec, parsed, condition)
                result["startup_valid"] = not startup_errors
                result["diagnostics"].extend(startup_errors)
                final = rt.tree_files(workspace, rt.EXCLUDED)
                validate_final_artifacts(final, launch["env"])
                rt.copy_files(final, artifacts / "final")
                (artifacts / "changes.diff").write_text(rt.scrub_text(diff_files(initial, final), launch["env"]))
                result["final_files_digest"] = rt.digest_files(final)
                if parsed["status"] == "authentication_failure":
                    result["status"] = "authentication_failure"
                elif execution["timed_out"] or execution.get("cancelled"):
                    result.update(status="timeout", task_success=False)
                    if execution.get("cancelled"):
                        result["diagnostics"].append("Run interrupted; partial evidence retained.")
                elif startup_errors:
                    result["status"] = "invalid_configuration"
                elif execution["output_overflow"] or execution.get("cleanup_warning") or execution["returncode"] != 0 or parsed["status"] != "completed":
                    result["status"] = "infrastructure_error"
                else:
                    if config.get("warm_project_index", False):
                        from evals.end_to_end.warmup import grade_warm_fixture
                        result["auto_grade"] = grade_warm_fixture(
                            fixture, artifacts / "initial", artifacts / "final", result["final_answer"])
                    else:
                        result["auto_grade"] = grade(fixture, artifacts / "final", result["final_answer"])
                    passed = result["auto_grade"]["passed"]
                    if condition != "baseline" and not result["treatment_invoked"]:
                        passed = False
                        result["diagnostics"].append("Dispatcher invocation not observed; treatment-compliance failure.")
                    result["status"] = "completed" if passed else "task_failure"
                    result["task_success"] = (None if result["auto_grade"]["human_required"] else True) if passed else False
            if (condition == "warm_experience" or condition in warmup.LEARNED_CONDITIONS) and started:
                # The arm records its own experience before the next step; grader content never enters the record.
                result["experience_record"] = warmup.record_trial_experience(config, client, workspace, condition, row, fixture, result, initial,
                                                                             rt.tree_files(workspace, rt.EXCLUDED))
                rt.write_json(artifacts / "experience-record.json", result["experience_record"])
                if condition in warmup.LEARNED_CONDITIONS:
                    # Oracle-adjacent learning observation keyed to that event; exposure stays unknown to the harness.
                    result["learning_observation"] = warmup.record_trial_observation(config, client, workspace, condition, row, fixture, result, result["experience_record"])
                    rt.write_json(artifacts / "learning-observation.json", result["learning_observation"])
    except ValueError as exc:
        result.update(status="task_failure" if started else "invalid_configuration",
                      task_success=False if started else None)
        result["diagnostics"].append(rt.scrub_text(str(exc)))
    except (OSError, subprocess.SubprocessError) as exc:
        result["diagnostics"].append(type(exc).__name__ + ": " + rt.scrub_text(str(exc)))
    except Exception as exc:
        # Preserve an attempted run even if a newer client breaks an adapter
        # contract. Do not continue the batch or mislabel it as an agent failure.
        result.update(status="infrastructure_error", task_success=None)
        result["diagnostics"].append("Unexpected adapter/grader error: " + type(exc).__name__)
    return rt.sanitize(result, launch_env)


def validate_final_artifacts(files, env):
    """Do not persist credential stores or known credentials generated by a trial."""
    forbidden = {"auth.json", "credentials.json", ".credentials.json", ".netrc"}
    secrets = [v.encode() for k, v in env.items() if len(v) >= 8
               and any(word in k.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD"))]
    for name, data in files.items():
        path = Path(name)
        if path.name in forbidden or path.name == ".env" or path.name.startswith(".env.") or ".codex" in path.parts:
            raise ValueError("Trial produced a credential/configuration artifact; omitted from saved artifacts.")
        if any(value in data for value in secrets):
            raise ValueError("Trial produced an artifact containing an active credential; omitted from saved artifacts.")


def smoke_ready(batch, results):
    trials = results["trials"]
    clients = selected_clients(batch.get("config", {}).get("clients", CLIENTS))
    conditions = conditions_of(batch.get("config", {}))
    return (len(trials) == len(batch["schedule"]) == 2 * len(conditions) * len(clients)
            and all(t["startup_valid"] and t.get("usage_observed") and t["status"] in ("completed", "task_failure")
                    and t.get("client", clients[0]) in clients
                    and (t["condition"] == "baseline" or t["treatment_invoked"])
                    for t in trials))


def reconcile_pair(trials):
    """Flag every side when native startup catalogs differ beyond the dispatcher within one task's group."""
    if len(trials) < 2:
        return
    current = trials[-1]
    group = [t for t in trials[:-1] if all(t[k] == current[k] for k in ("client", "fixture_id", "repetition"))]
    if not group:
        return
    previous = group[-1]
    if any(t["condition"] == current["condition"] for t in group):
        raise ValueError("paired trials must have different conditions")
    if not current.get("startup_valid") or not previous.get("startup_valid"):
        return  # Missing startup evidence is an incomplete pair, not catalog drift.

    def catalog(startup, key):
        value = startup.get(key)
        if value is None:
            return None
        if not isinstance(value, list):
            return value
        return sorted(json.dumps(item, sort_keys=True) for item in value
                      if "agent-dispatcher" not in json.dumps(item).lower())

    errors = []
    if current.get("starting_files_digest") != previous.get("starting_files_digest"):
        errors.append("Paired starting files differed.")
    if current.get("cli_version") != previous.get("cli_version"):
        errors.append("CLI version changed within a pair.")
    for key in ("tools", "skills", "mcp_servers", "plugins"):
        a = catalog(current.get("startup", {}), key)
        b = catalog(previous.get("startup", {}), key)
        if a != b:
            errors.append(f"Paired startup {key} catalogs differed beyond dispatcher.")
    if errors:
        for trial in (current, *group):
            trial.update(status="invalid_configuration", task_success=None, startup_valid=False)
            trial["diagnostics"].extend(errors)


def run(config, suite):
    from evals.end_to_end.grading import load_suite
    from evals.end_to_end.reporting import report
    output = Path(config["output_dir"])
    preflight = doctor(config)
    rt.write_json(output / "doctor.json", preflight)
    if not preflight["ok"]:
        raise ValueError("doctor found setup errors; see doctor.json. No model runs started.")
    if suite == "pilot":
        smoke = output / "smoke-ready.json"
        if not smoke.is_file() or rt.read_json(smoke).get("fingerprint") != fingerprint(config):
            raise ValueError("run a successful smoke test with this configuration before the pilot")
        if rt.read_json(smoke).get("versions") != {k: v["version"] for k, v in preflight["checks"].items()}:
            raise ValueError("CLI versions changed since smoke; rerun smoke")
    fixtures = load_suite(output / "fixtures")
    by_id = {f["id"]: f for f in fixtures}
    batch_dir = output / "batches" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8])
    batch_dir.mkdir(parents=True)
    batch = {"schema_version": 1, "created_at": now(), "suite": suite, "seed": config["seed"],
             "config": config, "provenance": config["provenance"], "fingerprint": fingerprint(config),
             "schedule": schedule(fixtures, suite, config["seed"], selected_clients(config["clients"]), conditions_of(config)), "doctor": preflight}
    rt.write_json(batch_dir / "batch.json", batch)
    results = {"schema_version": 1, "trials": []}
    rt.write_json(batch_dir / "results.json", results)
    for index, row in enumerate(batch["schedule"], 1):
        print(f"[{index}/{len(batch['schedule'])}] {row['id']}", flush=True)
        result = run_trial(config, batch_dir, row, by_id[row["fixture_id"]])
        results["trials"].append(result)
        reconcile_pair(results["trials"])
        rt.write_json(batch_dir / "results.json", results)
        for recent in results["trials"][-2:]:
            rt.write_json(batch_dir / recent["artifact_dir"] / "result.json", recent)
        print("  " + result["status"], flush=True)
        if result.get("cancelled") or result["status"] in ("invalid_configuration", "authentication_failure", "infrastructure_error"):
            print("Stopped on a setup/runtime error; attempted trials retained and remaining trials not run.")
            break
    if suite == "smoke" and smoke_ready(batch, results):
        rt.write_json(output / "smoke-ready.json", {"fingerprint": fingerprint(config), "batch_dir": str(batch_dir),
                       "versions": {k: v["version"] for k, v in preflight["checks"].items()}})
    report(batch_dir)
    return batch_dir


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare", help="stage packages, fixtures, and configuration without model calls")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--fixtures", type=Path)
    p.add_argument("--seed", type=int, default=20260919)
    p.add_argument("--warm-project-index", action="store_true",
                   help="prepare project indexes before each timed task in both conditions")
    p.add_argument("--clients", nargs="+", choices=CLIENTS, default=list(CLIENTS),
                   help="clients to evaluate (default: codex claude); selection persists in config")
    p.add_argument("--conditions", nargs="+", choices=ALL_CONDITIONS, default=list(CONDITIONS),
                   help="conditions to schedule (default: baseline dispatcher); indexed and warm_experience add the deep index; "
                        "dispatcher_lean and dispatcher_evidence set the helper's packet mode")
    p.add_argument("--packet-tokens", type=int,
                   help="soft packet target (AGENT_DISPATCHER_PACKET_TOKENS, 256-100000) for both packet-mode arms; default: the helper's own")
    for client in CLIENTS:
        p.add_argument(f"--{client}-model")
        p.add_argument(f"--{client}-effort")
        p.add_argument(f"--{client}-auth", choices=("subscription", "api"), default="subscription")
    for name in ("doctor", "run"):
        p = commands.add_parser(name)
        p.add_argument("--config", type=Path, required=True)
        if name == "run":
            p.add_argument("--suite", choices=("smoke", "pilot"), required=True)
    p = commands.add_parser("review")
    p.add_argument("--batch", type=Path, required=True)
    p.add_argument("--import", dest="ratings", type=Path)
    p = commands.add_parser("report")
    p.add_argument("--batch", type=Path, required=True)
    p = commands.add_parser("audit", help="re-derive cost, usage and helper evidence from saved events; prints JSON, writes nothing into the batch")
    p.add_argument("--batch", type=Path, action="append", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            config_path = prepare(args.output, args.fixtures,
                                  {c: getattr(args, c + "_model") for c in CLIENTS},
                                  {c: getattr(args, c + "_effort") for c in CLIENTS},
                                  {c: getattr(args, c + "_auth") for c in CLIENTS}, args.seed, clients=args.clients,
                                  warm_project_index=args.warm_project_index,
                                  conditions=[c for c in ALL_CONDITIONS if c in args.conditions or c == "baseline"],
                                  packet_tokens=args.packet_tokens)
            print(f"Prepared {config_path}; no model runs started.")
            print("Use native login with the dedicated profile directories in this configuration, or provider API environment variables.")
        elif args.command in ("doctor", "run"):
            config = load_config(args.config, live=True)
            with lock(config["output_dir"]):
                if args.command == "doctor":
                    result = doctor(config)
                    rt.write_json(Path(config["output_dir"]) / "doctor.json", result)
                    print(json.dumps(result, indent=2))
                    return 0 if result["ok"] else 2
                batch = run(config, args.suite)
                print(f"Results: {batch}")
                trials = rt.read_json(batch / "results.json")["trials"]
                if any(t.get("cancelled") for t in trials):
                    return 130
                if any(t["status"] in ("invalid_configuration", "authentication_failure", "infrastructure_error") for t in trials):
                    return 2
                if args.suite == "smoke" and not smoke_ready(rt.read_json(batch / "batch.json"), {"trials": trials}):
                    return 1
        elif args.command == "review":
            from evals.end_to_end.reporting import create_review, import_review
            print(import_review(args.batch, args.ratings) if args.ratings else create_review(args.batch))
        elif args.command == "audit":
            from evals.end_to_end.reporting import audit
            print(json.dumps(audit(args.batch), indent=2, allow_nan=False))
        else:
            from evals.end_to_end.reporting import report
            report(args.batch)
            print(f"Report: {args.batch / 'report.md'}")
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        print("Evaluation error: " + rt.scrub_text(str(exc)), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted; completed trial results are preserved.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
