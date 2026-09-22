#!/usr/bin/env python3
"""Offline end-to-end harness tests; no model or authenticated service is invoked."""
import json
import copy
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest.mock import patch

from evals.end_to_end import runtime as rt
from evals.end_to_end import run as runner

ROOT = Path(__file__).resolve().parents[1]


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def execute(self, code, **overrides):
        return rt.execute([sys.executable, "-c", code], cwd=self.root,
                          env={"PATH": os.environ.get("PATH", "")}, prompt="hello",
                          timeout=overrides.pop("timeout", 5), **overrides)

    def test_fake_cli_preserves_json_output_and_exit_status(self):
        result = self.execute("import sys,json; print(json.dumps({'prompt':sys.stdin.read()})); print('diagnostic',file=sys.stderr)")
        self.assertEqual(json.loads(result["stdout"]), {"prompt": "hello"})
        self.assertEqual(result["stderr"], "diagnostic\n")
        self.assertEqual(result["returncode"], 0)
        self.assertFalse(result["timed_out"])

    def test_partial_output_survives_timeout(self):
        result = self.execute("import time; print('partial',flush=True); time.sleep(20)", timeout=0.2)
        self.assertTrue(result["timed_out"])
        self.assertIn("partial", result["stdout"])
        self.assertLess(result["elapsed_seconds"], 4)

    def test_child_inheriting_pipes_does_not_hang_runner(self):
        result = self.execute("import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)']); print('parent exit',flush=True)", timeout=0.2)
        self.assertTrue(result["timed_out"])
        self.assertIn("parent exit", result["stdout"])
        self.assertLess(result["elapsed_seconds"], 4)

    def test_output_is_bounded(self):
        result = self.execute("print('x'*1000000,flush=True)", output_limit=1000)
        self.assertTrue(result["output_overflow"])
        self.assertLessEqual(len(result["stdout"]), 1000)

    def test_symlink_cannot_escape_artifact_snapshot(self):
        (self.root / "link").symlink_to(Path(__file__).resolve())
        with self.assertRaisesRegex(ValueError, "symlinks"):
            rt.tree_files(self.root)

    def test_snapshot_excludes_injected_skill_and_git(self):
        rt.copy_files({"app.py": b"print(1)\n", ".agents/skills/x/SKILL.md": b"guide", ".git/config": b"git"}, self.root)
        self.assertEqual(rt.tree_files(self.root, rt.EXCLUDED), {"app.py": b"print(1)\n"})

    def test_relative_paths_cannot_escape_copy_root(self):
        for name in ("../escape", "/absolute"):
            with self.assertRaisesRegex(ValueError, "unsafe"):
                rt.copy_files({name: b"x"}, self.root)

    def test_scrubbed_json_stream_stays_parseable(self):
        secret = "example-" + "private-credential"
        text = json.dumps({"type": "event", "text": 'key value "' + secret + '"'})
        cleaned = rt.sanitize_stream(text, {"PROVIDER_API_KEY": secret})
        self.assertNotIn(secret, cleaned)
        self.assertIn("[redacted]", json.loads(cleaned)["text"])

    def test_digest_detects_rename_and_content_change(self):
        a = rt.digest_files({"a": b"bc"})
        self.assertNotEqual(a, rt.digest_files({"ab": b"c"}))
        self.assertNotEqual(a, rt.digest_files({"a": b"bd"}))

    def test_generated_authentication_material_is_not_persistable(self):
        for name in (".env", ".env.local", "auth.json", ".codex/config.toml"):
            with self.assertRaisesRegex(ValueError, "credential/configuration"):
                runner.validate_final_artifacts({name: b"not even a secret"}, {})
        value = "private-" + "test-value"
        with self.assertRaisesRegex(ValueError, "active credential"):
            runner.validate_final_artifacts({"report.txt": value.encode()}, {"OPENAI_API_KEY": value})
        runner.validate_final_artifacts({"code.py": b"print(123)"}, {})

    def test_interrupt_returns_partial_evidence(self):
        # The child interrupts a disposable parent runner, never the test process.
        worker = """
import json, os, sys
from evals.end_to_end.runtime import execute
code = "import os,signal,time; print('partial',flush=True); time.sleep(0.15); os.kill(os.getppid(),signal.SIGINT); time.sleep(20)"
result = execute([sys.executable,'-c',code],cwd=os.getcwd(),env=dict(os.environ),prompt='',timeout=5)
print(json.dumps(result))
"""
        import subprocess
        completed = subprocess.run([sys.executable, "-c", worker], cwd=ROOT,
                                   capture_output=True, text=True, timeout=8)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertTrue(result["cancelled"])
        self.assertIn("partial", result["stdout"])

    def test_lock_does_not_remove_another_owners_lock(self):
        with runner.lock(self.root):
            with self.assertRaisesRegex(ValueError, "already running"):
                with runner.lock(self.root):
                    self.fail("acquired second lock")
            self.assertTrue((self.root / ".run-lock").exists())
        self.assertFalse((self.root / ".run-lock").exists())


