#!/usr/bin/env python3
"""Offline Capability Intelligence demonstration: fixture host, real modules, no model, no network, no real state.

    python3 -B evals/capabilities/demo.py [--json]

Runs in a throwaway home (cache, config, a fake Claude configuration and a project) that it removes afterwards. Every
evaluation number below comes from SYNTHETIC records and is labelled so: the demo proves lifecycle wiring, never that a
skill improves anything.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(name):
    path = ROOT / (name + ".py")
    namespace = {"__name__": "_demo_" + name, "__file__": str(path)}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    return namespace


def step(report, name, detail):
    report["steps"].append({"step": name, **detail})
    if not report["json"]:
        print(f"\n== {name}")
        for key, value in detail.items():
            text = value if isinstance(value, str) else json.dumps(value, default=str)
            print(f"  {key}: {text[:600]}")


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_host(home):
    """A fake Claude configuration: valid guidance, broken metadata, a skill whose optional CLI is absent, plugins."""
    config = home / "claude-config"
    write(config / "skills/local-review/SKILL.md", "---\nname: local-review\ndescription: Review a local diff against the repository conventions.\n---\n\n# Local review\n\n## Procedure\n\n1. Read the diff.\n")
    write(config / "skills/broken-guide/SKILL.md", "---\nname: Broken Guide!\n---\nno description\n")
    write(config / "skills/database-debug/SKILL.md", "---\nname: database-debug\ndescription: Debug database failures; can run a local psql fixture when present.\n---\n\n"
          "# Database debug\n\n## Procedure\n\n1. Read the schema files.\n2. When available, use the local CLI.\n\nDynamic context: !`psql --version`\n")
    write(config / "skills/database-debug/manifest.json", json.dumps({"dependencies": {"optional": ["cli:psql-fixture"]}}))
    sentinel = home / "HOOK-RAN"
    plugin = config / "plugins/cache/fixture-market/docs-plugin/1.0.0"
    write(plugin / ".claude-plugin/plugin.json", json.dumps({"name": "docs-plugin", "version": "1.0.0"}))
    write(plugin / "skills/style-guide/SKILL.md", "---\nname: style-guide\ndescription: House writing style.\n---\n\n# Style\n")
    write(plugin / "hooks/hooks.json", json.dumps({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": f"touch {sentinel}"}]}]}}))
    mixed = config / "plugins/cache/fixture-market/issue-plugin/2.0.0"
    write(mixed / ".claude-plugin/plugin.json", json.dumps({"name": "issue-plugin", "version": "2.0.0"}))
    write(mixed / "skills/issue-triage/SKILL.md", "---\nname: issue-triage\ndescription: Triage issues.\n---\n\n# Triage\n")
    write(mixed / ".mcp.json", json.dumps({"mcpServers": {"tracker": {"command": "/nonexistent/server"}}}))
    write(config / "settings.json", json.dumps({"enabledPlugins": {"docs-plugin@fixture-market": True, "issue-plugin@fixture-market": True}}))
    return config, sentinel


def run(home, report):  # noqa: C901 - one linear walkthrough
    health, resolver, skills, learning = load("capability_health"), load("capability_resolver"), load("skill_intelligence"), load("learning")
    project = home / "project"
    write(project / "src/signup.py", "def signup(email):\n    return db.insert('users', email)\n")
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    config, sentinel = build_host(home)
    os.environ["PATH"] = str(home / "bin")  # deterministic CLI discovery: only a fixture `git`, never executed
    write(home / "bin/git", "#!/bin/sh\necho should-never-run > " + str(home / "GIT-RAN") + "\n")
    os.chmod(home / "bin/git", 0o755)
    settings = health["load_settings"](project=project)
    settings["disabled"] = ["optional-chat"]
    snapshot = health["read_snapshot"](json.loads((FIXTURES / "observations.json").read_text()))
    pack, _ = health["find_pack"](str(ROOT))

    # 1-2. Inventory with fixture definitions and synthetic host observations; distinct health states.
    inventory = health["build_inventory"](pack, project, "claude", config, snapshot, settings)
    report_ = health["health_report"](inventory)
    shown = {}
    for entry in report_["entries"]:
        if entry["kind"] in ("skill", "mcp_server", "plugin", "cli") and entry["origin"] != "bundled":
            shown[entry["name"]] = f"{entry['display']} — {entry['qualifier']}" + (f" [{','.join(entry['badges'])}]" if entry.get("badges") else "")
    assert "HEALTHY" in shown["local-review"] and "MISCONFIGURED" in shown["broken-guide"]
    assert shown["database-debug"].startswith("DEGRADED") and "optional" in shown["database-debug"]
    assert shown["design-service"].startswith("AUTH_REQUIRED") and shown["docs-service"].startswith("UNTESTED")
    assert not sentinel.exists() and not (home / "GIT-RAN").exists(), "discovery must never run hooks, dynamic commands or binaries"
    step(report, "1-2 inventory and scoped health (synthetic host observations)", {"entries": shown, "coverage": report_["coverage"],
                                                                                   "hooks_or_binaries_executed": False})
    # 3. Health-aware route with an operation-correct fallback and explicit limits.
    compact = health["compact_snapshot"](inventory, settings)
    settings["health_routing"] = "on"
    plan = resolver["resolve"]("Diagnose why production signup is failing", pack=pack, role="database-engineer", snapshot=compact, settings=settings)
    operation = plan["operations"][0]
    assert plan["role"] == "database-engineer" and operation["status"] == "no_connection_route"
    assert any("target environment not established" in r["reason"] for r in plan["rejected"])
    step(report, "3 resolve: production database diagnosis", {"role": plan["role"], "operation": operation["operation"]["name"] + " @ " + operation["operation"]["environment"],
                                                                "preferred_failed": operation["failed_preferred"], "status": operation["status"], "limits": operation["limits"],
                                                                "rejected_fallbacks": [r for r in plan["rejected"] if "fallback" in r["reason"]]})
    staging_plan = resolver["resolve"]("Check the staging database schema", pack=pack, role="database-engineer", snapshot=compact, settings=settings)
    step(report, "3b resolve: staging read has an equivalent authorized binding", {"operations": [(o["operation"]["name"], o["status"], o.get("via")) for o in staging_plan["operations"]]})
    # 4-5. Offline discovery, quarantine and static review without executing anything.
    found = skills["discover"]("database debugging", settings, pack, offline=FIXTURES / "offline-source.json")
    step(report, "4 discover (offline fixture source; remote sources disabled)", {"query_sent": found["query_sent"], "sources": found["sources"],
                                                                                  "candidates": [(c["name"], c["popularity"][0]["value"] if c["popularity"] else None) for c in found["candidates"]]})
    risky = skills["inspect_candidate"]("offline:fixture-registry/risky-helper", settings, pack, "claude", config_dir=config, project=project, offline=FIXTURES / "offline-source.json")
    good = skills["inspect_candidate"]("offline:fixture-registry/sql-debugging", settings, pack, "claude", config_dir=config, project=project, offline=FIXTURES / "offline-source.json")
    quarantine = health["quarantine_root"]() / good["candidate_id"]
    assert not list(quarantine.rglob("SKILL.md")), "quarantined files never carry a discoverable name"
    assert risky["state"] == "static_review_only" and good["state"] == "eligible_for_isolated_evaluation"
    step(report, "5 quarantine and static review (no execution, no install)", {
        "risky-helper": {"state": risky["state"], "counts": risky["review"]["counts"], "kinds": sorted({f["kind"] for f in risky["review"]["findings"]}),
                         "popularity_reported": risky["popularity"][0]["value"]},
        "sql-debugging": {"state": good["state"], "counts": good["review"]["counts"], "license": good["license"], "local_utility": good["local_utility"]},
        "quarantine_outside_discovery_roots": True})
    # 6. Prepare and analyze paired SYNTHETIC evaluation records through the real report path.
    host_store = health["open_store"](health["host_directory"]("claude", config), readonly=True)
    candidate = host_store.candidate(good["candidate_id"])
    risky_record = host_store.candidate(risky["candidate_id"])
    host_store.close()
    suite = ROOT / "evals/end_to_end/fixtures/manifest.json"
    ids = [f["id"] for f in json.loads(suite.read_text())["fixtures"]]  # splits name real fixture ids
    spec = {"mode": "controlled", "arms": ["dispatcher_control", "dispatcher_candidate"], "host": "claude", "model": "fixture-model", "effort": "medium",
            "fixtures": str(suite), "seed": 11, "budgets": {"max_trials": 200, "max_wall_seconds": 200000},
            "splits": {"development": ids[:2], "validation": ids[2:3], "confirmation": ids[3:15]}, "synthetic": True}
    try:
        skills["prepare_experiment"](risky_record, spec, settings, project=project)
        refused = "ACCEPTED (unexpected)"
    except skills["SkillError"] as exc:
        refused = str(exc)
    experiment = skills["prepare_experiment"](candidate, spec, settings, project=project)
    validation = skills["validate_experiment"](experiment, candidate, settings)
    assert validation["valid"], validation["issues"]
    try:
        skills["authorize_launch"](experiment, settings, actor="demo", suite="smoke")
        launch = "ACCEPTED (unexpected)"
    except skills["SkillError"] as exc:
        launch = str(exc)
    rng = random.Random(5)
    records = []
    for family in spec["splits"]["confirmation"]:
        for repetition in (1, 2):  # noqa: B007 - records below
            base = rng.random() < 0.5
            treated = base or rng.random() < 0.3
            records.append({"task": family, "family": family, "repetition": repetition, "arm": "dispatcher_control", "status": "completed", "success": base,
                            "loaded": None, "cost_usd": None, "elapsed_seconds": 60, "verification": {"required_passed": base}})
            records.append({"task": family, "family": family, "repetition": repetition, "arm": "dispatcher_candidate", "status": "completed", "success": treated,
                            "loaded": repetition == 1 or family != ids[5], "cost_usd": None, "elapsed_seconds": 66, "verification": {"required_passed": treated}})
    analysis = skills["analyze"](experiment, records, settings, synthetic=True)
    assert analysis["synthetic"] and not analysis["eligible_as_evidence"]
    step(report, "6 experiment: prepare, validate, analyze (SYNTHETIC)", {"banner": analysis["banner"], "risky_prepare": refused, "experiment": experiment["experiment_id"],
                                                                         "validation": {"valid": validation["valid"], "scheduled_trials": validation["scheduled_trials"]},
                                                                         "live_launch": launch, "accounting": analysis["accounting"],
                                                                         "primary": {k: analysis["primary"][k] for k in ("tasks", "valid_pairs", "delta_success_pp", "bootstrap_pp", "conservative_pp")},
                                                                         "primary_status": analysis["primary"].get("status"), "category": analysis["category"],
                                                                         "cost": analysis["resources"]["cost_usd"]})
    # 7. Model-specific recommendation with explicit evidence scope; synthetic evidence never counts.
    recommendation = skills["recommend"]("debug failing database queries", pack=pack, project=project, settings=settings, role="database-engineer", snapshot=compact,
                                         candidates=[dict(candidate, state="evaluated")], reports=[analysis], host="claude", model="fixture-model", effort="medium")
    assert recommendation["recommendation"]["action"] == "use_no_additional_skill"
    step(report, "7 recommend (model/host/effort scoped)", {"recommendation": recommendation["recommendation"],
                                                             "alternatives": [(a["name"], a["status"], a["local_utility"]) for a in recommendation["alternatives"]]})
    # 8. Governed proposal: synthetic evidence refused; lifecycle wiring shown in a TEST namespace with the test-only runner, then rolled back.
    try:
        skills["proposal_document"](dict(candidate, state="evaluated"), action="adopt", scope="repo", report=analysis)
        synthetic_refusal = "ACCEPTED (unexpected)"
    except skills["SkillError"] as exc:
        synthetic_refusal = str(exc)
    lsettings = learning["load_settings"](project=project)
    pack = skills["learning_pack"](pack)
    directory = learning["repo_directory"](project)
    store = learning["LearningStore"](directory, create=True, readonly=False, namespace_kind="test")
    document = {"schema_version": 1, "kind": "skill_selection", "operation": "create", "scope": "repo", "target": {"artifact_id": "capabilities"},
                "payload": {"action": "adopt", "candidate_id": candidate["candidate_id"], "content_digest": candidate["content_digest"],
                            "source_identity": "offline:fixture-registry/sql-debugging", "revision": candidate["revision"], "skill_path": "skills/sql-debugging",
                            "execution_profile": "instruction_only", "target_scope": "repo"},
                "applicability": {"roles": ["database-engineer"], "task_terms": ["database", "query"], "min_term_matches": 1},
                "hypothesis": "Fixture walkthrough of the governed lifecycle; no benefit is claimed.", "created_by_kind": "human"}
    proposed = learning["propose_candidate"](store, None, document, lsettings, pack=pack, namespace=directory.name, scope="repo")
    global_refusal = None
    try:
        learning["propose_candidate"](store, None, dict(document, scope="global", payload=dict(document["payload"], target_scope="repo")), lsettings, pack=pack,
                                      namespace=directory.name, scope="global")
    except learning["LearningError"] as exc:
        global_refusal = str(exc)
    evaluation = load("learning_eval")["evaluate_candidate"](store, None, proposed["revision_id"], {
        "schema_version": 1, "objective": "correctness", "runner": "fake_test_runner", "min_paired_families": 6, "min_blocks": 2,
        "environment": {"model": "synthetic", "effort": "n/a", "auth_mode": "none", "cli_version": "none", "seed": 0},
        "data": {"final_test": {"families": [f"f{n}" for n in range(8)]}}}, lsettings, pack=pack, runner="fake_test_runner",
        fixture_results={"pairs": [{"family": f"f{n}", "block": n % 2, "candidate": True, "incumbent": n % 3 == 0} for n in range(8)]})
    with store.transaction():
        store.set_meta("namespace_kind", "production")
    try:
        learning["approve_candidate"](store, None, proposed["revision_id"], evaluation["evaluation_id"], None, {"kind": "human", "actor": "demo-operator"}, lsettings, pack=pack)
        production_refusal = "ACCEPTED (unexpected)"
    except learning["LearningError"] as exc:
        production_refusal = str(exc)
    with store.transaction():
        store.set_meta("namespace_kind", "test")
    approval = learning["approve_candidate"](store, None, proposed["revision_id"], evaluation["evaluation_id"], None, {"kind": "human", "actor": "demo-operator"}, lsettings, pack=pack)
    promotion = learning["promote_candidate"](store, None, proposed["revision_id"], None, lsettings, pack=pack)
    _, live = learning["eligible_revisions"](store, lsettings)
    active = next(dict(r["typed_payload"], revision_id=r["revision_id"]) for r in live if r["artifact_kind"] == "skill_selection")
    target_root = home / "adopted-skills"
    plan = skills["adoption_plan"](dict(candidate), host="claude", scope="repo", project=project, target_root=target_root, learning_state="active")
    applied = skills["apply_adoption"](dict(candidate), plan, active_selection=active, actor="demo-operator")
    rollback = learning["rollback_generation"](store, promotion["generation_id"], None, {"kind": "human", "actor": "demo-operator"}, lsettings, pack=pack)
    _, after = learning["eligible_revisions"](store, lsettings)
    store.close()
    try:
        skills["apply_adoption"](dict(candidate), dict(plan, target=str(target_root / "again")), active_selection=None, actor="demo-operator")
        after_rollback = "ACCEPTED (unexpected)"
    except skills["SkillError"] as exc:
        after_rollback = str(exc)
    step(report, "8 governed proposal, approval boundaries, rollback", {
        "synthetic_report_proposal": synthetic_refusal, "global_from_repo": global_refusal, "revision": proposed["revision_id"][:12],
        "test_runner_in_production_namespace": production_refusal, "approved": approval["approval_id"][:12], "generation": promotion["generation_id"][:12],
        "adoption": {"target": "adopted-skills/" + Path(applied["target"]).name, "applied": applied["applied"]},
        "rollback_to": rollback["restored_from"], "live_selections_after_rollback": sum(1 for r in after if r["artifact_kind"] == "skill_selection"),
        "adopt_after_rollback": after_rollback, "adopted_copy_left_on_disk": (target_root / "sql-debugging").is_dir()})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    home = Path(tempfile.mkdtemp(prefix="capability-demo-")).resolve()
    saved = {k: os.environ.get(k) for k in ("XDG_CACHE_HOME", "XDG_CONFIG_HOME", "PATH", "HOME", "CLAUDE_CONFIG_DIR", "CODEX_HOME")}
    os.environ.update(XDG_CACHE_HOME=str(home / "cache"), XDG_CONFIG_HOME=str(home / "config"), HOME=str(home), CLAUDE_CONFIG_DIR=str(home / "claude-config"),
                      CODEX_HOME=str(home / "codex"))
    report = {"json": args.json, "steps": [], "synthetic": True}
    try:
        run(home, report)
        report["result"] = "complete"
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(home, ignore_errors=True)
    del report["json"]
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("\nDemo complete. Fixture demonstration, not measured product performance; the temporary home was removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
