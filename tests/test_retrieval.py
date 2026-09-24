"""Repository intelligence: query analysis, retrievers, fusion, graph, history, budget, explorer."""
import hashlib
import importlib.util
from pathlib import Path
import unittest
from collections import Counter

import context
import context_budget
import repo_index
import retrieval


def build(files, history=None, config=None, path_only=()):
    hashes = {path: hashlib.sha256(text.encode()).hexdigest() for path, text in files.items()}
    return retrieval.build_index(files, hashes, context._kind, history=history, config=config, path_only=path_only)


def ranked(task, index, strategy="full", **options):
    return [row["path"] for row in retrieval.retrieve(task, index, retrieval.configure(strategy), **options)["ranked"]]


def log(*commits):
    return "".join(f"\x01{1700000000 + n}\n\n" + "\n".join(paths) + "\n" for n, paths in enumerate(commits))


SQL = {
    "sqlglot/__init__.py": "from sqlglot.executor import execute\n",
    "sqlglot/executor/__init__.py": "from sqlglot.executor.python import PythonExecutor\n\n\ndef execute(sql, tables=None):\n    return PythonExecutor().execute(sql)\n",
    "sqlglot/executor/python.py": "from sqlglot.planner import QueryPlanner\n\nMAX_RETRIES = 3\n\n\nclass PythonExecutor:\n    def execute(self, plan):\n        return QueryPlanner(plan).run()\n",
    "sqlglot/planner.py": "class QueryPlanner:\n    def __init__(self, expression):\n        self.expression = expression\n\n    def run(self):\n        return self.expression\n",
    "sqlglot/errors.py": "class UnsupportedError(Exception):\n    pass\n",
    "tests/test_executor.py": "from sqlglot.executor import execute\n\n\ndef test_execute():\n    assert execute('SELECT 1')\n",
    "README.md": "sqlglot parses SQL. The executor runs a query plan.\n",
}


class QueryAnalysisTests(unittest.TestCase):
    def test_request_is_split_into_named_things_concepts_and_generic_words(self):
        query = retrieval.analyze_query(
            "Fix sqlglot.executor so execute() handles unsupported table expressions in src/foo/bar.py. "
            "Client.connect() ignores MAX_RETRIES, query_executor and queryExecutor in HTTPClient.")
        self.assertEqual(query["paths"], ["src/foo/bar.py"])
        self.assertIn("sqlglot.executor", query["dotted"])
        self.assertIn("execute", query["symbols"])
        self.assertIn(("Client", "connect"), query["qualified"])
        for identifier in ("MAX_RETRIES", "query_executor", "queryExecutor", "HTTPClient"):
            self.assertIn(identifier, query["identifiers"])
        self.assertTrue({"unsupported", "table", "expressions"} <= set(query["concept_terms"]))
        self.assertTrue({"fix", "handles"} <= set(query["generic_terms"]))
        self.assertNotIn("fix", query["terms"])
        self.assertGreater(query["terms"]["MAX_RETRIES"], query["terms"]["table"])
        self.assertLess(query["terms"]["retry"], query["terms"]["MAX_RETRIES"])  # subtoken of the constant

    def test_dotted_symbol_feeds_module_and_symbol_lookup(self):
        query = retrieval.analyze_query("requests.sessions.Session leaks connections")
        self.assertEqual(query["dotted"], ["requests.sessions.Session"])
        self.assertIn(("sessions", "Session"), query["qualified"])
        self.assertIn("Session", query["symbol_names"])

    def test_abbreviations_urls_and_file_names_are_not_dotted_modules(self):
        query = retrieval.analyze_query("See https://example.com/a.b for e.g. README.md and i.e. nothing")
        self.assertEqual(query["dotted"], [])
        self.assertEqual(query["paths"], ["README.md"])

    def test_explain_query_is_readable(self):
        text = retrieval.render_query(retrieval.analyze_query("Fix execute() for unsupported tables"))
        self.assertIn("IDENTIFIERS\n  execute", text)
        self.assertIn("IGNORED/LOW-WEIGHT TERMS\n  fix", text)


