"""Offline behavioral checks for every independent E2E fixture and grader."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from evals.end_to_end.grading import DIMENSIONS, _run_check, grade, load_suite, tree_digest

ROOT = Path(__file__).resolve().parents[2]


class FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = load_suite()

    def test_suite_shape_and_balanced_categories(self):
        from collections import Counter
        self.assertEqual(len(self.fixtures), 15)
        self.assertEqual(Counter(f['category'] for f in self.fixtures), {
            'small_edit': 2, 'bug_fix': 2, 'feature': 2, 'review': 2,
            'plan': 1, 'research': 1, 'ambiguity': 1, 'scope': 1,
            'context_retrieval': 1, 'context_freshness': 1, 'architecture_discovery': 1})
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

    def test_trial_workspace_is_exactly_source_never_private(self):
        # The runner's own copy step, not just the manifest layout: evaluators and references never reach the agent.
        from evals.end_to_end import run as runner, runtime as rt
        for fixture in self.fixtures:
            with self.subTest(fixture=fixture['id']), \
                    runner.workspace_for({}, 'codex', 'baseline', fixture) as (workspace, skill):
                files = rt.tree_files(workspace, rt.EXCLUDED)
                self.assertIsNone(skill)
                self.assertEqual(files, rt.tree_files(fixture['source_dir']))
                for check in fixture['checks']:
                    if check['kind'] == 'python':
                        self.assertNotIn(Path(check['script']).read_bytes(), files.values())

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
        original_path = ROOT / 'evals' / 'end_to_end' / 'fixtures' / 'manifest.json'
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


class ContextOutcomeFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = {item['id']: item for item in load_suite()}

    def rejected_mutation(self, task_id, mutate):
        fixture = self.fixtures[task_id]
        reference = Path(fixture['references_dir']) / 'passing'
        with tempfile.TemporaryDirectory() as temp:
            final = Path(temp) / 'final'
            shutil.copytree(reference / 'files', final)
            mutate(final)
            result = grade(fixture, final, 'Claimed success, independently checked below.')
        self.assertFalse(result['passed'], result['checks'])
        self.assertFalse(any(check['name'] in {'evaluator_process', 'evaluator_output', 'evaluator_timeout'}
                             for check in result['checks']), result['checks'])
        return result

    def change_report(self, task_id, path, mutate):
        def apply(root):
            target = root / path
            value = json.loads(target.read_text())
            mutate(value)
            target.write_text(json.dumps(value))
        return self.rejected_mutation(task_id, apply)

    def test_live_auth_grader_rejects_disabled_everyone_and_partial_parser_shortcuts(self):
        settings = 'from dataclasses import dataclass\n@dataclass(frozen=True)\nclass Settings:\n    allow_guest: bool = False\n'
        variants = {
            'always_false': settings + 'def load_settings(env):\n    return Settings(False)\n',
            'only_literal_true': settings + 'def load_settings(env):\n    return Settings(env.get("APP_ALLOW_GUEST") == "true")\n',
            'original_truthiness': settings + 'def load_settings(env):\n    return Settings(bool(env.get("APP_ALLOW_GUEST", False)))\n',
        }
        for name, code in variants.items():
            with self.subTest(shortcut=name):
                self.rejected_mutation('auth_config_boundary',
                                       lambda root: (root / 'session_api/settings.py').write_text(code))

    def test_candidate_green_tests_do_not_rescue_the_unfixed_live_parser(self):
        source = Path(self.fixtures['auth_config_boundary']['source_dir'])
        def fake_tests(root):
            (root / 'session_api/settings.py').write_bytes((source / 'session_api/settings.py').read_bytes())
            (root / 'tests/test_auth_config.py').write_text('assert True\n')
        self.rejected_mutation('auth_config_boundary', fake_tests)

    def test_correct_parser_with_empty_green_tests_does_not_claim_regression_coverage(self):
        result = self.rejected_mutation('auth_config_boundary',
            lambda root: (root / 'tests/test_auth_config.py').write_text('assert True\n'))
        self.assertTrue(any(check['name'] == 'regression_catches_original_bug' and not check['passed']
                            for check in result['checks']))

    def test_auth_grader_rejects_changes_to_protected_router_despite_correct_parser(self):
        result = self.rejected_mutation('auth_config_boundary',
            lambda root: (root / 'session_api/api.py').write_text((root / 'session_api/api.py').read_text() + '\n# unrelated edit\n'))
        self.assertTrue(any(check['name'] == 'preserve_out_of_scope_sources' and not check['passed']
                            for check in result['checks']))

    def test_stale_summary_rejects_hash_path_quote_range_and_claim_shortcuts(self):
        mutations = {
            'false_value_with_valid_citation': lambda d: d['entries'][1].update(value=3),
            'stale_hash': lambda d: d['entries'][1]['evidence'].update(sha256='0' * 64),
            'renamed_path': lambda d: d['entries'][0]['evidence'].update(path='worker.py'),
            'deleted_path': lambda d: d['entries'][2]['evidence'].update(path='service/old_errors.py'),
            'fabricated_quote': lambda d: d['entries'][1]['evidence'].update(quote='MAX_ATTEMPTS = 3'),
            'invalid_range': lambda d: d['entries'][1]['evidence'].update(start_line=0),
            'bool_line_number': lambda d: d['entries'][1]['evidence'].update(start_line=True),
            'outside_path': lambda d: d['entries'][1]['evidence'].update(path='../service/policy.py'),
            'duplicate_fact': lambda d: d['entries'].__setitem__(1, copy.deepcopy(d['entries'][0])),
            'boolean_schema_version': lambda d: d.update(schema_version=True),
        }
        for name, mutate in mutations.items():
            with self.subTest(shortcut=name):
                self.change_report('stale_project_map', 'docs/PROJECT_MAP.json', mutate)

    def test_real_frozen_cache_is_stale_and_inspection_does_not_refresh_it(self):
        import project_map
        source = Path(self.fixtures['stale_project_map']['source_dir'])
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / 'project'
            shutil.copytree(source, project)
            # CI does not require ripgrep. Give the ignore-aware scanner the same
            # Git-backed workspace used by live trials, and exercise that path.
            subprocess.run(['git', 'init', '--quiet', str(project)], check=True, capture_output=True)
            state = project / '.agent-dispatcher/project-map.json'
            before = tree_digest(project)
            snapshot = json.loads(state.read_text())
            self.assertEqual(snapshot['owner'], 'agent-dispatcher-project-map')
            fresh_entries = [row for row in snapshot['entries']
                             if row['source']['path'] == 'service/errors.py']
            self.assertEqual(len(fresh_entries), 1)
            self.assertEqual(fresh_entries[0]['source']['sha256'],
                             hashlib.sha256((project / 'service/errors.py').read_bytes()).hexdigest())
            native_which = shutil.which
            with patch.object(shutil, 'which', side_effect=lambda command:
                              None if command == 'rg' else native_which(command)):
                report = project_map.inspect_map(project, pack=ROOT)
            self.assertEqual(report['status'], 'stale')
            self.assertEqual(report['counts']['fresh'], 1)
            self.assertEqual(report['counts']['withheld'], len(snapshot['entries']) - 1)
            self.assertEqual(report['entries'], fresh_entries)
            paths = {row['path'] for row in report['stale_sources']}
            self.assertTrue({'Makefile', 'worker.py', 'service/old_errors.py'} <= paths)
            self.assertFalse(any(row['source']['path'] in paths for row in report['entries']))
            self.assertEqual(before, tree_digest(project))

    def test_map_refresh_task_cannot_rewrite_protected_cache_or_source_to_match_a_claim(self):
        for path in ('.agent-dispatcher/project-map.json', 'service/policy.py'):
            with self.subTest(path=path):
                result = self.rejected_mutation('stale_project_map',
                    lambda root: (root / path).write_text((root / path).read_text() + '\n'))
                self.assertTrue(any(check['name'] == 'preserve_out_of_scope_sources' and not check['passed']
                                    for check in result['checks']))

    def test_architecture_report_rejects_false_facts_even_with_current_hashes(self):
        mutations = {
            'proposal_as_accepted_backend': lambda d: d['decision'].update(value='sqlite'),
            'undeclared_dependency': lambda d: d['dependencies'].update(value=['sqlite3']),
            'guessed_test_command': lambda d: d['test_command'].update(value='pytest'),
            'retired_entrypoint': lambda d: d['entrypoint'].update(value='prototype.sqlite_api:handle_request'),
            'invented_route': lambda d: d['features'][0].update(value='DELETE /tasks'),
            'duplicate_edge': lambda d: d['edges'].__setitem__(1, copy.deepcopy(d['edges'][0])),
            'import_is_not_callsite': lambda d: d['edges'][0]['evidence'].update(start_line=1, end_line=1,
                                quote='from flowdesk.service import TaskService'),
            'stale_hash': lambda d: d['entrypoint']['evidence'].update(sha256='f' * 64),
            'wrong_quote': lambda d: d['decision']['evidence'].update(quote='Status: accepted\nBackend: sqlite'),
            'oversized_range': lambda d: d['entrypoint']['evidence'].update(end_line=30),
        }
        for name, mutate in mutations.items():
            with self.subTest(shortcut=name):
                self.change_report('architecture_evidence', 'architecture.json', mutate)

    def test_architecture_report_rejects_unused_callsites_with_genuine_current_citations(self):
        source = Path(self.fixtures['architecture_evidence']['source_dir'])
        path = 'flowdesk/batch_service.py'
        raw = (source / path).read_bytes()
        lines = raw.decode().splitlines()
        for edge_index, line in ((2, 6), (3, 9)):
            citation = {'path': path, 'start_line': line, 'end_line': line,
                        'quote': lines[line - 1], 'sha256': hashlib.sha256(raw).hexdigest()}
            with self.subTest(edge=edge_index):
                result = self.change_report('architecture_evidence', 'architecture.json',
                    lambda report: report['edges'][edge_index].update(evidence=citation))
                self.assertTrue(any(check['name'] == 'direct_route_service_store_edges' and not check['passed']
                                    for check in result['checks']))

    def test_architecture_report_cannot_edit_the_unused_implementation(self):
        result = self.rejected_mutation('architecture_evidence',
            lambda root: (root / 'flowdesk/batch_service.py').write_text('# removed unused code\n'))
        self.assertTrue(any(check['name'] == 'preserve_out_of_scope_sources' and not check['passed']
                            for check in result['checks']))

    def test_context_success_does_not_require_helper_invocation_or_final_keywords(self):
        for task_id in ('auth_config_boundary', 'stale_project_map', 'architecture_evidence'):
            fixture = self.fixtures[task_id]
            good = Path(fixture['references_dir']) / 'passing'
            self.assertTrue(grade(fixture, good / 'files',
                'Solved manually from source files without invoking dispatcher helpers.')['passed'])


if __name__ == '__main__':
    unittest.main()
