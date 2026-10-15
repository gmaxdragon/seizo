"""Roll, contact provenance, task semantics, learning and API audit regressions."""
import json,math,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import mujoco
from core.mujoco_world import MuJoCoWorld,rx,rz,rotation_error
from core.gripper_check import check_world,run_check
from core.mjcf import MODEL_VERSION,ACTUATOR_NAMES
from core.world import TASKS,OBS_SIZE
from core.runner import Runner,evaluate
from core.cloud import HackClubPlanner

class Physics(unittest.TestCase):
 def test_real_joint_axis_is_longitudinal_not_vertical(self):
  w=MuJoCoWorld(1);np.testing.assert_array_equal(w.model.joint('wrist_roll').axis,[1,0,0]);self.assertFalse(w.model.joint('wrist_roll').limited)
  self.assertEqual(w.model.nu,5);self.assertEqual(len(ACTUATOR_NAMES),5)
 def test_full_roll_does_not_steer_tool(self):
  w,q=check_world();d=w.data[0];m=w.model;pos=[];directions=[]
  for deg in [0,90,180,270,360,-90]:
   q[3]=deg;w._set_pose(d,q);mujoco.mj_forward(m,d);pos.append(d.site_xpos[w.sid].copy());directions.append(d.xmat[m.body('wrist_and_palm').id].reshape(3,3)[:,0])
  self.assertLess(np.max(np.ptp(pos,axis=0)),1e-10);self.assertLess(np.max(np.ptp(directions,axis=0)),1e-10)
 def test_roll_check_reaches360_keeps_opening(self):
  r=run_check('wrist');self.assertGreater(max(f['roll_degrees'] for f in r['frames']),359.9)
  self.assertTrue(all(f['pose']['gripper']>.995 for f in r['frames']))
  self.assertTrue(all(not f['gripper_object_contact'] for f in r['frames']))
  self.assertFalse(r['weights_updated'])
 def test_floor_contact_is_not_gripper_contact(self):
  w,q=check_world();
  for _ in range(15):w.step(np.zeros((1,5)))
  s=w.contact_state(0);self.assertGreater(s['floor_object_count'],0);self.assertFalse(s['jaw_object']);self.assertFalse(s['arm_object'])
  self.assertFalse(w.frame()['gripper_contact_continues'])
 def test_empty_close_reports_no_object(self):
  r=run_check('open_close');self.assertFalse(r['contact_seen']);self.assertTrue(all(not f['gripper_object_contact'] for f in r['frames']))
  self.assertGreater(min(f['gripper_gap_mm'] for f in r['frames']),5.9)
 def test_fixture_really_resists_squeeze(self):
  r=run_check('contact');self.assertTrue(r['contact_seen']);self.assertGreater(r['continued_closing_steps_after_contact'],10)
  contacts=[f for f in r['frames'] if f['gripper_contact_continues']]
  self.assertTrue(contacts);self.assertGreater(contacts[-1]['contacts']['jaw_force_n'],0)
  self.assertLessEqual(r['peak_virtual_gripper_torque_nm'],.06001)
 def test_roll360_observation_is_periodic(self):
  w=MuJoCoWorld(1);d=w.data[0];q=w.q[0].copy();q[3]=0
  w._set_pose(d,q);mujoco.mj_forward(w.model,d);w._copy_from_physics((0,));a=w.observation().copy()
  q[3]=360;w._set_pose(d,q);mujoco.mj_forward(w.model,d);w._copy_from_physics((0,));b=w.observation()
  np.testing.assert_allclose(a,b,atol=1e-5)
 def test_increment_crosses360_without_wrap_teleport(self):
  w,q=check_world();d=w.data[0];q[3]=359;w.q[0]=q;w.targetq[0]=q;w._set_pose(d,q);mujoco.mj_forward(w.model,d)
  w.step(np.array([[0,0,0,1,0]]));self.assertEqual(w.targetq[0,3],366.)
 def test_every_task_has_finite_orientation_observations(self):
  for t in TASKS:
   w=MuJoCoWorld(2,seed=23,task=t);self.assertEqual(w.observation().shape,(2,OBS_SIZE));self.assertTrue(np.isfinite(w.observation()).all())
   for _ in range(8):w.step(np.zeros((2,5)))
   f=w.frame();self.assertEqual(len(f['target_orientation_wxyz']),4)
 def test_rotation_reward_checks_object_not_empty_wrist(self):
  w=MuJoCoWorld(1,task='rotate');j=w.target_obj[0]
  w.objects[0,j,2]+=100;w.pinched[0,j]=True;w.ever_gripped[0]=True
  w.goal_rotation[0]=w.object_rotations[0,j]@rx(math.pi/2);w.q[0,3]=90
  phi,success,metrics=w.metrics();self.assertFalse(success[0]);self.assertGreater(metrics['object_angle_error'][0],89.)
  w.object_rotations[0,j]=w.goal_rotation[0];self.assertTrue(w.metrics()[1][0])
 def test_oriented_place_requires_prior_grasp(self):
  w=MuJoCoWorld(1,task='orient_place');j=w.target_obj[0];w.ever_lifted[0]=True;w.pinched[0,j]=False
  w.object_rotations[0,j]=w.goal_rotation[0];w.objects[0,j,:2]=w.goal[0,:2];w.objects[0,j,2]=65+w.support_height(0,j)
  w.ov[0,j]=0;w.object_angular_vel[0,j]=0
  self.assertFalse(w.metrics()[1][0]);w.ever_gripped[0]=True;self.assertTrue(w.metrics()[1][0])
 def test_free_cylinder_shape_is_longer_than_diameter(self):
  w=MuJoCoWorld(1);size=w.model.geom('object_green').size;self.assertGreater(size[1],size[0]);self.assertEqual(w.frame()['objects'][1]['half_height'],30.)
 def test_roll_goals_are_object_frames_not_motor_commands(self):
  a=np.array([np.eye(3)]);b=np.array([rx(np.pi/2)]);self.assertAlmostEqual(rotation_error(a,b)[0],90)

 def test_prepositioned_free_block_can_be_rolled_then_released(self):
  r=run_check('held_roll');f=[x for x in r['frames'] if x['diagnostic_phase']=='Roll held block 90 degrees'][-1]
  self.assertFalse(r['weights_updated']);self.assertFalse(r['success']);self.assertFalse(r['physical_motion'])
  self.assertTrue(f['objects'][0]['pinched']);self.assertGreater(f['objects'][0]['position'][2],150.)
  rotation=np.zeros(9);mujoco.mju_quat2Mat(rotation,np.asarray(f['objects'][0]['quaternion_wxyz']))
  self.assertLess(rotation_error(rotation.reshape(1,3,3),rx(np.pi/2)[None])[0],12.)
  self.assertFalse(r['frames'][-1]['objects'][0]['pinched'])
  self.assertLess(r['frames'][-1]['objects'][0]['position'][2],80.)
  self.assertTrue(f['object_prepositioned_for_mechanism_check'])