class RetrieverTests(unittest.TestCase):
    def setUp(self):
        self.index = build(SQL)
        self.config = retrieval.configure("full")

    def top(self, name, task):
        rows = retrieval.RETRIEVERS[name](retrieval.analyze_query(task), self.index, self.config)
        return [row["file"] for row in rows]

    def test_exact_and_partial_path(self):
        self.assertEqual(self.top("path", "look at sqlglot/planner.py")[0], "sqlglot/planner.py")
        self.assertEqual(self.top("path", "the planner is slow")[0], "sqlglot/planner.py")
        self.assertIn("sqlglot/executor/python.py", self.top("path", "executor crashes"))
        self.assertEqual(self.top("path", "plann is slow"), ["sqlglot/planner.py"])  # partial match, five characters or more
        self.assertEqual(self.top("path", "plan is slow"), [])  # too short to guess from

    def test_dotted_name_resolves_module_package_and_symbol(self):
        rows = retrieval.path_retriever(retrieval.analyze_query("sqlglot.executor.python.PythonExecutor"), self.index, self.config)
        self.assertEqual(rows[0]["file"], "sqlglot/executor/python.py")
        package = retrieval.path_retriever(retrieval.analyze_query("sqlglot.executor fails"), self.index, self.config)
        self.assertEqual(package[0]["file"], "sqlglot/executor/__init__.py")
        self.assertIn("sqlglot/executor/python.py", [row["file"] for row in package])
        self.assertEqual(self.top("symbol_definitions", "sqlglot.executor.python.PythonExecutor")[0], "sqlglot/executor/python.py")

    def test_rare_terms_and_bm25(self):
        self.assertEqual(self.top("rare_terms", "unsupported statements")[0], "sqlglot/errors.py")
        self.assertEqual(self.top("bm25", "unsupported statements")[0], "sqlglot/errors.py")
        self.assertEqual(self.top("rare_terms", "fix this code please"), [])

    def test_symbol_definitions_and_references(self):
        self.assertEqual(self.top("symbol_definitions", "QueryPlanner is wrong")[0], "sqlglot/planner.py")
        self.assertEqual(self.top("symbol_references", "QueryPlanner is wrong"), ["sqlglot/executor/python.py"])
        self.assertEqual(self.index.definitions["execute"][0][:2], ("sqlglot/executor/__init__.py", 4))
        self.assertIn("tests/test_executor.py", self.index.referencing("execute"))
        self.assertIn("PythonExecutor", self.index.symbols_in("sqlglot/executor/python.py"))
        self.assertIn("MAX_RETRIES", self.index.symbols_in("sqlglot/executor/python.py"))

    def test_every_candidate_carries_provenance(self):
        result = retrieval.retrieve("Fix sqlglot.executor so execute() handles unsupported tables", self.index, self.config)
        for row in result["ranked"]:
            self.assertTrue(row["evidence"])
            for item in row["evidence"]:
                self.assertTrue({"source", "reason", "value", "rank"} <= set(item))
        self.assertEqual(result["ranked"][0]["path"], "sqlglot/executor/__init__.py")
        text = retrieval.render_explain(retrieval.run("Fix sqlglot.executor so execute() fails", self.index, self.config), verbose=True)
        for expected in ("QUERY ANALYSIS", "TOP FILES", "symbol_definitions rank #1", "PIPELINE", "SEEDS", "CONTEXT"):
            self.assertIn(expected, text)

    def test_traceback_frames_resolve_by_suffix_anchor_excerpts_and_name_symbols(self):
        index = build(SQL)
        task = ("The executor crashes:\n\nTraceback (most recent call last):\n"
                "  File \"/opt/venv/lib/python3.12/site-packages/sqlglot/executor/__init__.py\", line 4, in execute\n"
                "    return PythonExecutor().execute(sql)\n"
                "  File \"/opt/venv/lib/python3.12/site-packages/sqlglot/planner.py\", line 6, in run\n"
                "    return self.expression\nAttributeError: 'NoneType' object has no attribute 'expression'\n")
        query = retrieval.analyze_query(task)
        self.assertEqual([(f["path"].split("/")[-2:], f["line"], f["function"], f["innermost"]) for f in query["frames"]],
                         [(["executor", "__init__.py"], 4, "execute", False), (["sqlglot", "planner.py"], 6, "run", True)])
        self.assertEqual(query["paths"], [])  # An absolute frame path is never a pinned explicit path.
        self.assertIn("run", query["symbols"])
        rows = retrieval.path_retriever(query, index, retrieval.configure("full"))
        by_file = {row["file"]: row for row in rows}
        self.assertEqual(rows[0]["file"], "sqlglot/planner.py")  # The innermost frame counts double.
        self.assertIn("traceback frame", by_file["sqlglot/executor/__init__.py"]["reason"])
        self.assertFalse(any(row.get("decisive") for row in rows))
        self.assertEqual(retrieval.frame_anchors(query, index, retrieval.configure("full")), {"sqlglot/planner.py": 6, "sqlglot/executor/__init__.py": 4})
        outcome = retrieval.run(task, index, retrieval.configure("full"))
        planner = next(item for item in outcome["packet"]["files"] if item["path"] == "sqlglot/planner.py")
        self.assertTrue(any(e["start"] <= 6 <= e["end"] for e in planner["excerpts"]))
        without = retrieval.path_retriever(query, index, retrieval.configure("full-frames"))
        self.assertFalse(any("traceback" in row["reason"] for row in without))
        # A bare file name resolves only when unique; a frame in an unrelated tree names nothing.
        ambiguous = retrieval.analyze_query('File "/x/__init__.py", line 1, in f\nFile "/other/nowhere.py", line 2, in g')
        self.assertEqual(retrieval.frame_anchors(ambiguous, index, retrieval.configure("full")), {})

    def test_structural_records_make_oversized_files_findable_by_symbol_but_never_excerpted(self):
        files = dict(SQL)
        structural = {"sqlglot/generator.py": {"record": dict(repo_index.file_record("sqlglot/generator.py", "class Generator:\n    def generate_offset(self):\n        return 1\n"), terms={}, len=0, structural=True), "sha256": "a" * 64}}
        hashes = {path: hashlib.sha256(text.encode()).hexdigest() for path, text in files.items()}
        index = retrieval.build_index(files, hashes, context._kind, path_only=["sqlglot/generator.py"], structural=structural)
        self.assertIn("sqlglot/generator.py", index.path_only)
        self.assertEqual(index.symbols_in("sqlglot/generator.py"), ["Generator", "generate_offset"])
        outcome = retrieval.run("generate_offset() drops the OFFSET clause", index, retrieval.configure("full"))
        self.assertEqual(outcome["ranked"][0]["path"], "sqlglot/generator.py")
        self.assertIn("symbol_definitions", {e["source"] for e in outcome["ranked"][0]["evidence"]})
        item = next(item for item in outcome["packet"]["files"] if item["path"] == "sqlglot/generator.py")
        self.assertEqual((item["excerpts"], item["symbols"]), ([], ["generate_offset"]))
        self.assertIn("over the file read limit", item["note"])
        plain = retrieval.build_index(files, hashes, context._kind, path_only=["sqlglot/generator.py"], structural=structural,
                                      config=retrieval.configure("full-structure"))
        self.assertEqual(plain.symbols_in("sqlglot/generator.py"), [])

    def test_file_over_the_read_limit_is_ranked_by_name_imports_and_history_but_never_read(self):
        files = {"pkg/lexer.py": "from pkg.parser import Parser\n\n\ndef tokens():\n    return Parser()\n", "pkg/other.py": "value = 1\n"}
        index = build(files, history=log(*[["pkg/lexer.py", "pkg/parser.py"]] * 3), path_only=["pkg/parser.py"])
        self.assertNotIn("pkg/parser.py", index.records)
        self.assertIn("imports", index.edges["pkg/lexer.py"]["pkg/parser.py"])
        self.assertEqual(ranked("pkg.parser drops tokens", index)[0], "pkg/parser.py")
        result = retrieval.run("tokens() returns nothing", index, retrieval.configure("full"))
        item = next(item for item in result["packet"]["files"] if item["path"] == "pkg/parser.py")
        self.assertEqual(item["excerpts"], [])
        self.assertIn("read limit", item["note"])
        self.assertEqual({e["source"] for row in result["ranked"] if row["path"] == "pkg/parser.py" for e in row["evidence"]},
                         {"graph", "git"})

    def test_unsupported_language_indexes_without_symbols(self):
        index = build({"main.zig": "pub fn run() void {}\n", "notes.bin.txt": "\x01 garbage ((( \n", "broken.py": "def (:\n"})
        self.assertEqual(index.records["broken.py"]["lang"], "python-unparsed")
        self.assertEqual(ranked("run", index)[0], "main.zig")

    def test_typescript_definitions_imports_and_tests(self):
        index = build({"src/parse.ts": "export function parseQuery(sql: string) { return sql }\nexport class QueryPlanner {}\n",
                       "src/api.ts": "import { parseQuery } from './parse'\nexport const handler = () => parseQuery('x')\n",
                       "src/parse.test.ts": "import { parseQuery } from './parse'\n"})
        self.assertEqual(index.definitions["parseQuery"][0][0], "src/parse.ts")
        self.assertIn("imports", index.edges["src/api.ts"]["src/parse.ts"])
        self.assertIn("tested_by", index.edges["src/parse.ts"]["src/parse.test.ts"])


