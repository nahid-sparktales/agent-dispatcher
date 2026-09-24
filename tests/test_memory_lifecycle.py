"""The offline repository-intelligence lifecycle demo runs end to end and leaves nothing behind."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "evals" / "memory" / "demo.py"


class MemoryLifecycleDemoTests(unittest.TestCase):
    def test_demo_completes_every_step_in_an_isolated_home(self):
        done = subprocess.run([sys.executable, "-B", str(DEMO), "--json"], capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(done.returncode, 0, done.stderr[-3000:])
        report = json.loads(done.stdout)
        self.assertEqual(report["result"], "complete")
        self.assertEqual([step["step"] for step in report["steps"]],
                         ["build memory", "retrieve behavior query", "record experience", "consolidate", "source changed",
                          "correct episode", "forget episode", "working memory"])
        self.assertFalse(Path(report["isolated_home"]).exists())
        steps = {step["step"]: step for step in report["steps"]}
        self.assertEqual(steps["record experience"]["first"]["outcome"], "checked_success")
        self.assertEqual(steps["consolidate"]["support"]["families"], 2)
        self.assertEqual(steps["source changed"]["experience_layer"], "use_limited")
        self.assertEqual(steps["correct episode"]["candidates"], "no_candidates")
        self.assertEqual(steps["forget episode"]["experience_candidates"], 0)


if __name__ == "__main__":
    unittest.main()
