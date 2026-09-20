import unittest
from service.errors import TemporaryFailure
from service.worker import run_job


class WorkerTests(unittest.TestCase):
    def test_success(self):
        self.assertEqual(run_job(lambda: 42), 42)

    def test_budget(self):
        calls = []
        def fail():
            calls.append(1)
            raise TemporaryFailure("retry")
        with self.assertRaises(TemporaryFailure):
            run_job(fail)
        self.assertEqual(len(calls), 4)