class FusionTests(unittest.TestCase):
    def test_several_weak_votes_beat_one_noisy_first_place(self):
        config = retrieval.configure("full")
        lists = {"bm25": [{"file": "noisy.py", "rank": 1, "score": 99.0}, {"file": "real.py", "rank": 3, "score": 1.0}],
                 "path": [{"file": "real.py", "rank": 2, "score": 1.0}],
                 "symbol_definitions": [{"file": "real.py", "rank": 2, "score": 1.0}]}
        scores = retrieval.fuse(lists, config)
        self.assertGreater(scores["real.py"], scores["noisy.py"])
        self.assertAlmostEqual(scores["noisy.py"], 1 / (config["rrf_k"] + 1))

    def test_order_is_deterministic_and_near_ties_are_settled_by_evidence_before_path(self):
        files = {f"pkg/{name}.py": "value = compute_total()\n" for name in ("zeta", "alpha", "mid")}
        files["pkg/zeta.py"] = "def compute_total():\n    return 1\n"
        index = build(files)
        first = ranked("compute_total is wrong", index)
        self.assertEqual(first, ranked("compute_total is wrong", index))
        config = retrieval.configure("full", {"tie_tolerance": 0.25})
        order = [row["path"] for row in retrieval.retrieve("compute_total is wrong", index, config)["ranked"]]
        self.assertEqual(order[0], "pkg/zeta.py")  # The definition wins a near-tie although it sorts last by name.
        self.assertEqual(sorted(order[1:]), ["pkg/alpha.py", "pkg/mid.py"])


