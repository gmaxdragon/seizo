"""Protocol fixtures are synthetic, not learned-policy performance evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch
import numpy as np
from core.proposal_protocol import *
from core.proposal_receiver import MockPiTransport
from core.proposal_policy import load_saved_policy, evaluation_evidence, runtime_contract
from core.view_policy import Agent


def fixture(session=None, now=None):
    now = time.time() if now is None else now
    cp={'model_id':POLICY_ID,'sha256':'a'*64,'fingerprint':'b'*64,'optimizer_updates':1,'episodes':1}
    cal={'simulation_id':'estimated-simulation:'+'c'*64,'contract_sha256':'c'*64,'physical_id':None}
    ev={'task':'lift','report_sha256':'d'*64,'contract_sha256':'c'*64,'demonstrated':True,
        'blockers':[],'trials':20,'successes':16,'random_successes':1}
    p={'schema':SCHEMA,'proposal_id':str(uuid.uuid4()),'session_id':session or str(uuid.uuid4()),
       'created_at':now,'expires_at':now+10.,'domain':'simulation',
       'intent':{'schema':INTENT_SCHEMA,'status':'supported','task':'lift','target':'red_cube'},
       'checkpoint':cp,'calibration':cal,'evaluation':ev,'automatic_motion_enabled':False,
       'observation':{'id':str(uuid.uuid4()),'source':'rendered_simulation','captured_at':[now-.05]*2,
          'previous_captured_at':[now-.10]*2,'valid':[True,True],'camera_names':['overhead','wrist'],
          'helpers_masked':True,'input_sha256':'e'*64},
       'actions':[action_from_policy([.1,-.2,.3,-.4,.5])]}
    expected={'checkpoint':copy.deepcopy(cp),'calibration':copy.deepcopy(cal),'evaluation':copy.deepcopy(ev)}
    return p,expected


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.now=1000.;self.p,self.expected=fixture(now=self.now)
    def validate(self,p=None):
        return validate_proposal(p or self.p, now=self.now, session_id=self.p['session_id'], expected=self.expected)
    def test_valid_proposal_is_not_authorization(self):
        self.assertFalse(self.validate()['automatic_motion_enabled'])
    def test_json_rejects_prose_partial_fences_and_duplicates(self):
        for raw in ('hello','{"x":','```json\n{}\n```','{"a":1,"a":2}','{"x":NaN}','{"x":Infinity}'):
            with self.subTest(raw=raw),self.assertRaises(Rejected):strict_json(raw)
    def test_json_size_bound(self):
        with self.assertRaises(Rejected):strict_json(' '*16001)
    def test_normal_chat_is_not_intent(self):
        for raw in ('Hello!', '{}', '{"schema":"seizo-task-intent/v1","status":"unsupported"}'):
            with self.subTest(raw=raw),self.assertRaises(Rejected):parse_intent(raw)
    def test_intent_rejects_ai_approval_code_and_unknown_task(self):
        for key,value in [('approved',True),('gcode','G0 X20'),('shell','echo move')]:
            x={**self.p['intent'],key:value}
            with self.subTest(key=key),self.assertRaises(Rejected):parse_intent(canonical(x))
        x={**self.p['intent'],'task':'dance'}
        with self.assertRaises(Rejected):parse_intent(canonical(x))
    def test_unknown_top_field_rejected(self):
        self.p['approved']=True
        with self.assertRaises(Rejected):self.validate()
    def test_physical_domain_and_enable_rejected(self):
        for key,value in [('domain','physical'),('automatic_motion_enabled',True),('automatic_motion_enabled',0)]:
            p=copy.deepcopy(self.p);p[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(Rejected):self.validate(p)
    def test_stale_and_future_frames(self):
        for stamp in (990.,1001.,float('nan'),float('inf'),True,'999'):
            p=copy.deepcopy(self.p);p['observation']['captured_at'][0]=stamp
            with self.subTest(stamp=stamp),self.assertRaises(Rejected):self.validate(p)
    def test_stale_history_rejected(self):
        self.p['observation']['previous_captured_at'][1]=990.
        with self.assertRaises(Rejected):self.validate()
    def test_camera_loss_or_helpers_rejected(self):
        for key,value in [('valid',[True,False]),('valid',[1,1]),('helpers_masked',False),('source','real_pi')]:
            p=copy.deepcopy(self.p);p['observation'][key]=value
            with self.subTest(key=key),self.assertRaises(Rejected):self.validate(p)
    def test_expiry(self):
        for key,value in [('expires_at',999.),('expires_at',1100.),('created_at',1001.)]:
            p=copy.deepcopy(self.p);p[key]=value
            with self.subTest(key=key),self.assertRaises(Rejected):self.validate(p)
    def test_wrong_session_restart(self):
        with self.assertRaises(Rejected):
            validate_proposal(self.p,now=self.now,session_id=str(uuid.uuid4()),expected=self.expected)
    def test_policy_identity_mismatch(self):
        self.p['checkpoint']['fingerprint']='f'*64
        with self.assertRaises(Rejected):self.validate()
    def test_calibration_missing_or_unknown(self):
        for value in (None,{},'guessed', {**self.p['calibration'],'physical_id':'made-up'}):
            p=copy.deepcopy(self.p);p['calibration']=value
            with self.subTest(value=value),self.assertRaises(Rejected):self.validate(p)
    def test_policy_bad_numbers(self):
        for value in (True,'1',1.1,float('nan'),float('inf'),None):
            with self.subTest(value=value),self.assertRaises(Rejected):action_from_policy([value,0,0,0,0])
    def test_mapping_units_and_changed_deltas_rejected(self):
        for key,value in [('delta_units',['mm']*5),('mapping_id','guess'),('requested_delta',[9]*5),
                          ('axis_order',list(reversed(AXES))),('type','servo_set')]:
            p=copy.deepcopy(self.p);p['actions'][0][key]=value
            with self.subTest(key=key),self.assertRaises(Rejected):self.validate(p)
    def test_requested_delta_bool_rejected(self):
        self.p['actions'][0]=action_from_policy([0]*5);self.p['actions'][0]['requested_delta'][0]=False
        with self.assertRaises(Rejected):self.validate()
    def test_multiple_or_empty_actions_rejected(self):
        for value in ([],self.p['actions']*2):
            p=copy.deepcopy(self.p);p['actions']=value
            with self.subTest(value=value),self.assertRaises(Rejected):self.validate(p)
    def test_unevaluated_policy_not_receipted(self):
        self.p['evaluation']['demonstrated']=False;self.expected['evaluation']=self.p['evaluation']
        with self.assertRaisesRegex(Rejected,'skill_not_demonstrated'):self.validate()
    def test_no_automatic_authorization_field(self):
        for key in ('authorized','executed','physically_verified'):
            p=copy.deepcopy(self.p);p[key]=True
            with self.subTest(key=key),self.assertRaises(Rejected):self.validate(p)


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.p,self.expected=fixture()
        self.store=ReceiptStore(self.expected);self.p['session_id']=self.store.session_id
    def send(self):
        raw=canonical(self.p);return self.store.receive(raw,sign(self.store.key,raw))
    def test_authenticated_receipt_without_execution(self):
        r=self.send();self.assertEqual(r['state'],'received_by_mock_pi')
        for k in ('authorized','executed','physically_verified','automatic_motion_enabled'):self.assertIs(r[k],False)
    def test_unsigned_request_rejected(self):
        with self.assertRaisesRegex(Rejected,'authentication_failed'):self.store.receive(canonical(self.p),'bad')
    def test_replay_rejected(self):
        self.send()
        with self.assertRaisesRegex(Rejected,'replayed_proposal'):self.send()
    def test_restart_old_signature_and_session_rejected(self):
        raw=canonical(self.p);new=ReceiptStore(self.expected)
        with self.assertRaisesRegex(Rejected,'authentication_failed'):new.receive(raw,sign(self.store.key,raw))
        with self.assertRaisesRegex(Rejected,'session_replaced'):new.receive(raw,sign(new.key,raw))
    def test_stop_latches(self):
        self.store.stop()
        with self.assertRaisesRegex(Rejected,'stopped'):self.send()
    def test_rejected_request_cannot_be_replayed(self):
        self.p['actions'][0]['requested_delta'][0]=2.
        with self.assertRaises(Rejected):self.send()
        with self.assertRaisesRegex(Rejected,'replayed'):self.send()
    def test_real_loopback_http_roundtrip(self):
        with MockTransportContext(self.expected) as transport:
            self.p['session_id']=transport.session_id
            r=transport.send(self.p);self.assertTrue(r['received']);self.assertFalse(r['executed'])
            with self.assertRaisesRegex(Rejected,'replayed'):transport.send(self.p)
    def test_connection_failure_does_not_retry(self):
        with MockTransportContext(self.expected) as transport:
            self.p['session_id']=transport.session_id
            with patch('core.proposal_receiver.http.client.HTTPConnection.request',side_effect=ConnectionError) as request:
                with self.assertRaisesRegex(Rejected,'connection_lost_no_retry'):transport.send(self.p)
                self.assertEqual(request.call_count,1)
                with self.assertRaisesRegex(Rejected,'stopped'):transport.send(self.p)
                self.assertEqual(request.call_count,1)


class MockTransportContext:
    def __init__(self,expected):self.expected=expected
    def __enter__(self):self.transport=MockPiTransport(self.expected);return self.transport
    def __exit__(self,*_):self.transport.close()


class SavedPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agent=Agent(seed=101)
        # Real numerical PPO update, synthetic observations. This proves adapter
        # identity/preservation only, never image skill or physical learning.
        x=np.zeros((2,cls.agent.obs_size),np.float32)
        a,z,lp,val=cls.agent.act(x)
        cls.agent.update((x,z,lp,np.array([-1,1],np.float32),np.array([0,1],np.float32)),epochs=1)
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_missing_checkpoint_never_creates_one(self):
        with self.assertRaisesRegex(Rejected,'missing'):load_saved_policy(self.folder,{})
        self.assertFalse((self.folder/'policy.npz').exists())
    def test_corrupt_checkpoint_not_replaced(self):
        p=self.folder/'policy.npz';p.write_bytes(b'not npz')
        with self.assertRaisesRegex(Rejected,'incompatible_or_corrupt'):load_saved_policy(self.folder,{})
        self.assertEqual(p.read_bytes(),b'not npz')
    def test_untrained_checkpoint_blocked(self):
        Agent().save(self.folder/'policy.npz')
        with self.assertRaisesRegex(Rejected,'no_training'):load_saved_policy(self.folder,{})
    def test_matching_saved_policy_exact_and_unchanged(self):
        p=self.folder/'policy.npz';self.agent.save(p,{'camera_config':{}})
        before=p.read_bytes();loaded,identity=load_saved_policy(self.folder,{})
        self.assertEqual(identity['fingerprint'],self.agent.signature())
        np.testing.assert_array_equal(loaded.act(np.zeros((1,loaded.obs_size)),deterministic=True)[0],
                                      self.agent.act(np.zeros((1,loaded.obs_size)),deterministic=True)[0])
        self.assertEqual(p.read_bytes(),before)
        self.assertEqual(loaded.rng.bit_generator.state,self.agent.rng.bit_generator.state)
        for name in loaded.p:
            np.testing.assert_array_equal(loaded.m[name],self.agent.m[name])
            np.testing.assert_array_equal(loaded.v[name],self.agent.v[name])
    def test_wrong_model_rejected_without_backup_or_overwrite(self):
        a=self.agent.clone();a.model_id='old-v8';p=self.folder/'policy.npz';a.save(p)
        before=p.read_bytes()
        with self.assertRaisesRegex(Rejected,'incompatible'):load_saved_policy(self.folder,{})
        self.assertEqual(p.read_bytes(),before);self.assertEqual(len(list(self.folder.iterdir())),1)
    def test_config_mismatch_rejected(self):
        self.agent.save(self.folder/'policy.npz',{'camera_config':{'profile':'fixed'}})
        with self.assertRaisesRegex(Rejected,'configuration_mismatch'):load_saved_policy(self.folder,{})
    def test_missing_evaluation_has_no_claimed_skill(self):
        _,expected=fixture();r=evaluation_evidence(self.folder,expected['checkpoint'],'lift','c'*64)
        self.assertFalse(r['demonstrated']);self.assertEqual(r['blockers'],['frozen_evaluation_missing'])
    def test_old_evaluation_not_silently_reused(self):
        _,e=fixture();(self.folder/'evaluation.json').write_text(json.dumps(
            {'model_id':POLICY_ID,'policy_fingerprint':e['checkpoint']['fingerprint']}))
        r=evaluation_evidence(self.folder,e['checkpoint'],'lift','c'*64)
        self.assertEqual(r['blockers'],['evaluation_contract_missing_or_stale'])
    def test_real_contract_changes_with_camera_settings(self):
        self.assertNotEqual(runtime_contract({'profile':'fixed'}),runtime_contract({'profile':'nearby'}))

if __name__=='__main__':unittest.main()
