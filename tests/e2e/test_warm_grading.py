"""Warm grading must preserve __file__-relative evaluator baselines and scope."""
from pathlib import Path
import tempfile
import unittest

from evals.end_to_end import runtime as rt, warmup
from evals.end_to_end.grading import grade, load_suite


class WarmRelativeBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = next(f for f in load_suite() if f['id'] == 'auth_config_boundary')
        cls.reference = Path(cls.fixture['references_dir']) / 'passing'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='warm-grading-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.initial, self.final = self.root / 'initial', self.root / 'final'
        rt.copy_files(rt.tree_files(self.fixture['source_dir']), self.initial)
        rt.copy_files(rt.tree_files(self.reference / 'files'), self.final)
        self.answer = (self.reference / 'final_answer.txt').read_text()
        for tree in (self.initial, self.final):
            rt.copy_files({name: b'{"prepared": true}\n' for name in warmup.INDEX_PATHS}, tree)

    def score(self):
        return warmup.grade_warm_fixture(self.fixture, self.initial, self.final, self.answer)

    def test_relative_inventory_accepts_setup_caches_without_editing_evaluator(self):
        scripts = {c['script']: Path(c['script']).read_bytes() for c in self.fixture['checks'] if c['kind'] == 'python'}
        original_initial = rt.digest_tree(self.initial)
        original_final = rt.digest_tree(self.final)
        broken = grade(warmup.fixture_after_warmup(self.fixture, self.initial), self.final, self.answer)
        self.assertFalse(broken['passed'])
        self.assertIn('only_requested_files_changed_or_added', [c['name'] for c in broken['checks'] if not c['passed']])
        fixed = self.score()
        self.assertTrue(fixed['passed'], fixed)
        self.assertTrue(next(c for c in fixed['checks'] if c['name'] == 'regression_catches_original_bug')['passed'])
        self.assertEqual(original_initial, rt.digest_tree(self.initial))
        self.assertEqual(original_final, rt.digest_tree(self.final))
        self.assertTrue(all(Path(path).read_bytes() == data for path, data in scripts.items()))

    def test_unrequested_extra_file_still_fails_private_inventory(self):
        (self.final / 'unauthorized.py').write_text('pass\n')
        result = self.score()
        self.assertFalse(result['passed'])
        self.assertFalse(next(c for c in result['checks'] if c['name'] == 'only_requested_files_changed_or_added')['passed'])

    def test_both_prepared_indexes_remain_protected(self):
        for name in warmup.INDEX_PATHS:
            with self.subTest(index=name):
                original = (self.final / name).read_bytes()
                (self.final / name).write_text('changed')
                result = self.score()
                self.assertFalse(result['passed'])
                self.assertFalse(next(c for c in result['checks'] if c['name'] == 'preserve_out_of_scope_sources')['passed'])
                (self.final / name).write_bytes(original)

    def test_original_bug_still_fails_independent_behavior_checks(self):
        original = Path(self.fixture['source_dir']) / 'session_api/settings.py'
        (self.final / 'session_api/settings.py').write_bytes(original.read_bytes())
        result = self.score()
        self.assertFalse(result['passed'])
        self.assertFalse(next(c for c in result['checks'] if c['name'] == 'false_aliases_deny_guests')['passed'])

    def test_setup_cannot_silently_replace_original_settings_baseline(self):
        (self.initial / 'session_api/settings.py').write_text('replacement baseline\n')
        with self.assertRaisesRegex(ValueError, 'outside the project indexes'):
            self.score()


if __name__ == '__main__':
    unittest.main()