class RegressionTests(unittest.TestCase):
    def test_central_file_with_every_term_loses_to_the_specific_file(self):
        words = "executor specialized table offset unsupported expression planner generator parser token"
        files = {"central.py": "\n".join(f"{w} = '{w} {words}'" for w in words.split() * 40) + "\nimport executor\n",
                 "executor/specialized.py": "def execute_offset(table):\n    raise UnsupportedOffset(table)\n\n\nclass UnsupportedOffset(Exception):\n    pass\n"}
        files.update({f"lib/mod{n}.py": f"from central import {words.split()[n % 10]}\nvalue{n} = {n}\n" for n in range(30)})
        index = build(files)
        self.assertEqual(ranked("executor specialized: execute_offset fails for an unsupported table offset", index)[0],
                         "executor/specialized.py")
        self.assertEqual(ranked("UnsupportedOffset raised for table offset", index)[0], "executor/specialized.py")

    def test_generic_terms_in_200_files_do_not_tie_alphabetically(self):
        noise = "keep network package changes working when connection errors occur\n"
        files = {f"src/pkg{n:03}/__init__.py": f"# {noise}def keep_{n}():\n    return 'network package connection changes'\n" for n in range(200)}
        files["src/network/checkout.py"] = "def checkout_package(connection):\n    return connection.fetch()\n"
        index = build(files)
        task = "Keep network package checkout changes working when connection errors occur."
        result = retrieval.retrieve(task, index, retrieval.configure("full"))
        self.assertEqual(result["ranked"][0]["path"], "src/network/checkout.py")
        self.assertGreater(result["ranked"][0]["score"], result["ranked"][1]["score"])
        legacy_terms, identifiers, phrases, _ = context._terms(task)
        legacy = [c for path, text in files.items()
                  if (c := context._candidate(path, text, legacy_terms, identifiers, phrases, {}, set(), None))]
        top = sorted(legacy, key=context._sort)
        self.assertGreater(sum(c["score"] == top[0]["score"] for c in top), 100)  # the failure mode being replaced

    def test_tests_support_but_do_not_crowd_out_implementation(self):
        index = build(SQL)
        order = ranked("execute returns nothing", index)
        self.assertLess(order.index("sqlglot/executor/__init__.py"), order.index("tests/test_executor.py"))
        self.assertIn("tests/test_executor.py", order)
        asked = ranked("add a test for execute", index)
        self.assertLess(asked.index("tests/test_executor.py"), order.index("tests/test_executor.py") + 1)


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.index = build(SQL)

    def test_grouped_lexical_voters_cannot_outvote_one_decisive_source(self):
        row = lambda path, rank: {"file": path, "rank": rank, "score": 1.0 / rank}  # noqa: E731
        lists = {"bm25": [row("a.py", 1), row("c.py", 2)], "rare_terms": [row("a.py", 1), row("c.py", 2)],
                 "symbol_references": [row("a.py", 1), row("c.py", 2)], "symbol_definitions": [row("b.py", 1)], "path": [row("b.py", 1)]}
        plain = retrieval.fuse(lists, retrieval.configure("full"))
        self.assertGreater(plain["a.py"], plain["b.py"])  # Three readings of the same tokens outvote two independent facts.
        grouped = retrieval.configure("full", {"fusion_groups": {"lexical": {"sources": ["bm25", "rare_terms", "symbol_references"], "weight": 1.0}}})
        fused = retrieval.fuse(lists, grouped)
        self.assertGreater(fused["b.py"], fused["a.py"])
        self.assertEqual(set(fused), {"a.py", "b.py", "c.py"})
        self.assertEqual(lists.keys(), {"bm25", "rare_terms", "symbol_references", "symbol_definitions", "path"})  # Evidence lists untouched.

    def test_multi_edge_neighbors_count_every_edge_only_when_asked(self):
        class Index:
            in_degree = Counter()
            neighbors = staticmethod(lambda path: [("b.py", "imports", 3), ("b.py", "references", "Thing"), ("c.py", "calls", "helper")] if path == "a.py" else [])
            same_directory = staticmethod(lambda path: [])
        order = lambda policy: [r["file"] for r in retrieval.graph_candidates(["a.py"], Index(), retrieval.configure("full", {"graph": {"multi_edge": policy}}))]  # noqa: E731
        self.assertEqual(order("max"), ["c.py", "b.py"])  # calls 1.0 beats references 0.8
        self.assertEqual(order("sum"), ["b.py", "c.py"])  # references 0.8 + imports 0.5 beats calls 1.0
        self.assertEqual(order("soft"), ["b.py", "c.py"])  # 0.8 + 0.25
        best = next(r for r in retrieval.graph_candidates(["a.py"], Index(), retrieval.configure("full", {"graph": {"multi_edge": "sum"}})) if r["file"] == "b.py")
        self.assertIn("referenced by", best["reason"])  # The strongest edge still explains the neighbor.

    def test_one_hop_expansion_reaches_a_file_the_request_never_mentions(self):
        rows = retrieval.graph_candidates(["sqlglot/executor/python.py"], self.index, retrieval.configure("full"))
        found = {row["file"]: row for row in rows}
        self.assertIn("sqlglot/planner.py", found)
        self.assertEqual(found["sqlglot/planner.py"]["via"], "sqlglot/executor/python.py")
        self.assertNotIn("sqlglot/errors.py", found)  # unconnected

    def test_second_hop_is_optional_and_decayed(self):
        one = retrieval.graph_candidates(["tests/test_executor.py"], self.index, retrieval.configure("full"))
        self.assertNotIn("sqlglot/planner.py", [row["file"] for row in one])
        config = retrieval.configure("full", {"graph": {"max_hops": 3}})
        deep = {row["file"]: row["score"] for row in retrieval.graph_candidates(["tests/test_executor.py"], self.index, config)}
        self.assertIn("sqlglot/planner.py", deep)
        self.assertLess(deep["sqlglot/planner.py"], deep["sqlglot/executor/__init__.py"])

    def test_high_degree_hub_is_damped_and_neighbor_limits_hold(self):
        files = {"hub.py": "def shared_helper():\n    return 1\n", "rare.py": "def rare_helper():\n    return 2\n",
                 "seed.py": "from hub import shared_helper\nfrom rare import rare_helper\n"}
        files.update({f"user{n}.py": "from hub import shared_helper\n" for n in range(40)})
        index = build(files)
        scores = {row["file"]: row["score"] for row in retrieval.graph_candidates(["seed.py"], index, retrieval.configure("full"))}
        self.assertGreater(scores["rare.py"], scores["hub.py"])
        config = retrieval.configure("full", {"graph": {"max_neighbors_per_seed": 3, "max_candidates": 2}})
        self.assertLessEqual(len(retrieval.graph_candidates(["hub.py"], index, config)), 2)

    def test_same_directory_never_introduces_a_file(self):
        index = build({"pkg/auth.py": "def validateLogin():\n    pass\n", "pkg/unrelated.py": "value = 1\n"})
        self.assertEqual(ranked("Fix validateLogin", index), ["pkg/auth.py"])


