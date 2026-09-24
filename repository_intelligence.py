#!/usr/bin/env python3
"""Deep repository intelligence: explicit onboarding, incremental maintenance, inspection, exploration, experience.

    build     complete admitted inventory -> records, symbols, edges, corpus statistics, bounded history -> published
    refresh   reconcile the working tree incrementally (fast metadata signatures, or --strict content hashes)
    status    read-only coverage, freshness, counters; creates and modifies nothing
    explain   the context helper's ranking through the index, with per-file provenance
    explore   optional model-backed onboarding Explorer (off unless your settings file enables it)
    inferences / experience   inspect, correct, forget stored inferences and task experience
    prune     remove private state
    export    a sanitized JSON document about the repository; never runtime state

Every operation goes through the same admission, redaction and hardened Git rules as the context
helper, and calls shared implementations: repo_builder, repo_store, exploration, experience, context.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
import shutil
import sys
import time

_SIBLINGS = {}


def _sibling(name):
    if name not in _SIBLINGS:
        path = Path(__file__).resolve().with_name(name + ".py")
        namespace = {"__name__": "_dispatcher_ri_" + name, "__file__": str(path)}
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
        _SIBLINGS[name] = namespace
    return _SIBLINGS[name]


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, "repository_intelligence.py: invalid arguments; use --help. Input values withheld.\n")


def _project(value):
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("Project must be an existing readable directory.")
    return root


def _scrub(pack):
    context = _sibling("context")
    return context["_scrubber"](context["find_pack"](pack))


def _identity(args):
    return getattr(args, "identity", None) or os.environ.get("AGENT_DISPATCHER_INDEX_ID") or None


def _directory(root, args):
    return _sibling("repo_store")["state_directory"](root, _identity(args))


def _open_index(root, args, *, create=False, readonly=False):
    return _sibling("repo_store")["IndexStore"](_directory(root, args), create=create, readonly=readonly)


def _overrides(args):
    builder = _sibling("repo_builder")
    settings = builder["load_settings"](getattr(args, "config", None), root_of(args))
    config = builder["_merge"](builder["DEFAULTS"], settings["index"].get("build") or {})
    for item in getattr(args, "set", None) or []:
        key, _, value = item.partition("=")
        cursor = config
        parts = key.split(".")
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = json.loads(value)
    for name, key in (("max_files", "max_files"), ("max_bytes", "max_admitted_bytes"), ("max_seconds", "max_seconds"), ("batch_size", "batch_size")):
        if getattr(args, name, None) is not None:
            config[key] = getattr(args, name)
    if getattr(args, "strict", False):
        config["verify"] = "strict"
    return settings, config


def root_of(args):
    return _project(args.project)


# ---------------------------------------------------------------- commands


def build(args, mode):
    root = root_of(args)
    settings, config = _overrides(args)
    scrub = _scrub(args.pack)
    builder = _sibling("repo_builder")
    if args.dry_run:
        diagnostics = []
        paths, complete = builder["enumerate_inventory"](root, config["max_files"], diagnostics)
        context = _sibling("context")
        admitted = [p for p in paths if not context["_skip"](p)]
        return {"dry_run": True, "mode": mode, "discovered": len(paths), "admitted": len(admitted), "enumeration_complete": complete,
                "policy_excluded": len(paths) - len(admitted), "config": {k: config[k] for k in ("max_files", "max_admitted_bytes", "batch_size", "max_seconds", "verify")},
                "state_directory": str(_directory(root, args)), "diagnostics": diagnostics, "model_calls": 0, "writes": 0}
    with _open_index(root, args, create=mode == "build") as store:
        runner = builder["Builder"](root, store, scrub, config, log=lambda line: print(line, file=sys.stderr, flush=True) if args.progress else None)
        report = runner.run(mode=mode, resume=getattr(args, "resume", False))
        report["state_directory"] = str(store.directory)
        report["disk_bytes"] = store.disk_bytes()
        report["counts"] = store.counts()
    return report


def status(args):
    root = root_of(args)
    store_module, builder = _sibling("repo_store"), _sibling("repo_builder")
    directory = _directory(root, args)
    settings = builder["load_settings"](getattr(args, "config", None), root)
    report = {"read_only": True, "state_directory": str(directory), "index": {"status": "absent"}, "experience": {"status": "absent"},
              "settings": {"index_use": settings["index"]["use"], "maintain": settings["index"]["maintain"]["enabled"],
                           "exploration_enabled": settings["exploration"]["enabled"],
                           "experience_record": settings["experience"]["record"], "experience_use": settings["experience"]["use"]}}
    try:
        with store_module["IndexStore"](directory, readonly=True) as store:
            generation = store.published()
            item = {"status": "published" if generation else "unpublished", "generation": generation, "counts": store.counts(),
                    "disk_bytes": store.disk_bytes(), "integrity": store.integrity(), "building": store.building(),
                    "inferences": {"current": len(store.inferences(status="current")), "stale": len(store.inferences(status="stale"))}}
            if generation:
                item["freshness"] = builder["freshness"](store, root)
                item["policy_current"] = generation["policy"] == builder["policy_fingerprint"](_scrub(args.pack), builder["_merge"](builder["DEFAULTS"], settings["index"].get("build") or {}))
            report["index"] = item
    except ValueError as exc:
        report["index"] = {"status": "absent" if "No repository index" in str(exc) else "unavailable", "detail": str(exc)}
    try:
        with store_module["ExperienceStore"](directory, readonly=True) as events:
            report["experience"] = {"status": "present", "counts": events.counts(), "disk_bytes": events.disk_bytes()}
    except ValueError as exc:
        report["experience"] = {"status": "absent" if "No repository index" in str(exc) else "unavailable", "detail": str(exc)}
    try:  # Procedural learning: read-only summary of the user's own switch and this repository's store.
        learning = _sibling("learning")
        configured = learning["load_settings"](project=root)
        item = {"enabled": configured["enabled"], "mode": configured["mode"], "store": "absent"}
        if learning["store_exists"](directory):
            with learning["open_store"](directory, readonly=True) as store:
                active = store.active_generation()
                item.update(store="present", active_generation=(active or {}).get("generation_id"), counts=store.counts())
        report["learning"] = item
    except ValueError as exc:
        report["learning"] = {"status": "unavailable", "detail": str(exc)}
    return report


def explain(args):
    context = _sibling("context")
    outcome = context["explain_retrieval"](args.project, args.task, strategy=args.strategy, pack=args.pack, exclude_paths=args.exclude_path,
                                           llm=not args.no_llm, repository_index="require", index_identity=_identity(args))
    if args.json:
        return {key: outcome[key] for key in ("query", "ranked", "trace", "packet", "index", "diagnostics") if key in outcome}
    retrieval = _sibling("retrieval")
    text = retrieval["render_explain"](outcome, args.verbose)
    index = outcome.get("index") or {}
    return text + "\n\nREPOSITORY INDEX: " + json.dumps(index, sort_keys=True)


def _universe_and_loader(root, store, scrub, exclude_paths=()):
    """Published indexed files that the current policy still admits, and a policy-checked reader for snippets."""
    context = _sibling("context")
    manual = context["_exclusions"](root, exclude_paths)
    rows = store.file_rows(generation=(store.published() or {}).get("id"))
    universe = {p for p, row in rows.items() if row["status"] == "indexed" and not context["_skip"](p) and not context["_excluded"](p, manual)}

    def loader(path):
        excluded, diagnostics = [], []
        texts, hashes, _, _ = context["_scan_sources"](root, [path], manual, [], None, scrub, excluded, diagnostics)
        if path in texts and hashes[path] == rows[path]["sha256"]:
            return texts[path]
        return None
    return universe, loader


def explore(args):
    root = root_of(args)
    builder, exploration = _sibling("repo_builder"), _sibling("exploration")
    settings = builder["load_settings"](getattr(args, "config", None), root)
    scrub = _scrub(args.pack)
    with _open_index(root, args, readonly=args.dry_run) as store:
        if store.published() is None:
            raise ValueError("No published repository index; run build first.")
        universe, loader = _universe_and_loader(root, store, scrub, args.exclude_path)
        questions = args.question or (None if args.all else exploration["stale_questions"](store))
        if args.dry_run:
            return {"dry_run": True, "model_calls": 0, "enabled": settings["exploration"]["enabled"], "files": len(universe),
                    "brief": exploration["brief"](store, universe), "questions": list(questions or exploration["DEFAULT_QUESTIONS"]),
                    "budget": {k: settings["exploration"][k] for k in ("max_iterations", "max_operations", "max_calls", "max_evidence_bytes",
                                                                       "max_input_tokens", "max_total_output_tokens", "max_seconds", "max_spend_usd")}}
        if not settings["exploration"]["enabled"]:
            raise ValueError("Exploration is not enabled in your repository-intelligence settings file; no model was called.")
        if questions is not None and not questions:
            return {"skipped": "every default question already has current claims; pass --all to ask again", "model_calls": 0}
        explorer = exploration["Explorer"](store, universe, loader, settings["exploration"], scrub)
        report = explorer.run(questions)
        report["inferences"] = [{k: v for k, v in row.items() if k != "model"} for row in report["inferences"]]
        return report


def inferences(args):
    root = root_of(args)
    with _open_index(root, args, readonly=args.action in ("list", "show")) as store:
        if args.action == "list":
            rows = store.inferences(status=None if args.status == "all" else args.status)
            return {"inferences": [{"id": r["id"], "status": r["status"], "uncertainty": r["uncertainty"], "question": r["question"],
                                    "text": r["text"], "evidence": [e.get("path") for e in r["evidence"]], "created": r["created"]} for r in rows]}
        if args.action == "show":
            rows = [r for r in store.inferences(status=None) if r["id"] == args.id]
            if not rows:
                raise ValueError("Unknown inference id.")
            provenance = _sibling("repo_store")["provenance"]
            row = rows[0]
            return dict(row, provenance=provenance(row["id"], "inference", row["producer"], "exploration", row["model"].get("prompt_version") if row["model"] else None,
                                                   path=None, supports=[e["id"] for e in row["evidence"]], snapshot=row["generation"],
                                                   timestamp=row["created"], status=row["status"], invalidation=row["reason"], model=row["model"]))
        with store.transaction():
            if args.all:
                store.delete_inferences()
                return {"forgotten": "all"}
            if args.stale:
                stale = [r["id"] for r in store.inferences(status="stale")]
                store.delete_inferences(stale)
                return {"forgotten": stale}
            if not args.id:
                raise ValueError("Say which inference to forget: an id, --stale or --all.")
            store.delete_inferences([args.id])
            return {"forgotten": [args.id]}


def _edited_from_git(root, revision):
    context = _sibling("context")
    git = shutil.which("git")
    if not git:
        raise ValueError("Git is required for --edited-from-git.")
    if not isinstance(revision, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./^~@{}-]{0,199}", revision) or ".." in revision:
        raise ValueError("--edited-from-git takes one revision name or id, never an option or a range.")
    base = [git, "-c", "core.fsmonitor=false"]
    changed, okay, _ = context["_path_command"](base + ["diff", "--name-only", "--relative", "--no-renames", "--no-ext-diff", "--no-textconv",
                                                        "--ignore-submodules=all", "-z", revision, "--", "."], root)
    if not okay:
        raise ValueError("Git diff could not be read for that revision.")
    untracked, okay, _ = context["_path_command"](base + ["ls-files", "--others", "--exclude-standard", "-z", "--", "."], root)
    return sorted(set(changed) | (set(untracked) if okay else set()))


def experience(args):
    root = root_of(args)
    store_module, module, builder = _sibling("repo_store"), _sibling("experience"), _sibling("repo_builder")
    scrub = _scrub(args.pack)
    directory = _directory(root, args)
    if args.action == "record":
        settings = builder["load_settings"](getattr(args, "config", None), root)
        task = args.task
        if args.task_file:
            task = sys.stdin.read(16000) if args.task_file == "-" else Path(args.task_file).read_text(encoding="utf-8")[:16000]
        retrieved = []
        if args.packet:
            packet = json.loads(Path(args.packet).read_text(encoding="utf-8"))
            retrieved = [row.get("path") for row in packet.get("context", []) if isinstance(row, dict)]
        edited = list(args.edited or [])
        if args.edited_from_git:
            edited += _edited_from_git(root, args.edited_from_git)
        if args.audit:
            audit = json.loads(Path(args.audit).read_text(encoding="utf-8"))
            edited += audit.get("changes", {}).get("added", []) + audit.get("changes", {}).get("modified", [])
        checks = None
        if args.receipt:
            checks = _sibling("verification")["inspect_receipt"](root, args.receipt, pack=args.pack)
        outcome = None
        if args.outcome is not None:  # Verified success comes only from a receipt; a harness may label its own oracle outcome.
            outcome = "grader_passed" if args.outcome == "grader_passed" and args.source == "harness" else module["normalize_outcome"](args.outcome)
        event = module["build_event"](project=root, task_id=args.task_id, task=task, scrub=scrub, role=args.role, config_id=args.config_id,
                                      baseline={"head": builder["git_state"](root)["head"]} if not args.baseline_head else {"head": args.baseline_head},
                                      retrieved=retrieved, inspected=args.inspected, edited=edited, checks=checks, outcome=outcome,
                                      source=args.source, resources=json.loads(args.resources) if args.resources else None)
        with store_module["ExperienceStore"](directory, create=True) as store:
            result = module["record"](store, event, tuple(settings["experience"]["eligible_outcomes"]))
        result["settings"] = {"record": settings["experience"]["record"], "use": settings["experience"]["use"]}
        return result
    readonly = args.action in ("list", "show")
    with store_module["ExperienceStore"](directory, readonly=readonly) as store:
        if args.action == "list":
            rows = store.events(status=None if args.status == "all" else args.status)
            return {"events": [{"id": e["id"], "task_id": e["task_id"], "recorded": e["recorded"], "outcome": e["outcome"], "status": e["status"],
                                "edited": [r["path"] for r in e["edited"]], "summary": e["task"]["summary"]} for e in rows],
                    "counts": store.counts()}
        if args.action == "show":
            event = store.get_event(args.id)
            if event is None:
                raise ValueError("Unknown experience event.")
            return dict(event, corrections=store.corrections(args.id))
        if args.action == "correct":
            return module["correct"](store, args.id, args.path, args.verdict, args.note, scrub)
        return module["forget"](store, event_id=args.event, task_id=args.task, everything=args.all)


def prune(args):
    root = root_of(args)
    store_module = _sibling("repo_store")
    directory = _directory(root, args)
    result = {"state_directory": str(directory), "removed": []}
    for name, flag in ((store_module["INDEX_FILE"], args.index or args.all), (store_module["EXPERIENCE_FILE"], args.experience or args.all)):
        if not flag:
            continue
        cls = store_module["IndexStore"] if name == store_module["INDEX_FILE"] else store_module["ExperienceStore"]
        try:
            with cls(directory, readonly=True):  # Only a file this helper can open as its own store is ever deleted.
                pass
        except ValueError:
            continue
        target = directory / name
        if target.is_symlink() or not target.is_file():
            continue
        target.unlink()
        result["removed"].append(name)
    if args.retired and not args.experience and not args.all:
        try:
            with store_module["ExperienceStore"](directory) as store:
                with store.transaction():
                    removed = store.connection.execute("DELETE FROM events WHERE status IN ('retired','superseded')").rowcount
            result["retired_events_removed"] = removed
        except ValueError as exc:
            result["experience"] = str(exc)
    return result


def export(args):
    root = root_of(args)
    with _open_index(root, args, readonly=True) as store:
        generation = store.published()
        if generation is None:
            raise ValueError("No published repository index to export.")
        document = {"document": "repository-intelligence-export", "note": "A sanitized description, not trusted runtime state.",
                    "generated": int(time.time()), "coverage": generation["coverage"], "snapshot": {k: v for k, v in generation["snapshot"].items() if k != "policy"},
                    "counts": store.counts(),
                    "inferences": [{"text": r["text"], "uncertainty": r["uncertainty"], "status": r["status"], "evidence": [e.get("path") for e in r["evidence"]]}
                                   for r in store.inferences(status="current")]}
    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        return {"written": args.out, "bytes": len(text)}
    return document


# ---------------------------------------------------------------- command line


def main(argv=None):
    parser = SafeParser(prog="repository_intelligence.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True, parser_class=SafeParser)

    def common(command, *, json_only=False):
        command.add_argument("--project", default=".")
        command.add_argument("--pack")
        command.add_argument("--identity", help="Explicit index identity (harness use): maps successive workspaces to one store")
        command.add_argument("--config", help="Settings file outside the project (default: ~/.config/agent-dispatcher/repository-intelligence.json)")
        command.add_argument("--json", action="store_true")

    for name in ("build", "refresh"):
        command = sub.add_parser(name)
        common(command)
        command.add_argument("--strict", action="store_true", help="Re-hash every file's content instead of trusting metadata")
        command.add_argument("--max-files", type=int)
        command.add_argument("--max-bytes", type=int)
        command.add_argument("--max-seconds", type=float)
        command.add_argument("--batch-size", type=int)
        command.add_argument("--set", action="append", default=[], metavar="KEY=JSON")
        command.add_argument("--resume", action="store_true", help="Continue an interrupted generation instead of starting a new one")
        command.add_argument("--dry-run", action="store_true", help="Count what would be indexed; create and write nothing")
        command.add_argument("--progress", action="store_true")
    common(sub.add_parser("status"))
    command = sub.add_parser("explain")
    common(command)
    command.add_argument("task")
    command.add_argument("--strategy", default="full+deep")
    command.add_argument("--exclude-path", action="append", default=[])
    command.add_argument("--verbose", action="store_true")
    command.add_argument("--no-llm", action="store_true")
    command = sub.add_parser("explore")
    common(command)
    command.add_argument("--question", action="append")
    command.add_argument("--all", action="store_true", help="Ask every default question again, not only stale ones")
    command.add_argument("--exclude-path", action="append", default=[])
    command.add_argument("--dry-run", action="store_true", help="Show the brief, questions and budget; call no model")
    command = sub.add_parser("inferences")
    common(command)
    command.add_argument("action", choices=("list", "show", "forget"))
    command.add_argument("id", nargs="?")
    command.add_argument("--status", default="current", choices=("current", "stale", "all"))
    command.add_argument("--stale", action="store_true")
    command.add_argument("--all", action="store_true")
    command = sub.add_parser("experience")
    common(command)
    command.add_argument("action", choices=("record", "list", "show", "correct", "forget"))
    command.add_argument("id", nargs="?")
    command.add_argument("--task-id")
    command.add_argument("--task")
    command.add_argument("--task-file")
    command.add_argument("--role")
    command.add_argument("--config-id")
    command.add_argument("--baseline-head")
    command.add_argument("--packet", help="A context packet JSON: its context rows are the retrieved files")
    command.add_argument("--inspected", action="append")
    command.add_argument("--edited", action="append")
    command.add_argument("--edited-from-git", metavar="REVISION")
    command.add_argument("--audit", help="A change_audit finish result JSON")
    command.add_argument("--receipt", help="A verification receipt; its freshness decides the outcome")
    command.add_argument("--outcome", help="Explicit outcome category, e.g. accepted")
    command.add_argument("--source", default="explicit", choices=("explicit", "harness"))
    command.add_argument("--resources", help="Measured resource use as JSON numbers")
    command.add_argument("--status", default="current", choices=("current", "retired", "superseded", "all"))
    command.add_argument("--path")
    command.add_argument("--verdict", choices=("relevant", "irrelevant"))
    command.add_argument("--note", default="")
    command.add_argument("--event")
    command.add_argument("--all", action="store_true")
    command = sub.add_parser("prune")
    common(command)
    command.add_argument("--index", action="store_true")
    command.add_argument("--experience", action="store_true")
    command.add_argument("--retired", action="store_true", help="Remove retired and superseded experience events only")
    command.add_argument("--all", action="store_true")
    command = sub.add_parser("export")
    common(command)
    command.add_argument("--out")
    # Procedural learning shares this coordinator; learning.py holds the one implementation and its own help.
    command = sub.add_parser("learning", add_help=False)
    command.add_argument("rest", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command == "learning":
        return _sibling("learning")["main"](args.rest)
    try:
        if args.command in ("build", "refresh"):
            result = build(args, args.command)
        elif args.command == "status":
            result = status(args)
        elif args.command == "explain":
            result = explain(args)
        elif args.command == "explore":
            result = explore(args)
        elif args.command == "inferences":
            result = inferences(args)
        elif args.command == "experience":
            if args.action == "record" and not args.task_id:
                raise ValueError("experience record needs --task-id and --task or --task-file.")
            if args.action == "correct" and not (args.id and args.path and args.verdict):
                raise ValueError("experience correct needs an event id, --path and --verdict.")
            result = experience(args)
        elif args.command == "prune":
            result = prune(args)
        else:
            result = export(args)
    except (ValueError, OSError) as exc:
        print(str(exc) if isinstance(exc, ValueError) else "Repository intelligence could not complete; local I/O failed.", file=sys.stderr)
        return 2
    if isinstance(result, str):
        print(result)
    else:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
