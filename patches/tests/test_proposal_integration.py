"""Software integration evidence only. Passing-score fixtures are SYNTHETIC.

No user's checkpoint, live API key, physical camera, Pi, or actuator is accessed.
"""
import ast
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
import numpy as np
from core.proposal_bridge import ProposalBridge
from core.proposal_policy import runtime_contract, infer_saved_decision, evaluation_evidence
from core.proposal_protocol import *
from core.view_policy import Agent
from core.cloud import HackClubPlanner
from test_proposal_bridge import fixture

ROOT=Path(__file__).resolve().parents[1]
HAS_MUJOCO=importlib.util.find_spec('mujoco') is not None

class FakeCloud:
    def __init__(self):self.calls=0;self.entered=threading.Event();self.release=None
    def interpret_task(self,instruction,model):
        self.calls+=1;self.entered.set()
        if self.release is not None:self.release.wait(4.)
        return parse_intent(canonical({'schema':INTENT_SCHEMA,'status':'supported','task':'lift','target':'red_cube'})),{'test_fixture':True}

class FakeRunner:
    def __init__(self,folder,agent,config):
        self.folder=folder;self.agent=agent;self.camera_config=config
        self.status='paused';self.generation=0;self.lock=threading.RLock()


def report_fixture(folder, agent, config):
    # This is explicitly fabricated test input for a validator, not an evaluation.
    # No production path generates a passing report or substitutes these scores.
    row={'task':'lift','trials':20,'successes':16,'seed':91,'invalid_physics':0,'faults':0,
         'weights_updated':False,'physical_motion':False,'sensor_condition':'two_mounted_cameras'}
    r={'TEST_FIXTURE_ONLY_NOT_SKILL_EVIDENCE':True,'model_id':POLICY_ID,'policy_fingerprint':agent.signature(),
       'proposal_contract_sha256':runtime_contract(config),'fingerprint_unchanged':True,
       'weights_updated':False,'physical_motion':False,
       'by_task':[{'current':row,'random_actions':{**row,'successes':1}}]}
    (folder/'evaluation.json').write_text(json.dumps(r))
    return r


class BridgeIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agent=Agent()
        x=np.zeros((2,cls.agent.obs_size),np.float32);_,z,lp,_=cls.agent.act(x)
        cls.agent.update((x,z,lp,np.array([-1,1],np.float32),np.array([0,1],np.float32)),epochs=1)
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name)
        self.config={};self.agent.save(self.folder/'policy.npz',{'camera_config':self.config})
        self.runner=FakeRunner(self.folder,self.agent,self.config);self.cloud=FakeCloud()
        self.bridge=ProposalBridge(self.runner,self.cloud)
    def tearDown(self):
        self.bridge.stop()
        if self.cloud.release is not None:self.cloud.release.set()
        if self.bridge.thread:self.bridge.thread.join(8.)
        self.tmp.cleanup()
    def finish(self):
        self.bridge.thread.join(8.)
        self.assertFalse(self.bridge.active())
        return self.bridge.snapshot()
    def inference_fixture(self,*args):
        p,_=fixture()
        return p['actions'][0],p['observation'],{}, {'test_fixture':True}
    def test_mock_flow_receipt_is_never_execution(self):
        report_fixture(self.folder,self.agent,self.config)
        before=(self.folder/'policy.npz').read_bytes()
        with patch('core.proposal_bridge.infer_saved_decision',side_effect=self.inference_fixture):
            self.bridge.begin('Lift the red cube','qwen/qwen3-32b');r=self.finish()
        self.assertEqual(r['state'],'received_by_mock_pi',r)
        self.assertEqual(self.cloud.calls,1)
        self.assertFalse(r['automatic_motion_enabled']);self.assertFalse(r['executed'])
        self.assertFalse(r['real_pi_connected']);self.assertEqual(before,(self.folder/'policy.npz').read_bytes())
    def test_stop_while_cloud_waits_is_immediate_and_no_send(self):
        self.cloud.release=threading.Event()
        with patch('core.proposal_bridge.MockPiTransport') as transport:
            self.bridge.begin('Lift the red cube','qwen/qwen3-32b')
            self.assertTrue(self.cloud.entered.wait(3.))
            start=time.perf_counter();self.bridge.stop();elapsed=time.perf_counter()-start
            self.assertLess(elapsed,.2)
            self.cloud.release.set();r=self.finish()
            transport.assert_not_called()
        self.assertEqual(r['blockers'],['stopped'])
    def test_browser_lease_loss_no_automatic_resume(self):
        self.cloud.release=threading.Event()
        self.bridge.begin('Lift the red cube','qwen/qwen3-32b');self.assertTrue(self.cloud.entered.wait(3.))
        self.bridge.deadline=time.monotonic()-1
        with self.assertRaisesRegex(Rejected,'lease_expired'):self.bridge.heartbeat(self.bridge.job_id)
        self.cloud.release.set();r=self.finish()
        self.assertEqual(r['blockers'],['browser_connection_lost'])
        with self.assertRaises(Rejected):self.bridge.heartbeat(self.bridge.job_id)
    def test_missing_checkpoint_never_calls_cloud(self):
        (self.folder/'policy.npz').unlink()
        self.bridge.begin('Lift the red cube','qwen/qwen3-32b');r=self.finish()
        self.assertEqual(r['blockers'],['saved_checkpoint_missing']);self.assertEqual(self.cloud.calls,0)
    def test_checkpoint_changed_during_cloud_wait_is_blocked(self):
        self.cloud.release=threading.Event();report_fixture(self.folder,self.agent,self.config)
        with patch('core.proposal_bridge.infer_saved_decision',side_effect=self.inference_fixture):
            self.bridge.begin('Lift the red cube','qwen/qwen3-32b');self.assertTrue(self.cloud.entered.wait(3.))
            (self.folder/'policy.npz').write_bytes(b'changed')
            self.cloud.release.set();r=self.finish()
        self.assertEqual(r['blockers'],['saved_checkpoint_changed_during_proposal'])
    def test_unproven_task_returns_proposal_but_no_receipt(self):
        with patch('core.proposal_bridge.infer_saved_decision',side_effect=self.inference_fixture):
            self.bridge.begin('Lift the red cube','qwen/qwen3-32b');r=self.finish()
        self.assertEqual(r['state'],'rejected');self.assertIn('proposal',r)
        self.assertEqual(r['blockers'],['skill_not_demonstrated']);self.assertNotIn('receipt',r)
        self.assertEqual(r['evaluation']['blockers'],['frozen_evaluation_missing'])
    @unittest.skipUnless(HAS_MUJOCO,'MuJoCo not installed in local test environment')
    def test_actual_camera_policy_to_http_receiver_no_device_io(self):
        from core.camera_world import validate_config
        self.config=validate_config({});self.runner.camera_config=self.config
        self.agent.save(self.folder/'policy.npz',{'camera_config':self.config})
        report_fixture(self.folder,self.agent,self.config)
        before=(self.folder/'policy.npz').read_bytes()
        import builtins
        original_import=builtins.__import__; original_open=builtins.open
        attempted=[]
        def no_device_import(name,*args,**kwargs):
            if name.split('.')[0] in ('serial','RPi','gpiozero','pigpio','smbus','smbus2','seizo_core'):
                attempted.append(name);raise AssertionError('Physical import forbidden')
            return original_import(name,*args,**kwargs)
        def no_device_open(file,*args,**kwargs):
            text=str(file)
            if text.startswith(('/dev/tty','/dev/i2c','/dev/gpio','/sys/class/gpio')):
                attempted.append(text);raise AssertionError('Physical file forbidden')
            return original_open(file,*args,**kwargs)
        with patch('builtins.__import__',side_effect=no_device_import),patch('builtins.open',side_effect=no_device_open):
            self.bridge.begin('Lift the red cube','qwen/qwen3-32b')
            # Keep this explicit test-client lease alive during initial render.
            deadline=time.monotonic()+35
            while self.bridge.active() and time.monotonic()<deadline:
                self.bridge.heartbeat(self.bridge.job_id);time.sleep(.1)
            r=self.finish()
        self.assertEqual(r['state'],'received_by_mock_pi',r.get('blockers'))
        self.assertEqual(attempted,[]);self.assertEqual(r['simulator_steps_executed'],0)
        self.assertEqual(before,(self.folder/'policy.npz').read_bytes())
        self.assertEqual(r['proposal']['observation']['source'],'rendered_simulation')
        self.assertTrue(r['proposal']['observation']['helpers_masked'])
        self.assertFalse(r['executed']);self.assertFalse(r['physically_verified'])
        # Save bounded evidence, not keys, images, local paths, or private data.
        out={'scope':'CI integration with SYNTHETIC passing-score fixture; NOT skill evidence',
             'state':r['state'],'checkpoint_sha256':r['checkpoint']['sha256'],
             'policy_fingerprint':r['checkpoint']['fingerprint'],
             'real_rendered_rgb_input':True,'action':r['proposal']['actions'][0],
             'physical_io_attempts':attempted,'simulator_steps_executed':0,
             'cloud_requests':0,'mocked_intent':True,'real_pi_connected':False,
             'authorized':False,'executed':False,'physically_verified':False}
        (ROOT/'proposal-integration-evidence.json').write_text(json.dumps(out,indent=2))