class GitHistoryTests(unittest.TestCase):
    def test_jaccard_normalizes_high_churn_files(self):
        commits = [(n, ["parser.py", "generator.py"]) for n in range(6)] + [(n, ["parser.py", "optimizer.py"]) for n in range(3)]
        commits += [(n, ["CHANGELOG.md", name]) for n in range(30) for name in ("parser.py", "a.py", "b.py", "c.py")]
        partners = repo_index.cochange(commits, min_support=2)
        scores = {other: score for other, score, _ in partners["parser.py"]}
        self.assertAlmostEqual(scores["generator.py"], 6 / 39, places=3)
        self.assertGreater(scores["generator.py"], scores["optimizer.py"])
        self.assertLess(scores["CHANGELOG.md"], 0.3)  # 30 shared commits, but it changes with everything
        self.assertNotIn("x.py", repo_index.cochange([(1, ["x.py", "y.py"])], min_support=2))

    def test_recency_decay_is_optional(self):
        commits = [(0, ["a.py", "old.py"])] * 3 + [(400 * 86400, ["a.py", "new.py"])] * 3
        flat = dict((o, s) for o, s, _ in repo_index.cochange(commits, min_support=2)["a.py"])
        decayed = dict((o, s) for o, s, _ in repo_index.cochange(commits, min_support=2, half_life_days=90)["a.py"])
        self.assertEqual(flat["old.py"], flat["new.py"])
        self.assertGreater(decayed["new.py"], decayed["old.py"])

    def test_bulk_commits_and_unknown_paths_are_ignored(self):
        raw = log(["a.py", "b.py", "secret.env"], [f"f{n}.py" for n in range(50)] + ["a.py", "b.py"])
        commits = repo_index.parse_git_log(raw, {"a.py", "b.py"} | {f"f{n}.py" for n in range(50)}, max_commit_files=30)
        self.assertEqual(commits, [(1700000000, ["a.py", "b.py"])])

    def test_history_boosts_a_seed_partner_with_a_visible_reason(self):
        history = log(*[["sqlglot/planner.py", "sqlglot/errors.py"]] * 4)
        index = build(SQL, history=history)
        result = retrieval.retrieve("QueryPlanner is wrong", index, retrieval.configure("full"))
        errors = next(row for row in result["ranked"] if row["path"] == "sqlglot/errors.py")
        self.assertEqual([e["source"] for e in errors["evidence"]], ["git"])
        self.assertIn("frequently co-changed with sqlglot/planner.py", errors["evidence"][0]["reason"])
        self.assertEqual(result["ranked"][0]["path"], "sqlglot/planner.py")  # history never outranks primary evidence

    def test_unavailable_or_shallow_history_degrades_to_no_signal(self):
        for history in (None, "", log(["sqlglot/planner.py", "sqlglot/errors.py"])):
            index = build(SQL, history=history)
            self.assertEqual(index.partners, {})
            self.assertEqual(ranked("QueryPlanner is wrong", index)[0], "sqlglot/planner.py")

    def test_cochange_statistics_share_one_population_and_name_their_denominators(self):
        commits = [(n, ["a.py", "b.py"]) for n in range(6)] + [(n, ["a.py", "c.py"]) for n in range(3)] + [(n, ["c.py", "d.py"]) for n in range(2)]
        stats = {}
        jaccard = repo_index.cochange(commits, min_support=2, stats=stats)
        self.assertEqual(stats, {"events": 11, "changes": {"a.py": 9, "b.py": 6, "c.py": 5, "d.py": 2}, "statistic": "jaccard"})
        self.assertEqual(jaccard["a.py"][0], ["b.py", round(6 / 9, 4), 6])  # n(A,B) / (n(A) + n(B) - n(A,B))
        conditional = repo_index.cochange(commits, min_support=2, statistic="conditional")
        self.assertEqual(dict((o, s) for o, s, _ in conditional["a.py"]), {"b.py": round(6 / 9, 4), "c.py": round(3 / 9, 4)})
        self.assertEqual(conditional["b.py"][0][1], 1.0)  # directional: every event with b.py also has a.py
        shrunk = repo_index.cochange(commits, min_support=2, statistic="conditional", shrinkage=2)
        self.assertEqual(shrunk["b.py"][0][1], round(6 / 8, 4))
        lift = repo_index.cochange(commits, min_support=2, statistic="lift")
        self.assertEqual(lift["a.py"][0][1], round(6 * 11 / (9 * 6), 4))
        self.assertGreater(lift["d.py"][0][1], lift["a.py"][0][1])  # the rare pair scores highest: why lift needs its support floor
        with self.assertRaises(ValueError):
            repo_index.cochange(commits, min_support=2, statistic="pmi")
        history = log(*[["sqlglot/planner.py", "sqlglot/errors.py"]] * 4, ["sqlglot/planner.py", "sqlglot/executor/python.py"])
        index = build(SQL, history=history)
        self.assertEqual(index.history_stats["events"], 5)
        result = retrieval.retrieve("QueryPlanner is wrong", index, retrieval.configure("full"))
        errors = next(row for row in result["ranked"] if row["path"] == "sqlglot/errors.py")
        git = errors["evidence"][0]
        self.assertEqual(git["value"], "jaccard 0.8, 4 commits")  # the packet line is unchanged
        self.assertEqual(git["detail"], "changed in 4 of the 5 eligible events containing sqlglot/planner.py; 5 eligible events in the window")
        self.assertIn("4 of the 5 eligible events", retrieval.render_explain(result))
        self.assertNotIn("eligible events", context_budget.render_packet(retrieval.run("QueryPlanner is wrong", index)["packet"]))
        lifted = build(SQL, history=history, config=retrieval.configure("full", {"git": {"statistic": "lift", "min_support": 4}}))
        self.assertEqual([row[0] for row in lifted.partners["sqlglot/planner.py"]], ["sqlglot/errors.py"])
        self.assertEqual(retrieval.cochange_evidence("x.py", 2, {}), "event counts unavailable for this window")


