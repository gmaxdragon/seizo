import base64
import copy
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch
import seizo_sim_bridge as b


def status():
    return {'status':'paused','episodes':8897,'moves':40260,'updates':1680,
            'target_episodes':8917,'policy_fingerprint':'f'*64,'save_verified':True,
            'physical_motion':False,'uses_real_cameras':False,
            'model_id':b.MODEL,'input_source':'detailed_simulated_cameras',
            'config':{'task':'reach','episodes':20},
            'cloud':{'key':'SHOULD_NOT_LEAK'},'token':'LOCAL_SECRET',
            'error':'private local path','trace':{'frames':[{'secret':'not for upload'}]}}


def command(op='evaluate', **changes):
    result={'schema':b.COMMAND_SCHEMA,'id':str(uuid.uuid4()),'bridge_session':'bridge',
            'app_instance':'app','created_at':1000,'expires_at':1400,
            'policy_fingerprint':'f'*64,'op':op,'task':'reach','trials':5}
    result.update(changes)
    return result


class Commands(unittest.TestCase):
    def check(self,c,s=None,**kw):
        return b.validate_command(c,{'bridge_session':'bridge','app_instance':'app'},
                                  s or status(),now=1100,**kw)
    def test_frozen_reach(self):
        self.assertEqual(self.check(command()),('/api/evaluate',{'task':'reach','trials':5}))
    def test_no_arbitrary_commands(self):
        for op in ('shell','run_code','reset','quit','raw_gcode','gpio','show_key','/move'):
            with self.subTest(op=op),self.assertRaises(b.Blocked):self.check(command(op))
    def test_no_unknown_field(self):
        with self.assertRaises(b.Blocked):self.check(command(code='print(123)'))
    def test_expiry(self):
        for values in ({'expires_at':1050},{'created_at':1200},{'expires_at':9999},
                       {'created_at':float('nan')},{'expires_at':float('inf')},{'created_at':True}):
            with self.subTest(v=values),self.assertRaises(b.Blocked):self.check(command(**values))
    def test_stale_session(self):
        for k in ('bridge_session','app_instance'):
            with self.assertRaises(b.Blocked):self.check(command(**{k:'old'}))
    def test_changed_checkpoint(self):
        with self.assertRaises(b.Blocked):self.check(command(policy_fingerprint='other'))
    def test_training_disabled_by_default(self):
        with self.assertRaisesRegex(b.Blocked,'OPT_IN'):self.check(command('train',episodes=20))
    def test_bounded_opt_in_training(self):
        route,body=self.check(command('train',episodes=20),allow_training=True)
        self.assertEqual(route,'/api/start');self.assertEqual(body['episodes'],20)
        for n in (0,21,1_000_000,True,3.4):
            with self.subTest(n=n),self.assertRaises(b.Blocked):
                self.check(command('train',episodes=n),allow_training=True)
    def test_large_remaining_resume_is_blocked(self):
        s=status();s['target_episodes']=99999
        with self.assertRaisesRegex(b.Blocked,'RESUME_BUDGET'):
            self.check(command('train',episodes=20),s,allow_training=True)
    def test_busy_does_not_interrupt_run(self):
        for state in b.BUSY|{'error'}:
            s=status();s['status']=state
            with self.subTest(state=state),self.assertRaises(b.Blocked):self.check(command(),s)
    def test_stop_save_can_stop_busy_run(self):
        s=status();s['status']='training'
        route,body=self.check(command('stop_save',policy_fingerprint='older'),s)
        self.assertEqual(route,'/api/end-run');self.assertIn('control_seq',body)
    def test_no_advancing_milestone_task(self):
        for task in ('all','lift','orient','garbage'):
            with self.assertRaises(b.Blocked):self.check(command(task=task))
    def test_invalid_trial_counts(self):
        for trials in (0,6,100,True,'5'):
            with self.assertRaises(b.Blocked):self.check(command(trials=trials))
    def test_save_requested_blocks(self):
        s=status();s['end_run']={'state':'saving'}
        with self.assertRaises(b.Blocked):self.check(command(),s)
    def test_bad_ids(self):
        for ident in ('../../../file','evil.py',None):
            with self.assertRaises(b.Blocked):self.check(command(id=ident))


