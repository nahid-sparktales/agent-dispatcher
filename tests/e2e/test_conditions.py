"""Four-condition support: configuration, chronological scheduling, arm-scoped deep-index setup, experience recording, reporting."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from evals.end_to_end import reporting, run as runner, runtime as rt, warmup

ROOT = Path(__file__).resolve().parents[2]


class ConfigAndScheduleTests(unittest.TestCase):
    def config(self, **changes):
        base = {"schema_version": 1, "seed": 1, "timeout_seconds": 600, "output_dir": "/tmp/x", "warm_project_index": False,
                "clients": {"claude": {"auth": "subscription", "executable": "claude", "model": "m", "effort": "high", "profile_dir": "/tmp/profile"}}}
        base.update(changes)
        return base

    def test_conditions_are_validated_and_change_the_fingerprint(self):
        runner.validate_config(self.config())
        runner.validate_config(self.config(conditions=["baseline", "dispatcher", "indexed", "warm_experience"]))
        runner.validate_config(self.config(conditions=["baseline", "warm_experience"]))
        for bad in (["dispatcher"], ["baseline", "baseline"], ["baseline", "unknown"], ["dispatcher", "baseline"], "baseline", []):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "conditions"):
                runner.validate_config(self.config(conditions=bad))
        with self.assertRaisesRegex(ValueError, "experience_outcome"):
            runner.validate_config(self.config(experience_outcome="model_says_done"))
        self.assertNotEqual(runner.fingerprint(self.config()), runner.fingerprint(self.config(conditions=["baseline", "indexed"])))
        self.assertEqual(runner.conditions_of(self.config()), runner.CONDITIONS)
        self.assertEqual(runner.conditions_of(self.config(conditions=["baseline", "indexed"])), ("baseline", "indexed"))

    def test_sequence_steps_keep_their_order_while_conditions_shuffle_within_a_step(self):
        fixtures = [{"id": "s1-step2", "sequence": "s1", "step": 2, "smoke": False}, {"id": "s1-step1", "sequence": "s1", "step": 1, "smoke": True},
                    {"id": "plain", "smoke": True}, {"id": "s2-step1", "sequence": "s2", "step": 1, "smoke": False}]
        conditions = ("baseline", "dispatcher", "indexed", "warm_experience")
        rows = runner.schedule(fixtures, "pilot", 7, ("claude",), conditions)
        order = [row["fixture_id"] for row in rows]
        self.assertLess(order.index("s1-step1"), order.index("s1-step2"))
        self.assertLess(order.index("s1-step2"), order.index("s2-step1"))
        self.assertEqual(sum(1 for row in rows if row["fixture_id"] == "s1-step1"), 4)  # one repetition per sequenced step
        self.assertEqual(sum(1 for row in rows if row["fixture_id"] == "plain"), 8)  # unsequenced fixtures keep two repetitions
        step_rows = [row for row in rows if row["fixture_id"] == "s1-step1"]
        self.assertEqual({row["condition"] for row in step_rows}, set(conditions))
        self.assertTrue(all(row["sequence"] == "s1" and row["step"] == 1 for row in step_rows))
        orders = {tuple(row["condition"] for row in rows if row["fixture_id"] == name) for name in ("s1-step1", "s1-step2", "s2-step1")}
        self.assertGreater(len(orders), 1)  # seeded shuffling differs between steps
        self.assertEqual(runner.schedule(fixtures, "pilot", 7, ("claude",), conditions), rows)  # deterministic under the seed
        with self.assertRaisesRegex(ValueError, "sequenced fixture"):
            runner.schedule([{"id": "bad", "sequence": "s", "step": "one", "smoke": False}], "pilot", 1, ("claude",))
        plain = runner.schedule([{"id": "a", "smoke": True}, {"id": "b", "smoke": True}], "smoke", 3, ("codex", "claude"))
        self.assertEqual(len(plain), 8)  # unchanged two-condition smoke shape


class ArmSetupTests(unittest.TestCase):
    """The real helper builds and refreshes an arm-scoped index and records experience; no model, no workspace writes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dispatcher-conditions-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.output = self.root / "output"
        package = self.output / "packages/claude"
        package.mkdir(parents=True)
        for name in ("repository_intelligence.py", "repo_store.py", "repo_builder.py", "exploration.py", "experience.py", "context.py",
                     "repository_memory.py", "repo_history.py",
                     "repo_index.py", "retrieval.py", "context_budget.py", "llm_retrieval.py", "parser_cache.py", "project_map.py",
                     "project_graph.py", "verification.py", "change_audit.py", "resources.py", "context_packet.py", "context_reuse.py", "preferences.py"):
            (package / name).write_bytes((ROOT / name).read_bytes())
        for rel in ("catalog/loadouts.json", "catalog/resource-paths.json", "decision/redact.py", "decision/__init__.py"):
            (package / rel).parent.mkdir(parents=True, exist_ok=True)
            (package / rel).write_bytes((ROOT / rel).read_bytes())
        (self.root / "profile").mkdir()
        self.config = {"schema_version": 1, "seed": 1, "timeout_seconds": 600, "output_dir": str(self.output), "warm_project_index": False,
                       "conditions": ["baseline", "indexed", "warm_experience"], "experience_outcome": "harness_grader",
                       "warm_experience_eligible": ["grader_passed"],
                       "clients": {"claude": {"auth": "subscription", "executable": "claude", "model": "fixed", "effort": "high",
                                              "profile_dir": str(self.root / "profile")}}}
        self.fixture = {"id": "step-fixture", "prompt": "Make validate_token reject empty tokens.", "sequence": "seq-a", "step": 1}

    def workspace(self, name, content="def validate_token(token):\n    return True\n"):
        workspace = self.root / name / "project"
        workspace.mkdir(parents=True)
        (workspace / "app.py").write_text(content)
        (workspace / "README.md").write_text("# demo\n")
        subprocess.run(["git", "init", "-q", str(workspace)], check=True)
        return workspace

    def test_build_then_refresh_across_workspaces_with_recording_only_in_the_warm_arm(self):
        first = self.workspace("one")
        before = rt.tree_files(first, rt.EXCLUDED)
        row = {"id": "claude-step-fixture-1-indexed", "client": "claude", "condition": "indexed", "fixture_id": "step-fixture", "repetition": 1, "sequence": "seq-a", "step": 1}
        setup = warmup.deep_index_setup(self.config, "claude", first, "indexed", row, self.fixture)
        self.assertTrue(setup["ok"], setup)
        self.assertEqual((setup["mode"], setup["model_calls"]), ("build", 0))
        self.assertTrue(setup["coverage"]["complete_within_policy"])
        self.assertEqual(rt.tree_files(first, rt.EXCLUDED), before)
        env = setup["_env"]
        self.assertEqual(set(env), {"XDG_CACHE_HOME", "AGENT_DISPATCHER_INDEX_ID", "AGENT_DISPATCHER_INDEX_CONFIG", "AGENT_DISPATCHER_MEMORY_CONFIG"})
        self.assertEqual(json.loads(Path(env["AGENT_DISPATCHER_MEMORY_CONFIG"]).read_text())["experience"]["retrieval"], "off")
        self.assertTrue(env["XDG_CACHE_HOME"].startswith(str(self.output / "state/claude-indexed")))
        self.assertFalse(json.loads(Path(env["AGENT_DISPATCHER_INDEX_CONFIG"]).read_text())["experience"]["use"])
        # A later step of the same sequence lives in a new temporary workspace; the identity maps it to the same store.
        second = self.workspace("two", "def validate_token(token):\n    return bool(token)\n")
        row2 = dict(row, id="claude-step-fixture-2-indexed", step=2)
        setup2 = warmup.deep_index_setup(self.config, "claude", second, "indexed", row2, dict(self.fixture, step=2))
        self.assertTrue(setup2["ok"], setup2)
        self.assertEqual(setup2["mode"], "refresh")
        self.assertEqual(setup2["counters"]["parses"], 1)  # only app.py changed between the two workspaces
        # The warm arm has its own state and records its own experience; the indexed arm never uses any.
        warm_row = dict(row, id="claude-step-fixture-1-warm_experience", condition="warm_experience")
        warm = warmup.deep_index_setup(self.config, "claude", first, "warm_experience", warm_row, self.fixture)
        self.assertTrue(warm["ok"], warm)
        self.assertNotEqual(warm["_env"]["XDG_CACHE_HOME"], env["XDG_CACHE_HOME"])
        self.assertTrue(json.loads(Path(warm["_env"]["AGENT_DISPATCHER_INDEX_CONFIG"]).read_text())["experience"]["use"])
        self.assertEqual(json.loads(Path(warm["_env"]["AGENT_DISPATCHER_MEMORY_CONFIG"]).read_text())["experience"]["retrieval"], "on")
        initial = rt.tree_files(first, rt.EXCLUDED)
        (first / "app.py").write_text("def validate_token(token):\n    return bool(token) and token.strip() != ''\n")
        final = rt.tree_files(first, rt.EXCLUDED)
        result = {"status": "completed", "auto_grade": {"passed": True, "checks": [{"name": "behavior", "passed": True}]}}
        record = warmup.record_trial_experience(self.config, "claude", first, "warm_experience", warm_row, self.fixture, result, initial, final)
        self.assertEqual((record["outcome"], record["stored"], record["eligible"], record["edited"]), ("grader_passed", True, True, 1), record)
        self.assertEqual(warmup.trial_outcome({"status": "task_failure", "auto_grade": {"passed": False, "checks": [{}]}}), "failed_checks")
        self.assertEqual(warmup.trial_outcome({"status": "timeout"}), "cancelled")
        self.assertEqual(warmup.trial_outcome({"status": "completed", "auto_grade": {"passed": True, "checks": []}}), "failed_checks")  # no checks: no success
        self.assertEqual(warmup.trial_outcome({"status": "infrastructure_error"}), "infrastructure_error")
        helper = self.output / "packages/claude/context.py"
        seen = {}
        for condition, arm_env in (("warm_experience", warm["_env"]), ("indexed", env)):
            done = subprocess.run([sys.executable, "-B", str(helper), "--project", str(first), "--task", "validate_token should reject empty tokens", "--json"],
                                  capture_output=True, text=True, env={**os.environ, **arm_env, "HOME": str(self.root)})
            self.assertEqual(done.returncode, 0, done.stderr)
            packet = json.loads(done.stdout)
            seen[condition] = dict(packet["repository_intelligence"]["index"], memory=packet.get("memory"))
        # The unified experience layer: the warm arm's own record votes; the indexed arm has retrieval off.
        self.assertEqual(seen["warm_experience"]["memory"]["layers"]["experience"]["mode"], "on")
        self.assertEqual(seen["warm_experience"]["memory"]["layers"]["experience"]["matches"], 1)
        self.assertTrue(seen["warm_experience"]["memory"]["layers"]["experience"]["applied"])
        self.assertIsNone(seen["indexed"]["memory"])
        self.assertEqual((seen["indexed"]["status"], seen["warm_experience"]["status"]), ("used", "used"))
        stale = warmup.deep_index_setup({**self.config, "output_dir": str(self.root / "missing-package")}, "claude", first, "indexed", row, self.fixture)
        self.assertFalse(stale["ok"])