class PlanAndStatusTests(unittest.TestCase):
    def test_plan_is_deterministic_observational_and_profiles_the_request(self):
        index = build(SQL)
        config = retrieval.configure("full")
        for task, profile, reason in (("Fix sqlglot/planner.py", "exact", "explicit_path"),
                                      ("Fix sqlglot.planner.QueryPlanner.run", "exact", "qualified_name"),
                                      ("the planner regressed again like before", "history", "history_wording"),
                                      ("what does changing QueryPlanner affect downstream", "impact", "impact_wording"),
                                      ("add a unit test for the executor", "tests", "asks_for_tests"),
                                      ("make PythonExecutor faster", "behavior", "identifier"),
                                      ("planner", "behavior", "concept_terms_only")):
            plan = retrieval.retrieve(task, index, config)["plan"]
            self.assertEqual((plan["profile"], plan["policy"]), (profile, "observe"), task)
            self.assertIn(reason, plan["reasons"], task)
        plan = retrieval.retrieve("Fix sqlglot/planner.py", index, config, extra={"worktree": []})["plan"]
        self.assertEqual(plan["families"]["deterministic"], config["retrievers"])
        self.assertEqual(plan["families"]["expansion"], {"graph": True, "git": True})
        self.assertEqual(plan["families"]["assistance"], {"reranker": "off", "reranker_policy": "always", "explorer": "off"})
        self.assertEqual(plan["caps"]["git"], {"candidates": 10, "min_support": 2, "statistic": "jaccard"})
        self.assertEqual(plan, retrieval.retrieve("Fix sqlglot/planner.py", index, config, extra={"worktree": []})["plan"])
        text = retrieval.render_explain(retrieval.run("Fix sqlglot/planner.py", index, config))
        self.assertIn("PLAN               profile exact (explicit_path", text)
        self.assertIn("STATUS             ok (anchored evidence); conditions: none", text)

    def test_status_separates_unavailable_abstention_partial_coverage_and_budget(self):
        config = retrieval.configure("full")
        self.assertEqual(retrieval.retrieve("anything", build({}), config)["status"],
                         {"status": "unavailable", "evidence": "none", "leader": "none", "conditions": []})
        index = build(SQL)
        self.assertEqual(retrieval.retrieve("QueryPlanner", index, config)["status"]["evidence"], "anchored")
        weak = retrieval.retrieve("query plan", index, config)["status"]
        self.assertEqual((weak["status"], weak["evidence"]), ("ok", "lexical"))
        abstained = retrieval.retrieve("zzzz qqqq", index, config)["status"]
        self.assertEqual((abstained["status"], abstained["evidence"]), ("abstained_no_sufficient_local_evidence", "none"))
        partial = retrieval.retrieve("QueryPlanner", build(SQL, path_only=["sqlglot/huge.py"]), config)["status"]
        self.assertEqual(partial["conditions"], [{"condition": "partial_coverage", "unread_files": 1}])
        tight = retrieval.run("QueryPlanner execute PythonExecutor", index, retrieval.configure("full", {"context": {"max_bytes": 300}}))
        self.assertIn("budget_exhausted", [c["condition"] for c in tight["status"]["conditions"]])
        self.assertIn("budget_exhausted", retrieval.render_explain(tight))

    def test_displacement_reports_what_expansion_introduced_and_pushed_out(self):
        history = log(*[["sqlglot/planner.py", "sqlglot/errors.py"]] * 4)
        with_history, without = build(SQL, history=history), build(SQL)
        result = retrieval.retrieve("QueryPlanner is wrong", with_history, retrieval.configure("full"))
        effect = result["trace"]["displacement"]["expansion"]
        self.assertEqual(effect["window"], 10)
        introduced = {item["path"]: item["sources"] for item in effect["introduced"]}
        self.assertEqual(introduced["sqlglot/errors.py"], ["git"])
        self.assertNotIn("rerank", result["trace"]["displacement"])  # no model was asked
        baseline = retrieval.retrieve("QueryPlanner is wrong", without, retrieval.configure("full-graph-git" if "full-graph-git" in retrieval.STRATEGIES else "hybrid"))
        self.assertTrue(set(effect["displaced"]).isdisjoint(p["path"] for p in result["ranked"][:10]))
        self.assertIn("EXPANSION EFFECT", retrieval.render_explain(retrieval.run("QueryPlanner is wrong", with_history), verbose=True))
        self.assertTrue(baseline["ranked"])


