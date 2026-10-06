#!/usr/bin/env python3
"""Claude native canary with local scripted Anthropic responses, no real API/model.

Uses print/SDK mode only in a newly created synthetic workspace. The host responds
to normal tool approval requests; plugin hooks remain enabled. No bypass flags.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from native_codex import PRODUCT, invoke, repo


class Provider(BaseHTTPRequestHandler):
    actions = []
    def log_message(self, *args):
        pass
    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if 'count_tokens' in self.path:
            self.send_response(200);self.end_headers();self.wfile.write(b'{"input_tokens": 1}');return
        action = self.actions.pop(0) if self.actions and data.get('tools') else None
        content = {'type':'tool_use','id':'toolu_'+uuid.uuid4().hex,'name':'Bash','input':{}} if action else {'type':'text','text':''}
        delta = {'type':'input_json_delta','partial_json':json.dumps({'command':action,'description':'Synthetic local test'})} if action else {'type':'text_delta','text':'Synthetic case complete.'}
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
        events = [
            ('message_start',{'type':'message_start','message':{'id':'msg_'+uuid.uuid4().hex,'type':'message','role':'assistant','model':data.get('model','fixture'),'content':[],'stop_reason':None,'stop_sequence':None,'usage':{'input_tokens':1,'output_tokens':0}}}),
            ('content_block_start',{'type':'content_block_start','index':0,'content_block':content}),
            ('content_block_delta',{'type':'content_block_delta','index':0,'delta':delta}),
            ('content_block_stop',{'type':'content_block_stop','index':0}),
            ('message_delta',{'type':'message_delta','delta':{'stop_reason':'tool_use' if action else 'end_turn','stop_sequence':None},'usage':{'output_tokens':1}}),
            ('message_stop',{'type':'message_stop'})]
        for name,event in events:
            self.wfile.write(('event: '+name+'\ndata: '+json.dumps(event)+'\n\n').encode());self.wfile.flush()


def main():
    root=Path(tempfile.mkdtemp(prefix='bulletproof-claude-native-')).resolve()
    home=root/'claude-home';home.mkdir();project=repo(root,'synthetic project')
    package=root/'package with spaces'
    invoke([sys.executable,str(PRODUCT/'scripts/package.py'),str(package)])
    server=ThreadingHTTPServer(('127.0.0.1',0),Provider)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    env=dict(os.environ,CLAUDE_CONFIG_DIR=str(home),ANTHROPIC_BASE_URL='http://127.0.0.1:%d'%server.server_port,
             ANTHROPIC_AUTH_TOKEN='synthetic-fixture-token',CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1')
    for a in [('marketplace','add',str(package)),('install','bulletproof@bulletproof')]:
        print(invoke(['claude','plugin',*a],env=env))
    evidence=[]
    def case(name,commands,answer='allow'):
        Provider.actions[:]=commands
        p=subprocess.Popen(['claude','--print','--input-format','stream-json','--output-format','stream-json','--verbose',
                            '--debug-file',str(root/(name+'.debug')),'--permission-mode','default','--permission-prompt-tool','stdio','--no-session-persistence'],
                           cwd=project,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=(root/(name+'.stderr')).open('w'),text=True,bufsize=1)
        q=queue.Queue();events=[]
        def reader():
            for line in p.stdout:q.put(json.loads(line))
            q.put({"type":"eof"})
        threading.Thread(target=reader,daemon=True).start()
        def send(value):p.stdin.write(json.dumps(value)+'\n');p.stdin.flush()
        send({'type':'user','message':{'role':'user','content':'Run the synthetic verification fixture.'}})
        try:
            while True:
                item=q.get(timeout=30);events.append(item)
                if item.get('type')=='eof':raise RuntimeError('Claude exited: '+(root/(name+'.stderr')).read_text())
                if item.get('type')=='control_request':
                    req=item['request'];print('approval',req.get('subtype'),flush=True)
                    response={'behavior':answer,'updatedInput':req.get('input',{})} if answer=='allow' else {'behavior':'deny','message':'Synthetic human decline'}
                    send({'type':'control_response','response':{'subtype':'success','request_id':item['request_id'],'response':response}})
                if item.get('type')=='result':break
        finally:
            p.terminate();p.wait(timeout=10)
            evidence.append({'case':name,'events':events})
            (root/'native-results.json').write_text(json.dumps(evidence,indent=2)+'\n')
        return events
    try:
        head=invoke(['git','rev-parse','HEAD'],project)
        events=case('no-green',['git add -A && git commit -m synthetic'])
        assert any(e.get('subtype')=='init' and {'bulletproof:framework-init','bulletproof:testar'} <= set(e.get('slash_commands',[])) for e in events)
        assert 'SessionStart' in json.dumps(events) and '[Bulletproof]' in json.dumps(events)
        assert invoke(['git','rev-parse','HEAD'],project)==head
        assert 'BLOCKED (Exit Lock)' in json.dumps(events)
        print('PASS native Claude commit block',flush=True)
        events=case('green-and-commit',['python3 %s --platform claude testar .' % shlex.quote(str(package/'scripts/run.py')),'git add -A && git commit -m synthetic'])
        assert invoke(['git','rev-parse','HEAD'],project)!=head
        assert 'testar: GREEN' in json.dumps(events)
        print('PASS native Claude green releases commit',flush=True)
        (project/'app.py').write_text('value = 3\n')
        head=invoke(['git','rev-parse','HEAD'],project)
        events=case('invalidated',['git add -A && git commit -m changed'])
        assert invoke(['git','rev-parse','HEAD'],project)==head and 'BLOCKED (Exit Lock)' in json.dumps(events)
        print('PASS native Claude stamp invalidation',flush=True)
        cmd='./wrangler d1 execute synthetic --remote --command "DELETE FROM demo"'
        events=case('production-denied',[cmd],'deny')
        assert 'returned permissionDecision: ask' in (root/'production-denied.debug').read_text()
        assert not (project/'d1.sentinel').exists()
        assert any(e.get('type')=='control_request' and e.get('request',{}).get('subtype')=='can_use_tool' for e in events)
        print('PASS native Claude production ask denied',flush=True)
        events=case('production-allowed',[cmd])
        assert 'returned permissionDecision: ask' in (root/'production-allowed.debug').read_text()
        assert (project/'d1.sentinel').read_text()=='synthetic only\n'
        print('PASS native Claude production ask allowed',flush=True)
        print('Evidence: '+str(root),flush=True)
    finally:
        server.shutdown();server.server_close()


if __name__=='__main__':main()
