"""Task experience: recording from real receipts, outcomes that never count as success, corrections, forgetting, equivalence."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import context
import experience
import repo_builder
import repo_store
import retrieval
import verification

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "repository_intelligence.py"


def build(files):
    hashes = {path: hashlib.sha256(text.encode()).hexdigest() for path, text in files.items()}
    return retrieval.build_index(files, hashes, context._kind)


FILES = {"app/auth.py": "def validate_login(session):\n    return session.ok\n", "app/tokens.py": "def refresh_token(token):\n    return token\n",
         "app/billing.py": "def charge(amount):\n    return amount\n", "tests/test_auth.py": "from app.auth import validate_login\n"}


def inspection(outcome, freshness="current"):
    return {"observations": [{"provenance": "observed_execution", "outcome": outcome, "freshness": freshness,
                              "execution": {"kind": "tests", "runner": "unittest", "test_counts": {"run": 3, "skipped": 0, "failed": 0, "errors": 0, "runner_reported_pass": True}}}]}


class OutcomeTests(unittest.TestCase):
    def test_only_current_passing_checks_or_acceptance_count_as_success(self):
        cases = {("tests_passed", "current"): "checked_success", ("tests_passed", "stale"): "stale_checks",
                 ("tests_passed", "unknown"): "stale_checks", ("zero_tests", "current"): "zero_tests",
                 ("command_succeeded", "current"): "exit_code_only", ("executed_unknown", "current"): "exit_code_only",
                 ("tests_failed", "current"): "failed_checks", ("timeout", "current"): "infrastructure_error"}
        for (outcome, freshness), expected in cases.items():
            self.assertEqual(experience.outcome_from_receipt(inspection(outcome, freshness))[0], expected, (outcome, freshness))
        self.assertEqual(experience.outcome_from_receipt({"observations": [{"provenance": "reported_note", "outcome": "not_run"}]})[0], "insufficient_evidence")
        self.assertFalse({"exit_code_only", "zero_tests", "stale_checks", "failed_checks", "unresolved"} & set(experience.ELIGIBLE))


class EventTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / "project"
        for path, text in FILES.items():
            (self.project / path).parent.mkdir(parents=True, exist_ok=True)
            (self.project / path).write_text(text)
        self.scrub = context._scrubber(context.find_pack(str(ROOT)))
        self.directory = self.root / "state"
        self.directory.mkdir(mode=0o700)

    def store(self):
        return repo_store.ExperienceStore(self.directory, create=True)

    def event(self, task_id="t1", task="validate_login rejects a valid session token", edited=("app/auth.py",), outcome=None, checks=None):
        return experience.build_event(project=self.project, task_id=task_id, task=task, scrub=self.scrub, edited=edited, outcome=outcome, checks=checks)

    def test_events_are_bounded_sanitized_and_deduplicated(self):
        event = self.event(task="validate_login rejects token password=hunter2secret9 for user", checks=inspection("tests_passed"))
        self.assertEqual(event["outcome"], "checked_success")
        self.assertEqual(event["edited"][0]["association"], "changed_in_checked_task")
        self.assertNotIn("hunter2secret9", json.dumps(event))
        self.assertNotIn("password", event["task"]["terms"])
        self.assertEqual(event["edited"][0]["sha256"], hashlib.sha256(FILES["app/auth.py"].encode()).hexdigest())
        with self.store() as store:
            first = experience.record(store, event)
            second = experience.record(store, self.event(task="validate_login rejects token password=hunter2secret9 for user", checks=inspection("tests_passed")))
            self.assertTrue(first["stored"])
            self.assertFalse(second["stored"])
            self.assertEqual(store.counts()["events"], {"current": 1})
            with self.assertRaises(experience.ExperienceError):
                self.event(outcome="proven_bug_location")
            raw = (self.directory / repo_store.EXPERIENCE_FILE).read_bytes()
            self.assertNotIn(b"hunter2secret9", raw)
            self.assertEqual(oct((self.directory / repo_store.EXPERIENCE_FILE).stat().st_mode & 0o777), "0o600")

    def test_corrections_forgetting_and_retention_recompute_aggregates(self):
        with self.store() as store:
            experience.record(store, self.event(outcome="accepted", edited=("app/auth.py", "app/billing.py")))
            events = store.events()
            prepared = experience.prepare(events, store.corrections())
            self.assertEqual({row["path"] for row in prepared[0]["files"]}, {"app/auth.py", "app/billing.py"})
            experience.correct(store, events[0]["id"], "app/billing.py", "irrelevant", "unrelated drive-by edit", self.scrub)
            experience.correct(store, events[0]["id"], "app/tokens.py", "relevant", "the real cause", self.scrub)
            prepared = experience.prepare(store.events(), store.corrections())
            self.assertEqual({row["path"]: row["association"] for row in prepared[0]["files"]},
                             {"app/auth.py": "changed_in_accepted_task", "app/tokens.py": "user_correction"})
            with self.assertRaises(repo_store.StoreError):
                experience.correct(store, "missing-event", "app/x.py", "relevant", "", self.scrub)
            self.assertEqual(experience.forget(store, event_id=events[0]["id"])["removed"], 1)
            self.assertEqual(store.events(), [])
            self.assertEqual(store.corrections(), [])
            with mock.patch.object(repo_store, "MAX_EVENTS", 2):
                for number in range(3):
                    experience.record(store, self.event(task_id=f"task-{number}", outcome="accepted"))
            self.assertEqual(store.counts()["events"], {"current": 2, "retired": 1})
            self.assertEqual(experience.forget(store, everything=True)["removed"], 3)

    def test_scoring_is_bounded_explainable_and_ignores_unsupported_outcomes(self):
        index = build(FILES)
        tuning = retrieval.DEFAULTS["experience"]
        with self.store() as store:
            for number in range(3):
                experience.record(store, self.event(task_id=f"good-{number}", task=f"validate_login rejects a valid session {number}", outcome="accepted"))
            experience.record(store, self.event(task_id="bad", task="validate_login rejects a valid session", edited=("app/billing.py",), outcome="failed_checks"))
            experience.record(store, self.event(task_id="exit", task="validate_login rejects a valid session", edited=("app/tokens.py",), outcome="exit_code_only"))
            (self.project / "app/deleted.py").write_text("def gone():\n    return None\n")
            experience.record(store, self.event(task_id="gone", task="validate_login rejects a valid session", edited=("app/deleted.py",), outcome="accepted"))
            (self.project / "app/deleted.py").unlink()
            experience.record(store, self.event(task_id="far", task="charge the customer twice on retry", edited=("app/billing.py",), outcome="accepted"))
            events, corrections = store.events(), store.corrections()
        self.assertEqual(experience.attach(index, events, corrections), 5)
        query = retrieval.analyze_query("validate_login rejects a valid session")
        scores, reasons = experience.scores(query, index, index.experience, tuning)
        self.assertEqual(set(scores), {"app/auth.py"})  # failed/exit-code events and the deleted file contribute nothing
        self.assertIn("3 earlier tasks", reasons["app/auth.py"][0])
        self.assertIn("not a repository fact", reasons["app/auth.py"][0])
        changed = build(dict(FILES, **{"app/auth.py": FILES["app/auth.py"] + "# edited\n"}))
        experience.attach(changed, events, corrections)
        lower, _ = experience.scores(query, changed, changed.experience, tuning)
        self.assertAlmostEqual(lower["app/auth.py"], scores["app/auth.py"] * tuning["changed_file_factor"])
        rows = retrieval.experience_retriever(query, index, retrieval.configure("full+deep"))
        self.assertEqual([row["file"] for row in rows], ["app/auth.py"])
        self.assertLessEqual(len(rows), tuning["max_candidates"])

    def test_no_eligible_experience_means_indexed_only_ranking(self):
        index = build(FILES)
        task = "validate_login rejects a valid session"
        baseline = [row["path"] for row in retrieval.retrieve(task, index, retrieval.configure("full"))["ranked"]]
        self.assertEqual([row["path"] for row in retrieval.retrieve(task, index, retrieval.configure("full+deep"))["ranked"]], baseline)
        with self.store() as store:
            experience.record(store, self.event(task_id="bad", edited=("app/billing.py",), outcome="failed_checks"))
            experience.record(store, self.event(task_id="unchecked", edited=("app/billing.py",), outcome="exit_code_only"))
            self.assertEqual(experience.attach(index, store.events(), store.corrections()), 0)
        self.assertIsNone(index.experience)
        self.assertEqual([row["path"] for row in retrieval.retrieve(task, index, retrieval.configure("full+deep"))["ranked"]], baseline)

    def test_exposure_log_records_paths_only(self):
        log = self.root / "exposure.jsonl"
        experience.log_exposure(log, "digest", [{"file": "app/auth.py"}, {"file": "app/tokens.py"}], ["app/auth.py", "README.md"])
        line = json.loads(log.read_text())
        self.assertEqual((line["offered"], line["kept"]), (["app/auth.py", "app/tokens.py"], ["app/auth.py"]))
        self.assertEqual(set(line), {"time", "task_sha256", "offered", "kept"})


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / "project"
        for path, text in FILES.items():
            (self.project / path).parent.mkdir(parents=True, exist_ok=True)
            (self.project / path).write_text(text)
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        self.scrub = context._scrubber(context.find_pack(str(ROOT)))
        with repo_store.IndexStore(repo_store.state_directory(self.project), create=True) as store:
            repo_builder.Builder(self.project, store, self.scrub).run()
        self.settings = self.root / "ri.json"

    def configure(self, **experience_settings):
        """The unified switch: experience retrieval lives in the repository-memory settings (on by default)."""
        memory = self.root / "memory.json"
        memory.write_text(json.dumps({"experience": {"retrieval": "on" if experience_settings.get("use") else "off"}}))
        return mock.patch.dict(os.environ, {"AGENT_DISPATCHER_MEMORY_CONFIG": str(memory)})

    def cli(self, *arguments, env=None):
        return subprocess.run([sys.executable, "-B", str(CLI), *arguments, "--project", str(self.project), "--pack", str(ROOT)],
                              capture_output=True, text=True, env=env or dict(os.environ))

    def test_recording_from_a_real_receipt_and_using_it_only_when_enabled(self):
        task = "refresh_token drops the session when tokens expire"
        (self.project / "tests/test_tokens.py").write_text("import unittest\nfrom app.tokens import refresh_token\n\n\nclass T(unittest.TestCase):\n    def test_it(self):\n        self.assertEqual(refresh_token('x'), 'x')\n")
        receipt = self.root / "receipt.json"
        (self.project / "tests/__init__.py").write_text("")
        (self.project / "app/__init__.py").write_text("")
        verification.run_check(self.project, receipt, [sys.executable, "-B", "-m", "unittest", "-q", "tests.test_tokens"], pack=str(ROOT))
        done = self.cli("experience", "record", "--task-id", "task-1", "--task", task, "--edited", "app/tokens.py", "--receipt", str(receipt), "--json")
        self.assertEqual(done.returncode, 0, done.stderr)
        recorded = json.loads(done.stdout)
        self.assertEqual((recorded["outcome"], recorded["eligible"], recorded["stored"]), ("checked_success", True, True))
        with self.configure(use=False):
            plain = context.select_context(self.project, task, pack=ROOT)
        self.assertNotIn("memory", plain)  # Retrieval off and nothing else built: the packet is the baseline packet.
        used = context.select_context(self.project, task, pack=ROOT, explain=True)  # Defaults: experience on.
        self.assertEqual(used["memory"]["layers"]["experience"]["matches"], 1)
        self.assertTrue(used["memory"]["layers"]["experience"]["applied"])
        self.assertIn("experience rank #1", used["repository_intelligence"]["explain"])
        self.assertEqual(used["context"][0]["path"], "app/tokens.py")
        with self.configure(use=False):
            off = context.select_context(self.project, task, pack=ROOT)
        self.assertEqual([row["path"] for row in off["context"]], [row["path"] for row in plain["context"]])
        # A receipt that went stale (files changed after the check) records a non-eligible outcome.
        (self.project / "app/tokens.py").write_text("def refresh_token(token):\n    return token + '!'\n")
        done = self.cli("experience", "record", "--task-id", "task-2", "--task", task, "--edited", "app/tokens.py", "--receipt", str(receipt), "--json")
        self.assertEqual(json.loads(done.stdout)["outcome"], "stale_checks")
        done = self.cli("experience", "list", "--json")
        rows = json.loads(done.stdout)["events"]
        self.assertEqual({row["task_id"]: row["outcome"] for row in rows}, {"task-1": "checked_success", "task-2": "stale_checks"})
        first = next(row for row in rows if row["task_id"] == "task-1")
        done = self.cli("experience", "correct", first["id"], "--path", "app/tokens.py", "--verdict", "irrelevant", "--note", "wrong file", "--json")
        self.assertEqual(done.returncode, 0, done.stderr)
        corrected = context.select_context(self.project, task, pack=ROOT)
        self.assertEqual(corrected["memory"]["layers"]["experience"]["candidates"], 0)
        done = self.cli("experience", "forget", "--task", "task-1", "--json")
        self.assertEqual(json.loads(done.stdout)["removed"], 1)
        done = self.cli("experience", "show", first["id"])
        self.assertEqual(done.returncode, 2)


if __name__ == "__main__":
    unittest.main()