class ContextBudgetTests(unittest.TestCase):
    def packet(self, files, task, **limits):
        index = build(files)
        config = retrieval.configure("full", {"context": limits})
        return retrieval.run(task, index, config)["packet"], index

    def test_large_file_yields_the_function_neighborhood_not_the_file(self):
        big = "\n".join(f"def filler_{n}():\n    return {n}\n" for n in range(1500))
        big += "\ndef execute_table(table):\n    # unsupported tables raise\n    return table\n"
        packet, _ = self.packet({"big.py": big, "other.py": "x = 1\n"}, "execute_table fails", max_bytes=4000)
        item = packet["files"][0]
        self.assertEqual(item["path"], "big.py")
        self.assertIn("def execute_table", item["excerpts"][0]["content"])
        self.assertLess(packet["bytes"], 1500)
        self.assertEqual(item["symbols"], ["execute_table"])

    def test_budget_is_never_exceeded_and_every_kept_file_has_an_excerpt(self):
        files = {f"mod{n}.py": f"def handler_{n}(request):\n" + "    value = compute(request)\n" * 60 for n in range(30)}
        files.update({f"other{n}.py": f"unrelated_{n} = {n}\n" for n in range(60)})  # a term in every file carries no signal
        for limit in (600, 2000, 20000):
            packet, _ = self.packet(files, "handler request compute", max_bytes=limit, max_files=10)
            self.assertLessEqual(packet["bytes"], limit)
            self.assertEqual(packet["bytes"], len(context_budget.render_packet(packet).encode()))
            self.assertLessEqual(len(packet["files"]), 10)
            self.assertTrue(packet["files"] and all(item["excerpts"] for item in packet["files"]))
        self.assertEqual(len(packet["files"]), 10)
        self.assertTrue(any(d["reason"] == "file limit" for d in packet["dropped"]))

    def test_token_and_file_limits_apply(self):
        files = {f"mod{n}.py": "def handler():\n    return compute()\n" for n in range(9)}
        files.update({f"other{n}.py": f"unrelated_{n} = {n}\n" for n in range(20)})
        packet, _ = self.packet(files, "handler compute", max_tokens=200, max_files=3)
        self.assertLessEqual(packet["tokens"], 200)
        self.assertTrue(0 < len(packet["files"]) <= 3)

    def test_tests_may_not_crowd_out_implementation_but_never_leave_room_unused(self):
        index = build({f"tests/test_pay{n}.py": f"def test_payment_{n}():\n    assert charge_payment()\n" for n in range(5)} |
                      {f"api/route{n}/handler.py": f"import billing.payment\nROUTE = {n}\n" for n in range(3)} |
                      {"billing/payment.py": "def charge_payment():\n    return True\n"})
        config = retrieval.configure("full", {"context": {"max_files": 6}})
        rows = [{"path": path, "rank": rank, "score": 1.0 / rank, "kind": index.kinds[path],
                 "evidence": [{"file": path, "rank": rank, "score": 1.0, "source": "bm25", "reason": "lexical relevance (BM25)", "value": "payment"}]}
                for rank, path in enumerate(["billing/payment.py", *[f"tests/test_pay{n}.py" for n in range(5)],
                                             *[f"api/route{n}/handler.py" for n in range(3)]], 1)]
        query = retrieval.analyze_query("charge_payment double charges")
        packet = context_budget.build_packet(rows, index, query, config)
        paths = [item["path"] for item in packet["files"]]
        self.assertEqual(sum(p.startswith("tests/") for p in paths), 3)  # ceil(6 * max_test_share)
        self.assertEqual(sum(p.startswith("api/") for p in paths), 2)  # lower-ranked implementation takes the room
        self.assertIn({"path": "tests/test_pay3.py", "reason": "diversity: test share reached"}, packet["dropped"])
        self.assertIn({"path": "api/route2/handler.py", "reason": "file limit"}, packet["dropped"])
        packet = context_budget.build_packet(rows[:6], index, query, config)
        self.assertEqual(len(packet["files"]), 6)  # nothing else wants the room, so the held tests take it back
        asked = retrieval.analyze_query("add a test for charge_payment")
        self.assertEqual(sum(i["path"].startswith("tests/") for i in context_budget.build_packet(rows, index, asked, config)["files"]), 5)

    def test_byte_identical_copies_yield_to_distinct_files_when_room_is_short(self):
        source = "def parse_git_log(raw):\n    return raw.split()\n"
        files = {"repo_index.py": source, "skills/pack/repo_index.py": source, "other.py": "parse_git_log('x')\n"}
        index = build(files)
        rows = [{"path": path, "rank": rank, "score": 1.0 / rank, "kind": "source", "evidence": [
                    {"file": path, "rank": rank, "score": 1.0, "source": "bm25", "reason": "lexical relevance (BM25)", "value": "parse"}]}
                for rank, path in enumerate(["repo_index.py", "skills/pack/repo_index.py", "other.py"], 1)]
        config = retrieval.configure("full", {"context": {"max_files": 2}})
        packet = context_budget.build_packet(rows, index, retrieval.analyze_query("parse_git_log drops commits"), config)
        self.assertEqual([item["path"] for item in packet["files"]], ["repo_index.py", "other.py"])
        self.assertIn({"path": "skills/pack/repo_index.py", "reason": "diversity: same content as repo_index.py"}, packet["dropped"])
        packet, _ = self.packet(files, "parse_git_log drops commits", max_files=3)
        self.assertEqual(len(packet["files"]), 3)  # with room to spare the copy is still shown

    def test_packet_explains_selection_and_relationships(self):
        packet, _ = self.packet(SQL, "Fix sqlglot.executor so execute() handles unsupported tables")
        text = context_budget.render_packet(packet)
        for expected in ("REPOSITORY CONTEXT", "Task signals:", "Why selected:", "Relevant symbols:\n- execute",
                         "Relationships:", "tested by tests/test_executor.py", "Relevant excerpt (lines"):
            self.assertIn(expected, text)


