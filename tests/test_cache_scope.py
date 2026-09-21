#!/usr/bin/env python3
"""Offline regressions for task-scoped automatic project-cache writes."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import context
import project_graph
import project_map


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "evals/end_to_end/fixtures"
MAP = ".agent-dispatcher/project-map.json"
GRAPH = ".agent-dispatcher/project-graph.json"
TASK = "Inspect validate_token and its callers, dependencies, and tests."


class CacheScopeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        self.write("core.py", "def validate_token():\n    return True\n")
        self.write("api.py", "from core import validate_token\ndef login():\n    return validate_token()\n")
        self.write("test_api.py", "from api import login\ndef test_login():\n    assert login()\n")
        self.write("Makefile", "test:\n\tpython3 -B -m unittest\n")

    def write(self, relative, text):
        target = self.project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target

    def tree(self):
        """Record names, file bytes and mtimes; exclude Git's own bookkeeping."""
        return {path.relative_to(self.project).as_posix():
                ("directory",) if path.is_dir() else ("file", path.read_bytes(), path.stat().st_mtime_ns)
                for path in self.project.rglob("*")
                if ".git" not in path.relative_to(self.project).parts}

    def snapshot(self):
        helper = project_map._context()
        return project_map._scan(self.project, helper, helper._scrubber(ROOT))

    def select(self, task=TASK, **kwargs):
        return context.select_context(self.project, task, pack=ROOT, **kwargs)

    def deferred(self, result, target, reason):
        maintenance = result["maintenance"]
        self.assertTrue(maintenance["requested"])
        self.assertEqual(maintenance["action"], "deferred")
        self.assertFalse(maintenance["persisted"])
        self.assertEqual(maintenance["write_scope"],
                         {"allowed": False, "reason": reason, "target": target})

    def assert_packet_deferred(self, packet, reason):
        self.deferred(packet["project_map"], MAP, reason)
        self.deferred(packet["project_graph"], GRAPH, reason)
        self.assertTrue(packet["read_only"])
        if "project_read_only" in packet:
            self.assertTrue(packet["project_read_only"])
        self.assertTrue(packet["project_map"]["entries"])
        self.assertTrue(packet["project_graph"]["nodes"])

    def fixture_cases(self):
        manifest = json.loads((FIXTURES / "manifest.json").read_text())
        return [case for case in manifest["fixtures"]
                if case["id"] in {"stale_project_map", "architecture_evidence"}]

    def test_actual_eval_prompts_preserve_existing_cache_and_entire_tree(self):
        for fixture in self.fixture_cases():
            with self.subTest(fixture=fixture["id"]):
                shutil.copytree(FIXTURES / fixture["source_dir"], self.project, dirs_exist_ok=True)
                # Derive a valid owned cache, then make its evidence stale.
                self.select(map_maintain=True)
                (self.project / GRAPH).unlink()
                self.write("core.py", "def validate_token():\n    return False\n")
                before = self.tree()
                packet = self.select(fixture["prompt"], map_maintain=True, compact=True,
                                     packet_tokens=10000, auto_exclude=False)
                self.assert_packet_deferred(packet, "task_scope_restricted")
                self.assertEqual(self.tree(), before)
                self.assertFalse((self.project / GRAPH).exists())

    def test_actual_eval_prompts_do_not_create_cache_directory(self):
        for fixture in self.fixture_cases():
            with self.subTest(fixture=fixture["id"]):
                shutil.copytree(FIXTURES / fixture["source_dir"], self.project, dirs_exist_ok=True)
                shutil.rmtree(self.project / ".agent-dispatcher", ignore_errors=True)
                before = self.tree()
                packet = self.select(fixture["prompt"], map_maintain=True, auto_exclude=False)
                self.assert_packet_deferred(packet, "task_scope_restricted")
                self.assertEqual(self.tree(), before)
                self.assertFalse((self.project / ".agent-dispatcher").exists())

    def test_restricted_edit_and_read_only_phrases_defer_automatic_writes(self):
        restrictions = (
            "Modify only core.py; inspect validate_token.",
            "Inspect validate_token and preserve every other file.",
            "Inspect validate_token. Do not edit files.",
            "Read-only inspection of validate_token and its callers.",
            "Inspect validate_token; leave all other files unchanged.",
            "Inspect validate_token without modifying files.",
            "Inspect validate_token. Preserve everything else.",
            "Inspect validate_token. Leave everything else alone.",
            "Inspect validate_token. Preserve .agent-dispatcher/project-map.json.",
            "Inspect validate_token. No files should be changed.",
            "Inspect validate_token. Avoid editing files.",
            "Inspect validate_token. Only README.md may be modified.",
            "Inspect validate_token. Change no files except README.md.",
            "Inspect validate_token. All files except README.md are off limits.",
        )
        for task in restrictions:
            with self.subTest(task=task):
                before = self.tree()
                packet = self.select(task, map_maintain=True, auto_exclude=False)
                self.assert_packet_deferred(packet, "task_scope_restricted")
                self.assertEqual(self.tree(), before)

    def test_ordinary_task_still_builds_then_reuses_and_refreshes_both_caches(self):
        built = self.select(map_maintain=True)
        for key, target in (("project_map", MAP), ("project_graph", GRAPH)):
            maintenance = built[key]["maintenance"]
            self.assertEqual(maintenance["action"], "built")
            self.assertTrue(maintenance["persisted"])
            self.assertEqual(maintenance["write_scope"],
                             {"allowed": True, "reason": "automatic_maintenance", "target": target})
        before = self.tree()
        unchanged = self.select(map_maintain=True)
        self.assertEqual(self.tree(), before)
        for key in ("project_map", "project_graph"):
            self.assertEqual(unchanged[key]["maintenance"]["action"], "unchanged")
            self.assertFalse(unchanged[key]["maintenance"]["persisted"])
        self.write("core.py", "def validate_token():\n    return False\ndef expire_token():\n    return None\n")
        refreshed = self.select(map_maintain=True)
        for key in ("project_map", "project_graph"):
            self.assertEqual(refreshed[key]["maintenance"]["action"], "refreshed")
            self.assertTrue(refreshed[key]["maintenance"]["persisted"])

    def test_preview_takes_precedence_over_maintenance_without_losing_evidence(self):
        before = self.tree()
        packet = self.select(map_preview=True, map_maintain=True)
        self.assert_packet_deferred(packet, "read_only_preview")
        self.assertEqual(self.tree(), before)
        self.assertFalse((self.project / ".agent-dispatcher").exists())

    def test_preview_preserves_stale_existing_cache_bytes_and_mtime(self):
        self.select(map_maintain=True)
        self.write("core.py", "def validate_token():\n    return False\n")
        before = self.tree()
        packet = self.select(map_preview=True, map_maintain=True)
        self.assert_packet_deferred(packet, "read_only_preview")
        self.assertEqual(self.tree(), before)

    def test_exact_writable_file_allows_only_that_cache(self):
        packet = self.select(map_maintain=True, writable_paths=[MAP])
        self.assertTrue((self.project / MAP).is_file())
        self.assertFalse((self.project / GRAPH).exists())
        self.assertEqual(packet["project_map"]["maintenance"]["write_scope"],
                         {"allowed": True, "reason": "explicit_writable_paths", "target": MAP})
        self.deferred(packet["project_graph"], GRAPH, "outside_writable_paths")

    def test_writable_subtree_allows_both_owned_caches(self):
        packet = self.select(map_maintain=True, writable_paths=[".agent-dispatcher/"])
        for key, target in (("project_map", MAP), ("project_graph", GRAPH)):
            self.assertTrue((self.project / target).is_file())
            self.assertTrue(packet[key]["maintenance"]["persisted"])
            self.assertEqual(packet[key]["maintenance"]["write_scope"]["reason"], "explicit_writable_paths")

    def test_writable_boundaries_and_empty_allowlist_never_grant_prefix_matches(self):
        for allowed in ([], ["docs/"], [".agent-dispatcher"], [".agent-dispatcher-other/"],
                        [".agent-dispatcher/project-map"], [MAP + ".backup"], [MAP + "/"]):
            with self.subTest(allowed=allowed):
                before = self.tree()
                packet = self.select(map_maintain=True, writable_paths=allowed)
                self.assert_packet_deferred(packet, "outside_writable_paths")
                self.assertEqual(self.tree(), before)

    def test_explicit_writable_cache_does_not_override_task_preservation(self):
        before = self.tree()
        packet = self.select("Inspect validate_token; preserve every other file.",
                             map_maintain=True, writable_paths=[".agent-dispatcher/"])
        self.assert_packet_deferred(packet, "task_scope_restricted")
        self.assertEqual(self.tree(), before)

    def test_invalid_writable_paths_fail_before_creating_cache(self):
        invalid = ("core.py", [""], ["."], ["../outside"], ["core/../other"],
                   [str(self.root / "outside")], ["core\nprivate"], [None])
        for allowed in invalid:
            with self.subTest(allowed=repr(allowed)):
                before = self.tree()
                with self.assertRaises(context.ContextError):
                    self.select(map_maintain=True, writable_paths=allowed)
                self.assertEqual(self.tree(), before)

    def test_direct_map_helpers_honor_task_scope(self):
        task = "Inspect validate_token. Modify only docs/PROJECT_MAP.json."
        before = self.tree()
        maintained = project_map.maintain_map(self.project, pack=ROOT, task=task)
        self.deferred(maintained, MAP, "task_scope_restricted")
        self.assertTrue(maintained["entries"])
        selected = project_map.context_entries(self.project, task, pack=ROOT, maintain=True)
        self.deferred(selected, MAP, "task_scope_restricted")
        self.assertTrue(selected["entries"])
        self.assertEqual(self.tree(), before)

    def test_direct_graph_helper_honors_task_scope(self):
        before = self.tree()
        graph = project_graph.query_graph(self.project, "Inspect validate_token. Do not edit files.",
                                          pack=ROOT, snapshot=self.snapshot(), maintain=True)
        self.deferred(graph, GRAPH, "task_scope_restricted")
        self.assertTrue(graph["nodes"])
        self.assertEqual(self.tree(), before)

    def test_direct_helpers_honor_preview_over_maintenance(self):
        before = self.tree()
        maintained = project_map.maintain_map(self.project, pack=ROOT, task=TASK, preview=True)
        self.deferred(maintained, MAP, "read_only_preview")
        selected = project_map.context_entries(self.project, TASK, pack=ROOT, preview=True, maintain=True)
        self.deferred(selected, MAP, "read_only_preview")
        graph = project_graph.query_graph(self.project, TASK, pack=ROOT, snapshot=self.snapshot(),
                                          preview=True, maintain=True)
        self.deferred(graph, GRAPH, "read_only_preview")
        self.assertEqual(self.tree(), before)

    def test_direct_helpers_cannot_weaken_denied_snapshot_scope(self):
        snapshot = self.snapshot()
        snapshot["cache_write_scope"] = {
            target: {"allowed": False, "reason": "task_scope_restricted", "target": target}
            for target in (MAP, GRAPH)}
        before = self.tree()
        maintained = project_map.maintain_map(self.project, pack=ROOT, snapshot=snapshot,
                                               task=TASK, writable_paths=[".agent-dispatcher/"])
        self.deferred(maintained, MAP, "task_scope_restricted")
        selected = project_map.context_entries(self.project, TASK, pack=ROOT, snapshot=snapshot,
                                               maintain=True, writable_paths=[".agent-dispatcher/"])
        self.deferred(selected, MAP, "task_scope_restricted")
        graph = project_graph.query_graph(self.project, TASK, pack=ROOT, snapshot=snapshot,
                                          maintain=True, writable_paths=[".agent-dispatcher/"])
        self.deferred(graph, GRAPH, "task_scope_restricted")
        self.assertEqual(self.tree(), before)

    def test_malformed_or_missing_snapshot_decisions_fail_closed(self):
        for inherited in ({}, "not-a-scope", {MAP: {"allowed": True, "target": GRAPH}},
                          {MAP: {"allowed": "yes", "target": MAP}}):
            with self.subTest(inherited=inherited):
                snapshot = self.snapshot()
                snapshot["cache_write_scope"] = inherited
                before = self.tree()
                maintained = project_map.maintain_map(self.project, pack=ROOT, snapshot=snapshot, task=TASK)
                self.deferred(maintained, MAP, "invalid_snapshot_scope")
                graph = project_graph.query_graph(self.project, TASK, pack=ROOT, snapshot=snapshot, maintain=True)
                self.deferred(graph, GRAPH, "invalid_snapshot_scope")
                self.assertEqual(self.tree(), before)

    def test_permissive_snapshot_cannot_override_current_task_restriction(self):
        snapshot = self.snapshot()
        snapshot["cache_write_scope"] = {
            target: {"allowed": True, "reason": "automatic_maintenance", "target": target}
            for target in (MAP, GRAPH)}
        before = self.tree()
        task = "Inspect validate_token. Do not edit files."
        maintained = project_map.maintain_map(self.project, pack=ROOT, snapshot=snapshot, task=task)
        self.deferred(maintained, MAP, "task_scope_restricted")
        graph = project_graph.query_graph(self.project, task, pack=ROOT, snapshot=snapshot, maintain=True)
        self.deferred(graph, GRAPH, "task_scope_restricted")
        self.assertEqual(self.tree(), before)

    def test_direct_helpers_honor_empty_writable_allowlist(self):
        before = self.tree()
        maintained = project_map.maintain_map(self.project, pack=ROOT, task=TASK, writable_paths=[])
        self.deferred(maintained, MAP, "outside_writable_paths")
        selected = project_map.context_entries(self.project, TASK, pack=ROOT, maintain=True, writable_paths=[])
        self.deferred(selected, MAP, "outside_writable_paths")
        graph = project_graph.query_graph(self.project, TASK, pack=ROOT, snapshot=self.snapshot(),
                                          maintain=True, writable_paths=[])
        self.deferred(graph, GRAPH, "outside_writable_paths")
        self.assertEqual(self.tree(), before)

    def test_budgeted_packet_preserves_cache_write_decisions(self):
        before = self.tree()
        packet = self.select("Inspect validate_token. Do not edit files.", role="reviewer",
                             compact=True, packet_tokens=4000, map_maintain=True)
        self.assert_packet_deferred(packet, "task_scope_restricted")
        self.assertLessEqual(len(json.dumps(packet, ensure_ascii=False, separators=(",", ":"))), 16000)
        self.assertEqual(self.tree(), before)

    def cli(self, task=TASK, *extra):
        return subprocess.run([sys.executable, "-B", str(ROOT / "context.py"), "--project", str(self.project),
                               "--pack", str(ROOT), "--task-file", "-", "--map-maintain", "--json", *extra],
                              input=task, capture_output=True, text=True, cwd=self.root)

    def test_cli_no_auto_exclude_cannot_bypass_preservation_scope(self):
        before = self.tree()
        child = self.cli("Inspect validate_token; preserve every other file.", "--no-auto-exclude")
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assert_packet_deferred(json.loads(child.stdout), "task_scope_restricted")
        self.assertEqual(self.tree(), before)

    def test_cli_preview_precedence_is_read_only(self):
        before = self.tree()
        child = self.cli(TASK, "--map-preview")
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assert_packet_deferred(json.loads(child.stdout), "read_only_preview")
        self.assertEqual(self.tree(), before)

    def test_cli_repeated_writable_paths_are_enforced_per_cache(self):
        child = self.cli(TASK, "--writable-path", "docs/report.json", "--writable-path", MAP)
        self.assertEqual(child.returncode, 0, child.stderr)
        packet = json.loads(child.stdout)
        self.assertTrue(packet["project_map"]["maintenance"]["persisted"])
        self.deferred(packet["project_graph"], GRAPH, "outside_writable_paths")
        self.assertFalse((self.project / GRAPH).exists())


if __name__ == "__main__":
    unittest.main()
