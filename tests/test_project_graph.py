#!/usr/bin/env python3
"""Offline contracts for bounded, source-backed structural graph queries."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
import warnings

import project_graph
import project_map

ROOT = Path(__file__).resolve().parents[1]


class ProjectGraphTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        self.state = project_map.state_path(self.project, project_graph.STATE_FILE)  # private, outside the project

    def write(self, path, text):
        target = self.project / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        return target

    def snapshot(self):
        helper = project_map._context()
        return project_map._scan(self.project, helper, helper._scrubber(ROOT))

    def query(self, task="validate_token", role=None, maintain=False, snapshot=None):
        return project_graph.query_graph(self.project, task, role, pack=ROOT,
                                         snapshot=self.snapshot() if snapshot is None else snapshot, maintain=maintain)

    def basic(self):
        self.write("core.py", "def validate_token():\n    return fetch_user()\n\ndef fetch_user():\n    return 1\n")
        self.write("main.py", "from core import validate_token\n\ndef login():\n    return validate_token()\n")
        self.write("test_main.py", "from main import login\n\ndef test_login():\n    assert login()\n")

    def test_python_ast_records_definitions_imports_and_supported_calls_with_provenance(self):
        self.basic()
        result = self.query(maintain=True)
        self.assertEqual(result["maintenance"]["action"], "built")
        stored = json.loads(self.state.read_text())
        labels = {n["id"]: n["label"] for n in stored["nodes"]}
        calls = {(labels[e["from"]], labels[e["to"]]) for e in stored["edges"] if e["kind"] == "calls"}
        self.assertEqual(calls, {("login", "validate_token"), ("validate_token", "fetch_user"), ("test_login", "login")})
        hashes = {s["path"]: s["sha256"] for s in stored["sources"]}
        for edge in stored["edges"]:
            path = edge["evidence"]["path"]
            raw = (self.project / path).read_bytes()
            self.assertEqual(hashes[path], hashlib.sha256(raw).hexdigest())
            self.assertGreaterEqual(edge["evidence"]["line"], 1)
            self.assertIn(edge["confidence"], {"resolved", "inferred"})
            self.assertTrue(edge["method"])
        self.assertTrue(any(e["kind"] == "test_candidate" and e["confidence"] == "inferred" for e in stored["edges"]))
        self.assertIn("not runtime execution or test coverage", " ".join(result["limits"]))

    def test_task_view_prioritizes_callers_and_callees_without_lexical_matches(self):
        self.basic()
        result = self.query()
        priorities = result["source_priorities"]
        self.assertIn("main.py", priorities)
        self.assertTrue(all(0 < p["score"] <= 4 and p["lines"] for p in priorities.values()))
        labels = {n["id"]: n["label"] for n in result["nodes"]}
        self.assertIn("login", [labels[i] for i in result["upstream"]])
        self.assertIn("fetch_user", [labels[i] for i in result["downstream"]])
        self.assertIn(["validate_token", "fetch_user"], [[labels[i] for i in path] for path in result["possible_paths"]])
        self.assertFalse(self.state.parent.exists())

    def test_shadowed_wildcard_nested_and_dynamic_calls_stay_unresolved(self):
        self.write("core.py", "def target(): pass\n\ndef caller():\n    target()\n\ndef shadow(target):\n    target()\n\ndef dynamic(obj):\n    obj.target()\n\ndef outer():\n    target = lambda: None\n    def inner():\n        target()\n    inner()\n")
        self.write("wildcard.py", "from core import *\ndef caller():\n    target()\n")
        self.query("target", maintain=True)
        data = json.loads(self.state.read_text())
        labels = {n["id"]: (n["source"]["path"], n["label"]) for n in data["nodes"]}
        calls = [(labels[e["from"]], labels[e["to"]]) for e in data["edges"] if e["kind"] == "calls"]
        self.assertEqual(calls, [(("core.py", "caller"), ("core.py", "target"))])
        self.assertGreater(data["omitted"]["unresolved_calls"], 0)

    def test_testing_role_favors_related_test_candidates_within_same_limits(self):
        self.basic()
        ordinary = self.query()
        testing = self.query(role="tester")
        self.assertIn("test_main.py", testing["source_priorities"])
        self.assertGreater(testing["source_priorities"]["test_main.py"]["score"],
                           ordinary["source_priorities"]["test_main.py"]["score"])
        self.assertLessEqual(len(testing["nodes"]), 12)
        self.assertLessEqual(len(json.dumps(testing, ensure_ascii=False)), 6000)

    def test_rebound_target_does_not_produce_a_resolved_call(self):
        self.write("core.py", "def target(): pass\ntarget = lambda: None\ndef caller():\n    target()\n")
        self.query("target", maintain=True)
        data = json.loads(self.state.read_text())
        self.assertFalse(any(e["kind"] == "calls" for e in data["edges"]))

    def test_relative_python_imports_resolve_without_importing_modules(self):
        self.write("pkg/__init__.py", "")
        self.write("pkg/core.py", "raise RuntimeError('must never execute')\ndef validate_token(): pass\n")
        self.write("pkg/main.py", "from .core import validate_token as check\ndef login():\n    check()\n")
        result = self.query(maintain=True)
        data = json.loads(self.state.read_text())
        self.assertTrue(any(e["kind"] == "calls" for e in data["edges"]))
        self.assertEqual(result["cache_status"], "fresh")

    def test_imported_attribute_writes_suppress_resolved_calls_even_inside_other_functions(self):
        self.write("a.py", "def target(): pass\n")
        for mutation in ("a.target = replacement\n", "def mutate():\n    a.target = replacement\n",
                         "def mutate():\n    global a\n    a = replacement\n"):
            with self.subTest(mutation=mutation):
                self.write("b.py", "import a\ndef replacement(): pass\n" + mutation +
                           "def run():\n    return a.target()\n")
                self.query("target", maintain=True)
                data = json.loads(self.state.read_text())
                self.assertFalse(any(edge["kind"] == "calls" for edge in data["edges"]))
                self.assertGreater(data["omitted"]["unresolved_calls"], 0)

    def test_package_submodule_import_resolves_only_without_a_competing_package_binding(self):
        self.write("pkg/__init__.py", "")
        self.write("pkg/util.py", "def helper(): pass\n")
        self.write("main.py", "from pkg import util\ndef run():\n    return util.helper()\n")
        self.query("helper", maintain=True)
        data = json.loads(self.state.read_text())
        nodes = {node["id"]: node for node in data["nodes"]}
        imports = [nodes[edge["to"]]["source"]["path"] for edge in data["edges"] if edge["kind"] == "imports"]
        self.assertIn("pkg/util.py", imports)
        calls = [(nodes[edge["from"]]["label"], nodes[edge["to"]]["label"])
                 for edge in data["edges"] if edge["kind"] == "calls"]
        self.assertEqual(calls, [("run", "helper")])
        self.write("pkg/__init__.py", "util = object()\n")
        self.query("helper", maintain=True)
        data = json.loads(self.state.read_text())
        self.assertFalse(any(edge["kind"] == "calls" for edge in data["edges"]))

    def test_nonpython_relative_imports_are_candidates_never_execution_paths(self):
        self.write("ui/auth.ts", "export function validateToken() { return true; }\n")
        self.write("ui/login.ts", "import {validateToken} from './auth';\nvalidateToken();\n")
        result = self.query("auth", maintain=True)
        data = json.loads(self.state.read_text())
        imports = [e for e in data["edges"] if e["kind"] == "imports"]
        self.assertEqual(len(imports), 1)
        self.assertEqual(imports[0]["confidence"], "inferred")
        self.assertEqual(imports[0]["method"], "relative-import-regex")
        self.assertFalse(result["possible_paths"])
        self.assertFalse(result["upstream"])

    def test_shared_snapshot_never_triggers_a_second_scan_or_source_read(self):
        self.basic()
        snapshot = self.snapshot()
        with mock.patch.object(project_graph, "_map_helper", return_value=project_map), \
                mock.patch.object(project_map, "_scan", side_effect=AssertionError("second source scan")):
            result = self.query(snapshot=snapshot)
        self.assertTrue(result["nodes"])

    def test_excluded_and_partial_scans_never_persist_task_scope(self):
        self.basic()
        self.query(maintain=True)
        before = self.state.read_bytes()
        snapshot = self.snapshot()
        # Defense in depth: even a supplied text entry cannot override exclusion.
        snapshot.update(exclude_paths=("main.py", "test_main.py"), task_excluded_paths=["main.py", "test_main.py"])
        result = self.query(snapshot=snapshot, maintain=True)
        self.assertEqual(result["maintenance"]["action"], "deferred")
        self.assertEqual({s["path"] for s in result["sources"]}, {"core.py"})
        self.assertEqual(self.state.read_bytes(), before)
        snapshot = self.snapshot()
        snapshot["complete"] = False
        result = self.query(snapshot=snapshot, maintain=True)
        self.assertEqual(result["maintenance"]["action"], "deferred")
        self.assertEqual(result["cache_status"], "partial")
        self.assertEqual(self.state.read_bytes(), before)

    def test_unchanged_cache_is_not_written_and_new_changed_deleted_sources_refresh(self):
        self.basic()
        self.query(maintain=True)
        before = self.state.stat().st_mtime_ns
        with mock.patch.object(project_graph, "_map_helper", return_value=project_map), \
                mock.patch.object(project_map, "_write", side_effect=AssertionError("same graph rewritten")):
            result = self.query(maintain=True)
        self.assertEqual(result["maintenance"]["action"], "unchanged")
        self.assertEqual(self.state.stat().st_mtime_ns, before)
        self.write("core.py", "def validate_new(): pass\n")
        (self.project / "main.py").unlink()
        self.write("new.py", "from core import validate_new\ndef caller():\n    validate_new()\n")
        result = self.query("validate_new", maintain=True)
        self.assertEqual(result["maintenance"]["action"], "refreshed")
        self.assertNotIn("validate_token", self.state.read_text())
        self.assertNotIn('"path": "main.py"', self.state.read_text())

    def test_forged_graph_claim_with_matching_source_hash_is_not_used(self):
        self.basic()
        self.query(maintain=True)
        stored = json.loads(self.state.read_text())
        stored["nodes"][0]["label"] = "forged_instruction"
        self.state.write_text(json.dumps(stored))
        result = self.query("validate_token")
        self.assertEqual(result["cache_status"], "stale")
        self.assertNotIn("forged_instruction", json.dumps(result))
        self.query(maintain=True)
        self.assertNotIn("forged_instruction", self.state.read_text())

    def test_graph_is_private_and_an_in_project_graph_from_before_the_move_is_only_read(self):
        self.basic()
        self.assertEqual(self.query(maintain=True)["maintenance"]["action"], "built")
        self.assertFalse((self.project / ".agent-dispatcher").exists())
        old = self.project / ".agent-dispatcher/project-graph.json"
        old.parent.mkdir()
        shutil.move(self.state, old)
        original = old.read_bytes()
        self.assertEqual(self.query()["cache_status"], "fresh")  # read through the fallback
        self.write("extra.py", "def added():\n    return 1\n")
        self.assertEqual(self.query()["cache_status"], "stale")
        self.assertEqual(self.query(maintain=True)["maintenance"]["action"], "refreshed")
        self.assertEqual(old.read_bytes(), original)
        self.assertIn("extra.py", self.state.read_text())
        self.assertEqual(self.query()["cache_status"], "fresh")

    def test_malformed_or_symlinked_graph_leaves_legacy_map_and_user_files_untouched(self):
        self.basic()
        project_map.build_map(self.project, pack=ROOT)
        legacy = project_map.state_path(self.project)  # the fact map kept beside the graph
        original = legacy.read_bytes()
        self.state.write_text('{"foreign":true}')
        result = self.query(maintain=True)
        self.assertEqual(result["maintenance"]["action"], "unavailable")
        self.assertTrue(result["nodes"])
        self.assertEqual(self.state.read_text(), '{"foreign":true}')
        self.assertEqual(project_map.inspect_map(self.project, pack=ROOT)["status"], "fresh")
        self.assertEqual(legacy.read_bytes(), original)
        self.state.unlink()
        victim = self.root / "victim.json"
        victim.write_text("keep")
        self.state.symlink_to(victim)
        result = self.query(maintain=True)
        self.assertEqual(result["maintenance"]["action"], "unavailable")
        self.assertTrue(self.state.is_symlink())
        self.assertEqual(victim.read_text(), "keep")

    def test_trimming_removes_impact_and_paths_when_supporting_edges_are_gone(self):
        self.basic()
        result = self.query()
        self.assertTrue(result["upstream"])
        self.assertTrue(result["downstream"])
        result["edges"] = []
        project_graph._prune(result, result["sources"])
        self.assertFalse(result["upstream"])
        self.assertFalse(result["downstream"])
        self.assertFalse(result["possible_paths"])

    def test_unrelated_request_has_no_graph_priority_and_view_stays_bounded(self):
        for index in range(100):
            self.write(f"feature_{index}.py", f"def validate_operation_{index}(): pass\n")
        result = self.query("validate")
        self.assertLessEqual(len(result["nodes"]), 12)
        self.assertLessEqual(len(result["edges"]), 16)
        self.assertLessEqual(len(result["source_priorities"]), 8)
        self.assertLessEqual(result["estimated_tokens"], 1500)
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False)), 6000)
        self.assertFalse(self.query("utterlyunrelated")["source_priorities"])

    def test_missing_snapshot_never_enumerates_sources(self):
        self.basic()
        result = project_graph.query_graph(self.project, "validate_token", pack=ROOT)
        self.assertEqual(result["status"], "unavailable")
        self.assertFalse(result["nodes"])
        self.assertFalse(self.state.parent.exists())

    def test_parser_warnings_do_not_leak_source_snippets(self):
        self.write("core.py", "marker = '\\q'\ndef validate_token(): pass\n")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = self.query()
        self.assertTrue(result["nodes"])
        self.assertEqual(caught, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
