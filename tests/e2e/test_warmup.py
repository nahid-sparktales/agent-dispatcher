"""Warm-index setup and scope grading; fake helpers only, no native model calls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from evals.end_to_end import run as runner, runtime as rt, warmup
from evals.end_to_end.grading import grade


FAKE_HELPER = r'''
import json, sys
from pathlib import Path
maintain = '--map-maintain' in sys.argv
root = Path(sys.argv[sys.argv.index('--project') + 1])
if maintain:
    state = root / '.agent-dispatcher'
    state.mkdir(exist_ok=True)
    (state / 'project-map.json').write_text('{"facts": []}\n')
    (state / 'project-graph.json').write_text('{"nodes": []}\n')
index = {'status': 'fresh', 'cache_status': 'fresh',
         'coverage': {'scan_complete': True, 'task_filtered': False, 'excluded_files': 0},
         'maintenance': {'action': 'built' if maintain else 'not_requested'}}
stats = {'enabled': True, 'write_allowed': maintain, 'source_hits': 0 if maintain else 1,
         'source_misses': 1 if maintain else 0, 'source_bytes_read': 20 if maintain else 0,
         'parsed_files': 1 if maintain else 0,
         'writes': 1 if maintain else 0, 'fact_hits': 0 if maintain else 1,
         'fact_misses': 1 if maintain else 0, 'graph_hits': 0 if maintain else 1,
         'graph_misses': 1 if maintain else 0, 'private_path': '/not-for-artifacts'}
packet = {'project_map': index, 'project_graph': index, 'parser_cache': stats}
INJECT
print(json.dumps(packet))
'''


class WarmIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dispatcher-warm-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.output = self.root / 'output'
        self.helper = self.output / 'packages/claude/context.py'
        self.helper.parent.mkdir(parents=True)
        self.install_helper()
        self.workspace = self.root / 'project'
        self.workspace.mkdir()
        (self.workspace / 'app.py').write_text('def run():\n    pass\n')
        self.config = {'schema_version': 1, 'seed': 1, 'timeout_seconds': 600,
                       'output_dir': str(self.output), 'warm_project_index': True,
                       'clients': {'claude': {'auth': 'subscription', 'executable': 'claude',
                                             'model': 'fixed', 'effort': 'high',
                                             'profile_dir': str(self.root / 'profile')}}}

    def install_helper(self, injection=''):
        self.helper.write_text(FAKE_HELPER.replace('INJECT', injection))

    def warm(self):
        return warmup.warm_project_indexes(self.config, 'claude', self.workspace)

    def test_real_helper_setup_and_preview_are_outside_task_with_identical_indexes(self):
        result = self.warm()
        self.assertTrue(result['ok'], result)
        self.assertTrue(result['excluded_from_task_timing'])
        self.assertGreater(result['elapsed_seconds'], 0)
        self.assertEqual([s['mode'] for s in result['stages']], ['maintain', 'preview'])
        stats = result['stages'][1]['parser_cache']
        self.assertEqual(stats['parsed_files'], 0)
        self.assertEqual(stats['source_bytes_read'], 0)
        self.assertNotIn('private_path', stats)
        before = rt.tree_files(self.workspace)
        second = self.root / 'paired-project'
        rt.copy_files({'app.py': before['app.py']}, second)
        paired = warmup.warm_project_indexes(self.config, 'claude', second)
        self.assertTrue(paired['ok'], paired)
        self.assertEqual(rt.tree_files(second), before)
        self.assertEqual(paired['index_files_digest'], result['index_files_digest'])

    def test_partial_or_stale_indexes_fail_setup(self):
        for injection in ("index['coverage']['scan_complete'] = False",
                          "index['coverage']['task_filtered'] = True",
                          "index['cache_status'] = 'stale'",
                          "packet.pop('parser_cache')"):
            with self.subTest(injection=injection):
                self.install_helper(injection)
                self.assertFalse(self.warm()['ok'])

    def test_codex_uses_scripts_helper_layout(self):
        helper = self.output / 'packages/codex/scripts/context.py'
        helper.parent.mkdir(parents=True)
        helper.write_text(FAKE_HELPER.replace('INJECT', ''))
        config = copy.deepcopy(self.config)
        config['clients'] = {'codex': {**config['clients']['claude'], 'executable': 'codex'}}
        result = warmup.warm_project_indexes(config, 'codex', self.workspace)
        self.assertTrue(result['ok'], result)

    def test_warm_preview_must_prove_reuse_without_source_reads_parsing_or_writes(self):
        for key in ('source_misses', 'source_bytes_read', 'parsed_files', 'writes'):
            with self.subTest(counter=key):
                self.install_helper(f"stats[{key!r}] = 1")
                result = self.warm()
                self.assertFalse(result['ok'], result)
                self.assertIn('did not reuse', result['diagnostics'][0])

    def test_setup_cannot_change_other_sources_or_write_in_preview(self):
        for injection in ("(root / 'extra.txt').write_text('unexpected')",
                          "if not maintain: (root / '.agent-dispatcher/project-map.json').write_text('changed')"):
            with self.subTest(injection=injection):
                (self.workspace / 'extra.txt').unlink(missing_ok=True)
                self.install_helper(injection)
                self.assertFalse(self.warm()['ok'])

    def test_warm_preview_requires_graph_reuse_evidence(self):
        self.install_helper("stats['graph_hits'] = 0")
        result = self.warm()
        self.assertFalse(result['ok'])
        self.assertIn('relationship graph', result['diagnostics'][0])

    def test_warm_failure_stops_before_native_doctor_or_model_launch(self):
        fixture = {'id': 'fixture', 'source_dir': str(self.workspace), 'category': 'docs',
                   'human_required': False, 'prompt': 'Update report.', 'acceptance': [],
                   'rubric': {}, 'checks': [], 'timeout_seconds': 600}
        row = {'id': 'warm-failure', 'client': 'claude', 'condition': 'baseline',
               'fixture_id': 'fixture', 'repetition': 1}
        failed = {'ok': False, 'diagnostics': ['cache unavailable']}
        with patch.object(warmup, 'warm_project_indexes', return_value=failed), \
                patch('evals.end_to_end.adapters.doctor') as doctor, \
                patch('evals.end_to_end.adapters.build_launch') as launch:
            result = runner.run_trial(self.config, self.root / 'batch', row, fixture)
        doctor.assert_not_called()
        launch.assert_not_called()
        self.assertEqual(result['status'], 'invalid_configuration')
        self.assertIsNone(result['elapsed_seconds'])
        self.assertEqual(result['index_setup'], failed)

    def test_grade_uses_post_setup_baseline_and_protects_both_index_files(self):
        self.assertTrue(self.warm()['ok'])
        (self.workspace / 'report.json').write_text('old report')
        initial = self.root / 'initial'
        final = self.root / 'final'
        rt.copy_files(rt.tree_files(self.workspace), initial)
        rt.copy_files(rt.tree_files(self.workspace), final)
        fixture = {'source_dir': '/not/the/warm/baseline', 'human_required': False,
                   'checks': [{'kind': 'unchanged', 'name': 'scope', 'paths': ['app.py'],
                               'no_extra_files': True}]}
        original = copy.deepcopy(fixture)
        adapted = warmup.fixture_after_warmup(fixture, initial)
        (final / 'report.json').write_text('new report')
        self.assertTrue(grade(adapted, final, '')['passed'])
        self.assertEqual(fixture, original)
        for path in warmup.INDEX_PATHS:
            with self.subTest(path=path):
                old = (final / path).read_bytes()
                (final / path).write_text('tampered')
                self.assertFalse(grade(adapted, final, '')['passed'])
                (final / path).write_bytes(old)
        (final / 'extra.txt').write_text('scope violation')
        self.assertFalse(grade(adapted, final, '')['passed'])

    def test_warm_setting_is_validated_and_invalidates_smoke_fingerprint(self):
        runner.validate_config(self.config, live=True)
        cold = {**self.config, 'warm_project_index': False}
        self.assertNotEqual(runner.fingerprint(cold), runner.fingerprint(self.config))
        for invalid in (1, 'yes', None):
            with self.subTest(value=invalid), self.assertRaisesRegex(ValueError, 'boolean'):
                runner.validate_config({**self.config, 'warm_project_index': invalid})


if __name__ == '__main__':
    unittest.main()