class EvidenceRejections(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.agent=Agent()
    def test_rejects_bad_scores_baselines_camera_and_faults(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);base=report_fixture(folder,self.agent,{})
            identity={'model_id':POLICY_ID,'fingerprint':self.agent.signature()};contract=runtime_contract({})
            variants=[]
            for key,value in [('trials',1),('successes',2),('faults',1),('invalid_physics',1),
                               ('sensor_condition','four_cameras'),('weights_updated',True)]:
                r=copy.deepcopy(base);r['by_task'][0]['current'][key]=value;variants.append(r)
            r=copy.deepcopy(base);r['by_task'][0]['random_actions']['successes']=19;variants.append(r)
            for r in variants:
                (folder/'evaluation.json').write_text(json.dumps(r))
                self.assertFalse(evaluation_evidence(folder,identity,'lift',contract)['demonstrated'])


class CloudBoundary(unittest.TestCase):
    def test_interpreter_does_not_accept_actions_or_authority(self):
        planner=HackClubPlanner()
        for content in ('Hello!',json.dumps({'schema':INTENT_SCHEMA,'status':'supported','task':'lift','target':'red_cube','approved':True})):
            with patch.object(planner,'_request',return_value=(content,{})),self.assertRaises(Rejected):
                planner.interpret_task('Lift the red cube')
    def test_interpreter_uses_existing_request_and_never_camera_images(self):
        planner=HackClubPlanner();intent=fixture()[0]['intent']
        with patch.object(planner,'_request',return_value=(json.dumps(intent),{'fixture':True})) as call:
            parsed,_=planner.interpret_task('Lift the red cube')
            self.assertEqual(parsed,intent)
            self.assertEqual(call.call_args.args[2],'proposal_intent')
            self.assertEqual(call.call_count,1)
            self.assertTrue(all(type(m['content']) is str for m in call.call_args.args[1]))
    def test_receiver_source_has_no_hardware_import_or_execution_hook(self):
        for name in ('proposal_protocol.py','proposal_receiver.py','proposal_policy.py','proposal_bridge.py'):
            source=(ROOT/'core'/name).read_text();tree=ast.parse(source)
            imports=[]
            for node in ast.walk(tree):
                if isinstance(node,ast.Import):imports.extend(x.name for x in node.names)
                if isinstance(node,ast.ImportFrom):imports.append(node.module or '')
            self.assertFalse(any(x.split('.')[0] in ('serial','RPi','gpiozero','pigpio','smbus','seizo_core') for x in imports))
            for hook in ('move_stepper(', 'move_servo(', 'guarded_executor', '/auto/run'):
                self.assertNotIn(hook,source)


class HTTPIntegration(unittest.TestCase):
    def setUp(self):
        from app import Server,make_handler
        from core.runner import Runner
        self.tmp=tempfile.TemporaryDirectory();self.runner=Runner(Path(self.tmp.name))
        self.server=Server(('127.0.0.1',0),make_handler(self.runner,'test-token',threading.Event(),HackClubPlanner()))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(2);self.tmp.cleanup()
    def post(self,path,data,auth=True):
        raw=data if type(data) is bytes else json.dumps(data).encode()
        req=urllib.request.Request(self.url+path,data=raw,headers={
            'Origin':self.url,'Content-Type':'application/json','X-Lab-Token':'test-token' if auth else 'bad'})
        try:
            with urllib.request.urlopen(req,timeout=4) as r:return r.status,json.load(r)
        except urllib.error.HTTPError as r:return r.code,json.load(r)
    def test_no_auto_run_route(self):
        self.assertEqual(self.post('/auto/run',{})[0],404)
    def test_proposal_requires_same_origin_auth_and_sequence(self):
        self.assertEqual(self.post('/api/proposal/prepare',{'instruction':'lift'},False)[0],403)
        self.assertEqual(self.post('/api/proposal/prepare',{'instruction':'lift'})[0],400)
    def test_stop_sequence_supersedes_earlier_prepare(self):
        self.assertEqual(self.post('/api/proposal/stop',{'control_seq':10})[0],200)
        self.assertEqual(self.post('/api/proposal/prepare',{'instruction':'Lift the red cube','control_seq':9})[0],400)
    def test_duplicate_json_key_rejected(self):
        self.assertEqual(self.post('/api/proposal/prepare',b'{"control_seq":1,"control_seq":2,"instruction":"lift"}')[0],400)

if __name__=='__main__':unittest.main()
