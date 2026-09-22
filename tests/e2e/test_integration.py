"""Offline integration through source packaging, fake native streams, grading and review.

Only native doctor/launch are substituted. The fake client is a real child process;
stream parsing, workspaces, frozen artifacts, graders, reports and review imports are real.
No credentials, native clients, or model requests are involved.
"""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from evals.end_to_end import adapters, reporting, run as runner, runtime as rt
from evals.end_to_end.grading import load_suite


FAKE_CLIENT = r'''
import json
from pathlib import Path
import sys
client, model, skill = sys.argv[1:4]
prompt = sys.stdin.read()
if client == 'claude':
    prompt = json.loads(prompt)['message']['content']
treatment = bool(skill)
assert prompt.startswith(('$' if client == 'codex' else '/') + 'agent-dispatcher ') == treatment
if Path('greeting.py').exists():
    Path('greeting.py').write_text("def greet(name):\n    return f\"Hello, {name.strip() or 'World'}!\"\n\ndef farewell(name):\n    return f\"Bye, {name}!\"\n")
elif Path('intervals.py').exists():
    Path('intervals.py').write_text("def merge_intervals(intervals):\n    merged = []\n    for start, end in sorted(intervals):\n        if merged and start <= merged[-1][1]:\n            merged[-1][1] = max(merged[-1][1], end)\n        else:\n            merged.append([start, end])\n    return merged\n")
answer = 'Updated the requested implementation.'
def emit(value): print(json.dumps(value), flush=True)
if client == 'codex':
    emit({'type':'thread.started','thread_id':'fake','model':model})
    if treatment:
        emit({'type':'item.completed','item':{'type':'command_execution','command':'cat ' + skill + '/SKILL.md','exit_code':0,'aggregated_output':(Path(skill)/'SKILL.md').read_text()}})
    emit({'type':'item.completed','item':{'type':'agent_message','text':answer}})
    emit({'type':'turn.completed','usage':{'input_tokens':100,'output_tokens':20,'cached_input_tokens':0}})
else:
    emit({'type':'system','subtype':'init','model':model,'tools':['Read','Edit','Skill'],'skills':['agent-dispatcher'] if treatment else [],'plugins':[],'mcp_servers':[],'permissionMode':'dontAsk'})
    if treatment:
        emit({'type':'assistant','message':{'content':[{'type':'tool_use','id':'s1','name':'Skill','input':{'skill':'agent-dispatcher'}}]}})
        emit({'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':'s1','content':(Path(skill)/'SKILL.md').read_text(),'is_error':False}]}})
    emit({'type':'result','subtype':'success','result':answer,'is_error':False,'usage':{'input_tokens':100,'output_tokens':20,'cache_read_input_tokens':0},'total_cost_usd':0.001})
'''


class PipelineIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_tmp = tempfile.TemporaryDirectory(prefix='dispatcher-eval-test-source-')
        cls.addClassCleanup(cls.repo_tmp.cleanup)
        cls.repository = Path(cls.repo_tmp.name) / 'repository'
        runner.source_snapshot(cls.repository)
        subprocess.run(['git', 'init', '--quiet', str(cls.repository)], check=True, capture_output=True)
        subprocess.run(['git', 'add', '.'], cwd=cls.repository, check=True, capture_output=True)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dispatcher-eval-integration-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fake = self.root / 'fake_client.py'
        self.fake.write_text(FAKE_CLIENT)
        self.repository_patch = patch.object(runner, 'ROOT', self.repository)
        self.repository_patch.start()
        self.addCleanup(self.repository_patch.stop)
        with patch.object(Path, 'home', return_value=self.root / 'profile-home'):
            self.config_path = runner.prepare(self.root / 'output',
                models={c:'fixture-model' for c in runner.CLIENTS},
                efforts={c:'medium' for c in runner.CLIENTS})
        self.config = runner.load_config(self.config_path, live=True)
        self.fixture_by_id = {f['id']:f for f in load_suite(self.root/'output/fixtures')}
        self.probes = []

    def fake_doctor(self, client, spec, workspace, skill):
        self.assertFalse(Path(workspace).is_relative_to(self.repository))
        if skill is not None:
            self.assertTrue((Path(skill)/'SKILL.md').is_file())
        self.probes.append((client, bool(skill)))
        return {'ok':True, 'version':'fixture-cli 1.0', 'errors':[], 'warnings':[], 'evidence':{}}

    def fake_launch(self, client, spec, workspace, skill):
        return {'argv':[sys.executable,str(self.fake),client,spec['model'],str(skill) if skill else ''],
                'env':{'PATH':os.defpath},
                'stdin_prefix':(('$' if client=='codex' else '/')+'agent-dispatcher ') if skill else '',
                'effective':{'client':client,'model':spec['model'],'effort':spec['effort'],
                             'condition':'dispatcher' if skill else 'baseline',
                             'input_format':'text' if client=='codex' else 'stream-json'}}

    @contextlib.contextmanager
    def native_fakes(self):
        with patch.object(adapters,'doctor',side_effect=self.fake_doctor), patch.object(adapters,'build_launch',side_effect=self.fake_launch), contextlib.redirect_stdout(io.StringIO()):
            yield

    def test_full_smoke_then_blind_review_and_report(self):
        with self.native_fakes():
            proof = runner.doctor(self.config)
            self.assertTrue(proof['ok'])
            batch = runner.run(self.config, 'smoke')
        rows=rt.read_json(batch/'results.json')['trials']
        self.assertEqual(len(rows),8)
        self.assertTrue(all(row['status']=='completed' and row['task_success'] for row in rows),rows)
        self.assertTrue((self.root/'output/smoke-ready.json').is_file())
        for row in rows:
            final=batch/row['artifact_dir']/'final'
            self.assertTrue(final.is_dir())
            self.assertFalse((final/'.git').exists())
            self.assertFalse((final/'.agents').exists())
            self.assertTrue((batch/row['artifact_dir']/'events.jsonl').is_file())
        for first,second in zip(rows[::2],rows[1::2]):
            self.assertEqual(first['starting_files_digest'],second['starting_files_digest'])
            left={k:v for k,v in first['effective_settings'].items() if k!='condition'}
            right={k:v for k,v in second['effective_settings'].items() if k!='condition'}
            self.assertEqual(left,right)
        self.assertFalse((Path(self.config['clients']['claude']['profile_dir'])/'skills/agent-dispatcher').exists())
        review=reporting.create_review(batch,seed=8)
        packets=rt.read_json(review/'packets.json')
        self.assertEqual(len(packets['packets']),8)
        self.assertNotIn('codex-greeting',json.dumps(packets))
        self.assertNotIn('condition',packets['packets'][0])
        ratings=rt.read_json(review/'ratings-template.json')
        for row in ratings['ratings']:
            row.update(correctness=True,completeness=True,scope=True,unsupported_claims=False,unnecessary_intervention=False)
        rating_path=self.root/'ratings.json';rt.write_json(rating_path,ratings)
        self.assertEqual(reporting.import_review(batch,rating_path)['imported'],8)
        report=reporting.report(batch)
        self.assertEqual(set(report['clients']),{'codex','claude'})
        for client in report['clients'].values():
            self.assertEqual(client['pairs']['both_pass'],2)
            self.assertEqual(client['conditions']['baseline']['complete_success_rate'],1)
            self.assertEqual(client['conditions']['dispatcher']['complete_success_rate'],1)

    def test_claude_only_prepare_probe_smoke_and_report_never_touch_codex(self):
        output = self.root / 'claude-only'
        with patch.object(Path, 'home', return_value=self.root / 'single-profile-home'):
            path = runner.prepare(output, clients=['claude'],
                                  models={'claude': 'fixture-model'}, efforts={'claude': 'medium'})
        config = runner.load_config(path, live=True)
        self.assertEqual(set(config['clients']), {'claude'})
        self.assertEqual(set(config['provenance']['package_digests']), {'claude'})
        self.assertEqual({p.name for p in (output / 'packages').iterdir()}, {'claude'})
        profile = Path(config['clients']['claude']['profile_dir'])
        self.assertEqual({p.name for p in profile.parent.iterdir()}, {'claude'})
        with self.native_fakes():
            proof = runner.doctor(config)
            self.assertEqual(set(proof['checks']), {'claude/baseline', 'claude/dispatcher'})
            batch = runner.run(config, 'smoke')
        rows = rt.read_json(batch / 'results.json')['trials']
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row['client'] == 'claude' and row['status'] == 'completed'
                            and row['task_success'] for row in rows), rows)
        self.assertTrue(all(client == 'claude' for client, treatment in self.probes))
        self.assertEqual(set(reporting.report(batch)['clients']), {'claude'})
        self.assertTrue((output / 'smoke-ready.json').is_file())
        self.assertFalse((profile / 'skills/agent-dispatcher').exists())
        self.assertEqual(len(runner.schedule(load_suite(output / 'fixtures'), 'pilot',
                                           config['seed'], config['clients'])), 60)
        skill = output / 'packages/claude/SKILL.md'
        skill.write_bytes(skill.read_bytes() + b'\nchanged\n')
        with self.assertRaisesRegex(ValueError, 'dispatcher package changed'):
            runner.load_config(path, live=True)

    def test_prepare_cli_passes_explicit_client_selection_without_running_a_model(self):
        output = self.root / 'cli-selected'
        with patch.object(runner, 'prepare', return_value=output / 'config.json') as prepare, contextlib.redirect_stdout(io.StringIO()):
            result = runner.main(['prepare', '--output', str(output), '--clients', 'claude',
                                  '--claude-model', 'fixture-model', '--claude-effort', 'medium'])
        self.assertEqual(result, 0)
        self.assertEqual(prepare.call_args.kwargs['clients'], ['claude'])
        self.assertEqual(prepare.call_args.args[2]['claude'], 'fixture-model')

    def test_human_fixture_pending_until_review_import(self):
        fixture=self.fixture_by_id['review_cache']
        batch=self.root/'human-batch';batch.mkdir()
        row={'id':'codex-review-cache-1-baseline','client':'codex','condition':'baseline','fixture_id':fixture['id'],'repetition':1}
        rt.write_json(batch/'batch.json',{'schema_version':1,'suite':'integration','seed':1,'schedule':[row]})
        with self.native_fakes():
            trial=runner.run_trial(self.config,batch,row,fixture)
        self.assertEqual(trial['status'],'completed')
        self.assertIsNone(trial['task_success'])
        self.assertTrue(trial['auto_grade']['human_required'])
        rt.write_json(batch/'results.json',{'schema_version':1,'trials':[trial]})
        pending=reporting.report(batch)['clients']['codex']['conditions']['baseline']
        self.assertEqual(pending['required_reviews_pending'],1)
        self.assertIsNone(pending['complete_success_rate'])
        review=reporting.create_review(batch)
        ratings=rt.read_json(review/'ratings-template.json')
        ratings['ratings'][0].update(correctness=False,completeness=False,scope=True,unsupported_claims=False,unnecessary_intervention=False)
        rating_path=self.root/'bad-review.json';rt.write_json(rating_path,ratings)
        reporting.import_review(batch,rating_path)
        graded=reporting.report(batch)['clients']['codex']['conditions']['baseline']
        self.assertEqual(graded['required_reviews_pending'],0)
        self.assertEqual(graded['complete_success_rate'],0)

    def test_pilot_requires_matching_smoke_fingerprint(self):
        with self.native_fakes():
            with self.assertRaisesRegex(ValueError,'successful smoke'):
                runner.run(self.config,'pilot')
            runner.run(self.config,'smoke')
            changed=copy.deepcopy(self.config)
            changed['clients']['codex']['model']='different-explicit-model'
            with self.assertRaisesRegex(ValueError,'successful smoke'):
                runner.run(changed,'pilot')
        self.assertEqual(len(list((self.root/'output/batches').iterdir())),1)

    def test_package_and_fixture_tampering_invalidate_configuration(self):
        skill=self.root/'output/packages/codex/SKILL.md'
        original=skill.read_bytes();skill.write_bytes(original+b'\nchanged\n')
        with self.assertRaisesRegex(ValueError,'dispatcher package changed'):
            runner.load_config(self.config_path,live=True)
        skill.write_bytes(original)
        prompt=self.root/'output/fixtures/greeting/source/greeting.py'
        prompt.write_text('changed')
        with self.assertRaisesRegex(ValueError,'fixtures changed'):
            runner.load_config(self.config_path,live=True)

    def test_treatment_cleanup_on_trial_failure(self):
        profile=Path(self.config['clients']['claude']['profile_dir'])
        with self.assertRaisesRegex(RuntimeError,'fake failure'):
            with runner.workspace_for(self.config,'claude','dispatcher') as (workspace,skill):
                self.assertTrue(skill.is_dir())
                raise RuntimeError('fake failure')
        self.assertFalse((profile/'skills/agent-dispatcher').exists())
        with runner.workspace_for(self.config,'claude','baseline') as (workspace,skill):
            self.assertIsNone(skill)

    def test_agent_created_symlink_is_task_failure_not_setup_invalid(self):
        self.fake.write_text(FAKE_CLIENT + "\nPath('bad-link').symlink_to('/tmp')\n")
        batch = self.root / 'bad-artifact-batch'; batch.mkdir()
        row = {'id':'bad-artifact','client':'codex','condition':'baseline',
               'fixture_id':'greeting','repetition':1}
        with self.native_fakes():
            result = runner.run_trial(self.config, batch, row, self.fixture_by_id['greeting'])
        self.assertEqual(result['status'], 'task_failure')
        self.assertIs(result['task_success'], False)
        self.assertTrue((batch / result['artifact_dir'] / 'events.jsonl').is_file())

    def test_unexpected_adapter_failure_keeps_attempt_and_logs(self):
        batch = self.root / 'bad-parser-batch'; batch.mkdir()
        row = {'id':'bad-parser','client':'codex','condition':'baseline',
               'fixture_id':'greeting','repetition':1}
        with self.native_fakes(), patch.object(adapters, 'parse_events', side_effect=AttributeError('changed schema')):
            result = runner.run_trial(self.config, batch, row, self.fixture_by_id['greeting'])
        self.assertEqual(result['status'], 'infrastructure_error')
        self.assertIsNone(result['task_success'])
        self.assertTrue((batch / result['artifact_dir'] / 'events.jsonl').is_file())

    def test_snapshot_build_leaves_source_repository_unchanged(self):
        before=rt.tree_files(self.repository,exclude={'.git','__pycache__'})
        runner.stage_packages(self.root/'second-packages')
        after=rt.tree_files(self.repository,exclude={'.git','__pycache__'})
        self.assertEqual(rt.digest_files(before),rt.digest_files(after))
        self.assertTrue((self.root/'second-packages/codex/SKILL.md').is_file())
        self.assertTrue((self.root/'second-packages/claude/SKILL.md').is_file())

    def test_warm_setup_precedes_model_timing_and_paired_initial_snapshot(self):
        from evals.end_to_end import warmup
        self.config['warm_project_index'] = True

        def setup(config, client, workspace):
            self.assertTrue((workspace / 'greeting.py').is_file())
            rt.copy_files({path: b'{}\n' for path in warmup.INDEX_PATHS}, workspace)
            return {'ok': True, 'elapsed_seconds': 1234.0, 'excluded_from_task_timing': True,
                    'diagnostics': []}

        results = []
        batch = self.root / 'warm-paired'
        batch.mkdir()
        with self.native_fakes(), patch.object(warmup, 'warm_project_indexes', side_effect=setup):
            for condition in runner.CONDITIONS:
                row = {'id': condition, 'client': 'claude', 'condition': condition,
                       'fixture_id': 'greeting', 'repetition': 1}
                result = runner.run_trial(self.config, batch, row, self.fixture_by_id['greeting'])
                results.append(result)
                self.assertEqual(result['status'], 'completed', result)
                self.assertLess(result['elapsed_seconds'], result['index_setup']['elapsed_seconds'])
                evidence = batch / result['artifact_dir']
                self.assertTrue((evidence / 'index-setup.json').is_file())
                for path in warmup.INDEX_PATHS:
                    self.assertEqual((evidence / 'initial' / path).read_bytes(), b'{}\n')
                    self.assertEqual((evidence / 'final' / path).read_bytes(), b'{}\n')
        runner.reconcile_pair(results)
        self.assertEqual(results[0]['starting_files_digest'], results[1]['starting_files_digest'])
        self.assertTrue(all(r['status'] == 'completed' for r in results))

    def test_real_codex_warm_pairs_exclude_installed_skill_from_project_index(self):
        from evals.end_to_end import warmup
        home = self.root.resolve() / 'warm-cache-home'
        home.mkdir()
        initial = []
        with patch.dict(os.environ, {'HOME': str(home)}):
            for condition in runner.CONDITIONS:
                with runner.workspace_for(self.config, 'codex', condition,
                                          self.fixture_by_id['greeting']) as (workspace, skill):
                    result = warmup.warm_project_indexes(self.config, 'codex', workspace)
                    self.assertTrue(result['ok'], result)
                    files = rt.tree_files(workspace, rt.EXCLUDED)
                    initial.append(rt.digest_files(files))
                    self.assertFalse(any(path.startswith('.agent-dispatcher/') for path in files))
                    # The graph is private state under the helper's HOME, keyed by this workspace.
                    saved = [json.loads(path.read_text()) for path in home.glob('.cache/agent-dispatcher/state-v1/*/project-graph.json')]
                    graph = next(g for g in saved if any(s['path'] == 'greeting.py' for s in g['sources']))
                    self.assertTrue(all(not s['path'].startswith('.agents/') for s in graph['sources']))
        self.assertEqual(initial[0], initial[1])

    def test_warm_trial_preservation_checks_detect_generated_cache_mutation(self):
        from evals.end_to_end import warmup
        self.config['warm_project_index'] = True
        fixture = copy.deepcopy(self.fixture_by_id['greeting'])
        fixture['checks'].append({'kind': 'unchanged', 'name': 'protected_scope', 'paths': [],
                                  'no_extra_files': True})
        self.fake.write_text(FAKE_CLIENT +
                            "\nPath('.agent-dispatcher/project-graph.json').write_text('tampered')\n")

        def setup(config, client, workspace):
            rt.copy_files({path: b'{}\n' for path in warmup.INDEX_PATHS}, workspace)
            return {'ok': True, 'elapsed_seconds': 0.01, 'diagnostics': []}

        row = {'id': 'warm-scope', 'client': 'claude', 'condition': 'baseline',
               'fixture_id': 'greeting', 'repetition': 1}
        with self.native_fakes(), patch.object(warmup, 'warm_project_indexes', side_effect=setup):
            result = runner.run_trial(self.config, self.root / 'warm-scope', row, fixture)
        self.assertEqual(result['status'], 'task_failure', result)
        scope = next(c for c in result['auto_grade']['checks'] if c['name'] == 'protected_scope')
        self.assertFalse(scope['passed'])
        self.assertIn('project-graph.json', scope['detail'])

    def one_trial(self, name="scope"):
        batch = self.root / name
        batch.mkdir()
        row = {"id": name, "client": "codex", "condition": "baseline", "fixture_id": "greeting", "repetition": 1}
        with self.native_fakes():
            result = runner.run_trial(self.config, batch, row, self.fixture_by_id["greeting"])
        return batch, result

    def test_sibling_residue_fails_scope_while_preserving_artifact_acceptance(self):
        self.fake.write_text(FAKE_CLIENT + "\nPath('../check_map.py').write_text('temporary validator')\n")
        batch, result = self.one_trial()
        self.assertEqual(result["status"], "task_failure")
        self.assertFalse(result["task_success"])
        self.assertTrue(result["auto_grade"]["passed"])
        self.assertFalse(result["scope_check"]["passed"])
        self.assertEqual(result["scope_audit"]["entries"], [{"path": "check_map.py", "kind": "file", "size": 19}])
        evidence = batch / result["artifact_dir"]
        self.assertEqual(rt.read_json(evidence / "scope-audit.json"), result["scope_audit"])
        self.assertTrue((evidence / "activity.json").is_file())
        self.assertNotIn("temporary validator", (evidence / "scope-audit.json").read_text())

    def test_scope_capture_survives_parser_failure(self):
        self.fake.write_text(FAKE_CLIENT + "\nPath('../check_map.py').write_text('temporary validator')\n")
        with patch.object(adapters, "parse_events", side_effect=RuntimeError("schema changed")):
            batch, result = self.one_trial("parse-scope")
        self.assertEqual(result["status"], "infrastructure_error")
        self.assertFalse(result["scope_check"]["passed"])
        self.assertTrue((batch / result["artifact_dir"] / "scope-audit.json").is_file())
        self.assertTrue((batch / result["artifact_dir"] / "activity.json").is_file())

    def test_scope_capture_survives_timeout_and_detects_successful_cleanup(self):
        self.fake.write_text(FAKE_CLIENT + "\nPath('../check_map.py').write_text('temporary validator')\nimport time; time.sleep(5)\n")
        self.config["timeout_seconds"] = 0.2
        _, result = self.one_trial("timeout-scope")
        self.assertEqual(result["status"], "timeout")
        self.assertFalse(result["scope_check"]["passed"])
        self.assertEqual(result["activity"]["availability"], "partial")
        self.config["timeout_seconds"] = 600
        self.fake.write_text(FAKE_CLIENT + "\nPath('../check_map.py').write_text('temporary validator')\nPath('../check_map.py').unlink()\n")
        _, clean = self.one_trial("clean-scope")
        self.assertEqual(clean["status"], "completed")
        self.assertTrue(clean["scope_check"]["passed"])

    def test_incomplete_scope_capture_cannot_claim_clean_success(self):
        unknown = {"schema_version": 1, "availability": "partial", "entry_count": 0,
                   "clean": None, "entries": [], "diagnostics": ["bounded"]}
        with patch.object(rt, "audit_trial_parent", return_value=unknown):
            _, result = self.one_trial("unknown-scope")
        self.assertEqual(result["status"], "infrastructure_error")
        self.assertIsNone(result["task_success"])
        self.assertIsNone(result["scope_check"]["passed"])
        self.assertTrue(result["auto_grade"]["passed"])

    def test_claude_staging_uses_installed_resource_paths(self):
        pack = self.root / "output/packages/claude"
        manifest = rt.read_json(pack / "catalog/resource-paths.json")
        self.assertEqual(manifest["layout"], "claude_manual")
        self.assertTrue((pack / "resources.py").is_file())
        for kind in ("roles", "guides"):
            self.assertTrue(manifest[kind])
            for relative in manifest[kind].values():
                self.assertTrue((pack / relative).is_file(), relative)
                self.assertNotIn("..", Path(relative).parts)
        self.assertEqual(manifest["roles"]["explorer"], "roles/explorer.md")
        self.assertTrue(all(path.startswith("lib/") for path in manifest["guides"].values()))


if __name__=='__main__':
    unittest.main()
