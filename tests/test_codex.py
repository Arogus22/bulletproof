#!/usr/bin/env python3
"""Isolated adapter/consent tests, distinct from native-runtime evidence."""
import concurrent.futures
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import production_approval as approval
import runtime


class CodexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='bp-codex spaces-')
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / 'project'; self.repo.mkdir()
        self.env = dict(os.environ, BULLETPROOF_PLATFORM='codex', CODEX_HOME=str(self.root/'codex'),
                        CLAUDE_CONFIG_DIR=str(self.root/'claude'))
        self.env.pop('BULLETPROOF_STATE', None); self.env.pop('BULLETPROOF_LEDGER', None)
        self.patch = patch.dict(os.environ, self.env, clear=True); self.patch.start()
        self.fv = {'plugin':'bulletproof','version':'0.3','status':'active','layers':[1,2,3],
                   'stacks':['python'],'tests':{'python':'python3 -m unittest -q'},
                   'config':{'deploy':{'protected_branch':'main','deploy_cmds':['wrangler deploy']},'prod_db':{'kind':'d1'}}}
        (self.repo/'.framework-version').write_text(json.dumps(self.fv))
        (self.repo/'.gitignore').write_text('__pycache__/\n')
        (self.repo/'app.py').write_text('value = 1\n')
        (self.repo/'test_app.py').write_text('import unittest\nfrom app import value\nclass Test(unittest.TestCase):\n def test_positive(self): self.assertGreater(value, 0)\n')
        for args in [('init','-q','-b','main'),('config','user.name','Test'),('config','user.email','test@example.invalid'),('add','.'),('commit','-qm','baseline')]:
            subprocess.run(['git',*args],cwd=self.repo,check=True,capture_output=True)
        self.payload={'hook_event_name':'PreToolUse','session_id':'session-A','cwd':str(self.repo),
                      'tool_name':'Bash','tool_input':{'command':'git push origin main'}}

    def tearDown(self):
        self.patch.stop(); self.tmp.cleanup()

    def hook(self, payload=None):
        p=subprocess.run([sys.executable,str(ROOT/'scripts/codex-hook.py')],input=json.dumps(payload or self.payload),
                         text=True,capture_output=True,env=self.env)
        self.assertEqual(p.returncode,0,p.stderr)
        return json.loads(p.stdout)['hookSpecificOutput'] if p.stdout else {}

    def request(self):
        out=self.hook();self.assertEqual(out['permissionDecision'],'deny')
        return re.search(r'request_id=([a-f0-9]{32})',out['permissionDecisionReason']).group(1)

    def test_state_defaults_and_overrides(self):
        self.assertEqual(runtime.state_base(),str(self.root/'codex/state'))
        with patch.dict(os.environ,{'BULLETPROOF_PLATFORM':'claude'}):
            self.assertEqual(runtime.state_base(),str(self.root/'claude/state'))
        with patch.dict(os.environ,{'BULLETPROOF_STATE':str(self.root/'override')}):
            self.assertEqual(runtime.state_base(),str(self.root/'override'))

    def test_exit_lock_cycle_and_ledger(self):
        self.payload['tool_input']['command']='git add -A && git commit -m changed'
        (self.repo/'app.py').write_text('value = 2\n')
        self.assertEqual(self.hook()['permissionDecision'],'deny')
        p=subprocess.run([sys.executable,str(ROOT/'scripts/run.py'),'--platform','codex','testar',str(self.repo)],env=self.env,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertEqual(self.hook(),{})
        (self.repo/'app.py').write_text('value = 3\n')
        self.assertEqual(self.hook()['permissionDecision'],'deny')
        self.assertFalse((self.root/'claude').exists())
        self.assertTrue(list((self.root/'codex/state/exit-lock').glob('*/last-green')))
        self.assertIn('test_green',(self.root/'codex/state/bulletproof/ledger.jsonl').read_text())

    def test_unadopted_silence_no_state(self):
        (self.repo/'.framework-version').write_text('{}')
        self.assertEqual(self.hook(),{})
        self.payload['hook_event_name']='SessionStart'
        self.assertEqual(self.hook(),{})
        self.assertFalse((self.root/'codex').exists())

    def test_missing_session_blocks_without_request(self):
        self.payload.pop('session_id')
        self.assertIn('session_id',self.hook()['permissionDecisionReason'])
        self.assertFalse((self.root/'codex').exists())

    def test_one_use(self):
        rid=self.request(); self.assertTrue(approval.finish(rid,True))
        self.assertEqual(self.hook(),{})
        self.assertNotEqual(self.request(),rid)

    def test_decline_cannot_release(self):
        rid=self.request(); self.assertFalse(approval.finish(rid,False))
        self.assertNotEqual(self.request(),rid)

    def test_expiration(self):
        rid=self.request()
        with patch('production_approval.time.time',return_value=9999999999):
            with self.assertRaises(ValueError):approval.finish(rid,True)
        self.assertNotEqual(self.request(),rid)

    def test_other_session_cannot_consume(self):
        rid=self.request();approval.finish(rid,True)
        self.payload['session_id']='session-B';self.request()
        self.payload['session_id']='session-A';self.assertEqual(self.hook(),{})

    def test_other_command_cannot_consume(self):
        rid=self.request();approval.finish(rid,True)
        self.payload['tool_input']['command']='git push other main';self.request()
        self.payload['tool_input']['command']='git push origin main';self.assertEqual(self.hook(),{})

    def test_changes_before_consent_rejected(self):
        rid=self.request();(self.repo/'app.py').write_text('value = 9\n')
        with self.assertRaises(ValueError):approval.finish(rid,True)

    def test_changes_after_consent_rejected(self):
        rid=self.request();approval.finish(rid,True)
        (self.repo/'package.json').write_text('{"scripts":{"deploy":"wrangler deploy"}}')
        self.assertNotEqual(self.request(),rid)

    def test_remote_change_invalidates_consent(self):
        rid=self.request();approval.finish(rid,True)
        subprocess.run(['git','remote','add','origin',str(self.root/'other.git')],cwd=self.repo,check=True)
        self.assertNotEqual(self.request(),rid)

    def test_marker_above_git_root(self):
        (self.repo/'.framework-version').rename(self.root/'.framework-version')
        rid=self.request();approval.finish(rid,True);self.assertEqual(self.hook(),{})

    def test_concurrent_retry_consumes_once(self):
        rid=self.request();approval.finish(rid,True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(lambda _:self.hook(),range(2)))
        self.assertEqual(sum(not o for o in outcomes),1)

    def test_d1_and_deploy_share_one_consent(self):
        self.payload['tool_input']['command']='wrangler deploy && wrangler d1 execute db --remote --command "DELETE FROM demo"'
        rid=self.request();self.assertEqual(len(approval.pending(rid)['reasons']),2)
        approval.finish(rid,True);self.assertEqual(self.hook(),{})

    def test_d1_mcp_and_reads(self):
        self.payload['tool_name']='mcp__cloudflare__d1_query';self.payload['tool_input']={'sql':'DELETE FROM demo'}
        rid=self.request();approval.finish(rid,True);self.assertEqual(self.hook(),{})
        self.payload['tool_input']={'sql':'SELECT * FROM demo'};self.assertEqual(self.hook(),{})

    def test_request_path_validation(self):
        with self.assertRaises(ValueError):approval.pending('../escape')

    def test_stamp_failure_is_not_green(self):
        target=self.root/'not-a-directory';target.write_text('x')
        e=dict(self.env,BULLETPROOF_STATE=str(target))
        p=subprocess.run([sys.executable,str(ROOT/'scripts/run.py'),'--platform','codex','testar',str(self.repo)],env=e,capture_output=True,text=True)
        self.assertEqual(p.returncode,2);self.assertNotIn('testar: GREEN',p.stdout)

    def test_mcp_requires_elicitation_response(self):
        rid=self.request()
        proc=subprocess.Popen([sys.executable,str(ROOT/'scripts/approval-server.py')],env=self.env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        q=queue.Queue()
        def reader():
            for line in proc.stdout:q.put(json.loads(line))
        threading.Thread(target=reader,daemon=True).start()
        def send(v):proc.stdin.write(json.dumps({'jsonrpc':'2.0',**v})+'\n');proc.stdin.flush()
        try:
            send({'id':1,'method':'initialize','params':{'capabilities':{'elicitation':{'form':{}}}}});q.get(timeout=5)
            send({'id':2,'method':'tools/call','params':{'name':'request_approval','arguments':{'request_id':rid,'approve':True}}})
            self.assertTrue(q.get(timeout=5)['result']['isError'])
            send({'id':3,'method':'tools/call','params':{'name':'request_approval','arguments':{'request_id':rid}}})
            req=q.get(timeout=5);self.assertEqual(req['method'],'elicitation/create')
            self.assertEqual(self.request(),rid)
            send({'id':req['id'],'result':{'action':'accept','content':{'approve':False}}})
            self.assertIn('Not approved',q.get(timeout=5)['result']['content'][0]['text'])
            self.assertNotEqual(self.request(),rid)
        finally:
            proc.terminate();proc.wait(timeout=5);proc.stdin.close();proc.stdout.close()


if __name__=='__main__':unittest.main()