class Learning(unittest.TestCase):
 def test_training_changes_weights_and_evaluation_does_not(self):
  with tempfile.TemporaryDirectory() as td:
   r=Runner(td);before=r.agent.signature();r.start({'episodes':2,'task':'orient','compute':'fast'});r.thread.join(35)
   if r.thread.is_alive():r.stop();r.thread.join(10);self.fail('Training did not finish')
   self.assertEqual(r.status,'complete',r.error);self.assertNotEqual(before,r.agent.signature());self.assertGreater(r.agent.updates,0)
   signature=r.agent.signature();report=evaluate(r.agent,'orient',n=2,seed=918);self.assertEqual(signature,r.agent.signature());self.assertFalse(report['weights_updated'])
   self.assertTrue(r.last_run['weights_updated']);self.assertEqual(r.last_run['cloud_requests'],0)
 def test_stopping_evaluation_is_effective(self):
  with tempfile.TemporaryDirectory() as td:
   r=Runner(td);r.begin_evaluation('all',5);r.stop();r.thread.join(10)
   self.assertFalse(r.thread.is_alive());self.assertNotEqual(r.status,'evaluating');self.assertIsNone(r.last_evaluation)
 def test_missing_current_evaluation_not_treated_as_memory(self):
  with tempfile.TemporaryDirectory() as td:
   r=Runner(td);self.assertFalse(r.experience_summary()['evaluation_available'])
 def test_new_policy_rejects_v5_identity(self):
  with tempfile.TemporaryDirectory() as td:
   r=Runner(td);r.save();f=Path(td)/'policy.npz'
   with np.load(f,allow_pickle=False) as z:items={k:z[k] for k in z.files}
   meta=json.loads(str(items['meta']));meta['model_id']='seizo-two-servo-parallel-contact-v5';items['meta']=np.array(json.dumps(meta))
   with f.open('wb') as h:np.savez_compressed(h,**items)
   old=f.read_bytes();new=Runner(td);arch=list(Path(td).glob('legacy_physics_checkpoint_*/policy.npz'))
   self.assertEqual(len(arch),1);self.assertEqual(arch[0].read_bytes(),old);self.assertEqual(new.agent.updates,0)

