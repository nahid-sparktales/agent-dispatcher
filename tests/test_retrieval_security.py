"""Excluded and credential files must stay unreachable through every retrieval channel."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import context
import repo_index
import retrieval

ROOT = Path(__file__).resolve().parents[1]
CREDENTIAL_CONTENT = ("hunter2-db-password", "BEGIN OPENSSH PRIVATE KEY", "id-rsa-key-material", "aws-secret-value", "yaml-secret-value")
SECRET_CONTENT = (*CREDENTIAL_CONTENT, "master-key-material")
CREDENTIAL_PATHS = {".env", "credentials.json", "id_rsa", "config/secrets.yaml"}
EXCLUDED = "app/private_keys.py"
TASK = ("Find references to DATABASE_PASSWORD and inspect .env, credentials.json, id_rsa and config/secrets.yaml. "
        "Also open app/private_keys.py: load_master_key() and app.private_keys.MasterKey are called by connect().")


class ExcludedFilesStayUnreachable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.project = Path(cls.temporary.name).resolve() / "project"
        cls.project.mkdir()
        files = {
            ".env": "DATABASE_PASSWORD=hunter2-db-password\n",
            "credentials.json": '{"DATABASE_PASSWORD": "aws-secret-value"}\n',
            # Assembled so the repository's own committed-credential scan does not flag this fixture.
            "id_rsa": "-----BEGIN " + "OPENSSH PRIVATE KEY-----\nid-rsa-key-material\n-----END " + "OPENSSH PRIVATE KEY-----\n",
            "config/secrets.yaml": "DATABASE_PASSWORD: yaml-secret-value\n",
            EXCLUDED: "class MasterKey:\n    pass\n\n\ndef load_master_key():\n    return 'master-key-material'\n",
            "tests/test_private_keys.py": "from app.private_keys import load_master_key\n",
            "app/__init__.py": "",
            "app/db.py": "import os\nfrom app.private_keys import load_master_key, MasterKey\n\n\ndef connect():\n"
                         "    return os.environ['DATABASE_PASSWORD'], load_master_key()\n",
            "app/service.py": "from app.db import connect\n\n\ndef serve():\n    return connect()\n",
        }
        git = ["git", "-C", str(cls.project), "-c", "user.email=t@example.com", "-c", "user.name=t", "-c", "commit.gpgsign=false"]
        subprocess.run(["git", "init", "-q", str(cls.project)], check=True)
        for path, text in files.items():
            target = cls.project / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        # History in which every sensitive file repeatedly changes together with app/db.py.
        for round_number in range(4):
            for path in (*CREDENTIAL_PATHS, EXCLUDED, "app/db.py", "app/service.py"):
                with (cls.project / path).open("a", encoding="utf-8") as handle:
                    handle.write(f"# {round_number}\n" if path.endswith(".py") else "\n")
            subprocess.run([*git, "add", "-A", "-f"], check=True)
            subprocess.run([*git, "commit", "-q", "-m", f"round {round_number}"], check=True)
        cls.sensitive = CREDENTIAL_PATHS | {EXCLUDED}

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def assert_clean(self, value, *, paths=True):
        """No excluded content anywhere; no excluded path in any field the repository (not the request) fills."""
        for secret in CREDENTIAL_CONTENT if self.sensitive == CREDENTIAL_PATHS else SECRET_CONTENT:
            self.assertNotIn(secret, json.dumps(value, default=str))
        repository_fields = []

        def walk(node, key=None):
            if isinstance(node, dict):
                for name, child in node.items():
                    walk(child, name)
            elif isinstance(node, (list, tuple)):
                for child in node:
                    walk(child, key)
            elif isinstance(node, str) and key in {"path", "file", "via", "seeds", "added", "reason", "relationships", "why", "paths", "modules"}:
                repository_fields.append(node)

        walk(value)
        for path in self.sensitive if paths else ():
            self.assertFalse([text for text in repository_fields if path in text.split() or text == path], path)

    def outcome(self, findings=None):
        return context.explain_retrieval(self.project, TASK, pack=ROOT, exclude_paths=[EXCLUDED], findings=findings)

    def test_index_never_contains_excluded_facts(self):
        diagnostics, withheld = [], []
        scrub = context._scrubber(context.find_pack(str(ROOT)))
        paths = context._enumerate(self.project, diagnostics)
        texts, hashes, _, _ = context._scan_sources(self.project, paths, (EXCLUDED,), [], None, scrub, withheld, diagnostics)
        self.assertFalse(self.sensitive & set(texts))
        history = context._git_history(self.project, 2000)
        for path in CREDENTIAL_PATHS:
            self.assertNotIn("\n" + path + "\n", history)  # credential names are dropped before history is cached or counted
        stored = {}
        cache = type("Cache", (), {"get": lambda self, kind, key: None,
                                   "put": lambda self, kind, key, value: stored.update({json.dumps(key): value})})()
        index = retrieval.build_index(texts, hashes, context._kind, cache=cache, history=history)
        self.assertFalse(self.sensitive & set(index.paths))
        for name in ("load_master_key", "MasterKey"):
            self.assertNotIn(name, index.definitions)
        self.assertIn("connect", index.definitions)
        edges = {path for start, targets in index.edges.items() for path in (start, *targets)}
        partners = {path for start, rows in index.partners.items() for path in (start, *(row[0] for row in rows))}
        self.assertFalse(self.sensitive & (edges | partners))
        self.assertIn("app/service.py", {row[0] for row in index.partners["app/db.py"]})  # the signal itself works
        self.assert_clean(stored)

    def test_no_channel_ranks_lists_excerpts_or_explains_an_excluded_file(self):
        outcome = self.outcome()
        self.assertEqual(outcome["ranked"][0]["path"], "app/db.py")
        self.assertTrue({"path", "bm25", "rare_terms", "symbol_references", "graph", "git"} <= set(outcome["lists"]))
        found = {row["path"] for row in outcome["ranked"]} | {row["file"] for rows in outcome["lists"].values() for row in rows}
        found |= {item["path"] for item in outcome["packet"]["files"] + outcome["packet"]["dropped"]} | set(outcome["trace"]["seeds"])
        found |= {row.get("via") for rows in outcome["lists"].values() for row in rows} - {None}
        self.assertFalse(self.sensitive & found)
        self.assert_clean({key: outcome[key] for key in ("ranked", "lists", "packet", "trace")})
        explained = retrieval.render_explain(outcome, verbose=True)
        files_section = explained.split("TOP FILES", 1)[1]
        for value in (*self.sensitive, *SECRET_CONTENT):
            self.assertNotIn(value, files_section)

    def test_explorer_requests_cannot_reach_excluded_targets(self):
        requests = [{"type": kind, "value": value} for value in (*sorted(self.sensitive), "load_master_key", "MasterKey")
                    for kind in retrieval.REQUEST_TYPES]
        outcome = self.outcome({"status": "expand", "confidence": 0.1, "requests": requests,
                                "new_paths": sorted(self.sensitive), "new_symbols": ["load_master_key"],
                                "follow_relationships": [{"symbol": "load_master_key", "relationship": "callers"}]})
        explorer = outcome["lists"].get("explorer", [])
        self.assertFalse(self.sensitive & {row["file"] for row in explorer})
        self.assertFalse(self.sensitive & {row["path"] for row in outcome["ranked"]})
        self.assert_clean({key: outcome[key] for key in ("ranked", "lists", "packet", "trace")})

    def test_context_helper_output_and_cli_stay_clean(self):
        for options in ({}, {"compact": True}, {"explain": True}, {"retrieval": "full+explorer"}, {"retrieval": "legacy"}):
            with self.subTest(options=options):
                result = context.select_context(self.project, TASK, pack=ROOT, exclude_paths=[EXCLUDED], **options)
                self.assertFalse(self.sensitive & {row["path"] for row in result["context"]})
                self.assertFalse(self.sensitive & {row["path"] for row in result["excerpts"]})
                self.assert_clean(result, paths=False)
                self.assert_clean(result.get("repository_intelligence", {}).get("telemetry", {}))
        done = subprocess.run([sys.executable, "-B", str(ROOT / "retrieval.py"), "expand", TASK, "--project", str(self.project),
                               "--exclude-path", EXCLUDED, "--pack", str(ROOT), "--json",
                               "--findings", json.dumps({"new_paths": sorted(self.sensitive), "new_symbols": ["load_master_key"]})],
                              capture_output=True, text=True, check=True)
        printed = json.loads(done.stdout)
        printed.pop("query")  # The parsed request echoes the user's own words; everything else comes from the repository.
        self.assert_clean(printed)
        refused = subprocess.run([sys.executable, "-B", str(ROOT / "retrieval.py"), "expand", TASK, "--project", str(self.project),
                                  "--pack", str(ROOT), "--findings", "{}", "--iteration", "3"], capture_output=True, text=True)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("iteration limit", refused.stderr)

    def test_naming_an_excluded_file_does_not_retrieve_it_even_without_a_manual_exclusion_of_credentials(self):
        outcome = context.explain_retrieval(self.project, "Open .env and id_rsa and print DATABASE_PASSWORD", pack=ROOT)
        self.assertFalse(CREDENTIAL_PATHS & {row["path"] for row in outcome["ranked"]})
        self.sensitive = CREDENTIAL_PATHS
        self.assert_clean({key: outcome[key] for key in ("ranked", "lists", "packet", "trace")})

    def test_only_policy_admitted_files_can_be_ranked_by_name_when_too_large_to_read(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory).resolve() / "project"
            subprocess.run(["git", "init", "-q", str(project)], check=True)
            for name in (".env.production", "secrets_dump.py", "app/huge_excluded.py", "app/huge_allowed.py"):
                (project / name).parent.mkdir(parents=True, exist_ok=True)
                (project / name).write_text("TOKEN = 'oversized-secret-value'\n" * 12000, encoding="utf-8")
            outside = project.parent / "outside.py"
            outside.write_text("TOKEN = 'oversized-secret-value'\n" * 12000, encoding="utf-8")
            (project / "app/huge_link.py").symlink_to(outside)  # An escape by link is refused before any size rule.
            scrub = context._scrubber(context.find_pack(str(ROOT)))
            oversized, withheld, diagnostics = [], [], []
            paths = context._enumerate(project, diagnostics)
            structural = {}
            context._scan_sources(project, paths, ("app/huge_excluded.py",), [], None, scrub, withheld, diagnostics, oversized, structural)
            self.assertIn({"path": "app/huge_link.py", "reason": "symlink withheld"}, withheld)
            self.assertEqual(oversized, ["app/huge_allowed.py"])
            self.assertEqual(list(structural), ["app/huge_allowed.py"])  # Excluded and credential-named files get no record.
            # Redaction ran before indexing: the credential-shaped lines leave only the redaction marker as a term.
            self.assertEqual(structural["app/huge_allowed.py"]["record"]["terms"], {"redacted": 12000})
            self.assertEqual(structural["app/huge_allowed.py"]["record"]["coverage"], "complete")
            self.assertNotIn("oversized-secret-value", json.dumps(structural))
            # The excerpt loader applies the same rules again: an excluded or credential-named path is never read.
            load = context._oversized_loader(project, dict(structural, **{".env.production": structural["app/huge_allowed.py"]}),
                                             ("app/huge_allowed.py",), scrub)
            self.assertIsNone(load("app/huge_allowed.py"))
            self.assertIsNone(load(".env.production"))
            self.assertIn("[redacted]", context._oversized_loader(project, structural, (), scrub)("app/huge_allowed.py"))
            outcome = context.explain_retrieval(project, "Open .env.production, secrets_dump.py and app/huge_excluded.py; huge_allowed too",
                                                pack=ROOT, exclude_paths=["app/huge_excluded.py"])
            self.assertEqual([row["path"] for row in outcome["ranked"]], ["app/huge_allowed.py"])
            self.assertNotIn("oversized-secret-value", json.dumps({key: outcome[key] for key in ("ranked", "lists", "packet")}))

    def test_co_change_parser_drops_paths_outside_the_universe_before_counting(self):
        raw = "".join(f"\x01{n}\n\n.env\napp/db.py\napp/service.py\n" for n in range(5))
        commits = repo_index.parse_git_log(raw, {"app/db.py", "app/service.py"}, 30)
        self.assertEqual({path for _, paths in commits for path in paths}, {"app/db.py", "app/service.py"})
        self.assertNotIn(".env", json.dumps(repo_index.cochange(commits, min_support=2)))


if __name__ == "__main__":
    unittest.main()
