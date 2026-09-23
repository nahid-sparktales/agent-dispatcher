"""Learned end-to-end arms: configuration, isolated per-arm learning settings, frozen-library import as an authorized
experimental canary, oracle-adjacent observation recording, runtime consumption inside the arm, and reporting. Offline."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from evals.end_to_end import reporting, run as runner, runtime as rt, warmup

ROOT = Path(__file__).resolve().parents[2]


class LearnedConfigTests(unittest.TestCase):
    def config(self, **changes):
        base = {"schema_version": 1, "seed": 1, "timeout_seconds": 600, "output_dir": "/tmp/x", "warm_project_index": False,
                "clients": {"claude": {"auth": "subscription", "executable": "claude", "model": "m", "effort": "high", "profile_dir": "/tmp/profile"}}}
        base.update(changes)
        return base

    def test_learned_conditions_need_a_frozen_library_and_a_human_authorization(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / "library.json"
            library.write_text("{}")
            authorization = {"actor": "tester", "experiment": "exp-1"}
            with self.assertRaisesRegex(ValueError, "learning_library"):
                runner.validate_config(self.config(conditions=["baseline", "learned_skills"]))
            with self.assertRaisesRegex(ValueError, "experiment_authorization"):
                runner.validate_config(self.config(conditions=["baseline", "learned_skills"], learning_library=str(library)))
            with self.assertRaisesRegex(ValueError, "experiment_authorization"):
                runner.validate_config(self.config(conditions=["baseline", "learned_skills"], learning_library=str(library), experiment_authorization={"actor": "tester", "experiment": ""}))
            with self.assertRaisesRegex(ValueError, "learning_library is only"):
                runner.validate_config(self.config(learning_library=str(library)))
            good = self.config(conditions=["baseline", "warm_experience", "learned_skills", "learned_full"], learning_library=str(library), experiment_authorization=authorization)
            runner.validate_config(good)
            self.assertNotEqual(runner.fingerprint(good), runner.fingerprint(self.config()))
            rows = runner.schedule([{"id": "a", "smoke": True}, {"id": "b", "smoke": True}], "smoke", 3, ("claude",), tuple(good["conditions"]))
            self.assertEqual({row["condition"] for row in rows}, set(good["conditions"]))


class LearnedArmTests(unittest.TestCase):
    """The real helpers, a staged package copy and a fake library; no model, no workspace writes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dispatcher-learned-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.output = self.root / "output"
        package = self.output / "packages/claude"
        package.mkdir(parents=True)
        for name in ("repository_intelligence.py", "repo_store.py", "repo_builder.py", "exploration.py", "experience.py", "context.py",
                     "repository_memory.py", "repo_history.py", "learning.py", "learning_compose.py", "learning_eval.py",
                     "repo_index.py", "retrieval.py", "context_budget.py", "llm_retrieval.py", "parser_cache.py", "project_map.py",
                     "project_graph.py", "verification.py", "change_audit.py", "resources.py", "context_packet.py", "context_reuse.py", "preferences.py"):
            (package / name).write_bytes((ROOT / name).read_bytes())
        for rel in ("catalog/loadouts.json", "catalog/resource-paths.json", "catalog/skills.json", "catalog/signals.json", "decision/redact.py", "decision/__init__.py",
                    "skills/quality/systematic-debugging/SKILL.md", "skills/quality/systematic-debugging/manifest.json",
                    "skills/agent-dispatcher/roles/debugger.md", "recipes/debug-application.md", "recipes/debug-application.workflow.json"):
            (package / rel).parent.mkdir(parents=True, exist_ok=True)
            (package / rel).write_bytes((ROOT / rel).read_bytes())
        (self.root / "profile").mkdir()
        self.library = self.root / "library.json"
        self.library.write_text(json.dumps(self.frozen_library()))
        self.config = {"schema_version": 1, "seed": 1, "timeout_seconds": 600, "output_dir": str(self.output), "warm_project_index": False,
                       "conditions": ["baseline", "dispatcher", "warm_experience", "learned_skills"], "experience_outcome": "harness_grader",
                       "warm_experience_eligible": ["grader_passed"], "learning_library": str(self.library),
                       "experiment_authorization": {"actor": "tester", "experiment": "exp-offline"},
                       "clients": {"claude": {"auth": "subscription", "executable": "claude", "model": "fixed", "effort": "high", "profile_dir": str(self.root / "profile")}}}
        runner.validate_config(self.config)
        self.fixture = {"id": "token-fixture", "prompt": "Fix the failing regression bug in validate_token.", "sequence": "seq-a", "step": 1}

    def frozen_library(self):
        """A library frozen from a test-namespace store elsewhere: one repository skill overlay, admitted through the real lifecycle."""
        import context
        import learning
        import learning_eval as le
        env_home = self.root / "library-home"
        os.environ["XDG_CACHE_HOME"] = str(env_home / "cache")  # tests/__init__ already isolates the cache home; this is one more level
        pack = context.find_pack(str(ROOT))
        store = learning.LearningStore(env_home / "state", create=True, readonly=False, namespace_kind="test")
        with store.transaction():
            store.set_meta("pack", str(pack))
        settings = learning.validate_settings(learning._merge(learning.DEFAULTS, {"enabled": True, "mode": "active", "evaluation": {"min_paired_families": 4, "min_blocks": 1}}))
        document = {"schema_version": 1, "kind": "skill_overlay", "operation": "specialize", "scope": "repo", "target": {"artifact_id": "systematic-debugging", "slot": "repository_procedure"},
                    "payload": {"slot": "repository_procedure", "text": "Reproduce with an empty and an expired token before reading callers."},
                    "applicability": {"roles": ["debugger"], "task_terms": ["validate_token", "regression"], "min_term_matches": 1},
                    "hypothesis": "fixture library", "created_by_kind": "human"}
        revision = learning.propose_candidate(store, None, document, settings, pack=pack, namespace="library", scope="repo")["revision_id"]
        le.component_checks(store, revision, settings, pack=pack)
        report = le.evaluate_candidate(store, None, revision, {"schema_version": 1, "objective": "correctness", "runner": "fake_test_runner",
                                                                "environment": {"model": "m", "effort": "e", "auth_mode": "a", "cli_version": "v", "seed": 0}},
                                       settings, pack=pack, runner="fake_test_runner",
                                       fixture_results={"pairs": [{"family": f"f{n}", "block": n % 2, "candidate": True, "incumbent": n % 3 == 0} for n in range(8)]})
        learning.approve_candidate(store, None, revision, report["evaluation_id"], None, {"kind": "human", "actor": "tester"}, settings, pack=pack)
        learning.promote_candidate(store, None, revision, None, settings, pack=pack)
        frozen = learning.export_generation(store, settings)
        store.close()
        return frozen

    def workspace(self, name):
        workspace = self.root / name / "project"
        workspace.mkdir(parents=True)
        (workspace / "auth").mkdir()
        (workspace / "auth/tokens.py").write_text("def validate_token(token):\n    return bool(token)\n")
        (workspace / "README.md").write_text("# demo\n")
        subprocess.run(["git", "init", "-q", str(workspace)], check=True)
        return workspace

    def test_learned_arm_imports_the_library_records_observations_and_consumes_overlays_in_isolation(self):
        workspace = self.workspace("one")
        before = rt.tree_files(workspace, rt.EXCLUDED)
        row = {"id": "claude-token-fixture-1-learned_skills", "client": "claude", "condition": "learned_skills", "fixture_id": "token-fixture", "repetition": 1, "sequence": "seq-a", "step": 1}
        setup = warmup.deep_index_setup(self.config, "claude", workspace, "learned_skills", row, self.fixture)
        self.assertTrue(setup["ok"], setup)
        env = setup["_env"]
        self.assertIn("AGENT_DISPATCHER_LEARNING_CONFIG", env)
        learning_settings = json.loads(Path(env["AGENT_DISPATCHER_LEARNING_CONFIG"]).read_text())
        self.assertEqual((learning_settings["enabled"], learning_settings["mode"], learning_settings["kinds"]), (True, "active", ["skill_overlay"]))
        self.assertEqual(json.loads(Path(env["AGENT_DISPATCHER_MEMORY_CONFIG"]).read_text())["experience"]["retrieval"], "on")
        imported = warmup.learning_setup(self.config, "claude", workspace, "learned_skills", row, self.fixture, env)
        self.assertTrue(imported["ok"], imported)
        self.assertEqual((imported["mode"], imported["model_calls"], imported["libraries"][0]["installed"]), ("import", 0, 1))
        self.assertEqual(rt.tree_files(workspace, rt.EXCLUDED), before)
        # The staged package's own context helper, run inside the arm's environment, composes the imported overlay.
        from evals.end_to_end.adapters import _environment
        spec = dict(self.config["clients"]["claude"], index_env=env)
        child_env = _environment("claude", spec, Path(spec["profile_dir"]))
        child_env["PYTHONDONTWRITEBYTECODE"] = "1"
        execution = rt.execute([sys.executable, "-B", str(self.output / "packages/claude/context.py"), "--project", str(workspace), "--task", self.fixture["prompt"],
                                "--role", "debugger", "--compact", "--guide", "systematic-debugging", "--json"], cwd=workspace, env=child_env, prompt="", timeout=120, output_limit=1_000_000)
        self.assertEqual(execution["returncode"], 0, execution["stderr"])
        packet = json.loads(execution["stdout"])
        self.assertEqual(packet["guidance"]["guides"][0]["source"], "derived")
        self.assertEqual(packet["learning"]["status"], "active")
        self.assertEqual(rt.tree_files(workspace, rt.EXCLUDED), before)
        # The same request in a warm-experience arm (same workspace, its own state) sees no overlay at all.
        warm_row = dict(row, id="claude-token-fixture-1-warm_experience", condition="warm_experience")
        warm = warmup.deep_index_setup(self.config, "claude", workspace, "warm_experience", warm_row, self.fixture)
        self.assertTrue(warm["ok"], warm)
        self.assertFalse(json.loads(Path(warm["_env"]["AGENT_DISPATCHER_LEARNING_CONFIG"]).read_text())["enabled"])
        warm_env = _environment("claude", dict(self.config["clients"]["claude"], index_env=warm["_env"]), Path(spec["profile_dir"]))
        warm_env["PYTHONDONTWRITEBYTECODE"] = "1"
        execution = rt.execute([sys.executable, "-B", str(self.output / "packages/claude/context.py"), "--project", str(workspace), "--task", self.fixture["prompt"],
                               "--role", "debugger", "--compact", "--guide", "systematic-debugging", "--json"], cwd=workspace, env=warm_env, prompt="", timeout=120, output_limit=1_000_000)
        self.assertEqual(execution["returncode"], 0, execution["stderr"])
        self.assertNotIn("learning", json.loads(execution["stdout"]))
        self.assertFalse(json.loads(warmup.disabled_learning_settings(self.config).read_text())["enabled"])
        # After a trial: experience, then an oracle-adjacent observation keyed to that event; a later step does not re-import.
        result = {"status": "completed", "auto_grade": {"passed": True, "checks": [{"name": "behavior"}]}, "usage": {"input_tokens": 100, "output_tokens": 20, "cost_usd": None}, "elapsed_seconds": 3.5}
        final = dict(rt.tree_files(workspace, rt.EXCLUDED))
        final["auth/tokens.py"] = b"def validate_token(token):\n    return bool(token) and token != 'expired'\n"
        record = warmup.record_trial_experience(self.config, "claude", workspace, "learned_skills", row, self.fixture, result, before, final)
        self.assertTrue(record["stored"], record)
        self.assertEqual(record["outcome"], "grader_passed")
        observation = warmup.record_trial_observation(self.config, "claude", workspace, "learned_skills", row, self.fixture, result, record)
        self.assertTrue(observation["stored"], observation)
        self.assertEqual(observation["feedback_class"], "hidden_grader")
        again = warmup.learning_setup(self.config, "claude", self.workspace("two"), "learned_skills", dict(row, step=2), dict(self.fixture, step=2), env)
        self.assertEqual((again["ok"], again["mode"], again["libraries"]), (True, "already_imported", []))
        trials = [{"condition": "learned_skills", "deep_index_setup": setup, "learning_setup": imported, "experience_record": record, "learning_observation": observation, "status": "completed", "task_success": True, "usage": result["usage"]}]
        summary = reporting._setup(trials)
        self.assertEqual((summary["learning_library_imports"], summary["learning_observations_recorded"], summary["learning_feedback_class"]), (1, 1, ["hidden_grader"]))
        self.assertGreater(reporting._cost(trials)["setup_seconds_total"], 0)

    def test_incompatible_library_fails_setup_before_any_model_task(self):
        frozen = json.loads(self.library.read_text())
        frozen["revisions"][0]["base_artifact_digest"] = "0" * 64
        broken = self.root / "broken.json"
        broken.write_text(json.dumps(frozen))
        config = dict(self.config, learning_library=str(broken))
        workspace = self.workspace("three")
        row = {"id": "claude-token-fixture-1-learned_skills", "client": "claude", "condition": "learned_skills", "fixture_id": "token-fixture", "repetition": 1, "sequence": "seq-b", "step": 1}
        setup = warmup.deep_index_setup(config, "claude", workspace, "learned_skills", row, self.fixture)
        self.assertTrue(setup["ok"], setup)
        imported = warmup.learning_setup(config, "claude", workspace, "learned_skills", row, self.fixture, setup["_env"])
        self.assertFalse(imported["ok"])
        self.assertTrue(any("refused" in d or "import" in d for d in imported["diagnostics"]), imported)


if __name__ == "__main__":
    unittest.main()
