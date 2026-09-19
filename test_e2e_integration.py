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


if __name__=='__main__':
    unittest.main()
