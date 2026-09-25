#!/usr/bin/env python3
"""Public-release regressions, including the real installer in an isolated config directory.

Run separately from install.sh so installation tests cannot recursively install themselves.
No credentials or live provider requests are used.
"""
import contextlib
import io
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
from decision.cli import main as decision_cli
from decision.providers.mock import HTTPMock
from decision.providers.typesafe import ProviderError, TypeSafeProvider, endpoint

ROOT = Path(__file__).resolve().parents[1]


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


class DecisionResponseTests(unittest.TestCase):
    def test_unusable_agent_answers_follow_the_mode_policy(self):
        for answers in ({}, {"agent": None}, {"agent": {}}, {"agent": {"choice": 42}}):
            for mode in ("auto", "required"):
                with self.subTest(answers=answers, mode=mode), tempfile.TemporaryDirectory() as tmp:
                    env = dict(clean_env(), TYPESAFE_API_KEY="synthetic-review-credential",
                               AGENT_DISPATCHER_DECISION_SCOPES="agent")
                    response = HTTPMock(body={"answers": answers})
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with patch.dict(os.environ, env, clear=True), \
                            patch("decision.providers.typesafe._OPENER.open", response), \
                            contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        code = decision_cli(["--project", tmp, "--mode", mode, "plan",
                                             "--task", "Review this repository", "--json"])
                    self.assertEqual(len(response.requests), 1)
                    if mode == "required":
                        self.assertEqual(code, 2)
                        self.assertEqual(stdout.getvalue(), "")
                        self.assertIn("no usable agent answer", stderr.getvalue())
                    else:
                        self.assertEqual(code, 0, stderr.getvalue())
                        result = json.loads(stdout.getvalue())
                        self.assertIsNone(result["agent"])
                        self.assertEqual(result["engine"], "default")
                        self.assertTrue(result["fallback"])
                        self.assertIn("no-usable-answer", result["fallback_reason"])
                        self.assertTrue(result["decisions"][0]["fallback"])


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

    def test_unrecorded_skill_and_hook_are_preserved(self):
        for index, relative in enumerate(("skills/agent-dispatcher/SKILL.md",
                                          "hooks/agent-dispatcher-activate.sh")):
            for action, args in (("uninstall", ("--uninstall",)), ("install", ())):
                with self.subTest(target=relative, action=action):
                    self.config = self.root / f"unrecorded-{index}-{action}"
                    self.config.mkdir()
                    self.env["CLAUDE_CONFIG_DIR"] = str(self.config)
                    target = self.config / relative
                    target.parent.mkdir(parents=True)
                    target.write_text("user-owned content")
                    settings = self.config / "settings.json"
                    settings.write_text('{"model": "preserve"}')
                    before = {str(p.relative_to(self.config)): p.read_bytes()
                              for p in self.config.rglob("*") if p.is_file()}
                    result = self.run_installer(*args)
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    after = {str(p.relative_to(self.config)): p.read_bytes()
                             for p in self.config.rglob("*") if p.is_file()}
                    self.assertEqual(after, before)

    def test_uninstall_without_manifest_preserves_hook_registration(self):
        import shlex
        script = self.config / "hooks/agent-dispatcher-activate.sh"
        settings = self.config / "settings.json"
        original = json.dumps({"hooks": {"SessionStart": [{"hooks": [
            {"type": "command", "command": "bash " + shlex.quote(str(script))}]}]}})
        settings.write_text(original)
        result = self.run_installer("--uninstall")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(settings.read_text(), original)
        self.assertFalse((self.config / "settings.json.bak-agent-dispatcher").exists())

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
            doctor = subprocess.run([sys.executable, str(pack / "doctor.py"), "all", "--host", "claude",
                                     "--config-dir", str(self.config), "--project", str(self.root),
                                     "--role", "reviewer", "--json"], cwd=self.root, env=self.env,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(doctor.returncode, 0, doctor.stderr)
            report = json.loads(doctor.stdout)
            self.assertEqual(report["host"], "claude")
            self.assertEqual(report["role"], "reviewer")
            self.assertTrue(report["read_only"])
            self.assertTrue(report["entries"])
            self.assertEqual(next(row for row in report["entries"] if row["id"] == "package-files")["status"], "usable")
            project = self.root / "context-project"
            project.mkdir(exist_ok=True)
            subprocess.run(["git", "init", "-q", str(project)], check=True)
            (project / "session.py").write_text("def restore_session():\n    return 'ready'\n")
            selected = subprocess.run([sys.executable, "-B", str(pack / "context.py"),
                                       "--project", str(project), "--task", "Check restore_session",
                                       "--role", "reviewer", "--json"], cwd=self.root, env=self.env,
                                      capture_output=True, text=True, timeout=10)
            self.assertEqual(selected.returncode, 0, selected.stderr)
            self.assertIn("session.py", [row["path"] for row in json.loads(selected.stdout)["context"]])
            # The map is private state outside the project, so ask the helper whether one exists.
            shown = subprocess.run([sys.executable, "-B", str(pack / "project_map.py"), "show",
                                    "--project", str(project), "--json"], cwd=self.root, env=self.env,
                                   capture_output=True, text=True, timeout=10)
            action = "build" if json.loads(shown.stdout)["status"] == "missing" else "refresh"
            mapped = subprocess.run([sys.executable, "-B", str(pack / "project_map.py"), action,
                                     "--project", str(project), "--json"], cwd=self.root, env=self.env,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(mapped.returncode, 0, mapped.stderr)
            self.assertFalse((project / ".agent-dispatcher").exists())
            inspected = subprocess.run([sys.executable, "-B", str(pack / "project_map.py"), "show",
                                        "--project", str(project), "--json"], cwd=self.root, env=self.env,
                                       capture_output=True, text=True, timeout=10)
            self.assertEqual(inspected.returncode, 0, inspected.stderr)
            self.assertTrue(any(row["source"]["path"] == "session.py"
                                for row in json.loads(inspected.stdout)["entries"]))
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


class RecoverableInstallerTests(unittest.TestCase):
    """Real filesystem transactions with deterministic failures; no host config is touched."""
    def setUp(self):
        import install_claude
        self.installer = install_claude
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "source"
        self.config = self.root / "config"
        self.config.mkdir()
        sources = {
            "LICENSE": "MIT fixture license",
            "NOTICE": "Fixture attribution",
            "skills/agent-dispatcher/SKILL.md": "dispatcher v1",
            "skills/agent-dispatcher/INDEX.md": "index",
            "skills/agent-dispatcher/CONTEXT.md": "context",
            "skills/agent-dispatcher/CONTEXT-REFERENCE.md": "context reference",
            "skills/agent-dispatcher/ROLES.md": "roles",
            "skills/agent-dispatcher/CONTROLS.md": "controls",
            "skills/agent-dispatcher/DELEGATION.md": "delegation",
            "skills/agent-dispatcher/PROJECT-MAP.md": "project map",
            "skills/agent-dispatcher/VERIFICATION.md": "verification and preferences",
            "skills/agent-dispatcher/jev.md": "decision guide",
            "skills/agent-dispatcher/roles/implementer.md": "implementer",
            "skills/testing/check/SKILL.md": "guide",
            "recipes/check.md": "recipe",
            "decision/__main__.py": "# inert engine\n",
            "decision/redact.py": "# fixture\n",
            "catalog/loadouts.json": "{}",
            "catalog/resource-paths.json": json.dumps({
                "schema_version": 1, "layout": "source",
                "roles": {"implementer": "skills/agent-dispatcher/roles/implementer.md"},
                "guides": {"check": "skills/testing/check/SKILL.md"},
            }),
            "doctor.py": "# read-only doctor\n",
            "context.py": "# read-only selector\n",
            "context_packet.py": "# whole packet budget\n",
            "context_reuse.py": "# optional retained evidence ledger\n",
            "parser_cache.py": "# private incremental source and parser cache\n",
            "project_graph.py": "# source-backed structural graph\n",
            "repo_index.py": "# repository facts index\n",
            "retrieval.py": "# retrieval engine\n",
            "context_budget.py": "# context budget optimizer\n",
            "llm_retrieval.py": "# optional LLM-assisted retrieval\n",
            "repo_store.py": "# private sqlite stores\n",
            "repo_builder.py": "# deep index builder\n",
            "exploration.py": "# optional onboarding explorer\n",
            "experience.py": "# task experience\n",
            "repository_intelligence.py": "# deep index cli\n",
            "repository_memory.py": "# optional repository memory\n",
            "repo_history.py": "# eligible history\n",
            "learning.py": "# procedural learning lifecycle\n",
            "learning_compose.py": "# procedural learning composition\n",
            "learning_eval.py": "# procedural learning evaluation\n",
            "capability_health.py": "# capability health\n",
            "capability_resolver.py": "# capability resolver\n",
            "skill_intelligence.py": "# skill intelligence\n",
            "skills/agent-dispatcher/LEARNING.md": "procedural learning",
            "skills/agent-dispatcher/MEMORY.md": "repository memory",
            "project_map.py": "# explicit map builder and read-only inspector\n",
            "resources.py": "# read-only package resource resolver\n",
            "verification.py": "# task-scoped check evidence\n",
            "change_audit.py": "# task-scoped observed file changes\n",
            "preferences.py": "# saved dispatcher preferences\n",
            "hooks/agent-dispatcher-activate.sh": "#!/bin/bash\n",
            "commands/agent-reviewer.md": "review v1",
            "commands/agent-implementer.md": "implement v1",
        }
        for relative, value in sources.items():
            target = self.repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(value)
        (self.config / "settings.json").write_text('{"model": "preserve", "hooks": {}}')
        (self.config / "settings.json").chmod(0o600)
        self.build = patch("install_claude.build_and_validate")
        self.build.start()
        self.addCleanup(self.build.stop)
        self.quiet = contextlib.redirect_stdout(io.StringIO())
        self.quiet.__enter__()
        self.addCleanup(self.quiet.__exit__, None, None, None)
        self.installer.install(self.config, self.repo)
        # Legacy registration and an obsolete owned command both need updating. The original
        # user backup also remains exactly as it was, even if the current settings differ.
        settings = json.loads((self.config / "settings.json").read_text())
        settings["hooks"]["SessionStart"][0]["hooks"][0]["command"] = (
            f'bash "{self.config}/hooks/agent-dispatcher-activate.sh"')
        (self.config / "settings.json").write_text(json.dumps(settings, separators=(",", ":")))
        obsolete = self.config / "commands/agent-obsolete.md"
        obsolete.write_text("owned old command")
        with (self.config / self.installer.MANIFEST).open("a") as manifest:
            manifest.write(str(obsolete) + "\n")
        (self.repo / "skills/agent-dispatcher/SKILL.md").write_text("dispatcher v2")
        (self.repo / "commands/agent-reviewer.md").write_text("review v2")
        user = self.config / "commands/agent-user.md"
        user.write_text("unrelated command")
        (self.config / ".agent-dispatcher-active").touch()
        self.before = self.snapshot()

    def snapshot(self):
        return {str(p.relative_to(self.config)): (
            p.lstat().st_mode, os.readlink(p) if p.is_symlink() else p.read_bytes() if p.is_file() else None)
            for p in self.config.rglob("*")}

    def assert_restored(self):
        self.assertEqual(self.snapshot(), self.before, "failed update must restore all prior bytes and modes")

    def test_successful_update_replaces_pack_commands_and_removes_only_obsolete_owned_files(self):
        self.installer.install(self.config, self.repo)
        self.assertEqual((self.config / "skills/agent-dispatcher/SKILL.md").read_text(), "dispatcher v2")
        self.assertTrue((self.config / "skills/agent-dispatcher/doctor.py").is_file())
        pack = self.config / "skills/agent-dispatcher"
        self.assertEqual((pack / "resources.py").read_bytes(), (self.repo / "resources.py").read_bytes())
        self.assertEqual(json.loads((pack / "catalog/resource-paths.json").read_text()), {
            "schema_version": 1, "layout": "claude_manual",
            "roles": {"implementer": "roles/implementer.md"},
            "guides": {"check": "lib/testing/check/SKILL.md"},
        })
        self.assertEqual((self.config / "commands/agent-reviewer.md").read_text(), "review v2")
        self.assertFalse((self.config / "commands/agent-obsolete.md").exists())
        self.assertEqual((self.config / "commands/agent-user.md").read_text(), "unrelated command")
        self.assertEqual((self.config / "settings.json").stat().st_mode & 0o777, 0o600)
        self.assertFalse(list(self.config.glob(".agent-dispatcher-stage-*")))

    def test_staging_copy_failure_preserves_previous_installation(self):
        original = self.installer.copy_file
        def failing_copy(source, target):
            if source == self.repo / "doctor.py":
                raise OSError("simulated full disk while staging doctor")
            return original(source, target)
        with patch("install_claude.copy_file", side_effect=failing_copy), self.assertRaises(OSError):
            self.installer.install(self.config, self.repo)
        self.assert_restored()

    def test_incomplete_staged_pack_is_rejected_before_commit(self):
        (self.repo / "skills/agent-dispatcher/CONTEXT.md").unlink()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.installer.install(self.config, self.repo)
        self.assert_restored()

    def test_build_failure_does_not_touch_the_live_installation(self):
        with patch("install_claude.build_and_validate", side_effect=subprocess.CalledProcessError(1, "build")), \
                self.assertRaises(subprocess.CalledProcessError):
            self.installer.install(self.config, self.repo)
        self.assert_restored()

    def test_failed_replacements_restore_pack_settings_manifest_and_commands(self):
        original = os.replace
        for relative in ("commands/agent-reviewer.md", "settings.json", ".agent-dispatcher-installed"):
            for phase in ("backup", "replacement"):
                with self.subTest(target=relative, phase=phase):
                    failed = False
                    target = self.config / relative
                    def failing_replace(source, destination):
                        nonlocal failed
                        selected = source == target if phase == "backup" else destination == target
                        if not failed and selected:
                            failed = True
                            raise OSError("simulated rename failure")
                        return original(source, destination)
                    with patch("install_claude.os.replace", side_effect=failing_replace), \
                            self.assertRaises(OSError):
                        self.installer.install(self.config, self.repo)
                    self.assertTrue(failed)
                    self.assert_restored()

    def test_interrupt_after_a_completed_rename_restores_previous_installation(self):
        import signal
        original = os.replace
        interrupted = False
        def interrupt_after_replace(source, destination):
            nonlocal interrupted
            result = original(source, destination)
            if destination == self.config / "settings.json" and not interrupted:
                interrupted = True
                signal.raise_signal(signal.SIGTERM)
            return result
        with self.installer.interruptible(), \
                patch("install_claude.os.replace", side_effect=interrupt_after_replace), \
                self.assertRaises(KeyboardInterrupt):
            self.installer.install(self.config, self.repo)
        self.assertTrue(interrupted)
        self.assert_restored()

    def test_failed_fresh_install_removes_new_files_backup_and_directories(self):
        self.config = self.root / "fresh-config"
        self.config.mkdir()
        (self.config / "settings.json").write_text('{"model": "untouched"}')
        self.before = self.snapshot()
        original = os.replace
        failed = False
        def failing_replace(source, destination):
            nonlocal failed
            if destination == self.config / "settings.json" and not failed:
                failed = True
                raise OSError("simulated settings failure")
            return original(source, destination)
        with patch("install_claude.os.replace", side_effect=failing_replace), self.assertRaises(OSError):
            self.installer.install(self.config, self.repo)
        self.assertTrue(failed)
        self.assert_restored()

    def test_failure_during_uninstall_restores_registration_and_owned_files(self):
        original = os.replace
        failed = False
        def failing_replace(source, destination):
            nonlocal failed
            if source == self.config / "skills/agent-dispatcher" and not failed:
                failed = True
                raise OSError("simulated pack removal failure")
            return original(source, destination)
        with patch("install_claude.os.replace", side_effect=failing_replace), self.assertRaises(OSError):
            self.installer.install(self.config, self.repo, uninstall=True)
        self.assertTrue(failed)
        self.assert_restored()

    def test_user_settings_edit_during_staging_is_not_overwritten(self):
        original = self.installer.stage_pack
        updated = b'{"model": "user changed during staging"}'
        def stage_and_edit(repo, destination):
            original(repo, destination)
            (self.config / "settings.json").write_bytes(updated)
        with patch("install_claude.stage_pack", side_effect=stage_and_edit), \
                self.assertRaisesRegex(ValueError, "changed during staging"):
            self.installer.install(self.config, self.repo)
        self.before["settings.json"] = (self.before["settings.json"][0], updated)
        self.assert_restored()

    def test_cleanup_failure_reports_committed_installation(self):
        original = shutil.rmtree
        errors = io.StringIO()
        def failing_cleanup(path, *args, **kwargs):
            if Path(path).name.startswith(".agent-dispatcher-stage-"):
                raise OSError("simulated cleanup permissions failure")
            return original(path, *args, **kwargs)
        with patch("install_claude.shutil.rmtree", side_effect=failing_cleanup), \
                contextlib.redirect_stderr(errors):
            self.installer.install(self.config, self.repo)
        self.assertEqual((self.config / "skills/agent-dispatcher/SKILL.md").read_text(), "dispatcher v2")
        self.assertIn("Installation committed", errors.getvalue())
        self.assertNotIn("previous installation", errors.getvalue().lower())
        self.assertEqual(len(list(self.config.glob(".agent-dispatcher-stage-*"))), 1)

    def test_rollback_failure_keeps_recovery_files(self):
        original = os.replace
        failed = False
        def failing_replace(source, destination):
            nonlocal failed
            if destination == self.config / "settings.json":
                failed = True
                raise OSError("simulated persistent settings failure")
            return original(source, destination)
        with patch("install_claude.os.replace", side_effect=failing_replace), \
                self.assertRaisesRegex(RuntimeError, "recovery files preserved"):
            self.installer.install(self.config, self.repo)
        self.assertTrue(failed)
        workspaces = list(self.config.glob(".agent-dispatcher-stage-*"))
        self.assertEqual(len(workspaces), 1)
        recovery = json.loads((workspaces[0] / "recovery.json").read_text())
        self.assertIn(str(self.config / "settings.json"), [e["target"] for e in recovery["entries"]])
        old_settings = self.before["settings.json"][1]
        self.assertTrue(any(p.is_file() and p.read_bytes() == old_settings
                            for p in workspaces[0].glob("previous-*")))


class GeneratedArtifactTests(unittest.TestCase):
    def test_missing_generated_files_fail_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "source"
            shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv", "dist"))
            for rel in ("commands/agent-reviewer.md", "catalog/loadouts.json"):
                (repo / rel).unlink()
            result = subprocess.run([sys.executable, "-B", "-m", "tests.test_build"], cwd=repo,
                                    env=clean_env(), capture_output=True, text=True, timeout=60)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("commands/agent-reviewer.md", result.stdout)
            self.assertIn("catalog/loadouts.json", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
