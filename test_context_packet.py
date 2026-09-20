"""Full serialization budgets, trusted guidance reads, and evidence trimming contracts."""
import copy
import hashlib
import math
import os
from pathlib import Path
import tempfile
import unittest

import context_packet as packet


class ContextPacketTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.pack = self.root / "pack"
        self.pack.mkdir()
        self.role = self.pack / "role.md"
        self.role.write_text("Role instructions: preserve existing user changes.\n")
        self.guide = self.pack / "guide.md"
        self.guide.write_text("Guide instructions: verify the observable behavior.\n")

    def source(self, path="src/main.py", lines="1-10", content="print('hello')\n" * 10):
        return {"path": path, "lines": lines, "content": content,
                "source_sha256": hashlib.sha256(content.encode()).hexdigest(),
                "id": hashlib.sha256((path + lines + content).encode()).hexdigest()}

    def result(self):
        excerpt = self.source()
        return {"schema_version": 1, "read_only": True, "size": "small", "role": "implementer",
                "project": str(self.root / "project"),
                "resources": {"role": {"id": "implementer", "path": str(self.role)},
                              "guides": [{"id": "test-design", "path": str(self.guide),
                                          "status": "bundled", "tiers": ["core"], "conditions": []}],
                              "conditions": {}, "diagnostics": []},
                "retrieval": [{"query": "main", "reason": "request search term"}],
                "context": [{"path": excerpt["path"], "lines": excerpt["lines"], "rank": 1}],
                "excerpts": [excerpt], "excluded": [],
                "excluded_summary": {"total": 0, "shown": 0, "by_reason": {}},
                "exclusion_policy": {"excluded_paths": ["private"], "source": "user request"},
                "project_map": {"entries": [], "estimated_tokens": 0, "status": "fresh"},
                "diagnostics": ["One path could not be read; scan is incomplete."],
                "limits": ["Custom mandatory constraint must remain visible."],
                "budget": {"target_tokens": 2000, "estimated_tokens": 35}}

    def compact(self, result=None, guides=()):
        return packet.compact_packet(result or self.result(), self.pack, guides)

    def test_full_packet_estimate_matches_exact_serialization_with_unicode(self):
        result = self.result()
        result["diagnostics"].append("Unicode sources: café 日本語 🍎")
        out = packet.fit_packet(self.compact(result, ["test-design"]), target=1200)
        serialized = packet.dumps(out)
        self.assertLessEqual(len(serialized), 1200 * 4)
        self.assertEqual(out["budget"]["estimated_tokens"], math.ceil(len(serialized) / 4))
        self.assertGreater(out["budget"]["estimated_tokens"], out["budget"]["excerpt_tokens"])
        self.assertIn("guidance", out["budget"]["by_source"])
        self.assertEqual(packet.account_packet(copy.deepcopy(out)), out)

    def test_role_and_only_explicit_guides_are_inlined_intact(self):
        default = self.compact()
        self.assertEqual(default["guidance"]["role"]["content"], self.role.read_text())
        self.assertEqual(default["guidance"]["guides"], [])
        out = packet.fit_packet(self.compact(guides=["test-design", "test-design"]), target=1000)
        self.assertEqual([g["content"] for g in out["guidance"]["guides"]], [self.guide.read_text()])
        self.assertEqual(out["guidance"]["guides"][0]["sha256"], hashlib.sha256(self.guide.read_bytes()).hexdigest())

    def test_large_escaped_evidence_is_trimmed_using_serialized_size(self):
        result = self.result()
        result["excerpts"] = [self.source(content='quoted "value" and \\escaped\\ path\n' * 500)]
        out = packet.fit_packet(self.compact(result), target=900)
        self.assertLessEqual(len(packet.dumps(out)), 3600)
        self.assertEqual(out["excerpts"], [])
        self.assertEqual(out["context"], [])
        self.assertEqual(out["packet_omissions"]["excerpts"], 1)
        self.assertEqual(out["guidance"]["role"]["content"], self.role.read_text())

    def test_unknown_unavailable_and_invalid_guide_selection_fails_clearly(self):
        for guides in (["missing"], ["../test-design"], [""], "test-design", ["test-design"] * 6):
            with self.subTest(guides=guides), self.assertRaises(packet.PacketError):
                self.compact(guides=guides)
        result = self.result()
        result["resources"]["guides"][0]["status"] = "external_availability_unknown"
        with self.assertRaises(packet.PacketError):
            self.compact(result, ["test-design"])

    def test_missing_selected_role_cannot_silently_drop_instructions(self):
        for role in (None, {"id": "implementer", "path": None}):
            result = self.result()
            result["resources"]["role"] = role
            with self.assertRaises(packet.PacketError):
                self.compact(result)

    def test_guidance_errors_are_sanitized_and_paths_stay_inside_package(self):
        outside = self.root / "sensitive-outside.md"
        outside.write_text("outside instructions")
        symlink = self.pack / "link.md"
        symlink.symlink_to(self.role)
        linked_dir = self.pack / "alias"
        linked_dir.symlink_to(self.pack, target_is_directory=True)
        fifo = self.pack / "fifo"
        os.mkfifo(fifo)
        for path in (outside, self.pack / "private-missing-name.md", symlink,
                     linked_dir / "role.md", self.pack, fifo):
            result = self.result()
            result["resources"]["role"]["path"] = str(path)
            with self.subTest(path=path), self.assertRaises(packet.PacketError) as caught:
                self.compact(result)
            self.assertNotIn(str(path), str(caught.exception))

    def test_oversized_or_non_utf8_guidance_is_rejected(self):
        for raw in (b"x" * (packet.MAX_GUIDANCE_BYTES + 1), b"\xff\xfe"):
            self.role.write_bytes(raw)
            with self.assertRaises(packet.PacketError):
                self.compact()

    def test_too_small_budget_fails_instead_of_truncating_guidance_or_constraints(self):
        self.guide.write_text("mandatory guide text\n" * 200)
        compact = self.compact(guides=["test-design"])
        original = copy.deepcopy(compact)
        with self.assertRaisesRegex(packet.PacketError, "required guidance and constraints"):
            packet.fit_packet(compact, target=256)
        self.assertEqual(compact, original)

    def test_exclusion_policy_diagnostics_and_custom_limits_survive_trimming(self):
        result = self.result()
        result["excluded"] = [{"path": f"private/{i}.py", "reason": "explicit exclusion"} for i in range(12)]
        result["excluded_summary"] = {"total": 12, "shown": 12, "by_reason": {"explicit exclusion": 12}}
        out = packet.fit_packet(self.compact(result), target=700)
        self.assertEqual(out["exclusion_policy"], result["exclusion_policy"])
        self.assertEqual(out["diagnostics"], result["diagnostics"])
        self.assertIn(result["limits"][0], out["limits"])
        self.assertEqual(out["excluded_summary"]["total"], 12)
        self.assertEqual(out["excluded_summary"]["shown"], len(out["excluded"]))
        self.assertEqual(out["packet_omissions"]["excluded_paths"], 12 - len(out["excluded"]))

    def test_candidates_are_optional_including_verification_locations(self):
        result = self.result()
        candidate = result["resources"]["guides"][0]
        candidate["tiers"] = ["verification"]
        candidate["path"] = str(self.pack / ("very-long-location-" * 80))
        out = packet.fit_packet(self.compact(result), target=750)
        self.assertEqual(out["resources"]["guides"], [])
        self.assertEqual(len(out["excerpts"]), 1)
        self.assertEqual(out["packet_omissions"]["guide_candidates"], 1)

    def test_context_ranges_ranks_and_excerpt_counts_follow_actual_evidence(self):
        result = self.result()
        result["excerpts"] += [self.source(lines="20-30"), self.source(path="src/other.py")]
        result["context"] += [{"path": "src/other.py", "lines": "wrong", "rank": 9},
                              {"path": "src/omitted.py", "lines": "1-2", "rank": 12}]
        out = packet.account_packet(self.compact(result))
        self.assertEqual(out["context"], [{"path": "src/main.py", "lines": "1-10, 20-30", "rank": 1},
                                          {"path": "src/other.py", "lines": "1-10", "rank": 2}])
        self.assertEqual(out["budget"]["excerpt_tokens"], sum(math.ceil(len(e["content"]) / 4) for e in out["excerpts"]))

    def test_reuse_references_are_counted_and_keep_matching_context(self):
        result = self.compact()
        excerpt = result["excerpts"].pop()
        reference = {key: excerpt[key] for key in ("id", "path", "lines")}
        result["reuse"] = {"status": "prepared", "references": [reference], "emitted_count": 99, "reused_count": 99}
        out = packet.fit_packet(result, target=1000, reserve_chars=512)
        self.assertLessEqual(len(packet.dumps(out)) + 512, 4000)
        self.assertEqual(out["context"][0]["path"], reference["path"])
        self.assertEqual(out["reuse"]["emitted_count"], 0)
        self.assertEqual(out["reuse"]["reused_count"], 1)

    def test_budget_and_reserved_space_reject_invalid_values(self):
        for target in (True, "1000", 255, 100001):
            with self.assertRaises(packet.PacketError):
                packet.fit_packet(self.compact(), target=target)
        for reserve in (True, -1, "512", 400001):
            with self.assertRaises(packet.PacketError):
                packet.fit_packet(self.compact(), reserve_chars=reserve)

    def graph(self):
        return {"status": "ready", "cache_status": "fresh", "evidence_origin": "source",
                "maintenance": "automatic", "coverage": {"complete": False},
                "diagnostics": ["Graph is bounded."], "estimated_tokens": 1000,
                "nodes": [{"id": "a", "source": {"path": "src/main.py", "line": 1}},
                          {"id": "b", "source": {"path": "src/other.py", "line": 2}}],
                "edges": [{"from": "a", "to": "b", "kind": "calls", "confidence": "resolved",
                           "method": "ast", "evidence": {"path": "src/main.py", "line": 3}}],
                "sources": [{"path": "src/main.py", "sha256": "a" * 64},
                            {"path": "src/other.py", "sha256": "b" * 64}],
                "source_priorities": {"src/main.py": {"score": 4}},
                "upstream": [], "downstream": ["b"], "seed_ids": ["a"], "possible_paths": [["a", "b"]]}

    def test_graph_trimming_preserves_status_and_leaves_no_dangling_evidence(self):
        graph = self.graph()
        for _ in range(20):
            dropped = packet._trim_graph(graph)
            ids = {node["id"] for node in graph["nodes"]}
            self.assertTrue(all(edge["from"] in ids and edge["to"] in ids for edge in graph["edges"]))
            self.assertTrue(set(graph["seed_ids"] + graph["upstream"] + graph["downstream"]) <= ids)
            self.assertTrue(all(set(path) <= ids for path in graph["possible_paths"]))
            paths = {node["source"]["path"] for node in graph["nodes"]}
            paths.update(edge["evidence"]["path"] for edge in graph["edges"])
            self.assertEqual({source["path"] for source in graph["sources"]}, paths)
            if not dropped:
                break
        self.assertEqual(graph["status"], "ready")
        self.assertEqual(graph["coverage"], {"complete": False})
        self.assertEqual(graph["diagnostics"], ["Graph is bounded."])
        self.assertFalse(graph["nodes"])
        self.assertFalse(graph["source_priorities"])

    def test_graph_budget_is_included_and_optional_graph_can_be_trimmed(self):
        for metadata_chars in (0, 512, 2048):
            with self.subTest(metadata_chars=metadata_chars):
                compact = self.compact()
                compact["diagnostics"].append("x" * metadata_chars)
                compact["resources"]["guides"] = []
                # Absolute temporary paths vary across hosts. Leave a measured
                # allowance for graph metadata, but not the complete graph.
                baseline = packet.fit_packet(compact, target=100000)
                target = math.ceil(len(packet.dumps(baseline)) / 4) + 128
                compact["project_graph"] = self.graph()
                untrimmed = packet.fit_packet(compact, target=100000)
                self.assertGreater(len(packet.dumps(untrimmed)), target * 4)
                out = packet.fit_packet(compact, target=target)
                self.assertLessEqual(len(packet.dumps(out)), target * 4)
                self.assertIn("project_graph", out["budget"]["by_source"])
                self.assertGreater(out["packet_omissions"].get("graph_items", 0), 0)
                self.assertEqual(out["excerpts"], compact["excerpts"])
                self.assertEqual(out["guidance"], compact["guidance"])

    def test_graph_paths_require_surviving_resolved_call_edges(self):
        for kind, confidence in (("imports", "resolved"), ("calls", "inferred")):
            graph = self.graph()
            graph["edges"][0].update(kind=kind, confidence=confidence)
            graph["possible_paths"] = [["a", "b"], ["a", "b"]]
            packet._trim_graph(graph)
            self.assertEqual(graph["possible_paths"], [])

    def test_graph_upstream_and_downstream_require_surviving_connections(self):
        graph = self.graph()
        graph["edges"] = []
        graph["upstream"] = ["b"]
        packet._trim_graph(graph)
        self.assertEqual({node["id"] for node in graph["nodes"]}, {"a", "b"})
        self.assertEqual(graph["upstream"], [])
        self.assertEqual(graph["downstream"], [])


if __name__ == "__main__":
    unittest.main()
