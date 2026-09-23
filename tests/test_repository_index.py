"""Deep repository index: builds across batches, incremental refresh, admission, forged state, runtime integration, CLI."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import context
import repo_builder
import repo_store
import retrieval

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "repository_intelligence.py"


def git(project, *args):
    # No detached auto-maintenance after a commit: it created and removed .git/objects/maintenance.lock while a test
    # was copying the repository (seen on the macOS runner), and the copy failed on the vanished file.
    return subprocess.run(["git", "-C", str(project), "-c", "user.email=t@example.com", "-c", "user.name=t", "-c", "commit.gpgsign=false",
                           "-c", "gc.auto=0", "-c", "maintenance.auto=false", *args],
                          check=True, capture_output=True, text=True).stdout


class IndexCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.project)], check=True)
        self.scrub = context._scrubber(context.find_pack(str(ROOT)))
        self.write("pkg/__init__.py", "")
        self.write("pkg/core.py", "def validate_token(token):\n    return bool(token)\n\n\nclass Session:\n    def open(self):\n        return validate_token('x')\n")
        self.write("pkg/api.py", "from pkg.core import validate_token\n\n\ndef login(token):\n    return validate_token(token)\n")
        self.write("tests/test_api.py", "from pkg.api import login\n\n\ndef test_login():\n    assert login('t')\n")
        self.write("README.md", "# Demo\nRun tests with python3 -m unittest\n")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "-m", "initial")

    def write(self, relative, text):
        target = self.project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target

    def directory(self, identity=None):
        return repo_store.state_directory(self.project, identity)

    def build(self, mode="build", identity=None, resume=False, **config):
        with repo_store.IndexStore(self.directory(identity), create=mode == "build") as store:
            return repo_builder.Builder(self.project, store, self.scrub, config).run(mode=mode, resume=resume)

    def store(self, identity=None, readonly=True):
        return repo_store.IndexStore(self.directory(identity), readonly=readonly)

    def snapshot(self, identity=None):
        """Everything semantic the index holds; volatile metadata (timestamps, generation numbers, signatures) left out."""
        with self.store(identity) as store:
            rows = store.file_rows(with_record=True)
            files = {p: (r["sha256"], r["status"], r["record"]) for p, r in rows.items()}
            symbols = {(s["id"], s["path"], s["qualname"], s["kind"], s["line"], s["end_line"], s["fingerprint"]) for s in store.symbols(limit=10000)}
            edges = {(e["source"], e["target"], e["kind"], e["method"], e["status"]) for p in rows for e in store.edges_of(p, limit=10000)}
            return files, symbols, edges, store.stored_terms(), store.partners_map(), [c["sha"] for c in store.commits()]

    def select(self, task, **kwargs):
        return context.select_context(self.project, task, pack=ROOT, **kwargs)


class DeepBuildTests(IndexCase):
    def test_build_spans_batches_and_late_paths_stay_discoverable(self):
        for number in range(60):
            self.write(f"services/mod_{number:02d}.py", f"def step_{number:02d}():\n    return {number}\n")
        self.write("zz/late_module.py", "def late_unique_symbol():\n    return 'found at the end of path order'\n")
        report = self.build(batch_size=7)
        self.assertTrue(report["published"])
        self.assertEqual(report["coverage"]["indexed"], 66)
        self.assertGreater(report["counters"]["writes"], 5)
        with self.store() as store:
            self.assertEqual(store.counts()["files"], 66)
            self.assertEqual(store.stored_terms(), store.recount_terms())
            self.assertIn("zz/late_module.py", store.file_rows())
        result = self.select("late_unique_symbol returns the wrong text", map_maintain=True)
        self.assertEqual(result["context"][0]["path"], "zz/late_module.py")
        self.assertEqual(result["repository_intelligence"]["index"]["status"], "used")

    def test_noop_refresh_reads_and_parses_nothing(self):
        first = self.build()
        before = self.snapshot()
        report = self.build("refresh")
        self.assertTrue(report["published"])
        self.assertEqual(report["counters"].get("reads", 0), 0)
        self.assertEqual(report["counters"].get("parses", 0), 0)
        self.assertEqual(report["counters"]["records_reused"], first["coverage"]["indexed"])
        self.assertEqual(report["counters"]["history_reused"], 1)
        self.assertEqual(self.snapshot(), before)

    def test_edit_delete_rename_and_identifier_change(self):
        self.build()
        self.write("pkg/core.py", "def validate_token(token):\n    return token == 'ok'\n\n\nclass Session:\n    def open(self):\n        return validate_token('x')\n")
        report = self.build("refresh")
        self.assertEqual((report["counters"]["reads"], report["counters"]["parses"]), (1, 1))
        with self.store() as store:
            self.assertEqual(store.stored_terms(), store.recount_terms())
            edges = {(e["source"], e["target"], e["kind"]) for e in store.edges_of("pkg/api.py")}
            self.assertIn(("pkg/api.py", "pkg/core.py", "imports"), edges)
        # Rename the definition: the unchanged importer's call edge must retarget, its record untouched.
        self.write("pkg/core.py", "def check_token(token):\n    return token == 'ok'\n")
        self.build("refresh")
        with self.store() as store:
            edges = {(e["source"], e["target"], e["kind"]) for e in store.edges_of("pkg/api.py")}
            self.assertIn(("pkg/api.py", "pkg/core.py", "imports"), edges)  # `from pkg.core import validate_token` still names the module.
            self.assertNotIn(("pkg/api.py", "pkg/core.py", "calls"), edges)  # validate_token is no longer defined there.
        # Git rename with identical content keeps a supported alias to the old identity.
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "-m", "retarget")
        git(self.project, "mv", "pkg/core.py", "pkg/tokens.py")
        git(self.project, "commit", "-q", "-m", "move")
        report = self.build("refresh")
        self.assertEqual(report["counters"]["aliases_added"], 1)
        with self.store() as store:
            self.assertNotIn("pkg/core.py", store.file_rows())
            alias = store.aliases()[0]
            self.assertEqual(alias["status"], "supported")
            self.assertIn("content-fingerprint", alias["method"])
            self.assertEqual(store.stored_terms(), store.recount_terms())
        (self.project / "pkg/tokens.py").unlink()
        report = self.build("refresh")
        self.assertEqual(report["counters"]["swept"], 1)
        with self.store() as store:
            self.assertFalse(store.symbols(path="pkg/tokens.py"))
            self.assertEqual(store.stored_terms(), store.recount_terms())

    def test_incremental_result_equals_a_clean_rebuild(self):
        self.build()
        self.write("pkg/core.py", "def validate_token(token):\n    return token == 'ok'\n")
        self.write("pkg/new_module.py", "from pkg.core import validate_token\n\n\ndef check():\n    return validate_token('ok')\n")
        (self.project / "README.md").unlink()
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "-m", "second")
        self.build("refresh")
        self.build("refresh", verify="strict")
        clean = self.build(identity="clean-copy")
        self.assertTrue(clean["published"])
        self.assertEqual(self.snapshot(), self.snapshot("clean-copy"))

    def test_stable_symbol_ids_across_line_shifts_and_strict_reads_are_counted(self):
        self.build()
        with self.store() as store:
            before = {s["qualname"]: s for s in store.symbols(path="pkg/core.py")}
        self.write("pkg/core.py", "# a comment\n# another\n" + (self.project / "pkg/core.py").read_text())
        report = self.build("refresh", verify="strict")
        self.assertEqual(report["counters"]["reads"], report["coverage"]["indexed"])
        self.assertGreater(report["counters"]["bytes_read"], 0)
        with self.store() as store:
            after = {s["qualname"]: s for s in store.symbols(path="pkg/core.py")}
        for name, row in before.items():
            self.assertEqual(after[name]["id"], row["id"])
            self.assertEqual(after[name]["fingerprint"], row["fingerprint"])
            self.assertEqual(after[name]["line"], row["line"] + 2)

    def test_dirty_staged_untracked_files_and_branch_switch(self):
        self.write("pkg/staged.py", "STAGED = 1\n")
        git(self.project, "add", "pkg/staged.py")
        self.write("pkg/staged.py", "STAGED = 2\nEXTRA = 3\n")  # staged one way, working tree another
        self.write("pkg/untracked.py", "UNTRACKED = True\n")
        report = self.build()
        self.assertEqual(report["snapshot"]["worktree_changes"].get("untracked"), 1)
        self.assertEqual(report["snapshot"]["worktree_changes"].get("staged_added"), 1)
        with self.store() as store:
            self.assertIn("EXTRA", store.file_rows(["pkg/staged.py"], with_record=True)["pkg/staged.py"]["record"]["terms"])
            self.assertIn("pkg/untracked.py", store.file_rows())
        git(self.project, "checkout", "-q", "--orphan", "other")
        git(self.project, "rm", "-rfq", "--cached", ".")
        self.write("pkg/api.py", "def login(token):\n    return token\n")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "-m", "orphan history")
        report = self.build("refresh")
        self.assertIn("rebuilt", report["coverage"]["history"])
        self.assertEqual(report["coverage"]["history"]["commits"], 1)
        git(self.project, "checkout", "-q", "--detach", "HEAD")
        report = self.build("refresh")
        self.assertTrue(report["snapshot"]["detached"])

    def test_missing_git_is_source_only_and_future_refs_never_leak(self):
        head = git(self.project, "rev-parse", "HEAD").strip()
        self.write("pkg/future.py", "def future_only():\n    return 'not yet'\n")
        self.write("pkg/api.py", "from pkg.core import validate_token\nfrom pkg.future import future_only\n\n\ndef login(token):\n    return validate_token(token)\n")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "-m", "future fix touching api and future")
        git(self.project, "branch", "future")
        git(self.project, "checkout", "-q", "--detach", head)
        report = self.build()
        self.assertEqual(report["coverage"]["history"]["commits"], 1)
        with self.store() as store:
            self.assertNotIn("pkg/future.py", store.file_rows())
            self.assertFalse(any("future" in c["subject"] for c in store.commits()))
            self.assertEqual(store.partners_map(), {})
        if shutil.which("rg"):
            shutil.rmtree(self.project / ".git")
            report = self.build(identity="no-git")
            self.assertTrue(report["published"])
            self.assertFalse(report["coverage"]["history"]["available"])
            self.assertIsNone(report["snapshot"]["head"])

    def test_interrupted_build_resumes_and_a_spent_budget_keeps_the_previous_generation(self):
        for number in range(12):
            self.write(f"many/m{number:02d}.py", f"VALUE_{number} = {number}\n")
        calls = []
        original = repo_builder.symbol_rows

        def failing(path, record, text):
            calls.append(path)
            if len(calls) == 5:
                raise OSError("simulated interruption")
            return original(path, record, text)
        with mock.patch.object(repo_builder, "symbol_rows", failing), self.assertRaises(OSError):
            self.build(batch_size=3)
        with self.store() as store:
            self.assertIsNone(store.published())
            self.assertIsNotNone(store.building())
        report = self.build("build", resume=True, batch_size=3)
        self.assertTrue(report["published"])
        self.assertIn("Resuming", " ".join(report["diagnostics"]))
        self.assertGreater(report["counters"]["resumed"], 0)
        with self.store() as store:
            first = store.published()["id"]
            self.assertEqual(store.stored_terms(), store.recount_terms())
        self.write("many/m00.py", "VALUE_0 = 100\n")
        report = self.build("refresh", max_seconds=0)
        self.assertFalse(report["published"])
        self.assertGreater(report["coverage"]["pending"], 0)
        with self.store() as store:
            self.assertEqual(store.published()["id"], first)

    def test_policy_change_recomputes_every_record(self):
        self.build()
        with mock.patch.object(repo_builder, "VERSION", repo_builder.VERSION + 1):
            report = self.build("refresh")
        self.assertIn("policy changed", " ".join(report["diagnostics"]))
        self.assertEqual(report["counters"]["parses"], report["coverage"]["indexed"])

    def test_source_that_changes_during_the_build_is_rechecked(self):
        original = repo_builder.Builder._read
        edited = []

        def racing(self_, relative, remaining):
            result = original(self_, relative, remaining)
            if relative == "pkg/api.py" and not edited:
                edited.append(relative)
                (self.project / "pkg/api.py").write_text("def login(token):\n    return 'edited during build'\n", encoding="utf-8")
            return result
        with mock.patch.object(repo_builder.Builder, "_read", racing):
            report = self.build()
        self.assertEqual(report["counters"]["changed_during_build"], 1)
        with self.store() as store:
            self.assertIn("edited", store.file_rows(["pkg/api.py"], with_record=True)["pkg/api.py"]["record"]["terms"])


class AdmissionAndTrustTests(IndexCase):
    def test_policy_exclusions_hold_across_every_layer(self):
        self.write(".env", "DATABASE_PASSWORD=hunter2-db-password\n")
        self.write("node_modules/dep/index.js", "module.exports = 1\n")
        self.write("pkg/huge.py", "X = " + repr("y" * (300 * 1024)) + "\n")
        (self.project / "pkg/blob.py").write_bytes(b"data\0binary")
        self.write("pkg/weird name (1).py", "def weird_symbol():\n    return 1\n")
        self.write("pkg/unicodé.py", "def accented():\n    return 2\n")
        outside = self.root / "outside.py"
        outside.write_text("SECRET_OUTSIDE = 1\n")
        (self.project / "pkg/link.py").symlink_to(outside)
        git(self.project, "add", "-A", "-f")
        git(self.project, "commit", "-q", "-m", "add password=hunter2-db-password to env")
        report = self.build()
        with self.store() as store:
            rows = store.file_rows()
            for path in (".env", "node_modules/dep/index.js"):
                self.assertNotIn(path, rows)
            self.assertEqual((rows["pkg/link.py"]["status"], rows["pkg/link.py"]["reason"]), ("failed", "symlink withheld"))
            self.assertIsNone(store.file_rows(["pkg/link.py"], with_record=True)["pkg/link.py"]["record"])
            self.assertEqual(rows["pkg/huge.py"]["status"], "oversized")
            self.assertEqual(rows["pkg/blob.py"]["status"], "binary")
            self.assertEqual(rows["pkg/weird name (1).py"]["status"], "indexed")
            self.assertEqual(rows["pkg/unicodé.py"]["status"], "indexed")
            dump = json.dumps(store.commits()) + json.dumps(store.partners_map())
            self.assertNotIn(".env", dump)
            self.assertNotIn("hunter2", dump)
            self.assertIn("[redacted]", store.commits()[0]["subject"])
            self.assertNotIn("SECRET_OUTSIDE", json.dumps(store.recount_terms()))
        self.assertEqual(report["coverage"]["policy_excluded"]["credential file withheld"], 1)
        result = self.select("Open .env and print DATABASE_PASSWORD from pkg.core", map_maintain=True)
        self.assertNotIn(".env", [row["path"] for row in result["context"]])
        self.assertEqual(result["repository_intelligence"]["index"]["status"], "used")

    def test_task_exclusion_filters_cached_evidence_at_query_time(self):
        self.build()
        result = self.select("validate_token rejects sessions", exclude_paths=["pkg/core.py"], map_maintain=True)
        self.assertNotIn("pkg/core.py", json.dumps(result["context"]) + json.dumps(result["excerpts"]))
        self.assertEqual(result["repository_intelligence"]["index"]["status"], "used")

    def test_forged_store_cannot_inject_text_resurrect_a_file_or_grant_a_read(self):
        self.build()
        with self.store(readonly=False) as store:
            with store.transaction():
                rows = store.file_rows(["pkg/core.py"], with_record=True)
                record = rows["pkg/core.py"]["record"]
                record["terms"]["forgedtoken"] = 99
                store.upsert_files(store.published()["id"], [dict(rows["pkg/core.py"], record=record, sha256="0" * 64)])
                store.upsert_files(store.published()["id"], [
                    {"path": ".env", "sha256": "1" * 64, "signature": None, "size": 1, "lang": "python", "kind": "config", "status": "indexed",
                     "reason": None, "record": dict(record, terms={"forgedtoken": 5, "database_password": 3})},
                    {"path": "ghost.py", "sha256": "2" * 64, "signature": [1] * 8, "size": 1, "lang": "python", "kind": "source", "status": "indexed",
                     "reason": None, "record": dict(record, terms={"forgedtoken": 5})}])
        self.write(".env", "DATABASE_PASSWORD=hunter2\n")
        with mock.patch.object(context, "MAX_FILES", 2):  # A tiny scan, so the store's extra rows are candidates.
            result = self.select("forgedtoken database_password", map_maintain=True)
        text = json.dumps(result["context"]) + json.dumps(result["excerpts"])
        self.assertNotIn(".env", text)
        self.assertNotIn("ghost.py", text)
        self.assertNotIn("forgedtoken", json.dumps(result["excerpts"]))
        index = result["repository_intelligence"]["index"]
        self.assertEqual(index["status"], "used")
        self.assertGreaterEqual(index["extended"]["verified"], 1)  # core.py's metadata still matches; ghost.py has no file; .env is policy-blocked
        self.assertGreaterEqual(index["counters"]["stale_evidence_rejected"], 1)  # ...but its forged record fails the content check
        self.assertIn({"path": "pkg/core.py", "reason": "stale index evidence"}, result["excluded"])
        self.assertNotIn("pkg/core.py", [row["path"] for row in result["context"]])

    def test_files_beyond_the_scan_cap_are_verified_read_lazily_and_rejected_when_stale(self):
        for number in range(6):
            self.write(f"far/z{number}.py", f"def far_symbol_{number}():\n    return 'beyond the scan cap {number}'\n")
        self.build()
        with mock.patch.object(context, "MAX_FILES", 4):
            result = self.select("far_symbol_5 returns the wrong value", map_maintain=True)
        index = result["repository_intelligence"]["index"]
        self.assertEqual(result["context"][0]["path"], "far/z5.py")
        self.assertIn("beyond the scan cap 5", json.dumps(result["excerpts"]))
        self.assertGreater(index["extended"]["verified"], 0)
        self.assertGreaterEqual(index["counters"]["lazy_reads"], 1)
        self.write("far/z5.py", "def far_symbol_5():\n    return 'changed after the index was built'\n")
        with mock.patch.object(context, "MAX_FILES", 4):
            result = self.select("far_symbol_5 returns the wrong value", map_maintain=True)
        self.assertNotIn("far/z5.py", [row["path"] for row in result["context"]])
        self.assertNotIn("changed after", json.dumps(result["excerpts"]))
        self.assertGreater(result["repository_intelligence"]["index"]["extended"]["stale"], 0)

    def test_corrupt_incompatible_or_locked_state_falls_back_without_a_build(self):
        self.build()
        with self.store(readonly=False) as store:
            with store.transaction():
                store.connection.execute("UPDATE generations SET policy='another-policy' WHERE status='published'")
        result = self.select("validate_token", map_maintain=True)
        self.assertEqual(result["repository_intelligence"]["index"]["status"], "incompatible")
        self.assertTrue(any("rebuild" in line for line in result["diagnostics"]))
        self.assertEqual(result["context"][0]["path"], "pkg/core.py")
        (self.directory() / repo_store.INDEX_FILE).write_bytes(b"not a database at all")
        result = self.select("validate_token", map_maintain=True)
        self.assertIn(result["repository_intelligence"]["index"]["status"], {"unavailable", "unpublished"})
        self.assertEqual(result["context"][0]["path"], "pkg/core.py")
        shutil.rmtree(self.directory())
        self.build()
        holder = sqlite3.connect(str(self.directory() / repo_store.INDEX_FILE), isolation_level=None)
        holder.execute("PRAGMA locking_mode=EXCLUSIVE")
        holder.execute("BEGIN IMMEDIATE")
        holder.execute("INSERT INTO meta(key, value) VALUES('lock-probe', '1')")
        try:
            with mock.patch.object(repo_store, "BUSY_MS", 100):
                result = self.select("validate_token", map_maintain=True)
        finally:
            holder.execute("ROLLBACK")
            holder.close()
        self.assertEqual(result["repository_intelligence"]["index"]["status"], "unavailable")
        self.assertEqual(result["context"][0]["path"], "pkg/core.py")

    def test_status_dry_run_and_read_only_scopes_never_create_or_write_private_state(self):
        env = dict(os.environ, XDG_CACHE_HOME=os.environ["XDG_CACHE_HOME"])
        for arguments in (["status"], ["build", "--dry-run"]):
            done = subprocess.run([sys.executable, "-B", str(CLI), *arguments, "--project", str(self.project), "--pack", str(ROOT), "--json"],
                                  capture_output=True, text=True, env=env)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertFalse(self.directory().exists())
        result = self.select("validate_token", repository_index="require")
        self.assertFalse(self.directory().exists())
        self.assertTrue(any("Repository index required" in line for line in result["diagnostics"]))
        self.build()
        self.write("pkg/core.py", "def validate_token(token):\n    return False\n")
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.directory().iterdir()}
        for options in ({"task": "Inspect validate_token. Do not edit files.", "map_maintain": True},
                        {"task": "Inspect validate_token", "role": "reviewer", "map_maintain": True},
                        {"task": "Inspect validate_token", "map_preview": True, "map_maintain": True},
                        {"task": "Inspect validate_token", "map_maintain": True, "writable_paths": ["docs/"]},
                        {"task": "Inspect validate_token"}):
            with self.subTest(options=options):
                result = self.select(**options)
                self.assertFalse(result["repository_intelligence"]["index"]["maintenance"]["allowed"])
                self.assertEqual({p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.directory().iterdir()}, before)
        result = self.select("Fix validate_token", role="implementer", map_maintain=True)
        self.assertEqual(result["repository_intelligence"]["index"]["maintenance"]["records_upserted"], 1)
        with self.store() as store:
            self.assertEqual(store.stored_terms(), store.recount_terms())

    def test_worktrees_are_isolated_and_an_identity_maps_workspaces_together(self):
        other = self.root / "other"
        shutil.copytree(self.project, other)
        self.build()
        self.assertNotEqual(repo_store.state_directory(self.project), repo_store.state_directory(other))
        self.assertFalse(repo_store.state_directory(other).exists())
        self.assertEqual(repo_store.state_directory(self.project, "seq-1"), repo_store.state_directory(other, "seq-1"))
        with mock.patch.dict(os.environ, {"AGENT_DISPATCHER_INDEX_ID": "seq-1"}):
            self.assertEqual(context.select_context(other, "validate_token", pack=ROOT)["repository_intelligence"]["index"]["status"], "absent")
            self.build(identity="seq-1")
            self.assertEqual(context.select_context(other, "validate_token", pack=ROOT)["repository_intelligence"]["index"]["status"], "used")

    def test_settings_inside_the_project_are_refused_and_use_off_keeps_old_behavior(self):
        self.build()
        inside = self.write("repository-intelligence.json", json.dumps({"index": {"use": "auto"}}))
        with mock.patch.dict(os.environ, {"AGENT_DISPATCHER_INDEX_CONFIG": str(inside)}):
            result = self.select("validate_token")
        self.assertEqual(result["repository_intelligence"]["index"]["status"], "settings_invalid")
        settings = self.root / "settings.json"
        settings.write_text(json.dumps({"index": {"use": "off"}}))
        with mock.patch.dict(os.environ, {"AGENT_DISPATCHER_INDEX_CONFIG": str(settings)}):
            plain = self.select("validate_token")
        self.assertEqual(plain["repository_intelligence"]["index"]["status"], "off")
        self.assertEqual([row["path"] for row in plain["context"]], [row["path"] for row in self.select("validate_token", repository_index="off")["context"]])


class CommandLineTests(IndexCase):
    def cli(self, *arguments):
        env = dict(os.environ)
        return subprocess.run([sys.executable, "-B", str(CLI), *arguments, "--project", str(self.project), "--pack", str(ROOT)],
                              capture_output=True, text=True, env=env)

    def test_build_refresh_status_explain_export_and_prune(self):
        done = self.cli("build", "--json")
        self.assertEqual(done.returncode, 0, done.stderr)
        report = json.loads(done.stdout)
        self.assertTrue(report["published"])
        self.assertEqual(report["model_calls"], 0)
        done = self.cli("refresh", "--strict", "--json")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["counters"]["reads"], report["coverage"]["indexed"])
        done = self.cli("status", "--json")
        status = json.loads(done.stdout)
        self.assertEqual(status["index"]["status"], "published")
        self.assertEqual(status["index"]["freshness"]["status"], "fresh")
        self.assertTrue(status["read_only"])
        done = self.cli("explain", "validate_token rejects sessions", "--no-llm")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("REPOSITORY INDEX", done.stdout)
        self.assertIn('"status": "used"', done.stdout)
        out = self.root / "export.json"
        done = self.cli("export", "--out", str(out))
        self.assertEqual(done.returncode, 0, done.stderr)
        document = json.loads(out.read_text())
        self.assertEqual(document["document"], "repository-intelligence-export")
        self.assertNotIn("policy", document["snapshot"])
        done = self.cli("prune", "--index")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse((self.directory() / repo_store.INDEX_FILE).exists())
        done = self.cli("refresh", "--json")
        self.assertEqual(done.returncode, 2)
        self.assertIn("No repository index", done.stderr)

    def test_store_helpers_and_provenance_shape(self):
        self.build()
        with self.store() as store:
            row = store.symbols(name="validate_token")[0]
            item = repo_store.provenance(row["id"], "observation", "repo_index", "python-ast", 1, path=row["path"],
                                         symbol=row["qualname"], span=[row["line"], row["end_line"]], fingerprint=row["fingerprint"])
            self.assertEqual(item["kind"], "observation")
            self.assertEqual(item["status"], "current")
            with self.assertRaises(repo_store.StoreError):
                repo_store.provenance("x", "guess", "p", "m", 1)
            self.assertTrue(store.integrity())
            self.assertGreater(store.disk_bytes(), 0)
            self.assertTrue(store.search_symbols("validate"))
            self.assertEqual(store.history_of("pkg/core.py")[0]["touched"], 5)
        engine = retrieval.configure("full+deep")
        self.assertIn("experience", engine["retrievers"])
        self.assertIn("inference", engine["retrievers"])
        self.assertNotIn("experience", retrieval.configure("full")["retrievers"])


if __name__ == "__main__":
    unittest.main()
