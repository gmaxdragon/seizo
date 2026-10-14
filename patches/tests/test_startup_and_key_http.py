import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from app import BUILD, Server, make_handler
from core.cloud import HackClubPlanner
from core.key_store import KeyStore
from core.runner import Runner
from core.startup import health, wait_ready, write_instance, existing_url, clear_instance
from bootstrap import numpy_ok, safe_log
from test_key_storage import FakeProtector

ROOT=Path(__file__).resolve().parents[1]

class KeyHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)
        self.runner=Runner(self.path/'policy');self.cloud=HackClubPlanner(store=KeyStore(self.path/'vault',FakeProtector()))
        self.server=Server(('127.0.0.1',0),make_handler(self.runner,'session-test',threading.Event(),self.cloud,'nonce-test'))
        self.url=f'http://127.0.0.1:{self.server.server_port}'
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.runner.shutdown();self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def req(self,path,data=None,headers=None):
        h={'Origin':self.url,'X-Lab-Token':'session-test','Content-Type':'application/json'};h.update(headers or {})
        request=urllib.request.Request(self.url+path,data=None if data is None else json.dumps(data).encode(),headers=h)
        try:
            with urllib.request.urlopen(request,timeout=10) as r:return r.status,r.headers,r.read()
        except urllib.error.HTTPError as r:return r.code,r.headers,r.read()
    def test_ready_endpoint_no_key_or_token(self):
        self.cloud.set_key('not-a-real-hackclub-key-111')
        c,h,b=self.req('/healthz',headers={'X-Lab-Token':''})
        self.assertEqual(c,200);self.assertNotIn(b'hackclub-key',b);self.assertNotIn(b'session-test',b)
        self.assertTrue(wait_ready(self.server.server_port,'nonce-test',.5))
    def test_localhost_alias_works(self):
        h={'Host':f'localhost:{self.server.server_port}','Origin':f'http://localhost:{self.server.server_port}'}
        self.assertEqual(self.req('/api/hackclub/key',{'key':'not-a-real-hackclub-key-111'},h)[0],200)
    def test_reveal_requires_explicit_post_and_auth(self):
        self.cloud.set_key('not-a-real-hackclub-key-111')
        self.assertEqual(self.req('/api/hackclub/reveal')[0],404)
        self.assertEqual(self.req('/api/hackclub/reveal',{})[0],400)
        self.assertEqual(self.req('/api/hackclub/reveal',{'confirmed':True},{'X-Lab-Token':''})[0],403)
        self.assertEqual(self.req('/api/hackclub/reveal',{'confirmed':True},{'Origin':'https://evil.example'})[0],403)
        c,h,b=self.req('/api/hackclub/reveal',{'confirmed':True})
        self.assertEqual(c,200);self.assertEqual(json.loads(b)['key'],'not-a-real-hackclub-key-111')
        self.assertEqual(h['Cache-Control'],'no-store')
    def test_late_save_cannot_undo_delete(self):
        self.assertEqual(self.req('/api/hackclub/key',{'key':'not-a-real-hackclub-key-111','key_seq':1})[0],200)
        self.assertEqual(self.req('/api/hackclub/forget',{'key_seq':3})[0],200)
        self.assertEqual(self.req('/api/hackclub/key',{'key':'not-a-real-hackclub-key-222','key_seq':2})[0],400)
        self.assertFalse(self.cloud.status()['enabled'])
    def test_duplicate_save_no_password_in_reply(self):
        key='not-a-real-hackclub-key-111'
        c,h,b=self.req('/api/hackclub/key',{'key':key,'key_seq':123})
        self.assertNotIn(key.encode(),b);self.assertEqual(self.req('/api/hackclub/key',{'key':key,'key_seq':123})[0],400)
    def test_no_static_vault_access(self):
        for path in ('/../vault/hackclub.dpapi','/credentials/hackclub.dpapi','/logs/startup.log'):
            self.assertEqual(self.req(path)[0],404)
    def test_selected_model_validated(self):
        self.assertEqual(self.req('/api/hackclub/test',{'model':'not-real'})[0],400)
    def test_existing_instance_url_is_verified(self):
        write_instance(self.path,self.server.server_port,'nonce-test',BUILD)
        self.assertTrue(existing_url(self.path,BUILD).startswith(self.url))
        self.assertIsNone(existing_url(self.path,'old-build'))
        clear_instance(self.path,'wrong-nonce');self.assertTrue((self.path/'.running.json').exists())
        clear_instance(self.path,'nonce-test');self.assertFalse((self.path/'.running.json').exists())
    def test_fake_ready_record_rejected(self):
        write_instance(self.path,self.server.server_port,'wrong-nonce',BUILD)
        self.assertIsNone(existing_url(self.path,BUILD))