class Privacy(unittest.TestCase):
    def test_status_allowlist(self):
        out=b.sanitize(status(),'app','bridge',None,False);raw=b.dump(out)
        for secret in ('SHOULD_NOT_LEAK','LOCAL_SECRET','private local path','not for upload'):
            self.assertNotIn(secret,raw)
        self.assertEqual(out['episodes'],8897)
        self.assertTrue(out['simulator_only']);self.assertFalse(out['physical_motion'])
        self.assertFalse(out['full_episode_video_recording'])
    def test_evaluation_reduced(self):
        e={'episodes_at_test':8897,'policy_fingerprint':'f'*64,'raw_key':'SHOULD_NOT_LEAK',
           'by_task':[{'current':{'task':'reach','successes':0,'trials':5,
                      'guard_counts':{'table-clearance guard':5},'key':'SHOULD_NOT_LEAK'}}]}
        out=b.evaluation_summary(e)
        self.assertNotIn('SHOULD_NOT_LEAK',b.dump(out))
        self.assertEqual(out['tasks'][0]['current']['guard_counts'],{'table-clearance guard':5})
    def test_no_real_images_without_simulator_identity(self):
        with patch.object(b.LocalSeizo,'request',return_value={**status(),'uses_real_cameras':True}):
            with self.assertRaises(b.Blocked):b.LocalSeizo.__new__(b.LocalSeizo).status()
    def test_wrong_model_blocked(self):
        with patch.object(b.LocalSeizo,'request',return_value={**status(),'model_id':'physical_robot'}):
            with self.assertRaises(b.Blocked):b.LocalSeizo.__new__(b.LocalSeizo).status()
    def test_image_limit_and_format(self):
        self.assertEqual(b.image_payload({'live_camera':{'cameras':{'overhead':'abcd'}}}),{})
        self.assertEqual(b.image_payload({'live_camera':{'cameras':{'overhead':'A'*500000}}}),{})
    def test_no_public_upload(self):
        g=b.GitHub.__new__(b.GitHub);g.prefix='repos/'+b.REPO
        with patch.object(g,'api',return_value={'private':False,'full_name':b.REPO}):
            with self.assertRaises(b.Blocked):g.require_private()
    def test_only_allowed_local_post_routes(self):
        local=b.LocalSeizo.__new__(b.LocalSeizo)
        for path in ('/api/hackclub/reveal','/api/reset','/api/quit','http://evil','/move'):
            with self.assertRaises(b.Blocked):local.request(path,{})
    def test_file_writes_restricted(self):
        g=b.GitHub.__new__(b.GitHub);g.prefix='repos/'+b.REPO
        with patch.object(g,'require_private'),patch.object(g,'api',side_effect=[
                {'object':{'sha':'p'}},{'tree':{'sha':'t'}}]):
            with self.assertRaises(b.Blocked):g.publish({'.github/workflows/run.yml':'bad'}, {})
    def test_atomic_state(self):
        with tempfile.TemporaryDirectory() as p:
            f=Path(p)/'state.json';b.atomic(f,{'x':42})
            self.assertEqual(b.load(f),{'x':42})
            self.assertFalse(f.with_suffix('.json.next').exists())
    def test_report_staleness_explicit(self):
        r=b.sanitize(status(),'app','bridge',None,False)
        self.assertIn('older than 3 minutes',b.readme(r))
        self.assertIn('not complete video',b.readme(r))
    def test_html_token_parse(self):
        p=b.TokenParser();p.feed('<meta content="private123" name="lab-token">')
        self.assertEqual(p.token,'private123')


class Integration(unittest.TestCase):
    def test_local_http_token_and_route(self):
        import http.server
        import threading
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def do_GET(self):
                if self.path=='/healthz':obj={'app':'SeizoLearn','ready':True,'instance':'x'}
                elif self.path=='/':obj='<meta name="lab-token" content="local-only">'
                elif self.path=='/api/status':
                    assert self.headers.get('X-Lab-Token')=='local-only';obj=status()
                else:self.send_error(404);return
                raw=(obj if isinstance(obj,str) else json.dumps(obj)).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(raw)))
                self.end_headers();self.wfile.write(raw)
        server=http.server.HTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with patch.object(b,'load',return_value={'port':server.server_port}):
                client=b.LocalSeizo();self.assertEqual(client.status()['episodes'],8897)
        finally:server.shutdown();server.server_close();thread.join()
    def test_publisher_does_not_overwrite_command_or_main(self):
        g=b.GitHub.__new__(b.GitHub);g.prefix='repos/'+b.REPO
        replies=[{'object':{'sha':'parent'}},{'tree':{'sha':'tree0'}},{'sha':'tree1'},{'sha':'commit1'},{}]
        calls=[]
        def api(path,method='GET',body=None):
            calls.append((path,method,body));return replies.pop(0)
        with patch.object(g,'require_private'),patch.object(g,'api',side_effect=api):
            g.publish({'README.md':'x','latest.json':'{}'}, {})
        self.assertEqual(calls[-1][0],'repos/'+b.REPO+'/git/refs/heads/'+b.BRANCH)
        self.assertIs(calls[-1][2]['force'],False)
        self.assertEqual([e['path'] for e in calls[2][2]['tree']],['README.md','latest.json'])
        self.assertEqual(calls[2][2]['base_tree'],'tree0')
    def test_redirect_rejected(self):
        with self.assertRaises(b.Blocked):
            b.NoRedirect().redirect_request(None,None,302,'',{},'https://evil.example')
    def test_claim_before_command_and_no_repeat(self):
        with tempfile.TemporaryDirectory() as folder:
            fake_local=unittest.mock.Mock();fake_local.status.return_value=status();fake_local.instance='app'
            fake_local.request.return_value={'ok':True}
            fake_gh=unittest.mock.Mock();fake_gh.command.return_value=command()
            with patch.object(b,'HOME',Path(folder)),patch.object(b,'LocalSeizo',return_value=fake_local),patch.object(b,'GitHub',return_value=fake_gh),patch.object(b.uuid,'uuid4',return_value='bridge'),patch.object(b.time,'time',return_value=1100):
                def dispatched(*args):
                    j=b.load(Path(folder)/'journal.json')
                    self.assertIn(fake_gh.command.return_value['id'],j['handled'])
                    return {'ok':True}
                fake_local.request.side_effect=dispatched
                b.main_loop(once=True);b.main_loop(once=True)
            self.assertEqual(fake_local.request.call_count,1)


if __name__=='__main__':unittest.main(verbosity=2)
