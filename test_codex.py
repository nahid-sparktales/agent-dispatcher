#!/usr/bin/env python3
"""Offline integration tests for the self-contained Codex package and native activation."""
import contextlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import build
from build_codex import export_package
from install_codex import activation_module, install
from install_claude import stage_pack

ROOT = Path(__file__).resolve().parent


class CodexPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root = Path(cls.tmp.name).resolve()
        with contextlib.redirect_stdout(io.StringIO()):
            cls.data = build.main()
            cls.plugin = cls.root / "agent-dispatcher"
            cls.pack = export_package(cls.plugin, cls.data)

    def test_one_discoverable_skill_with_all_shared_guides(self):
        self.assertEqual(list(self.plugin.rglob("SKILL.md")), [self.pack / "SKILL.md"])
        guides = list((self.pack / "references/skills").glob("*/*/GUIDE.md"))
        self.assertEqual(len(guides), len(self.data["skills"]))
        for meta in self.data["skills"]:
            guide = self.pack / "references/skills" / meta["category"] / meta["id"] / "GUIDE.md"
            self.assertEqual(guide.read_bytes(), (ROOT / meta["path"]).read_bytes())
        self.assertEqual(len(list((self.pack / "references/roles").glob("*.md"))), len(self.data["roles"]))
        self.assertEqual(len(list((self.pack / "references/recipes").glob("*.md"))), len(self.data["recipes"]))

    def test_references_and_host_translation(self):
        references = [self.pack / "references" / name for name in build.REFERENCE_FILES]
        for file in [self.pack / "SKILL.md", *references]:
            self.assertTrue(file.is_file(), str(file))
            self.assertNotIn("{{", file.read_text(), str(file))
            for link in re.findall(r"\]\(([^)]+)\)", file.read_text()):
                if not re.match(r"[a-z]+://|#", link):
                    self.assertTrue((file.parent / link.split('#')[0]).is_file(), f"broken link: {file}: {link}")
        index = (self.pack / "references/INDEX.md").read_text()
        for relative in re.findall(r"`(references/[^`]+\.md)`", index):
            self.assertTrue((self.pack / relative).is_file(), relative)
        for role in (self.pack / "references/roles").glob("*.md"):
            text = role.read_text()
            self.assertNotIn("ExitPlanMode", text)
            self.assertNotIn("~/.claude", text)
        self.assertNotIn("PYTHONPATH=<pack>", (self.pack / "references/CONTEXT.md").read_text())
        for name in build.TEMPLATED_REFERENCES:
            text = (self.pack / "references" / name).read_text()
            self.assertNotIn("~/.claude", text)
            self.assertNotIn("CLAUDE_CONFIG_DIR", text)
            self.assertNotIn("python3 -m decision", text)

    def test_entrypoint_budgets_and_required_reading_scenarios(self):
        baseline = json.loads((ROOT / "evals/context/instruction-baseline.json").read_text())
        for host, pack in (("claude", ROOT / "skills/agent-dispatcher"), ("codex", self.pack)):
            refs = pack if host == "claude" else pack / "references"
            sizes = {name: (refs / name).stat().st_size for name in build.REFERENCE_FILES}
            sizes["SKILL.md"] = (pack / "SKILL.md").stat().st_size
            for name in ("SKILL.md", "CONTEXT.md"):
                self.assertLessEqual(sizes[name], 6144, (host, name, sizes[name]))
            scenarios = {
                "forced_role": sizes["SKILL.md"] + sizes["ACTIVITY.md"],
                "ordinary_routing": sizes["SKILL.md"] + sizes["ACTIVITY.md"] + sizes["ROLES.md"],
                "context_inspection": sizes["SKILL.md"] + sizes["CONTEXT.md"],
                "activation": sizes["SKILL.md"] + sizes["CONTROLS.md"],
            }
            for name, size in scenarios.items():
                self.assertLess(size, baseline["hosts"][host]["scenario_bytes"][name], (host, name, size))
            for name in ("ROLES.md", "CONTROLS.md", "DELEGATION.md", "CONTEXT.md"):
                self.assertIn(name, (pack / "SKILL.md").read_text())
            self.assertIn("CONTEXT-REFERENCE.md", (refs / "CONTEXT.md").read_text())
            entry = (pack / "SKILL.md").read_text()
            self.assertIn("If a user enabled an optional decision scope", entry)
            self.assertIn("--agent", entry)
            self.assertIn("CONTEXT-REFERENCE.md", entry)

    def test_context_selection_matches_source_manual_and_codex_without_writes(self):
        project = self.root / "selector-project"
        project.mkdir()
        subprocess.run(["git", "init", "-q", str(project)], check=True)
        (project / "auth.py").write_text("def validate_login(password):\n    return bool(password)\n")
        (project / "test_auth.py").write_text("from auth import validate_login\ndef test_login():\n    assert validate_login('example')\n")
        (project / "settings.py").write_text("LOGIN_ENABLED = True\n")
        manual = self.root / "manual-context-pack"
        stage_pack(ROOT, manual)
        scripts = [ROOT / "context.py", manual / "context.py", self.pack / "scripts/context.py",
                   ROOT / "skills/agent-dispatcher/context.py"]
        self.assertEqual(scripts[0].read_bytes(), scripts[1].read_bytes())
        self.assertEqual(scripts[0].read_bytes(), scripts[2].read_bytes())
        self.assertEqual(scripts[0].read_bytes(), (ROOT / "skills/agent-dispatcher/context.py").read_bytes())
        def snapshot(folder):
            return {str(p.relative_to(folder)): (p.read_bytes(), p.stat().st_mtime_ns)
                    for p in folder.rglob("*") if p.is_file()}
        before = [snapshot(folder) for folder in (project, manual, self.pack)]
        outputs = []
        for script in scripts:
            env = dict(os.environ, AGENT_DISPATCHER_DECISION_MODE="required", PYTHONDONTWRITEBYTECODE="1")
            result = subprocess.run([sys.executable, "-B", str(script), "--project", str(project),
                                     "--task-file", "-", "--role", "debugger", "--size", "small", "--json"],
                                    input="Fix validate_login in auth.py and check related login tests", text=True,
                                    capture_output=True, cwd=self.root, env=env, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(any(row["path"] == "auth.py" for row in report["context"]))
            self.assertTrue(report["excerpts"])
            outputs.append({k: report[k] for k in ("retrieval", "context", "excerpts", "excluded", "budget")})
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0], outputs[2])
        self.assertEqual(outputs[0], outputs[3])
        self.assertEqual(before, [snapshot(folder) for folder in (project, manual, self.pack)])

    def test_inventory_is_complete_and_paths_resolve_in_each_host(self):
        inventory = json.loads((self.pack / "references/INVENTORY.json").read_text())
        claude = json.loads((ROOT / "skills/agent-dispatcher/INVENTORY.json").read_text())
        self.assertEqual({row["id"] for row in inventory["local_skills"]},
                         {row["id"] for row in self.data["skills"]})
        for category, registry in (("external_skills", "external"), ("tools_and_mcps", "mcp")):
            self.assertEqual({row["id"] for row in inventory[category]}, set(self.data[registry]))
            self.assertEqual(inventory[category], claude[category])
        for item in inventory["local_skills"]:
            self.assertTrue(all((self.pack / path).is_file() for path in item["paths"]), item["id"])
            self.assertNotIn("status", item)  # availability belongs to the live session
        for item in claude["local_skills"]:
            self.assertTrue(any((ROOT / "skills/agent-dispatcher" / path).is_file()
                                for path in item["paths"]), item["id"])
        self.assertEqual((self.pack / "references/INVENTORY.md").read_text(),
                         (ROOT / "INVENTORY.template.md").read_text())
        # Editing metadata must flow into the shipped inventory rather than a second catalog.
        for row in inventory["tools_and_mcps"]:
            self.assertEqual(row["source"], self.data["mcp"][row["id"]].get("source"))
            self.assertEqual(row["auth"], self.data["mcp"][row["id"]].get("auth"))

    def test_optional_decision_cli_runs_outside_package(self):
        project = self.root / "project"
        project.mkdir(exist_ok=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("TYPESAFE_", "AGENT_DISPATCHER_"))}
        prefix = [sys.executable, str(self.pack / "scripts/decide.py"), "--project", str(project)]
        result = subprocess.run(prefix + ["status"], cwd=project, env=env,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No decision scope is enabled", result.stdout)
        result = subprocess.run(prefix + ["mode", "off"], cwd=project, env=env,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((project / ".agent-dispatcher-decision.json").read_text()), {"mode": "off"})
        result = subprocess.run(prefix + ["plan", "--task", "Review a patch", "--agent", "reviewer", "--json"],
                                cwd=project, env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["agent"]["id"], "reviewer")
        self.assertFalse(list(self.pack.rglob(".agent-dispatcher-decision.json")))

    def test_doctor_is_bundled_with_shared_procedure_and_inventory(self):
        self.assertEqual((self.pack / "scripts/doctor.py").read_bytes(),
                         (ROOT / "doctor.py").read_bytes())
        self.assertEqual((self.pack / "references/DOCTOR.md").read_bytes(),
                         (ROOT / "DOCTOR.template.md").read_bytes())
        self.assertEqual((ROOT / "skills/agent-dispatcher/doctor.py").read_bytes(),
                         (ROOT / "doctor.py").read_bytes())
        self.assertIn("references/DOCTOR.md", (self.pack / "SKILL.md").read_text())
        self.assertIn("DOCTOR.md", (ROOT / "commands/agent-doctor.md").read_text())

    def test_doctor_cli_reconciles_session_evidence_outside_package(self):
        project = self.root / "doctor-project"
        config = self.root / "doctor-config"
        project.mkdir(exist_ok=True)
        config.mkdir(exist_ok=True)
        evidence = {"schema_version": 1,
                    "mcps": [{"id": "github-session", "catalog_id": "github", "status": "verified"}],
                    "tools": [{"id": "mcp__github__list_issues", "server": "github-session", "status": "verified"},
                              {"id": "native_read_file", "status": "exposed"}],
                    "skills": [{"id": "extra-host-guide", "status": "exposed"}],
                    "disabled": ["slack"]}
        before = {str(p.relative_to(self.pack)): p.read_bytes()
                  for p in self.pack.rglob("*") if p.is_file()}
        result = subprocess.run([sys.executable, "-B", str(self.pack / "scripts/doctor.py"),
                                 "all", "--project", str(project), "--config-dir", str(config),
                                 "--role", "reviewer", "--evidence", "-", "--json"],
                                cwd=project, input=json.dumps(evidence),
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["read_only"])
        self.assertEqual(report["host"], "codex")
        self.assertEqual(report["role"], "reviewer")
        entries = {(row["category"], row["id"]): row for row in report["entries"]}
        self.assertEqual(sum(kind == "bundled_skill" for kind, _ in entries), len(self.data["skills"]))
        self.assertEqual(entries["mcp_server", "github"]["status"], "usable")
        self.assertEqual(entries["mcp_server", "github"]["evidence"], "verified")
        self.assertEqual(entries["mcp_server", "slack"]["status"], "blocked")
        self.assertEqual(entries["mcp_tool", "mcp__github__list_issues"]["status"], "usable")
        self.assertIn(("host_skill", "extra-host-guide"), entries)
        self.assertIn(("native_tool", "native_read_file"), entries)
        self.assertNotIn("github", [row["id"] for row in report["recommendations"]])
        self.assertEqual(list(project.iterdir()), [])
        self.assertEqual(list(config.iterdir()), [])
        self.assertEqual(before, {str(p.relative_to(self.pack)): p.read_bytes()
                                  for p in self.pack.rglob("*") if p.is_file()})

    def test_plugin_manifest_and_hook_use_codex_contract(self):
        manifest = json.loads((self.plugin / ".codex-plugin/plugin.json").read_text())
        source = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())
        self.assertEqual(manifest["version"], source["version"])
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertEqual(manifest["name"], self.plugin.name)
        hook = json.loads((self.plugin / "hooks/hooks.json").read_text())["hooks"]["SessionStart"][0]
        self.assertIn("${PLUGIN_ROOT}", hook["hooks"][0]["command"])
        self.assertNotIn("CLAUDE", hook["hooks"][0]["command"])

    def test_export_is_deterministic_and_self_contained(self):
        second = self.root / "second"
        export_package(second, self.data)
        def files(root):
            return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*")
                    if p.is_file() and "__pycache__" not in p.parts}
        self.assertEqual(files(self.plugin), files(second))
        self.assertFalse(any(p.is_symlink() for p in self.plugin.rglob("*")))


class CodexActivationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.config = self.root / "codex config"
        self.config.mkdir()
        self.project = self.root / "project"
        self.project.mkdir()
        self.activation = activation_module()

    def run_control(self, *args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return self.activation.main([*args, "--config-dir", str(self.config)])

    def hook(self, payload):
        result = subprocess.run([sys.executable, str(ROOT / "adapters/codex/activate.py"),
                                 "hook", "--config-dir", str(self.config)],
                                input=payload, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return result.stdout

    def test_activation_and_silence_scopes(self):
        payload = json.dumps({"session_id": "session-1", "cwd": str(self.project)})
        self.assertEqual(self.hook(payload), "")
        (self.project / ".agent-dispatcher-on").touch()
        self.assertEqual(self.hook(payload), "", "a cloned repository armed the hook")
        self.assertEqual(self.run_control("on", "--scope", "project", "--project", str(self.project)), 0)
        output = json.loads(self.hook(payload))["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "SessionStart")
        self.assertIn("AGENT DISPATCHER ACTIVE", output["additionalContext"])
        self.assertEqual(self.hook(json.dumps({"session_id": "s2", "cwd": str(self.root)})), "")
        self.assertEqual(self.run_control("on", "--scope", "global"), 0)
        self.assertEqual(self.run_control("off", "--scope", "project", "--project", str(self.project)), 0)
        self.assertEqual(self.hook(payload), "", "global activation ignored project silence")
        self.assertEqual(self.run_control("on", "--scope", "project", "--project", str(self.project)), 0)
        self.assertEqual(self.run_control("off", "--scope", "session", "--session", "session-1"), 0)
        self.assertEqual(self.hook(payload), "")
        self.assertTrue(self.hook(json.dumps({"session_id": "session-2", "cwd": str(self.project)})))
        self.assertEqual(self.run_control("off", "--scope", "global"), 0)
        self.assertTrue(self.hook(json.dumps({"session_id": "session-2", "cwd": str(self.project)})))
        self.assertEqual(self.run_control("off", "--scope", "session", "--session", "../bad"), 1)

    def test_malformed_payload_and_state_fail_closed(self):
        for payload in ("", "{", "[]", '{"cwd":42}', '{"cwd":"relative"}',
                        json.dumps({"cwd": str(self.project), "session_id": "../bad"}), " " * 65537):
            self.assertEqual(self.hook(payload), "")
        path = self.config / "agent-dispatcher/state.json"
        path.parent.mkdir()
        for value in ([], {"global_enabled": "false"}, None):
            path.write_text(json.dumps(value))
            self.assertEqual(self.hook(json.dumps({"cwd": str(self.project)})), "")

    def test_hook_is_read_only_and_preserves_unrelated_settings(self):
        other = {"type": "command", "command": "echo original"}
        seed = {"description": "mine", "hooks": {"SessionStart": [{"hooks": [other]}]}}
        path = self.config / "hooks.json"
        path.write_text(json.dumps(seed))
        self.assertEqual(self.run_control("on"), 0)
        state = self.config / "agent-dispatcher/state.json"
        before = state.read_bytes(), path.read_bytes()
        self.hook(json.dumps({"cwd": str(self.project), "session_id": "s"}))
        self.assertEqual(before, (state.read_bytes(), path.read_bytes()))
        self.activation.manage_hook(self.config, remove=True)
        self.assertEqual(json.loads(path.read_text()), seed)
        self.assertEqual(json.loads((self.config / "hooks.json.bak-agent-dispatcher").read_text()), seed)

    def test_invalid_hook_config_does_not_arm(self):
        (self.config / "hooks.json").write_text("[]")
        self.assertEqual(self.run_control("on"), 1)
        self.assertFalse((self.config / "agent-dispatcher/state.json").exists())


class CodexInstallTests(unittest.TestCase):
    def test_install_update_and_uninstall_preserve_neighbors(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp).resolve()
            skills, config = root / "skills with 'quotes'", root / "codex"
            config.mkdir()
            skills.mkdir()
            (skills / "unrelated").mkdir()
            (skills / "unrelated/SKILL.md").write_text("mine")
            other = {"type": "command", "command": "echo agent-dispatcher is my text"}
            original = {"hooks": {"SessionStart": [{"hooks": [other]}]}}
            (config / "hooks.json").write_text(json.dumps(original))
            target = install(skills, config)
            self.assertEqual(json.loads((config / "hooks.json").read_text()), original)
            self.assertFalse((config / "agent-dispatcher/state.json").exists())
            target = install(skills, config, with_hook=True)
            activation = activation_module()
            self.assertTrue(activation.registered(config, target))
            install(skills, config, with_hook=True)
            handlers = [h for g in json.loads((config / "hooks.json").read_text())["hooks"]["SessionStart"] for h in g["hooks"]]
            self.assertEqual(len(handlers), 2)
            activation.atomic_json(config / "agent-dispatcher/state.json",
                                   {**activation.defaults(), "global_enabled": True})
            registered_command = next(h["command"] for h in handlers if h != other)
            result = subprocess.run(registered_command, shell=True, cwd=root, capture_output=True,
                                    input=json.dumps({"cwd": str(root), "session_id": "test"}),
                                    text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
            self.assertIn(str(target / "SKILL.md"), output)
            install(skills, config, uninstall=True)
            self.assertFalse(target.exists())
            self.assertEqual((skills / "unrelated/SKILL.md").read_text(), "mine")
            self.assertEqual(json.loads((config / "hooks.json").read_text()), original)

    def test_unowned_and_symlinked_targets_are_never_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / "skills/agent-dispatcher"
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text("mine")
            for remove in (False, True):
                with self.assertRaises(ValueError):
                    install(target.parent, root / "config", uninstall=remove)
            self.assertEqual((target / "SKILL.md").read_text(), "mine")
            shutil.rmtree(target)
            target.symlink_to(root / "absent")
            with self.assertRaises(ValueError):
                install(target.parent, root / "config", uninstall=True)
            self.assertTrue(target.is_symlink())

    def test_hook_failure_rolls_back_existing_installation(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp).resolve()
            target = install(root / "skills", root / "config")
            (target / "custom.txt").write_text("preserve after failure")
            activation = activation_module()
            with patch("install_codex.activation_module", return_value=activation), \
                    patch.object(activation, "manage_hook", side_effect=OSError("simulated write failure")):
                with self.assertRaises(OSError):
                    install(root / "skills", root / "config", with_hook=True)
            self.assertEqual((target / "custom.txt").read_text(), "preserve after failure")


if __name__ == "__main__":
    unittest.main(verbosity=2)