class LauncherTests(unittest.TestCase):
    def test_numpy_probe_existing_and_bad_binary(self):
        self.assertTrue(numpy_ok(sys.executable));self.assertFalse(numpy_ok('/this/path/does/not/exist'))
    def test_health_never_fetches_external_addresses(self):
        for port in (None,'https://evil.example',True,-1,65536):self.assertEqual(health(port),{})
    def test_logs_redact_common_secret_patterns(self):
        output=safe_log('Authorization: Bearer anything-here\n key sk-ABCDEFG1234567890\nhttps://user:pass@proxy.test')
        self.assertNotIn('anything-here',output);self.assertNotIn('ABCDEFG',output);self.assertNotIn('user:pass',output)
    def test_actual_app_start_port_conflict_and_second_launch(self):
        import socket
        with tempfile.TemporaryDirectory() as td, socket.socket() as occupied:
            occupied.bind(('127.0.0.1',0));occupied.listen()
            port=occupied.getsockname()[1];data=Path(td)/'data'
            command=[sys.executable,'-u',str(ROOT/'app.py'),'--no-browser','--data-dir',str(data),'--port',str(port)]
            log=Path(td)/'console.txt'
            with log.open('w+') as console:
                p=subprocess.Popen(command,stdout=console,stderr=subprocess.STDOUT,cwd=td)
                try:
                    deadline=time.time()+20
                    while time.time()<deadline and not (data/'.running.json').exists():
                        if p.poll() is not None:self.fail(log.read_text())
                        time.sleep(.1)
                    record=json.loads((data/'.running.json').read_text())
                    self.assertNotEqual(record['port'],port);self.assertTrue(health(record['port']).get('ready'))
                    second=subprocess.run(command,capture_output=True,text=True,cwd=td,timeout=15)
                    self.assertEqual(second.returncode,0,second.stdout+second.stderr)
                    self.assertIn('already running',second.stdout)
                    base=f"http://127.0.0.1:{record['port']}"
                    page=urllib.request.urlopen(base+'/').read().decode()
                    token=re.search(r'name="lab-token" content="([^"]+)"',page).group(1)
                    req=urllib.request.Request(base+'/api/quit',data=b'{}',headers={'Origin':base,'X-Lab-Token':token,'Content-Type':'application/json'})
                    urllib.request.urlopen(req,timeout=5).read();p.wait(timeout=15)
                    self.assertEqual(p.returncode,0);self.assertFalse((data/'.running.json').exists())
                finally:
                    if p.poll() is None:p.terminate();p.wait(timeout=15)
            self.assertIn('Local server responded successfully',log.read_text())
    def test_browser_opens_only_after_readiness_call(self):
        code=(ROOT/'app.py').read_text();start=code.index('def main():')
        self.assertLess(code.index('if not wait_ready',start),code.index('webbrowser.open(url)',code.index('if not wait_ready',start)))
    def test_key_module_not_blocked_by_static_graphics_import(self):
        code=(ROOT/'web/app.js').read_text()
        self.assertNotIn("import {createView}",code)
        self.assertIn("import('./learning_view.js')",code)
        self.assertIn("const keyUI=setupKeyUI(api)",code)
    def test_no_clipboard_read_or_browser_persistence(self):
        code=(ROOT/'web/key_ui.js').read_text()
        self.assertNotIn('localStorage',code);self.assertNotIn('sessionStorage',code);self.assertNotIn('clipboard.read',code)
    def test_declared_physics_and_model_hashes(self):
        import hashlib
        # Engine changed intentionally: enforce the NEW audited source hashes.
        # This prevents old physics modules from silently mixing with new visuals.
        expected=json.loads((ROOT/'tests/preserved_source_hashes.json').read_text())
        for path,digest in expected.items():self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),digest,path)

if __name__=='__main__':unittest.main()