class Store:
 supported=False;warning=''
 def delete(self):pass

class FakeHTTP:
 calls=[];payload='OK';code=200
 def __init__(self,*a,**kw):pass
 def request(self,method,path,body,headers):type(self).calls.append(json.loads(body))
 def getresponse(self):return self
 @property
 def status(self):return self.code
 def read(self,n):return json.dumps({'choices':[{'message':{'content':self.payload}}],'usage':{'total_tokens':21}}).encode()
 def close(self):pass

class Cloud(unittest.TestCase):
 def setUp(self):FakeHTTP.calls=[];FakeHTTP.code=200;FakeHTTP.payload='OK'
 def memory(self):return {'schema':'seizo-experience/v1','model_id':MODEL_VERSION,'policy_fingerprint':'test-policy',
  'evaluation_available':True,'training_episodes':42,'optimizer_updates':9,'tasks':[{'task':'reach','successes':3,'trials':20}],
  'physical_validation':False,'cloud_model_finetuned':False}
 def test_key_test_records_real_request_purpose_not_learning(self):
  with tempfile.TemporaryDirectory() as td,patch('core.cloud.http.client.HTTPSConnection',FakeHTTP):
   p=HackClubPlanner('sk-'+('x'*32),store=Store(),audit_path=Path(td)/'audit.json');r=p.test_connection();a=p.status()['api_usage']
   self.assertEqual(a['attempts'],1);self.assertEqual(a['by_purpose'],{'key_test':1});self.assertFalse(r['weights_updated']);self.assertFalse(r['model_weights_updated'])
   self.assertNotIn('sk-'+('x'*32),(Path(td)/'audit.json').read_text())
 def test_review_shares_empirical_context_without_action(self):
  with patch('core.cloud.http.client.HTTPSConnection',FakeHTTP):
   FakeHTTP.payload=json.dumps({'summary':'3 of 20 succeeded.','next_task':'reach','reason':'Practice the prerequisite.'})
   p=HackClubPlanner('sk-'+('x'*32),store=Store());r=p.review_results(self.memory());sent=FakeHTTP.calls[0]
   self.assertIn('training_episodes',sent['messages'][1]['content']);self.assertTrue(r['experience_shared']);self.assertFalse(r['model_weights_updated']);self.assertEqual(p.status()['api_usage']['last']['purpose'],'experience_review')
 def test_missing_memory_never_makes_network_request(self):
  with patch('core.cloud.http.client.HTTPSConnection',FakeHTTP):
   p=HackClubPlanner('sk-'+('x'*32),store=Store())
   with self.assertRaises(ValueError):p.review_results({'evaluation_available':False})
   self.assertEqual(FakeHTTP.calls,[])
 def test_unknown_command_advice_rejected(self):
  with patch('core.cloud.http.client.HTTPSConnection',FakeHTTP):
   FakeHTTP.payload=json.dumps({'summary':'','next_task':'move_real_motor','reason':''});p=HackClubPlanner('sk-'+('x'*32),store=Store())
   with self.assertRaises(ValueError):p.review_results(self.memory())
 def test_provider_errors_are_counted(self):
  with patch('core.cloud.http.client.HTTPSConnection',FakeHTTP):
   FakeHTTP.code=429;p=HackClubPlanner('sk-'+('x'*32),store=Store())
   with self.assertRaises(ValueError):p.test_connection()
   self.assertEqual(p.status()['api_usage']['failed_requests'],1)

if __name__=='__main__':unittest.main()
