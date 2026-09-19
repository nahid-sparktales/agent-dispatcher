"""Offline behavioral checks for every independent E2E fixture and grader."""
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from evals.end_to_end.grading import DIMENSIONS, _run_check, grade, load_suite, tree_digest


class FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = load_suite()

    def test_suite_shape_and_balanced_categories(self):
        from collections import Counter
        self.assertEqual(len(self.fixtures), 12)
        self.assertEqual(Counter(f['category'] for f in self.fixtures), {
            'small_edit': 2, 'bug_fix': 2, 'feature': 2, 'review': 2,
            'plan': 1, 'research': 1, 'ambiguity': 1, 'scope': 1})
        self.assertEqual({f['id'] for f in self.fixtures if f['smoke']}, {'greeting', 'merge_intervals'})
        self.assertTrue(all(f['timeout_seconds'] == 600 for f in self.fixtures))
        self.assertTrue(all(len(f['fixture_digest']) == 64 for f in self.fixtures))

    def test_every_reference_passes_or_fails_for_observable_reasons(self):
        for fixture in self.fixtures:
            for label, expected in (('passing', True), ('failing', False)):
                with self.subTest(fixture=fixture['id'], reference=label):
                    reference = Path(fixture['references_dir']) / label
                    before = tree_digest(reference / 'files')
                    result = grade(fixture, reference / 'files', (reference / 'final_answer.txt').read_text())
                    self.assertEqual(result['passed'], expected, result['checks'])
                    self.assertEqual(result['human_required'], fixture['human_required'])
                    self.assertEqual(before, tree_digest(reference / 'files'), 'grading changed evidence')
                    self.assertTrue(all(isinstance(check['passed'], bool) for check in result['checks']))
                    if not expected:
                        self.assertTrue(any(not check['passed'] for check in result['checks']))

    def test_reference_human_ratings_have_boolean_contract(self):
        for fixture in self.fixtures:
            self.assertEqual(set(fixture['rubric']), set(DIMENSIONS))
            for label in ('passing', 'failing'):
                ratings = json.loads((Path(fixture['references_dir']) / label / 'ratings.json').read_text())
                self.assertEqual(set(ratings), set(DIMENSIONS))
                self.assertTrue(all(type(value) is bool for value in ratings.values()))
                success = all(ratings[x] for x in ('correctness', 'completeness', 'scope')) and not any(ratings[x] for x in ('unsupported_claims', 'unnecessary_intervention'))
                self.assertEqual(success, label == 'passing')

    def test_human_required_answers_are_never_semantically_graded_by_regex(self):
        for fixture in self.fixtures:
            if fixture['human_required']:
                good = Path(fixture['references_dir']) / 'passing'
                result = grade(fixture, good / 'files', 'Nonsense answer with every keyword missing.')
                self.assertTrue(result['passed'], result['checks'])
                self.assertTrue(result['human_required'])

    def test_only_source_is_supplied_to_agent(self):
        for fixture in self.fixtures:
            source = Path(fixture['source_dir'])
            self.assertFalse(Path(fixture['references_dir']).is_relative_to(source))
            for check in fixture['checks']:
                if check['kind'] == 'python':
                    self.assertFalse(Path(check['script']).is_relative_to(source))
            self.assertFalse(any(p.name in ('ratings.json', 'evaluator.py', 'final_answer.txt') for p in source.rglob('*')))

    def test_starting_files_are_copied_identically_between_conditions(self):
        with tempfile.TemporaryDirectory() as tmp:
            for fixture in self.fixtures:
                root = Path(tmp) / fixture['id']
                for condition in ('baseline', 'dispatcher'):
                    shutil.copytree(fixture['source_dir'], root / condition)
                self.assertEqual(tree_digest(root / 'baseline'), tree_digest(root / 'dispatcher'))
                self.assertEqual(tree_digest(root / 'baseline'), fixture['source_digest'])

    def test_agent_authored_tests_do_not_override_independent_checks(self):
        fixture = self.fixtures[0]
        with tempfile.TemporaryDirectory() as tmp:
            final = Path(tmp) / 'final'
            shutil.copytree(fixture['source_dir'], final)
            (final / 'test_greeting.py').write_text('assert True\n')
            (final / 'evaluator.py').write_text('print("all passed")\n')
            self.assertFalse(grade(fixture, final, 'All tests pass.')['passed'])

    def test_grader_does_not_leak_environment_or_import_into_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            final = root / 'final'
            final.mkdir()
            script = root / 'evaluator.py'
            script.write_text('''import os\ndef checks(root, answer):\n    def isolated():\n        assert "E2E_TEST_SECRET" not in os.environ\n        assert answer == "the answer"\n        (root / "artifact").write_text("changed in disposable copy")\n    return [("isolated", isolated)]\n''')
            with patch.dict(os.environ, {'E2E_TEST_SECRET': 'do-not-copy'}):
                result = _run_check(script, final, 'the answer')
            self.assertTrue(result[0]['passed'], result)
            self.assertFalse((final / 'artifact').exists())

    def test_grader_timeout_and_bad_output_are_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            final = root / 'final'
            final.mkdir()
            script = root / 'evaluator.py'
            script.write_text('import time\ndef checks(root, answer):\n    time.sleep(30)\n    return []\n')
            result = _run_check(script, final, '', timeout=0.15)
            self.assertFalse(result[0]['passed'])
            self.assertEqual(result[0]['name'], 'evaluator_timeout')
            script.write_text('import os\nos._exit(0)\n')
            result = _run_check(script, final, '')
            self.assertEqual(result[0]['name'], 'evaluator_output')

    def test_symlink_artifacts_rejected(self):
        fixture = self.fixtures[0]
        with tempfile.TemporaryDirectory() as tmp:
            final = Path(tmp) / 'final'
            shutil.copytree(fixture['source_dir'], final)
            (final / 'leak').symlink_to(Path(tmp))
            result = grade(fixture, final, '')
            self.assertFalse(result['passed'])
            self.assertEqual(result['checks'][0]['name'], 'artifact_validation')

    def test_manifest_rejects_traversal_symlinks_and_malformed_contract(self):
        original_path = Path(__file__).parent / 'evals' / 'end_to_end' / 'fixtures' / 'manifest.json'
        raw = json.loads(original_path.read_text())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / 'manifest.json'
            one = copy.deepcopy(raw)
            one['fixtures'] = [one['fixtures'][0]]
            one['fixtures'][0]['source_dir'] = '../outside'
            manifest.write_text(json.dumps(one))
            with self.assertRaises(ValueError): load_suite(manifest)
            one['fixtures'][0]['source_dir'] = 'link'
            (root / 'link').symlink_to(Path(self.fixtures[0]['source_dir']), target_is_directory=True)
            manifest.write_text(json.dumps(one))
            with self.assertRaises(ValueError): load_suite(manifest)
            one['fixtures'][0]['timeout_seconds'] = True
            manifest.write_text(json.dumps(one))
            with self.assertRaises(ValueError): load_suite(manifest)


if __name__ == '__main__':
    unittest.main()
