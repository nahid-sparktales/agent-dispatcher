#!/usr/bin/env python3
"""Offline reporting/preference integration across relocated host packages.

Builds are isolated; neither the real installation nor personal preferences are used.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def snapshot(directory):
    return {str(path.relative_to(directory)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in directory.rglob("*") if path.is_file()}


class ReportingPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name).resolve()
        cls.source = cls.root / "source"
        cls.source.mkdir()
        # Copy only package/build inputs, without private evaluation runs or user state.
        for name in ("skills", "templates", "recipes", "catalog", "adapters", "commands", "sources",
                     "hooks", "docs", "decision", ".claude-plugin"):
            shutil.copytree(ROOT / name, cls.source / name,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for path in ROOT.iterdir():
            if path.is_file() and (path.suffix in {".py", ".md", ".sh"} or path.name in {"LICENSE", "NOTICE"}):
                shutil.copyfile(path, cls.source / path.name)
        cls.build_home = cls.root / "build-home"
        cls.build_home.mkdir()
        env = dict(os.environ, HOME=str(cls.build_home), XDG_CONFIG_HOME=str(cls.root / "build-config"),
                   PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run([sys.executable, "-B", str(cls.source / "build.py")],
                                cwd=cls.root, env=env, text=True, capture_output=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.codex_plugin = cls.root / "codex-plugin"
        result = subprocess.run([sys.executable, "-B", str(cls.source / "build_codex.py"),
                                 "--output", str(cls.codex_plugin)], cwd=cls.root, env=env,
                                text=True, capture_output=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.codex = cls.codex_plugin / "skills/agent-dispatcher"
        cls.manual = cls.root / "manual-claude"
        code = ("import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
                "from install_claude import stage_pack; stage_pack(Path(sys.argv[1]), Path(sys.argv[2]))")
        result = subprocess.run([sys.executable, "-B", "-c", code, str(cls.source), str(cls.manual)],
                                cwd=cls.root, env=env, text=True, capture_output=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.claude_plugin = cls.root / "relocated-claude-plugin"
        for name in ("skills", "catalog", "decision", ".claude-plugin", "commands"):
            shutil.copytree(cls.source / name, cls.claude_plugin / name)
        cls.layouts = {
            "source": (cls.source, cls.source / "skills/agent-dispatcher", cls.source),
            "claude_manual": (cls.manual, cls.manual, cls.manual),
            "claude_plugin": (cls.claude_plugin / "skills/agent-dispatcher",
                              cls.claude_plugin / "skills/agent-dispatcher", cls.claude_plugin),
            "codex": (cls.codex / "scripts", cls.codex / "references", cls.codex),
        }

    def setUp(self):
        self.case = self.root / self._testMethodName
        self.case.mkdir()
        self.project = self.case / "project"
        self.project.mkdir()
        self.other_project = self.case / "other-project"
        self.other_project.mkdir()
        self.cwd = self.case / "unrelated-cwd"
        self.cwd.mkdir()
        for name in ("preferences", "verification", "context", "resources"):
            (self.cwd / (name + ".py")).write_text("raise AssertionError('Untrusted cwd code was imported')\n")
        self.home = self.case / "home"
        self.home.mkdir()
        self.config = self.case / "config"
        self.state = self.config / "agent-dispatcher"
        self.environment = dict(os.environ, HOME=str(self.home), XDG_CONFIG_HOME=str(self.config),
                                CODEX_HOME=str(self.home / ".codex"),
                                CLAUDE_CONFIG_DIR=str(self.home / ".claude"), PYTHONDONTWRITEBYTECODE="1")
        for name in (".codex/config.toml", ".claude/settings.json", ".claude.json"):
            path = self.home / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("Native settings must remain unchanged.\n")
        for project in (self.project, self.other_project):
            subprocess.run(["git", "init", "-q", str(project)], check=True, env=self.environment,
                           capture_output=True)
            (project / "auth.py").write_text("def login_enabled():\n    return True\n")
            (project / "test_auth.py").write_text(
                "import unittest\nfrom auth import login_enabled\n"
                "class LoginTest(unittest.TestCase):\n"
                "    def test_login_enabled(self):\n        self.assertTrue(login_enabled())\n")

    def invoke(self, layout, helper, *args, expected=0, json_output=True):
        script = self.layouts[layout][0] / helper
        result = subprocess.run([sys.executable, "-B", str(script), *map(str, args)],
                                cwd=self.cwd, env=self.environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, expected, (layout, helper, result.stdout, result.stderr))
        return json.loads(result.stdout) if json_output else result

    def context(self, layout, project=None):
        return self.invoke(layout, "context.py", "--project", project or self.project,
                           "--task", "Inspect login_enabled in auth.py and its test_auth.py tests",
                           "--role", "implementer", "--size", "small", "--json")

    def protected_state(self):
        return [snapshot(path) for path in (self.project, self.other_project, self.home, self.cwd)]

    def test_shared_helpers_are_identical_and_defaults_do_not_write(self):
        before = self.protected_state()
        reports = []
        for layout, (helpers, _refs, _pack) in self.layouts.items():
            with self.subTest(layout=layout):
                for name in ("preferences.py", "verification.py", "change_audit.py"):
                    self.assertEqual((helpers / name).read_bytes(), (ROOT / name).read_bytes())
                shown = self.invoke(layout, "preferences.py", "show", "--json")
                self.assertEqual(shown["output"], "eli5-succinct")
                self.assertEqual(shown["requested_effort"], "host")
                self.assertEqual(shown["effective_effort"], "unknown")
                report = self.context(layout)
                self.assertEqual(report["preferences"]["output"], "eli5-succinct")
                self.assertFalse(report["preferences"]["saved"])
                reports.append({key: report[key] for key in
                                ("retrieval", "context", "excerpts", "excluded", "budget", "preferences")})
        for report in reports[1:]:
            self.assertEqual(report, reports[0])
        self.assertFalse(self.config.exists())
        self.assertEqual(self.protected_state(), before)

    def test_saved_preferences_cross_hosts_and_project_overrides(self):
        before = self.protected_state()
        self.invoke("source", "preferences.py", "set", "--output", "detailed", "--effort", "low", "--json")
        for layout in self.layouts:
            with self.subTest(layout=layout, scope="global"):
                preferences = self.context(layout)["preferences"]
                self.assertEqual((preferences["output"], preferences["requested_effort"]), ("detailed", "low"))
                self.assertEqual(preferences["sources"], {"output": "global", "effort": "global"})
                self.assertEqual(preferences["effective_effort"], "unknown")
                self.assertTrue(preferences["requires_host_confirmation"])
        self.invoke("codex", "preferences.py", "set", "--project", self.project, "--effort", "high", "--json")
        for layout in self.layouts:
            with self.subTest(layout=layout, scope="project"):
                selected = self.context(layout)["preferences"]
                other = self.context(layout, self.other_project)["preferences"]
                self.assertEqual((selected["output"], selected["requested_effort"]), ("detailed", "high"))
                self.assertEqual(selected["sources"], {"output": "global", "effort": "project"})
                self.assertEqual(other["requested_effort"], "low")
        self.assertEqual(self.protected_state(), before)
        self.assertEqual([p.relative_to(self.config).as_posix() for p in self.config.rglob("*") if p.is_file()],
                         ["agent-dispatcher/preferences.json"])

    def test_invalid_preferences_fall_back_without_overwriting_or_leaking_content(self):
        self.state.mkdir(parents=True)
        stored = self.state / "preferences.json"
        stored.write_text("unrecognized-private-settings-content")
        before = self.protected_state(), snapshot(self.config)
        for layout in self.layouts:
            with self.subTest(layout=layout):
                result = self.context(layout)
                preferences = result["preferences"]
                self.assertEqual((preferences["output"], preferences["requested_effort"]), ("eli5-succinct", "host"))
                self.assertEqual(preferences["effective_effort"], "unknown")
                self.assertTrue(preferences["diagnostics"])
                self.assertNotIn(stored.read_text(), json.dumps(result))
                error = self.invoke(layout, "preferences.py", "show", "--json", expected=1)
                self.assertIn("error", error)
                self.assertNotIn(stored.read_text(), json.dumps(error))
        self.assertEqual((self.protected_state(), snapshot(self.config)), before)

    def test_verification_receipts_run_and_read_across_every_layout(self):
        before = self.protected_state()
        receipts = self.case / "task-state"
        receipts.mkdir()
        for layout in self.layouts:
            receipt = receipts / (layout + ".json")
            with self.subTest(layout=layout):
                run = self.invoke(layout, "verification.py", "run", "--project", self.project,
                                  "--receipt", receipt, "--kind", "tests", "--json", "--",
                                  sys.executable, "-B", "-m", "unittest", "discover", "-s", ".", "-p", "test_auth.py")
                evidence = run["observations"][-1]
                self.assertEqual(evidence["outcome"], "tests_passed")
                self.assertEqual(evidence["freshness"], "current")
                self.assertEqual(evidence["execution"]["test_counts"]["run"], 1)
                self.assertEqual(evidence["provenance"], "observed_execution")
                for reader in self.layouts:
                    shown = self.invoke(reader, "verification.py", "show", "--project", self.project,
                                        "--receipt", receipt, "--json")
                    self.assertEqual(shown, run)
        self.assertEqual(self.protected_state(), before)
        self.assertFalse(self.config.exists())
        (self.project / "auth.py").write_text("def login_enabled():\n    return False\n")
        changed = self.protected_state()
        for layout in self.layouts:
            shown = self.invoke(layout, "verification.py", "show", "--project", self.project,
                                "--receipt", receipts / "source.json", "--json")
            self.assertEqual(shown["observations"][-1]["freshness"], "stale")
        self.assertEqual(self.protected_state(), changed)

    def test_temporary_receipts_and_task_audits_work_across_packages(self):
        for layout in self.layouts:
            with self.subTest(layout=layout):
                result = self.invoke(layout, "verification.py", "run", "--project", self.project,
                                     "--kind", "tests", "--json", "--", sys.executable,
                                     "-B", "-m", "unittest", "discover")
                self.assertEqual(result["observations"][-1]["outcome"], "tests_passed")
                self.assertEqual(result["cleanup"]["status"], "removed")
                self.assertTrue(result["cleanup"]["directory_removed"])
                project = self.case / (layout + "-audit-project")
                project.mkdir()
                subprocess.run(["git", "init", "-q", str(project)], check=True, capture_output=True)
                source = project / "auth.py"
                source.write_text("def login_enabled():\n    return True\n")
                (project / ".gitignore").write_text(".agent-dispatcher/\n")
                packet = self.invoke(layout, "context.py", "--project", project, "--task",
                                     "Inspect login_enabled and its dependencies", "--role", "implementer",
                                     "--compact", "--map-maintain", "--audit", "--json")
                state = Path(packet["change_audit"]["state"])
                self.assertTrue(state.is_file())
                source.write_text("def login_enabled():\n    return False\n")
                (project / "untracked.txt").write_text("New task output\n")
                audit = self.invoke(layout, "change_audit.py", "finish", "--project", project,
                                    "--state", state, "--writable-path", "auth.py", "--json", expected=1)
                self.assertTrue(audit["complete"])
                self.assertEqual(audit["changes"]["modified"], ["auth.py"])
                self.assertEqual(audit["out_of_scope"], [".agent-dispatcher/project-graph.json",
                                                       ".agent-dispatcher/project-map.json", "untracked.txt"])
                self.assertEqual(audit["scope_status"], "out_of_scope")
                self.assertEqual(audit["cleanup"]["status"], "removed")
                self.assertFalse(state.parent.exists())

    def test_host_commands_links_and_single_codex_skill(self):
        for layout, (_helpers, refs, pack) in self.layouts.items():
            with self.subTest(layout=layout):
                entry = self.codex / "SKILL.md" if layout == "codex" else refs / "SKILL.md"
                reference = refs / "VERIFICATION.md"
                self.assertTrue(reference.is_file())
                for path in (entry, reference):
                    text = path.read_text()
                    self.assertNotIn("{{", text)
                    for link in re.findall(r"\]\(([^)]+)\)", text):
                        if not re.match(r"[a-z]+://|#", link):
                            self.assertTrue((path.parent / link.split("#")[0]).is_file(), (layout, path, link))
                text = reference.read_text()
                prefix = "PACK/scripts/" if layout == "codex" else "PACK/"
                self.assertIn(prefix + "preferences.py", text)
                self.assertIn(prefix + "verification.py", text)
                command_prefix = "$agent-dispatcher " if layout == "codex" else "/agent-"
                self.assertIn(command_prefix + "preferences", text)
                self.assertIn(command_prefix + "verify", text)
                self.assertIn("ELI5 succinct", text)
                self.assertIn("output compact|verbose", text)
                self.assertIn("effective effort unknown", text)
                if layout == "codex":
                    self.assertNotIn("/agent-verify", text)
                    self.assertNotIn("/agent-preferences", text)
        self.assertEqual(list(self.codex_plugin.rglob("SKILL.md")), [self.codex / "SKILL.md"])
        for pack in (self.manual, self.codex, self.codex_plugin):
            for name in ("NOTICE", "LICENSE"):
                self.assertEqual((pack / name).read_bytes(), (ROOT / name).read_bytes())
        self.assertIn("Copyright (c) 2026 isas1", (self.manual / "NOTICE").read_text())
        for command in ("verify", "preferences"):
            for root in (self.source, self.claude_plugin):
                path = root / "commands" / ("agent-" + command + ".md")
                self.assertTrue(path.is_file())
                self.assertIn("VERIFICATION.md", path.read_text())
        roles = json.loads((self.source / "catalog/loadouts.json").read_text())["roles"]
        for role in roles:
            command = self.source / "commands" / ("agent-" + role["slug"] + ".md")
            self.assertIn("preferences", command.read_text())
            self.assertIn("VERIFICATION.md", command.read_text())


if __name__ == "__main__":
    unittest.main()
