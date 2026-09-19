#!/usr/bin/env python3
"""Public-release regressions, including the real installer in an isolated config directory.

Run separately from install.sh so installation tests cannot recursively install themselves.
No credentials or live provider requests are used.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from decision.config import Config, load
from decision.providers.mock import HTTPMock
from decision.providers.typesafe import ProviderError, TypeSafeProvider, endpoint

ROOT = Path(__file__).resolve().parent


def clean_env():
    return {k: v for k, v in os.environ.items()
            if not k.startswith(("AGENT_DISPATCHER_", "TYPESAFE_", "CLAUDE_"))}


class ConfigurationTests(unittest.TestCase):
    def test_malformed_project_values_are_ignored(self):
        cases = [[], None, True, "text", {"max_task_chars": float("inf")},
                 {"max_task_chars": 10 ** 400}, {"max_task_chars": -1},
                 {"timeout_seconds": float("nan")}, {"timeout_seconds": -10},
                 {"scopes": {"agent": "false", "skills": 1}},
                 {"thresholds": {"agent_confidence": float("nan"), "skill_relevance": -1}}]
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, clean_env(), clear=True):
            path = Path(tmp) / ".agent-dispatcher-decision.json"
            for value in cases:
                with self.subTest(value=value):
                    path.write_text(json.dumps(value))
                    cfg = load(tmp)
                    self.assertFalse(any(cfg.scopes.values()))
                    self.assertEqual(cfg.max_task_chars, 2000)
                    self.assertEqual(cfg.timeout_seconds, 10)
                    self.assertEqual(cfg.thresholds["agent_confidence"], 0.8)
            path.write_bytes(b"\xff\xfe")
            self.assertFalse(any(load(tmp).scopes.values()))

    def test_invalid_environment_numbers_are_ignored(self):
        for value in ("nan", "inf", "-1", "0", "1e999"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                env = dict(clean_env(), AGENT_DISPATCHER_DECISION_TIMEOUT=value,
                           AGENT_DISPATCHER_DECISION_MAX_TASK_CHARS=value,
                           AGENT_DISPATCHER_DECISION_THRESHOLDS=f"agent_confidence={value}")
                with patch.dict(os.environ, env, clear=True):
                    cfg = load(tmp)
                    self.assertEqual(cfg.timeout_seconds, 10)
                    self.assertEqual(cfg.max_task_chars, 2000)
                    self.assertTrue(0 <= cfg.thresholds["agent_confidence"] <= 1)

    def test_explicit_invalid_limits_raise(self):
        for kw in ({"max_task_chars": float("inf")}, {"timeout_seconds": -1},
                   {"scopes": {"agent": "false"}},
                   {"thresholds": {"agent_confidence": float("nan")}}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                Config(**kw)

    def test_mode_command_recovers_non_object_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".agent-dispatcher-decision.json"
            path.write_text("[]")
            result = subprocess.run([sys.executable, "-m", "decision", "--project", tmp,
                                     "mode", "off"], cwd=ROOT, env=clean_env(),
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(path.read_text()), {"mode": "off"})


class TransportTests(unittest.TestCase):
    def test_endpoint_rejects_unsafe_urls_before_sending(self):
        for url in ("http://localhost:80@example.invalid", "http://127.0.0.1:80@example.invalid",
                    "http://elsewhere.invalid", "ftp://localhost", "https://",
                    "https://user:password@example.invalid", "https://example.invalid:bad",
                    "https://example.invalid?query=1", "https://example.invalid/#fragment",
                    "https://exam\nple.invalid"):
            with self.subTest(url=url), patch.dict(os.environ, {"TYPESAFE_BASE_URL": url}):
                with self.assertRaises(ProviderError):
                    endpoint(Config(), "/v1/systemone")

    def test_endpoint_accepts_https_and_exact_loopback_hosts(self):
        for url in ("https://api.typesafe.ai", "https://example.invalid/proxy",
                    "http://localhost:8080", "http://127.0.0.1:8080", "http://[::1]:8080"):
            with self.subTest(url=url), patch.dict(os.environ, {"TYPESAFE_BASE_URL": url}):
                self.assertEqual(endpoint(Config(), "/v1/systemone"), url + "/v1/systemone")

    def test_transport_errors_cannot_echo_a_credential(self):
        key = "synthetic-" + "credential-for-error-test"
        transport = HTTPMock(raises=urllib.error.URLError(key))
        with patch.dict(os.environ, dict(clean_env(), TYPESAFE_API_KEY=key), clear=True):
            with self.assertRaises(ProviderError) as caught:
                TypeSafeProvider(Config(), opener=transport).evaluate({}, {})
        self.assertNotIn(key, str(caught.exception))
        self.assertIn("could not reach", str(caught.exception))


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root / "config"
        self.config.mkdir()
        self.env = dict(clean_env(), CLAUDE_CONFIG_DIR=str(self.config))

    def run_installer(self, *args, repo=ROOT):
        return subprocess.run(["bash", str(repo / "install.sh"), *args], cwd=self.root,
                              env=self.env, capture_output=True, text=True, timeout=120)

    def test_invalid_settings_leave_existing_files_untouched(self):
        for value in ([], None, {"hooks": []}, {"hooks": {"SessionStart": {}}},
                      {"hooks": {"SessionStart": [None]}},
                      {"hooks": {"SessionStart": [{"hooks": [None]}]}}):
            with self.subTest(value=value):
                settings = self.config / "settings.json"
                settings.write_text(json.dumps(value))
                script = self.config / "hooks" / "agent-dispatcher-activate.sh"
                script.parent.mkdir(exist_ok=True)
                script.write_text("preserve me")
                for args in ((), ("--uninstall",)):
                    result = self.run_installer(*args)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertEqual(script.read_text(), "preserve me")
                    self.assertEqual(settings.read_text(), json.dumps(value))

    def test_manifest_cannot_delete_an_unrelated_file(self):
        unrelated = self.root / "unrelated.md"
        unrelated.write_text("preserve me")
        manifest = self.config / ".agent-dispatcher-installed"
        for entry in (str(unrelated), str(self.config / "commands" / ".." / "unrelated.md")):
            with self.subTest(entry=entry):
                manifest.write_text(entry + "\n")
                result = self.run_installer("--uninstall")
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(manifest.exists())
                self.assertEqual(unrelated.read_text(), "preserve me")

    def test_symlinked_installation_targets_are_refused(self):
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        (self.config / "commands").symlink_to(elsewhere, target_is_directory=True)
        for args in ((), ("--uninstall",)):
            result = self.run_installer(*args)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(elsewhere.iterdir()), [])

    def test_unknown_arguments_do_not_install(self):
        for args in (("--typo",), ("--uninstall", "extra")):
            result = self.run_installer(*args)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(list(self.config.iterdir()), [])

    def test_install_update_hook_and_uninstall(self):
        # Work on a copy: install.sh runs the generator and both validation suites.
        repo = self.root / "source"
        shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(
            ".git", "__pycache__", ".venv", "dist", ".agent-dispatcher-decision.json"))
        self.config = self.root / "config $(touch PWNED) 'quoted'"
        self.config.mkdir()
        self.env["CLAUDE_CONFIG_DIR"] = str(self.config)
        commands = self.config / "commands"
        commands.mkdir()
        user_command = commands / "agent-reviewer.md"
        user_command.write_text("my command mentions the agent-dispatcher skill")
        dangling = commands / "agent-generalist.md"
        dangling.symlink_to(self.root / "absent")
        user_hook = {"type": "command", "command": "echo agent-dispatcher-activate is mine"}
        seed = {"model": "example", "hooks": {"SessionStart": [{"hooks": [user_hook]}]}}
        settings = self.config / "settings.json"
        settings.write_text(json.dumps(seed))
        for iteration in range(2):
            result = self.run_installer(repo=repo)
            self.assertEqual(result.returncode, 0, result.stdout[-2000:] + result.stderr)
            installed = json.loads(settings.read_text())
            hooks = [h for e in installed["hooks"]["SessionStart"] for h in e["hooks"]]
            self.assertIn(user_hook, hooks)
            ours = [h for h in hooks if h != user_hook]
            self.assertEqual(len(ours), 1)
            # Execute the command as Claude does, so shell path escaping is exercised.
            (self.config / ".agent-dispatcher-active").touch()
            hook = subprocess.run(["bash", "-c", ours[0]["command"]], cwd=self.root,
                                  env=self.env, input="{}", capture_output=True,
                                  text=True, timeout=10)
            self.assertEqual(hook.returncode, 0, hook.stderr)
            self.assertIn("AGENT DISPATCHER ACTIVE", hook.stdout)
            self.assertFalse((self.root / "PWNED").exists())
            pack = self.config / "skills" / "agent-dispatcher"
            status = subprocess.run([sys.executable, "-m", "decision", "status"], cwd=pack,
                                    env=self.env, capture_output=True, text=True, timeout=10)
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertIn("No decision scope is enabled", status.stdout)
            if iteration == 0:
                # Emulate a previous release's registration before exercising the update.
                ours[0]["command"] = f'bash "{self.config}/hooks/agent-dispatcher-activate.sh"'
                settings.write_text(json.dumps(installed))
        self.assertEqual(json.loads((self.config / "settings.json.bak-agent-dispatcher").read_text()), seed)
        result = self.run_installer("--uninstall", repo=repo)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(settings.read_text()), seed)
        self.assertTrue(user_command.exists())
        self.assertTrue(dangling.is_symlink())
        self.assertFalse((self.config / "skills" / "agent-dispatcher").exists())
        self.assertFalse((self.config / ".agent-dispatcher-installed").exists())
        self.assertTrue((self.config / ".agent-dispatcher-active").exists())


class GeneratedArtifactTests(unittest.TestCase):
    def test_missing_generated_files_fail_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "source"
            shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv", "dist"))
            for rel in ("commands/agent-reviewer.md", "catalog/loadouts.json"):
                (repo / rel).unlink()
            result = subprocess.run([sys.executable, str(repo / "test_build.py")], cwd=repo,
                                    env=clean_env(), capture_output=True, text=True, timeout=60)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("commands/agent-reviewer.md", result.stdout)
            self.assertIn("catalog/loadouts.json", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