class ExplorerTests(unittest.TestCase):
    def setUp(self):
        self.index = build(SQL)
        self.config = retrieval.configure("full+explorer")

    def test_symbol_path_and_relationship_requests_are_resolved_deterministically(self):
        rows = retrieval.resolve_requests([{"type": "symbol", "value": "UnsupportedError"}, {"type": "path", "value": "planner.py"},
                                           {"type": "callers", "value": "QueryPlanner"},
                                           {"type": "neighbors", "value": "sqlglot/executor/__init__.py"}], self.index, self.config)
        found = {row["file"]: row["reason"] for row in rows}
        self.assertIn("sqlglot/errors.py", found)
        self.assertIn("sqlglot/planner.py", found)
        self.assertIn("calls QueryPlanner", found["sqlglot/executor/python.py"])
        self.assertLessEqual(len(rows), self.config["explorer"]["max_new_files"])

    def test_both_contract_spellings_are_accepted_and_bounded(self):
        findings = retrieval.normalize_findings(
            {"confidence": 0.63, "new_symbols": ["QueryPlanner"] * 30, "new_paths": ["sqlglot/planner.py"],
             "follow_relationships": [{"symbol": "execute", "relationship": "callers"}], "stop": False,
             "requests": [{"type": "shell", "value": "rm -rf"}, {"type": "symbol", "value": 7}]}, self.config)
        self.assertEqual(len(findings["requests"]), self.config["explorer"]["max_new_symbols"])
        self.assertTrue(all(r["type"] in retrieval.REQUEST_TYPES for r in findings["requests"]))
        self.assertTrue(retrieval.normalize_findings({"status": "sufficient"}, self.config)["stop"])
        self.assertTrue(retrieval.normalize_findings({"confidence": 0.87}, self.config)["stop"])
        self.assertTrue(retrieval.normalize_findings("not a dict", self.config)["stop"])

    def test_iteration_limit_and_stop_condition(self):
        calls = []

        def greedy(view):
            calls.append(len(view["files"]))
            return {"status": "expand", "confidence": 0.1, "requests": [{"type": "symbol", "value": "UnsupportedError"}]}

        result = retrieval.run("planner is slow", self.index, self.config, explorer=greedy)
        self.assertEqual(len(calls), self.config["explorer"]["max_iterations"])
        self.assertIn("sqlglot/errors.py", [row["path"] for row in result["ranked"]])
        self.assertIn("sqlglot/errors.py", result["exploration"][0]["added"])
        stopped = retrieval.run("planner is slow", self.index, self.config,
                                explorer=lambda view: {"status": "sufficient", "confidence": 0.9, "requests": [{"type": "symbol", "value": "UnsupportedError"}]})
        self.assertEqual(len(stopped["exploration"]), 1)
        self.assertNotIn("sqlglot/errors.py", [row["path"] for row in stopped["ranked"]])

    def test_disabled_explorer_is_never_called_and_default_needs_no_model(self):
        def forbidden(view):
            raise AssertionError("explorer must not run")

        retrieval.run("planner is slow", self.index, retrieval.configure("full"), explorer=forbidden)
        result = retrieval.run("execute() returns nothing", self.index, self.config)
        self.assertTrue(result["exploration"])
        self.assertLessEqual(len(result["exploration"]), self.config["explorer"]["max_iterations"])

    def test_unknown_target_returns_nothing(self):
        rows = retrieval.resolve_requests([{"type": "path", "value": ".env"}, {"type": "symbol", "value": "DATABASE_PASSWORD"},
                                           {"type": "neighbors", "value": ".env"}], self.index, self.config)
        self.assertEqual(rows, [])


class IncrementalIndexTests(unittest.TestCase):
    def test_only_changed_files_are_reindexed(self):
        class Store(dict):
            def get(self, kind, key):
                return dict.get(self, repr((kind, key)))

            def put(self, kind, key, value):
                self[repr((kind, key))] = value

        store, stats = Store(), {}
        hashes = {path: hashlib.sha256(text.encode()).hexdigest() for path, text in SQL.items()}
        repo_index.load_records(SQL, hashes, store, stats)
        self.assertEqual((stats["record_hits"], stats["record_misses"]), (0, len(SQL)))
        changed = dict(SQL, **{"sqlglot/errors.py": "class UnsupportedError(Exception):\n    code = 1\n"})
        hashes["sqlglot/errors.py"] = hashlib.sha256(changed["sqlglot/errors.py"].encode()).hexdigest()
        repo_index.load_records(changed, hashes, store, stats)
        self.assertEqual((stats["record_hits"], stats["record_misses"]), (len(SQL) - 1, 1))
        smaller = {path: text for path, text in changed.items() if path != "sqlglot/errors.py"}
        records = repo_index.load_records(smaller, hashes, store, stats)
        self.assertNotIn("sqlglot/errors.py", records)  # a path outside this call's universe is never read back

    def test_facts_carry_no_scores_and_config_is_centralized(self):
        record = repo_index.file_record("a.py", "def run():\n    return helper()\n")
        self.assertEqual(set(record), {"v", "lang", "len", "lines", "terms", "defs", "imports", "calls", "bases"})
        self.assertEqual(retrieval.configure("full")["rrf_k"], retrieval.DEFAULTS["rrf_k"])
        self.assertEqual(retrieval.configure("full", {"rrf_k": 10})["rrf_k"], 10)
        self.assertFalse(retrieval.configure("hybrid")["graph"]["enabled"])
        with self.assertRaises(ValueError):
            retrieval.configure("embeddings")


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / "evals/retrieval" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BenchmarkMathTests(unittest.TestCase):
    def test_metrics_match_their_documented_definitions(self):
        run = load("run")
        found = {"ranked": ["a", "t1", "b", "c", "t2"], "candidates": 5, "files": ["a", "t1"], "bytes": 400,
                 "excerpt_bytes": {"a": 300, "t1": 100}, "ms": 1.0}
        row = run._score(found, ["t1", "t2", "missing"])
        self.assertEqual([row[f"R@{k}"] for k in run.KS], [0, 1 / 3, 2 / 3, 2 / 3, 2 / 3, 2 / 3])  # k = 1, 3, 5, 8, 10, 20
        self.assertEqual(row["MRR"], 1 / 2)
        self.assertAlmostEqual(row["MAP"], (1 / 2 + 2 / 5 + 0) / 3)
        self.assertEqual((row["density"], row["ctx_recall"], row["tokens"]), (0.25, 1 / 3, 100))
        self.assertEqual(run.parse_overrides(["graph.max_hops=2", "rrf_k=30"]), {"graph": {"max_hops": 2}, "rrf_k": 30})

    def test_split_depends_only_on_the_task_id(self):
        mine = load("mine")
        self.assertEqual(mine.split_of("sqlglot-1a782c55a8"), mine.split_of("sqlglot-1a782c55a8"))
        counts = {name: 0 for name in ("train", "validation", "test")}
        for number in range(2000):
            counts[mine.split_of(f"repo-{number}")] += 1
        self.assertTrue(1100 < counts["train"] < 1300 and 330 < counts["validation"] < 470 and 330 < counts["test"] < 470)
        self.assertTrue(mine.is_test("tests/unit/test_x.py") and mine.is_test("src/foo.spec.ts") and not mine.is_test("src/contest.py"))


if __name__ == "__main__":
    unittest.main()
