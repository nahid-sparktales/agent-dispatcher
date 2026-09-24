"""Full serialization budgets, trusted guidance reads, and evidence trimming contracts."""
import copy
import hashlib
import json
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

    def many_candidates(self):
        result = self.result()
        resources = result["resources"]
        for index in range(18):
            ident = f"candidate-{index}"
            condition = f"condition-{index}"
            resources["guides"].append({"id": ident, "path": str(self.guide), "status": "bundled",
                                        "tiers": ["core"] if index < 2 else ["preferred"] if index < 4 else [],
                                        "conditions": [condition]})
            resources["conditions"][condition] = f"Use this candidate when its task condition {index} actually applies."
        resources["guides"][15].update(tiers=["verification"], path=None, status="external_availability_unknown")
        resources["guides"][17]["tiers"] = ["verification"]
        return result

    def test_default_budget_keeps_the_packet_under_the_host_inline_result_cap(self):
        # A standard packet of 8000 tokens serializes to about 32 KB; Claude Code returns only a 2 KB preview of a
        # Bash result over 30,000 characters. The default must stay below that; an explicit budget is the caller's.
        result = self.result()
        result["size"] = "standard"
        result["excerpts"] = [self.source(f"src/module_{n}.py", "1-40", f"# module {n}\n" + ("x = 1  # " + "detail " * 12 + "\n") * 40) for n in range(40)]
        result["context"] = [{"path": e["path"], "lines": e["lines"], "rank": n + 1} for n, e in enumerate(result["excerpts"])]
        compact = self.compact(result)
        self.assertGreater(len(packet.dumps(compact)), 32000)
        fitted = packet.fit_packet(compact)
        self.assertLessEqual(len(packet.dumps(fitted)), packet.MAX_INLINE_CHARS)
        self.assertEqual((fitted["budget"]["target_tokens"], fitted["budget"]["max_chars"]), (8000, packet.MAX_INLINE_CHARS))
        self.assertTrue(fitted["excerpts"])  # Trimmed from the lowest-ranked file up, never emptied.
        self.assertEqual([e["path"] for e in fitted["excerpts"]], [e["path"] for e in compact["excerpts"][:len(fitted["excerpts"])]])
        explicit = packet.fit_packet(compact, target=8000)
        self.assertGreater(len(packet.dumps(explicit)), packet.MAX_INLINE_CHARS)
        self.assertLessEqual(len(packet.dumps(explicit)), 32000)
        self.assertEqual(explicit["budget"]["max_chars"], 32000)

    def test_large_budget_still_returns_a_small_truthful_candidate_shortlist(self):
        original = self.many_candidates()
        untouched = copy.deepcopy(original)
        for target in (4000, 18000, 100000):
            with self.subTest(target=target):
                out = packet.fit_packet(self.compact(original), target=target)
                resources = out["resources"]
                self.assertEqual([guide["id"] for guide in resources["guides"]],
                                 ["candidate-14", "candidate-16", "test-design"])
                self.assertEqual(resources["guides"][0]["status"], "external_availability_unknown")
                self.assertIsNone(resources["guides"][0]["path"])
                self.assertEqual(set(resources["conditions"]), {"condition-14", "condition-16"})
                self.assertNotIn("role", resources)
                self.assertEqual(out["guidance"]["role"]["path"], str(self.role))
                self.assertEqual(out["guidance"]["guides"], [])
                self.assertEqual(out["packet_omissions"]["guide_candidates"], 16)
                self.assertTrue(any("--json without --compact" in line and "--guide ID" in line for line in out["limits"]))
                # Hold every other field constant to measure metadata savings independently
                # of excerpt/graph trimming, model behavior, or host token accounting.
                full_metadata = copy.deepcopy(out)
                full_metadata["resources"] = original["resources"]
                packet.account_packet(full_metadata)
                self.assertLess(len(packet.dumps(out)), len(packet.dumps(full_metadata)) * 0.8)
                self.assertEqual(out["excerpts"], original["excerpts"])
                self.assertEqual(out["budget"]["estimated_tokens"], math.ceil(len(packet.dumps(out)) / 4))
        self.assertEqual(original, untouched)

    def test_explicit_guide_is_resolved_before_shortlisting_and_keeps_its_conditions(self):
        result = self.many_candidates()
        default = self.compact(result)
        self.assertNotIn("candidate-17", [guide["id"] for guide in default["resources"]["guides"]])
        out = packet.fit_packet(self.compact(result, ["candidate-17"]), target=100000)
        self.assertEqual([guide["id"] for guide in out["resources"]["guides"]],
                         ["candidate-14", "candidate-16", "test-design", "candidate-17"])
        self.assertEqual(out["resources"]["conditions"]["condition-17"],
                         result["resources"]["conditions"]["condition-17"])
        self.assertEqual(out["guidance"]["guides"][0]["content"], self.guide.read_text())
        self.assertEqual(out["packet_omissions"]["guide_candidates"], 15)

    def test_shortlist_stays_bounded_with_many_verification_and_selected_guides(self):
        result = self.many_candidates()
        for guide in result["resources"]["guides"]:
            guide["tiers"] = ["verification"]
        selected = [f"candidate-{index}" for index in range(5)]
        out = self.compact(result, selected)
        self.assertEqual([guide["id"] for guide in out["resources"]["guides"]],
                         ["test-design", "candidate-5", "candidate-6", *selected])
        self.assertEqual(len(out["resources"]["guides"]), 8)
        self.assertEqual([guide["id"] for guide in out["guidance"]["guides"]], selected)
        self.assertEqual(out["packet_omissions"]["guide_candidates"], 11)

    def test_shortlist_preserves_maintenance_scope_exclusions_and_diagnostics(self):
        result = self.many_candidates()
        for key, name in (("project_map", "project-map.json"), ("project_graph", "project-graph.json")):
            result.setdefault(key, {})["maintenance"] = {
                "action": "deferred", "persisted": False,
                "write_scope": {"allowed": False, "reason": "outside_writable_paths",
                                "target": f".agent-dispatcher/{name}"}}
        result["resources"]["diagnostics"].append("A package guide is unavailable; use its fallback.")
        out = packet.fit_packet(self.compact(result), target=100000)
        for key in ("project_map", "project_graph"):
            self.assertEqual(out[key]["maintenance"], result[key]["maintenance"])
        self.assertEqual(out["exclusion_policy"], result["exclusion_policy"])
        self.assertEqual(out["diagnostics"], result["diagnostics"])
        self.assertEqual(out["resources"]["diagnostics"], result["resources"]["diagnostics"])

    def test_fit_drops_default_candidates_before_explicit_metadata_and_counts_all_omissions(self):
        result = self.many_candidates()
        for guide in result["resources"]["guides"]:
            if guide["id"] in {"candidate-14", "candidate-16", "test-design"}:
                guide["path"] = str(self.pack / ("long-candidate-location-" * 200))
        compact = self.compact(result, ["candidate-17"])
        minimum = copy.deepcopy(compact)
        minimum["resources"]["guides"] = [minimum["resources"]["guides"][-1]]
        minimum["resources"]["conditions"] = {"condition-17": result["resources"]["conditions"]["condition-17"]}
        packet.account_packet(minimum)
        out = packet.fit_packet(compact, target=minimum["budget"]["estimated_tokens"] + 2)
        self.assertEqual([guide["id"] for guide in out["resources"]["guides"]], ["candidate-17"])
        self.assertEqual(set(out["resources"]["conditions"]), {"condition-17"})
        self.assertEqual(out["packet_omissions"]["guide_candidates"], 18)
        self.assertEqual(out["guidance"], compact["guidance"])
        self.assertEqual(out["excerpts"], compact["excerpts"])

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
        result = self.compact(self.many_candidates())
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

    # Lean and evidence packets.

    def full_result(self, rows=6, partial=("big/generated_parser.py",)):
        self.role.write_text("---\nid: implementer\nskills_core: test-design\n---\n\n# Implementer\nKeep user changes.\n")
        result = self.result()
        result["excerpts"] = []
        for n in range(rows):
            path = f"src/module_{n}.py"
            result["excerpts"] += [self.source(path, "1-20", f"# header {n}\n" * 20), self.source(path, "5-10", "# inner\n" * 6),
                                   self.source(path, "30-45", f"value_{n} = '🐙 日本'\n" * 16)]
        result["context"] = [{"path": f"src/module_{n}.py", "type": "source", "rank": n + 1, "lines": "1-20, 30-45",
                              "reason": "defines function; lexical relevance (BM25); " + "long detail " * 30, "match": "symbol",
                              "symbols": ["a", "b", "c", "d"], "relationships": ["imports x"]} for n in range(rows)]
        result["excluded"] = [{"path": f"vendor/{n}.js", "reason": "artifact cap"} for n in range(7)]
        result["excluded_summary"] = {"total": 7, "shown": 7, "by_reason": {"artifact cap": 7}}
        result["project_graph"] = self.graph()
        result["parser_cache"] = {"source_hits": 1, "source_misses": 2}
        result["preferences"] = {"output": "eli5-succinct", "requested_effort": "low", "storage_path": "/home/x/prefs.json"}
        result["change_focus"] = {"source": "git_uncommitted", "paths": [], "total": 0}
        result["project_map"]["entries"] = [{"kind": "feature", "label": f"fact {n}"} for n in range(4)]
        result["memory"] = {"status": "ok", "hits": [{"path": f"src/module_{n}.py", "note": "remembered " * 5} for n in range(3)]}
        conditions = [{"condition": "partial_coverage", "unread_files": 0, "by_state": {"complete": 9, "partial_lexical": 1},
                       "paths": list(partial)}] if partial else []
        result["repository_intelligence"] = {"strategy": "full", "task_signals": {"concepts": ["x"]}, "telemetry": {"final": 9},
                                             "index": {"status": "absent"}, "explain": "trace " * 400,
                                             "retrieval_status": {"status": "ok", "evidence": "anchored", "leader": "anchored",
                                                                  "conditions": conditions}}
        return result

    def slim(self, mode, result=None, explain=False, reuse="disabled"):
        out = packet.slim_packet(self.compact(result or self.full_result()), mode, explain)
        out["reuse"] = {"status": reuse, "emitted_count": 0, "reused_count": 0, "references": []}  # As prepare_reuse sets it.
        return out

    def test_measure_counts_code_points_utf8_bytes_and_utf16_units(self):
        self.assertEqual(packet.measure("a🐙日\n"), {"chars": 4, "utf8_bytes": 9, "utf16_units": 5,
                                                   "estimated_tokens": 5, "legacy_estimate": 1})

    def test_lean_keeps_rows_coverage_and_role_body_and_drops_what_the_worker_does_not_act_on(self):
        out = packet.fit_slim(self.slim("lean"), 100000, None)
        self.assertNotIn("excerpts", out)
        for key in ("resources", "project_graph", "parser_cache", "excluded", "change_focus", "repository_intelligence", "reuse",
                    "project_map"):
            self.assertNotIn(key, out)
        self.assertEqual(out["packet_omissions"]["map_facts"], 4)  # Lean is navigation only: facts leave even with room.
        self.assertEqual(len(packet.fit_slim(self.slim("evidence"), 100000, None)["project_map"]["entries"]), 4)
        self.assertEqual(out["preferences"], {"output": "eli5-succinct", "requested_effort": "low"})
        self.assertEqual(out["excluded_summary"], {"total": 7, "by_reason": {"artifact cap": 7}})
        self.assertEqual(out["packet_omissions"]["excluded_paths"], 7)
        self.assertEqual(out["context"][0], {"rank": 1, "path": "src/module_0.py", "lines": "1-20, 30-45",
                                             "symbols": ["a", "b", "c"], "reason": "defines function", "match": "symbol"})
        self.assertEqual(len(out["context"]), 6)
        role = out["guidance"]["role"]
        self.assertEqual(role["content"], "\n# Implementer\nKeep user changes.\n")
        self.assertEqual((role["content_scope"], role["sha256"]), ("body", hashlib.sha256(self.role.read_bytes()).hexdigest()))
        self.assertEqual(out["coverage"], {"status": "ok", "evidence": "anchored",
                                           "conditions": self.full_result()["repository_intelligence"]["retrieval_status"]["conditions"]})
        self.assertIn("big/generated_parser.py", out["next_action"])
        self.assertEqual(out["limits"], packet.SLIM_LIMITS)
        self.assertEqual((out["packet_mode"], out["format"]), ("lean", "compact"))
        self.assertEqual(out["diagnostics"], ["One path could not be read; scan is incomplete."])

    def test_evidence_spans_drop_contained_duplicates_keep_two_per_file_in_rank_order(self):
        excerpts = [self.source("b.py", "1-20"), self.source("b.py", "5-10"), self.source("b.py", "30-40"),
                    self.source("b.py", "30-40"), self.source("b.py", "50-60"), self.source("a.py", "3-8")]
        kept = packet._evidence_spans(copy.deepcopy(excerpts), ["a.py", "b.py"])
        # Without an admission order (legacy retrieval), the first two spans listed.
        self.assertEqual([(e["path"], e["lines"]) for e in kept], [("a.py", "3-8"), ("b.py", "1-20"), ("b.py", "30-40")])
        for item, order in zip(excerpts, (2, 3, 0, 0, 1, 0)):
            item["order"] = order  # The engine's admission round: priority, then line.
        kept = packet._evidence_spans(excerpts, ["a.py", "b.py"])
        self.assertEqual([(e["path"], e["lines"]) for e in kept], [("a.py", "3-8"), ("b.py", "30-40"), ("b.py", "50-60")])
        self.assertFalse(any("order" in item for item in kept))
        # Two definitions (priority 1) and a reference (priority 2): the line-1 definition is a top span, never the first to go.
        spans = [dict(self.source("t.py", lines), order=order) for lines, order in (("1-12", 0), ("55-67", 2), ("114-123", 1))]
        self.assertEqual([e["lines"] for e in packet._evidence_spans(spans, ["t.py"])], ["1-12", "114-123"])
        out = packet.fit_slim(self.slim("evidence"), 100000, None)
        self.assertEqual([(e["path"], e["lines"]) for e in out["excerpts"][:2]], [("src/module_0.py", "1-20"), ("src/module_0.py", "30-45")])
        self.assertEqual(len(out["excerpts"]), 12)
        self.assertEqual(out["packet_omissions"]["excerpts"], 6)
        self.assertEqual(set(out["excerpts"][0]), {"path", "lines", "content"})  # Ids and digests serve only active reuse.
        prepared = packet.fit_slim(self.slim("evidence", reuse="prepared"), 100000, None)
        self.assertEqual(set(prepared["excerpts"][0]), {"path", "lines", "content", "id", "source_sha256"})
        self.assertEqual(prepared["reuse"]["emitted_count"], 12)

    def test_shared_budget_counts_skill_router_and_the_packet_with_its_newline(self):
        (self.pack / "SKILL.md").write_text("# Router 🐙\n" + "Route the request.\n" * 20, encoding="utf-8")
        skill = packet.router_size(self.pack)
        self.assertEqual(skill, {"source": "SKILL.md", **packet.measure((self.pack / "SKILL.md").read_text(encoding="utf-8"))})
        out = packet.fit_slim(self.slim("evidence"), 100000, skill)
        budget = out["budget"]
        self.assertEqual(budget["packet"], packet.measure(packet.dumps(out) + "\n"))
        self.assertEqual(budget["total"], {key: budget["packet"][key] + skill[key] for key in packet.SIZES})
        self.assertTrue(budget["target_met"])
        self.assertIn("not a tokenizer count", budget["estimator"])
        self.assertEqual(budget["excluded"], ["host command envelope", "tool-result framing"])
        self.assertEqual((budget["hard_limit"]["max"], budget["hard_limit"]["host_inline_limit"]), (28000, 30000))
        (self.pack / "SKILL.md").unlink()
        self.assertIsNone(packet.router_size(self.pack))
        unknown = packet.fit_slim(self.slim("lean"), 100000, None)["budget"]
        self.assertEqual(unknown["skill_router"], {"source": "unknown", **dict.fromkeys(packet.SIZES)})
        self.assertEqual(unknown["total"], unknown["packet"])

    def test_tiny_target_is_reported_unmet_and_drops_nothing_it_could_not_save(self):
        full = packet.fit_slim(self.slim("evidence", explain=True), 100000, None)
        out = packet.fit_slim(self.slim("evidence", explain=True), 256, None)
        budget = out["budget"]
        self.assertEqual((budget["target_met"], budget["reason"]), (False, "protected_content_exceeds_target"))
        self.assertGreater(budget["protected_tokens"], 256)
        self.assertEqual(budget["protected_tokens"], budget["total"]["estimated_tokens"])
        for key in ("guidance", "coverage", "next_action", "limits", "context", "diagnostics"):
            self.assertEqual(out[key], full[key])  # Protected content, navigation rows included, is intact ...
        self.assertEqual(out["excerpts"], [])  # ... and the minimum packet carries no optional item.
        self.assertNotIn("project_map", out)
        self.assertNotIn("explain", out["repository_intelligence"])
        self.assertEqual((out["memory"]["hits"], out["packet_omissions"]["memory_hits"]), ([], 3))

    def test_feasible_target_trims_optional_items_in_order_and_keeps_every_row_deterministically(self):
        floor = packet.fit_slim(self.slim("evidence", explain=True), 100000, None)
        while packet._trim_slim(floor):
            pass
        tokens, _ = packet.account_slim(floor, 100000, None)
        runs = [packet.fit_slim(self.slim("evidence", explain=True), tokens, None) for _ in range(2)]
        self.assertEqual(runs[0], runs[1])
        out = runs[0]
        self.assertTrue(out["budget"]["target_met"])
        self.assertEqual(out["context"], packet.fit_slim(self.slim("evidence", explain=True), 100000, None)["context"])
        self.assertEqual(out["excerpts"], [])
        self.assertNotIn("project_map", out)
        self.assertNotIn("explain", out["repository_intelligence"])
        self.assertEqual({key: out["packet_omissions"][key] for key in ("explain_trace", "map_facts", "excerpts")},
                         {"explain_trace": 1, "map_facts": 4, "excerpts": 18})
        self.assertNotIn("navigation_rows", out["packet_omissions"])
        trimmed = packet.fit_slim(self.slim("evidence", explain=True), 100000, None)
        packet._trim_slim(trimmed)
        just_trace = packet.fit_slim(self.slim("evidence", explain=True), packet.account_slim(trimmed, 100000, None)[0] + 8, None)
        self.assertNotIn("explain", just_trace["repository_intelligence"])  # The trace leaves first ...
        self.assertEqual(len(just_trace["excerpts"]), 12)  # ... and evidence stays when that suffices.
        self.assertEqual(just_trace["packet_omissions"]["map_facts"], 0)
        full = packet.fit_slim(self.slim("evidence"), 100000, None)
        middle = packet.fit_slim(self.slim("evidence"), packet.account_slim(full, 100000, None)[0] - 400, None)
        omitted = middle["packet_omissions"]
        self.assertEqual((omitted["map_facts"], omitted["memory_hits"]), (4, 3))  # Facts and memory hits go first ...
        self.assertTrue(0 < len(middle["excerpts"]) < 12)  # ... then excerpts, from the lowest-ranked file up.
        self.assertEqual(middle["excerpts"], full["excerpts"][:len(middle["excerpts"])])
        self.assertEqual(middle["excerpts"][0]["path"], "src/module_0.py")

    def test_slim_packets_keep_the_diagnostics_of_the_parts_they_reduce_or_drop(self):
        result = self.full_result()
        preferences = "Preferences unavailable or invalid; using defaults without changing saved settings."
        result["preferences"]["diagnostics"] = [preferences]
        result["project_map"]["diagnostics"] = ["Project map facts were stale and withheld."]
        for mode in ("lean", "evidence"):
            with self.subTest(mode=mode):
                out = packet.fit_slim(self.slim(mode, result), 100000, None)
                self.assertEqual(out["diagnostics"], ["One path could not be read; scan is incomplete.", preferences,
                                                      "Project map facts were stale and withheld."])
                self.assertEqual(out["preferences"], {"output": "eli5-succinct", "requested_effort": "low"})
        self.assertNotIn("diagnostics", out["project_map"])  # Evidence keeps the facts; the diagnostic is not shown twice.

    def test_hard_limit_counts_utf16_units_and_the_newline_and_fails_rather_than_truncating(self):
        result = self.full_result(rows=8)
        for n, excerpt in enumerate(result["excerpts"]):
            excerpt["content"] = "🐙" * 1400  # One code point, two UTF-16 units and four UTF-8 bytes each.
        out = packet.fit_slim(self.slim("evidence", result), 100000, None)
        serialized = packet.dumps(out) + "\n"
        self.assertLessEqual(len(serialized.encode("utf-16-le")) // 2, packet.MAX_INLINE_CHARS)
        self.assertEqual(out["budget"]["packet"]["utf16_units"], len(serialized.encode("utf-16-le")) // 2)
        self.assertGreater(out["packet_omissions"]["excerpts"], 8)
        self.assertLess(len(serialized) + 1500, packet.MAX_INLINE_CHARS)  # Counting code points would have kept another.
        self.assertEqual(json.loads(serialized)["context"][0]["path"], "src/module_0.py")
        long_paths = self.full_result(rows=8)
        for row in long_paths["context"]:
            row["path"] = "deeply/" * 60 + row["path"]
        out = packet.fit_slim(self.slim("lean", long_paths), 100000, None)
        self.assertEqual(len(out["context"]), 8)
        self.assertLessEqual(out["budget"]["packet"]["utf16_units"], packet.MAX_INLINE_CHARS)
        self.role.write_text("mandatory role text " * 1500)
        with self.assertRaisesRegex(packet.PacketError, "host inline limit") as caught:
            packet.fit_slim(self.slim("lean", self.result()), 100000, None)
        self.assertNotIn("mandatory role text", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
