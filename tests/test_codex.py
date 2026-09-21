#!/usr/bin/env python3
"""Offline integration tests for the self-contained Codex package and native activation."""
import contextlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import build
from preferences import get_preferences
from build_codex import adapt, export_package
from install_codex import activation_module, install
from install_claude import stage_pack

ROOT = Path(__file__).resolve().parents[1]


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

    def resource_reports(self, helper, pack, roles, cwd=None):
        code = """import importlib.util, json, sys
spec = importlib.util.spec_from_file_location('dispatcher_resources', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(json.dumps([module.resolve_resources(sys.argv[2], role) for role in json.loads(sys.argv[3])]))
"""
        result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(helper),
                                 str(pack), json.dumps(roles)], cwd=cwd or self.root,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_resource_manifests_and_resolution_are_exact_read_only_and_cwd_independent(self):
        manual = self.root / "manual-resource-pack"
        stage_pack(ROOT, manual)
        cwd = self.root / "untrusted-resource-cwd"
        cwd.mkdir()
        (cwd / "resources.py").write_text("raise AssertionError('project code must not be imported')\n")
        layouts = (("source", ROOT, ROOT / "catalog", ROOT / "resources.py"),
                   ("claude_manual", manual, manual / "catalog", manual / "resources.py"),
                   ("codex", self.pack, self.pack / "scripts/runtime/catalog", self.pack / "scripts/resources.py"))

        def snapshot(path):
            paths = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()]
            return {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}

        watched = (cwd, manual, self.pack, ROOT / "catalog", ROOT / "skills", ROOT / "resources.py")
        before = [snapshot(path) for path in watched]
        source_helper = (ROOT / "resources.py").read_bytes()
        self.assertEqual(source_helper, (ROOT / "skills/agent-dispatcher/resources.py").read_bytes())
        for layout, pack, catalog, helper in layouts:
            with self.subTest(layout=layout):
                self.assertEqual(helper.read_bytes(), source_helper)
                manifest = json.loads((catalog / "resource-paths.json").read_text())
                roles = {r["id"]: (f"skills/agent-dispatcher/roles/{r['id']}.md" if layout == "source"
                                   else f"roles/{r['id']}.md" if layout == "claude_manual"
                                   else f"references/roles/{r['id']}.md") for r in self.data["roles"]}
                guides = {s["id"]: (s["path"] if layout == "source"
                                    else s["path"].replace("skills/", "lib/", 1) if layout == "claude_manual"
                                    else "references/" + s["path"].replace("/SKILL.md", "/GUIDE.md"))
                          for s in self.data["skills"]}
                self.assertEqual(manifest, {"schema_version": 1, "layout": layout,
                                            "roles": roles, "guides": guides})
                for relative in [*roles.values(), *guides.values()]:
                    self.assertFalse(PurePosixPath(relative).is_absolute())
                    self.assertNotIn("..", PurePosixPath(relative).parts)
                    self.assertTrue((pack / relative).resolve().is_relative_to(pack.resolve()))
                    self.assertTrue((pack / relative).is_file(), relative)
                for skill in self.data["skills"]:
                    self.assertEqual((pack / guides[skill["id"]]).read_bytes(),
                                     (ROOT / skill["path"]).read_bytes())
                for role in self.data["roles"]:
                    source = (ROOT / "skills/agent-dispatcher/roles" / (role["id"] + ".md")).read_text()
                    self.assertEqual((pack / roles[role["id"]]).read_text(),
                                     adapt(source) if layout == "codex" else source)
                requested = [r[key] for r in self.data["roles"] for key in ("id", "slug")]
                reports = self.resource_reports(helper, pack, requested, cwd=cwd)
                for index, role in enumerate(self.data["roles"]):
                    report, alias = reports[index * 2:index * 2 + 2]
                    self.assertEqual(report, alias, role["id"])
                    self.assertEqual(report["diagnostics"], [])
                    self.assertEqual(report["role"], {"id": role["id"], "path": str(pack / roles[role["id"]])})
                    expected_ids = set(role["verification"])
                    for tier in ("core", "preferred", "optional"):
                        expected_ids.update(role["skills"][tier])
                    for ids in role["skills"]["conditional"].values():
                        expected_ids.update(ids)
                    self.assertEqual({g["id"] for g in report["guides"]}, expected_ids)
                    self.assertEqual(report["conditions"], {
                        key: self.data["signals"][key]["summary"] for key in role["skills"]["conditional"]})
                    for guide in report["guides"]:
                        ident = guide["id"]
                        expected_tiers = [tier for tier in ("core", "preferred", "optional")
                                          if ident in role["skills"][tier]]
                        if ident in role["verification"]:
                            expected_tiers.append("verification")
                        self.assertEqual(guide["tiers"], expected_tiers)
                        self.assertEqual(set(guide["conditions"]), {
                            key for key, ids in role["skills"]["conditional"].items() if ident in ids})
                        self.assertEqual(guide["path"], str(pack / guides[ident]) if ident in guides else None)
                        self.assertEqual(guide["status"], "bundled" if ident in guides else "external_availability_unknown")
                unselected, unknown = self.resource_reports(helper, pack, [None, "no-such-role"], cwd=cwd)
                self.assertIsNone(unselected["role"])
                self.assertEqual(unselected["guides"], [])
                self.assertIsNone(unknown["role"])
                self.assertEqual(unknown["guides"], [])
                self.assertTrue(unknown["diagnostics"])
        self.assertEqual(before, [snapshot(path) for path in watched])

    def test_full_context_workflows_reduce_recorded_bytes_by_at_least_35_percent(self):
        baseline = json.loads((ROOT / "evals/context/workflow-baseline.json").read_text())
        self.assertEqual(baseline["schema_version"], 1)
        # Normal work consumes the helper result directly; CONTEXT.md is for
        # limits/inspection, not a required startup read. Count the newly required
        # verification reference and candidate metadata, including their overhead.
        workflows = {
            "authentication": ("implementer", ("regression-testing", "authentication")),
            "map_refresh": ("documentation-writer", ("documentation-verification",)),
            "architecture_report": ("documentation-writer", ("technical-writing", "documentation-verification")),
        }
        # Saved display/effort requests are instruction-bearing helper metadata too.
        # Isolate defaults from the developer's real saved preferences and normalize
        # the state location just as package locations are normalized to PACK below.
        preference_state = self.root / "workflow-default-preferences"
        preferences = get_preferences(project=ROOT, state_dir=preference_state)
        self.assertFalse(preference_state.exists())
        preferences["storage_path"] = "STATE/preferences.json"
        preference_bytes = len(json.dumps(preferences, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        manual = self.root / "manual-budget-pack"
        stage_pack(ROOT, manual)
        layouts = (("claude", ROOT, ROOT / "skills/agent-dispatcher", ROOT / "catalog", ROOT / "resources.py"),
                   ("claude", manual, manual, manual / "catalog", manual / "resources.py"),
                   ("codex", self.pack, self.pack / "references", self.pack / "scripts/runtime/catalog",
                    self.pack / "scripts/resources.py"))
        for host, pack, refs, catalog, helper in layouts:
            manifest = json.loads((catalog / "resource-paths.json").read_text())
            entry = (ROOT / "skills/agent-dispatcher/SKILL.md" if pack == ROOT else pack / "SKILL.md")
            for name, (role, loaded_guides) in workflows.items():
                with self.subTest(host=host, layout=manifest["layout"], workflow=name):
                    previous = baseline["hosts"][host][name]
                    self.assertEqual(previous["total_bytes"], sum(c["bytes"] for c in previous["components"]))
                    self.assertTrue(set(loaded_guides) <= set(previous["guides"]))
                    resources = self.resource_reports(helper, pack, [role])[0]
                    self.assertEqual(resources["diagnostics"], [])
                    self.assertEqual(resources["role"]["id"], role)
                    self.assertTrue(set(loaded_guides) <= {g["id"] for g in resources["guides"]})
                    normalized = json.dumps(resources, ensure_ascii=False, separators=(",", ":")).replace(str(pack), "PACK")
                    files = [entry, refs / "VERIFICATION.md", Path(resources["role"]["path"]),
                             *(pack / manifest["guides"][ident] for ident in loaded_guides)]
                    measured = (sum(len(path.read_bytes()) for path in files)
                                + len(normalized.encode("utf-8")) + preference_bytes)
                    self.assertLessEqual(measured * 100, previous["total_bytes"] * 65,
                                         {"bytes": measured, "baseline": previous["total_bytes"],
                                          "loaded_guides": loaded_guides})

    def test_selected_role_methods_omit_shared_modes_and_preserve_boundaries(self):
        for role in self.data["roles"]:
            boundary = role["body"].split("ROLE BOUNDARIES\n", 1)[1].split("\n---", 1)[0].strip()
            self.assertTrue(boundary, role["id"])
            for host, path in (("claude", ROOT / "skills/agent-dispatcher/roles" / (role["id"] + ".md")),
                               ("codex", self.pack / "references/roles" / (role["id"] + ".md"))):
                text = path.read_text()
                with self.subTest(host=host, role=role["id"]):
                    self.assertNotIn("## Mode", text)
                    self.assertNotIn("## Response style", text)
                    self.assertIn("WORKING METHOD", text)
                    self.assertIn("DEFINITION OF DONE", text)
                    self.assertIn("ROLE BOUNDARIES", text)
                    self.assertIn(adapt(boundary) if host == "codex" else boundary, text)

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
        for script, pack in zip(scripts, (ROOT, manual, self.pack, ROOT)):
            env = dict(os.environ, AGENT_DISPATCHER_DECISION_MODE="required", PYTHONDONTWRITEBYTECODE="1")
            result = subprocess.run([sys.executable, "-B", str(script), "--project", str(project),
                                     "--task-file", "-", "--role", "debugger", "--size", "small", "--json"],
                                    input="Fix validate_login in auth.py and check related login tests", text=True,
                                    capture_output=True, cwd=self.root, env=env, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(any(row["path"] == "auth.py" for row in report["context"]))
            self.assertTrue(report["excerpts"])
            self.assertEqual(report["resources"], self.resource_reports(
                script.with_name("resources.py"), pack, ["debugger"])[0])
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

    def test_project_map_parity_freshness_and_read_only_context_across_hosts(self):
        project = self.root / "map-project"
        project.mkdir()
        subprocess.run(["git", "init", "-q", str(project)], check=True)
        source = project / "auth.py"
        source.write_text("def validate_login(name):\n    return bool(name)\n")
        (project / "package.json").write_text(json.dumps({"scripts": {"test": "python3 -m unittest"},
                                                       "dependencies": {"example-auth": "1.0.0"}}))
        manual = self.root / "manual-map-pack"
        stage_pack(ROOT, manual)
        folders = [ROOT, manual, ROOT / "skills/agent-dispatcher", self.pack / "scripts"]
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", AGENT_DISPATCHER_DECISION_MODE="required")

        def invoke(folder, helper, args):
            result = subprocess.run([sys.executable, "-B", str(folder / helper), *args,
                                     "--project", str(project), "--json"],
                                    cwd=self.root, env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)

        def snapshot(folder):
            return {str(p.relative_to(folder)): (p.read_bytes(), p.stat().st_mtime_ns)
                    for p in folder.rglob("*") if p.is_file()}

        for folder in folders:
            self.assertEqual((folder / "project_map.py").read_bytes(), (ROOT / "project_map.py").read_bytes())
        invoke(ROOT, "project_map.py", ["build"])
        before = [snapshot(folder) for folder in (project, manual, self.pack)]
        reports = [invoke(folder, "project_map.py", ["show", "--task", "validate_login"]) for folder in folders]
        self.assertTrue(reports[0]["entries"])
        for report in reports[1:]:
            self.assertEqual(reports[0], report)
        contexts = [invoke(folder, "context.py", ["--task", "validate_login", "--size", "small"]) for folder in folders]
        self.assertTrue(contexts[0]["project_map"]["entries"])
        for result in contexts[1:]:
            self.assertEqual(contexts[0]["project_map"], result["project_map"])
        self.assertEqual(before, [snapshot(folder) for folder in (project, manual, self.pack)])
        source.write_text("def validate_login(name):\n    return bool(name.strip())\n")
        for folder in folders:
            stale = invoke(folder, "project_map.py", ["show"])
            self.assertFalse(any(e["source"]["path"] == "auth.py" for e in stale["entries"]))
        invoke(self.pack / "scripts", "project_map.py", ["refresh"])
        refreshed = invoke(manual, "project_map.py", ["show"])
        self.assertTrue(any(e["source"]["path"] == "auth.py" for e in refreshed["entries"]))

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
