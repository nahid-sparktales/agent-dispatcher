#!/usr/bin/env python3
"""Integration contracts for incremental evidence and fresh relationship resolution."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import context
import parser_cache


ROOT = Path(__file__).resolve().parents[1]


class IncrementalContextTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.project = self.base / "project"
        self.project.mkdir()
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        self.cache = self.base / "private-cache"
        patch = mock.patch.object(context, "_parser_cache", side_effect=lambda project, writable, policy_extra=None:
                                  parser_cache.Cache(project, writable=writable, directory=self.cache,
                                                     policy_extra=policy_extra))
        patch.start()
        self.addCleanup(patch.stop)
        self.write("core.py", "def validate_token():\n    return True\n")
        self.write("api.py", "from core import validate_token\ndef login():\n    return validate_token()\n")
        self.write("test_api.py", "from api import login\ndef test_login():\n    assert login()\n")
        self.write("README.md", "Run tests with `python3 -m unittest`.\n")

    def write(self, name, text):
        target = self.project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        return target

    def select(self, **kwargs):
        return context.select_context(self.project, kwargs.pop("task", "Fix login token validation"),
                                      role="implementer", pack=ROOT, map_maintain=True, **kwargs)

    def state(self, name):
        return json.loads((self.project / ".agent-dispatcher" / name).read_text())

    def calls(self):
        graph = self.state("project-graph.json")
        labels = {node["id"]: node["label"] for node in graph["nodes"]}
        return {(labels[e["from"]], labels[e["to"]]) for e in graph["edges"] if e["kind"] == "calls"}

    def private_files(self):
        return {str(p.relative_to(self.cache)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.cache.rglob("*") if p.is_file()} if self.cache.exists() else {}

    def test_warm_scan_avoids_source_reads_and_parsing_with_identical_indexes(self):
        cold = self.select()
        initial = [self.state(name) for name in ("project-map.json", "project-graph.json")]
        warm = self.select()
        stats = warm["parser_cache"]
        self.assertEqual(stats["source_hits"], 4)
        self.assertEqual(stats["source_bytes_read"], 0)
        self.assertEqual(stats["parsed_files"], 0)
        self.assertEqual(stats["graph_hits"], 1)  # The resolved graph itself is reused.
        self.assertGreater(stats["fact_hits"], 0)
        self.assertEqual(stats["logical_source_bytes"], cold["parser_cache"]["logical_source_bytes"])
        self.assertEqual(initial, [self.state(name) for name in ("project-map.json", "project-graph.json")])
        self.assertEqual(warm["excerpts"], cold["excerpts"])

    def test_one_edit_rereads_one_file_and_relinks_unchanged_importer(self):
        self.select()
        self.assertIn(("login", "validate_token"), self.calls())
        source = self.project / "core.py"
        stamp = source.stat().st_mtime_ns
        # The importer itself stays unchanged. Restoring mtime must not retain
        # the old callee; ctime and the source content invalidate the entry.
        self.write("core.py", "def replaced_token():\n    return True\n")
        os.utime(source, ns=(stamp, stamp))
        changed = self.select()["parser_cache"]
        self.assertEqual(changed["source_misses"], 1)
        self.assertEqual(changed["parsed_files"], 3)  # A graph miss parses every Python file fresh.
        self.assertNotIn(("login", "validate_token"), self.calls())
        expected = [self.state(name) for name in ("project-map.json", "project-graph.json")]
        self.select(parser_cache=False)
        self.assertEqual(expected, [self.state(name) for name in ("project-map.json", "project-graph.json")])

    def test_rename_and_deletion_remove_old_edges_even_when_importer_is_reused(self):
        self.select()
        (self.project / "core.py").rename(self.project / "renamed.py")
        self.select()
        self.assertNotIn(("login", "validate_token"), self.calls())
        (self.project / "renamed.py").unlink()
        self.select()
        graph = self.state("project-graph.json")
        self.assertFalse(any(s["path"] in {"core.py", "renamed.py"} for s in graph["sources"]))

    def test_preview_restricted_and_filtered_tasks_never_write_private_state(self):
        self.select()
        self.write("core.py", "def validate_token():\n    return False\n")
        for options in ({"map_preview": True}, {"writable_paths": [".agent-dispatcher/"]},
                        {"task": "Only edit core.py and keep all other files unchanged"},
                        {"exclude_paths": ["core.py"]}):
            with self.subTest(options=options):
                before = self.private_files()
                result = self.select(**options)
                self.assertFalse(result["parser_cache"]["write_allowed"])
                self.assertEqual(result["parser_cache"]["writes"], 0)
                self.assertEqual(self.private_files(), before)

    def test_excluded_source_is_never_offered_to_cache_or_graph(self):
        self.select()
        seen = []
        original = parser_cache.Cache.read
        def record(instance, path, *args):
            seen.append(path)
            return original(instance, path, *args)
        with mock.patch.object(parser_cache.Cache, "read", record):
            result = self.select(exclude_paths=["core.py"])
        self.assertNotIn("core.py", seen)
        self.assertFalse(any(s["path"] == "core.py" for s in result["project_graph"]["sources"]))
        self.assertFalse(any(e["source"]["path"] == "core.py" for e in result["project_map"]["entries"]))

    def test_warm_source_sizes_still_exhaust_scan_budget(self):
        self.select()
        with mock.patch.object(context, "MAX_SCAN_BYTES", 1):
            result = self.select()
        self.assertFalse(result["project_map"]["coverage"]["scan_complete"])
        self.assertFalse(result["parser_cache"]["write_allowed"])
        self.assertEqual(result["parser_cache"]["writes"], 0)

    def test_forged_project_graph_cannot_become_parser_authority(self):
        self.select()
        graph = self.state("project-graph.json")
        original = json.loads(json.dumps(graph))
        for node in graph["nodes"]:
            if node["kind"] == "function":
                node["label"] = "forged_function"
        (self.project / ".agent-dispatcher/project-graph.json").write_text(json.dumps(graph))
        result = self.select()
        self.assertEqual(result["parser_cache"]["parsed_files"], 0)
        self.assertEqual(self.state("project-graph.json"), original)

    def test_disabled_cache_does_not_read_or_write_private_state(self):
        self.select()
        before = self.private_files()
        with mock.patch.object(context, "_parser_cache", side_effect=AssertionError("cache must be bypassed")):
            result = self.select(parser_cache=False)
        self.assertNotIn("parser_cache", result)
        self.assertEqual(self.private_files(), before)


if __name__ == "__main__":
    unittest.main()