class LLMSettingsPassThrough(unittest.TestCase):
    def test_llm_settings_reach_the_client_environment_as_a_path_only(self):
        from evals.end_to_end import adapters, run
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "llm.json"
            settings.write_text('{"enabled": true}')
            profile = Path(directory) / "profile"
            base = {"executable": "claude", "model": "m", "effort": "high", "auth": "subscription", "profile_dir": str(profile)}
            self.assertNotIn("AGENT_DISPATCHER_LLM_CONFIG", adapters._environment("claude", base, profile))
            env = adapters._environment("claude", dict(base, llm_settings=str(settings)), profile)
            self.assertEqual(env["AGENT_DISPATCHER_LLM_CONFIG"], str(settings))
            self.assertFalse({k for k in env if "KEY" in k or "TOKEN" in k})
            config = lambda spec: {"schema_version": 1, "seed": 1, "timeout_seconds": 600, "clients": {"claude": spec}}  # noqa: E731
            with self.assertRaisesRegex(ValueError, "llm_settings"):
                run.validate_config(config(dict(base, llm_settings="relative.json")))
            run.validate_config(config(dict(base, llm_settings=str(settings))))


class SchedulingTests(unittest.TestCase):
    fixtures = [{"id": f"task-{i}", "smoke": i < 2} for i in range(15)]

    def test_smoke_and_pilot_counts(self):
        self.assertEqual(len(runner.schedule(self.fixtures, "smoke", 4)), 8)
        self.assertEqual(len(runner.schedule(self.fixtures, "pilot", 4)), 120)

    def test_single_client_counts_and_conditions(self):
        for client in runner.CLIENTS:
            with self.subTest(client=client):
                smoke = runner.schedule(self.fixtures, "smoke", 4, clients=[client])
                pilot = runner.schedule(self.fixtures, "pilot", 4, clients=[client])
                self.assertEqual(len(smoke), 4)
                self.assertEqual(len(pilot), 60)
                self.assertEqual({row['client'] for row in smoke + pilot}, {client})
                for first, second in zip(pilot[::2], pilot[1::2]):
                    self.assertEqual(first['fixture_id'], second['fixture_id'])
                    self.assertEqual(first['repetition'], second['repetition'])
                    self.assertEqual({first['condition'], second['condition']}, set(runner.CONDITIONS))

    def test_client_selection_rejects_empty_duplicate_unknown_and_scalar_inputs(self):
        for clients in ([], {}, ['claude', 'claude'], ['unknown'], 'claude', None):
            with self.subTest(clients=clients), self.assertRaises(ValueError):
                runner.selected_clients(clients)
        self.assertEqual(runner.selected_clients(['claude', 'codex']), runner.CLIENTS)

    def test_single_client_smoke_readiness_rejects_partial_or_wrong_client_evidence(self):
        batch = {'config': {'clients': {'claude': {}}}, 'schedule': [None] * 4}
        trial = {'client': 'claude', 'startup_valid': True, 'usage_observed': True,
                 'status': 'completed', 'condition': 'dispatcher', 'treatment_invoked': True}
        results = {'trials': [dict(trial) for _ in range(4)]}
        self.assertTrue(runner.smoke_ready(batch, results))
        self.assertFalse(runner.smoke_ready(batch, {'trials': results['trials'][:3]}))
        results['trials'][0]['client'] = 'codex'
        self.assertFalse(runner.smoke_ready(batch, results))

    def test_current_suite_keeps_two_smoke_tasks_and_pairs_every_pilot_task(self):
        from evals.end_to_end.grading import load_suite
        fixtures = load_suite()
        self.assertEqual(len(runner.schedule(fixtures, "smoke", 4)), 8)
        pilot = runner.schedule(fixtures, "pilot", 4)
        self.assertEqual(len(pilot), len(fixtures) * len(runner.CLIENTS) * len(runner.CONDITIONS) * 2)
        self.assertEqual({row['fixture_id'] for row in pilot}, {item['id'] for item in fixtures})

    def test_seed_reproduces_pairs_not_best_of_selection(self):
        a = runner.schedule(self.fixtures, "pilot", 41)
        self.assertEqual(a, runner.schedule(self.fixtures, "pilot", 41))
        self.assertNotEqual(a, runner.schedule(self.fixtures, "pilot", 42))
        for i in range(0, len(a), 2):
            first, second = a[i:i + 2]
            self.assertEqual({first["condition"], second["condition"]}, set(runner.CONDITIONS))
            for field in ("client", "fixture_id", "repetition"):
                self.assertEqual(first[field], second[field])

    def test_smoke_missing_invocation_or_startup_is_not_ready(self):
        batch = {"schedule": [None] * 8}
        trial = {"startup_valid": True, "usage_observed": True, "status": "completed", "condition": "dispatcher", "treatment_invoked": True}
        rows = {"trials": [dict(trial) for _ in range(8)]}
        self.assertTrue(runner.smoke_ready(batch, rows))
        rows["trials"][0]["treatment_invoked"] = False
        self.assertFalse(runner.smoke_ready(batch, rows))

    def test_config_requires_explicit_models_for_live_runs(self):
        config = {"schema_version": 1, "seed": 1, "timeout_seconds": 600,
                  "clients": {c: {"auth": "subscription", "executable": c,
                                  "model": None, "effort": None, "profile_dir": "/tmp/eval-profile-" + c}
                              for c in runner.CLIENTS}}
        runner.validate_config(config)
        with self.assertRaisesRegex(ValueError, "explicit model"):
            runner.validate_config(config, live=True)

    def test_single_client_config_and_fingerprint_preserve_selected_scope(self):
        spec = {'auth': 'subscription', 'executable': 'claude', 'model': 'fixed-model',
                'effort': 'medium', 'profile_dir': '/tmp/eval-claude-only'}
        config = {'schema_version': 1, 'seed': 1, 'timeout_seconds': 600,
                  'clients': {'claude': spec}}
        runner.validate_config(config, live=True)
        both = copy.deepcopy(config)
        both['clients']['codex'] = {**spec, 'executable': 'codex', 'profile_dir': '/tmp/eval-codex-other'}
        runner.validate_config(both, live=True)
        self.assertNotEqual(runner.fingerprint(config), runner.fingerprint(both))
        both['clients']['codex']['profile_dir'] = spec['profile_dir'] + '/nested'
        with self.assertRaisesRegex(ValueError, 'separate evaluation profiles'):
            runner.validate_config(both, live=True)
        for clients in ({}, {'unknown': spec}, []):
            with self.subTest(clients=clients), self.assertRaises(ValueError):
                runner.validate_config({**config, 'clients': clients})

    def test_paired_catalog_drift_invalidates_both_sides(self):
        base = {"client": "claude", "fixture_id": "edit", "repetition": 1,
                "starting_files_digest": "same", "cli_version": "v1", "startup_valid": True,
                "status": "completed", "task_success": True}
        rows = [{**base, "condition": "baseline", "diagnostics": [], "startup": {"skills": ["builtin"]}},
                {**base, "condition": "dispatcher", "diagnostics": [], "startup": {"skills": ["builtin", "agent-dispatcher"]}}]
        runner.reconcile_pair(rows)
        self.assertTrue(all(t["status"] == "completed" for t in rows))
        rows[1]["startup"]["skills"].append("personal-skill")
        runner.reconcile_pair(rows)
        self.assertTrue(all(t["status"] == "invalid_configuration" for t in rows))


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    suite.addTests(loader.discover(str(Path(__file__).parent / "e2e"), pattern="test_*.py"))
    raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
