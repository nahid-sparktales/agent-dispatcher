"""Chronological sequence benchmark: arm isolation, before-t evidence only, oracle labeling, equivalence without experience."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "evals/retrieval" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(project, *args):
    return subprocess.run(["git", "-C", str(project), "-c", "user.email=t@example.com", "-c", "user.name=t", "-c", "commit.gpgsign=false", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


class SequenceBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.clone = self.root / "clone"
        self.clone.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.clone)], check=True)
        files = {"app/billing.py": "def charge(amount):\n    return amount\n", "app/auth.py": "def validate_login(session):\n    return session\n",
                 "app/tokens.py": "def refresh_token(token):\n    return token\n", "app/report.py": "def render_report(rows):\n    return rows\n"}
        for path, text in files.items():
            (self.clone / path).parent.mkdir(parents=True, exist_ok=True)
            (self.clone / path).write_text(text)
        git(self.clone, "add", "-A")
        git(self.clone, "commit", "-q", "-m", "initial", "--date", "2026-01-01T00:00:00")
        self.tasks = []
        # Each fix touches one file; the request words never name the file, so lexical retrieval alone is weak.
        for number, (path, query) in enumerate((("app/billing.py", "Customers are invoiced twice when a payment is retried."),
                                                ("app/auth.py", "Signing in with a valid session still shows the login page."),
                                                ("app/billing.py", "Customers are invoiced twice when a payment is retried again."),
                                                ("app/report.py", "The monthly summary document renders empty rows.")), 1):
            base = git(self.clone, "rev-parse", "HEAD")
            (self.clone / path).write_text((self.clone / path).read_text() + f"# fix {number}\n")
            git(self.clone, "commit", "-q", "-am", f"fix {number}", "--date", f"2026-01-0{number + 1}T00:00:00")
            self.tasks.append({"id": f"demo-{number}", "repo": "demo", "url": "", "base_commit": base, "fix_commit": git(self.clone, "rev-parse", "HEAD"),
                               "split": "test", "pr": None, "issue": None, "query_source": "issue", "query": query, "names_target": False,
                               "target_files": [path], "test_files": [], "added_files": []})
        self.sequence = load("sequence")

    def run_sequence(self, conditions, **options):
        tasks = self.sequence.families(sorted(self.tasks, key=lambda t: (self.sequence.commit_time(self.clone, t["base_commit"]), t["id"])))
        state = self.root / "state"
        state.mkdir(exist_ok=True)
        return self.sequence.evaluate(tasks, self.clone, conditions, state_dir=state / json.dumps(sorted(options.items()))[:40].replace("/", "_"),
                                      progress=False, **options)

    def test_oracle_experience_arrives_only_from_earlier_tasks_and_is_labeled(self):
        results = self.run_sequence(["basic", "indexed", "warm-experience"], experience_source="oracle")
        rows = [r for r in results if "conditions" in r]
        self.assertEqual([r["id"] for r in rows], ["demo-1", "demo-2", "demo-3", "demo-4"])
        self.assertTrue(rows[1]["family_repeat"] is False and rows[2]["family_repeat"] is True)  # demo-3 repeats demo-1's family
        first = rows[0]["conditions"]
        self.assertEqual(first["warm-experience"]["experience_attached"], 0)
        self.assertEqual(first["warm-experience"]["top"], first["indexed"]["top"])  # nothing before task 1: warm == indexed
        self.assertEqual(rows[0]["setup"]["indexed"]["counters"]["published"], 1)
        self.assertEqual(rows[1]["setup"]["indexed"]["counters"].get("parses", 0), 1)  # one file changed between snapshots
        third = rows[2]["conditions"]["warm-experience"]
        self.assertEqual(third["experience_attached"], 2)  # demo-1 and demo-2 only, never demo-3 itself or demo-4
        self.assertEqual(third["experience_hit"], 1.0)  # the family repeat is exactly what oracle memory finds
        self.assertGreaterEqual(third["R@1"], rows[2]["conditions"]["indexed"]["R@1"])
        self.assertEqual({r["recorded"]["warm-experience"]["outcome"] for r in rows}, {"grader_passed"})
        summary = next(r for r in results if r.get("arm_summary") == "warm-experience")
        self.assertEqual(summary["setup_counters"]["model_calls"], 0)
        self.assertEqual(summary["setup_counters"]["publications"], 4)
        text = self.sequence.table(results, ["basic", "indexed", "warm-experience"], "t") + self.sequence.paired(results, ["basic", "indexed", "warm-experience"]) \
            + self.sequence.thirds(results, ["basic", "indexed", "warm-experience"]) + self.sequence.costs(results, ["basic", "indexed", "warm-experience"])
        self.assertIn("negative transfer versus indexed", text)
        self.assertIn("monetary cost unknown", text)
        self.assertIn("warm-experience", text)

    def test_without_recorded_experience_the_warm_arm_equals_the_indexed_arm_and_history_stays_bounded(self):
        results = self.run_sequence(["indexed", "warm-experience"], experience_source="none")
        rows = [r for r in results if "conditions" in r]
        for row in rows:
            self.assertEqual(row["conditions"]["warm-experience"]["top"], row["conditions"]["indexed"]["top"])
            self.assertEqual(row["conditions"]["warm-experience"]["experience_attached"], 0)
            self.assertEqual(row["recorded"], {})
        # The clone holds every future commit, but each snapshot's history stops at its own HEAD.
        self.assertEqual([r["setup"]["indexed"]["counters"]["history_commits"] for r in rows], [1, 2, 3, 4])

    def test_replayed_events_only_count_when_eligible(self):
        events = [{"task_id": "demo-1", "query": self.tasks[0]["query"], "edited": ["app/billing.py"], "outcome": "checked_success"},
                  {"task_id": "demo-2", "query": self.tasks[1]["query"], "edited": ["app/auth.py"], "outcome": "exit_code_only"}]
        results = self.run_sequence(["indexed", "warm-experience"], experience_source="events", events=events, eligible=("checked_success",))
        rows = [r for r in results if "conditions" in r]
        self.assertEqual(rows[0]["recorded"]["warm-experience"], {"outcome": "checked_success", "eligible": True, "stored": True})
        self.assertEqual(rows[1]["recorded"]["warm-experience"], {"outcome": "exit_code_only", "eligible": False, "stored": True})
        self.assertEqual(rows[2]["conditions"]["warm-experience"]["experience_attached"], 1)  # the exit-code-only event never counts


if __name__ == "__main__":
    unittest.main()