class ReportingTests(unittest.TestCase):
    def test_four_condition_report_pairs_each_treatment_with_baseline_and_accounts_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch = Path(tmp)
            conditions = ["baseline", "dispatcher", "indexed", "warm_experience"]
            trials, schedule = [], []
            for condition in conditions:
                trial = {"id": f"claude-fx-1-{condition}", "client": "claude", "condition": condition, "fixture_id": "fx", "repetition": 1,
                         "category": "small_edit", "status": "completed", "task_success": condition != "dispatcher",
                         "auto_grade": {"passed": condition != "dispatcher", "checks": [{"name": "behavior", "passed": True}], "human_required": False},
                         "treatment_invoked": condition != "baseline", "elapsed_seconds": 10.0,
                         "usage": {"input_tokens": 100, "output_tokens": 10, "cached_input_tokens": 0, "cost_usd": None},
                         "final_answer": "", "prompt": "p", "acceptance": [], "rubric": {}, "diagnostics": [], "startup_valid": True}
                if condition == "dispatcher":
                    trial["status"], trial["task_success"] = "task_failure", False
                if condition in ("indexed", "warm_experience"):
                    trial["deep_index_setup"] = {"ok": True, "elapsed_seconds": 2.5, "model_calls": 0}
                if condition == "warm_experience":
                    trial["experience_record"] = {"stored": True, "eligible": True, "outcome": "grader_passed"}
                trials.append(trial)
                schedule.append({"client": "claude", "condition": condition, "fixture_id": "fx", "repetition": 1})
            rt.write_json(batch / "batch.json", {"schema_version": 1, "suite": "pilot", "seed": 1, "config": {"conditions": conditions}, "schedule": schedule})
            rt.write_json(batch / "results.json", {"schema_version": 1, "trials": trials})
            with patch.object(reporting, "_packet", return_value={}):
                result = reporting.report(batch)
            client = result["clients"]["claude"]
            self.assertEqual(set(client["conditions"]), set(conditions))
            self.assertEqual(set(client["pairs_by_condition"]), {"dispatcher", "indexed", "warm_experience"})
            self.assertEqual(client["pairs"]["treatment"], "dispatcher")
            self.assertEqual(client["pairs_by_condition"]["dispatcher"]["regressed"], 1)
            self.assertEqual(client["pairs_by_condition"]["indexed"]["both_pass"], 1)
            indexed = client["conditions"]["indexed"]
            self.assertEqual(indexed["setup"]["deep_index_setup"]["median"], 2.5)
            self.assertEqual(indexed["setup"]["setup_model_calls"]["median"], 0)
            self.assertEqual(client["conditions"]["warm_experience"]["setup"]["experience_recorded"], 1)
            self.assertEqual(client["conditions"]["baseline"]["setup"]["deep_index_setup"]["missing"], 1)
            cost = indexed["cost_accounting"]
            self.assertEqual((cost["attempted"], cost["verified_successes"]), (1, 1))
            self.assertIsNone(cost["amortized_cost_usd_per_task"])  # unknown cost stays unknown, never zero
            self.assertEqual(cost["setup_seconds_total"], 2.5)
            text = (batch / "report.md").read_text()
            self.assertIn("| Metric | Baseline | Dispatcher | Indexed | Warm-experience |", text)
            self.assertIn("Paired outcomes (warm_experience versus baseline)", text)
            self.assertTrue(any("Deep-index conditions" in line for line in result["limitations"]))
            # Two-condition batches keep their previous shape.
            rt.write_json(batch / "batch.json", {"schema_version": 1, "suite": "pilot", "seed": 1, "config": {}, "schedule": schedule[:2]})
            rt.write_json(batch / "results.json", {"schema_version": 1, "trials": trials[:2]})
            with patch.object(reporting, "_packet", return_value={}):
                result = reporting.report(batch)
            self.assertEqual(set(result["clients"]["claude"]["conditions"]), {"baseline", "dispatcher"})
            self.assertIn("| Metric | Baseline | Dispatcher |", (batch / "report.md").read_text())


if __name__ == "__main__":
    unittest.main()
